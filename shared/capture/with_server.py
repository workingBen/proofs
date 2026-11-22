#!/usr/bin/env python3
"""Start a dev server, wait until it answers, run one capture command, then always stop it.

    python3 <plugin root>/shared/capture/with_server.py --start "<server command>" --url <url> \\
        [--cwd DIR] [--timeout 120] [--grace 5] [--log FILE] [--pidfile FILE] -- <capture command> [args...]

Why it exists: a server started from Claude's Bash tool with `&` keeps that tool's stdout and
stderr open, so a headless `claude -p` turn never ends, and killing the turn kills the server.
This helper owns the server for exactly as long as the capture runs:

- The server runs in its own session (`start_new_session`), with stdin from /dev/null and
  stdout and stderr in the log file, so it never holds the caller's pipes.
- Stopping sends SIGTERM to the server's whole process group, waits --grace seconds, then
  sends SIGKILL, and removes the pidfile. It runs on every exit: normal finish, a failed
  capture, a server that never comes up, SIGINT, SIGTERM or SIGHUP to the helper, and the
  helper's parent dying (a watcher notices the helper was reparented and stops everything).
- The capture command runs in its own process group too, and that group is stopped as well.
- If a server already answers at --url, it is not this helper's, so it is used and left running.
- A pidfile left by an earlier run that was SIGKILLed (the one exit nothing can catch) is
  reaped on the next start.

Ready means any HTTP response below 500 (redirects count, and are not followed). Connection
errors and 5xx mean not ready yet. The capture gets PROOFS_BASE_URL=<url> in its environment
and runs in the current folder; the server runs in --cwd. --log and --pidfile default to
.proofs/server.log and .proofs/server.pid under --cwd (else the current folder).

Exit codes: the capture's own code when the server came up; 3 the server never answered below
500 within --timeout; 4 the server exited before answering; 128 + signal number when the
helper was stopped by SIGINT, SIGTERM or SIGHUP (129 when its parent died); 2 bad usage.

POSIX only (macOS and Linux): it relies on process groups, killpg and getppid.
Python 3 standard library only.
"""
import argparse
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

EXIT_NOT_READY = 3
EXIT_SERVER_EXITED = 4
STOP_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
POLL = 0.5
LOG_TAIL = 20


class ServerExited(Exception):
    """The server process exited before it answered."""

    def __init__(self, returncode):
        super().__init__("server exited with code %s" % returncode)
        self.returncode = returncode


class NotReady(Exception):
    """The server did not answer below 500 before the deadline."""

    def __init__(self, last_status):
        super().__init__("not ready (last status %s)" % last_status)
        self.last_status = last_status


class Stopped(BaseException):
    """Raised by the signal handlers, so every `finally` runs (Python's version of a shell trap)."""

    def __init__(self, signum):
        super().__init__(signum)
        self.signum = signum


def say(msg, err=False):
    """Print and flush; a closed pipe (the caller is gone) must never stop the cleanup."""
    try:
        print(msg, file=sys.stderr if err else sys.stdout, flush=True)
    except (OSError, ValueError):
        pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


