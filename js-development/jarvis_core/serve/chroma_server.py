"""
chroma_server.py

The supervised ChromaDB server: the single owner of jarvis_data/chromadb.

Run the server itself (what the supervisor spawns):
    PYTHONPATH=js-development python -m jarvis_core.serve.chroma_server --run
Self-test (starts scratch servers on scratch paths and ports):
    PYTHONPATH=js-development python -m jarvis_core.serve.chroma_server --self-test

LAYER: Memory (process ownership) — supervised by the hearth (Body/serve)

=============================================================================
THE BIG PICTURE
=============================================================================

Several processes each running their own Chroma compaction over one sqlite
file is the root cause of the recurring corruption (see memory/chroma_access.py).
This module makes one process the owner: `chroma run` semantics — the same
Rust server `chroma.exe run` starts — launched through a thin wrapper so that

    * the serving process holds the ownership lock (.chroma_direct.lock) for its
      whole life, so no direct-mode opener and no second server can exist beside
      it, and a refusal names it;
    * the descriptor (.chroma_server.json: pid, port, started) carries the pid
      from the lock note. On Windows the venv's python.exe is a redirector, so
      the pid Popen returns is NOT the server's.

The hearth's supervisor spawns it hidden, logs to jarvis_data/chroma_server.log,
probes /api/v2/heartbeat, restarts it when it dies, and stops it with the hearth.
A server left running by a hearth that was killed hard is ADOPTED by the next
hearth, not duplicated.

=============================================================================
THE FLOW
=============================================================================

STEP 1: hearth start -> ChromaServerSupervisor.ensure_running()
        heartbeat answers -> adopt it.  Otherwise refuse if a direct-mode process
        owns the files, else spawn `python -m jarvis_core.serve.chroma_server --run`.
        |
STEP 2: the wrapper (`--run`, pure Python, ~5 MB) starts the serving process (`--serve`),
        which takes the ownership lock and runs the Rust server; the wrapper publishes
        the descriptor once the heartbeat answers. (Two processes because the Rust
        call never releases the GIL, so the serving process cannot announce itself.)
        |
STEP 3: a monitor thread probes the heartbeat every few seconds; two misses in
        a row -> kill whatever is left and spawn again.
        |
STEP 4: hearth exit -> stop(): terminate the owner (verified against the lock
        note, never a bare pid from a stale file), remove the descriptor.
=============================================================================
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

from jarvis_core.memory.chroma_access import (
    DEFAULT_HOST, OwnerLock, ServerState, default_port, heartbeat, lock_holder,
    lock_path, read_descriptor, remove_descriptor, resolve_db_path, server_state,
    write_descriptor)

_HEARTBEAT_WAIT_S = 120.0
EXIT_OWNED_ELSEWHERE = 3
EXIT_SERVER_ENDED = 4


# =============================================================================
# Part 1: THE SERVER PROCESS AND ITS ANNOUNCER
# =============================================================================
#
# Two processes on purpose. chromadb_rust_bindings.cli() blocks WITHOUT releasing
# the GIL (measured: a Python thread in the same process never ran, so the
# descriptor was never written and the supervisor waited out its whole timeout).
# So the process that serves does nothing but own the lock and serve; a thin
# pure-Python parent (no chromadb import) watches for the heartbeat, publishes
# the descriptor and removes it when the server ends. The lock lives in the
# SERVING process: if the parent dies the server keeps its ownership, and if the
# server dies the lock is gone with it.

def serve_files(db_path: Path, host: str, port: int) -> int:
    """Own the files and serve until killed. The blocking half. Returns an exit code."""
    path = resolve_db_path(db_path)
    path.mkdir(parents=True, exist_ok=True)
    lock = OwnerLock(lock_path(path))
    if not lock.try_acquire("server"):
        info = lock_holder(lock.path)
        print(f"[chroma-server] refusing to start: {path} is already owned by "
              f"pid {info.get('pid')} ({info.get('role')}). Two owners is the bug "
              f"this server exists to remove.", flush=True)
        return EXIT_OWNED_ELSEWHERE
    remove_descriptor(path)
    try:
        import chromadb_rust_bindings
        chromadb_rust_bindings.cli(["chroma", "run", "--path", str(path),
                                    "--host", host, "--port", str(port)])
    except KeyboardInterrupt:
        pass
    finally:
        lock.release()
    return EXIT_SERVER_ENDED


def run_server(db_path: Path, host: str, port: int) -> int:
    """Spawn the serving process, publish the descriptor once it answers, clean up
    when it ends. What the supervisor launches."""
    path = resolve_db_path(db_path)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    child = subprocess.Popen(
        [sys.executable, "-m", "jarvis_core.serve.chroma_server", "--serve",
         "--path", str(path), "--host", host, "--port", str(port)],
        stdin=subprocess.DEVNULL, creationflags=flags)
    announced_pid = 0
    deadline = time.monotonic() + _HEARTBEAT_WAIT_S
    while child.poll() is None:
        if not announced_pid and time.monotonic() < deadline and heartbeat(host, port, 1.0):
            note = lock_holder(lock_path(path))
            if note.get("role") == "server" and note.get("pid"):
                announced_pid = int(note["pid"])
                write_descriptor(path, {"pid": announced_pid, "host": host, "port": port,
                                        "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                                        "path": str(path)})
                print(f"[chroma-server] serving {path} on {host}:{port} pid {announced_pid}", flush=True)
        time.sleep(0.3)
    if announced_pid:
        remove_descriptor(path, only_pid=announced_pid)
    return child.returncode


# =============================================================================
# Part 2: KILLING THE OWNER SAFELY
# =============================================================================

def _kill_pid(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


def stop_server(db_path: Path, timeout_s: float = 15.0) -> bool:
    """Stop the server that owns `db_path`. True when the files are free after.

    The pid is trusted only when the descriptor, the lock note and the lock
    itself agree: a stale descriptor naming a recycled pid must never get an
    unrelated process killed."""
    path = resolve_db_path(db_path)
    probe = OwnerLock(lock_path(path))
    if probe.try_acquire("probe"):
        probe.release()
        remove_descriptor(path)
        return True
    desc = read_descriptor(path) or {}
    note = lock_holder(lock_path(path))
    pid = int(note.get("pid") or 0)
    if note.get("role") != "server" or not pid or pid != int(desc.get("pid") or pid):
        return False
    _kill_pid(pid)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if probe.try_acquire("probe"):
            probe.release()
            remove_descriptor(path)
            return True
        time.sleep(0.2)
    return False


# =============================================================================
# Part 3: THE SUPERVISOR (lives in the hearth process)
# =============================================================================

class ChromaServerSupervisor:
    """Keep exactly one server alive for `db_path`; adopt one that already runs."""

    def __init__(self, db_path: Optional[Path] = None, host: str = DEFAULT_HOST,
                 port: Optional[int] = None, log_path: Optional[Path] = None,
                 probe_interval_s: float = 10.0, spawn_wait_s: float = 60.0) -> None:
        from jarvis_core.config import DATA_ROOT
        self.db_path = resolve_db_path(db_path)
        self.host = host
        self.port = port if port is not None else default_port()
        self.log_path = Path(log_path) if log_path else Path(DATA_ROOT) / "chroma_server.log"
        self.probe_interval_s = probe_interval_s
        self.spawn_wait_s = spawn_wait_s
        self.restarts = 0
        self.last_error = ""
        self._proc: Optional[subprocess.Popen] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def state(self) -> ServerState:
        return server_state(self.db_path)

    def _spawn(self) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        root = str(Path(__file__).resolve().parents[2])
        env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
        flags = 0
        if os.name == "nt":
            flags = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
                     | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        with open(self.log_path, "ab", buffering=0) as log:
            log.write(f"--- chroma server spawn {time.strftime('%Y-%m-%dT%H:%M:%S%z')} "
                      f"port {self.port} ---\n".encode("utf-8"))
            self._proc = subprocess.Popen(
                [sys.executable, "-m", "jarvis_core.serve.chroma_server", "--run",
                 "--path", str(self.db_path), "--host", self.host, "--port", str(self.port)],
                cwd=root, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                creationflags=flags)

    def ensure_running(self, wait_s: Optional[float] = None) -> ServerState:
        """Adopt a live server or start one; return its state (up=False on failure,
        with `last_error` saying why — never raises)."""
        with self._lock:
            state = self.state()
            if state.up:
                return state
            probe = OwnerLock(lock_path(self.db_path))
            if not probe.try_acquire("probe"):
                info = lock_holder(probe.path)
                if info.get("role") == "server":
                    return self._wait_up(wait_s)
                self.last_error = (f"cannot start the Chroma server: pid {info.get('pid')} "
                                   f"({info.get('role')}, {info.get('argv0')}) holds the files in "
                                   f"direct mode. Stop it; the server will start on the next probe.")
                return ServerState(up=False)
            probe.release()
            try:
                self._spawn()
            except OSError as e:
                self.last_error = f"spawn failed: {type(e).__name__}: {e}"
                return ServerState(up=False)
            return self._wait_up(wait_s)

    def _wait_up(self, wait_s: Optional[float]) -> ServerState:
        deadline = time.monotonic() + (self.spawn_wait_s if wait_s is None else wait_s)
        while True:
            state = self.state()
            if state.up:
                self.last_error = ""
                return state
            if self._proc is not None and self._proc.poll() is not None:
                self.last_error = (f"server exited rc={self._proc.returncode} during start; "
                                   f"see {self.log_path}")
                return state
            if time.monotonic() >= deadline:
                self.last_error = f"no heartbeat within the wait; see {self.log_path}"
                return state
            time.sleep(0.3)

    def start_monitor(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._monitor, daemon=True, name="chroma-supervisor")
        self._thread.start()

    def _monitor(self) -> None:
        misses = 0
        while not self._stop.wait(self.probe_interval_s):
            if self.state().up:
                misses = 0
                continue
            misses += 1
            if misses < 2:
                continue
            stop_server(self.db_path, timeout_s=5.0)
            self.restarts += 1
            print(f"[chroma-supervisor] server not answering; restart #{self.restarts}", flush=True)
            if not self.ensure_running().up:
                print(f"[chroma-supervisor] restart failed: {self.last_error}", flush=True)
            misses = 0

    def stop(self) -> None:
        self._stop.set()
        stop_server(self.db_path)
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.terminate()


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS
# =============================================================================

def _free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind((DEFAULT_HOST, 0))
        return s.getsockname()[1]


_WORKLOAD = r"""
import os, random, sys, time
sys.path.insert(0, sys.argv[1])
os.environ.setdefault('JARVIS_CHROMA_WAIT_S', '20')
mode, db, role, tag, amount = sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], int(sys.argv[6])
name = sys.argv[7] if len(sys.argv) > 7 else 'e2e'
rnd = random.Random(tag)
errors, first = 0, ''
def note(e):
    global errors, first
    errors += 1
    first = first or (type(e).__name__ + ': ' + str(e)[:160])
