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
            # A heading that breaks is its own element; "near" is a heading above it, never itself.
            self.assertEqual(m["midWordAt"][0]["el"], "h3")
            self.assertEqual(m["midWordAt"][0]["near"], "")

    def test_a_row_text_align_does_not_center_is_flagged(self):
        # Angular run 1: a footer column centered with text-align at 390, and its "Events"
        # link made display:flex for a badge, so it sat at the left. Nothing flagged it.
        with tempfile.TemporaryDirectory() as tmp:
            r, out = self.capture(tmp, "off-center.html", "--sizes", "390", "--evidence", "after")
            res = self.result(out, "after-")
            rows = res["measures"]["offCenter"]
            self.assertEqual(len(rows), 2, rows)
            self.assertEqual(res["measures"]["offCenterCount"], 2)
            events = rows[0]
            self.assertTrue(events["text"].startswith("Events"), events)
            self.assertEqual(events["tag"], "a")
            self.assertEqual(events["left"], 0)
            self.assertGreater(events["right"] - events["left"], 100)
            self.assertEqual(rows[1]["tag"], "div")
            verdict = {k: (v, ok) for k, v, ok in res["verdicts"]}
            self.assertEqual(verdict["off-center rows"], (2, False))
            self.assertIn("off-center rows: 2", r.stdout)
            self.assertIn("off-center:", r.stdout)
            shot = json.loads((out / "after.json").read_text())["shots"][0]
            self.assertEqual(shot["offCenterCount"], 2)
            self.assertTrue(shot["offCenter"][0]["text"].startswith("Events"))

    def test_centered_rows_and_left_aligned_pages_are_not_off_center(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, out = self.capture(tmp, "fits.html", "--sizes", "390,1440")
            data = json.loads((out / "measures.json").read_text())
            for res in data["results"]:
                self.assertEqual(res["measures"]["offCenter"], [], res["viewport"])
            _, out = self.capture(tmp, "midword.html", "--sizes", "1440")
            self.assertEqual(self.result(out)["measures"]["offCenterCount"], 0)

    # Astro run 1: AstroWind fades each section in as it scrolls into view, and the capture
    # never scrolled, so every full-page shot was blank below the hero and pr-qa called it clean.
    def test_sections_that_reveal_on_scroll_are_in_the_full_page_shot(self):
        with tempfile.TemporaryDirectory() as tmp:
            r, out = self.capture(tmp, "reveal.html", "--sizes", "1440")
            m = self.result(out)["measures"]
            width, height, rows, bpp = decode_png((out / "t-default-1440-full.png").read_bytes())
            # Four 400 px blue blocks, all below the first screen (900 px tall).
            blue = sum(1 for row in rows[900:] if tuple(row[1000 * bpp:1000 * bpp + 3]) == (0, 0, 255))
            self.assertGreaterEqual(blue, 4 * 400 - 8, (width, height))
            self.assertEqual(m["hiddenBlocks"], 0)
            self.assertFalse(m["blank"]["flagged"], m["blank"])
            verdict = {k: (v, ok) for k, v, ok in self.result(out)["verdicts"]}
            self.assertTrue(verdict["blank or hidden content"][1])
            self.assertNotIn("blank:", r.stdout)

    def test_content_that_stays_hidden_is_flagged_as_blank(self):
        with tempfile.TemporaryDirectory() as tmp:
            r, out = self.capture(tmp, "hidden.html", "--sizes", "1440", "--evidence", "after")
            res = self.result(out, "after-")
            m = res["measures"]
            self.assertEqual(m["hiddenBlocks"], 4)
            self.assertTrue(m["blank"]["flagged"], m["blank"])
            self.assertGreaterEqual(m["blank"]["flatShare"], 0.9)
            verdict = {k: (v, ok) for k, v, ok in res["verdicts"]}
            self.assertFalse(verdict["blank or hidden content"][1])
            self.assertIn("blank:", r.stdout)
            shot = json.loads((out / "after.json").read_text())["shots"][0]
            self.assertTrue(shot["blank"]["flagged"])
            self.assertEqual(shot["hiddenBlocks"], 4)
            f = subprocess.run(["python3", str(FINDINGS), "--dir", str(out)], capture_output=True, text=True)
            result = json.loads(f.stdout)
            self.assertNotEqual(result["verdict"], "clean")
            self.assertTrue(any("blank" in x["title"] for x in result["findings"]), result["findings"])

    def test_hover_overlays_and_short_pages_are_not_blank(self):
        with tempfile.TemporaryDirectory() as tmp:
            for page, sizes in (("hover-overlays.html", "1440,390"), ("fits.html", "1440,390"),
                                ("columns.html", "1440"), ("midword.html", "1440")):
                with self.subTest(page=page):
                    _, out = self.capture(tmp, page, "--sizes", sizes)
                    for res in json.loads((out / "measures.json").read_text())["results"]:
                        self.assertEqual(res["measures"]["hiddenBlocks"], 0, (page, res["viewport"]))
                        self.assertFalse(res["measures"]["blank"]["flagged"], (page, res["viewport"], res["measures"]["blank"]))

    def test_a_column_out_of_line_or_not_centered_is_flagged(self):
        # Astro run 1: the steps section's max-w-5xl column is centered but its content is
        # left-aligned, so its left edge sat 128 px right of the blocks above and below it.
        with tempfile.TemporaryDirectory() as tmp:
            r, out = self.capture(tmp, "columns.html", "--sizes", "1440", "--evidence", "after")
            res = self.result(out, "after-")
            cols = res["measures"]["offColumns"]
            self.assertEqual(len(cols), 2, cols)
            steps, shifted = cols
            self.assertEqual(steps["kind"], "edge")
            self.assertTrue(steps["text"].startswith("Steps"), steps)
            self.assertEqual(steps["edge"] - steps["neighbors"], 128)
            self.assertEqual(shifted["kind"], "column")
            self.assertTrue(shifted["text"].startswith("Shifted"), shifted)
            # 300 px of margin on the left; 1440 - 300 - (1024 + 48 padding) = 68 on the right.
            self.assertEqual((shifted["left"], shifted["right"]), (300, 68))
            self.assertEqual(res["measures"]["offColumnCount"], 2)
            verdict = {k: (v, ok) for k, v, ok in res["verdicts"]}
            self.assertEqual(verdict["off-center columns"], (2, False))
            self.assertIn("off-center columns: 2", r.stdout)
            shot = json.loads((out / "after.json").read_text())["shots"][0]
            self.assertEqual(shot["offColumnCount"], 2)

    def test_ordinary_pages_have_no_off_center_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            for page in ("fits.html", "off-center.html", "midword.html", "reveal.html", "hover-overlays.html"):
                with self.subTest(page=page):
                    _, out = self.capture(tmp, page, "--sizes", "1440,390")
                    for res in json.loads((out / "measures.json").read_text())["results"]:
                        self.assertEqual(res["measures"]["offColumns"], [], (page, res["viewport"]))
            _, out = self.capture(tmp, "columns.html", "--sizes", "390")
            self.assertEqual(self.result(out)["measures"]["offColumns"], [])

    # Astro run 2: AstroWind's proof strip and stats band have no heading, and nothing checked.
    def test_sections_without_headings_are_a_finding_not_a_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            for size in ("1440", "390"):
                with self.subTest(size=size):
                    r, out = self.capture(tmp, "untitled.html", "--sizes", size, "--evidence", "after")
                    res = self.result(out, "after-")
                    rows = res["measures"]["untitled"]
                    self.assertEqual([x["id"] for x in rows], ["proof", "stats"], rows)
                    self.assertEqual(res["measures"]["untitledCount"], 2)
                    self.assertTrue(rows[0]["text"].startswith("#1 most starred"), rows[0])
                    self.assertGreaterEqual(rows[0]["height"], 120)
                    verdict = {k: (v, ok) for k, v, ok in res["verdicts"]}
                    # A note for the reader, not a failed check.
                    self.assertEqual(verdict["sections without headings"], (2, None))
                    self.assertIn("sections without headings: 2", r.stdout)
                    self.assertIn("without a heading:", r.stdout)
                    self.assertIn('"#1 most starred', r.stdout)
                    shot = json.loads((out / "after.json").read_text())["shots"][0]
                    self.assertEqual(shot["untitledCount"], 2)

    def test_pages_with_headed_sections_have_no_untitled_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            for page in ("columns.html", "fits.html", "reveal.html"):
                with self.subTest(page=page):
                    r, out = self.capture(tmp, page, "--sizes", "1440")
                    m = self.result(out)["measures"]
                    self.assertEqual(m["untitled"], [], page)
                    self.assertNotIn("sections without headings", r.stdout)

    def test_a_mid_word_break_in_a_break_all_pre_is_counted(self):
        # Astro run 1: the quick-start command, a <pre> with break-all, broke "--tem" / "plate" at 390.
        with tempfile.TemporaryDirectory() as tmp:
            _, out = self.capture(tmp, "midword-pre.html", "--sizes", "390")
            words = self.result(out)["measures"]["midWord"]
            self.assertGreaterEqual(len(words), 1, words)
            self.assertTrue(all("|" in w for w in words), words)
            self.assertFalse(any(w.startswith("somethingv") for w in words), words)
            _, out = self.capture(tmp, "midword-anywhere.html", "--sizes", "390")
            words = self.result(out)["measures"]["midWord"]
            self.assertEqual(len(words), 1, words)

    def test_a_mid_word_break_says_where_it_is(self):
        # Astro run 3 (B1): the capture named only "tem|plate", the 390 shot was too tall to read,
        # and the session put the break in the hero headline; it was in the quick-start command.
        with tempfile.TemporaryDirectory() as tmp:
            r, out = self.capture(tmp, "tall-midword.html", "--sizes", "390")
            m = self.result(out)["measures"]
            self.assertTrue(all("|" in w for w in m["midWord"]), m["midWord"])
            spot = m["midWordAt"][0]
            self.assertIn("|", spot["at"])
            self.assertIn("pre.cmd", spot["el"])
            self.assertIn("#quick-start", spot["el"])
            self.assertEqual(spot["near"], "Quick start")
            self.assertGreater(spot["y"], 6000)
            self.assertLess(spot["y"], 6200)
            summary = (out / "summary.md").read_text()
            self.assertIn("mid-word breaks:", summary)
            self.assertIn("pre.cmd", summary)
            self.assertIn("y %d" % spot["y"], summary)
            self.assertIn(spot["part"], summary)
            self.assertIn("pre.cmd", r.stdout)

    def test_a_tall_page_is_cut_into_readable_parts(self):
        # Astro run 3: a 15,677 px page at 2x made a 31,354 px PNG, which no image reader shows legibly.
        with tempfile.TemporaryDirectory() as tmp:
            r, out = self.capture(tmp, "tall-midword.html", "--sizes", "390,1280")
            data = json.loads((out / "measures.json").read_text())
            for res in data["results"]:
                m = res["measures"]
                parts = m["parts"]
                self.assertGreaterEqual(len(parts), 2, res["viewport"])
                self.assertEqual(parts[0]["top"], 0)
                self.assertEqual(parts[-1]["bottom"], m["pageHeight"])
                for a, b in zip(parts, parts[1:]):
                    self.assertEqual(a["bottom"], b["top"])
                for p in parts:
                    png = (out / p["file"]).read_bytes()
                    w, h = struct.unpack(">II", png[16:24])
                    # One PNG pixel per CSS pixel, and no taller than four widths (or 1,600 px).
                    self.assertEqual(w, m["viewport"]["w"])
                    self.assertLessEqual(h, min(1600, 4 * w))
                    self.assertEqual(h, p["bottom"] - p["top"])
                # A full shot over 16,384 px at 2x is taken at 1x, and the overflow check still holds.
                full = (out / f"{res['file']}-full.png").read_bytes()
                fw, fh = struct.unpack(">II", full[16:24])
                self.assertLessEqual(fh, 16384)
                self.assertEqual(m["sideways"], 0, res["viewport"])
                # The blank check reads the 1x shot at 1x: it covers the page below the first screen.
                self.assertAlmostEqual(m["blank"]["regionPx"], m["pageHeight"] - m["viewport"]["h"], delta=2)
            phone = [x for x in data["results"] if x["viewport"] == "390"][0]["measures"]
            self.assertEqual(phone["fullScale"], 1)
            # Parts are cut from the full shot, not shot again: a second, clipped screenshot
            # re-lays out the page and drew AstroWind's sticky header over its hero.
            res390 = [x for x in data["results"] if x["viewport"] == "390"][0]
            _, _, full_rows, _ = decode_png((out / f"{res390['file']}-full.png").read_bytes())
            second = phone["parts"][1]
            _, _, part_rows, _ = decode_png((out / second["file"]).read_bytes())
            self.assertEqual(bytes(part_rows[0]), bytes(full_rows[second["top"]]))
            self.assertEqual(bytes(part_rows[-1]), bytes(full_rows[second["bottom"] - 1]))
            spot = phone["midWordAt"][0]
            part = [p for p in phone["parts"] if p["file"] == spot["part"]][0]
            self.assertTrue(part["top"] <= spot["y"] < part["bottom"])
            self.assertIn("-part-", r.stdout)

    def test_a_short_page_has_no_parts(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, out = self.capture(tmp, "midword.html", "--sizes", "1440,390")
            for res in json.loads((out / "measures.json").read_text())["results"]:
                self.assertEqual(res["measures"]["parts"], [])
                self.assertEqual(res["measures"]["fullScale"], 2 if res["viewport"] == "390" else 1)

    def test_compare_names_entries_that_are_new_since_an_earlier_capture(self):
        # Astro run 3 (B2): the fix took small tap targets from 11 to 9, and 3 of the 9 were new.
        with tempfile.TemporaryDirectory() as tmp:
            before = Path(tmp) / "before"
            cfg = Path(tmp) / "pages.json"
            env = dict(os.environ, PROOFS_PLAYWRIGHT=playwright_dir())
            for page, outdir, extra in (("taps-before.html", before, []),
                                        ("taps-after.html", Path(tmp) / "after", ["--compare", str(before / "measures.json")])):
                cfg.write_text(json.dumps({"base": self.base, "pages": [{"name": "t", "path": "/" + page}]}))
                r = subprocess.run([NODE, str(CAPTURE), str(cfg), "--out", str(outdir), "--sizes", "390", *extra],
                                   env=env, capture_output=True, text=True, timeout=180)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            m = self.result(Path(tmp) / "after")["measures"]
            self.assertEqual([t["el"] for t in m["newSince"]["smallTaps"]], ["Made"])
            self.assertEqual(m["newSince"]["midWord"], [])
            self.assertIn("new since the earlier capture", r.stdout)
            self.assertIn('small tap targets: "Made"', r.stdout)
            self.assertNotIn('"Docs"', r.stdout.split("new since the earlier capture")[1])

    def test_compare_says_when_there_is_nothing_to_compare_against(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, out = self.capture(tmp, "taps-before.html", "--sizes", "390")
            earlier = Path(tmp) / "earlier.json"
            earlier.write_text((out / "measures.json").read_text())
            r, _ = self.capture(tmp, "taps-after.html", "--sizes", "1280", "--compare", str(earlier))
            self.assertIn("no earlier capture of t default at 1280", r.stdout)

    def capture_fails(self, tmp, page, *extra):
        cfg = Path(tmp) / "pages.json"
        cfg.write_text(json.dumps({"base": self.base, "pages": [{"name": "t", "path": "/" + page}]}))
        out = Path(tmp) / "out"
        env = dict(os.environ, PROOFS_PLAYWRIGHT=playwright_dir())
        return subprocess.run([NODE, str(CAPTURE), str(cfg), "--out", str(out), *extra],
                              env=env, capture_output=True, text=True, timeout=180), out

    def test_a_404_is_a_loud_capture_failure_not_a_page(self):
        # SvelteKit run 1: "base/" + "/" made "//", which SvelteKit answers with its 404 page;
        # the capture measured it and pr-qa's findings called it clean.
        with tempfile.TemporaryDirectory() as tmp:
            r, out = self.capture_fails(tmp, "no-such-page.html", "--sizes", "390", "--evidence", "before")
            self.assertEqual(r.returncode, 6, r.stdout + r.stderr)
            self.assertIn("answered HTTP 404", r.stderr)
            self.assertIn("not the page", r.stderr)
            self.assertIn("/no-such-page.html", r.stderr)
            res = json.loads((out / "before-measures.json").read_text())["results"][0]
            self.assertEqual(res["status"], 404)
            self.assertIn("404", res["error"])
            ev = json.loads((out / "before.json").read_text())
            self.assertEqual(ev["shots"], [])
            self.assertEqual(ev["failures"][0]["status"], 404)
            self.assertIn("FAILED", r.stdout)
            f = subprocess.run(["python3", str(FINDINGS), "--dir", str(out)], capture_output=True, text=True)
            self.assertNotEqual(json.loads(f.stdout)["verdict"], "clean")

    def test_an_error_page_served_with_200_is_a_capture_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            r, out = self.capture_fails(tmp, "error-page.html", "--sizes", "1440")
            self.assertEqual(r.returncode, 6, r.stdout + r.stderr)
            self.assertIn("looks like an error page", r.stderr)
            self.assertIn("404 Not Found", r.stderr)

    def test_a_page_that_only_mentions_errors_is_captured(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, out = self.capture(tmp, "about-errors.html", "--sizes", "1440")
            self.assertEqual(self.result(out)["measures"]["sideways"], 0)

    def test_base_with_a_trailing_slash_and_a_rooted_path_reach_the_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "pages.json"
            cfg.write_text(json.dumps({"base": self.base + "/", "pages": [{"name": "t", "path": "/fits.html"}]}))
            out = Path(tmp) / "out"
            env = dict(os.environ, PROOFS_PLAYWRIGHT=playwright_dir())
            r = subprocess.run([NODE, str(CAPTURE), str(cfg), "--out", str(out), "--sizes", "390"],
                               env=env, capture_output=True, text=True, timeout=180)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(self.result(out)["url"], self.base + "/fits.html")

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

    def join(self, base, path):
        js = "process.stdout.write(require(process.argv[1]).joinUrl(process.argv[2], process.argv[3]))"
        r = subprocess.run([NODE, "-e", js, str(CAPTURE), base, path], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_join_url_makes_exactly_one_slash(self):
        cases = [
            ("http://localhost:3311/", "/", "http://localhost:3311/"),
            ("http://localhost:3311", "/", "http://localhost:3311/"),
            ("http://localhost:3311/", "", "http://localhost:3311/"),
            ("http://localhost:3311", "", "http://localhost:3311/"),
            ("http://localhost:3311/", "/pricing", "http://localhost:3311/pricing"),
            ("http://localhost:3311", "pricing", "http://localhost:3311/pricing"),
            ("http://localhost:3311//", "//pricing", "http://localhost:3311/pricing"),
            ("http://localhost:3311/app/", "/pricing?x=1", "http://localhost:3311/app/pricing?x=1"),
            ("http://localhost:3311/app", "list#top", "http://localhost:3311/app/list#top"),
            ("http://localhost:3311/list", "?as=empty", "http://localhost:3311/list?as=empty"),
            ("http://localhost:3311/", "#top", "http://localhost:3311/#top"),
            ("file:///srv/site/.proofs/pages", "/review.html", "file:///srv/site/.proofs/pages/review.html"),
            ("file:///srv/site/.proofs/pages/", "review.html", "file:///srv/site/.proofs/pages/review.html"),
            ("http://localhost:3311/", "http://127.0.0.1:4000/other", "http://127.0.0.1:4000/other"),
        ]
        for base, path, want in cases:
            with self.subTest(base=base, path=path):
                self.assertEqual(self.join(base, path), want)

    def test_base_url_with_trailing_slash_does_not_double_the_slash(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            pkg = tmp / "node_modules" / "playwright"
            pkg.mkdir(parents=True)
            (pkg / "package.json").write_text('{"name": "playwright", "main": "index.js"}')
            (pkg / "index.js").write_text(FAKE_PAGE)
            (tmp / "pages.json").write_text(json.dumps({"base": "http://localhost:9", "pages": [{"name": "x", "path": "/"}]}))
            log = tmp / "urls.log"
            env = {k: v for k, v in os.environ.items() if k not in ("NODE_PATH", "PLAYWRIGHT_PATH", "PROOFS_PLAYWRIGHT")}
            env.update(HOME=str(tmp), FAKE_LOG=str(log), PROOFS_BASE_URL="http://localhost:3311/")
            subprocess.run([NODE, str(CAPTURE), str(tmp / "pages.json"), "--out", str(tmp / "out"), "--sizes", "390"],
                           cwd=tmp, env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(log.read_text().split(), ["http://localhost:3311/"])

    def run_pages_file(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            pkg = tmp / "node_modules" / "playwright"
            pkg.mkdir(parents=True)
            (pkg / "package.json").write_text('{"name": "playwright", "main": "index.js"}')
            (pkg / "index.js").write_text(FAKE_PAGE)
            (tmp / "pages.json").write_text(text)
            env = {k: v for k, v in os.environ.items() if k not in ("NODE_PATH", "PLAYWRIGHT_PATH", "PROOFS_PLAYWRIGHT", "PROOFS_BASE_URL")}
            env.update(HOME=str(tmp), FAKE_LOG=str(tmp / "urls.log"))
            return subprocess.run([NODE, str(CAPTURE), str(tmp / "pages.json"), "--out", str(tmp / "out"), "--sizes", "390"],
                                  cwd=tmp, env=env, capture_output=True, text=True, timeout=60)

    def test_malformed_pages_file_is_one_plain_line(self):
        # SvelteKit run 1: a bare list crashed with "TypeError: cfg.pages is not iterable" and a stack trace.
        cases = [
            ('{"base": "http://localhost:9", "routes": [{"name": "home", "path": "/"}]}', 'needs a top-level "pages" list'),
            ('"home"', 'needs a top-level "pages" list'),
            # A bare list is taken (below), but without with_server.py there is no base for it.
            ('[{"name": "home", "path": "/"}]', 'needs a "base"'),
            ('[]', '"pages" is empty'),
            ('[{"name": "home"}]', 'pages[0] needs a "path"'),
            ('{"base": "http://localhost:9", "pages": {"name": "home"}}', '"pages" must be a list'),
            ('{"base": "http://localhost:9", "pages": [{"name": "home", "path": "/"},', "is not valid JSON"),
            ('{"base": "http://localhost:9", "pages": [{"name": "home"}]}', 'pages[0] needs a "path"'),
            ('{"base": "http://localhost:9", "pages": [{"path": "/"}]}', 'pages[0] needs a "name"'),
            ('{"pages": [{"name": "home", "path": "/"}]}', 'needs a "base"'),
            ('{"base": "http://localhost:9", "pages": []}', '"pages" is empty'),
        ]
        for text, want in cases:
            with self.subTest(text=text):
                r = self.run_pages_file(text)
                self.assertEqual(r.returncode, 1, r.stderr)
                self.assertIn(want, r.stderr)
                self.assertIn("pages.json", r.stderr)
                self.assertNotIn("    at ", r.stderr)
                self.assertNotIn("TypeError", r.stderr)
                self.assertEqual(len(r.stderr.strip().splitlines()), 1, r.stderr)

    def test_a_bare_list_of_pages_is_taken_when_with_server_sets_the_base(self):
        # Astro runs 1 and 2: pr-qa's first pages.json was a bare list both times, and the
        # plain error cost a server start (about 18 s) before the second try worked.
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            pkg = tmp / "node_modules" / "playwright"
            pkg.mkdir(parents=True)
            (pkg / "package.json").write_text('{"name": "playwright", "main": "index.js"}')
            (pkg / "index.js").write_text(FAKE_PAGE)
            (tmp / "pages.json").write_text('[{"name": "home", "path": "/"}, {"name": "about", "path": "/about"}]')
            log = tmp / "urls.log"
            env = {k: v for k, v in os.environ.items() if k not in ("NODE_PATH", "PLAYWRIGHT_PATH", "PROOFS_PLAYWRIGHT")}
            env.update(HOME=str(tmp), FAKE_LOG=str(log), PROOFS_BASE_URL="http://127.0.0.1:3411/")
            r = subprocess.run([NODE, str(CAPTURE), str(tmp / "pages.json"), "--out", str(tmp / "out"), "--sizes", "390"],
                               cwd=tmp, env=env, capture_output=True, text=True, timeout=60)
            self.assertNotIn('top-level "pages"', r.stderr)
            self.assertEqual(log.read_text().split(), ["http://127.0.0.1:3411/", "http://127.0.0.1:3411/about"])

    def test_the_example_pages_file_has_the_shape_the_capture_takes(self):
        js = ("const c=require(process.argv[1]);const f=c.readPagesFile(process.argv[2]);"
              "process.stdout.write(JSON.stringify({base:f.base,n:f.pages.length}))")
        example = CAPTURE.parent / "pages.example.json"
        r = subprocess.run([NODE, "-e", js, str(CAPTURE), str(example)], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(json.loads(r.stdout)["base"].startswith("http"))

    def test_missing_pages_file_is_one_plain_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([NODE, str(CAPTURE), str(Path(tmp) / "nope.json")], cwd=tmp,
                               capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 1, r.stderr)
            self.assertIn("nope.json", r.stderr)
            self.assertIn("cannot read", r.stderr)
            self.assertNotIn("    at ", r.stderr)

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


@unittest.skipUnless(NODE and playwright_dir(), "Playwright not found: set PROOFS_PLAYWRIGHT or install it in ~/.cache/proofs-playwright")
class SectionInventory(unittest.TestCase):
    """measures.sections: each section's elements, in DOM order, with page positions."""

    setUpClass = PhoneWidth.__dict__["setUpClass"]
    tearDownClass = PhoneWidth.__dict__["tearDownClass"]
    capture = PhoneWidth.capture
    result = PhoneWidth.result

    def measures(self, page):
        with tempfile.TemporaryDirectory() as tmp:
            _, out = self.capture(tmp, page, "--sizes", "1440")
            return self.result(out)["measures"]

    def test_sections_are_listed_with_their_elements(self):
        m = self.measures("inventory.html")
        secs = m["sections"]
        self.assertEqual([s["tag"] for s in secs], ["header", "section", "section", "footer"])
        self.assertEqual([s["label"] for s in secs], ["Site header", "First section", "Second section", "Site footer"])
        self.assertEqual(secs[2]["id"], "second")
        self.assertEqual([e["kind"] for e in secs[2]["elements"]], ["heading", "text", "button", "image", "list"])
        heading, text, button, image, lst = secs[2]["elements"]
        self.assertEqual(heading["text"], "Second section")
        self.assertEqual(button["text"], "Second section action")
        self.assertEqual(lst["tag"], "ul")
        for e in secs[2]["elements"]:
            self.assertEqual(set(e), {"kind", "text", "tag", "top", "left", "width", "height"})
        self.assertGreaterEqual(heading["top"], secs[2]["top"])
        self.assertEqual((image["width"], image["height"]), (120, 80))
        self.assertEqual([s["top"] for s in secs], sorted(s["top"] for s in secs))
        self.assertTrue(all(s["height"] > 0 for s in secs))

    def test_div_only_page_falls_back_to_main_children(self):
        secs = self.measures("inventory-divs.html")["sections"]
        self.assertEqual(len(secs), 4)
        self.assertEqual([s["tag"] for s in secs], ["div"] * 4)
        self.assertEqual(secs[1]["label"], "Second block")
        self.assertTrue(all(s["height"] > 200 for s in secs))

    def test_summary_lists_each_section_with_counts_by_kind(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, out = self.capture(tmp, "inventory.html", "--sizes", "1440")
            text = (out / "summary.md").read_text()
        self.assertIn("Sections (", text)
        self.assertIn("  - Second section: 1 heading, 1 text, 1 button, 1 image, 1 list", text)

    def test_font_sizes_are_distinct_and_sorted(self):
        sizes = self.measures("inventory.html")["fontSizes"]
        self.assertEqual(sizes, sorted(set(sizes)))
        self.assertIn(16, sizes)
        self.assertIn(24, sizes)  # the default h2

    def test_existing_measures_fields_unchanged(self):
        kinds = {
            "viewport": dict, "innerWidth": int, "dpr": (int, float), "scrollWidth": int, "clientWidth": int,
            "widestRight": int, "overflowing": list, "pageHeight": int, "sideways": int, "contentWidth": int,
            "contentShare": (int, float), "smallText": list, "smallTextCount": int, "smallTaps": list,
            "smallTapCount": int, "truncated": list, "offCenter": list, "offCenterCount": int,
            "offColumns": list, "offColumnCount": int, "hiddenBlocks": int, "hiddenList": list,
            "untitled": list, "untitledCount": int, "fullScale": (int, float), "parts": list,
            "midWord": list, "midWordAt": list, "pngWidth": int, "blank": dict, "signals": list,
        }
        for page in ("fits.html", "columns.html"):
            m = self.measures(page)
            for key, kind in kinds.items():
                self.assertIn(key, m, f"{page}: {key}")
                self.assertIsInstance(m[key], kind, f"{page}: {key}")
            self.assertIn("items", m)


if __name__ == "__main__":
    unittest.main()
