"""
parse_ledger.py — which captured turns still need parsing, and whose job each one is.

LAYER: Memory (curation + knowledge)

Run with:
    python -m jarvis_core.agent.parse_ledger            # self-test
    python -m jarvis_core.agent.parse_ledger --status   # backlog per host

=============================================================================
THE BIG PICTURE
=============================================================================

The owner's rule (2026-09-28): the agent the owner was talking to parses
those turns. That only works if every turn is attributable to exactly one
host, and if "not parsed yet" is a number anyone can see. A backlog that only
lives in an agent's good intentions is how 1,833 turns went uncurated for
13 days without anyone noticing.

A turn is PARSED when turn_curation.jsonl holds a verdict for it made under
the current PARSE_RULE_VERSION. Verdicts from before the rule existed (the
Gemini curator's) still route training, since the log is folded newest-wins,
but they carry no knowledge extraction, so the turn is offered again.

Which host a turn belongs to:
  1. its `host` field, written by every capture path from 2026-09-28;
  2. for older rows: JARVIS's own sessions (conv-*/terminal-*, or labelled
     terminal-ask/voice-ask); Claude models; a session id that matches a
     Codex rollout file or an Antigravity brain folder on this machine; the
     work laptop's /home/ cwd (only Claude Code runs there);
  3. otherwise "unknown", which is reported, never silently assigned.

=============================================================================
THE FLOW
=============================================================================

STEP 1: fold turn_curation.jsonl into {key: newest verdict}.
        |
STEP 2: stream observation_queue.jsonl; a turn is pending when its newest
        verdict is missing or older than PARSE_RULE_VERSION. Test sessions
        (ephemeral voicegate runs) are never pending.
        |
STEP 3: attribute each pending turn to a host; count, and report the oldest.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, FrozenSet, Iterator, List, Optional, Tuple

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from jarvis_core.agent.parse_rule import PARSE_RULE_VERSION  # noqa: E402
from jarvis_core.config import DATA_ROOT  # noqa: E402

HOSTS: Tuple[str, ...] = ("claude", "codex", "antigravity", "jarvis")
QUEUE_PATH = Path(DATA_ROOT) / "observation_queue.jsonl"
CURATION_PATH = Path(DATA_ROOT) / "turn_curation.jsonl"
_TEST_SESSION = re.compile(r"^conv-web-voicegate-")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-([0-9a-f])[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}$")


@dataclass(frozen=True)
class PendingTurn:
    ts: str
    session_id: str
    host: str
    row: Dict[str, Any]

    @property
    def key(self) -> Tuple[str, str]:
        return (self.ts, self.session_id)


@lru_cache(maxsize=1)
def _codex_ids() -> FrozenSet[str]:
    root = Path.home() / ".codex"       # sessions/ and archived_sessions/
    if not root.exists():
        return frozenset()
    ids = set()
    for p in root.rglob("rollout-*.jsonl"):
        m = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$", p.stem)
        if m:
            ids.add(m.group(1))
    return frozenset(ids)


@lru_cache(maxsize=1)
def _antigravity_ids() -> FrozenSet[str]:
    root = Path.home() / ".gemini" / "antigravity-ide" / "brain"
    if not root.exists():
        return frozenset()
    return frozenset(p.name for p in root.iterdir() if p.is_dir())


def host_of(row: Dict[str, Any]) -> str:
    explicit = str(row.get("host") or "").strip().lower()
    if explicit in HOSTS:
        return explicit
    sid = str(row.get("session_id") or "")
    label = str(row.get("chat_label") or "")
    if sid.startswith(("conv-", "terminal-")) or label in ("terminal-ask", "voice-ask"):
        return "jarvis"
    if str(row.get("model") or "").lower().startswith("claude"):
        return "claude"
    if sid in _codex_ids():
        return "codex"
    if sid in _antigravity_ids():
        return "antigravity"
    cwd = str(row.get("cwd") or "")
    if cwd.startswith("/home/"):
        return "claude"
    # Past the file lookups (a host may prune its own history): Codex mints
    # version-7 UUIDs; Antigravity mints version-4 and records no model, while
    # every Claude capture on this machine carries its model.
    version = _UUID.match(sid)
    if version and not row.get("model"):
        return "codex" if version.group(1) == "7" else "antigravity" if version.group(1) == "4" else "unknown"
    return "unknown"


def _folded(curation_path: Path) -> Dict[Tuple[str, str], Dict[str, Any]]:
    folded: Dict[Tuple[str, str], Dict[str, Any]] = {}
    if not curation_path.exists():
        return folded
    for line in curation_path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        folded[(str(rec.get("ts")), str(rec.get("session_id")))] = rec
    return folded


def is_parsed(rec: Optional[Dict[str, Any]]) -> bool:
    return bool(rec) and int(rec.get("rule_version") or 0) >= PARSE_RULE_VERSION


def pending(host: Optional[str] = None, queue_path: Path = QUEUE_PATH,
            curation_path: Path = CURATION_PATH) -> Iterator[PendingTurn]:
    """Pending turns in queue order, optionally for one host."""
    folded = _folded(curation_path)
    if not queue_path.exists():
        return
    with queue_path.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            ts, sid = str(row.get("ts") or ""), str(row.get("session_id") or "")
            if not ts or not sid or _TEST_SESSION.match(sid) or not str(row.get("user_text") or "").strip():
                continue
            if is_parsed(folded.get((ts, sid))):
                continue
            h = host_of(row)
            if host is None or h == host:
                yield PendingTurn(ts, sid, h, row)


def backlog(queue_path: Path = QUEUE_PATH, curation_path: Path = CURATION_PATH) -> Dict[str, Dict[str, Any]]:
    """{host: {"pending": n, "oldest": ts}} for every host with pending turns, plus all HOSTS."""
    out: Dict[str, Dict[str, Any]] = {h: {"pending": 0, "oldest": ""} for h in HOSTS}
    for turn in pending(None, queue_path, curation_path):
        slot = out.setdefault(turn.host, {"pending": 0, "oldest": ""})
        slot["pending"] += 1
        if not slot["oldest"] or turn.ts < slot["oldest"]:
            slot["oldest"] = turn.ts
    return out


def _self_test() -> int:
    import tempfile
    failed: List[str] = []

    def check(name: str, ok: bool, hint: str = "") -> None:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  {hint}"))
        if not ok:
            failed.append(name)

    rows = [
        {"ts": "1", "session_id": "conv-web-a", "user_text": "hi jarvis", "chat_label": "voice-ask"},
        {"ts": "2", "session_id": "u-1", "user_text": "fix the hook", "model": "claude-opus-5-5"},
        {"ts": "3", "session_id": "u-2", "user_text": "explicit", "host": "codex"},
        {"ts": "4", "session_id": "conv-web-voicegate-x", "user_text": "Hi, JARVIS.", "chat_label": "voice-ask"},
        {"ts": "5", "session_id": "u-3", "user_text": "old gemini verdict", "model": "claude-x"},
        {"ts": "6", "session_id": "u-4", "user_text": "parsed under v1", "model": "claude-x"},
        {"ts": "7", "session_id": "u-5", "user_text": "mystery"},
        {"ts": "8", "session_id": "01a0dcdc-8467-7c20-92bf-e2a66b8e8c27", "user_text": "pruned codex"},
        {"ts": "9", "session_id": "3dea28d3-1510-4d9c-9d1b-094f47b95e2e", "user_text": "pruned antigravity"},
    ]
    with tempfile.TemporaryDirectory() as td:
        q, c = Path(td) / "q.jsonl", Path(td) / "c.jsonl"
        q.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        c.write_text("\n".join(json.dumps(r) for r in [
            {"ts": "5", "session_id": "u-3", "corpora": ["none"]},
            {"ts": "6", "session_id": "u-4", "corpora": ["none"], "rule_version": PARSE_RULE_VERSION},
        ]) + "\n", encoding="utf-8")
        got = {(t.ts, t.host) for t in pending(None, q, c)}
        check("T1 hosts are attributed: jarvis / claude / explicit codex",
              {("1", "jarvis"), ("2", "claude"), ("3", "codex")} <= got, str(got))
        check("T2 ephemeral voicegate test turns are never pending", all(ts != "4" for ts, _ in got))
        check("T3 a pre-rule verdict is re-offered; a current-rule verdict is not",
              ("5", "claude") in got and all(ts != "6" for ts, _ in got), str(got))
        check("T4 an unattributable turn is reported as unknown, not assigned", ("7", "unknown") in got)
        check("T4b pruned hosts attributed by UUID version (v7 codex, v4 antigravity)",
              ("8", "codex") in got and ("9", "antigravity") in got, str(got))
        b = backlog(q, c)
        check("T5 backlog counts per host with the oldest pending ts",
              b["claude"]["pending"] == 2 and b["claude"]["oldest"] == "2" and b["jarvis"]["pending"] == 1, str(b))
    print(f"  {6 - len(failed)}/6 passed")
    return 1 if failed else 0


if __name__ == "__main__":
    if "--status" in sys.argv:
        print(json.dumps(backlog(), indent=2))
        sys.exit(0)
    sys.exit(_self_test())
