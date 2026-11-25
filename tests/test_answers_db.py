"""Answers saved in a published page's own database (the `db` capability).

Unit tests run the page's engine under plain node. The browser tests mock the claude.ai
runtime (window.claude.use("db")) in real Chromium; they need Playwright, as the
click-through tests in test_review_page do.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RP = ROOT / "shared" / "review_page"
BUILD = RP / "review_page.py"
EXAMPLES = RP / "examples"
sys.path.insert(0, str(RP))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import review_page  # noqa: E402
from test_review_page import NODE, playwright_dir  # noqa: E402

ENGINE_DRIVER = r"""
const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8");
const spec = JSON.parse(html.match(/<script type="application\/json" id="rp-spec">([\s\S]*?)<\/script>/)[1]);
const code = html.match(/<script>\n([\s\S]*?)\n<\/script>/)[1];
const m = { exports: {} };
new Function("module", code)(m);
const E = m.exports;
const st = JSON.parse(process.argv[3]);
const now = new Date(Date.UTC(2026, 10, 24, 12, 0));
const docs = E.answerDocs(spec, st);
const back = E.applyAnswerDocs(spec, {}, Object.values(docs));
process.stdout.write(JSON.stringify({ docs, export: E.exportText(spec, st, now), back: E.exportText(spec, back, now),
  ids: [E.docIdFor("s1", "plain-id_1"), E.docIdFor("s1", "has space/slash"), E.docIdFor("s1", "has space?slash")],
  collection: E.DB_COLLECTION, version: spec.page_version }));
