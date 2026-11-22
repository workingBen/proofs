import contextlib
import importlib.util
import io
import re
import shlex
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def section(skill: str, heading: str) -> str:
    """Text under a `##` or `###` heading of skills/<skill>/SKILL.md, up to the next heading of the same or higher level."""
    lines = (REPO / "skills" / skill / "SKILL.md").read_text().splitlines()
    out, level, in_fence = [], None, False
    for line in lines:
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        m = None if in_fence else re.match(r"(#{2,3}) (.*)", line)
        if level is None:
            if m and m.group(2).strip().startswith(heading):
                level = len(m.group(1))
            continue
        if m and len(m.group(1)) <= level:
            break
        out.append(line)
    if level is None:
        raise AssertionError(f"no heading starting {heading!r} in skills/{skill}/SKILL.md")
    return "\n".join(out)


def guidance_files():
    return sorted((REPO / "skills").glob("*/SKILL.md")) + sorted((REPO / "reference").glob("*.md"))


class DesignReviewGuidance(unittest.TestCase):
    def step2(self):
        return section("design-review", "2.")

    def test_design_review_captures_through_the_helper(self):
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/shared/capture/with_server.py --start", self.step2())

    def test_design_review_forbids_background_servers(self):
        text = self.step2()
        self.assertIn("run_in_background", text)
        self.assertIn("claude -p", text)

    def test_committed_screenshots_must_be_labeled_with_date(self):
        text = self.step2()
        self.assertIn("committed screenshot", text)
        self.assertIn("git log -1 --format=%cs", text)

    def test_no_free_standing_poll_loop(self):
        self.assertNotIn("seq 1 20", self.step2())

    def test_helper_flags_in_the_example_exist(self):
        helper = (REPO / "shared" / "capture" / "with_server.py").read_text()
        block = re.sub(r"\\\n\s*", " ", self.step2())
        used = set(re.findall(r"with_server\.py(.*?) -- ", block))
        flags = {f for chunk in used for f in re.findall(r"(?<!\S)(--[a-z-]+)", chunk)}
        self.assertIn("--start", flags)
        for flag in flags:
            self.assertIn(f'"{flag}"', helper)

    def test_capture_is_capture_cjs_after_with_server(self):
        # design-review's example runs the one default capture helper after `--`.
        for skill in ("design-review", "visual-qa", "pr-qa"):
            calls = [c for p, c in helper_calls() if p.parent.name == skill]
            self.assertTrue(any(re.search(r" -- node \$\{CLAUDE_PLUGIN_ROOT\}/skills/visual-qa/scripts/capture\.cjs ", c) for c in calls), skill)


def helper_calls():
    """(file, command) for every with_server.py call in a fenced block of a SKILL.md or reference page, continuations joined."""
    calls = []
    for path in guidance_files():
        in_fence = False
        for line in re.sub(r"\\\n\s*", " ", path.read_text()).splitlines():
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
            elif in_fence and "with_server.py" in line:
                calls.append((path, line.strip()))
    return calls


