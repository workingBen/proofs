#!/usr/bin/env python3
"""The open-PR session-start hook, as a starting session sees it."""
import contextlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from open_prs_session_start import (age_phrase, fetch_open_prs, read_token,
                                    repo_slug, summarize)

NOW = datetime(2026, 8, 5, 12, 0, 0, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, body):
        self._body = body.encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def opener_for(body="[]", error=None, captured=None):
    def opener(req, timeout=None):
        if captured is not None:
            captured.append(req)
        if error is not None:
            raise error
        return FakeResponse(body)
    return opener


@contextlib.contextmanager
def project_with(values):
    """A temp project whose .claude/settings.json sets `values`, entered as the working folder,
    with an empty home and no PROOFS_ variables, so only the file speaks."""
    with tempfile.TemporaryDirectory() as tmp:
        proj, home = Path(tmp).resolve() / "proj", Path(tmp).resolve() / "home"
        (proj / ".claude").mkdir(parents=True)
        home.mkdir()
        (proj / ".claude" / "settings.json").write_text(json.dumps({"env": values}))
        keep = {k: v for k, v in os.environ.items() if not k.startswith("PROOFS_")}
        keep.update(HOME=str(home), CLAUDE_CONFIG_DIR=str(home / ".claude"))
        old = os.getcwd()
        os.chdir(proj)
        try:
            with mock.patch.dict(os.environ, keep, clear=True):
                yield proj
        finally:
            os.chdir(old)

from pr_qa_plan import fill, is_visual, load_map, plan, read_map


def pr(number, ref, created, title="A change", draft=False):
    return {"number": number, "head": {"ref": ref}, "created_at": created,
            "title": title, "draft": draft}


class RepoSlugTest(unittest.TestCase):
    def _run_returning(self, url, returncode=0):
        class Out:
            pass
        out = Out()
        out.returncode = returncode
        out.stdout = url

        def run(*args, **kwargs):
            return out
        return run

    def test_reads_an_https_remote(self):
        run = self._run_returning("https://github.com/acme/widgets.git\n")
        self.assertEqual(repo_slug(run), "acme/widgets")

    def test_reads_an_ssh_remote(self):
        run = self._run_returning("git" + "@github.com:acme/widgets.git\n")
        self.assertEqual(repo_slug(run), "acme/widgets")

    def test_tolerates_a_missing_remote(self):
        self.assertIsNone(repo_slug(self._run_returning("", returncode=1)))

    def test_tolerates_git_not_being_there(self):
        def run(*args, **kwargs):
            raise OSError("no git")
        self.assertIsNone(repo_slug(run))


class ReadTokenTest(unittest.TestCase):
    @staticmethod
    def _gh(stdout="", returncode=0):
        def run(*args, **kwargs):
            class Out:
                pass
            out = Out()
            out.stdout, out.returncode = stdout, returncode
            return out
        return run

    def test_prefers_the_environment(self):
        self.assertEqual(read_token({"GITHUB_TOKEN": "from-env"}, self._gh("from-gh\n")), "from-env")

    def test_falls_back_to_gh_auth_token(self):
        self.assertEqual(read_token({}, self._gh("from-gh\n")), "from-gh")

    def test_none_when_gh_is_signed_out(self):
        self.assertIsNone(read_token({}, self._gh("", returncode=1)))

    def test_none_when_gh_is_not_installed(self):
        def run(*args, **kwargs):
            raise OSError("no gh")
        self.assertIsNone(read_token({}, run))


class AgePhraseTest(unittest.TestCase):
    def test_under_an_hour(self):
        self.assertEqual(age_phrase("2026-08-05T11:30:00Z", NOW), "under an hour old")

    def test_hours(self):
        self.assertEqual(age_phrase("2026-08-04T20:00:00Z", NOW), "16h old")

    def test_days_past_two(self):
        self.assertEqual(age_phrase("2026-08-01T12:00:00Z", NOW), "4 days old")

    def test_survives_a_missing_or_broken_date(self):
        self.assertEqual(age_phrase(None, NOW), "age unknown")
        self.assertEqual(age_phrase("not a date", NOW), "age unknown")


