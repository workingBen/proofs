"""The header's sync indicator and event-driven saving (Proofs 1.6.9).

The bar of every page that saves shows Saved, Saving… or Not saved yet while the page
has a database, and nothing when it has none. Taps save at once, typing is debounced,
and leaving the page flushes; a change that never reached the store is kept in
localStorage and pushed on the next load. The browser tests mock the claude.ai runtime
(window.claude.use("db")) as test_answers_db does, with writes that can be held, failed
or left hanging.
"""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_answers_db import BUILD, RP, TEXT_Q, build_example, build_spec  # noqa: E402
from test_review_page import NODE, playwright_dir  # noqa: E402


@unittest.skipUnless(NODE, "node is not installed")
class TypedAnswerIsTheAnswer(unittest.TestCase):
    """A text-box-only question stores what was typed as `answer`, not as `note`."""

    DRIVER = r"""
const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8");
const spec = JSON.parse(html.match(/<script type="application\/json" id="rp-spec">([\s\S]*?)<\/script>/)[1]);
const code = html.match(/<script>\n([\s\S]*?)\n<\/script>/)[1];
const m = { exports: {} };
new Function("module", code)(m);
const E = m.exports;
const st = { sec: { s1: { ans: { pick: "A" }, notes: { why: "because\nreasons", pick: "a note" } } } };
const now = new Date(Date.UTC(2026, 10, 24, 12, 0));
const docs = E.answerDocs(spec, st);
const back = E.applyAnswerDocs(spec, {}, Object.values(docs));
const old = E.applyAnswerDocs(spec, {}, [{ id: "why", section: "s1", kind: "question", answer: null, note: "old way" }]);
process.stdout.write(JSON.stringify({ docs, same: E.exportText(spec, back, now) === E.exportText(spec, st, now),
  old: E.exportText(spec, old, now) }));
"""

    def test_typed_answer_is_stored_as_answer_and_old_rows_still_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            page = build_spec(TEXT_Q, tmp)
            drv = Path(tmp) / "d.cjs"
            drv.write_text(self.DRIVER)
            r = subprocess.run([NODE, str(drv), str(page)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            res = json.loads(r.stdout)
            why = res["docs"]["s1.why"]
            self.assertEqual((why["answer"], why["note"]), ("because\nreasons", ""))
            self.assertEqual(res["docs"]["s1.pick"]["note"], "a note")  # a note on an option question stays a note
            self.assertTrue(res["same"])
            self.assertIn("Q why (raised r1) | Why?\n  -> old way\n", res["old"])

    def test_answers_command_prints_the_same_export_for_both_row_shapes(self):
        with tempfile.TemporaryDirectory() as tmp:
            page = build_spec(TEXT_Q, tmp)
            outs = []
            for shape in ({"answer": "because", "note": ""}, {"answer": None, "note": "because"}):
                rows = Path(tmp) / ("rows-%d" % len(outs)) / "proofs-answers"
                rows.mkdir(parents=True)
                body = {"id": "why", "section": "s1", "kind": "question", "read": False,
                        "updated_at": "2026-11-24T20:01:00.000Z"}
                body.update(shape)
                (rows / "s1.why.json").write_text(json.dumps(body))
                r = subprocess.run([sys.executable, str(BUILD), "--answers", str(page), "--rows", str(rows.parent)],
                                   capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)
                outs.append(r.stdout)
            self.assertEqual(outs[0], outs[1])
            self.assertIn("Q why (raised r1) | Why?\n  -> because\n", outs[0])


MOCK = r"""
const { chromium } = require(process.argv[2]);
const { launchChromium } = require(process.argv[3]);
const file = "file://" + process.argv[4];
const scenario = process.argv[5];
const shots = process.argv[6] || "";
// The mocked runtime. window.__mode decides what each set does: "ok" stores it, "hold"
// waits for window.__release(), "hang" never settles, "fail:<code>" rejects with that code.
function install({ seed, runtime, mode }) {
  window.__rows = JSON.parse(JSON.stringify(seed));
  window.__sets = 0;
  window.__mode = mode || "ok";
  window.__held = [];
  window.__release = () => { const h = window.__held; window.__held = []; h.forEach((f) => f()); };
  if (runtime === "absent") return;
  const db = {
    collection: (c) => ({
      get: async () => ({ docs: Object.keys(window.__rows).map((id) => ({ id, exists: true,
        data: () => JSON.parse(JSON.stringify(window.__rows[id])) })) }),
      doc: (id) => ({ set: (data) => {
        window.__sets++;
        const copy = JSON.parse(JSON.stringify(data));
        const m = window.__mode;
        if (m === "hang") return new Promise(() => {});
        if (m.startsWith("fail:")) return Promise.reject({ code: m.slice(5), message: "mock " + m });
        if (m === "hold") return new Promise((r) => window.__held.push(() => { window.__rows[id] = copy; r(); }));
        window.__rows[id] = copy;
        return Promise.resolve();
      } }),
    }),
  };
  window.claude = { use: (name) => new Promise((r) => setTimeout(() => r(runtime === "null" ? null : db), 30)) };
}
(async () => {
  const browser = await launchChromium(chromium, process.env);
  const errors = [];
  async function open(opts, ctx, viewport) {
    ctx = ctx || await browser.newContext({ viewport: viewport || { width: 1280, height: 800 } });
    const page = await ctx.newPage();
    page.on("pageerror", (e) => errors.push(e.message));
    await page.addInitScript(install, Object.assign({ seed: {}, runtime: "db" }, opts));
    await page.goto(file);
    await page.waitForTimeout(250);
    return { ctx, page };
  }
  const sync = (page) => page.evaluate(() => {
    const el = document.querySelector("span[data-sync]");
    if (!el) return { missing: true };
    return { hidden: el.hidden || getComputedStyle(el).display === "none", state: el.getAttribute("data-state") || "",
             text: el.innerText.trim(), live: el.getAttribute("aria-live"), svg: !!el.querySelector("svg"),
             sets: window.__sets };
  });
  const out = {};
  if (scenario === "none") {
    for (const runtime of ["absent", "null"]) {
      const a = await open({ runtime });
      await a.page.locator('[data-note="why"]').fill("typed");
      await a.page.locator('.q[data-qid="pick"] input[value="B"]').check();
      await a.page.waitForTimeout(1200);
      out[runtime] = await sync(a.page);
      await a.ctx.close();
    }
  } else if (scenario === "flow") {
    const a = await open({});
    out.loaded = await sync(a.page);
    await a.page.locator('[data-note="why"]').pressSequentially("abc", { delay: 20 });
    out.typing = await sync(a.page);
    await a.page.waitForTimeout(1300);
    out.typed = await sync(a.page);
    // A tap saves at once, without the debounce.
    await a.page.locator('.q[data-qid="pick"] input[value="B"]').check();
    await a.page.waitForTimeout(120);
    out.tapped = Object.assign(await sync(a.page),
      { row: await a.page.evaluate(() => (window.__rows["s1.pick"] || {}).answer) });
    // A write in flight shows Saving…
    await a.page.evaluate(() => { window.__mode = "hold"; });
    await a.page.locator('.q[data-qid="pick"] input[value="A"]').check();
    await a.page.waitForTimeout(120);
    out.held = await sync(a.page);
    await a.page.evaluate(() => { window.__mode = "ok"; window.__release(); });
    await a.page.waitForTimeout(120);
    out.released = await sync(a.page);
    // A failing store: Not saved yet, retried with backoff, then Saved when it recovers.
    await a.page.evaluate(() => { window.__mode = "fail:unavailable"; });
    await a.page.locator('.q[data-qid="pick"] input[value="B"]').check();
    await a.page.waitForTimeout(300);
    out.failed = await sync(a.page);
    await a.page.waitForTimeout(3500);
    out.retried = await sync(a.page);
    await a.page.evaluate(() => { window.__mode = "ok"; });
    await a.page.waitForTimeout(5000);
    out.recovered = Object.assign(await sync(a.page),
      { row: await a.page.evaluate(() => window.__rows["s1.pick"].answer) });
    // Leaving or hiding the page flushes typing at once, not after the debounce.
    for (const how of ["pagehide", "visibilitychange", "blur"]) {
      const before = await a.page.evaluate(() => window.__sets);
      await a.page.locator('[data-note="why"]').fill("flush " + how);
      await a.page.evaluate((how) => {
        if (how === "blur") document.querySelector('[data-note="why"]').blur();
        else if (how === "pagehide") window.dispatchEvent(new Event("pagehide"));
        else {
          Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" });
          document.dispatchEvent(new Event("visibilitychange"));
        }
      }, how);
      await a.page.waitForTimeout(60);
      out["flush_" + how] = { wrote: (await a.page.evaluate(() => window.__sets)) > before,
                              row: await a.page.evaluate(() => window.__rows["s1.why"].answer) };
      await a.page.evaluate(() => { delete document.visibilityState; });
    }
    if (shots) {
      for (const w of [1280, 390]) {
        await a.page.setViewportSize({ width: w, height: 800 });
        await a.page.evaluate(() => window.scrollTo(0, 0));
        await a.page.screenshot({ path: shots + "-saved-" + w + ".png", clip: { x: 0, y: 0, width: w, height: 140 } });
      }
    }
    await a.ctx.close();
  } else if (scenario === "unsent") {
    // The page goes away before its write lands: the change stays in localStorage, the
    // next load shows Not saved yet for it, and pushes it.
    const a = await open({ seed: { "s1.why": { id: "why", section: "s1", kind: "question", answer: "stored",
      note: "", read: false, updated_at: "2026-01-01T00:00:00.000Z" } }, mode: "hang" });
    out.before = await a.page.locator('[data-note="why"]').inputValue();
    await a.page.locator('[data-note="why"]').fill("unsent change");
    await a.page.waitForTimeout(100);
    const rows = await a.page.evaluate(() => window.__rows);
    await a.page.close();
    const b = await open({ seed: rows, mode: "hold" }, a.ctx);
    out.reload = Object.assign(await sync(b.page), { value: await b.page.locator('[data-note="why"]').inputValue() });
    await b.page.evaluate(() => { window.__mode = "ok"; window.__release(); });
    await b.page.waitForTimeout(150);
    out.pushed = Object.assign(await sync(b.page),
      { row: await b.page.evaluate(() => window.__rows["s1.why"].answer) });
    await a.ctx.close();
  } else if (scenario === "readonly") {
    const a = await open({ mode: "fail:permission_denied" });
    await a.page.locator('.q[data-qid="pick"] input[value="B"]').check();
    await a.page.waitForTimeout(300);
    out.state = await sync(a.page);
    out.db = await a.page.evaluate(() => document.body.getAttribute("data-answers-db"));
    await a.ctx.close();
  } else if (scenario === "shots") {
    // Each state at 1280 and 390, for the eye.
    for (const w of [1280, 390]) {
      const a = await open({}, null, { width: w, height: 800 });
      const shot = async (name) => { if (!shots) return; await a.page.evaluate(() => window.scrollTo(0, 0));
        await a.page.screenshot({ path: shots + "-" + name + "-" + w + ".png", clip: { x: 0, y: 0, width: w, height: 140 } }); };
      out["bar_" + w] = await a.page.evaluate(() => {
        const bar = document.querySelector(".rp-topbars, .bar, .rp-bar");
        return { height: Math.round(bar.getBoundingClientRect().height),
                 over: document.documentElement.scrollWidth - document.documentElement.clientWidth };
      });
      await shot("saved");
      await a.page.evaluate(() => { window.__mode = "hold"; });
      await a.page.locator('.q[data-qid="pick"] input[value="B"]').check();
      await a.page.waitForTimeout(100);
      await shot("saving");
      await a.page.evaluate(() => { window.__mode = "fail:unavailable"; window.__release(); });
      await a.page.locator('.q[data-qid="pick"] input[value="A"]').check();
      await a.page.waitForTimeout(200);
      await shot("unsaved");
      out["bar_" + w + "_unsaved"] = await a.page.evaluate(() => {
        const bar = document.querySelector(".rp-topbars, .bar, .rp-bar");
        const t = document.querySelector(".rp-sync-t");
        return { height: Math.round(bar.getBoundingClientRect().height),
                 over: document.documentElement.scrollWidth - document.documentElement.clientWidth,
                 word: t.scrollWidth <= t.clientWidth && t.getBoundingClientRect().width > 20 };
      });
      await a.ctx.close();
    }
  }
  out.errors = errors;
  await browser.close();
  console.log(JSON.stringify(out));
})().catch((e) => { console.log(JSON.stringify({ crash: String(e && e.stack || e) })); process.exit(1); });
"""

SESSION_Q = dict(TEXT_Q, mode="session", title="sync-test · P log",
                 project={"name": "P", "session": "sync-test", "repo": "o/r"})


def drive(scenario, spec=TEXT_Q, shots=""):
    with tempfile.TemporaryDirectory() as tmp:
        page = build_spec(spec, tmp)
        script = Path(tmp) / "mock.cjs"
        script.write_text(MOCK)
        r = subprocess.run([NODE, str(script), playwright_dir(), str(RP / "launch.cjs"), str(page), scenario, shots],
                           capture_output=True, text=True, timeout=240)
        res = json.loads(r.stdout.strip().splitlines()[-1])
        if "crash" in res:
            raise AssertionError(res["crash"])
        if res["errors"]:
            raise AssertionError(res["errors"])
        return res


@unittest.skipUnless(NODE and playwright_dir(), "Playwright not found")
class SyncIndicator(unittest.TestCase):
    def test_no_database_means_no_indicator_never_a_false_saved(self):
        res = drive("none")
        for runtime in ("absent", "null"):
            s = res[runtime]
            self.assertFalse(s.get("missing"), s)
            self.assertTrue(s["hidden"], s)
            self.assertNotIn("Saved", s["text"] if not s["hidden"] else "")
            self.assertEqual(s["sets"], 0)

    def test_states_follow_typing_taps_and_failures(self):
        for spec in (TEXT_Q, SESSION_Q):
            with self.subTest(mode=spec["mode"]):
                res = drive("flow", spec)
                self.assertEqual((res["loaded"]["state"], res["loaded"]["text"]), ("saved", "Saved"))
                self.assertFalse(res["loaded"]["hidden"])
                self.assertEqual(res["loaded"]["live"], "polite")
                self.assertTrue(res["loaded"]["svg"])
                self.assertEqual((res["typing"]["state"], res["typing"]["text"]), ("saving", "Saving…"))
                self.assertEqual(res["typed"]["state"], "saved")
                self.assertEqual(res["typed"]["sets"], 1)           # debounced: one write for three keys
                self.assertEqual(res["tapped"]["row"], "B")         # a tap is saved at once
                self.assertEqual(res["tapped"]["state"], "saved")
                self.assertEqual(res["held"]["state"], "saving")
                self.assertEqual(res["released"]["state"], "saved")
                self.assertEqual((res["failed"]["state"], res["failed"]["text"]), ("unsaved", "Not saved yet"))
                self.assertGreater(res["retried"]["sets"], res["failed"]["sets"])  # it keeps trying
                self.assertEqual(res["retried"]["state"], "unsaved")
                self.assertEqual((res["recovered"]["state"], res["recovered"]["row"]), ("saved", "B"))
                for how in ("pagehide", "visibilitychange", "blur"):
                    self.assertEqual(res["flush_" + how], {"wrote": True, "row": "flush " + how}, how)

    def test_a_change_that_never_landed_is_kept_and_pushed_on_the_next_load(self):
        res = drive("unsent")
        self.assertEqual(res["before"], "stored")
        self.assertEqual(res["reload"]["value"], "unsent change")
        self.assertEqual((res["reload"]["state"], res["reload"]["text"]), ("unsaved", "Not saved yet"))
        self.assertEqual((res["pushed"]["state"], res["pushed"]["row"]), ("saved", "unsent change"))

    def test_a_refused_write_says_not_saved_and_stops(self):
        res = drive("readonly")
        self.assertEqual(res["db"], "off")
        self.assertEqual(res["state"]["state"], "unsaved")
        self.assertEqual(res["state"]["sets"], 1)

    def test_the_phone_bar_stays_one_line_with_the_word_when_not_saved(self):
        res = drive("shots", dict(SESSION_Q, title="a long session name · P log",
                                  project={"name": "P", "session": "a long session name", "repo": "o/r"}))
        self.assertEqual(res["bar_390"]["height"], res["bar_390_unsaved"]["height"])
        self.assertLess(res["bar_390"]["height"], 70)  # one line
        for k in ("bar_390", "bar_390_unsaved", "bar_1280_unsaved"):
            self.assertEqual(res[k]["over"], 0, k)
        self.assertTrue(res["bar_390_unsaved"]["word"])  # "Not saved" is shown in full, not cut

    def test_every_bar_has_the_indicator(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("questions", "session", "log", "design-review", "copy-edit", "qa-checklist"):
                html = build_example(name, tmp).read_text()
                tag = re.findall(r'<span class="rp-sync"[^>]*>', html)
                self.assertEqual(len(tag), 1, name)
                self.assertIn('aria-live="polite"', tag[0], name)
                self.assertIn("hidden", tag[0], name)  # shown only once a database answers


if __name__ == "__main__":
    unittest.main()
