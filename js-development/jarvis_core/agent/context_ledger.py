"""
context_ledger.py — the backing store that makes eviction reversible.

LAYER: Agent (Memory — the swap file)

Import with:
    from jarvis_core.agent.context_ledger import ContextLedger, LedgerHandle

=============================================================================
THE BIG PICTURE
=============================================================================

Compaction was a ONE-WAY DOOR. compact.py replaced a window of history with a
single summary and persisted the originals NOWHERE — they were dropped from the
list and simply ceased to exist. Two consequences, both fatal to the user's
stated goal of "infinite context":

  1. IRREVERSIBLE. If the summary omitted the one detail that later mattered,
     nothing could recover it. The model could not even know it was missing.
  2. DRIFT COMPOUNDS. A second compaction summarised the first summary. Over a
     long session that is a copy of a copy of a copy — error accumulating with
     no floor, and no way to go back to the source.

This module is the swap file for the context window. It inverts the MemGPT
insight the previous design had backwards: PAGING OUT IS NOT DELETING. A
summary should be an INDEX ENTRY pointing at retrievable content, never a
replacement for lost content.

    "infinite memory" (already solved) = bytes on disk
    "infinite context" (this)          = bounded resident set over an
                                         unbounded, handle-addressable store

THE ANTI-DRIFT LAW, and it is the reason spans are stored whole rather than
per-message: EVERY SUMMARY IS COMPUTED FROM THE ORIGINALS, NEVER FROM A PRIOR
SUMMARY. When a tighter compaction is needed, the compactor expands the previous
boundary's handle, unions those originals with the newly-evicted messages, and
re-summarises THAT. Derivation depth stays 1 no matter how many times you
compact, so error cannot compound over months. This is the same rule
cognitive_index.py:198-203 already states for itself ("full rebuild every time,
not incremental sync") applied to summaries.

Content addressing (sha256 of role+content) means an identical span archived
twice costs one record, and a handle is a checksum: expand() returning content
that does not hash to its own handle is a detectable corruption, not a silent
wrong answer.

=============================================================================
THE FLOW
=============================================================================

STEP 1: compact.py is about to evict a window. It calls
        archive_span(messages) FIRST — nothing is dropped before it is stored.
        |
STEP 2: The span is written verbatim as ONE append-only, flock'd JSONL record
        under jarvis_data/context/<session_id>.jsonl, keyed by a
        content-addressed handle. Same discipline as capture.py:281-292.
        |
STEP 3: The handle is stamped into the SystemCompactBoundaryMessage, so the
        live transcript always carries a pointer back to what it dropped.
        |
STEP 4: expand_span(handle) returns the original messages byte-identical, for
        the context_expand tool (model-driven page-in) or for the next
        compaction's anti-drift union.
=============================================================================
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # standalone-run safety

from jarvis_core.config import DATA_ROOT

_IST = timezone(timedelta(hours=5, minutes=30))
_CONTEXT_ROOT = Path(DATA_ROOT) / "context"

# Handles appear inside the boundary message so the transcript itself carries
# the pointer. 16 hex chars of sha256 — collision-free at any plausible scale
# and short enough to read in a prompt.
_HANDLE_LEN = 16
HANDLE_PREFIX = "ctx:"
_HANDLE_RE = re.compile(rf"{re.escape(HANDLE_PREFIX)}([0-9a-f]{{{_HANDLE_LEN}}})")


@dataclass(frozen=True)
class LedgerHandle:
    """A content-addressed pointer to an archived span."""
    handle: str
    message_count: int
    chars: int

    @property
    def token(self) -> str:
        """The form embedded in a boundary message."""
        return f"{HANDLE_PREFIX}{self.handle}"


def _ends_with_newline(handle: Any) -> bool:
    """True when the file is empty or its last byte is already a newline.

    Every append-only log in this repo needs this and only kb_append.py had it
    (2026-09-08). A lock stops two writers colliding; it does NOT stop a writer
    that was KILLED from leaving a line with no terminator, and the next append
    then joins that torn line and dies with it. Guarding costs one seek.
    """
    try:
        handle.seek(0, 2)                      # SEEK_END
        if handle.tell() == 0:
            return True
        handle.seek(handle.tell() - 1)
        return handle.read(1) == "\n"
    except (OSError, ValueError):
        return True                            # unseekable -> never block a write


def _span_digest(messages: List[Dict[str, str]]) -> str:
    h = hashlib.sha256()
    for m in messages:
        h.update(str(m.get("role", "")).encode("utf-8"))
        h.update(b"\x00")
        h.update(str(m.get("content", "")).encode("utf-8"))
        h.update(b"\x1e")
    return h.hexdigest()[:_HANDLE_LEN]


def extract_handles(text: str) -> List[str]:
    """Every ledger handle mentioned in a string, in order, de-duplicated.

    Used by the compactor to find prior boundaries inside a window it is about
    to re-compact — the mechanism that enforces the anti-drift law.
    """
    seen: List[str] = []
    for h in _HANDLE_RE.findall(text or ""):
        if h not in seen:
            seen.append(h)
    return seen


class ContextLedger:
    """Append-only verbatim store for evicted context spans."""

    def __init__(self, session_id: str, root: Optional[Path] = None) -> None:
        self._session = self._safe_session(session_id)
        self._root = Path(root) if root else _CONTEXT_ROOT

    @staticmethod
    def _safe_session(session_id: str) -> str:
        """A session id becomes a filename, so it must not traverse."""
        cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", str(session_id or "unknown"))
        return cleaned[:120] or "unknown"

    @property
    def path(self) -> Path:
        return self._root / f"{self._session}.jsonl"

    # ---- write ----------------------------------------------------------

    def archive_span(self, messages: List[Dict[str, str]]) -> Optional[LedgerHandle]:
        """Store a span VERBATIM and return its handle. None on empty/failure.

        Called BEFORE eviction. A None return must make the caller abandon the
        compaction — evicting without archiving is the bug this module exists
        to prevent, so the caller treats a failed write as "do not compact".
        """
        if not messages:
            return None
        handle = _span_digest(messages)
        chars = sum(len(str(m.get("content", ""))) for m in messages)
        record = {
            "ts": datetime.now(_IST).isoformat(timespec="seconds"),
            "handle": handle,
            "message_count": len(messages),
            "chars": chars,
            "messages": [
                {"role": str(m.get("role", "")), "content": str(m.get("content", ""))}
                for m in messages
            ],
        }
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            with self.path.open("a+", encoding="utf-8") as fh:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
                try:
                    # Heal a missing terminator first: a killed process leaves a
                    # line with no "\n", and the next append would join it and be
                    # destroyed with it. Costs one seek; without it an evicted
                    # span becomes unrecoverable, which defeats this whole file.
                    line = json.dumps(record, ensure_ascii=False)
                    fh.write(("" if _ends_with_newline(fh) else "\n") + line + "\n")
                    fh.flush()
                    os.fsync(fh.fileno())
                finally:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            return None
        return LedgerHandle(handle=handle, message_count=len(messages), chars=chars)

    # ---- read -----------------------------------------------------------

    def expand_span(self, handle: str) -> Optional[List[Dict[str, str]]]:
        """Return an archived span byte-identical, or None if absent/corrupt.

        Verifies the content still hashes to its own handle: a mismatch is
        detectable corruption, and returning None is strictly better than
        handing the model silently-wrong history.
        """
        want = (handle or "").strip()
        if want.startswith(HANDLE_PREFIX):
            want = want[len(HANDLE_PREFIX):]
        if not want:
            return None
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    if want not in line:      # cheap reject before parsing
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if rec.get("handle") != want:
                        continue
                    msgs = rec.get("messages") or []
                    if _span_digest(msgs) != want:
                        return None           # corrupt, not merely missing
                    return msgs
        except (OSError, FileNotFoundError):
            return None
        return None

    def expand_all(self, handles: List[str]) -> List[Dict[str, str]]:
        """Flatten several spans in the order given. Missing handles are skipped."""
        out: List[Dict[str, str]] = []
        for h in handles:
            span = self.expand_span(h)
            if span:
                out.extend(span)
        return out

    def stats(self) -> Tuple[int, int]:
        """(spans, messages) archived for this session. Diagnostics only."""
        spans = msgs = 0
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    spans += 1
                    msgs += int(rec.get("message_count", 0) or 0)
        except (OSError, FileNotFoundError):
            pass
        return spans, msgs


# =============================================================================
# SMOKE TESTS (offline — temp dirs only, no network, no shared state)
# =============================================================================

def _run_self_test() -> None:
    import tempfile

    print("=" * 70)
    print("  context_ledger.py -- Smoke Tests")
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

    span = [
        {"role": "user", "content": "what did we decide about retention?"},
        {"role": "assistant", "content": "720 hours, not 168 — the framework overrode it."},
        {"role": "tool", "content": "x" * 5000},
    ]

    with tempfile.TemporaryDirectory() as td:
        led = ContextLedger("sess-1", root=Path(td))

        h = led.archive_span(span)
        check("T1 archive returns a handle", h is not None and len(h.handle) == 16,
              str(h))
        check("T2 handle carries span shape",
              h.message_count == 3 and h.chars > 5000, str(h))

        # T3 -- THE POINT OF THE WHOLE MODULE.
        back = led.expand_span(h.handle)
        check("T3 expand returns the span BYTE-IDENTICAL", back == span,
              f"{(back or [{}])[0]}")

        check("T4 expand accepts the ctx: prefixed form",
              led.expand_span(h.token) == span)
        check("T5 unknown handle -> None, not a crash",
              led.expand_span("0" * 16) is None)
        check("T6 empty handle -> None", led.expand_span("") is None)

        # T7 -- content addressing: same span twice is the same handle.
        h2 = led.archive_span(span)
        check("T7 content-addressed: identical span, identical handle",
              h2.handle == h.handle, f"{h2.handle} vs {h.handle}")

        h3 = led.archive_span([{"role": "user", "content": "different"}])
        check("T8 different span, different handle", h3.handle != h.handle)

        check("T9 empty span archives to None", led.archive_span([]) is None)

        both = led.expand_all([h.handle, h3.handle])
        check("T10 expand_all flattens in order",
              len(both) == 4 and both[3]["content"] == "different", str(len(both)))
        check("T11 expand_all skips missing handles silently",
              len(led.expand_all(["f" * 16, h3.handle])) == 1)

        spans, msgs = led.stats()
        check("T12 stats counts spans and messages",
              spans == 3 and msgs == 7, f"spans={spans} msgs={msgs}")

    # T13 -- corruption is detected, not served.
    with tempfile.TemporaryDirectory() as td:
        led = ContextLedger("sess-2", root=Path(td))
        h = led.archive_span(span)
        raw = led.path.read_text(encoding="utf-8")
        rec = json.loads(raw.strip())
        rec["messages"][0]["content"] = "TAMPERED"
        led.path.write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
        check("T13 tampered span fails its own checksum -> None",
              led.expand_span(h.handle) is None)

    # T14-T15 -- handle extraction from a boundary message.
    text = ("[compacted 12 earlier messages | recoverable: ctx:aaaaaaaaaaaaaaaa, "
            "ctx:bbbbbbbbbbbbbbbb]\nSummary here. ctx:aaaaaaaaaaaaaaaa again.")
    got = extract_handles(text)
    check("T14 extract_handles finds all handles, de-duplicated",
          got == ["a" * 16, "b" * 16], str(got))
    check("T15 extract_handles on plain prose returns nothing",
          extract_handles("no handles in this summary at all") == [])

    # T16 -- path traversal in a session id must not escape.
    with tempfile.TemporaryDirectory() as td:
        led = ContextLedger("../../etc/passwd", root=Path(td))
        led.archive_span(span)
        check("T16 session id cannot traverse out of the root",
              led.path.parent == Path(td) and "/" not in led.path.name,
              str(led.path))

    with tempfile.TemporaryDirectory() as td:
        led = ContextLedger("never-written", root=Path(td))
        check("T17 reading a session with no file degrades quietly",
              led.expand_span("a" * 16) is None and led.stats() == (0, 0))

    print("-" * 70)
    print(f"  {passed} passed, {len(failed)} failed")
    if failed:
        for name in failed:
            print(f"    - {name}")
    print("=" * 70)
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    _run_self_test()