class SummarizeTest(unittest.TestCase):
    def test_silent_when_nothing_is_open(self):
        # A quiet hook and a healthy repo look the same on purpose.
        self.assertIsNone(summarize([], NOW))

    def test_counts_and_orders_oldest_first(self):
        text = summarize([
            pr(4, "agent/newer", "2026-08-04T18:36:00Z", "Newer"),
            pr(2, "agent/older", "2026-08-04T08:43:00Z", "Older"),
        ], NOW)
        self.assertIn("2 open pull requests", text)
        self.assertLess(text.index("#2"), text.index("#4"))

    def test_singular_for_one(self):
        text = summarize([pr(2, "agent/x", "2026-08-04T08:43:00Z")], NOW)
        self.assertIn("1 open pull request in", text)

    def test_marks_agent_branches(self):
        text = summarize([pr(2, "agent/fix-thing", "2026-08-04T08:43:00Z")], NOW)
        self.assertIn("AI fix", text)

    def test_does_not_mark_a_human_branch(self):
        text = summarize([pr(9, "worktree-something", "2026-08-04T08:43:00Z")], NOW)
        self.assertNotIn("AI fix", text)

    def test_calls_out_a_draft_because_it_cannot_be_merged(self):
        text = summarize([pr(2, "agent/x", "2026-08-04T08:43:00Z", draft=True)], NOW)
        self.assertIn("draft", text)

    def test_the_age_that_started_this(self):
        # Opened 08:43 on 4 Aug, read at noon the next day.
        text = summarize([pr(2, "agent/implement-ability-to-clear-recon",
                             "2026-08-04T08:43:54Z")], NOW)
        self.assertIn("27h old", text)

    def test_points_at_the_skill_without_acting(self):
        text = summarize([pr(2, "agent/x", "2026-08-04T08:43:00Z")], NOW)
        self.assertIn("/proofs:pr-qa", text)
        self.assertIn("Do not act on these unasked", text)


class FetchTest(unittest.TestCase):
    def test_sends_the_token_and_asks_for_open_prs(self):
        captured = []
        fetch_open_prs("o/r", "secret", opener_for("[]", captured=captured))
        req = captured[0]
        self.assertIn("state=open", req.full_url)
        self.assertEqual(req.get_header("Authorization"), "Bearer secret")

    def test_returns_the_list(self):
        body = json.dumps([pr(2, "agent/x", "2026-08-04T08:43:00Z")])
        self.assertEqual(len(fetch_open_prs("o/r", "t", opener_for(body))), 1)

    def test_a_non_list_body_is_no_prs_not_a_crash(self):
        # GitHub answers an auth failure with an object, not an array.
        body = json.dumps({"message": "Bad credentials"})
        self.assertEqual(fetch_open_prs("o/r", "t", opener_for(body)), [])


