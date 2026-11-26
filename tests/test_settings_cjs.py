"""shared/settings.cjs (node) and shared/settings.py must resolve every key the same way.

Both read shared/settings.json and apply local file > project file > user file > environment >
default, so a value set anywhere reads identically from either language.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared"))
import settings  # noqa: E402

NODE = shutil.which("node")
PROBE = r"""
const s = require(process.argv[2]);
const out = {};
for (const row of s.loadTable()) out[row.key] = s.get(row.key);
process.stdout.write(JSON.stringify(out));
"""


@unittest.skipUnless(NODE, "node not found")
class Parity(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve()
        self.proj, self.home = self.tmp / "proj", self.tmp / "home"
        (self.proj / ".claude").mkdir(parents=True)
        (self.home / ".claude").mkdir(parents=True)
        (self.tmp / "probe.cjs").write_text(PROBE)

    def write(self, where, values):
        (where / "settings.json" if where != self.proj else where / ".claude" / "settings.json").write_text(
            json.dumps({"env": values}))

    def both(self, environ=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith("PROOFS_")}
        env.update(HOME=str(self.home), CLAUDE_CONFIG_DIR=str(self.home / ".claude"), **(environ or {}))
        py = {k: settings.get(k, cwd=self.proj, env=env, home=self.home) for k in (r["key"] for r in settings.load_table())}
        r = subprocess.run([NODE, str(self.tmp / "probe.cjs"), str(ROOT / "shared" / "settings.cjs")],
                           cwd=self.proj, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return py, json.loads(r.stdout)

    def test_defaults_agree(self):
        py, js = self.both()
        self.assertEqual(py, js)
        self.assertEqual(js["PROOFS_MIN_TEXT"], 16)

    def test_every_source_and_the_order_agree(self):
        self.write(self.home / ".claude", {"PROOFS_MIN_TEXT": "20", "PROOFS_PORT": "4000", "PROOFS_SPELLING": "american"})
        self.write(self.proj, {"PROOFS_MIN_TEXT": "18", "PROOFS_EXTRA_WIDTHS": "1024, 1100"})
        (self.proj / ".claude" / "settings.local.json").write_text(json.dumps({"env": {"PROOFS_PORT": "5000"}}))
        py, js = self.both({"PROOFS_SEND_WAIT_MIN": "9", "PROOFS_PORT": "6000", "PROOFS_DESIGN_OPTIONS": "2"})
        self.assertEqual(py, js)
        self.assertEqual((js["PROOFS_MIN_TEXT"], js["PROOFS_PORT"], js["PROOFS_SEND_WAIT_MIN"]), (18, 5000, 9))
        self.assertEqual(js["PROOFS_EXTRA_WIDTHS"], [1024, 1100])
        self.assertEqual(js["PROOFS_DESIGN_OPTIONS"], 2)  # a numeric choice is a number in both

    def test_invalid_and_below_floor_values_are_skipped_the_same_way(self):
        self.write(self.proj, {"PROOFS_MIN_TEXT": "12", "PROOFS_MIN_TAP": "abc", "PROOFS_SPELLING": "british",
                               "PROOFS_PR_REMINDER": "on", "PROOFS_AGENT_BRANCH_PREFIX": "agent/,claude/"})
        py, js = self.both({"PROOFS_MIN_TEXT": "17", "PROOFS_EXTRA_WIDTHS": "300"})
        self.assertEqual(py, js)
        self.assertEqual((js["PROOFS_MIN_TEXT"], js["PROOFS_MIN_TAP"], js["PROOFS_SPELLING"]), (17, 44, "off"))
        self.assertIs(js["PROOFS_PR_REMINDER"], True)
        self.assertEqual(js["PROOFS_AGENT_BRANCH_PREFIX"], ["agent/", "claude/"])
        self.assertEqual(js["PROOFS_EXTRA_WIDTHS"], [])

    def test_a_broken_settings_file_is_an_error_in_both(self):
        (self.proj / ".claude" / "settings.json").write_text("{not json")
        with self.assertRaises(settings.SettingError):
            settings.get("PROOFS_PORT", cwd=self.proj, home=self.home, env={"CLAUDE_CONFIG_DIR": str(self.home / ".claude")})
        env = dict(os.environ, HOME=str(self.home), CLAUDE_CONFIG_DIR=str(self.home / ".claude"))
        r = subprocess.run([NODE, "-e", "require(process.argv[1]).get('PROOFS_PORT')", str(ROOT / "shared" / "settings.cjs")],
                           cwd=self.proj, env=env, capture_output=True, text=True, timeout=60)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not valid JSON", r.stderr)


if __name__ == "__main__":
    unittest.main()