class HelperCalls(unittest.TestCase):
    def test_examples_exist(self):
        files = {p.parent.name for p, _ in helper_calls()}
        self.assertTrue({"design-review", "pr-qa"} <= files, files)

    def test_no_call_starts_with_a_variable_assignment(self):
        # Claude Code strips only a fixed list of safe env vars before matching a Bash
        # rule, so `CHROME=... python3 ...with_server.py` never matches the allow rule.
        for path, cmd in helper_calls():
            self.assertNotRegex(cmd, r"^[A-Z_][A-Z0-9_]*=", f"{path}: {cmd[:80]}")
            self.assertTrue(cmd.startswith("python3 ${CLAUDE_PLUGIN_ROOT}/shared/capture/with_server.py "), f"{path}: {cmd[:80]}")

    def test_every_flag_is_one_the_helper_accepts(self):
        spec = importlib.util.spec_from_file_location("with_server", REPO / "shared" / "capture" / "with_server.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for path, cmd in helper_calls():
            argv = shlex.split(cmd.split("with_server.py", 1)[1])
            with self.subTest(path=path.parent.name), contextlib.redirect_stderr(io.StringIO()) as err:
                try:
                    mod._parse(argv)
                except SystemExit:
                    self.fail(f"{path}: with_server.py rejects the example: {err.getvalue().strip()}")


SMOKE_SENTENCE = (
    'Run `--smoke`. If it reports Playwright missing, run the one-line install it prints (it uses your installed Google Chrome and downloads no browser), then run `--smoke` again; if it still cannot run, say on the page and in chat that the self-check did not run.'
)
PAGE_SKILLS = ("article-copy-edit", "design-review", "photo-picker", "qa-checklist", "questions", "style-guide", "working-log")


class SmokeGuidance(unittest.TestCase):
    def test_every_page_skill_says_to_install_and_rerun_smoke(self):
        paths = [REPO / "skills" / s / "SKILL.md" for s in PAGE_SKILLS] + [REPO / "reference" / "review-page.md"]
        for path in paths:
            with self.subTest(path=path.relative_to(REPO)):
                self.assertIn(SMOKE_SENTENCE, path.read_text())

    def test_no_skill_lets_smoke_be_skipped(self):
        for path in guidance_files():
            text = path.read_text()
            self.assertNotIn("when Playwright is available", text, path)
            self.assertNotIn("Without Playwright", text, path)

    def test_the_builder_prints_the_install_line_the_sentence_points_to(self):
        src = (REPO / "shared" / "review_page" / "review_page.py").read_text()
        self.assertIn("Playwright not found. \" + HOW_TO_PY", src)
        self.assertIn("npm install --prefix ~/.cache/proofs-playwright playwright@1.61.1", src)


class ReadmeInstall(unittest.TestCase):
    def test_install_paragraph_warns_that_claude_p_needs_the_allow_block(self):
        readme = (REPO / "README.md").read_text()
        after_install = readme.split("/plugin install proofs@proofs\n```\n", 1)[1].lstrip().splitlines()[0]
        self.assertIn("claude -p", after_install)
        self.assertIn("Allow Proofs", after_install)
        self.assertIn("will not start", after_install)

    def test_readme_says_pr_qa_in_claude_p_needs_both_blocks(self):
        # Final review M1.
        self.assertIn("For pr-qa in `claude -p`, use `--headless --project`", (REPO / "README.md").read_text())

    def test_readme_says_to_rerun_after_a_local_marketplace_change(self):
        # Final review M6: the folder rules record the path once.
        self.assertIn("rerun it after adding or moving a local marketplace", (REPO / "README.md").read_text())


class ChromeLines(unittest.TestCase):
    def test_every_chrome_line_turns_off_code_sign_clone(self):
        seen = 0
        for path in guidance_files():
            joined = re.sub(r"\\\n\s*", " ", path.read_text())
            for line in joined.splitlines():
                if "--headless" in line:
                    seen += 1
                    self.assertIn("--disable-features=MacAppCodeSignClone", line, f"{path.name}: {line[:80]}")
        self.assertGreater(seen, 0)


class PrQaGuidance(unittest.TestCase):
    def pr_qa(self):
        return (REPO / "skills" / "pr-qa" / "SKILL.md").read_text()

    def test_default_path_comes_before_the_sequence(self):
        text = self.pr_qa()
        self.assertIn("## Default path: one turn, page first", text)
        self.assertLess(text.index("## Default path: one turn, page first"), text.index("## The Sequence"))
        self.assertLess(text.index("## When to Use"), text.index("## Default path"))

    def test_default_path_builds_page_before_polish(self):
        text = section("pr-qa", "Default path")
        self.assertLess(text.index("pr_qa_page.py"), text.index("polish"))

    def test_no_redirect_for_findings(self):
        text = self.pr_qa()
        self.assertNotIn("> <dir>/findings.json", text)
        self.assertNotRegex(text, r"pr_qa_findings\.py[^\n]* > ")
        self.assertIn("--out .proofs/evidence/pr-<n>/findings.json", text)

    def test_never_asks_which_capture_method(self):
        text = self.pr_qa()
        sentence = "Do not ask the user which capture method to use."
        self.assertIn(sentence, text)
        self.assertNotRegex(text.replace(sentence, ""), r"(?i)choose how to|which capture")

    def test_default_path_uses_one_playwright_home(self):
        text = section("pr-qa", "Default path")
        self.assertIn("~/.cache/proofs-playwright", text)
        self.assertIn("not measured", text)

    def test_default_path_has_at_most_eleven_bash_calls(self):
        text = section("pr-qa", "Default path")
        fence = text.split("```bash", 1)[1].split("```", 1)[0]
        calls = [l for l in fence.splitlines() if l.strip() and not l.startswith("#")]
        self.assertLessEqual(len(calls), 11, calls)

    def test_default_path_checks_out_the_pr_before_the_after_capture(self):
        section_text = section("pr-qa", "Default path")
        text = section_text.split("```bash", 1)[1].split("```", 1)[0]
        remove = text.index("git worktree remove --force")
        checkout = text.index("gh pr checkout <n>")
        after = text.index("--evidence after")
        self.assertLess(remove, checkout)
        self.assertLess(checkout, after)
        self.assertIn("no-op", section_text)

    def test_default_path_honors_the_base_dir_setting(self):
        text = section("pr-qa", "Default path")
        fence = text.split("```bash", 1)[1].split("```", 1)[0]
        self.assertEqual(fence.strip().splitlines()[0], "printenv PROOFS_BASE_DIR")
        self.assertIn("<PROOFS_BASE_DIR>/<repo folder>-pr-qa-base", text)
        sequence = section("pr-qa", "The Sequence")
        self.assertIn("printenv PROOFS_BASE_DIR", sequence)
        self.assertNotIn("echo \"${PROOFS_BASE_DIR", self.pr_qa())
        self.assertNotIn("Read tool", text.split("PROOFS_BASE_DIR", 1)[1].split("gh pr checkout", 1)[0])

    def test_default_path_copies_env_with_cp_and_reinstalls_after_checkout(self):
        text = section("pr-qa", "Default path")
        self.assertIn("cp .env", text)
        self.assertNotIn("copy it into the base folder's `<app-dir>` with the Read", text)
        after_checkout = text.split("gh pr checkout <n>` is not optional", 1)[1]
        self.assertIn("package.json", after_checkout)
        self.assertIn("lockfile", after_checkout)

    def test_exclude_one_liner_is_gone(self):
        text = self.pr_qa()
        self.assertNotIn("git check-ignore", text)
        self.assertIn("adds `.proofs/` to `.git/info/exclude`", text)

    def test_default_path_says_how_to_compare_local_branches(self):
        # 2026-11-22 headless check: no GitHub PR, and the base branch checked out in the project.
        text = section("pr-qa", "Default path")
        fence = text.split("```bash", 1)[1].split("```", 1)[0]
        self.assertIn("git worktree add --detach .proofs/base origin/<base>", fence)
        # Final review I2: the after shot comes from a second detached worktree, never a switch.
        self.assertNotIn("git switch", self.pr_qa())
        local = text.split("**No GitHub PR", 1)[1].split("\n\n", 1)[0]
        self.assertIn("11 Bash calls", local)
        self.assertIn("in place of `gh pr checkout <n>`", local)
        self.assertIn("git worktree add --detach .proofs/base <branch>", local)
        self.assertIn("--cwd .proofs/base/<app-dir>", local)
        self.assertIn("never touched", local)

    def test_default_path_skips_the_install_without_package_json(self):
        # Final review M3: a static site has no package.json, so npm ci only fails.
        self.assertIn("has no `package.json`", section("pr-qa", "Default path"))

    def test_a_refused_open_prints_the_path_and_does_not_retry(self):
        # `open .proofs/pages/*` is allowed now; a refusal is not retried.
        self.assertIn("do not retry: print the path and the command", (REPO / "reference" / "where-the-page-goes.md").read_text())
        self.assertIn("do not retry: print the path and the command", section("pr-qa", "Default path"))

    def test_own_tests_need_preapproval_in_claude_p(self):
        # Final review M4: the project's test command is in no rule.
        step5 = section("pr-qa", "Default path").split("5. **Only then", 1)[1].split("\n", 1)[0]
        self.assertIn("in `claude -p`, only if their command is pre-approved", step5)

    def test_jsdom_verification_is_for_hand_built_pages(self):
        # Final review I4: pr_qa_page.py is tested by its own suite; no jsdom pass after the default path.
        artifact = section("pr-qa", "The Artifact")
        self.assertTrue(artifact.strip().startswith(
            "This section is for a page you build by hand; `pr_qa_page.py` already does all of it."), artifact[:200])
        self.assertIn("**Verify before publishing (a hand-built page only).**", artifact)

    def test_every_worktree_remove_says_force(self):
        # Step 3 removes the base worktree with --force; Common Mistakes must give the same command.
        mistakes = section("pr-qa", "Common Mistakes")
        self.assertIn("git worktree remove --force <base-dir>", mistakes)
        self.assertNotIn("git worktree remove <base-dir>", self.pr_qa())

    def test_pr_qa_base_worktree_lives_under_dot_proofs(self):
        text = section("pr-qa", "The Sequence")
        self.assertIn("git worktree add --detach <base-dir>", text)
        self.assertIn(".proofs/base", text)
        self.assertIn("info/exclude", text)

    def test_pr_qa_installs_dependencies_instead_of_symlinking(self):
        self.assertIn("npm ci", section("pr-qa", "The Sequence"))
        text = section("pr-qa", "The four things")
        self.assertNotIn("Link or copy them in", text)
        self.assertIn("do not symlink `node_modules`", text)

    def test_pr_qa_captures_through_the_helper_with_cwd(self):
        self.assertIn("with_server.py --cwd <base-dir>", section("pr-qa", "The Sequence"))

    def test_pr_qa_names_the_base_dir_setting(self):
        text = section("pr-qa", "The Sequence")
        self.assertIn("PROOFS_BASE_DIR", text)
        self.assertIn("-pr-qa-base", text)

    def test_pr_qa_says_to_use_the_literal_base_path(self):
        self.assertIn("literal resolved path", section("pr-qa", "The Sequence"))

    def test_pr_qa_cleanup_removes_the_base_worktree(self):
        self.assertIn("git worktree remove --force <base-dir>", section("pr-qa", "Common Mistakes"))

    def test_pr_qa_removes_the_base_worktree_before_the_branch_and_its_tests(self):
        text = section("pr-qa", "The Sequence")
        remove = text.index("**Then remove the base worktree at once**")
        self.assertIn("git worktree remove --force <base-dir>", text[remove:remove + 200])
        self.assertLess(text.index("--cwd <base-dir>"), remove)
        self.assertLess(remove, text.index("3. **Run the branch for real**"))
        self.assertLess(remove, text.index("4. **Run the PR's own tests**"))


HOUSE_RULE_SKILLS = ("design-review", "visual-qa", "working-log", "pr-qa")


class HouseRules(unittest.TestCase):
    def test_house_rules_in_capture_skills(self):
        for skill in HOUSE_RULE_SKILLS:
            text = (REPO / "skills" / skill / "SKILL.md").read_text()
            for rule in ("**Finish in this turn.**", "**Stay in two folders.**", "**One command per Bash call.**"):
                with self.subTest(skill=skill, rule=rule):
                    self.assertIn(rule, text)

    def test_design_review_phone_check_of_the_page_names_a_working_method(self):
        text = (REPO / "skills" / "design-review" / "SKILL.md").read_text()
        self.assertNotIn("screenshot the page at a desktop and a phone width", text)
        verify = text.split("**Verify before publishing", 1)[1].split("###", 1)[0]
        self.assertIn("390", verify)
        self.assertIn("file://", verify)
        self.assertIn("capture.cjs", verify)

    def test_visual_qa_default_capture_starts_its_own_server(self):
        text = (REPO / "skills" / "visual-qa" / "SKILL.md").read_text()
        self.assertNotIn("as `design-review` step 2 does", text)
        self.assertIn("run_in_background", text)
        self.assertIn("already answering", text)

    def test_design_review_file_url_example_uses_base_and_path(self):
        text = (REPO / "skills" / "design-review" / "SKILL.md").read_text()
        verify = text.split("**Verify before publishing", 1)[1].split("###", 1)[0]
        self.assertIn(".proofs/pages/", verify)
        self.assertIn("/<review-name>.html", verify)

    def test_house_rules_reference_exists(self):
        text = (REPO / "reference" / "house-rules.md").read_text()
        self.assertIn("~/.cache/proofs-playwright", text)

    def test_stay_in_two_folders_names_the_base_dir_exception(self):
        # Final review M2: pr-qa's PROOFS_BASE_DIR base folder is outside the project by design.
        exception = "and pr-qa's `PROOFS_BASE_DIR` base folder, when it is set"
        for path in [REPO / "reference" / "house-rules.md"] + [
                REPO / "skills" / s / "SKILL.md" for s in HOUSE_RULE_SKILLS]:
            with self.subTest(path=path.name if path.name != "SKILL.md" else path.parent.name):
                self.assertIn(exception, path.read_text())

    def test_no_phone_window_size_below_500(self):
        for path in guidance_files():
            for m in re.finditer(r"--window-size=(\d+),", path.read_text()):
                self.assertGreaterEqual(int(m.group(1)), 500, f"{path}: {m.group(0)}")

    def test_no_gitignore_advice(self):
        for path in guidance_files():
            text = path.read_text()
            self.assertIsNone(re.search(r"(?i)add it to `?\.gitignore", text), str(path))

    def test_no_parent_claude_md(self):
        for path in guidance_files():
            for line in path.read_text().splitlines():
                if "../CLAUDE.md" in line:
                    self.assertRegex(line, r"(?i)never|do not|don't", f"{path}: {line[:80]}")

    def test_examples_have_no_shell_tricks(self):
        paths = [REPO / "skills" / s / "SKILL.md" for s in HOUSE_RULE_SKILLS] + sorted((REPO / "reference").glob("*.md"))
        for path in paths:
            in_fence = False
            for line in path.read_text().splitlines():
                if line.lstrip().startswith("```"):
                    in_fence = line.lstrip().startswith("```bash") and not in_fence
                elif in_fence:
                    code = re.sub(r"<[^<>\s][^<>]{0,30}>", "X", line.split(" #", 1)[0]).lstrip()
                    if code.startswith("#"):
                        continue
                    self.assertIsNone(re.search(r"^[A-Z_]+=|\||&&|;|\$\(|^cd |(?<![-=])\d*>{1,2}|&>|(^|\s)<\s", code), f"{path.name}: {line[:80]}")


class AdHocShellAndOpen(unittest.TestCase):
    def test_house_rules_forbid_ad_hoc_tools(self):
        text = (REPO / "reference" / "house-rules.md").read_text()
        for word in ("sed -i", "magick", "`file`"):
            self.assertIn(word, text)

    def test_open_uses_allowed_form(self):
        text = (REPO / "reference" / "where-the-page-goes.md").read_text()
        self.assertIn("open .proofs/pages/", text)
        self.assertNotIn("do not open the page", text)

    def test_pr_qa_open_matches_where_the_page_goes(self):
        text = (REPO / "skills" / "pr-qa" / "SKILL.md").read_text()
        self.assertIn("open .proofs/pages/pr-qa.html", text)
        self.assertNotIn("do not `open` the page", text)

    def test_no_skill_tells_the_model_to_run_ad_hoc_tools(self):
        for path in sorted((REPO / "skills").glob("*/SKILL.md")):
            in_fence = False
            for line in path.read_text().splitlines():
                if line.lstrip().startswith("```"):
                    in_fence = not in_fence
                elif in_fence:
                    self.assertIsNone(re.match(r"\s*(sed -i|magick|identify|file|sips)\b", line), f"{path.parent.name}: {line[:80]}")

    def test_design_review_points_at_the_helpers_checks(self):
        text = (REPO / "skills" / "design-review" / "SKILL.md").read_text()
        self.assertIn("helpers' own checks", text)


if __name__ == "__main__":
    unittest.main()
