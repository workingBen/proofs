"""Unit tests for scripts/todos_page.py.

Standard library only for the render tests. The behavior test shells out to
node with jsdom, the same way the other generated pages are tested.

Run:  python3 -m unittest discover skills/todos/tests
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from todos_page import (
    render, build, esc, main, resolve_identity, UnknownIdentity,
    _repo_slug_from_url, _project_name_from_claude_md,
)
from todos_parse import stable_id

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Skip (not fail) when jsdom is absent -- unlike pr_qa_page_test.py, which
# fails loudly. This file can run
# in a repo with no package.json at all; a hard
# failure there would be wrong for a dependency that was never supposed to
# exist. But `OK (skipped=6)` reads identically to a real green run, so print
# a banner nothing can miss when it happens -- silence here is the landmine.
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
        "SKIPPED: TestPageBehavior did NOT run.",
        "jsdom is missing, so the built page's JavaScript was",
        "never actually executed -- 'OK' below does not mean this was checked.",
        "Fix: install jsdom (npm install jsdom) and point NODE_PATH at its node_modules, then re-run this file.",
        "=" * 72,
        "",
    ]), file=sys.stderr)

DATA = {
    "groups": ["Yours", "Decide", "Build", "Backlog", "Ongoing"],
    "items": [
        {"n": 1, "id": stable_id("Connect GitHub."), "group": "Yours",
         "verify": "none", "title": "Connect GitHub.",
         "body": "401 without it.", "line": 10},
        {"n": 2, "id": stable_id("Surface the to-do id."), "group": "Build",
         "verify": "repo", "title": "Surface the to-do id.",
         "body": "Two taps.", "line": 20},
    ],
    "unparsed": [],
}


class TestRender(unittest.TestCase):
    def test_every_item_becomes_a_checkbox(self):
        html = render(DATA, "Acme Widgets", "acme/widgets")
        for item in DATA["items"]:
            self.assertIn('data-step="%s"' % item["id"], html)

    def test_every_item_gets_a_note_field(self):
        html = render(DATA, "Acme Widgets", "acme/widgets")
        for item in DATA["items"]:
            self.assertIn('data-stepnote="%s"' % item["id"], html)

    def test_group_is_carried_onto_the_checkbox(self):
        html = render(DATA, "Acme Widgets", "acme/widgets")
        self.assertIn('data-sec="Yours"', html)
        self.assertIn('data-sec="Build"', html)

    def test_project_bar_names_the_repo_it_was_given(self):
        html = render(DATA, "Acme Widgets", "acme/widgets")
        self.assertIn("Acme Widgets", html)
        self.assertIn("acme/widgets", html)

    def test_no_unparsed_means_no_warning_banner(self):
        html = render(DATA, "P", "o/r")
        self.assertNotIn("could not be parsed", html)

    def test_unparsed_raises_a_banner_naming_each_line(self):
        data = dict(DATA, unparsed=[
            {"line": 312, "text": "51. **Old thing.**", "why": "numbered list entry"}])
        html = render(data, "P", "o/r")
        self.assertIn("could not be parsed", html)
        self.assertIn("312", html)
        self.assertIn("numbered list entry", html)

    def test_counter_states_both_numbers_when_something_is_unparsed(self):
        data = dict(DATA, unparsed=[
            {"line": 9, "text": "x", "why": "y"}])
        self.assertIn("2 open &middot; 1 unparsed", render(data, "P", "o/r"))

    def test_titles_are_escaped(self):
        data = dict(DATA, items=[dict(DATA["items"][0], title="A <script> & co.")])
        html = render(data, "P", "o/r")
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script> & co.", html)

    def test_esc_handles_all_five(self):
        self.assertEqual(esc('<>&"\''), "&lt;&gt;&amp;&quot;&#39;")

    def test_empty_list_still_renders_a_page(self):
        html = render(dict(DATA, items=[]), "P", "o/r")
        self.assertIn("0 open", html)
        self.assertIn("Nothing open.", html)
        self.assertIn('id="copy"', html)
        self.assertIn('id="freeform"', html)
        self.assertEqual(html.count('class="stepbox"'), 0)

    def test_stepcount_starts_at_zero_over_the_real_total(self):
        html = render(DATA, "P", "o/r")
        self.assertIn('id="stepcount">0 / 2 done<', html)

    def test_copytop_is_present_and_wired_to_the_one_shared_build(self):
        html = render(DATA, "P", "o/r")
        self.assertIn('id="copytop"', html)
        # Exactly one build() definition -- #copy and #copytop must call the
        # same function, so they can never disagree about what was copied.
        self.assertEqual(html.count("function build("), 1)
        self.assertIn("getElementById('copytop')", html)


DRIVER = r"""
const fs=require('fs'), {JSDOM}=require('jsdom');
let copied=null;
const dom=new JSDOM(fs.readFileSync(process.argv[2],'utf8'),
  {runScripts:'dangerously', url:'https://example.com/'});
