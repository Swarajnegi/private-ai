"""
episode_store.py — the verbatim episode store (Context Store, Layer 0).

LAYER: Memory (Context Store — the photographic memory)

Import with:
    from jarvis_core.memory.episode_store import (
        EpisodeStore, iter_episode, get_turn, list_episodes, read_turn,
        append_compaction, merge_shards, machine_name,
    )

=============================================================================
THE BIG PICTURE
=============================================================================

Every agent the owner talks to (Claude Code, Codex, Antigravity, JARVIS)
already writes its own full transcript somewhere on disk. Until this module,
JARVIS kept only a flattened slice of them — user text plus the final answer
in observation_queue.jsonl — and dropped the tool calls, tool outputs,
reasoning and compaction summaries that record HOW a decision was reached.

This store keeps all of it, verbatim, one normalized event per line:

    {id: "turn:<host>:<session>:<n>", key, episode: "ep:<host>:<session>",
     host, session_id, n, ts, role, kind, content, tool, media, source,
     machine, ...}

    role ∈ user | assistant | tool_call | tool_result | thinking | compaction | system

Three disciplines make it trustworthy as the ROOT of every later index:

1. APPEND-ONLY, NEVER COMPACTED, NEVER DELETED. Facts, summaries and graph
   edges built later are projections that point back to these ids. Nothing is
   cut: a tool output is stored whole however large it is.

2. IDEMPOTENT BY KEY. Each event carries a source-derived `key` (line number,
   step index + content hash, artifact version hash). Re-ingesting the same
   source can only append what is not already there. A manifest records the
   byte offset reached in every append-only source, so the hourly run reads
   only new bytes.

3. SYNC WITHOUT MERGE CONFLICTS. The local store (episodes/) is machine-local
   and gitignored. What travels is shards/<machine>/<host>/<YYYY-MM>.jsonl.gz:
   append-only gzip MEMBERS (an append never rewrites a byte), each file under
   50 MB, and each file written by exactly one machine — so two laptops that
   both run Claude Code never touch the same path. merge_shards() pulls the
   other machine's shards into the local store, idempotent by record id.

   A shard record differs from its local twin in three deliberate ways, all
   recorded on the record itself:
     - a record over 1 MB serialized becomes a STUB {held_by, bytes, sha256}:
       the other machine knows it exists, how big it is and where it lives;
     - tool calls/results that touch a file under client_work/<project>/ are
       stubbed the same way (client source never enters a tracked file);
     - credential-shaped tokens are masked (GitHub push protection would
       otherwise reject the push and freeze sync for both machines);
     - `opaque` blobs (provider-encrypted reasoning, signatures) stay local —
       no machine can read them, and random base64 trips the token masks.

=============================================================================
THE FLOW
=============================================================================

STEP 1: A host parser (memory/episode_sources.py) yields source events
        {key, ts, role, kind, content, tool, media, source, ...}.
        |
STEP 2: EpisodeStore.append(host, session, events) batches them; under the
        session file's lock it drops keys already present, assigns n, writes
        the shard member FIRST, then the local lines (heal-then-append).
        Shard-first means a crash can only duplicate a shard record, which
        merge_shards() de-duplicates by id; it can never lose one.
        |
STEP 3: The caller records the source offset in the manifest.
        |
STEP 4: Readers — iter_episode, get_turn, list_episodes, read_turn (paged).
=============================================================================
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import platform
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # standalone-run safety
from jarvis_core.agent.client_infra import mask as mask_client_infra  # noqa: E402
from jarvis_core.config import DATA_ROOT  # noqa: E402
from jarvis_core.locking import exclusive_lock  # noqa: E402

_IST = timezone(timedelta(hours=5, minutes=30))
MB = 1024 * 1024

STORE_ROOT = Path(DATA_ROOT) / "context_store"
HOSTS: Tuple[str, ...] = ("claude", "codex", "antigravity", "jarvis")
ROLES = frozenset({"user", "assistant", "tool_call", "tool_result",
                   "thinking", "compaction", "system"})

SHARD_LIMIT_BYTES = 50_000_000   # decimal: under 50 MB by every definition (GitHub warns at 50 MiB)
STUB_BYTES = 1 * MB
BATCH_BYTES = 8 * MB          # uncompressed bytes per commit == per gzip member
BATCH_EVENTS = 5000
DEFAULT_PAGE_CHARS = 12_000
MAX_PAGE_CHARS = 48_000
_MIN_PAGE_CHARS = 1_000

_LINE_PREFIX = re.compile(rb'^\{"id": "([^"]+)", "key": "((?:[^"\\]|\\.)*)"')
_CLIENT_PATH = re.compile(r"client_work[\\/]+[A-Za-z0-9_.-]+[\\/]", re.IGNORECASE)
# Prefix-shaped credentials only. capture.py's generic 40-hex / 50-base64
# patterns would also erase git SHAs and sha256 digests from tool output, and
# the shard is the one copy the other machine gets.
_SECRET_PATTERNS = (
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bsk-(?:ant-|proj-|or-v1-)?[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]{20,}"),
)
_SECRET_MASK = "[REDACTED-IN-SHARD]"


# =============================================================================
# Part 1: SMALL PURE HELPERS
# =============================================================================

def machine_name() -> str:
    """This machine's shard namespace. JARVIS_MACHINE overrides platform.node()."""
    return (os.environ.get("JARVIS_MACHINE") or platform.node() or "unknown").strip() or "unknown"


