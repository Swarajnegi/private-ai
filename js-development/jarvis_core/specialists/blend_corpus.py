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

STEP 1: Read both already-verified corpora — engineer_corpus.jsonl and
        personalization_corpus.jsonl. This module blends; it never re-derives
        what those two already built. Record counts are deliberately NOT
        quoted here: `python3 scripts/check_pipeline.py` prints the live ones,
        and the counts this docstring used to name (1,356 / 479) were both
        stale by roughly 2x when anyone finally checked.
        |
STEP 2: Build the personalization text-key set, then SKIP every engineer
        record carrying identical text. PERSONALIZATION OWNS SHARED TEXT —
        see _OWNERSHIP below for what that decision cost and why.
        |
STEP 3: Tag every surviving record with `origin_corpus` so the blend stays
        auditable and a training run can weight or ablate either side later.
        |
STEP 4: Apply _PERSONALIZATION_REPEATS (see below — a real open question,
        deliberately a visible constant rather than a buried default).
        |
STEP 5: Stream to blended_corpus.jsonl through one handle; report the
        realized ratio, which is the number that actually matters.

LAYER: Specialists (Corpus Assembly)
=============================================================================
"""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Generator, Optional, Set, Tuple

from jarvis_core.config import SPECIALIST_CORPUS_ROOT
from jarvis_core.specialists import third_parties
from jarvis_core.specialists.eval_exclusions import has_canary, load_registry

_ENGINEER_PATH = SPECIALIST_CORPUS_ROOT / "engineer_corpus.jsonl"
_PERSONALIZATION_PATH = SPECIALIST_CORPUS_ROOT / "personalization_corpus.jsonl"
_OUTPUT_PATH = SPECIALIST_CORPUS_ROOT / "blended_corpus.jsonl"

# OPEN QUESTION, not a settled default — and the numbers moved sharply on
# 2026-08-22 when client_work (real BUPA production DE, ~580k chars of it)
# entered the engineer corpus.
#
# MEASURE IN CHARACTERS, NOT RECORDS. This is the part that was quietly wrong
# before: at repeats=1 the blend reports 22.2% personalization BY RECORD COUNT
# but only 7.6% BY CHARACTER, because engineer records (code/YAML chunks up to
# 4k chars) are far larger than personalization records (a large share are
# short voice fragments). Training consumes tokens, so 7.6% is the real
# number and the record share was overstating the personal signal ~3x. It was
# ~13% by character before client_work landed; adding real production code
# nearly halved it.
#
# Still set to 1 (no upsampling), deliberately, for the same reason as before:
# the first training run should measure the honest baseline rather than
# pre-compensate for a problem not yet observed in an actual adapter. But note
# the decision has NOT gotten easier — it got sharper, and 7.6% is low enough
# that "the adapter learned the code style but not the person" is now the
# expected failure mode rather than a hypothetical one.
#
# Raising this is the lever if Stage 5.3 evaluation shows that. Rough guide
# from the current numbers: x2 -> ~14% char share, x3 -> ~20%, x5 -> ~29%.
# Upsampling repeats identical text, which risks memorization of the small
# personalization set — so prefer GROWING that corpus over multiplying it
# where both options exist.
_PERSONALIZATION_REPEATS = 1


# OWNERSHIP OF SHARED TEXT — decided by the user 2026-09-18 after measurement.
#
# 338 records were BYTE-IDENTICAL in both corpora: 533,736 chars, which is
# 57.6% of the entire personalization corpus. The blend used to be a straight
# concatenation (3,407 = 2,525 + 882), so every one of them was written TWICE
# and trained twice per epoch.
#
# That is the precise thing _PERSONALIZATION_REPEATS above refuses to do. The
# constant is set to 1 specifically because repeating a thin personalization
# set risks memorization — and the concatenation then upsampled 312 KB records
# 2x anyway, behind the constant's back. The worst class of text to memorize
# verbatim, too: KB entries are the most abstract, most written-ABOUT-the-user
# material in the corpus.
#
# WHY IT WENT UNNOTICED: personalization_corpus.py prints a NOTE saying
# professional_reasoning is "intentionally double-counted", which reads as
# "understood and deliberate" — it explained 17 of the 338 records (12.6%).
# check_pipeline.py reported "338 repeats, all accounted for", where
# "accounted for" means the ARITHMETIC RECONCILES, not that anyone chose it.
#
# THE DECISION WAS OWNERSHIP, NOT DEDUPE. Total is 6,559,497 chars either way;
# only the attribution moves, and it moves the headline number a Stage 5 spend
# decision is gated on:
#     personalization owns them -> 14.1% char share   <- CHOSEN
#     engineer owns them        ->  6.0% char share
#     both (the old behaviour)  -> 13.1% reported, and trained twice
# Personalization wins because engineer already carries ~5.6M chars of code,
# client_work and DE material — it does not learn engineering from KB prose,
# whereas kb_identity/kb_judgment ARE definitionally the personalization
# signal. Giving them to engineer would buy engineer nothing and gut the only
# corpus that is actually thin.
#
# Deduping at BLEND time rather than at source is deliberate: 17 of the shared
# records are professional_reasoning comment blocks living INSIDE client_work
# text, which cannot be removed from the engineer corpus without mutilating
# the record they are embedded in. Blend-time ownership handles all 338
# uniformly; source-time exclusion could only ever handle 321 of them.


@dataclass(frozen=True)
class BlendStats:
    per_origin: Dict[str, int]
    per_origin_chars: Dict[str, int]
    total_records: int
    total_chars: int
    personalization_share: float
    personalization_char_share: float
    dropped_to_personalization: int
    dropped_chars: int
    output_path: Path
    missing_inputs: Tuple[str, ...] = field(default_factory=tuple)
    third_party_redactions: int = 0
    eval_excluded: int = 0


def _text_key(text: str) -> str:
    """Exact-text identity for cross-corpus ownership. Near-dupes are already
    capped upstream by each corpus builder, so only byte-identical text is a
    double-count here."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _personalization_keys(path: Path) -> Set[str]:
    """Text keys the personalization corpus claims.

    Holds HASHES, not text — bounded at 20 bytes per record regardless of how
    large the corpus grows, so the module's streaming guarantee survives. The
    text itself is never materialized.
    """
    keys: Set[str] = set()
    try:
        handle = path.open("r", encoding="utf-8")
    except OSError:
        return keys
    with handle:
        for raw in handle:
            raw = raw.strip()
            if not raw:
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError:
                continue
            keys.add(_text_key(record.get("text", "")))
    return keys


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
    per_origin_chars: Dict[str, int] = {"engineer": 0, "personalization": 0}
    total = 0
    dropped = 0
    dropped_chars = 0

    owned_by_personalization = _personalization_keys(_PERSONALIZATION_PATH)
    people = third_parties.load()
    redactions = 0
    registry = load_registry()
    eval_excluded = 0

    with out.open("w", encoding="utf-8") as handle:
        for record in _iter_corpus(_ENGINEER_PATH, "engineer"):
            text = record.get("text", "")
            if has_canary(registry, text):
                eval_excluded += 1
                continue
            if _text_key(text) in owned_by_personalization:
                dropped += 1
                dropped_chars += len(text)
                continue
            text, hits = third_parties.redact(text, people)
            record["text"] = text
            redactions += hits
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            per_origin["engineer"] += 1
            per_origin_chars["engineer"] += len(text)
            total += 1

        for _ in range(_PERSONALIZATION_REPEATS):
            for record in _iter_corpus(_PERSONALIZATION_PATH, "personalization"):
                if has_canary(registry, record.get("text", "")):
                    eval_excluded += 1
                    continue
                record["text"], hits = third_parties.redact(record.get("text", ""), people)
                redactions += hits
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                per_origin["personalization"] += 1
                per_origin_chars["personalization"] += len(record.get("text", ""))
                total += 1

    total_chars = sum(per_origin_chars.values())
    return BlendStats(
        per_origin=per_origin,
        per_origin_chars=per_origin_chars,
        total_records=total,
        total_chars=total_chars,
        personalization_share=(per_origin["personalization"] / total) if total else 0.0,
        personalization_char_share=(
            per_origin_chars["personalization"] / total_chars if total_chars else 0.0
        ),
        dropped_to_personalization=dropped,
        dropped_chars=dropped_chars,
        output_path=out,
        missing_inputs=missing,
        third_party_redactions=redactions,
        eval_excluded=eval_excluded,
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

    # BOTH shares, because they disagree badly and only one of them is the
    # number that matters. Training consumes TOKENS, not records, and the two
    # corpora have wildly different record sizes: client_work chunks average
    # ~3.5k chars while a large share of personalization records are short
    # voice fragments. Reporting record share alone overstated the personal
    # signal by ~3x (22.2% of records = 7.6% of characters, measured
    # 2026-08-22) — a "share" that does not reflect what the model sees is
    # worse than no share at all, because it gets tuned against.
    print(f"\n  {'Origin':<18} {'Records':>9} {'Rec %':>8} {'Chars':>12} {'~Tokens':>10} {'Char %':>8}")
    print("  " + "-" * 69)
    for origin, count in stats.per_origin.items():
        chars = stats.per_origin_chars[origin]
        rec_pct = (count / stats.total_records * 100) if stats.total_records else 0.0
        chr_pct = (chars / stats.total_chars * 100) if stats.total_chars else 0.0
        print(f"  {origin:<18} {count:>9,} {rec_pct:>7.1f}% {chars:>12,} {chars // 4:>10,} {chr_pct:>7.1f}%")
    print("  " + "-" * 69)
    print(f"  {'TOTAL':<18} {stats.total_records:>9,} {'':>8} {stats.total_chars:>12,} {stats.total_chars // 4:>10,}")

    if stats.dropped_to_personalization:
        print()
        print(f"  Shared text owned by personalization: "
              f"{stats.dropped_to_personalization:,} record(s), "
              f"{stats.dropped_chars:,} chars")
        print("  ^ these were byte-identical in BOTH corpora. The engineer copy is")
        print("    dropped so they train ONCE, attributed to personalization.")
        print("    Before this rule they were concatenated and trained TWICE - see")
        print("    the OWNERSHIP note above for the measurement that found it.")

    if stats.third_party_redactions:
        print()
        print(f"  Third-party identifiers redacted: {stats.third_party_redactions:,} (see jarvis_data/third_parties.json)")

    print(f"\n  Personalization upsampling: x{_PERSONALIZATION_REPEATS}")
    print(f"  Realized personalization share: {stats.personalization_share:.1%} of records, "
          f"{stats.personalization_char_share:.1%} of characters")
    if stats.personalization_char_share < 0.15:
        print(f"  ^ CHAR SHARE IS THE ONE THAT MATTERS. At "
              f"{stats.personalization_char_share:.1%} the personal signal is a rounding\n"
              f"    error against the code volume. Raising _PERSONALIZATION_REPEATS is the\n"
              f"    lever; see that constant's note for why it is not pre-set.")

    if stats.output_path.is_file():
        size = stats.output_path.stat().st_size
        print(f"\n  Output: {stats.output_path} ({size:,} bytes)")
    print("=" * 70)


if __name__ == "__main__":
    main()
