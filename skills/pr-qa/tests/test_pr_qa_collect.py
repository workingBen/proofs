"""Unit tests for scripts/pr_qa_collect.py.

Standard library only, and entirely offline -- every network call goes through
an injected `fetch`.

Run:  python3 -m unittest discover skills/pr-qa/tests
"""
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
import zipfile
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from pr_qa_collect import (
    open_prs, qa_artifact_for, unpack, skeleton, ABSENT_REASONS, main,
)


def pull_url(number):
    return "https://github.com/x/y/pull/%d" % number


def fake_fetch(responses):
    """Map a URL substring to a payload. An unmatched URL is a test bug, loudly."""
    def fetch(url, token=None, binary=False):
        # Match longest fragment first to avoid substring ambiguity
        matches = [(fragment, payload) for fragment, payload in responses.items()
                   if fragment in url]
        if not matches:
            raise AssertionError(f"unexpected request: {url}")
        # Return the payload for the longest matching fragment
        return max(matches, key=lambda x: len(x[0]))[1]
    return fetch


class OpenPrsTest(unittest.TestCase):
    def test_returns_number_title_and_head_branch(self):
        fetch = fake_fetch({"/pulls": [
            {"number": 7, "title": "A change", "head": {"ref": "agent/todo-31"},
             "draft": True, "html_url": pull_url(7)}]})
        prs = open_prs("x/y", "t", fetch=fetch)
        self.assertEqual(prs[0]["number"], 7)
        self.assertEqual(prs[0]["branch"], "agent/todo-31")
        self.assertTrue(prs[0]["draft"])


