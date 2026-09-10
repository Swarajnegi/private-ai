#!/usr/bin/env python3
"""
consolidate.py — run the sleep-time consolidator outside a Mind boot.

LAYER: Agent (Cognitive Synthesis Loop — the missing runner)

Run with:
    python3 scripts/consolidate.py --dry-run     # inspect, write nothing
    python3 scripts/consolidate.py               # deterministic, no LLM, ₹0
    python3 scripts/consolidate.py --llm         # richer synthesis via OpenRouter

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
STEP 2: Build CrossDomainCorrelationEngine (reads observation_queue.jsonl) and
        Consolidator, with llm_call only when --llm is passed.
        |
STEP 3: --dry-run stops here and prints the model: turns, domains, links and
        which would clear the floor. Writes nothing.
        |
STEP 4: Otherwise await consolidate(): links >= floor are synthesized, written
        to the KB through scripts/kb_append.py (the single write path) and
        appended to the feed for life_state_monitor to drain next session.
=============================================================================
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

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


def _build_llm_call():
    """Only imported when --llm is passed: the default path must stay ₹0."""
    from jarvis_core.brain.llm_client import build_llm_call
    return build_llm_call()


def _build_detector(args):
    """The tension detector, or None with the reason printed.

    UNLIKE the retired link path, this one CANNOT degrade to a deterministic
    template — judging whether a new claim contradicts an old one is not
    expressible as a formula, which is precisely why the formula-based detector
    produced nothing worth reading for 80 days. So a missing model means NO
    findings, said out loud, rather than a fabricated one.
    """
    from jarvis_core.agent.tension import TensionDetector, TensionJudge
    from jarvis_core.brain.llm_client import build_llm_call
    from jarvis_core.brain.boot import MEMORY_COLLECTION

    try:
        from jarvis_core.memory.store import JarvisMemoryStore
        from jarvis_core.agent.memory_manager import MemoryManager
        store = JarvisMemoryStore()
        store.__enter__()
        retriever = MemoryManager(store=store, collection_name=MEMORY_COLLECTION)
    except Exception as e:
        print(f"[consolidate] no retriever ({type(e).__name__}: {e}) — "
              f"tension detection DISABLED this run")
        return None

    try:
        judge_llm = build_llm_call(budget_usd=None)
    except Exception as e:
        print(f"[consolidate] no judge model ({type(e).__name__}) — "
              f"tension detection DISABLED this run")
        return None

    return TensionDetector(retriever=retriever, judge=TensionJudge(judge_llm),
                           confidence_floor=args.floor)


async def _run(args: argparse.Namespace) -> int:
    now = datetime.now(_IST)
    feed_path = Path(args.feed) if args.feed else _FEED_PATH

    if not args.dry_run and not args.force and _already_ran_today(_ATTEMPT_MARKER, now):
        print("[consolidate] already ran today — skipping (--force to override)")
        return 0

    llm_call = None
    if args.llm:
        try:
            llm_call = _build_llm_call()
        except Exception as e:
            # Degrading to the template is correct: the consolidator's own
            # contract says the loop still runs without a model.
            print(f"[consolidate] llm unavailable ({type(e).__name__}) — "
                  f"falling back to deterministic template")

    engine = CrossDomainCorrelationEngine(llm_call=llm_call)
    model = await engine.build_model(window_days=args.window, now=now)

    print(f"[consolidate] window={args.window}d  turns={model.total_turns}  "
          f"domains={len(model.domains)}  floor={args.floor}")
    for d in model.domains:
        print(f"    domain  {d.domain:<20} {d.turn_count:>4} turns")

    # THE DETECTOR (2026-09-09). The engine above is telemetry; insights come from
    # here — what the user is doing now, judged against their own past decisions
    # and failures. Needs BOTH a retriever (the existing chromadb KB index, no new
    # index) and a judge model. Missing either means no findings, reported plainly
    # rather than silently producing nothing.
    detector = _build_detector(args)

    if args.dry_run:
        findings = await detector.scan(limit=args.scan_limit, advance=False) if detector else []
        print(f"[consolidate] --dry-run: {len(findings)} finding(s), nothing written")
        for f in findings:
            print(f"    {f.relation:<11} {f.confidence:.2f}  {f.surface_line()[:110]}")
        return 0

    consolidator = Consolidator(engine=engine, llm_call=llm_call,
                               feed_path=feed_path,
                               confidence_floor=args.floor,
                               detector=detector)
    result = await consolidator.consolidate(window_days=args.window, now=now)

    print(f"[consolidate] kb_writes={result.kb_writes}  "
          f"feed_writes={result.feed_writes}  "
          f"skipped_low_confidence={result.skipped_low_confidence}")
    for insight in result.insights:
        print(f"    surfaced-able  {insight.confidence:.3f}  "
              f"{insight.surface_line[:100]}")
    if not result.insights:
        print("[consolidate] no tension found — the correct outcome when nothing "
              "the user did contradicts what they already decided. Silence here "
              "is a result, not a failure.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="Run the sleep-time consolidator over the capture queue.")
    p.add_argument("--window", type=int, default=21,
                   help="days of observation history to model (default 21)")
    p.add_argument("--scan-limit", type=int, default=40, dest="scan_limit",
                   help="max candidates judged per run (bounds spend on a backlog: "
                        "the first run has ~580 queue turns behind it)")
    p.add_argument("--floor", type=float, default=0.55,
                   help="confidence floor for surfacing (default 0.60 — do not "
                        "lower this to manufacture output)")
    p.add_argument("--llm", action="store_true",
                   help="use an LLM for synthesis prose (costs money); default "
                        "is the deterministic template")
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
