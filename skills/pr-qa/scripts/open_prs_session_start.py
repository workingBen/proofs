#!/usr/bin/env python3
"""Tell the session, at its start, which pull requests are still open.

A PR that nobody names can sit open for days: no CI failure, no comment, no
note pointed at it. Each batch gets reviewed; no one is counting the total.
A better habit does not fix that. A count does. This runs as a SessionStart
hook and says how many PRs are open and how old the oldest is, so an
unreviewed one cannot go quiet.

It ships with the plugin (hooks/hooks.json) but is off by default: it does
nothing unless PROOFS_PR_REMINDER is on (1). Turn it on for a project with
`python3 scripts/install_session_hook.py`.

The token comes from $GITHUB_TOKEN, then `gh auth token`.

It must never be the reason a session fails to start. Every failure path --
no token, no network, GitHub down, malformed JSON -- exits 0 and says
nothing. A silent hook is a hook that has nothing to report; that is the
same outcome as a healthy repo with no open PRs, and deliberately so.
"""
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "shared"))
import settings  # shared/settings.py: the Proofs settings table and resolver

_warned = []


def setting(key):
    """The setting's value, or the table's default when a settings file cannot be read: the
    hook must never block a session, so it says so once on stderr and goes on with defaults."""
    try:
        return settings.get(key)
    except settings.SettingsFileError as e:
        if not _warned:
            _warned.append(True)
            print("proofs PR reminder: %s Using the defaults for now." % e, file=sys.stderr)
        return settings._row(key)["default"]

# The session is waiting on the network, so the wait is a setting (PROOFS_PR_REMINDER_TIMEOUT,
# five seconds by default: plenty for one API call, and an unreachable GitHub costs less than a
# blink). The branch prefixes that mark a PR an AI agent opened, which get a label, are the
# PROOFS_AGENT_BRANCH_PREFIX setting.

def repo_slug(run=subprocess.run):
    """owner/name from origin's URL, for both SSH and HTTPS remotes."""
    try:
        out = run(
            ["git", "config", "--get", "remote.origin.url"],
            capture_output=True, text=True, timeout=setting("PROOFS_PR_REMINDER_TIMEOUT"),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if getattr(out, "returncode", 1) != 0:
        return None
    m = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?\s*$", (out.stdout or "").strip())
    return m.group(1) if m else None


def read_token(environ=None, run=subprocess.run):
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


def fetch_open_prs(slug, token, opener=urllib.request.urlopen):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{slug}/pulls?state=open&per_page=100"
    )
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    with opener(req, timeout=setting("PROOFS_PR_REMINDER_TIMEOUT")) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data if isinstance(data, list) else []


def age_phrase(created_at, now):
    """How old, in the coarsest unit that is still honest."""
    try:
        opened = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return "age unknown"
    hours = (now - opened).total_seconds() / 3600
    if hours < 1:
        return "under an hour old"
    if hours < 48:
        return f"{int(hours)}h old"
    return f"{int(hours // 24)} days old"


def summarize(prs, now):
    """The hook's message, or None when there is nothing worth saying.

    Ordered oldest first: the one that has been waiting longest is the one
    most likely to have been forgotten, which is the whole point.
    """
    if not prs:
        return None
    rows = sorted(prs, key=lambda p: p.get("created_at") or "")
    lines = [
        f"{len(rows)} open pull request{'s' if len(rows) != 1 else ''} "
        f"in this repo, oldest first:",
        "",
    ]
    prefixes = setting("PROOFS_AGENT_BRANCH_PREFIX")
    for pr in rows:
        head = (pr.get("head") or {}).get("ref") or "?"
        marks = []
        if head.startswith(tuple(prefixes)):
            marks.append("AI fix")
        if pr.get("draft"):
            marks.append("draft — cannot be merged until marked ready")
        suffix = f" [{'; '.join(marks)}]" if marks else ""
        lines.append(
            f"  #{pr.get('number')}  {age_phrase(pr.get('created_at'), now)}"
            f"  {pr.get('title') or head}{suffix}"
        )
    lines += [
        "",
        "Do not act on these unasked. Mention them if the user has not, and "
        "offer /proofs:pr-qa, which with no arguments QAs every one of them.",
    ]
    return "\n".join(lines)


def main():
    if not setting("PROOFS_PR_REMINDER"):
        return 0
    slug = repo_slug()
    token = read_token()
    if not slug or not token:
        return 0
    try:
        prs = fetch_open_prs(slug, token)
    except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError):
        return 0
    message = summarize(prs, datetime.now(timezone.utc))
    if not message:
        return 0
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": message,
        }
    }))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 -- never block a session from starting
        sys.exit(0)
