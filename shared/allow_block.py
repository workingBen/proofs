#!/usr/bin/env python3
"""Print the Claude Code permission rules that let Proofs read its own files and run
its own page builders without asking, for this machine.

    python3 <plugin root>/shared/allow_block.py [--lines] [--headless] [--project] [--stack NAME[,NAME]] [--commit]

Prints {"permissions": {"allow": [...]}} for a settings file that has no permissions
key yet, or with --lines just the rules, comma-separated, to add to an existing
permissions.allow list. --headless adds one more rule, for unattended (claude -p) runs
only: it pre-approves shared/capture/with_server.py, which runs whatever --start command
it is given, so it is never in the standard output. --project prints a separate,
opt-in block for the project's own commands (its toolchain's install, test and type-check
lines, the pr-qa base worktree and its read-only gh pr lines, the one-time Playwright install, opening pages under
.proofs/pages) and nothing else; it holds no home path, so it may go in a committed
.claude/settings.json, but its installs run the project's own install scripts. The
toolchain comes from marker files in the folder you run it in (package.json for node,
requirements.txt, pyproject.toml or manage.py for python, composer.json for php, Gemfile
for ruby, a *.csproj or *.sln for dotnet, pom.xml or build.gradle for java); --stack
names it instead, when there is no marker (for example --stack python, or --stack
python,node for two). With no marker and no --stack it prints the node rules, as
before 1.6.0, and says so on stderr. --project may be combined with --headless (the output is both
sets, so it holds the home folder again). --commit prints a second opt-in block for
saving and sharing work (git add, git commit, git push -u origin HEAD, gh pr create). It
is opt-in, never part of --project, because git push and gh pr create reach GitHub; it
holds no home path and combines with every other flag. For the default and --headless
output use ~/.claude/settings.json (every project; with a custom $CLAUDE_CONFIG_DIR, that folder's
settings.json) or a project's .claude/settings.local.json, never a committed
.claude/settings.json: those Bash lines hold your home folder.

The scripts come from each skill's allowed-tools list, read at run time, so there is
no second list to keep in step. Claude Code fills in ~ in Read rules but matches Bash
rules against the command text, which holds the absolute path, so Bash lines carry
the home folder (or $CLAUDE_CONFIG_DIR when it is set) and a * for the version folder.
A proofs marketplace added from a local folder (`/plugin marketplace add <folder>`) runs
from that folder, not the cache, so its rules are added too, with that folder's path.
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
# nothing that runs an arbitrary command (no with_server.py, no npm run *, no bare interpreter, no
# bare wildcard): each wildcard rule names its subcommand first. Installs run the project's own
# install scripts (package scripts, composer scripts, setup.py), which is the one risk.
# Shared by every stack: the pr-qa base worktree, the Playwright install, opening pages.
PROJECT_RULES = [
    # pr-qa: resolve the base folder, list open PRs, switch to the PR branch.
    "Bash(printenv PROOFS_BASE_DIR)",
    # Rails run 1: pr-qa's first line reads both settings in one call (where pages go, and the
    # base folder); the skill gives this exact form.
    "Bash(printenv PROOFS_PAGES PROOFS_BASE_DIR)",
    "Bash(gh pr list *)",
    "Bash(gh pr checkout *)",
    # Read-only: another open PR's files and details, to check for overlap (Django run 2).
    "Bash(gh pr diff *)",
    "Bash(gh pr view *)",
    # The default base folder only; a PROOFS_BASE_DIR base is an absolute path, so it still asks.
    "Bash(cp .env .proofs/base/*)",
    "Bash(git fetch origin)",
    # --detach: works when the base branch is the one checked out in the project. With no GitHub
    # PR the after shot uses the same slot for the branch, so nothing switches your checkout.
    "Bash(git worktree add --detach .proofs/base *)",
    "Bash(git worktree remove --force .proofs/base)",
    # The capture is a Node script on every stack, so every stack needs this one install.
    "Bash(npm install --prefix ~/.cache/proofs-playwright playwright@1.61.1)",
    # Open a page the skills just built (macOS, then Linux); only under .proofs/pages.
    "Bash(open .proofs/pages/*)",
    "Bash(xdg-open .proofs/pages/*)",
]
# Each toolchain's own lines, in the forms sessions type them (Django run 1: `python3 -m venv
# .venv`, `.venv/bin/pip install -r requirements.txt`, `.venv/bin/python manage.py test`).
# Dev servers are not here: they start through with_server.py, which --headless covers.
STACK_RULES = {
    "node": [
        "Bash(npm install)",
        "Bash(npm ci)",
        # The * also accepts .proofs/base/../other; low risk in an opt-in block.
        "Bash(npm ci --prefix .proofs/base/*)",
        "Bash(npx tsc --noEmit)",
        "Bash(pnpm install)",
        "Bash(pnpm install --frozen-lockfile)",
        "Bash(yarn install)",
        "Bash(yarn install --frozen-lockfile)",
        # Vue run 1: a Vue app type-checks with vue-tsc, not tsc, and the check was skipped. The
        # front-end frameworks' own checkers, then the check and build scripts, each by name (never
        # `npm run *`: dev, start and deploy still ask, and dev servers go through with_server.py).
        "Bash(npx vue-tsc --noEmit)",
        "Bash(npx vue-tsc --build)",
        "Bash(npx svelte-check)",
        "Bash(npx svelte-check --tsconfig *)",
        "Bash(npx astro check)",
        "Bash(npx ng build)",
        "Bash(npx ng test --watch=false)",
        "Bash(npm run build)",
        "Bash(npm test)",
        "Bash(npm run test)",
        "Bash(npm run lint)",
        "Bash(npm run type-check)",
        "Bash(npm run typecheck)",
        "Bash(npm run check)",
    ],
    "python": [
        "Bash(python3 -m venv .venv)",
        # A requirements file only: a bare `pip install <name>` still asks.
        "Bash(.venv/bin/pip install -r *)",
        "Bash(.venv/bin/pip install -e .)",
        "Bash(.venv/bin/python manage.py test *)",
        "Bash(.venv/bin/python manage.py migrate *)",
        "Bash(.venv/bin/python manage.py check *)",
        "Bash(.venv/bin/python manage.py collectstatic *)",
        "Bash(.venv/bin/pytest *)",
        "Bash(.venv/bin/python -m pytest *)",
        "Bash(uv sync *)",
        "Bash(uv run pytest *)",
        "Bash(uv run manage.py test *)",
    ],
    "php": [
        "Bash(composer install *)",
        "Bash(php artisan key:generate)",
        "Bash(php artisan migrate *)",
        "Bash(php artisan test *)",
        "Bash(vendor/bin/phpunit *)",
    ],
    "ruby": [
        "Bash(bundle install)",
        # pr-qa's base checkout (Rails run 1: `bundle install --gemfile .proofs/base/rails/Gemfile`
        # was denied). Like `npm ci --prefix`, the * also accepts .proofs/base/../other.
        "Bash(bundle install --gemfile .proofs/base/*)",
        "Bash(bin/rails db:prepare)",
        "Bash(bin/rails test *)",
        "Bash(bundle exec rake test *)",
        "Bash(bundle exec rspec *)",
    ],
    "dotnet": [
        "Bash(dotnet restore *)",
        "Bash(dotnet build *)",
        "Bash(dotnet test *)",
    ],
    "java": [
        "Bash(mvn install -DskipTests)",
        "Bash(mvn test *)",
        "Bash(./mvnw install -DskipTests)",
        "Bash(./mvnw test *)",
        "Bash(gradle build *)",
        "Bash(gradle test *)",
        "Bash(./gradlew build *)",
        "Bash(./gradlew test *)",
    ],
}
STACKS = tuple(STACK_RULES)
# Marker files in the project folder: exact names, then glob patterns.
STACK_MARKERS = {
    "node": (["package.json"], []),
    "python": (["requirements.txt", "pyproject.toml", "setup.py", "Pipfile", "manage.py", "uv.lock"], []),
    "php": (["composer.json", "artisan"], []),
    "ruby": (["Gemfile"], []),
    "dotnet": (["global.json"], ["*.csproj", "*.fsproj", "*.vbproj", "*.sln"]),
    "java": (["pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts",
              "mvnw", "gradlew"], []),
}
# Opt-in (--commit), never part of --project: git push and gh pr create reach GitHub.
COMMIT_RULES = [
    "Bash(git add *)",
    "Bash(git commit *)",
    "Bash(git push -u origin HEAD)",
    "Bash(gh pr create *)",
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


def local_roots(home, config_dir):
    """Plugin folders of a proofs marketplace added from a local folder.

    Claude Code runs such a plugin from that folder, not from plugins/cache, so the cache
    rules never match its commands."""
    base = Path(config_dir) if config_dir else Path(home) / ".claude"
    try:
        known = json.loads((base / "plugins" / "known_marketplaces.json").read_text())
    except (OSError, ValueError):
        return []
    roots = []
    for entry in known.values() if isinstance(known, dict) else []:
        source = entry.get("source") if isinstance(entry, dict) else None
        if not isinstance(source, dict) or source.get("source") != "directory" or not source.get("path"):
            continue
        folder = Path(source["path"])
        # Only a marketplace that lists a plugin named proofs; an unreadable one is skipped,
        # so an unrelated local marketplace never gets proofs rules.
        try:
            plugins = json.loads((folder / ".claude-plugin" / "marketplace.json").read_text()).get("plugins", [])
        except (OSError, ValueError, AttributeError):
            continue
        if not isinstance(plugins, list):
            continue
        sub = next((p.get("source") for p in plugins if isinstance(p, dict) and p.get("name") == "proofs"), None)
        if not isinstance(sub, str):
            continue
        root = os.path.normpath(str(folder / sub))
        if root not in roots:
            roots.append(root)
    return roots


def folder_rules(root, headless=False):
    """Read and Bash rules for a plugin run from a local folder (no version folder)."""
    root = root.rstrip("/")
    bash = sorted("Bash(%s %s/%s *)" % (interp, root, path) for interp, path in scripts())
    extra = ["Bash(%s %s/%s *)" % (HEADLESS_SCRIPT[0], root, HEADLESS_SCRIPT[1])] if headless else []
    return ["Read(/%s/**)" % root] + bash + extra


def detect_stacks(folder):
    """The stacks whose marker files are in folder (not its subfolders), in STACKS order."""
    folder = Path(folder)
    found = []
    for stack in STACKS:
        names, globs = STACK_MARKERS[stack]
        if any((folder / n).exists() for n in names) or any(next(folder.glob(g), None) for g in globs):
            found.append(stack)
    return found


def project_rules(stacks):
    """The named stacks' rules in STACKS order, then the rules every stack shares."""
    return [r for s in STACKS if s in stacks for r in STACK_RULES[s]] + list(PROJECT_RULES)


