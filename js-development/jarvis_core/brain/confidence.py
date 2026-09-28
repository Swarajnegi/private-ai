"""
confidence.py — Confidence Gate v1 (Stage 4.0.3: the Metacognitive pillar).

LAYER: Brain (Cognitive Control Loop — epistemic control)

Import with:
    from jarvis_core.brain.confidence import (
        ConfidenceGate, ConfidenceReport, detect_divergence, DivergenceReport,
    )

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

Stage 4.5.1 adds a SECOND, orthogonal gate: `detect_divergence` — given N
SourcedAnswers to the SAME question (Stage 4.4's fan-out), does deterministic,
₹0 triage on whether they actually agree. Two independent signals, either one
trips it:
  - semantic: min pairwise cosine across answers (injected EmbedFn) below a
    threshold — the answers are substantively about different things.
  - numeric: a shared-topic pair (>=2 common content words) that states a
    DIFFERENT number for the SAME unit — "220 ohms" vs "330 ohms" is a real
    factual conflict no cosine check reliably catches (embeddings blur exact
    digits; two numbers in the same sentence shape read as near-identical).
This is DELIBERATELY NOT a logical-contradiction detector — "yes" vs "no" on
the same claim can embed as near-identical (same topic, negation blurred) and
carries no extractable number. That class is reasoning.py's ContradictionJudge
(4.5.2) — an LLM asked directly "do these actually contradict?" — which
`detect_divergence` feeds but does not replace. `divergence_eval.jsonl` is the
frozen fixture proving the honest scope: 4/6 conflicts are numeric (exact,
same-topic), 2/6 are genuinely different-substance answers (semantic-only);
0/6 rely on catching a bare logical inversion, because THIS gate structurally
cannot.

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
        |
STEP 4 (4.5.1, separate entry point): detect_divergence(answers): <2 usable
        -> not measurable, diverged=False. Else pairwise cosine (min across
        all pairs) + numeric-claim diff (shared-topic gate + unit-normalized
        number compare) -> diverged if EITHER signal trips.

=============================================================================
"""

from __future__ import annotations

import json
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
# MiniLM reads 256 tokens and silently drops the rest, so a text is embedded as
# overlapping windows that together cover ALL of it (~600 chars ≈ 150 tokens,
# safely under the model's own cut). Grading matches each draft window to its
# best evidence window; nothing past a head is ever invisible to the gate.
_WINDOW_CHARS = 600
_WINDOW_OVERLAP = 150
_MIN_WORD_LEN = 3               # "content words" — drop is/a/of noise

VERDICT_CONFIDENT = "CONFIDENT"
VERDICT_UNCERTAIN = "UNCERTAIN"
VERDICT_ESCALATE = "ESCALATE"


# =============================================================================
# Part 1: CONTRACT (frozen)
# =============================================================================

@dataclass(frozen=True)
class ConfidenceReport:
    """The gate's output: a score in [0,1], a verdict, and WHY.

    `had_evidence` distinguishes the TWO opposite reasons grade() returns
    ESCALATE: False == no evidence was gathered at all (a pure-reasoning answer
    is ungrounded *by construction*), True == evidence WAS gathered but the
    draft scored against it (a low score here is the fabrication / contradicts-
    the-facts signal). Downstream fusion must not conflate them."""
    score: float
    verdict: str
    grounds: Tuple[str, ...]
    had_evidence: bool = False


# =============================================================================
# Part 2: THE GATE
# =============================================================================

def _content_words(text: str) -> set:
    return {w for w in re.findall(r"\w+", text.lower()) if len(w) >= _MIN_WORD_LEN}


def _windows(text: str) -> List[str]:
    """Overlapping windows that together cover every character of `text`."""
    if len(text) <= _WINDOW_CHARS:
        return [text]
    step = _WINDOW_CHARS - _WINDOW_OVERLAP
    return [text[i:i + _WINDOW_CHARS] for i in range(0, len(text) - _WINDOW_OVERLAP, step)]


