import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "shared"))
import settings  # noqa: E402

SCRIPT = REPO / "shared" / "settings.py"

EXPECTED_KEYS = {
    "PROOFS_COST_CAP_USD", "PROOFS_PAGES", "PROOFS_SPELLING", "PROOFS_PR_REMINDER",
    "PROOFS_AGENT_BRANCH_PREFIX", "PROOFS_DESIGN_PROFILE", "PROOFS_PORT", "PROOFS_BASE_PORT",
    "PROOFS_SERVER_TIMEOUT", "PROOFS_IMAGE_QUALITY", "PROOFS_IMAGE_MAX_WIDTH",
    "PROOFS_BROWSER_CHANNEL", "PROOFS_PLAYWRIGHT", "PROOFS_BASE_DIR", "PROOFS_MIN_TEXT",
    "PROOFS_MIN_TAP",
    # the maybes, all advanced
    "PROOFS_EXTRA_WIDTHS", "PROOFS_DESIGN_OPTIONS", "PROOFS_CRITIC", "PROOFS_CORRECTION_PASSES",
    "PROOFS_PHOTO_CANDIDATES", "PROOFS_QA_MOCKUPS", "PROOFS_CHECKPOINT_ITEMS",
    "PROOFS_PR_REMINDER_TIMEOUT", "PROOFS_QA_PATHS", "PROOFS_QA_WORKFLOW", "PROOFS_QA_MAP",
    "PROOFS_SEND_WAIT_MIN", "PROOFS_TODO_TITLE", "PROOFS_CHANGELOG_DIR", "PROOFS_TODO_FILE",
    "PROOFS_TODO_ARCHIVE_DIR", "PROOFS_STYLE_GUIDE", "PROOFS_PAGE_WARN_MB",
}


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name).resolve()
        self.home = root / "home"
        self.project = root / "project"
        (self.home / ".claude").mkdir(parents=True)
        (self.project / ".claude").mkdir(parents=True)
        self.sub = self.project / "app" / "deep"
        self.sub.mkdir(parents=True)

    def write(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n")

    def user_file(self):
        return self.home / ".claude" / "settings.json"

    def project_file(self):
        return self.project / ".claude" / "settings.json"

    def local_file(self):
        return self.project / ".claude" / "settings.local.json"

    def kw(self, env=None):
        return {"cwd": self.sub, "env": {} if env is None else env, "home": self.home}

    def run_cli(self, *args, env_extra=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith("PROOFS_") and k != "CLAUDE_CONFIG_DIR"}
        env["HOME"] = str(self.home)
        env.update(env_extra or {})
        return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=str(self.sub), env=env,
                              capture_output=True, text=True)


class TableTest(unittest.TestCase):
    def test_table_has_every_inventory_key(self):
        table = settings.load_table()
        keys = [row["key"] for row in table]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(set(keys), EXPECTED_KEYS)
        for row in table:
            for field in ("label", "help", "group", "scope", "type", "default"):
                self.assertIn(field, row, row["key"])
            self.assertTrue(row["label"].strip() and row["help"].strip(), row["key"])
            self.assertIn(row["group"], ("read", "checks", "app", "prs", "computer"), row["key"])
            self.assertIn(row["scope"], ("user", "project", "local"), row["key"])
            self.assertIn(row["type"], ("int", "choice", "bool", "text", "list", "path", "auto"), row["key"])

    def test_advanced_flag_marks_exactly_the_maybes(self):
        advanced = {row["key"] for row in settings.load_table() if row["advanced"]}
        self.assertEqual(advanced, {
            "PROOFS_EXTRA_WIDTHS", "PROOFS_DESIGN_OPTIONS", "PROOFS_CRITIC", "PROOFS_CORRECTION_PASSES",
            "PROOFS_PHOTO_CANDIDATES", "PROOFS_QA_MOCKUPS", "PROOFS_CHECKPOINT_ITEMS",
            "PROOFS_PR_REMINDER_TIMEOUT", "PROOFS_QA_PATHS", "PROOFS_QA_WORKFLOW", "PROOFS_QA_MAP",
            "PROOFS_SEND_WAIT_MIN", "PROOFS_TODO_TITLE", "PROOFS_CHANGELOG_DIR", "PROOFS_TODO_FILE",
            "PROOFS_TODO_ARCHIVE_DIR", "PROOFS_STYLE_GUIDE", "PROOFS_PAGE_WARN_MB"})

    def test_mockup_wording_and_floors(self):
        rows = {r["key"]: r for r in settings.load_table()}
        self.assertEqual(rows["PROOFS_SPELLING"]["label"], "Spelling check")
        self.assertEqual(rows["PROOFS_MIN_TEXT"]["label"], "Smallest text")
        self.assertEqual(rows["PROOFS_MIN_TEXT"]["default"], 16)
        self.assertTrue(rows["PROOFS_MIN_TEXT"]["raise_only"])
        self.assertEqual(rows["PROOFS_MIN_TAP"]["default"], 44)
        self.assertEqual(rows["PROOFS_MIN_TAP"]["max"], 96)
        self.assertEqual(rows["PROOFS_COST_CAP_USD"]["unit"], "$ est.")
        self.assertEqual(rows["PROOFS_SEND_WAIT_MIN"]["scope"], "user")
        self.assertEqual(rows["PROOFS_PAGE_WARN_MB"]["scope"], "user")
        self.assertEqual(rows["PROOFS_BASE_DIR"]["scope"], "local")

    def test_every_default_passes_its_own_validation(self):
        for row in settings.load_table():
            d = row["default"]
            raw = ",".join(str(x) for x in d) if isinstance(d, list) else ("1" if d is True else "0" if d is False else str(d))
            if raw == "":
                continue
            self.assertEqual(settings.validate(row["key"], raw), d, row["key"])


