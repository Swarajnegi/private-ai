"""
aggregator.py — Response Aggregation (Stage 4.4: bounded fan-out + synthesis).

LAYER: Brain (Orchestration — escalation-only multi-model fan-out)

Import with:
    from jarvis_core.brain.aggregator import (
        SourcedAnswer, AggregatedAnswer, fan_out, aggregate,
    )

=============================================================================
THE BIG PICTURE
=============================================================================

Single-Model-First (Strategic Principle 1) holds by default: one target
answers, ConfidenceGate grades it, done. Fan-out costs N× and is NEVER the
default path — it fires only when the orchestrator decides the single answer
wasn't good enough (gate failure / low route confidence / an explicit flag).

This module owns exactly the escalation machinery, in two stages:

  fan_out()  — call 2-3 peer targets CONCURRENTLY, capture every answer
               (including failures) as a SourcedAnswer. Never raises: a target
               that errors, times out, or hits its budget gate just produces
               ok=False, its sibling still returns. This is deliberately NOT
               ModelPool.acall() — the pool stops at the FIRST healthy target
               (failover semantics); aggregation needs the OPPOSITE: every
               answer, so downstream can compare them.

  aggregate() — turn N SourcedAnswers into ONE AggregatedAnswer:
               1. quality filter (4.4.3): drop failed/degenerate answers,
                  LOG every drop (no silent truncation).
               2. voting (4.4.2, ₹0): short-form answers (yes/no, a number, a
                  single entity) that already agree need no LLM call.
               3. synthesis (4.4.2, one LLM call): only when voting can't
                  resolve it — an injected synthesizer merges survivors into
                  one attributed answer, PRESERVING disagreement rather than
                  averaging it away (Stage 4.5's job is to act on that).

Budget safety is inherited, not reinvented: every fanned target already shares
the Stage 4.3.2 CostTracker, so an over-budget fan-out call degrades to
ok=False through the existing per-client LLMBudgetExceeded gate — it can never
silently overspend.

=============================================================================
THE FLOW
=============================================================================

STEP 1: fan_out(targets, messages) -> asyncio.gather(..., return_exceptions=True)
        over each target.ensure_ready() -> target.llm_call(messages). Any
        exception -> SourcedAnswer(ok=False, error=...); success ->
        SourcedAnswer(ok=True, answer=...).
        |
STEP 2: aggregate(question, sources, ...): drop ok=False / degenerate answers
        (logged). 0 survive -> passthrough (primary answer untouched). 1
        survives -> single. >=2 survive:
        |
STEP 3: try VOTING first (short-form, already-agreeing answers, ₹0). If that
        doesn't resolve it, call the injected SYNTHESIZER once -> one
        attributed answer.
        |
STEP 4: AggregatedAnswer(answer, method, sources, attribution, agreement).

=============================================================================
"""

from __future__ import annotations

import asyncio
import inspect
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, Union

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # standalone-run safety

from jarvis_core.brain.targets import RouteTarget

LLMCall = Callable[[List[Dict[str, str]]], Union[str, Awaitable[str]]]

_MAX_PEERS = 3                  # hard cap — fan-out is escalation, not a swarm
_MAX_VOTE_ANSWER_CHARS = 40      # short-form ceiling for the ₹0 voting path


# =============================================================================
# Part 1: CONTRACT (frozen)
# =============================================================================

@dataclass(frozen=True)
class SourcedAnswer:
    """One target's answer to a fanned-out question — success or failure,
    always present so nothing silently vanishes from the comparison."""
    model: str
    answer: str
    ok: bool
    latency_s: float = 0.0
    error: str = ""
    cost_usd: float = 0.0


@dataclass(frozen=True)
class AggregatedAnswer:
    """The escalation path's single output. `method` names HOW it was reached
    so callers/logs never have to guess: vote | synthesis | single | passthrough."""
    answer: str
    method: str
    sources: Tuple[SourcedAnswer, ...]
    attribution: str
    agreement: float = 1.0


# =============================================================================
# Part 2: FAN-OUT (4.4.1)
# =============================================================================

def _is_degenerate(text: str) -> bool:
    """Same structural shape-check the orchestrator's output gate uses — a raw
    tool-call fragment or empty string is never a usable answer to vote/merge."""
    s = (text or "").strip()
    if not s:
        return True
    if s.startswith("["):
        return True
    if s.startswith("{") and ('"name"' in s or '"arguments"' in s):
        return True
    return False


