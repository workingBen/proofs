#!/usr/bin/env python3
"""Print the Claude Code permission rules that let Proofs read its own files and run
its own page builders without asking, for this machine.

    python3 <plugin root>/shared/allow_block.py [--lines] [--headless | --project]

Prints {"permissions": {"allow": [...]}} for a settings file that has no permissions
key yet, or with --lines just the rules, comma-separated, to add to an existing
permissions.allow list. --headless adds one more rule, for unattended (claude -p) runs
only: it pre-approves shared/capture/with_server.py, which runs whatever --start command
it is given, so it is never in the standard output. --project prints a separate,
opt-in block for the project's own commands (installs, the type check, the pr-qa base
worktree, the one-time Playwright install) and nothing else; it holds no home path, so
it may go in a committed .claude/settings.json, but its npm install and npm ci run the
project's package scripts. --project may be combined with --headless (the output is both
sets, so it holds the home folder again). For the default and --headless output use
~/.claude/settings.json (every project; with a custom $CLAUDE_CONFIG_DIR, that folder's
settings.json) or a project's .claude/settings.local.json, never a committed
.claude/settings.json: those Bash lines hold your home folder.

The scripts come from each skill's allowed-tools list, read at run time, so there is
no second list to keep in step. Claude Code fills in ~ in Read rules but matches Bash
rules against the command text, which holds the absolute path, so Bash lines carry
the home folder (or $CLAUDE_CONFIG_DIR when it is set) and a * for the version folder.
"""
import json
import os
import re
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
ROOT = "${CLAUDE_PLUGIN_ROOT}"
CACHE = "plugins/cache/proofs"
# One Bash rule shape, the only one bin/check-skills accepts: interpreter, the plugin root, one script.
BASH_RULE = re.compile(r"Bash\((python3|node) " + re.escape(ROOT) + r"/([\w./-]+) \*\)")
# A skill that declares allowed-tools makes Claude Code ask before the Skill call itself.
SKILL_RULE = "Skill(proofs:*)"
# Opt-in (--project): the project's own commands the skills run. No home path in any rule, and
# nothing that runs an arbitrary command (no with_server.py, no npm run, no bare wildcard).
# npm install and npm ci run the project's package scripts, which is the one risk.
PROJECT_RULES = [
    "Bash(npm install)",
    "Bash(npm ci)",
    # The * also accepts .proofs/base/../other; low risk in an opt-in block.
    "Bash(npm ci --prefix .proofs/base/*)",
    "Bash(npx tsc --noEmit)",
    # pr-qa: resolve the base folder, list open PRs, switch to the PR branch.
    "Bash(printenv PROOFS_BASE_DIR)",
    "Bash(gh pr list *)",
    "Bash(gh pr checkout *)",
    # The default base folder only; a PROOFS_BASE_DIR base is an absolute path, so it still asks.
    "Bash(cp .env .proofs/base/*)",
    "Bash(git fetch origin)",
    "Bash(git worktree add .proofs/base *)",
    "Bash(git worktree remove --force .proofs/base)",
    "Bash(npm install --prefix ~/.cache/proofs-playwright playwright@1.61.1)",
]
# Starts a dev server from an arbitrary command, so it is opt-in (--headless), never default.
HEADLESS_SCRIPT = ("python3", "shared/capture/with_server.py")


def _allowed_tools(text):
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not m:
        return []
    out, inside = [], False
    for line in m.group(1).splitlines():
        if re.match(r"allowed-tools\s*:", line):
            inside = True
            continue
        if inside:
            im = re.match(r"\s+-\s+(.*\S)\s*$", line)
            if not im:
                break
            out.append(im.group(1).strip("\"'"))
    return out


def scripts(plugin=PLUGIN):
    """Sorted (interpreter, path from the plugin root) for every pre-approved script."""
    found = set()
    for skill in sorted((plugin / "skills").glob("*/SKILL.md")):
        for rule in _allowed_tools(skill.read_text()):
            m = BASH_RULE.fullmatch(rule)
            if m:
                found.add((m.group(1), m.group(2)))
    return sorted(found)


def rules(home, config_dir, headless=False):
    """Read rule first, then the Skill rule, then one Bash rule per script, sorted.

    headless=True appends one rule for the capture helper, for unattended runs only."""
    if config_dir:
        base = config_dir.rstrip("/")
        read = "Read(/%s/%s/**)" % (base, CACHE)
    else:
        base = home.rstrip("/") + "/.claude"
        read = "Read(~/.claude/%s/**)" % CACHE
    def bash_rule(interp, path):
        return "Bash(%s %s/%s/proofs/*/%s *)" % (interp, base, CACHE, path)
    bash = sorted(bash_rule(interp, path) for interp, path in scripts())
    extra = [bash_rule(*HEADLESS_SCRIPT)] if headless else []
    return [read, SKILL_RULE] + bash + extra


def main(argv):
    args = argv[1:]
    if len(set(args)) != len(args) or not set(args) <= {"--lines", "--headless", "--project"}:
        print(__doc__.strip(), file=sys.stderr)
        return 0 if args in (["-h"], ["--help"]) else 2
    home = os.environ.get("HOME") or str(Path.home())
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR") or None
    if config_dir:
        config_dir = os.path.abspath(os.path.expanduser(config_dir))
    if "--project" in args and "--headless" not in args:
        allow = list(PROJECT_RULES)
    else:
        allow = rules(home, config_dir, headless="--headless" in args)
        if "--project" in args:
            allow += PROJECT_RULES
    if "--lines" in args:
        print(",\n".join(json.dumps(r) for r in allow))
    else:
        print(json.dumps({"permissions": {"allow": allow}}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
