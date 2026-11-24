#!/usr/bin/env python3
"""Start a dev server, wait until it answers, run one capture command, then always stop it.

    python3 <plugin root>/shared/capture/with_server.py --start "<server command>" --url <url> \\
        [--cwd DIR] [--timeout 120] [--grace 5] [--log FILE] [--pidfile FILE] -- <capture command> [args...]

Why it exists: a server started from Claude's Bash tool with `&` keeps that tool's stdout and
stderr open, so a headless `claude -p` turn never ends, and killing the turn kills the server.
This helper owns the server for exactly as long as the capture runs:

- The server runs in its own session (`start_new_session`), with stdin from /dev/null and
  stdout and stderr in the log file, so it never holds the caller's pipes. The start command
  must run in the foreground: a server that detaches itself (`rails s -d`, a double fork)
  leaves the process group and cannot be stopped; the helper warns when that happens.
- Stopping sends SIGTERM to the server's whole process group, waits --grace seconds, then
  sends SIGKILL, and removes the pidfile. It runs on every exit: normal finish, a failed
  capture, a server that never comes up, SIGINT, SIGTERM or SIGHUP to the helper (further
  signals during the stop are ignored, so they cannot cut it short), and the helper's parent
  dying (a watcher notices the helper was reparented and stops everything).
- The capture runs in its own process group, stopped the same way. Its stdout and stderr
  are pipes that the helper relays to its own, so the capture never holds the caller's
  output directly: if the helper is SIGKILLed, the caller's pipes close with it.
- If a server already answers at --url, it is not this helper's, so it is used and left running.
- Runs that share a pidfile take turns: each holds an flock on <pidfile>.lock for its whole
  life (the kernel drops it even on SIGKILL) and a second run waits up to --timeout for it.
  A run that stops normally removes the lock file, so nothing is left in .proofs/.
- SIGKILL to the helper is the one exit nothing can catch: the server keeps running (its
  output goes to the log, so it holds no pipe) until the next run in that folder reaps it.
  The pidfile records the server's pid and exact start time (read by ps in UTC, so a time
  zone change between runs cannot alter it), and the reap kills only a process that still
  has both, so a recycled pid is never touched. Without ps, reaping is off (with a warning).

Ready means any HTTP response below 500 (redirects count, and are not followed). Connection
errors and 5xx mean not ready yet. The capture gets PROOFS_BASE_URL=<url> in its environment
and runs in the current folder; the server runs in --cwd. --log and --pidfile default to
.proofs/server.log and .proofs/server.pid under --cwd (else the current folder).

Exit codes: the capture's own code when the server came up; 3 the server never answered below
500 within --timeout; 4 the server exited before answering; 5 another run still held the
pidfile's lock after --timeout (the wait for it comes before, and on top of, the server's own
--timeout); 127 the capture command could not be run; 128 + signal number when the helper was
stopped by SIGINT, SIGTERM or SIGHUP (129 when its parent died); 2 bad usage.

POSIX only (macOS and Linux): it relies on process groups, killpg, flock, getppid and ps.
The parent watcher cannot notice a lost parent when the helper starts with parent pid 1
(for example under a double fork); there is no portable PDEATHSIG.
Python 3 standard library only.
"""
import argparse
import fcntl
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

EXIT_NOT_READY = 3
EXIT_SERVER_EXITED = 4
EXIT_LOCKED = 5
EXIT_NO_CAPTURE = 127
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
    """Raised by the signal handler, so every `finally` runs (Python's version of a shell trap)."""

    def __init__(self, signum):
        super().__init__(signum)
        self.signum = signum


# Signal state. "stopping": the first stop signal was raised, or cleanup has begun; every later
# signal is ignored, so a second one can never cut the cleanup short. "hold": a child is being
# spawned; a signal then is kept in "held" and raised once the child is recorded (a blocked
# signal mask would do the same, but children inherit the mask and could not hear SIGTERM).
_flags = {"stopping": False, "hold": False, "held": []}


def _on_stop_signal(signum, _frame):
    if _flags["stopping"]:
        return
    if _flags["hold"]:
        _flags["held"].append(signum)
        return
    _flags["stopping"] = True
    raise Stopped(signum)


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
    """SIGTERM the group, wait up to grace, then SIGKILL. proc (the leader) is reaped if given.

    Returns False without waiting when the group is not ours to signal (PermissionError)."""
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except PermissionError:
        return False
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
        except (ProcessLookupError, PermissionError):
            pass
    if proc is not None:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
    end = time.monotonic() + 2
    while _group_alive(pgid) and time.monotonic() < end:
        time.sleep(0.05)
    return True


def stop(proc, grace):
    """Stop proc's whole process group: SIGTERM, wait grace seconds, then SIGKILL."""
    _stop_group(proc.pid, grace, proc)


def _ps(field, pid):
    try:
        r = subprocess.run(["ps", "-o", field + "=", "-p", str(pid)], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=10, env=dict(os.environ, LC_ALL="C", TZ="UTC"))
    except (OSError, subprocess.SubprocessError):
        return None
    out = r.stdout.strip()
    return out if r.returncode == 0 and out else None


