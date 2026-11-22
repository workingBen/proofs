import os, re, subprocess, sys, unittest, glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")


sys.path.insert(0, os.path.join(ROOT, "site-src"))
from site_order import NOT_YET_ON_SITE  # noqa: E402


def skills():
    """Skills that have a site page: every skill, less the ones waiting on review."""
    return sorted(d for d in os.listdir(os.path.join(ROOT, "skills"))
                  if os.path.isfile(os.path.join(ROOT, "skills", d, "SKILL.md")) and d not in NOT_YET_ON_SITE)


def build():
    subprocess.run([sys.executable, os.path.join(ROOT, "site-src", "build.py")], check=True, cwd=ROOT,
                   stdout=subprocess.DEVNULL)


class SiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build()

    def pages(self):
        return sorted(os.path.basename(p)[:-5] for p in glob.glob(os.path.join(DOCS, "*.html")))

    def test_every_skill_has_a_page_and_vice_versa(self):
        self.assertEqual([p for p in self.pages() if p != "index"], skills())
        pj = sorted(os.path.basename(p)[:-5] for p in glob.glob(os.path.join(ROOT, "site-src", "pages", "*.json")))
        self.assertEqual(pj, skills())

    def test_build_writes_a_page_per_skill_plus_index(self):
        self.assertEqual(len(self.pages()), len(skills()) + 1)
        self.assertTrue(os.path.exists(os.path.join(DOCS, ".nojekyll")))
        self.assertEqual(glob.glob(os.path.join(ROOT, "site-src", "page-*.html")), [])

    def test_site_links_resolve(self):
        for f in glob.glob(os.path.join(DOCS, "*.html")):
            txt = open(f, encoding="utf-8").read()
            for href in re.findall(r'href="([^"]+)"', txt):
                if re.match(r"(https?:|mailto:|#)", href):
                    continue
                target = href.split("#")[0]
                self.assertTrue(os.path.exists(os.path.join(DOCS, target)), f"{f}: {href}")
            for src in re.findall(r'\bsrc="([^"]+)"', txt) + [u.split()[0] for s in re.findall(r'srcset="([^"]+)"', txt) for u in s.split(",")]:
                if src.startswith("examples/"):
                    self.assertTrue(os.path.exists(os.path.join(DOCS, src)), f"{f}: {src}")
            ids = set(re.findall(r'id="([^"]+)"', txt))
            for frag in re.findall(r'href="#([^"]+)"', txt):
                self.assertIn(frag, ids, f"{f}: #{frag}")

    def test_no_placeholders_left(self):
        for f in glob.glob(os.path.join(DOCS, "*.html")):
            self.assertNotIn("%%", open(f, encoding="utf-8").read(), f)

    def test_home_page_says_twelve_skills(self):
        txt = open(os.path.join(DOCS, "index.html"), encoding="utf-8").read()
        self.assertIn("12 skills", txt)

    def test_install_line_uses_https(self):
        # The owner/repo shorthand clones over SSH and fails without a GitHub SSH key.
        line = "/plugin marketplace add https://github.com/workingBen/proofs.git"
        for f in (os.path.join(ROOT, "README.md"), os.path.join(DOCS, "index.html"),
                  os.path.join(DOCS, "try", "index.html")):
            txt = open(f, encoding="utf-8").read()
            self.assertIn(line, txt, f)
            self.assertNotIn("/plugin marketplace add workingBen/proofs\n", txt, f)


if __name__ == "__main__":
    unittest.main()
