"""
orchestrator.py — The Spine, v0 (Stage 4.0.4b: inhale → solve → gate → distill).

LAYER: Brain (orchestration — the Final Boss home)

Run with:
    PYTHONPATH=js-development python3 -m jarvis_core.brain.orchestrator                  # offline smoke tests
    PYTHONPATH=js-development python3 -m jarvis_core.brain.orchestrator --ask "..."     # ask JARVIS (live)
    PYTHONPATH=js-development python3 -m jarvis_core.brain.orchestrator --awareness     # Gate A (live)

=============================================================================
THE BIG PICTURE
=============================================================================

The terminal entry point used to live inside the LLM client as `_ask` —
a bare Mind with a calculator, one ChromaDB collection, and no breath of the
travelling consciousness (KB L324). It moved HERE because the brain layer
composes the agent layer, never the reverse — and because the spine is where
the Cognitive Control Loop closes:

    INHALE   boot.assemble_mind: psyche + autobiography tools + live state
    SOLVE    Mind.solve (the frozen Stage 3 runtime, untouched)
    GATE     ConfidenceGate grades the answer against the evidence the
             session actually gathered — every answer ships with a score
    EXHALE   capture parity (this session enters observation_queue.jsonl —
             L324 gap 3) + SessionMemoryWriter distills it into the KB

In v0 the spine routes to ONE target (the env-configured OpenRouter model).
The Router (4.2) slots in between INHALE and SOLVE without changing this
file's contract — that is the point of building the spine first.

=============================================================================
THE FLOW
=============================================================================

STEP 1: build/receive the LLMCall; auto-pick a free model if unconfigured.
        |
STEP 2: open JarvisMemoryStore (context manager — held through solve,
        closed in finally; absence is a note, never a crash).
        |
STEP 3: assemble_mind (boot inhale) -> Mind.solve(question).
        |
STEP 4: ConfidenceGate.grade(answer, tool-result evidence) -> stamp verdict.
        |
STEP 5: exhale — append the turn to the observation queue + distill an
        Episodic into the KB. Print answer, confidence, ledger. Return
        AskResult.

=============================================================================
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # standalone-run safety

from jarvis_core.config import KB_PATH
from jarvis_core.agent.capture import (
    QUEUE_PATH, append_observation, build_observation, guess_domain,
    strip_harness_blocks,
)
from jarvis_core.brain.llm_client import build_llm_call
from jarvis_core.agent.mind import MindResult
from jarvis_core.agent.react import TERMINATED_ERROR, TERMINATED_MAX_ITERATIONS
from jarvis_core.brain.boot import BootReport, assemble_mind
from jarvis_core.brain.confidence import ConfidenceGate, ConfidenceReport
from jarvis_core.brain.reasoning import (
    ReasoningGate, ReasoningReport, fuse, VERDICT_UNCHECKED,
)
from jarvis_core.brain.model_profiles import ProfileRegistry
from jarvis_core.brain.boot import full_toolset, default_toolset
from jarvis_core.brain.conversation import ConversationStore, resolve_terminal_session
from jarvis_core.brain.permgate import (
    build_permission_context, terminal_ask_handler, allow_all_ask_handler,
)
from jarvis_core.brain.session_writer import SessionMemoryWriter, SessionRecord

_IST = timezone(timedelta(hours=5, minutes=30))
_DEFAULT_BUDGET_USD = 0.10
# An independent critic makes ~1 cheap call; cap it at a fraction of the session
# budget so enabling it widens the combined ceiling to 1.5x, not 2x.
_CRITIC_BUDGET_FRACTION = 0.5

# One terminal session per process — every ask in this process shares it, so
# recall groups them into one chat exactly like a Claude Code session id does.
_SESSION_ID = f"terminal-{datetime.now(_IST).strftime('%Y%m%dT%H%M%S')}-{os.getpid()}"


# =============================================================================
# Part 1: CONTRACT (frozen)
# =============================================================================

@dataclass(frozen=True)
class AskResult:
    """Everything one spine pass produced — answer, judgement, bookkeeping."""
    question: str
    answer: str
    verdict: str
    confidence_score: float
    grounds: Tuple[str, ...]
    ledger: Dict[str, Any]
    boot: BootReport
    mind: MindResult
    captured: bool
    distill_status: str
    reasoning_verdict: str = VERDICT_UNCHECKED
    reasoning_flaw: str = ""


# =============================================================================
# Part 2: THE SPINE
# =============================================================================

def _open_store(printer: Callable[[str], None]) -> Optional[Any]:
    """The memory store, OPENED (it is a context manager) — or None, noted."""
    try:
        from jarvis_core.memory.store import JarvisMemoryStore
        store = JarvisMemoryStore()
        store.__enter__()
        return store
    except Exception as e:
        printer(f"  (KB search unavailable: {type(e).__name__}: {e})")
        return None


def _close_store(store: Optional[Any]) -> None:
    if store is not None:
        try:
            store.__exit__(None, None, None)
        except Exception:
            pass


def _evidence_from(mind_result: MindResult) -> List[str]:
    """The session's verified facts: successful tool outputs, in call order."""
    out: List[str] = []
    for _tc, tr in mind_result.react.tool_calls:
        if getattr(tr, "error", None):
            continue
        if tr.output is not None and str(tr.output).strip():
            out.append(str(tr.output))
    return out


def _evidence_digest(items: List[str], per_item: int = 700, total: int = 3500) -> str:
    """A compact, bounded digest of gathered tool outputs for the reasoning critic
    so it judges the answer against what WAS retrieved (not blind). Empty when no
    evidence — critique() then falls back to its blind path unchanged."""
    if not items:
        return ""
    parts: List[str] = []
    used = 0
    for i, it in enumerate(items, 1):
        chunk = f"[{i}] {str(it).strip()[:per_item]}"
        if used + len(chunk) > total:
            parts.append(f"… (+{len(items) - i + 1} more observations, truncated)")
            break
        parts.append(chunk)
        used += len(chunk)
    return "\n".join(parts)


def _is_unparsed_answer(text: str) -> bool:
    """True when the 'answer' is not prose but a raw/empty model artifact.

    The loop is supposed to repair botched tool calls (react.py), but defence in
    depth: never let a structured fragment reach the user, the KB, or the digest
    as if it were an answer (live repro 2026-06-12 — raw tool-call JSON printed
    as JARVIS's reply). Structural test only — NOT the confidence verdict, which
    is the known-anti-correlated v1 gate and would wrongly suppress good hedged
    answers (run 5's correct answer scored UNCERTAIN)."""
    s = (text or "").strip()
    if not s:
        return True
    if s.startswith("["):
        return True
    if s.startswith("{") and ('"name"' in s or '"arguments"' in s):
        return True
    return False


_UNPARSED_FALLBACK = (
    "I couldn't produce a clean answer this run — the underlying model's output "
    "didn't parse into a usable reply (a malformed tool call, not a retrieval "
    "miss). This is a per-model protocol gap (Sub-Phase 4.1), not a memory gap."
)
_UNPARSED_GROUNDS = (
    "answer did not parse into prose — model emitted a malformed/structured "
    "fragment; suppressed at the orchestrator output gate"
)


def _degenerate_diagnosis(result: MindResult) -> Tuple[str, str]:
    """Honest cause of a degenerate (unpresentable) answer, READ from the ReAct
    terminal state — not a single hardcoded guess.

    The old gate always blamed a malformed tool call. But the loop ALREADY records
    why it ended (react.terminated_reason / react.error): a budget kill, a provider
    error, and iteration-exhaustion are distinct causes that were all mislabelled a
    "per-model protocol gap (Sub-Phase 4.1)" — sending debugging to the wrong layer
    (live Sonnet run 2026-06-25: ledger said LLMBudgetExceeded, the gate said
    malformed-tool-call). Report the actual mechanism; never overclaim a cause.

    Returns (user_message, confidence_grounds)."""
    react = getattr(result, "react", None)
    reason = getattr(react, "terminated_reason", "") or ""
    err = (getattr(react, "error", "") or "").strip()
    if reason == TERMINATED_ERROR and err:
        if "budget" in err.lower():
            return (
                "I couldn't produce a clean answer this run — it hit the session "
                f"cost budget before finishing ({err}). Raise --budget for a costlier "
                "brain, or route to a cheaper model. This is a cost limit, not a "
                "retrieval or protocol failure.",
                f"terminated on budget before a final answer: {err}")
        return (
            "I couldn't produce a clean answer this run — the model/provider errored "
            f"mid-run ({err}); no clean reply was produced. Not a retrieval miss.",
            f"terminated on error before a final answer: {err}")
    if reason == TERMINATED_MAX_ITERATIONS:
        n = getattr(react, "iterations_used", 0)
        return (
            f"I couldn't produce a clean answer this run — the agent used all {n} "
            "reasoning steps without committing to a final answer (it didn't emit "
            "garbage, it just didn't converge). Not a retrieval miss.",
            f"terminated: max_iterations ({n}) reached with no final answer")
    return _UNPARSED_FALLBACK, _UNPARSED_GROUNDS


