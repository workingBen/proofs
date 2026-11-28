"""Follow-up rounds on one review page URL: stale answers never pre-fill a changed item.

Each review item carries a fingerprint (`rev`) of its proposal, saved with every answer.
An answer saved on another rev shows on the card read-only ("Round 1: ...") and never as
the live pick or comment; the same build reloaded keeps every answer. The builder puts
items decided in earlier rounds (`decided`) folded at the bottom, under the open ones.
"""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RP = ROOT / "shared" / "review_page"
sys.path.insert(0, str(RP))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import review_page  # noqa: E402
from test_answers_db import build_spec  # noqa: E402
from test_review_page import NODE, playwright_dir  # noqa: E402

ROUND1 = {"mode": "review", "title": "Finish review", "decisions": "copy-edit",
          "project": {"name": "P", "session": "S"},
          "items": [{"id": "finish", "label": "Finish", "body_html": "<p>Matte black</p>"},
                    {"id": "keep", "label": "Keep", "body_html": "<p>Same both rounds</p>"}]}


def round2(spec=ROUND1):
    s = copy.deepcopy(spec)
    s["items"][0]["body_html"] = "<p>Brushed brass</p>"
    s["items"][0]["history_html"] = "<p>Round 1: matte black</p>"
    s["decided"] = [{"id": "3", "title": "Hinges", "decision": "ACCEPT", "when": "Round 1"}]
    return s


def page_spec(text):
    return json.loads(review_page.re.search(r'id="rp-spec">(.*?)</script>', text, review_page.re.S).group(1))


def revs(spec):
    with tempfile.TemporaryDirectory() as tmp:
        js = page_spec(build_spec(spec, tmp).read_text())
    return {it["id"]: it["rev"] for s in js["sections"] if s["kind"] == "review" for it in s["items"]}


class Fingerprint(unittest.TestCase):
    def test_changed_proposal_gets_a_new_rev_and_commentary_does_not(self):
        r1 = revs(ROUND1)
        r2 = revs(round2())
        self.assertNotEqual(r1["finish"], r2["finish"])
        self.assertEqual(r1["keep"], r2["keep"])
        s = copy.deepcopy(ROUND1)
        s["items"][1].update(history_html="<p>x</p>", reason_html="<p>why</p>", recommended=True)
        self.assertEqual(revs(s)["keep"], r1["keep"])  # a republish of the same round keeps answers

    def test_variants_round_and_pinned_rev(self):
        base = copy.deepcopy(ROUND1)
        base["items"][1]["variants"] = [{"html": "<p>A</p>"}, {"html": "<p>B</p>"}]
        changed = copy.deepcopy(base)
        changed["items"][1]["variants"][1]["html"] = "<p>B2</p>"
        self.assertNotEqual(revs(base)["keep"], revs(changed)["keep"])
        bumped = copy.deepcopy(ROUND1)
        bumped["project"]["round"] = 2
        self.assertNotEqual(revs(bumped)["keep"], revs(ROUND1)["keep"])
        pinned = copy.deepcopy(round2())
        pinned["items"][0]["rev"] = "typo-fix"
        self.assertEqual(revs(pinned)["finish"], "typo-fix")


class DecidedAtTheBottom(unittest.TestCase):
    def test_decided_shorthand_renders_folded_after_the_open_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = build_spec(round2(), tmp).read_text()
        self.assertEqual(review_page.rendered_kinds(text), ["review", "decided"])
        self.assertIn('<details class="rp-decided"><summary>1 settled', text)
        self.assertIn("Hinges", text)

    def test_a_decided_section_listed_first_still_goes_last(self):
        spec = {"mode": "review", "title": "T", "decisions": "copy-edit", "sections": [
            {"kind": "decided", "items": [{"title": "Old", "decision": "DENY"}]},
            {"title": "Open", "items": [{"id": "a", "label": "A", "body_html": "<p>a</p>"}]}]}
        with tempfile.TemporaryDirectory() as tmp:
            text = build_spec(spec, tmp).read_text()
        self.assertEqual(review_page.rendered_kinds(text), ["review", "decided"])