def _mean_unit(vecs: List[List[float]]) -> List[float]:
    """One vector for a whole multi-window text: the renormalized mean."""
    if len(vecs) == 1:
        return list(vecs[0])
    dim = len(vecs[0])
    mean = [sum(v[k] for v in vecs) / len(vecs) for k in range(dim)]
    norm = sum(x * x for x in mean) ** 0.5
    return [x / norm for x in mean] if norm else mean


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
        2. Lexical coverage of the draft's content words by the WHOLE evidence.
        3. Semantic: every draft window's best cosine against every evidence
           window (windows cover all of both), averaged over draft windows.
        4. Blend 50/50 -> threshold verdict -> report with human-readable grounds.

        Returns:
            ConfidenceReport — ESCALATE is the floor, never an exception.
        """
        draft = (draft or "").strip()
        chunks = [e.strip() for e in (evidence or []) if e and e.strip()]
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

        draft_windows = _windows(draft)
        ev_windows = [(ci, w) for ci, c in enumerate(chunks) for w in _windows(c)]
        vecs = self._embed(draft_windows + [w for _ci, w in ev_windows])
        draft_vecs, ev_vecs = vecs[:len(draft_windows)], vecs[len(draft_windows):]
        per_window_best: List[float] = []
        best_sim, best_j = -2.0, 0
        for dv in draft_vecs:
            sims = [_dot(dv, ev) for ev in ev_vecs]
            j = max(range(len(sims)), key=lambda k: sims[k])
            per_window_best.append(sims[j])
            if sims[j] > best_sim:
                best_sim, best_j = sims[j], j
        max_cos = max(0.0, min(1.0, sum(per_window_best) / len(per_window_best)))
        best_chunk, best_window = ev_windows[best_j]

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
            f"evidence: {len(chunks)} chunk(s); best match in chunk {best_chunk + 1} "
            f"({len(chunks[best_chunk]):,} chars): \"{best_window}\"",
        )
        return ConfidenceReport(round(score, 4), verdict, grounds, had_evidence=True)


# =============================================================================
# Part 3: DIVERGENCE DETECTION (Stage 4.5.1 — deterministic, ₹0, cross-source)
# =============================================================================

@dataclass(frozen=True)
class DivergenceReport:
    """Whether N answers to the SAME question actually agree.

    `pairwise` lists every (model_a, model_b, cosine) pair checked, so a
    caller can see WHICH sources disagreed, not just that "something" did.
    `numeric_conflicts` are human-readable strings, one per conflicting claim
    pair found."""
    diverged: bool
    agreement: float
    pairwise: Tuple[Tuple[str, str, float], ...]
    numeric_conflicts: Tuple[str, ...]
    grounds: Tuple[str, ...]


_DIVERGENCE_MIN_COSINE = 0.60   # below this, two answers read as different substance
_NUMERIC_REL_TOL = 0.08         # >8% relative gap on the SAME unit = a real conflict
_NUMERIC_MIN_SHARED_WORDS = 2   # topical-overlap gate before comparing numbers at all

_UNIT_ALIASES = {
    "ohm": "ohm", "ohms": "ohm",
    "v": "volt", "volt": "volt", "volts": "volt",
    "ma": "milliamp", "mah": "milliamp",
    "amp": "amp", "amps": "amp",
    "w": "watt", "watt": "watt", "watts": "watt",
    "hz": "hz", "khz": "khz", "mhz": "mhz", "ghz": "ghz",
    "%": "percent", "percent": "percent",
    "ms": "millisecond",
    "s": "second", "sec": "second", "secs": "second",
    "second": "second", "seconds": "second",
    "min": "minute", "mins": "minute", "minute": "minute", "minutes": "minute",
}
_NUM_UNIT_RE = re.compile(
    r"(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>ohms?|mah|ma|amps?|khz|mhz|ghz|hz|"
    r"volts?|v|watts?|w|percent|%|ms|secs?|seconds?|s|mins?|minutes?|min)\b",
    re.IGNORECASE)


def _extract_numeric_claims(text: str) -> List[Tuple[float, str]]:
    """Every (number, normalized_unit) pair found in text. Unrecognized units
    (e.g. 'million', bare counts) are skipped — better to miss a claim than
    fabricate a comparison across incompatible units."""
    out: List[Tuple[float, str]] = []
    for m in _NUM_UNIT_RE.finditer(text):
        try:
            num = float(m.group("num"))
        except ValueError:
            continue
        unit = _UNIT_ALIASES.get(m.group("unit").lower())
        if unit:
            out.append((num, unit))
    return out


def _numeric_conflicts(name_a: str, text_a: str, name_b: str, text_b: str) -> List[str]:
    """Shared-topic gate (>=2 common content words) BEFORE comparing any
    numbers — two answers about unrelated things that happen to both mention
    a number are not a conflict. Within a shared topic, same unit + different
    value (beyond _NUMERIC_REL_TOL) IS one, regardless of semantic cosine."""
    shared = _content_words(text_a) & _content_words(text_b)
    if len(shared) < _NUMERIC_MIN_SHARED_WORDS:
        return []
    claims_a = _extract_numeric_claims(text_a)
    claims_b = _extract_numeric_claims(text_b)
    conflicts: List[str] = []
    seen: set = set()
    for na, ua in claims_a:
        for nb, ub in claims_b:
            if ua != ub:
                continue
            denom = max(abs(na), abs(nb), 1e-9)
            if abs(na - nb) / denom <= _NUMERIC_REL_TOL:
                continue
            key = (na, nb, ua)
            if key in seen:
                continue
            seen.add(key)
            conflicts.append(f"{name_a}: {na:g}{ua} vs {name_b}: {nb:g}{ub}")
    return conflicts


def detect_divergence(
    answers: List[Tuple[str, str]],
    embed_fn: Optional[EmbedFn] = None,
    *,
    min_cosine: float = _DIVERGENCE_MIN_COSINE,
    model_name: str = _DEFAULT_MODEL,
) -> DivergenceReport:
    """
    Do N (model, answer) pairs to the SAME question actually agree?

    EXECUTION FLOW:
    1. Drop blank answers. Fewer than 2 usable -> not measurable, diverged=False
       (nothing to disagree WITH — an honest floor, not a false pass).
    2. Embed once; pairwise cosine over every pair -> track the minimum.
    3. Numeric-claim diff over every pair (shared-topic gated).
    4. diverged = (min cosine < min_cosine) OR (any numeric conflict).

    Returns:
        DivergenceReport — never raises; a broken embed_fn propagates its own
        exception (same contract as ConfidenceGate.grade's embedder call).
    """
    usable = [(m, a.strip()) for m, a in answers if a and a.strip()]
    if len(usable) < 2:
        return DivergenceReport(
            diverged=False, agreement=1.0, pairwise=(), numeric_conflicts=(),
            grounds=("fewer than 2 usable answers — divergence not measurable",))

    active_embed = embed_fn or _build_default_embed_fn(model_name)
    windows = [_windows(a) for _m, a in usable]
    flat = active_embed([w for ws in windows for w in ws])
    vecs: List[List[float]] = []
    pos = 0
    for ws in windows:
        vecs.append(_mean_unit(flat[pos:pos + len(ws)]))
        pos += len(ws)

    pairwise: List[Tuple[str, str, float]] = []
    min_cos = 1.0
    for i in range(len(usable)):
        for j in range(i + 1, len(usable)):
            cos = max(-1.0, min(1.0, _dot(vecs[i], vecs[j])))
            pairwise.append((usable[i][0], usable[j][0], round(cos, 4)))
            min_cos = min(min_cos, cos)

    numeric_conflicts: List[str] = []
    for i in range(len(usable)):
        for j in range(i + 1, len(usable)):
            numeric_conflicts.extend(_numeric_conflicts(
                usable[i][0], usable[i][1], usable[j][0], usable[j][1]))

    semantic_diverged = min_cos < min_cosine
    diverged = semantic_diverged or bool(numeric_conflicts)
    agreement = round(max(0.0, min_cos), 4)

    grounds: List[str] = []
    if semantic_diverged:
        worst = min(pairwise, key=lambda p: p[2])
        grounds.append(f"semantic divergence: '{worst[0]}' vs '{worst[1]}' "
                       f"cosine {worst[2]:.2f} < {min_cosine}")
    if numeric_conflicts:
        grounds.append("numeric conflict(s): " + "; ".join(numeric_conflicts))
    if not grounds:
        grounds.append(f"sources agree: min pairwise cosine {min_cos:.2f}, no numeric conflicts")

    return DivergenceReport(diverged=diverged, agreement=agreement,
                            pairwise=tuple(pairwise),
                            numeric_conflicts=tuple(numeric_conflicts),
                            grounds=tuple(grounds))


# =============================================================================
# Part 4: FROZEN DIVERGENCE GATE (Stage 4.5.1 DoD — 6/6 conflicts, 0/6 false flags)
# =============================================================================

_DIVERGENCE_EVAL_PATH = Path(__file__).resolve().parents[2] / "tests" / "divergence_eval.jsonl"


def _make_pair_embed(same_topic: bool) -> EmbedFn:
    """The fixture declares topic-sameness explicitly (`same_topic`) rather
    than relying on keyword pattern-matching over fixture text — fully
    deterministic, and it makes each row self-documenting: a same-topic
    numeric-conflict row proves the numeric path trips even when cosine is
    forced to 1.0; a different-topic row proves the semantic path alone."""
    def _embed(texts: List[str]) -> List[List[float]]:
        if same_topic:
            return [[1.0, 0.0] for _ in texts]
        return [[1.0, 0.0]] + [[0.0, 1.0] for _ in texts[1:]]
    return _embed


def _run_divergence_gate(path: Path = _DIVERGENCE_EVAL_PATH) -> Tuple[int, int, List[str]]:
    """Replay the frozen fixture; returns (correct, total, mismatch descriptions)."""
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    correct = 0
    mismatches: List[str] = []
    for row in rows:
        report = detect_divergence(
            [(row["model_a"], row["answer_a"]), (row["model_b"], row["answer_b"])],
            embed_fn=_make_pair_embed(bool(row["same_topic"])))
        expect = bool(row["expect_diverged"])
        if report.diverged == expect:
            correct += 1
        else:
            mismatches.append(f"{row['id']}: expected diverged={expect}, "
                              f"got {report.diverged} ({report.grounds})")
    return correct, len(rows), mismatches


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

    # T10: long evidence is embedded WHOLE through overlapping windows. The
    # only grounding fact sits at char ~9,000 — past any head — and must still
    # be what the draft matches; every window stays under the model's limit.
    seen10: List[str] = []

    def recording_embed(texts: List[str]) -> List[List[float]]:
        seen10.extend(texts)
        return scripted_embed(texts)

    long_ev = "portfolio " * 900 + "spark shuffle partitions default to 200"
    r10 = ConfidenceGate(embed_fn=recording_embed).grade(
        "spark shuffle partitions default to 200", [long_ev])
    ev_seen = seen10[1:]
    check("T10 a fact 9,000 chars into the evidence is found (no head cut)",
          r10.verdict == VERDICT_CONFIDENT and "spark shuffle" in r10.grounds[2],
          f"{r10.score} {r10.grounds}")
    check("T10b windows cover the whole evidence, each under the embed limit",
          all(len(w) <= _WINDOW_CHARS for w in ev_seen)
          and sum(len(w) for w in ev_seen) >= len(long_ev)
          and ev_seen[-1].endswith("default to 200"), str(len(ev_seen)))

    # T10c: a long DRAFT is graded on all of it — a fabricated tail after a
    # grounded head lowers the semantic score (the old 600-char head hid it).
    head = "spark shuffle partitions default to 200 " * 15
    tail = "the moon base launches tomorrow at dawn " * 60
    r10c_head = gate.grade(head, ev)
    r10c_full = gate.grade(head + tail, ev)
    check("T10c fabricated tail beyond 600 chars is seen by the gate",
          r10c_full.score < r10c_head.score, f"{r10c_full.score} vs {r10c_head.score}")

    # T11: score clamped to [0,1] even with a pathological embedder
    def weird_embed(texts: List[str]) -> List[List[float]]:
        return [[2.0, 0.0, 0.0] for _ in texts]  # non-unit on purpose
    r11 = ConfidenceGate(embed_fn=weird_embed).grade("spark spark", ["spark spark"])
    check("T11 score clamped", 0.0 <= r11.score <= 1.0, str(r11.score))

    # --- detect_divergence() ---

    # D1: fewer than 2 usable answers -> not measurable, diverged=False
    d1 = detect_divergence([("solo", "the only answer")])
    check("D1 single answer -> not measurable, diverged=False",
          d1.diverged is False and "not measurable" in d1.grounds[0], str(d1))

    # D2: blank answers dropped before the count check
    d2 = detect_divergence([("a", "real answer"), ("b", "   ")])
    check("D2 blank answer dropped -> effectively single -> not measurable", d2.diverged is False)

    # D3: same-topic (forced cosine=1.0), numeric claims disagree -> diverged
    # via the numeric path ALONE (proves it's independent of semantic cosine)
    d3 = detect_divergence(
        [("a", "The current-limiting resistor should be about 220 ohms."),
         ("b", "You need roughly 330 ohms for that current-limiting resistor.")],
        embed_fn=_make_pair_embed(same_topic=True))
    check("D3 numeric conflict trips diverged even with forced-identical cosine",
          d3.diverged is True and any("ohm" in c for c in d3.numeric_conflicts), str(d3))

    # D4: same-topic, numbers agree -> NOT diverged
    d4 = detect_divergence(
        [("a", "The resistor should be 220 ohms."), ("b", "Use a 220 ohm resistor.")],
        embed_fn=_make_pair_embed(same_topic=True))
    check("D4 matching numbers -> not diverged", d4.diverged is False, str(d4))

    # D5: different-topic (forced cosine=0.0), no numbers -> diverged via semantic path
    d5 = detect_divergence(
        [("a", "Salting the join key fixes skew."), ("b", "Skew usually isn't worth fixing.")],
        embed_fn=_make_pair_embed(same_topic=False))
    check("D5 semantic-only divergence (no numbers involved)",
          d5.diverged is True and "semantic divergence" in d5.grounds[0], str(d5))

    # D6: numbers present but NO shared topical words -> gate blocks the
    # comparison (unrelated coincidental numbers must not read as a conflict)
    d6 = detect_divergence(
        [("a", "The resistor is 220 ohms."), ("b", "The invoice total is 330 dollars.")],
        embed_fn=_make_pair_embed(same_topic=True))
    check("D6 no shared topic words -> numeric path stays silent",
          d6.numeric_conflicts == (), str(d6.numeric_conflicts))

    # D7: pairwise tuple names both models for a 2-source check
    check("D7 pairwise names both sources",
          len(d3.pairwise) == 1 and d3.pairwise[0][0] == "a" and d3.pairwise[0][1] == "b",
          str(d3.pairwise))

    # D7b: a long answer is compared on ALL of it: the disagreeing claim sits
    # past 2,000 chars of shared preamble, and the windowed embedding sees it.
    pre = "portfolio allocation context " * 80
    d7b = detect_divergence(
        [("a", pre + " spark spark spark " * 60), ("b", pre + " portfolio " * 60)],
        embed_fn=scripted_embed)
    check("D7b divergence visible past the first window of a long answer",
          d7b.agreement < 0.99, str(d7b.agreement))

    # D8 (Stage 4.5.1 DoD): the frozen 12-fixture gate — 6/6 conflicts flagged,
    # 0/6 false flags, exact.
    correct, total_g, mismatches = _run_divergence_gate()
    check(f"D8 divergence gate: {correct}/{total_g} on frozen fixture (6/6 conflict, 6/6 agree)",
          correct == total_g, "; ".join(mismatches))

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