class ArtifactMatchTest(unittest.TestCase):
    # The server-side-scoped endpoint (finding 1): the WORKFLOW's own runs,
    # filtered by branch, newest first, one requested. Only ever one run in
    # these fixtures -- the server already did the filtering GitHub-side.
    RUNS = {"/actions/workflows/pr-qa.yml/runs": {"workflow_runs": [
        {"id": 22, "head_branch": "agent/todo-31", "created_at": "2026-08-05T00:00:00Z"}]}}

    def test_picks_the_agent_fix_run_for_that_branch(self):
        fetch = fake_fetch(dict(self.RUNS, **{
            "/runs/22/artifacts": {"artifacts": [
                {"name": "pr-qa", "expired": False,
                 "archive_download_url": "https://api/zip/22"}]}}))
        found = qa_artifact_for("x/y", "agent/todo-31", "t", fetch=fetch)
        self.assertEqual(found["run_id"], 22)

    def test_requests_the_workflow_scoped_branch_filtered_endpoint(self):
        """The URL itself must name WORKFLOW and the URL-encoded branch --
        this is what makes the request server-side scoped rather than a
        client-side filter over every workflow's runs."""
        seen = {}

        def fetch(url, token=None, binary=False):
            if "/actions/workflows/pr-qa.yml/runs" in url:
                seen["runs_url"] = url
                return {"workflow_runs": [
                    {"id": 22, "head_branch": "agent/todo-31",
                     "created_at": "2026-08-05T00:00:00Z"}]}
            return {"artifacts": []}

        qa_artifact_for("x/y", "agent/todo-31", "t", fetch=fetch)
        self.assertIn("/actions/workflows/pr-qa.yml/runs", seen["runs_url"])
        self.assertIn("branch=agent%2Ftodo-31", seen["runs_url"])

    def test_a_newer_non_agent_fix_run_on_the_same_branch_is_not_picked(self):
        """The unscoped `/actions/runs` endpoint (every workflow in the repo)
        would return a NEWER test-workflow run on this branch here. The
        collector must never look at it -- only the workflow-scoped endpoint
        -- or it explains a run it never looked at (finding 1)."""
        def fetch(url, token=None, binary=False):
            if "/actions/workflows/pr-qa.yml/runs" in url:
                return {"workflow_runs": [
                    {"id": 22, "head_branch": "agent/todo-31",
                     "created_at": "2026-08-01T00:00:00Z"}]}
            if "/runs/22/artifacts" in url:
                return {"artifacts": [
                    {"name": "pr-qa", "expired": False,
                     "archive_download_url": "https://api/zip/22"}]}
            if "/actions/runs" in url:
                raise AssertionError(
                    "must not query the unscoped /actions/runs endpoint -- "
                    "it mixes in every other workflow")
            raise AssertionError(f"unexpected request: {url}")

        found = qa_artifact_for("x/y", "agent/todo-31", "t", fetch=fetch)
        self.assertEqual(found["run_id"], 22)

    def test_an_expired_artifact_is_reported_not_silently_skipped(self):
        fetch = fake_fetch(dict(self.RUNS, **{
            "/runs/22/artifacts": {"artifacts": [
                {"name": "pr-qa", "expired": True, "archive_download_url": "u"}]}}))
        found = qa_artifact_for("x/y", "agent/todo-31", "t", fetch=fetch)
        self.assertIsNone(found["archive_download_url"])
        self.assertEqual(found["reason"], ABSENT_REASONS["expired"])

    def test_a_run_with_no_pr_qa_artifact_says_which_reason(self):
        fetch = fake_fetch(dict(self.RUNS, **{
            "/runs/22/artifacts": {"artifacts": []}}))
        found = qa_artifact_for("x/y", "agent/todo-31", "t", fetch=fetch)
        self.assertEqual(found["reason"], ABSENT_REASONS["no_artifact"])

    def test_a_branch_with_no_agent_run_at_all_is_not_from_the_pipeline(self):
        # A real ?branch=<x> query returns an empty list server-side when no
        # run of this workflow ever ran on that branch -- there is nothing
        # for the fixture to filter client-side, unlike the old unscoped
        # endpoint.
        fetch = fake_fetch({"/actions/workflows/pr-qa.yml/runs":
                            {"workflow_runs": []}})
        found = qa_artifact_for("x/y", "hand-written-branch", "t", fetch=fetch)
        self.assertEqual(found["reason"], ABSENT_REASONS["no_run"])

    def test_one_pr_lookup_failure_does_not_abort_the_whole_run(self):
        """Test that main() records per-PR lookup failures and continues gathering others."""
        def fetch_selective(url, token=None, binary=False):
            # Return PRs list
            if "/pulls" in url:
                return [
                    {"number": 7, "title": "Good", "head": {"ref": "agent/good-31"},
                     "draft": False, "html_url": pull_url(7)},
                    {"number": 5, "title": "Bad", "head": {"ref": "agent/bad-31"},
                     "draft": False, "html_url": pull_url(5)},
                ]
            # Return the workflow-scoped, branch-filtered run for each branch
            if "/actions/workflows/pr-qa.yml/runs" in url:
                if "branch=agent%2Fgood-31" in url:
                    return {"workflow_runs": [
                        {"id": 1, "head_branch": "agent/good-31",
                         "created_at": "2026-08-05T00:00:00Z"}]}
                if "branch=agent%2Fbad-31" in url:
                    return {"workflow_runs": [
                        {"id": 2, "head_branch": "agent/bad-31",
                         "created_at": "2026-08-05T00:00:00Z"}]}
                raise AssertionError(f"unexpected branch query: {url}")
            # Artifact lookup for run 1 succeeds with an artifact
            if "/runs/1/artifacts" in url:
                return {"artifacts": [
                    {"name": "pr-qa", "expired": False,
                     "archive_download_url": "https://api/zip/1"}]}
            # Artifact lookup for run 2 fails (simulating transient GitHub error)
            if "/runs/2/artifacts" in url:
                raise OSError("GitHub API temporarily unavailable")
            # Handle artifact download for the good PR
            if "zip/1" in url:
                # Return a minimal valid ZIP
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, "w") as archive:
                    archive.writestr("test.txt", b"evidence")
                return buffer.getvalue()
            raise AssertionError(f"unexpected request: {url}")

        with tempfile.TemporaryDirectory() as tmp:
            argv = ["--repo", "x/y", "--out", tmp, "--token", "t"]
            result = main(argv, fetch=fetch_selective)
            # main() should exit 0 even if one PR failed
            self.assertEqual(result, 0)
            # Read meta.json to verify both PRs are recorded
            with open(os.path.join(tmp, "meta.json")) as f:
                meta = json.load(f)
            self.assertEqual(len(meta), 2)
            pr_7 = [m for m in meta if m["number"] == 7][0]
            pr_5 = [m for m in meta if m["number"] == 5][0]
            # PR 7 succeeded (has directory or at least no error reason)
            self.assertEqual(pr_7["branch"], "agent/good-31")
            self.assertIsNotNone(pr_7["dir"])
            # PR 5 has the lookup_failed reason
            self.assertEqual(pr_5["branch"], "agent/bad-31")
            # Check for the actual reason text and exception type
            self.assertIn("Could not reach GitHub", pr_5["absent_reason"])
            self.assertIn("OSError", pr_5["absent_reason"])

    def test_corrupt_archive_is_labeled_unpack_failed_not_download_failed(self):
        """Test that a corrupt ZIP is reported as unpack_failed, not download_failed."""
        def fetch_with_corrupt(url, token=None, binary=False):
            # Return PRs list
            if "/pulls" in url:
                return [
                    {"number": 7, "title": "Corrupt", "head": {"ref": "agent/corrupt-31"},
                     "draft": False, "html_url": pull_url(7)},
                ]
            # Return the workflow-scoped, branch-filtered run
            if "/actions/workflows/pr-qa.yml/runs" in url:
                return {"workflow_runs": [
                    {"id": 1, "head_branch": "agent/corrupt-31", "created_at": "2026-08-05T00:00:00Z"}]}
            if "/runs/1/artifacts" in url:
                return {"artifacts": [
                    {"name": "pr-qa", "expired": False,
                     "archive_download_url": "https://api/zip/corrupt"}]}
            # Return garbage bytes for the download
            if "zip/corrupt" in url:
                return b"not a valid zip file at all"
            raise AssertionError(f"unexpected request: {url}")

        with tempfile.TemporaryDirectory() as tmp:
            argv = ["--repo", "x/y", "--out", tmp, "--token", "t"]
            result = main(argv, fetch=fetch_with_corrupt)
            self.assertEqual(result, 0)
            # Read meta.json to verify the reason is unpack_failed, not download_failed
            with open(os.path.join(tmp, "meta.json")) as f:
                meta = json.load(f)
            self.assertEqual(len(meta), 1)
            pr_7 = meta[0]
            self.assertIn("corrupt", pr_7["absent_reason"].lower())
            self.assertIn("BadZipFile", pr_7["absent_reason"])