DRIVER = r"""
const fs = require("fs");
function load(p) {
  const html = fs.readFileSync(p, "utf8");
  const spec = JSON.parse(html.match(/<script type="application\/json" id="rp-spec">([\s\S]*?)<\/script>/)[1]);
  const m = { exports: {} };
  new Function("module", html.match(/<script>\n([\s\S]*?)\n<\/script>/)[1])(m);
  return { spec, E: m.exports };
}
const one = load(process.argv[2]), two = load(process.argv[3]);
const now = new Date(Date.UTC(2026, 10, 27, 12, 0));
// Round 1: both items answered, saved as rows.
const st1 = { sec: { s1: { items: {
  finish: { s: "accept-comment", c: "love it" }, keep: { s: "accept", c: "fine" } } } } };
const rows = Object.values(one.E.answerDocs(one.spec, st1));
// Round 2 opens on another device: only the rows.
const back = two.E.applyAnswerDocs(two.spec, {}, JSON.parse(JSON.stringify(rows)));
// Round 2 in the same browser: round 1's local records (stamped with their rev).
const local = JSON.parse(JSON.stringify(st1));
const s1 = one.spec.sections[0];
s1.items.forEach((it) => { local.sec.s1.items[it.id].rev = it.rev; local.sec.s1.items[it.id].round = it.round; });
two.E.sweepStale(two.spec, local);
// A legacy row (no rev, built before 1.10.0) restores as before.
const legacy = rows.map((r) => { const c = Object.assign({}, r); delete c.rev; delete c.round; return c; });
const legacyBack = two.E.applyAnswerDocs(two.spec, {}, legacy);
// Answering round 2 writes the earlier answer into the new row.
const st2 = JSON.parse(JSON.stringify(back));
st2.sec.s1.items.finish = { s: "deny", c: "" };
const rows2 = two.E.answerDocs(two.spec, st2);
const sec2 = two.spec.sections.filter((s) => s.kind === "review")[0];
process.stdout.write(JSON.stringify({
  rows, back, local, rows2,
  exportBack: two.E.exportText(two.spec, back, now),
  exportLegacy: two.E.exportText(two.spec, legacyBack, now),
  reread: two.E.exportText(two.spec, two.E.applyAnswerDocs(two.spec, {}, Object.values(rows2)), now),
  line: two.E.earlierLine(sec2, sec2.items[0], back.sec.s1.earlier.finish[0]),
}));
"""


@unittest.skipUnless(NODE, "node is not installed")
class StaleAnswers(unittest.TestCase):
    def run_driver(self, spec1, spec2):
        with tempfile.TemporaryDirectory() as tmp:
            p1, p2 = build_spec(spec1, tmp, "r1"), build_spec(spec2, tmp, "r2")
            drv = Path(tmp) / "d.cjs"
            drv.write_text(DRIVER)
            r = subprocess.run([NODE, str(drv), str(p1), str(p2)], capture_output=True, text=True,
                               env=dict(os.environ, TZ="UTC"))
            self.assertEqual(r.returncode, 0, r.stderr)
            return json.loads(r.stdout)

    def test_a_changed_item_is_not_prefilled_and_shows_the_earlier_answer(self):
        res = self.run_driver(ROUND1, round2())
        for row in res["rows"]:
            self.assertTrue(row["rev"])
        items = res["back"]["sec"]["s1"]["items"]
        self.assertNotIn("finish", items)                       # no live pick, no comment
        self.assertEqual((items["keep"]["s"], items["keep"]["c"]), ("accept", "fine"))  # unchanged item kept
        self.assertEqual(res["back"]["sec"]["s1"]["earlier"]["finish"],
                         [{"round": None, "answer": "accept-comment", "note": "love it", "variant": None}])
        self.assertIn("1. Finish — PENDING", res["exportBack"])  # Claude never reads round 1 as round 2
        self.assertIn("2. Keep — ACCEPT (Use Edit) — COMMENT: fine", res["exportBack"])
        self.assertEqual(res["line"], "An earlier round: Approve with Comment: “love it”")

    def test_this_browsers_round1_records_are_swept_the_same_way(self):
        res = self.run_driver(ROUND1, round2())
        ss = res["local"]["sec"]["s1"]
        self.assertNotIn("finish", ss["items"])
        self.assertEqual(ss["items"]["keep"]["c"], "fine")
        self.assertEqual(ss["earlier"]["finish"][0]["note"], "love it")

    def test_legacy_rows_without_a_rev_restore_as_before(self):
        res = self.run_driver(ROUND1, round2())
        self.assertIn("1. Finish — ACCEPT WITH COMMENT — COMMENT: love it", res["exportLegacy"])

    def test_the_new_answer_carries_the_earlier_one_and_reads_back_live(self):
        res = self.run_driver(ROUND1, round2())
        row = res["rows2"]["s1.finish"]
        self.assertEqual(row["answer"], "deny")
        self.assertEqual(row["earlier"][0]["note"], "love it")
        self.assertIn("1. Finish — DENY (Keep Original)", res["reread"])

    def test_rounds_label_earlier_answers(self):
        s1, s2 = copy.deepcopy(ROUND1), round2()
        s1["project"]["round"], s2["project"]["round"] = 1, 2
        res = self.run_driver(s1, s2)
        self.assertEqual(res["line"], "Round 1: Approve with Comment: “love it”")
        # A new round invalidates every item, the unchanged one included.
        self.assertEqual(sorted(res["back"]["sec"]["s1"]["earlier"]), ["finish", "keep"])


