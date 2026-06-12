"""
confidence.py — Confidence Gate v1 (Stage 4.0.3: the Metacognitive pillar).

LAYER: Brain (Cognitive Control Loop — epistemic control)

Import with:
    from jarvis_core.brain.confidence import ConfidenceGate, ConfidenceReport

=============================================================================
THE BIG PICTURE
=============================================================================

"Are you sure about that?" must produce a NUMBER with GROUNDS, not a vibe.
This is the Metacognitive pillar of the Cognitive Control Loop (KB L107) and
the runtime twin of the conduct lesson in JARVIS_METACOGNITION_PROMPT:
distinguish verified facts from hypotheses, fail closed on uncertainty.

v1 is deterministic and ₹0 — NO LLM judge (that layer arrives in 4.5 with
fail-closed contradiction judging). The gate measures how well a DRAFT answer
is GROUNDED in the EVIDENCE the session actually gathered (tool results,
knowledge-base hits):

    score = 0.5 * semantic   (max cosine: draft vs each evidence chunk,
                              injected EmbedFn — same protocol as
                              agent/domain_classifier.py)
          + 0.5 * lexical    (coverage: fraction of the draft's content words
                              that appear anywhere in the evidence)

Fail-closed by construction: no evidence, or an empty draft, is ESCALATE —
an ungrounded answer is never silently CONFIDENT.

=============================================================================
THE FLOW
=============================================================================

STEP 1: grade(draft, evidence): sanitize inputs; empty either way -> ESCALATE.
        |
STEP 2: lexical coverage (pure stdlib) + semantic max-cosine (lazy embedder,
        injected for tests).
        |
STEP 3: blend -> verdict by thresholds (>=0.55 CONFIDENT, >=0.30 UNCERTAIN,
        else ESCALATE) -> ConfidenceReport(score, verdict, grounds).

=============================================================================
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # standalone-run safety

from jarvis_core.agent.domain_classifier import (
    EmbedFn, _build_default_embed_fn, _dot,
)

_DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_EVIDENCE_CHUNK_CHARS = 600     # embed heads, not megabytes of tool output
_MIN_WORD_LEN = 3               # "content words" — drop is/a/of noise

VERDICT_CONFIDENT = "CONFIDENT"
VERDICT_UNCERTAIN = "UNCERTAIN"
VERDICT_ESCALATE = "ESCALATE"


# =============================================================================
# Part 1: CONTRACT (frozen)
# =============================================================================

@dataclass(frozen=True)
class ConfidenceReport:
    """The gate's output: a score in [0,1], a verdict, and WHY."""
    score: float
    verdict: str
    grounds: Tuple[str, ...]


# =============================================================================
# Part 2: THE GATE
# =============================================================================

def _content_words(text: str) -> set:
    return {w for w in re.findall(r"\w+", text.lower()) if len(w) >= _MIN_WORD_LEN}


class ConfidenceGate:
    """Grades a draft answer against session evidence. Deterministic, ₹0."""

    def __init__(
        self,
        embed_fn: Optional[EmbedFn] = None,
        confident_at: float = 0.55,
        uncertain_at: float = 0.30,
        model_name: str = _DEFAULT_MODEL,
    ) -> None:
        if not (0.0 <= uncertain_at <= confident_at <= 1.0):
            raise ValueError("thresholds must satisfy 0 <= uncertain_at <= confident_at <= 1")
        self._embed_fn = embed_fn
        self._confident_at = confident_at
        self._uncertain_at = uncertain_at
        self._model_name = model_name

    def _embed(self, texts: List[str]) -> List[List[float]]:
        if self._embed_fn is None:
            self._embed_fn = _build_default_embed_fn(self._model_name)  # lazy, once
        return self._embed_fn(texts)

    def grade(self, draft: str, evidence: List[str]) -> ConfidenceReport:
        """
        Grade one draft against the evidence the session gathered.

        EXECUTION FLOW:
        1. Sanitize: keep non-empty evidence strings; empty draft/evidence -> ESCALATE.
        2. Lexical coverage of the draft's content words by the evidence union.
        3. Semantic max-cosine of the draft vs each evidence chunk head.
        4. Blend 50/50 -> threshold verdict -> report with human-readable grounds.

        Returns:
            ConfidenceReport — ESCALATE is the floor, never an exception.
        """
        draft = (draft or "").strip()
        chunks = [e.strip()[:_EVIDENCE_CHUNK_CHARS] for e in (evidence or [])
                  if e and e.strip()]
        if not draft:
            return ConfidenceReport(0.0, VERDICT_ESCALATE, ("empty draft — nothing to grade",))
        if not chunks:
            return ConfidenceReport(
                0.0, VERDICT_ESCALATE,
                ("no evidence gathered this session (no tool results / KB hits) — "
                 "the draft is ungrounded by construction",))

        draft_words = _content_words(draft)
        evidence_words = set().union(*(_content_words(c) for c in chunks))
        coverage = (len(draft_words & evidence_words) / len(draft_words)
                    if draft_words else 0.0)

        vecs = self._embed([draft[:_EVIDENCE_CHUNK_CHARS]] + chunks)
        draft_vec, chunk_vecs = vecs[0], vecs[1:]
        sims = [_dot(draft_vec, cv) for cv in chunk_vecs]
        best_i = max(range(len(sims)), key=lambda i: sims[i])
        max_cos = max(0.0, min(1.0, sims[best_i]))

        score = max(0.0, min(1.0, 0.5 * max_cos + 0.5 * coverage))
        if score >= self._confident_at:
            verdict = VERDICT_CONFIDENT
        elif score >= self._uncertain_at:
            verdict = VERDICT_UNCERTAIN
        else:
            verdict = VERDICT_ESCALATE

        grounds = (
            f"semantic: best-evidence cosine {max_cos:.2f}",
            f"lexical: {coverage:.0%} of draft content words found in evidence",
            f"evidence: {len(chunks)} chunk(s); best match: "
            f"\"{chunks[best_i][:80]}{'…' if len(chunks[best_i]) > 80 else ''}\"",
        )
        return ConfidenceReport(round(score, 4), verdict, grounds)


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS (offline — scripted embed_fn, no downloads)
# =============================================================================

