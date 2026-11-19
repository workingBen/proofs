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
const state = JSON.parse(process.argv[3]);
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
        self.assertEqual(text, "[working-log questions v1.2 — answers]\n"
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
                 "questions": [{"qid": "a"}, {"qid": "a"}]}, "qid")]
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

    def test_custom_decisions_override_a_preset(self):
        p = self.tmp / "s.json"
        p.write_text(json.dumps({"title": "x", "decisions": {"preset": "copy-edit", "mark_read": True},
                                 "items": [{"label": "a"}]}))
        text = review_page.page(review_page.load_spec(p))
        self.assertIn("Mark as read", text)
        self.assertIn("✓ Use Edit", text)


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