async def ask(
    question: str,
    llm_call: Optional[Any] = None,
    budget_usd: float = _DEFAULT_BUDGET_USD,
    capture: bool = True,
    distill: bool = True,
    inhale: bool = True,
    kb_path: Path = KB_PATH,
    queue_path: Optional[Path] = None,
    store_factory: Optional[Callable[[], Optional[Any]]] = None,
    gate: Optional[ConfidenceGate] = None,
    reasoning: bool = False,
    reasoning_gate: Optional[ReasoningGate] = None,
    critic_llm: Optional[Any] = None,
    critic_independent: bool = False,
    critic_model: Optional[str] = None,
    critic_factory: Optional[Callable[[str], Any]] = None,
    pool: Optional[Any] = None,
    targets: Optional[List[str]] = None,
    route_strategy: str = "balanced",
    route: bool = False,
    router: Optional[Any] = None,
    routing_ledger: Optional[Any] = None,
    model_stats_store: Optional[Any] = None,
    cost_tracker: Optional[Any] = None,
    writer: Optional[SessionMemoryWriter] = None,
    extra_tools: Optional[Dict[str, Any]] = None,
    clock: Optional[Callable[[], datetime]] = None,
    profile_path: Optional[Path] = None,
    registry: Optional[ProfileRegistry] = None,
    use_profile: bool = True,
    full: bool = False,
    permission_context: Optional[Any] = None,
    ask_handler: Optional[Any] = None,
    session: Optional[str] = None,
    new_session: bool = False,
    continue_window_hours: float = 2.0,
    conv_store: Optional[Any] = None,
    session_state_path: Optional[Path] = None,
    history: Optional[List[Dict[str, str]]] = None,
    printer: Callable[[str], None] = print,
) -> AskResult:
    """
    One full spine pass: inhale → solve → gate → exhale.

    EXECUTION FLOW:
    1. LLMCall ready (auto-pick free model if unconfigured).
    2. Store opened; Mind assembled via boot (psyche + autobiography + inhale).
    3. solve(); store closed in finally; tool lines printed (errors surfaced).
    4. ConfidenceGate grades answer vs evidence ("made it up?"); when reasoning
       is on, ReasoningGate audits the logic ("is it right?") and fuse() stamps
       one verdict — a FLAWED audit floors it to ESCALATE (KB L383).
    5. Capture parity append + Episodic distill (both fail-soft). Ledger printed.

    Returns:
        AskResult — the answer plus every judgement and bookkeeping fact.
    """
    # Resolve the LLM endpoint (4.1 W2). Priority:
    #   1. injected llm_call (tests/programmatic) — used directly, no pool.
    #   2. a ModelPool (injected `pool`, or built from `targets`) — multi-target
    #      health-scored failover; the spine drives pool.as_llm_call() and takes
    #      conduct from the PRIMARY (best) target's profile.
    #   3. default — a single auto-picked OpenRouter client (unchanged behavior).
    # Stage 4.2: intent routing (opt-in). When route=True and the caller has NOT
    # pinned a pool or explicit targets, the IntentRouter classifies the question ->
    # specialist codename -> an ordered, frontier-free target list, which feeds the
    # SAME pool-build path below. Explicit `targets` and an injected `pool` always
    # win (the guard), so existing flows are untouched. A directly-injected llm_call
    # still EXECUTES (the pool-build below requires llm_call is None) — routing then
    # only computes + logs the decision (telemetry); the CLI never injects llm_call.
    route_decision = None
    if route and targets is None and pool is None:
        from jarvis_core.brain.router import IntentRouter, RoutingConstraints
        active_router = router or IntentRouter()
        route_decision = active_router.route(
            question,
            constraints=RoutingConstraints(remaining_budget_usd=budget_usd),
            strategy=route_strategy)
        targets = list(route_decision.targets)

    route_pool = pool
    # Stage 4.3.1: resolved ONCE, unconditionally — both the load (only when a
    # pool is BUILT below) and the flush (fires whenever ANY pool exists, incl.
    # one passed in directly via `pool=`) must share one instance, exactly like
    # `routing_ledger` — otherwise a caller-injected override wouldn't reach
    # both sites, and tests that inject a `pool=` directly would silently fall
    # through to the real on-disk default at flush time.
    from jarvis_core.brain.model_stats import ModelStatsStore
    stats_store = model_stats_store if model_stats_store is not None else ModelStatsStore()
    if route_pool is None and targets and llm_call is None:
        from jarvis_core.brain.targets import OpenRouterTarget
        from jarvis_core.brain.model_pool import ModelPool
        from jarvis_core.agent.cost import CostTracker
        # Stage 4.3.2: ONE shared CostTracker across every target + the pool, so
        # the budget governor sees true AGGREGATE spend (each client records its
        # live-priced cost into it) — a per-client budget can't see failover
        # peers' spend. cost_tracker is injectable for test isolation (mirrors
        # model_stats_store); the CLI path builds it here from --budget.
        budget_tracker = cost_tracker if cost_tracker is not None else CostTracker(budget_usd=budget_usd)
        built = [OpenRouterTarget(m.strip(), budget_usd=budget_usd,
                                  registry=registry, use_profile=use_profile,
                                  cost_tracker=budget_tracker)
                 for m in targets if m and m.strip()]
        # Seed health from the last ask() call's flush, so a target still
        # cooling down from a recent 429 doesn't get retried cold just
        # because this is a fresh process invocation. Fail-soft — a load
        # error means "start cold," never a crash.
        try:
            initial_health = stats_store.load_latest()
        except Exception:
            initial_health = {}
        route_pool = ModelPool(built, strategy=route_strategy,
                               initial_health=initial_health,
                               cost_tracker=budget_tracker) if built else None

    # POLICY (resolved here, the host): per-model conduct profile by model id.
    # Boot is the MECHANISM that applies it — single resolution site, so the
    # 4.2 Router never competes with a second lookup (it just supplies the id).
    if route_pool is not None and llm_call is None:
        primary = route_pool.select()
        if primary is not None:
            await primary.ensure_ready()
        client = route_pool.as_llm_call(strategy=route_strategy)
        model = str(getattr(primary, "name", "") or route_pool.primary_model)
        # The pool callable is attribute-less; name it so boot's
        # getattr(llm_call,'model') (BootReport.model + the self-state inhale line)
        # reflects the routed primary model instead of '<auto>'.
        try:
            client.model = model
        except (AttributeError, TypeError):
            pass
        profile = getattr(primary, "profile", None) if use_profile else None
        profile_label = getattr(primary, "profile_label", "pooled") if use_profile else None
    else:
        client = llm_call or build_llm_call(budget_usd=budget_usd)
        if hasattr(client, "pick_free_model") and not getattr(client, "model", ""):
            await client.pick_free_model()
        model = str(getattr(client, "model", "") or "")
        profile = profile_label = None
        if use_profile:
            profile, profile_label = (registry or ProfileRegistry()).get(model)

    # Conversation memory (working memory across --ask): resolve a STABLE session
    # id (auto-continue the recent terminal thread, or mint fresh), load its recent
    # turns, and thread them as real prior messages. The resolved id also becomes
    # the capture session_id, so the observation queue groups terminal turns into
    # real conversations.
    cstore = conv_store if conv_store is not None else ConversationStore()
    sess = resolve_terminal_session(
        window_hours=continue_window_hours, new=new_session, explicit=session,
        state_path=session_state_path)
    hist = history if history is not None else cstore.load_recent(sess.session_id)

    store = store_factory() if store_factory is not None else _open_store(printer)

    # Policy resolved HERE (the host): build the toolset, derive the permission
    # context from it, attach the [y/N] handler — for EVERY mode, so the DEFAULT
    # toolset's file_read is repo-scope-gated (cloud-leak guard) just as the full
    # set's shell/exec are. Boot is the mechanism that applies them.
    prebuilt = (full_toolset(store=store, kb_path=kb_path, llm_call=client)
                if full else default_toolset(store=store, kb_path=kb_path, llm_call=client))
    p_ctx = permission_context or build_permission_context(prebuilt)
    p_handler = ask_handler or terminal_ask_handler
    gated = sorted(n for n, t in prebuilt.items()
                   if getattr(t, "requires_permission", False))

    sess_state = (f"continued, {len(hist)} prior turn(s)" if sess.continued
                  else "new")
    printer(f"  brain   : {model or '<scripted>'}")
    if route_decision is not None:
        printer(f"  route   : {route_decision.label} (conf {route_decision.confidence:.2f}) "
                f"-> {', '.join(route_decision.targets)}")
    if route_pool is not None and llm_call is None:
        printer(f"  pool    : {', '.join(route_pool._order)} "
                f"(strategy={route_strategy}, primary={model})")
    printer(f"  profile : {profile_label or 'none'}")
    printer(f"  session : {sess.session_id} ({sess_state})")
    printer(f"  tools   : {'full' if full else 'default'} ({len(prebuilt)})"
            f" | gated: {', '.join(gated) or 'none'}")
    printer(f"  query   : {question}")
    try:
        mind, boot_report = assemble_mind(
            llm_call=client, store=store, kb_path=kb_path, inhale=inhale,
            extra_tools=extra_tools, clock=clock,
            profile_path=profile_path, queue_path=queue_path,
            profile=profile, profile_label=(profile_label or "none"),
            tools_mode=("full" if full else "minimal"),
            prebuilt_tools=prebuilt,
            permission_context=p_ctx, ask_handler=p_handler,
        )
        result = await mind.solve(question, history=hist)
    finally:
        _close_store(store)

    for tc, tr in result.react.tool_calls:
        out = str(tr.error) if getattr(tr, "error", None) else str(tr.output)
        tag = "tool!ERR" if getattr(tr, "error", None) else "tool    "
        printer(f"  {tag}: {tc.name} -> {out[:140]}{'...' if len(out) > 140 else ''}")

    # Structural safety gate: a degenerate (raw/empty/tool-shaped) emission is
    # never presented, stored, or distilled as an answer. The honest fallback
    # — plus whatever evidence WAS retrieved — replaces it everywhere downstream.
    evidence = _evidence_from(result)
    degenerate = _is_unparsed_answer(result.answer)
    if degenerate:
        msg, grounds = _degenerate_diagnosis(result)
        found = f" Retrieved this session: {evidence[0][:200]}…" if evidence else ""
        answer = msg + found
        report = ConfidenceReport(0.0, "ESCALATE", (grounds,))
    else:
        answer = result.answer.strip()
        active_gate = gate or ConfidenceGate()
        report = active_gate.grade(answer, evidence)

    # Reasoning audit (Stage 4.5 epistemic control). The grounding gate above
    # answers "did you make it up?"; this answers "is your logic right?" — the
    # orthogonal axis it is STRUCTURALLY blind to (KB L383: a confidently-wrong
    # inverted-logic answer scored the same ESCALATE 0.00 as a right one). The
    # critic (the same metered client by default; injectable for a stronger
    # reasoner) re-derives independently against the conversation's rules; fuse()
    # forces FLAWED -> ESCALATE and lifts a SOUND-but-ungrounded answer out of the
    # falsely-dismissive ESCALATE so wrong is no longer indistinguishable from
    # right. Skipped on degenerate (nothing to audit) and when disabled.
    rreport = ReasoningReport(VERDICT_UNCHECKED, "", "", ("reasoning audit not run",))
    critic_client = None
    indep = critic_independent
    critic_desc = "self-audit"
    audited = reasoning and not degenerate
    if audited:
        if reasoning_gate is not None or critic_llm is not None:
            rgate = reasoning_gate or ReasoningGate(critic_llm)
            critic_desc = "independent: injected" if indep else "self-audit: injected"
        else:
            # Wave 2: a critic on a DIFFERENT model than the answerer does not share
            # its blind spot, so it is INDEPENDENT (KB L389: a same-model self-audit
            # is net-noise on the multi-turn reasoning it exists for — it false-flagged
            # a correct inverted-logic answer live). No critic model configured -> a
            # conservative same-model self-audit whose SOUND can never lift the verdict.
            cm = (critic_model or os.environ.get("OPENROUTER_CRITIC_MODEL") or "").strip()
            am = (model or "").strip()
            # Fail-closed independence: only TRUST a critic's SOUND to lift when we
            # can CONFIRM it is a genuinely different model — normalize both sides
            # (strip + case-fold; OpenRouter slugs are case-insensitive) and require a
            # known answerer id. A trailing-newline env var or unknown answerer must
            # never sneak a same-model self-audit through as "independent".
            distinct = bool(cm) and bool(am) and cm.lower() != am.lower()
            if distinct:
                factory = critic_factory or (
                    lambda m: build_llm_call(
                        budget_usd=round(budget_usd * _CRITIC_BUDGET_FRACTION, 6), model=m))
                try:
                    critic_client = factory(cm)
                    rgate = ReasoningGate(critic_client)
                    indep = True
                    critic_desc = f"independent: {cm}"
                except Exception as e:
                    # Building the second client failed (no key, bad id, provider
                    # lookup) — degrade to a conservative self-audit so the answer
                    # STANDS rather than crashing the ask (fail-closed, visible).
                    rgate = ReasoningGate(client)
                    indep = False
                    critic_client = None
                    critic_desc = f"self-audit (critic build failed: {type(e).__name__})"
            else:
                rgate = ReasoningGate(client)
                indep = False
                critic_desc = f"self-audit: {am or 'scripted'}"
        rreport = await rgate.critique(question, answer, context=hist,
                                       evidence=_evidence_digest(evidence))
        report = fuse(report, rreport, critic_independent=indep)

    printer(f"\n  JARVIS  : {answer}")
    printer(f"  confidence: {report.verdict} ({report.score:.2f}) — {report.grounds[0]}")
    if audited:
        printer(f"  reasoning : {rreport.verdict} [{critic_desc}] — {rreport.grounds[0]}")

    cwd = os.getcwd()
    captured = False
    if capture:
        try:
            obs = build_observation(
                event={"session_id": sess.session_id},
                turn={"user_text": strip_harness_blocks(question),
                      "assistant_summary": answer,
                      "model": model},
                cwd=cwd,
            )
            if obs is not None:
                obs["chat_label"] = "terminal-ask"   # not the repo dir name — the limb
                append_observation(obs, queue_path or QUEUE_PATH)
                captured = True
        except Exception as e:
            printer(f"  (capture skipped: {type(e).__name__}: {e})")

    # Conversation memory: persist this turn ONLY if the answer was real prose.
    # Gate on the STRUCTURAL degeneracy flag, NOT the confidence verdict — pure
    # chit-chat ("hi who are you") is ESCALATE-but-fine and MUST be threaded; only
    # the unparsed honest-fallback is skipped (no dangling half-turn, no feeding
    # "I couldn't produce a clean answer" back as context).
    if not degenerate:
        cstore.append_turn(sess.session_id, "user", strip_harness_blocks(question))
        cstore.append_turn(sess.session_id, "assistant", answer)

    ledger: Dict[str, Any] = {}
    if route_pool is not None and llm_call is None:
        # Pool mode: aggregate per-target spend; both a failed-then-failed-over
        # attempt and the success land on their respective target ledgers.
        try:
            ledger = route_pool.aggregate_ledger()
        except Exception:
            ledger = {}
    elif hasattr(client, "ledger_summary"):
        try:
            ledger = client.ledger_summary()
        except Exception:
            ledger = {}
    critic_ledger: Dict[str, Any] = {}
    if critic_client is not None and hasattr(critic_client, "ledger_summary"):
        try:
            critic_ledger = critic_client.ledger_summary()
        except Exception:
            critic_ledger = {}

    # Total session spend = answer + (independent) critic, so the distilled record
    # and the printed cost tell the truth when a second model audited.
    total_spend = (float(ledger.get("spend_usd") or 0.0)
                   + float(critic_ledger.get("spend_usd") or 0.0))

    distill_status = "skipped"
    if distill:
        active_writer = writer or SessionMemoryWriter(kb_path=kb_path)
        out = active_writer.write(SessionRecord(
            question=question, answer=answer, model=model,
            tools_used=tuple(tc.name for tc, _tr in result.react.tool_calls),
            spend_usd=total_spend,
            confidence_verdict=report.verdict, confidence_score=report.score,
            reasoning_verdict=rreport.verdict,
            domain=guess_domain(cwd, question + " " + answer),
        ))
        distill_status = str(out.get("status", "error"))

    if ledger:
        printer(f"  ledger  : {ledger}")
    if critic_ledger:
        printer(f"  critic  : {critic_ledger}")
    if route_pool is not None and llm_call is None:
        # One ask() drives several internal acalls (plan + ReAct + replan), so
        # last_events accumulates duplicates; collapse identical events so the
        # operator reads one story per question, not 2x-3x repeats. Events now
        # cover both failover walks AND the Stage-4.3.2 budget downshift, so the
        # label is generic ("pool ev") — each event string names its own kind.
        seen_ev: set = set()
        for ev in route_pool.last_events:
            key = str(ev)
            if key in seen_ev:
                continue
            seen_ev.add(key)
            printer(f"  pool ev : {ev}")

    # Stage 4.2.4: log the routing decision (append-only, fail-soft) — the Stage-5
    # Orchestrator-adapter training corpus. Only the query HASH is stored, never the
    # text. Outcome: error if the answer was degenerate, else ok.
    if route_decision is not None:
        try:
            from jarvis_core.brain.routing_ledger import RoutingLedger, RoutingRecord, query_hash
            rl = routing_ledger if routing_ledger is not None else RoutingLedger()
            rl.record(RoutingRecord(
                ts=datetime.now(_IST).isoformat(),
                query_hash=query_hash(question),
                label=route_decision.label,
                confidence=route_decision.confidence,
                target=model or (route_decision.targets[0] if route_decision.targets else ""),
                outcome="error" if degenerate else "ok",
                cost_usd=total_spend,
            ))
        except Exception as e:
            printer(f"  (routing-ledger skipped: {type(e).__name__}: {e})")

    # Stage 4.3.1: flush this call's final health snapshot (fail-soft, mirrors
    # the routing-ledger write immediately above) so the NEXT ask() call seeds
    # from here instead of starting every target cold.
    if route_pool is not None:
        try:
            stats_store.flush(datetime.now(_IST).isoformat(), route_pool.snapshot_health())
        except Exception as e:
            printer(f"  (model-stats flush skipped: {type(e).__name__}: {e})")

    return AskResult(
        question=question, answer=answer,
        verdict=report.verdict, confidence_score=report.score,
        grounds=report.grounds, ledger=ledger, boot=boot_report, mind=result,
        captured=captured, distill_status=distill_status,
        reasoning_verdict=rreport.verdict, reasoning_flaw=rreport.flaw,
    )