def safe_session(session_id: str) -> str:
    """A session id becomes a filename and an id segment: no ':' or path separators."""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(session_id or ""))[:160] or "unknown"


def episode_id(host: str, session_id: str) -> str:
    return f"ep:{host}:{session_id}"


def turn_id(host: str, session_id: str, n: int) -> str:
    return f"turn:{host}:{session_id}:{n}"


def parse_turn_id(tid: str) -> Optional[Tuple[str, str, int]]:
    parts = str(tid).split(":")
    if len(parts) < 4 or parts[0] != "turn":
        return None
    try:
        return parts[1], ":".join(parts[2:-1]), int(parts[-1])
    except ValueError:
        return None


def parse_episode_id(ep: str) -> Optional[Tuple[str, str]]:
    parts = str(ep).split(":", 2)
    if len(parts) != 3 or parts[0] != "ep":
        return None
    return parts[1], parts[2]


def to_ist(value: Any) -> str:
    """ISO-8601 (with Z/offset) or epoch seconds/ms -> IST ISO string; '' if absent.

    An unparseable string passes through unchanged rather than being dropped.
    """
    if value is None or value == "":
        return ""
    try:
        if isinstance(value, (int, float)):
            seconds = float(value) / (1000.0 if value > 1e11 else 1.0)
            dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
        else:
            text = str(value).strip()
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_IST).isoformat(timespec="milliseconds")
    except (ValueError, OverflowError, OSError):
        return str(value)


def now_ist() -> str:
    return datetime.now(_IST).isoformat(timespec="milliseconds")


def _dumps_line(rec: Dict[str, Any]) -> bytes:
    """One JSON line. Lone surrogates (seen in real transcripts) fall back to
    ASCII escapes so the line stays valid UTF-8 without losing a character."""
    try:
        return (json.dumps(rec, ensure_ascii=False) + "\n").encode("utf-8")
    except UnicodeEncodeError:
        return (json.dumps(rec, ensure_ascii=True) + "\n").encode("utf-8")


def _month_of(ts: str) -> str:
    return ts[:7] if re.match(r"^\d{4}-\d{2}", ts or "") else datetime.now(_IST).strftime("%Y-%m")


def _read_last_line(path: Path) -> bytes:
    """The final complete-or-torn line of a file, reading backwards in chunks."""
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            end = fh.tell()
            if end == 0:
                return b""
            pos, buf = end, b""
            while pos > 0:
                step = min(65536, pos)
                pos -= step
                fh.seek(pos)
                buf = fh.read(step) + buf
                body = buf.rstrip(b"\n")
                idx = body.rfind(b"\n")
                if idx >= 0:
                    return body[idx + 1:]
            return buf.rstrip(b"\n")
    except OSError:
        return b""


def _read_first_line(path: Path) -> bytes:
    try:
        with path.open("rb") as fh:
            return fh.readline().rstrip(b"\n")
    except OSError:
        return b""


def _loads(raw: bytes) -> Optional[Dict[str, Any]]:
    try:
        rec = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    return rec if isinstance(rec, dict) else None


def _append_healed(path: Path, data: bytes) -> int:
    """Append bytes after healing a torn last line; returns the new file size.

    Caller holds the lock. A writer killed mid-line leaves no terminator; the
    next append would otherwise join that fragment and die with it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        prefix = b""
        if size:
            fh.seek(size - 1)
            if fh.read(1) != b"\n":
                prefix = b"\n"
        fh.seek(0, os.SEEK_END)
        fh.write(prefix + data)
        fh.flush()
        os.fsync(fh.fileno())
        return fh.tell()


# =============================================================================
# Part 2: THE MANIFEST (append-only JSONL, folded on read)
# =============================================================================

class Manifest:
    """Per-source ingest progress and per-session store state.

    Two row kinds, newest row per key wins:
      {"t": "source", "source": <key>, "size", "mtime", "offset", "line", ...}
      {"t": "session", "episode": <ep id>, "next_n", "store_bytes", "title", ...}
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._sources: Optional[Dict[str, Dict[str, Any]]] = None
        self._sessions: Optional[Dict[str, Dict[str, Any]]] = None

    def _load(self) -> None:
        if self._sources is not None:
            return
        self._sources, self._sessions = {}, {}
        try:
            fh = self.path.open("rb")
        except OSError:
            return
        with fh:
            for raw in fh:
                rec = _loads(raw)
                if rec is None:
                    continue
                if rec.get("t") == "source" and rec.get("source"):
                    self._sources[str(rec["source"])] = rec
                elif rec.get("t") == "session" and rec.get("episode"):
                    prev = self._sessions.get(str(rec["episode"]), {})
                    if not rec.get("title") and prev.get("title"):
                        rec["title"] = prev["title"]
                    self._sessions[str(rec["episode"])] = rec

    def source(self, key: str) -> Dict[str, Any]:
        self._load()
        return dict(self._sources.get(key, {}))  # type: ignore[union-attr]

    def session(self, ep: str) -> Dict[str, Any]:
        self._load()
        return dict(self._sessions.get(ep, {}))  # type: ignore[union-attr]

    def sources(self) -> Dict[str, Dict[str, Any]]:
        self._load()
        return dict(self._sources)  # type: ignore[arg-type]

    def sessions(self) -> Dict[str, Dict[str, Any]]:
        self._load()
        return dict(self._sessions)  # type: ignore[arg-type]

    def _append(self, rec: Dict[str, Any]) -> None:
        rec = {**rec, "ts": now_ist()}
        with exclusive_lock(self.path):
            _append_healed(self.path, _dumps_line(rec))

    def record_source(self, key: str, **fields: Any) -> None:
        self._load()
        rec = {"t": "source", "source": key, **fields}
        self._append(rec)
        self._sources[key] = rec  # type: ignore[index]

    def record_session(self, ep: str, **fields: Any) -> None:
        self._load()
        prev = self._sessions.get(ep, {})  # type: ignore[union-attr]
        rec = {"t": "session", "episode": ep, **fields}
        if not rec.get("title") and prev.get("title"):
            rec["title"] = prev["title"]
        self._append(rec)
        self._sessions[ep] = rec  # type: ignore[index]


