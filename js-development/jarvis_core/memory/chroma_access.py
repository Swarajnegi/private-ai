"""
chroma_access.py

JARVIS Memory Layer: the ONE way any process obtains a ChromaDB client.

Import with:
    from jarvis_core.memory.chroma_access import get_chroma_client

LAYER: Memory

=============================================================================
THE BIG PICTURE: exactly one process owns the Chroma files
=============================================================================

Measured 2026-09-29: the hearth held a chromadb.PersistentClient open for its
whole life, every scheduled job subprocess opened its own, and so did every
script and evaluation. The Rust bindings run compaction inside each process
over the SAME sqlite file, so they collide. `reindex_memory` failed 20 of 21
scheduled runs with "Error in compaction: Failed to apply logs to the metadata
segment", and the store was reset on 2026-09-29, losing `research_papers`.
A cross-process write lock did not help: readers and other compactors still
collided. Locking writers cannot fix a design with N compactors.

The fix is ownership, not locking:

    server mode   the hearth supervises `chroma run` (serve/chroma_server.py).
                  It is the only process that touches the files; every other
                  process is a chromadb.HttpClient.
    direct mode   no server is running. The process takes an EXCLUSIVE
                  ownership lock for its whole life and opens a
                  PersistentClient. A second direct process is refused, and
                  so is a direct process while a server runs.

The same lock is what the server holds, so "server up" and "direct open" are
mutually exclusive by construction, and a crashed owner releases it by dying.

=============================================================================
THE FLOW
=============================================================================

STEP 1: get_chroma_client(db_path) -> cached client for this process, or:
        |
STEP 2: descriptor <db_path.parent>/.chroma_server.json + GET /api/v2/heartbeat
        answers -> chromadb.HttpClient (server mode).
        |
STEP 3: otherwise try the ownership lock <db_path.parent>/.chroma_direct.lock,
        polling for up to JARVIS_CHROMA_WAIT_S (a starting server may still
        come up; a finishing direct process may still release).
        |
STEP 4: lock won -> PersistentClient, lock held until the process exits.
        Lock lost -> ChromaOwnershipError naming the holder. Never a silent
        second opener.
=============================================================================
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]

try:
    import msvcrt
except ImportError:
    msvcrt = None  # type: ignore[assignment]

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8759
DEFAULT_WAIT_S = 10.0

_LOCK_NAME = ".chroma_direct.lock"
_DESCRIPTOR_NAME = ".chroma_server.json"
_HEARTBEAT_PATH = "/api/v2/heartbeat"
REQUIRE_SERVER_ENV = "JARVIS_CHROMA_REQUIRE_SERVER"


class ChromaOwnershipError(RuntimeError):
    """Another process owns the Chroma files and this one may not open them."""


def resolve_db_path(db_path: Optional[Path] = None) -> Path:
    if db_path is None:
        from jarvis_core.config import DB_ROOT
        db_path = DB_ROOT
    return Path(db_path).resolve()


def lock_path(db_path: Path) -> Path:
    return Path(db_path).parent / _LOCK_NAME


def descriptor_path(db_path: Path) -> Path:
    return Path(db_path).parent / _DESCRIPTOR_NAME


def default_port() -> int:
    return int(os.environ.get("JARVIS_CHROMA_PORT", DEFAULT_PORT))


# =============================================================================
# Part 1: THE OWNERSHIP LOCK (held for a whole process life)
# =============================================================================

class OwnerLock:
    """Non-blocking exclusive lock on byte 0 of a sibling file; bytes 1.. carry
    a JSON note saying who holds it, so a refusal can name the culprit. The OS
    drops the lock when the holder dies, however it dies."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._fh: Any = None

    @property
    def held(self) -> bool:
        return self._fh is not None

    def try_acquire(self, role: str) -> bool:
        if self._fh is not None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "ab"):
            pass
        fh = open(self.path, "r+b")
        try:
            if fh.seek(0, os.SEEK_END) == 0:
                fh.write(b"0")
                fh.flush()
            fh.seek(0)
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            elif msvcrt is not None:
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                raise RuntimeError("no supported file-locking primitive on this platform")
        except OSError:
            fh.close()
            return False
        self._fh = fh
        note = json.dumps({"pid": os.getpid(), "role": role,
                           "argv0": os.path.basename(sys.argv[0]) if sys.argv else "",
                           "since": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
        fh.seek(1)
        fh.truncate()
        fh.write(note.encode("utf-8"))
        fh.flush()
        return True

    def release(self) -> None:
        fh, self._fh = self._fh, None
        if fh is None:
            return
        try:
            fh.seek(0)
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            elif msvcrt is not None:
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        finally:
            fh.close()


def lock_holder(path: Path) -> Dict[str, Any]:
    """Who the lock file says holds it ({} when unreadable). A hint, not proof."""
    try:
        with open(path, "rb") as fh:
            fh.seek(1)
            return json.loads(fh.read().decode("utf-8") or "{}")
    except (OSError, ValueError):
        return {}


def _holder_text(path: Path) -> str:
    info = lock_holder(path)
    if not info:
        return "an unidentified process"
    return (f"pid {info.get('pid')} ({info.get('role')}, {info.get('argv0') or '?'}, "
            f"since {info.get('since')})")


# =============================================================================
# Part 2: THE SERVER DESCRIPTOR AND ITS HEARTBEAT
# =============================================================================

@dataclass(frozen=True)
class ServerState:
    up: bool
    host: str = DEFAULT_HOST
    port: int = 0
    pid: int = 0
    started: str = ""
    has_descriptor: bool = False


def read_descriptor(db_path: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(descriptor_path(db_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("port") else None


def write_descriptor(db_path: Path, info: Dict[str, Any]) -> None:
    target = descriptor_path(db_path)
    tmp = target.with_name(target.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(info), encoding="utf-8")
    for attempt in range(20):
        try:
            os.replace(tmp, target)
            return
        except PermissionError:
            time.sleep(0.05 * (attempt + 1))
    os.replace(tmp, target)


def remove_descriptor(db_path: Path, only_pid: Optional[int] = None) -> None:
    if only_pid is not None:
        current = read_descriptor(db_path)
        if current is not None and int(current.get("pid", 0)) != only_pid:
            return
    try:
        descriptor_path(db_path).unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def heartbeat(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(f"http://{host}:{port}{_HEARTBEAT_PATH}", timeout=timeout) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def server_state(db_path: Path, probe_timeout: float = 1.5) -> ServerState:
    desc = read_descriptor(db_path)
    if desc is None:
        return ServerState(up=False)
    host, port = str(desc.get("host") or DEFAULT_HOST), int(desc["port"])
    return ServerState(up=heartbeat(host, port, probe_timeout), host=host, port=port,
                       pid=int(desc.get("pid") or 0), started=str(desc.get("started") or ""),
                       has_descriptor=True)


# =============================================================================
# Part 3: THE FACTORY
# =============================================================================

@dataclass
class _Entry:
    client: Any
    mode: str
    lock: Optional[OwnerLock]


_CLIENTS: Dict[str, _Entry] = {}
_CLIENTS_LOCK = threading.RLock()


def _open_direct(path: Path, wait_s: float) -> _Entry:
    lock = OwnerLock(lock_path(path))
    require_server = os.environ.get(REQUIRE_SERVER_ENV, "") not in ("", "0")
    deadline = time.monotonic() + max(0.0, wait_s)
    while True:
        state = server_state(path)
        if state.up:
            return _open_http(state)
        if not require_server and lock.try_acquire("direct"):
            break
        if time.monotonic() >= deadline:
            if require_server:
                raise ChromaOwnershipError(
                    f"the Chroma server for {path} is not answering and {REQUIRE_SERVER_ENV} is set "
                    f"(the hearth and its jobs must never take direct ownership: it would block the "
                    f"server's restart). Waited {wait_s:.0f} s. See jarvis_data/chroma_server.log.")
            raise ChromaOwnershipError(
                f"refusing to open {path} directly: it is owned by "
                f"{_holder_text(lock.path)}. Direct mode needs sole ownership; two "
                f"openers of one Chroma store is the corruption this guard exists to "
                f"prevent. Start the hearth (it supervises the Chroma server) or wait "
                f"for the owner to exit. Waited {wait_s:.0f} s (JARVIS_CHROMA_WAIT_S).")
        time.sleep(0.25)
    try:
        remove_descriptor(path)
        import chromadb
        return _Entry(chromadb.PersistentClient(path=str(path)), "direct", lock)
    except BaseException:
        lock.release()
        raise


def _open_http(state: ServerState) -> _Entry:
    import chromadb
    return _Entry(chromadb.HttpClient(host=state.host, port=state.port), "server", None)


def get_chroma_client(db_path: Optional[Path] = None) -> Any:
    """The process-wide client for `db_path` (default DB_ROOT): HttpClient when
    the supervised server answers, else an exclusively-owned PersistentClient.
    Raises ChromaOwnershipError rather than ever opening a second direct client."""
    path = resolve_db_path(db_path)
    key = str(path)
    with _CLIENTS_LOCK:
        entry = _CLIENTS.get(key)
        if entry is not None:
            return entry.client
        state = server_state(path)
        if state.up:
            entry = _open_http(state)
        else:
            wait_s = float(os.environ.get("JARVIS_CHROMA_WAIT_S", DEFAULT_WAIT_S))
            entry = _open_direct(path, wait_s)
        print(f"[Chroma] {entry.mode} mode at {path}", flush=True)
        _CLIENTS[key] = entry
        return entry.client


def chroma_mode(db_path: Optional[Path] = None) -> Optional[str]:
    """'server' | 'direct' for an already-open client in this process, else None."""
    entry = _CLIENTS.get(str(resolve_db_path(db_path)))
    return entry.mode if entry else None


def reset_client_cache(db_path: Optional[Path] = None) -> None:
    """Forget the cached client (and, for direct mode, drop the SQLite handles and
    release ownership) so the next get_chroma_client re-decides the mode."""
    with _CLIENTS_LOCK:
        keys = [str(resolve_db_path(db_path))] if db_path is not None else list(_CLIENTS)
        for key in keys:
            entry = _CLIENTS.pop(key, None)
            if entry is None:
                continue
            if entry.mode == "direct":
                try:
                    from chromadb.api.shared_system_client import SharedSystemClient
                    SharedSystemClient.clear_system_cache()
                except Exception:                              # noqa: BLE001
                    pass
                if entry.lock is not None:
                    entry.lock.release()


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS (scratch dir and scratch ports only)
# =============================================================================

def _free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind((DEFAULT_HOST, 0))
        return s.getsockname()[1]


def _run_self_test() -> int:
    import http.server
    import shutil
    import subprocess
    import tempfile
    from unittest import mock

    passed, failed = 0, []

    def check(name: str, ok: bool, hint: str = "") -> None:
        nonlocal passed
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  {hint}"))
        if ok:
            passed += 1
        else:
            failed.append(name)

    class _Beat(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:                              # noqa: N802
            self.send_response(200 if self.path == _HEARTBEAT_PATH else 404)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *_a: Any) -> None:
            pass

    print("=" * 70)
    print("  chroma_access.py -- self-test (scratch dir, scratch ports)")
    print("=" * 70)
    scratch = Path(tempfile.mkdtemp(prefix="chroma_access_"))
    os.environ["JARVIS_CHROMA_WAIT_S"] = "1"
    try:
        db = scratch / "chromadb"
        db.mkdir()

        # T1: no server, no owner -> direct, lock held by this process.
        c1 = get_chroma_client(db)
        check("T1 no server -> direct mode (PersistentClient)",
              chroma_mode(db) == "direct" and type(c1).__name__ != "HttpClient")
        check("T1b the same client is returned on the second call", get_chroma_client(db) is c1)
        check("T1c the ownership lock is held for the process life",
              not OwnerLock(lock_path(db)).try_acquire("probe"))

        # T2: a second opener (another process) is refused, naming this pid.
        probe = ("import sys; sys.path.insert(0, %r); "
                 "from jarvis_core.memory.chroma_access import get_chroma_client, ChromaOwnershipError; "
                 "import os; os.environ['JARVIS_CHROMA_WAIT_S']='1'\n"
                 "try:\n get_chroma_client(%r); print('OPENED')\n"
                 "except ChromaOwnershipError as e:\n print('REFUSED', e)\n") % (
                     str(Path(__file__).resolve().parents[2]), str(db))
        out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=120)
        check("T2 a second direct process is refused with the owner named",
              "REFUSED" in out.stdout and f"pid {os.getpid()}" in out.stdout, out.stdout + out.stderr)

        # T3: server up (fake heartbeat + descriptor) -> a fresh process gets HttpClient.
        reset_client_cache(db)
        released = OwnerLock(lock_path(db))
        check("T3a resetting a direct client releases ownership", released.try_acquire("probe"))
        released.release()
        port = _free_port()
        beat = http.server.ThreadingHTTPServer((DEFAULT_HOST, port), _Beat)
        threading.Thread(target=beat.serve_forever, daemon=True).start()
        try:
            write_descriptor(db, {"pid": os.getpid(), "host": DEFAULT_HOST, "port": port,
                                  "started": "now", "path": str(db)})
            reset_client_cache(db)
            check("T3 a descriptor plus an answering heartbeat reads as server up", server_state(db).up)
            holder = OwnerLock(lock_path(db))
            with mock.patch("chromadb.HttpClient", side_effect=lambda **kw: ("HTTP", kw)):
                c3 = get_chroma_client(db)
            check("T3b server up -> factory builds an HttpClient for the descriptor's port",
                  chroma_mode(db) == "server" and c3 == ("HTTP", {"host": DEFAULT_HOST, "port": port}), str(c3))
            check("T3c ...and never takes the ownership lock (a server may own it)",
                  holder.try_acquire("probe"))
            holder.release()
            reset_client_cache(db)
        finally:
            beat.shutdown()
            beat.server_close()

        # T3d: the hearth and its jobs set REQUIRE_SERVER: no server means an error, never the lock.
        os.environ[REQUIRE_SERVER_ENV] = "1"
        try:
            try:
                get_chroma_client(db)
                refused = False
            except ChromaOwnershipError as e:
                refused = REQUIRE_SERVER_ENV in str(e)
            free = OwnerLock(lock_path(db))
            check("T3d with the server required and down: an error, and the lock stays free",
                  refused and free.try_acquire("probe"))
            free.release()
        finally:
            del os.environ[REQUIRE_SERVER_ENV]

        # T4: descriptor left behind by a dead server is ignored, then cleaned up.
        check("T4a the dead server no longer answers", not server_state(db).up)
        c4 = get_chroma_client(db)
        check("T4 stale descriptor + free lock -> direct mode, descriptor removed",
              chroma_mode(db) == "direct" and read_descriptor(db) is None)
        reset_client_cache(db)
        del c1, c4
    finally:
        reset_client_cache()
        shutil.rmtree(scratch, ignore_errors=True)
    print("-" * 70)
    print(f"  {passed} passed, {len(failed)} failed")
    print("=" * 70)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_self_test())