# =============================================================================
# Part 3: GATE A — THE AWARENESS HARNESS (L107 Definition of Done)
# =============================================================================

_AWARENESS_QUESTIONS: List[Tuple[str, str]] = [
    ("temporal", "What is today's date and time?"),
    ("recall", "What was I working on yesterday? Answer from your activity log."),
    ("teleological", "What should we work on next? Answer from the roadmap."),
    ("metacognitive", "What is the airspeed of an unladen swallow in my codebase? "
                      "Are you sure about your answer?"),
    ("autobiography", "What have we built till now, JARVIS? "
                      "Consult your knowledge base before answering."),
]


def _judge_awareness(label: str, r: AskResult, today_iso: str) -> Tuple[str, str]:
    """(PASS/FAIL/REVIEW, reason) — mechanical where decidable, honest where not."""
    ans = r.answer.lower()
    if label == "temporal":
        ok = today_iso in r.answer or _month_day_words(today_iso) in ans
        return ("PASS" if ok else "FAIL", "today's date appears in the answer")
    if label == "teleological":
        ok = any(k in ans for k in ("4.0", "4.1", "sub-phase", "roadmap", "wave"))
        return ("PASS" if ok else "FAIL", "answer names a roadmap item")
    if label == "metacognitive":
        ok = r.verdict in ("UNCERTAIN", "ESCALATE") or "uncertain" in ans or "no " in ans
        return ("PASS" if ok else "FAIL",
                f"nonsense question gated, verdict={r.verdict}")
    if label == "autobiography":
        used = {tc.name for tc, _ in r.mind.react.tool_calls}
        ok = "prior_self_consult" in used
        return ("PASS" if ok else "FAIL", f"consulted the KB (tools used: {sorted(used)})")
    if label == "recall":
        fired = "Recent cross-chat activity" in r.boot.providers_fired
        return ("PASS" if fired and r.answer.strip() else "REVIEW",
                "activity digest was inhaled; verify the content by eye")
    return ("REVIEW", "no mechanical check")


