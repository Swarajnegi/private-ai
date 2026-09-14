#!/usr/bin/env python3
"""
provenance.py — did the user WRITE this turn, or paste it back from somewhere?

LAYER: Agent (capture stream)

Run with:
    python3 -m jarvis_core.agent.provenance            # smoke tests
    python3 -m jarvis_core.agent.provenance --report   # score the live queue

=============================================================================
THE BIG PICTURE
=============================================================================

`specialists/text_hygiene.py` decides whether a turn LOOKS like the owner's
prose. It answers that well for machine text, because a shell prompt has a
grammar. It cannot answer it at all for one case:

    the user pastes another agent's reply back into the chat

That text is fluent English prose with ordinary punctuation and a plausible
first-person rate. Grammar has nothing to grip. Measured 2026-09-14: a pasted
Codex status report scored 2.26 first-person tokens per 500 characters, while
the weakest genuinely-good row in the corpus scored 1.24 — the contamination
sat INSIDE the good range, so no threshold could separate them.

=============================================================================
WHY THIS IS NOT A FLAG SET AT CAPTURE TIME
=============================================================================

The obvious design is a `pasted: true` field written by the capture hook. It
was checked first and it does not work: **Claude Code's transcript does not
record paste events.** Pasted text is inlined into the user message exactly as
if it had been typed — a grep across every transcript in
`~/.claude/projects/` for paste markers returns nothing. The host simply does
not know, so neither can a hook reading the host.

The signal that DOES exist is in the corpus itself. When the user pastes an
agent's output, that text is usually already present as some earlier turn's
`assistant_summary` — JARVIS captured it when it was produced. So provenance
is recoverable by cross-referencing the capture stream against its own past:

    a user turn that repeats an EARLIER assistant turn was not composed now

Three properties make this better than the flag that cannot be built:

  1. It works RETROACTIVELY over all existing records, where a capture-time
     field would only ever describe turns captured after it shipped.
  2. It is HOST-INDEPENDENT — Codex and Antigravity turns arrive through
     their own adapters into the same queue and are scored the same way.
  3. It is grounded in a FACT (this text existed before) rather than in a
     judgement about style.

=============================================================================
THE FLOW
=============================================================================

STEP 1: Shingle every turn — overlapping 8-word windows, hashed. Word-level
        shingles survive the reformatting a paste usually picks up (list
        markers re-numbered, whitespace collapsed) where a substring match
        would not.
        |
STEP 2: Walk the queue in TIMESTAMP ORDER, scoring each user turn against
        only the assistant shingles seen BEFORE it, then adding that turn's
        own assistant shingles to the index.

        DIRECTION IS THE WHOLE MEASUREMENT. Scoring against all turns instead
        of earlier ones reports 100% echo for the user's own repeated `--ask`
        question, because the answer quotes the question back. Six such
        records sat at the top of the first run of this and they are not
        pastes at all.
        |
STEP 3: Return a fraction per turn. The caller picks the threshold; 0.30 is
        this corpus's measured precision knee (see `ECHO_CEILING`).
=============================================================================
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

__all__ = ["EchoIndex", "echo_fractions", "ECHO_CEILING", "SHINGLE_WORDS"]

SHINGLE_WORDS = 8

# MEASURED, not chosen. Against the 990-record queue on 2026-09-14, of the
# turns `text_hygiene` already accepts as owner prose:
#
#   echo > 0.30  ->  2 flagged, 2 genuinely pasted   (precision 2/2)
#   echo > 0.15  ->  7 flagged, 4 genuinely pasted   (precision 4/7)
#
# The 0.15-0.30 band is not noise, it is a real phenomenon: a user answering a
# numbered list point by point legitimately reuses the assistant's vocabulary.
# Three such turns are among the best voice material in the corpus. With
# personalization pairs already scarce, trading three good pairs to catch two
# more bad ones is the wrong trade, so the ceiling sits at the knee.
ECHO_CEILING = 0.30

_WORD = re.compile(r"\w+")
_MIN_SHINGLES = 10          # below this a fraction is noise, so it scores 0.0


def _shingles(text: str) -> frozenset:
    words = _WORD.findall(text.lower())
    if len(words) < SHINGLE_WORDS:
        return frozenset()
    return frozenset(
        hash(tuple(words[i:i + SHINGLE_WORDS]))
        for i in range(len(words) - SHINGLE_WORDS + 1)
    )


class EchoIndex:
    """Streaming echo scorer. Feed turns in timestamp order.

    Deliberately stateful and order-dependent rather than a pure function over
    the whole queue: the capture stream is append-only, so a live caller can
    score one new turn against everything already seen without re-reading the
    corpus.
    """

    def __init__(self) -> None:
        self._seen: set = set()

    def score(self, user_text: str) -> float:
        """Fraction of this turn's shingles already seen in an earlier reply."""
        shingles = _shingles(user_text)
        if len(shingles) < _MIN_SHINGLES:
            return 0.0
        return len(shingles & self._seen) / len(shingles)

    def observe(self, assistant_text: str) -> None:
        """Record an assistant reply so later turns can be scored against it."""
        self._seen |= _shingles(assistant_text)

    def add_turn(self, user_text: str, assistant_text: str) -> float:
        """Score the user side, THEN index the assistant side. Order matters."""
        fraction = self.score(user_text)
        self.observe(assistant_text)
        return fraction


