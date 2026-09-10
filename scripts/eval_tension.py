#!/usr/bin/env python3
"""
eval_tension.py — the ship gate for the tension detector.

LAYER: Tools (measurement harness — the detector lives in jarvis_core/agent/)

Run with:
    python3 scripts/eval_tension.py --offline    # validate the harness, no LLM, free
    python3 scripts/eval_tension.py              # score the real judge (costs ~$0.03)
    python3 scripts/eval_tension.py --show       # print the labelled cases and exit

=============================================================================
WHY THIS EXISTS, AND WHY IT RUNS BEFORE THE DETECTOR IS WIRED
=============================================================================

The detector this replaces shipped with 16 passing tests and produced three
useless sentences in 80 days. Its tests proved the code ran; nothing ever asked
whether the OUTPUT WAS WORTH READING. That is the mistake being avoided here, so
this harness is a precondition for wiring tension.py to the live feed, not a
follow-up to it.

THE GROUND TRUTH IS ALREADY IN THE REPO. This project has spent months recording
its own reversals in prose, which makes a labelled set possible without inventing
anything. The cases below are real KB entries, and the load-bearing ones were
each verified by reading both sides.

THE DISCRIMINATION THAT MATTERS. POS_GOLD and NEG_NEW_GROUNDS have the SAME shape
— a later decision reversing an earlier one — and differ only in whether the
grounds were already considered and rejected:

    POS  KB 461 vs KB 429: 429 ruled that specialist training does NOT gate on
         personal-corpus availability ("two separate moats", "needs zero personal
         data"). 461 then re-weighted per-specialist priority BY "EVIDENCED
         personal-data volume", offering no new reason. KB 463 confirms it, weeks
         later, by hand: "directly contradicted KB 429". THE DETECTOR SHOULD HAVE
         CAUGHT THIS.

    NEG  KB 518 vs KB 509: 509 records the client-IP rule being lifted on privacy
         grounds and reinstated — privacy was tried and rejected. 518 reverses it
         AGAIN, but explicitly on different grounds (artifact separation,
         file-bloat), and says so: "is therefore NOT a re-litigation of the
         settled question". Changing your mind for a NEW reason is thinking.
         SURFACING THIS WOULD BE NAGGING.

A detector that cannot separate those two is not shippable at any accuracy,
because the second kind of error is the one that teaches the user to ignore the
channel. So the gate weighs negatives at least as heavily as positives.

HONEST LIMITATION, stated rather than padded around: the positive set is SMALL.
Only a handful of historical reversals name their prior precisely enough to label
without guessing, and inventing synthetic positives would measure the harness
instead of the detector. Treat a pass here as "not obviously broken", not as
"validated" — the real evidence is the hand-inspected replay described in the
plan's verification section.

=============================================================================
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "js-development"))

from jarvis_core.agent.tension import (  # noqa: E402
    NONE, REVERSES, PriorRecord, TensionCandidate, TensionJudge)
from jarvis_core.config import KB_PATH  # noqa: E402


@dataclass(frozen=True)
class Case:
    """One labelled example. `expect_surface` is the only thing scored."""
    name: str
    candidate_id: int
    prior_ids: Tuple[int, ...]      # the first is the intended match, rest distract
    expect_surface: bool
    expect_relation: str
    why: str


CASES: Tuple[Case, ...] = (
    Case(
        name="POS_GOLD",
        candidate_id=461, prior_ids=(429, 509, 489),
        expect_surface=True, expect_relation=REVERSES,
        why="461 re-weighted specialist priority BY personal-data volume; 429 had "
            "already ruled training does NOT gate on it, and 461 gives no new "
            "reason. KB 463 confirms the contradiction by hand weeks later."),
    Case(
        name="NEG_NEW_GROUNDS",
        candidate_id=518, prior_ids=(509, 489, 429),
        expect_surface=False, expect_relation=NONE,
        why="518 reverses the client-IP rule that 509 records as already lifted "
            "and reinstated — but on explicitly NEW grounds, and it says so. "
            "Legitimate evolution. Surfacing it would be nagging."),
    Case(
        name="NEG_POSTMORTEM",
        candidate_id=463, prior_ids=(429, 461, 509),
        expect_surface=False, expect_relation=NONE,
        why="463 IS the hand-written postmortem that names the 461/429 clash. The "
            "user already knows; re-raising what they just wrote down is noise."),
    Case(
        name="NEG_TOPICAL_CORPUS",
        candidate_id=497, prior_ids=(494, 489),
        expect_surface=False, expect_relation=NONE,
        why="497 and 494 are both corpus/client-work housekeeping on adjacent days. "
            "Same subject, same vocabulary, no clash. This is the commonest false "
            "positive shape: similarity mistaken for tension."),
    Case(
        name="NEG_TOPICAL_DOCROT",
        candidate_id=529, prior_ids=(527, 521),
        expect_surface=False, expect_relation=NONE,
        why="529 (a privacy guarantee in prose) and 527 (prose status headers rot) "
            "are the SAME failure family and cite each other approvingly. Agreement "
            "between two entries must never read as contradiction."),
)


def load_entries(kb_path: Optional[Path] = None) -> Dict[int, dict]:
    path = Path(kb_path) if kb_path else Path(KB_PATH)
    out: Dict[int, dict] = {}
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry.get("id"), int):
                out[entry["id"]] = entry
    return out


def build_case(case: Case, entries: Dict[int, dict]
               ) -> Optional[Tuple[TensionCandidate, List[PriorRecord]]]:
    """Materialise a case, or None when an id is missing from this KB."""
    cand = entries.get(case.candidate_id)
    if cand is None:
        return None
    priors: List[PriorRecord] = []
    for pid in case.prior_ids:
        p = entries.get(pid)
        if p is None:
            continue
        priors.append(PriorRecord(
            entry_id=str(pid), entry_type=str(p.get("type", "")),
            ts=str(p.get("timestamp", "")), text=str(p.get("content", ""))))
    if not priors:
        return None
    return TensionCandidate(
        source="kb", ref=str(case.candidate_id),
        ts=str(cand.get("timestamp", "")), text=str(cand.get("content", ""))), priors


async def run(judge: TensionJudge, entries: Dict[int, dict], floor: float
              ) -> Tuple[int, int, List[str]]:
    """(correct, total, report lines)."""
    correct = 0
    total = 0
    lines: List[str] = []
    for case in CASES:
        built = build_case(case, entries)
        if built is None:
            lines.append(f"  SKIP  {case.name:<20} (an id is absent from this KB)")
            continue
        candidate, priors = built
        finding = await judge.judge(candidate, priors)
        surfaced = finding.is_real and finding.confidence >= floor
        ok = surfaced == case.expect_surface
        total += 1
        correct += int(ok)
        verdict = "PASS" if ok else "FAIL"
        got = (f"{finding.relation}"
               f"{'' if finding.relation == NONE else f'/{finding.prior_ref}'}"
               f" conf={finding.confidence:.2f}"
               f" grounds_rejected={finding.grounds_already_rejected}")
        lines.append(f"  {verdict}  {case.name:<20} "
                     f"want surface={str(case.expect_surface):<5} got {got}")
        if not ok:
            lines.append(f"          why this case exists: {case.why}")
            if finding.grounds:
                lines.append(f"          judge said: {finding.grounds[0]}")
        elif surfaced:
            lines.append(f"          would say: {finding.surface_line()[:150]}")
    return correct, total, lines


def _offline_judge() -> TensionJudge:
    """A scripted judge that answers each case correctly — validates the HARNESS.

    It keys off text the candidate actually contains, so it cannot accidentally
    pass by returning a constant.
    """
    def call(messages: List[Dict[str, str]]) -> str:
        body = messages[-1]["content"]
        # Read ONLY the NOW block. Matching the whole prompt is wrong and this
        # double got it wrong first time: NEG_POSTMORTEM carries KB 461 as a
        # PRIOR, so a naive substring search found 461's text and returned
        # REVERSES for the postmortem that merely cites it. That is exactly the
        # confusion the real judge is instructed to avoid, so the stand-in must
        # not be allowed to make it accidentally.
        start = body.find("--- NOW (untrusted) ---")
        end = body.find("--- END NOW ---")
        now_block = body[start:end] if start != -1 and end != -1 else ""
        if "13-model resource-allocation framework" in now_block:
            return ('{"relation":"REVERSES","prior_ref":"429","which":"priority '
                    'gated on personal-data volume","grounds_already_rejected":true,'
                    '"confidence":0.85}')
        return '{"relation":"NONE","prior_ref":"","which":"","confidence":0.0}'
    return TensionJudge(call)


def main() -> int:
    p = argparse.ArgumentParser(description="Score the tension detector against labelled history.")
    p.add_argument("--offline", action="store_true",
                   help="validate the harness with a scripted judge; no LLM, no cost")
    p.add_argument("--show", action="store_true", help="print the cases and exit")
    p.add_argument("--floor", type=float, default=0.55)
    p.add_argument("--model", default=None, help="override the judge model")
    args = p.parse_args()

    if args.show:
        for case in CASES:
            tag = "SURFACE" if case.expect_surface else "SILENT "
            print(f"  [{tag}] {case.name:<20} KB {case.candidate_id} "
                  f"vs {list(case.prior_ids)}")
            print(f"            {case.why}")
        return 0

    entries = load_entries()
    print("=" * 74)
    print(f"  tension eval — {len(CASES)} labelled cases from this project's own history")
    print("=" * 74)

    if args.offline:
        judge = _offline_judge()
        print("  judge: SCRIPTED (harness validation only — proves nothing about the LLM)")
    else:
        from jarvis_core.brain.llm_client import build_llm_call
        client = build_llm_call(budget_usd=None)
        if hasattr(client, "pick_free_model") and not getattr(client, "model", ""):
            asyncio.get_event_loop().run_until_complete(client.pick_free_model())
        judge = TensionJudge(client)
        print(f"  judge: {getattr(client, 'model', '<auto>')}")
    print(f"  surface floor: {args.floor}")
    print()

    correct, total, lines = asyncio.get_event_loop().run_until_complete(
        run(judge, entries, args.floor))
    for line in lines:
        print(line)

    positives = [c for c in CASES if c.expect_surface]
    negatives = [c for c in CASES if not c.expect_surface]
    print("-" * 74)
    print(f"  {correct}/{total} correct "
          f"({len(positives)} positive case(s), {len(negatives)} negative)")
    if correct < total:
        print()
        print("  NOT SHIPPABLE YET. A failed NEGATIVE is the serious one: it means the")
        print("  detector would raise something the user already settled, and that is")
        print("  what trains them to ignore the channel. Fix the judge prompt in")
        print("  agent/tension.py — do NOT lower the floor to make this pass.")
    return 0 if correct == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
