import importlib.machinery
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CHECK = Path(__file__).resolve().parent.parent / "bin" / "check-skills"

GOOD = """---
name: {name}
description: Use when something happens.
version: 1.2.0
---

# {name}

{body}
"""
LOG = "# Changelog\n\n- **1.2.0** (2026-01-01): first merged version.\n"
REF = "# Where the page goes\n\nSet `PROOFS_PAGES` to artifact, file or wifi.\n"


class CheckBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.skills = Path(self._tmp.name) / "skills"
        self.skills.mkdir()
        self.ref = Path(self._tmp.name) / "reference" / "where-the-page-goes.md"
        self.ref.parent.mkdir()
        self.ref.write_text(REF)

    def skill(self, folder, text=None, name=None, body="", log=LOG):
        d = self.skills / folder
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(text if text is not None else GOOD.format(name=name or folder, body=body))
        if log is None:
            (d / "CHANGELOG.md").unlink(missing_ok=True)
        else:
            (d / "CHANGELOG.md").write_text(log)

    def run_check(self):
        return subprocess.run([sys.executable, str(CHECK), str(self.skills)],
                              capture_output=True, text=True)



class CheckCase(CheckBase):
    def test_good_skill_passes(self):
        self.skill("alpha")
        r = self.run_check()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_empty_skills_dir_fails(self):
        r = self.run_check()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no skills found", r.stdout + r.stderr)

    def test_missing_skills_dir_fails(self):
        self.skills.rmdir()
        r = self.run_check()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no skills found", r.stdout + r.stderr)

    def test_name_matches_folder(self):
        self.skill("alpha", name="beta")
        r = self.run_check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("name", r.stdout)

    def test_description_starts_use_when(self):
        self.skill("alpha", text=GOOD.format(name="alpha", body="").replace("Use when something", "Does something"))
        r = self.run_check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("description", r.stdout)

    def test_semver_and_changelog_required(self):
        base = GOOD.format(name="alpha", body="")
        self.skill("alpha", text=base.replace("version: 1.2.0", "version: 1.2"))
        self.assertEqual(self.run_check().returncode, 1)
        self.skill("alpha", log=None)
        r = self.run_check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("missing CHANGELOG.md", r.stdout)
        self.skill("alpha", log=LOG.replace("1.2.0", "0.9.0"))
        r = self.run_check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("changelog", r.stdout.lower())

    def test_changelog_section_in_skill_md_rejected(self):
        self.skill("alpha", body="## Changelog\n\n- **1.2.0**: x\n")
        r = self.run_check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("belongs in CHANGELOG.md", r.stdout)

    def test_bare_script_path_rejected(self):
        self.skill("alpha", body="Run `scripts/capture.cjs` now.")
        self.assertEqual(self.run_check().returncode, 1)
        self.skill("alpha", body="Run `node scripts/capture.cjs` now.")
        r = self.run_check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("run plugin scripts through ${CLAUDE_PLUGIN_ROOT}", r.stdout)

    def test_skill_references_resolve(self):
        self.skill("alpha", body="This needs the `beta` skill first.")
        r = self.run_check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("beta", r.stdout)
        self.skill("beta")
        r = self.run_check()
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_relative_paths_need_the_whole_plugin_line(self):
        self.skill("alpha", body="Read `../../reference/where-the-page-goes.md` first.")
        r = self.run_check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("Needs the whole plugin", r.stdout)
        self.skill("alpha", body="**Needs the whole plugin.** Install it.\n\nRead `../../reference/where-the-page-goes.md` first.")
        self.assertEqual(self.run_check().returncode, 0, self.run_check().stdout)

    def test_other_plugin_references_ignored(self):
        self.skill("alpha", body="Use the `superpowers:brainstorming` skill.")
        self.assertEqual(self.run_check().returncode, 0)

    def test_proofs_namespace_references(self):
        self.skill("alpha", body="Needs the `proofs:beta` skill.")
        r = self.run_check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("beta", r.stdout)
        self.skill("beta")
        self.assertEqual(self.run_check().returncode, 0)

    def test_slash_and_capital_skill_forms(self):
        self.skill("alpha", body="Run /proofs:gamma first. Then the `delta` Skill.")
        r = self.run_check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("gamma", r.stdout)
        self.assertIn("delta", r.stdout)
        self.skill("gamma")
        self.skill("delta")
        self.assertEqual(self.run_check().returncode, 0)

    def test_bare_slash_commands_and_paths(self):
        self.skill("alpha", body="Run /epsilon now.")
        self.assertEqual(self.run_check().returncode, 1)
        self.skill("alpha", body="Use /clear, a/b, https://x.dev/page and /usr/bin.")
        self.assertEqual(self.run_check().returncode, 0, self.run_check().stdout)

    def test_html_closing_tags_and_code_fences_ignored(self):
        body = ("Click <button>Go</button> or <div>x</div> then.\n\n"
                "```\n/epsilon here\nrun /zeta\n```\n")
        self.skill("alpha", body=body)
        r = self.run_check()
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_fence_toggle_resets_and_tilde_fences_ignored(self):
        body = "```\n/inside\n```\n\nthen run /missing now.\n"
        self.skill("alpha", body=body)
        r = self.run_check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("missing", r.stdout)
        self.assertNotIn("inside", r.stdout)
        self.skill("alpha", body="~~~\n/inside\n~~~\n")
        self.assertEqual(self.run_check().returncode, 0, self.run_check().stdout)

    PAGES = ("**Needs the whole plugin.** Install it.\n\n## Where the page goes\n\nRead `../../reference/where-the-page-goes.md` before publishing.\n")

    def test_page_skills_need_where_the_page_goes(self):
        self.skill("design-review")
        r = self.run_check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("Where the page goes", r.stdout)

    def test_page_section_must_point_to_reference(self):
        self.skill("design-review", body="## Where the page goes\n\nartifact, file or wifi.\n")
        r = self.run_check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("must point to", r.stdout)

    def test_reference_must_name_all_three_values(self):
        self.ref.write_text("artifact or file only.\n")
        self.skill("design-review", body=self.PAGES)
        r = self.run_check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("wifi", r.stdout)

    def test_missing_reference_file_fails(self):
        self.ref.unlink()
        self.skill("design-review", body=self.PAGES)
        r = self.run_check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("does not exist", r.stdout)

    def test_plugin_root_paths_must_exist(self):
        self.skill("alpha", body="**Needs the whole plugin.**\n\nRead `../../shared/missing.py` first.")
        r = self.run_check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("../../shared/missing.py", r.stdout)
        (Path(self._tmp.name) / "shared").mkdir()
        (Path(self._tmp.name) / "shared" / "missing.py").write_text("")
        self.assertEqual(self.run_check().returncode, 0, self.run_check().stdout)

    def test_skill_reference_files_must_exist(self):
        self.skill("alpha", body="Read `reference/checkpoints.md` when a trigger fires.")
        r = self.run_check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("reference/checkpoints.md", r.stdout)
        (self.skills / "alpha" / "reference").mkdir()
        (self.skills / "alpha" / "reference" / "checkpoints.md").write_text("# x\n")
        self.assertEqual(self.run_check().returncode, 0, self.run_check().stdout)

    def test_page_skills_with_section_pass_and_others_exempt(self):
        self.skill("design-review", body=self.PAGES)
        self.skill("changelog")
        r = self.run_check()
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_section_heading_inside_code_fence_ignored(self):
        self.skill("design-review", body="```\n" + self.PAGES + "```\n")
        r = self.run_check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("missing '## Where the page goes'", r.stdout)

    def test_section_text_identical_across_page_skills(self):
        self.skill("design-review", body=self.PAGES)
        self.skill("todos", body=self.PAGES)
        self.skill("pr-qa", body=self.PAGES.replace("Read", "Open"))
        r = self.run_check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("pr-qa", r.stdout)
        self.assertIn("differs", r.stdout)
        self.assertNotIn("design-review: ", r.stdout)
        self.assertNotIn("todos: ", r.stdout)
        self.skill("pr-qa", body=self.PAGES)
        self.assertEqual(self.run_check().returncode, 0, self.run_check().stdout)

    def test_interpreter_flags_quotes_and_nested_paths_allowed(self):
        body = ("Run `python3 -I scripts/x.py`, `node --check scripts/x.cjs`, "
                "`python3 \"scripts/x.py\"` and `python3 scripts/sub/x.py`.")
        self.skill("alpha", body=body)
        r = self.run_check()
        self.assertNotIn("must run through python3 or node", r.stdout)

    def test_bare_nested_and_flagged_paths_still_rejected(self):
        self.skill("alpha", body="Run `scripts/sub/x.py` now.")
        self.assertEqual(self.run_check().returncode, 1)
        self.skill("alpha", body="Run `bash -x scripts/x.sh` now.")
        self.assertEqual(self.run_check().returncode, 1)

    def test_changelog_version_needs_word_boundary(self):
        self.skill("alpha", log=LOG.replace("**1.2.0**", "**11.2.0**"))
        r = self.run_check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("changelog", r.stdout.lower())
        self.skill("alpha", log=LOG.replace("**1.2.0** (2026-01-01)", "1.2.0 (2026)"))
        self.assertEqual(self.run_check().returncode, 0, self.run_check().stdout)


