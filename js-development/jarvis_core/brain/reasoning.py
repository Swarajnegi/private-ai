"""
reasoning.py — Reasoning Gate (Stage 4.5: Epistemic Control, Wave 1).

LAYER: Brain (Cognitive Control Loop — epistemic control)

Import with:
    from jarvis_core.brain.reasoning import (
        ReasoningGate, ReasoningReport, fuse,
        ContradictionJudge, ContradictionReport, resolve_conflict,
    )

=============================================================================
THE BIG PICTURE
=============================================================================

The ConfidenceGate (confidence.py) answers ONE question: "did you make this
up?" — it grades a draft against the evidence the session gathered. It is
deterministic, ₹0, and STRUCTURALLY BLIND to a second, different question:
"is your logic right?"

Live repro that motivated this organ (KB L383, gpt-4o-mini, 2026-06-15): the
user set a yes/no protocol, INVERTED it ("respond no if true and yes if
false"), then asked "is earth flat?". Earth-flat is FALSE → the correct
inverted answer is "Yes"; the brain answered "No" (it dropped the inversion).
That answer is COHERENT PROSE with NO external evidence, so the grounding gate
scored it ESCALATE 0.00 — the SAME score a *correct* evidence-less answer
gets. Wrong was indistinguishable from right. A gate that cannot tell those
apart is not epistemic control.

This is the LLM-judge layer the confidence.py docstring explicitly reserved
for 4.5. The mechanism is ADVERSARIAL SELF-CRITIQUE, not self-consistency:
sampling the same answer N times and voting catches STOCHASTIC uncertainty,
but the earth-flat miss is SYSTEMATIC — the model drops the inversion every
time, so all N samples agree on the wrong answer and self-consistency reports
HIGH confidence on it. Self-critique with INDEPENDENT RE-DERIVATION reframes
the model's attention away from the (wrong) given answer.

HONEST LIMIT (do not overclaim — KB L383 was gpt-4o-mini auditing gpt-4o-mini):
self-critique catches errors a model can recognize ON REFLECTION, but a
SAME-MODEL audit can share the very blind spot that produced a SYSTEMATIC
error — re-derive the same wrong way, compare wrong-to-wrong, and return SOUND.
So a self-audit's SOUND is WEAK evidence and is NOT allowed to upgrade
confidence (see `fuse`'s `critic_independent` gate); only FLAWED is acted on,
because a same-model critic errs toward false-SOUND (missing a flaw), not
false-FLAWED — making both directions fail-closed. The real fix for the
systematic class is an INDEPENDENT / stronger critic, which is why the critic
model is INJECTED (defaults to the same llm_call — cheapest first cut; a
stronger reasoning-grade critic is a one-line swap). This is the seed of the
multi-model conflict detection mandated for Phase 4+ (never hide a
disagreement between models).

The two signals stay ORTHOGONAL and are reported SEPARATELY (epistemic
honesty — never collapse two axes into one number and hide the disagreement).
`fuse()` derives a single stamped verdict for downstream bookkeeping:
FLAWED reasoning forces ESCALATE (and surfaces the flaw); SOUND from an
INDEPENDENT critic LIFTS a *no-evidence* ESCALATE to UNCERTAIN so a sound
pure-reasoning answer is distinguishable from a flawed one — but never lifts a
*had-evidence* ESCALATE (that ESCALATE is the grounding gate's fabrication
signal, not a pure-reasoning case), and never lifts on a self-audit.

Stage 4.5.2 adds a SECOND judge, over a DIFFERENT pair of things: not "is one
answer's own logic right?" but "do TWO models' answers to the SAME question
actually contradict?" `confidence.detect_divergence` (4.5.1) already did the
cheap, ₹0, deterministic triage (semantic cosine + numeric-claim diff) and
flagged that two answers LOOK different. `ContradictionJudge` is the fine
judgment layer on top: an LLM asked directly whether that difference is a real
contradiction or just compatible/complementary phrasing — the class embeddings
structurally cannot resolve (see confidence.py's docstring: "yes" vs "no" on
the same claim often embeds as near-identical).

The fail-closed asymmetry is the point, not an oversight: the judge may only
DOWNGRADE a flagged divergence (a COMPATIBLE verdict clears it); it can NEVER
be the reason a conflict is raised in the first place (that's 4.5.1's job),
and a judge that ERRORS or babbles (UNCHECKED) must NEVER be read as
clearance — an audit that couldn't run is not evidence of agreement.
`resolve_conflict()` is this exact rule, mirroring how `fuse()` combines
grounding + reasoning into one stamp.

=============================================================================
THE FLOW
=============================================================================

STEP 1: critique(question, answer, context): empty answer → UNCHECKED (fail
        closed — UNCHECKED is NOT a pass). Build the auditor messages: restate
        the user's rules → re-derive INDEPENDENTLY → compare.
        |
STEP 2: call the injected critic (sync or async); parse its JSON via the same
        extractor the tool parser uses. Any error / unparseable / unknown
        verdict → UNCHECKED (never crashes the ask).
        |
STEP 3: ReasoningReport(verdict ∈ {SOUND, FLAWED, UNCHECKED}, flaw, corrected,
        grounds).
        |
STEP 4: fuse(grounding, reasoning, critic_independent) → one ConfidenceReport
        for the stamp: FLAWED→ESCALATE(flaw leads); SOUND lifts a no-evidence
        ESCALATE→UNCERTAIN *only when the critic is independent*; SOUND otherwise
        only annotates (grounding signal still leads); UNCHECKED→grounding
        unchanged (graceful degradation, no regression).
        |
STEP 5 (4.5.2, separate entry point): ContradictionJudge.judge(question,
        source_a, source_b) → ContradictionReport(verdict ∈ {CONTRADICTION,
        COMPATIBLE, UNCHECKED}, which, grounds). Empty answer / no judge wired
        / call error / unparseable → UNCHECKED, never a silent pass.
        |
STEP 6: resolve_conflict(divergence, judgment) → (conflict: bool, detail):
        no divergence → no conflict (judge never even needed). Divergence +
        COMPATIBLE → cleared. Divergence + CONTRADICTION or UNCHECKED → conflict
        STANDS (the asymmetric fail-closed rule).

=============================================================================
"""

