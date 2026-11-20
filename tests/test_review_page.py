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


@unittest.skipUnless(NODE, "node is not installed")
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

    def test_design_review_defaults_to_first_variant(self):
        text = self.export("design-review", {"items": {"1": {"s": "accept-comment", "c": "x"}}})
        self.assertIn("1. Article card layout — ACCEPT WITH COMMENT (Use Selected: Variant A) — COMMENT: x", text)

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
        self.assertIn('<span class="rp-where">Acme app · <b class="rp-session">articles-redesign</b>'
                      '<span class="rp-pb-x"> · acme/app</span></span></div>', dr)
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


def playwright_dir():
    return review_page.find_playwright(None)


@unittest.skipUnless(NODE and playwright_dir(), "Playwright not found (set PROOFS_PLAYWRIGHT)")
class ClickThrough(unittest.TestCase):
    """Drive every example in real Chromium: decisions, variants, comments, read
    switch, export, reload persistence, clipboard fallback, images, no sideways scroll."""

    def test_every_example(self):
        with tempfile.TemporaryDirectory() as tmp:
            for spec in sorted(EXAMPLES.glob("*.json")):
                page = build(spec.stem, tmp)
                ok, res = review_page.smoke(page)
                self.assertTrue(ok, "%s: %s" % (spec.name, res))

    def test_design_review_export_after_clicks(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok, res = review_page.smoke(build("design-review", tmp))
            self.assertTrue(ok, res)
            self.assertEqual(res["export"], "[Articles Index — Design Review]\n"
                                            "1. Article card layout — REVISE — READ — COMMENT: smoke comment\n"
                                            "2. Read More button placement — PENDING")


if __name__ == "__main__":
    unittest.main()
