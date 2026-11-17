"""End-to-end: TODO.md -> page -> simulated ticks -> export -> decisions.

Each half is unit-tested elsewhere. This is the only suite that fails when the
CONTRACT between them drifts -- a renamed data attribute, a changed export
format, a title truncation the matcher does not expect.

Run:  python3 -m unittest discover skills/todos/tests
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from todos_page import build
from todos_apply import parse_export, plan
from todos_parse import parse

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def _find_node_modules():
    """A node_modules directory holding jsdom: NODE_PATH entries first, then
    one beside this skill, then one at the project root."""
    candidates = [d for d in os.environ.get("NODE_PATH", "").split(os.pathsep) if d]
    candidates += [os.path.join(REPO_ROOT, "node_modules"),
                   os.path.join(os.getcwd(), "node_modules")]
    for directory in candidates:
        if os.path.isdir(os.path.join(directory, "jsdom")):
            return directory
    return None


NODE_MODULES = _find_node_modules()
HAS_JSDOM = NODE_MODULES is not None

if not HAS_JSDOM:
    print("\n".join([
        "",
        "=" * 72,
        "SKIPPED: the round-trip suite did NOT run.",
        "jsdom is missing, so no real page was ever built or",
        "driven -- 'OK' below does not mean the parser/page/apply contract",
        "was checked.",
        "Fix: install jsdom (npm install jsdom) and point NODE_PATH at its node_modules, then re-run this file.",
        "=" * 72,
        "",
    ]), file=sys.stderr)

TODO = """### Yours

- [ ] **1. Revoke the seven credentials.** The storage provider first, it has delete on every user photo.

### Build

- [ ] **2. Surface the to-do id in the admin.** Makes the manual trigger two taps.

- [ ] **3. Merge agent-run-port in side-project.** Pushed but not merged.
"""

# Tick items 1 and 3, leave 2 alone, and put a note on 1.
DRIVER = r"""
const fs=require('fs'), {JSDOM}=require('jsdom');
let copied=null;
const dom=new JSDOM(fs.readFileSync(process.argv[2],'utf8'),
  {runScripts:'dangerously', url:'https://example.com/'});
const w=dom.window, d=w.document;
Object.defineProperty(w.navigator,'clipboard',
  {value:{writeText:t=>{copied=t;return Promise.resolve();}},configurable:true});
// By POSITION, not by id. Ids are a hash of the title now (they used to be
// the item's number, which is what let a renumber hand one item's tick to
// another) -- and this test's intent has always been "the 1st and 3rd items".
const all=[...d.querySelectorAll('input.stepbox[data-step]')];
for (const b of [all[0], all[2]]) {
  b.checked=true; b.dispatchEvent(new w.Event('change'));
}
const n=d.querySelector('[data-stepnote="'+all[0].dataset.step+'"]');
n.value='Storage and email done, billing tomorrow';
n.dispatchEvent(new w.Event('input',{bubbles:true}));
d.getElementById('copy').dispatchEvent(new w.Event('click'));
Promise.resolve().then(()=>{ console.log(JSON.stringify({export: copied||''})); });
"""


def _drive(todo_text, driver_js, tmp):
    """Build a real page from todo_text, drive it through jsdom with
    driver_js, and return the JSON object the driver printed on its last
    stdout line."""
    todo = os.path.join(tmp, "TODO.md")
    with open(todo, "w", encoding="utf-8") as handle:
        handle.write(todo_text)
    page = os.path.join(tmp, "todos.html")
    build(todo, page, "Acme Widgets", "acme/widgets")
    driver = os.path.join(tmp, "driver.js")
    with open(driver, "w", encoding="utf-8") as handle:
        handle.write(driver_js)
    # NODE_PATH, not cwd: node resolves `require` from the SCRIPT's directory,
    # and driver.js lives in a tmpdir -- cwd=REPO_ROOT does nothing for module
    # resolution. Setting NODE_PATH is what actually lets the symlinked
    # node_modules resolve (see test_todos_page.py).
    env = dict(os.environ, NODE_PATH=NODE_MODULES)
    out = subprocess.run(["node", driver, page], capture_output=True,
                          text=True, cwd=REPO_ROOT, env=env, check=True)
    return json.loads(out.stdout.strip().split("\n")[-1])


@unittest.skipUnless(HAS_JSDOM, "jsdom absent")
class TestRoundTrip(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        result = _drive(TODO, DRIVER, cls.tmp.name)
        cls.export_text = result["export"]
        cls.items = parse(TODO)["items"]
        cls.result = plan(parse_export(cls.export_text), cls.items)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_export_is_not_empty(self):
        self.assertIn("OPEN ITEMS", self.export_text)

    def test_exactly_the_ticked_items_are_actioned(self):
        actioned = sorted(i["n"] for i, _ in
                          self.result["archive"] + self.result["verify"])
        self.assertEqual(actioned, [1, 3])

    def test_the_unticked_item_is_untouched(self):
        actioned = [i["n"] for i, _ in
                    self.result["archive"] + self.result["verify"]]
        self.assertNotIn(2, actioned)

    def test_yours_goes_to_archive_and_build_goes_to_verify(self):
        self.assertEqual([i["n"] for i, _ in self.result["archive"]], [1])
        self.assertEqual([i["n"] for i, _ in self.result["verify"]], [3])

    def test_the_note_survives_the_whole_trip(self):
        note = self.result["archive"][0][1]
        self.assertEqual(note, "Storage and email done, billing tomorrow")

    def test_nothing_failed_to_match(self):
        self.assertEqual(self.result["unmatched"], [])


# The sharpest edge in the pipeline: match() refuses to guess between two
# items whose titles could both explain a pasted row, rather than silently
# archiving the wrong one (see todos_apply.py's PREFIX_FLOOR/match()
# comments -- this is the exact failure mode fix round 1 found and closed).
# That refusal is only SAFE in practice because the real page always exports
# a full, untruncated "N. Title" via data-title, never the clipped label text
# a human sees -- so an unedited paste of a ticked item can never actually be
# ambiguous, even when two items share a long title prefix. This drives that
# claim through the real page rather than asserting it about match() in
# isolation: two items share the prefix "Merge the ", only the longer one is
# ticked, and the export -> plan path must still resolve it to exactly one
# item.
TODO_PREFIX = """### Build

