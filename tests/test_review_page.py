"""Tests for shared/review_page: build every example, check it, and pin the export text.

The export tests run the page's own engine under plain node (no DOM), so they need
node but not a browser. The click-through test needs Playwright: set
PROOFS_PLAYWRIGHT to an installed playwright package folder, or it is skipped.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RP = ROOT / "shared" / "review_page"
BUILD = RP / "review_page.py"
EXAMPLES = RP / "examples"
NODE = shutil.which("node")
sys.path.insert(0, str(RP))
import review_page  # noqa: E402

DRIVER = r"""
const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8");
const spec = JSON.parse(html.match(/<script type="application\/json" id="rp-spec">([\s\S]*?)<\/script>/)[1]);
const code = html.match(/<script>\n([\s\S]*?)\n<\/script>/)[1];
const m = { exports: {} };
new Function("module", code)(m);
// Tests write a flat state; each section's exporter reads only its own ids.
const flat = JSON.parse(process.argv[3]);
const state = { sec: {}, extra: flat.extra };
spec.sections.forEach((s) => { state.sec[s.id] = flat; });
process.stdout.write(m.exports.exportText(spec, state, new Date(Date.UTC(2026, 2, 14, 18, 53))));
"""


def build(name, tmp):
    out = Path(tmp) / (name + ".html")
    r = subprocess.run([sys.executable, str(BUILD), str(EXAMPLES / (name + ".json")), "--out", str(out)],
                       capture_output=True, text=True)
    if r.returncode:
        raise AssertionError(r.stdout + r.stderr)
    return out


class StackVariants(unittest.TestCase):
    def test_stack_variants_puts_one_variant_per_row(self):
        spec = {"title": "T", "project": {"name": "P", "session": "s"}, "decisions": "design-review",
                "items": [{"label": "Wide", "stack_variants": True, "variants": [{"html": "<p>a</p>"}, {"html": "<p>b</p>"}]},
                          {"label": "Narrow", "variants": [{"html": "<p>a</p>"}, {"html": "<p>b</p>"}]}]}
        with tempfile.TemporaryDirectory() as tmp:
            src, out = Path(tmp) / "s.json", Path(tmp) / "p.html"
            src.write_text(json.dumps(spec))
            r = subprocess.run([sys.executable, str(BUILD), str(src), "--out", str(out), "--no-check"],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            html = out.read_text()
            self.assertEqual(html.count('class="rp-gallery rp-stack"'), 1)
            self.assertEqual(html.count('class="rp-gallery"'), 1)
            self.assertIn(".rp-gallery.rp-stack", html)


@unittest.skipUnless(NODE, "node is not installed")
class Stylesheet(unittest.TestCase):
    CSS = (RP / "style.css").read_text()

    def test_links_in_item_text_have_a_color_for_every_theme(self):
        # A bare <a> in item text, a note or a question once fell back to the browser's
        # blue, unreadable on the dark theme. Every theme block must set --rp-link.
        self.assertIn(":where(body.rp) a { color:var(--rp-link); }", self.CSS)
        blocks = [":root {", ':root:not([data-theme="light"]) {', ':root[data-theme="dark"] {',
                  "body.rp-mode-questions, :root[data-theme] body.rp-mode-questions {"]
        for head in blocks:
            body = self.CSS[self.CSS.index(head):]
            body = body[:body.index("}")]
            self.assertIn("--rp-link:", body, head)


class PhoneFrame(unittest.TestCase):
    """Vue run 1: at 390 the brand line cut the session name to "hom…" and the sticky bar
    took 138px. Measured in Chromium at 390 before and after; these pin the rules."""
    CSS = (RP / "style.css").read_text()
    JS = (RP / "engine.js").read_text()

    def phone(self):
        start = self.CSS.index("@media (max-width: 600px) {")
        return self.CSS[start:]

    def test_the_brand_line_wraps_on_a_phone_instead_of_cutting_the_session(self):
        self.assertIn(".rp-brandline { height:auto;", self.phone())
        self.assertIn("white-space:normal", self.phone())

    def test_the_brand_line_hides_its_separators_on_a_phone(self):
        # Rails run 1: a " · " left at the end of a wrapped header line. On a phone the parts
        # wrap onto their own lines with a gap, and no dot is drawn.
        self.assertIn(".rp-brandline .rp-sep { display:none; }", self.phone())
        self.assertIn(".rp-where { display:flex; flex-wrap:wrap;", self.phone())

    def test_the_bar_drops_the_per_decision_counts_on_a_phone(self):
        self.assertIn(".rp-bar .rp-tally-st { display:none; }", self.phone())

    def test_each_count_carries_its_own_separator(self):
        # Hiding the counts must not leave " · · ·" behind.
        self.assertIn("'\"> · ' + b.label", self.JS)
        self.assertNotRegex(self.JS, r'#rp-tally"\)\.innerHTML = parts\.join\(" · "\);\n\s+var prog')


class ExportText(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.driver = Path(self._tmp.name) / "driver.cjs"
        self.driver.write_text(DRIVER)

    def export(self, name, state):
        page = build(name, self._tmp.name)
        r = subprocess.run([NODE, str(self.driver), str(page), json.dumps(state)],
                           capture_output=True, text=True, env=dict(os.environ, TZ="UTC"))
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_design_review(self):
        text = self.export("design-review", {"items": {
            "1": {"s": "accept", "v": "B"},
            "2": {"s": "accept", "r": True}}})
        self.assertEqual(text, "[Articles Index — Design Review]\n"
                               "1. Article card layout — ACCEPT (Use Selected: Variant B)\n"
                               "2. Read More button placement — ACCEPT (Use Proposed) — READ")

    def test_design_review_comments_and_pending(self):
        text = self.export("design-review", {"items": {
            "1": {"s": "revise", "c": "still too much white space,\ntry tightening"}}})
        self.assertEqual(text, "[Articles Index — Design Review]\n"
                               "1. Article card layout — REVISE — COMMENT: still too much white space, try tightening\n"
                               "2. Read More button placement — PENDING")
        text = self.export("design-review", {"items": {"2": {"s": "accept-comment", "c": "make it teal"},
                                                       "1": {"s": "deny"}}})
        self.assertIn("1. Article card layout — DENY\n", text)
        self.assertIn("2. Read More button placement — ACCEPT WITH COMMENT — COMMENT: make it teal", text)

    def test_design_review_defaults_to_the_recommended_variant(self):
        text = self.export("design-review", {"items": {"1": {"s": "accept-comment", "c": "x"}}})
        self.assertIn("1. Article card layout — ACCEPT WITH COMMENT (Use Selected: Variant B) — COMMENT: x", text)

    def test_design_review_defaults_to_the_first_variant_when_none_is_recommended(self):
        spec = self._recommend_b()
        spec["sections"][0]["items"][0]["variants"][1].pop("recommended")
        text = self.export_spec(spec, {"items": {"1": {"s": "accept"}}})
        self.assertIn("1. Article card layout — ACCEPT (Use Selected: Variant A", text)

    def test_capture_findings_go_on_the_page_as_their_own_section(self):
        # Astro run 2: the capture's findings were offered only in chat. design-review now puts
        # them in a second review section, "Found by the capture", one item each, after the
        # requested items; the reader accepts or denies each, and the export numbers run on.
        spec = json.loads((EXAMPLES / "design-review.json").read_text())
        spec.pop("assets")
        spec["sections"][0]["items"][0].pop("body_html")
        spec["sections"].append({"title": "Found by the capture", "items": [
            {"label": "Steps column out of line at 1440", "category": "capture", "recommended": True,
             "body_html": "<p>off-center columns: edge at 232 px, the columns around it at 104 px</p>",
             "reason_html": "<p>Give it its neighbors' max-width.</p>"},
            {"label": "Quick-start command breaks mid-word at 390", "category": "capture",
             "body_html": "<p>mid-word breaks: tem|plate</p>"}]})
        page = Path(self._tmp.name) / "c.json"
        page.write_text(json.dumps(spec))
        html = review_page.page(review_page.load_spec(page))
        self.assertIn("Found by the capture", html)
        self.assertLess(html.index("Article card layout"), html.index("Found by the capture"))
        text = self.export_spec(spec, {"items": {"3": {"s": "accept"}, "4": {"s": "deny"}}})
        self.assertIn("3. Steps column out of line at 1440 — ACCEPT (Use Proposed)", text)
        self.assertIn("4. Quick-start command breaks mid-word at 390 — DENY", text)

    def _recommend_b(self, **item):
        # The example's first item, three variants, B recommended (no asset: the spec moves).
        spec = json.loads((EXAMPLES / "design-review.json").read_text())
        spec.pop("assets")
        it = spec["sections"][0]["items"][0]
        it.pop("body_html")
        it["variants"].append({"html": "<p>Third</p>"})
        it.update(item)
        return spec

    def test_design_review_starts_on_the_recommended_variant(self):
        # Vue run 1: B was recommended, but "Use Selected" untouched exported Variant A.
        text = self.export_spec(self._recommend_b(), {"items": {"1": {"s": "accept"}}})
        self.assertIn("1. Article card layout — ACCEPT (Use Selected: Variant B", text)

    def test_design_review_explicit_selected_beats_recommended(self):
        text = self.export_spec(self._recommend_b(selected="C"), {"items": {"1": {"s": "accept"}}})
        self.assertIn("1. Article card layout — ACCEPT (Use Selected: Variant C", text)

    def test_a_selected_key_that_names_no_variant_is_an_error(self):
        p = Path(self._tmp.name) / "bad.json"
        p.write_text(json.dumps(self._recommend_b(selected="Z")))
        r = subprocess.run([sys.executable, str(BUILD), str(p), "--out", str(Path(self._tmp.name) / "bad.html")],
                           capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("selected 'Z' is not one of its variants (A, B, C)", r.stdout + r.stderr)

    def test_design_review_a_pick_beats_the_recommended_variant(self):
        text = self.export_spec(self._recommend_b(), {"items": {"1": {"s": "accept", "v": "A"}}})
        self.assertIn("1. Article card layout — ACCEPT (Use Selected: Variant A", text)

    def test_copy_edit(self):
        text = self.export("copy-edit", {"items": {
            "1": {"s": "deny"},
            "2": {"s": "accept-comment", "c": 'swap "proprietary" for "our own"'}}})
        self.assertEqual(text, "[Pricing Page — Copy-Edit Review]\n"
                               "1. Intro — first sentence — DENY (Keep Original)\n"
                               '2. New — Introduction to the Method — ACCEPT WITH COMMENT — COMMENT: swap "proprietary" for "our own"')
        self.assertIn("1. Intro — first sentence — ACCEPT (Use Edit)",
                      self.export("copy-edit", {"items": {"1": {"s": "accept"}}}))

    def test_comment_on_plain_accept_is_kept_and_blank_comment_dropped(self):
        text = self.export("copy-edit", {"items": {"1": {"s": "accept", "c": "note"}, "2": {"s": "deny", "c": "  "}}})
        self.assertIn("1. Intro — first sentence — ACCEPT (Use Edit) — COMMENT: note", text)
        self.assertIn("2. New — Introduction to the Method — DENY (Keep Original)\n", text + "\n")

    def test_photo_picker(self):
        text = self.export("photo-picker", {"items": {
            "1": {"s": "accept", "v": "B"},
            "2": {"s": "deny"}}})
        self.assertEqual(text, "[How-To Guides — Photo Picker]\n"
                               "1. Article One — Introduction section — ACCEPT (Use Selected: Option B, trail map)\n"
                               "2. Article Two — Proofing Basket — DENY (Keep None)")

    def test_style_guide(self):
        text = self.export("style-guide", {"items": {
            "1": {"s": "accept-now"},
            "2": {"s": "accept-later", "v": "B", "c": "match the templated size"},
            "3": {"s": "deny", "w": True, "c": "two audiences"}}})
        self.assertEqual(text, "[Style Guide Audit — 2026-01-15]\n"
                               "1. Body text size on disclaimer notes — ACCEPT (Apply Everywhere Now)\n"
                               "2. H2 size on plain articles vs templated ones — ACCEPT (Record for Later: Option B) — COMMENT: match the templated size\n"
                               "3. Customer vs. admin card density — DENY (Works as Designed) — COMMENT: two audiences")

    def test_style_guide_omits_undecided_items(self):
        text = self.export("style-guide", {"items": {"3": {"s": "deny"}}})
        self.assertEqual(text, "[Style Guide Audit — 2026-01-15]\n3. Customer vs. admin card density — DENY")

    def test_questions(self):
        text = self.export("questions", {
            "ans": {"filter-placement": "A - Beside the sort menu in the header row", "qa-delete-item": "COULDN'T TEST"},
            "notes": {"filter-placement": "check the flip-up\non a short viewport", "qa-delete-item": "no attachment handy"}})
        self.assertEqual(text, "[questions v1.3 — answers]\n"
                               "project: acme-app\n"
                               "stream:  list screen filters\n"
                               "round:   2\n"
                               "artifact: (the published URL of this page)\n"
                               "sent:    2026-03-14T18:53Z\n"
                               "\n"
                               "Q filter-placement (raised r1) | Where the new filter control sits on the list screen\n"
                               "  -> A - Beside the sort menu in the header row\n"
                               "  note: check the flip-up\n"
                               "  note: on a short viewport\n"
                               "\n"
                               "Q spec-approval (raised r2) | Does the written spec match what you agreed?\n"
                               "  -> (UNANSWERED)\n"
                               "\n"
                               "--- QA results ---\n"
                               "\n"
                               "QA qa-delete-item | Delete an item that has an attachment\n"
                               "  -> COULDN'T TEST\n"
                               "  note: no attachment handy\n")

    def test_questions_unchecked_qa(self):
        self.assertIn("QA qa-delete-item | Delete an item that has an attachment\n  -> (NOT CHECKED)\n",
                      self.export("questions", {}))

    def test_log(self):
        text = self.export("log", {"read": {"M6": True}, "ans": {"M6::push": "Pushed — it worked"},
                                   "notes": {"M6": "had to add the workflow permission"}, "extra": "ship it"})
        self.assertEqual(text, "WORKING LOG — my replies\n"
                               "project: Acme Widgets\n"
                               "session: invoice-export\n"
                               "repo: acme/widgets\n"
                               "log: 2026-03-14 · invoice-export · page v3\n"
                               "round: M5–M6\n"
                               "branch: invoice-export\n"
                               "exported: 2026-03-14 18:53\n"
                               "\n"
                               "M6  [read]  Found it — the config change was never being used\n"
                               "      answer: Pushed — it worked\n"
                               "      note: had to add the workflow permission\n"
                               "M5  [unread]  Why the new setting changed nothing\n"
                               "\n"
                               "anything else:\n"
                               "ship it\n")

    def export_spec(self, spec, state):
        p = Path(self._tmp.name) / "spec.json"
        p.write_text(json.dumps(spec))
        page = Path(self._tmp.name) / "spec.html"
        r = subprocess.run([sys.executable, str(BUILD), str(p), "--out", str(page)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = subprocess.run([NODE, str(self.driver), str(page), json.dumps(state)],
                           capture_output=True, text=True, env=dict(os.environ, TZ="UTC"))
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_sections_list_matches_flat_shorthand(self):
        spec = json.loads((EXAMPLES / "questions.json").read_text())
        spec["sections"] = [{"kind": "questions", "items": spec.pop("questions")},
                            {"kind": "qa", "items": spec.pop("qa")}]
        state = {"ans": {"spec-approval": "Not yet - see my note", "qa-delete-item": "FAIL"}}
        self.assertEqual(self.export_spec(spec, state), self.export("questions", state))

    def test_mixed_kinds_each_add_their_block(self):
        spec = {"mode": "log", "title": "s1 · P log", "project": {"name": "P", "session": "s1"},
                "sections": [
                    {"kind": "log", "items": [{"id": "M1", "title": "One"}]},
                    {"kind": "review", "decisions": "design-review", "items": [{"label": "Card"}]},
                    {"kind": "qa", "items": [{"qaid": "qa-x", "check": "Open it"}]}]}
        text = self.export_spec(spec, {"items": {"1": {"s": "accept"}}, "ans": {"qa-x": "PASS"}})
        self.assertEqual(text.split("\n\n", 1)[1],
                         "M1  [unread]  One\n1. Card — ACCEPT (Use Proposed)\n--- QA results ---\n\n"
                         "QA qa-x | Open it\n  -> PASS\n\n")

    def test_session_exports_every_section_in_one_block(self):
        text = self.export("session", {
            "ans": {"csv-dates": "ISO dates (2026-03-14)", "qa-export-file": "FAIL"},
            "notes": {"push-fix": "wait for CI", "qa-export-file": "totals off by one cent", "M5": "thanks"},
            "read": {"M6": True}, "extra": "ship it"})
        self.assertEqual(text, "WORKING LOG — my replies\n"
                               "project: Acme Widgets\n"
                               "session: invoice-export\n"
                               "repo: acme/widgets\n"
                               "artifact: (the published URL of this page)\n"
                               "page: v4\n"
                               "branch: invoice-export\n"
                               "exported: 2026-03-14 18:53\n"
                               "\n"
                               "--- Questions ---\n"
                               "\n"
                               "Q csv-dates (raised r2) | Which date format should the CSV export use?\n"
                               "  -> ISO dates (2026-03-14)\n"
                               "\n"
                               "Q push-fix (raised r1) | Can I push the settings fix to the branch?\n"
                               "  -> (UNANSWERED)\n"
                               "  note: wait for CI\n"
                               "\n"
                               "--- QA results ---\n"
                               "\n"
                               "QA qa-export-file | Export last month's invoices and open the file\n"
                               "  -> FAIL\n"
                               "  note: totals off by one cent\n"
                               "\n"
                               "--- Log ---\n"
                               "\n"
                               "M6  [read]  Mar 14 - 3:54PM  Found it — the config change was never being used\n"
                               "M5  [unread]  Why the new setting changed nothing\n"
                               "      note: thanks\n"
                               "\n"
                               "anything else:\n"
                               "ship it\n")

    def test_session_export_leaves_out_empty_sections(self):
        spec = {"mode": "session", "title": "s1 · P session", "project": {"name": "P", "session": "s1"},
                "entries": [{"id": "M1", "title": "One"}]}
        self.assertEqual(self.export_spec(spec, {}).split("\n", 4)[4],
                         "\n--- Log ---\n\nM1  [unread]  One\n")

    def test_qa_checklist_page_exports_results(self):
        text = self.export("qa-checklist", {"ans": {"qa-delete-item": "PASS"}})
        self.assertTrue(text.startswith("[qa-checklist v1.0 — results]\nproject: acme-app\nstream:  attachments release\n"))
        self.assertIn("QA qa-delete-item | Delete an item that has an attachment\n  -> PASS\n", text)
        self.assertIn("QA qa-photos | Open an inspection on your phone and tap a photo\n  -> (NOT CHECKED)\n", text)
        self.assertNotIn("Q ", text.replace("QA ", ""))

    def test_log_unanswered_group(self):
        self.assertIn("M6  [unread]  Found it — the config change was never being used\n      answer: (unanswered)\n",
                      self.export("log", {}))


class BuildAndCheck(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    @unittest.skipUnless(NODE, "node is not installed")
    def test_every_example_builds_and_checks(self):
        for spec in sorted(EXAMPLES.glob("*.json")):
            page = build(spec.stem, self.tmp)
            self.assertEqual(review_page.check(page), [], spec.name)
            text = page.read_text()
            self.assertNotIn("{{asset:", text)
            self.assertIn("<title>", text)

    def test_spec_errors(self):
        bad = [({"mode": "review"}, "title"),
               ({"mode": "nope", "title": "x"}, "mode"),
               ({"title": "x", "decisions": "made-up"}, "preset"),
               ({"title": "x", "items": [{"label": "a", "id": "1"}, {"label": "b", "id": "1"}]}, "duplicate"),
               ({"title": "x", "items": [{"id": "1"}]}, "label"),
               ({"mode": "log", "title": "x", "project": {"name": "p"}}, "session"),
               ({"mode": "questions", "title": "x", "project": {"name": "p", "stream": "s"},
                 "questions": [{"qid": "a"}, {"qid": "a"}]}, "qid"),
               ({"title": "x", "sections": [{"kind": "nope"}]}, "kind"),
               ({"title": "x", "sections": [{"id": "a", "items": [{"label": "a"}]}, {"id": "a"}]}, "section id"),
               ({"mode": "questions", "title": "x", "project": {"name": "p", "stream": "s"},
                 "sections": [{"kind": "questions", "items": [{"qid": "a"}]},
                              {"kind": "qa", "items": [{"qaid": "a"}]}]}, "unique on the page"),
               ({"mode": "session", "title": "s · p", "project": {"name": "p", "session": "s"},
                 "sections": [{"kind": "review", "items": [{"label": "a"}]}]}, "links"),
               ({"mode": "session", "title": "s · p", "project": {"name": "p", "session": "s"},
                 "entries": [{"id": "M1", "questions": [{"q": "a", "options": ["x"]}]}]}, "Waiting on you"),
               ({"mode": "session", "title": "s · p", "project": {"name": "p"}}, "session"),
               ({"mode": "session", "title": "s · p", "project": {"name": "p", "session": "s"},
                 "links": [{"label": "Design review"}]}, "url")]
        for spec, word in bad:
            p = self.tmp / "s.json"
            p.write_text(json.dumps(spec))
            with self.assertRaises(review_page.SpecError) as cm:
                review_page.page(review_page.load_spec(p))
            self.assertIn(word, str(cm.exception))

    def test_html_fields_are_raw_and_text_fields_escaped(self):
        p = self.tmp / "s.json"
        p.write_text(json.dumps({"title": "A <b> & C", "items": [
            {"label": "<script>x</script>", "body_html": "<em>kept</em>", "reason_html": "@file:reason.html"}]}))
        (self.tmp / "reason.html").write_text("<p>from a file</p>")
        text = review_page.page(review_page.load_spec(p))
        self.assertIn("<title>A &lt;b&gt; &amp; C</title>", text)
        self.assertIn("&lt;script&gt;x&lt;/script&gt;", text)
        self.assertIn("<em>kept</em>", text)
        self.assertIn("<p>from a file</p>", text)
        self.assertIn('"header": "[A \\u003cb> & C]"', text)

    def test_spec_json_cannot_close_its_script(self):
        p = self.tmp / "s.json"
        p.write_text(json.dumps({"title": "x</script><script>alert(1)", "items": [{"label": "a"}]}))
        text = review_page.page(review_page.load_spec(p))
        self.assertEqual(len(re.findall(r"<script", text)), 2)

    @unittest.skipUnless(NODE, "node is not installed")
    def test_check_catches_a_broken_script(self):
        page = build("copy-edit", self.tmp)
        page.write_text(page.read_text().replace('"use strict";', '"use strict"; var x = \'it\\\\\'s\';', 1))
        errs = review_page.check(page)
        self.assertTrue(any("node --check" in e for e in errs), errs)

    def test_check_catches_missing_buttons_and_bad_log_title(self):
        page = build("copy-edit", self.tmp) if NODE else None
        if page:
            page.write_text(page.read_text().replace('data-choice="revise"', 'data-x="revise"', 1))
            self.assertTrue(any("decision buttons" in e for e in review_page.check(page)))
            log = build("log", self.tmp)
            log.write_text(log.read_text().replace("<title>invoice-export · ", "<title>"))
            self.assertTrue(any("session" in e for e in review_page.check(log)))

    def page_text(self, spec):
        p = self.tmp / "s.json"
        p.write_text(json.dumps(spec))
        return review_page.page(review_page.load_spec(p))

    def first_in_main(self, text):
        return re.search(r'<main class="rp-main"[^>]*>\s*(<[^>]+>)', text).group(1)

    SESSION = {"mode": "session", "title": "s1 · P session", "project": {"name": "P", "session": "s1"},
               "heading": "About", "intro_html": "<p>context</p>", "facts": [["Tests", "green"]]}

    def test_session_sections_render_in_fixed_order_whatever_the_spec_order(self):
        spec = dict(self.SESSION, sections=[
            {"kind": "decided", "items": [{"title": "Old call", "decision": "yes"}]},
            {"kind": "log", "items": [{"id": "M1", "title": "One"}]},
            {"kind": "qa", "items": [{"qaid": "qa-x", "check": "Open it"}]},
            {"kind": "links", "items": [{"label": "Design review", "status": "3 decisions open", "url": "https://x.test/r"}]},
            {"kind": "questions", "items": [{"qid": "q1", "ask": "Which?", "options": [{"label": "A"}]}]}])
        text = self.page_text(spec)
        self.assertEqual(review_page.rendered_kinds(text), ["questions", "links", "qa", "log", "decided"])
        for title in ("Waiting on you", "Other pages waiting on you", "Checks for you", "Log", "Decided"):
            self.assertIn("<h2>%s" % title, text)
        self.assertIn("<b>Design review</b>: <span class=\"rp-link-status\">3 decisions open</span>", text)
        # context (heading, intro, facts) sits after the action sections, before the log
        self.assertLess(text.index('<section class="rp-section rp-kind-qa"'), text.index('<div class="rp-context">'))
        self.assertLess(text.index('<div class="rp-context">'), text.index('<section class="rp-section rp-kind-log"'))

    def test_log_has_a_hidden_read_heading_for_folded_entries(self):
        text = self.page_text(dict(self.SESSION, entries=[{"id": "M1", "title": "One"}]))
        log = text[text.index('<section class="rp-section rp-kind-log"'):]
        # the engine unhides it once an entry is ticked; read entries fold under it
        self.assertIn('<h3 class="rp-read-head" hidden>Read</h3>', log)
        self.assertLess(log.index("rp-read-head"), log.index('data-entry="M1"'))
        self.assertIn('<span class="rp-tick-l">Read this</span>', log)

    def test_in_page_links_stay_on_the_page_and_say_where_they_go(self):
        spec = dict(self.SESSION, questions=[{"qid": "q1", "ask": "Which?", "options": [{"label": "A"}]}],
                    entries=[{"id": "L3", "title": "One"}],
                    links=[{"label": "Repos", "status": "1 question", "url": "#questions"},
                           {"label": "Brief", "url": "#L3"},
                           {"label": "Review", "url": "https://x.test/r"}])
        text = self.page_text(spec)
        self.assertIn('<section class="rp-section rp-kind-questions" data-section="s1" id="questions">', text)
        self.assertIn('id="L3" data-entry="L3"', text)
        self.assertIn('<a href="#questions">Open questions above</a>', text)
        self.assertIn('<a href="#L3">See it in the log below</a>', text)
        self.assertNotIn('href="#questions" target', text)
        self.assertIn('href="https://x.test/r" target="_blank" rel="noopener">Open it</a>', text)

    def test_check_catches_an_in_page_link_with_nothing_to_land_on(self):
        spec = dict(self.SESSION, entries=[{"id": "L3", "title": "One"}],
                    links=[{"label": "Repos", "status": "answered", "url": "#questions"}])
        page = self.tmp / "p.html"
        page.write_text(self.page_text(spec))
        errs = review_page.check(page)
        self.assertTrue(any("link to #questions" in e for e in errs), errs)

    def test_session_shows_only_sections_with_content(self):
        spec = dict(self.SESSION, questions=[], qa=[], links=[], decided=[],
                    entries=[{"id": "M1", "title": "One"}])
        text = self.page_text(spec)
        self.assertEqual(review_page.rendered_kinds(text), ["log"])
        self.assertNotIn("Waiting on you", text)
        self.assertNotIn("Checks for you", text)
        spec = dict(self.SESSION, qa=[{"qaid": "qa-x", "check": "Open it"}])
        self.assertEqual(review_page.rendered_kinds(self.page_text(spec)), ["qa"])

    def test_open_questions_come_first_on_session_and_questions_pages(self):
        spec = dict(self.SESSION, entries=[{"id": "M1", "title": "One"}],
                    questions=[{"qid": "q1", "ask": "Which?", "options": [{"label": "A"}]}])
        self.assertIn("rp-kind-questions", self.first_in_main(self.page_text(spec)))
        q = {"mode": "questions", "title": "x", "project": {"name": "p", "stream": "s"},
             "heading": "Round 2", "intro_html": "<p>long context</p>",
             "sections": [{"kind": "qa", "items": [{"qaid": "qa-x", "check": "Open it"}]},
                          {"kind": "questions", "items": [{"qid": "q1", "ask": "Which?"}]}]}
        text = self.page_text(q)
        self.assertIn("rp-kind-questions", self.first_in_main(text))
        self.assertEqual(review_page.rendered_kinds(text), ["questions", "qa"])
        self.assertLess(text.index('<section class="rp-section rp-kind-qa"'), text.index("Round 2"))

    @unittest.skipUnless(NODE, "node is not installed")
    def test_check_catches_questions_pushed_down_the_page(self):
        page = build("session", self.tmp)
        text = page.read_text()
        page.write_text(text.replace('<main class="rp-main" data-preview="light">',
                                     '<main class="rp-main" data-preview="light"><p>A long report first</p>', 1))
        self.assertTrue(any("first thing under the sticky bar" in e for e in review_page.check(page)))
        log_at = text.index('<section class="rp-section rp-kind-log"')
        qa = re.search(r'<section class="rp-section rp-kind-qa".*?</section>', text, re.S).group(0)
        swapped = text.replace(qa, "", 1)
        swapped = swapped.replace('<section class="rp-section rp-kind-decided"', qa + '<section class="rp-section rp-kind-decided"', 1)
        page.write_text(swapped)
        self.assertTrue(log_at and any("out of order" in e for e in review_page.check(page)))

    def test_standalone_questions_and_qa_pages_have_their_own_chrome(self):
        for name, fmt in (("questions", "questions v1.3"), ("qa-checklist", "qa-checklist v1.0")):
            spec = json.loads((EXAMPLES / (name + ".json")).read_text())
            text = review_page.page(review_page.load_spec(EXAMPLES / (name + ".json")))
            self.assertIn('class="rp rp-mode-questions"', text)
            self.assertIn('<div class="bar">', text)
            self.assertNotIn('<div class="rp-projectbar">', text)
            self.assertIn('"format": "%s"' % fmt, text)
            self.assertIn(spec.get("copy_label", "Copy my answers"), text)

    def brand_of(self, text):
        m = re.search(r'<span class="rp-brand">.*?<span class="rp-sr">(.*?)</span>', text)
        return m and m.group(1)

    def test_every_mode_starts_with_the_brand_and_its_default_skill(self):
        want = {"session": "Proofs, working-log", "log": "Proofs, working-log",
                "questions": "Proofs, questions", "qa-checklist": "Proofs, qa-checklist",
                "design-review": "Proofs, design-review", "copy-edit": "Proofs, article-copy-edit",
                "style-guide": "Proofs, style-guide", "photo-picker": "Proofs, photo-picker"}
        for name, sr in want.items():
            text = review_page.page(review_page.load_spec(EXAMPLES / (name + ".json")))
            self.assertEqual(self.brand_of(text), sr, name)
            self.assertEqual(text.count('<span class="rp-brand">'), 1, name)
            self.assertIn('<span class="rp-wm" aria-hidden="true">pro<i>o</i>fs</span>', text)
            self.assertIn('<span class="rp-sk" aria-hidden="true">%s</span>' % sr.split(", ")[1], text)
        # where it sits: first in the project bar, first in the questions bar, above a review heading
        session = review_page.page(review_page.load_spec(EXAMPLES / "session.json"))
        self.assertIn('<div class="rp-projectbar"><span class="rp-brand">', session)
        self.assertNotIn("Session page", session)
        q = review_page.page(review_page.load_spec(EXAMPLES / "questions.json"))
        self.assertIn('<div class="bar"><span class="rp-brand">', q)
        dr = review_page.page(review_page.load_spec(EXAMPLES / "design-review.json"))
        self.assertRegex(dr, r'<main class="rp-main"[^>]*>\s*<div class="rp-brandline"><span class="rp-brand">')
        self.assertLess(dr.index("rp-brandline"), dr.index('<h1 class="rp-h1">'))

    def test_every_mode_names_its_project_and_session_beside_the_mark(self):
        session = review_page.page(review_page.load_spec(EXAMPLES / "session.json"))
        self.assertRegex(session, r'<div class="rp-projectbar"><span class="rp-brand">.*?</span></span>'
                                  r'<span class="rp-pb-x">Acme Widgets · </span><b class="rp-session">invoice-export</b>')
        q = review_page.page(review_page.load_spec(EXAMPLES / "qa-checklist.json"))
        self.assertIn('<div class="bar-title">Acme app <span>· checks after deploy</span>'
                      '<span class="rp-sess"> · <b class="rp-session">attachments-release</b></span></div>', q)
        dr = review_page.page(review_page.load_spec(EXAMPLES / "design-review.json"))
        # Rails run 1: each separator belongs to the part after it (and hides with it).
        self.assertIn('<span class="rp-where">Acme app<span class="rp-wp"><span class="rp-sep"> · </span>'
                      '<b class="rp-session">articles-redesign</b></span>'
                      '<span class="rp-pb-x"><span class="rp-sep"> · </span>acme/app</span></span></div>', dr)
        # a review page with no project at all keeps the bare mark line
        text = self.page_text({"title": "x", "decisions": "design-review", "items": [{"label": "a"}]})
        self.assertNotIn('class="rp-where"', text)

    def test_a_page_with_no_session_builds_with_a_warning(self):
        for spec in ({"title": "x", "items": [{"label": "a"}]},
                     {"title": "x", "project": {"name": "P"}, "items": [{"label": "a"}]},
                     {"mode": "questions", "title": "x", "project": {"name": "p", "stream": "s"},
                      "questions": [{"qid": "q1", "ask": "Which?"}]}):
            p = self.tmp / "s.json"
            p.write_text(json.dumps(spec))
            r = subprocess.run([sys.executable, str(BUILD), str(p), "--out", str(self.tmp / "p.html"), "--no-check"],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(review_page.warnings(self.tmp / "p.html"), [review_page.NO_SESSION])
        for name in ("design-review", "questions", "session", "log"):
            self.assertEqual(review_page.warnings(build(name, self.tmp)), [], name)

    def test_skill_field_overrides_the_default_and_custom_decisions_show_the_wordmark_alone(self):
        text = self.page_text(dict(self.SESSION, skill="review-cycle", entries=[{"id": "M1", "title": "One"}]))
        self.assertEqual(self.brand_of(text), "Proofs, review-cycle")
        text = self.page_text({"title": "x", "skill": "pr-qa", "decisions": "design-review", "items": [{"label": "a"}]})
        self.assertEqual(self.brand_of(text), "Proofs, pr-qa")
        custom = {"buttons": [{"state": "accept", "label": "OK", "export": "OK"}]}
        for spec in ({"title": "x", "decisions": custom, "items": [{"label": "a"}]},
                     {"title": "x", "skill": "", "decisions": "copy-edit", "items": [{"label": "a"}]}):
            text = self.page_text(spec)
            self.assertEqual(self.brand_of(text), "Proofs")
            self.assertNotIn('class="rp-sk"', text)
        # the preset may come from a section, or from a custom set built on a preset
        text = self.page_text({"title": "x", "sections": [{"decisions": {"preset": "photo-picker"}, "items": [{"label": "a"}]}]})
        self.assertEqual(self.brand_of(text), "Proofs, photo-picker")

    def test_links_in_progress_sort_after_open_ones_without_the_call_to_action(self):
        links = [{"label": "Copy edit", "status": "answered", "url": "https://x.test/c", "state": "in-progress"},
                 {"label": "Design review", "status": "3 open", "url": "https://x.test/d"}]
        text = self.page_text(dict(self.SESSION, links=links))
        sec = text[text.index('<section class="rp-section rp-kind-links"'):]
        sec = sec[:sec.index("</section>")]
        self.assertIn("<h2>Other pages waiting on you</h2>", sec)
        self.assertLess(sec.index("Design review"), sec.index("Copy edit"))
        self.assertIn('<a href="https://x.test/d" target="_blank" rel="noopener">Open it</a>', sec)
        self.assertIn('<li class="rp-link-wip"><b>Copy edit</b>: <span class="rp-link-status">answered</span> '
                      '<span class="rp-wip">In progress</span> <a class="rp-link-quiet" href="https://x.test/c"', sec)
        self.assertEqual(sec.count("Open it"), 1)
        # all in progress: the heading says so, unless the spec names its own
        text = self.page_text(dict(self.SESSION, links=links[:1]))
        self.assertIn("<h2>Pages Claude is working on</h2>", text)
        self.assertNotIn("Other pages waiting on you", text)
        text = self.page_text(dict(self.SESSION, links=links[:1], links_heading="Mine"))
        self.assertIn("<h2>Mine</h2>", text)
        with self.assertRaises(review_page.SpecError) as cm:
            self.page_text(dict(self.SESSION, links=[dict(links[0], state="done")]))
        self.assertIn("state", str(cm.exception))

    def test_when_reads_as_a_short_local_time(self):
        for iso, want in (("2026-11-19T15:54", "Nov 19 - 3:54PM"), ("2026-11-19T00:05", "Nov 19 - 12:05AM"),
                          ("2026-01-02T12:30", "Jan 2 - 12:30PM"), ("2026-12-31T09:07:45", "Dec 31 - 9:07AM"),
                          ("2026-07-04 23:59", "Jul 4 - 11:59PM")):
            self.assertEqual(review_page.short_when(iso), want, iso)
        for bad in ("Nov 19", "2026-13-01T10:00", "2026-11-19T24:00", "2026-11-19T15:54Z"):
            with self.assertRaises(review_page.SpecError):
                review_page.short_when(bad)

    def test_log_entries_show_when_only_if_given(self):
        text = self.page_text(dict(self.SESSION, entries=[{"id": "M2", "title": "Two", "when": "2026-11-19T00:05"},
                                                          {"id": "M1", "title": "One"}]))
        self.assertIn('<h3>Two</h3><time class="rp-when" datetime="2026-11-19T00:05">Nov 19 - 12:05AM</time>', text)
        self.assertIn("<h3>One</h3><span class=\"rp-status", text)
        self.assertEqual(text.count('<time class="rp-when"'), 1)

    def test_session_log_entries_never_ask(self):
        # A free-text question once went out as a "Your move" log entry: no buttons, so the
        # option-group check let it through, and the user had to find it in the log.
        ok = self.page_text(dict(self.SESSION, entries=[{"id": "M1", "title": "One", "status": "Queued"}]))
        self.assertIn("rp-status-queued", ok)
        for entry in ({"id": "M1", "title": "One", "status": "Your move"},
                      {"id": "M1", "title": "One", "lede": "What should the logo make a developer feel?"}):
            with self.assertRaises(review_page.SpecError) as cm:
                self.page_text(dict(self.SESSION, entries=[entry]))
            self.assertIn("`questions`", str(cm.exception))

    def test_custom_decisions_override_a_preset(self):
        p = self.tmp / "s.json"
        p.write_text(json.dumps({"title": "x", "decisions": {"preset": "copy-edit", "mark_read": True},
                                 "items": [{"label": "a"}]}))
        text = review_page.page(review_page.load_spec(p))
        self.assertIn("Mark as read", text)
        self.assertIn("✓ Use Edit", text)


MAGICK = shutil.which("magick")
WEBP = MAGICK or shutil.which("cwebp")


def write_png(path, width, height):
    """A real, compressible PNG (a gradient) made with the stdlib only."""
    import struct
    import zlib
    raw = b"".join(b"\x00" + b"".join(bytes(((x * 7 + y * 3) % 256, (x * 2) % 256, (y * 5) % 256))
                                       for x in range(width)) for y in range(height))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class Assets(unittest.TestCase):
    """Each asset's bytes appear once; screenshots become WebP; the settings and
    fallbacks behave."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        write_png(self.tmp / "shot.png", 400, 300)
        (self.tmp / "font.woff2").write_bytes(b"wOF2" + os.urandom(3000))

    def spec(self, body, css="", **extra):
        s = {"mode": "review", "title": "Assets — Design Review", "decisions": "design-review",
             "assets": {"shot": "shot.png", "font": "font.woff2"}, "css": css,
             "sections": [{"title": "S", "items": [{"label": "x", "recommended": True, "body_html": body,
                                                    "reason_html": "<p>r</p>"}]}]}
        s.update(extra)
        (self.tmp / "spec.json").write_text(json.dumps(s))
        return self.tmp / "spec.json"

    def built(self, *a, env=None, **k):
        out = self.tmp / "page.html"
        e = dict(os.environ, **(env or {}))
        r = subprocess.run([sys.executable, str(BUILD), str(self.spec(*a, **k)), "--out", str(out), "--no-check"],
                           capture_output=True, text=True, env=e)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return out.read_text(), r.stdout

    def b64(self, name):
        import base64
        return base64.b64encode((self.tmp / name).read_bytes()).decode()

    def test_font_in_css_is_embedded_once(self):
        text, _ = self.built("<p>x</p>", css="@font-face{font-family:F;src:url({{asset:font}}) format('woff2')}")
        self.assertEqual(text.count(self.b64("font.woff2")), 1)
        self.assertIn("src:url(data:font/woff2;base64,", text)  # @font-face cannot read a CSS variable
        self.assertNotIn("--asset-font", text)

    def test_one_html_use_is_inlined_without_a_variable(self):
        text, _ = self.built('<img alt="a" src="{{asset:shot}}">', env={"PROOFS_IMAGE_QUALITY": ""})
        self.assertEqual(len(re.findall(r"data:image/webp;base64", text)), 1 if WEBP else 0)
        self.assertEqual(len(re.findall(r"data:image/(?:png|jpeg);base64", text)), 1)
        self.assertNotIn("--asset-shot", text)
        self.assertNotIn("data-rp-asset", text)
        self.assertNotIn('id="rp-assets"', text)

    def test_many_uses_share_one_copy(self):
        body = '<img alt="a" src="{{asset:shot}}"><img alt="b" src="{{asset:shot}}"><div style="background:url({{asset:shot}})"></div>'
        text, _ = self.built(body)
        self.assertEqual(len(re.findall(r"data:image/webp;base64", text)), 1 if WEBP else 0)
        self.assertEqual(text.count('data-rp-asset="src shot img"'), 2)
        self.assertIn("background:var(--asset-shot)", text)
        self.assertRegex(text, r"--asset-shot:url\(data:image/(?:png|jpeg);")  # CSS gets the format every browser shows
        self.assertNotIn("{{asset:", text)
        self.assertEqual(review_page.image_errors(text), [])

    @unittest.skipUnless(WEBP and shutil.which("magick"), "needs a WebP encoder and ImageMagick to measure")
    def test_a_shot_taller_than_webp_allows_is_scaled_to_fit(self):
        # Vue run 1: a 390px phone page at 2x was 27188px tall; WebP stops at 16383, so the
        # encoder failed and the full PNG went in. Now it is scaled down until it fits.
        write_png(self.tmp / "tall.png", 60, 20000)
        self.assertEqual(review_page.image_size(self.tmp / "tall.png"), (60, 20000))
        data = review_page.to_webp(self.tmp / "tall.png", review_page.image_settings({}), review_page.image_tool())
        self.assertIsNotNone(data)
        (self.tmp / "tall.webp").write_bytes(data)
        w, h = subprocess.run(["magick", "identify", "-format", "%w %h", str(self.tmp / "tall.webp")],
                              capture_output=True, text=True).stdout.split()
        self.assertLessEqual(int(h), review_page.WEBP_MAX_DIM)
        self.assertEqual(int(w), 60 * review_page.WEBP_MAX_DIM // 20000)

    @unittest.skipUnless(WEBP, "no WebP encoder installed")
    def test_webp_img_is_a_picture_with_a_fallback_old_safari_can_show(self):
        # Regression: older iOS Safari (before 14) cannot decode WebP and showed a "?".
        text, _ = self.built('<img class="rp-shot" alt="Card grid" loading="lazy" src="{{asset:shot}}">')
        pic = re.search(r'<picture class="rp-pic">(<source [^>]*>)(<img [^>]*>)</picture>', text)
        self.assertIsNotNone(pic, "no <picture> around the screenshot")
        self.assertIn('type="image/webp" srcset="data:image/webp;base64,', pic.group(1))
        self.assertRegex(pic.group(2), r'src="data:image/(?:png|jpeg);base64,')
        for attr in ('class="rp-shot"', 'alt="Card grid"', 'loading="lazy"'):
            self.assertIn(attr, pic.group(2))
        self.assertEqual(review_page.image_errors(text), [])

    @unittest.skipUnless(WEBP, "no WebP encoder installed")
    def test_repeated_images_fill_from_a_json_map_not_a_css_variable(self):
        # Regression: repeated images were read back with getComputedStyle(), which
        # returned nothing usable on older iOS Safari, so every one stayed blank.
        text, _ = self.built('<img alt="a" src="{{asset:shot}}"><img alt="b" src="{{asset:shot}}">')
        self.assertNotIn("getComputedStyle", text)
        self.assertNotIn("--asset-shot", text)
        m = re.search(r'<script type="application/json" id="rp-assets">(.*?)</script>', text, re.S)
        shared = json.loads(m.group(1))["shot"]
        self.assertTrue(shared["webp"].startswith("data:image/webp;base64,"))
        self.assertRegex(shared["img"], r"^data:image/(?:png|jpeg);base64,")
        self.assertEqual(text.count(shared["webp"]), 1)
        self.assertEqual(text.count(shared["img"]), 1)
        self.assertEqual(text.count('<source type="image/webp" data-rp-asset="srcset shot webp">'), 2)
        self.assertEqual(text.count('data-rp-asset="src shot img"'), 2)
        self.assertEqual(review_page.image_errors(text), [])

    @unittest.skipUnless(NODE, "node is not installed")
    def test_fill_script_sets_every_shared_attribute(self):
        text, _ = self.built('<img alt="a" src="{{asset:shot}}"><img alt="b" src="{{asset:shot}}">')
        m = re.search(r'<script type="application/json" id="rp-assets">(.*?)</script>', text, re.S)
        driver = (
            "const map = %s; const els = [];"
            "function El(a){this.a=a;} El.prototype.getAttribute=function(k){return this.a[k];};"
            "El.prototype.setAttribute=function(k,v){this.a[k]=v;};"
            "%s.forEach(function(a){els.push(new El(a));});"
            "global.document={getElementById:function(){return {textContent:JSON.stringify(map)};},"
            "querySelectorAll:function(){return els;}};"
            "%s\nconsole.log(JSON.stringify(els.map(function(e){return e.a;})));"
        ) % (m.group(1), json.dumps([{"data-rp-asset": d} for d in re.findall(r'data-rp-asset="([^"]*)"', text)]),
             review_page.ASSET_FILL)
        r = subprocess.run([NODE, "-e", driver], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        for el in json.loads(r.stdout):
            attr = el["data-rp-asset"].split(" ")[0]
            self.assertTrue(el.get(attr, "").startswith("data:image/"), el["data-rp-asset"])
            self.assertNotIn("image/gif", el[attr])

    def test_check_catches_a_picture_without_a_usable_fallback(self):
        webp = '<picture class="rp-pic"><source type="image/webp" srcset="data:image/webp;base64,AA"><img src="data:image/webp;base64,AA"></picture>'
        none = '<picture><source type="image/webp" srcset="data:image/webp;base64,AA"></picture>'
        self.assertIn("falls back to WebP", review_page.image_errors(webp)[0])
        self.assertIn("no <img src> fallback", review_page.image_errors(none)[0])
        blank = '<img src="%s" alt="x">' % review_page.BLANK_GIF
        self.assertIn("blank placeholder", review_page.image_errors(blank)[0])
        orphan = '<img src="%s" data-rp-asset="src gone img">' % review_page.BLANK_GIF
        self.assertIn("nothing in rp-assets", review_page.image_errors(orphan)[0])

    def test_a_font_with_no_fallback_stack_is_a_warning(self):
        # Django run 1: the font download was denied and the mockups fell to the browser default.
        self.built('<p style="font-family:&quot;Space Grotesk&quot;">x</p>',
                   css="@font-face{font-family:F;src:url({{asset:font}}) format('woff2')}"
                       ".mk{font-family:'Space Grotesk'}.b{font-family:Inter, Arial}")
        found = [w for w in review_page.warnings(self.tmp / "page.html") if "fallback" in w]
        self.assertEqual(len(found), 3, found)
        self.assertIn("'Space Grotesk'", found[0])
        self.assertIn("Inter, Arial", found[1])
        self.assertIn('"Space Grotesk"', found[2])  # the style attribute
        self.assertIn("sans-serif", found[0])

    def test_a_font_stack_ending_in_a_generic_family_is_fine(self):
        self.built('<p style="font-family:Georgia, serif">x</p>',
                   css="@font-face{font-family:F;src:url({{asset:font}}) format('woff2')}"
                       ".mk{font-family:\"Space Grotesk\", \"Avenir Next\", ui-sans-serif, system-ui, sans-serif}"
                       ".c{font-family:var(--mono)}.d{font-family:inherit}.e{font-family:F, monospace;}")
        self.assertEqual([w for w in review_page.warnings(self.tmp / "page.html") if "fallback" in w], [])

    def test_a_webp_asset_with_no_fallback_is_a_warning(self):
        (self.tmp / "pic.webp").write_bytes(b"RIFF\x00\x00\x00\x00WEBPVP8 ")
        self.built('<img alt="a" src="{{asset:w}}">', assets={"w": "pic.webp"})
        self.assertTrue(any("older Safari" in w for w in review_page.warnings(self.tmp / "page.html")))

    def stub_fallback(self, sizes):
        """Replace the fallback encoder with one returning sizes[(width, fmt)] bytes."""
        calls = []
        def fake(path, quality, width, fmt):
            calls.append((width, fmt))
            n = sizes.get((width, fmt))
            return None if n is None else b"x" * n
        real = review_page.encode_fallback
        review_page.encode_fallback = fake
        self.addCleanup(setattr, review_page, "encode_fallback", real)
        return calls

    def test_fallback_is_the_smallest_of_jpeg_shrunk_png_and_the_original(self):
        src = self.tmp / "shot.png"  # 400 px wide, opaque
        size = src.stat().st_size
        calls = self.stub_fallback({(None, "jpg"): size - 5, (200, "jpg"): size - 50, (200, "png"): size - 20})
        data, mime = review_page.to_fallback(src, {"quality": 70, "max_width": 200})
        self.assertEqual((len(data), mime), (size - 50, "image/jpeg"))
        self.assertEqual(sorted(calls, key=str), sorted([(None, "jpg"), (200, "jpg"), (200, "png")], key=str))
        self.stub_fallback({(None, "jpg"): size + 5})
        data, mime = review_page.to_fallback(src, {"quality": 70, "max_width": 4000})
        self.assertEqual((data, mime), (src.read_bytes(), "image/png"))

    def test_fallback_never_turns_a_transparent_png_into_a_jpeg(self):
        import struct, zlib
        src = self.tmp / "alpha.png"
        def chunk(t, d):
            return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
        src.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 1, 8, 6, 0, 0, 0))
                        + chunk(b"IDAT", zlib.compress(b"\x00" + b"\x00" * 8)) + chunk(b"IEND", b""))
        self.assertTrue(review_page.has_alpha(src))
        self.assertFalse(review_page.has_alpha(self.tmp / "shot.png"))
        calls = self.stub_fallback({})
        review_page.to_fallback(src, {"quality": 70, "max_width": 1})
        self.assertNotIn("jpg", [f for _, f in calls])

    def test_unused_asset_is_left_out(self):
        text, _ = self.built("<p>x</p>")
        self.assertNotIn(self.b64("font.woff2"), text)

    def test_fonts_svg_and_gif_are_never_converted(self):
        self.assertNotIn(".woff2", review_page.CONVERTIBLE)
        for ext in (".svg", ".gif", ".webp"):
            self.assertNotIn(ext, review_page.CONVERTIBLE)

    def test_settings_precedence_env_then_spec_then_default(self):
        d = review_page.image_settings({}, env={})
        self.assertEqual((d["quality"], d["max_width"]), (review_page.DEFAULT_IMAGE_QUALITY, review_page.DEFAULT_IMAGE_MAX_WIDTH))
        s = review_page.image_settings({"image_quality": 60, "image_max_width": 900}, env={})
        self.assertEqual((s["quality"], s["max_width"]), (60, 900))
        e = review_page.image_settings({"image_quality": 60}, env={"PROOFS_IMAGE_QUALITY": "40", "PROOFS_IMAGE_MAX_WIDTH": "640"})
        self.assertEqual((e["quality"], e["max_width"]), (40, 640))
        for bad in ({"image_quality": 0}, {"image_quality": "high"}, {"image_max_width": 5}):
            with self.assertRaises(review_page.SpecError):
                review_page.image_settings(bad, env={})

    def test_width_is_read_from_png_and_jpeg_headers(self):
        self.assertEqual(review_page.image_width(self.tmp / "shot.png"), 400)
        if MAGICK:
            subprocess.run([MAGICK, str(self.tmp / "shot.png"), str(self.tmp / "shot.jpg")], check=True)
            self.assertEqual(review_page.image_width(self.tmp / "shot.jpg"), 400)

    def test_missing_tool_keeps_the_original_and_says_so(self):
        text, out = self.built('<img alt="a" src="{{asset:shot}}">', env={"PATH": "/nonexistent"})
        self.assertIn("data:image/png;base64," + self.b64("shot.png"), text)
        self.assertNotIn("<picture", text)  # nothing to fall back from
        self.assertIn("no magick or cwebp found", out)

    @unittest.skipUnless(MAGICK or shutil.which("cwebp"), "no WebP encoder installed")
    def test_png_becomes_smaller_webp(self):
        text, out = self.built('<img alt="a" src="{{asset:shot}}">')
        self.assertIn("data:image/webp;base64,", text)
        self.assertIn("lossy at quality %d and lossless" % review_page.DEFAULT_IMAGE_QUALITY, out)
        self.assertIn("fallback for older Safari", out)

    @unittest.skipUnless(MAGICK, "ImageMagick is not installed")
    def test_downscales_when_wider_never_upscales(self):
        tool = review_page.image_tool()
        small = review_page.encode_webp(self.tmp / "shot.png", 80, 200, False, tool)
        (self.tmp / "s.webp").write_bytes(small)
        w = subprocess.run([MAGICK, "identify", "-format", "%w", str(self.tmp / "s.webp")], capture_output=True, text=True).stdout
        self.assertEqual(w, "200")
        big = review_page.to_webp(self.tmp / "shot.png", {"quality": 80, "max_width": 4000}, tool)
        if big is not None:
            (self.tmp / "b.webp").write_bytes(big)
            w = subprocess.run([MAGICK, "identify", "-format", "%w", str(self.tmp / "b.webp")], capture_output=True, text=True).stdout
            self.assertEqual(w, "400")

    def stub_encoder(self, sizes):
        """Replace the encoder with one returning sizes[(width, lossless)] bytes."""
        calls = []
        def fake(path, quality, width, lossless, tool):
            calls.append((width, lossless))
            n = sizes.get((width, lossless))
            return None if n is None else b"x" * n
        real = review_page.encode_webp
        review_page.encode_webp = fake
        self.addCleanup(setattr, review_page, "encode_webp", real)
        return calls

    def test_keeps_the_smaller_of_lossy_and_lossless(self):
        src = self.tmp / "shot.png"
        self.stub_encoder({(None, False): 900, (None, True): 600})
        self.assertEqual(len(review_page.to_webp(src, {"quality": 70, "max_width": None}, ("magick", "m"))), 600)
        self.stub_encoder({(None, False): 500, (None, True): 600})
        self.assertEqual(len(review_page.to_webp(src, {"quality": 70, "max_width": None}, ("magick", "m"))), 500)

    def test_keeps_the_original_when_it_is_smallest(self):
        src = self.tmp / "shot.png"
        big = src.stat().st_size + 10
        self.stub_encoder({(None, False): big, (None, True): big})
        self.assertIsNone(review_page.to_webp(src, {"quality": 70, "max_width": None}, ("magick", "m")))

    def test_shrinks_only_when_the_shrunk_file_is_smaller(self):
        src = self.tmp / "shot.png"  # 400 px wide
        calls = self.stub_encoder({(None, False): 800, (None, True): 700, (200, False): 900, (200, True): 750})
        self.assertEqual(len(review_page.to_webp(src, {"quality": 70, "max_width": 200}, ("magick", "m"))), 700)
        self.assertIn((200, True), calls)
        self.stub_encoder({(None, False): 800, (None, True): 700, (200, False): 300, (200, True): 450})
        self.assertEqual(len(review_page.to_webp(src, {"quality": 70, "max_width": 200}, ("magick", "m"))), 300)

    def test_never_tries_a_width_at_or_above_the_screenshot(self):
        calls = self.stub_encoder({(None, False): 10, (None, True): 10})
        review_page.to_webp(self.tmp / "shot.png", {"quality": 70, "max_width": 4000}, ("magick", "m"))
        self.assertEqual(sorted(calls, key=str), [(None, False), (None, True)])

    def test_size_warning_names_the_largest_assets(self):
        spec = {"_assets": {"big": {"img": "x" * 3000000, "webp": "w" * 1000000}, "small": {"img": "y" * 10, "webp": None}}}
        line = review_page.size_warning("z" * (4 * 1024 * 1024), spec)
        self.assertIn("big (3906 KB)", line)
        self.assertIsNone(review_page.size_warning("z" * 1000, spec))