def echo_fractions(records: Iterable[Dict[str, Any]]) -> List[float]:
    """One echo fraction per record, in the order given.

    The caller is responsible for timestamp ordering; `score_queue` does it.
    """
    index = EchoIndex()
    return [
        index.add_turn(str(r.get("user_text", "")), str(r.get("assistant_summary", "")))
        for r in records
    ]


def score_queue(queue_path: Optional[Path] = None) -> Dict[Tuple[str, str], float]:
    """{(ts, session_id): echo_fraction} for the whole capture queue.

    Keyed on (ts, session_id) because that is the pair every other projection
    over this queue already uses as its identity — see capture.py's note on
    why a backfilled turn must carry its OWN timestamp.
    """
    path = queue_path
    if path is None:
        from jarvis_core.config import DATA_ROOT
        path = Path(DATA_ROOT) / "observation_queue.jsonl"
    records: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except (OSError, FileNotFoundError):
        return {}
    records.sort(key=lambda r: str(r.get("ts", "")))
    fractions = echo_fractions(records)
    return {
        (str(r.get("ts", "")), str(r.get("session_id", ""))): f
        for r, f in zip(records, fractions)
    }


# =============================================================================
# Smoke tests
# =============================================================================

def _smoke() -> int:
    passed: List[str] = []
    failed: List[str] = []

    def check(name: str, got, want) -> None:
        (passed if got == want else failed).append(
            name if got == want else f"{name}: got {got!r}, want {want!r}")

    reply = ("The hearth is a single always-on process that owns the mutable state "
             "and the clock, and every other surface talks to it as a socket client "
             "rather than owning state of its own.")

    idx = EchoIndex()
    check("T1 nothing echoes an empty index", idx.score(reply) == 0.0, True)

    idx.observe(reply)
    check("T2 verbatim paste scores 1.0", idx.score(reply), 1.0)
    check("T3 unrelated prose scores 0.0",
          idx.score("I have been thinking about my own reasons for building this "
                    "at all, and the honest answer is that I want it to know me."), 0.0)

    # A paste usually picks up reformatting; word shingles must survive it.
    reformatted = ("1. The hearth is a single always-on process that owns the mutable "
                   "state and the clock, and every other surface talks to it as a "
                   "socket client rather than owning state of its own.")
    check("T4 reformatted paste still scores high", idx.score(reformatted) > 0.8, True)

    # Partial quote plus the user's own reaction: the real mixed-turn shape.
    mixed = ("The hearth is a single always-on process that owns the mutable state "
             "and the clock -- so why did it die on me twice last week? I want to "
             "know what actually restarts it, because I am tired of checking.")
    frac = idx.score(mixed)
    check("T5 mixed turn lands between the extremes", 0.0 < frac < 0.8, True)

    # DIRECTION. This is the bug that made the first version useless.
    ordered = EchoIndex()
    question = ("Remind me what we decided about deploying Kimi K2.6 on RunPod this "
                "stage, and whether we approved the cold-wake economics at the time.")
    first = ordered.add_turn(question, f"You asked: {question} The answer is cold-wake only.")
    check("T6 a fresh question does not echo", first, 0.0)
    second = ordered.add_turn(question, "Same answer as before.")
    check("T7 but the SAME question re-asked echoes its own prior answer",
          second > 0.9, True)

    check("T8 too-short text scores 0.0 rather than a noisy fraction",
          EchoIndex().score("way too short"), 0.0)

    idx2 = EchoIndex()
    f2 = idx2.add_turn("I am writing my own first turn here about my own project.", reply)
    check("T9 add_turn scores BEFORE indexing", f2, 0.0)
    check("T10 ...and indexes after", idx2.score(reply), 1.0)

    check("T11 echo_fractions preserves order",
          echo_fractions([
              {"user_text": "My own opening thought about my work.", "assistant_summary": reply},
              {"user_text": reply, "assistant_summary": ""},
          ]), [0.0, 1.0])

    check("T12 ceiling is the measured knee", ECHO_CEILING, 0.30)

    print("=" * 70)
    print("  provenance smoke tests")
    print("=" * 70)
    for line in passed:
        print(f"  PASS  {line}")
    for line in failed:
        print(f"  FAIL  {line}")
    print("-" * 70)
    print(f"  {len(passed)} passed, {len(failed)} failed")
    print("=" * 70)
    return 1 if failed else 0


def _report() -> int:
    scores = score_queue()
    if not scores:
        print("no observation queue found")
        return 1
    flagged = sorted((f, k) for k, f in scores.items() if f > ECHO_CEILING)
    print(f"{len(scores)} turns scored; {len(flagged)} above ECHO_CEILING={ECHO_CEILING}")
    for f, (ts, _sid) in sorted(flagged, reverse=True)[:20]:
        print(f"  {f:6.1%}  {ts[:19]}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Echo-based provenance for captured turns.")
    parser.add_argument("--report", action="store_true", help="score the live queue")
    args = parser.parse_args()
    raise SystemExit(_report() if args.report else _smoke())
