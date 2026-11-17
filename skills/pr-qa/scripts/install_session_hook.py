#!/usr/bin/env python3
"""Turn on the open-PR session reminder for one project.

    python3 scripts/install_session_hook.py

The reminder itself ships with the proofs plugin as a SessionStart hook
(hooks/hooks.json), but it stays silent unless the environment variable
PROOFS_PR_REMINDER is 1. This script sets that variable in the project's
.claude/settings.json "env" block. No path is written, so the file is safe
to commit. Everything else in the file is left alone, and running it twice
changes nothing the second time.
"""
import json
import os
import sys

NAME = "PROOFS_PR_REMINDER"
VALUE = "1"


def install(project_root):
    """True if the setting was added or changed, False if it was already on."""
    path = os.path.join(project_root, ".claude", "settings.json")
    settings = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as handle:
                settings = json.load(handle)
        except ValueError as err:
            sys.exit("==> %s is not valid JSON (%s); fix it and run this again" % (path, err))
        if not isinstance(settings, dict):
            sys.exit("==> %s is not a JSON object; fix it and run this again" % path)
    env = settings.setdefault("env", {})
    if not isinstance(env, dict):
        sys.exit("==> %s has an env entry in an unexpected shape; fix it and run this again" % path)
    if env.get(NAME) == VALUE:
        return False
    env[NAME] = VALUE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(settings, handle, indent=2)
        handle.write("\n")
    return True


def main():
    if install(os.getcwd()):
        print("==> set %s=1 in .claude/settings.json; new sessions will report open pull requests" % NAME)
    else:
        print("==> the open-PR reminder is already on; nothing changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