class UnpackTest(unittest.TestCase):
    def test_unzips_the_evidence_into_the_destination(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("findings.json", json.dumps({"verdict": "clean"}))
            archive.writestr("after-x-phone.png", b"\x89PNG")
        with tempfile.TemporaryDirectory() as tmp:
            dest = unpack(buffer.getvalue(), os.path.join(tmp, "pr-7"))
            self.assertTrue(os.path.exists(os.path.join(dest, "findings.json")))
            self.assertTrue(os.path.exists(os.path.join(dest, "after-x-phone.png")))

    def test_rejects_zip_entries_that_escape_destination(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("../escape.txt", b"should not extract")
            archive.writestr("safe.txt", b"safe")
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "pr-7")
            self.assertRaises(ValueError, unpack, buffer.getvalue(), dest)
            # Verify no file was written outside destination
            self.assertFalse(os.path.exists(os.path.join(tmp, "escape.txt")))
            self.assertFalse(os.path.exists(os.path.join(tmp, "pr-7", "escape.txt")))

    def test_corrupt_archive_raises_unpack_error(self):
        # Garbage bytes that are not a valid ZIP
        corrupt_blob = b"This is not a zip file at all"
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "pr-7")
            self.assertRaises(zipfile.BadZipFile, unpack, corrupt_blob, dest)