const w=dom.window, d=w.document;
Object.defineProperty(w.navigator,'clipboard',
  {value:{writeText:t=>{copied=t;return Promise.resolve();}},configurable:true});

const boxes=[...d.querySelectorAll('input.stepbox[data-step]')];
const box1=boxes[0];
const stepcount=d.getElementById('stepcount');

// Tick t2 the programmatic way -- the counter-tracking contract this repo
// already relies on: one of two items ticked reads "1 / 2 done".
boxes[1].checked=true; boxes[1].dispatchEvent(new w.Event('change'));
const counter=stepcount.textContent;

// Clicking the item's OWN label text (not the note field) must still tick
// its box -- this is the real risk: a stopPropagation guard scoped too
// broadly (e.g. to the whole .step, not just [data-stepnote]) would break
// ordinary ticking, and nothing else here would catch that. Only the
// script's 'change' listener + refresh() can move #stepcount's text, so a
// change here also proves the script is actually executing, not just
// present in a <script> tag.
const label1=box1.closest('label');
const span1=label1.querySelector('span');
// cancelable:true matters: a real user click is always cancelable, and
// label-forwarding's default action is gated on `!event.defaultPrevented`,
// which can only ever become true for a cancelable event. Leaving this at
// the MouseEvent default (cancelable:false) would make ticking succeed
// unconditionally, no matter what any guard does -- an unfalsifiable test
// for a different reason than the ones this fixes.
span1.dispatchEvent(new w.MouseEvent('click',{bubbles:true,cancelable:true}));
const tickedByLabelClick=box1.checked;
const counterAfterLabelClick=stepcount.textContent;

// Put t1 back to unticked so the export below matches the "one ticked, one
// not" shape the other export assertions depend on.
box1.checked=false; box1.dispatchEvent(new w.Event('change'));

// A per-item note must actually be wired: type into it and confirm the text
// comes back out in the export, attached to its own item.
const note=d.querySelector('[data-stepnote="'+box1.dataset.step+'"]');
note.value='remember the thing';
note.dispatchEvent(new w.Event('input',{bubbles:true}));

