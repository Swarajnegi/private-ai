"""
eval_exclusions.py — keeps the c002 evaluation out of every training corpus.

LAYER: Specialists (corpus assembly) + the evaluation harness

=============================================================================
THE BIG PICTURE
=============================================================================
Every Claude Code prompt and reply is captured to observation_queue.jsonl, parsed
into verdicts, and flows into the training corpora. The session that AUTHORS an
evaluation therefore writes its own answer key into the training data: the
adapter would be trained on the questions it is later tested on, and a retrieval
arm would find the gold in the episode index. Nothing in the corpus builders
filtered this, and eval markers were already found in blended_corpus.jsonl.

This module is the single place that says "this material belongs to the
measurement, not to the owner's life". It holds two things:

    * session exclusions   a session-id prefix, optionally from a timestamp on
                           ("since"), so a long working session keeps feeding
                           training for everything BEFORE the eval was authored
    * canaries             unique strings placed in every c002 file; a record
                           that contains one is dropped whatever session it is in

Readers: the three corpus builders, `check_pipeline.py` (invariant), the recall
router (contamination markers) and `scripts/eval_c002.py` (audit, scoring).

=============================================================================
THE FLOW
=============================================================================
STEP 1: `load_registry()` reads jarvis_data/eval/c002/exclusions.json, cached by
        mtime; a missing file is an empty registry, a corrupt one raises.
        |
STEP 2: a builder asks `excluded_turn(registry, session_id, ts, *texts)`.
        |
STEP 3: the answer is True when the session matches a prefix whose `since` is
        at or before ts, or any text holds a canary. The builder drops the record.
=============================================================================
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

from jarvis_core.config import DATA_ROOT

REGISTRY_PATH = Path(DATA_ROOT) / "eval" / "c002" / "exclusions.json"
IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))


@dataclass(frozen=True)
class SessionExclusion:
    prefix: str
    since: Optional[_dt.datetime]
    reason: str


@dataclass(frozen=True)
class Registry:
    sessions: Tuple[SessionExclusion, ...] = ()
    canaries: Tuple[str, ...] = ()


_cache: Dict[str, Tuple[Tuple[int, int], Registry]] = {}


def parse_ts(value: str) -> Optional[_dt.datetime]:
    """An ISO timestamp as an aware datetime; a naive one is read as IST."""
    try:
        parsed = _dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=IST)


def load_registry(path: Path = REGISTRY_PATH) -> Registry:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return Registry()
    mtime = (stat.st_mtime_ns, stat.st_size)
    cached = _cache.get(str(path))
    if cached and cached[0] == mtime:
        return cached[1]
    raw = json.loads(path.read_text(encoding="utf-8"))
    sessions = []
    for entry in raw.get("sessions", []):
        prefix = str(entry.get("prefix", "")).strip()
        if len(prefix) < 8:
            raise ValueError(f"{path}: session prefix {prefix!r} is too short to be safe")
        since = None
        if entry.get("since"):
            since = parse_ts(entry["since"])
            if since is None:
                raise ValueError(f"{path}: unparseable since {entry['since']!r}")
        sessions.append(SessionExclusion(prefix, since, str(entry.get("reason", ""))))
    canaries = tuple(str(c) for c in raw.get("canaries", []) if str(c).strip())
    if any(len(c) < 16 for c in canaries):
        raise ValueError(f"{path}: a canary shorter than 16 characters would match ordinary text")
    registry = Registry(tuple(sessions), canaries)
    _cache[str(path)] = (mtime, registry)
    return registry


def has_canary(registry: Registry, *texts: str) -> bool:
    return any(c in (t or "") for c in registry.canaries for t in texts)


def excluded_session(registry: Registry, session_id: str, ts: str = "") -> bool:
    """True when `session_id` falls under an exclusion in force at `ts`.

    A `since` bound with an unparseable or missing ts excludes: when the order of
    events cannot be established, the safe reading is that it is inside the window.
    """
    for entry in registry.sessions:
        if not str(session_id).startswith(entry.prefix):
            continue
        if entry.since is None:
            return True
        moment = parse_ts(ts)
        if moment is None or moment >= entry.since:
            return True
    return False


def excluded_turn(registry: Registry, session_id: str, ts: str, *texts: str) -> bool:
    return excluded_session(registry, session_id, ts) or has_canary(registry, *texts)


def session_prefixes(registry: Registry) -> Tuple[str, ...]:
    """Prefixes for the recall router, which excludes whole sessions only."""
    return tuple(sorted({e.prefix for e in registry.sessions}))


def _self_test() -> int:
    import tempfile

    failures = 0

    def check(name: str, got: object, want: object) -> None:
        nonlocal failures
        ok = got == want
        failures += not ok
        print(f"  [{'OK' if ok else 'FAIL'}] {name}" + ("" if ok else f"  got={got!r} want={want!r}"))

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "exclusions.json"
        check("missing file is an empty registry", load_registry(path), Registry())
        path.write_text(json.dumps({
            "sessions": [{"prefix": "f44ca14d-4868", "since": "2026-10-07T10:00:00+05:30", "reason": "c002"},
                         {"prefix": "whole-session-1", "reason": "always"}],
            "canaries": ["c002-canary-0123456789abcdef"]}), encoding="utf-8")
        reg = load_registry(path)
        check("before the window is kept", excluded_session(reg, "f44ca14d-4868-4dc7-9e83", "2026-10-07T09:59:59+05:30"), False)
        check("at the window is excluded", excluded_session(reg, "f44ca14d-4868-4dc7-9e83", "2026-10-07T10:00:00+05:30"), True)
        check("after the window is excluded", excluded_session(reg, "f44ca14d-4868-4dc7-9e83", "2026-10-07T12:00:00+05:30"), True)
        check("a sub-agent session id matches by prefix", excluded_session(reg, "f44ca14d-4868-4dc7-9e83.agent-1", "2026-10-07T12:00:00+05:30"), True)
        check("UTC timestamps are compared correctly", excluded_session(reg, "f44ca14d-4868", "2026-10-07T04:31:00+00:00"), True)
        check("unparseable ts inside a since window excludes", excluded_session(reg, "f44ca14d-4868", "garbage"), True)
        check("a prefix without since excludes always", excluded_session(reg, "whole-session-1x", "2020-01-01T00:00:00+05:30"), True)
        check("another session is kept", excluded_session(reg, "someone-else", "2026-10-07T12:00:00+05:30"), False)
        check("a canary in any text excludes", excluded_turn(reg, "x", "", "a", "has c002-canary-0123456789abcdef in it"), True)
        check("no canary, no session keeps", excluded_turn(reg, "x", "", "plain text"), False)
        check("prefixes for the router", session_prefixes(reg), ("f44ca14d-4868", "whole-session-1"))
        path.write_text(json.dumps({"sessions": [{"prefix": "abc"}]}), encoding="utf-8")
        try:
            load_registry(path)
            check("a short prefix is refused", "accepted", "refused")
        except ValueError:
            check("a short prefix is refused", "refused", "refused")
        path.write_text(json.dumps({"canaries": ["short"]}), encoding="utf-8")
        try:
            load_registry(path)
            check("a short canary is refused", "accepted", "refused")
        except ValueError:
            check("a short canary is refused", "refused", "refused")
    print("PASS" if not failures else f"{failures} FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
