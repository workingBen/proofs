#!/usr/bin/env python3
"""Gather every open PR's QA evidence, and say why any PR has none.

    python3 scripts/pr_qa_collect.py --repo owner/name --out work/

Leaves `work/pr-<n>/` per PR that has evidence, and `work/meta.json` with every
mechanical field filled in and the judgment fields empty for a session to write.

WHY EVERY PR GETS AN ENTRY. When two PRs land and are the ones being
discussed, a third that was opened earlier can go unreviewed for days, with no
CI failure and nothing wrong with it. Each batch was reviewed; nobody was
counting the total. A PR with no evidence renders as a card saying so, because
an omission that looks like coverage is worse than a gap.

The token is read from --token, then $GITHUB_TOKEN, then `gh auth token`. With
none of them, the script stops with a plain message. It talks to the REST API
with urllib, so it needs no extra tools.
"""
import argparse
import io
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "shared"))
import settings  # shared/settings.py: the Proofs settings table and resolver

API = "https://api.github.com"
ARTIFACT_NAME = "pr-qa"

ABSENT_REASONS = {
    "no_run": "No run of the QA workflow for this branch — it did not come from the pipeline.",
    "no_artifact": "The run took no screenshots: the gate went red first, "
                   "or the change touched no mapped page.",
    "expired": "The screenshots expired. Actions keeps them 30 days.",
    "download_failed": "The artifact could not be downloaded.",
    "unpack_failed": "The artifact was corrupt or could not be extracted.",
    "lookup_failed": "Could not reach GitHub for this PR's runs.",
}


def find_token(environ=None, run=subprocess.run):
    """$GITHUB_TOKEN, else `gh auth token`, else None."""
    environ = os.environ if environ is None else environ
    if environ.get("GITHUB_TOKEN"):
        return environ["GITHUB_TOKEN"]
    try:
        out = run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    token = (getattr(out, "stdout", "") or "").strip()
    return token if getattr(out, "returncode", 1) == 0 and token else None


