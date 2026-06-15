"""
conversation.py — Conversation memory (Stage 4.1: working memory across --ask).

LAYER: Brain (model-facing strategy — short-term/working memory)

Import with:
    from jarvis_core.brain.conversation import ConversationStore, resolve_terminal_session

=============================================================================
THE BIG PICTURE
=============================================================================

JARVIS remembers last WEEK (the KB / recall digest) but, until now, not the last
SENTENCE. Each terminal `--ask` is a fresh process: the Mind starts with
[system, user(question)] and zero prior turns. Live repro (KB L376): JARVIS asked
"want more detail?"; the user's next `--ask` said "yeah"; JARVIS greeted them
fresh — it had forgotten it asked. That's a missing WORKING memory, distinct from
the long-term episodic/semantic KB (which works).

Two clean pieces, deliberately split (so a future host — a daemon, a web UI —
reuses the persistence without inheriting terminal quirks):

  - ConversationStore — DUMB, host-agnostic transcript persistence keyed on a
    session_id. It knows nothing about terminals or time windows. append_turn /
    load_recent, both bounded.
  - resolve_terminal_session — the TERMINAL host's policy: which session am I in?
    Auto-continue the most recent one within an inactivity window (effortless, the
    standing zero-user-effort value), else mint a fresh, pid-qualified id. A future
    host brings its own session-id source and reuses ConversationStore unchanged.

Raw transcripts are machine-local (gitignored), like the observation queue — only
distilled KB entries migrate.

=============================================================================
THE FLOW (per --ask)
=============================================================================

STEP 1: resolve_terminal_session() -> session_id (reuse recent, or mint).
        |
STEP 2: ConversationStore.load_recent(session_id) -> the last few turns.
        |
STEP 3: orchestrator passes them as `history` to Mind.solve (real prior turns).
        |
STEP 4: after a NON-degenerate answer, append_turn(user) + append_turn(assistant).

=============================================================================
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # standalone-run safety

from jarvis_core.config import DATA_ROOT

_IST = timezone(timedelta(hours=5, minutes=30))
_CONV_DIR = Path(DATA_ROOT) / "conversations"
_SESSION_STATE = Path(DATA_ROOT) / ".terminal_session.json"

_DEFAULT_MAX_TURNS = 6          # ~3 exchanges of context — plenty for continuity
_DEFAULT_READ_CHARS = 4000      # read-time budget across all loaded turns
_STORE_ASSISTANT_CHARS = 2000   # store-time head cap (a --full answer can't bloat the file)
_DEFAULT_WINDOW_HOURS = 2.0
_VALID_ROLES = frozenset({"user", "assistant"})


# =============================================================================
# Part 1: THE STORE (host-agnostic persistence, keyed on session_id)
# =============================================================================

class ConversationStore:
    """Append/replay a per-session transcript. Knows nothing about hosts or time."""

    def __init__(self, conv_dir: Optional[Path] = None) -> None:
        # Read the module global at call time (not def time) so tests can redirect
        # the whole store with one assignment, same idiom resolve_terminal_session uses.
        self._dir = Path(conv_dir) if conv_dir is not None else _CONV_DIR

    def _path(self, session_id: str) -> Path:
        safe = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in session_id)
        return self._dir / f"{safe}.jsonl"

    def append_turn(self, session_id: str, role: str, content: str) -> None:
        """Persist one turn. Assistant content is head-capped at store time; a
        problem here must never crash the session that produced it."""
        if role not in _VALID_ROLES or not (content or "").strip():
            return
        text = content if role != "assistant" else content[:_STORE_ASSISTANT_CHARS]
        rec = {"ts": datetime.now(_IST).isoformat(timespec="seconds"),
               "role": role, "content": text}
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            with self._path(session_id).open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def load_recent(
        self, session_id: str,
        max_turns: int = _DEFAULT_MAX_TURNS, max_chars: int = _DEFAULT_READ_CHARS,
    ) -> List[Dict[str, str]]:
        """The last `max_turns` turns (newest-bounded by `max_chars`), in chronological
        order, as [{role, content}] ready to prepend to the Mind's messages."""
        path = self._path(session_id)
        if not path.exists():
            return []
        turns: List[Dict[str, str]] = []
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    role, content = rec.get("role"), rec.get("content", "")
                    if role in _VALID_ROLES and content:
                        turns.append({"role": role, "content": content})
        except OSError:
            return []
        # take the last max_turns, then trim oldest until under the char budget
        recent = turns[-max_turns:]
        while recent and sum(len(t["content"]) for t in recent) > max_chars:
            recent.pop(0)
        return recent

    def turn_count(self, session_id: str) -> int:
        return len(self.load_recent(session_id, max_turns=10_000, max_chars=10_000_000))


# =============================================================================
# Part 2: TERMINAL SESSION RESOLVER (host policy — NOT part of the store)
# =============================================================================

@dataclass(frozen=True)
class SessionResolution:
    session_id: str
    continued: bool        # True = reused a recent session; False = fresh


def resolve_terminal_session(
    now: Optional[datetime] = None,
    window_hours: float = _DEFAULT_WINDOW_HOURS,
    new: bool = False,
    explicit: Optional[str] = None,
    state_path: Optional[Path] = None,
) -> SessionResolution:
    """Which terminal conversation are we in? Auto-continue the most recent within
    `window_hours` of inactivity (effortless), else mint a fresh pid-qualified id.
    `new` forces fresh; `explicit` names a thread. Single-writer assumption (one
    interactive terminal at a time) — no lock; pid-qualified ids keep accidental
    concurrent mints from colliding."""
    now = now or datetime.now(_IST)
    state_path = state_path or _SESSION_STATE

    if explicit:
        _write_state(state_path, explicit, now)
        return SessionResolution(explicit, continued=not new)

    if not new:
        prev = _read_state(state_path)
        if prev:
            sid, last = prev
            if last is not None and (now - last) <= timedelta(hours=window_hours):
                _write_state(state_path, sid, now)
                return SessionResolution(sid, continued=True)

    sid = f"conv-{now.strftime('%Y%m%dT%H%M%S')}-{os.getpid()}"
    _write_state(state_path, sid, now)
    return SessionResolution(sid, continued=False)


