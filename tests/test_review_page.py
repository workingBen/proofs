"""Tests for shared/review_page: build every example, check it, and pin the export text.

The export tests run the page's own engine under plain node (no DOM), so they need
node but not a browser. The click-through test needs Playwright: set
PROOFS_PLAYWRIGHT to an installed playwright package folder, or it is skipped.
"""
import base64
import contextlib
import html
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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


@contextlib.contextmanager
def project_with(values):
    """A temp project whose .claude/settings.json sets `values`, entered as the working folder,
    with an empty home and no PROOFS_ variables, so only the file speaks."""
    with tempfile.TemporaryDirectory() as tmp:
        proj, home = Path(tmp).resolve() / "proj", Path(tmp).resolve() / "home"
        (proj / ".claude").mkdir(parents=True)
        home.mkdir()
        (proj / ".claude" / "settings.json").write_text(json.dumps({"env": values}))
        keep = {k: v for k, v in os.environ.items() if not k.startswith("PROOFS_")}
        keep.update(HOME=str(home), CLAUDE_CONFIG_DIR=str(home / ".claude"))
        old = os.getcwd()
        os.chdir(proj)
        try:
            with mock.patch.dict(os.environ, keep, clear=True):
                yield proj
        finally:
            os.chdir(old)


IMAGE_DEFAULTS = {r["key"]: r["default"] for r in json.loads((Path(__file__).resolve().parent.parent / "shared" / "settings.json").read_text())}


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

    def test_a_text_box_question_counts_its_typed_text_as_the_answer(self):
        # Astro run 2: a question with no options and a notes_label shows only a text box,
        # and its typed text went out as "(UNANSWERED)" plus a note.
        spec = {"mode": "questions", "title": "T", "project": {"name": "P", "stream": "s", "round": 1},
                "questions": [{"qid": "why", "ask": "Why?", "options": [], "notes_label": "Your answer"},
                              {"qid": "pick", "ask": "Pick", "options": [{"label": "A"}, {"label": "B"}]}]}
        src = Path(self._tmp.name) / "text-q.json"
        src.write_text(json.dumps(spec))
        page = Path(self._tmp.name) / "text-q.html"
        r = subprocess.run([sys.executable, str(BUILD), str(src), "--out", str(page)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = subprocess.run([NODE, str(self.driver), str(page), json.dumps({"notes": {"why": "because\nit is", "pick": "x"}})],
                           capture_output=True, text=True, env=dict(os.environ, TZ="UTC"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Q why (raised r1) | Why?\n  -> because\n     it is\n\n", r.stdout)
        self.assertIn("Q pick (raised r1) | Pick\n  -> (UNANSWERED)\n  note: x\n", r.stdout)

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


REFINE = ROOT / "tests" / "fixtures" / "review_page" / "refine"
RC = 'html[data-rc~="x"] '


class Refine(unittest.TestCase):
    """design-review's Refine mode: one `refine` item, a base snapshot and a list of changes,
    each its own card and export line, then a `Combined:` line (spec §3 and §4)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name) / "refine"
        shutil.copytree(REFINE, self.dir)
        self.driver = Path(self._tmp.name) / "driver.cjs"
        self.driver.write_text(DRIVER)

    def spec(self):
        return json.loads((REFINE / "spec.json").read_text())

    @staticmethod
    def item(spec):
        return spec["sections"][0]["items"][0]

    def load(self, spec):
        p = self.dir / "s.json"
        p.write_text(json.dumps(spec))
        return review_page.load_spec(p)

    def html(self, spec=None):
        return review_page.page(self.load(spec or self.spec()))

    def error(self, spec):
        with self.assertRaises(review_page.SpecError) as cm:
            self.html(spec)
        return str(cm.exception)

    def built(self, spec=None):
        out = Path(self._tmp.name) / "page.html"
        out.write_text(self.html(spec))
        return out

    def export(self, state, spec=None):
        r = subprocess.run([NODE, str(self.driver), str(self.built(spec)), json.dumps({"items": state})],
                           capture_output=True, text=True, env=dict(os.environ, TZ="UTC"))
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def frames(self, text):
        """Each frame's width and the document the engine gives it: the page's one embedded
        copy of the snapshot (the frames carry no srcdoc of their own)."""
        widths = re.findall(r'<iframe class="rp-rc-frame" data-rc-width="(\d+)"', text)
        m = re.search(r'<script type="application/json" id="rp-rc-base-home">(.*?)</script>', text, re.S)
        self.assertTrue(m, "no embedded snapshot")
        return [(w, json.loads(m.group(1))) for w in widths]

    def card(self, text, cid):
        m = re.search(r'<article class="rp-item"[^>]*data-rc-change="%s".*?</article>' % re.escape(cid), text, re.S)
        self.assertTrue(m, "no card for change %s" % cid)
        return m.group(0)

    @unittest.skipUnless(NODE, "node is not installed")
    def test_refine_export_lists_each_change_and_the_combined_line(self):
        text = self.export({"bold-totals": {"s": "accept"}, "tight-rows": {"s": "deny"}, "alert-color": {"s": "accept"}})
        self.assertEqual(text, "[Host Headroom dashboard — Design Review (Refine)]\n"
                               "1. Bolder totals — YES\n"
                               "2. Tighter row spacing — NO\n"
                               "3. Status color on the alert column — YES\n"
                               "Combined: 1, 3")
        text = self.export({"alert-color": {"s": "revise", "c": "amber,\nnot red"}})
        self.assertEqual(text, "[Host Headroom dashboard — Design Review (Refine)]\n"
                               "1. Bolder totals — PENDING\n"
                               "2. Tighter row spacing — PENDING\n"
                               "3. Status color on the alert column — REVISE — COMMENT: amber, not red\n"
                               "Combined: none")

    def test_refine_preset_buttons_and_skill(self):
        self.assertEqual(review_page.PRESETS["refine"]["buttons"], [
            {"state": "accept", "label": "✓ Yes", "export": "YES"},
            {"state": "deny", "label": "✕ No", "export": "NO"},
            {"state": "revise", "label": "↻ Revise", "export": "REVISE", "comment": "required"}])
        self.assertEqual(review_page.PRESETS["refine"]["pending"], "PENDING")
        self.assertEqual(review_page.PRESET_SKILLS["refine"], "design-review")
        text = self.html()
        self.assertIn('<span class="rp-sk" aria-hidden="true">design-review</span>', text)
        card = self.card(text, "tight-rows")
        for label in ("✓ Yes", "✕ No", "↻ Revise"):
            self.assertIn(">%s</button>" % label, card)

    def test_refine_scopes_every_selector_of_a_comma_list(self):
        scope = review_page.scope_css
        self.assertEqual(scope(".a, .b > c { color: red }", "x"), RC + ".a, " + RC + ".b > c { color: red }")
        media = scope("@media (max-width: 600px) { .a, .b { margin: 0 } .c { padding: 0 } }", "x")
        self.assertEqual(media, "@media (max-width: 600px) { " + RC + ".a, " + RC + ".b { margin: 0 }\n"
                                + RC + ".c { padding: 0 } }")
        for verbatim in ("@font-face { font-family: X; src: url(a.woff2) format(\"woff2\") }",
                         "@keyframes spin { from { opacity: 0 } to { opacity: 1 } }",
                         "@import url(\"x.css\");"):
            self.assertEqual(scope(verbatim, "x"), verbatim)
        # A comma inside :is(), an attribute value or a string is not a selector list.
        self.assertEqual(scope(':is(.a, .b) [title="p, q"] { content: "}, {" }', "x"),
                         RC + ':is(.a, .b) [title="p, q"] { content: "}, {" }')
        # html and :root are the frame's own root: the attribute goes on them, not above them.
        self.assertEqual(scope("html.dark .a, :root { --gap: 4px }", "x"),
                         'html[data-rc~="x"].dark .a, html[data-rc~="x"] { --gap: 4px }')
        self.assertEqual(scope("/* note */ .a { color: red } /* end */", "x"), RC + ".a { color: red }")
        with self.assertRaises(review_page.SpecError):
            scope(".a { color: red", "x")

    def test_refine_scope_css_keeps_escaped_selectors_whole(self):
        # Tailwind-style escapes: an escaped comma is not a list, an escaped quote opens no string.
        scope = review_page.scope_css
        self.assertEqual(scope(".a\\,b { color: red }", "x"), RC + ".a\\,b { color: red }")
        self.assertEqual(scope('.x\\:\\"q { color: red }', "x"), RC + '.x\\:\\"q { color: red }')
        self.assertEqual(scope(".md\\:flex, .w-1\\/2 { display: flex }", "x"),
                         RC + ".md\\:flex, " + RC + ".w-1\\/2 { display: flex }")

    def test_refine_scope_css_leaves_whitespace_in_strings_alone(self):
        self.assertEqual(review_page.scope_css('.a  /* c */  [title="a  b"]\n.c { color: red }', "x"),
                         RC + '.a [title="a  b"] .c { color: red }')

    def test_refine_scope_css_scopes_starting_style_and_refuses_scope(self):
        self.assertEqual(review_page.scope_css("@starting-style { .a { opacity: 0 } }", "x"),
                         "@starting-style { " + RC + ".a { opacity: 0 } }")
        with self.assertRaises(review_page.SpecError) as cm:
            review_page.scope_css("@scope (.card) { .a { color: red } }", "x")
        self.assertIn("cannot use @scope", str(cm.exception))

    def test_refine_css_goes_in_one_style_inside_the_snapshot(self):
        frames = self.frames(self.html())
        self.assertEqual([w for w, _ in frames], ["1280", "390"])
        for _, doc in frames:
            self.assertEqual(doc.count("<style data-rc-css>"), 1)
            css = doc[doc.index("<style data-rc-css>"):]
            css = css[:css.index("</style>")]
            self.assertIn('html[data-rc~="bold-totals"] .total { font-weight: 700; }', css)
            self.assertIn('html[data-rc~="alert-color"] .badge { display: none; }', css)
            # After the page's own sheet, so an equal rule still wins, and in its <head>.
            self.assertLess(doc.index(".total { font-weight:400; }"), doc.index("<style data-rc-css>"))
            self.assertLess(doc.index("<style data-rc-css>"), doc.index("</head>"))
            self.assertIn('<template data-rc-swap="alert-color" data-rc-target=".status-icon">'
                          '<i class="status-icon">▲</i></template>', doc)

    def test_refine_base_outside_the_project_publishes_only_its_file_name(self):
        # The tests run from the repo; the snapshot is in a temp folder, outside it.
        text = self.html()
        self.assertIn('data-rc-base="home-snapshot.html"', text)
        self.assertNotIn(str(Path(self._tmp.name).resolve().parent), text)
        self.assertNotIn('data-rc-base="..', text)

    def test_refine_embeds_the_snapshot_assets(self):
        for _, doc in self.frames(self.html()):
            self.assertNotIn("home-snapshot-assets/", doc)
            self.assertIn('url("data:image/svg+xml;base64,', doc)
            self.assertRegex(doc, r'<img class="photo" src="data:image/(png|webp|jpeg);base64,')

    def test_refine_embeds_color_managed_pngs_untouched(self):
        """Lossless WebP keeps the pixel values but not a PNG's gAMA (ImageMagick rewrites the
        values, Chrome then draws them differently) or its ICC profile (cwebp drops it): measured
        in Chrome, 99.8% and 48% of pixels changed. Such a PNG goes in as it is, so the base
        still matches the page pixel for pixel."""
        import struct
        import zlib
        def chunk(k, b):
            return struct.pack(">I", len(b)) + k + b + struct.pack(">I", zlib.crc32(k + b) & 0xFFFFFFFF)
        rows = b"".join(b"\0" + bytes((x * 37 + y * 11) % 256 for x in range(8 * 3)) for y in range(8))
        ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0))
        tail = chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")
        sig = b"\x89PNG\r\n\x1a\n"
        assets = self.dir / "before" / "home-snapshot-assets"
        for extra in (chunk(b"gAMA", struct.pack(">I", 100000)), chunk(b"iCCP", b"p\0\0" + zlib.compress(b"x" * 64))):
            png = sig + ihdr + extra + tail
            (assets / "3f2a9c81d0-photo.png").write_bytes(png)
            with mock.patch.object(review_page, "image_tool", return_value=("magick", "/bin/false")), \
                    mock.patch.object(review_page, "encode_webp", return_value=b"RIFF") as enc:
                for _, doc in self.frames(self.html()):
                    self.assertIn('src="data:image/png;base64,%s"' % base64.b64encode(png).decode(), doc)
            enc.assert_not_called()
        # A plain 8-bit PNG still becomes lossless WebP when that is smaller.
        (assets / "3f2a9c81d0-photo.png").write_bytes(sig + ihdr + tail)
        with mock.patch.object(review_page, "image_tool", return_value=("magick", "/bin/false")), \
                mock.patch.object(review_page, "encode_webp", return_value=b"RIFF") as enc:
            doc = self.frames(self.html())[0][1]
        self.assertIn('src="data:image/webp;base64,UklGRg=="', doc)
        enc.assert_called_once()

    @unittest.skipUnless(NODE, "node is not installed")
    def test_refine_srcdoc_survives_quotes_and_script_text(self):
        page = self.built()
        self.assertEqual(review_page.check(page), [])
        text = page.read_text()
        self.assertNotIn("srcdoc=", text)
        raw = re.search(r'<script type="application/json" id="rp-rc-base-home">(.*?)</script>', text, re.S).group(1)
        self.assertNotIn("<", raw)
        self.assertEqual(len(review_page.SCRIPT_RX.findall(text)), 1)
        for _, doc in self.frames(text):
            self.assertIn('print("&lt;/script&gt;") # it\'s "quoted"</pre>', doc)
            self.assertIn('title="a &quot;quoted&quot; title with </script> in it"', doc)

    @unittest.skipUnless(NODE, "node is not installed")
    def test_refine_snapshot_is_embedded_once(self):
        page = self.built()
        text = page.read_text()
        # Text only the snapshot has, and one of its inlined assets: each once on the page.
        self.assertEqual(text.count("web-2"), 1)
        self.assertEqual(text.count("print("), 1)
        self.assertEqual(text.count('url(\\"data:image/svg+xml;base64,'), 1)
        self.assertEqual(review_page.check(page), [])
        # A page whose embedded snapshot is not JSON fails the check.
        page.write_text(text.replace('id="rp-rc-base-home">"', 'id="rp-rc-base-home">{', 1))
        self.assertIn("rp-rc-base-home is not valid JSON", "\n".join(review_page.check(page)))

    def test_refine_rejects_more_than_eight_changes(self):
        spec = self.spec()
        base = self.item(spec)["changes"][1]
        self.item(spec)["changes"] = [dict(base, id="c%d" % i) for i in range(9)]
        msg = self.error(spec)
        self.assertIn("9 changes", msg)
        self.assertIn("1 to 8", msg)

    def test_refine_rejects_fewer_than_one(self):
        spec = self.spec()
        self.item(spec)["changes"] = []
        msg = self.error(spec)
        self.assertIn("0 changes", msg)
        self.assertIn("1 to 8", msg)

    def test_refine_rejects_duplicate_change_ids(self):
        spec = self.spec()
        self.item(spec)["changes"][2]["id"] = "bold-totals"
        self.assertIn("unique on the page (got 'bold-totals')", self.error(spec))
        spec = self.spec()
        self.item(spec)["changes"][2]["id"] = "home"
        self.assertIn("unique on the page (got 'home')", self.error(spec))
        spec = self.spec()
        self.item(spec)["changes"][2]["id"] = "Alert_Color"
        self.assertIn("[a-z0-9-]+", self.error(spec))

    def test_refine_rejects_a_change_with_no_targets(self):
        for targets in (None, [], [""], ".total"):
            spec = self.spec()
            ch = self.item(spec)["changes"][0]
            if targets is None:
                ch.pop("targets")
            else:
                ch["targets"] = targets
            self.assertIn("change bold-totals: targets", self.error(spec), targets)

    def test_refine_rejects_scores_out_of_range(self):
        for scores, word in (({"gain": 6, "keeps": 4}, "gain must be a whole number from 1 to 5"),
                             ({"gain": 0, "keeps": 4}, "gain must be a whole number from 1 to 5"),
                             ({"gain": 3, "keeps": True}, "keeps must be a whole number from 1 to 5"),
                             ({"gain": 3, "hierarchy": 4}, "unknown score 'hierarchy' (use gain, keeps)")):
            spec = self.spec()
            self.item(spec)["changes"][0]["scores"] = scores
            self.assertIn(word, self.error(spec))

    def test_refine_rejects_missing_fields_and_bad_shapes(self):
        cases = (("label", None, "change bold-totals needs a label"),
                 ("why_html", None, "change bold-totals needs why_html"),
                 ("css", None, "change bold-totals needs css"),
                 ("css", ".a { color: red } </style>", "</style>"),
                 ("swaps", [{"selector": ".a"}], "every swap needs a selector and html"),
                 ("swaps", [{"selector": ".a", "html": "<p></template></p>"}], "</template>"),
                 ("removes", [{"element": "badge"}], "every removes line needs an element and a reason"))
        for key, value, word in cases:
            spec = self.spec()
            ch = self.item(spec)["changes"][0]
            if value is None:
                ch.pop(key)
            else:
                ch[key] = value
            self.assertIn(word, self.error(spec), key)

    def test_refine_hiding_an_element_needs_a_removes_line(self):
        spec = self.spec()
        self.item(spec)["changes"][2].pop("removes")
        self.assertIn("change alert-color hides an element (display: none) but has no removes line", self.error(spec))

    def test_refine_a_swap_needs_a_removes_line(self):
        spec = self.spec()
        self.item(spec)["changes"][1]["swaps"] = [{"selector": ".badge", "html": "<span class=\"badge\">NEW</span>"}]
        self.assertIn("change tight-rows swaps an element but has no removes line", self.error(spec))

    def test_refine_display_none_in_a_comment_needs_no_removes_line(self):
        spec = self.spec()
        self.item(spec)["changes"][1]["css"] = ".rows td { padding: 6px 8px; } /* not display: none */"
        self.assertIn("Tighter row spacing", self.html(spec))

    def test_refine_base_must_name_a_snapshot_that_exists(self):
        spec = self.spec()
        self.item(spec)["base"] = "before/home-snapshot.html"
        self.assertIn('base must be {"from": ', self.error(spec))
        spec = self.spec()
        self.item(spec)["base"] = {"from": "before/nope-snapshot.html"}
        msg = self.error(spec)
        self.assertIn("nope-snapshot.html not found (tried ", msg)

    def test_refine_needs_the_refine_preset_and_one_item_per_page(self):
        spec = self.spec()
        spec["decisions"] = "design-review"
        self.assertIn('a refine item needs the "refine" decisions preset', self.error(spec))
        spec = self.spec()
        second = json.loads(json.dumps(self.item(spec)))
        second["id"] = "home-2"
        for ch in second["changes"]:
            ch["id"] += "-2"
        spec["sections"][0]["items"].append(second)
        self.assertIn("one refine item per page", self.error(spec))

    def test_refine_recommending_an_unscored_change_is_an_error_when_judged(self):
        spec = self.spec()
        self.item(spec)["changes"][0].pop("scores")
        self.assertIn("change bold-totals is recommended but has no scores", self.error(spec))
        # Unjudged and nothing scored: recommending is fine, and no score rows show.
        spec = self.spec()
        it = self.item(spec)
        it.pop("judged_by")
        for ch in it["changes"]:
            ch.pop("scores")
        text = self.html(spec)
        self.assertNotIn("Not scored", text)
        # Judged: an unscored change that is not recommended says "Not scored".
        spec = self.spec()
        self.item(spec)["changes"][1].pop("scores")
        self.assertIn("Not scored", self.card(self.html(spec), "tight-rows"))

    def test_refine_card_shows_label_why_location_scores_badge_and_a_crops_slot(self):
        text = self.html()
        card = self.card(text, "bold-totals")
        self.assertIn('<span class="rp-num">1</span><h3 class="rp-label">Bolder totals</h3>', card)
        self.assertIn('<span class="rp-loc">Hosts table</span>', card)
        self.assertIn("at regular weight they read like the host names", card)
        self.assertIn("Gain <b>4</b> · Keeps <b>5</b>", card)
        self.assertIn('<span class="rp-badge rp-rec">Recommended</span>', card)
        self.assertIn('data-rc-crops="bold-totals"', card)
        # A change with no location of its own names the item's section.
        self.assertIn('<span class="rp-loc">Dashboard</span>', self.card(text, "tight-rows"))
        self.assertIn('<span class="rp-badge rp-notrec">Not recommended</span>', self.card(text, "tight-rows"))

    def test_refine_combined_preview_follows_the_cards(self):
        text = self.html()
        prev = text.index('data-rc-preview="home"')
        self.assertLess(text.index('data-rc-change="alert-color"'), prev)
        self.assertLess(prev, text.index('data-rc-width="1280"'))
        self.assertIn('data-rc-view="picks" aria-pressed="true">With your picks</button>', text)
        self.assertIn('data-rc-view="original" aria-pressed="false">Original</button>', text)
        self.assertIn("Judged by a separate helper", text[prev:])

    def test_refine_items_get_no_near_copy_check(self):
        text = self.html()
        js = json.loads(re.search(r'<script type="application/json" id="rp-spec">(.*?)</script>', text, re.S).group(1))
        items = js["sections"][0]["items"]
        self.assertEqual([i["id"] for i in items], ["bold-totals", "tight-rows", "alert-color"])
        self.assertEqual([i["num"] for i in items], ["1", "2", "3"])
        for i in items:
            self.assertEqual(i["refine"], "home")
            self.assertIs(i["near_copy"], False)
            self.assertIs(i["design_review"], False)
            self.assertIsNone(i["before_sections"])
        self.assertIn("if (it.refine) continue;", (RP / "smoke.cjs").read_text())

    def test_refine_set_scores_use_the_six_criteria_and_show_against_the_current_page(self):
        spec = self.spec()
        self.item(spec)["set_scores"] = {"hierarchy": 9}
        self.assertIn("item home, your picks together: score hierarchy must be a whole number from 1 to 5",
                      self.error(spec))
        spec = self.spec()
        self.item(spec)["set_scores"] = {"gain": 4}
        self.assertIn("unknown score 'gain'", self.error(spec))
        text = self.html()
        prev = text[text.index('data-rc-preview="home"'):]
        cur = prev.index('<span class="rp-scores-label">Current page</span> Hierarchy <b>3</b>')
        picks = prev.index('<span class="rp-scores-label">Your picks together (recommended)</span> Hierarchy <b>4</b>')
        self.assertLess(cur, picks)

    def test_refine_removes_lines_show_on_the_card(self):
        card = self.card(self.html(), "alert-color")
        self.assertIn('<li class="rp-rc-remove"><b>Removes</b> new badge — It repeats what the alert color now says.</li>',
                      card)
        self.assertRegex((RP / "style.css").read_text(), r"\.rp-rc-remove \{[^}]*color:var\(--rp-deny\)")

    @unittest.skipUnless(NODE, "node is not installed")
    def test_capture_findings_number_on_after_the_changes(self):
        spec = self.spec()
        spec["sections"].append({"title": "Found by the capture", "decisions": "design-review", "items": [
            {"label": "Totals column out of line at 1280", "category": "capture",
             "body_html": "<p>off-center columns</p>"},
            {"label": "Host name breaks mid-word at 390", "category": "capture", "body_html": "<p>mid-word</p>"}]})
        text = self.export({"bold-totals": {"s": "accept"}, "4": {"s": "accept"}, "5": {"s": "deny"}}, spec)
        self.assertEqual(text, "[Host Headroom dashboard — Design Review (Refine)]\n"
                               "1. Bolder totals — YES\n"
                               "2. Tighter row spacing — PENDING\n"
                               "3. Status color on the alert column — PENDING\n"
                               "Combined: 1\n"
                               "4. Totals column out of line at 1280 — ACCEPT (Use Proposed)\n"
                               "5. Host name breaks mid-word at 390 — DENY")
        self.assertEqual(review_page.check(self.built(spec)), [])

    @unittest.skipUnless(NODE, "node is not installed")
    def test_existing_presets_unchanged(self):
        # Pinned before Refine was added: the other presets' exports must not move a byte.
        pinned = {
            "design-review": [
                ({"1": {"s": "accept-comment", "v": "A", "c": "a\nb"}, "2": {"s": "revise", "r": True, "c": "x"}},
                 "[Articles Index — Design Review]\n1. Article card layout — ACCEPT WITH COMMENT (Use Selected: "
                 "Variant A) — COMMENT: a b\n2. Read More button placement — REVISE — READ — COMMENT: x"),
                ({"1": {"s": "deny", "r": True}},
                 "[Articles Index — Design Review]\n1. Article card layout — DENY — READ\n"
                 "2. Read More button placement — PENDING"),
                ({"2": {"s": "accept"}},
                 "[Articles Index — Design Review]\n1. Article card layout — PENDING\n"
                 "2. Read More button placement — ACCEPT (Use Proposed)")],
            "copy-edit": [({"1": {"s": "deny"}, "2": {"s": "revise", "c": "z"}},
                           "[Pricing Page — Copy-Edit Review]\n1. Intro — first sentence — DENY (Keep Original)\n"
                           "2. New — Introduction to the Method — REVISE — COMMENT: z")],
            "photo-picker": [({"1": {"s": "deny"}, "2": {"s": "revise", "c": "z"}},
                              "[How-To Guides — Photo Picker]\n1. Article One — Introduction section — DENY (Keep None)\n"
                              "2. Article Two — Proofing Basket — REVISE — COMMENT: z")],
            "style-guide": [({"1": {"s": "deny"}, "2": {"s": "revise", "c": "z"}},
                             "[Style Guide Audit — 2026-01-15]\n1. Body text size on disclaimer notes — DENY\n"
                             "2. H2 size on plain articles vs templated ones — REVISE — COMMENT: z")]}
        for name, cases in pinned.items():
            page = build(name, self._tmp.name)
            for state, want in cases:
                r = subprocess.run([NODE, str(self.driver), str(page), json.dumps({"items": state})],
                                   capture_output=True, text=True, env=dict(os.environ, TZ="UTC"))
                self.assertEqual(r.stdout, want, name)


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
        with project_with({}):
            d = review_page.image_settings({}, env=dict(os.environ))
            self.assertEqual((d["quality"], d["max_width"]), (IMAGE_DEFAULTS["PROOFS_IMAGE_QUALITY"], IMAGE_DEFAULTS["PROOFS_IMAGE_MAX_WIDTH"]))
            s = review_page.image_settings({"image_quality": 60, "image_max_width": 900}, env=dict(os.environ))
            self.assertEqual((s["quality"], s["max_width"]), (60, 900))
            e = review_page.image_settings({"image_quality": 60}, env=dict(os.environ, PROOFS_IMAGE_QUALITY="40", PROOFS_IMAGE_MAX_WIDTH="640"))
            self.assertEqual((e["quality"], e["max_width"]), (40, 640))
            for bad in ({"image_quality": 0}, {"image_quality": "high"}, {"image_max_width": 5}):
                with self.assertRaises(review_page.SpecError):
                    review_page.image_settings(bad, env=dict(os.environ))

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
        self.assertIn("lossy at quality %d and lossless" % review_page.image_settings({})["quality"], out)
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


class SettingsRead(unittest.TestCase):
    """The builder reads its numbers and switches from the settings files, not copied constants."""

    def test_image_quality_and_width_come_from_the_project_file(self):
        with project_with({"PROOFS_IMAGE_QUALITY": "55", "PROOFS_IMAGE_MAX_WIDTH": "900"}):
            got = review_page.image_settings({})
            self.assertEqual((got["quality"], got["max_width"]), (55, 900))

    def test_the_size_warning_fires_at_the_set_number_of_megabytes(self):
        spec = {"_assets": {"a": "x" * 10}}
        text = "z" * int(1.5 * 1024 * 1024)
        with project_with({}):
            self.assertIsNone(review_page.size_warning(text, spec))  # default 3 MB
        with project_with({"PROOFS_PAGE_WARN_MB": "1"}):
            line = review_page.size_warning(text, spec)
            self.assertIn("over 1 MB", line)

    def test_spelling_check_follows_the_setting(self):
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "p.html"
            spec = {"mode": "log", "session": "s"}
            page.write_text('<script type="application/json" id="rp-spec">%s</script><p>the old behaviour</p>' % json.dumps(spec))
            with project_with({}):
                self.assertEqual([w for w in review_page.warnings(page) if "british" in w], [])
            with project_with({"PROOFS_SPELLING": "american"}):
                self.assertEqual(len([w for w in review_page.warnings(page) if "british" in w]), 1)


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


    def test_a_text_box_question_is_answered_once_typed(self):
        spec = {"mode": "questions", "title": "T", "project": {"name": "P", "stream": "s", "round": 1},
                "questions": [{"qid": "why", "ask": "Why?", "options": [], "notes_label": "Your answer"}]}
        script = r"""
const { chromium } = require(process.argv[2]);
const { launchChromium } = require(process.argv[3]);
(async () => {
  const browser = await launchChromium(chromium, process.env);
  const page = await browser.newPage();
  await page.goto("file://" + process.argv[4]);
  const before = await page.locator("#rp-tally").innerText();
  await page.locator('[data-note="why"]').fill("because");
  const r = { before, tally: await page.locator("#rp-tally").innerText(),
              answered: await page.locator('.q[data-qid="why"]').evaluate((c) => c.classList.contains("answered")),
              export: await page.evaluate(() => window.rpExport()) };
  await browser.close();
  console.log(JSON.stringify(r));
})().catch((e) => { console.log(JSON.stringify({ crash: String(e && e.stack || e) })); process.exit(1); });
"""
        with tempfile.TemporaryDirectory() as tmp:
            src, out, js = Path(tmp) / "s.json", Path(tmp) / "p.html", Path(tmp) / "t.cjs"
            src.write_text(json.dumps(spec))
            js.write_text(script)
            r = subprocess.run([sys.executable, str(BUILD), str(src), "--out", str(out)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            r = subprocess.run([NODE, str(js), playwright_dir(), str(RP / "launch.cjs"), str(out)],
                               capture_output=True, text=True, timeout=180)
            res = json.loads(r.stdout.strip().splitlines()[-1])
            self.assertNotIn("crash", res, res)
            self.assertIn("0", res["before"])
            self.assertEqual(res["tally"], "all 1 answered")
            self.assertTrue(res["answered"])
            self.assertIn("Q why (raised r1) | Why?\n  -> because\n", res["export"])
            self.assertNotIn("UNANSWERED", res["export"])
            self.assertNotIn("note:", res["export"])



# Drives the Refine preview in real Chromium. The db runtime mock is the one the answers-db
# tests use (tests/test_answers_db.py's install()), spliced in by RefineBrowser.
REFINE_DRIVE = r"""
const { chromium } = require(process.argv[2]);
const { launchChromium } = require(process.argv[3]);
const file = "file://" + process.argv[4];
/*INSTALL*/
(async () => {
  const browser = await launchChromium(chromium, process.env);
  const errors = [];
  const out = {};
  async function open(opts, seed, runtime, shared) {
    const ctx = shared || await browser.newContext(opts);
    const page = await ctx.newPage();
    page.on("pageerror", (e) => errors.push(e.message));
    if (runtime) await page.addInitScript(install, { seed, runtime });
    await page.goto(file);
    await ready(page);
    return { ctx, page };
  }
  // Both frames loaded and painted: the engine marks each frame once its layers are set.
  const ready = (page) => page.waitForFunction(() => {
    const f = document.querySelectorAll(".rp-rc-frame");
    return f.length === 2 && Array.prototype.every.call(f, (x) => x.dataset.rcReady === "1");
  }, null, { timeout: 15000 });
  // What each frame shows right now, keyed by its width.
  const look = (page) => page.evaluate(() => {
    const r = {};
    document.querySelectorAll(".rp-rc-frame").forEach((f) => {
      const d = f.contentDocument, cs = (sel, prop) => getComputedStyle(d.querySelector(sel))[prop];
      r[f.dataset.rcWidth] = {
        rc: d.documentElement.getAttribute("data-rc"),
        weight: cs(".total", "fontWeight"), alert: cs(".alert", "color"), badge: cs(".badge", "display"),
        pad: cs(".rows td", "paddingTop"), h1: cs("h1", "color"),
        icons: Array.prototype.map.call(d.querySelectorAll(".status-icon"), (i) => i.textContent),
        swapped: d.querySelectorAll("template[data-rc-swap]").length };
    });
    return r;
  });
  const tap = async (page, id, choice) => {
    await page.locator('[data-item="' + id + '"][data-choice="' + choice + '"]').click();
    await page.waitForTimeout(50);
  };
  const state = (page) => page.evaluate(() => window.rpRefine.state());
  const desk = { viewport: { width: 1440, height: 900 } };

  // 1. Undecided: every layer off, recommended ones too.
  const a = await open(desk);
  out.start = { look: await look(a.page), state: await state(a.page) };
  // 2. Yes on a change: on in both frames. No and Revise: off.
  await tap(a.page, "bold-totals", "accept");
  out.yes = { look: await look(a.page), state: await state(a.page) };
  // The frame's height follows its page both ways: tighter rows, then back.
  const tall = () => a.page.evaluate(() => Array.prototype.map.call(document.querySelectorAll(".rp-rc-frame"),
    (f) => parseFloat(f.style.height)));
  out.heights = [await tall()];
  await tap(a.page, "tight-rows", "accept");
  out.heights.push(await tall());
  await tap(a.page, "tight-rows", "deny");
  out.heights.push(await tall());
  await tap(a.page, "alert-color", "revise");
  out.noRevise = { look: await look(a.page), state: await state(a.page) };
  // 3. The swap: on with Yes, restored with No.
  await tap(a.page, "alert-color", "accept");
  out.swapOn = { look: await look(a.page), state: await state(a.page) };
  await tap(a.page, "alert-color", "deny");
  out.swapOff = await look(a.page);
  await tap(a.page, "alert-color", "accept");
  // 4. Original and back.
  await a.page.locator('[data-rc-view="original"]').click();
  out.original = { look: await look(a.page), state: await state(a.page),
                   pressed: await a.page.evaluate(() => Array.prototype.map.call(
                     document.querySelectorAll("[data-rc-view]"), (b) => b.dataset.rcView + ":" + b.getAttribute("aria-pressed"))) };
  await a.page.locator('[data-rc-view="picks"]').click();
  out.back = { look: await look(a.page), state: await state(a.page) };
  // 5. A frame that reloads gets its layers again.
  await a.page.evaluate(() => new Promise((res) => {
    const f = document.querySelector('.rp-rc-frame[data-rc-width="390"]');
    f.addEventListener("load", () => setTimeout(res, 50), { once: true });
    f.srcdoc = f.srcdoc;
  }));
  out.frameReload = await look(a.page);
  // A load of a document that is not the snapshot does not mark the frame ready.
  out.blank = await a.page.evaluate(() => new Promise((res) => {
    const f = document.querySelector('.rp-rc-frame[data-rc-width="390"]'), base = f.srcdoc;
    delete f.dataset.rcReady;
    f.addEventListener("load", () => setTimeout(() => {
      const other = { ready: f.dataset.rcReady || null, rc: f.contentDocument.documentElement.getAttribute("data-rc") };
      f.addEventListener("load", () => setTimeout(() => res({ other, after: f.dataset.rcReady || null }), 50), { once: true });
      f.srcdoc = base;
    }, 50), { once: true });
    f.srcdoc = "<!doctype html><p>not the snapshot</p>";
  }));
  // Content that grows after load, with no window resize: the frame and its box follow.
  out.late = await a.page.evaluate(() => new Promise((res) => {
    const f = document.querySelector('.rp-rc-frame[data-rc-width="1280"]'), box = f.parentNode;
    const before = { h: parseFloat(f.style.height), box: parseFloat(box.style.height) };
    const tall = f.contentDocument.createElement("div");
    tall.style.height = "600px";
    f.contentDocument.body.appendChild(tall);
    setTimeout(() => {
      const after = { h: parseFloat(f.style.height), box: parseFloat(box.style.height) };
      tall.remove();
      res({ before, after });
    }, 200);
  }));
  await a.page.waitForTimeout(200);
  // 6. The page reloads: saved answers come back into the preview.
  await a.page.reload();
  await ready(a.page);
  out.pageReload = { look: await look(a.page), state: await state(a.page) };
  // The desktop frame scaled to its column.
  out.fit1440 = await a.page.evaluate(() => {
    const f = document.querySelector('.rp-rc-frame[data-rc-width="1280"]'), fig = f.closest(".rp-rc-fig");
    const r = f.getBoundingClientRect();
    return { frame: r.width, col: fig.getBoundingClientRect().width, h: r.height,
             box: f.parentNode.getBoundingClientRect().height };
  });
  await a.ctx.close();

  // WebKit fires a load for the frame's initial about:blank after the engine is listening:
  // dispatched here before the snapshot arrives, it must not mark the frame ready.
  const early = await browser.newContext(desk);
  const ep = await early.newPage();
  await ep.addInitScript(() => {
    // The engine attaches its load listener, then sets srcdoc: fire the blank load in between.
    const d = Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype, "srcdoc");
    window.__early = [];
    Object.defineProperty(HTMLIFrameElement.prototype, "srcdoc", { configurable: true, get: d.get,
      set(v) {
        if (this.classList.contains("rp-rc-frame") && !this.__blankFired) {
          this.__blankFired = true;
          const url = this.contentDocument && this.contentDocument.URL;
          this.dispatchEvent(new Event("load"));
          window.__early.push({ url, ready: this.dataset.rcReady || null });
        }
        d.set.call(this, v);
      } });
  });
  await ep.goto(file);
  await ready(ep);
  out.early = { before: await ep.evaluate(() => window.__early), look: await look(ep) };
  await early.close();

  // 7. Another device: the answers come from the page's database.
  const w = await open(desk, {}, "db");
  await tap(w.page, "alert-color", "accept");
  await w.page.waitForTimeout(300);
  const rows = await w.page.evaluate(() => window.__rows);
  await w.ctx.close();
  const b = await open(desk, rows, "db");
  await b.page.waitForTimeout(400);
  out.dbRestore = { look: await look(b.page), state: await state(b.page), rows: Object.keys(rows) };
  await b.ctx.close();

  // 8. At 390: no sideways scroll, and both frames fit the column.
  const m = await open({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 });
  out.phone = await m.page.evaluate(() => {
    const fr = {};
    document.querySelectorAll(".rp-rc-frame").forEach((f) => {
      const r = f.getBoundingClientRect(), col = f.closest(".rp-rc-fig").getBoundingClientRect();
      fr[f.dataset.rcWidth] = { left: r.left, right: r.right, width: r.width, colLeft: col.left, colRight: col.right };
    });
    return { scrollWidth: document.documentElement.scrollWidth, frames: fr };
  });
  out.phoneLook = await look(m.page);
  await m.ctx.close();
  out.errors = errors;
  await browser.close();
  console.log(JSON.stringify(out));
})().catch((e) => { console.log(JSON.stringify({ crash: String(e && e.stack || e) })); process.exit(1); });
"""


@unittest.skipUnless(NODE and playwright_dir(), "Playwright not found")
class RefineBrowser(unittest.TestCase):
    """The combined preview live in Chromium: Yes turns a change's layer on in both frames,
    anything else leaves it off, the Original toggle, swaps, reloads, and the 390 fit (spec §4)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls.tmp.name)
        shutil.copytree(REFINE, tmp / "refine")
        # Taller than the frames' floor (the capture's 800 and 844 px viewports), so the height
        # tests see the frame follow its page.
        snap = tmp / "refine" / "before" / "home-snapshot.html"
        snap.write_text(snap.read_text().replace("</div></body>", '<div style="height:1200px"></div>\n</div></body>', 1))
        src, out = tmp / "refine" / "s.json", tmp / "page.html"
        src.write_text((REFINE / "spec.json").read_text())
        r = subprocess.run([sys.executable, str(BUILD), str(src), "--out", str(out)], capture_output=True, text=True,
                           cwd=str(tmp / "refine"))
        if r.returncode:
            raise AssertionError(r.stdout + r.stderr)
        install = re.search(r"^function install\(\{ seed, runtime \}\) \{.*?^\}$",
                            (ROOT / "tests" / "test_answers_db.py").read_text(), re.S | re.M).group(0)
        script = tmp / "drive.cjs"
        script.write_text(REFINE_DRIVE.replace("/*INSTALL*/", install))
        r = subprocess.run([NODE, str(script), playwright_dir(), str(RP / "launch.cjs"), str(out)],
                           capture_output=True, text=True, timeout=300)
        lines = r.stdout.strip().splitlines()
        cls.res = json.loads(lines[-1]) if lines else {"crash": r.stderr}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.assertNotIn("crash", self.res, self.res.get("crash"))
        self.assertEqual(self.res["errors"], [])

    def both(self, look):
        self.assertEqual(sorted(look), ["1280", "390"])
        return [look["1280"], look["390"]]

    def test_yes_turns_the_layer_on_in_both_frames(self):
        for f in self.both(self.res["yes"]["look"]):
            self.assertIn("bold-totals", f["rc"].split())
            self.assertEqual(f["weight"], "700")
        for f in self.both(self.res["start"]["look"]):
            self.assertEqual(f["weight"], "400")
        self.assertEqual(self.res["yes"]["state"], {"on": ["bold-totals"], "view": "picks"})

    def test_no_and_pending_leave_it_off(self):
        st = self.res["noRevise"]
        for f in self.both(st["look"]):
            self.assertEqual(f["rc"].split(), ["bold-totals"])      # tight-rows No, alert-color Revise
            self.assertEqual(f["pad"], "12px")
            self.assertEqual(f["alert"], "rgb(55, 65, 81)")
            self.assertEqual(f["badge"], "inline")
        self.assertEqual(st["state"], {"on": ["bold-totals"], "view": "picks"})

    def test_undecided_cards_start_off_even_when_recommended(self):
        st = self.res["start"]
        for f in self.both(st["look"]):
            self.assertEqual(f["rc"], "")
            self.assertEqual(f["alert"], "rgb(55, 65, 81)")
            self.assertEqual(f["icons"], ["!"])
        self.assertEqual(st["state"], {"on": [], "view": "picks"})

    def test_original_toggle_shows_no_layers_and_back(self):
        orig = self.res["original"]
        for f in self.both(orig["look"]):
            self.assertEqual(f["rc"], "")
            self.assertEqual((f["weight"], f["icons"], f["badge"]), ("400", ["!"], "inline"))
        self.assertEqual(orig["state"]["view"], "original")
        self.assertEqual(orig["pressed"], ["picks:false", "original:true"])
        back = self.res["back"]
        for f in self.both(back["look"]):
            self.assertEqual(sorted(f["rc"].split()), ["alert-color", "bold-totals"])
            self.assertEqual((f["weight"], f["icons"]), ("700", ["▲"]))
        self.assertEqual(back["state"], {"on": ["bold-totals", "alert-color"], "view": "picks"})

    def test_swap_replaces_the_element_while_on_and_restores_it_off(self):
        for f in self.both(self.res["swapOn"]["look"]):
            self.assertEqual(f["icons"], ["▲"])
            self.assertEqual(f["badge"], "none")
            self.assertEqual(f["alert"], "rgb(180, 35, 24)")
            self.assertEqual(f["swapped"], 1)        # the template stays for the next time
        for f in self.both(self.res["swapOff"]):
            self.assertEqual(f["icons"], ["!"])
            self.assertEqual(f["badge"], "inline")

    def test_reload_restores_saved_answers_into_the_preview(self):
        for key in ("pageReload", "dbRestore"):
            look = self.res[key]["look"]
            for f in self.both(look):
                self.assertIn("alert-color", f["rc"].split(), key)
                self.assertEqual(f["icons"], ["▲"], key)
        self.assertEqual(self.res["pageReload"]["state"], {"on": ["bold-totals", "alert-color"], "view": "picks"})
        self.assertEqual(self.res["dbRestore"]["state"], {"on": ["alert-color"], "view": "picks"})
        self.assertIn("s1.alert-color", self.res["dbRestore"]["rows"])
        # A frame that reloads on its own is painted again.
        for f in self.both(self.res["frameReload"]):
            self.assertEqual(sorted(f["rc"].split()), ["alert-color", "bold-totals"])
            self.assertEqual(f["icons"], ["▲"])

    def test_390_viewport_has_no_sideways_scroll_and_1280_frame_fits(self):
        ph = self.res["phone"]
        self.assertLessEqual(ph["scrollWidth"], 390)
        for w, f in ph["frames"].items():
            self.assertGreaterEqual(f["left"], f["colLeft"] - 0.5, w)
            self.assertLessEqual(f["right"], f["colRight"] + 0.5, w)
            self.assertLessEqual(f["right"], 390, w)
        self.assertLess(ph["frames"]["1280"]["width"], 390)
        # At 1440 the desktop frame is scaled to its column too, and its box is as tall as it is.
        fit = self.res["fit1440"]
        self.assertLessEqual(fit["frame"], fit["col"] + 0.5)
        self.assertGreater(fit["h"], 50)
        self.assertAlmostEqual(fit["box"], fit["h"] + 2, delta=2)

    def test_frame_height_follows_its_page_down_and_back_up(self):
        before, tight, back = self.res["heights"]
        for i in range(2):
            self.assertLess(tight[i], before[i])
            self.assertEqual(back[i], before[i])

    def test_a_blank_document_load_does_not_mark_the_frame_ready(self):
        b = self.res["blank"]
        self.assertEqual(b["other"], {"ready": None, "rc": None})
        self.assertEqual(b["after"], "1")
        early = self.res["early"]
        self.assertEqual(early["before"], [{"url": "about:blank", "ready": None}] * 2)
        for f in self.both(early["look"]):
            self.assertEqual(f["icons"], ["!"])   # and the snapshot still painted once it loaded

    def test_frame_height_follows_late_content_without_a_window_resize(self):
        late = self.res["late"]
        self.assertGreaterEqual(late["after"]["h"], late["before"]["h"] + 590)
        self.assertGreater(late["after"]["box"], late["before"]["box"])

    def test_each_frame_uses_its_own_width_layout(self):
        for key in ("start", "back"):
            look = self.res[key]["look"]
            self.assertEqual(look["1280"]["h1"], "rgb(0, 128, 0)", key)
            self.assertEqual(look["390"]["h1"], "rgb(200, 0, 0)", key)
        self.assertEqual(self.res["phoneLook"]["390"]["h1"], "rgb(200, 0, 0)")


# Shoots an HTML file the way the capture shoots a page (fidelity.cjs's SHOT_VIEWPORTS, the
# capture's own 1280 and 390): per width, the first screen as <out>-<width>.png and the whole
# page as <out>-<width>-full.png, at 1x when the capture would take it so (FULL_MAX_PX).
SHOOT = r"""
const path = require("path");
const [pw, rp, file, out] = process.argv.slice(2);
const { chromium } = require(pw);
const { launchChromium } = require(path.join(rp, "launch.cjs"));
const { SHOT_VIEWPORTS, SETTLE_MS, FULL_MAX_PX } = require(path.join(rp, "fidelity.cjs"));
(async () => {
  const browser = await launchChromium(chromium, process.env);
  for (const w of Object.keys(SHOT_VIEWPORTS)) {
    const ctx = await browser.newContext(SHOT_VIEWPORTS[w]);
    const page = await ctx.newPage();
    await page.goto("file://" + path.resolve(file));
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(SETTLE_MS);
    await page.screenshot({ path: out + "-" + w + ".png" });
    const tall = await page.evaluate(() => document.documentElement.scrollHeight);
    const dpr = SHOT_VIEWPORTS[w].deviceScaleFactor || 1;
    await page.screenshot({ path: out + "-" + w + "-full.png", fullPage: true,
      ...(dpr > 1 && tall * dpr > FULL_MAX_PX ? { scale: "css" } : {}) });
    await ctx.close();
  }
  await browser.close();
})().catch((e) => { console.error(e.stack || String(e)); process.exit(1); });
"""


@unittest.skipUnless(NODE and playwright_dir(), "Playwright not found")
class RefineSmoke(unittest.TestCase):
    """--smoke on a Refine page: the base against the before shots (fidelity), overlapping
    changes, the design checks with each change on alone and all on, and --match-preview (spec
    §2, §3 and §7)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.dir = self.tmp / "refine"
        shutil.copytree(REFINE, self.dir)
        self.snap = self.dir / "before" / "home-snapshot.html"
        self.shoot_js = self.tmp / "shoot.cjs"
        self.shoot_js.write_text(SHOOT)

    def shoot(self, html_file, out_stem):
        r = subprocess.run([NODE, str(self.shoot_js), playwright_dir(), str(RP), str(html_file), str(out_stem)],
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)

    def before_shots(self):
        """The capture's shots of the page the snapshot was taken from: home-1280-full.png and
        home-390-full.png (and the first-screen shots) beside home-snapshot.html."""
        self.shoot(self.snap, self.dir / "before" / "home")

    def spec(self):
        return json.loads((REFINE / "spec.json").read_text())

    def build(self, spec=None):
        src, out = self.dir / "s.json", self.tmp / "page.html"
        src.write_text(json.dumps(spec or self.spec()))
        r = subprocess.run([sys.executable, str(BUILD), str(src), "--out", str(out), "--no-check"],
                           capture_output=True, text=True, cwd=str(self.dir))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return out

    def smoke(self, spec=None):
        page = self.build(spec)
        r = subprocess.run([sys.executable, str(BUILD), "--smoke", str(page)], capture_output=True, text=True,
                           cwd=str(self.dir), timeout=300)
        try:
            return json.loads(r.stdout)
        except ValueError:
            raise AssertionError(r.stdout + r.stderr)

    def add_css(self, css, file=None):
        f = file or self.snap
        f.write_text(f.read_text().replace("</style>", css + "\n</style>", 1))

    def make_tall(self):
        """Content below the first screen at both widths: a spacer, then a dark block."""
        self.add_css(".low { height: 200px; background: #334; }")
        self.snap.write_text(self.snap.read_text().replace(
            "</div></body>", '<div style="height:1400px"></div><div class="low"></div>\n</div></body>', 1))

    @staticmethod
    def refine_lines(res):
        return [p for p in res["problems"] if "(Refine)" in p]

    def test_fidelity_passes_the_exact_snapshot(self):
        self.before_shots()
        self.assertIn('data-rc-base="before/home-snapshot.html"', self.build().read_text())
        res = self.smoke()
        self.assertEqual(self.refine_lines(res), [])
        fid = res["refine"]["fidelity"]
        self.assertEqual(sorted(fid), ["1280", "390"])
        for w in ("1280", "390"):
            self.assertLessEqual(fid[w]["pixelRatio"], 0.001, fid)
            self.assertTrue(fid[w]["before"].endswith("home-%s-full.png" % w), fid)

    def test_fidelity_flags_a_base_that_does_not_match_the_before_shot(self):
        self.before_shots()
        # The base is a copy with one extra margin: everything under the heading moves down 25px.
        self.add_css("h1 { margin-top: 25px; }")
        res = self.smoke()
        for w in ("1280", "390"):
            ratio = res["refine"]["fidelity"][w]["pixelRatio"]
            self.assertGreater(ratio, 0.005)
            self.assertIn("item home (Refine): base differs from the page at %s (pixel ratio %.3f)" % (w, ratio),
                          res["problems"])

    def test_fidelity_sees_drift_below_the_first_screen(self):
        self.make_tall()
        self.before_shots()
        self.add_css(".low { margin-top: 25px; }")
        res = self.smoke()
        for w in ("1280", "390"):
            self.assertTrue([p for p in res["problems"] if p.startswith(
                "item home (Refine): base differs from the page at %s " % w)], res["problems"])

    def test_fidelity_without_a_before_shot_is_a_problem_not_a_pass(self):
        res = self.smoke()
        self.assertTrue(any(p.startswith("item home (Refine): no before shot at 1280") and p.endswith(
            "pass --shots DIR with the folder of the before shots") for p in res["problems"]), res["problems"])

    def test_overlap_names_both_changes_the_element_and_the_property(self):
        self.before_shots()
        spec = self.spec()
        changes = spec["sections"][0]["items"][0]["changes"]
        changes.append({"id": "heavy-totals", "label": "Heavier totals", "why_html": "<p>w</p>",
                        "targets": [".total"], "css": ".total { font-weight: 800; letter-spacing: 1px; }"})
        res = self.smoke(spec)
        ov = res["refine"]["overlaps"]
        self.assertIn({"a": "1", "b": "4", "element": ".total", "property": "font-weight"}, ov)
        self.assertIn("item home (Refine): changes 1 and 4 both change font-weight on .total", res["problems"])
        # Only what both change: the letter spacing is change 4's alone, and changes 2 and 3 touch other things.
        self.assertEqual([o for o in ov if (o["a"], o["b"]) != ("1", "4") or o["property"] != "font-weight"], [], ov)

    def test_overlap_through_a_custom_property(self):
        # Change 4 sets only --accent; the page's .alert reads it, and change 5 sets .alert's color.
        self.add_css(".alert { color: var(--accent, #374151); }")
        self.before_shots()
        spec = self.spec()
        spec["sections"][0]["items"][0]["changes"] += [
            {"id": "accent", "label": "Accent", "why_html": "<p>a</p>", "targets": [".wrap"],
             "css": ".wrap { --accent: #b42318; }"},
            {"id": "alert-ink", "label": "Ink", "why_html": "<p>i</p>", "targets": [".alert"],
             "css": ".alert { color: #000055; }"}]
        res = self.smoke(spec)
        self.assertIn({"a": "4", "b": "5", "element": ".alert", "property": "color"}, res["refine"]["overlaps"])
        self.assertIn("item home (Refine): changes 4 and 5 both change color on .alert", res["problems"])

    def test_overlap_of_a_swap_and_a_property_on_the_same_element(self):
        self.before_shots()
        spec = self.spec()
        spec["sections"][0]["items"][0]["changes"].append(
            {"id": "icon-blue", "label": "Blue icon", "why_html": "<p>b</p>", "targets": [".status-icon"],
             "css": ".status-icon { color: #0000aa; }"})
        res = self.smoke(spec)
        self.assertIn({"a": "3", "b": "4", "element": ".status-icon", "property": "color"}, res["refine"]["overlaps"])
        self.assertIn("item home (Refine): change 3 swaps .status-icon, which change 4 also changes (color)",
                      res["problems"])

    def test_no_overlap_from_a_reflow_onto_a_layout_property(self):
        # Change 4's bigger type makes the header and table taller; change 5 declares a height,
        # on the logo only. Neither declares height on the header, so they do not overlap there.
        self.before_shots()
        spec = self.spec()
        spec["sections"][0]["items"][0]["changes"] += [
            {"id": "big-type", "label": "Bigger type", "why_html": "<p>t</p>", "targets": [".wrap"],
             "css": ".wrap { font-size: 20px; }"},
            {"id": "tall-logo", "label": "Taller logo", "why_html": "<p>l</p>", "targets": [".logo"],
             "css": ".logo { height: 30px; }"}]
        res = self.smoke(spec)
        self.assertEqual([o for o in res["refine"]["overlaps"] if {o["a"], o["b"]} & {"4", "5"}], [],
                         res["refine"]["overlaps"])

    def test_no_overlap_from_a_property_inherited_into_a_swap(self):
        # Change 4's font size reaches the swapped .status-icon only by inheritance.
        self.before_shots()
        spec = self.spec()
        spec["sections"][0]["items"][0]["changes"].append(
            {"id": "big-type", "label": "Bigger type", "why_html": "<p>t</p>", "targets": [".wrap"],
             "css": ".wrap { font-size: 20px; }"})
        res = self.smoke(spec)
        self.assertEqual([o for o in res["refine"]["overlaps"] if (o["a"], o["b"]) == ("3", "4")], [],
                         res["refine"]["overlaps"])
        self.assertFalse([p for p in res["problems"] if "swaps" in p], res["problems"])

    def test_design_checks_run_on_each_change_alone_and_all_on(self):
        self.before_shots()
        spec = self.spec()
        changes = spec["sections"][0]["items"][0]["changes"]
        changes[2]["css"] = ".alert { color: #d0d0d0; } .badge { display: none; }"
        res = self.smoke(spec)
        for state in ("change 3 on", "all changes on"):
            for w in (1280, 390):
                line = r"item home \(Refine\), %s: \d+ text elements below AA contrast at %dpx" % (state, w)
                self.assertTrue([p for p in res["problems"] if re.fullmatch(line, p)], res["problems"])
        # The other changes keep contrast: no line for them, and none for the page as it is.
        self.assertFalse([p for p in res["problems"] if "change 1 on" in p or "change 2 on" in p], res["problems"])
        states = {(c["state"], c["width"]) for c in res["refine"]["checks"]}
        self.assertEqual(states, {(s, w) for s in ("base", "1", "2", "3", "all") for w in (1280, 390)})

    def test_no_near_copy_line_for_refine_items(self):
        self.before_shots()
        res = self.smoke()
        self.assertEqual(res["near_copies"], [])
        self.assertEqual(res["layout_scores"], [])
        self.assertFalse([t for t in res["problems"] + res["notes"] if "near-copies" in t])

    def match(self, page, picks, shots):
        r = subprocess.run([sys.executable, str(BUILD), "--match-preview", str(page), "--picks", picks,
                            "--shots", str(shots)], capture_output=True, text=True, cwd=str(self.dir), timeout=300)
        return r.returncode, r.stdout + r.stderr

    def test_match_preview_passes_identical_and_fails_a_different_build(self):
        self.before_shots()
        page = self.build()
        after = self.tmp / "after"
        after.mkdir()
        # The real page with change 1 built: its CSS in the page's own sheet, not scoped.
        built = self.dir / "before" / "built.html"
        built.write_text(self.snap.read_text().replace("</style>", ".total { font-weight: 700; }\n</style>", 1))
        self.shoot(built, after / "home")
        code, out = self.match(page, "1", after)
        self.assertEqual(code, 0, out)
        self.assertIn("match", out)
        # The same build against picks 1 and 3: change 3 was never built.
        code, out = self.match(page, "1,3", after)
        self.assertEqual(code, 1, out)
        for w in ("1280", "390"):
            self.assertTrue(re.search(r"^%s: .*changes 1, 3" % w, out, re.M), out)
        # A build that missed its one pick fails too, though it changes only a few pixels of the page.
        nothing = self.tmp / "nothing"
        nothing.mkdir()
        self.shoot(self.snap, nothing / "home")
        code, out = self.match(page, "1", nothing)
        self.assertEqual(code, 1, out)
        self.assertEqual(len([l for l in out.splitlines() if re.match(r"(1280|390): ", l)]), 2, out)

    def test_match_preview_sees_a_pick_below_the_first_screen(self):
        self.make_tall()
        self.before_shots()
        spec = self.spec()
        spec["sections"][0]["items"][0]["changes"].append(
            {"id": "low-red", "label": "Red block", "why_html": "<p>r</p>", "targets": [".low"],
             "css": ".low { background: #a33; }"})
        page = self.build(spec)
        code, out = self.match(page, "4", self.dir / "before")   # the page as it was: change 4 not built
        self.assertEqual(code, 1, out)
        built = self.dir / "before" / "built.html"
        built.write_text(self.snap.read_text())
        self.add_css(".low { background: #a33; }", built)
        after = self.tmp / "after"
        after.mkdir()
        self.shoot(built, after / "home")
        code, out = self.match(page, "4", after)
        self.assertEqual(code, 0, out)

    def test_match_preview_cannot_measure_picks_that_change_nothing_visible(self):
        self.before_shots()
        spec = self.spec()
        spec["sections"][0]["items"][0]["changes"].append(
            {"id": "hand", "label": "Hand cursor", "why_html": "<p>h</p>", "targets": [".total"],
             "css": ".total { cursor: pointer; }"})
        code, out = self.match(self.build(spec), "4", self.dir / "before")
        self.assertEqual(code, 2, out)
        self.assertIn("change 4 changes nothing visible", out)

    def test_match_preview_cannot_measure_without_the_build_shots(self):
        self.before_shots()
        page = self.build()
        empty = self.tmp / "empty"
        empty.mkdir()
        code, out = self.match(page, "1", empty)
        self.assertEqual(code, 2, out)
        self.assertIn("no shot of the built page", out)
        code, out = self.match(page, "1", self.tmp / "nowhere")
        self.assertEqual(code, 2, out)
        self.assertIn(str((self.tmp / "nowhere").resolve()), out)

    def test_match_preview_refuses_a_pick_the_page_does_not_have(self):
        self.before_shots()
        code, out = self.match(self.build(), "9", self.dir / "before")
        self.assertEqual(code, 2, out)
        self.assertIn("9", out)

    def viewport_page(self, name):
        """A Refine page on before/<name>-snapshot.html, one change, with its before shots."""
        self.snap = self.dir / "before" / ("%s-snapshot.html" % name)
        self.shoot(self.snap, self.dir / "before" / name)
        spec = self.spec()
        item = spec["sections"][0]["items"][0]
        item["base"] = {"from": "before/%s-snapshot.html" % name}
        item["changes"] = [{"id": "bold-totals", "label": "Bolder totals", "why_html": "<p>b</p>",
                            "targets": [".total"], "css": ".total { font-weight: 700; }"}]
        return spec

    def test_a_100vh_hero_keeps_its_height_in_the_frames(self):
        # Inside a frame 100vh is the frame, and the frame took the page's height, so a
        # min-height: 100vh hero with content below grew without bound. The builder writes vh as
        # --rp-vh, which each frame and renderBase set to the capture's viewport / 100.
        res = self.smoke(self.viewport_page("hero"))
        self.assertEqual(self.refine_lines(res), [])
        for w, vh in (("1280", 800), ("390", 844)):
            h = res["refine"]["heights"][w]
            self.assertIsNotNone(h["before"], h)
            self.assertGreater(h["before"], vh + 900)                    # the hero, then the rest
            self.assertLessEqual(abs(h["frame"] - h["before"]), 2, (w, h))
            self.assertLessEqual(res["refine"]["fidelity"][w]["pixelRatio"], 0.001, res["refine"]["fidelity"])

    def test_an_app_shell_is_as_tall_as_the_capture_viewport(self):
        # html, body { height: 100% } with the body scrolling: the frame used to stay at the
        # iframe's default 150 px. It is measured at the capture's viewport height instead.
        res = self.smoke(self.viewport_page("shell"))
        self.assertEqual(self.refine_lines(res), [])
        for w, vh in (("1280", 800), ("390", 844)):
            self.assertEqual(res["refine"]["heights"][w], {"frame": vh, "before": vh}, w)

    def test_a_frame_that_does_not_match_the_before_height_is_a_problem(self):
        self.before_shots()
        self.make_tall()   # the base is now 1600 px taller than the page the before shots show
        res = self.smoke()
        for w in ("1280", "390"):
            h = res["refine"]["heights"][w]
            self.assertIn("item home (Refine): the %s frame lays the page out %d px tall, but the before shot is %d px; "
                          "the preview does not show the page as it is" % (w, round(h["frame"]), h["before"]), res["problems"])

    def test_hidden_or_reworded_without_removes_is_a_problem_and_with_removes_a_note(self):
        self.add_css(".code { color: #999; }")    # the page's own failure, made worse by change 8
        self.before_shots()
        spec = self.spec()
        spec["sections"][0]["items"][0]["changes"] += [
            {"id": "ghost-brand", "label": "g", "why_html": "<p>g</p>", "targets": [".brand"], "css": ".brand { visibility: hidden; }"},
            {"id": "faded-photo", "label": "f", "why_html": "<p>f</p>", "targets": [".photo"], "css": ".photo { opacity: 0; }"},
            # Both .alert cells, and the icon inside one, which inherits the transform.
            {"id": "loud-alert", "label": "l", "why_html": "<p>l</p>", "targets": [".alert"], "css": ".alert { text-transform: uppercase; }"},
            {"id": "missing", "label": "m", "why_html": "<p>m</p>", "targets": [".nope", "a[["], "css": ".nope { color: #000; }"},
            {"id": "paler-code", "label": "p", "why_html": "<p>p</p>", "targets": [".code"], "css": ".code { color: #c8c8c8; }"}]
        res = self.smoke(spec)
        probs = self.refine_lines(res)
        for w in (1280, 390):
            self.assertIn("item home (Refine): change 4 hides 1 element at %dpx (.brand) with no removes line saying what and why" % w, probs)
            self.assertIn("item home (Refine): change 5 hides 1 element at %dpx (.photo) with no removes line saying what and why" % w, probs)
            self.assertTrue([p for p in probs if p.startswith("item home (Refine): change 6 changes words in 3 elements at %dpx (.alert, .alert, .status-icon)" % w)
                             and p.endswith("with no removes line saying what and why")], probs)
            # Change 3 hides the two badges and swaps out the icon, and says so: notes, not problems.
            self.assertFalse([p for p in probs if "change 3 hides" in p or "change 3 changes words" in p], probs)
            self.assertTrue([n for n in res["notes"] if n.startswith("item home (Refine): change 3 hides 3 elements at %dpx (.badge, .status-icon, .badge)" % w)
                             and "check its removes lines (new badge; ! status icon) cover them" in n], res["notes"])
            self.assertTrue([n for n in res["notes"] if n.startswith("item home (Refine), change 8 on: makes 1 text element already "
                             "below AA contrast worse at %dpx" % w)], res["notes"])
        self.assertIn("item home (Refine): change 7: target .nope matches nothing", probs)
        self.assertIn("item home (Refine): change 7: target a[[ is not a valid selector", probs)
        self.assertFalse([p for p in probs if "change 1 " in p or "change 2 " in p], probs)

    def test_match_preview_says_when_a_mismatch_is_mostly_text(self):
        # The build shows other numbers than the before did (a page on live data): most of what
        # differs, outside the picked change, is text, and the line says so.
        digits = '<p class="data" style="font:14px/1.4 ui-monospace, monospace">%s</p>'
        self.snap.write_text(self.snap.read_text().replace("</div></body>", digits % ("1234567890 " * 60) + "\n</div></body>", 1))
        page = self.build()
        built = self.dir / "before" / "built.html"
        built.write_text(self.snap.read_text().replace("1234567890 " * 60, "9876543210 " * 60)
                         .replace("</style>", ".total { font-weight: 700; }\n</style>", 1))
        after = self.tmp / "after"
        after.mkdir()
        self.shoot(built, after / "home")
        code, out = self.match(page, "1", after)
        self.assertEqual(code, 1, out)
        for w in ("1280", "390"):
            self.assertTrue(re.search(r"^%s: .*\d+%% of the differing pixels outside the picks are text, as when the page shows "
                                      r"other data than the before did" % w, out, re.M), out)
        # A real miss (change 1 never built) is not called data.
        self.shoot(self.snap, self.dir / "before" / "home")
        code, out = self.match(page, "1", self.dir / "before")
        self.assertEqual(code, 1, out)
        self.assertNotIn("are text", out)

    def test_shot_viewports_are_the_captures(self):
        r = subprocess.run([NODE, "-e", "const c = require(process.argv[1]); const f = require(process.argv[2]);"
                            "console.log(JSON.stringify([c.VIEWPORTS, f.SHOT_VIEWPORTS]))",
                            str(ROOT / "skills" / "visual-qa" / "scripts" / "capture.cjs"), str(RP / "fidelity.cjs")],
                           capture_output=True, text=True)
        cap, shot = json.loads(r.stdout)
        for vp in cap:
            if vp["label"] in shot:
                want = {k: v for k, v in vp.items() if k not in ("label", "width", "height")}
                want["viewport"] = {"width": vp["width"], "height": vp["height"]}
                self.assertEqual(shot[vp["label"]], want)
        self.assertEqual(sorted(shot), ["1280", "390"])
        # The frames' floors and --rp-vh come from the builder's copy of the same heights.
        self.assertEqual({int(k): v["viewport"]["height"] for k, v in shot.items()}, review_page.REFINE_VIEWPORT_H)


# Measures a change outside the review page, for RefineCrops: the base rendered as its own page
# at each width with the change off and on (fidelity.cjs applyChanges, as the engine paints it):
# each target's box, the page's height, the bounding box of the pixels the change moves
# (renderBase, diffMask), and the two crops crops.cjs wrote.
CROP_MEASURE = r"""
const fs = require("fs");
const path = require("path");
const [pw, rp, page, id, targetsArg, crops] = process.argv.slice(2);
const { chromium } = require(pw);
const { launchChromium } = require(path.join(rp, "launch.cjs"));
const { renderBase, applyChanges, diffMask, SHOT_VIEWPORTS } = require(path.join(rp, "fidelity.cjs"));
const targets = JSON.parse(targetsArg);
const text = fs.readFileSync(page, "utf8");
const doc = JSON.parse(text.match(/<script type="application\/json" id="rp-rc-base-[^"]*">([\s\S]*?)<\/script>/)[1]);
function bbox(d, scale) {
  let x0 = Infinity, y0 = Infinity, x1 = -1, y1 = -1;
  for (let y = 0; y < d.height; y++) for (let x = 0; x < d.width; x++) {
    if (!d.mask[y * d.width + x]) continue;
    x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x + 1); y1 = Math.max(y1, y + 1);
  }
  return x1 < 0 ? null : [x0 / scale, y0 / scale, x1 / scale, y1 / scale];
}
(async () => {
  const browser = await launchChromium(chromium, process.env);
  const out = {};
  for (const w of [1280, 390]) {
    const boxes = [], heights = [];
    for (const on of [[], [id]]) {
      const ctx = await browser.newContext({ viewport: { width: w, height: 800 } });
      const p = await ctx.newPage();
      await p.setContent(doc, { waitUntil: "load" });
      await p.evaluate(applyChanges, on);
      boxes.push(...await p.evaluate((sels) => sels.flatMap((s) => Array.from(document.querySelectorAll(s)).map((e) => {
        const r = e.getBoundingClientRect();
        return [r.left + scrollX, r.top + scrollY, r.right + scrollX, r.bottom + scrollY];
      })).filter((b) => b[2] > b[0] && b[3] > b[1]), targets));
      heights.push(await p.evaluate(() => document.documentElement.getBoundingClientRect().height));
      await ctx.close();
    }
    const dpr = SHOT_VIEWPORTS[w].deviceScaleFactor || 1;
    const moved = bbox(diffMask(await renderBase(browser, doc, w, []), await renderBase(browser, doc, w, [id])), dpr);
    const r = { targets: boxes, height: Math.min(...heights), moved, crops: null };
    const before = path.join(crops, `${id}-before-${w}.png`), after = path.join(crops, `${id}-after-${w}.png`);
    if (fs.existsSync(before) && fs.existsSync(after)) {
      const d = diffMask(before, after);
      r.crops = { width: d.width, height: d.height, differ: d.count };
    }
    out[w] = r;
  }
  await browser.close();
  console.log(JSON.stringify(out));
})().catch((e) => { console.log(JSON.stringify({ crash: String(e && e.stack || e) })); process.exit(1); });
"""


@unittest.skipUnless(NODE and playwright_dir(), "Playwright not found")
class RefineCrops(unittest.TestCase):
    """--crops: each change's before and after at 1280 and 390, cut from the built page's frames
    to the union of its targets plus the margin, and the next build showing them on its card
    (spec §4, "One card per change")."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.dir = self.tmp / "refine"
        shutil.copytree(REFINE, self.dir)
        self.snap = self.dir / "before" / "home-snapshot.html"
        self.out = self.dir / ".proofs" / "design-review" / "crops"

    def spec(self):
        return json.loads((REFINE / "spec.json").read_text())

    def build(self, spec=None):
        src, out = self.dir / "s.json", self.tmp / "page.html"
        src.write_text(json.dumps(spec or self.spec()))
        r = subprocess.run([sys.executable, str(BUILD), str(src), "--out", str(out)],
                           capture_output=True, text=True, cwd=str(self.dir))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return out

    def crops(self, page):
        r = subprocess.run([sys.executable, str(BUILD), "--crops", str(page), "--out", str(self.out)],
                           capture_output=True, text=True, cwd=str(self.dir), timeout=300)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads((self.out / "crops.json").read_text()), r.stdout

    def measure(self, page, change):
        script = self.tmp / "measure.cjs"
        script.write_text(CROP_MEASURE)
        r = subprocess.run([NODE, str(script), playwright_dir(), str(RP), str(page), change["id"],
                            json.dumps(change["targets"]), str(self.out)], capture_output=True, text=True, timeout=300)
        res = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertNotIn("crash", res, res.get("crash"))
        return res

    @staticmethod
    def crop_constants():
        r = subprocess.run([NODE, "-e", "const c = require(process.argv[1]); "
                            "console.log(JSON.stringify([c.CROP_MARGIN, c.CROP_SCALE]))", str(RP / "crops.cjs")],
                           capture_output=True, text=True)
        return json.loads(r.stdout)

    @staticmethod
    def card(text, cid):
        """The inside of change cid's crops slot (figures and notes, no inner div)."""
        m = re.search(r'<div class="rp-rc-crops" data-rc-crops="%s">(.*?)</div>' % cid, text, re.S)
        return m.group(1) if m else None

    def test_crops_cover_the_union_of_targets_plus_margin(self):
        margin, _ = self.crop_constants()
        self.assertGreater(margin, 0)
        spec = self.spec()
        page = self.build(spec)
        boxes, _ = self.crops(page)
        changes = spec["sections"][0]["items"][0]["changes"]
        self.assertEqual(sorted(boxes), sorted(c["id"] for c in changes))
        # alert-color: two targets, and .badge is hidden while it is on, so the union spans both states.
        change = [c for c in changes if c["id"] == "alert-color"][0]
        res = self.measure(page, change)
        for w in ("1280", "390"):
            box, t = boxes["alert-color"][w], res[w]["targets"]
            self.assertTrue(t)
            want = [max(0, min(b[0] for b in t) - margin), max(0, min(b[1] for b in t) - margin),
                    min(int(w), max(b[2] for b in t) + margin), min(res[w]["height"], max(b[3] for b in t) + margin)]
            got = [box["x"], box["y"], box["x"] + box["w"], box["y"] + box["h"]]
            # Contains every target plus the margin (a pixel for rounding), and no more than that.
            self.assertLessEqual(got[0], want[0] + 1e-6, (w, box, want))
            self.assertLessEqual(got[1], want[1] + 1e-6, (w, box, want))
            self.assertGreaterEqual(got[2], want[2] - 1e-6, (w, box, want))
            self.assertGreaterEqual(got[3], want[3] - 1e-6, (w, box, want))
            self.assertLessEqual(box["w"], want[2] - want[0] + 2, (w, box, want))
            self.assertLessEqual(box["h"], want[3] - want[1] + 2, (w, box, want))
            for k in "xywh":
                self.assertIsInstance(box[k], int)

    def test_crops_before_and_after_differ_only_inside_the_box(self):
        _, scale = self.crop_constants()
        spec = self.spec()
        # A change that moves nothing but its targets' pixels. (Bolder totals also widen their
        # column, which shifts the table's other columns: the crop is cut to the targets, as
        # spec §4 says, so that reflow is outside it.)
        change = {"id": "alert-ink", "label": "Darker alert text", "why_html": "<p>i</p>", "targets": [".alert"],
                  "css": ".alert { color: #b42318; }"}
        spec["sections"][0]["items"][0]["changes"].append(change)
        page = self.build(spec)
        # Every file and folder but --out, what is in it, and the folders it sits in.
        files = lambda: {p for p in self.tmp.rglob("*")
                         if self.out not in p.parents and p != self.out and p not in self.out.parents}
        before = files()
        boxes, _ = self.crops(page)
        self.assertEqual(files() - before, set(), "--crops wrote outside its --out folder")
        res = self.measure(page, change)
        for w in ("1280", "390"):
            box, r = boxes["alert-ink"][w], res[w]
            # Every pixel the change moves, on the page as its own page, is inside the box.
            self.assertIsNotNone(r["moved"], w)
            x0, y0, x1, y1 = r["moved"]
            self.assertGreaterEqual(x0, box["x"], (w, r["moved"], box))
            self.assertGreaterEqual(y0, box["y"], (w, r["moved"], box))
            self.assertLessEqual(x1, box["x"] + box["w"], (w, r["moved"], box))
            self.assertLessEqual(y1, box["y"] + box["h"], (w, r["moved"], box))
            # Both crops are that box, at the crop scale, and they show the change.
            self.assertEqual((r["crops"]["width"], r["crops"]["height"]), (box["w"] * scale, box["h"] * scale), w)
            self.assertGreater(r["crops"]["differ"], 0, w)
        for c in spec["sections"][0]["items"][0]["changes"]:
            for state in ("before", "after"):
                for w in ("1280", "390"):
                    self.assertTrue((self.out / ("%s-%s-%s.png" % (c["id"], state, w))).is_file())
        # Nothing but the crops and crops.json in the folder (nothing outside it: checked above).
        self.assertEqual(sorted(p.name for p in self.out.iterdir() if not p.name.endswith(".png")), ["crops.json"])

    def test_a_card_shows_four_crops_when_crops_is_set(self):
        spec = self.spec()
        boxes, _ = self.crops(self.build(spec))
        # Without `crops` the slot stays empty; a folder that is not there yet changes nothing.
        self.assertEqual(self.card(self.build(spec).read_text(), "bold-totals"), "")
        spec["sections"][0]["items"][0]["crops"] = ".proofs/design-review/nowhere"
        self.assertEqual(self.card(self.build(spec).read_text(), "bold-totals"), "")
        spec["sections"][0]["items"][0]["crops"] = ".proofs/design-review/crops"
        text = self.build(spec).read_text()
        for c in spec["sections"][0]["items"][0]["changes"]:
            inner = self.card(text, c["id"])
            self.assertTrue(inner, c["id"])
            imgs = re.findall(r"<img\b[^>]*>", inner)
            self.assertEqual(len(imgs), 4, inner[:400])
            alts = sorted(re.search(r'alt="([^"]*)"', i).group(1) for i in imgs)
            self.assertEqual(alts, sorted("%s: %s, %s px" % (s, html.escape(c["label"]), w)
                                          for s in ("Before", "After") for w in ("1280", "390")))
            for i in imgs:   # each shown at its box's size, never wider than the column
                w = re.search(r'alt="[^"]*, (\d+) px"', i).group(1)
                self.assertIn('width="%d" height="%d"' % (boxes[c["id"]][w]["w"], boxes[c["id"]][w]["h"]), i)
        self.assertNotIn("{{asset:", text)
        self.assertNotIn(str(self.out), text)

    def test_a_target_hidden_at_390_gives_a_note_not_a_crash(self):
        self.snap.write_text(self.snap.read_text().replace(
            "</style>", "@media (max-width: 600px) { .photo { display: none; } }\n</style>", 1))
        spec = self.spec()
        spec["sections"][0]["items"][0]["changes"].append(
            {"id": "photo-ring", "label": "Ring on the photo", "why_html": "<p>r</p>", "targets": [".photo"],
             "css": ".photo { outline: 3px solid #b42318; }"})
        boxes, stdout = self.crops(self.build(spec))
        self.assertEqual(sorted(boxes["photo-ring"]["1280"]), ["h", "w", "x", "y"])
        note = boxes["photo-ring"]["390"]["note"]
        self.assertIn(".photo", note)
        self.assertIn("390", note)
        self.assertIn(note, stdout)
        self.assertTrue((self.out / "photo-ring-after-1280.png").is_file())
        self.assertFalse((self.out / "photo-ring-before-390.png").exists())
        self.assertFalse((self.out / "photo-ring-after-390.png").exists())
        # The other changes still get all four.
        self.assertEqual(sorted(boxes["bold-totals"]), ["1280", "390", "key"])
        spec["sections"][0]["items"][0]["crops"] = ".proofs/design-review/crops"
        inner = self.card(self.build(spec).read_text(), "photo-ring")
        self.assertEqual(len(re.findall(r"<img\b", inner)), 2, inner[:400])
        self.assertIn(html.escape(note), inner)

    def test_crops_of_a_change_edited_since_are_not_shown(self):
        spec = self.spec()
        self.crops(self.build(spec))
        item = spec["sections"][0]["items"][0]
        item["crops"] = ".proofs/design-review/crops"
        item["changes"][0]["css"] = ".total { font-weight: 800; }"
        src, out = self.dir / "s.json", self.tmp / "page.html"
        src.write_text(json.dumps(spec))
        r = subprocess.run([sys.executable, str(BUILD), str(src), "--out", str(out)],
                           capture_output=True, text=True, cwd=str(self.dir))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("change bold-totals changed since its crops were made", r.stderr)
        text = out.read_text()
        self.assertEqual(self.card(text, "bold-totals"), "")
        # The changes left as they were keep theirs, and only the edited one is warned about.
        self.assertEqual(len(re.findall(r"<img\b", self.card(text, "tight-rows"))), 4)
        self.assertEqual(r.stderr.count("changed since its crops were made"), 1, r.stderr)

    def test_set_shoots_the_recommended_changes_together_for_the_critic(self):
        page = self.build()
        r = subprocess.run([sys.executable, str(BUILD), "--crops", str(page), "--out", str(self.out), "--set", "1,3"],
                           capture_output=True, text=True, cwd=str(self.dir), timeout=300)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("with changes 1, 3 on together, for the critic", r.stdout)
        for w in ("1280", "390"):
            self.assertTrue((self.out / ("set-%s.png" % w)).is_file(), w)
        # The whole page as the capture shoots it: renderBase's own shot of the base with them on.
        script = self.tmp / "set.cjs"
        script.write_text(r"""
const fs = require("fs"), path = require("path");
const [pw, rp, page, out] = process.argv.slice(2);
const { chromium } = require(pw);
const { launchChromium } = require(path.join(rp, "launch.cjs"));
const { renderBase, diffMask } = require(path.join(rp, "fidelity.cjs"));
const doc = JSON.parse(fs.readFileSync(page, "utf8").match(/<script type="application\/json" id="rp-rc-base-[^"]*">([\s\S]*?)<\/script>/)[1]);
(async () => {
  const browser = await launchChromium(chromium, process.env);
  const res = {};
  for (const w of [1280, 390]) {
    const on = diffMask(await renderBase(browser, doc, w, ["bold-totals", "alert-color"]), path.join(out, `set-${w}.png`));
    const off = diffMask(await renderBase(browser, doc, w, []), path.join(out, `set-${w}.png`));
    res[w] = { on: on.count, off: off.count };
  }
  await browser.close();
  console.log(JSON.stringify(res));
})();
""")
        m = subprocess.run([NODE, str(script), playwright_dir(), str(RP), str(page), str(self.out)], capture_output=True,
                           text=True, timeout=300)
        res = json.loads(m.stdout)
        for w in ("1280", "390"):
            self.assertEqual(res[w]["on"], 0, res)
            self.assertGreater(res[w]["off"], 0, res)
        bad = subprocess.run([sys.executable, str(BUILD), "--crops", str(page), "--out", str(self.out), "--set", "9"],
                             capture_output=True, text=True, cwd=str(self.dir), timeout=300)
        self.assertEqual(bad.returncode, 2, bad.stdout + bad.stderr)
        self.assertIn("--set: no change 9", bad.stderr)

    def test_a_change_that_makes_the_page_taller_says_so(self):
        # Taller than the frames' floor, so the extra row height shows in the page's height.
        self.snap.write_text(self.snap.read_text().replace("</div></body>", '<div style="height:1200px"></div>\n</div></body>', 1))
        spec = self.spec()
        spec["sections"][0]["items"][0]["changes"].append(
            {"id": "roomy-rows", "label": "Roomier rows", "why_html": "<p>r</p>", "targets": [".rows td"],
             "css": ".rows td { padding: 30px 8px; }"})
        boxes, stdout = self.crops(self.build(spec))
        for w in ("1280", "390"):
            taller = boxes["roomy-rows"][w]["taller"]
            self.assertGreater(taller, 40, boxes["roomy-rows"])
            self.assertIn("note: Change 4 makes the page %d px taller at %s." % (taller, w), stdout)
            self.assertNotIn("taller", boxes["bold-totals"][w])
        spec["sections"][0]["items"][0]["crops"] = ".proofs/design-review/crops"
        inner = self.card(self.build(spec).read_text(), "roomy-rows")
        self.assertIn("Makes the page %d px taller at 390 px." % boxes["roomy-rows"]["390"]["taller"], inner)

    def test_crops_needs_a_refine_page_and_an_out_folder(self):
        r = subprocess.run([sys.executable, str(BUILD), "--crops", str(self.build())], capture_output=True, text=True,
                           cwd=str(self.dir))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--out", r.stderr)
        plain = build("design-review", self.tmp)
        r = subprocess.run([sys.executable, str(BUILD), "--crops", str(plain), "--out", str(self.out)],
                           capture_output=True, text=True, cwd=str(self.dir), timeout=300)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("no Refine preview", r.stderr)
        self.assertFalse(self.out.exists())


class HelperErrors(unittest.TestCase):
    """--crops and --match-preview without node, or with a helper that never finishes: one line
    on stderr and exit 2, never a traceback."""

    def run_both(self):
        out = []
        for name, call in (("crops", lambda: review_page.crops("page.html", "out", "pw")),
                           ("match-preview", lambda: review_page.match_preview("page.html", "1", "shots", "pw"))):
            err = io.StringIO()
            with mock.patch.object(review_page, "find_playwright", return_value="pw"), \
                    contextlib.redirect_stderr(err):
                code = call()
            out.append((name, code, err.getvalue()))
        return out

    def test_no_node(self):
        with mock.patch.object(review_page.shutil, "which", return_value=None):
            for name, code, err in self.run_both():
                self.assertEqual(code, 2, name)
                self.assertTrue(err.startswith(name + ": node is not installed"), err)

    def test_timeout(self):
        def slow(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
        with mock.patch.object(review_page.shutil, "which", return_value="/usr/bin/node"), \
                mock.patch.object(review_page.subprocess, "run", side_effect=slow):
            for name, code, err in self.run_both():
                self.assertEqual(code, 2, name)
                self.assertIn("did not finish in %d seconds" % review_page.HELPER_TIMEOUT, err)
                self.assertTrue(err.startswith(name + ": "), err)

    def test_smoke_timeout_and_no_node(self):
        def slow(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
        for which, run, want in (("/usr/bin/node", slow, "did not finish in %d seconds" % review_page.HELPER_TIMEOUT),
                                 (None, None, "node is not installed")):
            err, out = io.StringIO(), io.StringIO()
            with mock.patch.object(review_page, "find_playwright", return_value="pw"), \
                    mock.patch.object(review_page.shutil, "which", return_value=which), \
                    mock.patch.object(review_page.subprocess, "run", side_effect=run), \
                    mock.patch.object(review_page, "check", return_value=[]), \
                    mock.patch.object(review_page, "warnings", return_value=[]), \
                    contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
                code = review_page.main(["--smoke", "page.html"])
            self.assertEqual(code, 2)
            self.assertEqual(len(err.getvalue().strip().splitlines()), 1, err.getvalue())
            self.assertTrue(err.getvalue().startswith("smoke: "), err.getvalue())
            self.assertIn(want, err.getvalue())
            self.assertEqual(out.getvalue(), "")


class RefineBaseRewrites(unittest.TestCase):
    """What the builder does to a Refine base before the frames get it: viewport-height units
    as --rp-vh, no nested srcdoc, a warning for files from another site, the frames' heights."""

    def test_vh_units_in_styles_and_style_attributes_become_rp_vh(self):
        doc = ('<style>.hero{min-height:100vh}.a{height:calc(50dvh - 2rem);margin-top:-10svh}'
               '.h-100vh{top:.5lvh}.min-h-\\[100vh\\]{x:1}</style>'
               '<div style="height: 30vh" title="100vh"><p>a 100vh page</p></div>')
        out = review_page.vh_to_var(doc)
        self.assertIn("min-height:calc(100 * var(--rp-vh, 1vh))", out)
        self.assertIn("height:calc(calc(50 * var(--rp-vh, 1dvh)) - 2rem)", out)
        self.assertIn("margin-top:calc(-10 * var(--rp-vh, 1svh))", out)
        self.assertIn(".h-100vh{top:calc(.5 * var(--rp-vh, 1lvh))}", out)   # the class name kept
        self.assertIn(".min-h-\\[100vh\\]", out)
        self.assertIn('style="height: calc(30 * var(--rp-vh, 1vh))"', out)
        self.assertIn('title="100vh"', out)                                  # not a style
        self.assertIn("<p>a 100vh page</p>", out)                            # nor the page's words
        self.assertNotIn("vh}", out.replace("1vh))}", ""))

    def test_vh_rewrite_leaves_urls_strings_and_media_queries_alone(self):
        css = ('@font-face{src:url(data:font/woff2;base64,AAAA/12vh+BBBB)}'
               '.a::after{content:"fits 100vh"}.b{background:url("x 3vh.png")}'
               '@media (min-height: 50vh) and (orientation: portrait) { .h{height:100vh} }'
               '@supports (height: 1dvh) { .i{height:50dvh} }/* 100vh */')
        out = review_page._vh_css(css)
        for kept in ("url(data:font/woff2;base64,AAAA/12vh+BBBB)", 'content:"fits 100vh"', 'url("x 3vh.png")',
                     "@media (min-height: 50vh) and (orientation: portrait) {", "@supports (height: 1dvh) {", "/* 100vh */"):
            self.assertIn(kept, out)
        self.assertIn(".h{height:calc(100 * var(--rp-vh, 1vh))}", out)
        self.assertIn(".i{height:calc(50 * var(--rp-vh, 1dvh))}", out)
        doc = ('<style>.h{height:100vh}.f{src:url(data:font/woff2;base64,AAAA/12vh+BBBB)}</style>'
               '<p style="height:10vh; background:url(&quot;data:image/png;base64,QQ12vhQQ&quot;)">a</p>')
        out = review_page.vh_to_var(doc)
        self.assertIn(".h{height:calc(100 * var(--rp-vh, 1vh))}", out)
        self.assertIn("AAAA/12vh+BBBB", out)
        self.assertIn('style="height:calc(10 * var(--rp-vh, 1vh)); background:url(&quot;data:image/png;base64,QQ12vhQQ&quot;)"', out)

    def test_nested_iframe_srcdoc_is_dropped(self):
        doc = '<p>x</p><iframe src="https://e.example/a" srcdoc="&lt;script&gt;parent.x=1&lt;/script&gt;" width="9"></iframe>'
        out = review_page.strip_nested_srcdoc(doc)
        self.assertNotIn("srcdoc", out)
        self.assertIn('<iframe src="https://e.example/a" width="9"></iframe>', out)

    def test_external_loads_name_what_a_published_page_cannot_load(self):
        doc = ('<link rel="stylesheet" href="https://cdn.example/a.css"><link rel="canonical" href="https://x.example/">'
               '<style>@import url("https://cdn.example/b.css"); .x{background:url(https://img.example/c.png)}</style>'
               '<img src="https://img.example/d.png"><a href="https://x.example/page">link</a><img src="data:image/png;base64,AA">')
        self.assertEqual(review_page.external_loads(doc), ["https://cdn.example/a.css", "https://img.example/d.png",
                                                           "https://cdn.example/b.css", "https://img.example/c.png"])

    def build(self, tmp, edit=None):
        shutil.copytree(REFINE, tmp / "refine")
        snap = tmp / "refine" / "before" / "home-snapshot.html"
        if edit:
            snap.write_text(edit(snap.read_text()))
        src, out = tmp / "refine" / "s.json", tmp / "page.html"
        src.write_text((REFINE / "spec.json").read_text())
        r = subprocess.run([sys.executable, str(BUILD), str(src), "--out", str(out), "--no-check"],
                           capture_output=True, text=True, cwd=str(tmp / "refine"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return out.read_text(), r.stderr

    def test_build_warns_about_files_from_another_site(self):
        with tempfile.TemporaryDirectory() as t:
            _, err = self.build(Path(t))
            self.assertNotIn("another site", err)
        with tempfile.TemporaryDirectory() as t:
            _, err = self.build(Path(t), lambda h: h.replace("</head>", '<link rel="stylesheet" href="https://cdn.example/far.css"></head>', 1))
            self.assertIn("warning: item home: the base still loads 1 file from another site (https://cdn.example/far.css), "
                          "which will not load in a published page", err)

    def test_frames_carry_the_capture_viewport_height_and_take_no_taps(self):
        with tempfile.TemporaryDirectory() as t:
            text, _ = self.build(Path(t))
        self.assertIn('data-rc-width="1280" data-rc-height="800"', text)
        self.assertIn('data-rc-width="390" data-rc-height="844"', text)
        css = (RP / "style.css").read_text()
        rule = re.search(r"\.rp-rc-frame \{[^}]*\}", css).group(0)
        self.assertIn("pointer-events:none", rule)
        self.assertEqual(review_page.REFINE_VIEWPORT_H, {1280: 800, 390: 844})

    def test_change_js_items_carry_their_removes(self):
        with tempfile.TemporaryDirectory() as t:
            text, _ = self.build(Path(t))
        spec = json.loads(re.search(r'<script type="application/json" id="rp-spec">(.*?)</script>', text, re.S).group(1))
        items = {i["id"]: i for sec in spec["sections"] for i in sec["items"]}
        self.assertEqual(items["bold-totals"]["removes"], [])
        self.assertEqual(items["alert-color"]["removes"], ["new badge", "! status icon"])

    def test_a_card_says_when_its_change_makes_the_page_taller(self):
        html_ = review_page.crop_figures({"label": "L"}, {"390": {"note": "n", "taller": 140}})
        self.assertIn("Makes the page 140 px taller at 390 px.", html_)

    def test_set_goes_with_crops(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit):
            review_page.main(["--smoke", "page.html", "--set", "1,3"])
        self.assertIn("--set goes with --crops", err.getvalue())


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

FIXTURES = ROOT / "tests" / "fixtures" / "review_page"


@unittest.skipUnless(NODE and playwright_dir(), "Playwright not found")
class DesignChecks(unittest.TestCase):
    """Every mockup in a review page is measured for contrast, tap targets, line length and edges."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.res = cls.smoke(json.loads((FIXTURES / "design_checks.json").read_text()), cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @staticmethod
    def smoke(spec, tmp, name="s"):
        src, out = Path(tmp) / (name + ".json"), Path(tmp) / (name + ".html")
        src.write_text(json.dumps(spec))
        r = subprocess.run([sys.executable, str(BUILD), str(src), "--out", str(out)], capture_output=True, text=True)
        if r.returncode:
            raise AssertionError(r.stdout + r.stderr)
        return review_page.smoke(out)[1]

    def checks(self, variant, width):
        rows = [c for c in self.res["design_checks"] if c["variant"] == variant and c["width"] == width]
        self.assertEqual(len(rows), 1, self.res["design_checks"])
        return rows[0]

    def design_problems(self, variant):
        return [p for p in self.res["problems"] if p.startswith("item 1 (Hero), Variant %s:" % variant)]

    def test_low_contrast_is_reported_with_its_ratio(self):
        c = self.checks("B", 1280)
        gray = [x for x in c["contrast"] if x["text"].startswith("Gray on white")]
        self.assertEqual(len(gray), 1, c["contrast"])
        self.assertAlmostEqual(gray[0]["ratio"], 2.85, places=1)
        self.assertEqual(gray[0]["needed"], 4.5)
        self.assertIn("item 1 (Hero), Variant B: 1 text elements below AA contrast at 1280px", self.res["problems"])

    def test_small_target_at_390(self):
        c = self.checks("B", 390)
        self.assertEqual([(t["w"], t["h"]) for t in c["smallTargets"]], [(30, 30)])
        self.assertTrue(any("tap targets under 44x44 at 390px" in p for p in self.design_problems("B")))

    def test_long_line_at_1280(self):
        c = self.checks("B", 1280)
        self.assertEqual(len(c["longLines"]), 1, c)
        self.assertGreaterEqual(c["longLines"][0]["chars"], 120)
        self.assertTrue(any("over 80 characters at 1280px" in p for p in self.design_problems("B")))

    def test_text_on_gradient_is_unmeasured_not_failed(self):
        c = self.checks("C", 1280)
        self.assertTrue(any(u["text"].startswith("Text on a gradient") for u in c["unmeasured"]), c)
        self.assertEqual(c["contrast"], [])
        self.assertEqual(self.design_problems("C"), [])
        self.assertIn("item 1 (Hero), Variant C: contrast not measured for 1 text elements "
                      "(text over an image or gradient) at 1280px", self.res["notes"])

    def test_text_over_an_image_is_unmeasured_not_failed(self):
        c = self.checks("D", 1280)
        self.assertEqual([u["text"] for u in c["unmeasured"]], ["Text over a picture"], c)
        self.assertEqual(c["unmeasured"][0]["reason"], "contrast: not measured (text over an image or gradient)")
        self.assertEqual(c["contrast"], [])
        self.assertEqual(self.design_problems("D"), [])

    def test_one_option_proposal_is_checked_and_the_pages_own_label_is_not(self):
        rows = [c for c in self.res["design_checks"] if c["item"] == "2" and c["width"] == 1280]
        self.assertEqual([r["variant"] for r in rows], ["proposed"], rows)
        self.assertEqual([x["text"] for x in rows[0]["contrast"]], ["Proposed gray text"])
        self.assertIn("item 2 (One option), Proposed: 1 text elements below AA contrast at 1280px", self.res["problems"])
        self.assertFalse([p for p in self.res["problems"] if p.startswith("item 2") and "Original" in p])

    def test_clean_variant_has_no_design_problems(self):
        for w in (1280, 390):
            c = self.checks("A", w)
            for k in ("contrast", "unmeasured", "smallTargets", "longLines", "edges"):
                self.assertEqual(c[k], [], (w, k, c))
        self.assertEqual(self.design_problems("A"), [])

    def test_off_scale_size_is_a_note(self):
        spec = {"title": "Scale", "project": {"name": "P", "session": "s"}, "decisions": "design-review",
                "items": [{"label": "Hero", "reason_html": "<p>r</p>", "recommended": True,
                           "before_font_sizes": [16, 20, 32],
                           "variants": [{"html": '<div style="font:16px sans-serif"><h1 style="font-size:27px;margin:0">Big</h1>'
                                                 '<p style="margin:0">Body</p></div>'}]}]}
        with tempfile.TemporaryDirectory() as tmp:
            res = self.smoke(spec, tmp)
        notes = [o for c in res["design_checks"] if c["width"] == 1280 for o in c["offScale"]]
        self.assertEqual([(o["text"], o["size"]) for o in notes], [("Big", 27)], res["design_checks"])
        self.assertEqual([p for p in res["problems"] if "scale" in p.lower()], [])
        self.assertTrue([n for n in res["notes"] if "off the page's own scale" in n and "27px" in n], res["notes"])


FR_BOX = "font:16px sans-serif;padding:20px;"
FR_VARIANTS = [
    # A: light gray in oklch on an oklch white: measured, and below AA.
    '<div style="%sbackground:oklch(1 0 0);color:oklch(0.75 0 0)"><p style="margin:0">Pale oklch text</p></div>' % FR_BOX,
    # B: near-black in color() on white: measured and clean.
    '<div style="%sbackground:color(srgb 1 1 1);color:color(srgb 0.07 0.07 0.07)"><p style="margin:0">Dark color() text</p></div>'
    % FR_BOX,
    # C: dark text faded to 30%%: composited, so it fails like the pale gray it looks.
    '<div style="%sbackground:#fff;color:#111"><p style="margin:0;opacity:.3">Faded text</p></div>' % FR_BOX,
    # D: a gradient overlay that ignores the pointer still covers the text.
    '<div style="%sbackground:#fff;color:#111;position:relative"><p style="margin:0">Under a scrim</p>'
    '<div style="position:absolute;inset:0;pointer-events:none;background:linear-gradient(#0008,#0000)"></div></div>'
    % FR_BOX,
    # E: an opaque background inside a faded element: still faded, so not a full-contrast pass.
    '<div style="%sbackground:#fff;color:#111"><div style="opacity:.3"><p style="margin:0;background:#fff;color:#111">'
    'Opaque under a fade</p></div></div>' % FR_BOX,
]


@unittest.skipUnless(NODE and playwright_dir(), "Playwright not found")
class DesignChecksScope(unittest.TestCase):
    """Final review, items 3-5: what the design checks measure and on which pages."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        spec = {"title": "Scope", "project": {"name": "P", "session": "s"}, "decisions": "design-review",
                "items": [{"label": "Colors", "reason_html": "<p>r</p>", "recommended": True, "stack_variants": True,
                           "variants": [{"html": h} for h in FR_VARIANTS]},
                          {"label": "No mockup", "reason_html": "<p>r</p>", "body_html": "<p>Just words</p>"},
                          {"label": "Capture find", "category": "capture", "reason_html": "<p>r</p>",
                           "body_html": "<p>measured numbers</p>"}]}
        cls.dr = DesignChecks.smoke(spec, cls.tmp.name, "dr")
        sg = json.loads(json.dumps(spec))
        sg["decisions"] = "style-guide"
        cls.sg = DesignChecks.smoke(sg, cls.tmp.name, "sg")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def row(self, variant):
        rows = [c for c in self.dr["design_checks"] if c["item"] == "1" and c["variant"] == variant and c["width"] == 1280]
        self.assertEqual(len(rows), 1, self.dr["design_checks"])
        return rows[0]

    def test_oklch_colors_are_measured(self):
        c = self.row("A")
        self.assertEqual([x["text"] for x in c["contrast"]], ["Pale oklch text"], c)
        self.assertLess(c["contrast"][0]["ratio"], 4.5)
        self.assertEqual(c["unmeasured"], [])

    def test_color_function_colors_are_measured_and_clean(self):
        c = self.row("B")
        self.assertEqual((c["contrast"], c["unmeasured"]), ([], []), c)

    def test_a_faded_element_is_composited(self):
        c = self.row("C")
        self.assertEqual([x["text"] for x in c["contrast"]], ["Faded text"], c)

    def test_an_opaque_background_inside_a_faded_element_is_not_a_pass(self):
        c = self.row("E")
        self.assertEqual(c["contrast"], [], c)
        self.assertEqual([(u["text"], u["reason"]) for u in c["unmeasured"]],
                         [("Opaque under a fade", "contrast: not measured (a translucent element over its own background)")], c)

    def test_a_pointer_events_none_overlay_still_covers_the_text(self):
        c = self.row("D")
        self.assertEqual([u["text"] for u in c["unmeasured"]], ["Under a scrim"], c)
        self.assertEqual(c["contrast"], [])

    def test_style_guide_pages_get_no_design_checks(self):
        self.assertEqual(self.sg["design_checks"], [])
        self.assertFalse([p for p in self.sg["problems"] if "contrast" in p], self.sg["problems"])
        self.assertTrue([p for p in self.dr["problems"] if "below AA contrast" in p], self.dr["problems"])

    def test_one_option_item_without_a_mockup_is_a_note(self):
        self.assertIn("item 2: no .rp-mockup, design checks skipped", self.dr["notes"])
        self.assertFalse([n for n in self.dr["notes"] if n.startswith("item 3:")], self.dr["notes"])
        self.assertFalse([n for n in self.sg["notes"] if "rp-mockup" in n], self.sg["notes"])


CR_LINKS = ["Pricing &amp; trial", "Features", "Paths", "Works with AI helpers", "Dependable uptime"]
CR_ROW = ("display:flex;gap:0 18px;font:14px sans-serif;color:#111;background:#fff;padding:0 14px;%s")
CR_LINK = '<a href="#" style="flex:none;white-space:nowrap;padding:14px 0;color:#111">%s</a>'
CR_VARIANTS = [
    # A: the hillock nav (bench run hillock-new, options B and C): one row that scrolls sideways
    # with its scrollbar hidden, so the last link it shows is cut mid-word at the phone's edge.
    '<nav style="%s">%s</nav>' % (CR_ROW % "flex-wrap:nowrap;overflow-x:auto;scrollbar-width:none",
                                  "".join(CR_LINK % t for t in CR_LINKS)),
    # B: the same links allowed to wrap: nothing is cut.
    '<nav style="%s">%s</nav>' % (CR_ROW % "flex-wrap:wrap", "".join(CR_LINK % t for t in CR_LINKS)),
    # C: a card carousel whose next card peeks in: a swipe affordance, a note and never a problem.
    '<div style="display:flex;gap:12px;overflow-x:auto;font:16px sans-serif;color:#111;background:#fff">%s</div>'
    % "".join('<div style="flex:none;width:80%%;padding:16px;border:1px solid #ccc"><h3 style="margin:0">Card %d</h3>'
              '<p style="margin:0">A longer card body.</p></div>' % i for i in (1, 2, 3)),
    # D: the cut row's links sit in a track wider than the scroller (nav > div > a): still the links.
    '<nav style="%s"><div style="display:flex;gap:0 18px;flex:none">%s</div></nav>'
    % (CR_ROW % "overflow-x:hidden", "".join(CR_LINK % t for t in CR_LINKS)),
    # E: hillock option C in the review page's 292px box: the cut link is over half the row wide,
    # but a one-line label is a link, never a carousel card.
    '<nav style="%s">%s</nav>' % (CR_ROW % "overflow-x:auto;scrollbar-width:none",
                                  "".join(CR_LINK % t for t in ["Pricing", "Paths", "Works with AI helpers and agents"])),
    # F: hillock option B in the review page's box: the row ends in the gap after a link, so nothing
    # is partly visible, and the rest of the links sit wholly past the edge with no scrollbar to show it.
    '<nav style="display:flex;gap:0 20px;width:240px;overflow-x:auto;scrollbar-width:none;font:14px sans-serif;'
    'background:#fff">%s</nav>' % "".join(
        '<a href="#" style="flex:none;width:100px;white-space:nowrap;overflow:hidden;padding:14px 0;color:#111">%s</a>' % t
        for t in ["Pricing", "Paths", "Works with AI", "Uptime"]),
]


@unittest.skipUnless(NODE and playwright_dir(), "Playwright not found")
class ClippedRows(unittest.TestCase):
    """A sideways row cut at the phone's edge: the page never scrolls, so nothing else saw it."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        spec = {"title": "Rows", "project": {"name": "P", "session": "s"}, "decisions": "design-review",
                "items": [{"label": "Nav", "reason_html": "<p>r</p>", "recommended": True, "stack_variants": True,
                           "variants": [{"html": h} for h in CR_VARIANTS]}]}
        cls.res = DesignChecks.smoke(spec, cls.tmp.name, "rows")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def row(self, variant, width):
        rows = [c for c in self.res["design_checks"] if c["variant"] == variant and c["width"] == width]
        self.assertEqual(len(rows), 1, self.res["design_checks"])
        return rows[0]

    def cut_problems(self, variant):
        return [p for p in self.res["problems"] if p.startswith("item 1 (Nav), Variant %s:" % variant) and "cut" in p]

    def test_a_cut_nav_row_at_390_is_a_problem(self):
        c = self.row("A", 390)
        self.assertEqual(len(c["clippedRows"]), 1, c)
        cut = c["clippedRows"][0]
        self.assertIn(cut["text"], [t.replace("&amp;", "&") for t in CR_LINKS])
        self.assertTrue(cut["text"].startswith(cut["cut"]) and cut["cut"] != cut["text"], cut)
        self.assertGreater(cut["px"], 0)
        self.assertTrue(cut["hidden"], cut)
        self.assertEqual(self.cut_problems("A"),
                         ['item 1 (Nav), Variant A: 1 row cut at the right edge at 390px ("%s" cut; %d more hidden past it)'
                          % (cut["cut"], len(cut["hidden"]))])

    def test_the_same_row_wrapping_is_clean(self):
        self.assertEqual(self.row("B", 390)["clippedRows"], [])
        self.assertEqual(self.cut_problems("B"), [])

    def test_a_card_carousel_peek_is_a_note_only(self):
        c = self.row("C", 390)
        self.assertEqual(c["clippedRows"], [], c)
        self.assertEqual(len(c["peekRows"]), 1, c)
        self.assertEqual(self.cut_problems("C"), [])
        self.assertTrue([n for n in self.res["notes"] if n.startswith("item 1 (Nav), Variant C:") and "peek" in n],
                        self.res["notes"])

    def test_links_inside_a_wide_track_are_still_cut_items(self):
        c = self.row("D", 390)
        self.assertEqual(len(c["clippedRows"]), 1, c)
        self.assertEqual(c["peekRows"], [])
        self.assertEqual(len(self.cut_problems("D")), 1, self.res["problems"])

    def test_a_one_line_link_wider_than_half_the_row_is_still_cut(self):
        c = self.row("E", 390)
        self.assertEqual(c["peekRows"], [], c)
        self.assertEqual([r["text"] for r in c["clippedRows"]], ["Works with AI helpers and agents"], c)
        self.assertEqual(len(self.cut_problems("E")), 1, self.res["problems"])

    def test_links_wholly_past_the_edge_are_hidden_items(self):
        c = self.row("F", 390)
        self.assertEqual(c["peekRows"], [], c)
        self.assertEqual(len(c["clippedRows"]), 1, c)
        r = c["clippedRows"][0]
        self.assertEqual((r["text"], r["cut"], r["hidden"]), (None, None, ["Works with AI", "Uptime"]), r)
        self.assertEqual(self.cut_problems("F") + [p for p in self.res["problems"]
                                                   if p.startswith("item 1 (Nav), Variant F:") and "hides" in p],
                         ['item 1 (Nav), Variant F: 1 row hides 2 items past the right edge at 390px '
                          '("Works with AI", "Uptime")'])

    def test_a_carousels_hidden_cards_are_not_hidden_items(self):
        c = self.row("C", 390)
        self.assertEqual(c["clippedRows"], [], c)

    def test_the_cut_row_at_1280_where_it_fits_is_clean(self):
        for v in ("A", "D"):
            c = self.row(v, 1280)
            self.assertEqual((c["clippedRows"], c["peekRows"]), ([], []), c)
        self.assertFalse([p for p in self.res["problems"] if "cut" in p and "1280px" in p], self.res["problems"])


class DesignerFields(unittest.TestCase):
    """Option roles, the element inventory and the critic's scores on a design-review item."""
    SC = {"hierarchy": 4, "action": 5, "fold": 3, "grouping": 4, "fit": 4, "care": 5}

    @staticmethod
    def page(items):
        spec = {"title": "D", "project": {"name": "P", "session": "s"}, "decisions": "design-review",
                "items": items}
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "s.json"
            p.write_text(json.dumps(spec))
            return review_page.page(review_page.load_spec(p))

    def variants(self, **second):
        return [{"html": "<p>a</p>", "role": "careful", "scores": self.SC},
                dict({"html": "<p>b</p>", "role": "bold", "scores": self.SC}, **second)]

    def error(self, items):
        with self.assertRaises(review_page.SpecError) as cm:
            self.page(items)
        return str(cm.exception)

    def test_roles_render_as_labels(self):
        v = self.variants()
        v.append({"html": "<p>c</p>", "role": "step-up", "scores": self.SC})
        html = self.page([{"label": "Hero", "variants": v}])
        for label in ("Careful", "Step up", "Bold"):
            self.assertIn('<span class="rp-vrole">%s</span>' % label, html)
        self.assertIn("unknown role", self.error([{"label": "Hero", "variants": self.variants(role="loud")}]))

    def test_removed_element_is_marked(self):
        inv = [{"element": "Hero title", "status": "kept"}, {"element": "Promo bar", "status": "removed",
                                                              "reason": "competes with the call to action"}]
        html = self.page([{"label": "Hero", "variants": [{"html": "<p>a</p>", "inventory": inv}]}])
        self.assertIn('<tr class="rp-inv-removed"><td>Promo bar</td><td>removed</td>'
                      '<td>competes with the call to action</td></tr>', html)
        self.assertIn('<tr class="rp-inv-kept"><td>Hero title</td>', html)
        self.assertIn(".rp-inv tr.rp-inv-removed td { color:var(--rp-deny); }", html)
        self.assertIn("status", self.error([{"label": "Hero", "variants": [
            {"html": "x", "inventory": [{"element": "a", "status": "gone"}]}]}]))

    def test_brand_row_carries_a_brand_tag(self):
        inv = [{"element": "Acme logo", "status": "kept", "brand": True},
               {"element": "Hero title", "status": "kept", "brand": False}]
        html = self.page([{"label": "Hero", "variants": [{"html": "<p>a</p>", "inventory": inv}]}])
        self.assertIn('<tr class="rp-inv-kept rp-inv-brand"><td>Acme logo <span class="rp-inv-brandtag">Brand</span>'
                      '</td><td>kept</td>', html)
        self.assertIn('<tr class="rp-inv-kept"><td>Hero title</td>', html)
        self.assertEqual(html.count('<span class="rp-inv-brandtag">'), 1)
        self.assertIn(".rp-inv-brandtag {", html)

    def test_brand_must_be_a_boolean(self):
        for bad in ("yes", 1, None):
            with self.subTest(bad=bad):
                msg = self.error([{"label": "Hero", "variants": [
                    {"html": "x", "inventory": [{"element": "Logo", "status": "kept", "brand": bad}]}]}])
                self.assertIn("brand", msg)
                self.assertIn("true or false", msg)

    def test_inventory_missing_a_captured_element_counts_as_removed(self):
        before = {"id": "hero", "tag": "section", "label": "Hero", "top": 0, "left": 0, "width": 1000, "height": 400,
                  "elements": [{"kind": "heading", "text": "  Hero   title ", "tag": "h1", "top": 0, "left": 0,
                                "width": 10, "height": 10},
                               {"kind": "image", "text": "", "tag": "img", "top": 0, "left": 0, "width": 10, "height": 10},
                               {"kind": "text", "text": "Free shipping", "tag": "p", "top": 0, "left": 0,
                                "width": 10, "height": 10}]}
        inv = [{"element": "hero title", "status": "kept"}, {"element": "Newsletter", "status": "moved"}]
        html = self.page([{"label": "Hero", "before_sections": before,
                           "variants": [{"html": "<p>a</p>", "inventory": inv}]}])
        self.assertIn("<td>Free shipping</td><td>removed — no reason given</td>", html)
        self.assertIn("<td>image</td><td>removed — no reason given</td>", html)
        self.assertIn("<td>Newsletter</td><td>moved</td>", html)
        self.assertEqual(html.count("removed — no reason given"), 2)

    def test_scores_render_and_unscored_says_not_scored(self):
        html = self.page([{"label": "Hero", "variants": [
            {"html": "<p>a</p>", "scores": self.SC}, {"html": "<p>b</p>"}]}])
        self.assertIn('<div class="rp-scores">Hierarchy <b>4</b> · Action <b>5</b> · Fold <b>3</b> · '
                      'Grouping <b>4</b> · Fit <b>4</b> · Care <b>5</b></div>', html)
        self.assertIn('<div class="rp-scores rp-unscored">Not scored</div>', html)
        for bad in (0, 6, 3.5, "4"):
            msg = self.error([{"label": "Hero", "variants": [{"html": "a", "scores": dict(self.SC, fold=bad)}]}])
            self.assertIn("fold", msg)
            self.assertIn("1 to 5", msg)

    def test_before_scores_render_once_above_the_options(self):
        before = {"hierarchy": 2, "action": 3, "fold": 2, "grouping": 3, "fit": 4, "care": 5}
        html = self.page([{"label": "Hero", "before_scores": before, "variants": self.variants()}])
        row = ('<div class="rp-scores rp-before-scores"><span class="rp-scores-label">Current page</span> '
               'Hierarchy <b>2</b> · Action <b>3</b> · Fold <b>2</b> · Grouping <b>3</b> · Fit <b>4</b> · Care <b>5</b></div>')
        self.assertEqual(html.count(row), 1)
        self.assertLess(html.index(row), html.index('class="rp-gallery'))
        single = self.page([{"label": "Hero", "before_scores": before, "body_html": "<p>x</p>", "scores": self.SC}])
        self.assertEqual(single.count(row), 1)

    def test_before_scores_out_of_range_is_a_spec_error(self):
        for bad in (0, 6, 3.5, "4"):
            with self.subTest(bad=bad):
                msg = self.error([{"label": "Hero", "before_scores": dict(self.SC, fold=bad),
                                   "variants": self.variants()}])
                self.assertEqual(msg, "item 1, current page: score fold must be a whole number from 1 to 5, got %r"
                                 % (bad,))
        self.assertIn("unknown score", self.error([{"label": "Hero", "before_scores": {"vibe": 3},
                                                    "variants": self.variants()}]))
        self.assertIn("must be an object", self.error([{"label": "Hero", "before_scores": [3],
                                                        "variants": self.variants()}]))

    def test_no_before_scores_renders_no_current_page_row(self):
        html = self.page([{"label": "Hero", "variants": self.variants()}])
        self.assertNotIn("rp-before-scores", html.split("<style>")[0] + html.split("</style>")[-1])
        self.assertNotIn("Current page</span>", html)

    def test_recommending_an_unscored_variant_is_a_spec_error(self):
        msg = self.error([{"label": "Hero", "variants": [
            {"html": "<p>a</p>", "scores": self.SC}, {"html": "<p>b</p>", "recommended": True}]}])
        self.assertEqual(msg, "item 1: variant B is recommended but has no scores")
        self.assertIn("variant B", self.error([{"label": "Hero", "selected": "B", "variants": [
            {"html": "<p>a</p>", "scores": self.SC}, {"html": "<p>b</p>"}]}]))

    def test_one_variant_item_needs_no_role_or_scores(self):
        self.page([{"label": "Hero", "variants": [{"html": "<p>a</p>", "recommended": True}]}])
        html = self.page([{"label": "Hero", "scores": self.SC,
                           "inventory": [{"element": "Promo", "status": "removed", "reason": "noise"}]}])
        self.assertIn("Hierarchy <b>4</b>", html)
        self.assertIn('<tr class="rp-inv-removed"><td>Promo</td>', html)
        self.assertNotIn("<span class=\"rp-vrole\">", html)
        self.assertNotIn("Not scored", html)

    def test_judged_by_line(self):
        v = self.variants()
        self.assertIn("Judged by a separate helper",
                      self.page([{"label": "Hero", "judged_by": "helper", "variants": v}]))
        self.assertIn("Checked by the designer itself",
                      self.page([{"label": "Hero", "judged_by": "self", "variants": v}]))
        html = self.page([{"label": "Hero", "variants": v}])
        self.assertNotIn("Judged by", html)
        self.assertNotIn("Checked by the designer", html)
        self.assertIn("judged_by", self.error([{"label": "Hero", "judged_by": "robot", "variants": v}]))

    def test_judged_by_with_nothing_scored_recommending_is_a_spec_error(self):
        msg = self.error([{"label": "Hero", "judged_by": "helper", "variants": [
            {"html": "<p>a</p>"}, {"html": "<p>b</p>", "recommended": True}]}])
        self.assertEqual(msg, "item 1: variant B is recommended but has no scores")

    def test_judged_by_with_nothing_scored_says_not_scored_on_every_variant(self):
        html = self.page([{"label": "Hero", "judged_by": "helper", "variants": [
            {"html": "<p>a</p>"}, {"html": "<p>b</p>"}]}])
        self.assertEqual(html.count('<div class="rp-scores rp-unscored">Not scored</div>'), 2)

    def test_no_judged_by_and_nothing_scored_builds_as_before(self):
        html = self.page([{"label": "Hero", "variants": [
            {"html": "<p>a</p>"}, {"html": "<p>b</p>", "recommended": True}]}])
        self.assertNotIn('<div class="rp-scores', html)


    def test_item_without_variants_shows_no_score_row_unless_scored_or_judged(self):
        # Task 6 fix round: a copy-edit item and a capture item carry neither scores nor judged_by.
        for item in ({"label": "Line 3", "body_html": "<p>old</p><p>new</p>", "recommended": True},
                     {"label": "Mid-word break", "category": "capture", "body_html": "<p>fix</p>"}):
            with self.subTest(item=item["label"]):
                self.assertNotIn('<div class="rp-scores', self.page([item]))

    def test_one_option_item_with_judged_by_and_no_scores_says_not_scored(self):
        html = self.page([{"label": "Hero", "judged_by": "self",
                           "body_html": '<div class="rp-mockup"><p>a</p></div>'}])
        self.assertEqual(html.count('<div class="rp-scores rp-unscored">Not scored</div>'), 1)

    def test_copy_edit_example_has_no_score_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertNotIn("Not scored", build("copy-edit", tmp).read_text())

    # Final review, item 2: before_sections, before_font_sizes, role and judged_by of the wrong
    # shape are one-line spec errors, never a Python crash.
    def test_before_sections_must_be_one_section_object(self):
        sec = {"label": "Hero", "elements": [{"kind": "heading", "text": "Hi"}]}
        for bad in ([sec], "Hero", 3, {"label": "Hero"}, {"label": "Hero", "elements": "x"}):
            with self.subTest(bad=bad):
                msg = self.error([{"label": "Hero", "before_sections": bad, "variants": self.variants()}])
                self.assertEqual(msg, "item 1: before_sections must be one captured section object with an "
                                      "elements list (from measures.json), got %s" % type(bad).__name__)

    def test_before_font_sizes_must_be_a_list_of_numbers(self):
        for bad in (16, "16", [16, "20"], [True], {"a": 1}):
            with self.subTest(bad=bad):
                msg = self.error([{"label": "Hero", "before_font_sizes": bad, "variants": self.variants()}])
                self.assertIn("item 1: before_font_sizes must be a list of numbers", msg)
        self.page([{"label": "Hero", "before_font_sizes": [16, 20.5], "variants": self.variants()}])

    def test_unhashable_role_and_judged_by_are_spec_errors(self):
        self.assertIn("unknown role", self.error([{"label": "Hero", "variants": self.variants(role=["bold"])}]))
        self.assertIn("unknown role", self.error([{"label": "Hero", "role": {"a": 1}, "body_html": "x"}]))
        for bad in (["helper"], {"by": "self"}):
            with self.subTest(bad=bad):
                self.assertIn("judged_by", self.error([{"label": "Hero", "judged_by": bad, "variants": self.variants()}]))


class BeforeFromMeasures(unittest.TestCase):
    """Final review, item 7b: before_sections and before_font_sizes can name the capture's measures.json."""
    SEC = {"id": "", "tag": "section", "label": "Hero", "top": 0, "left": 0, "width": 1280, "height": 500,
           "elements": [{"kind": "heading", "text": "Big title", "tag": "h1", "top": 0, "left": 0,
                         "width": 100, "height": 40}]}

    def measures(self):
        other = dict(self.SEC, label="Footer", elements=[])
        res = [{"page": "home", "state": "default", "viewport": "390",
                "measures": {"sections": [dict(self.SEC, width=390)], "fontSizes": [14, 28]}},
               {"page": "home", "state": "default", "viewport": "1280",
                "measures": {"sections": [self.SEC, other], "fontSizes": [16, 20, 40]}},
               {"page": "about", "state": "default", "viewport": "1280", "error": "boom"}]
        return {"results": res, "errors": [], "failures": []}

    def load(self, item):
        spec = {"title": "D", "project": {"name": "P", "session": "s"}, "decisions": "design-review",
                "items": [dict({"label": "Hero", "variants": [{"html": "<p>a</p>", "inventory": []}]}, **item)]}
        with tempfile.TemporaryDirectory() as tmp:
            cap = Path(tmp) / "capture"
            cap.mkdir()
            (cap / "measures.json").write_text(json.dumps(self.measures()))
            p = Path(tmp) / "s.json"
            p.write_text(json.dumps(spec))
            loaded = review_page.load_spec(p)
            return loaded, review_page.page(loaded)

    def error(self, item):
        with self.assertRaises(review_page.SpecError) as cm:
            self.load(item)
        return str(cm.exception)

    def test_before_sections_from_measures_resolves_to_the_section(self):
        spec, html = self.load({"before_sections": {"from": "capture/measures.json", "page": "home",
                                                    "width": 1280, "label": "Hero"}})
        self.assertEqual(spec["items"][0]["before_sections"], self.SEC)
        self.assertIn("<td>Big title</td><td>removed — no reason given</td>", html)

    def test_before_font_sizes_from_measures_resolves_to_the_list(self):
        spec, _ = self.load({"before_font_sizes": {"from": "capture/measures.json", "page": "home", "width": 1280}})
        self.assertEqual(spec["items"][0]["before_font_sizes"], [16, 20, 40])

    def test_a_label_not_found_lists_the_labels_it_has(self):
        msg = self.error({"before_sections": {"from": "capture/measures.json", "page": "home", "width": 1280,
                                              "label": "Heroes"}})
        self.assertEqual(msg, "item 1: before_sections: no section labeled 'Heroes' in capture/measures.json "
                              "(home at 1280); it has: Hero, Footer")

    def test_a_page_or_width_not_found_says_what_was_captured(self):
        msg = self.error({"before_font_sizes": {"from": "capture/measures.json", "page": "home", "width": 1440}})
        self.assertIn("item 1: before_font_sizes: no capture of home at 1440 in capture/measures.json", msg)
        self.assertIn("home at 390, home at 1280", msg)

    def test_a_missing_measures_file_is_a_spec_error(self):
        msg = self.error({"before_sections": {"from": "nope/measures.json", "page": "home", "width": 1280,
                                              "label": "Hero"}})
        self.assertIn("item 1: before_sections: nope/measures.json not found", msg)

@unittest.skipUnless(NODE and playwright_dir(), "Playwright not found")
class InventoryFit(unittest.TestCase):
    def test_long_inventory_rows_do_not_scroll_the_page_sideways(self):
        long = "Promotional banner with a very long caption " * 3
        inv = [{"element": long + str(i), "status": "removed" if i % 2 else "kept",
                "reason": "a long reason that also runs on and on " * 2} for i in range(5)]
        sc = {"hierarchy": 4, "action": 5, "fold": 3, "grouping": 4, "fit": 4, "care": 5}
        spec = {"title": "Fit", "project": {"name": "P", "session": "s"}, "decisions": "design-review",
                "items": [{"label": "Hero", "judged_by": "helper", "reason_html": "<p>r</p>", "recommended": True,
                           "variants": [
                               {"html": '<h1 style="margin:0">Alpha</h1><p>one</p>', "role": "careful",
                                "scores": sc, "inventory": inv, "recommended": True},
                               {"html": '<div style="display:flex;gap:30px"><b>Beta</b><i>two</i><u>x</u></div>',
                                "role": "bold", "scores": sc, "inventory": inv}]}]}
        with tempfile.TemporaryDirectory() as tmp:
            res = DesignChecks.smoke(spec, tmp)
        self.assertEqual([p for p in res["problems"] if "sideways" in p], [], res["problems"])


def abs_box(h1="", p="", btn="", color="#111"):
    """A 400px-tall mockup whose elements sit at fixed fractions of its box, so the near-copy
    signature is known in advance. Each argument is a 'left,top,width,height' tuple in percent.
    Each block is painted, so the signature measures its box, not just its few words of text."""
    def at(tag, g, text, extra=""):
        l, t, w, h = g
        return ('<%s style="position:absolute;margin:0;left:%s%%;top:%s%%;width:%s%%;height:%s%%;'
                'background:#eef2f7;%s">%s</%s>' % (tag, l, t, w, h, extra, text, tag))
    inner = at("h1", h1, "Title", "font-size:20px;") + at("p", p, "Body text here", "font-size:16px;") \
        + at("button", btn, "Go", "font-size:16px;")
    return '<div style="position:relative;height:400px;background:#fff;color:%s">%s</div>' % (color, inner)


STACKED = dict(h1=(5, 5, 60, 10), p=(5, 25, 60, 20), btn=(5, 60, 30, 12))
TWO_COL = dict(h1=(55, 40, 40, 10), p=(55, 55, 40, 20), btn=(5, 5, 30, 12))
# The same arrangement as STACKED with every block resized and nudged, as a reproduction of a
# real page is (the two-app trial scored such mockups 0.33 to 0.54 against the capture).
STACKED_RESIZED = dict(h1=(5, 5, 60, 16), p=(5, 30, 60, 25), btn=(5, 66, 26, 16))


@unittest.skipUnless(NODE and playwright_dir(), "Playwright not found")
class NearCopy(unittest.TestCase):
    """A variant that only recolors another variant, or the page it replaces, is not a second option."""

    @staticmethod
    def spec(variants, **item):
        return {"title": "Near", "project": {"name": "P", "session": "s"}, "decisions": "design-review",
                "items": [dict({"label": "Hero", "reason_html": "<p>r</p>", "recommended": True,
                                "stack_variants": True,
                                "variants": [{"html": v} for v in variants]}, **item)]}

    def run_smoke(self, spec):
        with tempfile.TemporaryDirectory() as tmp:
            return DesignChecks.smoke(spec, tmp)

    @staticmethod
    def before(**g):
        """A before_sections object (the capture's shape) at the given fractions of a 1000 x 400 section."""
        kinds = {"h1": ("heading", "h1"), "p": ("text", "p"), "btn": ("button", "button")}
        els = [{"kind": kinds[k][0], "text": k, "tag": kinds[k][1], "top": 1000 + round(4 * t),
                "left": round(10 * l), "width": round(10 * w), "height": round(4 * h)}
               for k, (l, t, w, h) in g.items()]
        return {"id": "", "tag": "section", "label": "Hero", "top": 1000, "height": 400, "left": 0, "width": 1000,
                "elements": els}

    @staticmethod
    def centered_before(**g):
        """A before_sections with no left/width, its elements in a 600px column starting at x=200."""
        kinds = {"h1": ("heading", "h1"), "p": ("text", "p"), "btn": ("button", "button")}
        els = [{"kind": kinds[k][0], "text": k, "tag": kinds[k][1], "top": 1000 + round(4 * t),
                "left": 200 + round(6 * l), "width": round(6 * w), "height": round(4 * h)}
               for k, (l, t, w, h) in g.items()]
        return {"id": "", "tag": "section", "label": "Hero", "top": 1000, "height": 400, "elements": els}

    def copies(self, res):
        return [(c["a"], c["b"]) for c in res["near_copies"]]

    def test_identical_variants_flagged(self):
        res = self.run_smoke(self.spec([abs_box(color="#111", **STACKED), abs_box(color="#900", **STACKED)]))
        self.assertEqual(self.copies(res), [("A", "B")], res["near_copies"])
        self.assertGreaterEqual(res["near_copies"][0]["score"], 0.85)
        self.assertEqual(res["near_copies"][0]["item"], "1")
        self.assertTrue([p for p in res["problems"]
                         if p.startswith("item 1 (Hero): Variant A and Variant B are near-copies (")], res["problems"])

    def test_same_arrangement_resized_is_flagged(self):
        res = self.run_smoke(self.spec([abs_box(**STACKED), abs_box(**STACKED_RESIZED)]))
        self.assertEqual(self.copies(res), [("A", "B")], res["near_copies"])
        self.assertEqual([(s["a"], s["b"]) for s in res["layout_scores"]], [("A", "B")])

    def test_same_arrangement_resized_matches_the_page(self):
        res = self.run_smoke(self.spec([abs_box(**STACKED_RESIZED), abs_box(**TWO_COL)],
                                       before_sections=self.before(**STACKED)))
        self.assertEqual(self.copies(res), [("A", "before")], res["near_copies"])

    def test_different_layouts_pass(self):
        res = self.run_smoke(self.spec([abs_box(**STACKED), abs_box(**TWO_COL)]))
        self.assertEqual(res["near_copies"], [])
        self.assertFalse([p for p in res["problems"] if "near-copies" in p])

    def test_variant_matching_before_sections_flagged(self):
        res = self.run_smoke(self.spec([abs_box(color="#900", **STACKED), abs_box(**TWO_COL)],
                                       before_sections=self.before(**STACKED)))
        self.assertEqual(self.copies(res), [("A", "before")], res["near_copies"])
        self.assertTrue([p for p in res["problems"]
                         if p.startswith("item 1 (Hero): Variant A and the current page are near-copies (")], res["problems"])

    def test_one_variant_item_has_no_pair_check(self):
        res = self.run_smoke(self.spec([abs_box(**STACKED)]))
        self.assertEqual(res["near_copies"], [])

    def test_one_option_item_is_still_compared_with_the_page(self):
        spec = self.spec([], body_html='<div class="rp-mockup">%s</div>' % abs_box(**STACKED),
                         before_sections=self.before(**STACKED))
        res = self.run_smoke(spec)
        self.assertEqual(self.copies(res), [("proposed", "before")], res["near_copies"])
        # Final review, item 4: a one-option fix keeps its layout by design, so this is a note.
        self.assertFalse([p for p in res["problems"] if "near-copies" in p], res["problems"])
        self.assertTrue([n for n in res["notes"]
                         if n.startswith("item 1 (Hero): Proposed and the current page are near-copies (")
                         and "expected for a one-option fix" in n], res["notes"])

    def test_one_variant_item_is_compared_with_the_page_too(self):
        res = self.run_smoke(self.spec([abs_box(**STACKED)], before_sections=self.before(**STACKED)))
        self.assertEqual(self.copies(res), [("A", "before")], res["near_copies"])
        # Ruling 30: one variant is a one-option fix too, so its page near-copy is a note.
        self.assertFalse([p for p in res["problems"] if "near-copies" in p], res["problems"])
        self.assertTrue([n for n in res["notes"]
                         if n.startswith("item 1 (Hero): Variant A and the current page are near-copies (")
                         and "expected for a one-option fix" in n], res["notes"])

    def test_centered_column_without_left_and_width_still_matches(self):
        full = dict(h1=(0, 5, 100, 10), p=(0, 25, 100, 20), btn=(0, 60, 50, 12))
        res = self.run_smoke(self.spec([abs_box(**full), abs_box(**TWO_COL)],
                                       before_sections=self.centered_before(**full)))
        self.assertEqual(self.copies(res), [("A", "before")], res["near_copies"])

    def test_before_sections_are_compared_on_any_kind_of_page_but_pairs_are_not(self):
        spec = self.spec([abs_box(**STACKED), abs_box(**STACKED)], before_sections=self.before(**STACKED))
        spec["decisions"] = "style-guide"
        res = self.run_smoke(spec)
        self.assertEqual(self.copies(res), [("A", "before"), ("B", "before")], res["near_copies"])

    def test_options_on_other_kinds_of_page_are_not_flagged(self):
        spec = self.spec([abs_box(**STACKED), abs_box(**STACKED)])
        spec["decisions"] = "style-guide"
        res = self.run_smoke(spec)
        self.assertEqual(res["near_copies"], [])

    def test_kind_classifier_matches_the_captures(self):
        def grab(path, start, end):
            text = (ROOT / path).read_text()
            i = text.index(start)
            return re.sub(r"\s+", "", text[i:text.index(end, i)])
        a = grab("skills/visual-qa/scripts/capture.cjs", "const kindOf", "const elementSel")
        b = grab("shared/review_page/signature.cjs", "const kindOf", "const elementSel")
        self.assertEqual(a, b)
        a = grab("skills/visual-qa/scripts/capture.cjs", "const elementSel", "// What an element")
        b = grab("shared/review_page/signature.cjs", "const elementSel", "// What an element")
        self.assertEqual(a, b)
        a = grab("skills/visual-qa/scripts/capture.cjs", "// Layout boxes:", "// End of layout boxes.")
        b = grab("shared/review_page/signature.cjs", "// Layout boxes:", "// End of layout boxes.")
        self.assertEqual(a, b)

    def test_layout_list_from_a_new_capture_is_the_before_signature(self):
        # A section whose `layout` says the heading's text sits in the right half, while its block
        # box (`elements`) spans the row: the layout wins, so a right-column option matches it.
        right = '<div style="position:relative;height:400px"><h1 style="position:absolute;margin:0;left:55%;top:10%;font-size:20px">Title</h1></div>'
        sec = self.before(h1=(0, 10, 100, 10))
        sec["layout"] = [{"kind": "heading", "top": 1040, "left": 550, "width": 400, "height": 40}]
        res = self.run_smoke(self.spec([right], before_sections=sec))
        score = res["layout_scores"][0]["score"]
        del sec["layout"]
        old = self.run_smoke(self.spec([right], before_sections=sec))["layout_scores"][0]["score"]
        self.assertGreater(score, old)


# The near-copy labeled set (Task 7b). Realistic flow-layout mockups, not absolute boxes: the
# metric has to hold on what a designer actually writes. Each case is one item with two options.
LB_FONT = "font-family:Arial,Helvetica,sans-serif;color:%s;background:#fff"
LB_IMG = ("data:image/svg+xml;utf8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='800' height='450'%3E"
          "%3Crect width='800' height='450' fill='%23dbeafe'/%3E%3C/svg%3E")
LB_H1 = "Plan a calmer week with one simple list"
LB_P = ("Bring your tasks, notes and reminders into one quiet place, so the next step is always clear "
        "and nothing slips through the gaps between your apps.")


def lb_buttons(s=1.0, justify="center", accent="#1d4ed8"):
    btn = ('<a href="#" style="display:inline-block;padding:14px 24px;border-radius:8px;font-size:16px;'
           'text-decoration:none;%s">%s</a>')
    return ('<div style="display:flex;gap:%dpx;justify-content:%s;margin:0 0 %dpx">%s%s</div>'
            % (round(16 * s), justify, round(32 * s),
               btn % ("background:%s;color:#fff" % accent, "Start free"),
               btn % ("border:2px solid %s;color:%s" % (accent, accent), "See how it works")))


def lb_img(h=320, w="100%"):
    return '<img alt="" src="%s" style="display:block;width:%s;height:%dpx;object-fit:cover">' % (LB_IMG, w, h)


LB_BADGE = ('<span class="badge" style="%sfont-size:12px;background:#eef2f7;color:#111827;padding:2px 6px;'
            'border-radius:4px">New</span>')


def lb_stacked(s=1.0, ink="#111827", accent="#1d4ed8", h1=44, pmax=620, buttons_last=False, badge=None):
    """A centered hero: heading, line, two buttons, picture. `s` scales every gap and padding.
    `badge`: a small "New" badge, "top" (centered above the heading) or "corner" (top right)."""
    head = '<h1 style="font-size:%dpx;line-height:1.15;margin:0 0 %dpx">%s</h1>' % (h1, round(16 * s), LB_H1)
    if badge == "top":
        head = '<div style="margin:0 0 12px">%s</div>' % (LB_BADGE % "display:inline-block;") + head
    elif badge == "corner":
        head = LB_BADGE % "position:absolute;right:16px;top:16px;" + head
    para = ('<p style="font-size:18px;line-height:1.5;max-width:%dpx;margin:0 auto %dpx">%s</p>'
            % (pmax, round(24 * s), LB_P))
    btns = lb_buttons(s, accent=accent)
    body = head + para + (lb_img() + '<div style="height:%dpx"></div>' % round(24 * s) + btns
                          if buttons_last else btns + lb_img())
    return ('<div style="%s;padding:%dpx;text-align:center;position:relative">%s</div>'
            % (LB_FONT % ink, round(48 * s), body))


def lb_split(image_first=False):
    text = ('<div><h1 style="font-size:40px;line-height:1.15;margin:0 0 16px">%s</h1>'
            '<p style="font-size:18px;line-height:1.5;margin:0 0 24px">%s</p>%s</div>'
            % (LB_H1, LB_P, lb_buttons(justify="flex-start")))
    cols = (lb_img(), text) if image_first else (text, lb_img())
    return ('<div style="%s;padding:48px;display:grid;grid-template-columns:1fr 1fr;gap:40px;align-items:center">'
            '%s%s</div>' % (LB_FONT % "#111827", cols[0], cols[1]))


def lb_text(column=False):
    """Heading and paragraph, full width or in a 57% column on the right."""
    inner = ('<h1 style="font-size:40px;line-height:1.15;margin:0 0 16px">%s</h1>'
             '<p style="font-size:18px;line-height:1.5;margin:0">%s %s</p>' % (LB_H1, LB_P, LB_P))
    if column:
        inner = '<div style="margin-left:43%%">%s</div>' % inner
    return '<div style="%s;padding:48px">%s</div>' % (LB_FONT % "#111827", inner)


def lb_features(grid=False):
    items = "".join('<div><h3 style="font-size:22px;margin:0 0 8px">Feature %s</h3>'
                    '<p style="font-size:16px;line-height:1.5;margin:0 0 24px">%s</p></div>' % (n, LB_P)
                    for n in ("one", "two", "three"))
    wrap = ('<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:32px">%s</div>' if grid
            else '<div>%s</div>') % items
    return ('<div style="%s;padding:48px"><h2 style="font-size:32px;margin:0 0 24px">Everything in one place</h2>'
            '%s</div>' % (LB_FONT % "#111827", wrap))


def lb_card(picture=True):
    """Text beside a placeholder picture (a painted div, no <img>), or the text alone."""
    pic = '<div style="flex:0 0 40%;min-height:220px;background:#d1d5db;border-radius:8px"></div>' if picture else ""
    return ('<div style="%s;padding:32px;display:flex;gap:24px;align-items:center">%s<div style="flex:1">'
            '<h3 style="font-size:24px;margin:0 0 8px">Two columns</h3>'
            '<p style="font-size:16px;line-height:1.5;margin:0">%s</p></div></div>'
            % (LB_FONT % "#111827", pic, LB_P))


# name: (option A, option B, a near-copy?)
LABELED = {
    "recolor_only": (lb_stacked(), lb_stacked(ink="#7c2d12", accent="#c2410c"), True),
    "spacing_x1_1": (lb_stacked(), lb_stacked(s=1.1), True),
    "spacing_x1_35": (lb_stacked(), lb_stacked(s=1.35), True),
    "text_reflowed_slightly": (lb_stacked(), lb_stacked(pmax=560), True),
    "same_plus_one_small_badge": (lb_stacked(), lb_stacked(badge="corner"), True),
    "small_badge_moved_to_a_corner": (lb_stacked(badge="top"), lb_stacked(badge="corner"), True),
    "bigger_heading_and_moved_buttons": (lb_stacked(), lb_stacked(h1=72, buttons_last=True), False),
    "text_column_vs_full_width": (lb_text(), lb_text(column=True), False),
    "mirrored_split": (lb_split(), lb_split(image_first=True), False),
    "stacked_vs_split": (lb_stacked(), lb_split(), False),
    "stacked_vs_grid": (lb_features(), lb_features(grid=True), False),
    "placeholder_picture_vs_text_alone": (lb_card(), lb_card(picture=False), False),
}
# Each labeled score must clear the cut by this much, so the labels hold with room to spare.
LABEL_MARGIN = 0.15


def near_copy_cut():
    text = (RP / "signature.cjs").read_text()
    return float(re.search(r"const NEAR_COPY = ([0-9.]+);", text).group(1))


@unittest.skipUnless(NODE and playwright_dir(), "Playwright not found")
class NearCopyLabeled(unittest.TestCase):
    """The labeled set: what must and must not read as a near-copy, each with margin, both orders."""

    @classmethod
    def setUpClass(cls):
        # Each case twice: (A, B) as item 2k+1 and (B, A) as item 2k+2.
        items = [{"label": name, "reason_html": "<p>r</p>", "stack_variants": True,
                  "variants": [{"html": x}, {"html": y}]}
                 for name, (a, b, _) in LABELED.items() for (x, y) in ((a, b), (b, a))]
        items[0]["recommended"] = True
        spec = {"title": "Labeled", "project": {"name": "P", "session": "s"}, "decisions": "design-review",
                "items": items}
        with tempfile.TemporaryDirectory() as tmp:
            cls.res = DesignChecks.smoke(spec, tmp)
        cls.cut = near_copy_cut()

    def score(self, num):
        rows = [s for s in self.res.get("layout_scores", []) if s["item"] == num and s["b"] != "before"]
        self.assertEqual(len(rows), 1, self.res.get("layout_scores"))
        return rows[0]["score"]

    def check(self, name):
        flag = LABELED[name][2]
        k = list(LABELED).index(name)
        scores = []
        for num in (str(2 * k + 1), str(2 * k + 2)):
            score = self.score(num)
            scores.append(score)
            flagged = [c for c in self.res["near_copies"] if c["item"] == num]
            if flag:
                self.assertGreaterEqual(score, self.cut + LABEL_MARGIN, f"{name} #{num}: {score} vs cut {self.cut}")
                self.assertEqual(len(flagged), 1, self.res["near_copies"])
            else:
                self.assertLessEqual(score, self.cut - LABEL_MARGIN, f"{name} #{num}: {score} vs cut {self.cut}")
                self.assertEqual(flagged, [], self.res["near_copies"])
        self.assertEqual(scores[0], scores[1], f"{name}: the two orders differ")

    def test_recolor_only_is_flagged(self):
        self.check("recolor_only")

    def test_spacing_only_x1_1_is_flagged(self):
        self.check("spacing_x1_1")

    def test_spacing_only_x1_35_is_flagged(self):
        self.check("spacing_x1_35")

    def test_slightly_reflowed_text_is_flagged(self):
        self.check("text_reflowed_slightly")

    def test_same_plus_one_small_badge_is_flagged(self):
        self.check("same_plus_one_small_badge")

    def test_small_badge_moved_to_a_corner_is_flagged(self):
        self.check("small_badge_moved_to_a_corner")

    def test_bigger_heading_and_moved_buttons_pass(self):
        self.check("bigger_heading_and_moved_buttons")

    def test_text_column_vs_full_width_passes(self):
        self.check("text_column_vs_full_width")

    def test_mirrored_split_passes(self):
        self.check("mirrored_split")

    def test_stacked_vs_split_passes(self):
        self.check("stacked_vs_split")

    def test_stacked_vs_grid_passes(self):
        self.check("stacked_vs_grid")

    def test_placeholder_picture_beside_text_vs_text_alone_passes(self):
        self.check("placeholder_picture_vs_text_alone")


@unittest.skipUnless(NODE, "node not found")
class NearCopyMetric(unittest.TestCase):
    """similarity() on hand-made signatures: symmetric, 1 for identical, and insensitive to spacing."""

    @staticmethod
    def sim(pairs):
        js = ("const { similarity } = require(%s);\nconst pairs = %s;\n"
              "console.log(JSON.stringify(pairs.map(([a, b]) => [similarity(a, b), similarity(b, a)])));"
              % (json.dumps(str(RP / "signature.cjs")), json.dumps(pairs)))
        r = subprocess.run(["node", "-e", js], capture_output=True, text=True)
        if r.returncode:
            raise AssertionError(r.stderr)
        return json.loads(r.stdout)

    def test_symmetric_and_identical_is_one(self):
        e = lambda k, x, y, w, h: {"kind": k, "x": x, "y": y, "w": w, "h": h}
        hero = [e("heading", 0.1, 0.05, 0.8, 0.14), e("text", 0.2, 0.21, 0.6, 0.08),
                e("button", 0.38, 0.33, 0.11, 0.06), e("button", 0.51, 0.33, 0.11, 0.06),
                e("image", 0.05, 0.43, 0.9, 0.52)]
        spaced = [dict(x, y=x["y"] * 1.35) for x in hero]
        mirrored = [e("image", 0, 0.1, 0.45, 0.6), e("heading", 0.55, 0.2, 0.45, 0.1), e("text", 0.55, 0.35, 0.45, 0.1)]
        mirrored_b = [dict(x, x=1 - x["x"] - x["w"]) for x in mirrored]
        # Repeated kinds: the tied-pair walk depends on which side goes first (review probe:
        # 0.24 one way, 0.35 the other, before both directions were averaged).
        rep_a = [e("text", 0.1, 0.1, 0.8, 0.05), e("heading", 0.1, 0.2, 0.8, 0.1),
                 e("text", 0.1, 0.35, 0.3, 0.05), e("text", 0.1, 0.45, 0.8, 0.2)]
        rep_b = [e("heading", 0.1, 0.1, 0.8, 0.1), e("text", 0.1, 0.25, 0.8, 0.2),
                 e("text", 0.1, 0.5, 0.3, 0.05), e("text", 0.1, 0.6, 0.8, 0.05)]
        (same, spacing, mirror, rep) = self.sim([[hero, hero], [hero, spaced], [mirrored, mirrored_b], [rep_a, rep_b]])
        self.assertAlmostEqual(rep[0], rep[1], places=9)
        self.assertAlmostEqual(same[0], 1.0, places=6)
        self.assertAlmostEqual(spacing[0], spacing[1], places=9)
        self.assertAlmostEqual(mirror[0], mirror[1], places=9)
        self.assertGreater(spacing[0], 0.95)
        self.assertLess(mirror[0], 0.2)

    def test_full_bleed_section_with_centered_content_matches_a_mockup_that_fills_its_box(self):
        # Astro trial, fresh capture: the page's hero sits in a 1024px container centered in a
        # 1280px section (x 0.10 to 0.90); a mockup reproducing it fills its box (0.02 to 0.98).
        e = lambda k, x, y, w, h: {"kind": k, "x": x, "y": y, "w": w, "h": h}
        page = [e("text", 0.43, 0.13, 0.14, 0.02), e("heading", 0.14, 0.15, 0.73, 0.11),
                e("text", 0.21, 0.27, 0.59, 0.07), e("link", 0.37, 0.35, 0.14, 0.04),
                e("link", 0.52, 0.35, 0.12, 0.04), e("image", 0.10, 0.45, 0.80, 0.48)]
        mock = [dict(x, x=0.5 + (x["x"] - 0.5) * 1.2, w=x["w"] * 1.2, y=x["y"] * 0.6) for x in page]
        [(score, _)] = self.sim([[mock, page]])
        self.assertGreater(score, 0.9)

    def test_a_short_line_just_above_a_heading_reads_before_it(self):
        # A 20px eyebrow 16px above a heading, in a tall section: two rows, not one.
        e = lambda k, x, y, w, h: {"kind": k, "x": x, "y": y, "w": w, "h": h}
        page = [e("text", 0.43, 0.130, 0.14, 0.017), e("heading", 0.14, 0.143, 0.73, 0.11)]
        mock = [e("text", 0.43, 0.06, 0.14, 0.02), e("heading", 0.14, 0.10, 0.73, 0.12)]
        [(score, _)] = self.sim([[mock, page]])
        self.assertGreater(score, 0.9)

    def test_a_narrower_box_does_not_read_as_a_size_change(self):
        # Vue trial: type keeps its px size while the picture scales with the box, so the same hero
        # in a 1046px box has text-to-picture shares about (1046/1280)^2 of the page's.
        e = lambda k, x, y, w, h: {"kind": k, "x": x, "y": y, "w": w, "h": h}
        page = [e("heading", 0.20, 0.13, 0.59, 0.09), e("text", 0.26, 0.23, 0.48, 0.03),
                e("button", 0.34, 0.29, 0.15, 0.03), e("link", 0.51, 0.29, 0.15, 0.03),
                e("image", 0.03, 0.37, 0.94, 0.54)]
        k = 1280 / 1046
        box = [dict(x, x=0.5 + (x["x"] - 0.5) * k, w=x["w"] * k) if x["kind"] != "image" else x for x in page]
        js = ("const { similarityParts } = require(%s);\nconsole.log(JSON.stringify(similarityParts(%s, %s)));"
              % (json.dumps(str(RP / "signature.cjs")), json.dumps(box), json.dumps(page)))
        r = subprocess.run(["node", "-e", js], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertGreater(json.loads(r.stdout)["size"], 0.97)

    def test_empty_signature_scores_zero(self):
        self.assertEqual(self.sim([[[], []]]), [[0, 0]])


if __name__ == "__main__":
    unittest.main()