"""

TEXT_Q = {"mode": "questions", "title": "T", "project": {"name": "P", "stream": "s", "round": 1},
          "questions": [{"qid": "pick", "ask": "Which one?", "options": [{"label": "A"}, {"label": "B"}]},
                        {"qid": "why", "ask": "Why?", "options": [], "notes_label": "Your answer"}]}


def build_spec(spec, tmp, name="p"):
    src, out = Path(tmp) / (name + ".json"), Path(tmp) / (name + ".html")
    src.write_text(json.dumps(spec))
    r = subprocess.run([sys.executable, str(BUILD), str(src), "--out", str(out)], capture_output=True, text=True)
    if r.returncode:
        raise AssertionError(r.stdout + r.stderr)
    return out


def build_example(name, tmp):
    out = Path(tmp) / (name + ".html")
    r = subprocess.run([sys.executable, str(BUILD), str(EXAMPLES / (name + ".json")), "--out", str(out)],
                       capture_output=True, text=True)
    if r.returncode:
        raise AssertionError(r.stdout + r.stderr)
    return out


@unittest.skipUnless(NODE, "node is not installed")
class AnswerDocs(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = self._tmp.name
        self.driver = Path(self.tmp) / "d.cjs"
        self.driver.write_text(ENGINE_DRIVER)

    def run_engine(self, page, st):
        r = subprocess.run([NODE, str(self.driver), str(page), json.dumps(st)], capture_output=True, text=True,
                           env=dict(os.environ, TZ="UTC"))
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_one_document_per_card_with_only_cards_that_hold_something(self):
        page = build_spec(TEXT_Q, self.tmp)
        sec = json.loads(review_page.re.search(r'id="rp-spec">(.*?)</script>', page.read_text(), review_page.re.S)
                         .group(1))["sections"][0]["id"]
        res = self.run_engine(page, {"sec": {sec: {"ans": {"pick": "A"}, "notes": {"why": ""}}}})
        self.assertEqual(res["collection"], "proofs-answers")
        self.assertEqual(list(res["docs"]), [sec + ".pick"])
        self.assertEqual(res["docs"][sec + ".pick"], {"id": "pick", "section": sec, "kind": "question",
                                                      "answer": "A", "note": "", "read": False})
        self.assertTrue(res["version"])

    def test_document_ids_are_one_valid_path_segment(self):
        res = self.run_engine(build_spec(TEXT_Q, self.tmp), {})
        self.assertEqual(res["ids"][0], "s1.plain-id_1")
        for i in res["ids"]:
            self.assertRegex(i, r"^[A-Za-z0-9_\-.~:@+]{1,200}$")
        self.assertNotEqual(res["ids"][1], res["ids"][2])  # two ids that sanitize alike stay apart

    def test_every_kind_round_trips_to_the_same_export(self):
        states = {
            "questions": {"ans": {"filter-placement": "A - Beside the sort menu in the header row",
                                  "qa-delete-item": "FAIL"},
                          "notes": {"filter-placement": "two\nlines", "qa-delete-item": "it broke"}},
            "session": {"ans": {"Q1": "Yes", "E2::Ship it?": "Yes"}, "notes": {"E1": "a note"},
                        "read": {"E1": True}},
            "log": {"ans": {"L4::Approve?": "Approve"}, "notes": {"L1": "seen"}, "read": {"L1": True, "L2": True}},
            "design-review": {"items": {}},
            "copy-edit": {"items": {}},
        }
        for name, flat in states.items():
            with self.subTest(example=name):
                page = build_example(name, self.tmp)
                spec = json.loads(review_page.re.search(r'id="rp-spec">(.*?)</script>', page.read_text(),
                                                        review_page.re.S).group(1))
                st = {"sec": {}, "extra": "anything else here"}
                for s in spec["sections"]:
                    ss = json.loads(json.dumps(flat))
                    if s["kind"] == "review" and s["items"]:
                        first = s["items"][0]
                        ss["items"] = {first["id"]: {"s": s["decisions"]["buttons"][0]["state"], "c": "a comment",
                                                     "r": True}}
                    st["sec"][s["id"]] = ss
                res = self.run_engine(page, st)
                self.assertTrue(res["docs"], res)
                self.assertEqual(res["back"], res["export"])


@unittest.skipUnless(NODE, "node is not installed")
class AnswersCommand(unittest.TestCase):
    """review_page.py --answers prints the rows ArtifactData read as the Copy export."""

    def test_rows_folder_prints_the_copy_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            page = build_spec(TEXT_Q, tmp)
            rows = Path(tmp) / "rows" / "proofs-answers"
            rows.mkdir(parents=True)
            # One body as written, one wrapped the way a reader may save it; plus a stale row.
            (rows / "s1.pick.json").write_text(json.dumps(
                {"id": "pick", "section": "s1", "kind": "question", "answer": "B", "note": "",
                 "read": False, "updated_at": "2026-11-24T20:00:00.000Z", "page_version": "x", "page": "k"}))
            (rows / "s1.why.json").write_text(json.dumps({"id": "s1.why", "version": 3, "data": {
                "id": "why", "section": "s1", "kind": "question", "answer": None, "note": "because",
                "read": False, "updated_at": "2026-11-24T20:01:00.000Z"}}))
            (rows / "s1.gone.json").write_text(json.dumps(
                {"id": "gone", "section": "s1", "kind": "question", "answer": "A", "note": ""}))
            r = subprocess.run([sys.executable, str(BUILD), "--answers", str(page), "--rows", str(Path(tmp) / "rows")],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout, "[questions v1.3 — answers]\nproject: P\nstream:  s\nround:   1\n"
                                       "artifact: (the published URL of this page)\nsent:    2026-11-24T20:01Z\n\n"
                                       "Q pick (raised r1) | Which one?\n  -> B\n\n"
                                       "Q why (raised r1) | Why?\n  -> because\n")

    def test_answers_needs_rows(self):
        r = subprocess.run([sys.executable, str(BUILD), "--answers", "x.html"], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--rows", r.stderr)


MOCK = r"""
const { chromium } = require(process.argv[2]);
const { launchChromium } = require(process.argv[3]);
const file = "file://" + process.argv[4];
const mode = process.argv[5];
// The mocked runtime: window.claude.use("db") resolves a tiny in-memory store, seeded
// from `seed`; every set lands in window.__rows. `runtime` picks the case under test.
function install({ seed, runtime }) {
  window.__rows = JSON.parse(JSON.stringify(seed));
  window.__sets = 0;
  if (runtime === "absent") return;
  const db = {
    collection: (c) => ({
      get: async () => ({ docs: Object.keys(window.__rows).map((id) => ({ id, exists: true,
        data: () => JSON.parse(JSON.stringify(window.__rows[id])) })) }),
      doc: (id) => ({ set: async (data) => {
        if (c !== "proofs-answers") throw { code: "invalid_argument", message: "wrong collection " + c };
        window.__sets++;
        if (runtime === "readonly") throw { code: "invalid_argument", message: "read only" };
        window.__rows[id] = JSON.parse(JSON.stringify(data));
      } }),
    }),
  };
  window.claude = { use: (name) => new Promise((r) => setTimeout(() => r(runtime === "null" || name !== "db" ? null : db), 30)) };
}
(async () => {
  const browser = await launchChromium(chromium, process.env);
  const errors = [];
  async function open(seed, runtime, shared) {
    const ctx = shared || await browser.newContext();
    const page = await ctx.newPage();
    page.on("pageerror", (e) => errors.push(e.message));
    await page.addInitScript(install, { seed, runtime });
    await page.addInitScript(() => {
      window.__copied = [];
      Object.defineProperty(navigator, "clipboard", { configurable: true,
        value: { writeText: (t) => { window.__copied.push(t); return Promise.resolve(); } } });
    });
    await page.goto(file);
    await page.waitForTimeout(200);
    return { ctx, page };
  }
  const strip = (t) => t.replace(/^sent:.*$/m, "");
  async function answer(page) {
    await page.locator('.q[data-qid="pick"] input[value="B"]').check();
    await page.locator('[data-note="why"]').fill("because");
    await page.waitForTimeout(1300);
  }
  async function copy(page) {
    await page.locator("[data-copy]").first().click();
    await page.waitForTimeout(100);
    return page.evaluate(() => window.__copied[window.__copied.length - 1] || "");
  }
  const out = {};
  if (mode === "runtime") {
    // 1. Answer with the runtime present: rows are written, Copy still works.
    const a = await open({}, "db");
    await answer(a.page);
    out.rows = await a.page.evaluate(() => window.__rows);
    out.state = await a.page.evaluate(() => document.body.getAttribute("data-answers-db"));
    out.copied = await copy(a.page);
    out.sets = await a.page.evaluate(() => window.__sets);
    // No further change, no further writes.
    await a.page.waitForTimeout(1000);
    out.setsLater = await a.page.evaluate(() => window.__sets);
    await a.ctx.close();
    // 2. Another device: empty localStorage, same rows. The page shows the answers.
    const b = await open(out.rows, "db");
    await b.page.waitForTimeout(300);
    out.restored = {
      pick: await b.page.locator('.q[data-qid="pick"] input[value="B"]').isChecked(),
      why: await b.page.locator('[data-note="why"]').inputValue(),
      tally: await b.page.locator("#rp-tally").innerText(),
      export: await b.page.evaluate(() => window.rpExport()),
      setsOnLoad: await b.page.evaluate(() => window.__sets),
    };
    // 3. Clearing an answer writes the cleared row.
    await b.page.locator('[data-note="why"]').fill("");
    await b.page.waitForTimeout(1300);
    out.clearedRow = await b.page.evaluate(() => window.__rows["s1.why"]);
    await b.ctx.close();
    // 4. Same browser (local stamps kept), rows changed elsewhere: the newer updated_at wins.
    const c = await open({}, "db");
    await answer(c.page);
    const rows = await c.page.evaluate(() => window.__rows);
    const older = JSON.parse(JSON.stringify(rows));
    older["s1.pick"].answer = "A";
    older["s1.pick"].updated_at = "2000-01-01T00:00:00.000Z";
    const c1 = await open(older, "db", c.ctx);
    await c1.page.waitForTimeout(300);
    out.olderRow = { keptB: await c1.page.locator('.q[data-qid="pick"] input[value="B"]').isChecked(),
                     pushed: await c1.page.evaluate(() => window.__rows["s1.pick"].answer) };
    const newer = JSON.parse(JSON.stringify(rows));
    newer["s1.pick"].answer = "A";
    newer["s1.pick"].updated_at = "2999-01-01T00:00:00.000Z";
    const c2 = await open(newer, "db", c.ctx);
    await c2.page.waitForTimeout(300);
    out.newerRow = { showsA: await c2.page.locator('.q[data-qid="pick"] input[value="A"]').isChecked(),
                     sets: await c2.page.evaluate(() => window.__sets) };
    await c.ctx.close();
  } else {
    const a = await open({}, mode);
    await answer(a.page);
    out.state = await a.page.evaluate(() => document.body.getAttribute("data-answers-db"));
    out.sets = await a.page.evaluate(() => window.__sets);
    out.copied = await copy(a.page);
    await a.page.locator('[data-note="pick"]').fill("more");
    await a.page.waitForTimeout(1300);
    out.setsAfter = await a.page.evaluate(() => window.__sets);
    await a.page.locator('[data-note="pick"]').fill("");
    out.copied = await copy(a.page);
    await a.page.reload();
    await a.page.waitForTimeout(200);
    out.afterReload = await a.page.evaluate(() => window.rpExport());
    await a.ctx.close();
  }
  out.errors = errors;
  await browser.close();
  console.log(JSON.stringify(out));
})().catch((e) => { console.log(JSON.stringify({ crash: String(e && e.stack || e) })); process.exit(1); });
"""

EXPECT = ("Q pick (raised r1) | Which one?\n  -> B\n\nQ why (raised r1) | Why?\n  -> because\n")


@unittest.skipUnless(NODE and playwright_dir(), "Playwright not found")
class PageDatabase(unittest.TestCase):
    def drive(self, mode):
        with tempfile.TemporaryDirectory() as tmp:
            page = build_spec(TEXT_Q, tmp)
            script = Path(tmp) / "mock.cjs"
            script.write_text(MOCK)
            r = subprocess.run([NODE, str(script), playwright_dir(), str(RP / "launch.cjs"), str(page), mode],
                               capture_output=True, text=True, timeout=180)
            res = json.loads(r.stdout.strip().splitlines()[-1])
            self.assertNotIn("crash", res, res)
            self.assertEqual(res["errors"], [], res)
            return res

    def test_answers_are_saved_restored_and_copy_still_works(self):
        res = self.drive("runtime")
        rows = res["rows"]
        self.assertEqual(sorted(rows), ["s1.pick", "s1.why"])
        pick = rows["s1.pick"]
        for k in ("id", "section", "kind", "answer", "note", "read", "updated_at", "page_version", "page"):
            self.assertIn(k, pick)
        self.assertEqual((pick["id"], pick["kind"], pick["answer"]), ("pick", "question", "B"))
        self.assertEqual((rows["s1.why"]["answer"], rows["s1.why"]["note"]), ("because", ""))  # typed answer
        self.assertRegex(pick["updated_at"], r"^\d{4}-\d\d-\d\dT")
        self.assertEqual(res["state"], "on")
        self.assertIn(EXPECT, res["copied"])
        self.assertEqual(res["sets"], 2)          # the tap at once, the typing debounced: one write per card
        self.assertEqual(res["setsLater"], 2)     # nothing rewritten without a change
        rest = res["restored"]
        self.assertTrue(rest["pick"])
        self.assertEqual(rest["why"], "because")
        self.assertEqual(rest["tally"], "all 2 answered")
        self.assertIn(EXPECT, rest["export"])
        self.assertEqual(rest["setsOnLoad"], 0)   # opening the page writes nothing
        self.assertEqual(res["clearedRow"]["note"], "")
        self.assertIsNone(res["clearedRow"]["answer"])
        self.assertEqual(res["olderRow"], {"keptB": True, "pushed": "B"})
        self.assertEqual(res["newerRow"], {"showsA": True, "sets": 0})

    def test_without_the_runtime_the_page_works_as_before(self):
        for mode in ("absent", "null"):
            with self.subTest(runtime=mode):
                res = self.drive(mode)
                self.assertEqual(res["sets"], 0)
                self.assertEqual(res["state"], None if mode == "absent" else "off")
                self.assertIn(EXPECT, res["copied"])
                self.assertIn(EXPECT, res["afterReload"])  # localStorage still keeps the answers

    def test_a_refused_write_falls_back_to_copy(self):
        res = self.drive("readonly")
        self.assertEqual(res["state"], "off")
        self.assertEqual(res["sets"], 1)       # the tap was sent at once and refused
        self.assertEqual(res["setsAfter"], 1)  # after a refusal, nothing more is tried
        self.assertIn(EXPECT, res["copied"])
        self.assertIn(EXPECT, res["afterReload"])


if __name__ == "__main__":
    unittest.main()