async def _call_one(target: RouteTarget, messages: List[Dict[str, str]],
                     clock: Callable[[], float]) -> SourcedAnswer:
    t0 = clock()
    try:
        await target.ensure_ready()
        out = target.llm_call(messages)
        if inspect.isawaitable(out):
            out = await out
        text = str(out)
        cost = 0.0
        try:
            cost = float((target.ledger_summary() or {}).get("spend_usd") or 0.0)
        except Exception:
            pass
        return SourcedAnswer(model=target.name, answer=text, ok=not _is_degenerate(text),
                             latency_s=clock() - t0, cost_usd=cost,
                             error="" if not _is_degenerate(text) else "degenerate answer")
    except Exception as e:  # noqa: BLE001 — a fanned peer's failure must not sink its siblings
        return SourcedAnswer(model=target.name, answer="", ok=False,
                             latency_s=clock() - t0, error=f"{type(e).__name__}: {e}")


async def fan_out(
    targets: List[RouteTarget],
    messages: List[Dict[str, str]],
    *,
    max_peers: int = _MAX_PEERS,
    clock: Callable[[], float] = time.monotonic,
) -> List[SourcedAnswer]:
    """
    Call up to `max_peers` targets CONCURRENTLY; every one returns a
    SourcedAnswer regardless of outcome. Never raises.

    EXECUTION FLOW:
    1. Bound the peer list (fan-out is escalation, never a swarm).
    2. asyncio.gather each target's ensure_ready()+llm_call, catching per-call.
    3. Return one SourcedAnswer per attempted target, in the same order.
    """
    peers = list(targets)[:max_peers]
    if not peers:
        return []
    return list(await asyncio.gather(*(_call_one(t, messages, clock) for t in peers)))


# =============================================================================
# Part 3: QUALITY FILTER + VOTING + SYNTHESIS (4.4.3, 4.4.2)
# =============================================================================

def _normalize_short(text: str) -> str:
    return re.sub(r"[^\w]+", "", text.strip().lower())


def _try_vote(survivors: List[SourcedAnswer]) -> Optional[AggregatedAnswer]:
    """₹0 path: if every survivor is short-form AND they already agree once
    normalized, no LLM call is needed. Returns None when voting can't resolve
    it (mixed lengths, or genuine disagreement — that's synthesis's job)."""
    if not all(len(s.answer.strip()) <= _MAX_VOTE_ANSWER_CHARS for s in survivors):
        return None
    normalized = [_normalize_short(s.answer) for s in survivors]
    if len(set(normalized)) != 1:
        return None  # they don't actually agree — do not paper over a split
    winner = survivors[0].answer.strip()
    attribution = "; ".join(f"{s.model} agrees" for s in survivors)
    return AggregatedAnswer(answer=winner, method="vote", sources=tuple(survivors),
                            attribution=attribution, agreement=1.0)


_DEFAULT_SYNTHESIS_SYSTEM = (
    "You merge several models' answers to the SAME question into ONE final "
    "answer. Attribute claims to their source model by name where the models "
    "differ. Do NOT average away or hide a disagreement — if the sources "
    "genuinely conflict, say so explicitly and name which model said what. "
    "Be concise; do not repeat a claim every source agrees on more than once."
)


def _build_synthesis_messages(question: str, survivors: List[SourcedAnswer]) -> List[Dict[str, str]]:
    body = "\n\n".join(f"[{s.model}]: {s.answer.strip()}" for s in survivors)
    user = (f"QUESTION:\n{question}\n\nANSWERS FROM {len(survivors)} MODELS:\n{body}\n\n"
            "Produce ONE merged, attributed answer.")
    return [{"role": "system", "content": _DEFAULT_SYNTHESIS_SYSTEM},
            {"role": "user", "content": user}]


