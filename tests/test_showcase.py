"""import_examples.py and the before/after showcase the build emits from it."""
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMPORT = os.path.join(ROOT, "site-src", "import_examples.py")
BUILD = os.path.join(ROOT, "site-src", "build.py")
HAVE_MAGICK = bool(shutil.which("magick") or shutil.which("convert"))


def png(path, w, h, rgb):
    """A tiny solid-color PNG, written with the standard library only."""
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def fixture_examples():
    fr = lambda n, l: {"name": n, "label": l, "widths": [480, 960]}
    return {"examples": [
        {"id": "hero-pair", "title": "Hero pair", "skill": "design-review", "caption": "A plain page becomes a rich one.",
         "use": "hero", "view": "desktop", "w": 960, "h": 600, "frames": [fr("before", "Before"), fr("after", "After")], "gif": None},
        {"id": "three-step", "title": "Three steps", "skill": "photo-picker", "caption": "Old photo, the picker, new photo.",
         "use": "hero", "view": "desktop", "w": 960, "h": 600,
         "frames": [fr("before", "Before"), fr("picker", "The picker"), fr("after", "After")], "gif": None},
        {"id": "phone-pair", "title": "Phone pair", "skill": "design-review", "caption": "A list becomes a cover wall.",
         "use": "featured", "view": "phone", "w": 450, "h": 800, "frames": [fr("before", "Before"), fr("after", "After")], "gif": None},
    ]}


@unittest.skipUnless(HAVE_MAGICK, "ImageMagick not installed")
class ImportExamplesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.final = os.path.join(self.tmp, "final")
        self.root = os.path.join(self.tmp, "repo")
        os.makedirs(self.root)
        for xid, names in (("pair-one", ("before", "after")), ("steps-two", ("before", "picker", "after"))):
            os.makedirs(os.path.join(self.final, xid))
            for i, n in enumerate(names):
                png(os.path.join(self.final, xid, f"{n}.png"), 600, 400, (40 * i, 120, 200))
        with open(os.path.join(self.final, "pair-one", "wipe.gif"), "wb") as f:
            f.write(b"GIF89a fake")
        manifest = {
            "steps-two": {"title": "Steps", "skill": "photo-picker", "caption": "Three steps.", "use": "hero"},
            "pair-one": {"title": "Pair", "skill": "design-review", "caption": "A long caption the short one replaces.", "short": "Before and after.", "use": "featured",
                         "labels": {"after": "After · variant B"}},
        }
        json.dump(manifest, open(os.path.join(self.final, "manifest.json"), "w"))
        with open(os.path.join(self.root, "README.md"), "w") as f:
            f.write("# x\n<!-- examples:grid:start -->\nold\n<!-- examples:grid:end -->\ntail\n")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_import(self, *extra):
        return subprocess.run([sys.executable, IMPORT, self.final, "--root", self.root, *extra],
                              capture_output=True, text=True)

    def test_writes_resized_images_json_and_readme(self):
        r = self.run_import()
        self.assertEqual(r.returncode, 0, r.stderr)
        web = os.path.join(self.root, "docs", "examples")
        self.assertEqual(sorted(os.listdir(os.path.join(web, "pair-one"))),
                         ["after-480.jpg", "after-480.webp", "after-600.jpg", "after-600.webp",
                          "before-480.jpg", "before-480.webp", "before-600.jpg", "before-600.webp"])
        self.assertEqual(len(os.listdir(os.path.join(web, "steps-two"))), 12)
        self.assertTrue(os.path.isfile(os.path.join(self.root, "assets", "examples", "pair-one", "wipe.gif")))
        data = json.load(open(os.path.join(self.root, "site-src", "examples.json")))
        ex = {x["id"]: x for x in data["examples"]}
        self.assertEqual(ex["pair-one"]["frames"][1], {"name": "after", "label": "After · variant B", "widths": [480, 600]})
        self.assertEqual([f["name"] for f in ex["steps-two"]["frames"]], ["before", "picker", "after"])
        self.assertEqual((ex["pair-one"]["w"], ex["pair-one"]["h"], ex["pair-one"]["view"]), (600, 400, "desktop"))
        self.assertEqual(ex["steps-two"]["use"], "hero")
        self.assertEqual(ex["pair-one"]["caption"], "Before and after.")
        self.assertIsNone(ex["steps-two"]["gif"])
        readme = open(os.path.join(self.root, "README.md")).read()
        self.assertNotIn("old", readme)
        self.assertIn("assets/examples/pair-one/wipe.gif", readme)
        self.assertTrue(readme.endswith("tail\n"))

    def test_rerun_replaces_stale_examples(self):
        self.assertEqual(self.run_import().returncode, 0)
        shutil.rmtree(os.path.join(self.final, "steps-two"))
        m = json.load(open(os.path.join(self.final, "manifest.json")))
        del m["steps-two"]
        json.dump(m, open(os.path.join(self.final, "manifest.json"), "w"))
        self.assertEqual(self.run_import().returncode, 0)
        self.assertEqual(os.listdir(os.path.join(self.root, "docs", "examples")), ["pair-one"])

    def test_skips_dropped_and_held_ids(self):
        os.makedirs(os.path.join(self.final, "e-stays-photos"))
        for n in ("before", "after"):
            png(os.path.join(self.final, "e-stays-photos", f"{n}.png"), 60, 40, (9, 9, 9))
        m = json.load(open(os.path.join(self.final, "manifest.json")))
        m["e-stays-photos"] = {"title": "Held", "skill": "photo-picker", "caption": "Held.", "use": "featured"}
        json.dump(m, open(os.path.join(self.final, "manifest.json"), "w"))
        r = self.run_import()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("skipped e-stays-photos (held)", r.stderr)
        ids = [x["id"] for x in json.load(open(os.path.join(self.root, "site-src", "examples.json")))["examples"]]
        self.assertNotIn("e-stays-photos", ids)
        self.assertFalse(os.path.exists(os.path.join(self.root, "docs", "examples", "e-stays-photos")))

    def test_rejects_unknown_skill(self):
        m = json.load(open(os.path.join(self.final, "manifest.json")))
        m["pair-one"]["skill"] = "no-such-skill"
        json.dump(m, open(os.path.join(self.final, "manifest.json"), "w"))
        r = self.run_import()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("unknown skill", r.stderr)


