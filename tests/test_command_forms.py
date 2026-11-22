"""Every example command in every skill must be allowed by the rules Proofs prints.

The matcher (check_skills.claude_code_allows) is a deliberately strict model of Claude
Code's Bash permission matching: stricter on purpose, never looser. A command it accepts
must be accepted by Claude Code. Do not loosen it to make a skill pass; fix the skill.
"""
import importlib.machinery
import importlib.util
import re
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "shared"))
sys.path.insert(0, str(REPO / "shared" / "review_page"))
import allow_block  # noqa: E402

_loader = importlib.machinery.SourceFileLoader("check_skills", str(REPO / "bin" / "check-skills"))
_spec = importlib.util.spec_from_loader("check_skills", _loader)
check_skills = importlib.util.module_from_spec(_spec)
_loader.exec_module(check_skills)

HOME = "/opt/claude-home"
VERSION_ROOT = HOME + "/.claude/plugins/cache/proofs/proofs/1.9.9"
FIRST_WORDS = {"python3", "node", "npm", "npx", "git"}
CHROME = re.compile(r"/(?:Applications|usr|opt)/\S*(?:Chrome|chrome)\S*")
FENCE = re.compile(r"^\s*```(\S*)\s*$")


def all_rules():
    return allow_block.rules(HOME, None, headless=True) + allow_block.PROJECT_RULES


def allowed(cmd):
    return check_skills.claude_code_allows(all_rules(), cmd)


def substitute(line):
    line = line.replace("${CLAUDE_PLUGIN_ROOT}", VERSION_ROOT).replace("<plugin root>", VERSION_ROOT)
    for key, value in (("<base>", "main"), ("<app-dir>", "web"), ("<n>", "7"), ("<base-dir>", ".proofs/base")):
        line = line.replace(key, value)
    return re.sub(r"<[^<>\n]+>", "x", line)


def example_commands():
    """(file, command) for every example command line in a fenced block, continuations joined."""
    files = sorted((REPO / "skills").glob("*/SKILL.md")) + sorted((REPO / "reference").glob("*.md"))
    out = []
    for path in files:
        fence, pending = None, ""
        for raw in path.read_text().splitlines():
            m = FENCE.match(raw)
            if m:
                fence = None if fence is not None else (m.group(1) or "plain")
                pending = ""
                continue
            if fence is None or fence == "text":
                continue
            line = raw.strip()
            if pending:
                line = pending + " " + line
            if line.endswith("\\"):
                pending = line[:-1].rstrip()
                continue
            pending = ""
            words = line.split()
            if not words or not (words[0] in FIRST_WORDS or CHROME.fullmatch(words[0])):
                continue
            cmd = substitute(line)
            if any(name in cmd for name in check_skills.NEVER_PREAPPROVED if "with_server" not in name):
                continue
            out.append((path.relative_to(REPO).as_posix(), cmd))
    return out