- [ ] **1. Merge the PR into main.** Already reviewed twice.

- [ ] **2. Merge the docs site rebuild into main.** Longer follow-up, not reviewed yet.
"""

# Tick only item 2, the longer of the two prefix-sharing titles.
DRIVER_PREFIX = r"""
const fs=require('fs'), {JSDOM}=require('jsdom');
let copied=null;
const dom=new JSDOM(fs.readFileSync(process.argv[2],'utf8'),
  {runScripts:'dangerously', url:'https://example.com/'});
const w=dom.window, d=w.document;
Object.defineProperty(w.navigator,'clipboard',
  {value:{writeText:t=>{copied=t;return Promise.resolve();}},configurable:true});
const b=[...d.querySelectorAll('input.stepbox[data-step]')][1];
b.checked=true; b.dispatchEvent(new w.Event('change'));
d.getElementById('copy').dispatchEvent(new w.Event('click'));
Promise.resolve().then(()=>{ console.log(JSON.stringify({export: copied||''})); });
"""


@unittest.skipUnless(HAS_JSDOM, "jsdom absent")
class TestRoundTripPrefixSharingTitlesStillResolveUniquely(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        result = _drive(TODO_PREFIX, DRIVER_PREFIX, cls.tmp.name)
        cls.export_text = result["export"]
        cls.items = parse(TODO_PREFIX)["items"]
        cls.result = plan(parse_export(cls.export_text), cls.items)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_titles_really_do_share_a_long_prefix(self):
        # Guard the fixture itself: if this ever stops being true the test
        # below stops proving anything.
        t1, t2 = self.items[0]["title"], self.items[1]["title"]
        self.assertTrue(t2.startswith("Merge the "))
        self.assertTrue(t1.startswith("Merge the "))
        self.assertNotEqual(t1, t2)

    def test_only_the_ticked_item_resolves_and_uniquely(self):
        self.assertEqual(self.result["unmatched"], [])
        actioned = [i["n"] for i, _ in
                    self.result["archive"] + self.result["verify"]]
        self.assertEqual(actioned, [2])

    def test_the_untouched_sibling_with_the_shared_prefix_is_not_pulled_in(self):
        actioned = [i["n"] for i, _ in
                    self.result["archive"] + self.result["verify"]]
        self.assertNotIn(1, actioned)


# Fix round 1, 2026-08-06: mutation testing found that renaming (or dropping)
# the checkbox's data-title attribute was invisible to every fixture above,
# because todos_page.py's export code silently falls back to the (possibly
# 96-char-clipped) label text when data-title is absent -- see SCRIPT in
# todos_page.py, "var text=box.dataset.title||'';". Every title used above is
# under 40 characters, so below the clip the fallback produces a
# byte-identical string and the two code paths were indistinguishable.
#
# The fallback itself is reasonable defensiveness for a hand-edited page --
# it is not being removed, and this file does not touch todos_page.py. The
# defect fix round 1 closes is that nothing exercised the PRIMARY path (the
# data-title attribute actually being read) with a title long enough for the
# two paths to diverge. This fixture's title is 198 characters, chosen to
# clear todos_page.MAX_TITLE (96) by a wide margin.
LONG_TITLE = (
    "Move every reference to the old price list template out of the "
    "landing pages, the side-project microsite, and the onboarding email "
    "sequence, replacing each one with the new CDN-hosted version")

TODO_LONG = """### Build