# =============================================================================
# Part 3: SHARDS (per-machine, append-only gzip members, < 50 MB per file)
# =============================================================================

def shard_view(rec: Dict[str, Any], machine: str) -> Dict[str, Any]:
    """The record as it travels in git. See THE BIG PICTURE for each rule."""
    out = {k: v for k, v in rec.items() if k != "opaque"}
    if rec.get("opaque"):
        out["opaque_local"] = sorted(rec["opaque"])
    full = _dumps_line(rec)
    reason = ""
    if len(full) > STUB_BYTES:
        reason = "size"
    elif rec.get("role") in ("tool_call", "tool_result"):
        probe = str(rec.get("content") or "") + json.dumps(rec.get("tool") or {}, ensure_ascii=False)
        if _CLIENT_PATH.search(probe):
            reason = "client_work"
    if reason:
        tool = rec.get("tool") or {}
        out["content"] = ""
        out["tool"] = {k: tool[k] for k in ("name", "id", "use_id", "call_id") if k in tool} or None
        out["stub"] = {"held_by": machine, "bytes": len(full),
                       "sha256": hashlib.sha256(full).hexdigest(), "reason": reason}
        return out
    masked = 0
    for fld in ("content", "tool"):
        val = out.get(fld)
        if val in (None, "", {}):
            continue
        text = val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)
        new = text
        for rx in _SECRET_PATTERNS:
            new, k = rx.subn(_SECRET_MASK, new)
            masked += k
        new, k = mask_client_infra(new)      # client environment names: pseudonymised, not stored in git
        masked += k
        if new != text:
            out[fld] = new if isinstance(val, str) else json.loads(new)
    if masked:
        out["redacted_in_shard"] = masked
    return out


class ShardWriter:
    """Writes IMMUTABLE shard files for ONE machine's namespace.

    Layout: shards/<machine>/<host>/<YYYY-MM>/<run-ts>-<seq>.jsonl.gz. A
    writer only ever appends to files IT created during its own lifetime (one
    run), and never opens a file that already existed when it started — so a
    committed shard is never modified and git never re-stores it. An appended
    monthly file would be a modified binary on every commit: a 31 MB shard
    committed daily is ~1 GB of history a month. Files are created lazily, so
    a run with nothing new writes nothing.
    """

    def __init__(self, shards_root: Path, machine: str, lock_path: Path) -> None:
        self.root = shards_root
        self.machine = machine
        self._lock_path = lock_path
        self._run = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        self._open: Dict[Tuple[str, str], Tuple[Path, int]] = {}   # (host, month) -> (path, size)
        self._seq = 0
        self.created: List[Path] = []

    def host_dir(self, host: str) -> Path:
        return self.root / safe_session(self.machine) / host

    def _new_file(self, host: str, month: str) -> Path:
        d = self.host_dir(host) / month
        d.mkdir(parents=True, exist_ok=True)
        while True:
            self._seq += 1
            path = d / f"{self._run}-{self._seq:04d}.jsonl.gz"
            try:
                with path.open("xb"):
                    pass
            except FileExistsError:
                continue
            self.created.append(path)
            return path

    def write(self, records: List[Dict[str, Any]]) -> int:
        """Append one gzip member per (host, month) to this run's files; returns bytes."""
        groups: Dict[Tuple[str, str], List[bytes]] = {}
        for rec in records:
            key = (str(rec.get("host")), _month_of(str(rec.get("ts") or "")))
            groups.setdefault(key, []).append(_dumps_line(shard_view(rec, self.machine)))
        written = 0
        for (host, month), lines in groups.items():
            member = gzip.compress(b"".join(lines), compresslevel=6, mtime=0)
            with exclusive_lock(self._lock_path):
                path, size = self._open.get((host, month), (None, 0))
                if path is None or (size and size + len(member) >= SHARD_LIMIT_BYTES):
                    path, size = self._new_file(host, month), 0
                with path.open("ab") as fh:
                    fh.write(member)
                    fh.flush()
                    os.fsync(fh.fileno())
                self._open[(host, month)] = (path, size + len(member))
            written += len(member)
        return written