class ResolveTest(Base):
    def test_default_when_nothing_set(self):
        self.assertEqual(settings.get("PROOFS_PORT", **self.kw()), 3311)
        eff = settings.effective(**self.kw())["PROOFS_PORT"]
        self.assertEqual(eff["source"], "default")
        self.assertEqual(eff["value"], 3311)
        self.assertEqual(eff["default"], 3311)
        self.assertFalse(eff["note"])

    def test_typed_values(self):
        self.write(self.project_file(), {"env": {
            "PROOFS_PR_REMINDER": "1", "PROOFS_AGENT_BRANCH_PREFIX": "claude/, codex/",
            "PROOFS_EXTRA_WIDTHS": "1024,768", "PROOFS_DESIGN_OPTIONS": "2", "PROOFS_PAGES": "file"}})
        kw = self.kw()
        self.assertIs(settings.get("PROOFS_PR_REMINDER", **kw), True)
        self.assertEqual(settings.get("PROOFS_AGENT_BRANCH_PREFIX", **kw), ["claude/", "codex/"])
        self.assertEqual(settings.get("PROOFS_EXTRA_WIDTHS", **kw), [1024, 768])
        self.assertEqual(settings.get("PROOFS_DESIGN_OPTIONS", **kw), 2)
        self.assertEqual(settings.get("PROOFS_PAGES", **kw), "file")
        self.assertEqual(settings.get("PROOFS_AGENT_BRANCH_PREFIX", **self.kw()) , ["claude/", "codex/"])

    def test_file_order(self):
        kw = self.kw({"PROOFS_PORT": "3500"})
        self.assertEqual(settings.effective(**kw)["PROOFS_PORT"]["source"], "environment")
        self.write(self.user_file(), {"env": {"PROOFS_PORT": "3600"}})
        self.assertEqual(settings.get("PROOFS_PORT", **kw), 3600)
        self.assertEqual(settings.effective(**kw)["PROOFS_PORT"]["source"], "user")
        self.write(self.project_file(), {"env": {"PROOFS_PORT": "3700"}})
        self.assertEqual(settings.get("PROOFS_PORT", **kw), 3700)
        self.assertEqual(settings.effective(**kw)["PROOFS_PORT"]["source"], "project")
        self.write(self.local_file(), {"env": {"PROOFS_PORT": "3800"}})
        self.assertEqual(settings.get("PROOFS_PORT", **kw), 3800)
        self.assertEqual(settings.effective(**kw)["PROOFS_PORT"]["source"], "local")

    def test_file_beats_stale_env(self):
        self.write(self.project_file(), {"env": {"PROOFS_PORT": "3099"}})
        kw = self.kw({"PROOFS_PORT": "3311"})
        self.assertEqual(settings.get("PROOFS_PORT", **kw), 3099)
        eff = settings.effective(**kw)["PROOFS_PORT"]
        self.assertEqual(eff["value"], 3099)
        self.assertIn("restart", eff["note"].lower())
        self.assertIn("restart Claude Code to pass the new value to hooks", eff["note"])

    def test_no_note_when_env_matches_the_file(self):
        self.write(self.project_file(), {"env": {"PROOFS_PORT": "3099"}})
        eff = settings.effective(**self.kw({"PROOFS_PORT": "3099"}))["PROOFS_PORT"]
        self.assertFalse(eff["note"])

    def test_project_root_is_the_nearest_folder_with_claude_or_git(self):
        self.write(self.project_file(), {"env": {"PROOFS_PORT": "3099"}})
        self.assertEqual(settings.get("PROOFS_PORT", **self.kw()), 3099)
        # a nearer .git folder becomes the root, so the outer file no longer applies
        (self.project / "app" / ".git").mkdir()
        self.assertEqual(settings.get("PROOFS_PORT", **self.kw()), 3311)

    def test_home_is_never_the_project(self):
        self.write(self.user_file(), {"env": {"PROOFS_PORT": "3600"}})
        eff = settings.effective(cwd=self.home / "elsewhere", env={}, home=self.home)["PROOFS_PORT"]
        self.assertEqual((eff["value"], eff["source"]), (3600, "user"))

    def test_claude_config_dir_is_the_user_file(self):
        cfg = self.home.parent / "cfg"
        self.write(cfg / "settings.json", {"env": {"PROOFS_PORT": "3650"}})
        self.write(self.user_file(), {"env": {"PROOFS_PORT": "3600"}})
        kw = self.kw({"CLAUDE_CONFIG_DIR": str(cfg)})
        self.assertEqual(settings.get("PROOFS_PORT", **kw), 3650)
        path = settings.set_value("PROOFS_COST_CAP_USD", "7", cwd=self.sub, home=self.home,
                                  env={"CLAUDE_CONFIG_DIR": str(cfg)})
        self.assertEqual(path, cfg / "settings.json")
        self.assertEqual(json.loads((cfg / "settings.json").read_text())["env"]["PROOFS_COST_CAP_USD"], "7")

    def test_invalid_stored_value_is_skipped_with_a_note(self):
        self.write(self.user_file(), {"env": {"PROOFS_PORT": "3600"}})
        self.write(self.project_file(), {"env": {"PROOFS_PORT": "99999"}})
        eff = settings.effective(**self.kw())["PROOFS_PORT"]
        self.assertEqual((eff["value"], eff["source"]), (3600, "user"))
        self.assertIn("99999", eff["note"])

    def test_json_output_shape(self):
        self.write(self.project_file(), {"env": {"PROOFS_PORT": "3099"}})
        r = self.run_cli("--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(set(data), EXPECTED_KEYS)
        for entry in data.values():
            self.assertEqual(set(entry), {"value", "source", "default", "note"})
        self.assertEqual(data["PROOFS_PORT"]["value"], 3099)
        self.assertEqual(data["PROOFS_PORT"]["source"], "project")
        self.assertEqual(data["PROOFS_PORT"]["default"], 3311)

    def test_print_is_a_human_table(self):
        self.write(self.project_file(), {"env": {"PROOFS_PORT": "3099"}})
        r = self.run_cli("--print")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Running the app", r.stdout)
        self.assertIn("PROOFS_PORT", r.stdout)
        self.assertIn("3099", r.stdout)
        self.assertIn("project", r.stdout)


class ValidateTest(unittest.TestCase):
    def test_raise_only_floor(self):
        with self.assertRaises(settings.SettingError) as cm:
            settings.validate("PROOFS_MIN_TEXT", "14")
        self.assertIn("can only go up from 16", str(cm.exception))
        self.assertEqual(settings.validate("PROOFS_MIN_TEXT", "18"), 18)
        self.assertEqual(settings.validate("PROOFS_MIN_TEXT", "16"), 16)
        with self.assertRaises(settings.SettingError) as cm:
            settings.validate("PROOFS_MIN_TAP", "40")
        self.assertIn("can only go up from 44", str(cm.exception))
        with self.assertRaises(settings.SettingError):
            settings.validate("PROOFS_MIN_TAP", "97")
        with self.assertRaises(settings.SettingError):
            settings.validate("PROOFS_MIN_TEXT", "33")

    def test_rejects_bad_values(self):
        for key, raw in [("PROOFS_PORT", "99999"), ("PROOFS_PORT", "80"), ("PROOFS_IMAGE_QUALITY", "0"),
                         ("PROOFS_IMAGE_QUALITY", "abc"), ("PROOFS_DESIGN_OPTIONS", "4"),
                         ("PROOFS_EXTRA_WIDTHS", "300"), ("PROOFS_EXTRA_WIDTHS", "1024,abc"),
                         ("PROOFS_PAGES", "carrier-pigeon"), ("PROOFS_SPELLING", "british"),
                         ("PROOFS_PR_REMINDER", "maybe"), ("PROOFS_COST_CAP_USD", "101"),
                         ("PROOFS_COST_CAP_USD", "2.5"), ("PROOFS_AGENT_BRANCH_PREFIX", " , "),
                         ("PROOFS_DESIGN_PROFILE", ""), ("PROOFS_SERVER_TIMEOUT", "9")]:
            with self.assertRaises(settings.SettingError, msg="%s=%r" % (key, raw)):
                settings.validate(key, raw)

    def test_unknown_key(self):
        with self.assertRaises(settings.SettingError):
            settings.validate("PROOFS_NOPE", "1")

    def test_accepts_good_values(self):
        self.assertEqual(settings.validate("PROOFS_PORT", "3099"), 3099)
        self.assertEqual(settings.validate("PROOFS_PAGES", "wifi"), "wifi")
        self.assertIs(settings.validate("PROOFS_PR_REMINDER", "1"), True)
        self.assertIs(settings.validate("PROOFS_PR_REMINDER", "off"), False)
        self.assertEqual(settings.validate("PROOFS_EXTRA_WIDTHS", "1024, 768"), [1024, 768])
        self.assertEqual(settings.validate("PROOFS_EXTRA_WIDTHS", ""), [])
        self.assertEqual(settings.validate("PROOFS_AGENT_BRANCH_PREFIX", "claude/,codex/"), ["claude/", "codex/"])
        self.assertEqual(settings.validate("PROOFS_BROWSER_CHANNEL", "chrome"), "chrome")
        self.assertEqual(settings.validate("PROOFS_BROWSER_CHANNEL", "auto"), "auto")


class WriteTest(Base):
    def test_set_keeps_other_keys(self):
        original = {"permissions": {"allow": ["Bash(ls)"]}, "hooks": {"SessionStart": [{"hooks": []}]},
                    "env": {"FOO": "bar", "PROOFS_PAGES": "file"}, "model": "opus"}
        self.write(self.project_file(), original)
        r = self.run_cli("--set", "PROOFS_PORT=3099")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(self.project_file().read_text())
        expected = json.loads(json.dumps(original))
        expected["env"]["PROOFS_PORT"] = "3099"
        self.assertEqual(data, expected)
        self.assertEqual(list(data), list(original))

    def test_set_creates_missing_file_and_env_block(self):
        path = settings.set_value("PROOFS_PORT", "3099", cwd=self.sub, home=self.home, env={})
        self.assertEqual(path, self.project_file())
        self.assertEqual(json.loads(path.read_text()), {"env": {"PROOFS_PORT": "3099"}})
        self.write(self.local_file(), {"model": "opus"})
        settings.set_value("PROOFS_BASE_DIR", "/tmp/base", cwd=self.sub, home=self.home, env={})
        self.assertEqual(json.loads(self.local_file().read_text()),
                         {"model": "opus", "env": {"PROOFS_BASE_DIR": "/tmp/base"}})

    def test_set_uses_the_table_scope_and_an_override(self):
        self.assertEqual(settings.set_value("PROOFS_COST_CAP_USD", "8", cwd=self.sub, home=self.home, env={}),
                         self.user_file())
        self.assertEqual(settings.set_value("PROOFS_COST_CAP_USD", "9", "project", cwd=self.sub, home=self.home, env={}),
                         self.project_file())
        self.assertEqual(settings.set_value("PROOFS_COST_CAP_USD", "6", "local", cwd=self.sub, home=self.home, env={}),
                         self.local_file())
        r = self.run_cli("--set", "PROOFS_SPELLING=american", "--scope", "user")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(self.user_file().read_text())["env"]["PROOFS_SPELLING"], "american")

    def test_set_stores_canonical_strings(self):
        settings.set_value("PROOFS_PR_REMINDER", "on", cwd=self.sub, home=self.home, env={})
        settings.set_value("PROOFS_EXTRA_WIDTHS", "1024, 768", cwd=self.sub, home=self.home, env={})
        env = json.loads(self.project_file().read_text())["env"]
        self.assertEqual(env["PROOFS_PR_REMINDER"], "1")
        self.assertEqual(env["PROOFS_EXTRA_WIDTHS"], "1024,768")

    def test_set_visible_to_get_with_a_stale_env(self):
        settings.set_value("PROOFS_PORT", "3099", cwd=self.sub, home=self.home, env={})
        self.assertEqual(settings.get("PROOFS_PORT", **self.kw({"PROOFS_PORT": "3311"})), 3099)

    def test_set_refuses_non_proofs_key(self):
        before = None
        r = self.run_cli("--set", "PATH=/evil")
        self.assertEqual(r.returncode, 2)
        self.assertFalse(self.project_file().exists())
        r = self.run_cli("--set", "PROOFS_NOT_A_SETTING=1")
        self.assertEqual(r.returncode, 2)
        with self.assertRaises(settings.SettingError):
            settings.set_value("ANTHROPIC_API_KEY", "x", cwd=self.sub, home=self.home, env={})
        self.assertIsNone(before)

    def test_set_rejects_invalid_value_exit_2_and_writes_nothing(self):
        r = self.run_cli("--set", "PROOFS_PORT=99999")
        self.assertEqual(r.returncode, 2)
        self.assertIn("1024", r.stderr)
        self.assertFalse(self.project_file().exists())
        r = self.run_cli("--set", "PROOFS_MIN_TEXT=14")
        self.assertEqual(r.returncode, 2)
        self.assertIn("can only go up from 16", r.stderr)

    def test_invalid_json_exit_3_untouched(self):
        self.project_file().write_text('{"env": {"PROOFS_PORT": "3099",}\n')
        before = self.project_file().read_bytes()
        r = self.run_cli("--set", "PROOFS_PORT=3100")
        self.assertEqual(r.returncode, 3)
        self.assertEqual(self.project_file().read_bytes(), before)
        r = self.run_cli("--unset", "PROOFS_PORT")
        self.assertEqual(r.returncode, 3)
        self.assertEqual(self.project_file().read_bytes(), before)
        r = self.run_cli("--print")
        self.assertEqual(r.returncode, 3)

    def test_unset_removes_only_that_key(self):
        self.write(self.project_file(), {"permissions": {"allow": []}, "env": {"PROOFS_PORT": "3099", "FOO": "1",
                                                                           "PROOFS_PAGES": "file"}})
        r = self.run_cli("--unset", "PROOFS_PORT")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(self.project_file().read_text()),
                         {"permissions": {"allow": []}, "env": {"FOO": "1", "PROOFS_PAGES": "file"}})

    def test_unset_of_a_missing_key_or_file_changes_nothing(self):
        r = self.run_cli("--unset", "PROOFS_PORT")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(self.project_file().exists())
        self.write(self.project_file(), {"env": {"FOO": "1"}})
        before = self.project_file().read_bytes()
        self.run_cli("--unset", "PROOFS_PORT")
        self.assertEqual(self.project_file().read_bytes(), before)

    def test_unset_refuses_non_proofs_key(self):
        self.write(self.project_file(), {"env": {"FOO": "1"}})
        r = self.run_cli("--unset", "FOO")
        self.assertEqual(r.returncode, 2)
        self.assertEqual(json.loads(self.project_file().read_text()), {"env": {"FOO": "1"}})

    def test_cli_rejects_bad_usage(self):
        self.assertEqual(self.run_cli("--set", "PROOFS_PORT").returncode, 2)
        self.assertEqual(self.run_cli("--set", "PROOFS_PORT=3099", "--scope", "galaxy").returncode, 2)
        self.assertEqual(self.run_cli().returncode, 2)

    def test_env_block_of_the_wrong_type_is_an_unreadable_file(self):
        self.project_file().write_text('{"env": ["x"]}\n')
        before = self.project_file().read_bytes()
        r = self.run_cli("--set", "PROOFS_PORT=3100")
        self.assertEqual(r.returncode, 3)
        self.assertEqual(self.project_file().read_bytes(), before)


