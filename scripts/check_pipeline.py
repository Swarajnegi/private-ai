#!/usr/bin/env python3
"""
check_pipeline.py — invariants BETWEEN the corpus artifacts, which nothing owned.

LAYER: Tools (verification)

    python3 scripts/check_pipeline.py             # all invariants
    python3 scripts/check_pipeline.py --verbose   # plus example offenders
    python3 scripts/check_pipeline.py --self-test # hermetic, no repo data

=============================================================================
THE BIG PICTURE
=============================================================================

Every bug found on 2026-09-15 lived in a RELATIONSHIP between artifacts, and
not one lived inside a module's own logic:

    11% of blended_corpus.jsonl duplicated   — a queue-to-corpus relationship
    UI answers paired with a fake prompt     — conversations-to-pairs
    machine text reaching assistant targets  — queue-to-pairs

All 94 smoke suites passed throughout, and correctly: no module owns a
relationship, so no module's tests can see one break. `check_projections.py`
covers KB-to-projection freshness and stops there. The corpus pipeline is six
artifacts —

    observation_queue -> turn_curation -> engineer/personalization -> blend
                                                                  -> sft_pairs

— and before this file, NOTHING compared any of them against any other. Each
count was produced independently and reconciled with nothing.

=============================================================================
WHY THESE INVARIANTS AND NOT OTHERS
=============================================================================

Each one below is derived from a defect that actually occurred, not from
imagining what might. An invariant nobody has seen fail is a guess about the
future; these are all descriptions of the past.

Where an invariant cannot be checked honestly it is reported as UNKNOWN rather
than quietly passing — a green line that means "not measured" is how
`domain_labels.jsonl` sat six days stale while calling itself authoritative.

=============================================================================
WHAT THIS DOES NOT COVER
=============================================================================

  * Semantic quality. It cannot tell a good training pair from a bad one; that
    is what Antigravity's a_005 audit did by reading rows, and it took a human-
    shaped judgement.
  * Anything upstream of the queue. If a capture adapter drops turns at the
    source, every downstream count is consistently wrong and this stays green.
  * Module-internal logic — that is `scripts/run_all_tests.py`.

=============================================================================
THE FLOW
=============================================================================

STEP 1: load each artifact once, tolerating a torn final line rather than
        dying on it (the queue is append-only and a killed writer happens).
        |
STEP 2: run each invariant; each returns OK / FAIL / UNKNOWN plus a count and
        up to three example offenders.
        |
STEP 3: print one line per invariant and exit non-zero if any FAILed, so the
        hearth records a real failure rather than a quiet log line.
=============================================================================
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "js-development"))

OK, FAIL, UNKNOWN = "OK", "FAIL", "UNKNOWN"

# A handful of prompts are reused by design — the rotation in build_sft_pairs
# deliberately shares templates. Past this many pairs on ONE prompt, the model
# sees one input mapped to many different targets, which teaches nothing.
_MAX_PAIRS_PER_PROMPT = 10


@dataclass
class Finding:
    name: str
    status: str
    detail: str = ""
    examples: List[str] = field(default_factory=list)


def _load(path: Path) -> List[Dict[str, Any]]:
    """Every parseable record. A torn final line is skipped, not fatal."""
    out: List[Dict[str, Any]] = []
    try:
        handle = path.open("r", encoding="utf-8", errors="replace")
    except (OSError, FileNotFoundError):
        return out
    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


@dataclass
class Artifacts:
    root: Path

    def __post_init__(self) -> None:
        d = self.root / "jarvis_data"
        c = d / "training_corpus"
        self.queue = _load(d / "observation_queue.jsonl")
        self.curation = _load(d / "turn_curation.jsonl")
        self.engineer = _load(c / "engineer_corpus.jsonl")
        self.personalization = _load(c / "personalization_corpus.jsonl")
        self.blend = _load(c / "blended_corpus.jsonl")
        self.pairs = _load(c / "sft_pairs.jsonl")
        self.heldout = _load(c / "sft_pairs_heldout.jsonl")
        self.conversations = d / "conversations"


# =============================================================================
# The invariants. Each is named for the defect it would have caught.
# =============================================================================

def inv_no_exact_duplicates(a: Artifacts) -> List[Finding]:
    """357 of 3,291 blend records were byte-identical copies (2026-09-15).

    `_MAX_PER_CLUSTER = 2` caps NEAR-duplicates at two, which is right for
    near-duplicates and wrong for exact ones: a byte-identical record carries
    no new information and simply over-weights that sample in training.
    """
    findings: List[Finding] = []
    for label, rows in (("engineer_corpus", a.engineer),
                        ("personalization_corpus", a.personalization)):
        if not rows:
            findings.append(Finding(f"no exact dupes: {label}", UNKNOWN, "artifact absent"))
            continue
        counts = collections.Counter(str(r.get("text", "")) for r in rows)
        dupes = {t: n for t, n in counts.items() if n > 1 and t}
        extra = sum(n - 1 for n in dupes.values())
        findings.append(Finding(
            f"no exact dupes: {label}",
            OK if not dupes else FAIL,
            f"{extra} redundant of {len(rows)} ({extra / len(rows):.1%})" if dupes
            else f"{len(rows)} records, all distinct",
            [t[:90] for t in list(dupes)[:3]]))
    findings.extend(inv_blend_duplication_is_explained(a))
    return findings


def inv_blend_duplication_is_explained(a: Artifacts) -> List[Finding]:
    """The blend legitimately contains some text twice — but only some.

    THIS INVARIANT WAS WRONG IN ITS FIRST FORM and the correction is the point.
    It flagged every duplicate in `blended_corpus.jsonl` as a defect. After both
    source corpora were deduped it still reported 9.9%, because the blend
    CONCATENATES two corpora that legitimately share source material:
    `personalization_corpus` says outright that `professional_reasoning` is
    "intentionally double-counted — the same comment blocks also remain in
    engineer_corpus's client_work records."

    A check that fails on intended behaviour trains people to ignore it, which
    is worse than no check. So the assertion is not "no duplication" but "no
    duplication I cannot ACCOUNT for": every repeated blend record must be
    explained by a text present in both source corpora. Anything beyond that is
    new duplication and fails.

    The explained portion is printed rather than swallowed, because 312 of the
    338 are KB entries reaching both corpora and — unlike the 17 client_work
    ones — that has never been written down as deliberate.
    """
    if not a.blend:
        return [Finding("blend duplication is explained", UNKNOWN, "artifact absent")]
    if not a.engineer or not a.personalization:
        return [Finding("blend duplication is explained", UNKNOWN, "source corpora absent")]
    counts = collections.Counter(str(r.get("text", "")) for r in a.blend)
    redundant = sum(n - 1 for n in counts.values() if n > 1)
    overlap = {str(r.get("text", "")) for r in a.engineer} & {
        str(r.get("text", "")) for r in a.personalization}
    unexplained = redundant - len(overlap)
    return [Finding(
        "blend duplication is explained",
        OK if unexplained <= 0 else FAIL,
        f"{redundant} repeats, {len(overlap)} explained by cross-corpus overlap"
        + (f", {unexplained} UNEXPLAINED" if unexplained > 0 else " (all accounted for)"))]


def inv_pair_targets_are_owner_prose(a: Artifacts) -> List[Finding]:
    """27 SFT assistant targets were pasted shell transcripts (q_003, 2026-09-11).

    With loss masking on assistant tokens this teaches the adapter to emit a
    shell prompt when asked to reason.
    """
    try:
        from jarvis_core.specialists.text_hygiene import MACHINE_TEXT, classify
    except ImportError:
        return [Finding("pair targets are not machine text", UNKNOWN, "text_hygiene unavailable")]
    findings = []
    for label, rows in (("sft_pairs", a.pairs), ("sft_pairs_heldout", a.heldout)):
        if not rows:
            findings.append(Finding(f"targets not machine text: {label}", UNKNOWN, "absent"))
            continue
        bad = []
        for r in rows:
            msgs = r.get("messages") or []
            if len(msgs) < 2:
                continue
            target = str(msgs[1].get("content", ""))
            if classify(target)[0] == MACHINE_TEXT:
                bad.append(target[:90])
        findings.append(Finding(
            f"targets not machine text: {label}",
            OK if not bad else FAIL,
            f"{len(bad)} of {len(rows)} are machine text" if bad else f"{len(rows)} clean",
            bad[:3]))
    return findings


def inv_heldout_is_isolated(a: Artifacts) -> List[Finding]:
    """A held-out slice that overlaps train measures nothing (spec §7/§8.3)."""
    if not a.pairs or not a.heldout:
        return [Finding("held-out is isolated", UNKNOWN, "artifact absent")]
    def sig(r): return json.dumps(r.get("messages"), sort_keys=True)
    train = {sig(r) for r in a.pairs}
    overlap = [r for r in a.heldout if sig(r) in train]
    return [Finding(
        "held-out is isolated", OK if not overlap else FAIL,
        f"{len(overlap)} of {len(a.heldout)} held-out pairs also in train" if overlap
        else f"{len(a.heldout)} held-out, zero overlap")]


def inv_curation_traces_to_queue(a: Artifacts) -> List[Finding]:
    """A verdict about a turn that does not exist is a verdict about nothing."""
    if not a.curation:
        return [Finding("curation traces to the queue", UNKNOWN, "no curation yet")]
    keys = {(str(r.get("ts", "")), str(r.get("session_id", ""))) for r in a.queue}
    orphans = [r for r in a.curation
               if (str(r.get("ts", "")), str(r.get("session_id", ""))) not in keys]
    folded = {(str(r.get("ts", "")), str(r.get("session_id", ""))) for r in a.curation}
    return [Finding(
        "curation traces to the queue", OK if not orphans else FAIL,
        f"{len(orphans)} verdicts reference a turn not in the queue" if orphans
        else f"{len(folded)} curated of {len(a.queue)} turns ({len(folded)/max(len(a.queue),1):.0%})",
        [str(r.get("ts", ""))[:19] for r in orphans[:3]])]


def inv_no_prompt_monoculture(a: Artifacts) -> List[Finding]:
    """One prompt on 14 different answers teaches the model nothing (2026-09-15).

    Found while adding the interview extractor: the synthetic-prompt rotation
    in `extract_user_explanations` has 5 templates across ~59 pairs, so
    collisions are structural rather than accidental.
    """
    if not a.pairs:
        return [Finding("no prompt monoculture", UNKNOWN, "no pairs")]
    counts = collections.Counter(
        str((r.get("messages") or [{}])[0].get("content", "")) for r in a.pairs)
    worst = counts.most_common(1)[0]
    over = {p: n for p, n in counts.items() if n > _MAX_PAIRS_PER_PROMPT}
    return [Finding(
        "no prompt monoculture", OK if not over else FAIL,
        f"{len(over)} prompt(s) used by >{_MAX_PAIRS_PER_PROMPT} pairs; worst {worst[1]}x"
        if over else f"worst prompt reuse is {worst[1]}x, under the {_MAX_PAIRS_PER_PROMPT} bar",
        [p[:80] for p in list(over)[:3]])]


def inv_ui_answers_keep_their_question(a: Artifacts) -> List[Finding]:
    """UI answers were paired with a synthetic prompt, discarding the real one.

    The interview extractor must win the global dedup against
    `extract_user_explanations`; if the registration order is ever flipped,
    every interview pair silently reverts to a generic prompt.
    """
    if not a.pairs or not a.conversations.is_dir():
        return [Finding("UI answers keep their question", UNKNOWN, "no conversations/")]
    ui_answers = set()
    for path in a.conversations.glob("*.jsonl"):
        for rec in _load(path):
            if rec.get("role") == "user":
                text = str(rec.get("content", "")).strip()
                if len(text) >= 60:
                    ui_answers.add(text)
    if not ui_answers:
        return [Finding("UI answers keep their question", UNKNOWN, "no UI answers on disk")]
    synthetic = []
    for r in a.pairs:
        msgs = r.get("messages") or []
        if len(msgs) < 2:
            continue
        target = str(msgs[1].get("content", "")).strip()
        if target in ui_answers and r.get("metadata", {}).get("form") != "interview":
            synthetic.append(str(msgs[0].get("content", ""))[:80])
    return [Finding(
        "UI answers keep their question", OK if not synthetic else FAIL,
        f"{len(synthetic)} UI answer(s) paired with a synthetic prompt" if synthetic
        else f"{len(ui_answers)} UI answers on disk, none flattened",
        synthetic[:3])]


def inv_records_are_well_formed(a: Artifacts) -> List[Finding]:
    """A record missing its identity cannot be joined, deduped or audited."""
    findings = []
    for label, rows, required in (
        ("observation_queue", a.queue, ("ts", "session_id", "user_text")),
        ("turn_curation", a.curation, ("ts", "session_id", "corpora", "domain")),
        ("sft_pairs", a.pairs, ("messages", "source_type")),
    ):
        if not rows:
            findings.append(Finding(f"well-formed: {label}", UNKNOWN, "absent"))
            continue
        bad = [r for r in rows if any(k not in r for k in required)]
        findings.append(Finding(
            f"well-formed: {label}", OK if not bad else FAIL,
            f"{len(bad)} of {len(rows)} missing a required field" if bad
            else f"{len(rows)} records, all carry {', '.join(required)}"))
    return findings


INVARIANTS: Tuple[Callable[[Artifacts], List[Finding]], ...] = (
    inv_no_exact_duplicates,   # includes inv_blend_duplication_is_explained
    inv_pair_targets_are_owner_prose,
    inv_heldout_is_isolated,
    inv_curation_traces_to_queue,
    inv_no_prompt_monoculture,
    inv_ui_answers_keep_their_question,
    inv_records_are_well_formed,
)


def run(root: Optional[Path] = None) -> List[Finding]:
    artifacts = Artifacts(root or _REPO_ROOT)
    findings: List[Finding] = []
    for fn in INVARIANTS:
        try:
            findings.extend(fn(artifacts))
        except Exception as exc:                        # noqa: BLE001
            findings.append(Finding(fn.__name__, UNKNOWN, f"check raised: {exc}"[:150]))
    return findings


def report(findings: Sequence[Finding], verbose: bool = False) -> int:
    print("=" * 78)
    print("  PIPELINE INVARIANTS — relationships no single module owns")
    print("=" * 78)
    for f in findings:
        mark = {OK: "  OK  ", FAIL: " FAIL ", UNKNOWN: " ???? "}[f.status]
        print(f"  [{mark}] {f.name:<42} {f.detail}")
        if verbose and f.examples:
            for ex in f.examples:
                print(f"            e.g. {ex!r}")
    failed = [f for f in findings if f.status == FAIL]
    unknown = [f for f in findings if f.status == UNKNOWN]
    print("-" * 78)
    print(f"  {len(findings) - len(failed) - len(unknown)} ok · {len(failed)} failed · "
          f"{len(unknown)} unmeasurable")
    if unknown:
        print("  UNMEASURABLE is not PASS — it means the artifact was missing or the")
        print("  check could not run, and it is reported rather than hidden.")
    print("=" * 78)
    return 1 if failed else 0


def _self_test() -> int:
    """Hermetic: builds artifacts in a temp dir, never reads the real ones."""
    import tempfile
    passed, failed = [], []

    def check(name, got, want):
        (passed if got == want else failed).append(
            name if got == want else f"{name}: got {got!r}, want {want!r}")

    def write(root, rel, rows):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    def status_of(findings, needle):
        return next(f.status for f in findings if needle in f.name)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write(root, "jarvis_data/training_corpus/engineer_corpus.jsonl",
              [{"text": "same"}, {"text": "same"}, {"text": "other"}])
        f = run(root)
        check("T1 within-corpus exact duplicates are caught",
              status_of(f, "no exact dupes: engineer_corpus"), FAIL)

        write(root, "jarvis_data/training_corpus/engineer_corpus.jsonl",
              [{"text": "a"}, {"text": "b"}])
        check("T2 distinct records pass",
              status_of(run(root), "no exact dupes: engineer_corpus"), OK)

        write(root, "jarvis_data/observation_queue.jsonl",
              [{"ts": "t1", "session_id": "s", "user_text": "hi"}])
        write(root, "jarvis_data/turn_curation.jsonl",
              [{"ts": "GHOST", "session_id": "s", "corpora": ["none"], "domain": "unknown"}])
        check("T3 a verdict about a nonexistent turn is caught",
              status_of(run(root), "curation traces"), FAIL)

        write(root, "jarvis_data/turn_curation.jsonl",
              [{"ts": "t1", "session_id": "s", "corpora": ["none"], "domain": "unknown"}])
        check("T4 a traceable verdict passes", status_of(run(root), "curation traces"), OK)

        pair = {"messages": [{"role": "user", "content": "Q?"},
                             {"role": "assistant", "content": "my own considered answer here"}],
                "source_type": "sft_personalization", "metadata": {}}
        write(root, "jarvis_data/training_corpus/sft_pairs.jsonl", [pair])
        write(root, "jarvis_data/training_corpus/sft_pairs_heldout.jsonl", [pair])
        check("T5 held-out overlapping train is caught",
              status_of(run(root), "held-out"), FAIL)

        write(root, "jarvis_data/training_corpus/sft_pairs_heldout.jsonl",
              [{"messages": [{"role": "user", "content": "Z?"},
                             {"role": "assistant", "content": "different answer entirely"}],
                "source_type": "sft_personalization", "metadata": {}}])
        check("T6 an isolated held-out slice passes", status_of(run(root), "held-out"), OK)

        write(root, "jarvis_data/training_corpus/sft_pairs.jsonl",
              [{"messages": [{"role": "user", "content": "same prompt"},
                             {"role": "assistant", "content": f"answer {i}"}],
                "source_type": "x", "metadata": {}} for i in range(_MAX_PAIRS_PER_PROMPT + 2)])
        check("T7 prompt monoculture is caught", status_of(run(root), "monoculture"), FAIL)

        write(root, "jarvis_data/observation_queue.jsonl", [{"ts": "t", "session_id": "s"}])
        check("T8 a record missing a required field is caught",
              status_of(run(root), "well-formed: observation_queue"), FAIL)

        empty = Path(tmp) / "nothing"
        empty.mkdir()
        f = run(empty)
        check("T9 a missing artifact is UNKNOWN, never a silent pass",
              all(x.status == UNKNOWN for x in f), True)
        check("T10 UNKNOWN does not make the run fail", report(f), 0)

        # T12/T13: blend duplication is judged against the source overlap, not
        # against zero — the first version of this check failed on intended
        # behaviour, which is how a check teaches people to ignore it.
        write(root, "jarvis_data/training_corpus/engineer_corpus.jsonl", [{"text": "shared"}])
        write(root, "jarvis_data/training_corpus/personalization_corpus.jsonl",
              [{"text": "shared"}])
        write(root, "jarvis_data/training_corpus/blended_corpus.jsonl",
              [{"text": "shared"}, {"text": "shared"}])
        check("T12 duplication explained by cross-corpus overlap passes",
              status_of(run(root), "blend duplication"), OK)
        write(root, "jarvis_data/training_corpus/blended_corpus.jsonl",
              [{"text": "shared"}, {"text": "shared"}, {"text": "new"}, {"text": "new"}])
        check("T13 duplication BEYOND the overlap fails",
              status_of(run(root), "blend duplication"), FAIL)

        write(root, "jarvis_data/training_corpus/engineer_corpus.jsonl",
              [{"text": "dup"}, {"text": "dup"}])
        check("T11 report() exits non-zero on a real failure", report(run(root)), 1)

    print("=" * 78)
    print("  check_pipeline self-test")
    print("=" * 78)
    for line in passed:
        print(f"  PASS  {line}")
    for line in failed:
        print(f"  FAIL  {line}")
    print("-" * 78)
    print(f"  {len(passed)} passed, {len(failed)} failed")
    print("=" * 78)
    return 1 if failed else 0


def main() -> int:
    p = argparse.ArgumentParser(description="Check invariants between corpus artifacts.")
    p.add_argument("--verbose", action="store_true", help="show example offenders")
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    if args.self_test:
        return _self_test()
    return report(run(), verbose=args.verbose)


if __name__ == "__main__":
    raise SystemExit(main())