def shard_files(shards_root: Path, machine: Optional[str] = None) -> List[Path]:
    """Every shard file (optionally one machine's), in write order."""
    base = shards_root / safe_session(machine) if machine else shards_root
    return sorted(base.rglob("*.jsonl.gz")) if base.exists() else []


def iter_shard(path: Path) -> Iterator[Dict[str, Any]]:
    """Every record in a (multi-member) shard. A torn trailing member ends the read."""
    try:
        with gzip.open(path, "rb") as fh:
            for raw in fh:
                rec = _loads(raw)
                if rec is not None:
                    yield rec
    except (OSError, EOFError, gzip.BadGzipFile):
        return


# =============================================================================
# Part 4: THE STORE
# =============================================================================

@dataclass
class _SessionState:
    next_n: int = 0
    known_bytes: int = 0
    keys: Set[str] = field(default_factory=set)
    ids: Set[str] = field(default_factory=set)
    keys_loaded: bool = False


class EpisodeStore:
    """Local verbatim store + this machine's shard writer + the manifest."""

    def __init__(self, root: Optional[Path] = None, machine: Optional[str] = None,
                 write_shards: bool = True) -> None:
        self.root = Path(root) if root is not None else STORE_ROOT
        self.machine = machine or machine_name()
        self.episodes_dir = self.root / "episodes"
        self.shards_dir = self.root / "shards"
        self.manifest = Manifest(self.root / "manifest.jsonl")
        self.write_shards = write_shards
        self.shards = ShardWriter(self.shards_dir, self.machine, self.root / "shards")
        self._states: Dict[Tuple[str, str], _SessionState] = {}
        self.stats: Dict[str, int] = {"events": 0, "bytes": 0, "shard_bytes": 0, "skipped": 0}

    # ---- paths & state ---------------------------------------------------

    def session_path(self, host: str, session_id: str) -> Path:
        return self.episodes_dir / host / f"{safe_session(session_id)}.jsonl"

    def _scan(self, path: Path) -> _SessionState:
        st = _SessionState(keys_loaded=True)
        max_n = -1
        try:
            fh = path.open("rb")
        except OSError:
            return st
        with fh:
            for raw in fh:
                m = _LINE_PREFIX.match(raw)
                # A torn line carries a valid-looking prefix; counting its key
                # would make the retry skip the very event the crash lost.
                if not m or _loads(raw) is None:
                    continue
                tid = m.group(1).decode("utf-8", "replace")
                st.ids.add(tid)
                st.keys.add(json.loads(b'"' + m.group(2) + b'"'))
                parsed = parse_turn_id(tid)
                if parsed and parsed[2] > max_n:
                    max_n = parsed[2]
            st.known_bytes = fh.tell()
        st.next_n = max_n + 1
        return st

    def _state(self, host: str, session_id: str, need_keys: bool) -> _SessionState:
        path = self.session_path(host, session_id)
        size = path.stat().st_size if path.exists() else 0
        cached = self._states.get((host, session_id))
        if cached and cached.known_bytes == size and (cached.keys_loaded or not need_keys):
            return cached
        if size == 0:
            st = _SessionState(keys_loaded=True)
        else:
            m = self.manifest.session(episode_id(host, session_id))
            if (not need_keys and m.get("store_bytes") == size
                    and isinstance(m.get("next_n"), int)):
                st = _SessionState(next_n=m["next_n"], known_bytes=size)
            else:
                st = self._scan(path)
        self._states[(host, session_id)] = st
        return st

    # ---- writing -----------------------------------------------------------

    def _build(self, host: str, session_id: str, n: int, ev: Dict[str, Any]) -> Dict[str, Any]:
        role = ev.get("role") or "system"
        if role not in ROLES:
            role = "system"
        rec: Dict[str, Any] = {
            "id": turn_id(host, session_id, n),
            "key": str(ev["key"]),
            "episode": episode_id(host, session_id),
            "host": host,
            "session_id": session_id,
            "n": n,
            "ts": ev.get("ts") or "",
            "role": role,
            "kind": ev.get("kind") or role,
            "content": ev.get("content") if isinstance(ev.get("content"), str) else
                       ("" if ev.get("content") is None else json.dumps(ev.get("content"), ensure_ascii=False)),
            "tool": ev.get("tool"),
            "media": list(ev.get("media") or []),
            "source": ev.get("source") or {},
            "machine": self.machine,
        }
        for extra, val in ev.items():
            if extra not in rec and extra != "key" and val not in (None, "", [], {}):
                rec[extra] = val
        return rec

    def _commit(self, host: str, session_id: str, pending: List[Dict[str, Any]],
                need_keys: bool) -> int:
        path = self.session_path(host, session_id)
        with exclusive_lock(path):
            st = self._state(host, session_id, need_keys)
            recs: List[Dict[str, Any]] = []
            for ev in pending:
                k = str(ev["key"])
                if k in st.keys:
                    self.stats["skipped"] += 1
                    continue
                recs.append(self._build(host, session_id, st.next_n, ev))
                st.next_n += 1
                st.keys.add(k)
            if not recs:
                return 0
            if self.write_shards:
                self.stats["shard_bytes"] += self.shards.write(recs)
            data = b"".join(_dumps_line(r) for r in recs)
            st.known_bytes = _append_healed(path, data)
            st.ids.update(r["id"] for r in recs)
        self.stats["events"] += len(recs)
        self.stats["bytes"] += len(data)
        return len(recs)

    def append(self, host: str, session_id: str, events: Iterable[Dict[str, Any]],
               need_keys: bool = False, title: str = "") -> int:
        """Append source events for one session; returns how many were new.

        need_keys=True for any re-read from the start of a source (dedupe must
        consult every stored key); False on offset-resumed reads, where the
        manifest offset already guarantees novelty and scanning a 150 MB
        session file every hour would be pure waste.
        """
        session_id = safe_session(session_id)
        added = 0
        pending: List[Dict[str, Any]] = []
        pending_bytes = 0
        for ev in events:
            pending.append(ev)
            pending_bytes += len(ev.get("content") or "") + 512
            if pending_bytes >= BATCH_BYTES or len(pending) >= BATCH_EVENTS:
                added += self._commit(host, session_id, pending, need_keys)
                pending, pending_bytes = [], 0
        if pending:
            added += self._commit(host, session_id, pending, need_keys)
        st = self._states.get((host, session_id))
        if st is not None and (added or title):
            self.manifest.record_session(
                episode_id(host, session_id), host=host, session_id=session_id,
                next_n=st.next_n, store_bytes=st.known_bytes, title=title or "")
        return added

    def set_title(self, host: str, session_id: str, title: str) -> None:
        session_id = safe_session(session_id)
        st = self._state(host, session_id, need_keys=False)
        self.manifest.record_session(episode_id(host, session_id), host=host,
                                     session_id=session_id, next_n=st.next_n,
                                     store_bytes=st.known_bytes, title=title)

    def insert_foreign(self, records: List[Dict[str, Any]]) -> int:
        """Insert another machine's records (already id'd) that are not here yet."""
        added = 0
        by_session: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for rec in records:
            host, sid = str(rec.get("host", "")), str(rec.get("session_id", ""))
            if host and sid and rec.get("id"):
                by_session.setdefault((host, safe_session(sid)), []).append(rec)
        for (host, sid), recs in by_session.items():
            path = self.session_path(host, sid)
            with exclusive_lock(path):
                st = self._state(host, sid, need_keys=True)
                new = [r for r in recs if r["id"] not in st.ids]
                if not new:
                    continue
                st.known_bytes = _append_healed(path, b"".join(_dumps_line(r) for r in new))
                for r in new:
                    st.ids.add(r["id"])
                    st.keys.add(str(r.get("key", "")))
                    if isinstance(r.get("n"), int) and r["n"] >= st.next_n:
                        st.next_n = r["n"] + 1
                added += len(new)
            self.manifest.record_session(episode_id(host, sid), host=host, session_id=sid,
                                         next_n=st.next_n, store_bytes=st.known_bytes,
                                         title="", foreign=True)
        return added


