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

## Changelog

- 1.2.0: first merged version.
"""


class CheckCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.skills = Path(self._tmp.name) / "skills"
        self.skills.mkdir()

    def skill(self, folder, text=None, name=None, body=""):
        d = self.skills / folder
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(text if text is not None else GOOD.format(name=name or folder, body=body))

    def run_check(self):
        return subprocess.run([sys.executable, str(CHECK), str(self.skills)],
                              capture_output=True, text=True)

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
        self.skill("alpha", text=base.replace("## Changelog", "## History"))
        self.assertEqual(self.run_check().returncode, 1)
        self.skill("alpha", text=base.replace("- 1.2.0: first", "- 0.9.0: first"))
        r = self.run_check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("changelog", r.stdout.lower())

    def test_bare_script_path_rejected(self):
        self.skill("alpha", body="Run `scripts/capture.cjs` now.")
        self.assertEqual(self.run_check().returncode, 1)
        self.skill("alpha", body="Run `node scripts/capture.cjs` now and `python3 scripts/x.py`.")
        r = self.run_check()
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_skill_references_resolve(self):
        self.skill("alpha", body="This needs the `beta` skill first.")
        r = self.run_check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("beta", r.stdout)
        self.skill("beta")
        r = self.run_check()
        self.assertEqual(r.returncode, 0, r.stdout)

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

    PAGES = ("## Where the page goes\n\nSet `PROOFS_PAGES` to artifact, file or wifi.\n")

    def test_page_skills_need_where_the_page_goes(self):
        self.skill("design-review")
        r = self.run_check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("Where the page goes", r.stdout)

    def test_page_skills_must_name_all_three_values(self):
        self.skill("design-review", body="## Where the page goes\n\nartifact or file only.\n")
        r = self.run_check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("wifi", r.stdout)

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
        self.skill("pr-qa", body=self.PAGES.replace("Set", "Choose"))
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
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_bare_nested_and_flagged_paths_still_rejected(self):
        self.skill("alpha", body="Run `scripts/sub/x.py` now.")
        self.assertEqual(self.run_check().returncode, 1)
        self.skill("alpha", body="Run `bash -x scripts/x.sh` now.")
        self.assertEqual(self.run_check().returncode, 1)

    def test_changelog_version_needs_word_boundary(self):
        text = GOOD.format(name="alpha", body="").replace("- 1.2.0: first", "- 11.2.0: first")
        self.skill("alpha", text=text)
        r = self.run_check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("changelog", r.stdout.lower())
        text = GOOD.format(name="alpha", body="").replace("- 1.2.0: first", "- **1.2.0** (2026): first")
        self.skill("alpha", text=text)
        self.assertEqual(self.run_check().returncode, 0, self.run_check().stdout)


if __name__ == "__main__":
    unittest.main()
