"""Send to Claude (Proofs 1.8.0).

Answers saved to a page's database start no turn, so the session that published the
page sat idle until the reader pasted anyway. Every page that saves answers now has a
Send to Claude button beside Copy: it waits for Saved, then posts a short summary with
the comments capability's sendToClaude, which wakes the publishing session. The page
cannot read the reply (comments are write-only), so a republish is the confirmation:
the next version says "Claude picked up your answers".

--smoke cannot reach claude.ai, so it stubs window.claude.use("comments") and drives
the button itself; these tests read what it found.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_answers_db import BUILD, TEXT_Q, build_example, build_spec, review_page  # noqa: E402
from test_review_page import NODE, playwright_dir  # noqa: E402

RP = Path(__file__).resolve().parent.parent / "shared" / "review_page"

PURE = r"""
const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8");
const spec = JSON.parse(html.match(/<script type="application\/json" id="rp-spec">([\s\S]*?)<\/script>/)[1]);
const code = html.match(/<script>\n([\s\S]*?)\n<\/script>/)[1];
const m = { exports: {} };
new Function("module", code)(m);
const E = m.exports;
const bytes = (s) => Buffer.byteLength(s, "utf8");
const one = { sec: { s1: { ans: { pick: "A" } } } };
const big = { sec: { s1: { ans: { pick: "A" } } }, extra: "word \u{1F600} ".repeat(2000) + "\u0007bell" };
const now = Date.UTC(2026, 10, 24, 21, 10);
const sentAt = new Date(Date.UTC(2026, 10, 24, 21, 1)).toISOString();
process.stdout.write(JSON.stringify({
  one: E.sendText(spec, one), none: E.sendText(spec, {}),
  big: E.sendText(spec, big), bigBytes: bytes(E.sendText(spec, big)),
  newer: E.pickupNote({ sentAt, fromVersion: "old" }, spec, now),
  fresh: E.pickupNote({ sentAt, fromVersion: spec.page_version }, spec, Date.UTC(2026, 10, 24, 21, 2)),
  stale: E.pickupNote({ sentAt, fromVersion: spec.page_version }, spec, now),
  nothing: E.pickupNote(null, spec, now), version: spec.page_version }));
