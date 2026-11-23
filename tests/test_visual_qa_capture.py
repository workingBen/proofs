import functools
import http.server
import json
import os
import shutil
import struct
import subprocess
import tempfile
import threading
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CAPTURE = ROOT / "skills" / "visual-qa" / "scripts" / "capture.cjs"
NODE = shutil.which("node")
FIXTURES = ROOT / "tests" / "fixtures" / "capture"
FINDINGS = ROOT / "skills" / "pr-qa" / "scripts" / "pr_qa_findings.py"
FLAG = "--disable-features=MacAppCodeSignClone"

# A stand-in for Playwright: chromium.launch records its options, then throws each
# scripted error in turn; once the script runs out it throws "fake: stop" so the
# capture ends before it tries to open a page.
FAKE = r"""
const fs = require('fs');
const script = JSON.parse(process.env.FAKE_SCRIPT);
let n = 0;
module.exports = { chromium: { launch: async (opts) => {
  fs.appendFileSync(process.env.FAKE_LOG, JSON.stringify(opts) + '\n');
  const step = script[n++];
  throw new Error(step || 'fake: stop');
} } };
"""


@unittest.skipUnless(NODE, "node not found")
class CaptureLaunch(unittest.TestCase):
    def run_capture(self, script, extra_env=None):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            pkg = tmp / "node_modules" / "playwright"
            pkg.mkdir(parents=True)
            (pkg / "package.json").write_text('{"name": "playwright", "main": "index.js"}')
            (pkg / "index.js").write_text(FAKE)
            (tmp / "pages.json").write_text(json.dumps({"base": "http://localhost:9", "pages": [{"name": "x", "path": "/"}]}))
            log = tmp / "launch.log"
            env = {k: v for k, v in os.environ.items() if k not in ("NODE_PATH", "PLAYWRIGHT_PATH", "PROOFS_PLAYWRIGHT", "PROOFS_BROWSER_CHANNEL")}
            env.update(HOME=str(tmp), FAKE_LOG=str(log), FAKE_SCRIPT=json.dumps(script), **(extra_env or {}))
            r = subprocess.run([NODE, str(CAPTURE), str(tmp / "pages.json"), "--out", str(tmp / "out")],
                               cwd=tmp, env=env, capture_output=True, text=True, timeout=60)
            calls = [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []
            return r, calls

    def test_uses_playwrights_browser_first_with_the_flag(self):
        r, calls = self.run_capture([])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("fake: stop", r.stderr)
        self.assertEqual(calls, [{"args": [FLAG]}])

    def test_falls_back_to_installed_chrome_without_downloading(self):
        r, calls = self.run_capture(["browserType.launch: Executable doesn't exist at /x"])
        self.assertEqual(calls, [{"args": [FLAG]}, {"channel": "chrome", "args": [FLAG]}])

    def test_channel_setting_forces_one_launch(self):
        r, calls = self.run_capture([], {"PROOFS_BROWSER_CHANNEL": "chrome"})
        self.assertEqual(calls, [{"channel": "chrome", "args": [FLAG]}])

    def test_missing_playwright_prints_the_no_download_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "pages.json").write_text('{"base": "http://localhost:9", "pages": []}')
            env = {k: v for k, v in os.environ.items() if k not in ("NODE_PATH", "PLAYWRIGHT_PATH")}
            env["HOME"] = tmp
            r = subprocess.run([NODE, str(CAPTURE), str(Path(tmp) / "pages.json")], cwd=tmp, env=env,
                               capture_output=True, text=True, timeout=60)
        if "Playwright not found" not in r.stderr:
            self.skipTest("a real Playwright is resolvable from the plugin folder")
        self.assertEqual(r.returncode, 2)
        self.assertIn("npm install --prefix ~/.cache/proofs-playwright", r.stderr)
        self.assertNotIn("PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD", r.stderr)
        self.assertNotIn("playwright install chromium", r.stderr)


# A Playwright stand-in that gets as far as the first page.goto and records its URL.
FAKE_PAGE = r"""
const fs = require('fs');
const page = { on() {}, goto: async (url) => { fs.appendFileSync(process.env.FAKE_LOG, url + '\n'); throw new Error('fake: stop'); } };
const context = { newPage: async () => page, close: async () => {} };
module.exports = { chromium: { launch: async () => ({ newContext: async () => context, close: async () => {} }) } };
"""


