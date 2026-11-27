import contextlib
import importlib.machinery
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

    def test_an_app_that_cannot_start_stops_and_asks(self):
        # Django run 1 (B1): the venv was denied and the review was built on committed PNGs, unasked.
        text = self.step2()
        ask = text[text.index("**When the app cannot start, stop and ask.**"):]
        ask = ask[:ask.index("\n\n")]
        self.assertIn("(a)", ask)
        self.assertIn("(b)", ask)
        self.assertIn("python3 -m venv .venv", ask)
        self.assertIn(".venv/bin/pip install -r requirements.txt", ask)
        self.assertIn("not live", ask)
        self.assertIn("before you build", ask)
        self.assertIn("End the turn", ask)
        self.assertNotIn("may stand in", text)

    def test_mockup_fonts_never_depend_on_a_fetch(self):
        text = section("design-review", "4.")
        fonts = text[text.index("**Fonts and images.**"):]
        fonts = fonts[:fonts.index("\n- ")]
        self.assertNotIn("download the real fonts", fonts)
        self.assertIn("head_html", fonts)
        self.assertIn("<link", fonts)
        self.assertIn("fallback stack", fonts)
        self.assertIn("curl", fonts)
        self.assertIn("{{asset:", fonts)
        ref = (REPO / "reference" / "review-page.md").read_text()
        self.assertIn("fallback stack", ref)

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

    def test_breakpoint_in_the_diff_adds_a_width_just_above_it(self):
        # Django run 2: an lg: two-column hero was shot only at 390 and 1440.
        text = section("pr-qa", "Default path")
        for prefix, width in (("sm:", "656"), ("md:", "784"), ("lg:", "1040"), ("xl:", "1280")):
            self.assertRegex(text, r"`%s`[^`]*?\b%s\b" % (re.escape(prefix), width), prefix)
        self.assertIn("--sizes 390,1040,1440", text)
        self.assertIn("at most two", text)

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
        # Rails run 1 (C2): the session read both settings at once and the one-variable rule
        # did not match; the skill and the --project rule now give the same two-variable form.
        self.assertEqual(fence.strip().splitlines()[0], "printenv PROOFS_PAGES PROOFS_BASE_DIR")
        self.assertIn("<PROOFS_BASE_DIR>/<repo folder>-pr-qa-base", text)
        sequence = section("pr-qa", "The Sequence")
        self.assertIn("printenv PROOFS_PAGES PROOFS_BASE_DIR", sequence)
        import re as _re
        forms = set(_re.findall(r"printenv [A-Z_ ]*[A-Z_]", self.pr_qa()))
        self.assertEqual(forms, {"printenv PROOFS_PAGES PROOFS_BASE_DIR"}, forms)
        self.assertNotIn("echo \"${PROOFS_BASE_DIR", self.pr_qa())
        self.assertNotIn("Read tool", text.split("PROOFS_BASE_DIR", 1)[1].split("gh pr checkout", 1)[0])

    def test_rails_base_checkout_installs_in_the_allowed_form(self):
        # Rails run 1 (C2): `bundle install --gemfile .proofs/base/rails/Gemfile` was denied.
        self.assertIn("bundle install --gemfile .proofs/base/<app-dir>/Gemfile", self.pr_qa())

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

    def test_the_playwright_cache_is_never_listed(self):
        # Django run 1 (C3): `ls .proofs ~/.cache/proofs-playwright` was denied; the capture says it itself.
        ref = (REPO / "reference" / "house-rules.md").read_text()
        rule = next(l for l in ref.splitlines() if "**Stay in two folders.**" in l)
        self.assertIn("never `ls` or Read it", rule)
        for skill in HOUSE_RULE_SKILLS:
            text = (REPO / "skills" / skill / "SKILL.md").read_text()
            with self.subTest(skill=skill):
                self.assertIn(rule.split(". ", 1)[1], text)

    def test_pr_qa_names_the_non_node_forms(self):
        # Django run 1 (C3): `.venv/bin/python manage.py test` was refused; --project now covers it.
        text = section("pr-qa", "The Sequence")
        for form in ("python3 -m venv .venv", ".venv/bin/pip install -r requirements.txt",
                     ".venv/bin/python manage.py test", "--stack"):
            self.assertIn(form, text)

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

    def test_every_page_build_writes_under_proofs_pages(self):
        # Django run 2: working-log built .proofs/session.html, which the `open .proofs/pages/*` rule missed.
        builders = r"(?:review_page\.py|pr_qa_page\.py|todos_page\.py)"
        found = 0
        for path in guidance_files():
            for m in re.finditer(builders + r" [^`\n]*?--out (\S+?)`?(?=[\s`;,)]|$)", path.read_text()):
                if "--crops" in m.group(0):  # crops are images in a folder, not a built page
                    continue
                out = m.group(1).strip("`")
                if out.startswith("<"):  # a placeholder in a helper's usage line
                    continue
                found += 1
                self.assertTrue(out.startswith(".proofs/pages/"), f"{path.relative_to(REPO)}: --out {out}")
        self.assertGreaterEqual(found, 8)

    def test_design_review_points_at_the_helpers_checks(self):
        text = (REPO / "skills" / "design-review" / "SKILL.md").read_text()
        self.assertIn("helpers' own checks", text)



PORT_SENTENCE = ("The port flag belongs to the dev server: `--port` for Vite (SvelteKit, Vue, Astro), "
                 "Nuxt and Angular, `-p` or `--port` for Next.js")