d.getElementById('copy').dispatchEvent(new w.Event('click'));
Promise.resolve().then(()=>{
  console.log(JSON.stringify({
    boxes: boxes.length, counter, tickedByLabelClick, counterAfterLabelClick,
    export: copied || '',
  }));
});
"""


@unittest.skipUnless(HAS_JSDOM, "jsdom absent")
class TestPageBehavior(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        todo = os.path.join(cls.tmp.name, "TODO.md")
        with open(todo, "w", encoding="utf-8") as handle:
            handle.write(
                "### Yours\n\n- [ ] **1. Connect GitHub.** Body one.\n\n"
                "### Build\n\n- [ ] **2. Surface the id.** Body two.\n")
        page = os.path.join(cls.tmp.name, "todos.html")
        build(todo, page, "Acme Widgets", "acme/widgets")
        driver = os.path.join(cls.tmp.name, "driver.js")
        with open(driver, "w", encoding="utf-8") as handle:
            handle.write(DRIVER)
        # NODE_PATH, not cwd: node resolves `require` from the SCRIPT's
        # directory, and driver.js lives in a tmpdir -- cwd=REPO_ROOT does
        # nothing for module resolution. Setting
        # NODE_PATH is what actually lets the symlinked node_modules resolve.
        env = dict(os.environ, NODE_PATH=NODE_MODULES)
        out = subprocess.run(
            ["node", driver, page], capture_output=True, text=True,
            cwd=REPO_ROOT, env=env, check=True)
        cls.result = json.loads(out.stdout.strip().split("\n")[-1])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_script_ran_at_all(self):
        # `boxes` alone (server-rendered static markup) survives a total JS
        # syntax error and proves nothing. #stepcount's text, by contrast, is
        # owned entirely by the script -- it only moves when the 'change'
        # listener and refresh() actually execute. Going from "1 / 2 done"
        # to "2 / 2 done" in response to a click cannot happen from a dead
        # script.
        self.assertEqual(self.result["boxes"], 2)
        self.assertNotEqual(self.result["counter"], self.result["counterAfterLabelClick"])

    def test_label_click_ticks_the_item(self):
        """Clicking the item's own label text (not the note field) must
        still tick the checkbox. This is the real risk a too-broad
        stopPropagation selector creates -- nothing else here would catch a
        guard that swallowed normal ticking along with the note field."""
        self.assertTrue(self.result["tickedByLabelClick"])
        self.assertEqual(self.result["counterAfterLabelClick"], "2 / 2 done")

    def test_counter_tracks_ticks(self):
        self.assertEqual(self.result["counter"], "1 / 2 done")

    def test_export_names_items_in_full_not_by_id(self):
        text = self.result["export"]
        self.assertIn("Surface the id.", text)
        self.assertNotIn("[x] t2", text)

    def test_export_marks_ticked_and_unticked(self):
        text = self.result["export"]
        self.assertIn("[x]", text)
        self.assertIn("[ ]", text)

    def test_note_text_survives_into_export(self):
        """Proves the note field is wired at all -- typing into it must
        show up in the copied export, anchored under its own item rather
        than merely present somewhere on the page."""
        text = self.result["export"]
        self.assertIn("note: remember the thing", text)
        idx_item1 = text.index("Connect GitHub.")
        idx_note = text.index("note: remember the thing")
        idx_item2 = text.index("Surface the id.")
        self.assertTrue(idx_item1 < idx_note < idx_item2,
                        "the note must sit under item 1, before item 2")


COPY_DRIVER = r"""
const fs=require('fs'), {JSDOM}=require('jsdom');
const mode=process.argv[3];
const dom=new JSDOM(fs.readFileSync(process.argv[2],'utf8'),
  {runScripts:'dangerously', url:'http://192.168.1.5:8000/'});
const w=dom.window, d=w.document;
if(mode==='ok') Object.defineProperty(w.navigator,'clipboard',
  {value:{writeText:t=>Promise.resolve()},configurable:true});
if(mode==='reject') Object.defineProperty(w.navigator,'clipboard',
  {value:{writeText:t=>Promise.reject(new Error('no'))},configurable:true});