def playwright_dir():
    for c in (os.environ.get("PROOFS_PLAYWRIGHT"),
              str(Path.home() / ".cache" / "proofs-playwright" / "node_modules" / "playwright")):
        if c and Path(c).is_dir():
            return c
    return None


def decode_png(data):
    """(width, height, rows of RGBA-or-RGB bytes) for the 8-bit non-interlaced PNGs Chrome writes."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, width, height, ctype = 8, b"", 0, 0, 2
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            width, height, _, ctype = struct.unpack(">IIBB", body[:10])
        elif kind == b"IDAT":
            idat += body
        pos += 12 + length
    bpp = 4 if ctype == 6 else 3
    raw, stride, rows, prev = zlib.decompress(idat), width * bpp, [], bytearray(width * bpp)
    for y in range(height):
        f, line = raw[y * (stride + 1)], bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if f == 1:
                line[i] = (line[i] + a) & 255
            elif f == 2:
                line[i] = (line[i] + b) & 255
            elif f == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(line)
        prev = line
    return width, height, rows, bpp


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


@unittest.skipUnless(NODE and playwright_dir(), "Playwright not found: set PROOFS_PLAYWRIGHT or install it in ~/.cache/proofs-playwright")
class PhoneWidth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handler = functools.partial(Quiet, directory=str(FIXTURES))
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def capture(self, tmp, page, *extra):
        cfg = Path(tmp) / "pages.json"
        cfg.write_text(json.dumps({"base": self.base, "pages": [{"name": "t", "path": "/" + page}]}))
        out = Path(tmp) / "out"
        env = dict(os.environ, PROOFS_PLAYWRIGHT=playwright_dir())
        r = subprocess.run([NODE, str(CAPTURE), str(cfg), "--out", str(out), *extra],
                           env=env, capture_output=True, text=True, timeout=180)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r, out

    def result(self, out, prefix=""):
        data = json.loads((out / f"{prefix}measures.json").read_text())
        self.assertEqual(data["results"][0].get("error"), None)
        return data["results"][0]

    def test_phone_shot_is_390_css_px(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, out = self.capture(tmp, "fits.html", "--sizes", "390")
            res = self.result(out)
            self.assertEqual(res["measures"]["innerWidth"], 390)
            self.assertEqual(res["measures"]["pngWidth"], 780)
            width, _, rows, bpp = decode_png((out / "t-default-390.png").read_bytes())
            self.assertEqual(width, 780)
            # The 390 media query only matches if the page was laid out at 390 CSS px.
            self.assertEqual(tuple(rows[10][770 * bpp:770 * bpp + 3]), (0, 0xaa, 0))

    def test_clipped_overflow_is_caught(self):
        with tempfile.TemporaryDirectory() as tmp:
            r, out = self.capture(tmp, "wide-nav.html", "--sizes", "390")
            m = self.result(out)["measures"]
            self.assertEqual(m["scrollWidth"], 390)
            self.assertGreaterEqual(m["widestRight"], 455)
            self.assertGreaterEqual(m["sideways"], 65)
            self.assertIn("clipped", r.stdout)

    def test_clipping_wrapper_does_not_hide_overflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            r, out = self.capture(tmp, "wrapper-clip.html", "--sizes", "390")
            m = self.result(out)["measures"]
            self.assertGreaterEqual(m["widestRight"], 455)
            self.assertIn("clipped", r.stdout)

    def test_offscreen_drawer_is_not_overflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, out = self.capture(tmp, "drawer.html", "--sizes", "390")
            self.assertEqual(self.result(out)["measures"]["sideways"], 0)

    def test_scrolling_carousel_is_not_overflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, out = self.capture(tmp, "carousel.html", "--sizes", "390")
            self.assertEqual(self.result(out)["measures"]["sideways"], 0)

    def test_default_sizes_give_unique_pr_qa_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.capture(tmp, "fits.html", "--evidence", "before")
            self.capture(tmp, "wide-nav.html", "--evidence", "after")
            out = Path(tmp) / "out"
            for label in ("before", "after"):
                shots = json.loads((out / f"{label}.json").read_text())["shots"]
                keys = [(s["slug"], s["size"]) for s in shots]
                self.assertEqual(len(keys), 3)
                self.assertEqual(len(set(keys)), 3, keys)
            r = subprocess.run(["python3", str(FINDINGS), "--dir", str(out)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("sideways", r.stdout)

    def test_evidence_carries_small_targets_and_culprit(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.capture(tmp, "wide-nav.html", "--sizes", "390", "--evidence", "after")
            shot = json.loads((Path(tmp) / "out" / "after.json").read_text())["shots"][0]
            self.assertIn("smallTargets", shot)
            self.assertGreaterEqual(shot["overflowing"][0]["past"], 65)
            self.assertEqual(shot["overflowing"][0]["tag"], "nav")

    def test_real_phone_overflow_is_a_finding_not_an_untrusted_capture(self):
        # Rails run 1: an emulated phone widens its layout to fit content that is too wide
        # (407 px at 390), the way a real phone zooms out. That is the page's bug, so the
        # capture records it and keeps the phone's text and tap numbers.
        with tempfile.TemporaryDirectory() as tmp:
            r, out = self.capture(tmp, "overflow-17.html", "--sizes", "390", "--evidence", "before")
            res = self.result(out, "before-")
            m = res["measures"]
            self.assertEqual(m["sideways"], 17)
            self.assertEqual(m["zoomedOut"], {"layoutWidth": 407, "screenWidth": 390, "past": 17})
            self.assertEqual(m["clientWidth"], 390)
            self.assertEqual(m["overflowing"][0]["tag"], "div")
            self.assertEqual(m["overflowing"][0]["past"], 17)
            self.assertGreaterEqual(m["smallTapCount"], 1)
            self.assertGreaterEqual(m["smallTextCount"], 1)
            verdict = {k: (v, ok) for k, v, ok in res["verdicts"]}
            self.assertEqual(verdict["sideways scroll"], ("17px, zoomed", False))
            self.assertIn("zoomed", r.stdout)
            self.assertIn("zooms out", r.stdout)
            shot = json.loads((out / "before.json").read_text())["shots"][0]
            self.assertEqual(shot["overflow"], 17)
            self.assertEqual(shot["clientWidth"], 390)
            self.assertEqual(shot["overflowing"][0]["past"], 17)

    def test_mid_word_break_is_counted_and_a_hyphen_break_is_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, out = self.capture(tmp, "midword.html", "--sizes", "1440")
            m = self.result(out)["measures"]
            self.assertEqual(len(m["midWord"]), 1, m["midWord"])
            self.assertTrue(m["midWord"][0].startswith("authentic"), m["midWord"])

    def test_fitting_page_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, out = self.capture(tmp, "fits.html", "--sizes", "390")
            self.assertEqual(self.result(out)["measures"]["sideways"], 0)

    def test_evidence_json_matches_pr_qa_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.capture(tmp, "wide-nav.html", "--sizes", "390,1440", "--evidence", "before")
            out = Path(tmp) / "out"
            shots = json.loads((out / "before.json").read_text())["shots"]
            self.assertEqual(sorted(s["size"] for s in shots), ["desktop", "phone"])
            phone = [s for s in shots if s["size"] == "phone"][0]
            for k in ("label", "slug", "pageLabel", "path", "file", "overflow", "scrollWidth",
                      "clientWidth", "widestRight", "pngWidth", "innerWidth", "errors"):
                self.assertIn(k, phone)
            self.assertTrue((out / phone["file"]).exists(), phone["file"])
            self.assertTrue(phone["file"].startswith("before-"))
            self.assertTrue((out / "before-measures.json").exists())
            self.assertTrue((out / "before-summary.md").exists())
            r = subprocess.run(["python3", str(FINDINGS), "--dir", str(out)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            json.loads(r.stdout)

    def test_1280_evidence_page_label_says_1280(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.capture(tmp, "fits.html", "--sizes", "1440,1280", "--evidence", "after")
            shots = json.loads((Path(tmp) / "out" / "after.json").read_text())["shots"]
            by = {s["label"]: s for s in shots}
            self.assertNotIn("(1280)", by["1440"]["pageLabel"])
            self.assertTrue(by["1280"]["pageLabel"].endswith(" (1280)"), by["1280"]["pageLabel"])

    def test_breakpoint_width_gets_its_own_pr_qa_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.capture(tmp, "fits.html", "--sizes", "1440,1040", "--evidence", "after")
            shots = json.loads((Path(tmp) / "out" / "after.json").read_text())["shots"]
            by = {s["label"]: s for s in shots}
            self.assertEqual(by["1040"]["size"], "desktop")
            self.assertTrue(by["1040"]["pageLabel"].endswith(" (1040)"), by["1040"]["pageLabel"])
            self.assertNotEqual(by["1040"]["slug"], by["1440"]["slug"])

    def test_two_labels_share_one_out_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.capture(tmp, "fits.html", "--sizes", "390", "--evidence", "before")
            self.capture(tmp, "fits.html", "--sizes", "390", "--evidence", "after")
            names = {p.name for p in (Path(tmp) / "out").iterdir()}
            self.assertTrue({"before.json", "after.json", "before-measures.json", "after-measures.json"} <= names)


@unittest.skipUnless(NODE, "node not found")
class CaptureOptions(unittest.TestCase):
    def test_base_url_env_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            pkg = tmp / "node_modules" / "playwright"
            pkg.mkdir(parents=True)
            (pkg / "package.json").write_text('{"name": "playwright", "main": "index.js"}')
            (pkg / "index.js").write_text(FAKE_PAGE)
            (tmp / "pages.json").write_text(json.dumps({"base": "http://localhost:9", "pages": [{"name": "x", "path": "/p"}]}))
            log = tmp / "urls.log"
            env = {k: v for k, v in os.environ.items() if k not in ("NODE_PATH", "PLAYWRIGHT_PATH", "PROOFS_PLAYWRIGHT")}
            env.update(HOME=str(tmp), FAKE_LOG=str(log), PROOFS_BASE_URL="http://127.0.0.1:4567")
            subprocess.run([NODE, str(CAPTURE), str(tmp / "pages.json"), "--out", str(tmp / "out"), "--sizes", "390"],
                           cwd=tmp, env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(log.read_text().split(), ["http://127.0.0.1:4567/p"])

    def test_untrusted_width_exits_3(self):
        fake = r"""