class PortFlag(unittest.TestCase):
    """SvelteKit run 1: two sessions copied `npm run dev -- -p 3311` and Vite rejected -p."""

    def test_no_skill_passes_p_through_npm(self):
        for path in sorted((REPO / "skills").glob("*/SKILL.md")) + sorted((REPO / "reference").glob("*.md")):
            with self.subTest(path=path.name):
                self.assertNotIn("-- -p ", path.read_text())

    def test_every_capture_skill_names_the_flag_per_tool(self):
        for skill in ("design-review", "visual-qa", "pr-qa"):
            with self.subTest(skill=skill):
                text = (REPO / "skills" / skill / "SKILL.md").read_text()
                self.assertIn('--start "npm run dev -- --port 3', text)
                self.assertIn(PORT_SENTENCE, text)


class AngularRun1(unittest.TestCase):
    """Angular run 1: no build before the commit or the QA, an undersold description, an
    unasked lockfile in the commit, and string human findings that crashed the builder."""

    def test_pr_qa_and_design_review_build_or_type_check(self):
        for skill, where in (("pr-qa", "Default path"), ("design-review", "5.")):
            with self.subTest(skill=skill):
                text = section(skill, where)
                for cmd in ("npm run build", "npx ng build", "npx tsc --noEmit"):
                    self.assertIn(cmd, text)
                # Astro run 2 made it "build and type-check": both, when the project has both.
                self.assertIn("build and type", text.lower())

    def test_pr_qa_checks_the_description_against_the_diff(self):
        text = section("pr-qa", "What to look for")
        self.assertIn("A description that does not match the diff", text)
        self.assertIn("gh pr view <n> --json body", text)
        self.assertIn('"severity": "warning"', text)

    def test_committing_skills_leave_unintended_lockfiles_out(self):
        for skill in ("design-review", "review-cycle"):
            with self.subTest(skill=skill):
                text = (REPO / "skills" / skill / "SKILL.md").read_text()
                self.assertIn("lockfile", text)
                self.assertIn("stays out", text.replace("left out of the commit", "stays out"))

    def test_pr_qa_documents_the_human_finding_shapes_the_builder_takes(self):
        row = [l for l in section("pr-qa", "The helper scripts").splitlines() if l.startswith("| `human_findings`")][0]
        self.assertIn('"severity"', row)
        self.assertIn("plain string", row)

    def test_off_center_rows_are_a_measured_target(self):
        self.assertIn("| Off-center rows |", (REPO / "skills" / "visual-qa" / "SKILL.md").read_text())
        self.assertIn("`off-center rows`", section("design-review", "5."))


class AstroRun1(unittest.TestCase):
    """Astro run 1: pr-qa started Astro without --ignore-lock, so it moved itself to the
    background and was left running; and shots blank below the hero were called clean."""

    def test_pr_qa_copies_the_projects_own_start_command(self):
        text = section("pr-qa", "Default path")
        self.assertIn("copy the project's own start command from its README or `CLAUDE.md`", text)

    def test_capture_skills_name_astros_foreground_flag(self):
        for skill in ("design-review", "pr-qa"):
            with self.subTest(skill=skill):
                text = (REPO / "skills" / skill / "SKILL.md").read_text()
                self.assertIn("--ignore-lock", text)
                self.assertIn("npx astro dev stop", text)

    def test_capture_skills_never_call_a_blank_shot_clean(self):
        for skill, where in (("design-review", "2."), ("pr-qa", "Default path")):
            with self.subTest(skill=skill):
                text = section(skill, where)
                self.assertIn("`blank or hidden content`", text)
                self.assertIn("not clean", text)

    def test_new_measures_are_targets(self):
        text = (REPO / "skills" / "visual-qa" / "SKILL.md").read_text()
        self.assertIn("| Off-center columns |", text)
        self.assertIn("| Blank or hidden content |", text)
        self.assertIn("`off-center columns`", section("design-review", "5."))


class AstroRun2(unittest.TestCase):
    """Astro run 2: design-review called a change built that did not type-check, committed
    unasked, and offered the capture's findings only in chat; pr-qa left flaws already on
    main off its page; and its first pages.json had the wrong shape again."""

    def test_build_and_type_check_both_run_and_a_build_alone_proves_no_types(self):
        for skill, where in (("design-review", "5."), ("pr-qa", "Default path")):
            with self.subTest(skill=skill):
                text = section(skill, where)
                self.assertIn("A build alone does not prove the types", text)
                for cmd in ("npx tsc --noEmit", "npx astro check", "npx vue-tsc --noEmit", "npx svelte-check",
                            "npx ng build", "@astrojs/check"):
                    self.assertIn(cmd, text)

    def test_type_check_commands_are_allowed(self):
        text = (REPO / "shared" / "allow_block.py").read_text()
        for cmd in ("npx tsc --noEmit", "npx astro check", "npx vue-tsc --noEmit", "npx svelte-check",
                    "npx ng build", "npm run type-check", "npm run typecheck", "npm run check"):
            self.assertIn(f"Bash({cmd})", text)

    def test_design_review_does_not_commit_unasked(self):
        text = section("design-review", "5.")
        self.assertIn("Do not commit unless the user asked you to", text)
        self.assertIn("uncommitted", text)
        self.assertNotIn("commit following the project's own notes", text)

    def test_design_review_puts_capture_findings_on_the_page(self):
        text = section("design-review", "4.")
        self.assertIn('"Found by the capture"', text)
        self.assertIn("one item per flaw", text)
        self.assertIn("if this change caused it", section("design-review", "5."))

    def test_pr_qa_lists_flaws_already_on_main_apart(self):
        text = section("pr-qa", "Default path")
        self.assertIn("Already on main (not caused by this PR)", text)
        self.assertIn("never change the verdict", text)

    def test_pr_qa_shows_the_pages_file_shape(self):
        text = section("pr-qa", "Default path")
        self.assertIn('{"base": "http://localhost:3411", "pages": [{"name": "home", "path": "/"}]}', text)

    def test_sections_without_headings_are_a_target(self):
        self.assertIn("| Sections without headings |", (REPO / "skills" / "visual-qa" / "SKILL.md").read_text())