const b=d.getElementById('copy');
b.dispatchEvent(new w.Event('click'));
setTimeout(()=>{
  const box=d.querySelector('textarea[data-copy-fallback]');
  console.log(JSON.stringify({label:b.textContent, box: box?box.value:null}));
},50);
"""


@unittest.skipUnless(HAS_JSDOM, "jsdom absent")
class TestCopyFallback(unittest.TestCase):
    def _copy(self, mode):
        with tempfile.TemporaryDirectory() as tmp:
            todo = os.path.join(tmp, "TODO.md")
            with open(todo, "w", encoding="utf-8") as handle:
                handle.write("### Yours\n\n- [ ] **1. Connect GitHub.** Body one.\n")
            page = os.path.join(tmp, "todos.html")
            build(todo, page, "Acme Widgets", "acme/widgets")
            driver = os.path.join(tmp, "driver.js")
            with open(driver, "w", encoding="utf-8") as handle:
                handle.write(COPY_DRIVER)
            out = subprocess.run(["node", driver, page, mode], capture_output=True, text=True,
                                 cwd=REPO_ROOT, env=dict(os.environ, NODE_PATH=NODE_MODULES), check=True)
            return json.loads(out.stdout.strip().split("\n")[-1])

    def test_success_says_copied_and_shows_no_box(self):
        out = self._copy("ok")
        self.assertTrue(out["label"].startswith("Copied"))
        self.assertIsNone(out["box"])

    def test_no_clipboard_shows_a_selectable_box_and_never_says_copied(self):
        out = self._copy("missing")
        self.assertFalse(out["label"].startswith("Copied"))
        self.assertIn("Connect GitHub", out["box"] or "")

    def test_rejected_write_shows_a_selectable_box_and_never_says_copied(self):
        out = self._copy("reject")
        self.assertFalse(out["label"].startswith("Copied"))
        self.assertIn("Connect GitHub", out["box"] or "")


class TestIdentity(unittest.TestCase):
    """The project name and repo slug must be DERIVED, never guessed -- a
    prior version defaulted argv[3]/argv[4] to this repo's own name and
    slug, which was silently wrong the moment the skill was ported
    elsewhere. See resolve_identity in todos_page.py."""

    def test_slug_from_https_with_and_without_dot_git(self):
        self.assertEqual(
            _repo_slug_from_url("https://github.com/owner/name.git"), "owner/name")
        self.assertEqual(
            _repo_slug_from_url("https://github.com/owner/name"), "owner/name")

    def test_slug_from_ssh_with_and_without_dot_git(self):
        self.assertEqual(
            _repo_slug_from_url("git@example.com:owner/name.git"), "owner/name")
        self.assertEqual(
            _repo_slug_from_url("git@example.com:owner/name"), "owner/name")

    def test_project_name_from_a_claude_md_fixture(self):
        text = (
            "# CLAUDE.md\n\n"
            "## About This App\n\n"
            "**Widget Tracker** -- tracks widgets for people who like widgets.\n\n"
            "## Commands\n\n**Not This.**\n"
        )
        self.assertEqual(_project_name_from_claude_md(text), "Widget Tracker")

    def test_neither_derivable_raises_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            todo = os.path.join(tmp, "TODO.md")
            with open(todo, "w", encoding="utf-8") as handle:
                handle.write("### Build\n\n- [ ] **1. A thing.** Body.\n")
            out = os.path.join(tmp, "todos.html")
            # No CLAUDE.md in tmp, and tmp is not inside any git checkout
            # with an 'origin' remote -- neither the project name nor the
            # repo slug can be derived, so this must fail loudly rather
            # than fall back to a guess. main() resolves identity against
            # the process's actual cwd (there is no cwd parameter on the
            # CLI entry point, deliberately -- it always means "here"), so
            # this has to really chdir into the empty fixture dir, not just
            # point argv at it.
            cwd_before = os.getcwd()
            os.chdir(tmp)
            try:
                with self.assertRaises(UnknownIdentity) as ctx:
                    main(["todos_page.py", todo, out])
            finally:
                os.chdir(cwd_before)
            self.assertIn("project name", str(ctx.exception))
            self.assertIn("repo slug", str(ctx.exception))
            self.assertFalse(os.path.exists(out))

    def test_default_output_path_is_the_proofs_pages_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "TODO.md"), "w", encoding="utf-8") as handle:
                handle.write("### Build\n\n- [ ] **1. A thing.** Body.\n")
            cwd_before = os.getcwd()
            os.chdir(tmp)
            try:
                import todos_page
                from unittest import mock
                self.assertEqual(todos_page.DEFAULT_OUT, ".proofs/pages/todos.html")
                with mock.patch.object(todos_page, "resolve_identity", return_value=("Acme", "acme/widgets")):
                    todos_page.main(["todos_page.py"])
                self.assertTrue(os.path.exists(os.path.join(tmp, ".proofs", "pages", "todos.html")))
            finally:
                os.chdir(cwd_before)

    def test_end_to_end_project_bar_carries_derived_values_not_a_literal(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "CLAUDE.md"), "w", encoding="utf-8") as handle:
                handle.write("## About This App\n\n**Acme Widgets** -- widgets.\n")
            subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
            subprocess.run(
                ["git", "remote", "add", "origin", "git@example.com:acme/widgets.git"],
                cwd=tmp, check=True)
            todo = os.path.join(tmp, "TODO.md")
            with open(todo, "w", encoding="utf-8") as handle:
                handle.write("### Build\n\n- [ ] **1. A thing.** Body.\n")
            project, repo = resolve_identity(["todos_page.py", todo], cwd=tmp)
            self.assertEqual(project, "Acme Widgets")
            self.assertEqual(repo, "acme/widgets")
            html = render({"items": [], "unparsed": [], "groups": []}, project, repo)
            self.assertIn("Acme Widgets", html)
            self.assertIn("acme/widgets", html)
            self.assertNotIn("Other Project", html)
            self.assertNotIn("other/project", html)

    def test_no_about_this_app_line_falls_back_to_the_repo_name(self):
        """No "About This App" bold name in CLAUDE.md -- e.g. a CLAUDE.md
        that, which heads its equivalent section "## Project" with
        plain, unbolded text. Falling back to the repo's own name (the last
        segment of the slug already derived from git remote) is not a
        guess -- it's the same source of truth, and the page still
        renders."""
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "CLAUDE.md"), "w", encoding="utf-8") as handle:
                handle.write("## Project\n\nSide Project - a reporting platform.\n")
            subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
            subprocess.run(
                ["git", "remote", "add", "origin",
                 "git@example.com:acme/side-project.git"],
                cwd=tmp, check=True)
            todo = os.path.join(tmp, "TODO.md")
            with open(todo, "w", encoding="utf-8") as handle:
                handle.write("### Build\n\n- [ ] **1. A thing.** Body.\n")
            project, repo = resolve_identity(["todos_page.py", todo], cwd=tmp)
            self.assertEqual(project, "side-project")
            self.assertEqual(repo, "acme/side-project")
            out = os.path.join(tmp, "todos.html")
            html = build(todo, out, project, repo)
            self.assertTrue(os.path.exists(out))
            self.assertIn("side-project", html)

    def test_about_this_app_name_wins_over_the_repo_name_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "CLAUDE.md"), "w", encoding="utf-8") as handle:
                handle.write("## About This App\n\n**Acme Widgets** -- widgets.\n")
            subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
            subprocess.run(
                ["git", "remote", "add", "origin",
                 "git@example.com:acme/widgets-repo-name.git"],
                cwd=tmp, check=True)
            project, repo = resolve_identity(["todos_page.py"], cwd=tmp)
            # The authored name, NOT "widgets-repo-name" -- CLAUDE.md wins
            # whenever it's present; the repo name is only a fallback.
            self.assertEqual(project, "Acme Widgets")
            self.assertEqual(repo, "acme/widgets-repo-name")

    def test_no_remote_and_no_claude_md_name_still_fails_loud(self):
        with tempfile.TemporaryDirectory() as tmp:
            todo = os.path.join(tmp, "TODO.md")
            with open(todo, "w", encoding="utf-8") as handle:
                handle.write("### Build\n\n- [ ] **1. A thing.** Body.\n")
            out = os.path.join(tmp, "todos.html")
            # No CLAUDE.md, no git remote -- there is nothing for even the
            # repo-name fallback to fall back ON, since that fallback itself
            # depends on a resolved repo slug.
            with self.assertRaises(UnknownIdentity):
                resolve_identity(["todos_page.py", todo, out], cwd=tmp)
            self.assertFalse(os.path.exists(out))

    def test_module_carries_no_repo_specific_literal(self):
        src_path = os.path.join(REPO_ROOT, "scripts", "todos_page.py")
        with open(src_path, encoding="utf-8") as handle:
            src = handle.read()
        for literal in ("Acme Widgets", "acme/widgets", "side-project"):
            self.assertNotIn(literal, src)


class TestBuild(unittest.TestCase):
    def test_build_writes_the_file_and_returns_the_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            todo = os.path.join(tmp, "TODO.md")
            with open(todo, "w", encoding="utf-8") as handle:
                handle.write("### Build\n\n- [ ] **1. A thing.** Body.\n")
            out = os.path.join(tmp, "todos.html")
            html = build(todo, out, "P", "o/r")
            self.assertTrue(os.path.exists(out))
            with open(out, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), html)
            self.assertIn('data-step="%s"' % stable_id("A thing."), html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
