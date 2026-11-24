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
sys.path.insert(0, str(REPO / "shared" / "capture"))
import with_server  # noqa: E402

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
                return int(raw.splitlines()[0])
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
        for name in ("parent.pid", "child.pid", "capture.pid", "helper.pid", ".proofs/server.pid"):
            try:
                self._leftovers.append(int((self.dir / name).read_text().splitlines()[0]))
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

    def run_helper(self, start, capture, *extra, timeout=60, env=None):
        return subprocess.run(self.args(start, capture, *extra), cwd=self.dir, capture_output=True,
                              text=True, timeout=timeout, stdin=subprocess.DEVNULL, env=env)

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

    def test_unknown_port_flag_gets_a_hint(self):
        # SvelteKit run 1: `npm run dev -- -p 3311` reached Vite, which has no -p.
        start = "sh -c 'echo \"CACError: Unknown option \\`-p\\`\"; exit 1'"
        r = self.run_helper(start, ["sh", "-c", "touch captured"])
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)
        self.assertIn("hint:", r.stderr)
        self.assertIn("--port", r.stderr)

    def test_commander_style_unknown_option_gets_a_hint(self):
        r = self.run_helper("sh -c \"echo \\\"error: unknown option '-p'\\\"; exit 1\"", ["sh", "-c", "true"])
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)
        self.assertIn("--port", r.stderr)

    def test_an_ordinary_early_exit_has_no_port_hint(self):
        r = self.run_helper("sh -c 'echo boom; exit 1'", ["sh", "-c", "true"])
        self.assertNotIn("hint:", r.stderr)

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
        (self.dir / ".proofs" / "server.pid").write_text(with_server.pidfile_text(stale.pid))
        end = time.monotonic() + 10
        while port_closed(self.port, wait=0) and time.monotonic() < end:
            time.sleep(0.05)
        r = self.run_helper(self.tree_server(), ["true"], "--grace", "1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("server: reaped a leftover server (pid %d) from an earlier run" % stale.pid, r.stdout)
        self.assertNotIn("not started by this helper", r.stdout)
        self.assertTrue(gone(stale.pid))
        self.assert_tree_gone()

    def tearDown_kill(self, pidfile):
        try:
            os.killpg(int(pidfile.read_text().splitlines()[0]), signal.SIGKILL)
        except (OSError, ValueError, IndexError):
            pass

    def simple_server(self, port=None):
        return "exec %s -m http.server %d --bind 127.0.0.1" % (PY, port or self.port)

    def start_bg(self, start, capture, out, *extra, url=None):
        args = self.args(start, capture, *extra)
        if url:
            args[args.index("--url") + 1] = url
        with open(out, "w") as fh:
            p = subprocess.Popen(args, cwd=self.dir, stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        self._leftovers.append(p.pid)
        return p

    def test_second_signal_during_stop_cannot_skip_cleanup(self):
        # SIGTERM then SIGHUP back to back (0 to 5 ms apart): the second one used to land in
        # `finally` before the cleanup and skip it, leaving the server and the capture behind.
        pidfile = self.dir / ".proofs" / "server.pid"
        for i in range(30):
            with self.subTest(run=i):
                for name in ("capture.pid", "out.txt"):
                    (self.dir / name).unlink(missing_ok=True)
                out = self.dir / "out.txt"
                p = self.start_bg(self.simple_server(), ["sh", "-c", "echo $$ > capture.pid; exec sleep 30"], out,
                                  "--grace", "2")
                try:
                    self.assertTrue(wait_for(out, "server: ready"), out.read_text())
                    server = read_pid(pidfile)
                    capture = read_pid(self.dir / "capture.pid")
                    self._leftovers += [server, capture]
                    p.send_signal(signal.SIGTERM)
                    gap = (0, 0.001, 0.005)[i % 3]
                    if gap:
                        time.sleep(gap)
                    p.send_signal(signal.SIGHUP)
                    rc = p.wait(timeout=20)
                finally:
                    if p.poll() is None:
                        p.kill()
                        p.wait()
                        self.tearDown_kill(pidfile)
                self.assertIn(rc, (128 + signal.SIGTERM, 128 + signal.SIGHUP), out.read_text())
                self.assertTrue(gone(server), "server %d survived run %d" % (server, i))
                self.assertTrue(gone(capture), "capture %d survived run %d" % (capture, i))
                self.assertTrue(port_closed(self.port))
                self.assertNotIn("Traceback", out.read_text())

    def test_only_the_first_stop_signal_raises(self):
        # The deterministic half of the double-signal case (the loop above hits the window only
        # sometimes): once a stop has begun, the handler must return instead of raising again.
        saved = dict(with_server._flags)
        try:
            with_server._flags.update(stopping=False, hold=False, held=[])
            with self.assertRaises(with_server.Stopped) as cm:
                with_server._on_stop_signal(signal.SIGTERM, None)
            self.assertEqual(cm.exception.signum, signal.SIGTERM)
            self.assertIsNone(with_server._on_stop_signal(signal.SIGHUP, None))
            self.assertIsNone(with_server._on_stop_signal(signal.SIGINT, None))
            # A signal during a spawn is held, then raised once; later ones are no-ops.
            with_server._flags.update(stopping=False, hold=True, held=[])
            self.assertIsNone(with_server._on_stop_signal(signal.SIGINT, None))
            self.assertEqual(with_server._flags["held"], [signal.SIGINT])
        finally:
            with_server._flags.clear()
            with_server._flags.update(saved)

    def test_pidfile_naming_an_unrelated_process_is_not_killed(self):
        # A recycled pid: a live session leader of ours, but not the server the pidfile recorded.
        other = subprocess.Popen(["sleep", "60"], start_new_session=True)
        self._leftovers.append(other.pid)
        try:
            (self.dir / ".proofs").mkdir()
            text = with_server.pidfile_text(other.pid).splitlines()
            text[1] = "started Mon Jan  1 00:00:00 2001"
            (self.dir / ".proofs" / "server.pid").write_text("\n".join(text) + "\n")
            r = self.run_helper(self.tree_server(), ["true"])
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertNotIn("reaped", r.stdout)
            self.assertIsNone(other.poll(), "the helper killed a process it did not start")
            self.assert_tree_gone()
        finally:
            other.kill()
            other.wait()

    @unittest.skipIf(os.geteuid() == 0, "running as root, so pid 1 could really be signaled")
    def test_pidfile_naming_a_root_process_does_not_crash(self):
        (self.dir / ".proofs").mkdir()
        for run in range(2):
            with self.subTest(run=run):
                # pid 1 with its true identity: the reap is attempted and gets PermissionError.
                (self.dir / ".proofs" / "server.pid").write_text(with_server.pidfile_text(1))
                r = self.run_helper(self.simple_server(), ["true"])
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertNotIn("Traceback", r.stderr)
                self.assertNotIn("reaped", r.stdout)
                self.assertTrue(port_closed(self.port))

    def test_concurrent_runs_in_one_folder_do_not_kill_each_other(self):
        port_b = free_port()
        out_a, out_b = self.dir / "a.txt", self.dir / "b.txt"
        a = self.start_bg(self.simple_server(),
                          ["sh", "-c", 'sleep 2; curl -sf --noproxy "*" "$PROOFS_BASE_URL" > a.html'], out_a)
        self.assertTrue(wait_for(out_a, "server: ready"), out_a.read_text())
        b = self.start_bg(self.simple_server(port_b),
                          ["sh", "-c", 'curl -sf --noproxy "*" "$PROOFS_BASE_URL" > b.html'], out_b,
                          url="http://127.0.0.1:%d/" % port_b)
        try:
            self.assertEqual(a.wait(timeout=30), 0, out_a.read_text())
            self.assertEqual(b.wait(timeout=30), 0, out_b.read_text())
        finally:
            for p in (a, b):
                if p.poll() is None:
                    p.kill()
                    p.wait()
        self.assertGreater((self.dir / "a.html").stat().st_size, 0, "run B stopped run A's server mid-capture")
        self.assertGreater((self.dir / "b.html").stat().st_size, 0)
        self.assertIn("waiting for another with_server.py run", out_b.read_text())
        self.assertNotIn("reaped", out_b.read_text())
        self.assertTrue(port_closed(self.port) and port_closed(port_b))

    def test_sigkilled_helper_releases_the_callers_output(self):
        # The capture outlives a SIGKILLed helper (nothing can catch SIGKILL), but it must not
        # keep the caller's stdout open: that is what hung the claude -p turn.
        p = subprocess.Popen(self.args(self.tree_server(), ["sh", "-c", "echo $$ > capture.pid; echo hello; exec sleep 30"]),
                             cwd=self.dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
        self._leftovers.append(p.pid)
        try:
            capture = read_pid(self.dir / "capture.pid")
            self._leftovers.append(capture)
            seen = b""
            while b"hello" not in seen:  # the capture's output reaches the caller through the relay
                seen += p.stdout.read1(4096)
            p.kill()
            p.wait()
            result = {}
            reader = threading.Thread(target=lambda: result.update(out=p.stdout.read(), err=p.stderr.read()), daemon=True)
            reader.start()
            reader.join(timeout=5)
            self.assertFalse(reader.is_alive(), "the caller's pipes stayed open after the helper was SIGKILLed")
        finally:
            p.stdout.close()
            p.stderr.close()
            for pid in self.tree_pids() + (capture,):
                for kill in (os.killpg, os.kill):
                    try:
                        kill(pid, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        pass

    def test_server_left_by_a_helper_killed_during_boot_is_reaped(self):
        # SIGKILL the helper while `sh -c` is still sleeping, before it execs the real server:
        # the process's command changes after the pidfile was written, its start time does not.
        pidfile = self.dir / ".proofs" / "server.pid"
        start = "sleep 3; exec %s -m http.server %d --bind 127.0.0.1" % (PY, self.port)
        out = self.dir / "out.txt"
        p = self.start_bg(start, ["true"], out)
        try:
            self.assertTrue(wait_for(out, "server: started pid"), out.read_text())
            leftover = read_pid(pidfile)
            self._leftovers.append(leftover)
            time.sleep(1)
            p.kill()
            p.wait()
        finally:
            if p.poll() is None:
                p.kill()
                p.wait()
        end = time.monotonic() + 10  # let the leftover finish booting, so it really answers
        while port_closed(self.port, wait=0) and time.monotonic() < end:
            time.sleep(0.05)
        self.assertFalse(port_closed(self.port, wait=0), "the leftover server never came up")
        r = self.run_helper(self.simple_server(), ["true"], "--grace", "1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("server: reaped a leftover server (pid %d) from an earlier run" % leftover, r.stdout)
        self.assertNotIn("not started by this helper", r.stdout)
        self.assertTrue(gone(leftover), "the leftover server %d survived the next run" % leftover)
        self.assertTrue(port_closed(self.port))

    def test_lock_timeout_has_its_own_exit_code(self):
        import fcntl
        (self.dir / ".proofs").mkdir()
        with open(self.dir / ".proofs" / "server.pid.lock", "w") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            r = self.run_helper("touch started", ["sh", "-c", "touch captured"], "--timeout", "1")
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertIn("another run still holds", r.stderr)
        self.assertFalse((self.dir / "started").exists())
        self.assertFalse((self.dir / "captured").exists())

    def test_missing_ps_warns_that_reaping_is_off(self):
        empty = self.dir / "empty-bin"
        empty.mkdir()
        env = dict(os.environ, PATH=str(empty))
        r = self.run_helper(self.simple_server(), [sys.executable, "-c", "pass"], env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("ps not found", r.stderr)
        self.assertTrue(port_closed(self.port))

    def test_bad_usage_exits_2(self):
        r = subprocess.run([sys.executable, HELPER, "--start", "true", "--url", self.url], capture_output=True, text=True,
                           cwd=self.dir, timeout=10)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