col = None
try:
    if mode == 'legacy':
        import chromadb
        client = chromadb.PersistentClient(path=db)
    else:
        from jarvis_core.memory.chroma_access import get_chroma_client
        client = get_chroma_client(db)
    col = client.get_or_create_collection(name, embedding_function=None, metadata={'hnsw:space': 'cosine'})
    if role == 'cold':
        col.upsert(ids=[tag], embeddings=[[rnd.random() for _ in range(384)]])
except Exception as e:
    note(e)
if col is None:
    pass
elif role == 'writer':
    for b in range(amount):
        ids = [f'{tag}-{b}-{i}' for i in range(300)]
        try:
            col.upsert(ids=ids, embeddings=[[rnd.random() for _ in range(384)] for _ in ids],
                       metadatas=[{'tag': tag, 'b': b} for _ in ids], documents=['x ' * 50 for _ in ids])
            col.query(query_embeddings=[[rnd.random() for _ in range(384)]], n_results=5)
        except Exception as e:
            note(e)
elif role == 'reader':
    end = time.time() + amount
    while time.time() < end:
        try:
            col.count()
            col.query(query_embeddings=[[rnd.random() for _ in range(384)]], n_results=5)
        except Exception as e:
            note(e)
        time.sleep(0.05)
try:
    total = col.count() if col is not None else -1