from __future__ import annotations

import inspect
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, Union

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # standalone-run safety

from jarvis_core.agent.parser import _extract_json_str
from jarvis_core.brain.confidence import (
    ConfidenceReport,
    DivergenceReport,
    VERDICT_CONFIDENT,
    VERDICT_ESCALATE,
    VERDICT_UNCERTAIN,
)

# Critic protocol: same shape as the agent's LLMCall — messages in, text out,
# sync or async. Default critic == the answering model (cheapest honest cut).
CriticCall = Callable[[List[Dict[str, str]]], Union[str, Awaitable[str]]]

VERDICT_SOUND = "SOUND"
VERDICT_FLAWED = "FLAWED"
VERDICT_UNCHECKED = "UNCHECKED"

# A SOUND but evidence-less answer is lifted out of the falsely-dismissive
# ESCALATE-0.00 to here: above the 0.30 uncertain threshold, below 0.55
# confident — "logic checks out, but ungrounded by external evidence."
# NOTE: kept just above ConfidenceGate's DEFAULT uncertain_at (0.30) so a lifted
# score sits inside the UNCERTAIN band. A caller raising uncertain_at past 0.35
# would make the pair inconsistent — fuse() has no handle on the gate's config;
# revisit if a non-default threshold is ever wired (no production caller is today).
_REASONING_SOUND_FLOOR = 0.35
# History is bounded before it enters the critic prompt. Rules are almost always
# USER turns, so user turns get a generous cap; assistant turns (which can be a
# pathological --full wall of text) get a tight one. Truncation is MARKED, never
# silent (project EXPLANATION STYLE rule #3: no invisible operations).
_CONTEXT_USER_CHARS = 2000
_CONTEXT_ASSISTANT_CHARS = 400
_MAX_CONTEXT_TURNS = 12


# =============================================================================
# Part 1: CONTRACT (frozen)
# =============================================================================

@dataclass(frozen=True)
class ReasoningReport:
    """The reasoning auditor's output: a verdict, the flaw (if any), a
    correction (if any), and human-readable grounds."""
    verdict: str
    flaw: str
    corrected: str
    grounds: Tuple[str, ...]


# =============================================================================
# Part 2: PROMPT (independent re-derivation — the anti-anchoring core)
# =============================================================================

_CRITIC_SYSTEM = (
    "You are a strict reasoning auditor. Your only job is to catch logical "
    "errors in an answer — dropped constraints, unchecked false premises, "
    "answer-format inversions the user imposed, and non-sequiturs. You do NOT "
    "care whether the answer sounds confident or fluent; only whether its "
    "logic is correct given everything the user stated. Be skeptical: it is "
    "far worse to wave through a wrong answer than to flag a right one."
)


def _render_context(context: Optional[List[Dict[str, str]]]) -> str:
    if not context:
        return "(no prior conversation)"
    dropped = max(0, len(context) - _MAX_CONTEXT_TURNS)
    turns = context[-_MAX_CONTEXT_TURNS:]
    lines = []
    if dropped:
        lines.append(f"[{dropped} older turn(s) elided — a rule stated earlier "
                     "than this window is not visible to the audit]")
    for t in turns:
        role = str(t.get("role", "?"))
        full = str(t.get("content", "")).strip()
        cap = _CONTEXT_USER_CHARS if role == "user" else _CONTEXT_ASSISTANT_CHARS
        content = full[:cap]
        if len(full) > cap:
            content += " […turn truncated]"
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines) if lines else "(no prior conversation)"