def _run_self_test() -> None:
    print("=" * 70)
    print("  confidence.py -- Smoke Tests")
    print("=" * 70)
    passed = 0
    failed: List[str] = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        nonlocal passed
        if cond:
            passed += 1
        else:
            failed.append(f"FAIL: {name}" + (f" ({hint})" if hint else ""))

    # Scripted embedder: vector by keyword family. Unit vectors -> dot == cosine.
    def scripted_embed(texts: List[str]) -> List[List[float]]:
        out: List[List[float]] = []
        for t in texts:
            tl = t.lower()
            if "spark" in tl:
                out.append([1.0, 0.0, 0.0])
            elif "portfolio" in tl:
                out.append([0.0, 1.0, 0.0])
            else:
                out.append([0.0, 0.0, 1.0])
        return out

    gate = ConfidenceGate(embed_fn=scripted_embed)

    # T1: grounded draft (same family + shared words) -> CONFIDENT
    ev = ["spark shuffle partitions default to 200 and AQE coalesces them"]
    r1 = gate.grade("spark shuffle partitions default to 200; AQE coalesces small ones", ev)
    check("T1 grounded -> CONFIDENT", r1.verdict == VERDICT_CONFIDENT, str(r1))
    check("T1b score high", r1.score >= 0.8, str(r1.score))

    # T2: fabricated draft (different family, no shared content words) -> ESCALATE
    r2 = gate.grade("the moon base launches tomorrow at dawn", ev)
    check("T2 fabricated -> ESCALATE", r2.verdict == VERDICT_ESCALATE, str(r2))

    # T3: empty evidence -> ESCALATE, fail-closed wording
    r3 = gate.grade("a perfectly fine answer", [])
    check("T3 no evidence -> ESCALATE", r3.verdict == VERDICT_ESCALATE
          and "ungrounded" in r3.grounds[0], str(r3.grounds))

    # T4: empty draft -> ESCALATE
    r4 = gate.grade("   ", ev)
    check("T4 empty draft -> ESCALATE", r4.verdict == VERDICT_ESCALATE)

    # T5: whitespace-only evidence entries dropped (== no evidence)
    r5 = gate.grade("answer", ["  ", ""])
    check("T5 blank evidence dropped", r5.verdict == VERDICT_ESCALATE)

    # T6: middle band -> UNCERTAIN (engineered: cos=0.8, zero word overlap
    # -> score exactly 0.40)
    def mid_embed(texts: List[str]) -> List[List[float]]:
        return [[1.0, 0.0, 0.0]] + [[0.8, 0.6, 0.0]] * (len(texts) - 1)
    r6 = ConfidenceGate(embed_fn=mid_embed).grade("alpha beta gamma", ["delta epsilon zeta"])
    check("T6 partial grounding -> UNCERTAIN", r6.verdict == VERDICT_UNCERTAIN,
          f"{r6.score} {r6.verdict}")

    # T7: grounds are human-readable and carry the best-match snippet
    check("T7 grounds carry semantic + lexical + snippet",
          len(r1.grounds) == 3 and "cosine" in r1.grounds[0]
          and "%" in r1.grounds[1] and "best match" in r1.grounds[2], str(r1.grounds))

    # T8: threshold boundaries honored (engineered score 0.5417: 1 of 12 draft
    # words covered, cos=1.0 -> below default 0.55, above custom 0.50)
    g8 = ConfidenceGate(embed_fn=scripted_embed, confident_at=0.5, uncertain_at=0.5)
    noisy = "spark zzz qqq www eee rrr ttt yyy uuu iii ooo ppp"
    r8 = gate.grade(noisy, ["spark internals deep dive"])
    # exact-boundary semantics: score >= confident_at is CONFIDENT
    r8b = g8.grade(noisy, ["spark internals deep dive"])
    check("T8 boundary: >= confident_at flips verdict",
          r8.verdict != VERDICT_CONFIDENT and r8b.verdict == VERDICT_CONFIDENT,
          f"{r8.score}/{r8.verdict} vs {r8b.score}/{r8b.verdict}")

    # T9: invalid thresholds rejected loudly
    try:
        ConfidenceGate(confident_at=0.2, uncertain_at=0.5)
        check("T9 invalid thresholds raise", False)
    except ValueError:
        check("T9 invalid thresholds raise", True)

    # T10: long evidence chunks are head-truncated before embedding (no crash,
    # snippet bounded)
    r10 = gate.grade("spark stuff", ["spark " + "y" * 5000])
    check("T10 long evidence handled", r10.score > 0 and len(r10.grounds[2]) < 200)

    # T11: score clamped to [0,1] even with a pathological embedder
    def weird_embed(texts: List[str]) -> List[List[float]]:
        return [[2.0, 0.0, 0.0] for _ in texts]  # non-unit on purpose
    r11 = ConfidenceGate(embed_fn=weird_embed).grade("spark spark", ["spark spark"])
    check("T11 score clamped", 0.0 <= r11.score <= 1.0, str(r11.score))

    total = passed + len(failed)
    print(f"\n  Passed: {passed}/{total}")
    if failed:
        for f_ in failed:
            print(f"  {f_}")
        print("=" * 70)
        raise SystemExit(1)
    print(f"  All {total} confidence smoke tests passed.")
    print("=" * 70)


if __name__ == "__main__":
    _run_self_test()