class ReadmeGridTests(unittest.TestCase):
    def test_grid_keeps_the_examples_order(self):
        sys.path.insert(0, os.path.dirname(IMPORT))
        import import_examples
        ex = lambda i, use: {"id": i, "title": i, "skill": "design-review", "caption": f"Caption {i}.", "use": use,
                             "gif": f"assets/examples/{i}/wipe.gif"}
        exs = [ex("herox", "hero"), ex("alpha", "featured"), ex("skillonly", "skill"), ex("stepsx", "hero")]
        self.assertEqual([x["id"] for x in import_examples.readme_grid(exs)], ["herox", "alpha", "stepsx"])
        cells = import_examples.readme_block(exs)
        self.assertLess(cells.index("examples/herox/"), cells.index("examples/alpha/"))
        self.assertNotIn("skillonly", cells)
        tiles = import_examples.readme_block(exs, {i: f"assets/examples/{i}/tile.gif" for i in ("herox", "alpha", "stepsx")})
        self.assertIn('<img src="assets/examples/herox/tile.gif" width="380"', tiles)
        self.assertNotIn("<table>", tiles)  # tables never wrap; linked pictures do, two across on a laptop, one on a phone
        self.assertLess(tiles.index("Caption herox."), tiles.index("Caption alpha."))
        self.assertNotIn("examples/alpha/wipe.gif", tiles)

    def test_rows_past_the_first_two_fold_away(self):
        sys.path.insert(0, os.path.dirname(IMPORT))
        import import_examples
        exs = [{"id": f"e{i}", "title": f"T{i}", "skill": "design-review", "caption": f"Cap {i}.", "use": "featured",
                "gif": f"assets/examples/e{i}/wipe.gif"} for i in range(8)]
        md = import_examples.readme_block(exs, {f"e{i}": f"assets/examples/e{i}/tile.gif" for i in range(8)})
        top, fold = md.split("<details>")
        self.assertIn("e3/tile.gif", top)
        self.assertNotIn("e4/tile.gif", top)
        self.assertIn("<summary><b>More examples (4)</b></summary>", fold)
        self.assertIn("e7/tile.gif", fold)


class ShowcaseBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.out = os.path.join(cls.tmp, "docs")
        path = os.path.join(cls.tmp, "examples.json")
        json.dump(fixture_examples(), open(path, "w"))
        env = dict(os.environ, PROOFS_EXAMPLES=path, PROOFS_SITE_OUT=cls.out)
        subprocess.run([sys.executable, BUILD], check=True, cwd=ROOT, env=env, stdout=subprocess.DEVNULL)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def page(self, name):
        return open(os.path.join(self.out, name), encoding="utf-8").read()

    def test_home_hero_is_a_click_to_play_video(self):
        txt = self.page("index.html")
        hero = re.search(r'<figure class="hero-vid">(.*?)</figure>', txt, re.S).group(1)
        self.assertIn('data-yt="LGoRROsziv8"', hero)
        self.assertIn('src="media/proofs-short-cover.jpg"', hero)
        self.assertIn('fetchpriority="high"', hero)
        self.assertNotIn("<iframe", txt)  # nothing from YouTube until the play button is pressed
        self.assertNotIn("youtube.com/", txt.replace("youtube-nocookie.com/embed/", ""))
        self.assertIn("https://www.youtube-nocookie.com/embed/", txt)
        for f in ("proofs-short-cover.jpg", "proofs-short-cover.webp"):
            self.assertTrue(os.path.isfile(os.path.join(self.out, "media", f)), f)
        self.assertNotIn("dchip", txt)
        self.assertIn("/plugin install proofs@proofs", txt)
        self.assertLess(txt.index("hero-vid"), txt.index("class=\"tries\""))

    def test_retreat_pair_leads_the_gallery(self):
        txt = self.page("index.html")
        cards = re.findall(r'<figure class="bx v-[a-z]+" id="ex-([^"]+)"', txt)
        self.assertEqual(cards[0], "hero-pair")
        self.assertEqual(re.findall(r'class="fx-pick[^"]*"[^>]*><b>([^<]+)</b>', txt)[0], "Hero pair")

    def test_home_has_gallery_steps_and_script(self):
        txt = self.page("index.html")
        self.assertIn('id="ex-phone-pair"', txt)
        self.assertIn('class="bx v-phone"', txt)
        self.assertIn("data-steps", txt)
        self.assertEqual(len(re.findall(r'class="st-b( on)?"', txt)), 3)
        self.assertIn('loading="lazy"', txt)
        self.assertIn("IntersectionObserver", txt)
        self.assertIn("prefers-reduced-motion", txt)
        self.assertIn('href="photo-picker.html"', txt)

    def test_skill_pages_show_only_their_own_examples(self):
        dr = self.page("design-review.html")
        self.assertEqual(dr.count("data-ba style="), 2)
        self.assertNotIn("data-steps>", dr)
        self.assertIn("data-steps>", self.page("photo-picker.html"))
        todos = self.page("todos.html")
        self.assertNotIn("data-ba style=", todos)
        self.assertNotIn("IntersectionObserver(function(es){es.forEach(function(en){en.isIntersecting", todos)

    def test_labels_fade_with_the_share_they_name(self):
        js = self.page("index.html")
        self.assertIn("l.style.opacity=fade(p); r.style.opacity=fade(1-p);", js)
        self.assertIn("set(.5); l.style.opacity=1; r.style.opacity=1;", js)
        fn = re.search(r"var FADE_LO=[^;]+, FADE_HI=[^;]+;\s*function fade\(share\)\{.*?\}\n", js, re.S).group(0)
        if not shutil.which("node"):
            self.skipTest("node not installed")
        out = subprocess.run(["node", "-e", fn + "console.log(JSON.stringify([0,.35,.5,.65,1].map(fade)))"],
                             capture_output=True, text=True, check=True).stdout
        self.assertEqual(json.loads(out), [0, 0, 0.5, 1, 1])

    def test_step_frames_carry_their_labels(self):
        txt = self.page("photo-picker.html")
        stage = re.search(r'<div class="st-stage".*?</div></div>(?=<div class="st-row")', txt, re.S).group(0)
        self.assertEqual(re.findall(r'class="ba-lbl l(?: r)?">([^<]+)<', stage), ["Before", "The picker", "After"])

    def test_no_placeholders_left(self):
        for f in os.listdir(self.out):
            if f.endswith(".html"):
                self.assertNotIn("%%", self.page(f), f)


if __name__ == "__main__":
    unittest.main()
