"""
surface_life_state.py — Claude Code SessionStart-hook: proactive surfacing.

LAYER: Tools (Personalization — the RAISE channel)

Registered as a SECOND `SessionStart` hook alongside inject_profile.py. Where
inject_profile injects the standing model of the user as BACKGROUND, this hook
asks JARVIS to RAISE a specific high-confidence cross-domain life-state insight
this session (the loop-3 fix from KB L310).

Thin by design: it delegates ALL logic to jarvis_core.agent.life_state_monitor
(stdlib-only, no embeddings, no network) so the session never blocks. If there
is nothing to surface, it emits nothing. It can NEVER break a session: every
path returns exit 0 and any error is swallowed.

=============================================================================
THE FLOW
=============================================================================

STEP 1: Read the SessionStart event JSON on stdin (cwd, source).
        |
STEP 2: Build a LifeStateMonitor and ask for the SessionStart payload (it
        selects one unsurfaced, high-confidence insight and advances the
        watermark so it is never surfaced again).
        |
STEP 3: If a payload exists, write it to stdout; else emit nothing. Exit 0.

=============================================================================
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _load_monitor(cwd: str):
    # Primary: resolve js-development relative to this file (cwd-independent).
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "js-development"))
        from jarvis_core.agent.life_state_monitor import LifeStateMonitor  # type: ignore
        return LifeStateMonitor()
    except Exception:
        pass
    # Fallback: a DIFFERENT path (cwd-relative) — only meaningful because it inserts a
    # new sys.path entry before retrying; otherwise it would just re-raise identically.
    try:
        sys.path.insert(0, str(Path(cwd) / "js-development"))
        from jarvis_core.agent.life_state_monitor import LifeStateMonitor  # type: ignore
        feed = Path(cwd) / "jarvis_data" / "life_state_feed.jsonl"
        wm = Path(cwd) / "jarvis_data" / ".surfaced_watermark"
        return LifeStateMonitor(feed_path=feed, watermark_path=wm)
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
        monitor = _load_monitor(cwd)
        if monitor is None:
            return 0
        payload = monitor.session_start_payload()
        if payload:
            sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