def _build_critic_messages(
    question: str, answer: str, context: Optional[List[Dict[str, str]]],
    evidence: Optional[str] = None,
) -> List[Dict[str, str]]:
    # De-anchoring is STRUCTURAL, not just verbal: derive first, reveal the given
    # answer last. (A single call still sees everything, but order biases the
    # chain-of-thought; a truly blind two-call derive-then-compare is the Wave-2
    # upgrade for the systematic-blind-spot class — see module docstring.)
    # EVIDENCE (optional): the tool observations the agent actually gathered this
    # run, so the critic judges against what WAS retrieved instead of blind — it can
    # then catch "the answer ignores the files it read / only reports process"
    # rather than falsely claiming the material "was never provided".
    evidence_block = (
        ("EVIDENCE THE AGENT GATHERED THIS RUN (tool observations it received — a "
         "good answer is grounded in and actually USES this):\n"
         f"{evidence}\n\n") if (evidence or "").strip() else ""
    )
    user = (
        "CONVERSATION CONTEXT (rules/premises the user established earlier, "
        "oldest first — read for inversions and constraints):\n"
        f"{_render_context(context)}\n\n"
        f"{evidence_block}"
        f"THE USER'S CURRENT QUESTION:\n{question}\n\n"
        "Work in THREE steps, IN ORDER, before you look at the answer that was "
        "given:\n"
        "1. RESTATE every rule, constraint, or premise the user imposed "
        "(including answer-format inversions like \"say X if true\"). If a "
        "premise is factually false, say so.\n"
        "2. From scratch, DERIVE the correct answer yourself under those rules. "
        "Write your derived answer out explicitly. If EVIDENCE was gathered above, "
        "base your derivation on it. Do this WITHOUT regard to any answer you are "
        "about to be shown.\n"
        "3. ONLY NOW compare your derived answer to the answer that was given "
        "below, and judge whether the given answer matches your derivation AND "
        "actually answers the question — an answer that merely reports process "
        "(\"steps complete\", \"see above\") or ignores the gathered evidence is "
        f"FLAWED.\n\n"
        f"THE ANSWER THAT WAS GIVEN (do not read until after step 2):\n{answer}\n\n"
        "Respond with ONLY a JSON object, no prose around it:\n"
        '{"verdict": "SOUND" or "FLAWED", '
        '"flaw": "<one sentence naming the specific logical error, or empty if SOUND>", '
        '"corrected": "<the correct answer if FLAWED, else empty>"}'
    )
    return [
        {"role": "system", "content": _CRITIC_SYSTEM},
        {"role": "user", "content": user},
    ]


# =============================================================================
# Part 3: THE GATE
# =============================================================================

class ReasoningGate:
    """Audits an answer's LOGIC via an injected critic. Fail-closed to
    UNCHECKED — a critic that errors or babbles is never a pass."""

    def __init__(self, critic_llm: Optional[CriticCall] = None) -> None:
        self._critic = critic_llm

    async def critique(
        self,
        question: str,
        answer: str,
        context: Optional[List[Dict[str, str]]] = None,
        evidence: Optional[str] = None,
    ) -> ReasoningReport:
        """
        Audit ONE answer's reasoning. Returns a ReasoningReport; UNCHECKED is
        the floor and is never an exception (a failed audit must not sink the
        ask).

        EXECUTION FLOW:
        1. Empty answer or no critic wired → UNCHECKED (nothing audited).
        2. Build auditor messages (restate rules → re-derive → compare).
        3. Call critic (sync/async); parse JSON; map verdict.
        4. Unknown verdict / parse failure / any exception → UNCHECKED.
        """
        answer = (answer or "").strip()
        if not answer:
            return ReasoningReport(
                VERDICT_UNCHECKED, "", "",
                ("empty answer — nothing to audit",))
        if self._critic is None:
            return ReasoningReport(
                VERDICT_UNCHECKED, "", "",
                ("no critic model wired — reasoning audit disabled",))

        messages = _build_critic_messages(question, answer, context, evidence)
        try:
            out = self._critic(messages)
            if inspect.isawaitable(out):
                out = await out
            raw = str(out)
        except Exception as e:  # budget exhausted, HTTP error, anything
            return ReasoningReport(
                VERDICT_UNCHECKED, "", "",
                (f"critic call failed ({type(e).__name__}) — audit skipped, "
                 "not treated as a pass",))

        return _parse_critic(raw)


def _parse_critic(raw: str) -> ReasoningReport:
    """Map the critic's raw text to a ReasoningReport. Fail-closed."""
    json_str = _extract_json_str(raw)
    if json_str is None:
        return ReasoningReport(
            VERDICT_UNCHECKED, "", "",
            ("critic emitted no parseable JSON — audit inconclusive",))
    try:
        data = json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        return ReasoningReport(
            VERDICT_UNCHECKED, "", "",
            ("critic JSON did not parse — audit inconclusive",))
    if not isinstance(data, dict):
        return ReasoningReport(
            VERDICT_UNCHECKED, "", "",
            ("critic JSON was not an object — audit inconclusive",))

    verdict = str(data.get("verdict", "")).strip().upper()
    flaw = str(data.get("flaw", "") or "").strip()
    corrected = str(data.get("corrected", "") or "").strip()

    if verdict == VERDICT_SOUND:
        return ReasoningReport(
            VERDICT_SOUND, "", "",
            ("auditor re-derived independently and agrees with the answer",))
    if verdict == VERDICT_FLAWED:
        return ReasoningReport(
            VERDICT_FLAWED, flaw or "(flaw unspecified)", corrected,
            (f"auditor found a logical flaw: {flaw or '(unspecified)'}",
             f"corrected: {corrected}" if corrected else "no correction supplied"))
    return ReasoningReport(
        VERDICT_UNCHECKED, "", "",
        (f"critic returned an unknown verdict {verdict!r} — audit inconclusive",))


# =============================================================================
# Part 4: FUSION (two orthogonal signals -> one stamped verdict)
# =============================================================================

