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

    store = store_factory() if store_factory is not None else _open_store(printer)
    printer(f"  brain   : {model or '<scripted>'}")
    printer(f"  query   : {question}")
    try:
        mind, boot_report = assemble_mind(
            llm_call=client, store=store, kb_path=kb_path, inhale=inhale,
            extra_tools=extra_tools, clock=clock,
            profile_path=profile_path, queue_path=queue_path,
        )
        result = await mind.solve(question)
    finally:
        _close_store(store)

    for tc, tr in result.react.tool_calls:
        out = str(tr.error) if getattr(tr, "error", None) else str(tr.output)
        tag = "tool!ERR" if getattr(tr, "error", None) else "tool    "
        printer(f"  {tag}: {tc.name} -> {out[:140]}{'...' if len(out) > 140 else ''}")

    active_gate = gate or ConfidenceGate()
    report: ConfidenceReport = active_gate.grade(result.answer, _evidence_from(result))

    printer(f"\n  JARVIS  : {result.answer.strip()}")
    printer(f"  confidence: {report.verdict} ({report.score:.2f}) — {report.grounds[0]}")

    cwd = os.getcwd()
    captured = False
    if capture:
        try:
            obs = build_observation(
                event={"session_id": _SESSION_ID},
                turn={"user_text": strip_harness_blocks(question),
                      "assistant_summary": result.answer,
                      "model": model},
                cwd=cwd,
            )
            if obs is not None:
                obs["chat_label"] = "terminal-ask"   # not the repo dir name — the limb
                append_observation(obs, queue_path or QUEUE_PATH)
                captured = True
        except Exception as e:
            printer(f"  (capture skipped: {type(e).__name__}: {e})")

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
            question=question, answer=result.answer, model=model,
            tools_used=tuple(tc.name for tc, _tr in result.react.tool_calls),
            spend_usd=float(ledger.get("spend_usd") or 0.0),
            confidence_verdict=report.verdict, confidence_score=report.score,
            domain=guess_domain(cwd, question + " " + result.answer),
        ))
        distill_status = str(out.get("status", "error"))

    if ledger:
        printer(f"  ledger  : {ledger}")

    return AskResult(
        question=question, answer=result.answer,
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
                  qrec["session_id"].startswith("terminal-")
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
    args = p.parse_args()
    if args.awareness:
        return asyncio.run(_awareness())
    if args.ask:
        asyncio.run(ask(args.ask, capture=not args.no_capture))
        return 0
    _run_self_test()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
