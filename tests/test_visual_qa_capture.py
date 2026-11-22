import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CAPTURE = ROOT / "skills" / "visual-qa" / "scripts" / "capture.cjs"
NODE = shutil.which("node")
FLAG = "--disable-features=MacAppCodeSignClone"

# A stand-in for Playwright: chromium.launch records its options, then throws each
# scripted error in turn; once the script runs out it throws "fake: stop" so the
# capture ends before it tries to open a page.
FAKE = r"""
const fs = require('fs');
const script = JSON.parse(process.env.FAKE_SCRIPT);
let n = 0;
module.exports = { chromium: { launch: async (opts) => {
  fs.appendFileSync(process.env.FAKE_LOG, JSON.stringify(opts) + '\n');
  const step = script[n++];
  throw new Error(step || 'fake: stop');
} } };
"""


@unittest.skipUnless(NODE, "node not found")
class CaptureLaunch(unittest.TestCase):
    def run_capture(self, script, extra_env=None):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            pkg = tmp / "node_modules" / "playwright"
            pkg.mkdir(parents=True)
            (pkg / "package.json").write_text('{"name": "playwright", "main": "index.js"}')
            (pkg / "index.js").write_text(FAKE)
            (tmp / "pages.json").write_text(json.dumps({"base": "http://localhost:9", "pages": [{"name": "x", "path": "/"}]}))
            log = tmp / "launch.log"
            env = {k: v for k, v in os.environ.items() if k not in ("NODE_PATH", "PLAYWRIGHT_PATH", "PROOFS_BROWSER_CHANNEL")}
            env.update(HOME=str(tmp), FAKE_LOG=str(log), FAKE_SCRIPT=json.dumps(script), **(extra_env or {}))
            r = subprocess.run([NODE, str(CAPTURE), str(tmp / "pages.json"), "--out", str(tmp / "out")],
                               cwd=tmp, env=env, capture_output=True, text=True, timeout=60)
            calls = [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []
            return r, calls

    def test_uses_playwrights_browser_first_with_the_flag(self):
        r, calls = self.run_capture([])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("fake: stop", r.stderr)
        self.assertEqual(calls, [{"args": [FLAG]}])

    def test_falls_back_to_installed_chrome_without_downloading(self):
        r, calls = self.run_capture(["browserType.launch: Executable doesn't exist at /x"])
        self.assertEqual(calls, [{"args": [FLAG]}, {"channel": "chrome", "args": [FLAG]}])

    def test_channel_setting_forces_one_launch(self):
        r, calls = self.run_capture([], {"PROOFS_BROWSER_CHANNEL": "chrome"})
        self.assertEqual(calls, [{"channel": "chrome", "args": [FLAG]}])

    def test_missing_playwright_prints_the_no_download_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "pages.json").write_text('{"base": "http://localhost:9", "pages": []}')
            env = {k: v for k, v in os.environ.items() if k not in ("NODE_PATH", "PLAYWRIGHT_PATH")}
            env["HOME"] = tmp
            r = subprocess.run([NODE, str(CAPTURE), str(Path(tmp) / "pages.json")], cwd=tmp, env=env,
                               capture_output=True, text=True, timeout=60)
        if "Playwright not found" not in r.stderr:
            self.skipTest("a real Playwright is resolvable from the plugin folder")
        self.assertEqual(r.returncode, 2)
        self.assertIn("PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1", r.stderr)
        self.assertNotIn("playwright install chromium", r.stderr)


if __name__ == "__main__":
    unittest.main()