- [ ] **1. %s** Reviewed and approved 2026-08-05.
""" % LONG_TITLE

# Tick the one (long-titled) item and export.
DRIVER_LONG = r"""
const fs=require('fs'), {JSDOM}=require('jsdom');
let copied=null;
const dom=new JSDOM(fs.readFileSync(process.argv[2],'utf8'),
  {runScripts:'dangerously', url:'https://example.com/'});
const w=dom.window, d=w.document;
Object.defineProperty(w.navigator,'clipboard',
  {value:{writeText:t=>{copied=t;return Promise.resolve();}},configurable:true});
const b=[...d.querySelectorAll('input.stepbox[data-step]')][0];
b.checked=true; b.dispatchEvent(new w.Event('change'));
d.getElementById('copy').dispatchEvent(new w.Event('click'));
Promise.resolve().then(()=>{ console.log(JSON.stringify({export: copied||''})); });
"""


@unittest.skipUnless(HAS_JSDOM, "jsdom absent")
class TestRoundTripLongTitleTravelsWholeAndUnclipped(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert len(LONG_TITLE) > 96, "fixture must clear MAX_TITLE to prove anything"
        cls.tmp = tempfile.TemporaryDirectory()
        result = _drive(TODO_LONG, DRIVER_LONG, cls.tmp.name)
        cls.export_text = result["export"]
        cls.items = parse(TODO_LONG)["items"]
        cls.result = plan(parse_export(cls.export_text), cls.items)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_exported_line_carries_the_full_title_verbatim(self):
        self.assertIn("    [x] 1. %s" % LONG_TITLE, self.export_text)

    def test_the_exported_line_is_not_a_96_char_clip_with_an_ellipsis(self):
        # The label text a human sees IS clipped (todos_page.MAX_TITLE); the
        # export must never be that clip. Under the data-title-renamed
        # mutation this fires because the fallback path adds "..." where the
        # real path never does.
        self.assertNotIn("...", self.export_text)

    def test_plan_resolves_it_uniquely(self):
        self.assertEqual(self.result["unmatched"], [])
        actioned = [i["n"] for i, _ in
                    self.result["archive"] + self.result["verify"]]
        self.assertEqual(actioned, [1])


def _stepboxes(html):
    """Every <input class="stepbox" ...> opening tag in a built page."""
    import re
    return re.findall(r'<input type="checkbox" class="stepbox"[^>]*>', html)


class TestEveryStepboxCarriesANonEmptyDataTitle(unittest.TestCase):
    """Fix round 1: proves the data-title attribute exists at all, so that
    renaming or dropping it (this suite's blind spot before this fix) fails
    loudly and immediately here, rather than degrading into a clipped-but-
    plausible title that only a long-enough fixture would ever expose. Pure
    string inspection of build()'s output -- does not need jsdom, so it runs
    even in an environment where the jsdom-driven classes above are skipped.
    """

    def _assert_all_have_titles(self, todo_text):
        import re
        with tempfile.TemporaryDirectory() as tmp:
            todo = os.path.join(tmp, "TODO.md")
            with open(todo, "w", encoding="utf-8") as handle:
                handle.write(todo_text)
            html = build(todo, os.path.join(tmp, "todos.html"),
                         "Acme Widgets", "acme/widgets")
        boxes = _stepboxes(html)
        self.assertTrue(boxes, "fixture produced no stepboxes to check")
        for tag in boxes:
            m = re.search(r'data-title="([^"]*)"', tag)
            self.assertIsNotNone(m, "stepbox missing data-title entirely: %s" % tag)
            self.assertNotEqual(m.group(1), "", "stepbox has an empty data-title: %s" % tag)

    def test_every_stepbox_has_a_title_in_the_main_fixture(self):
        self._assert_all_have_titles(TODO)

    def test_every_stepbox_has_a_title_when_titles_share_a_prefix(self):
        self._assert_all_have_titles(TODO_PREFIX)

    def test_every_stepbox_has_a_title_when_the_title_is_very_long(self):
        self._assert_all_have_titles(TODO_LONG)


if __name__ == "__main__":
    unittest.main(verbosity=2)
