#!/usr/bin/env python3
"""
consolidate.py — run the sleep-time consolidator outside a Mind boot.

LAYER: Agent (Cognitive Synthesis Loop — the missing runner)

Run with:
    python3 scripts/consolidate.py --dry-run     # inspect, write nothing
    python3 scripts/consolidate.py               # deterministic, no LLM, ₹0

=============================================================================
THE BIG PICTURE
=============================================================================

JARVIS's one genuinely differentiated capability is UNPROMPTED SURFACING: it
says "you decided the opposite in July" at the moment it matters, rather than
answering well when asked. A frontier subscription matches everything else the
moment you paste the right context — but pasting requires knowing what you
forgot. That gap is the whole moat.

The organ for it exists and is good: agent/life_state_monitor.py (3.5.11),
fail-closed, never-nags, watermarked, wired as a SessionStart hook. On
2026-09-06 it was found DEAD — 3 insights surfaced, all on 2026-06-18, nothing
since.

THE DEADLOCK, which is why:

    Consolidator runs only inside Mind's heartbeat (mind.py:349)
      -> Mind boots only during `--ask`
        -> `--ask` unused for 35 days
          -> life_state_feed.jsonl frozen at 3 June entries
            -> life_state_monitor fail-closes, surfaces nothing
              -> JARVIS has nothing to say
                -> no reason to open `--ask`

A closed loop: the capability that would justify using JARVIS is starved by
not using JARVIS.

WHAT WAS ACTUALLY MISSING was small. CrossDomainCorrelationEngine already reads
observation_queue.jsonl (correlation.py:86) — the Claude Code capture stream,
535 turns of real work. It was never `--ask`-specific. Nothing simply CALLED
it outside the heartbeat. This script is that call.

Both sources now feed one organ: this runner drains the Claude Code queue, and
Mind's heartbeat still runs the same Consolidator during `--ask`. The heartbeat
path is deliberately untouched.

NO MODEL CALL, BY THE OWNER'S RULE (2026-09-28). This runner used to build a
paid tension judge (TensionDetector + TensionJudge over OpenRouter) and scan
40 candidates a day with it. Background jobs make no paid LLM calls now: the
agent the owner was talking to parses its own turns by parse_rule.PARSE_RULE,
and that verdict carries the tension judgement against the priors it was
handed. scripts/parse_turns.py writes it through Consolidator.record_finding,
the same KB + life_state_feed path a scan used, so the surfacing organ reads
one feed either way. What stays here is the part that never needed a model:
the behavioural activity model.

NOT A LICENCE TO LOWER THE BAR: the 0.60 surface floor is epistemic control. On
the day this shipped the best live link scored 0.592 and correctly produced
NOTHING. A consolidator that always finds something is a consolidator that
invents things.

=============================================================================
THE FLOW
=============================================================================

STEP 1: Rate-limit on ATTEMPT — if behavioral_state_model.jsonl was written
        today, exit 0 immediately. That file is persisted on every run whether
        or not anything clears the floor, so "found nothing" does not read as
        "never ran" and re-trigger on every turn.
        |
STEP 2: Build CrossDomainCorrelationEngine (reads observation_queue.jsonl),
        with no model.
        |
STEP 3: --dry-run stops here and prints the model: turns and domains.
        Writes nothing.
        |
STEP 4: Otherwise await consolidate(), which persists the behavioural model.
        Tension findings arrive through parse submissions, not from here.
=============================================================================
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "js-development"))

from jarvis_core.config import DATA_ROOT  # noqa: E402
from jarvis_core.agent.correlation import CrossDomainCorrelationEngine  # noqa: E402
from jarvis_core.agent.consolidator import Consolidator  # noqa: E402

_IST = timezone(timedelta(hours=5, minutes=30))
_FEED_PATH = Path(DATA_ROOT) / "life_state_feed.jsonl"

# The rate limit keys off THIS file, not the feed. Consolidator.consolidate()
# persists the behavioural model on every run whether or not any link clears
# the floor — so it records that we ATTEMPTED today. Keying off the feed would
# mean "nothing cleared the floor" reads as "never ran", and a Stop hook would
# then re-run the correlation engine on literally every turn.
_ATTEMPT_MARKER = Path(DATA_ROOT) / "behavioral_state_model.jsonl"


def _already_ran_today(marker_path: Path, now: datetime) -> bool:
    """Rate-limit on attempt, not on output."""
    try:
        mtime = datetime.fromtimestamp(marker_path.stat().st_mtime, tz=_IST)
    except (OSError, FileNotFoundError):
        return False
    return mtime.date() == now.date()


async def _run(args: argparse.Namespace) -> int:
    now = datetime.now(_IST)
    feed_path = Path(args.feed) if args.feed else _FEED_PATH

    if not args.dry_run and not args.force and _already_ran_today(_ATTEMPT_MARKER, now):
        print("[consolidate] already ran today — skipping (--force to override)")
        return 0

    engine = CrossDomainCorrelationEngine()
    model = await engine.build_model(window_days=args.window, now=now)

    print(f"[consolidate] window={args.window}d  turns={model.total_turns}  "
          f"domains={len(model.domains)}  floor={args.floor}")
    for d in model.domains:
        print(f"    domain  {d.domain:<20} {d.turn_count:>4} turns")

    if args.dry_run:
        print("[consolidate] --dry-run: nothing written")
        return 0

    consolidator = Consolidator(engine=engine, feed_path=feed_path,
                               confidence_floor=args.floor)
    await consolidator.consolidate(window_days=args.window, now=now)
    print("[consolidate] behavioural model persisted. Tension is judged by the agent "
          "parsing each turn (scripts/parse_turns.py), not by a background model.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="Run the sleep-time consolidator over the capture queue.")
    p.add_argument("--window", type=int, default=21,
                   help="days of observation history to model (default 21)")
    p.add_argument("--floor", type=float, default=0.55,
                   help="confidence floor for surfacing (default 0.60 — do not "
                        "lower this to manufacture output)")
    p.add_argument("--dry-run", action="store_true",
                   help="print the model and exit without writing")
    p.add_argument("--force", action="store_true",
                   help="ignore the once-per-day rate limit")
    p.add_argument("--feed", type=str, default=None,
                   help="override feed path (testing)")
    args = p.parse_args()

    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        # A hook calls this. It must never take a session down with it.
        print(f"[consolidate] failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
