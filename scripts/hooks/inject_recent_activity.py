"""
inject_recent_activity.py — Claude Code SessionStart-hook: cross-chat recall.

LAYER: Tools (Personalization — recall)

The THIRD SessionStart hook, alongside inject_profile.py (who you are) and
surface_life_state.py (raise an insight). This one answers "what have I been
doing?" — it injects a day-by-day activity digest built from the local capture
queue (observation_queue.jsonl), spanning ALL chats, so every fresh chat opens
knowing your recent cross-chat work WITHOUT running `git log`.

This closes the recall gap that made a fresh chat fall back to git (and miss a
heavy no-commit day like a full DE-lessons session). Source is your actual
per-prompt capture — local, private — not commits.

Thin + stdlib-only (delegates to jarvis_core.agent.recall, which is stdlib): the
session never blocks. Any error is swallowed; always exit 0.

=============================================================================
THE FLOW
=============================================================================

STEP 1: Read the SessionStart event JSON on stdin (cwd).
        |
STEP 2: Build the recent-activity digest (last 7 days) from the capture queue.
        |
STEP 3: Emit it as additionalContext (background — factual activity log). Exit 0.

=============================================================================
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_DAYS = 7


def _recaller(cwd: str):
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "js-development"))
        from jarvis_core.agent.recall import ActivityRecaller  # type: ignore
        return ActivityRecaller()
    except Exception:
        try:
            sys.path.insert(0, str(Path(cwd) / "js-development"))
            from jarvis_core.agent.recall import ActivityRecaller  # type: ignore
            return ActivityRecaller(queue_path=Path(cwd) / "jarvis_data" / "observation_queue.jsonl")
        except Exception:
            return None


def main() -> int:
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0

    try:
        cwd = event.get("cwd", os.getcwd())
        recaller = _recaller(cwd)
        if recaller is None:
            return 0
        digest = recaller.digest(days=_DAYS)
        if not digest or "no captured turns" in digest:
            return 0
        context = (
            "The following is your recent cross-chat activity, recalled from the local "
            "per-prompt capture (NOT git). Treat it as background so you know what the "
            "user has been working on across their other chats:\n\n" + digest
        )
        out = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": context,
            }
        }
        sys.stdout.write(json.dumps(out, ensure_ascii=False))
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