def _take_stack(args):
    """Split --stack NAME / --stack=NAME out of args: (other args, [names] or None, ok)."""
    rest, names, ok = [], None, True
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--stack" or a.startswith("--stack="):
            if a == "--stack":
                value = args[i + 1] if i + 1 < len(args) else ""
                i += 1
            else:
                value = a[len("--stack="):]
            parts = value.split(",")
            if names is not None or not value or not all(p in STACKS for p in parts):
                ok = False
            names = parts
        else:
            rest.append(a)
        i += 1
    return rest, names, ok


def main(argv):
    args, stacks, ok = _take_stack(argv[1:])
    if (not ok or len(set(args)) != len(args) or not set(args) <= {"--lines", "--headless", "--project", "--commit"}
            or (stacks is not None and "--project" not in args)):
        print(__doc__.strip(), file=sys.stderr)
        return 0 if args in (["-h"], ["--help"]) else 2
    if "--project" in args and stacks is None:
        stacks = detect_stacks(os.getcwd())
        if not stacks:
            # As before 1.6.0, so nobody upgrading loses rules: npm, then the shared ones.
            stacks = ["node"]
            print("allow_block: no project marker file here (package.json, requirements.txt, composer.json, "
                  "Gemfile, *.csproj, pom.xml, ...), so the node (npm) rules are printed, as before. Run it in "
                  "the project folder, or name the toolchain with --stack (one of: %s)." % ", ".join(STACKS),
                  file=sys.stderr)
    project = project_rules(stacks) if "--project" in args else []
    home = os.environ.get("HOME") or str(Path.home())
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR") or None
    if config_dir:
        config_dir = os.path.abspath(os.path.expanduser(config_dir))
    if "--headless" not in args and ("--project" in args or "--commit" in args):
        allow = list(project)
    else:
        allow = rules(home, config_dir, headless="--headless" in args)
        for root in local_roots(home, config_dir):
            allow += folder_rules(root, headless="--headless" in args)
        allow += project
    if "--commit" in args:
        allow += COMMIT_RULES
    if "--lines" in args:
        print(",\n".join(json.dumps(r) for r in allow))
    else:
        print(json.dumps({"permissions": {"allow": allow}}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