LAUNCH = RP / "launch.cjs"
LAUNCH_DRIVER = r"""
const { launchChromium, CHROME_ARGS } = require(process.argv[1]);
const script = JSON.parse(process.argv[2]);
const env = JSON.parse(process.argv[3]);
const calls = [];
const chromium = { launch: async (opts) => {
  calls.push(opts);
  const step = script[calls.length - 1];
  if (step) throw new Error(step);
  return { fake: true };
} };
launchChromium(chromium, env).then(
  (b) => console.log(JSON.stringify({ ok: !!b.fake, calls, args: CHROME_ARGS })),
  (e) => console.log(JSON.stringify({ ok: false, message: e.message, calls })));
"""
FLAG = "--disable-features=MacAppCodeSignClone"


@unittest.skipUnless(NODE, "node not found")
class Paths(unittest.TestCase):
    """Django run 2: asset paths written from the project folder, and a session page
    saved outside .proofs/pages/ where the open rule could not reach it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve()
        (self.tmp / ".proofs" / "review").mkdir(parents=True)
        (self.tmp / "baseline-screens").mkdir()
        write_png(self.tmp / "baseline-screens" / "home-1440.png", 40, 30)

    def run_build(self, *args):
        return subprocess.run([sys.executable, str(BUILD), *args, "--no-check"],
                              capture_output=True, text=True, cwd=self.tmp)

    def review_spec(self, rel):
        s = {"mode": "review", "title": "Paths — Design Review", "decisions": "design-review",
             "assets": {"home1440": rel},
             "sections": [{"title": "S", "items": [{"label": "x", "recommended": True,
                                                    "body_html": '<img alt="a" src="{{asset:home1440}}">',
                                                    "reason_html": "<p>r</p>"}]}]}
        p = self.tmp / ".proofs" / "review" / "spec.json"
        p.write_text(json.dumps(s))
        return p

    def test_asset_falls_back_to_the_working_directory(self):
        spec = self.review_spec("baseline-screens/home-1440.png")
        r = self.run_build(str(spec), "--out", ".proofs/pages/review.html")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("data:image/", (self.tmp / ".proofs" / "pages" / "review.html").read_text())

    def test_asset_next_to_the_spec_still_wins(self):
        write_png(self.tmp / ".proofs" / "review" / "home.png", 40, 30)
        spec = self.review_spec("home.png")
        r = self.run_build(str(spec), "--out", ".proofs/pages/review.html")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_missing_asset_error_names_both_paths_tried(self):
        spec = self.review_spec("baseline-screens/nope.png")
        r = self.run_build(str(spec), "--out", ".proofs/pages/review.html")
        self.assertEqual(r.returncode, 1)
        self.assertIn("asset 'home1440' not found", r.stderr)
        self.assertIn(str(self.tmp / ".proofs" / "review" / "baseline-screens" / "nope.png"), r.stderr)
        self.assertIn(str(self.tmp / "baseline-screens" / "nope.png"), r.stderr)

    def file_spec(self, rel):
        # Vue run 1 (B1): "@file:.proofs/design-review/mock.css", written from the project folder.
        s = {"mode": "review", "title": "Paths — Design Review", "decisions": "design-review", "css": "@file:" + rel,
             "sections": [{"title": "S", "items": [{"label": "x", "recommended": True, "reason_html": "<p>r</p>"}]}]}
        p = self.tmp / ".proofs" / "review" / "spec.json"
        p.write_text(json.dumps(s))
        return p

    def test_at_file_falls_back_to_the_working_directory(self):
        (self.tmp / ".proofs" / "review" / "mock.css").write_text(".from-spec-folder{}")
        (self.tmp / ".proofs" / "mock.css").write_text(".from-project-folder{}")
        spec = self.file_spec(".proofs/mock.css")
        r = self.run_build(str(spec), "--out", ".proofs/pages/review.html")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(".from-project-folder{}", (self.tmp / ".proofs" / "pages" / "review.html").read_text())

    def test_at_file_next_to_the_spec_still_wins(self):
        (self.tmp / ".proofs" / "review" / "mock.css").write_text(".from-spec-folder{}")
        (self.tmp / "mock.css").write_text(".from-project-folder{}")
        r = self.run_build(str(self.file_spec("mock.css")), "--out", ".proofs/pages/review.html")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        html = (self.tmp / ".proofs" / "pages" / "review.html").read_text()
        self.assertIn(".from-spec-folder{}", html)
        self.assertNotIn(".from-project-folder{}", html)

    def test_missing_at_file_error_names_both_paths_tried(self):
        r = self.run_build(str(self.file_spec("styles/nope.css")), "--out", ".proofs/pages/review.html")
        self.assertEqual(r.returncode, 1)
        self.assertIn("@file not found: styles/nope.css", r.stderr)
        self.assertIn(str(self.tmp / ".proofs" / "review" / "styles" / "nope.css"), r.stderr)
        self.assertIn(str(self.tmp / "styles" / "nope.css"), r.stderr)

    def test_session_page_with_no_out_goes_under_proofs_pages(self):
        shutil.copy(EXAMPLES / "session.json", self.tmp / ".proofs" / "session.json")
        r = self.run_build(".proofs/session.json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((self.tmp / ".proofs" / "pages" / "session.html").is_file())
        self.assertIn(".proofs/pages/session.html", r.stdout)

    def test_log_page_with_no_out_goes_under_proofs_pages(self):
        shutil.copy(EXAMPLES / "log.json", self.tmp / "my-log.json")
        r = self.run_build("my-log.json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((self.tmp / ".proofs" / "pages" / "my-log.html").is_file())

    def test_review_page_still_needs_out(self):
        spec = self.review_spec("baseline-screens/home-1440.png")
        r = self.run_build(str(spec))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--out", r.stderr)
        self.assertFalse((self.tmp / ".proofs" / "pages").exists())


class BrowserLaunch(unittest.TestCase):
    def run_launch(self, script, env=None):
        r = subprocess.run([NODE, "-e", LAUNCH_DRIVER, str(LAUNCH), json.dumps(script), json.dumps(env or {})],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_launch_uses_bundled_browser_first_with_the_flag(self):
        res = self.run_launch([None])
        self.assertTrue(res["ok"])
        self.assertEqual(len(res["calls"]), 1)
        self.assertEqual(res["calls"][0]["args"], [FLAG])
        self.assertNotIn("channel", res["calls"][0])

    def test_launch_falls_back_to_installed_chrome(self):
        res = self.run_launch(["browserType.launch: Executable doesn't exist at /x", None])
        self.assertTrue(res["ok"])
        self.assertEqual(len(res["calls"]), 2)
        self.assertEqual(res["calls"][1]["channel"], "chrome")
        self.assertEqual(res["calls"][1]["args"], [FLAG])

    def test_channel_env_forces_one_launch(self):
        res = self.run_launch([None], {"PROOFS_BROWSER_CHANNEL": "chrome"})
        self.assertEqual(len(res["calls"]), 1)
        self.assertEqual(res["calls"][0]["channel"], "chrome")
        self.assertEqual(res["calls"][0]["args"], [FLAG])

    def test_other_launch_errors_are_not_retried(self):
        res = self.run_launch(["spawn EACCES"])
        self.assertFalse(res["ok"])
        self.assertEqual(len(res["calls"]), 1)

    def test_launch_reports_how_to_get_a_browser_when_both_fail(self):
        res = self.run_launch(["Executable doesn't exist at /x", "Chromium distribution 'chrome' is not found"])
        self.assertFalse(res["ok"])
        self.assertIn("npm install --prefix ~/.cache/proofs-playwright", res["message"])
        self.assertIn("Install Google Chrome", res["message"])

    def test_find_playwright_checks_the_proofs_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp) / ".cache" / "proofs-playwright" / "node_modules" / "playwright"
            pkg.mkdir(parents=True)
            (pkg / "package.json").write_text("{}")
            old = {k: os.environ.get(k) for k in ("HOME", "PROOFS_PLAYWRIGHT")}
            os.environ["HOME"] = tmp
            os.environ.pop("PROOFS_PLAYWRIGHT", None)
            try:
                self.assertEqual(review_page.find_playwright(None), str(pkg.resolve()))
            finally:
                for k, v in old.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v

    def test_smoke_without_playwright_says_how_to_get_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = {k: os.environ.get(k) for k in ("HOME", "PROOFS_PLAYWRIGHT")}
            cwd = os.getcwd()
            os.environ["HOME"] = tmp
            os.environ.pop("PROOFS_PLAYWRIGHT", None)
            os.chdir(tmp)
            try:
                ok, res = review_page.smoke(str(Path(tmp) / "x.html"))
            finally:
                os.chdir(cwd)
                for k, v in old.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
            self.assertIsNone(ok)
            self.assertIn("npm install --prefix ~/.cache/proofs-playwright", res["error"])


class Spelling(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self._old = os.environ.get("PROOFS_SPELLING")
        os.environ["PROOFS_SPELLING"] = "american"
        self.addCleanup(self._restore)

    def _restore(self):
        if self._old is None:
            os.environ.pop("PROOFS_SPELLING", None)
        else:
            os.environ["PROOFS_SPELLING"] = self._old

    def page(self, mutate):
        spec = json.loads((EXAMPLES / "log.json").read_text())
        mutate(spec)
        shutil.copy(EXAMPLES / "sample.png", self.tmp / "sample.png")
        src = self.tmp / "spec.json"
        src.write_text(json.dumps(spec))
        out = self.tmp / "page.html"
        r = subprocess.run([sys.executable, str(BUILD), str(src), "--out", str(out)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return out

    def spelling(self, page):
        return [w for w in review_page.warnings(page) if "british spelling" in w]

    def test_british_word_in_an_entry_warns(self):
        page = self.page(lambda s: s["entries"][1].update(lede="the old behaviour"))
        self.assertEqual(self.spelling(page),
                         ['british spelling "behaviour" (American: "behavior") in M5'])

    def test_spelling_ignores_css_urls_and_assets(self):
        def mutate(s):
            s["css"] = ".grey-card{}"
            s["entries"][1]["detail_html"] = '<p><a href="/colour-guide">guide</a> <code>centre</code></p>'
            s["assets"] = {"centre.png": "sample.png"}
        self.assertEqual(self.spelling(self.page(mutate)), [])

    def test_alt_and_title_text_is_scanned(self):
        page = self.page(lambda s: s["entries"][1].update(
            detail_html='<p><img alt="a grey box" src="sample.png"> <span title="the centre">x</span></p>'))
        found = " ".join(self.spelling(page))
        self.assertIn('"grey"', found)
        self.assertIn('"centre"', found)

    def test_analyses_is_not_flagged(self):
        page = self.page(lambda s: s["entries"][1].update(lede="two analyses"))
        self.assertEqual(self.spelling(page), [])

    def test_spelling_is_off_by_default(self):
        page = self.page(lambda s: s["entries"][1].update(lede="the old behaviour"))
        for val in (None, "off", "british"):
            if val is None:
                os.environ.pop("PROOFS_SPELLING", None)
            else:
                os.environ["PROOFS_SPELLING"] = val
            self.assertEqual(self.spelling(page), [], val)

    def test_spelling_opt_in(self):
        page = self.page(lambda s: s["entries"][1].update(lede="organisation and colours"))
        found = self.spelling(page)
        self.assertEqual(len(found), 2, found)
        self.assertIn('(American: "organization")', found[0] + found[1])

    def test_examples_have_no_british_spelling(self):
        for spec in sorted(EXAMPLES.glob("*.json")):
            self.assertEqual(self.spelling(build(spec.stem, self.tmp)), [], spec.name)



def playwright_dir():
    return review_page.find_playwright(None)


@unittest.skipUnless(NODE and playwright_dir(), "Playwright not found: set PROOFS_PLAYWRIGHT, or install it where "
                     "the builder looks (~/.cache/proofs-playwright) with no browser download: "
                     "npm install --prefix ~/.cache/proofs-playwright playwright@1.61.1")
class ClickThrough(unittest.TestCase):
    """Drive every example in real Chromium: decisions, variants, comments, read
    switch, export, reload persistence, clipboard fallback, images, no sideways scroll."""

    def test_every_example(self):
        with tempfile.TemporaryDirectory() as tmp:
            for spec in sorted(EXAMPLES.glob("*.json")):
                page = build(spec.stem, tmp)
                ok, res = review_page.smoke(page)
                self.assertTrue(ok, "%s: %s" % (spec.name, res))

    def test_smoke_names_the_variant_whose_mockup_breaks_a_word(self):
        # Rails run 1: design-review's feature cards broke "authenticat / ion" and only pr-qa
        # noticed. The smoke check now runs the same mid-word measure on every mockup.
        spec = {"title": "Cards", "project": {"name": "P", "session": "s"}, "decisions": "design-review",
                "items": [{"label": "Feature cards", "reason_html": "<p>r</p>", "recommended": True, "variants": [
                    {"html": '<div style="width:300px;font:20px sans-serif"><h4>Devise authentication</h4></div>'},
                    {"html": '<div style="width:120px;font:20px sans-serif"><h4 style="overflow-wrap:anywhere;font-size:20px">'
                             'Devise authentication</h4><p style="width:70px">Role-based</p></div>'}]}]}
        with tempfile.TemporaryDirectory() as tmp:
            src, out = Path(tmp) / "s.json", Path(tmp) / "p.html"
            src.write_text(json.dumps(spec))
            r = subprocess.run([sys.executable, str(BUILD), str(src), "--out", str(out)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            ok, res = review_page.smoke(out)
            self.assertFalse(ok, res)
            broken = [p for p in res["problems"] if "mid-word" in p]
            self.assertEqual(len(broken), 1, res["problems"])
            self.assertIn('item 1 (Feature cards), Variant B: "authentic', broken[0])
            self.assertIn("breaks mid-word", broken[0])
            self.assertEqual(res["mid_word"][0]["variant"], "B")

    def test_smoke_reports_each_mockups_box_width_and_stack_variants_widens_it(self):
        # SvelteKit run 1: two variants side by side left each desktop mockup about 490 px at a
        # 1280 px window, so its desktop layout collapsed; the session spent four rebuild-and-
        # capture rounds overriding .rp-gallery and .rp-panes to find that out.
        def item(label, stack):
            it = {"label": label, "reason_html": "<p>r</p>", "recommended": True, "variants": [
                {"html": "<div>A</div>"}, {"html": "<div>B</div>"}]}
            if stack:
                it["stack_variants"] = True
            return it
        spec = {"title": "Widths", "project": {"name": "P", "session": "s"}, "decisions": "design-review",
                "items": [item("Side by side", False), item("Stacked", True)]}
        with tempfile.TemporaryDirectory() as tmp:
            src, out = Path(tmp) / "s.json", Path(tmp) / "p.html"
            src.write_text(json.dumps(spec))
            r = subprocess.run([sys.executable, str(BUILD), str(src), "--out", str(out)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            ok, res = review_page.smoke(out)
            self.assertTrue(ok, res)
            widths = {(w["item"], w["variant"]): w["width"] for w in res["mockup_widths"]}
            self.assertLess(widths[("1", "A")], 700, res["mockup_widths"])
            self.assertGreater(widths[("2", "A")], 900, res["mockup_widths"])
            self.assertGreater(widths[("2", "B")], 900, res["mockup_widths"])

    def test_design_review_export_after_clicks(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok, res = review_page.smoke(build("design-review", tmp))
            self.assertTrue(ok, res)
            self.assertEqual(res["export"], "[Articles Index — Design Review]\n"
                                            "1. Article card layout — REVISE — READ — COMMENT: smoke comment\n"
                                            "2. Read More button placement — PENDING")



READ_JUMP = r"""
const { chromium } = require(process.argv[2]);
const { launchChromium } = require(process.argv[3]);
(async () => {
  const browser = await launchChromium(chromium, process.env);
  const out = {};
  for (const motion of ["reduce", "no-preference"]) {
    const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true,
                                           deviceScaleFactor: 2, reducedMotion: motion });
    const page = await ctx.newPage();
    await page.goto("file://" + process.argv[4]);
    const settle = () => page.waitForTimeout(motion === "reduce" ? 80 : 900);
    const bars = () => page.evaluate(() => document.querySelector(".rp-topbars").getBoundingClientRect().bottom);
    const top = (id) => page.evaluate((i) => document.querySelector('[data-entry="' + i + '"]').getBoundingClientRect().top, id);
    const tick = (id) => page.evaluate((i) => { const t = document.querySelector('[data-tick="' + i + '"]'); t.click(); }, id);
    // Scroll into the middle of entry 3, then tick it.
    await page.evaluate(() => { const e = document.querySelector('[data-entry="E3"]');
      window.scrollTo({ top: window.scrollY + e.getBoundingClientRect().top + e.offsetHeight / 2 - 300, behavior: "instant" }); });
    await page.waitForTimeout(50);
    await tick("E3"); await settle();
    const r = { afterTick: { next: await top("E4"), bars: await bars() } };
    // Untick E3 from the Read list: it comes back, and its top stays where it was just before.
    await page.evaluate(() => { const e = document.querySelector('[data-entry="E3"]');
      window.scrollTo({ top: window.scrollY + e.getBoundingClientRect().top - 400, behavior: "instant" }); });
    await page.waitForTimeout(50);
    const before = await top("E3");
    await tick("E3"); await settle();
    r.untick = { before, after: await top("E3") };
    // Tick everything but E10, then from E10's middle tick E10: nothing unread is left.
    for (let i = 1; i <= 9; i++) { await tick("E" + i); }
    await settle();
    await page.evaluate(() => { const e = document.querySelector('[data-entry="E10"]');
      window.scrollTo({ top: window.scrollY + e.getBoundingClientRect().top + 400, behavior: "instant" }); });
    await page.waitForTimeout(50);
    const y0 = await page.evaluate(() => window.scrollY);
    await tick("E10"); await settle();
    r.last = { y0, y1: await page.evaluate(() => window.scrollY),
               maxY: await page.evaluate(() => document.documentElement.scrollHeight - window.innerHeight) };
    if (y0 < 100) throw new Error("the last-entry case never scrolled: y0 " + y0);
    // Untick E2 and E5 (unread again), then tick E9's neighbor E10 is read; tick E5 from the bottom:
    // nothing unread below it, so it goes to the first unread one above (E2).
    await tick("E2"); await tick("E5"); await settle();
    await tick("E5"); await settle();
    r.above = { e2: await top("E2"), bars: await bars() };
    out[motion] = r;
    await ctx.close();
  }
  await browser.close();
  console.log(JSON.stringify(out));
})().catch((e) => { console.log(JSON.stringify({ crash: String(e && e.stack || e) })); process.exit(1); });
"""


@unittest.skipUnless(NODE and playwright_dir(), "Playwright not found")
class ReadTickScroll(unittest.TestCase):
    """Found on a phone: ticking "Read this" folds the entry and moves it to the Read list,
    and the page jumped somewhere unrelated. Now the next unread entry's top lands just under
    the sticky bars; unticking keeps the entry where it was."""

    def test_tick_lands_on_the_next_unread_entry(self):
        long = "<p>" + ("A long paragraph of working-log detail that goes on for a while. " * 30) + "</p>"
        entries = [{"id": "E%d" % i, "title": "Entry %d" % i, "status": "FYI", "when": "2026-11-24T10:%02d" % i,
                    "lede": "Lede %d" % i, "detail_html": long} for i in range(1, 11)]
        spec = {"mode": "log", "title": "s · P log", "project": {"name": "P", "session": "s", "repo": "a/b"},
                "heading": "Working log", "entries": entries}
        with tempfile.TemporaryDirectory() as tmp:
            src, out = Path(tmp) / "s.json", Path(tmp) / "p.html"
            src.write_text(json.dumps(spec))
            r = subprocess.run([sys.executable, str(BUILD), str(src), "--out", str(out)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            script = Path(tmp) / "jump.cjs"
            script.write_text(READ_JUMP)
            r = subprocess.run([NODE, str(script), playwright_dir(), str(RP / "launch.cjs"), str(out)],
                               capture_output=True, text=True, timeout=180)
            res = json.loads(r.stdout.strip().splitlines()[-1])
            self.assertNotIn("crash", res, res)
            for motion, m in res.items():
                with self.subTest(motion=motion):
                    gap = m["afterTick"]["next"] - m["afterTick"]["bars"]
                    self.assertTrue(0 <= gap <= 12, m)
                    self.assertLess(abs(m["untick"]["after"] - m["untick"]["before"]), 3, m)
                    # Left alone: the same scroll, unless the shorter page clamps it.
                    self.assertLess(abs(m["last"]["y1"] - min(m["last"]["y0"], m["last"]["maxY"])), 3, m)
                    gap = m["above"]["e2"] - m["above"]["bars"]
                    self.assertTrue(0 <= gap <= 12, m)

if __name__ == "__main__":
    unittest.main()