class ApplyTest(Base):
    """--apply: the rows the settings page saved, written into the settings files."""

    def rows_dir(self, *rows):
        d = self.home.parent / "rows"
        (d / "proofs-answers").mkdir(parents=True, exist_ok=True)
        for r in rows:
            body = {"id": r["id"], "data": dict({"section": "settings", "kind": "setting", "scope": "project",
                                                 "note": "", "updated_at": "2026-11-26T12:00:00Z"}, **r),
                    "version": 1}
            (d / "proofs-answers" / ("%s.json" % r["id"])).write_text(json.dumps(body))
        return d

    def test_apply_applies_and_reports(self):
        rows = self.rows_dir(
            {"id": "PROOFS_PORT", "answer": "3099", "from": "3311", "scope": "project"},
            {"id": "PROOFS_PAGES", "answer": "file", "from": "artifact", "scope": "user"})
        r = self.run_cli("--apply", str(rows))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("APPLIED PROOFS_PORT 3311 \u2192 3099 (project %s)" % self.project_file(), r.stdout)
        self.assertIn("APPLIED PROOFS_PAGES artifact \u2192 file (user ", r.stdout)
        self.assertEqual(json.loads(self.project_file().read_text())["env"], {"PROOFS_PORT": "3099"})
        self.assertEqual(json.loads((self.home / ".claude" / "settings.json").read_text())["env"],
                         {"PROOFS_PAGES": "file"})

    def test_apply_skips_stale_from_and_invalid(self):
        self.write(self.project_file(), {"env": {"PROOFS_PORT": "4000"}})
        rows = self.rows_dir(
            {"id": "PROOFS_PORT", "answer": "3099", "from": "3311", "scope": "project"},
            {"id": "PROOFS_MIN_TEXT", "answer": "14", "from": "16", "scope": "project"},
            {"id": "PROOFS_BASE_PORT", "answer": "3500", "from": "3411", "scope": "project"})
        r = self.run_cli("--apply", str(rows))
        self.assertEqual(r.returncode, 1)
        self.assertIn("SKIPPED PROOFS_PORT:", r.stdout)
        self.assertIn("4000", r.stdout)
        self.assertIn("SKIPPED PROOFS_MIN_TEXT:", r.stdout)
        self.assertIn("can only go up", r.stdout)
        self.assertIn("APPLIED PROOFS_BASE_PORT 3411 \u2192 3500", r.stdout)
        env = json.loads(self.project_file().read_text())["env"]
        self.assertEqual(env, {"PROOFS_PORT": "4000", "PROOFS_BASE_PORT": "3500"})

    def test_apply_ignores_undone_rows_and_other_kinds(self):
        rows = self.rows_dir({"id": "PROOFS_PORT", "answer": None, "from": "3311"},
                             {"id": "some-question", "kind": "pick", "answer": "A"})
        r = self.run_cli("--apply", str(rows))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("SKIPPED", r.stdout)
        self.assertNotIn("APPLIED", r.stdout)
        self.assertFalse(self.project_file().exists())

    def test_apply_unknown_key_is_skipped(self):
        rows = self.rows_dir({"id": "PROOFS_NOPE", "answer": "1", "from": "0"})
        r = self.run_cli("--apply", str(rows))
        self.assertEqual(r.returncode, 1)
        self.assertIn("SKIPPED PROOFS_NOPE:", r.stdout)

    def test_apply_dry_run_writes_nothing(self):
        rows = self.rows_dir({"id": "PROOFS_PORT", "answer": "3099", "from": "3311"},
                             {"id": "PROOFS_BASE_PORT", "answer": "x", "from": "3411"})
        r = self.run_cli("--apply", str(rows), "--dry-run")
        self.assertEqual(r.returncode, 1)
        self.assertIn("WOULD APPLY PROOFS_PORT 3311 \u2192 3099", r.stdout)
        self.assertIn("SKIPPED PROOFS_BASE_PORT:", r.stdout)
        self.assertNotIn("APPLIED", r.stdout)
        self.assertFalse(self.project_file().exists())

    def test_apply_reads_the_rows_folder_itself_or_its_parent(self):
        rows = self.rows_dir({"id": "PROOFS_PORT", "answer": "3099", "from": "3311"})
        r = self.run_cli("--apply", str(rows / "proofs-answers"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("APPLIED PROOFS_PORT", r.stdout)

    def test_spec_out_writes_the_spec_to_a_file(self):
        target = self.project / ".proofs" / "settings" / "spec.json"
        r = self.run_cli("--spec", "--out", str(target))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(target.read_text())["mode"], "settings")
        self.assertEqual(self.run_cli("--print", "--out", str(target)).returncode, 2)

    def test_dry_run_needs_apply_and_missing_folder_exits_2(self):
        self.assertEqual(self.run_cli("--print", "--dry-run").returncode, 2)
        self.assertEqual(self.run_cli("--apply", "/no/such/folder").returncode, 2)


class FinalReviewTest(Base):
    """The fixes from the final whole-branch review."""

    rows_dir = ApplyTest.rows_dir

    # 1. A write a narrower file still overrides is not reported as applied.
    def test_apply_reports_a_change_a_narrower_file_still_overrides(self):
        self.write(self.project_file(), {"env": {"PROOFS_PAGES": "file"}})
        rows = self.rows_dir({"id": "PROOFS_PAGES", "answer": "wifi", "from": "file", "scope": "user"})
        r = self.run_cli("--apply", str(rows))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("SKIPPED PROOFS_PAGES: still overridden by project file (%s)" % self.project_file(), r.stdout)
        self.assertNotIn("APPLIED", r.stdout)
        self.assertEqual(settings.get("PROOFS_PAGES", **self.kw()), "file")

    def test_dry_run_reports_the_override_too_and_writes_nothing(self):
        self.write(self.local_file(), {"env": {"PROOFS_PORT": "5000"}})
        rows = self.rows_dir({"id": "PROOFS_PORT", "answer": "3099", "from": "5000", "scope": "project"})
        r = self.run_cli("--apply", str(rows), "--dry-run")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("SKIPPED PROOFS_PORT: still overridden by local file (%s)" % self.local_file(), r.stdout)
        self.assertFalse(self.project_file().exists())

    def test_an_override_holding_the_same_value_is_applied(self):
        self.write(self.project_file(), {"env": {"PROOFS_PAGES": "wifi"}})
        self.write(self.user_file(), {"env": {"PROOFS_PAGES": "file"}})
        rows = self.rows_dir({"id": "PROOFS_PAGES", "answer": "wifi", "from": "wifi", "scope": "user"})
        r = self.run_cli("--apply", str(rows))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("APPLIED PROOFS_PAGES", r.stdout)

    # 2. Resetting an `auto` setting, or the pr-qa base folder, removes the key.
    def test_set_auto_removes_the_key(self):
        self.write(self.local_file(), {"permissions": {"allow": []},
                                       "env": {"PROOFS_BROWSER_CHANNEL": "chrome", "PROOFS_PORT": "4000"}})
        settings.set_value("PROOFS_BROWSER_CHANNEL", "auto", **self.kw())
        data = json.loads(self.local_file().read_text())
        self.assertEqual(data["env"], {"PROOFS_PORT": "4000"})
        self.assertEqual(data["permissions"], {"allow": []})
        self.assertEqual(settings.get("PROOFS_BROWSER_CHANNEL", **self.kw()), "auto")

    def test_set_auto_on_a_missing_file_writes_nothing(self):
        settings.set_value("PROOFS_PLAYWRIGHT", "auto", **self.kw())
        self.assertFalse(self.local_file().exists())

    def test_cli_set_auto_says_it_removed_the_key(self):
        self.write(self.local_file(), {"env": {"PROOFS_BROWSER_CHANNEL": "chrome"}})
        r = self.run_cli("--set", "PROOFS_BROWSER_CHANNEL=auto")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("PROOFS_BROWSER_CHANNEL reset to auto (removed from %s)" % self.local_file(), r.stdout)

    def test_base_dir_default_removes_the_key_and_others_must_be_absolute(self):
        self.write(self.local_file(), {"env": {"PROOFS_BASE_DIR": "/srv/base"}})
        settings.set_value("PROOFS_BASE_DIR", ".proofs/base", **self.kw())
        self.assertEqual(json.loads(self.local_file().read_text())["env"], {})
        self.assertEqual(settings.validate("PROOFS_BASE_DIR", "/tmp/qa"), "/tmp/qa")
        for bad in ("relative/base", "~/base", "base"):
            with self.subTest(bad=bad), self.assertRaises(settings.SettingError) as cm:
                settings.validate("PROOFS_BASE_DIR", bad)
            self.assertEqual(str(cm.exception),
                             "pr-qa base folder must be an absolute folder path (starting with /), or .proofs/base.")

    def test_apply_reset_of_auto_reports_removed(self):
        self.write(self.local_file(), {"env": {"PROOFS_BROWSER_CHANNEL": "chrome"}})
        rows = self.rows_dir({"id": "PROOFS_BROWSER_CHANNEL", "answer": "auto", "from": "chrome", "scope": "local"})
        r = self.run_cli("--apply", str(rows))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("APPLIED PROOFS_BROWSER_CHANNEL chrome \u2192 auto (removed from local %s)" % self.local_file(),
                      r.stdout)
        self.assertEqual(json.loads(self.local_file().read_text())["env"], {})

    def test_reset_that_leaves_a_broader_file_in_charge_is_reported(self):
        self.write(self.user_file(), {"env": {"PROOFS_BROWSER_CHANNEL": "chrome"}})
        self.write(self.local_file(), {"env": {"PROOFS_BROWSER_CHANNEL": "msedge"}})
        rows = self.rows_dir({"id": "PROOFS_BROWSER_CHANNEL", "answer": "auto", "from": "msedge", "scope": "local"})
        for extra in (["--dry-run"], []):
            r = self.run_cli("--apply", str(rows), *extra)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn("SKIPPED PROOFS_BROWSER_CHANNEL: still overridden by user file (%s)" % self.user_file(),
                          r.stdout)

    # 3. A symlinked settings file is written through, not replaced.
    def test_set_writes_through_a_symlinked_settings_file(self):
        dotfiles = self.home / "dotfiles"
        dotfiles.mkdir()
        target = dotfiles / "claude-settings.json"
        target.write_text(json.dumps({"model": "x"}, indent=2) + "\n")
        os.chmod(target, 0o600)
        link = self.user_file()
        link.symlink_to(target)
        settings.set_value("PROOFS_PAGES", "file", **self.kw())
        self.assertTrue(link.is_symlink())
        self.assertEqual(json.loads(target.read_text()), {"model": "x", "env": {"PROOFS_PAGES": "file"}})
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        settings.unset("PROOFS_PAGES", **self.kw())
        self.assertTrue(link.is_symlink())
        self.assertEqual(json.loads(target.read_text())["env"], {})

    # 4. A row with no `from` is skipped.
    def test_apply_skips_a_row_with_no_from(self):
        rows = self.rows_dir({"id": "PROOFS_PORT", "answer": "3099"})
        r = self.run_cli("--apply", str(rows))
        self.assertEqual(r.returncode, 1)
        self.assertIn("SKIPPED PROOFS_PORT: no shown value; reopen the page.", r.stdout)
        self.assertFalse(self.project_file().exists())

    # 5. One spend cap for every skill.
    def test_cost_cap_wording(self):
        row = settings._row("PROOFS_COST_CAP_USD")
        self.assertEqual(row["label"], "Spend cap per run")
        self.assertEqual(row["help"], "An estimate Claude plans around, not a hard stop. Every skill stays under it.")

    # 6. Control characters, `..` and absolute paths.
    def test_control_characters_are_refused_in_every_value(self):
        for row in settings.load_table():
            for bad in ("x\ny", "x\ty", "x\x00", "5\n", "\x1b[31m"):
                with self.subTest(key=row["key"], bad=bad), self.assertRaises(settings.SettingError) as cm:
                    settings.validate(row["key"], bad)
                self.assertEqual(str(cm.exception),
                                 "%s cannot contain control characters such as a line break." % row["label"])

    def test_project_paths_stay_inside_the_project(self):
        keys = ("PROOFS_TODO_FILE", "PROOFS_TODO_ARCHIVE_DIR", "PROOFS_CHANGELOG_DIR", "PROOFS_STYLE_GUIDE",
                "PROOFS_DESIGN_PROFILE", "PROOFS_QA_MAP", "PROOFS_QA_WORKFLOW")
        for key in keys:
            label = settings._row(key)["label"]
            self.assertEqual(settings.validate(key, "notes/a-b.md"), "notes/a-b.md")
            self.assertEqual(settings.validate(key, "x..y.md"), "x..y.md")
            for bad in ("/etc/passwd", "~/x", "\\x", "C:\\x"):
                with self.subTest(key=key, bad=bad), self.assertRaises(settings.SettingError) as cm:
                    settings.validate(key, bad)
                self.assertEqual(str(cm.exception), "%s must be a path inside the project, not an absolute one." % label)
            for bad in ("../x", "docs/../../x", "a/..", ".."):
                with self.subTest(key=key, bad=bad), self.assertRaises(settings.SettingError) as cm:
                    settings.validate(key, bad)
                self.assertEqual(str(cm.exception), "%s cannot use .. to leave the project." % label)

    def test_a_control_character_in_a_file_is_ignored_with_a_note(self):
        self.write(self.project_file(), {"env": {"PROOFS_TODO_FILE": "TODO.md\nrm -rf x"}})
        e = settings.effective(**self.kw())["PROOFS_TODO_FILE"]
        self.assertEqual((e["value"], e["source"]), ("TODO.md", "default"))
        self.assertIn("control characters", e["note"])


class BrokenFileMessageTest(Base):
    """Item 8: the page builder and the capture stop with one line naming the file, not a traceback."""

    def setUp(self):
        super().setUp()
        self.broken = self.user_file()
        self.broken.write_text("{not json")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("PROOFS_") and k != "CLAUDE_CONFIG_DIR"}
        self.env["HOME"] = str(self.home)

    def check(self, r):
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stderr)
        self.assertNotIn("    at ", r.stderr)  # a node stack
        self.assertEqual(len(r.stderr.strip().splitlines()), 1, r.stderr)
        self.assertIn(str(self.broken), r.stderr)

    def test_page_builder(self):
        spec = self.project / "q.json"
        spec.write_text(json.dumps({"mode": "questions", "title": "T", "project": {"name": "P", "stream": "s"},
                                    "questions": [{"qid": "p", "ask": "Pick", "options": [{"label": "A"}, {"label": "B"}]}]}))
        r = subprocess.run([sys.executable, str(REPO / "shared" / "review_page" / "review_page.py"), str(spec),
                            "--out", str(self.project / "q.html"), "--no-check"],
                           cwd=str(self.project), env=self.env, capture_output=True, text=True, timeout=120)
        self.check(r)

    def test_with_server(self):
        r = subprocess.run([sys.executable, str(REPO / "shared" / "capture" / "with_server.py"), "--start", "true",
                            "--url", "http://127.0.0.1:9/", "--", "true"],
                           cwd=str(self.project), env=self.env, capture_output=True, text=True, timeout=120)
        self.check(r)

    @unittest.skipUnless(__import__("shutil").which("node"), "node is not installed")
    def test_capture(self):
        pages = self.project / "pages.json"
        pages.write_text(json.dumps({"base": "http://127.0.0.1:9", "pages": [{"name": "home", "path": "/"}]}))
        r = subprocess.run(["node", str(REPO / "skills" / "visual-qa" / "scripts" / "capture.cjs"), str(pages)],
                           cwd=str(self.project), env=self.env, capture_output=True, text=True, timeout=120)
        self.check(r)


class ReferenceTest(unittest.TestCase):
    def test_settings_skill_passes_check_skills(self):
        self.assertTrue((REPO / "skills" / "settings" / "SKILL.md").exists())
        r = subprocess.run([sys.executable, str(REPO / "bin" / "check-skills")], cwd=str(REPO),
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_settings_skill_never_preapproves_a_write(self):
        text = (REPO / "skills" / "settings" / "SKILL.md").read_text(encoding="utf-8")
        head = text.split("\n---\n", 1)[0]
        self.assertIn("name: settings", head)
        for flag in ("--set", "--unset", "--apply"):
            self.assertNotIn(flag, head)

    def test_reference_lists_every_key(self):
        text = (REPO / "reference" / "settings.md").read_text(encoding="utf-8")
        for key in EXPECTED_KEYS:
            self.assertIn("`%s`" % key, text, key)
        for row in settings.load_table():
            self.assertIn("`%s`" % row["key"], text)


if __name__ == "__main__":
    unittest.main()
