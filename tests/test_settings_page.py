"""The settings page (Proofs 1.9.0): layout B, a `settings` mode of the review-page builder.

settings.py --spec prints a builder spec of the effective settings; review_page.py builds it
into a page with a sticky save bar, a sidebar of the five groups and one group's pane. Each
change the reader makes is one row in the page's database (kind `setting`) carrying the value
the page showed (`from`), and the export is one `SET KEY=VALUE (scope; was OLD)` line per
change. The page refuses what settings.py refuses, with the same reason, from the same table
data embedded in the page.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RP = ROOT / "shared" / "review_page"
BUILD = RP / "review_page.py"
EXAMPLE = RP / "examples" / "settings.json"
SETTINGS = ROOT / "shared" / "settings.py"
sys.path.insert(0, str(RP))
sys.path.insert(0, str(ROOT / "shared"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import review_page  # noqa: E402
import settings  # noqa: E402
from test_review_page import NODE, playwright_dir  # noqa: E402

TABLE = settings.load_table()
KEYS = [r["key"] for r in TABLE]


def clean_env(home):
    env = {k: v for k, v in os.environ.items() if not k.startswith("PROOFS_") and k != "CLAUDE_CONFIG_DIR"}
    env["HOME"] = str(home)
    return env


def build(spec_path, out):
    r = subprocess.run([sys.executable, str(BUILD), str(spec_path), "--out", str(out)], capture_output=True, text=True)
    if r.returncode:
        raise AssertionError(r.stdout + r.stderr)
    return r


def build_spec(spec, tmp, name="settings"):
    src, out = Path(tmp) / (name + ".json"), Path(tmp) / (name + ".html")
    src.write_text(json.dumps(spec))
    build(src, out)
    return out


ENGINE = r"""
const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8");
const spec = JSON.parse(html.match(/<script type="application\/json" id="rp-spec">([\s\S]*?)<\/script>/)[1]);
const code = html.match(/<script>\n([\s\S]*?)\n<\/script>/)[1];
const m = { exports: {} };
new Function("module", code)(m);
const E = m.exports;
const args = JSON.parse(process.argv[3]);
const sec = spec.sections[0];
const row = (k) => sec.items.filter((i) => i.id === k)[0];
const out = { checks: {} };
Object.keys(args.checks || {}).forEach((k) => {
  out.checks[k] = args.checks[k].map((raw) => E.settingCheck(spec, row(k), raw));
});
if (args.state) {
  const st = { sec: { settings: { ans: args.state } } };
  out.docs = E.answerDocs(spec, st);
  out.export = E.exportText(spec, st, new Date(Date.UTC(2026, 10, 26, 12, 0)));
  out.count = E.answeredCount(spec, st);
  out.send = E.sendText(spec, st);
}
process.stdout.write(JSON.stringify(out));
"""


def engine(page, args):
    with tempfile.TemporaryDirectory() as tmp:
        drv = Path(tmp) / "e.cjs"
        drv.write_text(ENGINE)
        r = subprocess.run([NODE, str(drv), str(page), json.dumps(args)], capture_output=True, text=True,
                           env=dict(os.environ, TZ="UTC"))
        if r.returncode:
            raise AssertionError(r.stderr)
        return json.loads(r.stdout)


class SpecFromSettings(unittest.TestCase):
    """settings.py --spec in an isolated project: the page is built from what the files say."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve()
        self.home, self.proj = self.tmp / "home", self.tmp / "demo-app"
        (self.home / ".claude").mkdir(parents=True)
        (self.proj / ".claude").mkdir(parents=True)
        (self.proj / ".claude" / "settings.json").write_text(json.dumps(
            {"permissions": {"allow": []}, "env": {"PROOFS_MIN_TEXT": "18", "PROOFS_SPELLING": "american"}}))
        (self.home / ".claude" / "settings.json").write_text(json.dumps({"env": {"PROOFS_SEND_WAIT_MIN": "10"}}))

    def spec(self):
        r = subprocess.run([sys.executable, str(SETTINGS), "--spec"], cwd=self.proj, env=clean_env(self.home),
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_spec_from_settings_py_builds_and_checks(self):
        spec = self.spec()
        self.assertEqual(spec["mode"], "settings")
        self.assertEqual(spec["project"]["name"], "demo-app")
        self.assertEqual(spec["send_wait_ms"], 10 * 60000)
        self.assertEqual([s["key"] for s in spec["settings"]], KEYS)
        by = {s["key"]: s for s in spec["settings"]}
        self.assertEqual((by["PROOFS_MIN_TEXT"]["value"], by["PROOFS_MIN_TEXT"]["source"]), (18, "project"))
        self.assertEqual((by["PROOFS_PORT"]["value"], by["PROOFS_PORT"]["source"]), (3311, "default"))
        self.assertEqual(by["PROOFS_MIN_TEXT"]["min"], 16)  # the whole table row rides along
        src, out = self.tmp / "s.json", self.tmp / "s.html"
        src.write_text(json.dumps(spec))
        r = build(src, out)
        self.assertIn("check: ok", r.stdout)
        self.assertEqual(review_page.check(out), [])
        text = out.read_text()
        self.assertIn('<span class="rp-sk" aria-hidden="true">settings</span>', text)
        self.assertIn("Changed · default 16 px", text)

    def test_a_spec_value_settings_py_would_refuse_is_a_spec_error(self):
        spec = {"mode": "settings", "title": "Proofs settings", "project": {"name": "x"},
                "settings": [{"key": "PROOFS_MIN_TEXT", "value": 14, "source": "project"}]}
        src = self.tmp / "bad.json"
        src.write_text(json.dumps(spec))
        r = subprocess.run([sys.executable, str(BUILD), str(src), "--out", str(self.tmp / "bad.html")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("can only go up from 16", r.stderr)
        spec["settings"] = [{"key": "PROOFS_NOT_A_THING", "value": 1}]
        src.write_text(json.dumps(spec))
        r = subprocess.run([sys.executable, str(BUILD), str(src), "--out", str(self.tmp / "bad.html")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("PROOFS_NOT_A_THING", r.stderr)


class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.page = Path(cls._tmp.name) / "settings-example.html"
        build(EXAMPLE, cls.page)
        cls.html = cls.page.read_text()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_every_table_key_has_one_row(self):
        rows = re.findall(r'data-set-row="([A-Z_]+)"', self.html)
        self.assertEqual(sorted(rows), sorted(KEYS))
        for key in KEYS:
            self.assertEqual(rows.count(key), 1, key)

    def test_groups_and_counts_match_the_table(self):
        nav = re.findall(r'data-set-nav="(\w+)".*?<span class="rp-set-nav-t">([^<]+)</span>'
                         r'<span class="rp-set-nav-n" data-set-n>(\d+)</span>', self.html)
        want = [(g, title, str(sum(1 for r in TABLE if r["group"] == g))) for g, title in settings.GROUP_TITLES.items()]
        self.assertEqual(nav, want)
        for g in settings.GROUP_TITLES:
            pane = re.search(r'<div class="rp-set-group" data-set-group="%s".*?<!--/group-->' % g, self.html, re.S).group(0)
            self.assertEqual(pane.count('<h1 class="rp-set-h1">'), 1)
            main, _, adv = pane.partition('<h2 class="rp-set-h2"')
            want_main = [r["key"] for r in TABLE if r["group"] == g and not r["advanced"]]
            want_adv = [r["key"] for r in TABLE if r["group"] == g and r["advanced"]]
            self.assertEqual(re.findall(r'data-set-row="([A-Z_]+)"', main), want_main, g)
            self.assertEqual(re.findall(r'data-set-row="([A-Z_]+)"', adv), want_adv, g)
            self.assertEqual(bool(adv), bool(want_adv), g)
        self.assertNotIn("Advanced</span>", self.html)  # no per-row Advanced tag
        self.assertIn("Fixed on purpose.", self.html)

    def test_controls_follow_the_type(self):
        def row(key):
            return re.search(r'data-set-row="%s".*?<!--/row-->' % key, self.html, re.S).group(0)
        self.assertIn('inputmode="numeric"', row("PROOFS_PORT"))
        self.assertIn('class="rp-set-unit">px<', row("PROOFS_MIN_TEXT"))
        self.assertEqual(row("PROOFS_CRITIC").count('class="rp-set-seg-b"'), 2)
        self.assertIn('role="switch"', row("PROOFS_PR_REMINDER"))
        self.assertIn("rp-set-in-text", row("PROOFS_QA_PATHS"))
        self.assertIn("rp-set-in-text", row("PROOFS_DESIGN_PROFILE"))
        self.assertIn(">Change</button>", row("PROOFS_BROWSER_CHANNEL"))

    @unittest.skipUnless(NODE, "node is not installed")
    def test_raise_only_field_refuses_lower_value_with_reason(self):
        res = engine(self.page, {"checks": {"PROOFS_MIN_TEXT": ["14", "18"]},
                                 "state": {"PROOFS_MIN_TEXT": "14", "PROOFS_PORT": "99999"}})
        low, ok = res["checks"]["PROOFS_MIN_TEXT"]
        self.assertFalse(low["ok"])
        self.assertEqual(low["error"], "Smallest text can only go up from 16 px.")
        self.assertEqual((ok["ok"], ok["canon"]), (True, "18"))
        self.assertEqual(res["docs"], {})      # a refused value is never saved
        self.assertEqual(res["count"], 0)      # and so Send stays off

    @unittest.skipUnless(NODE, "node is not installed")
    def test_page_validation_matches_settings_py_for_every_key(self):
        tries = ["", " ", "abc", "0", "1", "2", "3", "5", "14", "16", "18", "44", "43", "99999", "3099", "-1",
                 "+5", "+-5", " 7 ", "7.5", "1e3", "on", "off", "yes", "No", "TRUE", "american", "self", "helper",
                 "file", "wifi", "artifact", "auto", "chrome", "docs/x.md", "agent/,bot/", ",", "400,2560", "399",
                 "1600, 2000", "1600,abc", "app/", "２", "٣"]
        res = engine(self.page, {"checks": {k: tries for k in KEYS}})
        for key in KEYS:
            row = next(r for r in TABLE if r["key"] == key)
            for raw, js in zip(tries, res["checks"][key]):
                with self.subTest(key=key, raw=raw):
                    try:
                        want = settings.validate(key, raw)
                    except settings.SettingError as e:
                        self.assertFalse(js["ok"], js)
                        self.assertEqual(js["error"], str(e))
                    else:
                        self.assertTrue(js["ok"], js)
                        self.assertEqual(js["canon"], settings._canonical(row, want))

    @unittest.skipUnless(NODE, "node is not installed")
    def test_numeric_choices_treat_3_and_the_string_3_alike(self):
        res = engine(self.page, {"state": {"PROOFS_DESIGN_OPTIONS": "3", "PROOFS_CORRECTION_PASSES": "2"}})
        self.assertEqual(list(res["docs"]), ["settings.PROOFS_CORRECTION_PASSES"])  # 3 is already the value
        self.assertEqual(res["docs"]["settings.PROOFS_CORRECTION_PASSES"]["from"], "1")

    @unittest.skipUnless(NODE, "node is not installed")
    def test_export_and_answers_print_SET_lines(self):
        state = {"PROOFS_MIN_TEXT": "18", "PROOFS_PORT": "3099", "PROOFS_EXTRA_WIDTHS": "1600, 2000",
                 "PROOFS_SPELLING": "off", "PROOFS_MIN_TAP": "40"}
        res = engine(self.page, {"state": state})
        lines = [ln for ln in res["export"].splitlines() if ln.startswith("SET ")]
        self.assertEqual(lines, ["SET PROOFS_SPELLING=off (project; was american)",
                                 "SET PROOFS_MIN_TEXT=18 (project; was 16)",
                                 "SET PROOFS_EXTRA_WIDTHS=1600,2000 (project; was none)",
                                 "SET PROOFS_PORT=3099 (project; was 3311)"])
        self.assertTrue(res["export"].startswith("PROOFS SETTINGS — my changes\nproject: Acme app\n"))
        self.assertIn("answered PROOFS_SPELLING, PROOFS_MIN_TEXT, PROOFS_EXTRA_WIDTHS, PROOFS_PORT", res["send"])
        doc = res["docs"]["settings.PROOFS_MIN_TEXT"]
        self.assertEqual(doc, {"id": "PROOFS_MIN_TEXT", "section": "settings", "kind": "setting", "answer": "18",
                               "from": "16", "scope": "project", "note": ""})
        with tempfile.TemporaryDirectory() as tmp:
            rows = Path(tmp) / "rows.json"
            stamped = [dict(d, updated_at="2026-11-26T12:00:00.000Z") for d in res["docs"].values()]
            rows.write_text(json.dumps(stamped))
            r = subprocess.run([sys.executable, str(BUILD), "--answers", str(self.page), "--rows", str(rows)],
                               capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([ln for ln in r.stdout.splitlines() if ln.startswith("SET ")], lines)

    @unittest.skipUnless(NODE, "node is not installed")
    def test_no_change_exports_no_SET_line(self):
        res = engine(self.page, {"state": {"PROOFS_MIN_TEXT": "016"}})
        self.assertEqual(res["docs"], {})
        self.assertIn("(no changes)", res["export"])
        self.assertNotIn("SET ", res["export"])


BROWSER = r"""
const { chromium } = require(process.argv[2]);
const { launchChromium } = require(process.argv[3]);
const file = "file://" + process.argv[4];
function install() {
  window.__rows = {};
  const db = { collection: () => ({
    get: async () => ({ docs: [] }),
    doc: (id) => ({ set: (d) => { window.__rows[id] = JSON.parse(JSON.stringify(d)); return Promise.resolve(); } }),
  }) };
  window.claude = { use: (n) => new Promise((r) => setTimeout(() => r(n === "db" ? db : null), 20)) };
}
(async () => {
  const browser = await launchChromium(chromium, process.env);
  const errors = [];
  const out = {};
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(e.message));
  await page.addInitScript(install);
  await page.goto(file);
  await page.waitForTimeout(200);
  const bar = () => page.locator("[data-set-save]").innerText();
  const row = (k) => page.locator(`[data-set-row="${k}"]`);
  const visibleRows = () => page.$$eval("[data-set-row]", (els) => els.filter((e) => e.offsetParent !== null).map((e) => e.dataset.setRow));
  out.start = { bar: await bar(), rows: await visibleRows() };
  // the checks group: a refused value, then a good one
  await page.locator('[data-set-nav="checks"]').click();
  out.checks_rows = await visibleRows();
  const minText = row("PROOFS_MIN_TEXT").locator("input");
  await minText.fill("14");
  await page.waitForTimeout(100);
  const err = row("PROOFS_MIN_TEXT").locator("[data-set-err]");
  out.refused = { bar: await bar(), err: await err.innerText(), err_shown: await err.isVisible(),
    err_color: await err.evaluate((e) => getComputedStyle(e).color),
    deny: await page.evaluate(() => { const d = document.createElement("i"); d.style.color = "var(--rp-deny)"; document.body.appendChild(d); const c = getComputedStyle(d).color; d.remove(); return c; }) };
  await minText.fill("18");
  await page.waitForTimeout(1200);
  out.pending = { bar: await bar(), mark: await row("PROOFS_MIN_TEXT").locator("[data-set-mark]").innerText(),
    amber: await row("PROOFS_MIN_TEXT").evaluate((e) => e.classList.contains("rp-set-row-p")),
    err_shown: await err.isVisible(), row: await page.evaluate(() => window.__rows["settings.PROOFS_MIN_TEXT"]),
    dot: await page.locator('[data-set-nav="checks"] [data-set-dot]').evaluate((d) => getComputedStyle(d).visibility) };
  // Reset on a changed setting writes its default as the answer
  out.changed_mark = await row("PROOFS_SPELLING").locator("[data-set-mark]").innerText();
  await row("PROOFS_SPELLING").locator("[data-set-reset]").click();
  await page.waitForTimeout(300);
  out.reset = { row: await page.evaluate(() => window.__rows["settings.PROOFS_SPELLING"]),
    pressed: await row("PROOFS_SPELLING").locator('[aria-pressed="true"]').innerText(), bar: await bar() };
  // Undo takes the change back: the row stays a setting row, with no answer to apply
  await row("PROOFS_MIN_TEXT").locator("[data-set-undo]").click();
  await page.waitForTimeout(300);
  out.undo = { row: await page.evaluate(() => window.__rows["settings.PROOFS_MIN_TEXT"]), bar: await bar(),
    box: await minText.inputValue() };
  // search across groups
  await page.locator("[data-set-search]").fill("wait");
  await page.waitForTimeout(100);
  out.search = await visibleRows();
  await page.locator("[data-set-search]").fill("");
  await page.waitForTimeout(100);
  out.search_cleared = await visibleRows();
  // a phone: the sidebar stacks above the pane, segmented controls span the row
  await page.setViewportSize({ width: 390, height: 900 });
  await page.waitForTimeout(100);
  out.phone = await page.evaluate(() => {
    const nav = document.querySelector(".rp-set-nav").getBoundingClientRect();
    const pane = document.querySelector(".rp-set-pane").getBoundingClientRect();
    const segs = Array.from(document.querySelectorAll(".rp-set-seg")).filter((s) => s.offsetParent !== null).map((s) => {
      const row = s.closest("[data-set-row]"), cs = getComputedStyle(row);
      const r = s.getBoundingClientRect(), rowR = row.getBoundingClientRect();
      const pl = parseFloat(cs.paddingLeft), pr = parseFloat(cs.paddingRight);
      const hs = Array.from(s.querySelectorAll("button")).map((b) => Math.round(b.getBoundingClientRect().height));
      return { key: row.dataset.setRow, width: Math.round(r.width), row: Math.round(rowR.width - pl - pr),
               rowLeft: Math.round(rowR.left + pl), left: Math.round(r.left), heights: hs };
    });
    return { stacked: nav.bottom <= pane.top + 1, segs, over: document.documentElement.scrollWidth - document.documentElement.clientWidth };
  });
  await ctx.close();
  await browser.close();
  out.errors = errors;
  console.log(JSON.stringify(out));
})().catch((e) => { console.log(JSON.stringify({ crash: e.stack })); process.exit(1); });
"""


@unittest.skipUnless(NODE and playwright_dir(), "Playwright not found")
class InTheBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "p.html"
            build(EXAMPLE, page)
            drv = Path(tmp) / "b.cjs"
            drv.write_text(BROWSER)
            r = subprocess.run([NODE, str(drv), playwright_dir(), str(RP / "launch.cjs"), str(page)],
                               capture_output=True, text=True, timeout=240)
        cls.res = json.loads(r.stdout.strip().splitlines()[-1])
        if "crash" in cls.res:
            raise AssertionError(cls.res["crash"])

    def test_no_page_errors(self):
        self.assertEqual(self.res["errors"], [])

    def test_one_group_shows_at_a_time(self):
        self.assertEqual(self.res["start"]["rows"], [r["key"] for r in TABLE if r["group"] == "read"])
        self.assertEqual(self.res["checks_rows"], [r["key"] for r in TABLE if r["group"] == "checks"])
        self.assertIn("No changes yet", self.res["start"]["bar"])

    def test_raise_only_field_refuses_lower_value_in_the_page(self):
        ref = self.res["refused"]
        self.assertEqual(ref["err"], "Smallest text can only go up from 16 px.")
        self.assertTrue(ref["err_shown"])
        self.assertEqual(ref["err_color"], ref["deny"])
        self.assertIn("No changes yet", ref["bar"])  # left out of the pending list

    def test_pending_change_shows_in_save_bar_and_saves_row_with_from(self):
        p = self.res["pending"]
        self.assertIn("1 change not saved yet", p["bar"])
        self.assertIn("Smallest text 16 → 18 px", p["bar"])
        self.assertEqual(" ".join(p["mark"].split()), "Not saved · was 16 px · Undo")
        self.assertTrue(p["amber"])
        self.assertFalse(p["err_shown"])
        self.assertEqual(p["dot"], "visible")
        row = dict(p["row"])
        self.assertTrue(row.pop("updated_at"))
        for k in ("page_version", "page"):
            row.pop(k, None)
        self.assertEqual(row, {"id": "PROOFS_MIN_TEXT", "section": "settings", "kind": "setting", "answer": "18",
                               "from": "16", "scope": "project", "note": ""})

    def test_reset_writes_default_as_answer(self):
        self.assertEqual(" ".join(self.res["changed_mark"].split()), "Changed · default Off · Reset")
        row = self.res["reset"]["row"]
        self.assertEqual((row["answer"], row["from"], row["kind"]), ("off", "american", "setting"))
        self.assertEqual(self.res["reset"]["pressed"], "Off")
        self.assertIn("2 changes not saved yet", self.res["reset"]["bar"])
        self.assertIn("Spelling check American → Off", self.res["reset"]["bar"])

    def test_undo_clears_the_answer_and_keeps_the_row_shape(self):
        row = dict(self.res["undo"]["row"])
        for k in ("updated_at", "page_version", "page"):
            row.pop(k, None)
        self.assertEqual(row, {"id": "PROOFS_MIN_TEXT", "section": "settings", "kind": "setting", "answer": None,
                               "from": "16", "scope": "project", "note": ""})
        self.assertEqual(self.res["undo"]["box"], "16")
        self.assertIn("1 change not saved yet", self.res["undo"]["bar"])

    def test_search_filters_across_groups(self):
        def hit(r):
            text = " ".join([r["key"], r["label"], r["help"]] + list((r.get("choice_labels") or {}).values()))
            return "wait" in text.lower()
        want = [r["key"] for r in TABLE if hit(r)]
        self.assertGreaterEqual(len({r["group"] for r in TABLE if hit(r)}), 3)
        self.assertEqual(self.res["search"], want)
        self.assertEqual(self.res["search_cleared"], self.res["checks_rows"])

    def test_phone_stacks_the_sidebar_and_segmented_controls_span_the_row(self):
        ph = self.res["phone"]
        self.assertTrue(ph["stacked"])
        self.assertEqual(ph["over"], 0)
        self.assertTrue(ph["segs"])
        for s in ph["segs"]:
            self.assertLessEqual(abs(s["width"] - s["row"]) + abs(s["left"] - s["rowLeft"]), 2, s)
            self.assertEqual(len(set(s["heights"])), 1, s)  # no option taller than its neighbors
            self.assertTrue(all(h >= 44 for h in s["heights"]), s)


@unittest.skipUnless(NODE and playwright_dir(), "Playwright not found")
class Smoke(unittest.TestCase):
    def test_smoke_settings_page_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "p.html"
            build(EXAMPLE, page)
            ok, res = review_page.smoke(page)
        self.assertTrue(ok, res)
        self.assertEqual(res["problems"], [])
        self.assertEqual(res["mode"], "settings")
        self.assertEqual(res["items"], len(KEYS))
        self.assertEqual(res["small_taps"], [])
        self.assertIn("SET PROOFS_DESIGN_PROFILE=", res["export"])
        self.assertFalse(res["send_to_claude"]["nothing_answered"]["hidden"])


if __name__ == "__main__":
    unittest.main()
