"""
notice_runtime_change.py — Claude Code UserPromptSubmit-hook: runtime self-state.

LAYER: Tools (Personalization — Identity pillar)

Fires on EVERY prompt in EVERY chat. Detects when the brain running the session
CHANGED (a `/model` swap mid-session) and injects a one-line self-state notice so
the model knows what it is — instead of greeting a new name like a nickname while
its own substrate was just replaced (the 2026-06-11 "Friday" probe, KB L318).

Why UserPromptSubmit and not SessionStart: SessionStart fires once, at boot. A
mid-session `/model` swap happens between turns — only a per-prompt hook can catch
it in the SAME session. Discipline: emit ONLY on change (fail-closed, no spam),
tail-read the transcript (bounded bytes — a months-old transcript can be tens of
MB and this path must stay sub-second), always exit 0.

Detection, two signals (newest wins):
  1. The `/model` command stdout recorded in a user message AFTER the last
     assistant turn — catches the swap IMMEDIATELY, before the new brain has
     produced anything. MENTION-VS-USE GUARD (2026-06-12): the pattern is matched
     ONLY inside <local-command-stdout> blocks, and the captured id must look like
     a real model id. A conversation that merely QUOTES the pattern in prose (e.g.
     a compaction summary documenting this very hook) must not register — the
     live repro was this hook announcing a swap to literal "X" after the summary
     contained the documentation string for its own regex.
  2. The latest non-synthetic assistant `message.model` — the brain that actually
     produced the last turn (one turn behind on a fresh swap, authoritative after).

State: jarvis_data/.runtime_state.json — {session_id: {"model","ts"}}, flock'd
read-modify-write (same pattern as the surfacing watermark), pruned to the most
recent sessions.

=============================================================================
THE FLOW
=============================================================================

STEP 1: stdin event (session_id, transcript_path). Missing either -> exit 0.
        |
STEP 2: tail-read the transcript (last ~256KB); derive current model from the two
        signals above; normalize (strip a trailing "[...]" variant marker).
        |
STEP 3: compare vs this session's last-seen model in the state file (flock).
        First sighting -> record baseline, emit nothing.
        |
STEP 4: changed -> update state + emit ONE additionalContext line naming
        old -> new. Unchanged -> silent. Always exit 0.

=============================================================================
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import fcntl
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False

_IST = timezone(timedelta(hours=5, minutes=30))
_TAIL_BYTES = 262144          # 256KB tail — bounded regardless of transcript size
_MAX_SESSIONS_KEPT = 40

_SET_MODEL_RX = re.compile(r"Set model to\s+([A-Za-z0-9._\-\[\]]+)", re.IGNORECASE)
_CMD_STDOUT_RX = re.compile(r"<local-command-stdout>(.*?)</local-command-stdout>", re.DOTALL)
# Real model ids are lowercase slugs with at least one hyphen ("claude-fable-5",
# "gpt-4"); rejects prose placeholders like "X" or "Friday".
_PLAUSIBLE_MODEL_RX = re.compile(r"^[a-z0-9][a-z0-9._/]*(?:-[a-z0-9._/]+)+$")


def _state_path(cwd: str) -> Path:
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "js-development"))
        from jarvis_core.config import DATA_ROOT  # type: ignore
        return Path(DATA_ROOT) / ".runtime_state.json"
    except Exception:
        return Path(cwd) / "jarvis_data" / ".runtime_state.json"


def _normalize(model: str) -> str:
    """Strip a trailing context-variant marker like '[1m]' — same brain, same identity."""
    return re.sub(r"\[[^\]]*\]$", "", (model or "").strip())


def _block_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _tail_lines(path: Path, tail_bytes: int = _TAIL_BYTES) -> List[str]:
    """Last complete JSONL lines of a (possibly huge) transcript, bounded read."""
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            offset = max(0, size - tail_bytes)
            f.seek(offset)
            data = f.read().decode("utf-8", errors="replace")
        lines = data.splitlines()
        if offset > 0 and lines:
            lines = lines[1:]  # drop the partial first line
        return lines
    except OSError:
        return []


def detect_current_model(transcript_path: Path) -> str:
    """Current brain: a 'Set model to X' seen AFTER the last assistant turn wins
    (immediate swap signal); else the last non-synthetic assistant model."""
    last_assistant = ""
    set_model_after = ""
    for line in _tail_lines(transcript_path):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        rtype = rec.get("type")
        if rtype == "assistant" and not rec.get("isSidechain"):
            m = (rec.get("message") or {}).get("model") or ""
            if m and m != "<synthetic>":
                last_assistant = m
                set_model_after = ""  # only /model AFTER the last assistant counts
        elif rtype == "user" and not rec.get("isSidechain"):
            txt = _block_text((rec.get("message") or {}).get("content"))
            for stdout_block in _CMD_STDOUT_RX.finditer(txt):
                for m in _SET_MODEL_RX.finditer(stdout_block.group(1)):
                    candidate = _normalize(m.group(1))
                    if _PLAUSIBLE_MODEL_RX.match(candidate):
                        set_model_after = candidate
    return _normalize(set_model_after or last_assistant)


def check_and_update(
    state_path: Path, session_id: str, current_model: str, ts: Optional[str] = None
) -> Optional[Tuple[str, str]]:
    """Record `current_model` for the session; return (old, new) iff it CHANGED."""
    if not current_model or not session_id:
        return None
    ts = ts or datetime.now(_IST).isoformat(timespec="seconds")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with open(state_path, "a+", encoding="utf-8") as f:
        if _HAS_FCNTL:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.seek(0)
            raw = f.read().strip()
            try:
                data = json.loads(raw) if raw else {}
                if not isinstance(data, dict):
                    data = {}
            except json.JSONDecodeError:
                data = {}
            prev = (data.get(session_id) or {}).get("model", "")
            data[session_id] = {"model": current_model, "ts": ts}
            if len(data) > _MAX_SESSIONS_KEPT:  # prune oldest sessions
                for sid, _ in sorted(data.items(), key=lambda kv: kv[1].get("ts", ""))[
                        :len(data) - _MAX_SESSIONS_KEPT]:
                    data.pop(sid, None)
            f.seek(0)
            f.truncate()
            f.write(json.dumps(data, ensure_ascii=False))
            f.flush()
        finally:
            if _HAS_FCNTL:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    if prev and prev != current_model:
        return (prev, current_model)
    return None


def main() -> int:
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0
    try:
        session_id = event.get("session_id", "")
        transcript_path = event.get("transcript_path", "")
        cwd = event.get("cwd", os.getcwd())
        if not transcript_path or not session_id:
            return 0
        current = detect_current_model(Path(transcript_path))
        if not current:
            return 0
        change = check_and_update(_state_path(cwd), session_id, current)
        if change is None:
            return 0
        old, new = change
        ts = datetime.now(_IST).strftime("%H:%M IST")
        context = (
            f"RUNTIME SELF-STATE: your underlying model changed {old} -> {new} "
            f"(detected {ts}). You are now running on {new}. This is live self-state "
            f"from the session transcript — acknowledge naturally if relevant; do not "
            f"treat your boot-time model label as current."
        )
        out = {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": context,
            }
        }
        sys.stdout.write(json.dumps(out, ensure_ascii=False))
    except Exception:
        return 0
    return 0


# =============================================================================
# SMOKE TESTS (dev-only: --self-test; the hook itself is invoked with no args)
# =============================================================================

def _run_self_test() -> None:
    import tempfile

    print("=" * 70)
    print("  notice_runtime_change.py -- Smoke Tests")
    print("=" * 70)
    passed = 0
    failed: List[str] = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        nonlocal passed
        if cond:
            passed += 1
        else:
            failed.append(f"FAIL: {name}" + (f" ({hint})" if hint else ""))

    def w(path: Path, recs: List[Dict[str, Any]]) -> None:
        path.write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")

    A = lambda m, txt="x": {"type": "assistant", "message": {"model": m, "content": [{"type": "text", "text": txt}]}}
    U = lambda txt: {"type": "user", "message": {"content": [{"type": "text", "text": txt}]}}

    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)

        # T1: detect last non-synthetic assistant model
        t1 = tdp / "t1.jsonl"
        w(t1, [A("claude-opus-4-8"), A("<synthetic>"), U("hi")])
        check("T1 last real assistant model", detect_current_model(t1) == "claude-opus-4-8")

        # T2: 'Set model to' in command stdout AFTER last assistant wins (immediate swap signal)
        t2 = tdp / "t2.jsonl"
        w(t2, [A("claude-opus-4-8"),
               U("<local-command-stdout>Set model to claude-fable-5[1m]</local-command-stdout>")])
        check("T2 /model stdout wins + variant marker normalized",
              detect_current_model(t2) == "claude-fable-5", detect_current_model(t2))

        # T3: 'Set model to' BEFORE a newer assistant turn does NOT override it
        t3 = tdp / "t3.jsonl"
        w(t3, [U("<local-command-stdout>Set model to claude-fable-5</local-command-stdout>"),
               A("claude-fable-5"), A("claude-fable-5", "more")])
        check("T3 assistant model after the swap is authoritative",
              detect_current_model(t3) == "claude-fable-5")

        # T12: MENTION-VS-USE — prose quoting the pattern (no stdout block) must NOT register
        t12 = tdp / "t12.jsonl"
        w(t12, [A("claude-fable-5"),
                U('summary says: current model = "Set model to X" after last assistant')])
        check("T12 prose mention of the pattern ignored",
              detect_current_model(t12) == "claude-fable-5", detect_current_model(t12))

        # T13: stdout-wrapped but implausible id (placeholder) ignored -> assistant fallback
        t13 = tdp / "t13.jsonl"
        w(t13, [A("claude-fable-5"),
                U("<local-command-stdout>Set model to X</local-command-stdout>")])
        check("T13 implausible model id rejected",
              detect_current_model(t13) == "claude-fable-5", detect_current_model(t13))

        # T4-T7: state machine — baseline silent, change fires ONCE, then silent
        sp = tdp / ".state.json"
        check("T4 first sighting -> baseline, no change",
              check_and_update(sp, "sess1", "claude-opus-4-8", ts="2026-06-11T10:00:00") is None)
        chg = check_and_update(sp, "sess1", "claude-fable-5", ts="2026-06-11T10:05:00")
        check("T5 swap detected once", chg == ("claude-opus-4-8", "claude-fable-5"), str(chg))
        check("T6 repeat same model -> silent",
              check_and_update(sp, "sess1", "claude-fable-5", ts="2026-06-11T10:06:00") is None)
        check("T7 separate session tracked independently",
              check_and_update(sp, "sess2", "claude-haiku-4-5", ts="2026-06-11T10:07:00") is None)

        # T8: corrupt state file tolerated (treated as empty -> baseline)
        sp2 = tdp / ".corrupt.json"
        sp2.write_text("}{nope", encoding="utf-8")
        check("T8 corrupt state tolerated",
              check_and_update(sp2, "s", "m1") is None
              and isinstance(json.loads(sp2.read_text()), dict))

        # T9: missing transcript -> empty model, no crash
        check("T9 missing transcript -> ''", detect_current_model(tdp / "nope.jsonl") == "")

        # T10: tail-read of a big file still finds the model (bounded read)
        big = tdp / "big.jsonl"
        filler = [U("padding line " + "z" * 400) for _ in range(2000)]
        w(big, filler + [A("claude-fable-5", "tail answer")])
        check("T10 big transcript tail-read works", detect_current_model(big) == "claude-fable-5")

        # T11: end-to-end main() emits valid JSON on a seeded change
        sp3 = tdp / ".e2e.json"
        sp3.write_text(json.dumps({"sessX": {"model": "claude-opus-4-8", "ts": "t"}}), encoding="utf-8")
        t11 = tdp / "t11.jsonl"
        w(t11, [A("claude-fable-5")])
        import io
        from unittest import mock
        event = {"session_id": "sessX", "transcript_path": str(t11), "cwd": td}
        with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(event))), \
             mock.patch("__main__._state_path", return_value=sp3), \
             mock.patch.object(sys, "stdout", io.StringIO()) as out:
            rc = main()
            emitted = out.getvalue()
        check("T11 e2e: exit 0 + change notice emitted",
              rc == 0 and "claude-opus-4-8 -> claude-fable-5" in emitted
              and json.loads(emitted)["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit",
              emitted[:160])

    total = passed + len(failed)
    print(f"\n  Passed: {passed}/{total}")
    if failed:
        for f_ in failed:
            print(f"  {f_}")
        print("=" * 70)
        raise SystemExit(1)
    print(f"  All {total} notice_runtime_change smoke tests passed.")
    print("=" * 70)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        _run_self_test()
    else:
        raise SystemExit(main())
