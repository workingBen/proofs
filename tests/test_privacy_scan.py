import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Fixture strings are assembled from pieces so this file passes the scan itself.
AT = "@"
PERSON = "B" + "en"
USERS = "/Us" + "ers/"
SCAN = Path(__file__).resolve().parent.parent / "bin" / "privacy-scan"


def git(cwd, *args, author="t"):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": author, "GIT_AUTHOR_EMAIL": "t" + AT + "example.com",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t" + AT + "example.com"})


class ScanCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "repo"
        self.root.mkdir()
        git(self.root, "init", "-q", "-b", "main")
        self.list = Path(self._tmp.name) / "deny.txt"
        self.list.write_text("# comment\nZorblax\n" + PERSON + "\nSecret Place\n")

    def write(self, rel, content, mode="w"):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if "b" in mode:
            p.write_bytes(content)
        else:
            p.write_text(content)
        return p

    def run_scan(self, *args, list_path="default", env_extra=None):
        args = list(args)
        if list_path == "default":
            args += ["--list", str(self.list)]
        elif list_path:
            args += ["--list", str(list_path)]
        env = {**os.environ, "HOME": self._tmp.name}
        env.pop("PROOFS_DENY", None)
        env.update(env_extra or {})
        return subprocess.run([sys.executable, str(SCAN), *args], cwd=self.root,
                              capture_output=True, text=True, env=env)

    def test_flags_deny_word(self):
        self.write("a.md", "hello\nthe Zorblax is here\n")
        r = self.run_scan("--all")
        self.assertEqual(r.returncode, 1)
        self.assertIn("a.md:2: deny-list", r.stdout)

    def test_clean_exits_zero(self):
        self.write("a.md", "nothing private\n")
        self.assertEqual(self.run_scan("--all").returncode, 0)

    def test_missing_list_fails(self):
        self.write("a.md", "clean\n")
        r = self.run_scan("--all", list_path=self.list.parent / "nope.txt")
        self.assertEqual(r.returncode, 2)
        r = self.run_scan("--all", list_path=None)  # falls back to $HOME/.config/proofs/deny.txt
        self.assertEqual(r.returncode, 2)

    def test_empty_list_fails(self):
        self.write("a.md", "clean\n")
        empty = self.list.parent / "empty.txt"
        empty.write_text("# only a comment\n\n")
        self.assertEqual(self.run_scan("--all", list_path=empty).returncode, 2)

    def test_env_var_list_used(self):
        self.write("a.md", "Zorblax\n")
        r = self.run_scan("--all", list_path=None, env_extra={"PROOFS_DENY": str(self.list)})
        self.assertEqual(r.returncode, 1)

    def test_word_boundaries(self):
        self.write("a.md", PERSON + " went by\n")
        self.write("b.md", "Benefit and benchmark and workingBen\n")
        r = self.run_scan("--all")
        self.assertIn("a.md:1", r.stdout)
        self.assertNotIn("b.md", r.stdout)

    def test_case_insensitive_and_phrases(self):
        self.write("a.md", "zORBLAX\nvisit secret   place today\n")
        r = self.run_scan("--all")
        self.assertIn("a.md:1: deny-list", r.stdout)
        self.assertIn("a.md:2: deny-list", r.stdout)

    def test_output_never_contains_match(self):
        self.write("a.md", "Zorblax and " + PERSON + " and a" + AT + "b.com and 555-123" + "-4567 and " + USERS + "someone/x\n")
        r = self.run_scan("--all")
        out = (r.stdout + r.stderr).lower()
        for needle in ("zorblax", "a" + AT + "b.com", "555-123" + "-4567", "someone"):
            self.assertNotIn(needle, out)
        self.assertNotIn(PERSON, r.stdout + r.stderr)

    def test_flags_email_phone_userpath(self):
        self.write("a.md", "mail me at jo" + AT + "corp.io\n")
        self.write("b.md", "call (415) 555" + "-0199 now\n")
        self.write("c.md", "see " + USERS + "jo/x and /home/" + "dayt" + "ona/y\n")
        r = self.run_scan("--all")
        self.assertIn("a.md:1: email", r.stdout)
        self.assertIn("b.md:1: phone", r.stdout)
        self.assertIn("c.md:1: user-path", r.stdout)

    def test_flags_artifact_id_and_pr_number(self):
        self.write("a.md", "https://claude.ai/code/" + "artifact/AbC123xyz9QrStUv\n")
        self.write("b.md", "fixed in PR " + "#412 and (" + "#99)\n")
        r = self.run_scan("--all")
        self.assertIn("a.md:1: artifact-id", r.stdout)
        self.assertIn("b.md:1: pr-number", r.stdout)

    def test_example_email_allowed(self):
        self.write("a.md", "dev" + AT + "example.com\n")
        self.assertEqual(self.run_scan("--all").returncode, 0)

    def test_lists_skipped_binaries(self):
        self.write("img.png", b"\x89PNG\r\n\x1a\n\x00\x00", mode="wb")
        self.write("blob.dat", b"ab\x00cd", mode="wb")
        self.write("a.md", "clean\n")
        r = self.run_scan("--all")
        self.assertEqual(r.returncode, 0)
        self.assertIn("skipped (check by eye): img.png", r.stdout)
        self.assertIn("skipped (check by eye): blob.dat", r.stdout)

    def test_staged_scans_index_only(self):
        self.write("a.md", "clean\n")
        git(self.root, "add", "a.md")
        self.write("b.md", "Zorblax\n")  # untracked, unstaged
        self.assertEqual(self.run_scan("--staged").returncode, 0)
        git(self.root, "add", "b.md")
        self.assertEqual(self.run_scan("--staged").returncode, 1)

    def test_history_mode_scans_old_commits(self):
        self.write("a.md", "Zorblax lives here\n")
        git(self.root, "add", "a.md")
        git(self.root, "commit", "-q", "-m", "one")
        self.write("a.md", "all clean now\n")
        git(self.root, "add", "a.md")
        git(self.root, "commit", "-q", "-m", "two")
        self.assertEqual(self.run_scan("--all").returncode, 0)
        r = self.run_scan("--history")
        self.assertEqual(r.returncode, 1)
        self.assertIn("a.md", r.stdout)
        self.assertNotIn("Zorblax", r.stdout)

    def commit_file(self, rel, content, author="t", msg="c"):
        self.write(rel, content)
        git(self.root, "add", "--", rel)
        git(self.root, "commit", "-q", "-m", msg, author=author)

    def test_history_survives_added_line_that_looks_like_header(self):
        # an added line "++ x" appears in a diff as "+++ x"
        self.commit_file("a.md", "++ dashes\nZorblax here\n")
        r = self.run_scan("--history")
        self.assertEqual(r.returncode, 1)
        self.assertIn("a.md@", r.stdout)
        self.assertIn(":2: deny-list", r.stdout)

    def test_history_scans_quoted_and_spaced_paths(self):
        self.commit_file("caf\u00e9 notes.md", "Zorblax\n")
        self.commit_file("with\ttab.md", "Zorblax\n")
        r = self.run_scan("--history")
        self.assertEqual(r.returncode, 1)
        self.assertIn("caf\u00e9 notes.md@", r.stdout)
        self.assertIn("with\ttab.md@", r.stdout)

    def test_history_scans_commit_metadata(self):
        self.commit_file("a.md", "clean\n", author="Zorblax")
        r = self.run_scan("--history")
        self.assertEqual(r.returncode, 1)
        self.assertRegex(r.stdout, r"commit [0-9a-f]+: deny-list")
        self.assertNotIn("Zorblax", r.stdout)
        self.commit_file("b.md", "clean\n", msg="mentions " + "Secret Place")
        r = self.run_scan("--history")
        self.assertGreaterEqual(r.stdout.count("commit "), 2)

    def test_history_clean_metadata_passes(self):
        self.commit_file("a.md", "clean\n")
        self.assertEqual(self.run_scan("--history").returncode, 0)

    def test_case_sensitive_entries(self):
        self.list.write_text("case:Rend" + "er\n")
        self.write("a.md", "the Rend" + "er dashboard\nrend" + "er the page\n")
        r = self.run_scan("--all")
        self.assertEqual(r.returncode, 1)
        self.assertIn("a.md:1: deny-list", r.stdout)
        self.assertNotIn("a.md:2", r.stdout)

    def test_flags_session_ids(self):
        self.write("a.md", "https://claude.ai/code/" + "sess" + "ion_01AbCdEfGhIjKlMnOpQrStUv\n")
        self.write("b.md", "Claude-Session: " + "sess" + "ion_01AbCdEfGhIjKlMnOpQrStUv\n")
        self.write("c.md", "a session_name and a session_id word\n")
        r = self.run_scan("--all")
        self.assertIn("a.md:1: session-id", r.stdout)
        self.assertIn("b.md:1: session-id", r.stdout)
        self.assertNotIn("c.md", r.stdout)

    def test_history_allows_exact_noreply_addresses(self):
        self.write("a.md", "clean\n")
        git(self.root, "add", "a.md")
        env = {**os.environ, "GIT_AUTHOR_NAME": "dev", "GIT_AUTHOR_EMAIL": "12345+dev" + AT + "users.noreply.github.com",
               "GIT_COMMITTER_NAME": "dev", "GIT_COMMITTER_EMAIL": "12345+dev" + AT + "users.noreply.github.com"}
        subprocess.run(["git", "commit", "-q", "-m", "msg\n\nCo-Authored-By: Claude <noreply" + AT + "anthropic.com>"],
                       cwd=self.root, check=True, capture_output=True, env=env)
        r = self.run_scan("--history")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_other_anthropic_addresses_still_flagged(self):
        self.write("a.md", "ask jo" + AT + "anthropic.com\n")
        self.assertIn("a.md:1: email", self.run_scan("--all").stdout)

    def test_npm_versions_are_not_emails(self):
        self.write("a.md", "npm install playwright" + AT + "1.61.1 and " + AT + "scope/pkg" + AT + "2.0.0\n")
        self.assertEqual(self.run_scan("--all").returncode, 0)

    def test_real_addresses_still_flagged(self):
        self.write("a.md", "someone" + AT + "example.com\n")
        self.write("b.md", "a.b" + AT + "sub.example.io\n")
        r = self.run_scan("--all")
        self.assertIn("b.md:1: email", r.stdout)
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
