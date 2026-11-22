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

    def test_chrome_is_set_inside_the_capture_command(self):
        self.assertIn("""-- sh -c 'CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"; "$CHROME" --headless""", self.step2())


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
        self.assertIn("PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm install", src)


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
    def test_pr_qa_base_worktree_lives_under_dot_proofs(self):
        text = section("pr-qa", "The Sequence")
        self.assertIn("git worktree add <base-dir>", text)
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
        self.assertIn("git worktree remove <base-dir>", section("pr-qa", "Common Mistakes"))

    def test_pr_qa_removes_the_base_worktree_before_the_branch_and_its_tests(self):
        text = section("pr-qa", "The Sequence")
        remove = text.index("**Then remove the base worktree at once**")
        self.assertIn("git worktree remove --force <base-dir>", text[remove:remove + 200])
        self.assertLess(text.index("--cwd <base-dir>"), remove)
        self.assertLess(remove, text.index("3. **Run the branch for real**"))
        self.assertLess(remove, text.index("4. **Run the PR's own tests**"))


if __name__ == "__main__":
    unittest.main()