def _read_state(path: Path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        sid = data.get("session_id")
        ts = data.get("last_active_ts")
        if not sid:
            return None
        try:
            last = datetime.fromisoformat(ts) if ts else None
        except (ValueError, TypeError):
            last = None
        return sid, last
    except (OSError, json.JSONDecodeError):
        return None


def _write_state(path: Path, session_id: str, now: datetime) -> None:
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(
            json.dumps({"session_id": session_id,
                        "last_active_ts": now.isoformat(timespec="seconds")}),
            encoding="utf-8")
    except OSError:
        pass


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS (offline — temp dirs, injected clock)
# =============================================================================

def _run_self_test() -> None:
    import tempfile

    print("=" * 70)
    print("  conversation.py -- Smoke Tests")
    print("=" * 70)
    passed = 0
    failed: List[str] = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        nonlocal passed
        if cond:
            passed += 1
        else:
            failed.append(f"FAIL: {name}" + (f" ({hint})" if hint else ""))

    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        store = ConversationStore(conv_dir=tdp / "conversations")
        sid = "conv-test-1"

        # T1: append + load round-trip, chronological
        store.append_turn(sid, "user", "your responses are short, why?")
        store.append_turn(sid, "assistant", "Concise by default. Want more detail?")
        store.append_turn(sid, "user", "yeah")
        recent = store.load_recent(sid)
        check("T1 round-trip chronological",
              [t["role"] for t in recent] == ["user", "assistant", "user"]
              and recent[0]["content"].startswith("your responses")
              and recent[-1]["content"] == "yeah", str(recent))

        # T2: roles validated, empty/blank skipped
        store.append_turn(sid, "system", "should be ignored")
        store.append_turn(sid, "user", "   ")
        check("T2 invalid role + blank skipped", store.turn_count(sid) == 3)

        # T3: store-time assistant head cap
        store.append_turn(sid, "assistant", "X" * 5000)
        last = store.load_recent(sid, max_turns=1)[0]
        check("T3 assistant store-cap ~2000", len(last["content"]) == _STORE_ASSISTANT_CHARS)

        # T4: max_turns window
        check("T4 max_turns", len(store.load_recent(sid, max_turns=2)) == 2)

        # T5: max_chars trims oldest
        s5 = "conv-test-5"
        store.append_turn(s5, "user", "a" * 1500)
        store.append_turn(s5, "assistant", "b" * 1500)
        store.append_turn(s5, "user", "c" * 1500)
        r5 = store.load_recent(s5, max_turns=6, max_chars=4000)
        check("T5 char budget trims oldest",
              sum(len(t["content"]) for t in r5) <= 4000 and len(r5) == 2, str([len(t['content']) for t in r5]))

        # T6: missing session -> empty
        check("T6 missing session -> []", store.load_recent("nope") == [])

        # T7: path sanitization (a slashed id can't escape the dir)
        store.append_turn("evil/../../x", "user", "hi")
        check("T7 path sanitized", (tdp / "conversations").exists()
              and not (tdp / "x.jsonl").exists())

        # --- resolver ---
        state = tdp / ".terminal_session.json"
        FIXED = datetime(2026, 6, 15, 12, 0, tzinfo=_IST)

        # T8: first call mints a fresh pid-qualified id
        r8 = resolve_terminal_session(now=FIXED, state_path=state)
        check("T8 first call mints fresh, pid-qualified",
              r8.continued is False and r8.session_id.startswith("conv-")
              and r8.session_id.endswith(f"-{os.getpid()}"), r8.session_id)

        # T9: within window -> continue same id
        r9 = resolve_terminal_session(now=FIXED + timedelta(minutes=30), state_path=state)
        check("T9 within window continues", r9.continued is True and r9.session_id == r8.session_id)

        # T10: past window -> new id
        r10 = resolve_terminal_session(now=FIXED + timedelta(hours=5), state_path=state)
        check("T10 past window mints new", r10.continued is False and r10.session_id != r8.session_id)

        # T11: new=True forces fresh even within window
        r11a = resolve_terminal_session(now=FIXED, state_path=state)
        r11b = resolve_terminal_session(now=FIXED + timedelta(minutes=1), new=True, state_path=state)
        check("T11 new=True forces fresh", r11b.continued is False and r11b.session_id != r11a.session_id)

        # T12: explicit name overrides
        r12 = resolve_terminal_session(now=FIXED, explicit="my-thread", state_path=state)
        check("T12 explicit name honored", r12.session_id == "my-thread")
        check("T12b explicit persists for the next call",
              resolve_terminal_session(now=FIXED + timedelta(minutes=1), state_path=state).session_id == "my-thread")

        # T13: corrupt state file tolerated -> mint fresh
        state.write_text("}{ nope", encoding="utf-8")
        r13 = resolve_terminal_session(now=FIXED, state_path=state)
        check("T13 corrupt state tolerated", r13.session_id.startswith("conv-"))

    total = passed + len(failed)
    print(f"\n  Passed: {passed}/{total}")
    if failed:
        for f_ in failed:
            print(f"  {f_}")
        print("=" * 70)
        raise SystemExit(1)
    print(f"  All {total} conversation smoke tests passed.")
    print("=" * 70)


if __name__ == "__main__":
    _run_self_test()
