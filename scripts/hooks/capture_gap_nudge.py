"""
capture_gap_nudge.py — Claude Code UserPromptSubmit-hook: the missing trigger.

LAYER: Tools (Personalization capture — self-correction trigger)

Registered as a `UserPromptSubmit` hook in .claude/settings.json. Fires BEFORE
each assistant turn, so the nudge lands while there is still a turn left in
which to act on it.

=============================================================================
THE BIG PICTURE: why this exists
=============================================================================

KB entry 474 (2026-08-19) diagnosed the root cause of a ~97% collapse in
personality capture: "finishing a build is a trigger; noticing a personality
signal has NO trigger." That diagnosis was logged — and then the very next
few turns repeated the failure (2026-08-20: 3 of 9 turns captured, missing
turns that carried planning-horizon, constraint-model and hypothesis-first
signal). Diagnosis without a countermeasure is how a failure repeats.

Willpower is not a mechanism. This hook is the mechanism: it converts
"did I remember to capture?" from something invisible into a number that
appears in context every turn once it crosses a threshold.

Deliberately NOT a per-turn reminder. A nudge on every single turn would be
noise, would be tuned out within a session, and would fire on genuinely empty
procedural turns ("run it", "continue") where the standing directive itself
says there is nothing to capture. It only speaks when a real gap has opened.

=============================================================================
THE FLOW
=============================================================================

STEP 1: stdin event. Unparseable -> silent exit 0.
        |
STEP 2: read the newest timestamp in knowledge_base.jsonl (last capture).
        |
STEP 3: count observation_queue turns NEWER than that timestamp — i.e. real
        turns that have happened since anything was last written down.
        Ordering note: UserPromptSubmit fires before this turn's Stop hook,
        so the queue holds prior turns only. That is correct — the gap being
        measured is what has already gone uncaptured.
        |
STEP 4: gap >= _NUDGE_THRESHOLD -> emit ONE additionalContext line.
        Below threshold -> silent. Always exit 0.

Never raises, never blocks, never writes. A broken nudge must not cost a turn.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# 2 is deliberate: 1 would fire constantly (a build turn legitimately produces a
# Decision entry, not a Cognitive_Pattern, and the next turn is often still that
# same work). 3+ lets a real gap open before anyone notices. 2 catches drift
# while it is still one turn old.
_NUDGE_THRESHOLD = 2

# Above this, the message escalates — a long silent run means the standing
# every-prompt directive has stopped operating, not that one turn was skipped.
_ESCALATE_AT = 5


def _latest_kb_timestamp(kb_path: Path) -> str:
    """Newest timestamp in the KB. Scans all lines — appends are not sorted."""
    newest = ""
    try:
        with kb_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ts = json.loads(line).get("timestamp", "")
                except json.JSONDecodeError:
                    continue
                if ts > newest:
                    newest = ts
    except OSError:
        return ""
    return newest


def _turns_since(queue_path: Path, since_ts: str) -> int:
    if not since_ts:
        return 0
    n = 0
    try:
        with queue_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ts = json.loads(line).get("ts", "")
                except json.JSONDecodeError:
                    continue
                if ts > since_ts:
                    n += 1
    except OSError:
        return 0
    return n


def _message(gap: int) -> str:
    if gap >= _ESCALATE_AT:
        return (
            f"CAPTURE GAP: {gap} turns since the last knowledge_base.jsonj append. "
            "The standing every-prompt capture directive (KB 473) has stopped "
            "operating, not merely slipped once. Before continuing the current task, "
            "review those turns for user signal — especially behaviour deltas, "
            "corrections, and short evaluative turns (brevity is NOT a capture "
            "filter, per KB 485) — and append what is real."
        )
    return (
        f"CAPTURE GAP: {gap} turns since the last knowledge_base.jsonl append. "
        "Check whether those turns carried signal about the user (mind, character, "
        "behaviour change, corrections, stated purpose). If yes, append now rather "
        "than at session end. If genuinely procedural, continue — that is the "
        "directive's stated exception."
    )


def main() -> int:
    try:
        raw = sys.stdin.read()
        json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0

    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "js-development"))
        from jarvis_core.config import DATA_ROOT, KB_PATH  # type: ignore

        queue = Path(DATA_ROOT) / "observation_queue.jsonl"
        gap = _turns_since(queue, _latest_kb_timestamp(Path(KB_PATH)))
        if gap < _NUDGE_THRESHOLD:
            return 0
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": _message(gap),
            }
        }))
    except Exception:
        pass  # never disrupt a turn
    return 0


def _run_self_test() -> None:
    import tempfile

    print("=" * 70)
    print("  capture_gap_nudge.py -- Smoke Tests")
    print("=" * 70)
    passed = 0
    failed = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        nonlocal passed
        if cond:
            passed += 1
        else:
            failed.append(f"FAIL: {name}" + (f" ({hint})" if hint else ""))

    with tempfile.TemporaryDirectory() as td:
        kb = Path(td) / "kb.jsonl"
        q = Path(td) / "q.jsonl"

        kb.write_text("\n".join(json.dumps(r) for r in [
            {"timestamp": "2026-08-20T10:00:00+05:30", "type": "Decision", "content": "a"},
            {"timestamp": "2026-08-20T09:00:00+05:30", "type": "Idea", "content": "b"},
        ]) + "\n", encoding="utf-8")
        check("T1 newest timestamp wins over file order",
              _latest_kb_timestamp(kb) == "2026-08-20T10:00:00+05:30")

        q.write_text("\n".join(json.dumps(r) for r in [
            {"ts": "2026-08-20T09:30:00+05:30"},   # before last KB append
            {"ts": "2026-08-20T10:30:00+05:30"},   # after
            {"ts": "2026-08-20T11:00:00+05:30"},   # after
        ]) + "\n", encoding="utf-8")
        check("T2 counts only turns newer than last append",
              _turns_since(q, "2026-08-20T10:00:00+05:30") == 2)

        check("T3 no KB timestamp -> no false alarm", _turns_since(q, "") == 0)
        check("T4 missing files are silent",
              _latest_kb_timestamp(Path(td) / "nope.jsonl") == ""
              and _turns_since(Path(td) / "nope.jsonl", "2026-01-01") == 0)
        check("T5 escalates past the long-run threshold",
              "stopped operating" in _message(_ESCALATE_AT)
              and "stopped operating" not in _message(_NUDGE_THRESHOLD))

    total = passed + len(failed)
    print(f"\n  Passed: {passed}/{total}")
    if failed:
        for f_ in failed:
            print(f"  {f_}")
        raise SystemExit(1)
    print(f"  All {total} nudge smoke tests passed.")
    print("=" * 70)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        _run_self_test()
    else:
        raise SystemExit(main())