async def aggregate(
    question: str,
    primary: SourcedAnswer,
    sources: List[SourcedAnswer],
    *,
    synthesizer: Optional[LLMCall] = None,
    agreement: float = 1.0,
    logger: Callable[[str], None] = lambda _m: None,
) -> AggregatedAnswer:
    """
    Turn the primary answer + N fanned peer answers into ONE AggregatedAnswer.

    EXECUTION FLOW:
    1. Quality filter: drop ok=False / degenerate sources, LOG each drop.
    2. 0 survivors -> passthrough (primary, untouched). 1 -> single.
    3. >=2 -> try voting (₹0); if it can't resolve, call the synthesizer once.
    """
    all_sources = [primary] + list(sources)
    survivors = []
    for s in all_sources:
        if not s.ok or _is_degenerate(s.answer):
            logger(f"aggregate: dropped '{s.model}' ({s.error or 'degenerate answer'})")
            continue
        survivors.append(s)

    if not survivors:
        return AggregatedAnswer(answer=primary.answer, method="passthrough",
                                sources=tuple(all_sources), attribution="no usable source survived filtering",
                                agreement=agreement)
    if len(survivors) == 1:
        only = survivors[0]
        return AggregatedAnswer(answer=only.answer, method="single",
                                sources=tuple(all_sources), attribution=f"only '{only.model}' survived filtering",
                                agreement=agreement)

    voted = _try_vote(survivors)
    if voted is not None:
        return AggregatedAnswer(answer=voted.answer, method="vote",
                                sources=tuple(all_sources), attribution=voted.attribution,
                                agreement=agreement)

    if synthesizer is None:
        # No synthesizer wired — degrade to the primary rather than crash;
        # attribution is honest about why nothing was merged.
        return AggregatedAnswer(answer=primary.answer, method="passthrough",
                                sources=tuple(all_sources),
                                attribution="sources disagree but no synthesizer was configured",
                                agreement=agreement)

    messages = _build_synthesis_messages(question, survivors)
    out = synthesizer(messages)
    if inspect.isawaitable(out):
        out = await out
    merged = str(out).strip()
    attribution = "synthesized from: " + ", ".join(s.model for s in survivors)
    return AggregatedAnswer(answer=merged, method="synthesis",
                            sources=tuple(all_sources), attribution=attribution,
                            agreement=agreement)


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS (offline — fake targets, no network)
# =============================================================================

