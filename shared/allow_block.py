#!/usr/bin/env python3
"""Print the Claude Code permission rules that let Proofs read its own files and run
its own page builders without asking, for this machine.

    python3 <plugin root>/shared/allow_block.py [--lines]

Prints {"permissions": {"allow": [...]}} for a settings file that has no permissions
key yet, or with --lines just the rules, comma-separated, to add to an existing
permissions.allow list. Use ~/.claude/settings.json (every project) or a project's
.claude/settings.local.json, never a committed .claude/settings.json: the Bash lines
hold your home folder.

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


def rules(home, config_dir):
    """Read rule first, then the Skill rule, then one Bash rule per script, sorted."""
    if config_dir:
        base = config_dir.rstrip("/")
        read = "Read(/%s/%s/**)" % (base, CACHE)
    else:
        base = home.rstrip("/") + "/.claude"
        read = "Read(~/.claude/%s/**)" % CACHE
    bash = sorted("Bash(%s %s/%s/proofs/*/%s *)" % (interp, base, CACHE, path) for interp, path in scripts())
    return [read, SKILL_RULE] + bash


def main(argv):
    args = argv[1:]
    if args not in ([], ["--lines"]):
        print(__doc__.strip(), file=sys.stderr)
        return 0 if args in (["-h"], ["--help"]) else 2
    home = os.environ.get("HOME") or str(Path.home())
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR") or None
    if config_dir:
        config_dir = os.path.abspath(os.path.expanduser(config_dir))
    allow = rules(home, config_dir)
    if args == ["--lines"]:
        print(",\n".join(json.dumps(r) for r in allow))
    else:
        print(json.dumps({"permissions": {"allow": allow}}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
