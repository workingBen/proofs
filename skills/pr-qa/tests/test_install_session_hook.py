#!/usr/bin/env python3
"""install_session_hook.py turns on the plugin's open-PR reminder via the project's settings env."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPTS)

from install_session_hook import install  # noqa: E402


class InstallTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = os.path.realpath(self._tmp.name)
        self.settings = os.path.join(self.project, ".claude", "settings.json")

    def load(self):
        with open(self.settings, encoding="utf-8") as handle:
            return json.load(handle)

    def test_sets_the_env_var_once_and_writes_no_path(self):
        self.assertTrue(install(self.project))
        self.assertFalse(install(self.project))
        settings = self.load()
        self.assertEqual(settings["env"]["PROOFS_PR_REMINDER"], "1")
        self.assertNotIn("hooks", settings)
        with open(self.settings, encoding="utf-8") as handle:
            self.assertNotIn(os.sep + "skills" + os.sep, handle.read())

    def test_keeps_existing_settings(self):
        os.makedirs(os.path.dirname(self.settings))
        existing = {
            "permissions": {"allow": ["Bash(ls:*)"]},
            "env": {"OTHER": "x"},
            "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "echo start"}]}]},
        }
        with open(self.settings, "w", encoding="utf-8") as handle:
            json.dump(existing, handle)
        install(self.project)
        settings = self.load()
        self.assertEqual(settings["permissions"], existing["permissions"])
        self.assertEqual(settings["hooks"], existing["hooks"])
        self.assertEqual(settings["env"], {"OTHER": "x", "PROOFS_PR_REMINDER": "1"})

    def test_a_different_value_is_replaced(self):
        os.makedirs(os.path.dirname(self.settings))
        with open(self.settings, "w", encoding="utf-8") as handle:
            json.dump({"env": {"PROOFS_PR_REMINDER": "0"}}, handle)
        self.assertTrue(install(self.project))
        self.assertEqual(self.load()["env"]["PROOFS_PR_REMINDER"], "1")

    def test_refuses_settings_it_cannot_parse(self):
        os.makedirs(os.path.dirname(self.settings))
        with open(self.settings, "w", encoding="utf-8") as handle:
            handle.write("{ not json")
        with self.assertRaises(SystemExit):
            install(self.project)
        with open(self.settings, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "{ not json")

    def test_refuses_malformed_env_shapes(self):
        os.makedirs(os.path.dirname(self.settings))
        for shape in ([], {"env": []}, {"env": "x"}):
            with open(self.settings, "w", encoding="utf-8") as handle:
                json.dump(shape, handle)
            with self.assertRaises(SystemExit) as caught:
                install(self.project)
            self.assertIn("==>", str(caught.exception.code), shape)
            with open(self.settings, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), shape)

    def test_runs_from_the_command_line(self):
        script = os.path.join(SCRIPTS, "install_session_hook.py")
        run = subprocess.run([sys.executable, script], cwd=self.project,
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(self.load()["env"]["PROOFS_PR_REMINDER"], "1")


if __name__ == "__main__":
    unittest.main()