def fuse(
    grounding: ConfidenceReport,
    reasoning: ReasoningReport,
    critic_independent: bool = False,
) -> ConfidenceReport:
    """
    Combine the grounding signal ("did you make it up?") and the reasoning
    signal ("is your logic right?") into ONE ConfidenceReport for the stamp.
    The two are still reported SEPARATELY by the caller — fuse() is only the
    single number downstream bookkeeping needs.

    `critic_independent` is True only when the auditor is a DIFFERENT model than
    the one that produced the answer. A self-audit's SOUND is weak evidence (it
    can share the answer's blind spot) so it is NOT allowed to upgrade the
    verdict — only an independent SOUND lifts. FLAWED is acted on regardless,
    because a same-model critic errs toward false-SOUND, not false-FLAWED, so
    both directions stay fail-closed.

    RULES:
    - reasoning UNCHECKED -> grounding unchanged (graceful degradation; the
      pre-4.5 behavior exactly, so disabling the critic is a clean no-op).
    - reasoning FLAWED -> ESCALATE, score 0.0, the flaw LEADS the grounds.
      A confidently-wrong answer can no longer score like a right one.
    - reasoning SOUND + INDEPENDENT critic + grounding ESCALATE with NO evidence
      -> lift to UNCERTAIN at the reasoning floor: an evidence-less but logically
      sound answer is distinguishable from a flawed one. A *had_evidence*
      ESCALATE is NEVER lifted — that ESCALATE is the grounding gate's
      contradicts-the-evidence (fabrication) signal, which SOUND logic must not
      mask.
    - reasoning SOUND otherwise -> keep the grounding verdict/score and the
      grounding grounds LEADING; SOUND is only an appended annotation (a
      self-audit cannot upgrade confidence, and the grounding signal — including
      a fabrication finding — must keep leading the surfaced grounds).
    """
    if reasoning.verdict == VERDICT_UNCHECKED:
        return grounding

    if reasoning.verdict == VERDICT_FLAWED:
        return ConfidenceReport(
            0.0, VERDICT_ESCALATE,
            reasoning.grounds + grounding.grounds,
            had_evidence=grounding.had_evidence)

    # SOUND
    if (critic_independent
            and grounding.verdict == VERDICT_ESCALATE
            and not grounding.had_evidence):
        score = max(grounding.score, _REASONING_SOUND_FLOOR)
        return ConfidenceReport(
            round(score, 4), VERDICT_UNCERTAIN,
            ("reasoning audit: SOUND (independent critic re-derived the logic)",
             "but ungrounded by session evidence — uncertain, not confident")
            + grounding.grounds,
            had_evidence=grounding.had_evidence)

    note = ("reasoning audit: SOUND (self-audit — weak signal, no confidence lift)"
            if not critic_independent else "reasoning audit: SOUND")
    return ConfidenceReport(
        grounding.score, grounding.verdict,
        grounding.grounds + (note,),
        had_evidence=grounding.had_evidence)


# =============================================================================
# Part 5: CONTRADICTION JUDGE (Stage 4.5.2 — cross-source, fail-closed)
# =============================================================================

VERDICT_CONTRADICTION = "CONTRADICTION"
VERDICT_COMPATIBLE = "COMPATIBLE"
# VERDICT_UNCHECKED (defined above) is shared with ReasoningGate — the same
# "an audit that couldn't run is not a pass" floor applies to both judges.


@dataclass(frozen=True)
class ContradictionReport:
    """The contradiction judge's output: a verdict, WHICH claim conflicts (if
    any), and human-readable grounds."""
    verdict: str
    which: str
    grounds: Tuple[str, ...]


_CONTRADICTION_SYSTEM = (
    "You are a strict conflict judge. You are given ONE question and TWO "
    "different models' answers to it. Your only job is to decide whether the "
    "two answers are a genuine CONTRADICTION (both cannot be true at once) or "
    "merely COMPATIBLE (different wording, complementary detail, one is more "
    "specific than the other — but nothing actually clashes). Do NOT judge "
    "which answer is better, more complete, or more confident — only whether "
    "they conflict. Be skeptical of calling something COMPATIBLE: it is worse "
    "to wave through a real conflict than to flag two answers that just happen "
    "to differ in emphasis."
)


def _build_contradiction_messages(
    question: str, model_a: str, answer_a: str, model_b: str, answer_b: str,
) -> List[Dict[str, str]]:
    user = (
        f"QUESTION:\n{question}\n\n"
        f"ANSWER FROM {model_a}:\n{answer_a}\n\n"
        f"ANSWER FROM {model_b}:\n{answer_b}\n\n"
        "Respond with ONLY a JSON object, no prose around it:\n"
        '{"verdict": "CONTRADICTION" or "COMPATIBLE", '
        '"which": "<the specific claim that conflicts, or empty if COMPATIBLE>"}'
    )
    return [{"role": "system", "content": _CONTRADICTION_SYSTEM},
            {"role": "user", "content": user}]