def _run_self_test() -> None:
    import asyncio as _asyncio
    from jarvis_core.brain.targets import TargetKind

    print("=" * 70)
    print("  aggregator.py -- Smoke Tests")
    print("=" * 70)
    passed = 0
    failed: List[str] = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        nonlocal passed
        if cond:
            passed += 1
        else:
            failed.append(f"FAIL: {name}" + (f" ({hint})" if hint else ""))

    def run(coro):
        return _asyncio.run(coro)

    class FakeTarget(RouteTarget):
        """Scriptable RouteTarget: behavior in {'ok', 'raise', 'degenerate'}."""
        def __init__(self, name, behavior="ok", reply=None, cost=0.0):
            self.name = name
            self.kind = TargetKind.API_MODEL
            self.profile = None
            self._behavior = behavior
            self._reply = reply if reply is not None else f"{name}:ANSWER"
            self._cost = cost
            self.calls = 0
        @property
        def llm_call(self):
            def _c(messages):
                self.calls += 1
                if self._behavior == "raise":
                    raise RuntimeError("boom")
                if self._behavior == "degenerate":
                    return "[]"
                return self._reply
            return _c
        async def ensure_ready(self):
            pass
        async def release(self):
            pass
        def ledger_summary(self):
            return {"model": self.name, "calls": self.calls, "spend_usd": self._cost}

    # ---- fan_out() ----------------------------------------------------------

    # T1: two healthy targets -> two SourcedAnswers, both ok
    r1 = run(fan_out([FakeTarget("A"), FakeTarget("B")], [{"role": "user", "content": "q"}]))
    check("T1 two ok targets -> 2 SourcedAnswers", len(r1) == 2 and all(s.ok for s in r1), str(r1))

    # T2: one raises, sibling still returns
    r2 = run(fan_out([FakeTarget("A", "raise"), FakeTarget("B")], [{"role": "user", "content": "q"}]))
    ok_map = {s.model: s.ok for s in r2}
    check("T2 one raises, sibling ok", ok_map == {"A": False, "B": True}, str(ok_map))
    a2 = next(s for s in r2 if s.model == "A")
    check("T2b failure captures error text", "boom" in a2.error, a2.error)

    # T3: all raise -> list of failures, fan_out never raises
    r3 = run(fan_out([FakeTarget("A", "raise"), FakeTarget("B", "raise")], [{"role": "user", "content": "q"}]))
    check("T3 all-fail -> no exception, all ok=False", len(r3) == 2 and not any(s.ok for s in r3), str(r3))

    # T4: latency recorded (non-negative float)
    r4 = run(fan_out([FakeTarget("A")], [{"role": "user", "content": "q"}]))
    check("T4 latency recorded", r4[0].latency_s >= 0.0, str(r4[0].latency_s))

    # T5: empty target list -> []
    r5 = run(fan_out([], [{"role": "user", "content": "q"}]))
    check("T5 empty targets -> []", r5 == [])

    # T5b: max_peers caps the fan-out
    r5b = run(fan_out([FakeTarget("A"), FakeTarget("B"), FakeTarget("C"), FakeTarget("D")],
                      [{"role": "user", "content": "q"}], max_peers=2))
    check("T5b max_peers caps fan-out", len(r5b) == 2, str(len(r5b)))

    # ---- aggregate() ---------------------------------------------------------

    primary_ok = SourcedAnswer(model="primary", answer="42", ok=True)

    # T6: unanimous short-form survivors -> vote, no synthesizer call needed
    called = {"n": 0}
    def counting_synth(messages):
        called["n"] += 1
        return "SHOULD NOT BE CALLED"
    r6 = run(aggregate("what is the answer?", primary_ok,
                       [SourcedAnswer(model="peer1", answer="42", ok=True),
                        SourcedAnswer(model="peer2", answer="42", ok=True)],
                       synthesizer=counting_synth))
    check("T6 unanimous short-form -> vote", r6.method == "vote" and r6.answer == "42", str(r6))
    check("T6b synthesizer NOT called on a clean vote", called["n"] == 0, str(called))

    # T7: long-form disagreeing survivors -> synthesis, with a scripted synthesizer
    def scripted_synth(messages):
        return "Model A says X; Model B says Y — they disagree on the specific number."
    long_primary = SourcedAnswer(model="primary", answer="The current-limiting resistor should be about 220 ohms for a standard 5mm LED.", ok=True)
    long_peer = SourcedAnswer(model="peer1", answer="You need roughly 330 ohms depending on the LED's forward voltage and supply.", ok=True)
    r7 = run(aggregate("what resistor value?", long_primary, [long_peer], synthesizer=scripted_synth))
    check("T7 disagreeing long-form -> synthesis", r7.method == "synthesis", str(r7))
    check("T7b attribution names both sources", "primary" in r7.attribution and "peer1" in r7.attribution, r7.attribution)
    check("T7c merged answer carries the synthesizer's text", "disagree" in r7.answer, r7.answer)

    # T8: EVERY source (including primary) fails filtering -> passthrough,
    # falling back to the primary's raw answer as the safety net.
    bad_primary = SourcedAnswer(model="primary", answer="[]", ok=True)  # degenerate shape
    r8 = run(aggregate("q", bad_primary,
                       [SourcedAnswer(model="peer1", answer="", ok=False, error="boom"),
                        SourcedAnswer(model="peer2", answer="[]", ok=True)]))
    check("T8 zero survivors -> passthrough falls back to primary",
          r8.method == "passthrough" and r8.answer == "[]", str(r8))

    # T9: exactly one usable survivor -> single
    r9 = run(aggregate("q", SourcedAnswer(model="primary", answer="", ok=False, error="died"),
                       [SourcedAnswer(model="peer1", answer="the real answer", ok=True)]))
    check("T9 one survivor -> single", r9.method == "single" and r9.answer == "the real answer", str(r9))

    # T10: every drop is logged (no silent truncation)
    logs: List[str] = []
    run(aggregate("q", primary_ok,
                  [SourcedAnswer(model="peer1", answer="", ok=False, error="timeout"),
                   SourcedAnswer(model="peer2", answer="42", ok=True)],
                  logger=logs.append))
    check("T10 dropped source logged", any("peer1" in l and "timeout" in l for l in logs), str(logs))

    # T11: no synthesizer configured on a real disagreement -> honest passthrough, not a crash
    r11 = run(aggregate("q", long_primary, [long_peer]))  # synthesizer=None
    check("T11 no synthesizer -> passthrough with honest attribution",
          r11.method == "passthrough" and "no synthesizer" in r11.attribution, str(r11))

    # T12: agreement score threads through unchanged
    r12 = run(aggregate("q", primary_ok, [SourcedAnswer(model="peer1", answer="42", ok=True)], agreement=0.42))
    check("T12 agreement threads through", r12.agreement == 0.42, str(r12.agreement))

    # T13: all sources (including dropped) are retained on the result for audit
    r13 = run(aggregate("q", primary_ok,
                        [SourcedAnswer(model="peer1", answer="", ok=False, error="boom"),
                         SourcedAnswer(model="peer2", answer="42", ok=True)]))
    check("T13 sources retains dropped entries for audit", len(r13.sources) == 3, str(len(r13.sources)))

    total = passed + len(failed)
    print(f"\n  Passed: {passed}/{total}")
    if failed:
        for f_ in failed:
            print(f"  {f_}")
        print("=" * 70)
        raise SystemExit(1)
    print(f"  All {total} aggregator smoke tests passed.")
    print("=" * 70)


if __name__ == "__main__":
    _run_self_test()