BROWSER = r"""
const { chromium } = require(process.argv[2]);
const { launchChromium } = require(process.argv[3]);
const r1 = "file://" + process.argv[4], r2 = "file://" + process.argv[5];
function install(seed) {
  window.__rows = window.__rows || JSON.parse(JSON.stringify(seed));
  window.__sets = 0;
  const db = { collection: () => ({
    get: async () => ({ docs: Object.keys(window.__rows).map((id) => ({ id, exists: true,
      data: () => JSON.parse(JSON.stringify(window.__rows[id])) })) }),
    doc: (id) => ({ set: async (data) => { window.__sets++; window.__rows[id] = JSON.parse(JSON.stringify(data)); } }) }) };
  window.claude = { use: (name) => Promise.resolve(name === "db" ? db : null) };
}
(async () => {
  const browser = await launchChromium(chromium, process.env);
  const ctx = await browser.newContext();
  const errors = [];
  async function open(url, seed) {
    const page = await ctx.newPage();
    page.on("pageerror", (e) => errors.push(e.message));
    await page.addInitScript(install, seed);
    await page.goto(url);
    await page.waitForTimeout(300);
    return page;
  }
  const card = (p, id) => p.locator('.rp-item[data-id="' + id + '"]');
  async function look(p) {
    const o = {};
    for (const id of ["finish", "keep"]) {
      o[id] = { comment: await card(p, id).locator("textarea").inputValue(),
                pill: await card(p, id).locator("[data-pill]").innerText(),
                earlier: await card(p, id).locator("[data-earlier]").isVisible()
                  ? await card(p, id).locator("[data-earlier]").innerText() : "" };
    }
    return o;
  }
  const out = {};
  // Round 1: answer both items.
  const a = await open(r1, {});
  await card(a, "finish").locator('[data-choice="accept-comment"]').click();
  await card(a, "finish").locator("textarea").fill("love it");
  await card(a, "keep").locator('[data-choice="revise"]').click();
  await card(a, "keep").locator("textarea").fill("fine");
  await a.waitForTimeout(1300);
  const rows = await a.evaluate(() => window.__rows);
  // The same build reloaded: every answer is still there.
  await a.reload();
  await a.waitForTimeout(300);
  out.reload = await look(a);
  await a.close();
  // Round 2 republished to the same URL, same browser and same rows.
  const b = await open(r2, rows);
  out.round2 = await look(b);
  out.setsOnLoad = await b.evaluate(() => window.__sets);
  out.staleRowKept = await b.evaluate(() => window.__rows["s1.finish"].note);
  out.decidedLast = await b.evaluate(() => Array.from(document.querySelectorAll(".rp-section")).map((s) => s.className));
  await card(b, "finish").locator('[data-choice="deny"]').click();
  await b.waitForTimeout(300);
  out.newRow = await b.evaluate(() => window.__rows["s1.finish"]);
  await b.close();
  // Another device on round 2: no localStorage, only the rows.
  const ctx2 = await browser.newContext();
  const c = await ctx2.newPage();
  c.on("pageerror", (e) => errors.push(e.message));
  await c.addInitScript(install, rows);
  await c.goto(r2);
  await c.waitForTimeout(300);
  out.otherDevice = await look(c);
  out.errors = errors;
  await browser.close();
  console.log(JSON.stringify(out));
})().catch((e) => { console.log(JSON.stringify({ crash: String(e && e.stack || e) })); process.exit(1); });
"""


@unittest.skipUnless(NODE and playwright_dir(), "Playwright not found")
class RoundsInTheBrowser(unittest.TestCase):
    def test_round2_on_the_same_url_starts_clean_with_round1_shown(self):
        with tempfile.TemporaryDirectory() as tmp:
            p1, p2 = build_spec(ROUND1, tmp, "r1"), build_spec(round2(), tmp, "r2")
            script = Path(tmp) / "b.cjs"
            script.write_text(BROWSER)
            r = subprocess.run([NODE, str(script), playwright_dir(), str(RP / "launch.cjs"), str(p1), str(p2)],
                               capture_output=True, text=True, timeout=180)
            res = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertNotIn("crash", res, res)
        self.assertEqual(res["errors"], [])
        self.assertEqual(res["reload"]["finish"]["comment"], "love it")   # same round: notes survive
        self.assertEqual(res["reload"]["finish"]["earlier"], "")
        for view in ("round2", "otherDevice"):
            with self.subTest(view=view):
                fin, keep = res[view]["finish"], res[view]["keep"]
                self.assertEqual((fin["comment"], fin["pill"]), ("", "Pending"))
                self.assertIn("Approve with Comment: “love it”", fin["earlier"])
                self.assertEqual((keep["comment"], keep["earlier"]), ("fine", ""))
        self.assertEqual(res["setsOnLoad"], 0)        # opening round 2 writes nothing
        self.assertEqual(res["staleRowKept"], "love it")
        self.assertEqual([c.split()[-1] for c in res["decidedLast"]], ["rp-kind-review", "rp-kind-decided"])
        self.assertEqual(res["newRow"]["answer"], "deny")
        self.assertEqual(res["newRow"]["earlier"][0]["note"], "love it")


if __name__ == "__main__":
    unittest.main()
