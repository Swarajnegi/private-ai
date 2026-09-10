"""
run_consolidation.py — Claude Code Stop-hook: feed the surfacing organ.

LAYER: Tools (Personalization — the loop that keeps the RAISE channel alive)

Registered as a SECOND `Stop` hook alongside capture_turn.py. capture_turn
APPENDS this turn to observation_queue.jsonl; this hook periodically DRAINS
that queue into cross-domain insights, so life_state_monitor has something to
raise at the next SessionStart.

WHY A HOOK EXISTS AT ALL. Until 2026-09-06 the consolidator ran only inside
Mind's heartbeat, which runs only during `--ask`, which had not been used in 35
days. So the feed froze in June, the surfacing daemon fail-closed, and JARVIS
had nothing proactive to say — which removed the reason to run `--ask`. A closed
loop. This hook breaks it by driving the same Consolidator from the capture
stream that is already being written every turn. Mind's heartbeat is untouched
and still feeds the same organ whenever `--ask` runs.

WHY `Stop` AND NOT `SessionStart`. Consolidation walks a 21-day window and can
call a model. That must never sit in the path that opens a session. Running it
after a turn completes costs the user nothing.

THIN BY DESIGN, and hard-bounded:
  - ALL logic lives in scripts/consolidate.py + jarvis_core.agent.consolidator.
  - Deterministic template only (no --llm) so a background hook is never a
    surprise bill.
  - Rate-limited to once per day by consolidate.py, which reads the feed's own
    timestamps rather than keeping a sidecar state file.
  - Subprocess with a timeout, output discarded, every path returns exit 0.
    A consolidation failure must never break a turn.

=============================================================================
THE FLOW
=============================================================================

STEP 1: Read the Stop event JSON on stdin (for cwd only).
        |
STEP 2: Spawn `python3 scripts/consolidate.py` detached from this process's
        stdout, with a wall-clock timeout.
        |
STEP 3: Ignore the result entirely and exit 0. The feed either grew or it did
        not; either way the turn is already finished.
=============================================================================
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_TIMEOUT_SECONDS = 90


def _repo_root(cwd: str) -> Path:
    # Resolve relative to this file first so the hook is cwd-independent.
    here = Path(__file__).resolve().parents[2]
    if (here / "scripts" / "consolidate.py").exists():
        return here
    return Path(cwd)


def main() -> int:
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0

    try:
        root = _repo_root(event.get("cwd", os.getcwd()))
        runner = root / "scripts" / "consolidate.py"
        if not runner.exists():
            return 0
        subprocess.run(
            [sys.executable, str(runner)],
            cwd=str(root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