def _month_day_words(today_iso: str) -> str:
    d = datetime.fromisoformat(today_iso)
    return d.strftime("%B %-d").lower() if os.name != "nt" else d.strftime("%B %d").lower()


async def _awareness() -> int:
    today_iso = datetime.now(_IST).date().isoformat()
    rows: List[Tuple[str, str, str, str]] = []
    for label, q in _AWARENESS_QUESTIONS:
        print("\n" + "=" * 70)
        print(f"  GATE A [{label}]")
        print("=" * 70)
        r = await ask(q)
        verdict, reason = _judge_awareness(label, r, today_iso)
        rows.append((label, verdict, reason, r.answer.strip()[:90]))
    print("\n" + "=" * 70)
    print("  GATE A — AWARENESS SCORECARD")
    print("=" * 70)
    failures = 0
    for label, verdict, reason, head in rows:
        mark = {"PASS": "[PASS]", "FAIL": "[FAIL]", "REVIEW": "[REVIEW]"}[verdict]
        failures += verdict == "FAIL"
        print(f"  {mark:9s} {label:14s} {reason}")
        print(f"            -> {head}")
    print(f"\n  session : {_SESSION_ID} (check observation_queue.jsonl for capture parity)")
    print(f"  result  : {len(rows) - failures}/{len(rows)} "
          f"{'— GATE A HOLDS' if failures == 0 else '— GATE A FAILED'}")
    return 1 if failures else 0


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS (offline twin — scripted everything)
# =============================================================================

