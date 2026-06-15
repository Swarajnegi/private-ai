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

The terminal entry point used to live inside agent/llm_client.py as `_ask` —
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
from jarvis_core.agent.llm_client import build_llm_call
from jarvis_core.agent.mind import MindResult
from jarvis_core.brain.boot import BootReport, assemble_mind
from jarvis_core.brain.confidence import ConfidenceGate, ConfidenceReport
from jarvis_core.brain.model_profiles import ProfileRegistry
from jarvis_core.brain.boot import full_toolset, default_toolset
from jarvis_core.brain.conversation import ConversationStore, resolve_terminal_session
from jarvis_core.brain.permgate import (
    build_permission_context, terminal_ask_handler, allow_all_ask_handler,
)
from jarvis_core.brain.session_writer import SessionMemoryWriter, SessionRecord

_IST = timezone(timedelta(hours=5, minutes=30))
_DEFAULT_BUDGET_USD = 0.10

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
    4. ConfidenceGate grades answer vs tool-result evidence; verdict stamped.
    5. Capture parity append + Episodic distill (both fail-soft). Ledger printed.

    Returns:
        AskResult — the answer plus every judgement and bookkeeping fact.
    """
    client = llm_call or build_llm_call(budget_usd=budget_usd)
    if hasattr(client, "pick_free_model") and not getattr(client, "model", ""):
        await client.pick_free_model()
    model = str(getattr(client, "model", "") or "")

    # POLICY (resolved here, the host): per-model conduct profile by model id.
    # Boot is the MECHANISM that applies it — single resolution site, so the
    # 4.2 Router never competes with a second lookup (it just supplies the id).
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
        found = f" Retrieved this session: {evidence[0][:200]}…" if evidence else ""
        answer = _UNPARSED_FALLBACK + found
        report = ConfidenceReport(
            0.0, "ESCALATE",
            ("answer did not parse into prose — model emitted a malformed/structured "
             "fragment; suppressed at the orchestrator output gate",))
    else:
        answer = result.answer.strip()
        active_gate = gate or ConfidenceGate()
        report = active_gate.grade(answer, evidence)

    printer(f"\n  JARVIS  : {answer}")
    printer(f"  confidence: {report.verdict} ({report.score:.2f}) — {report.grounds[0]}")

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
    if hasattr(client, "ledger_summary"):
        try:
            ledger = client.ledger_summary()
        except Exception:
            ledger = {}

    distill_status = "skipped"
    if distill:
        active_writer = writer or SessionMemoryWriter(kb_path=kb_path)
        out = active_writer.write(SessionRecord(
            question=question, answer=answer, model=model,
            tools_used=tuple(tc.name for tc, _tr in result.react.tool_calls),
            spend_usd=float(ledger.get("spend_usd") or 0.0),
            confidence_verdict=report.verdict, confidence_score=report.score,
            domain=guess_domain(cwd, question + " " + answer),
        ))
        distill_status = str(out.get("status", "error"))

    if ledger:
        printer(f"  ledger  : {ledger}")

    return AskResult(
        question=question, answer=answer,
        verdict=report.verdict, confidence_score=report.score,
        grounds=report.grounds, ledger=ledger, boot=boot_report, mind=result,
        captured=captured, distill_status=distill_status,
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
    args = p.parse_args()
    if args.awareness:
        return asyncio.run(_awareness())
    if args.ask:
        handler = allow_all_ask_handler if (args.full and args.allow_all) else None
        asyncio.run(ask(args.ask, capture=not args.no_capture,
                        use_profile=not args.no_profile,
                        full=args.full, ask_handler=handler,
                        new_session=args.new, session=args.session))
        return 0
    _run_self_test()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
