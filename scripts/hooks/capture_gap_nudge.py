"""
capture_gap_nudge.py — Claude Code UserPromptSubmit-hook: the parse trigger.

LAYER: Tools (Memory Contract — Claude Code's parse trigger)

Registered as a `UserPromptSubmit` hook in .claude/settings.json. Fires BEFORE
each assistant turn, so the nudge lands while there is still a turn left in
which to act on it. The file keeps its old name because the manifest and every
machine's settings.json register it by that name.

=============================================================================
THE BIG PICTURE: why this exists
=============================================================================

The Memory Contract (NERVOUS_SYSTEM.md §3, owner's decision 2026-09-28): the
agent the owner is chatting with parses those turns, by the one rule in
jarvis_core/agent/parse_rule.py, with no paid background LLM. On this host that
agent is Claude, and willpower is not a mechanism — Antigravity's manual
/memory produced zero records in months, and before this hook the "append to
the KB" nudge here produced KB entries only when Claude happened to agree.

So the trigger is a number, not a reminder: parse_ledger.backlog() counts
Claude Code turns that have no verdict under the current PARSE_RULE_VERSION.
At _NUDGE_THRESHOLD or more, the instruction to parse appears in context,
with the count and the oldest pending turn's age, before the user's request.
Below it, silent — a nudge on every turn would be tuned out.

This replaced the old "CAPTURE GAP: N turns since the last KB append" nudge:
the parse writes the KB facts itself (with verbatim evidence), so a separate
append reminder would ask for the same work twice, by two different rules.

=============================================================================
THE FLOW
=============================================================================

STEP 1: stdin event. Unparseable -> silent exit 0.
        |
STEP 2: parse_ledger.backlog()["claude"] -> pending count + oldest ts.
        UserPromptSubmit fires before this turn's Stop hook, so the queue
        holds prior turns only — the backlog being measured already exists.
        |
STEP 3: pending >= _NUDGE_THRESHOLD -> emit ONE additionalContext block with
        the exact commands. Below threshold -> silent. Always exit 0.

Never raises, never blocks, never writes. A broken nudge must not cost a turn.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# The contract's "about every 10 turns": ten unparsed turns is one full batch.
_NUDGE_THRESHOLD = 10
_BATCH = 10
_IST = timezone(timedelta(hours=5, minutes=30))


def _python() -> str:
    return "python" if sys.platform.startswith("win") else "python3"


def _age(oldest_ts: str, now: Optional[datetime] = None) -> str:
    try:
        then = datetime.fromisoformat(oldest_ts)
    except (TypeError, ValueError):
        return "unknown age"
    if then.tzinfo is None:
        then = then.replace(tzinfo=_IST)
    delta = (now or datetime.now(_IST)) - then
    if delta.days >= 1:
        return f"{delta.days} day(s) old ({oldest_ts})"
    hours = int(delta.total_seconds() // 3600)
    return f"{hours} hour(s) old ({oldest_ts})" if hours else f"under an hour old ({oldest_ts})"


def message(pending: int, oldest_ts: str, now: Optional[datetime] = None) -> str:
    py = _python()
    return (
        f"PARSE BACKLOG (Memory Contract, NERVOUS_SYSTEM.md §3): {pending} Claude Code "
        f"turn(s) have no verdict under the current parse rule; the oldest is "
        f"{_age(oldest_ts, now)}. You are the agent the owner chatted with, so parsing them "
        "is your job, and nothing else will do it. BEFORE continuing with the user's request:\n"
        f"  1. `{py} scripts/parse_turns.py --pending --host claude --limit {_BATCH}` — "
        "a JSON packet with the rule, the whole turns, their whole session context and "
        "the tension priors. If the harness saves the output to a file, Read that file IN "
        "FULL (page with offset/limit). Never judge from a preview.\n"
        "  2. Judge every offered turn by the rule text in the packet — exactly that rule, "
        "no private variant.\n"
        '  3. Write {"verdicts": [...]} (one per offered turn) to a scratchpad file, then '
        f"`{py} scripts/parse_turns.py --submit <file> --agent claude/<your model id>`. "
        "If it rejects a verdict, fix that verdict and resubmit; do not drop turns.\n"
        "Then answer the user. Say in one line that you parsed N turns and what backlog remains."
    )


def _claude_backlog() -> Dict[str, Any]:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "js-development"))
    from jarvis_core.agent.parse_ledger import backlog  # type: ignore
    return backlog().get("claude", {"pending": 0, "oldest": ""})


def main() -> int:
    try:
        raw = sys.stdin.read()
        json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0

    try:
        slot = _claude_backlog()
        pending = int(slot.get("pending") or 0)
        if pending < _NUDGE_THRESHOLD:
            return 0
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": message(pending, str(slot.get("oldest") or "")),
            }
        }))
    except Exception:
        pass  # never disrupt a turn
    return 0


def _run_self_test() -> None:
    print("=" * 70)
    print("  capture_gap_nudge.py (parse trigger) -- Smoke Tests")
    print("=" * 70)
    passed = 0
    failed = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        nonlocal passed
        if cond:
            passed += 1
        else:
            failed.append(f"FAIL: {name}" + (f" ({hint})" if hint else ""))

    now = datetime(2026, 9, 28, 18, 0, tzinfo=_IST)
    msg = message(778, "2026-06-02T10:46:20+05:30", now)
    check("T1 message names the exact pending and submit commands",
          "parse_turns.py --pending --host claude --limit 10" in msg
          and "parse_turns.py --submit" in msg and "--agent claude/" in msg, msg)
    check("T2 message carries the count and the oldest age",
          "778 Claude Code" in msg and "118 day(s) old" in msg, msg)
    check("T3 message says before the user's request, and read in full",
          "BEFORE continuing" in msg and "IN FULL" in msg)
    check("T4 age degrades instead of raising on a bad timestamp",
          _age("not-a-ts", now) == "unknown age" and "hour" in _age("2026-09-28T15:00:00+05:30", now))

    import io
    import contextlib
    global _claude_backlog
    real = _claude_backlog

    def run_with(fake) -> str:
        global _claude_backlog
        _claude_backlog = fake
        buf = io.StringIO()
        old_stdin = sys.stdin
        sys.stdin = io.StringIO('{"prompt": "hi"}')
        try:
            with contextlib.redirect_stdout(buf):
                rc = main()
        finally:
            sys.stdin = old_stdin
            _claude_backlog = real
        return f"{rc}|{buf.getvalue()}"

    below = run_with(lambda: {"pending": _NUDGE_THRESHOLD - 1, "oldest": "2026-09-28T10:00:00+05:30"})
    check("T5 below threshold is silent", below == "0|", below)
    at = run_with(lambda: {"pending": _NUDGE_THRESHOLD, "oldest": "2026-09-28T10:00:00+05:30"})
    check("T6 at threshold emits one UserPromptSubmit additionalContext",
          at.startswith("0|") and '"UserPromptSubmit"' in at and "PARSE BACKLOG" in at, at)

    def boom():
        raise RuntimeError("ledger broken")
    broken = run_with(boom)
    check("T7 a broken ledger is fail-soft: exit 0, no output", broken == "0|", broken)

    try:
        live = real()
        check("T8 live ledger answers with a count", isinstance(live.get("pending"), int), str(live))
    except Exception as exc:  # noqa: BLE001
        check("T8 live ledger answers with a count", False, repr(exc))

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
