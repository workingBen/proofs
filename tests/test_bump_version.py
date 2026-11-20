import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BUMP = REPO / "bin" / "bump-version"

SKILL = "---\nname: alpha\ndescription: Use when something happens.\nversion: {v}\n---\n\n# alpha\n{body}\n"


class BumpCase(unittest.TestCase):
    """Each test gets a repo with an origin/main at plugin 1.0.1 and a feature branch off it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "work"
        self.origin = Path(self._tmp.name) / "origin.git"
        self.root.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "T")
        self.write(".claude-plugin/plugin.json", json.dumps({"name": "proofs", "version": "1.0.1"}, indent=2) + "\n")
        self.write("skills/alpha/SKILL.md", SKILL.format(v="1.2.0", body=""))
        self.write("README.md", "hi\n")
        self.commit("start")
        subprocess.run(["git", "init", "-q", "--bare", str(self.origin)], check=True)
        self.git("remote", "add", "origin", str(self.origin))
        self.git("push", "-q", "origin", "main")
        self.git("checkout", "-q", "-b", "feature")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True, check=True).stdout

    def write(self, path, text):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        self.git("add", path)

    def commit(self, msg):
        self.git("commit", "-q", "--no-verify", "-m", msg)

    def bump(self, *args):
        return subprocess.run([sys.executable, str(BUMP), *args], cwd=self.root, capture_output=True, text=True)

    def version(self, ref=None):
        text = self.git("show", "%s:.claude-plugin/plugin.json" % ref) if ref else \
            (self.root / ".claude-plugin/plugin.json").read_text()
        return json.loads(text)["version"]

    def test_skill_minor_bump_bumps_plugin_minor_and_stages_it(self):
        self.write("skills/alpha/SKILL.md", SKILL.format(v="1.3.0", body="new"))
        r = self.bump()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.version(), "1.1.0")
        self.assertIn(".claude-plugin/plugin.json", self.git("diff", "--cached", "--name-only"))

    def test_skill_patch_bump_bumps_plugin_patch(self):
        self.write("skills/alpha/SKILL.md", SKILL.format(v="1.2.1", body="fix"))
        self.bump()
        self.assertEqual(self.version(), "1.0.2")

    def test_new_skill_counts_as_minor(self):
        self.write("skills/beta/SKILL.md", SKILL.replace("alpha", "beta").format(v="1.0.0", body=""))
        self.bump()
        self.assertEqual(self.version(), "1.1.0")

    def test_shared_change_without_skill_bump_is_patch(self):
        self.write("shared/review_page/build.py", "x = 1\n")
        self.bump()
        self.assertEqual(self.version(), "1.0.2")

    def test_docs_only_change_leaves_version(self):
        self.write("README.md", "changed\n")
        r = self.bump()
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.version(), "1.0.1")

    def test_second_commit_on_branch_does_not_bump_again(self):
        self.write("skills/alpha/SKILL.md", SKILL.format(v="1.2.1", body="fix"))
        self.bump()
        self.commit("one")
        self.write("skills/alpha/SKILL.md", SKILL.format(v="1.2.1", body="fix more"))
        self.bump()
        self.assertEqual(self.version(), "1.0.2")

    def test_larger_skill_bump_later_on_branch_raises_plugin_level(self):
        self.write("skills/alpha/SKILL.md", SKILL.format(v="1.2.1", body="fix"))
        self.bump()
        self.commit("one")
        self.write("skills/alpha/SKILL.md", SKILL.format(v="1.3.0", body="feature"))
        self.bump()
        self.assertEqual(self.version(), "1.1.0")

    def test_check_reports_without_writing(self):
        self.write("skills/alpha/SKILL.md", SKILL.format(v="1.3.0", body="new"))
        r = self.bump("--check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("should be 1.1.0", r.stdout)
        self.assertEqual(self.version(), "1.0.1")

    def test_version_taken_by_another_merge_is_bumped_again(self):
        # This branch releases 1.0.2...
        self.write("skills/alpha/SKILL.md", SKILL.format(v="1.2.1", body="ours"))
        self.bump()
        self.commit("ours")
        # ...but another branch merged 1.0.2 to main first.
        self.git("checkout", "-q", "main")
        self.write("shared/other.py", "y = 2\n")
        self.write(".claude-plugin/plugin.json", json.dumps({"name": "proofs", "version": "1.0.2"}, indent=2) + "\n")
        self.commit("theirs")
        self.git("push", "-q", "origin", "main")
        self.git("checkout", "-q", "feature")
        self.git("fetch", "-q", "origin")
        self.git("merge", "-q", "--no-commit", "origin/main")
        r = self.bump()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.version(), "1.0.3")

    def test_merge_bringing_only_main_changes_does_not_bump(self):
        self.git("checkout", "-q", "main")
        self.write("shared/other.py", "y = 2\n")
        self.write(".claude-plugin/plugin.json", json.dumps({"name": "proofs", "version": "1.0.2"}, indent=2) + "\n")
        self.commit("theirs")
        self.git("push", "-q", "origin", "main")
        self.git("checkout", "-q", "feature")
        self.write("README.md", "docs\n")
        self.commit("docs")
        self.git("fetch", "-q", "origin")
        self.git("merge", "-q", "--no-commit", "origin/main")
        r = self.bump()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.version(), "1.0.2")

    def test_installed_hook_puts_the_bump_in_the_commit(self):
        for name in ("bump-version", "check-skills", "privacy-scan", "install-hooks"):
            (self.root / "bin").mkdir(exist_ok=True)
            shutil.copy(REPO / "bin" / name, self.root / "bin" / name)
        # Only the bump is under test here; the other checks have their own tests.
        hook = subprocess.run(["sh", "bin/install-hooks"], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(hook.returncode, 0, hook.stderr)
        hooks = Path(self.git("rev-parse", "--git-path", "hooks").strip())
        hooks = hooks if hooks.is_absolute() else self.root / hooks
        (hooks / "pre-commit").write_text('#!/bin/sh\npython3 "$(git rev-parse --show-toplevel)/bin/bump-version" || exit 1\n')
        self.write("skills/alpha/SKILL.md", SKILL.format(v="1.2.1", body="fix"))
        self.git("commit", "-q", "-m", "fix")
        self.assertEqual(self.version("HEAD"), "1.0.2")
        self.assertEqual(self.git("status", "--porcelain", "--", ".claude-plugin").strip(), "")


if __name__ == "__main__":
    unittest.main()