ROOT = "${CLAUDE_PLUGIN_ROOT}"
PAGE = ROOT + "/shared/review_page/review_page.py"
APPLY = ROOT + "/skills/todos/scripts/todos_apply.py"
WHOLE = "**Needs the whole plugin.**\n\n"


def fm(rules):
    items = "".join("\n  - " + r for r in rules)
    return GOOD.format(name="alpha", body="{body}").replace("version: 1.2.0\n", "version: 1.2.0\nallowed-tools:" + items + "\n")


class PluginRootScripts(CheckBase):
    def setUp(self):
        super().setUp()
        for rel in ("shared/review_page/review_page.py", "skills/todos/scripts/todos_apply.py"):
            f = Path(self._tmp.name) / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("")

    def alpha(self, body, rules=None):
        text = fm(rules).replace("{body}", WHOLE + body) if rules is not None else None
        self.skill("alpha", text=text, body=WHOLE + body)
        return self.run_check()

    def test_relative_script_call_is_rejected(self):
        r = self.alpha("Run `python3 ../../shared/review_page/review_page.py spec.json --out p.html`.")
        self.assertEqual(r.returncode, 1)
        self.assertIn("run plugin scripts through ${CLAUDE_PLUGIN_ROOT}", r.stdout)

    def test_skill_folder_relative_script_call_is_rejected(self):
        r = self.alpha("Run `python3 scripts/todos_page.py`.")
        self.assertEqual(r.returncode, 1)
        self.assertIn("run plugin scripts through ${CLAUDE_PLUGIN_ROOT}", r.stdout)

    def test_plugin_root_call_to_missing_file_is_rejected(self):
        r = self.alpha("Run `python3 " + ROOT + "/shared/nope.py`.")
        self.assertEqual(r.returncode, 1)
        self.assertIn("path " + ROOT + "/shared/nope.py does not exist", r.stdout)

    def test_quoted_plugin_root_call_is_rejected(self):
        r = self.alpha('Run `python3 "' + PAGE + '" x`.')
        self.assertEqual(r.returncode, 1)
        self.assertIn("unquoted", r.stdout)

    def test_call_not_covered_by_allowed_tools_is_rejected(self):
        r = self.alpha("Run `python3 " + PAGE + " spec.json`.")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not covered by allowed-tools", r.stdout)

    def test_covered_call_passes(self):
        rules = ["Bash(python3 " + PAGE + " *)", "Read(/" + ROOT + "/**)", "Skill(proofs:alpha)"]
        r = self.alpha("Run `python3 " + PAGE + " spec.json --out p.html`.", rules)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_single_line_allowed_tools_is_read(self):
        text = GOOD.format(name="alpha", body=WHOLE + "Run `python3 " + PAGE + " x`.").replace(
            "version: 1.2.0\n", "version: 1.2.0\nallowed-tools: Bash(python3 " + PAGE + " *) Read(/" + ROOT + "/**)\n")
        self.skill("alpha", text=text)
        r = self.run_check()
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_never_preapproved_script_may_be_called_uncovered(self):
        r = self.alpha("Run `python3 " + APPLY + " --all`.")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_never_preapproved_script_in_allowed_tools_is_rejected(self):
        r = self.alpha("Run `python3 " + APPLY + "`.", ["Bash(python3 " + APPLY + " *)", "Read(/" + ROOT + "/**)"])
        self.assertEqual(r.returncode, 1)
        self.assertIn("must keep prompting", r.stdout)

    def test_root_wildcard_rule_is_rejected(self):
        r = self.alpha("Plain text.", ["Bash(python3 " + ROOT + "/*)", "Read(/" + ROOT + "/**)"])
        self.assertEqual(r.returncode, 1)
        self.assertIn("is not allowed", r.stdout)

    def test_rule_shapes_outside_the_allow_list_are_rejected(self):
        for bad in ("Bash(*)", "Bash(python3 *)", "Bash(python3 /opt/x/*)", "Write(*)"):
            with self.subTest(rule=bad):
                r = self.alpha("Plain text.", [bad, "Read(/" + ROOT + "/**)"])
                self.assertEqual(r.returncode, 1, r.stdout)
                self.assertIn("is not allowed", r.stdout)

    def test_skill_rule_is_accepted(self):
        r = self.alpha("Plain text.", ["Read(/" + ROOT + "/**)", "Skill(proofs:alpha)"])
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_allowed_tools_without_read_rule_is_rejected(self):
        r = self.alpha("Run `python3 " + PAGE + " x`.", ["Bash(python3 " + PAGE + " *)"])
        self.assertEqual(r.returncode, 1)
        self.assertIn("missing Read(/${CLAUDE_PLUGIN_ROOT}/**)", r.stdout)

    def test_plugin_root_without_whole_plugin_line_is_rejected(self):
        self.skill("alpha", body="Run `python3 " + APPLY + "`.")
        r = self.run_check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("Needs the whole plugin", r.stdout)

    def test_rule_matches_semantics(self):
        loader = importlib.machinery.SourceFileLoader("check_skills", str(CHECK))
        mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("check_skills", loader))
        loader.exec_module(mod)
        rm = mod.rule_matches
        rule = "Bash(python3 /r/a.py *)"
        self.assertTrue(rm(rule, "python3 /r/a.py x --out y"))
        self.assertTrue(rm(rule, "python3 /r/a.py"))
        self.assertFalse(rm(rule, "python3 /r/a.pyc"))
        self.assertFalse(rm(rule, 'python3 "/r/a.py" x'))


if __name__ == "__main__":
    unittest.main()
