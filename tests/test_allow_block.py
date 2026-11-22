import importlib.machinery
import importlib.util
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "shared"))
import allow_block  # noqa: E402

_loader = importlib.machinery.SourceFileLoader("check_skills", str(REPO / "bin" / "check-skills"))
_spec = importlib.util.spec_from_loader("check_skills", _loader)
check_skills = importlib.util.module_from_spec(_spec)
_loader.exec_module(check_skills)

ROOT = "${CLAUDE_PLUGIN_ROOT}"
README_HOME = "/YOUR/HOME"
FAKE_VERSION_ROOT = "/opt/claude-home/.claude/plugins/cache/proofs/proofs/1.2.0"


def skill_files():
    return sorted((REPO / "skills").glob("*/SKILL.md"))


def declared_scripts():
    """Every script a skill's allowed-tools pre-approves, as a path from the plugin root."""
    out = set()
    for path in skill_files():
        for r in check_skills.allowed_tools(path.read_text()):
            m = re.fullmatch(r"Bash\((?:python3|node) " + re.escape(ROOT) + r"/(\S+) \*\)", r)
            if m:
                out.add(m.group(1))
    return out


def skills_with_allowed_tools():
    return {p.parent.name for p in skill_files() if check_skills.allowed_tools(p.read_text())}


def rule_scripts(rules):
    out = set()
    for r in rules:
        m = re.fullmatch(r"Bash\((?:python3|node) \S+/plugins/cache/proofs/proofs/\*/(\S+) \*\)", r)
        if m:
            out.add(m.group(1))
    return out


def readme_block():
    text = (REPO / "README.md").read_text()
    m = re.search(r"<!-- allow-proofs:start -->(.*?)<!-- allow-proofs:end -->", text, re.S)
    assert m, "README has no allow-proofs markers"
    j = re.search(r"```json\n(.*?)\n```", m.group(1), re.S)
    assert j, "allow-proofs section has no json block"
    return json.loads(j.group(1))


class AllowBlockTest(unittest.TestCase):
    def test_rules_cover_every_preapproved_script(self):
        scripts = declared_scripts()
        self.assertTrue(scripts)
        self.assertEqual(rule_scripts(allow_block.rules("/opt/claude-home", None)), scripts)

    def test_no_rule_covers_a_keep_asking_script(self):
        rules = allow_block.rules("/opt/claude-home", None)
        for name in check_skills.NEVER_PREAPPROVED:
            self.assertFalse(any(name in r for r in rules), name)

    def test_read_rule_uses_tilde_by_default(self):
        self.assertEqual(allow_block.rules("/opt/claude-home", None)[0], "Read(~/.claude/plugins/cache/proofs/**)")

    def test_config_dir_makes_an_absolute_read_rule(self):
        rules = allow_block.rules("/opt/claude-home", "/opt/cfg")
        self.assertEqual(rules[0], "Read(//opt/cfg/plugins/cache/proofs/**)")
        self.assertTrue(all("/opt/cfg/plugins/cache/proofs/proofs/*/" in r for r in rules if r.startswith("Bash(")))

    def test_skill_rule_covers_every_gated_skill(self):
        rules = allow_block.rules("/opt/claude-home", None)
        skill_rules = [r for r in rules if r.startswith("Skill(")]
        self.assertTrue(skill_rules)
        for name in skills_with_allowed_tools():
            self.assertTrue(any(r in ("Skill(proofs:*)", "Skill(proofs:%s)" % name) for r in skill_rules), name)

    def test_version_folder_is_a_wildcard(self):
        bash = [r for r in allow_block.rules("/opt/claude-home", None) if r.startswith("Bash(")]
        self.assertTrue(bash)
        for r in bash:
            self.assertIn("/plugins/cache/proofs/proofs/*/", r)
            self.assertEqual(r.count("*"), 2, r)

    def test_bash_rules_are_sorted(self):
        bash = [r for r in allow_block.rules("/opt/claude-home", None) if r.startswith("Bash(")]
        self.assertEqual(bash, sorted(bash))

    def test_rules_match_the_commands_skills_write(self):
        rules = [r for r in allow_block.rules("/opt/claude-home", None) if r.startswith("Bash(")]
        seen = 0
        for path in skill_files():
            for cm in check_skills.PLUGIN_CMD.finditer(path.read_text()):
                interp, flags, _quote, target = cm.groups()
                if not target.startswith(ROOT + "/"):
                    continue
                if target[len(ROOT) + 1:] in check_skills.NEVER_PREAPPROVED:
                    continue
                cmd = ("%s%s %s --out page.html" % (interp, flags, target)).replace(ROOT, FAKE_VERSION_ROOT)
                seen += 1
                self.assertTrue(any(check_skills.rule_matches(r, cmd) for r in rules), cmd)
        self.assertGreater(seen, 0)

    def test_rules_do_not_match_other_commands(self):
        rules = [r for r in allow_block.rules("/opt/claude-home", None) if r.startswith("Bash(")]
        for cmd in ("python3 /opt/claude-home/.claude/plugins/cache/proofs/proofs/1.2.0/skills/todos/scripts/todos_apply.py x",
                    "python3 /opt/claude-home/evil.py",
                    "python3 -c print(1)"):
            self.assertFalse(any(check_skills.rule_matches(r, cmd) for r in rules), cmd)

    def test_readme_example_matches_the_generator_with_a_placeholder_home(self):
        self.assertEqual(readme_block(), {"permissions": {"allow": allow_block.rules(README_HOME, None)}})

    def test_readme_has_no_tilde_bash_rule(self):
        self.assertFalse(any(r.startswith("Bash(") and "~" in r for r in readme_block()["permissions"]["allow"]))

    def test_readme_command_comes_before_the_example(self):
        text = (REPO / "README.md").read_text()
        section = text[text.index("<!-- allow-proofs:start -->"):]
        self.assertLess(section.index("allow_block.py"), section.index("```json"))

    def test_readme_command_honors_claude_config_dir(self):
        text = (REPO / "README.md").read_text()
        self.assertIn('"${CLAUDE_CONFIG_DIR:-$HOME/.claude}"/plugins/cache/proofs/proofs/*/', text)

    def _cli(self, home, config_dir=None, *args):
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CONFIG_DIR"}
        env["HOME"] = home
        if config_dir:
            env["CLAUDE_CONFIG_DIR"] = config_dir
        return subprocess.run([sys.executable, str(REPO / "shared" / "allow_block.py"), *args],
                              capture_output=True, text=True, env=env)

    def test_cli_prints_the_block_for_this_home(self):
        r = self._cli("/opt/claude-home")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {"permissions": {"allow": allow_block.rules("/opt/claude-home", None)}})
        self.assertEqual(r.stderr, "")

    def test_cli_uses_claude_config_dir(self):
        r = self._cli("/opt/claude-home", "/opt/cfg")
        self.assertEqual(json.loads(r.stdout)["permissions"]["allow"][0], "Read(//opt/cfg/plugins/cache/proofs/**)")

    def test_lines_prints_items_to_merge_into_an_existing_allow_list(self):
        r = self._cli("/opt/claude-home", None, "--lines")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("permissions", r.stdout)
        self.assertEqual(json.loads("[" + r.stdout + "]"), allow_block.rules("/opt/claude-home", None))


if __name__ == "__main__":
    unittest.main()