class AnswersWithoutCopy(unittest.TestCase):
    """1.6.8: pages that take answers publish with the db capability, and sessions read
    the answers from it before asking for a paste."""

    def test_answer_skills_publish_with_db_and_read_it_first(self):
        for skill in ("working-log", "questions", "qa-checklist"):
            with self.subTest(skill=skill):
                text = (REPO / "skills" / skill / "SKILL.md").read_text()
                self.assertIn('capabilities: {"db": {}, "comments": {}}', text)
                self.assertNotIn('capabilities: {"db": {}}', text)
                self.assertIn("`ArtifactData` `list` of `proofs-answers`", text)
                self.assertIn("review_page.py --answers", text)
                self.assertIn("the newer (`updated_at`", text)
                self.assertIn("Anyone the page is shared with can write answers; pages are private by default", text)

    def test_reference_documents_the_rows_and_privacy(self):
        text = " ".join((REPO / "reference" / "review-page.md").read_text().split())
        for needle in ('collection: "proofs-answers"', "| `updated_at` |", "| `page_version`, `page` |",
                       "--answers .proofs/pages/<name>.html --rows", "never pass `capabilities: {}`",
                       "Pages are private by default"):
            with self.subTest(needle=needle):
                self.assertTrue(needle in text, needle)


class SendToClaudeGuidance(unittest.TestCase):
    """1.8.0: a send wakes the session; its first act is a republish, never a second reply."""

    def test_answer_skills_say_what_the_session_does_on_a_send(self):
        for skill in ("working-log", "questions", "qa-checklist"):
            with self.subTest(skill=skill):
                text = " ".join((REPO / "skills" / skill / "SKILL.md").read_text().split())
                for needle in ("## Sent to Claude: what the session does", "`artifact-auto-react`",
                               "Republish the page first, before any other work.", "Never post a second reply",
                               "resolve the thread with `ArtifactComments`", "After `/clear`, a closed terminal or a new session",
                               "Editors only", "posted by the harness"):
                    self.assertIn(needle, text)

    def test_a_send_updates_the_page_first(self):
        text = (REPO / "skills" / "working-log" / "SKILL.md").read_text()
        self.assertIn("**A paste or a send updates the page first, before any other work.**", text)

    def test_reference_documents_states_and_limits(self):
        text = " ".join((REPO / "reference" / "review-page.md").read_text().split())
        for needle in ("## Send to Claude", "This page's Claude session isn't listening; use Copy",
                       "Only editors can send; use Copy", "Not available here; use Copy",
                       "Allow commenting when asked, then tap again", "Nothing was sent; use Copy.",
                       "Claude picked up your answers", "Not picked up yet. The session may be busy or closed; Copy still works.",
                       "### Sent to Claude: what the session does", "Never post a second reply",
                       'capabilities: {"db": {}, "comments": {}}', "must name `db` too"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()


class CommitAndPrGuidance(unittest.TestCase):
    """Astro run 3, session C: a push failed and stalled, `git add -A .`, a one-line PR body."""

    def text(self):
        return (REPO / "reference" / "commit-and-pr.md").read_text()

    def test_stage_by_name(self):
        text = self.text()
        self.assertIn("git add <path> <path>", text)
        for bad in ("`git add -A`", "`git add .`", "`git commit -a`"):
            self.assertIn(bad, text)

    def test_a_failed_push_is_reported_plainly_not_stalled(self):
        text = self.text()
        for word in ("HTTP 400", "git fetch origin", "git -c http.postBuffer=524288000 push -u origin HEAD",
                     "the exact command", "Do not open the pull request", "one retry"):
            self.assertIn(word, text)

    def test_a_pr_body_says_what_why_and_how_checked(self):
        text = self.text()
        for word in ("**What changed**", "**Why**", "**How it was checked**", "--body-file .proofs/pr-body.md"):
            self.assertIn(word, text)
        self.assertIn("never only file names", text)

    def test_committing_skills_point_at_it(self):
        for skill in ("design-review", "review-cycle", "pr-qa"):
            with self.subTest(skill=skill):
                self.assertIn("../../reference/commit-and-pr.md", (REPO / "skills" / skill / "SKILL.md").read_text())
        self.assertNotIn("gh pr create --fill", (REPO / "skills" / "review-cycle" / "SKILL.md").read_text())

    def test_readme_names_the_larger_buffer_push(self):
        self.assertIn("http.postBuffer", (REPO / "README.md").read_text())


class DesignReviewScopeAndCost(unittest.TestCase):
    """Astro run 3, session B: unpicked copy changed, new narrow targets, a cost that doubled."""

    def test_applying_picks_changes_only_what_was_picked(self):
        text = section("design-review", "5.")
        self.assertIn("Change only what was picked", text)
        self.assertIn("proposed, not applied", text)
        self.assertIn("Never change words the user did not pick", section("design-review", "3."))

    def test_after_capture_is_compared_by_text(self):
        text = section("design-review", "5.")
        self.assertIn("--compare .proofs/capture/before/measures.json", text)
        self.assertIn("new since the earlier capture", text)

    def test_capture_items_need_no_mockup_and_no_measuring_page(self):
        text = section("design-review", "4.")
        self.assertIn("need no mockup", text)
        self.assertIn("never build a page to measure", text)
        self.assertIn("-part-", text)
        self.assertIn("midWordAt", section("design-review", "2."))


class ResultsFirst(unittest.TestCase):
    """The maintainer's 1.6.10 principle: save tokens by cutting waste, never a check the result needs."""

    SHORT = ("**Results first.** Nothing matters more than a result the user wants. Save tokens by cutting waste, "
             "never by cutting a check, an option or a revise pass the result needs (full text: "
             "`../../reference/house-rules.md`).")

    def test_every_skill_says_results_first(self):
        skills = sorted((REPO / "skills").glob("*/SKILL.md"))
        self.assertEqual(len(skills), 13)
        for path in skills:
            with self.subTest(skill=path.parent.name):
                self.assertIn(self.SHORT, path.read_text())

    def test_house_rules_put_it_first(self):
        text = (REPO / "reference" / "house-rules.md").read_text()
        self.assertIn("Nothing matters more than a result the user wants", text)
        self.assertLess(text.index("0. **Results first.**"), text.index("1. **Finish in this turn.**"))
        self.assertIn("A cheap run whose result nobody wants is the most expensive kind", text)
        for skill in HOUSE_RULE_SKILLS:
            with self.subTest(skill=skill):
                lines = (REPO / "skills" / skill / "SKILL.md").read_text().splitlines()
                first = lines.index(next(l for l in lines if l.startswith("1. **Finish in this turn.**")))
                self.assertEqual(lines[first - 1], "0. " + self.SHORT)

    def test_readme_says_it(self):
        self.assertIn("And every skill puts the result first: it saves tokens by cutting waste, never by cutting "
                      "the checks that make the result right.", (REPO / "README.md").read_text())


_privacy_loader = importlib.machinery.SourceFileLoader("privacy_scan", str(REPO / "bin" / "privacy-scan"))
_privacy_spec = importlib.util.spec_from_loader("privacy_scan", _privacy_loader)
privacy_scan = importlib.util.module_from_spec(_privacy_spec)
_privacy_loader.exec_module(privacy_scan)


class DesignerReferences(unittest.TestCase):
    """The designer upgrade: the critic's rubric and the optional design profile."""

    KEYS = ("hierarchy", "action", "fold", "grouping", "fit", "care")

    def rubric(self):
        return " ".join((REPO / "reference" / "design-rubric.md").read_text().split())

    def profile(self):
        return " ".join((REPO / "reference" / "design-profile.md").read_text().split())

    def test_rubric_names_every_score_key_with_its_anchors(self):
        text = self.rubric()
        for key in self.KEYS:
            with self.subTest(key=key):
                self.assertIn(f"`{key}`", text)
        for anchor in ("**1**", "**3**", "**5**"):
            self.assertGreaterEqual(text.count(anchor), len(self.KEYS), anchor)

    def test_rubric_sets_the_bar(self):
        text = self.rubric()
        self.assertIn("2 or below", text)
        self.assertIn("any failed design check", text)
        self.assertIn("revise it (once per correction pass", text)
        self.assertIn("reason on the page", text)
        # Ruling 20: a near-copy kept with a Reason line is not a failed check, in every place
        # the bar is stated, and a one-option fix still names what changed.
        carve = "any failed design check other than a near-copy kept with a Reason line"
        self.assertEqual(text.lower().count(carve.lower()), 2, text)
        self.assertNotRegex(text, r"(?i)any failed design check(?! other than)")
        self.assertIn("the Reason line still names what changed", text)
        skill = " ".join((REPO / "skills" / "design-review" / "SKILL.md").read_text().split())
        self.assertIn(carve, skill)
        self.assertNotRegex(skill, r"(?i)any failed design check(?! other than)")

    def test_rubric_judges_the_three_roles_and_the_measured_checks(self):
        text = self.rubric()
        for needle in ("**Careful**", "**Step up**", "**Bold**", "`--smoke`", "not measured", "near-copies",
                       "`judged_by`"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_rubric_scores_the_current_page_and_reads_near_copies_per_case(self):
        text = self.rubric()
        for needle in ("`before_scores`", "beat the current page", "`fold` or `hierarchy`",
                       "Two options that are near-copies of each other fail unless the author, having looked, records what differs",
                       "never ignored silently", "one line in the item's Reason saying what genuinely differs",
                       "fails for Step up and Bold", "it is expected and not a failure",
                       "the current page's screenshots at 1280 and 390", "the style guide's path"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)
        self.assertNotIn("always fail", text)

    def test_profile_is_made_on_two_questions_pages_rules_second(self):
        text = self.profile()
        self.assertIn("two questions pages", text)
        self.assertLess(text.index("**First page: references and audience.**"),
                        text.index("**Second page: rules.**"))

    def test_profile_documents_path_setting_and_headings(self):
        text = self.profile()
        self.assertIn("`docs/design-profile.md`", text)
        self.assertIn("`PROOFS_DESIGN_PROFILE`", text)
        for heading in ("References", "Rules", "Audience", "Tokens"):
            with self.subTest(heading=heading):
                self.assertIn(f"## {heading}", (REPO / "reference" / "design-profile.md").read_text())

    def test_profile_is_optional_and_created_on_a_questions_page(self):
        text = self.profile()
        self.assertIn("never required", text)
        self.assertIn("questions page", text)
        for word in ("Love", "Like", "Not for us"):
            self.assertIn(word, text)

    def test_neither_file_names_anything_private(self):
        deny = privacy_scan.load_deny(None) or privacy_scan.Deny(None, None)
        for name in ("design-rubric.md", "design-profile.md"):
            for num, line in enumerate((REPO / "reference" / name).read_text().splitlines(), 1):
                with self.subTest(file=name, line=num):
                    self.assertEqual(privacy_scan.categories(line, deny), [])


class DesignerGuidance(unittest.TestCase):
    """1.7.0: design-review reads an optional profile, builds a real range, keeps an inventory and runs a critic."""

    def skill(self):
        return " ".join((REPO / "skills" / "design-review" / "SKILL.md").read_text().split())

    def step(self, heading):
        return " ".join(section("design-review", heading).split())

    def test_profile_is_read_when_present_and_never_required(self):
        text = self.step("1.")
        for needle in ("`docs/design-profile.md`", "`PROOFS_DESIGN_PROFILE`", "Never require it",
                       "`../../reference/design-profile.md`", "two questions pages", "one line"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_range_is_three_roles_for_a_redesign_and_one_for_a_bug_sized_fix(self):
        text = self.step("3.")
        for needle in ("Careful", "Step up", "Bold", "`careful`", "`step-up`", "`bold`",
                       "one option for a bug-sized fix", "\"Found by the capture\"",
                       "layout or hierarchy", "near-copies",
                       "one line in the item's Reason saying what genuinely differs", "never ignore it silently"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_inventory_comes_from_the_capture(self):
        text = self.step("3.")
        for needle in ("`before_sections`", "`before_font_sizes`", "`measures.sections`", "`measures.fontSizes`",
                       "`inventory`", "1280", "kept", "moved", "removed"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_one_option_proposal_is_wrapped_for_smoke(self):
        self.assertIn('<div class="rp-mockup">', self.step("4."))

    def test_smoke_notes_are_read_and_said(self):
        text = self.step("4.")
        for needle in ("`notes`", "`problems`", "contrast not measured", "by eye", "in chat"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_critic_pass(self):
        text = self.step("4.")
        for needle in ("`../../reference/design-rubric.md`", "separate helper", "fresh context", "Who judges",
                       "`claude -p`", "`judged_by`", "`helper`", "`self`", "`scores`", "`before_scores`",
                       "Current page", "revise it (once per correction pass", "Not scored", "Never recommend an unscored option"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_critic_comes_after_smoke_and_before_the_correction_pass_ends(self):
        text = self.step("4.")
        self.assertLess(text.index("**Verify before publishing"), text.index("**The critic"))
        self.assertLess(text.index("**The critic"), text.index("**One build, then at most the correction passes setting"))

    def test_first_build_is_a_critic_build(self):
        text = self.step("4.")
        self.assertIn("critic build", text)
        crit = text.split("**The first build is a critic build.**", 1)[1].split("**The critic judges", 1)[0]
        for needle in ('`"stack_variants": true`', "`note_html`", "`reason_html`", "`recommended`", "`judged_by`",
                       "`scores`", "`before_scores`", "rebuild"):
            with self.subTest(needle=needle):
                self.assertIn(needle, crit)
        self.assertIn("`reason_html` and `recommended` in the rebuild", text)

    def test_capture_item_without_mockup_has_no_inventory_or_scores(self):
        self.assertIn("every mockup", self.step("3."))
        self.assertIn("without a mockup carries neither `inventory` nor `scores`", self.step("3."))

    def test_results_first_keeps_the_critic_and_the_options(self):
        text = self.step("4.")
        self.assertIn("never by cutting an option, the critic or the revise pass", text)
        self.assertIn("spend cap setting (default $5", text)

    def test_keep_x_on_accept_with_comment(self):
        text = self.step("5.")
        accept = text.split("**`ACCEPT WITH COMMENT`**", 1)[1].split("**`DENY`**", 1)[0]
        self.assertIn("keep", accept)
        self.assertIn("ask", accept)

    def test_existing_rules_survive(self):
        text = self.skill()
        for needle in ("**Never change words the user did not pick.**", "\"Found by the capture\"",
                       "**Change only what was picked.**", "`../../reference/commit-and-pr.md`",
                       "**One build, then at most the correction passes setting", "--compare .proofs/capture/before/measures.json"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_style_guide_points_at_design_review(self):
        text = " ".join((REPO / "skills" / "style-guide" / "SKILL.md").read_text().split())
        self.assertIn("design-profile.md", text)
        self.assertIn("design-review", text.rsplit("## Where the page goes", 1)[0][-800:])

    def test_readme_says_three_roles_and_a_critic(self):
        readme = (REPO / "README.md").read_text()
        part = readme.split("### design-review:", 1)[1].split("### ", 1)[0]
        for needle in ("Careful", "Step up", "Bold", "scored"):
            with self.subTest(needle=needle):
                self.assertIn(needle, part)


class BrandKept(unittest.TestCase):
    """Task 6b: the designer keeps a site's branding intact unless the user asks for a rebrand."""

    def step(self, heading):
        return " ".join(section("design-review", heading).split())

    def rubric(self):
        return " ".join((REPO / "reference" / "design-rubric.md").read_text().split())

    def test_brand_elements_are_named_and_kept_exactly(self):
        text = self.step("3.")
        for needle in ("**Keep the brand exactly as it is.**", "logo", "wordmark", "company name", "product names",
                       "brand colors", "tagline", "never redrawn, recolored, simplified or replaced by a text stand-in"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_every_role_keeps_the_brand_and_bold_changes_only_around_it(self):
        text = self.step("3.")
        self.assertIn("Careful, Step up and Bold all keep the brand", text)
        self.assertIn("Bold may change everything around it", text)
        self.assertIn("Bold may change everything around it", self.rubric())

    def test_inventory_marks_brand_rows(self):
        self.assertIn('`"brand": true`', self.step("3."))
        doc = " ".join((REPO / "reference" / "review-page.md").read_text().split())
        self.assertIn("`brand`", doc)
        self.assertIn("Brand", doc)

    def test_brand_loss_is_care_1_and_a_failure_not_a_carve_out(self):
        text = self.rubric()
        self.assertIn("a brand element removed or changed scores `care` 1", text.lower())
        self.assertIn("fails the option whatever its other scores", text)
        self.assertIn("never a carve-out", text)
        self.assertNotIn("a brand break scores `fit` 2 or below", text)
        bar = self.step("4.").split("**The bar.**", 1)[1]
        self.assertIn("brand element", bar)
        self.assertIn("never a carve-out", bar)

    def test_logo_not_found_falls_back_to_the_capture_crop(self):
        text = self.step("3.")
        for needle in ("cannot be found in the project", "on the page and in chat", "crop", "never invent one",
                       "`logo.file`", "`<name>-logo-<width>.png`", "Put that crop in `assets`",
                       "counts as the site's own logo", "When `logo` is `null`, show the header's part shot as is",
                       "never a typed stand-in"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_keep_the_best_one_never_publishes_a_lost_brand(self):
        needle = "an option that lost the brand is never published"
        self.assertIn("except a brand failure (care 1): put the brand back first; " + needle, self.rubric())
        bar = self.step("4.").split("**The bar.**", 1)[1]
        self.assertIn("put the brand back first", bar)
        self.assertIn(needle, bar)

    def test_rebrand_request_is_the_only_exception(self):
        self.assertIn("rebrand", self.step("3."))
        self.assertIn("rebrand", self.rubric())


class FinalReviewGuidance(unittest.TestCase):
    """The final whole-branch review's wording fixes (1.7.0)."""

    def rubric(self):
        return " ".join((REPO / "reference" / "design-rubric.md").read_text().split())

    def step(self, heading):
        return " ".join(section("design-review", heading).split())

    def test_bold_palette_is_carved_out_of_fit(self):
        text = self.rubric()
        fit = text.split("### `fit`", 1)[1].split("### `care`", 1)[0]
        for needle in ("the site's own palette, its style guide or the profile's Love references",
                       "clash with the brand or the profile", "recolor a brand color"):
            with self.subTest(needle=needle):
                self.assertIn(needle, fit)
        self.assertNotIn("brings colors, fonts or a button style the site does not use", fit)
        roles = text.split("## The three roles", 1)[1].split("## The bar", 1)[0]
        self.assertIn("new colors only from the site's own palette, its style guide or the profile's Love references",
                      roles)
        self.assertIn("new colors only from the site's own palette, its style guide or the profile's Love references",
                      self.step("3."))

    def test_step_up_when_careful_is_already_5_and_a_trade_for_the_target(self):
        roles = self.rubric().split("## The three roles", 1)[1].split("## The bar", 1)[0]
        self.assertIn('drop Step up with the reason "Careful already at 5"', roles)
        self.assertIn("rises by 2 or more", roles)
        self.assertIn("one criterion may drop by one point", roles)

    def test_before_sections_come_from_measures_not_copied(self):
        text = self.step("3.")
        self.assertIn('"before_sections": {"from": ".proofs/capture/before/measures.json"', text)
        self.assertIn('"before_font_sizes": {"from":', text)
        self.assertIn("never copy", text)

    def test_unscored_recommendation_error_matches_the_code(self):
        text = self.step("4.")
        self.assertIn("recommending one is a build error when the item has two or more options", text)
        self.assertNotIn("with it set, an option without scores shows \"Not scored\" and recommending one is a build error.",
                         text)

    def test_near_copy_problem_is_for_two_or_more_options_only(self):
        text = " ".join((REPO / "skills" / "design-review" / "SKILL.md").read_text().split())
        self.assertIn("on an item with two or more options, that stays a problem line, not a note", text)
        self.assertIn("A near-copy of the current page on a one-option fix (one proposal, or exactly one variant) "
                      "is a note instead (Ruling 30)", text)
        self.assertIn("a near-copy on an item with two or more options)", text)
        self.assertNotIn("(0.91)`: that stays a problem line, not a note.", text)

    def test_profile_offer_is_one_line_and_pages_only_on_yes(self):
        text = self.step("1.")
        self.assertIn("offer in one line to create one", text)
        self.assertIn("build the questions pages only if the reader says yes", text)
        self.assertIn("in `claude -p`, just the one line", text)

    def test_logo_crop_with_an_error_is_treated_as_null(self):
        self.assertIn("`logo.file` is `null` with an `error`", self.step("3."))

    def test_visual_qa_lists_the_logo_crop_and_new_fields(self):
        text = " ".join((REPO / "skills" / "visual-qa" / "SKILL.md").read_text().split())
        for needle in ("`<page>-logo-<width>.png`", "`sections`", "`fontSizes`", "`logo`"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)


class SkillsReadSettings(unittest.TestCase):
    READ = "python3 ${CLAUDE_PLUGIN_ROOT}/shared/settings.py --print"
    SKILL_WORDS = {
        "design-review": ("the port", "the spend cap", "the option count", "the critic", "the correction passes", "the design profile path"),
        "visual-qa": ("the port", "the smallest text", "the smallest tap target", "the mockups per item"),
        "pr-qa": ("the port", "the before-shot port", "the base folder", "the visual paths"),
        "photo-picker": ("the candidate count",),
        "review-cycle": ("the checkpoint count",),
        "changelog": ("the changelog folder",),
        "todos": ("the to-do file", "the to-do archive folder"),
        "style-guide": ("the style guide file", "the design profile path"),
    }

    def text(self, rel):
        return " ".join((REPO / rel).read_text().split())

    def test_every_skill_using_a_setting_reads_settings_first(self):
        for skill, words in self.SKILL_WORDS.items():
            with self.subTest(skill=skill):
                text = self.text(f"skills/{skill}/SKILL.md")
                self.assertIn("Read the settings: `" + self.READ + "`", text)
                self.assertIn("(pre-approved)", text)
                for word in words:
                    self.assertIn("*" + word + "*", text)
                # it comes before the first numbered or lettered step
                self.assertLess(text.index(self.READ), text.index("## ", text.index(self.READ)))

    def test_cap_is_one_setting_stated_in_house_rules(self):
        rules = self.text("reference/house-rules.md")
        self.assertIn("PROOFS_COST_CAP_USD", rules)
        self.assertIn("estimate", rules)
        for path in sorted((REPO / "skills").glob("*/SKILL.md")):
            for m in re.finditer(r"\$\d+", path.read_text()):
                with self.subTest(skill=path.parent.name):
                    around = path.read_text()[max(0, m.start() - 12):m.end() + 2]
                    self.assertIn("default " + m.group(0), around)

    def test_where_the_page_goes_has_no_claude_md_fallback(self):
        for path in guidance_files():
            with self.subTest(path=path.name):
                self.assertNotIn("proofs pages: file", path.read_text())

    def test_design_review_option_count_and_passes_read_settings(self):
        text = self.text("skills/design-review/SKILL.md")
        self.assertIn("option count setting (default 3)", text)
        self.assertIn("with 2, use Careful and Step up", text)
        self.assertIn("correction passes setting (default 1; 0 means none)", text)
        self.assertIn("critic setting (default `helper`)", text)
        self.assertIn("use the setting's value in its place", text)
        self.assertNotIn("at most one correction pass.**", text)

    def test_correction_passes_setting_drives_the_whole_paragraph(self):
        for rel in ("skills/design-review/SKILL.md", "reference/design-rubric.md"):
            text = self.text(rel)
            with self.subTest(rel=rel):
                self.assertNotIn("one correction pass", text)
                self.assertNotIn("revise it once or drop it", text)
                self.assertNotIn("revised once or dropped", text)
        text = self.text("skills/design-review/SKILL.md")
        self.assertIn("With 0, skip the pass", text)
        self.assertIn("`note_html`", text.split("With 0, skip the pass", 1)[1][:400])
        self.assertIn("With 2,** a second fix, rebuild and rescore cycle", text)

    def test_settings_line_names_each_key_and_pr_qa_ports_follow_settings(self):
        for skill, words in self.SKILL_WORDS.items():
            line = [l for l in (REPO / "skills" / skill / "SKILL.md").read_text().splitlines() if l.startswith("Read the settings:")][0]
            with self.subTest(skill=skill):
                self.assertEqual(len(re.findall(r"\*[^*]+\* \(`PROOFS_[A-Z_]+`\)", line)), len(words), line)
        pr = self.text("skills/pr-qa/SKILL.md")
        self.assertNotIn("the ports with free high ones", pr)
        self.assertIn("after shots use the port setting (`PROOFS_PORT`, default 3311), before shots the before-shot port setting (`PROOFS_BASE_PORT`, default 3411)", pr)

    def test_checkpoints_reference_uses_the_setting(self):
        text = self.text("skills/review-cycle/reference/checkpoints.md")
        self.assertIn("PROOFS_CHECKPOINT_ITEMS", text)
        self.assertNotIn("Five items", text)

    def test_other_literals_name_their_setting(self):
        self.assertIn("candidates-per-spot setting (default 3)", self.text("skills/photo-picker/SKILL.md"))
        self.assertIn("checkpoint setting's number of items (default 5)", self.text("skills/review-cycle/SKILL.md"))
        self.assertIn("mockups-per-item setting (default 2)", self.text("skills/visual-qa/SKILL.md"))
        self.assertIn("`PROOFS_SEND_WAIT_MIN`", self.text("reference/review-page.md"))


class RefineGuidance(unittest.TestCase):
    """Refine and Redesign modes (Proofs 1.10.0): the skill text, the rubric and the profile."""

    def skill(self):
        return " ".join((REPO / "skills" / "design-review" / "SKILL.md").read_text().split())

    def rubric(self):
        return " ".join((REPO / "reference" / "design-rubric.md").read_text().split())

    def profile(self):
        return " ".join((REPO / "reference" / "design-profile.md").read_text().split())

    def test_skill_names_both_modes_and_gives_the_mode_rule(self):
        text = self.skill()
        self.assertIn("Refine mode", text)
        self.assertIn("Redesign mode", text)
        self.assertIn("Refine** when the page exists, renders, and the capture shows no blocking flaw", text)
        self.assertIn("without asking for a new layout", text)
        self.assertIn("**Redesign** when the request says redesign", text)
        self.assertIn("Refine: your page works, so these are small changes you can take or leave. Say 'redesign' for full alternatives.", text)
        self.assertIn("`intro_html`", text)
        self.assertIn("In `claude -p`", text)

    def test_refine_capture_takes_the_snapshot(self):
        text = self.skill()
        self.assertIn("--out .proofs/capture/before --sizes 390,1280 --snapshot", text)
        self.assertIn("<name>-snapshot.html", text)

    def test_refine_flow_is_in_order(self):
        text = self.skill()
        sec = text[text.index("### Refine mode"):text.index("### 4. Build the review page")]
        steps = ["**Snapshot.**", "**Write the `changes`.**", "**Critic build.**", "**`--smoke`.**", "**Crops.**",
                 "**Critic.**", "**Rebuild.**", "**Publish.**"]
        pos = 0
        for step in steps:
            with self.subTest(step=step):
                found = sec.find(step, pos)
                self.assertNotEqual(found, -1, step)
                pos = found
        for cmd in ("--snapshot", "review_page.py --smoke .proofs/pages/<review-name>.html",
                    "--crops .proofs/pages/<review-name>.html --out .proofs/design-review/crops"):
            with self.subTest(cmd=cmd):
                self.assertIn(cmd, sec)
        for word in ("`base`", "`crops`", "`targets`", "`css`", "`swaps`", "`removes`", "3 to 8", "`refine`"):
            with self.subTest(word=word):
                self.assertIn(word, text)

    def test_refine_critic_points_at_the_redesign_rules_and_lists_its_inputs(self):
        text = self.skill()
        sec = text[text.index("6. **Critic.**"):text.index("7. **Rebuild.**")]
        self.assertNotIn("Same rules as step 4", sec)   # step 4 of this list is --smoke
        self.assertIn('The Redesign critic\'s rules ("Who scores", in step 4)', sec)
        self.assertIn("crops and `removes` lines only", sec)
        self.assertIn("crops and `removes` lines only", self.rubric())
        for given in ("crops at both widths", "`removes` lines", "`Density:` line", "the `--smoke` output",
                      "the set shots", "the current page's shots at 1280 and 390"):
            with self.subTest(given=given):
                self.assertIn(given, sec)
        self.assertIn("Never `why_html`", sec)
        self.assertNotIn("shots and inventory only", sec)
        self.assertIn("--crops .proofs/pages/<review-name>.html --out .proofs/design-review/crops --set 1,3", sec)
        self.assertIn("`set-1280.png` and `set-390.png`", sec)

    def test_match_preview_uses_the_same_data_as_the_before(self):
        text = self.skill()
        self.assertIn("**Capture the built page from the same input data as the before**", text)
        self.assertIn("When you cannot use the same data, say so in chat", text)
        self.assertIn("mostly text", text)

    def test_apply_step_matches_the_preview_and_states_the_yes_plus_revise_rule(self):
        text = self.skill()
        self.assertIn("--match-preview .proofs/pages/<review-name>.html --picks 1,3 --shots .proofs/capture/after", text)
        self.assertIn("A round with both `YES` and `REVISE`", text)
        self.assertIn("fresh snapshot", text)

    def test_redesign_falls_back_to_refine_and_reads_density(self):
        text = self.skill()
        self.assertIn("offers Refine for the next round", text)
        self.assertIn("Density", text)

    def test_rubric_has_a_refine_section(self):
        text = self.rubric()
        self.assertIn("## Refine mode", text)
        for key in ("gain", "keeps"):
            with self.subTest(key=key):
                self.assertIn(f"`{key}`", text)
        sec = text[text.index("## Refine mode"):]
        for anchor in ("**1**", "**3**", "**5**"):
            self.assertGreaterEqual(sec.count(anchor), 2, anchor)
        self.assertIn("`gain` 3 or more, `keeps` 4 or more, and no failed design check", sec)
        self.assertIn("no worse on any of the six criteria", sec)
        self.assertIn("better on at least one", sec)

    def test_rubric_grouping_and_fit_read_the_density_line(self):
        text = self.rubric()
        for key in ("grouping", "fit"):
            sec = text[text.index(f"### `{key}`") + 5:]
            sec = re.split(r"### |## ", sec)[0]
            with self.subTest(key=key):
                self.assertIn("`Density:` line", sec)

    def test_profile_has_a_density_line_asked_with_audience(self):
        text = self.profile()
        self.assertIn("Density: dense. Many numbers on one screen; people scan, not read. Don't add padding.", text)
        for word in ("`dense`", "`balanced`", "`airy`"):
            self.assertIn(word, text)
        self.assertIn("**Density**, asked next to Audience.", text)
