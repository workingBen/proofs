"""Tests for shared/capture/with_server.py: start a dev server, run one capture, always stop it.

Every test starts real processes, so every test also proves they are gone afterwards.
POSIX only, like the helper.
"""
import os
import shlex
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HELPER = str(REPO / "shared" / "capture" / "with_server.py")
PY = shlex.quote(sys.executable)

SERVER_500 = '''
import http.server, sys
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(500)
        self.end_headers()
        self.wfile.write(b"broken")
    def log_message(self, *a):
        pass
http.server.HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
'''


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def gone(pid, wait=3.0):
    """True once pid no longer exists (polls for up to `wait` seconds)."""
    end = time.monotonic() + wait
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        if time.monotonic() > end:
            return False
        time.sleep(0.05)


def port_closed(port, wait=3.0):
    end = time.monotonic() + wait
    while True:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                pass
        except OSError:
            return True
        if time.monotonic() > end:
            return False
        time.sleep(0.05)


def wait_for(path, text, wait=15.0):
    end = time.monotonic() + wait
    while time.monotonic() < end:
        if path.exists() and text in path.read_text():
            return True
        time.sleep(0.05)
    return False


def read_pid(path, wait=10.0):
    end = time.monotonic() + wait
    while time.monotonic() < end:
        if path.exists():
            raw = path.read_text().strip()
            if raw:
                return int(raw)
        time.sleep(0.05)
    raise AssertionError("no pid in %s" % path)


class WithServerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.port = free_port()
        self.url = "http://127.0.0.1:%d/" % self.port
        self._leftovers = []

    def tearDown(self):
        # Belt and braces: never leave a test process behind, even when an assertion failed
        # (a failed test can leave the helper SIGKILLed here, so its server group is killed too).
        for name in ("parent.pid", "child.pid", "capture.pid", "helper.pid"):
            try:
                self._leftovers.append(int((self.dir / name).read_text().strip()))
            except (OSError, ValueError):
                pass
        for pid in self._leftovers:
            for kill in (os.killpg, os.kill):
                try:
                    kill(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
        self._tmp.cleanup()

    def tree_server(self):
        """A server command with a grandchild, so the tests prove the whole group dies."""
        return ("sh -c '%s -m http.server %d --bind 127.0.0.1 & echo $! > child.pid; echo $$ > parent.pid; wait'"
                % (PY, self.port))

    def args(self, start, capture, *extra):
        return [sys.executable, HELPER, "--start", start, "--url", self.url, "--cwd", str(self.dir), *extra, "--", *capture]

    def run_helper(self, start, capture, *extra, timeout=60):
        return subprocess.run(self.args(start, capture, *extra), cwd=self.dir, capture_output=True,
                              text=True, timeout=timeout, stdin=subprocess.DEVNULL)

    def tree_pids(self):
        parent, child = read_pid(self.dir / "parent.pid"), read_pid(self.dir / "child.pid")
        self._leftovers += [parent, child]
        return parent, child

    def assert_tree_gone(self):
        parent, child = self.tree_pids()
        self.assertTrue(gone(parent), "server shell %d still running" % parent)
        self.assertTrue(gone(child), "server grandchild %d still running" % child)
        self.assertTrue(port_closed(self.port), "port %d still open" % self.port)
        self.assertFalse((self.dir / ".proofs" / "server.pid").exists(), "pidfile left behind")

    def test_runs_capture_then_stops_the_whole_server_tree(self):
        r = self.run_helper(self.tree_server(), ["sh", "-c", 'curl -sf --noproxy "*" "$PROOFS_BASE_URL" > page.html'])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertGreater((self.dir / "page.html").stat().st_size, 0)
        self.assert_tree_gone()
        self.assertIn("server: started pid ", r.stdout)
        self.assertIn("server: ready after ", r.stdout)
        self.assertIn("server: stopped", r.stdout)
        self.assertTrue((self.dir / ".proofs" / "server.log").exists())

    def test_helper_releases_its_output_pipes(self):
        # capture_output makes run() wait until every holder of the pipes closes them; a server
        # holding them (what kept the claude -p turn alive) would hit the timeout instead.
        try:
            r = self.run_helper(self.tree_server(), ["true"], timeout=30)
        except subprocess.TimeoutExpired:
            self.fail("helper or its server kept stdout/stderr open")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assert_tree_gone()

    def test_server_and_capture_still_hear_sigterm(self):
        # Stopping must not need SIGKILL: a long --grace finishes fast only if SIGTERM reaches
        # the server and the capture (a child that inherited a blocked signal mask would not hear it).
        out = self.dir / "out.txt"
        with open(out, "w") as fh:
            p = subprocess.Popen(self.args(self.tree_server(), ["sh", "-c", "echo $$ > capture.pid; exec sleep 30"],
                                           "--grace", "30"),
                                 cwd=self.dir, stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        self._leftovers.append(p.pid)
        self.assertTrue(wait_for(out, "server: ready"), out.read_text())
        read_pid(self.dir / "capture.pid")
        t0 = time.monotonic()
        p.send_signal(signal.SIGTERM)
        self.assertEqual(p.wait(timeout=60), 128 + signal.SIGTERM)
        self.assertLess(time.monotonic() - t0, 10, "stop waited out the grace period, so SIGTERM was not heard")
        self.assert_tree_gone()

    def test_capture_failure_keeps_its_exit_code_and_stops_server(self):
        r = self.run_helper(self.tree_server(), ["sh", "-c", "exit 7"])
        self.assertEqual(r.returncode, 7, r.stdout + r.stderr)
        self.assert_tree_gone()

    def test_signal_to_helper_stops_server(self):
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            with self.subTest(sig=sig.name):
                for name in ("parent.pid", "child.pid", "capture.pid", "out.txt"):
                    (self.dir / name).unlink(missing_ok=True)
                out = self.dir / "out.txt"
                with open(out, "w") as fh:
                    p = subprocess.Popen(self.args(self.tree_server(), ["sh", "-c", "echo $$ > capture.pid; exec sleep 30"]),
                                         cwd=self.dir, stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
                self._leftovers.append(p.pid)
                try:
                    self.assertTrue(wait_for(out, "server: ready"), out.read_text())
                    capture = read_pid(self.dir / "capture.pid")
                    self._leftovers.append(capture)
                    p.send_signal(sig)
                    self.assertEqual(p.wait(timeout=15), 128 + sig, out.read_text())
                finally:
                    if p.poll() is None:
                        p.kill()
                        p.wait()
                self.assert_tree_gone()
                self.assertTrue(gone(capture), "capture %d still running" % capture)
                self.assertIn("server: stopped", out.read_text())

    def test_server_that_ignores_sigterm_is_killed_after_grace(self):
        start = "sh -c 'echo $$ > parent.pid; trap \"\" TERM; exec %s -m http.server %d --bind 127.0.0.1'" % (PY, self.port)
        t0 = time.monotonic()
        r = self.run_helper(start, ["true"], "--grace", "1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        pid = read_pid(self.dir / "parent.pid")
        self._leftovers.append(pid)
        self.assertTrue(gone(pid), "SIGTERM-ignoring server %d survived" % pid)
        self.assertTrue(port_closed(self.port))
        self.assertLess(time.monotonic() - t0, 20)

    def test_server_never_ready_exits_3_and_stops(self):
        start = "sh -c 'echo $$ > parent.pid; echo still booting; exec sleep 100'"
        r = self.run_helper(start, ["sh", "-c", "touch captured"], "--timeout", "2")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        pid = read_pid(self.dir / "parent.pid")
        self._leftovers.append(pid)
        self.assertTrue(gone(pid))
        self.assertIn("still booting", r.stderr)
        self.assertFalse((self.dir / "captured").exists())
        self.assertFalse((self.dir / ".proofs" / "server.pid").exists())

    def test_server_answering_500_is_not_ready(self):
        (self.dir / "server500.py").write_text(SERVER_500)
        start = "sh -c 'echo $$ > parent.pid; exec %s server500.py %d'" % (PY, self.port)
        r = self.run_helper(start, ["sh", "-c", "touch captured"], "--timeout", "3")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("last answer: HTTP 500", r.stderr)
        self.assertFalse((self.dir / "captured").exists())
        pid = read_pid(self.dir / "parent.pid")
        self._leftovers.append(pid)
        self.assertTrue(gone(pid))
        self.assertTrue(port_closed(self.port))

    def test_server_exiting_early_exits_4(self):
        r = self.run_helper("sh -c 'echo boom; exit 1'", ["sh", "-c", "touch captured"])
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)
        self.assertIn("boom", r.stderr)
        self.assertFalse((self.dir / "captured").exists())

    def test_already_running_server_is_left_alone(self):
        theirs = subprocess.Popen([sys.executable, "-m", "http.server", str(self.port), "--bind", "127.0.0.1"],
                                  cwd=self.dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._leftovers.append(theirs.pid)
        try:
            end = time.monotonic() + 10
            while port_closed(self.port, wait=0) and time.monotonic() < end:
                time.sleep(0.05)
            r = self.run_helper("touch started", ["sh", "-c", 'curl -sf --noproxy "*" "$PROOFS_BASE_URL" > page.html'])
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("not started by this helper", r.stdout)
            self.assertFalse((self.dir / "started").exists())
            self.assertIsNone(theirs.poll(), "the helper stopped a server it did not start")
            self.assertFalse(port_closed(self.port, wait=0), "the test's own server stopped answering")
        finally:
            theirs.kill()
            theirs.wait()

    def test_parent_death_stops_server(self):
        out = self.dir / "out.txt"
        helper = " ".join(shlex.quote(a) for a in self.args(self.tree_server(), ["sh", "-c", "echo $PPID > helper.pid; exec sleep 60"]))
        # "; true" keeps sh from exec-ing the helper, so there is a real parent to kill.
        launcher = subprocess.Popen(["sh", "-c", "%s > %s 2>&1; true" % (helper, shlex.quote(str(out)))],
                                    cwd=self.dir, stdin=subprocess.DEVNULL)
        self._leftovers.append(launcher.pid)
        try:
            self.assertTrue(wait_for(out, "server: ready"), out.read_text() if out.exists() else "")
            helper_pid = read_pid(self.dir / "helper.pid")
            self._leftovers.append(helper_pid)
            launcher.kill()
            launcher.wait()
            self.assertTrue(gone(helper_pid, wait=5), "helper outlived its parent")
        finally:
            if launcher.poll() is None:
                launcher.kill()
                launcher.wait()
        self.assert_tree_gone()
        self.assertIn("server: stopped", out.read_text())

    def test_stale_pidfile_is_reaped(self):
        stale = subprocess.Popen([sys.executable, "-m", "http.server", str(self.port), "--bind", "127.0.0.1"],
                                 cwd=self.dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
        self._leftovers.append(stale.pid)
        threading.Thread(target=stale.wait, daemon=True).start()  # reap it, so a dead one is really gone
        (self.dir / ".proofs").mkdir()
        (self.dir / ".proofs" / "server.pid").write_text("%d\n" % stale.pid)
        end = time.monotonic() + 10
        while port_closed(self.port, wait=0) and time.monotonic() < end:
            time.sleep(0.05)
        r = self.run_helper(self.tree_server(), ["true"], "--grace", "1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("server: reaped a leftover server (pid %d) from an earlier run" % stale.pid, r.stdout)
        self.assertNotIn("not started by this helper", r.stdout)
        self.assertTrue(gone(stale.pid))
        self.assert_tree_gone()

    def test_bad_usage_exits_2(self):
        r = subprocess.run([sys.executable, HELPER, "--start", "true", "--url", self.url], capture_output=True, text=True,
                           cwd=self.dir, timeout=10)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