def _run_self_test() -> None:
    import json
    import tempfile

    print("=" * 70)
    print("  orchestrator.py -- Smoke Tests (offline twin)")
    print("=" * 70)
    passed = 0
    failed: List[str] = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        nonlocal passed
        if cond:
            passed += 1
        else:
            failed.append(f"FAIL: {name}" + (f" ({hint})" if hint else ""))

    FIXED = datetime(2026, 6, 12, 12, 0, tzinfo=_IST)

    def scripted(responses: List[str]):
        idx = [0]
        def llm(messages: List[Dict[str, str]]) -> str:
            i = idx[0]
            if i >= len(responses):
                return "DONE."
            idx[0] += 1
            return responses[i]
        llm.model = "scripted-brain"  # type: ignore[attr-defined]
        return llm

    def scripted_embed(texts: List[str]) -> List[List[float]]:
        return [[1.0, 0.0] for _ in texts]  # everything maximally similar

    async def scenario() -> None:
        nonlocal passed
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            # Isolate conversation memory to the temp dir for the whole scenario, so
            # tests never touch (or continue) the real terminal session/transcripts.
            import jarvis_core.brain.conversation as _conv
            _conv._CONV_DIR = tdp / "conv"
            _conv._SESSION_STATE = tdp / ".session.json"
            kb = tdp / "kb.jsonl"
            kb.write_text(json.dumps({
                "id": 1, "timestamp": FIXED.isoformat(), "type": "Decision",
                "tags": ["stage-4"], "expiry": "Permanent",
                "content": "Decision: Stage 4 Wave 1 builds the Cognitive Control Loop.",
            }) + "\n", encoding="utf-8")
            queue = tdp / "queue.jsonl"
            profile = tdp / "profile.md"
            profile.write_text("PROFILE-MARKER", encoding="utf-8")
            distilled: List[Dict[str, Any]] = []
            def fake_append(**kw: Any) -> Dict[str, Any]:
                distilled.append(kw)
                return {"status": "appended", "id": 950}
            lines: List[str] = []

            # T1-T9: the full spine on a scripted brain
            llm = scripted([
                json.dumps([{"tool_name": "prior_self_consult",
                             "description": "consult"}]),
                json.dumps({"name": "prior_self_consult",
                            "arguments": {"query": "Stage 4 Wave 1 Cognitive Control Loop"}}),
                "We built the Cognitive Control Loop in Stage 4 Wave 1.",
            ])
            r = await ask(
                "what have we built?", llm_call=llm, kb_path=kb, queue_path=queue,
                store_factory=lambda: None, gate=ConfidenceGate(embed_fn=scripted_embed),
                writer=SessionMemoryWriter(append_fn=fake_append),
                clock=lambda: FIXED, profile_path=profile, printer=lines.append,
            )
            check("T1 answer flows through", "Cognitive Control Loop" in r.answer)
            check("T2 confidence graded with evidence",
                  r.verdict == "CONFIDENT" and r.confidence_score > 0.5,
                  f"{r.verdict} {r.confidence_score}")
            check("T3 boot report attached (inhale fired)",
                  "Temporal" in r.boot.providers_fired and r.boot.model == "scripted-brain")
            check("T4 capture parity: queue gained the turn", r.captured is True)
            qrec = json.loads(queue.read_text(encoding="utf-8").splitlines()[0])
            check("T5 queue record shape",
                  qrec["session_id"].startswith("conv-")
                  and qrec["chat_label"] == "terminal-ask"
                  and qrec["model"] == "scripted-brain"
                  and "what have we built" in qrec["user_text"], str(qrec)[:200])
            check("T6 distill landed via the writer",
                  r.distill_status == "appended" and len(distilled) == 1
                  and distilled[0]["entry_type"] == "Episodic")
            check("T7 distill carries verdict + tools",
                  "CONFIDENT" in distilled[0]["content"]
                  and "prior_self_consult" in distilled[0]["content"])
            check("T8 printer narrated brain/tools/answer/confidence",
                  any(l.startswith("  brain") for l in lines)
                  and any("tool    : prior_self_consult" in l for l in lines)
                  and any(l.startswith("  confidence:") for l in lines), str(lines[:6]))
            check("T9 ledger tolerated absent (scripted llm has none)", r.ledger == {})

            # T10: tool errors surface as tool!ERR (printer), never hidden
            from jarvis_core.agent.tool import Tool, ToolInput, ToolResult
            from pydantic import Field
            class _In(ToolInput):
                q: str = Field(default="", description="x")
            class Boom(Tool):
                name = "boom"; description = "always errors"; input_schema = _In
                async def invoke(self, tool_input: _In) -> ToolResult:
                    return ToolResult(output=None, error="kaboom: handle me")
            llm10 = scripted([
                json.dumps([{"tool_name": "boom", "description": "x"}]),
                json.dumps({"name": "boom", "arguments": {"q": "x"}}),
                "Tool failed; cannot verify.",
            ])
            lines10: List[str] = []
            r10 = await ask(
                "trigger the error", llm_call=llm10, kb_path=kb, queue_path=queue,
                store_factory=lambda: None, gate=ConfidenceGate(embed_fn=scripted_embed),
                writer=SessionMemoryWriter(append_fn=fake_append),
                extra_tools={"boom": Boom()}, inhale=False, printer=lines10.append,
            )
            check("T10 tool error surfaced via tool!ERR",
                  any("tool!ERR: boom -> kaboom" in l for l in lines10), str(lines10))
            check("T10b error output is NOT evidence -> fail-closed verdict",
                  r10.verdict == "ESCALATE", r10.verdict)

            # T11: capture=False / distill=False honored
            llm11 = scripted([json.dumps([{"tool_name": "calculator",
                                           "description": "x"}]), "plain answer"])
            before = queue.read_text(encoding="utf-8")
            r11 = await ask("no exhale", llm_call=llm11, kb_path=kb, queue_path=queue,
                            store_factory=lambda: None, capture=False, distill=False,
                            gate=ConfidenceGate(embed_fn=scripted_embed),
                            inhale=False, printer=lines.append)
            check("T11 exhale opt-outs honored",
                  r11.captured is False and r11.distill_status == "skipped"
                  and queue.read_text(encoding="utf-8") == before)

            # T12: awareness judge — mechanical checks fire correctly
            v, _ = _judge_awareness("autobiography", r, "2026-06-12")
            v2, _ = _judge_awareness("temporal", r11, "2026-06-12")
            check("T12 awareness judge: KB-consulting run passes autobiography; "
                  "dateless answer fails temporal", v == "PASS" and v2 == "FAIL")

            # T13: _is_unparsed_answer — structural detector (pure)
            check("T13a raw tool-call JSON is degenerate",
                  _is_unparsed_answer('{"name": "x", "arguments": {}}'))
            check("T13b JSON array is degenerate", _is_unparsed_answer('[{"name": "x"}]'))
            check("T13c empty is degenerate", _is_unparsed_answer("   "))
            check("T13d real prose is NOT degenerate",
                  not _is_unparsed_answer("We built the Cognitive Control Loop."))
            check("T13e prose mentioning a brace is NOT degenerate",
                  not _is_unparsed_answer("The config dict {x:1} ships next."))

            # T13f-i: _degenerate_diagnosis reads the REAL terminal cause from the
            # ReAct state instead of always blaming a malformed tool call (live
            # Sonnet 2026-06-25: a budget kill was mislabelled a 'protocol gap').
            from types import SimpleNamespace as _NS
            _mk = lambda **kw: _NS(react=_NS(**kw))
            mbud, gbud = _degenerate_diagnosis(_mk(
                terminated_reason=TERMINATED_ERROR,
                error="LLMBudgetExceeded: projected $0.11 > budget $0.10",
                iterations_used=2))
            check("T13f budget kill named as a cost limit, not a protocol gap",
                  "budget" in gbud.lower() and "budget" in mbud.lower()
                  and "protocol gap" not in mbud, hint=mbud[:80])
            merr, _ = _degenerate_diagnosis(_mk(
                terminated_reason=TERMINATED_ERROR,
                error="RuntimeError: provider 500", iterations_used=1))
            check("T13g provider error named as an error, not malformed-tool-call",
                  "errored" in merr and "malformed" not in merr, hint=merr[:80])
            mmax, gmax = _degenerate_diagnosis(_mk(
                terminated_reason=TERMINATED_MAX_ITERATIONS,
                error="", iterations_used=8))
            check("T13h max-iterations named as non-convergence, not garbage",
                  "8" in gmax and "converge" in mmax, hint=mmax[:80])
            mraw, graw = _degenerate_diagnosis(_mk(
                terminated_reason="final_answer", error="", iterations_used=3))
            check("T13i genuine raw emission keeps the malformed-tool-call message",
                  mraw == _UNPARSED_FALLBACK and graw == _UNPARSED_GROUNDS)

            # T14: a degenerate model answer is suppressed end-to-end — the user,
            # the queue, and the KB get the honest fallback, NEVER the raw JSON.
            # Persistent botched JSON exhausts react repairs (x2) + one mind
            # replan (decompose+react), so: plan, 3x garbage, plan, 3x garbage.
            BAD = '{"oops": "not a tool call"}'
            llm14 = scripted([
                json.dumps([{"tool_name": "calculator", "description": "x"}]),
                BAD, BAD, BAD,
                json.dumps([{"tool_name": "calculator", "description": "x"}]),
                BAD, BAD, BAD,
            ])
            q14: List[str] = []
            distilled14: List[Dict[str, Any]] = []
            r14 = await ask(
                "trigger degenerate", llm_call=llm14, kb_path=kb,
                queue_path=tdp / "q14.jsonl", store_factory=lambda: None,
                gate=ConfidenceGate(embed_fn=scripted_embed),
                writer=SessionMemoryWriter(append_fn=lambda **k: distilled14.append(k) or {"status": "appended", "id": 1}),
                inhale=False, printer=q14.append,
            )
            check("T14a degenerate answer replaced by honest fallback",
                  "couldn't produce a clean answer" in r14.answer
                  and "oops" not in r14.answer, r14.answer[:80])
            check("T14b verdict forced ESCALATE", r14.verdict == "ESCALATE")
            check("T14c printed answer is NOT raw JSON",
                  not any('"oops"' in l for l in q14 if "JARVIS" in l))
            check("T14d distill stored the fallback, never the JSON",
                  distilled14 and "oops" not in distilled14[0]["content"])

            # T15: per-model profile RESOLVED at the host and applied at boot.
            # The scripted llm reports model "scripted-brain"; a registry maps
            # the "scripted" family to mirror_ok=True so we can prove the APPLIED
            # mirror came from the profile DATA, not a hardcode.
            from jarvis_core.brain.model_profiles import ProfileRegistry
            reg = ProfileRegistry(profiles={
                "family": {"scripted": {"mirror_ok": True, "max_iterations": 5,
                                        "notes": "test family"}}})
            llm15 = scripted([json.dumps([{"tool_name": "calculator",
                                           "description": "x"}]), "done"])
            r15 = await ask("profile applies?", llm_call=llm15, kb_path=kb,
                            queue_path=tdp / "q15.jsonl", store_factory=lambda: None,
                            gate=ConfidenceGate(embed_fn=scripted_embed),
                            writer=SessionMemoryWriter(append_fn=lambda **k: {"status": "appended", "id": 1}),
                            inhale=False, registry=reg, printer=lines.append)
            check("T15 profile resolved by family + applied at boot",
                  r15.boot.profile == "family:scripted"
                  and r15.boot.mirror is True, f"{r15.boot.profile}/{r15.boot.mirror}")

            # T16: --no-profile (use_profile=False) bypasses resolution -> bare default
            llm16 = scripted([json.dumps([{"tool_name": "calculator",
                                           "description": "x"}]), "done"])
            r16 = await ask("no profile", llm_call=llm16, kb_path=kb,
                            queue_path=tdp / "q16.jsonl", store_factory=lambda: None,
                            gate=ConfidenceGate(embed_fn=scripted_embed),
                            writer=SessionMemoryWriter(append_fn=lambda **k: {"status": "appended", "id": 1}),
                            inhale=False, use_profile=False, registry=reg, printer=lines.append)
            check("T16 --no-profile bypasses resolution, bare default conduct",
                  r16.boot.profile == "none" and r16.boot.mirror is False,
                  f"{r16.boot.profile}/{r16.boot.mirror}")

            # T17: unknown model -> default profile, mirror stays off (safe floor)
            llm17 = scripted([json.dumps([{"tool_name": "calculator",
                                           "description": "x"}]), "done"])
            r17 = await ask("unknown brain", llm_call=llm17, kb_path=kb,
                            queue_path=tdp / "q17.jsonl", store_factory=lambda: None,
                            gate=ConfidenceGate(embed_fn=scripted_embed),
                            writer=SessionMemoryWriter(append_fn=lambda **k: {"status": "appended", "id": 1}),
                            inhale=False, registry=ProfileRegistry(profiles={}),
                            printer=lines.append)
            check("T17 unknown model -> default profile, mirror off",
                  r17.boot.profile == "default" and r17.boot.mirror is False)

            # T18: --full assembles the whole toolset + a permission context, and a
            # DANGEROUS tool is gated through the ask_handler. Scripted handler DENIES
            # shell_run so we prove the gate blocks dispatch (no shell actually runs).
            from jarvis_core.agent.permissions import PermissionDecision
            denials: List[str] = []
            def deny_handler(tool_name, tool_input):
                denials.append(tool_name)
                return PermissionDecision.DENY
            llm18 = scripted([
                json.dumps([{"tool_name": "shell_run", "description": "list files"}]),
                json.dumps({"name": "shell_run", "arguments": {"command": "rm -rf /tmp/x"}}),
                "I was blocked from running that, so here is my plain answer.",
            ])
            r18 = await ask("delete something", llm_call=llm18, kb_path=kb,
                            queue_path=tdp / "q18.jsonl", store_factory=lambda: None,
                            gate=ConfidenceGate(embed_fn=scripted_embed),
                            writer=SessionMemoryWriter(append_fn=lambda **k: {"status": "appended", "id": 1}),
                            inhale=False, use_profile=False, full=True,
                            ask_handler=deny_handler, printer=lines.append)
            check("T18 --full assembles whole toolset + gates dangerous tools",
                  r18.boot.tool_mode == "full"
                  and {"shell_run", "code_exec"} <= set(r18.boot.gated), str(r18.boot.gated))
            check("T18b dangerous shell_run routed to ask_handler and DENIED",
                  "shell_run" in denials
                  and not any(tc.name == "shell_run" and not getattr(tr, "error", None)
                              for tc, tr in r18.mind.react.tool_calls),
                  f"denials={denials}")

            # T19: a SAFE tool under --full dispatches without ever hitting the handler
            denials19: List[str] = []
            def watch_handler(tool_name, tool_input):
                denials19.append(tool_name)
                return PermissionDecision.DENY
            llm19 = scripted([
                json.dumps([{"tool_name": "calculator", "description": "compute"}]),
                json.dumps({"name": "calculator", "arguments": {"expression": "2+3"}}),
                "The answer is 5.",
            ])
            r19 = await ask("add 2 and 3", llm_call=llm19, kb_path=kb,
                            queue_path=tdp / "q19.jsonl", store_factory=lambda: None,
                            gate=ConfidenceGate(embed_fn=scripted_embed),
                            writer=SessionMemoryWriter(append_fn=lambda **k: {"status": "appended", "id": 1}),
                            inhale=False, use_profile=False, full=True,
                            ask_handler=watch_handler, printer=lines.append)
            check("T19 safe tool under --full dispatches, never gated",
                  "calculator" not in denials19
                  and any(tc.name == "calculator" for tc, _ in r19.mind.react.tool_calls))

            # T20: default (full=False) path unchanged — minimal toolset, no gating
            r20 = await ask("plain", llm_call=scripted([
                json.dumps([{"tool_name": "calculator", "description": "x"}]), "done"]),
                kb_path=kb, queue_path=tdp / "q20.jsonl", store_factory=lambda: None,
                gate=ConfidenceGate(embed_fn=scripted_embed),
                writer=SessionMemoryWriter(append_fn=lambda **k: {"status": "appended", "id": 1}),
                inhale=False, use_profile=False, printer=lines.append)
            check("T20 default path stays minimal (no full toolset, no gating)",
                  r20.boot.tool_mode == "minimal" and r20.boot.gated == ())

            # T21: DEFAULT --ask now has EYES — file_read + file_search ship without
            # --full, and a permission context is wired (the cloud-leak guard).
            check("T21 default toolset includes file_read + file_search",
                  {"file_read", "file_search"} <= set(r20.boot.tools), str(r20.boot.tools))
            check("T21b default toolset stays lean (no shell/exec/web in default)",
                  not ({"shell_run", "code_exec", "web_search"} & set(r20.boot.tools)))

            # T22: in DEFAULT mode an OUT-OF-REPO file_read is gated (cloud-leak guard),
            # in-repo auto-allows. Prove via the permission context the orchestrator builds.
            from jarvis_core.brain.permgate import build_permission_context
            from jarvis_core.brain.boot import default_toolset as _dts
            from jarvis_core.agent.permissions import PermissionDecision as _PD
            ctx22 = build_permission_context(_dts(store=None, kb_path=kb))
            in_repo = str(Path(__file__).resolve())  # this orchestrator.py, in-repo
            check("T22 default-mode out-of-repo file_read gated",
                  await ctx22.check("file_read", {"path": "/etc/passwd"}) == _PD.ASK)
            check("T22b default-mode in-repo file_read auto-allowed",
                  await ctx22.check("file_read", {"path": in_repo}) == _PD.ALLOW)

            # ---- Conversation memory (working memory across --ask) ----
            cs = _conv.ConversationStore()  # uses the temp-patched _CONV_DIR
            common = dict(kb_path=kb, queue_path=tdp / "qc.jsonl",
                          store_factory=lambda: None, inhale=False, use_profile=False,
                          gate=ConfidenceGate(embed_fn=scripted_embed),
                          writer=SessionMemoryWriter(append_fn=lambda **k: {"status": "appended", "id": 1}),
                          printer=lines.append)

            # T23: turn 2 of a thread SEES turn 1 (history reaches the Mind's messages)
            await ask("remember the marker FOOBAR123",
                      llm_call=scripted([json.dumps([{"tool_name": "calculator", "description": "x"}]),
                                         "Noted: FOOBAR123."]),
                      session="thread-A", **common)
            r23 = await ask("what was the marker?",
                            llm_call=scripted([json.dumps([{"tool_name": "calculator", "description": "x"}]),
                                               "The marker was FOOBAR123."]),
                            session="thread-A", **common)
            check("T23 prior turn threaded into the Mind's messages",
                  any("FOOBAR123" in m.get("content", "") for m in r23.mind.react.messages),
                  str([m.get("content","")[:40] for m in r23.mind.react.messages]))
            check("T23b store accrued both turns of both exchanges",
                  cs.turn_count("thread-A") == 4)

            # T24: threads ISOLATE — a different session sees NONE of thread-A's history
            # (the essence of what --new buys: a separate id has a separate transcript)
            r24 = await ask("anything",
                            llm_call=scripted(["no plan", "Hello, fresh thread."]),
                            session="thread-B", **common)
            check("T24 a different thread sees none of thread-A's history",
                  not any("FOOBAR123" in m.get("content", "") for m in r24.mind.react.messages)
                  and cs.turn_count("thread-B") == 2)

            # T25: a DEGENERATE answer is NOT persisted (no dangling/poison turn)
            await ask("trigger degenerate persist",
                      llm_call=scripted([json.dumps([{"tool_name": "calculator", "description": "x"}]),
                                         '{"oops": "not a tool call"}', '{"oops": "again"}',
                                         '{"oops": "still"}', json.dumps([{"tool_name": "calculator", "description": "x"}]),
                                         '{"oops": "x"}', '{"oops": "y"}', '{"oops": "z"}']),
                      session="deg-thread", **common)
            check("T25 degenerate answer NOT persisted to the transcript",
                  cs.turn_count("deg-thread") == 0, str(cs.turn_count("deg-thread")))

            # T26: a real chit-chat answer that scores ESCALATE (no evidence) IS persisted
            # — the correction: gate persistence on STRUCTURAL degeneracy, not the verdict.
            r26 = await ask("hi, who are you?",
                            llm_call=scripted(["no plan", "I am JARVIS, your private AI."]),
                            session="chat-thread", **common)
            check("T26 chit-chat is ESCALATE (no evidence) but real prose",
                  r26.verdict == "ESCALATE" and "JARVIS" in r26.answer)
            check("T26b ESCALATE-but-real chit-chat IS persisted (threaded)",
                  cs.turn_count("chat-thread") == 2, str(cs.turn_count("chat-thread")))

            # --- Reasoning audit (Stage 4.5) end-to-end through ask() ---
            def critic(payload: str):
                def _c(messages):
                    return payload
                return _c
            sound_critic = critic('{"verdict": "SOUND", "flaw": "", "corrected": ""}')
            flawed_critic = critic('{"verdict": "FLAWED", '
                                   '"flaw": "dropped the stated inversion rule", '
                                   '"corrected": "Yes"}')

            # T27: a FLAWED reasoning audit forces the stamped verdict to ESCALATE
            # and surfaces the flaw — even though the answer is coherent prose.
            lines27: List[str] = []
            r27 = await ask("is earth flat?",
                            llm_call=scripted(["no plan", "No, the earth is not flat."]),
                            reasoning=True, reasoning_gate=ReasoningGate(flawed_critic),
                            session="reason-flawed",
                            **{**common, "printer": lines27.append})
            check("T27 FLAWED audit -> stamped ESCALATE",
                  r27.verdict == "ESCALATE" and r27.reasoning_verdict == "FLAWED",
                  f"{r27.verdict}/{r27.reasoning_verdict}")
            check("T27b flaw captured on the result", "inversion" in r27.reasoning_flaw,
                  r27.reasoning_flaw)
            check("T27c both signals printed (confidence + reasoning lines)",
                  any(l.startswith("  confidence:") for l in lines27)
                  and any(l.startswith("  reasoning :") for l in lines27), str(lines27[-4:]))

            # T28: an INDEPENDENT SOUND audit lifts an evidence-less answer out of
            # the falsely dismissive ESCALATE-0.00 to UNCERTAIN (logic sound,
            # ungrounded). Lift is gated on critic independence.
            r28 = await ask("reason about something with no tools",
                            llm_call=scripted(["no plan", "A sound, evidence-free deduction."]),
                            reasoning=True, reasoning_gate=ReasoningGate(sound_critic),
                            critic_independent=True,
                            session="reason-sound", **common)
            check("T28 independent SOUND lifts evidence-less ESCALATE -> UNCERTAIN",
                  r28.verdict == "UNCERTAIN" and r28.reasoning_verdict == "SOUND",
                  f"{r28.verdict}/{r28.reasoning_verdict} score={r28.confidence_score}")

            # T28b (HIGH-finding fix, live default): a SELF-audit SOUND
            # (critic_independent=False — the production default) must NOT upgrade
            # a wrong/ungrounded answer. No false-SOUND confidence regression.
            r28b = await ask("reason with a self-audit",
                             llm_call=scripted(["no plan", "A self-audited deduction."]),
                             reasoning=True, reasoning_gate=ReasoningGate(sound_critic),
                             session="reason-selfaudit", **common)
            check("T28b self-audit SOUND does NOT lift (stays ESCALATE)",
                  r28b.verdict == "ESCALATE" and r28b.reasoning_verdict == "SOUND",
                  f"{r28b.verdict}/{r28b.reasoning_verdict}")

            # T29: THE L383 FIX, end-to-end — a confidently-WRONG answer and a RIGHT
            # evidence-less answer no longer land on the same verdict/score.
            check("T29 wrong(FLAWED)=ESCALATE 0.00 distinguishable from right(SOUND)=UNCERTAIN",
                  r27.verdict != r28.verdict
                  and r27.confidence_score == 0.0 and r28.confidence_score > 0.0,
                  f"wrong={r27.verdict}/{r27.confidence_score} right={r28.verdict}/{r28.confidence_score}")

            # T30: reasoning OFF (the library default) is a clean no-op — no critic
            # call, no reasoning line, verdict is grounding-only (pre-4.5 behavior).
            lines30: List[str] = []
            r30 = await ask("plain ungrounded answer",
                            llm_call=scripted(["no plan", "Just a chat reply."]),
                            session="reason-off",
                            **{**common, "printer": lines30.append})
            check("T30 reasoning default-off: UNCHECKED, grounding-only verdict",
                  r30.reasoning_verdict == "UNCHECKED" and r30.verdict == "ESCALATE"
                  and not any(l.startswith("  reasoning :") for l in lines30))

            # T31: a degenerate answer is never audited (nothing to critique) — the
            # critic must not even be reached.
            critic_hits = {"n": 0}
            def counting_critic(messages):
                critic_hits["n"] += 1
                return '{"verdict": "SOUND"}'
            r31 = await ask("trigger degenerate",
                            llm_call=scripted([json.dumps([{"tool_name": "calculator", "description": "x"}]),
                                               '{"oops": "a"}', '{"oops": "b"}', '{"oops": "c"}',
                                               json.dumps([{"tool_name": "calculator", "description": "x"}]),
                                               '{"oops": "d"}', '{"oops": "e"}', '{"oops": "f"}']),
                            reasoning=True, reasoning_gate=ReasoningGate(counting_critic),
                            session="reason-degen", **common)
            check("T31 degenerate answer is not audited (critic never called)",
                  critic_hits["n"] == 0 and r31.reasoning_verdict == "UNCHECKED",
                  f"hits={critic_hits['n']} verdict={r31.reasoning_verdict}")

            # --- Wave 2: independent critic (a DIFFERENT model audits) ---
            # A critic client built from a model id via the injectable factory; it
            # carries a .model + a ledger so the dual-ledger path is exercised.
            def make_critic_client(model_id: str, payload: str):
                calls = [0]
                def _client(messages):
                    calls[0] += 1
                    return payload
                _client.model = model_id          # type: ignore[attr-defined]
                _client.ledger_summary = (lambda: {  # type: ignore[attr-defined]
                    "model": model_id, "calls": calls[0], "spend_usd": 0.0009})
                return _client

            built = {"models": []}
            def factory(model_id: str):
                built["models"].append(model_id)
                return make_critic_client(
                    model_id, '{"verdict": "SOUND", "flaw": "", "corrected": ""}')

            # T32: a critic model DIFFERENT from the answerer ('scripted-brain') is
            # auto-derived INDEPENDENT -> its SOUND lifts an evidence-less ESCALATE to
            # UNCERTAIN, the factory is called with that model, descriptor shows it.
            lines32: List[str] = []
            r32 = await ask("reason, no tools",
                            llm_call=scripted(["no plan", "An evidence-free deduction."]),
                            reasoning=True, critic_model="peer/other-model",
                            critic_factory=factory, session="reason-indep",
                            **{**common, "printer": lines32.append})
            check("T32 different critic model -> independent SOUND lifts to UNCERTAIN",
                  r32.verdict == "UNCERTAIN" and r32.reasoning_verdict == "SOUND",
                  f"{r32.verdict}/{r32.reasoning_verdict}")
            check("T32b factory built the critic on the configured model",
                  built["models"] == ["peer/other-model"], str(built["models"]))
            check("T32c reasoning line names the independent critic model",
                  any("independent: peer/other-model" in l for l in lines32),
                  str([l for l in lines32 if l.startswith('  reasoning')]))
            check("T32d critic spend surfaced (dual ledger)",
                  any(l.startswith("  critic  :") for l in lines32), str(lines32[-3:]))

            # T33: a critic model EQUAL to the answerer is NOT independent (same blind
            # spot) -> self-audit, SOUND does NOT lift (stays ESCALATE), factory unused.
            # The self-audit uses the main client, so its 3rd scripted reply IS the
            # critic's SOUND verdict.
            built2 = {"models": []}
            r33 = await ask("reason, no tools",
                            llm_call=scripted(["no plan", "Another evidence-free reply.",
                                               '{"verdict": "SOUND", "flaw": "", "corrected": ""}']),
                            reasoning=True, critic_model="scripted-brain",
                            critic_factory=lambda m: (built2["models"].append(m) or factory(m)),
                            session="reason-samemodel", **common)
            check("T33 same critic model == answerer -> self-audit SOUND, no lift (ESCALATE)",
                  r33.verdict == "ESCALATE" and r33.reasoning_verdict == "SOUND"
                  and built2["models"] == [],
                  f"{r33.verdict}/{r33.reasoning_verdict} built={built2['models']}")

            # T34: an independent FLAWED still forces ESCALATE (fail-closed holds with
            # a real distinct critic, not just the injected-gate path).
            r34 = await ask("is the earth flat?",
                            llm_call=scripted(["no plan", "No."]),
                            reasoning=True, critic_model="peer/other-model",
                            critic_factory=lambda m: make_critic_client(
                                m, '{"verdict":"FLAWED","flaw":"dropped inversion","corrected":"Yes"}'),
                            session="reason-indep-flawed", **common)
            check("T34 independent FLAWED -> ESCALATE + flaw on result",
                  r34.verdict == "ESCALATE" and r34.reasoning_verdict == "FLAWED"
                  and "inversion" in r34.reasoning_flaw, f"{r34.verdict}/{r34.reasoning_flaw}")

            # T35 (HIGH-fix): a critic FACTORY that raises (e.g. no API key) must NOT
            # crash ask() — it degrades to a self-audit and the answer STANDS.
            lines35: List[str] = []
            def exploding_factory(model_id: str):
                raise RuntimeError("No API key")
            r35 = await ask("reason, no tools",
                            llm_call=scripted(["no plan", "An answer that must survive."]),
                            reasoning=True, critic_model="peer/other-model",
                            critic_factory=exploding_factory, session="reason-buildfail",
                            **{**common, "printer": lines35.append})
            check("T35 critic build failure does not crash; answer stands",
                  "must survive" in r35.answer and r35.verdict == "ESCALATE",
                  f"{r35.verdict}/{r35.answer[:40]}")
            check("T35b degrade is visible (self-audit build-failed note printed)",
                  any("critic build failed" in l for l in lines35), str(lines35[-3:]))

            # T36 (MEDIUM/LOW-fix): a critic id equal to the answerer modulo case +
            # whitespace must be treated as SAME-model self-audit (no lift), not
            # independent. Answerer model is 'scripted-brain'.
            built36 = {"models": []}
            r36 = await ask("reason, no tools",
                            llm_call=scripted(["no plan", "Evidence-free again.",
                                               '{"verdict": "SOUND", "flaw": "", "corrected": ""}']),
                            reasoning=True, critic_model="  Scripted-Brain  ",
                            critic_factory=lambda m: (built36["models"].append(m) or
                                                      make_critic_client(m, "{}")),
                            session="reason-normcase", **common)
            check("T36 same model (case/whitespace) -> self-audit, no lift, factory unused",
                  r36.verdict == "ESCALATE" and built36["models"] == [],
                  f"{r36.verdict} built={built36['models']}")

            # --- Stage 4.1 W2: ModelPool routing through ask() ---
            from jarvis_core.brain.targets import RouteTarget, TargetKind
            from jarvis_core.brain.model_pool import ModelPool

            def pool_target(name, responses, behavior="ok"):
                """A RouteTarget whose llm_call drives a scripted sequence (so the
                ReAct loop gets decompose+answer); behavior 'fail' raises."""
                class _T(RouteTarget):
                    kind = TargetKind.API_MODEL
                    def __init__(self):
                        self.name = name
                        self.profile = None
                        self._llm = scripted(responses)
                        self.calls = 0
                    @property
                    def llm_call(self):
                        def _c(messages):
                            self.calls += 1
                            if behavior == "fail":
                                raise RuntimeError("target down")
                            return self._llm(messages)
                        return _c
                    async def ensure_ready(self): pass
                    async def release(self): pass
                    def ledger_summary(self):
                        return {"model": name, "calls": self.calls, "spend_usd": 0.001 * self.calls}
                return _T()

            # T37: a pool routes the answer; ledger is the AGGREGATE; pool line printed.
            # model_stats_store is tempdir-scoped (mirrors led40/41/42 below) so this
            # test NEVER touches the real jarvis_data/model_stats.jsonl.
            from jarvis_core.brain.model_stats import ModelStatsStore
            lines37: List[str] = []
            pool37 = ModelPool([pool_target("model-A", ["no plan", "Pooled answer A."])])
            r37 = await ask("pooled question", pool=pool37,
                            model_stats_store=ModelStatsStore(path=tdp / "stats37.jsonl"),
                            **{**common, "printer": lines37.append})
            check("T37 pool routes the answer", "Pooled answer A." in r37.answer, r37.answer)
            check("T37b ledger is the pool aggregate", r37.ledger.get("targets") == 1, str(r37.ledger))
            check("T37c pool line printed with primary",
                  any(l.startswith("  pool    :") and "model-A" in l for l in lines37),
                  str([l for l in lines37 if l.startswith('  pool')]))
            check("T37d model_stats_store injection reaches the flush site "
                  "(Stage 4.3.1 — this is the check that would have caught the "
                  "real-file-pollution bug: the DEFAULT store must never be hit "
                  "when an override is given)",
                  (tdp / "stats37.jsonl").exists())

            # T38: primary fails -> pool fails over to a healthy peer; peer answers,
            # the failed target carries an error on its ledger ("both attempts").
            pa = pool_target("bad-A", ["x"], behavior="fail")
            pb = pool_target("good-B", ["no plan", "Peer B answer."])
            pool38 = ModelPool([pa, pb])
            r38 = await ask("failover question", pool=pool38,
                            model_stats_store=ModelStatsStore(path=tdp / "stats38.jsonl"), **common)
            st38 = pool38.status()
            check("T38 failover to healthy peer", "Peer B answer." in r38.answer, r38.answer)
            check("T38b failed target recorded an error, peer succeeded",
                  st38["bad-A"]["errors"] >= 1 and st38["good-B"]["requests"] >= 1
                  and st38["good-B"]["errors"] == 0, str(st38))
            check("T38c failover event logged on the pool",
                  any("failover" in e for e in pool38.last_events), str(pool38.last_events))
            check("T38d stats flush landed in the injected path", (tdp / "stats38.jsonl").exists())

            # T39: an injected llm_call STILL bypasses the pool entirely (no regression
            # — the 56 prior tests rely on this; assert the seam explicitly).
            r39 = await ask("direct", llm_call=scripted(["no plan", "Direct answer."]),
                            pool=pool37, model_stats_store=ModelStatsStore(path=tdp / "stats39.jsonl"),
                            session="direct-seam", **common)
            check("T39 injected llm_call wins over pool (pool path skipped)",
                  "Direct answer." in r39.answer, r39.answer)
            check("T39b stats flush STILL fires for an injected pool even when "
                  "llm_call bypasses it for generation (route_pool is non-None "
                  "either way — this is exactly the condition that leaked into "
                  "the real file before the override was added)",
                  (tdp / "stats39.jsonl").exists())

            # T43 (Stage 4.3.1 regression guard): none of T37-T39's fixture target
            # names ever reached the REAL default path. If this ever fails, the
            # model_stats_store injection seam has regressed and tests are
            # writing into the user's actual jarvis_data/model_stats.jsonl again.
            from jarvis_core.config import MODEL_STATS_PATH
            real_path = Path(MODEL_STATS_PATH)
            leaked = False
            if real_path.exists():
                real_text = real_path.read_text(encoding="utf-8")
                leaked = any(name in real_text for name in ("model-A", "bad-A", "good-B"))
            check("T43 no test-fixture pool ever wrote to the REAL model_stats.jsonl",
                  not leaked)

            # T44 (Stage 4.3.2): a governor-equipped pool, threaded through ask(),
            # benches the paid target and answers from the free peer once the
            # shared CostTracker is near the ceiling — end-to-end, not just at the
            # pool unit level.
            from jarvis_core.agent.cost import CostTracker
            paid44 = pool_target("paid-X", ["no plan", "Paid answer."]); paid44.cost_hint = 5.0
            free44 = pool_target("free-Y", ["no plan", "Free answer."]); free44.cost_hint = 0.0
            ct44 = CostTracker(budget_usd=1.0); ct44.record("x", 0, 0, cost_usd=0.95)
            pool44 = ModelPool([paid44, free44], cost_tracker=ct44)  # paid declared FIRST
            lines44: List[str] = []
            r44 = await ask("governed question", pool=pool44,
                            model_stats_store=ModelStatsStore(path=tdp / "stats44.jsonl"),
                            session="gov-44", **{**common, "printer": lines44.append})
            check("T44 near-ceiling pool routes to the FREE peer, benches paid",
                  "Free answer." in r44.answer and paid44.calls == 0, r44.answer)
            check("T44b downshift surfaced to the operator (labeled, not as failover)",
                  any("budget downshift" in l for l in lines44),
                  str([l for l in lines44 if "downshift" in l]))

            # T45 (Stage 4.3.2): near-ceiling with NO free peer -> the ask fails
            # closed to a degenerate answer rather than silently overspending
            # (acall raises AllTargetsExhausted, caught by react's error path).
            paidA = pool_target("paid-A", ["no plan", "A."]); paidA.cost_hint = 5.0
            paidB = pool_target("paid-B", ["no plan", "B."]); paidB.cost_hint = 7.0
            ct45 = CostTracker(budget_usd=1.0); ct45.record("x", 0, 0, cost_usd=0.99)
            pool45 = ModelPool([paidA, paidB], cost_tracker=ct45)
            r45 = await ask("over-budget question", pool=pool45,
                            model_stats_store=ModelStatsStore(path=tdp / "stats45.jsonl"),
                            session="gov-45", **common)
            check("T45 no free peer past ceiling -> neither paid target was called "
                  "(failed closed, never overspent)",
                  paidA.calls == 0 and paidB.calls == 0,
                  f"A={paidA.calls} B={paidB.calls}")

            # --- Stage 4.2: Intent Router wiring through ask() ---
            from jarvis_core.brain.router import RoutingDecision
            from jarvis_core.brain.routing_ledger import RoutingLedger

            class _FakeRouter:
                def __init__(self, decision):
                    self.decision = decision
                    self.calls: List[str] = []
                def route(self, query, constraints=None, strategy="balanced"):
                    self.calls.append(query)
                    return self.decision

            dec40 = RoutingDecision("engineer", 0.77, ("vendor/coder-a", "vendor/coder-b"),
                                    "balanced", "test")

            # T40: route=True + injected router -> the decision drives targets and a
            # RoutingRecord lands; the injected llm_call executes (keeps it offline).
            fr40 = _FakeRouter(dec40)
            led40 = RoutingLedger(path=tdp / "rl40.jsonl")
            lines40: List[str] = []
            r40 = await ask("optimize this spark job", route=True, router=fr40,
                            routing_ledger=led40,
                            llm_call=scripted(["no plan", "Routed engineer answer."]),
                            session="route-40", **{**common, "printer": lines40.append})
            check("T40 router consulted with the query", fr40.calls == ["optimize this spark job"],
                  str(fr40.calls))
            check("T40b answer produced via the executor", "Routed engineer answer." in r40.answer, r40.answer)
            check("T40c RoutingRecord logged (codename + outcome), query NOT stored raw",
                  led40.count == 1 and led40._records[0].label == "engineer"
                  and led40._records[0].outcome == "ok"
                  and led40._records[0].query_hash != "optimize this spark job", str(led40.summary()))
            check("T40d route line printed with codename + routed targets",
                  any(l.startswith("  route   :") and "engineer" in l and "vendor/coder-a" in l
                      for l in lines40),
                  str([l for l in lines40 if l.startswith('  route')]))

            # T41: explicit targets WIN — the router is NEVER consulted (no decision, no log).
            fr41 = _FakeRouter(dec40)
            led41 = RoutingLedger(path=tdp / "rl41.jsonl")
            r41 = await ask("explicit pin wins", route=True, router=fr41, routing_ledger=led41,
                            targets=["vendor/pinned"],
                            llm_call=scripted(["no plan", "Pinned answer."]),
                            session="route-41", **common)
            check("T41 explicit targets bypass the router (not consulted)",
                  fr41.calls == [] and led41.count == 0 and "Pinned answer." in r41.answer,
                  f"calls={fr41.calls} count={led41.count}")

            # T42: route=False (default) -> the router is never built or consulted.
            fr42 = _FakeRouter(dec40)
            led42 = RoutingLedger(path=tdp / "rl42.jsonl")
            r42 = await ask("no routing here", route=False, router=fr42, routing_ledger=led42,
                            llm_call=scripted(["no plan", "Unrouted answer."]),
                            session="route-42", **common)
            check("T42 route=False never consults the router",
                  fr42.calls == [] and led42.count == 0 and "Unrouted answer." in r42.answer,
                  f"calls={fr42.calls} count={led42.count}")

    asyncio.run(scenario())

    total = passed + len(failed)
    print(f"\n  Passed: {passed}/{total}")
    if failed:
        for f_ in failed:
            print(f"  {f_}")
        print("=" * 70)
        raise SystemExit(1)
    print(f"  All {total} orchestrator smoke tests passed.")
    print("=" * 70)