# =============================================================================
# Part 5: MERGE (pull another machine's shards into the local store)
# =============================================================================

def merge_shards(store: Optional[EpisodeStore] = None) -> Dict[str, int]:
    """Ingest every shard NOT written by this machine. Idempotent by record id."""
    store = store or EpisodeStore()
    out = {"shards_read": 0, "records_seen": 0, "records_added": 0}
    if not store.shards_dir.exists():
        return out
    own = safe_session(store.machine)
    for mdir in sorted(p for p in store.shards_dir.iterdir() if p.is_dir()):
        if mdir.name == own:
            continue
        for shard in shard_files(mdir.parent, mdir.name):
            st = shard.stat()
            key = "shard:" + shard.relative_to(store.shards_dir).as_posix()
            prev = store.manifest.source(key)
            # Shards are immutable, so name + size identifies one; mtime is
            # not compared because a git checkout rewrites it.
            if prev.get("size") == st.st_size:
                continue
            out["shards_read"] += 1
            batch: List[Dict[str, Any]] = []
            for rec in iter_shard(shard):
                out["records_seen"] += 1
                batch.append(rec)
                if len(batch) >= BATCH_EVENTS:
                    out["records_added"] += store.insert_foreign(batch)
                    batch = []
            if batch:
                out["records_added"] += store.insert_foreign(batch)
            store.manifest.record_source(key, size=st.st_size, mtime=st.st_mtime, kind="shard")
    return out