"""


@unittest.skipUnless(NODE, "node is not installed")
class SendText(unittest.TestCase):
    """The text sent is a short summary under 4 KiB, not the whole export."""

    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            page = build_spec(dict(TEXT_Q, version="v7", project=dict(TEXT_Q["project"], session="Sess")), tmp)
            drv = Path(tmp) / "d.cjs"
            drv.write_text(PURE)
            r = subprocess.run([NODE, str(drv), str(page)], capture_output=True, text=True)
            if r.returncode:
                raise AssertionError(r.stderr)
            cls.res = json.loads(r.stdout)

    def test_summary_names_the_session_version_and_answered_ids(self):
        self.assertEqual(self.res["one"],
                         "Sess page v7: answered pick (1 of 2). Read proofs-answers on this artifact.")
        self.assertIn("nothing answered yet (0 of 2)", self.res["none"])

    def test_anything_else_is_added_and_the_whole_text_stays_under_4_kib(self):
        self.assertLess(self.res["bigBytes"], 4096)
        self.assertIn("\n\nAnything else: word", self.res["big"])
        self.assertTrue(self.res["big"].endswith("…"))
        self.assertNotIn("\u0007", self.res["big"])  # control characters make sendToClaude refuse the text

    def test_pickup_note_after_a_send(self):
        newer = self.res["newer"]
        self.assertEqual(newer["tone"], "ok")
        self.assertTrue(newer["clear"])
        self.assertRegex(newer["text"], r"^Claude picked up your answers \(sent \d{1,2}:\d\d\s?[AP]M, now v7\)$")
        self.assertIn("This page updates when Claude has read your answers", self.res["fresh"]["text"])
        self.assertFalse(self.res["fresh"]["clear"])
        self.assertEqual(self.res["stale"]["text"],
                         "Not picked up yet. The session may be busy or closed; Copy still works.")
        self.assertIsNone(self.res["nothing"])


WAIT_PROBE = r"""
const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8");
const spec = JSON.parse(html.match(/<script type="application\/json" id="rp-spec">([\s\S]*?)<\/script>/)[1]);
const code = html.match(/<script>\n([\s\S]*?)\n<\/script>/)[1];
const m = { exports: {} };
new Function("module", code)(m);
const sentAt = new Date(Date.UTC(2026, 10, 24, 21, 0)).toISOString();
const at = (min) => m.exports.pickupNote({ sentAt, fromVersion: spec.page_version }, spec, Date.UTC(2026, 10, 24, 21, min));
process.stdout.write(JSON.stringify({ wait: spec.send_wait_ms, at6: at(6).text, at11: at(11).text }));
"""


@unittest.skipUnless(NODE, "node is not installed")
class SendWaitSetting(unittest.TestCase):
    """The wait before "Not picked up yet" is the PROOFS_SEND_WAIT_MIN setting, baked into the page."""

    def probe(self, values, spec=TEXT_Q):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp).resolve()
            proj, home = tmp / "proj", tmp / "home"
            (proj / ".claude").mkdir(parents=True)
            home.mkdir()
            (proj / ".claude" / "settings.json").write_text(json.dumps({"env": values}))
            src, out = proj / "p.json", proj / "p.html"
            src.write_text(json.dumps(spec))
            env = {k: v for k, v in os.environ.items() if not k.startswith("PROOFS_")}
            env.update(HOME=str(home), CLAUDE_CONFIG_DIR=str(home / ".claude"))
            r = subprocess.run([sys.executable, str(BUILD), str(src), "--out", str(out)], cwd=proj, env=env,
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            (tmp / "d.cjs").write_text(WAIT_PROBE)
            r = subprocess.run([NODE, str(tmp / "d.cjs"), str(out)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            return json.loads(r.stdout)

    def test_the_default_wait_is_five_minutes(self):
        got = self.probe({})
        self.assertEqual(got["wait"], 5 * 60000)
        self.assertTrue(got["at6"].startswith("Not picked up yet"))

    def test_a_ten_minute_setting_waits_ten_minutes_before_saying_not_picked_up(self):
        got = self.probe({"PROOFS_SEND_WAIT_MIN": "10"})
        self.assertEqual(got["wait"], 10 * 60000)
        self.assertIn("This page updates when Claude has read your answers", got["at6"])
        self.assertTrue(got["at11"].startswith("Not picked up yet"))


class BuilderNote(unittest.TestCase):
    def test_build_prints_the_capabilities_to_publish_with(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, out = Path(tmp) / "p.json", Path(tmp) / "p.html"
            src.write_text(json.dumps(TEXT_Q))
            r = subprocess.run([sys.executable, str(BUILD), str(src), "--out", str(out)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('publish with capabilities: {"db": {}, "comments": {}}', r.stdout)
            self.assertEqual(review_page.CAPABILITIES, {"db": {}, "comments": {}})

    def test_every_bar_has_one_hidden_send_button_beside_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("questions", "session", "log", "design-review", "copy-edit", "qa-checklist"):
                html = build_example(name, tmp).read_text()
                tags = re.findall(r'<button[^>]*data-send[^>]*>', html)
                self.assertEqual(len(tags), 1, name)
                self.assertIn("hidden", tags[0], name)  # shown only once the comments capability answers
                self.assertEqual(len(re.findall(r'<div[^>]*data-send-msg', html)), 1, name)


NONE_MSG = "Answer something first: Send sends your saved answers."

NOTHING_DRIVER = r"""
const { chromium } = require(process.argv[2]);
const { launchChromium } = require(process.argv[3]);
const file = "file://" + process.argv[4];
function install() {
  window.__rows = {};
  const db = { collection: () => ({
    get: async () => ({ docs: [] }),
    doc: (id) => ({ set: async (d) => { window.__rows[id] = d; }, delete: async () => { delete window.__rows[id]; } }),
  }) };
  const comments = { canSendToClaude: async () => "available", anchorFor: async () => ({}),
                     sendToClaude: async () => ({}) };
  window.claude = { use: (n) => new Promise((r) => setTimeout(() => r(n === "db" ? db : n === "comments" ? comments : null), 20)) };
}
(async () => {
  const browser = await launchChromium(chromium, process.env);
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.addInitScript(install);
  await page.goto(file);
  await page.waitForTimeout(300);
  const btn = page.locator("[data-send]");
  const st = async () => ({ hidden: await btn.isHidden(), disabled: await btn.isDisabled(),
    msg: await page.locator("[data-send-msg]").evaluate((el) => (el.hidden ? "" : el.textContent)),
    sync: await page.evaluate(() => document.body.getAttribute("data-rp-sync")) });
  const out = { errors };
  out.start = await st();
  if (await page.locator('.q[data-qid="pick"]').count()) {
    await page.locator('.q[data-qid="pick"] input[value="B"]').check();
    await page.waitForTimeout(400);
    out.answered = await st();
    // The page's own Clear button (it asks first), which ends with an immediate save.
    page.on("dialog", (d) => d.accept());
    await page.locator("#rp-clear").click();
    await page.waitForTimeout(400);
    out.cleared = await st();
  }
  if (await page.locator("[data-extra]").count()) {
    await page.locator("[data-extra]").fill("one more thing");
    await page.waitForTimeout(1400);
    out.extra_only = await st();
    await page.locator("[data-extra]").fill("");
    await page.waitForTimeout(1400);
    out.extra_cleared = await st();
  }
  await browser.close();
  console.log(JSON.stringify(out));
})().catch((e) => { console.log(JSON.stringify({ crash: String(e && e.stack || e) })); process.exit(1); });
"""


@unittest.skipUnless(NODE and playwright_dir(), "Playwright not found")
class SendStaysOffUntilAnswered(unittest.TestCase):
    """Send tapped with nothing answered woke the session for nothing (2026-11-26)."""

    @staticmethod
    def drive(make_page):
        with tempfile.TemporaryDirectory() as tmp:
            page = make_page(tmp)
            script = Path(tmp) / "d.cjs"
            script.write_text(NOTHING_DRIVER)
            r = subprocess.run([NODE, str(script), playwright_dir(), str(RP / "launch.cjs"), str(page)],
                               capture_output=True, text=True, timeout=180)
            res = json.loads(r.stdout.strip().splitlines()[-1])
        assert "crash" not in res, res
        assert res["errors"] == [], res
        return res

    @classmethod
    def setUpClass(cls):
        cls.res = cls.drive(lambda tmp: build_spec(TEXT_Q, tmp))
        cls.log = cls.drive(lambda tmp: build_example("log", tmp))  # has the "Anything else" box

    def test_send_off_with_nothing_answered(self):
        s = self.res["start"]
        self.assertFalse(s["hidden"])
        self.assertTrue(s["disabled"])
        self.assertEqual(s["msg"], NONE_MSG)

    def test_send_turns_on_after_first_answer_saved(self):
        a = self.res["answered"]
        self.assertFalse(a["disabled"])
        self.assertEqual(a["msg"], "")
        self.assertEqual(a["sync"], "saved")

    def test_clearing_the_last_answer_turns_it_off_again(self):
        c = self.res["cleared"]
        self.assertTrue(c["disabled"])
        self.assertEqual(c["msg"], NONE_MSG)

    def test_anything_else_alone_counts(self):
        self.assertTrue(self.log["start"]["disabled"])
        self.assertEqual(self.log["start"]["msg"], NONE_MSG)
        self.assertFalse(self.log["extra_only"]["disabled"])
        self.assertTrue(self.log["extra_cleared"]["disabled"])


@unittest.skipUnless(NODE and playwright_dir(), "Playwright not found")
class SmokeDrivesTheButton(unittest.TestCase):
    """--smoke stubs the comments capability and drives Send to Claude on every page kind."""

    def test_states_wait_for_saved_and_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("session", "questions", "design-review"):
                with self.subTest(page=name):
                    page = build_example(name, tmp)
                    ok, res = review_page.smoke(str(page))
                    self.assertTrue(ok, res.get("problems"))
                    s = res["send_to_claude"]
                    self.assertTrue(s["absent_hidden"])  # no runtime: no button at all
                    self.assertTrue(s["no_session"]["disabled"])
                    self.assertEqual(s["no_session"]["msg"], "This page's Claude session isn't listening; use Copy")
                    self.assertTrue(s["nothing_answered"]["disabled"])  # a listening session is not enough
                    self.assertEqual(s["nothing_answered"]["msg"], NONE_MSG)
                    self.assertFalse(s["available"]["disabled"])     # re-checked when the page is shown again
                    self.assertEqual(s["sent_while_saving"], 0)      # held until Saved
                    self.assertEqual(s["sync_at_send"], "saved")
                    self.assertLess(s["text_bytes"], 4096)
                    self.assertIn(json.loads(page.read_text().split('id="rp-spec">')[1].split("</script>")[0])
                                  ["page_version"], s["text"])
                    self.assertTrue(s["text_has_answered_id"], s["text"])
                    self.assertTrue(s["sent_msg"].startswith("Sent. This page updates when Claude has read your answers"))
                    self.assertFalse(s["consent"]["disabled"])
                    self.assertIn("Allow commenting when asked, then tap again", s["consent"]["msg"])
                    self.assertEqual(s["unavailable_msg"], "Nothing was sent; use Copy.")
                    self.assertTrue(s["picked_up"].startswith("Claude picked up your answers (sent "))
                    self.assertEqual(s["not_picked_up"],
                                     "Not picked up yet. The session may be busy or closed; Copy still works.")


if __name__ == "__main__":
    unittest.main()