# No proxies (a dev server is local) and no redirects (a 302 already proves it answers).
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def probe(url, timeout=2.0):
    """HTTP status of one GET, or None when nothing answered."""
    try:
        with _OPENER.open(url, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:  # refused, reset, timed out, or a half-written response: not an answer yet
        return None


def wait_ready(url, deadline, proc):
    """Poll url every 0.5 s until it answers below 500; return that status.

    Raises ServerExited if proc exits first (after one last look, for start commands that
    fork a daemon and return), or NotReady(last_status) at the deadline (time.monotonic()).
    """
    last = None
    while True:
        status = probe(url, timeout=max(0.2, min(2.0, deadline - time.monotonic())))
        if status is not None:
            last = status
            if status < 500:
                return status
        if proc is not None and proc.poll() is not None:
            status = probe(url, timeout=1.0)
            if status is not None and status < 500:
                return status
            raise ServerExited(proc.returncode)
        if time.monotonic() >= deadline:
            raise NotReady(last)
        time.sleep(min(POLL, max(0.0, deadline - time.monotonic())))


def _group_alive(pgid):
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _stop_group(pgid, grace, proc=None):
    """SIGTERM the group, wait up to grace, then SIGKILL. proc (the leader) is reaped if given."""
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    end = time.monotonic() + grace
    while time.monotonic() < end:
        if proc is not None:
            proc.poll()
        if not _group_alive(pgid):
            break
        time.sleep(0.05)
    else:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if proc is not None:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
    end = time.monotonic() + 2
    while _group_alive(pgid) and time.monotonic() < end:
        time.sleep(0.05)


def stop(proc, grace):
    """Stop proc's whole process group: SIGTERM, wait grace seconds, then SIGKILL."""
    _stop_group(proc.pid, grace, proc)


def _reap_stale(pidfile, grace):
    """Kill the server an earlier, uncatchably killed run left behind, if its pidfile says so."""
    try:
        pid = int(open(pidfile).read().strip())
    except (OSError, ValueError):
        pid = None
    # Only a live session leader can be ours: the helper starts every server with setsid.
    if pid and pid > 1 and _group_alive(pid):
        try:
            ours = os.getsid(pid) == pid
        except OSError:
            ours = False
        if ours:
            _stop_group(pid, grace)
            say("server: reaped a leftover server (pid %d) from an earlier run" % pid)
    try:
        os.unlink(pidfile)
    except FileNotFoundError:
        pass


def _log_tail(log):
    try:
        with open(log, "rb") as fh:
            lines = fh.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return
    say("server: last %d lines of %s:" % (LOG_TAIL, log), err=True)
    for line in lines[-LOG_TAIL:]:
        say("  " + line, err=True)


# While a child is being spawned, a stop signal is held here instead of raised, so it can never
# land between the fork and the line that records the child (which would leak that child).
# A blocked signal mask would do the same job, but children inherit the mask, and a server
# started with SIGTERM blocked could only ever be stopped by SIGKILL.
_held = {"active": False, "signals": []}


def _raise_stopped(signum, _frame):
    if _held["active"]:
        _held["signals"].append(signum)
        return
    raise Stopped(signum)


def _watch_parent(original, done, main_ident):
    """If the helper is reparented (Claude or its shell was killed), stop like on SIGHUP.

    The signal goes to the main thread by name: a process-wide kill could land on this
    thread, and the main thread, blocked in wait(), would never see it.
    """
    while not done.wait(1.0):
        if os.getppid() != original:
            signal.pthread_kill(main_ident, signal.SIGHUP)
            return


def _parse(argv):
    p = argparse.ArgumentParser(prog="with_server.py",
                                description="Start a dev server, run one capture command, always stop the server.")
    p.add_argument("--start", required=True, help="shell command that starts the server")
    p.add_argument("--url", required=True, help="URL that answers once the server is up")
    p.add_argument("--cwd", help="folder to start the server in (default: the current folder)")
    p.add_argument("--timeout", type=float, default=120.0, help="seconds to wait for the server (default 120)")
    p.add_argument("--grace", type=float, default=5.0, help="seconds between SIGTERM and SIGKILL (default 5)")
    p.add_argument("--log", default=os.path.join(".proofs", "server.log"), help="server output (default .proofs/server.log)")
    p.add_argument("--pidfile", default=os.path.join(".proofs", "server.pid"), help="default .proofs/server.pid")
    if "--" in argv:
        i = argv.index("--")
        args, capture = p.parse_args(argv[:i]), argv[i + 1:]
    else:
        args, capture = p.parse_args(argv), []
    if not capture:
        p.error("give the capture command after --")
    base = os.path.abspath(args.cwd or os.getcwd())
    args.cwd = base
    args.log = os.path.join(base, os.path.expanduser(args.log))
    args.pidfile = os.path.join(base, os.path.expanduser(args.pidfile))
    return args, capture


def _spawn(state, key, *popen_args, **kwargs):
    """Popen in a new session and record it in state[key], with stop signals held until it is recorded."""
    _held["active"] = True
    try:
        state[key] = subprocess.Popen(*popen_args, start_new_session=True, **kwargs)
    finally:
        _held["active"] = False
        if _held["signals"]:
            raise Stopped(_held["signals"][0])
    return state[key]


def _returncode(rc):
    return 128 - rc if rc < 0 else rc


def main(argv=None):
    args, capture = _parse(sys.argv[1:] if argv is None else argv)
    state = {"server": None, "capture": None, "pidfile": None}

    def cleanup():
        cap = state["capture"]
        if cap is not None:
            _stop_group(cap.pid, args.grace, cap)
        srv = state["server"]
        if srv is not None:
            stop(srv, args.grace)
            say("server: stopped")
        if state["pidfile"]:
            try:
                os.unlink(state["pidfile"])
            except FileNotFoundError:
                pass

    for sig in STOP_SIGNALS:
        signal.signal(sig, _raise_stopped)
    done = threading.Event()
    # The watcher starts with the stop signals blocked (threads inherit the mask), so a signal
    # sent to the helper is always handled by the main thread, which is the one that cleans up.
    old_mask = signal.pthread_sigmask(signal.SIG_BLOCK, STOP_SIGNALS)
    try:
        threading.Thread(target=_watch_parent, args=(os.getppid(), done, threading.get_ident()),
                         daemon=True).start()
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, old_mask)
    try:
        for path in (args.log, args.pidfile):
            os.makedirs(os.path.dirname(path), exist_ok=True)
        _reap_stale(args.pidfile, args.grace)

        status = probe(args.url, timeout=1.0)
        if status is not None and status < 500:
            say("server: already answering at %s; not started by this helper, so it will not be stopped" % args.url)
        else:
            t0 = time.monotonic()
            with open(args.log, "wb") as log:
                _spawn(state, "server", args.start, shell=True, cwd=args.cwd, stdin=subprocess.DEVNULL,
                       stdout=log, stderr=subprocess.STDOUT, close_fds=True)
            srv = state["server"]
            with open(args.pidfile, "w") as fh:
                fh.write("%d\n" % srv.pid)
            state["pidfile"] = args.pidfile
            say("server: started pid %d, log %s" % (srv.pid, args.log))
            try:
                status = wait_ready(args.url, t0 + args.timeout, srv)
            except NotReady as e:
                say("server: not answering below 500 at %s after %gs" % (args.url, args.timeout), err=True)
                say("last answer: %s" % ("HTTP %d" % e.last_status if e.last_status else "none (no connection)"), err=True)
                _log_tail(args.log)
                return EXIT_NOT_READY
            except ServerExited as e:
                say("server: exited with code %s before answering at %s" % (e.returncode, args.url), err=True)
                _log_tail(args.log)
                return EXIT_SERVER_EXITED
            say("server: ready after %.1fs (HTTP %d)" % (time.monotonic() - t0, status))

        env = dict(os.environ, PROOFS_BASE_URL=args.url)
        try:
            _spawn(state, "capture", capture, env=env, stdin=subprocess.DEVNULL)
        except OSError as e:
            say("capture: could not run %s: %s" % (capture[0], e), err=True)
            return 127
        return _returncode(state["capture"].wait())
    except Stopped as e:
        return 128 + e.signum
    finally:
        done.set()
        while True:  # ignore further stop signals first, so a second Ctrl-C cannot cut the cleanup short
            try:
                for sig in STOP_SIGNALS:
                    signal.signal(sig, signal.SIG_IGN)
                break
            except Stopped:
                continue
        cleanup()


if __name__ == "__main__":
    sys.exit(main())
