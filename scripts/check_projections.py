#!/usr/bin/env python3
"""
check_projections.py — CLI adapter for the projection-integrity organ.

LAYER: Tools (thin adapter — all logic lives in jarvis_core)

Run with:
    python3 scripts/check_projections.py          # human report; exit 1 if stale
    python3 scripts/check_projections.py --line   # one line; always exit 0

Thin by design, per the Consciousness Portability Contract: every check lives
in jarvis_core/brain/projections.py so the boot inhale, a future hook, and this
CLI all share one implementation. See that module's header for why this exists
(the 544-vs-533 staleness window that nothing was looking for).

Exit codes are the point: 1 on stale makes this usable from a hook or CI, not
only by a human who remembered to look — which is the failure it addresses.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "js-development"))

from jarvis_core.brain.projections import (  # noqa: E402
    domain_label_health, id_collisions, run_checks, stale_line)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Verify every derived projection still matches knowledge_base.jsonl.")
    p.add_argument("--line", action="store_true",
                   help="one-line summary (boot-inhale form); always exits 0")
    p.add_argument("--only", metavar="SUBSTRING", default=None,
                   help="Consider ONLY projections whose name contains SUBSTRING "
                        "(e.g. --only chromadb). Needed because the scheduler uses "
                        "this as a per-job guard: an unfiltered check exits non-zero "
                        "if ANY projection is stale, so the job that ran FIRST would "
                        "clear the guard for a job that fixes a DIFFERENT artifact — "
                        "and the vector index would then never be rebuilt. Measured "
                        "live on 2026-09-08: refresh_profile ran, and reindex_memory "
                        "was skipped as 'nothing to do' on the strength of it.")
    args = p.parse_args()

    if args.line:
        print(stale_line() or "Derived indexes match the knowledge base.")
        return 0

    checks, expected, newest = run_checks()
    if args.only:
        needle = args.only.lower()
        checks = [c for c in checks if needle in c.name.lower()]
        if not checks:
            print(f"no projection matches --only {args.only!r}; "
                  f"known: {', '.join(c.name for c in run_checks()[0])}")
            return 2
    stale = [c for c in checks if c.stale]
    # A FACT-level id collision is never scoped away by --only: it invalidates
    # every projection built on top of it, so a filtered guard must still see it.
    collisions = id_collisions()

    print("=" * 68)
    print("  Projection integrity")
    print("=" * 68)
    print(f"  FACT  knowledge_base.jsonl : {expected} entries"
          f"{f' (newest {newest[:19]})' if newest else ''}")
    if collisions:
        print(f"  [STALE] kb id uniqueness      {len(collisions)} duplicated id(s): "
              f"{', '.join(f'{i}x{n}' for i, n in sorted(collisions.items())[:6])}")
        print("           fix: python3 scripts/kb_append.py --audit")
    else:
        print("  [  OK ] kb id uniqueness      no duplicate ids")
    # Accuracy, not a row count: the domain classifier's failure mode is being
    # confidently wrong, which no count can detect. Skipped by --only, since a
    # scheduled job guarding one artifact should not be blocked by a different one.
    drift = None if args.only else domain_label_health()
    if drift:
        print(f"  [STALE] domain classifier    {drift[:60]}...")
        print("           fix: python3 scripts/relabel_domains.py --gold")
    elif not args.only:
        print("  [  OK ] domain classifier     accuracy above the gold-set bar")
    print()
    for c in checks:
        print(f"  [{'STALE' if c.stale else '  OK '}] {c.name:<26} {c.detail}")
        if c.stale:
            print(f"           fix: {c.fix}")
    print("-" * 68)
    if collisions:
        print(f"  {len(collisions)} KB id collision(s) — this is a FACT-level fork, not")
        print("  a stale projection: two entries share an id, so every join on id")
        print("  silently picks one of them.")
    if stale:
        print(f"  {len(stale)} of {len(checks)} projections are stale.")
        print("  The log is intact — a stale projection does not corrupt the mind.")
        print("  But retrieval and the injected profile are describing an older")
        print("  version of it, silently. That silence is the bug this catches.")
    elif not collisions:
        print(f"  All {len(checks)} projections match; no id collisions.")
    print("=" * 68)
    return 1 if (stale or collisions or drift) else 0


if __name__ == "__main__":
    raise SystemExit(main())
