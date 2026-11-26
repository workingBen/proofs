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

    def test_validate_agrees_with_settings_py_for_every_key(self):
        tries = ["", "abc", "5", "16", "14", "on", "auto", "chrome", "docs/x.md", "agent/,bot/", "400,2560",
                 "x\ny", "5\n", "a\tb", "\x00", "\x1b[1m", "\x7f", "../x", "docs/../../x", "a/..", "..", "x..y.md",
                 "/etc/passwd", "/tmp/qa", "~/x", "\\x", "C:\\x", ".proofs/base", "relative/base"]
        probe = ("const s = require(process.argv[1]); const tries = JSON.parse(process.argv[2]); const out = {};"
                 "for (const row of s.loadTable()) out[row.key] = tries.map((t) => {"
                 "  try { return { ok: true, value: s.validate(row.key, t) }; }"
                 "  catch (e) { if (!(e instanceof s.SettingError)) throw e; return { ok: false, error: e.message }; } });"
                 "process.stdout.write(JSON.stringify(out));")
        r = subprocess.run([NODE, "-e", probe, str(ROOT / "shared" / "settings.cjs"), json.dumps(tries)],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        js = json.loads(r.stdout)
        for row in settings.load_table():
            for raw, got in zip(tries, js[row["key"]]):
                with self.subTest(key=row["key"], raw=raw):
                    try:
                        want = settings.validate(row["key"], raw)
                    except settings.SettingError as e:
                        self.assertEqual(got, {"ok": False, "error": str(e)})
                    else:
                        self.assertEqual(got, {"ok": True, "value": want})

    def test_a_control_character_or_escaping_path_in_a_file_is_skipped_in_both(self):
        self.write(self.proj, {"PROOFS_TODO_FILE": "TODO.md\nrm x", "PROOFS_QA_MAP": "../map.json",
                               "PROOFS_STYLE_GUIDE": "/etc/guide.html", "PROOFS_BASE_DIR": "base"})
        py, js = self.both()
        self.assertEqual(py, js)
        self.assertEqual((js["PROOFS_TODO_FILE"], js["PROOFS_QA_MAP"], js["PROOFS_BASE_DIR"]),
                         ("TODO.md", "pr_qa_pages.json", ".proofs/base"))

    def test_a_broken_settings_file_is_a_settings_file_error_in_node(self):
        (self.proj / ".claude" / "settings.json").write_text("{not json")
        env = dict(os.environ, HOME=str(self.home), CLAUDE_CONFIG_DIR=str(self.home / ".claude"))
        probe = ("const s = require(process.argv[1]); try { s.get('PROOFS_PORT'); } catch (e) {"
                 " process.stdout.write(String(e instanceof s.SettingsFileError) + ' ' + e.message); }")
        r = subprocess.run([NODE, "-e", probe, str(ROOT / "shared" / "settings.cjs")],
                           cwd=self.proj, env=env, capture_output=True, text=True, timeout=60)
        self.assertTrue(r.stdout.startswith("true "), r.stdout + r.stderr)
        self.assertNotIn("\n", r.stdout)

    def test_launch_treats_a_channel_of_auto_as_unset(self):
        probe = ("const { launchChromium } = require(process.argv[1]); const calls = [];"
                 "const chromium = { launch: async (o) => { calls.push(o.channel || null); return {}; } };"
                 "(async () => { await launchChromium(chromium, { PROOFS_BROWSER_CHANNEL: 'auto' });"
                 " await launchChromium(chromium, { PROOFS_BROWSER_CHANNEL: 'msedge' });"
                 " process.stdout.write(JSON.stringify(calls)); })();")
        r = subprocess.run([NODE, "-e", probe, str(ROOT / "shared" / "review_page" / "launch.cjs")],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), [None, "msedge"])

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
