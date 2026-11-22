"""Tests for shared/proofs_dir.py: keep the .proofs/ scratch folder out of git."""
import os
import shlex
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "shared"))
import proofs_dir  # noqa: E402

HELPER = str(REPO / "shared" / "capture" / "with_server.py")
PY = shlex.quote(sys.executable)
GIT_ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_COMMITTER_NAME="t",
               GIT_AUTHOR_EMAIL="", GIT_COMMITTER_EMAIL="")


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, env=GIT_ENV, capture_output=True, text=True, check=True).stdout


def init_repo(path):
    Path(path).mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q")
    return Path(path).resolve()


class EnsureExcludedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def lines(self, repo):
        p = repo / ".git" / "info" / "exclude"
        return [ln for ln in p.read_text().splitlines() if ln.strip() == ".proofs/"]

    def test_adds_once_and_is_idempotent(self):
        repo = init_repo(self.root / "r")
        first = proofs_dir.ensure_excluded(repo)
        self.assertEqual(Path(first).resolve(), (repo / ".git" / "info" / "exclude").resolve())
        self.assertIsNone(proofs_dir.ensure_excluded(repo))
        self.assertIsNone(proofs_dir.ensure_excluded(repo))
        self.assertEqual(len(self.lines(repo)), 1)

    def test_adds_newline_when_file_lacks_one(self):
        repo = init_repo(self.root / "r")
        ex = repo / ".git" / "info" / "exclude"
        ex.write_text("foo")
        proofs_dir.ensure_excluded(repo)
        self.assertEqual(ex.read_text(), "foo\n.proofs/\n")

    def test_no_op_outside_repo(self):
        plain = self.root / "plain"
        plain.mkdir()
        self.assertIsNone(proofs_dir.ensure_excluded(plain))

    def test_no_op_when_gitignore_covers_it(self):
        repo = init_repo(self.root / "r")
        (repo / ".gitignore").write_text(".proofs/\n")
        self.assertIsNone(proofs_dir.ensure_excluded(repo))
        self.assertEqual(self.lines(repo), [])

    def test_subfolder_status_clean(self):
        repo = init_repo(self.root / "r")
        sub = repo / "sub"
        (sub / ".proofs").mkdir(parents=True)
        (sub / ".proofs" / "x.log").write_text("x")
        self.assertIn("sub/.proofs/", git(repo, "status", "--porcelain", "-uall").replace("sub/.proofs/x.log", "sub/.proofs/"))
        proofs_dir.ensure_excluded(sub)
        self.assertEqual(git(repo, "status", "--porcelain", "-uall"), "")

    def test_linked_worktree_uses_common_exclude(self):
        repo = init_repo(self.root / "r")
        (repo / "a.txt").write_text("a")
        git(repo, "add", "a.txt")
        git(repo, "commit", "-q", "--allow-empty-message", "-m", "init")
        wt = self.root / "wt"
        git(repo, "worktree", "add", "-q", str(wt), "-b", "other")
        (wt / ".proofs").mkdir()
        (wt / ".proofs" / "x.log").write_text("x")
        written = proofs_dir.ensure_excluded(wt)
        self.assertEqual(Path(written).resolve(), (repo / ".git" / "info" / "exclude").resolve())
        self.assertEqual(len(self.lines(repo)), 1)
        self.assertEqual(git(wt, "status", "--porcelain", "-uall"), "")

    def test_never_raises_on_read_only_file(self):
        repo = init_repo(self.root / "r")
        ex = repo / ".git" / "info" / "exclude"
        ex.chmod(0o444)
        try:
            if os.access(ex, os.W_OK):
                self.skipTest("running as a user who ignores file modes")
            self.assertIsNone(proofs_dir.ensure_excluded(repo))
        finally:
            ex.chmod(0o644)

    def test_with_server_leaves_repo_clean(self):
        repo = init_repo(self.root / "r")
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        r = subprocess.run([sys.executable, HELPER, "--start", "%s -m http.server %d" % (PY, port),
                            "--url", "http://127.0.0.1:%d/" % port, "--timeout", "20", "--",
                            sys.executable, "-c", "pass"], cwd=repo, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((repo / ".proofs").is_dir())
        self.assertEqual(git(repo, "status", "--porcelain", "-uall"), "")

    def test_review_page_under_proofs_leaves_repo_clean(self):
        repo = init_repo(self.root / "r")
        spec = REPO / "shared" / "review_page" / "examples"
        example = sorted(spec.glob("*.json"))[0]
        r = subprocess.run([sys.executable, str(REPO / "shared" / "review_page" / "review_page.py"), str(example),
                            "--out", str(repo / ".proofs" / "page.html"), "--no-check"],
                           cwd=repo, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(git(repo, "status", "--porcelain", "-uall"), "")


if __name__ == "__main__":
    unittest.main()