class SkeletonTest(unittest.TestCase):
    def test_every_pr_gets_an_entry_even_with_no_evidence(self):
        prs = [{"number": 7, "title": "A", "branch": "agent/todo-31", "draft": True},
               {"number": 5, "title": "B", "branch": "docs-only", "draft": False}]
        artifacts = {7: {"dir": "work/pr-7", "run_id": 22, "reason": ""},
                     5: {"dir": None, "run_id": None,
                         "reason": ABSENT_REASONS["no_run"]}}
        meta = skeleton(prs, artifacts)
        self.assertEqual(len(meta), 2)
        absent = [m for m in meta if m["number"] == 5][0]
        self.assertIsNone(absent["dir"])
        self.assertEqual(absent["absent_reason"], ABSENT_REASONS["no_run"])

    def test_the_judgment_fields_are_left_empty_for_a_session_to_fill(self):
        meta = skeleton([{"number": 7, "title": "A", "branch": "b", "draft": True}],
                        {7: {"dir": "work/pr-7", "run_id": 1, "reason": ""}})
        self.assertEqual(meta[0]["human_findings"], [])
        self.assertEqual(meta[0]["narrative"], "")
        self.assertEqual(meta[0]["recommendation"], "")


class NoTokenTest(unittest.TestCase):
    def _fake_run(self, stdout, returncode=0):
        return lambda *a, **k: mock.Mock(stdout=stdout, returncode=returncode)

    def test_env_token_wins(self):
        from pr_qa_collect import find_token
        self.assertEqual(find_token({"GITHUB_TOKEN": "env"}, self._fake_run("gh\n")), "env")

    def test_falls_back_to_gh_auth_token(self):
        from pr_qa_collect import find_token
        self.assertEqual(find_token({}, self._fake_run("gh\n")), "gh")

    def test_no_token_anywhere_is_none(self):
        from pr_qa_collect import find_token
        self.assertIsNone(find_token({}, self._fake_run("", returncode=1)))

    def test_no_token_stops_with_a_plain_message_and_no_network(self):
        def never(url, token=None, binary=False):
            raise AssertionError("must not touch the network without a token")
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("pr_qa_collect.find_token", return_value=None):
            result = main(["--repo", "x/y", "--out", tmp], fetch=never)
        self.assertEqual(result, 2)


class TokenErrorTest(unittest.TestCase):
    def test_a_stale_token_401_reports_clearly_not_a_traceback(self):
        """An unset token never reaches the network (that path already exited
        2 before this). A STALE token does reach GitHub, which 401s on the
        very first call (`open_prs`) -- that used to propagate as a bare
        HTTPError out of main(), a traceback with no meta.json."""
        def fetch_401(url, token=None, binary=False):
            if "/pulls" in url:
                raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, None)
            raise AssertionError(f"unexpected request: {url}")

        with tempfile.TemporaryDirectory() as tmp:
            argv = ["--repo", "x/y", "--out", tmp, "--token", "stale-token"]
            result = main(argv, fetch=fetch_401)
            self.assertEqual(result, 2)
            self.assertFalse(os.path.exists(os.path.join(tmp, "meta.json")))

    def test_a_non_401_http_error_is_not_swallowed_as_a_token_problem(self):
        """A 500 from GitHub is not a credential problem -- it must still
        surface, not be misreported as a rejected token."""
        def fetch_500(url, token=None, binary=False):
            if "/pulls" in url:
                raise urllib.error.HTTPError(url, 500, "Server Error", {}, None)
            raise AssertionError(f"unexpected request: {url}")

        with tempfile.TemporaryDirectory() as tmp:
            argv = ["--repo", "x/y", "--out", tmp, "--token", "t"]
            with self.assertRaises(urllib.error.HTTPError):
                main(argv, fetch=fetch_500)


if __name__ == "__main__":
    unittest.main()
