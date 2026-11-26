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


if __name__ == "__main__":
    unittest.main()