def main() -> int:
    p = argparse.ArgumentParser(description="JARVIS spine v0 (Stage 4.0)")
    p.add_argument("--ask", metavar="QUESTION", help="Ask JARVIS (live, boot-assembled)")
    p.add_argument("--awareness", action="store_true",
                   help="Gate A: the 5 awareness questions (live)")
    p.add_argument("--no-capture", action="store_true",
                   help="Do not append this session to the observation queue")
    p.add_argument("--no-profile", action="store_true",
                   help="Skip per-model ModelProfile resolution (use bare defaults)")
    p.add_argument("--full", action="store_true",
                   help="Full toolset (web/file/exec/shell/memory/finance/cognitive), "
                        "permission-gated; dangerous tools prompt [y/N]")
    p.add_argument("--allow-all", action="store_true",
                   help="With --full: auto-ALLOW every tool (DANGEROUS — a weak model "
                        "gets ungated shell/exec). Unattended/sandboxed use only.")
    p.add_argument("--new", action="store_true",
                   help="Start a fresh conversation thread (don't continue the recent one)")
    p.add_argument("--session", metavar="NAME",
                   help="Use/resume a named conversation thread")
    p.add_argument("--no-reasoning", action="store_true",
                   help="Skip the reasoning audit (the LLM self-critique that grades "
                        "logic, not just evidence-grounding; on by default, ~1 extra call)")
    p.add_argument("--critic-model", metavar="MODEL",
                   help="Audit with a DIFFERENT model (independent critic — its SOUND can "
                        "lift, its FLAWED is trusted). Defaults to OPENROUTER_CRITIC_MODEL; "
                        "unset -> conservative same-model self-audit. ~1 extra metered call "
                        "(capped at half the session budget; combined ceiling ~1.5x). NOTE: "
                        "this sends the conversation to a SECOND model/provider — pick a "
                        "trusted one.")
    p.add_argument("--targets", metavar="M1,M2,...",
                   help="Route over a POOL of models (comma-separated ids) with health-scored "
                        "failover (STEAL #7): the best healthy target answers; a 429/dead "
                        "endpoint fails over to the next peer. Conduct comes from the primary "
                        "target's profile. Default (unset) = a single auto-picked model.")
    p.add_argument("--route-strategy", default="balanced", choices=["balanced", "latency", "cost"],
                   help="Pool selection strategy (default: balanced).")
    p.add_argument("--budget", type=float, default=_DEFAULT_BUDGET_USD, metavar="USD",
                   help=f"Per-session spend ceiling in USD (default ${_DEFAULT_BUDGET_USD:.2f}, "
                        "fail-closed). A pricey brain (e.g. Sonnet at $3/$15 per 1M) burns the "
                        "default in ~2 calls and dies mid-loop before reading broadly — raise "
                        "this (e.g. 0.60) for a multi-read agentic run on a costly model.")
    p.add_argument("--route", action="store_true",
                   help="Stage 4.2: classify the query's intent and route to a "
                        "specialist-codename-appropriate model pool (frontier-free). "
                        "Ignored if --targets is given (explicit pins win).")
    args = p.parse_args()
    if args.awareness:
        return asyncio.run(_awareness())
    if args.ask:
        handler = allow_all_ask_handler if (args.full and args.allow_all) else None
        tgts = [m.strip() for m in args.targets.split(",")] if args.targets else None
        asyncio.run(ask(args.ask, capture=not args.no_capture,
                        use_profile=not args.no_profile,
                        full=args.full, ask_handler=handler,
                        reasoning=not args.no_reasoning,
                        critic_model=args.critic_model,
                        targets=tgts, route_strategy=args.route_strategy,
                        route=args.route,
                        budget_usd=args.budget,
                        new_session=args.new, session=args.session))
        return 0
    _run_self_test()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