const page = { on() {}, goto: async () => {}, click: async () => {}, waitForSelector: async () => {},
  screenshot: async () => {},
  evaluate: async (fn, arg) => (arg && 'minText' in arg ? { innerWidth: 500 } : undefined) };
const context = { newPage: async () => page, close: async () => {} };
module.exports = { chromium: { launch: async () => ({ newContext: async () => context, close: async () => {} }) } };
"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            pkg = tmp / "node_modules" / "playwright"
            pkg.mkdir(parents=True)
            (pkg / "package.json").write_text('{"name": "playwright", "main": "index.js"}')
            (pkg / "index.js").write_text(fake)
            (tmp / "pages.json").write_text(json.dumps({"base": "http://localhost:9", "pages": [{"name": "x", "path": "/"}]}))
            env = {k: v for k, v in os.environ.items() if k not in ("NODE_PATH", "PLAYWRIGHT_PATH", "PROOFS_PLAYWRIGHT")}
            env["HOME"] = str(tmp)
            r = subprocess.run([NODE, str(CAPTURE), str(tmp / "pages.json"), "--out", str(tmp / "out"), "--sizes", "390"],
                               cwd=tmp, env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 3, r.stderr)
            self.assertIn("the browser laid the page out at 500 px, not 390 px; the capture is not trustworthy", r.stderr)
            self.assertFalse((tmp / "out" / "measures.json").exists())

    def test_a_viewport_that_stays_wide_without_phone_emulation_is_still_untrusted(self):
        # The old headless-Chrome-on-macOS minimum width: the layout is wide in a plain
        # desktop context too, so the viewport itself is wrong, not the page.
        fake = r"""
const fs = require('fs');
const page = { on() {}, goto: async () => {}, click: async () => {}, waitForSelector: async () => {},
  screenshot: async () => {},
  evaluate: async (fn, arg) => (arg && 'minText' in arg ? { innerWidth: 500, scrollWidth: 500, widestRight: 500, overflowing: [] } : undefined) };
const context = { newPage: async () => page, close: async () => {} };
module.exports = { chromium: { launch: async () => ({ close: async () => {},
  newContext: async (o) => { fs.appendFileSync(process.env.FAKE_LOG, JSON.stringify(o) + '\n'); return context; } }) } };
"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            pkg = tmp / "node_modules" / "playwright"
            pkg.mkdir(parents=True)
            (pkg / "package.json").write_text('{"name": "playwright", "main": "index.js"}')
            (pkg / "index.js").write_text(fake)
            (tmp / "pages.json").write_text(json.dumps({"base": "http://localhost:9", "pages": [{"name": "x", "path": "/"}]}))
            log = tmp / "ctx.log"
            env = {k: v for k, v in os.environ.items() if k not in ("NODE_PATH", "PLAYWRIGHT_PATH", "PROOFS_PLAYWRIGHT")}
            env.update(HOME=str(tmp), FAKE_LOG=str(log))
            r = subprocess.run([NODE, str(CAPTURE), str(tmp / "pages.json"), "--out", str(tmp / "out"), "--sizes", "390"],
                               cwd=tmp, env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 3, r.stderr)
            self.assertIn("the browser laid the page out at 500 px, not 390 px; the capture is not trustworthy", r.stderr)
            ctx = [json.loads(l) for l in log.read_text().splitlines()]
            # the phone context, then one plain context at the same width to tell the two apart
            self.assertEqual(len(ctx), 2)
            self.assertTrue(ctx[0].get("isMobile"))
            self.assertNotIn("isMobile", ctx[1])
            self.assertEqual(ctx[1]["viewport"]["width"], 390)

    def run_sizes(self, sizes):
        """Run with a Playwright stand-in that records each context's viewport; returns (result, widths)."""
        fake = r"""
const fs = require('fs');
const page = { on() {}, goto: async () => { throw new Error('fake: stop'); } };
const context = { newPage: async () => page, close: async () => {} };
module.exports = { chromium: { launch: async () => ({ close: async () => {},
  newContext: async (o) => { fs.appendFileSync(process.env.FAKE_LOG, JSON.stringify(o) + '\n'); return context; } }) } };
"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            pkg = tmp / "node_modules" / "playwright"
            pkg.mkdir(parents=True)
            (pkg / "package.json").write_text('{"name": "playwright", "main": "index.js"}')
            (pkg / "index.js").write_text(fake)
            (tmp / "pages.json").write_text(json.dumps({"base": "http://localhost:9", "pages": [{"name": "x", "path": "/"}]}))
            log = tmp / "ctx.log"
            env = {k: v for k, v in os.environ.items() if k not in ("NODE_PATH", "PLAYWRIGHT_PATH", "PROOFS_PLAYWRIGHT")}
            env.update(HOME=str(tmp), FAKE_LOG=str(log))
            r = subprocess.run([NODE, str(CAPTURE), str(tmp / "pages.json"), "--out", str(tmp / "out"), "--sizes", sizes],
                               cwd=tmp, env=env, capture_output=True, text=True, timeout=60)
            ctx = [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []
            return r, ctx

    def test_sizes_take_a_breakpoint_width(self):
        # Django run 2: a PR adding an lg: two-column layout needs a shot just above 1024.
        r, ctx = self.run_sizes("390,1440,1040")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([c["viewport"]["width"] for c in ctx], [1440, 1040, 390])
        wide = [c for c in ctx if c["viewport"]["width"] == 1040][0]
        self.assertNotIn("isMobile", wide)
        self.assertEqual(wide["viewport"]["height"], 900)

    def test_sizes_refuse_widths_out_of_range(self):
        for bad in ("100", "1040px", "9000"):
            r, ctx = self.run_sizes(bad)
            self.assertEqual(r.returncode, 1, bad)
            self.assertIn("matches none", r.stderr)
            self.assertEqual(ctx, [])

    def test_not_found_message_names_proofs_playwright(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "pages.json").write_text('{"base": "http://localhost:9", "pages": []}')
            env = {k: v for k, v in os.environ.items() if k not in ("NODE_PATH", "PLAYWRIGHT_PATH", "PROOFS_PLAYWRIGHT")}
            env["HOME"] = tmp
            r = subprocess.run([NODE, str(CAPTURE), str(Path(tmp) / "pages.json")], cwd=tmp, env=env,
                               capture_output=True, text=True, timeout=60)
        if "Playwright not found" not in r.stderr:
            self.skipTest("a real Playwright is resolvable from the plugin folder")
        self.assertIn("PROOFS_PLAYWRIGHT", r.stderr)

    def test_how_to_has_no_env_prefix(self):
        import re
        line = "npm install --prefix ~/.cache/proofs-playwright playwright@1.61.1"
        for path in (ROOT / "shared" / "review_page" / "launch.cjs", ROOT / "shared" / "review_page" / "review_page.py",
                     ROOT / "reference" / "review-page.md"):
            text = path.read_text()
            self.assertIn(line, text, path)
            self.assertNotIn("PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD", text, path)
            for l in text.splitlines():
                if line in l:
                    self.assertIsNone(re.match(r"^`?[A-Z_]+=", l.strip()), l)


if __name__ == "__main__":
    unittest.main()