def repo_slug(run=subprocess.run):
    """owner/name from origin's URL, for both SSH and HTTPS remotes."""
    try:
        out = run(["git", "config", "--get", "remote.origin.url"],
                  capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if getattr(out, "returncode", 1) != 0:
        return None
    m = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?\s*$", (out.stdout or "").strip())
    return m.group(1) if m else None


def http(url, token=None, binary=False):
    request = urllib.request.Request(url)
    request.add_header("Accept", "application/vnd.github+json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=60) as response:
        body = response.read()
    return body if binary else json.loads(body.decode("utf-8"))


def open_prs(repo, token, fetch=http):
    raw = fetch(f"{API}/repos/{repo}/pulls?state=open&per_page=100", token=token)
    return [{"number": pr["number"], "title": pr.get("title", ""),
             "branch": (pr.get("head") or {}).get("ref", ""),
             "draft": bool(pr.get("draft")), "url": pr.get("html_url", "")}
            for pr in raw]


def qa_artifact_for(repo, branch, token, fetch=http, workflow=None):
    """The newest run of the QA workflow for `branch`, and its pr-qa artifact if it has one.

    Scoped to the workflow's own runs, filtered by branch server-side. Querying
    the unscoped `/actions/runs` (every workflow in the repo) picks up whichever
    workflow happened to run most recently on the branch -- usually a test
    workflow with no `pr-qa` artifact. The 100-run window on that endpoint also
    meant a QA run old enough to have scrolled out of it reported "did not come
    from the pipeline", which was false.
    """
    workflow = workflow or settings.get("PROOFS_QA_WORKFLOW")
    encoded_branch = urllib.parse.quote(branch, safe="")
    runs = fetch(f"{API}/repos/{repo}/actions/workflows/{workflow}/runs"
                 f"?branch={encoded_branch}&per_page=1",
                 token=token).get("workflow_runs", [])
    if not runs:
        return {"run_id": None, "archive_download_url": None,
                "reason": ABSENT_REASONS["no_run"]}
    run = runs[0]
    artifacts = fetch(f"{API}/repos/{repo}/actions/runs/{run['id']}/artifacts",
                      token=token).get("artifacts", [])
    match = next((a for a in artifacts if a.get("name") == ARTIFACT_NAME), None)
    if match is None:
        return {"run_id": run["id"], "archive_download_url": None,
                "reason": ABSENT_REASONS["no_artifact"]}
    if match.get("expired"):
        return {"run_id": run["id"], "archive_download_url": None,
                "reason": ABSENT_REASONS["expired"]}
    return {"run_id": run["id"],
            "archive_download_url": match["archive_download_url"], "reason": ""}


def unpack(blob, dest):
    os.makedirs(dest, exist_ok=True)
    dest_real = os.path.realpath(dest)
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        for entry in archive.namelist():
            # Prevent zip-slip: validate that extracted path stays inside dest.
            # realpath resolves ".." and symlinks; the trailing os.sep on
            # dest_real is what stops a sibling that merely shares dest's name
            # as a prefix (e.g. "work/pr-1-evil") from passing as "inside"
            # "work/pr-1".
            entry_path = os.path.realpath(os.path.join(dest, entry))
            if not entry_path.startswith(dest_real + os.sep):
                raise ValueError(f"Zip entry escapes destination: {entry}")
        archive.extractall(dest)
    return dest


def skeleton(prs, artifacts):
    """meta.json with everything mechanical filled and the judgment left blank."""
    meta = []
    for pr in prs:
        found = artifacts.get(pr["number"], {})
        meta.append({
            "number": pr["number"], "title": pr["title"], "branch": pr["branch"],
            "draft": pr.get("draft", False), "url": pr.get("url", ""),
            "run_id": found.get("run_id"),
            "dir": found.get("dir"),
            "absent_reason": found.get("reason", ""),
            "cost": "", "tests": "",
            # Left empty ON PURPOSE. A session fills these after reading the
            # diff and looking at every screenshot; the builder renders an
            # empty `human_findings` as "not yet read by a reviewer".
            "narrative": "", "recommendation": "", "human_findings": [],
        })
    return meta


def main(argv=None, fetch=http):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", help="owner/name; default: read from the origin remote")
    parser.add_argument("--out", required=True)
    parser.add_argument("--token", help="default: $GITHUB_TOKEN, then `gh auth token`")
    parser.add_argument("--workflow", default=None,
                        help="workflow file whose runs carry the pr-qa artifact (default: the PROOFS_QA_WORKFLOW setting)")
    args = parser.parse_args(argv)
    args.token = args.token or find_token()
    if not args.token:
        print("==> no token: set $GITHUB_TOKEN, run `gh auth login`, or pass --token")
        return 2
    args.repo = args.repo or repo_slug()
    if not args.repo:
        print("==> no repo: pass --repo owner/name, or run from a clone with an origin remote")
        return 2

    os.makedirs(args.out, exist_ok=True)
    try:
        prs = open_prs(args.repo, args.token, fetch=fetch)
    except urllib.error.HTTPError as error:
        if error.code == 401:
            print("==> token rejected (401): GitHub says the token is invalid or "
                  "expired -- renew it and try again")
            return 2
        raise
    artifacts = {}
    for pr in prs:
        try:
            found = qa_artifact_for(args.repo, pr["branch"], args.token, fetch=fetch,
                                   workflow=args.workflow)
        except Exception as error:   # noqa: BLE001 -- best effort, and it SAYS so
            found = {"run_id": None, "archive_download_url": None,
                     "reason": (f'{ABSENT_REASONS["lookup_failed"]} '
                                f"({type(error).__name__})")}
        found["dir"] = None
        url = found.get("archive_download_url")
        if url:
            try:
                blob = fetch(url, token=args.token, binary=True)
            except Exception as error:   # noqa: BLE001 -- best effort, and it SAYS so
                found["reason"] = (f'{ABSENT_REASONS["download_failed"]} '
                                   f"({type(error).__name__})")
            else:
                try:
                    found["dir"] = unpack(blob, os.path.join(args.out, f'pr-{pr["number"]}'))
                except Exception as error:   # noqa: BLE001 -- best effort, and it SAYS so
                    found["reason"] = (f'{ABSENT_REASONS["unpack_failed"]} '
                                       f"({type(error).__name__})")
        artifacts[pr["number"]] = found
        state = found["dir"] or f'no evidence — {found["reason"]}'
        print(f'==> #{pr["number"]} {pr["branch"]}: {state}')

    meta = skeleton(prs, artifacts)
    with open(os.path.join(args.out, "meta.json"), "w", encoding="utf-8") as handle:
        json.dump(meta, handle, indent=2)
    print(f'==> {len(meta)} PR(s) -> {os.path.join(args.out, "meta.json")}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
