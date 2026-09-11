#!/usr/bin/env python3
"""
hearth.py — start/stop/inspect the one process that owns JARVIS's clock.

LAYER: Tools (thin adapter — all logic lives in jarvis_core/serve/)

Run with:
    python3 scripts/hearth.py                    # serve in the foreground
    python3 scripts/hearth.py --background       # detach, write a pid file
    python3 scripts/hearth.py --status           # ask the running hearth
    python3 scripts/hearth.py --stop             # SIGTERM it
    python3 scripts/hearth.py --token            # print the bearer token
    python3 scripts/hearth.py --no-clock         # serve without the scheduler

Thin by design, per the Consciousness Portability Contract: this file binds a
socket and manages a pid file. It contains no request handling and no job
definitions — those are jarvis_core/serve/hearth.py and scheduler.py, so the
same organs serve a future systemd unit, an Android foreground service, or a
test harness without being reimplemented per host.

WHY NOT A systemd UNIT (checked, 2026-09-08): systemd IS pid 1 in this WSL
distro, but `systemctl --user` cannot reach a session bus from a non-login
shell ("Failed to connect to bus") and `loginctl` reports Linger=no, so a user
unit would not survive logout anyway. --background + a pid file works today on
both laptops. A unit file can be added later without touching any of this.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import urllib.error
import urllib.request
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "js-development"))

from jarvis_core.config import DATA_ROOT                                # noqa: E402
from jarvis_core.serve.hearth import (                                  # noqa: E402
    DEFAULT_HOST, DEFAULT_PORT, HearthConfig, ensure_token, serve)
from jarvis_core.serve.scheduler import Scheduler, default_jobs         # noqa: E402

PID_PATH = Path(DATA_ROOT) / ".hearth.pid"


def _read_pid() -> int:
    """The pid of a LIVE hearth, or 0. A stale pid file reads as 0."""
    try:
        pid = int(PID_PATH.read_text(encoding="utf-8").strip())
    except (OSError, FileNotFoundError, ValueError):
        return 0
    if os.name == "nt":
        # Windows rejects os.kill(pid, 0) with WinError 87 even for a live
        # process. Querying the process handle is the equivalent existence test.
        import ctypes
        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            process_query_limited_information, False, pid)
        if not handle:
            return 0
        ctypes.windll.kernel32.CloseHandle(handle)
        return pid
    try:
        os.kill(pid, 0)                        # signal 0 = existence check only
    except (ProcessLookupError, ValueError, SystemError):
        return 0
    except PermissionError:
        return pid                             # alive, owned by someone else
    return pid


def _request(path: str, host: str, port: int, token: str, timeout: float = 10.0) -> dict:
    req = urllib.request.Request(
        f"http://{host}:{port}{path}",
        headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _cmd_status(args: argparse.Namespace, token: str) -> int:
    pid = _read_pid()
    try:
        health = _request("/v1/health", args.host, args.port, token)
    except (urllib.error.URLError, OSError, ValueError) as e:
        print(f"hearth NOT reachable on {args.host}:{args.port} "
              f"({type(e).__name__}: {e})")
        print(f"  pid file: {'stale/absent' if not pid else f'pid {pid} alive but not answering'}")
        return 1
    # Health is the authority when a previous stop attempt removed a valid PID
    # file on Windows. Restore it so the next --stop can target this process.
    try:
        health_pid = int(health.get("pid", 0))
        if health_pid > 0 and health_pid != pid:
            PID_PATH.parent.mkdir(parents=True, exist_ok=True)
            PID_PATH.write_text(str(health_pid), encoding="utf-8")
    except (OSError, TypeError, ValueError):
        pass
    print(f"hearth UP on {args.host}:{args.port}  pid {health.get('pid')}  "
          f"uptime {health.get('uptime_seconds')}s")
    print(f"  served {health.get('requests_served')} · "
          f"rejected {health.get('requests_rejected')} · "
          f"busy {health.get('busy')}")
    if health.get("last_error"):
        print(f"  last error: {health['last_error']}")
    jobs = health.get("jobs") or []
    if not jobs:
        print("  clock: DISABLED (no scheduler) — JARVIS has no pulse in this process")
    for job in jobs:
        age = job.get("last_run_age_s")
        when = f"{age / 3600:.1f}h ago" if age else "never"
        print(f"  job {job['name']:<18} every {job['every_hours']}h  "
              f"last {when:<12} {job['status']}"
              f"  (runs {job['runs']}, failed {job['failures']}, "
              f"skipped {job['skipped']})")
    return 0


def _cmd_stop(args: argparse.Namespace) -> int:
    pid = _read_pid()
    if not pid:
        print("no live hearth found (pid file absent or stale)")
        PID_PATH.unlink(missing_ok=True)
        return 1
    if os.name == "nt":
        import subprocess
        res = subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
        if res.returncode == 0:
            print(f"SIGTERM sent to hearth pid {pid}")
            PID_PATH.unlink(missing_ok=True)
            return 0
    try:
        os.kill(pid, signal.SIGTERM)
    except PermissionError:
        print(f"cannot stop hearth pid {pid}: permission denied")
        return 1
    print(f"SIGTERM sent to hearth pid {pid}")
    PID_PATH.unlink(missing_ok=True)
    return 0


def _detach() -> None:
    """Double-fork so the hearth outlives this shell. POSIX only."""
    if os.fork() > 0:
        os._exit(0)
    os.setsid()
    if os.fork() > 0:
        os._exit(0)
    log = Path(DATA_ROOT) / "hearth.log"
    with open(os.devnull, "rb") as devnull, open(log, "ab", buffering=0) as out:
        os.dup2(devnull.fileno(), sys.stdin.fileno())
        os.dup2(out.fileno(), sys.stdout.fileno())
        os.dup2(out.fileno(), sys.stderr.fileno())
    print(f"--- hearth started, pid {os.getpid()} ---", flush=True)


def main() -> int:
    p = argparse.ArgumentParser(
        description="The hearth: one process, the clock, and every surface's socket.")
    p.add_argument("--host", default=DEFAULT_HOST,
                   help="bind address (default 127.0.0.1 — do NOT widen in v0)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--background", action="store_true",
                   help="detach and write a pid file; logs to jarvis_data/hearth.log")
    p.add_argument("--no-clock", action="store_true",
                   help="serve requests but run no scheduled jobs")
    p.add_argument("--status", action="store_true", help="query a running hearth")
    p.add_argument("--stop", action="store_true", help="SIGTERM a running hearth")
    p.add_argument("--token", action="store_true", help="print the bearer token")
    p.add_argument("--tick-once", action="store_true",
                   help="run every due scheduled job once, then exit (no socket)")
    args = p.parse_args()

    token = ensure_token()

    if args.token:
        print(token)
        return 0
    if args.stop:
        return _cmd_stop(args)
    if args.status:
        return _cmd_status(args, token)

    if args.tick_once:
        import asyncio
        sched = Scheduler()
        # ignore_stagger: a one-shot must not be silenced by the startup delays
        # that exist only to spread a daemon's first tick. Without this the
        # command printed "nothing was due" and did nothing, every time.
        ran = asyncio.get_event_loop().run_until_complete(
            sched.tick(ignore_stagger=True))
        print(f"ran: {ran or 'nothing was due'}")
        for job in sched.status():
            print(f"  {job['name']:<18} {job['status']}")
        return 0

    if _read_pid():
        print(f"a hearth is already running (pid {_read_pid()}) — "
              f"use --stop first, or --status to inspect it")
        return 1

    if args.background:
        if not hasattr(os, "fork"):
            print("--background needs POSIX fork; run in the foreground on Windows")
            return 2
        _detach()

    PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    PID_PATH.write_text(str(os.getpid()), encoding="utf-8")

    scheduler = None if args.no_clock else Scheduler(jobs=default_jobs())
    banner = "clock ON" if scheduler else "clock OFF"
    print(f"hearth listening on http://{args.host}:{args.port}  ({banner})", flush=True)
    print(f"  token: {Path(DATA_ROOT) / '.hearth_token'}  (gitignored, 0600)", flush=True)
    try:
        return serve(HearthConfig(host=args.host, port=args.port, token=token),
                     scheduler=scheduler)
    finally:
        PID_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