def pid_started(pid):
    """Exact start time of a live pid (ps lstart, in UTC and the C locale), or None.

    Only the start time identifies the process: its command changes when `sh -c` execs the
    real server or a server rewrites its title, but its start time never does."""
    return _ps("lstart", pid)


def pidfile_text(pid):
    """The pidfile: the pid on line 1 (so `kill $(head -1 ...)` works), then its start time."""
    started = pid_started(pid)
    return "%d\n" % pid + ("started %s\n" % started if started else "")


def _read_pidfile(path):
    try:
        lines = open(path).read().splitlines()
        pid = int(lines[0].strip())
    except (OSError, ValueError, IndexError):
        return None
    started = next((ln[8:] for ln in lines[1:] if ln.startswith("started ")), None)
    return pid, started


def _write_pidfile(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        fh.write(text)
    os.replace(tmp, path)


def _reap_stale(pidfile, grace):
    """Kill the server a SIGKILLed earlier run left behind. Call only while holding the lock.

    The lock proves the run that wrote the pidfile is dead; the start time proves the pid
    still names its server and not a process that reused the number."""
    try:
        rec = _read_pidfile(pidfile)
        if rec and rec[0] > 1 and rec[1]:
            pid, started = rec
            if pid_started(pid) == started and _stop_group(pid, grace):
                say("server: reaped a leftover server (pid %d) from an earlier run" % pid)
    finally:
        try:
            os.unlink(pidfile)
        except FileNotFoundError:
            pass


def _same_file(fd, path):
    try:
        a, b = os.fstat(fd), os.stat(path)
    except FileNotFoundError:
        return False
    return (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)


def _take_lock(path, deadline):
    """Open and flock path, waiting until deadline (monotonic) when another run holds it.

    The holder removes the file when it is done (_release_lock), so a run that opened the
    file before that may get the flock on a file no longer at `path`; it then opens the new
    one and tries again, which keeps exactly one holder of the file every run can see.
    """
    told = False
    while True:
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                if not told:
                    say("server: waiting for another with_server.py run using %s" % path)
                    told = True
                if time.monotonic() >= deadline:
                    os.close(fd)
                    return None
                time.sleep(0.2)
                continue
            if _same_file(fd, path):
                return fd
            os.close(fd)  # locked a removed file: take the current one
            break


def _release_lock(path, fd):
    """Remove the lock file while still holding it, then release it (Angular run 1: an empty
    server.pid.lock stayed in .proofs/). Removing it first means no run can take it between."""
    try:
        if _same_file(fd, path):
            os.unlink(path)
    except OSError:
        pass
    os.close(fd)


# The port flag differs by tool: Vite (SvelteKit, Vue, Astro, Remix), Nuxt, Angular and
# webpack-dev-server take --port; Next.js takes -p or --port; Rails and Django differ again.
# A dev server that rejects the flag says so in its log (Vite: "CACError: Unknown option `-p`";
# commander-based CLIs: "error: unknown option '-p'"). SvelteKit run 1 guessed -p twice.
_UNKNOWN_FLAG = re.compile(r"unknown (?:option|argument|flag)\W+(-{1,2}[A-Za-z][\w-]*)", re.I)
PORT_HINT = ("hint: the dev server rejected %s. Vite (SvelteKit, Vue, Astro), Nuxt and Angular take "
             "--port, as in --start \"npm run dev -- --port 3311\"; Next.js takes -p or --port. "
             "Copy the start command from the project's README or CLAUDE.md when it gives one")


def _log_tail(log):
    try:
        with open(log, "rb") as fh:
            lines = fh.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return
    say("server: last %d lines of %s:" % (LOG_TAIL, log), err=True)
    for line in lines[-LOG_TAIL:]:
        say("  " + line, err=True)
    for line in lines[-LOG_TAIL:]:
        m = _UNKNOWN_FLAG.search(line)
        if m and m.group(1) in ("-p", "--p", "-P", "--listen", "-l"):
            say(PORT_HINT % m.group(1), err=True)
            break


def _watch_parent(original, done, main_ident):
    """If the helper is reparented (Claude or its shell was killed), stop like on SIGHUP.

    The signal goes to the main thread by name: a process-wide kill could land on this
    thread, and the main thread, blocked in wait(), would never see it.
    """
    while not done.wait(1.0):
        if os.getppid() != original:
            signal.pthread_kill(main_ident, signal.SIGHUP)
            return


def _relay(src_fd, dst):
    """Copy the capture's output to ours until EOF. If ours is closed, keep draining and drop it."""
    broken = False
    try:
        while True:
            try:
                chunk = os.read(src_fd, 65536)
            except InterruptedError:
                continue
            except OSError:
                break
            if not chunk:
                break
            if not broken:
                try:
                    dst.write(chunk)
                    dst.flush()
                except (OSError, ValueError):
                    broken = True
    finally:
        os.close(src_fd)


def _background(target, *args):
    """A daemon thread with the stop signals blocked, so only the main thread ever handles them."""
    old = signal.pthread_sigmask(signal.SIG_BLOCK, STOP_SIGNALS)
    try:
        t = threading.Thread(target=target, args=args, daemon=True)
        t.start()
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, old)
    return t


