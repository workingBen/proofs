import importlib.machinery
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
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

    def test_headless_adds_exactly_the_capture_helper(self):
        plain = allow_block.rules("/opt/claude-home", None)
        headless = allow_block.rules("/opt/claude-home", None, headless=True)
        extra = [r for r in headless if r not in plain]
        self.assertEqual(headless[:len(plain)], plain)
        self.assertEqual(extra, ["Bash(python3 /opt/claude-home/.claude/plugins/cache/proofs/proofs/*/shared/capture/with_server.py *)"])
        cmd = "python3 %s/shared/capture/with_server.py --start x --url y -- z" % FAKE_VERSION_ROOT
        self.assertTrue(check_skills.rule_matches(extra[0], cmd))
        self.assertFalse(any(check_skills.rule_matches(r, cmd) for r in plain))

    def test_headless_follows_claude_config_dir(self):
        self.assertEqual(allow_block.rules("/opt/claude-home", "/opt/cfg", headless=True)[-1],
                         "Bash(python3 /opt/cfg/plugins/cache/proofs/proofs/*/shared/capture/with_server.py *)")

    def test_capture_helper_is_never_in_the_default_output(self):
        self.assertIn("shared/capture/with_server.py", check_skills.NEVER_PREAPPROVED)
        for config_dir in (None, "/opt/cfg"):
            self.assertFalse(any("with_server.py" in r for r in allow_block.rules("/opt/claude-home", config_dir)))
        r = self._cli("/opt/claude-home")
        self.assertNotIn("with_server.py", r.stdout)
        self.assertFalse(any("with_server.py" in r for r in readme_block()["permissions"]["allow"]))

    def test_cli_headless_flag_works_with_and_without_lines(self):
        r = self._cli("/opt/claude-home", None, "--headless")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["permissions"]["allow"], allow_block.rules("/opt/claude-home", None, headless=True))
        r = self._cli("/opt/claude-home", None, "--lines", "--headless")
        self.assertEqual(json.loads("[" + r.stdout + "]"), allow_block.rules("/opt/claude-home", None, headless=True))

    def test_project_flag_prints_only_the_project_rules(self):
        r = self._cli("/opt/claude-home", None, "--project")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {"permissions": {"allow": allow_block.PROJECT_RULES}})
        r = self._cli("/opt/claude-home", None, "--lines", "--project")
        self.assertEqual(json.loads("[" + r.stdout + "]"), allow_block.PROJECT_RULES)
        self.assertNotIn("/opt/claude-home", r.stdout)

    def test_project_rules_are_never_in_the_default_or_headless_output(self):
        for headless in (False, True):
            plain = allow_block.rules("/opt/claude-home", None, headless=headless)
            self.assertFalse(set(plain) & set(allow_block.PROJECT_RULES))
        self.assertFalse(set(readme_block()["permissions"]["allow"]) & set(allow_block.PROJECT_RULES))

    def test_project_and_headless_combine_into_one_block(self):
        r = self._cli("/opt/claude-home", None, "--project", "--headless")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["permissions"]["allow"],
                         allow_block.rules("/opt/claude-home", None, headless=True) + allow_block.PROJECT_RULES)

    def test_project_rules_cover_the_pr_qa_commands(self):
        for cmd in ("printenv PROOFS_BASE_DIR", "gh pr checkout 7", "gh pr list --state open", "cp .env .proofs/base/web/.env",
                    "git worktree add --detach .proofs/base main", "git worktree add --detach .proofs/base fix-nav"):
            self.assertTrue(check_skills.claude_code_allows(allow_block.PROJECT_RULES, cmd), cmd)
        # Final review I2: the local-branch after shot uses a worktree; nothing switches the developer's checkout.
        for cmd in ("git switch fix-nav", "git switch -f main", "git switch --discard-changes main"):
            self.assertFalse(check_skills.claude_code_allows(allow_block.PROJECT_RULES, cmd), cmd)
        self.assertFalse(check_skills.claude_code_allows(allow_block.PROJECT_RULES, "cp .env /opt/claude-home/base/web/.env"))

    def test_readme_offers_the_project_block_labeled_and_apart(self):
        text = (REPO / "README.md").read_text()
        section = text[text.index("<!-- allow-proofs:start -->"):text.index("<!-- allow-proofs:end -->")]
        self.assertIn("Allow your project's commands too (optional", section)
        self.assertIn("--project", section)
        self.assertGreater(section.index("--project"), section.index("--headless"))
        self.assertIn("npm install", section)
        self.assertIn("package scripts", section)
        self.assertIn(".claude/settings.local.json", section.split("Allow your project's commands too")[1])
        self.assertIn("no home path", section.split("Allow your project's commands too")[1])

    def test_readme_states_the_one_command_per_call_rule(self):
        text = (REPO / "README.md").read_text()
        self.assertIn("one command per Bash call", text)
        self.assertNotIn("that script alone", text)

    def test_usage_line_shows_headless_and_project_combine(self):
        usage = next(l for l in allow_block.__doc__.splitlines() if "allow_block.py [" in l)
        self.assertIn("[--headless]", usage)
        self.assertIn("[--project]", usage)
        self.assertIn("[--commit]", usage)
        self.assertNotIn("|", usage)

    def test_project_allows_opening_pages(self):
        self.assertIn("Bash(open .proofs/pages/*)", allow_block.PROJECT_RULES)
        self.assertIn("Bash(xdg-open .proofs/pages/*)", allow_block.PROJECT_RULES)
        for cmd in ("open .proofs/pages/review.html", "xdg-open .proofs/pages/review.html"):
            self.assertTrue(check_skills.claude_code_allows(allow_block.PROJECT_RULES, cmd), cmd)
        r = self._cli("/opt/claude-home", None, "--project")
        self.assertIn("Bash(open .proofs/pages/*)", json.loads(r.stdout)["permissions"]["allow"])

    def test_commit_block_alone(self):
        self.assertEqual(allow_block.COMMIT_RULES, ["Bash(git add *)", "Bash(git commit *)",
                                                    "Bash(git push -u origin HEAD)", "Bash(gh pr create *)"])
        r = self._cli("/opt/claude-home", None, "--commit")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {"permissions": {"allow": allow_block.COMMIT_RULES}})
        self.assertNotIn("/opt/claude-home", r.stdout)
        self.assertFalse(set(allow_block.COMMIT_RULES) & set(allow_block.PROJECT_RULES))

    def test_commit_combines(self):
        r = self._cli("/opt/claude-home", None, "--project", "--commit")
        self.assertEqual(r.returncode, 0, r.stderr)
        allow = json.loads(r.stdout)["permissions"]["allow"]
        self.assertEqual(allow, allow_block.PROJECT_RULES + allow_block.COMMIT_RULES)
        r = self._cli("/opt/claude-home", None, "--headless", "--project", "--commit")
        self.assertEqual(r.returncode, 0, r.stderr)
        allow = json.loads(r.stdout)["permissions"]["allow"]
        self.assertEqual(allow, allow_block.rules("/opt/claude-home", None, headless=True)
                         + allow_block.PROJECT_RULES + allow_block.COMMIT_RULES)
        self.assertEqual(len(allow), len(set(allow)))

    def test_unknown_flag_still_rejected(self):
        self.assertEqual(self._cli("/opt/claude-home", None, "--commit", "--everything").returncode, 2)
        self.assertEqual(self._cli("/opt/claude-home", None, "--commit", "--commit").returncode, 2)

    def test_cli_rejects_unknown_flags(self):
        self.assertEqual(self._cli("/opt/claude-home", None, "--everything").returncode, 2)

    def test_readme_offers_the_headless_line_labeled_and_apart(self):
        text = (REPO / "README.md").read_text()
        section = text[text.index("<!-- allow-proofs:start -->"):text.index("<!-- allow-proofs:end -->")]
        self.assertIn("For unattended (`claude -p`) runs only", section)
        self.assertIn("--headless", section)
        self.assertGreater(section.index("--headless"), section.index("```json"))
        self.assertIn("`with_server.py`", section.split("still ask every time")[1].split("\n")[0])
        self.assertIn("custom `CLAUDE_CONFIG_DIR`, put the rules in that folder's `settings.json`", section)

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

    def _known(self, config, marketplaces):
        (Path(config) / "plugins").mkdir(parents=True, exist_ok=True)
        (Path(config) / "plugins" / "known_marketplaces.json").write_text(json.dumps(marketplaces))

    def _local_marketplace(self, config, name, plugins):
        """A local-folder marketplace under config/<name>; plugins=None leaves out marketplace.json."""
        folder = Path(config) / name
        (folder / ".claude-plugin").mkdir(parents=True)
        if plugins is not None:
            (folder / ".claude-plugin" / "marketplace.json").write_text(json.dumps({"name": name, "plugins": plugins}))
        return str(folder)

    def _allow(self, config, *args):
        r = self._cli("/opt/claude-home", config, *args)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["permissions"]["allow"]

    def test_directory_marketplace_adds_rules_for_its_source_folder(self):
        # A marketplace added from a local folder runs the plugin from that folder, not the cache:
        # the 2026-11-22 headless check had with_server.py denied for exactly this reason.
        with tempfile.TemporaryDirectory() as config:
            root = self._local_marketplace(config, "proofs", [{"name": "proofs", "source": "./"}])
            self._known(config, {"proofs": {"source": {"source": "directory", "path": root}}})
            allow = self._allow(config, "--headless")
            base = allow_block.rules("/opt/claude-home", config, headless=True)
        cmd = ("python3 %s/shared/capture/with_server.py --start \"python3 -m http.server 3411\" "
               "--url http://localhost:3411/ -- node %s/skills/visual-qa/scripts/capture.cjs "
               ".proofs/capture/pages.json --out .proofs/evidence/pr-1 --sizes 390,1440 --evidence before" % (root, root))
        self.assertTrue(check_skills.claude_code_allows(allow, cmd), allow)
        self.assertIn("Read(/%s/**)" % root, allow)
        self.assertEqual(allow[:len(base)], base)

    def test_directory_rules_follow_the_headless_flag(self):
        with tempfile.TemporaryDirectory() as config:
            root = self._local_marketplace(config, "proofs", [{"name": "proofs", "source": "./"}])
            self._known(config, {"proofs": {"source": {"source": "directory", "path": root}}})
            allow = self._allow(config)
        self.assertFalse(any(root + "/shared/capture/with_server.py" in r for r in allow), allow)
        self.assertIn("Bash(python3 %s/skills/pr-qa/scripts/pr_qa_page.py *)" % root, allow)

    def test_a_github_marketplace_adds_no_folder_rules(self):
        with tempfile.TemporaryDirectory() as config:
            self._known(config, {"proofs": {"source": {"source": "github", "repo": "workingBen/proofs"}}})
            allow = self._allow(config, "--headless")
            base = allow_block.rules("/opt/claude-home", config, headless=True)
        self.assertEqual(allow, base)

    def test_a_directory_marketplace_without_proofs_adds_no_rules(self):
        # Final review I1: an unrelated local marketplace got a full set of proofs rules.
        with tempfile.TemporaryDirectory() as config:
            other = self._local_marketplace(config, "tap-to-fix", [{"name": "tap-to-fix", "source": "./"}])
            self._known(config, {"tap-to-fix": {"source": {"source": "directory", "path": other}}})
            allow = self._allow(config, "--headless", "--project")
            base = allow_block.rules("/opt/claude-home", config, headless=True) + allow_block.PROJECT_RULES
        self.assertEqual(allow, base)
        self.assertFalse(any(other in r for r in allow), allow)

    def test_unreadable_marketplace_json_adds_no_rules(self):
        with tempfile.TemporaryDirectory() as config:
            missing = self._local_marketplace(config, "proofs", None)
            self._known(config, {"proofs": {"source": {"source": "directory", "path": missing}}})
            allow = self._allow(config, "--headless")
            base = allow_block.rules("/opt/claude-home", config, headless=True)
        self.assertEqual(allow, base)

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
