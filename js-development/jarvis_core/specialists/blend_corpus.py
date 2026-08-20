"""
blend_corpus.py

Stage 5: Blended Specialist + Personalization Training Set.

Run with:
    PYTHONPATH=js-development python3 -m jarvis_core.specialists.blend_corpus

=============================================================================
THE BIG PICTURE: why ONE adapter, not two composed
=============================================================================

The requirement: personalization must be active for EVERY answer, from
whichever specialist responds — "the Orchestrator is also my JARVIS, it needs
to know me." The obvious-looking implementation (a personalization adapter
loaded alongside a domain adapter) does not work. Verified 2026-08-16:

    - vLLM serving docs, verbatim: "we only allow one LoRA per prompt."
      Its multi-LoRA feature routes DIFFERENT adapters to DIFFERENT requests
      in a batch; it does not stack two adapters on one inference.
    - This codebase already encodes the same constraint independently:
      brain/targets.py PodHandle.__init__(self, adapter_id: str, ...) —
      a singular string, not a list.
    - Merging two independently-trained adapters is not a safe fallback.
      The literature describes it as a worst-case interference setting, with
      degradation that is highly non-uniform and can collapse on specific
      domains.
    - Training ONE adapter on a MIXED corpus empirically beats merging
      separately-trained adapters on the same skills.

So: blend the corpora, train once. This requires no unsolved technology, is
compatible with one-LoRA-per-prompt as it actually exists, costs one training
run instead of two, and validates ENDGAME §3's existing architecture instead
of demanding a rewrite of it.

Scaling caveat, stated rather than hidden: each future specialist needs its
own `specialist + personalization` mixed adapter, duplicating the
personalization data per adapter. Acceptable at the 2-3 specialists the
demand-gating decision (KB 463) actually permits; genuinely awkward at 12.

=============================================================================
THE FLOW
=============================================================================

STEP 1: Read both already-verified corpora — engineer_corpus.jsonl (1,356
        records, near-dupe capped) and personalization_corpus.jsonl (479
        records, id-deduped, facts/voice separated). This module blends; it
        never re-derives what those two already built.
        |
STEP 2: Tag every record with `origin_corpus` so the blend stays auditable
        and a training run can weight or ablate either side later.
        |
STEP 3: Apply _PERSONALIZATION_REPEATS (see below — a real open question,
        deliberately a visible constant rather than a buried default).
        |
STEP 4: Stream to blended_corpus.jsonl through one handle; report the
        realized ratio, which is the number that actually matters.

LAYER: Specialists (Corpus Assembly)
=============================================================================
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Generator, Optional, Tuple

from jarvis_core.config import SPECIALIST_CORPUS_ROOT

_ENGINEER_PATH = SPECIALIST_CORPUS_ROOT / "engineer_corpus.jsonl"
_PERSONALIZATION_PATH = SPECIALIST_CORPUS_ROOT / "personalization_corpus.jsonl"
_OUTPUT_PATH = SPECIALIST_CORPUS_ROOT / "blended_corpus.jsonl"

# OPEN QUESTION, not a settled default. Raw counts are 1,356 engineer : 479
# personalization — personalization is ~26% of the blend. The adapter has to
# learn BOTH "how this user's code and DE work looks" and "who this user is,"
# and at roughly 1-in-4 the personal signal may simply get washed out by the
# much larger volume of code text.
#
# Set to 1 (no upsampling) so the FIRST run measures the honest baseline
# rather than pre-compensating for a problem that hasn't been observed yet.
# Raise this if evaluation (Stage 5.3) shows the adapter learned the code
# style but not the person. Kept as a visible module constant precisely so
# that tuning knob is findable instead of buried in a training script.
_PERSONALIZATION_REPEATS = 1


@dataclass(frozen=True)
class BlendStats:
    per_origin: Dict[str, int]
    total_records: int
    personalization_share: float
    output_path: Path
    missing_inputs: Tuple[str, ...] = field(default_factory=tuple)


def _iter_corpus(path: Path, origin: str) -> Generator[Dict[str, Any], None, None]:
    """Streams one source corpus, stamping origin. Never materializes the file."""
    try:
        handle = path.open("r", encoding="utf-8")
    except OSError:
        return
    with handle:
        for raw in handle:
            raw = raw.strip()
            if not raw:
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError:
                continue
            record["origin_corpus"] = origin
            yield record


def blend(output_path: Optional[Path] = None) -> BlendStats:
    """
    LAYER: Specialists (Corpus Assembly)

    Fails loud on a missing input rather than silently emitting a half blend —
    a training set quietly missing its personalization half would produce an
    adapter that looks trained and simply doesn't know the user.
    """
    out = output_path or _OUTPUT_PATH
    out.parent.mkdir(parents=True, exist_ok=True)

    missing = tuple(
        name for name, path in (
            ("engineer_corpus.jsonl", _ENGINEER_PATH),
            ("personalization_corpus.jsonl", _PERSONALIZATION_PATH),
        ) if not path.is_file()
    )

    per_origin: Dict[str, int] = {"engineer": 0, "personalization": 0}
    total = 0

    with out.open("w", encoding="utf-8") as handle:
        for record in _iter_corpus(_ENGINEER_PATH, "engineer"):
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            per_origin["engineer"] += 1
            total += 1

        for _ in range(_PERSONALIZATION_REPEATS):
            for record in _iter_corpus(_PERSONALIZATION_PATH, "personalization"):
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                per_origin["personalization"] += 1
                total += 1

    share = (per_origin["personalization"] / total) if total else 0.0
    return BlendStats(
        per_origin=per_origin,
        total_records=total,
        personalization_share=share,
        output_path=out,
        missing_inputs=missing,
    )


def main() -> None:
    print("=" * 70)
    print("  JARVIS: Blended Engineer + Personalization Training Set")
    print("=" * 70)

    stats = blend()

    if stats.missing_inputs:
        print("\n  MISSING INPUT CORPORA — blend is incomplete:")
        for name in stats.missing_inputs:
            print(f"    - {name}")
        print("  Rebuild via the corresponding *_corpus.py module first.")

    print(f"\n  {'Origin':<20} {'Records':>10} {'Share':>10}")
    print("  " + "-" * 42)
    for origin, count in stats.per_origin.items():
        share = (count / stats.total_records * 100) if stats.total_records else 0.0
        print(f"  {origin:<20} {count:>10,} {share:>9.1f}%")
    print("  " + "-" * 42)
    print(f"  {'TOTAL':<20} {stats.total_records:>10,}")

    print(f"\n  Personalization upsampling: x{_PERSONALIZATION_REPEATS}")
    print(f"  Realized personalization share: {stats.personalization_share:.1%}")

    if stats.output_path.is_file():
        size = stats.output_path.stat().st_size
        print(f"\n  Output: {stats.output_path} ({size:,} bytes)")
    print("=" * 70)


if __name__ == "__main__":
    main()