def _parse(argv):
    p = argparse.ArgumentParser(prog="with_server.py",
                                description="Start a dev server, run one capture command, always stop the server.",
                                epilog="exit codes: the capture's own code once the server answers; 3 the server never "
                                       "answered below 500 within --timeout; 4 the server exited before answering; "
                                       "5 another run still held the pidfile's lock after --timeout; 127 the capture "
                                       "could not be run; 128 + signal number when stopped by a signal; 2 bad usage")
    p.add_argument("--start", required=True, help="shell command that starts the server, in the foreground")
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


def _spawn(state, key, after, *popen_args, **kwargs):
    """Popen in a new session, record it in state[key] and run after(proc), signals held meanwhile."""
    _flags["hold"] = True
    try:
        state[key] = subprocess.Popen(*popen_args, start_new_session=True, **kwargs)
        if after:
            after(state[key])
    finally:
        _flags["hold"] = False
        if _flags["held"] and not _flags["stopping"]:
            _flags["stopping"] = True
            raise Stopped(_flags["held"][0])
    return state[key]


def _returncode(rc):
    return 128 - rc if rc < 0 else rc


def _keep_proofs_out_of_git(start):
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import proofs_dir
        proofs_dir.ensure_excluded(start)
    except Exception:
        pass


def _run(args, capture, state):
    for path in (args.log, args.pidfile):
        os.makedirs(os.path.dirname(path), exist_ok=True)
    if ".proofs" in os.path.normpath(args.log).split(os.sep) or ".proofs" in os.path.normpath(args.pidfile).split(os.sep):
        _keep_proofs_out_of_git(args.cwd)
    state["lock"] = _take_lock(args.pidfile + ".lock", time.monotonic() + args.timeout)
    if state["lock"] is None:
        say("server: another run still holds %s.lock after %gs" % (args.pidfile, args.timeout), err=True)
        return EXIT_LOCKED
    if shutil.which("ps") is None:
        say("server: warning: ps not found, so a server left by a killed earlier run cannot be "
            "identified and will not be reaped", err=True)
    _reap_stale(args.pidfile, args.grace)

    status = probe(args.url, timeout=1.0)
    if status is not None and status < 500:
        say("server: already answering at %s; not started by this helper, so it will not be stopped" % args.url)
    else:
        t0 = time.monotonic()

        def record(proc):
            _write_pidfile(args.pidfile, pidfile_text(proc.pid))
            state["pidfile"] = args.pidfile

        with open(args.log, "wb") as log:
            _spawn(state, "server", record, args.start, shell=True, cwd=args.cwd, stdin=subprocess.DEVNULL,
                   stdout=log, stderr=subprocess.STDOUT, close_fds=True)
        srv = state["server"]
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
        if srv.poll() is not None and not _group_alive(srv.pid):
            say("server: warning: the start command exited and the server left its process group, so this "
                "helper cannot stop it; run the server in the foreground", err=True)
        say("server: ready after %.1fs (HTTP %d)" % (time.monotonic() - t0, status))

    env = dict(os.environ, PROOFS_BASE_URL=args.url)
    out_r, out_w = os.pipe()
    err_r, err_w = os.pipe()
    try:
        _spawn(state, "capture", None, capture, env=env, stdin=subprocess.DEVNULL, stdout=out_w, stderr=err_w)
    except OSError as e:
        for fd in (out_r, err_r):
            os.close(fd)
        say("capture: could not run %s: %s" % (capture[0], e), err=True)
        return EXIT_NO_CAPTURE
    finally:
        os.close(out_w)
        os.close(err_w)
    state["relays"] = [_background(_relay, out_r, sys.stdout.buffer), _background(_relay, err_r, sys.stderr.buffer)]
    return _returncode(state["capture"].wait())


def _cleanup(args, state):
    cap = state["capture"]
    if cap is not None:
        _stop_group(cap.pid, args.grace, cap)
    for t in state["relays"]:
        t.join(timeout=2)
    srv = state["server"]
    if srv is not None:
        stop(srv, args.grace)
        say("server: stopped")
    if state["pidfile"]:
        try:
            os.unlink(state["pidfile"])
        except FileNotFoundError:
            pass
    if state["lock"] is not None:
        _release_lock(args.pidfile + ".lock", state["lock"])


def main(argv=None):
    args, capture = _parse(sys.argv[1:] if argv is None else argv)
    _flags.update(stopping=False, hold=False, held=[])
    state = {"server": None, "capture": None, "pidfile": None, "lock": None, "relays": []}
    done = threading.Event()
    try:
        for sig in STOP_SIGNALS:
            signal.signal(sig, _on_stop_signal)
        _background(_watch_parent, os.getppid(), done, threading.get_ident())
        return _run(args, capture, state)
    except Stopped as e:
        return 128 + e.signum
    finally:
        _flags["stopping"] = True  # first statement: from here on every stop signal is a no-op
        done.set()
        _cleanup(args, state)


if __name__ == "__main__":
    sys.exit(main())