# =============================================================================
# Part 6: READERS
# =============================================================================

def _root(root: Optional[Path]) -> Path:
    return Path(root) if root is not None else STORE_ROOT


def iter_episode(ep_id: str, root: Optional[Path] = None) -> Iterator[Dict[str, Any]]:
    """Every stored event of one episode, in stored (n) order."""
    parsed = parse_episode_id(ep_id)
    if not parsed:
        return
    path = _root(root) / "episodes" / parsed[0] / f"{safe_session(parsed[1])}.jsonl"
    try:
        fh = path.open("rb")
    except OSError:
        return
    with fh:
        for raw in fh:
            rec = _loads(raw)
            if rec is not None:
                yield rec


def get_turn(tid: str, root: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """One event by id. Matches the line prefix before parsing, so a scan is cheap."""
    parsed = parse_turn_id(tid)
    if not parsed:
        return None
    host, sid, _ = parsed
    path = _root(root) / "episodes" / host / f"{safe_session(sid)}.jsonl"
    needle = ('{"id": ' + json.dumps(tid) + ",").encode("utf-8")
    try:
        fh = path.open("rb")
    except OSError:
        return None
    with fh:
        for raw in fh:
            if raw.startswith(needle):
                return _loads(raw)
    return None


def list_episodes(host: Optional[str] = None, since: Optional[str] = None,
                  root: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Every episode (optionally one host; optionally last activity >= since)."""
    base = _root(root)
    manifest = Manifest(base / "manifest.jsonl").sessions()
    out: List[Dict[str, Any]] = []
    hosts = [host] if host else sorted(p.name for p in (base / "episodes").glob("*") if p.is_dir())
    for h in hosts:
        for path in sorted((base / "episodes" / h).glob("*.jsonl")):
            first = _loads(_read_first_line(path)) or {}
            last = _loads(_read_last_line(path)) or {}
            last_ts = str(last.get("ts") or first.get("ts") or "")
            if since and last_ts and last_ts < since:
                continue
            ep = episode_id(h, path.stem)
            out.append({
                "episode": ep, "host": h, "session_id": path.stem,
                "path": str(path), "bytes": path.stat().st_size,
                "first_ts": str(first.get("ts") or ""), "last_ts": last_ts,
                "events": (int(last["n"]) + 1) if isinstance(last.get("n"), int) else None,
                "title": manifest.get(ep, {}).get("title", ""),
                "machine": first.get("machine", ""),
            })
    return out


def render_event(rec: Dict[str, Any]) -> str:
    """The one text form of an event that read_turn page offsets index into."""
    parts = [str(rec.get("content") or "")]
    tool = rec.get("tool")
    if tool and rec.get("role") in ("tool_call", "tool_result"):
        tool_text = json.dumps(tool, ensure_ascii=False)
        if tool_text not in parts[0]:
            parts.insert(0, f"[tool] {tool_text}")
    if rec.get("stub"):
        parts.append(f"[held locally by {rec['stub'].get('held_by')}: "
                     f"{rec['stub'].get('bytes')} bytes, sha256 {rec['stub'].get('sha256')}]")
    if rec.get("media"):
        parts.append("[media] " + " ".join(map(str, rec["media"])))
    return "\n".join(p for p in parts if p)


def read_turn(tid: str, offset: int = 0, page_chars: int = DEFAULT_PAGE_CHARS,
              root: Optional[Path] = None) -> Dict[str, Any]:
    """Page through one (possibly multi-MB) event: every page states next_offset."""
    rec = get_turn(tid, root)
    if rec is None:
        return {"id": tid, "error": "not found"}
    text = render_event(rec)
    total = len(text)
    page = min(MAX_PAGE_CHARS, max(_MIN_PAGE_CHARS, int(page_chars)))
    offset = max(0, int(offset))
    if offset > total:
        return {"id": tid, "error": f"offset {offset} past end ({total} chars)"}
    end = min(total, offset + page)
    return {
        "id": tid, "episode": rec.get("episode"), "role": rec.get("role"),
        "kind": rec.get("kind"), "ts": rec.get("ts"),
        "total_chars": total, "offset": offset, "returned_chars": end - offset,
        "next_offset": None if end >= total else end, "complete": end >= total,
        "content": text[offset:end],
    }


# =============================================================================
# Part 7: SINGLE-EVENT WRITERS (JARVIS's own compactor)
# =============================================================================

def append_compaction(session_id: str, messages: List[Dict[str, Any]],
                      handle: Optional[str] = None, host: str = "jarvis",
                      root: Optional[Path] = None, ts: Optional[str] = None) -> Optional[str]:
    """Archive a span evicted by compaction as ONE role=compaction event.

    content is the verbatim message list as JSON — lossless, unlike any
    rendered transcript. Returns the turn id, or None on failure (never raises:
    the compactor's own ledger remains the gate on whether eviction proceeds).
    """
    try:
        if not session_id or not messages:
            return None
        body = json.dumps([{"role": str(m.get("role", "")), "content": str(m.get("content", ""))}
                           for m in messages], ensure_ascii=False)
        digest = handle or hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
        store = EpisodeStore(root=root)
        added = store.append(host, session_id, [{
            "key": f"compaction:{digest}", "ts": ts or now_ist(), "role": "compaction",
            "kind": "jarvis_compaction", "content": body,
            "tool": {"handle": handle, "message_count": len(messages)} if handle else
                    {"message_count": len(messages)},
            "source": {"path": "jarvis_core/agent/compact.py", "handle": handle},
        }], need_keys=True)
        st = store._states.get((host, safe_session(session_id)))
        if not added or st is None:
            return None
        return turn_id(host, safe_session(session_id), st.next_n - 1)
    except Exception:
        return None


# =============================================================================
# SMOKE TESTS (temp dirs only — never touches the real store)
# =============================================================================

def _run_self_test() -> None:
    import tempfile

    print("=" * 70)
    print("  episode_store.py -- Smoke Tests")
    print("=" * 70)
    passed = 0
    failed: List[str] = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        nonlocal passed
        if cond:
            passed += 1
            print(f"  PASS  {name}")
        else:
            failed.append(name)
            print(f"  FAIL  {name}  {hint}")

    def ev(k: str, content: str = "x", role: str = "user", ts: str = "2026-09-01T10:00:00.000+05:30",
           **kw: Any) -> Dict[str, Any]:
        return {"key": k, "ts": ts, "role": role, "content": content, **kw}

    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "cs"
        s = EpisodeStore(root=root, machine="alpha")
        n = s.append("claude", "sess-1", [ev("L0"), ev("L1", role="assistant"), ev("L2", role="bogus")])
        check("T1 three events appended", n == 3, str(n))
        recs = list(iter_episode("ep:claude:sess-1", root))
        check("T2 ids are turn:<host>:<session>:<n> with n monotonic",
              [r["id"] for r in recs] == [f"turn:claude:sess-1:{i}" for i in range(3)])
        check("T3 unknown role normalizes to system", recs[2]["role"] == "system")
        check("T4 re-append with need_keys is a no-op",
              EpisodeStore(root=root, machine="alpha").append(
                  "claude", "sess-1", [ev("L0"), ev("L1")], need_keys=True) == 0)
        s2 = EpisodeStore(root=root, machine="alpha")
        check("T5 a fresh store resumes n from the manifest",
              s2.append("claude", "sess-1", [ev("L3")]) == 1
              and get_turn("turn:claude:sess-1:3", root) is not None)

        # torn last line heals and is not joined to the next record
        p = s2.session_path("claude", "sess-1")
        with p.open("ab") as fh:
            fh.write(b'{"id": "turn:claude:sess-1:99", "key": "torn"')
        s3 = EpisodeStore(root=root, machine="alpha")
        s3.append("claude", "sess-1", [ev("L4")], need_keys=True)
        check("T6 append after a torn line keeps the new record whole",
              get_turn("turn:claude:sess-1:4", root) is not None,
              str([r["id"] for r in iter_episode("ep:claude:sess-1", root)]))

        # paging
        big = "abc" * 20_000
        s3.append("codex", "c1", [ev("L0", big, role="tool_result", tool={"name": "exec"})])
        page = read_turn("turn:codex:c1:0", 0, 12_000, root)
        pieces, off = [], 0
        while True:
            pg = read_turn("turn:codex:c1:0", off, 12_000, root)
            pieces.append(pg["content"])
            if pg["complete"]:
                break
            off = pg["next_offset"]
        check("T7 paging returns the whole event across pages",
              "".join(pieces) == render_event(get_turn("turn:codex:c1:0", root))
              and not page["complete"] and big in "".join(pieces))

        # shards: > 1 MB stubbed in shard only; secrets masked in shard only; opaque local
        huge = "Z" * (STUB_BYTES + 10)
        s3.append("codex", "c2", [
            ev("L0", huge, role="tool_result", tool={"name": "exec", "call_id": "c"}),
            ev("L1", "token github_pat_" + "A" * 30, role="assistant"),
            ev("L2", "", role="thinking", opaque={"encrypted_content": "gAAAA"}),
            ev("L3", "cat client_work/bupa/x.py", role="tool_call", tool={"name": "Bash"}),
        ])
        shard_recs = [r for f in shard_files(root / "shards", "alpha")
                      for r in iter_shard(f) if r["session_id"] == "c2"]
        local = {r["key"]: r for r in iter_episode("ep:codex:c2", root)}
        by_key = {r["key"]: r for r in shard_recs}
        check("T8 >1 MB content is a stub in the shard with held_by/bytes/sha256",
              by_key["L0"]["content"] == "" and by_key["L0"]["stub"]["held_by"] == "alpha"
              and by_key["L0"]["stub"]["bytes"] > STUB_BYTES
              and len(by_key["L0"]["stub"]["sha256"]) == 64, str(by_key["L0"].get("stub")))
        check("T9 ...and whole in the local store", local["L0"]["content"] == huge)
        check("T10 credentials masked in the shard, verbatim locally",
              "github_pat_" not in by_key["L1"]["content"] and "github_pat_" in local["L1"]["content"])
        check("T11 opaque blobs stay local", "opaque" not in by_key["L2"]
              and local["L2"]["opaque"]["encrypted_content"] == "gAAAA")
        check("T12 client_work tool events are stubbed in the shard",
              by_key["L3"]["stub"]["reason"] == "client_work" and by_key["L3"]["content"] == "")

        # shard roll at the size limit
        global SHARD_LIMIT_BYTES
        saved = SHARD_LIMIT_BYTES
        SHARD_LIMIT_BYTES = 3000
        try:
            import random
            rnd = random.Random(7)
            for i in range(6):
                noise = "".join(rnd.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(2000))
                s3.append("antigravity", "roll", [ev(f"k{i}", noise, ts="2026-08-15T00:00:00+05:30")])
        finally:
            SHARD_LIMIT_BYTES = saved
        parts = sorted((root / "shards" / "alpha" / "antigravity" / "2026-08").glob("*.jsonl.gz"))
        check("T13 a run rolls to a new file at the limit; every file stays under it",
              len(parts) > 1 and all(p.stat().st_size < 3000 for p in parts),
              str([(p.name, p.stat().st_size) for p in parts]))
        check("T14 every rolled record is still readable",
              sum(1 for p in parts for _ in iter_shard(p)) == 6)

        # immutability: a later run never modifies an existing shard file
        import hashlib as _h
        snap = {p: _h.sha256(p.read_bytes()).hexdigest() for p in shard_files(root / "shards")}
        later = EpisodeStore(root=root, machine="alpha")
        later.append("codex", "c2", [ev("L9", "one more", role="assistant")])
        after = {p: _h.sha256(p.read_bytes()).hexdigest() for p in shard_files(root / "shards")}
        check("T14b a later run leaves every existing shard byte-identical, adds one new file",
              all(after[p] == d for p, d in snap.items()) and len(after) == len(snap) + 1
              and later.shards.created and later.shards.created[0] not in snap)
        idle = EpisodeStore(root=root, machine="alpha")
        idle.append("codex", "c2", [ev("L9", "one more", role="assistant")], need_keys=True)
        check("T14c a run with no new events writes no shard file",
              not idle.shards.created and len(shard_files(root / "shards")) == len(after))

        # merge from another machine's shard
        other_root = Path(td) / "other"
        beta = EpisodeStore(root=other_root, machine="beta")
        beta.append("claude", "work-1", [ev("L0", "from beta"), ev("L1", huge, role="tool_result")])
        import shutil
        shutil.copytree(other_root / "shards" / "beta", root / "shards" / "beta")
        mine = EpisodeStore(root=root, machine="alpha")
        r1 = merge_shards(mine)
        merged = list(iter_episode("ep:claude:work-1", root))
        check("T15 merge brings the other machine's session in, ids preserved",
              r1["records_added"] == 2 and [m["id"] for m in merged]
              == ["turn:claude:work-1:0", "turn:claude:work-1:1"], str(r1))
        check("T16 the merged >1 MB record arrives as a stub naming its holder",
              merged[1].get("stub", {}).get("held_by") == "beta" and merged[1]["content"] == "")
        r2 = merge_shards(EpisodeStore(root=root, machine="alpha"))
        check("T17 re-merge is a no-op", r2["records_added"] == 0, str(r2))
        (root / "manifest.jsonl").write_text("", encoding="utf-8")
        r3 = merge_shards(EpisodeStore(root=root, machine="alpha"))
        check("T18 even with a lost manifest, merge dedupes by id",
              r3["records_added"] == 0 and r3["records_seen"] == 2, str(r3))
        check("T19 own shards are never merged back", not any(
            m.get("machine") == "alpha" for m in merged))

        eps = list_episodes(root=root)
        check("T20 list_episodes covers every host/session",
              {e["episode"] for e in eps} >= {"ep:claude:sess-1", "ep:codex:c2", "ep:claude:work-1"})
        check("T21 list_episodes(since=future) filters by last activity",
              list_episodes(root=root, since="2099") == [])

        tid = append_compaction("conv-x", [{"role": "user", "content": "q"},
                                           {"role": "assistant", "content": "a"}],
                                handle="abc", root=root)
        rec = get_turn(tid or "", root)
        check("T22 append_compaction stores the verbatim span as role=compaction",
              rec is not None and rec["role"] == "compaction"
              and json.loads(rec["content"])[1]["content"] == "a", str(rec))
        again = append_compaction("conv-x", [{"role": "user", "content": "q"},
                                             {"role": "assistant", "content": "a"}],
                                  handle="abc", root=root)
        check("T23 the same span twice is stored once",
              again is None and len(list(iter_episode("ep:jarvis:conv-x", root))) == 1)
        check("T24 safe_session strips separators", safe_session("a:b/c\\d") == "a_b_c_d")

    total = passed + len(failed)
    print("-" * 70)
    print(f"  {passed}/{total} passed")
    if failed:
        for name in failed:
            print(f"    - {name}")
    print("=" * 70)
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    _run_self_test()