class CommandFormsTest(unittest.TestCase):
    def test_every_example_command_is_allowed(self):
        found = example_commands()
        self.assertGreater(len(found), 10)
        for rel, cmd in found:
            with self.subTest(file=rel, command=cmd):
                why = check_skills.why_not_allowed(all_rules(), cmd)
                self.assertIsNone(why, "%s: %s\n  %s" % (rel, why, cmd))

    def test_matcher_rejects_the_forms_that_failed_in_run_2b(self):
        wp = HOME + "/.claude/plugins/cache/proofs/proofs/1.4.1/shared/capture/with_server.py"
        for cmd in (
            "git worktree add nextjs/.proofs/base origin/main | tail -1",
            "cd .proofs/base/nextjs && npm ci --no-audit --no-fund",
            "R=$(pwd); python3 %s --cwd $R/.proofs/base/nextjs --start x --url y -- z" % wp,
            "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm install --prefix ~/.cache/proofs-playwright playwright@1.61.1",
            'git check-ignore -q nextjs/.proofs/ || echo ".proofs/" >> "$(git rev-parse --git-path info/exclude)"',
            "npm ci 2>&1",
            "npm ci &> out.log",
            "git fetch origin > out.txt",
            "npm install `pwd`",
            "git fetch origin; ls",
            "npm install\nls",
        ):
            with self.subTest(command=cmd):
                self.assertFalse(allowed(cmd))

    def test_matcher_accepts_the_new_forms(self):
        capture = ("python3 %s/shared/capture/with_server.py --start \"npm run dev -- -p 3311\" "
                   "--url http://localhost:3311/ -- node %s/skills/visual-qa/scripts/capture.cjs "
                   ".proofs/visual-qa/pages.json --out .proofs/visual-qa/before" % (VERSION_ROOT, VERSION_ROOT))
        for cmd in (
            capture,
            "npm install --prefix ~/.cache/proofs-playwright playwright@1.61.1",
            "git worktree add .proofs/base origin/main",
            "npm ci --prefix .proofs/base/web",
            "git worktree remove --force .proofs/base",
        ):
            with self.subTest(command=cmd):
                self.assertTrue(allowed(cmd), cmd)

    def test_matcher_is_stricter_than_rule_matching_alone(self):
        rule = "Bash(npm install)"
        self.assertTrue(check_skills.rule_matches(rule, "npm install"))
        self.assertTrue(check_skills.claude_code_allows([rule], "npm install"))
        self.assertFalse(check_skills.claude_code_allows([rule], "npm install && npm install"))
        # Quoted operator characters are one argument, not a shell operator.
        self.assertTrue(check_skills.claude_code_allows(["Bash(git worktree add *)"], 'git worktree add "a|b" x'))
        self.assertFalse(check_skills.claude_code_allows(["Bash(git worktree add *)"], 'git worktree add "$(pwd)" x'))
        self.assertFalse(check_skills.claude_code_allows([rule], "cd x"))

    def test_project_rules_hold_no_home_path(self):
        for rule in allow_block.PROJECT_RULES:
            with self.subTest(rule=rule):
                self.assertFalse(re.search(r"(?<![~\w.])/(?:Users|home|root|opt)/", rule), rule)
                self.assertNotIn("claude-home", rule)
                self.assertNotIn(HOME, rule)
        self.assertIn("Bash(npm install --prefix ~/.cache/proofs-playwright playwright@1.61.1)",
                      allow_block.PROJECT_RULES)

    def test_project_rules_never_run_arbitrary_commands(self):
        for rule in allow_block.PROJECT_RULES:
            with self.subTest(rule=rule):
                self.assertNotIn("with_server.py", rule)
                self.assertNotIn("npm run", rule)
                self.assertNotIn("npx *", rule)
                self.assertNotIn("sh -c", rule)
                self.assertTrue(rule.startswith("Bash(") and rule.endswith(")"))
                body = rule[len("Bash("):-1]
                self.assertNotEqual(body.strip(), "*")
                self.assertFalse(body.startswith("*"))
                self.assertFalse(body.endswith("npm *") or body.endswith("git *"), rule)

    def test_helpers_print_install_lines_that_are_allowed(self):
        how_to_js = subprocess.run(
            ["node", "-p", "require(%r).HOW_TO" % str(REPO / "shared" / "review_page" / "launch.cjs")],
            capture_output=True, text=True)
        self.assertEqual(how_to_js.returncode, 0, how_to_js.stderr)
        import review_page  # noqa: E402
        for label, text in (("launch.cjs HOW_TO", how_to_js.stdout), ("review_page HOW_TO_PY", review_page.HOW_TO_PY)):
            with self.subTest(label):
                m = re.search(r"npm install [^\n]*", text)
                self.assertTrue(m, text)
                self.assertTrue(allowed(m.group(0).strip()), m.group(0))


if __name__ == "__main__":
    unittest.main()