class NeverBlocksTheSessionTest(unittest.TestCase):
    """Whatever goes wrong, the hook exits 0 and prints nothing."""

    def _run(self, env):
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              os.pardir, "scripts", "open_prs_session_start.py")
        return subprocess.run([sys.executable, script], capture_output=True,
                              text=True, timeout=30, env=env, cwd=tempfile.gettempdir())

    def test_no_token_and_no_repo_is_silent_and_clean(self):
        env = {k: v for k, v in os.environ.items() if k not in
               ("GITHUB_TOKEN", "GH_TOKEN")}
        env["PATH"] = os.environ.get("PATH", "")
        result = self._run(env)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def _main_with(self, fetch):
        import io
        from unittest import mock
        import open_prs_session_start as hook
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"PROOFS_PR_REMINDER": "1"}), \
                mock.patch.object(hook, "repo_slug", return_value="o/r"), \
                mock.patch.object(hook, "read_token", return_value="t"), \
                mock.patch.object(hook, "fetch_open_prs", side_effect=fetch), \
                mock.patch("sys.stdout", out):
            code = hook.main()
        return code, out.getvalue()

    def test_off_unless_opted_in(self):
        import io
        from unittest import mock
        import open_prs_session_start as hook
        out = io.StringIO()
        env = {k: v for k, v in os.environ.items() if k != "PROOFS_PR_REMINDER"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(hook, "repo_slug", return_value="o/r"), \
                mock.patch.object(hook, "read_token", return_value="t"), \
                mock.patch.object(hook, "fetch_open_prs") as fetch, \
                mock.patch("sys.stdout", out):
            code = hook.main()
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue(), "")
        fetch.assert_not_called()

    def test_message_uses_the_namespaced_command(self):
        self.assertIn("/proofs:pr-qa", summarize([{"number": 1, "created_at": "2026-08-01T00:00:00Z",
                                                   "head": {"ref": "x"}, "title": "t"}], NOW))

    def test_plugin_ships_the_hook(self):
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        with open(os.path.join(root, "hooks", "hooks.json"), encoding="utf-8") as handle:
            cfg = json.load(handle)
        cmd = cfg["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        self.assertEqual(cmd, 'python3 "${CLAUDE_PLUGIN_ROOT}/skills/pr-qa/scripts/open_prs_session_start.py"')
        self.assertTrue(os.path.exists(os.path.join(root, "skills", "pr-qa", "scripts", "open_prs_session_start.py")))

    def test_an_unreachable_github_is_silent(self):
        def blocked(*args, **kwargs):
            raise urllib.error.URLError("blocked")
        code, printed = self._main_with(blocked)
        self.assertEqual(code, 0)
        self.assertEqual(printed, "")

    def test_malformed_json_is_silent(self):
        def bad(*args, **kwargs):
            raise ValueError("not json")
        code, printed = self._main_with(bad)
        self.assertEqual(code, 0)
        self.assertEqual(printed, "")


class BrokenSettingsFileTest(unittest.TestCase):
    """A malformed settings file: defaults, one stderr line naming the file, exit 0."""

    def test_falls_back_to_defaults_with_one_line_and_exit_0(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve() / "home"
            project = Path(tmp).resolve() / "project"
            (home / ".claude").mkdir(parents=True)
            (project / ".git").mkdir(parents=True)
            broken = home / ".claude" / "settings.json"
            broken.write_text("{not json", encoding="utf-8")
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith("PROOFS_") and k not in ("CLAUDE_CONFIG_DIR", "GITHUB_TOKEN", "GH_TOKEN")}
            env["HOME"] = str(home)
            script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  os.pardir, "scripts", "open_prs_session_start.py")
            r = subprocess.run([sys.executable, script], capture_output=True, text=True,
                               timeout=30, env=env, cwd=str(project))
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, "")
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(len(r.stderr.strip().splitlines()), 1, r.stderr)
        self.assertIn(str(broken), r.stderr)
        self.assertIn("defaults", r.stderr)

    def test_summarize_still_works_on_defaults(self):
        import open_prs_session_start as hook
        import settings
        with mock.patch.object(settings, "get", side_effect=settings.SettingsFileError("x is not valid JSON")), \
                mock.patch("sys.stderr", new_callable=lambda: __import__("io").StringIO()) as err:
            hook._warned.clear()
            text = summarize([pr(1, "agent/x", "2026-08-04T08:43:00Z")], NOW)
            text2 = summarize([pr(2, "agent/y", "2026-08-04T08:43:00Z")], NOW)
        self.assertIn("AI fix", text)
        self.assertIn("AI fix", text2)
        self.assertEqual(len(err.getvalue().strip().splitlines()), 1)


class SettingsTest(unittest.TestCase):
    def test_extra_agent_prefixes_get_the_label(self):
        row = pr(3, "claude/fix", "2026-08-04T08:43:00Z")
        with project_with({}):
            self.assertNotIn("AI fix", summarize([row], NOW))
        with project_with({"PROOFS_AGENT_BRANCH_PREFIX": "agent/,claude/"}):
            self.assertIn("AI fix", summarize([row], NOW))
            self.assertIn("AI fix", summarize([pr(4, "agent/x", "2026-08-04T08:43:00Z")], NOW))
            self.assertNotIn("AI fix", summarize([pr(5, "main-fix", "2026-08-04T08:43:00Z")], NOW))

    def test_the_network_wait_is_the_setting(self):
        seen = []

        def opener(req, timeout=None):
            seen.append(timeout)
            return FakeResponse("[]")
        with project_with({}):
            fetch_open_prs("o/r", "t", opener)
        with project_with({"PROOFS_PR_REMINDER_TIMEOUT": "12"}):
            fetch_open_prs("o/r", "t", opener)
        self.assertEqual(seen, [5, 12])

    def test_the_reminder_is_on_when_the_project_file_says_so(self):
        import io
        import open_prs_session_start as hook
        for values, expect_call in (({}, False), ({"PROOFS_PR_REMINDER": "1"}, True)):
            with project_with(values), \
                    mock.patch.object(hook, "repo_slug", return_value="o/r"), \
                    mock.patch.object(hook, "read_token", return_value="t"), \
                    mock.patch.object(hook, "fetch_open_prs", return_value=[]) as fetch, \
                    mock.patch("sys.stdout", io.StringIO()):
                hook.main()
            self.assertEqual(fetch.called, expect_call, values)


if __name__ == "__main__":
    unittest.main(verbosity=2)