class ContradictionJudge:
    """Judges whether two DIVERGENCE-FLAGGED answers genuinely contradict.
    Fail-closed to UNCHECKED — a judge that errors or babbles is never read
    as clearance (see resolve_conflict, which enforces this at the call site)."""

    def __init__(self, judge_llm: Optional[CriticCall] = None) -> None:
        self._judge = judge_llm

    async def judge(
        self, question: str,
        source_a: Tuple[str, str], source_b: Tuple[str, str],
    ) -> ContradictionReport:
        """
        Judge ONE pair of divergent answers to the SAME question.

        EXECUTION FLOW:
        1. Either answer empty, or no judge wired → UNCHECKED (nothing judged).
        2. Build judge messages (question + both attributed answers).
        3. Call judge (sync/async); parse JSON; map verdict.
        4. Unknown verdict / parse failure / any exception → UNCHECKED.
        """
        model_a, answer_a = source_a
        model_b, answer_b = source_b
        answer_a, answer_b = (answer_a or "").strip(), (answer_b or "").strip()
        if not answer_a or not answer_b:
            return ContradictionReport(
                VERDICT_UNCHECKED, "",
                ("one or both answers empty — nothing to judge",))
        if self._judge is None:
            return ContradictionReport(
                VERDICT_UNCHECKED, "",
                ("no judge model wired — contradiction check disabled",))

        messages = _build_contradiction_messages(question, model_a, answer_a, model_b, answer_b)
        try:
            out = self._judge(messages)
            if inspect.isawaitable(out):
                out = await out
            raw = str(out)
        except Exception as e:  # budget exhausted, HTTP error, anything
            return ContradictionReport(
                VERDICT_UNCHECKED, "",
                (f"judge call failed ({type(e).__name__}) — treated as unresolved, NOT as agreement",))

        return _parse_contradiction(raw)


def _parse_contradiction(raw: str) -> ContradictionReport:
    """Map the judge's raw text to a ContradictionReport. Fail-closed."""
    json_str = _extract_json_str(raw)
    if json_str is None:
        return ContradictionReport(
            VERDICT_UNCHECKED, "",
            ("judge emitted no parseable JSON — inconclusive",))
    try:
        data = json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        return ContradictionReport(
            VERDICT_UNCHECKED, "",
            ("judge JSON did not parse — inconclusive",))
    if not isinstance(data, dict):
        return ContradictionReport(
            VERDICT_UNCHECKED, "",
            ("judge JSON was not an object — inconclusive",))

    verdict = str(data.get("verdict", "")).strip().upper()
    which = str(data.get("which", "") or "").strip()

    if verdict == VERDICT_CONTRADICTION:
        return ContradictionReport(
            VERDICT_CONTRADICTION, which or "(unspecified)",
            (f"judge found a contradiction: {which or '(unspecified)'}",))
    if verdict == VERDICT_COMPATIBLE:
        return ContradictionReport(
            VERDICT_COMPATIBLE, "",
            ("judge found the answers compatible (different wording/complementary, not conflicting)",))
    return ContradictionReport(
        VERDICT_UNCHECKED, "",
        (f"judge returned an unknown verdict {verdict!r} — inconclusive",))


# =============================================================================
# Part 6: CONFLICT RESOLUTION (combining 4.5.1 divergence + 4.5.2 judgment)
# =============================================================================

def resolve_conflict(
    divergence: DivergenceReport, judgment: ContradictionReport,
) -> Tuple[bool, str]:
    """
    Combine the deterministic divergence flag (4.5.1) with the LLM judge's
    verdict (4.5.2) into ONE conflict decision, mirroring how fuse() combines
    grounding + reasoning.

    RULES (the fail-closed asymmetry is deliberate):
    - no divergence -> no conflict. The judge is not even consulted for this
      case in practice (the orchestrator only calls it when 4.5.1 flags).
    - divergence + COMPATIBLE -> cleared. The judge may DOWNGRADE a flagged
      divergence to "not actually a conflict" (different wording/complementary).
    - divergence + CONTRADICTION -> conflict stands, judge NAMES the clash.
    - divergence + UNCHECKED -> conflict STILL stands. A judge that errored or
      produced nothing is not evidence of agreement — the deterministic flag
      from 4.5.1 is the floor, and only a POSITIVE compatibility finding can
      clear it.

    Returns:
        (conflict: bool, detail: str) — detail is always human-readable.
    """
    if not divergence.diverged:
        return False, "no divergence detected"
    if judgment.verdict == VERDICT_COMPATIBLE:
        return False, (f"divergence flagged but judge cleared it: "
                       f"{judgment.grounds[0] if judgment.grounds else 'compatible'}")
    detail = judgment.grounds[0] if judgment.grounds else divergence.grounds[0]
    return True, detail


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS (offline — scripted critics, no network)
# =============================================================================

