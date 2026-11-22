"""Keep the .proofs/ scratch folder out of git without touching the project's .gitignore.

ensure_excluded(start) appends ".proofs/" to the repo's info/exclude (the per-clone ignore
file, shared by linked worktrees) unless git already ignores it. It never raises: no git,
not a repository or a read-only file all return None. Python 3 standard library only.
"""
import subprocess
from pathlib import Path

PATTERN = ".proofs/"


def _git(start, *args):
    return subprocess.run(["git", *args], cwd=str(start), capture_output=True, text=True, timeout=30)


def ensure_excluded(start):
    """Return the exclude file written, or None when nothing was (or could be) written."""
    try:
        start = Path(start)
        r = _git(start, "rev-parse", "--git-path", "info/exclude")
        if r.returncode != 0 or not r.stdout.strip():
            return None
        if _git(start, "check-ignore", "-q", PATTERN).returncode == 0:
            return None
        target = (start / r.stdout.strip()).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        existing = target.read_text() if target.exists() else ""
        if any(ln.strip() == PATTERN for ln in existing.splitlines()):
            return None
        with open(target, "a") as f:
            f.write(("" if not existing or existing.endswith("\n") else "\n") + PATTERN + "\n")
        return str(target)
    except Exception:
        return None