except Exception as e:
    note(e)
    total = -1
print('RESULT', 'mode', mode, 'role', role, 'errors', errors, 'count', total, 'first', first)
"""


def _rss_mb(pid: int) -> float:
    """Working set of `pid` in MB (Windows tasklist; 0.0 when unavailable)."""
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, timeout=20).stdout
        digits = "".join(ch for ch in out.strip().split('","')[-1] if ch.isdigit())
        return int(digits) / 1024.0
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0


def _run_self_test() -> int:
    import shutil
    import tempfile
    from unittest import mock

    from jarvis_core.memory import chroma_access as ca

    pkg_root = str(Path(__file__).resolve().parents[2])
    passed, failed = 0, []
    env_base = {**os.environ, "PYTHONPATH": pkg_root}

    def check(name: str, ok: bool, hint: str = "") -> None:
        nonlocal passed
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  {hint}"))
        if ok:
            passed += 1
        else:
            failed.append(name)

    def spawn(mode: str, db: Path, role: str, tag: str, amount: int, name: str = "e2e") -> subprocess.Popen:
        return subprocess.Popen([sys.executable, "-c", _WORKLOAD, pkg_root, mode, str(db), role, tag,
                                 str(amount), name],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env_base)

    def result(text: str) -> Dict[str, str]:
        for line in text.splitlines()[::-1]:
            if line.startswith("RESULT"):
                head, _, first = line.partition(" first ")
                kv = head.split()[1:]
                d = dict(zip(kv[::2], kv[1::2]))
                d["first"] = first
                return d
        return {"errors": "-1", "count": "-1", "first": text[-300:]}

    def cold_race(mode: str, db: Path, name: str, n: int = 3) -> List[Dict[str, str]]:
        procs = [spawn(mode, db, "cold", f"c{i}", 0, name) for i in range(n)]
        return [result(p.communicate(timeout=600)[0]) for p in procs]

    def run_workload(mode: str, db: Path, writers: int, batches: int, read_s: int) -> List[Dict[str, str]]:
        result(spawn(mode, db, "writer", "seed", 8).communicate(timeout=600)[0])
        procs = [spawn(mode, db, "reader", "r", read_s)]
        procs += [spawn(mode, db, "writer", f"w{i}", batches) for i in range(writers)]
        return [result(p.communicate(timeout=900)[0]) for p in procs]

    print("=" * 70)
    print("  chroma_server.py -- self-test (scratch dir, scratch port, never jarvis_data)")
    print("=" * 70)
    scratch = Path(tempfile.mkdtemp(prefix="chroma_e2e_"))
    os.environ["JARVIS_CHROMA_WAIT_S"] = "2"
    sup: Optional[ChromaServerSupervisor] = None
    writers, batches, read_s = 2, 20, 45
    expect = (8 + writers * batches) * 300
    try:
        # ---- REPRODUCTION: several processes, one path, each with its own PersistentClient ----
        found = 0
        for rnd_no in range(1, 7):
            fresh = scratch / f"cold{rnd_no}" / "chromadb"
            fresh.mkdir(parents=True)
            rows = cold_race("legacy", fresh, "e2e")
            bad = [r for r in rows if r["errors"] != "0"]
            if bad:
                found += 1
                print(f"  REPRODUCED (old design) on cold-start round {rnd_no}: {len(bad)} of {len(rows)} "
                      f"processes failed to open one fresh path together: {bad[0]['first'][:150]}")
                break
        if not found:
            print("  reproduction: 6 rounds of 3 processes cold-opening one path via PersistentClient "
                  "did not fail this run (the race is timing-dependent)")
        legacy = scratch / "legacy" / "chromadb"
        legacy.mkdir(parents=True)
        rows = run_workload("legacy", legacy, writers, batches, read_s)
        print(f"  sustained legacy workload ({writers} writers + 1 reader, own PersistentClient each): "
              f"errors per process {[r['errors'] for r in rows]}")

        # ---- supervisor: adopt / spawn / heartbeat / descriptor ----
        db = scratch / "srv" / "chromadb"
        db.mkdir(parents=True)
        port = _free_port()
        sup = ChromaServerSupervisor(db_path=db, port=port, log_path=scratch / "server.log",
                                     probe_interval_s=1.0, spawn_wait_s=90.0)
        held = OwnerLock(lock_path(db))
        held.try_acquire("direct")
        st = sup.ensure_running(wait_s=2)
        check("T1 the launcher refuses to start while a direct-mode process owns the files",
              not st.up and "direct mode" in sup.last_error, sup.last_error)
        rc = subprocess.run([sys.executable, "-m", "jarvis_core.serve.chroma_server", "--run",
                             "--path", str(db), "--port", str(_free_port())],
                            capture_output=True, text=True, timeout=120, env=env_base).returncode
        check("T1b ...and the server process itself exits with the refusal code", rc == EXIT_OWNED_ELSEWHERE, str(rc))
        held.release()

        t0 = time.perf_counter()
        st = sup.ensure_running()
        start_s = time.perf_counter() - t0
        check(f"T2 the supervisor starts a real server ({start_s:.1f} s)", st.up and st.port == port, sup.last_error)
        desc = read_descriptor(db) or {}
        check("T2b descriptor holds the real pid/port and the lock note agrees",
              desc.get("port") == port and desc.get("pid") == lock_holder(lock_path(db)).get("pid"), str(desc))
        idle_mb = _rss_mb(int(desc.get("pid") or 0))

        ca.reset_client_cache()
        with mock.patch("chromadb.HttpClient", side_effect=lambda **kw: ("HTTP", kw)):
            c = ca.get_chroma_client(db)
        check("T3 server up -> factory returns an HttpClient for the descriptor's port",
              c[0] == "HTTP" and c[1]["port"] == port and ca.chroma_mode(db) == "server", str(c))
        ca.reset_client_cache()
        intruder = OwnerLock(lock_path(db))
        check("T3b server up -> a direct opener cannot take the ownership lock",
              not intruder.try_acquire("direct") and lock_holder(intruder.path).get("role") == "server")

        rc2 = subprocess.run([sys.executable, "-m", "jarvis_core.serve.chroma_server", "--run",
                              "--path", str(db), "--port", str(_free_port())],
                             capture_output=True, text=True, timeout=120, env=env_base).returncode
        check("T4 a second server on the same files refuses to start", rc2 == EXIT_OWNED_ELSEWHERE, str(rc2))

        races = [r for i in range(3) for r in cold_race("factory", db, f"race{i}")]
        check(f"T5a {len(races)} processes racing to create collections through the server: zero errors",
              all(r["errors"] == "0" for r in races), " || ".join(r["first"] for r in races if r["errors"] != "0"))
        rows = run_workload("factory", db, writers, batches, read_s)
        check(f"T5 same sustained workload via the server: {len(rows)} processes, zero errors",
              all(r["errors"] == "0" for r in rows), " || ".join(f"{r['errors']}:{r['first']}" for r in rows))
        peak_mb = _rss_mb(int((read_descriptor(db) or {}).get("pid") or 0))
        cnt = result(spawn("factory", db, "count", "c", 0).communicate(timeout=300)[0])
        check(f"T5b every write is readable back (expected {expect})", cnt["count"] == str(expect), str(cnt))
        print(f"  server working set: {idle_mb:.0f} MB idle, {peak_mb:.0f} MB after the workload ({expect} vectors x 384d)")

        sup.start_monitor()
        old_pid = int((read_descriptor(db) or {}).get("pid"))
        _kill_pid(old_pid)
        deadline = time.monotonic() + 90
        st = sup.state()
        while time.monotonic() < deadline and not (st.up and st.pid != old_pid):
            time.sleep(1.0)
            st = sup.state()
        check("T6 a hard-killed server is restarted by the monitor (new pid)",
              st.up and st.pid != old_pid and sup.restarts >= 1, f"{st} restarts={sup.restarts} {sup.last_error}")
        cnt = result(spawn("factory", db, "count", "c", 0).communicate(timeout=300)[0])
        check("T6b the data written before the kill survived it", cnt["count"] == str(expect), str(cnt))

        sup.stop()
        time.sleep(1.0)
        probe = OwnerLock(lock_path(db))
        check("T7 stop() removes the descriptor and frees the ownership lock",
              read_descriptor(db) is None and probe.try_acquire("probe"))
        probe.release()
        cnt = result(spawn("factory", db, "count", "c", 0).communicate(timeout=300)[0])
        check("T7b with the server gone a fresh process falls back to direct mode and still sees the data",
              cnt["count"] == str(expect), str(cnt))
    finally:
        if sup is not None:
            sup.stop()
        ca.reset_client_cache()
        time.sleep(0.5)
        shutil.rmtree(scratch, ignore_errors=True)
    print("-" * 70)
    print(f"  {passed} passed, {len(failed)} failed")
    print("=" * 70)
    return 1 if failed else 0


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="The supervised Chroma server for JARVIS.")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--run", action="store_true", help="spawn the server and publish its descriptor (blocks)")
    g.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    g.add_argument("--status", action="store_true")
    g.add_argument("--self-test", action="store_true")
    p.add_argument("--path", default=None)
    p.add_argument("--host", default=DEFAULT_HOST)
    p.add_argument("--port", type=int, default=None)
    args = p.parse_args(argv)
    if args.self_test:
        return _run_self_test()
    path = resolve_db_path(Path(args.path) if args.path else None)
    if args.status:
        st = server_state(path)
        print(f"chroma server {'UP' if st.up else 'DOWN'}  {st.host}:{st.port}  pid {st.pid}  "
              f"started {st.started}  path {path}" if st.has_descriptor else f"no descriptor for {path}: DOWN")
        return 0 if st.up else 1
    port = args.port if args.port is not None else default_port()
    return (serve_files if args.serve else run_server)(path, args.host, port)


if __name__ == "__main__":
    raise SystemExit(main())