def _run_self_test() -> None:
    import asyncio

    print("=" * 70)
    print("  reasoning.py -- Smoke Tests")
    print("=" * 70)
    passed = 0
    failed: List[str] = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        nonlocal passed
        if cond:
            passed += 1
        else:
            failed.append(f"FAIL: {name}" + (f" ({hint})" if hint else ""))

    def scripted(payload: str) -> CriticCall:
        def _c(messages: List[Dict[str, str]]) -> str:
            return payload
        return _c

    def run(coro):  # modern, loop-agnostic (matches the orchestrator twin)
        return asyncio.new_event_loop().run_until_complete(coro)

    # T1: SOUND verdict
    g1 = ReasoningGate(scripted('{"verdict": "SOUND", "flaw": "", "corrected": ""}'))
    r1 = run(g1.critique("is earth flat?", "No."))
    check("T1 SOUND parsed", r1.verdict == VERDICT_SOUND, str(r1))

    # T2: FLAWED verdict carries flaw + correction
    g2 = ReasoningGate(scripted(
        '{"verdict": "FLAWED", "flaw": "dropped the stated inversion rule", '
        '"corrected": "Yes"}'))
    r2 = run(g2.critique("is earth flat?", "No.",
                         context=[{"role": "user", "content": "say yes if false"}]))
    check("T2 FLAWED parsed", r2.verdict == VERDICT_FLAWED, str(r2))
    check("T2b flaw captured", "inversion" in r2.flaw, r2.flaw)
    check("T2c correction captured", r2.corrected == "Yes", r2.corrected)

    # T3: fenced ```json ``` is extracted (reuses the tool parser's extractor)
    g3 = ReasoningGate(scripted(
        'Here is my audit:\n```json\n{"verdict": "SOUND", "flaw": "", "corrected": ""}\n```'))
    r3 = run(g3.critique("q", "a"))
    check("T3 fenced JSON parsed", r3.verdict == VERDICT_SOUND, str(r3))

    # T4: babble (no JSON) -> UNCHECKED (fail-closed, NOT a pass)
    g4 = ReasoningGate(scripted("I think the answer looks fine to me, yes."))
    r4 = run(g4.critique("q", "a"))
    check("T4 no-JSON -> UNCHECKED", r4.verdict == VERDICT_UNCHECKED, str(r4))

    # T5: critic raises -> UNCHECKED, no exception escapes
    def boom(messages: List[Dict[str, str]]) -> str:
        raise RuntimeError("budget exhausted")
    r5 = run(ReasoningGate(boom).critique("q", "a"))
    check("T5 critic exception -> UNCHECKED", r5.verdict == VERDICT_UNCHECKED, str(r5))
    check("T5b grounds name the failure", "failed" in r5.grounds[0], str(r5.grounds))

    # T6: unknown verdict -> UNCHECKED (never silently SOUND)
    g6 = ReasoningGate(scripted('{"verdict": "MAYBE", "flaw": "", "corrected": ""}'))
    r6 = run(g6.critique("q", "a"))
    check("T6 unknown verdict -> UNCHECKED", r6.verdict == VERDICT_UNCHECKED, str(r6))

    # T7: async critic (awaitable) handled
    async def acritic(messages: List[Dict[str, str]]) -> str:
        return '{"verdict": "SOUND", "flaw": "", "corrected": ""}'
    r7 = run(ReasoningGate(acritic).critique("q", "a"))
    check("T7 async critic", r7.verdict == VERDICT_SOUND, str(r7))

    # T8: empty answer -> UNCHECKED without calling the critic
    called = {"n": 0}
    def counting(messages: List[Dict[str, str]]) -> str:
        called["n"] += 1
        return '{"verdict": "SOUND"}'
    r8 = run(ReasoningGate(counting).critique("q", "   "))
    check("T8 empty answer -> UNCHECKED", r8.verdict == VERDICT_UNCHECKED, str(r8))
    check("T8b critic not called on empty answer", called["n"] == 0, str(called))

    # T9: no critic wired -> UNCHECKED (audit disabled, graceful)
    r9 = run(ReasoningGate(None).critique("q", "a"))
    check("T9 no critic -> UNCHECKED", r9.verdict == VERDICT_UNCHECKED, str(r9))

    # T10: critic messages carry context rule + question + answer (anti-anchor)
    msgs = _build_critic_messages(
        "is earth flat?", "No.",
        [{"role": "user", "content": "respond no if true and yes if false"}])
    body = msgs[-1]["content"]
    check("T10 context rule injected", "yes if false" in body, body[:120])
    check("T10b question injected", "is earth flat?" in body)
    check("T10c answer injected", "No." in body)
    check("T10d derive-before-reveal: derive instruction precedes the given answer",
          "DERIVE the correct answer yourself" in body
          and body.index("DERIVE the correct answer yourself")
          < body.index("THE ANSWER THAT WAS GIVEN"), body[:160])

    # T10e: an EVIDENCE digest is injected and precedes the given answer, so the
    # critic judges the answer against what was gathered (not blind).
    msgs_ev = _build_critic_messages(
        "what is jarvis?", "All plan steps are complete; the answer is above.",
        None, evidence="[1] CLAUDE.md: JARVIS is a Model-of-Models cognitive orchestrator.")
    body_ev = msgs_ev[-1]["content"]
    check("T10e evidence block injected",
          "EVIDENCE THE AGENT GATHERED" in body_ev
          and "Model-of-Models cognitive orchestrator" in body_ev, body_ev[:160])
    check("T10e2 evidence precedes the given answer (still de-anchored)",
          body_ev.index("EVIDENCE THE AGENT GATHERED") < body_ev.index("THE ANSWER THAT WAS GIVEN"))
    check("T10f evidence=None -> no evidence block (unchanged blind path)",
          "EVIDENCE THE AGENT GATHERED" not in body)

    # --- fuse() composition ---
    ground_escalate = ConfidenceReport(                       # case A: NO evidence
        0.0, VERDICT_ESCALATE, ("no evidence gathered this session",),
        had_evidence=False)
    ground_fabricated = ConfidenceReport(                     # case B: contradicts evidence
        0.0, VERDICT_ESCALATE,
        ("semantic: best-evidence cosine 0.00",
         "lexical: 0% of draft content words found in evidence",
         "evidence: 1 chunk(s)"), had_evidence=True)
    ground_confident = ConfidenceReport(
        0.82, VERDICT_CONFIDENT, ("semantic: 0.9", "lexical: 80%"), had_evidence=True)
    ground_uncertain = ConfidenceReport(
        0.40, VERDICT_UNCERTAIN, ("semantic: 0.6", "lexical: 20%"), had_evidence=True)

    sound = ReasoningReport(VERDICT_SOUND, "", "", ("agrees",))
    flawed = ReasoningReport(VERDICT_FLAWED, "dropped inversion", "Yes",
                             ("auditor found a logical flaw: dropped inversion",
                              "corrected: Yes"))
    unchecked = ReasoningReport(VERDICT_UNCHECKED, "", "", ("disabled",))

    # T11: FLAWED forces ESCALATE, flaw leads grounds (regardless of independence)
    f11 = fuse(ground_confident, flawed)
    check("T11 FLAWED -> ESCALATE", f11.verdict == VERDICT_ESCALATE and f11.score == 0.0,
          str(f11))
    check("T11b flaw leads grounds", "flaw" in f11.grounds[0], str(f11.grounds))

    # T12: a confidently-WRONG answer (FLAWED) no longer scores like a RIGHT
    # evidence-less one (the L383 fix). The SOUND lift requires an INDEPENDENT
    # critic — a self-audit's SOUND must not upgrade (HIGH-finding fix).
    right_pure = fuse(ground_escalate, sound, critic_independent=True)   # right, no evidence
    wrong_pure = fuse(ground_escalate, flawed)                          # wrong, no evidence
    check("T12 right(SOUND,independent)=UNCERTAIN vs wrong(FLAWED)=ESCALATE distinguishable",
          right_pure.verdict == VERDICT_UNCERTAIN
          and wrong_pure.verdict == VERDICT_ESCALATE
          and right_pure.verdict != wrong_pure.verdict,
          f"{right_pure.verdict} vs {wrong_pure.verdict}")
    check("T12b independent SOUND lift clears the uncertain floor",
          right_pure.score >= 0.30, str(right_pure.score))

    # T13: UNCHECKED -> grounding returned UNCHANGED (no regression / clean off)
    f13 = fuse(ground_confident, unchecked)
    check("T13 UNCHECKED identity", f13 is ground_confident, str(f13))

    # T14: SOUND + CONFIDENT stays CONFIDENT; grounding LEADS, SOUND is appended
    f14 = fuse(ground_confident, sound, critic_independent=True)
    check("T14 SOUND+CONFIDENT stays CONFIDENT, grounding leads",
          f14.verdict == VERDICT_CONFIDENT
          and f14.grounds[0] == ground_confident.grounds[0]
          and any("SOUND" in g for g in f14.grounds), str(f14))

    # T15: SOUND + UNCERTAIN stays UNCERTAIN (not lifted past its band)
    f15 = fuse(ground_uncertain, sound, critic_independent=True)
    check("T15 SOUND+UNCERTAIN stays UNCERTAIN", f15.verdict == VERDICT_UNCERTAIN,
          str(f15))

    # T16 (HIGH-finding fix): a SELF-audit SOUND (critic_independent=False, the
    # live default) must NOT upgrade a no-evidence ESCALATE — no false-SOUND
    # confidence regression. Verdict + score unchanged; note flags self-audit.
    f16 = fuse(ground_escalate, sound, critic_independent=False)
    check("T16 self-audit SOUND does NOT lift ESCALATE",
          f16.verdict == VERDICT_ESCALATE and f16.score == ground_escalate.score,
          str(f16))
    check("T16b self-audit grounds flag the weak signal",
          any("self-audit" in g for g in f16.grounds), str(f16.grounds))

    # T17 (MEDIUM-finding fix): even an INDEPENDENT SOUND must NOT lift a
    # had_evidence ESCALATE (that is the fabrication / contradicts-the-facts
    # signal) — and the fabrication finding must keep LEADING the grounds.
    f17 = fuse(ground_fabricated, sound, critic_independent=True)
    check("T17 independent SOUND does NOT lift a had_evidence (fabrication) ESCALATE",
          f17.verdict == VERDICT_ESCALATE, str(f17))
    check("T17b fabrication finding still leads the surfaced grounds",
          "cosine 0.00" in f17.grounds[0], str(f17.grounds))

    # T18: the independence gate is real — the SAME no-evidence SOUND case lands
    # on DIFFERENT verdicts depending on critic independence.
    check("T18 independence gate flips the verdict",
          fuse(ground_escalate, sound, critic_independent=False).verdict
          != fuse(ground_escalate, sound, critic_independent=True).verdict)

    # --- ContradictionJudge (4.5.2) ---

    # T19: CONTRADICTION verdict parsed, names the clash
    cj_contra = ContradictionJudge(scripted(
        '{"verdict": "CONTRADICTION", "which": "resistor value: 220 ohms vs 330 ohms"}'))
    r19 = run(cj_contra.judge("what resistor?", ("gpt-4o-mini", "220 ohms"), ("deepseek-chat", "330 ohms")))
    check("T19 CONTRADICTION parsed", r19.verdict == VERDICT_CONTRADICTION, str(r19))
    check("T19b which names the clash", "220" in r19.which and "330" in r19.which, r19.which)

    # T20: COMPATIBLE verdict parsed, which is empty
    cj_compat = ContradictionJudge(scripted('{"verdict": "COMPATIBLE", "which": ""}'))
    r20 = run(cj_compat.judge("q", ("a", "answer one"), ("b", "answer two, worded differently")))
    check("T20 COMPATIBLE parsed", r20.verdict == VERDICT_COMPATIBLE, str(r20))
    check("T20b which empty on COMPATIBLE", r20.which == "", r20.which)

    # T21: babble (no JSON) -> UNCHECKED
    cj_babble = ContradictionJudge(scripted("these seem fine to me"))
    r21 = run(cj_babble.judge("q", ("a", "x"), ("b", "y")))
    check("T21 no-JSON -> UNCHECKED", r21.verdict == VERDICT_UNCHECKED, str(r21))

    # T22: judge raises -> UNCHECKED, never crashes
    def judge_boom(messages: List[Dict[str, str]]) -> str:
        raise RuntimeError("budget exhausted")
    r22 = run(ContradictionJudge(judge_boom).judge("q", ("a", "x"), ("b", "y")))
    check("T22 judge exception -> UNCHECKED", r22.verdict == VERDICT_UNCHECKED, str(r22))
    check("T22b grounds explicitly say NOT agreement",
          "NOT as agreement" in r22.grounds[0], str(r22.grounds))

    # T23: no judge wired -> UNCHECKED (disabled, graceful)
    r23 = run(ContradictionJudge(None).judge("q", ("a", "x"), ("b", "y")))
    check("T23 no judge -> UNCHECKED", r23.verdict == VERDICT_UNCHECKED, str(r23))

    # T24: one empty answer -> UNCHECKED without calling the judge
    called24 = {"n": 0}
    def counting_judge(messages: List[Dict[str, str]]) -> str:
        called24["n"] += 1
        return '{"verdict": "COMPATIBLE"}'
    r24 = run(ContradictionJudge(counting_judge).judge("q", ("a", "x"), ("b", "   ")))
    check("T24 empty answer -> UNCHECKED, judge not called",
          r24.verdict == VERDICT_UNCHECKED and called24["n"] == 0, str((r24, called24)))

    # T25: unknown verdict -> UNCHECKED (never silently COMPATIBLE)
    cj_unknown = ContradictionJudge(scripted('{"verdict": "MAYBE", "which": ""}'))
    r25 = run(cj_unknown.judge("q", ("a", "x"), ("b", "y")))
    check("T25 unknown verdict -> UNCHECKED", r25.verdict == VERDICT_UNCHECKED, str(r25))

    # T26: async judge (awaitable) handled
    async def ajudge(messages: List[Dict[str, str]]) -> str:
        return '{"verdict": "CONTRADICTION", "which": "test"}'
    r26 = run(ContradictionJudge(ajudge).judge("q", ("a", "x"), ("b", "y")))
    check("T26 async judge", r26.verdict == VERDICT_CONTRADICTION, str(r26))

    # T27: messages carry the question + both attributed answers
    msgs27 = _build_contradiction_messages("is X true?", "modelA", "yes", "modelB", "no")
    body27 = msgs27[-1]["content"]
    check("T27 question + both models + both answers present",
          "is X true?" in body27 and "modelA" in body27 and "modelB" in body27
          and "yes" in body27 and "no" in body27, body27[:200])

    # --- resolve_conflict() (4.5.1 + 4.5.2 combination) ---

    no_diverge = DivergenceReport(diverged=False, agreement=1.0, pairwise=(),
                                  numeric_conflicts=(), grounds=("sources agree",))
    diverged = DivergenceReport(diverged=True, agreement=0.2, pairwise=(("a", "b", 0.2),),
                                numeric_conflicts=(), grounds=("semantic divergence: low cosine",))

    contradiction = ContradictionReport(VERDICT_CONTRADICTION, "resistor value",
                                        ("judge found a contradiction: resistor value",))
    compatible = ContradictionReport(VERDICT_COMPATIBLE, "",
                                     ("judge found the answers compatible",))
    unchecked_j = ContradictionReport(VERDICT_UNCHECKED, "", ("judge call failed",))

    # T28: no divergence -> no conflict regardless of judgment
    c28, d28 = resolve_conflict(no_diverge, contradiction)
    check("T28 no divergence -> no conflict even if judge somehow ran",
          c28 is False and "no divergence" in d28, str((c28, d28)))

    # T29: divergence + CONTRADICTION -> conflict stands, names the clash
    c29, d29 = resolve_conflict(diverged, contradiction)
    check("T29 divergence + CONTRADICTION -> conflict", c29 is True and "resistor value" in d29, str((c29, d29)))

    # T30 (the asymmetry): divergence + COMPATIBLE -> cleared
    c30, d30 = resolve_conflict(diverged, compatible)
    check("T30 divergence + COMPATIBLE -> cleared", c30 is False and "cleared" in d30, str((c30, d30)))

    # T31 (the fail-closed floor): divergence + UNCHECKED -> conflict STILL stands
    c31, d31 = resolve_conflict(diverged, unchecked_j)
    check("T31 divergence + UNCHECKED -> conflict stands (errored judge != agreement)",
          c31 is True, str((c31, d31)))

    total = passed + len(failed)
    print(f"\n  Passed: {passed}/{total}")
    if failed:
        for f_ in failed:
            print(f"  {f_}")
        print("=" * 70)
        raise SystemExit(1)
    print(f"  All {total} reasoning smoke tests passed.")
    print("=" * 70)


if __name__ == "__main__":
    _run_self_test()
