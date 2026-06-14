"""
boot.py — The Boot Assembler (Stage 4.0.4a: composition root of the runtime Mind).

LAYER: Brain (Cognitive Control Loop — assembly)

Import with:
    from jarvis_core.brain.boot import assemble_mind, BootReport

=============================================================================
THE BIG PICTURE
=============================================================================

L324's live repro: asked "what have we built till now?", the terminal Mind
searched one ChromaDB collection of research papers and honestly found
nothing — while knowledge_base.jsonl (the actual autobiography, 325 entries)
sat unread because the entry point never wired the tool that reads it
(PriorSelfConsultTool — built in Stage 3.2, never handed to the Mind).

This module is the fix and the standard: ONE composition root that every
host adapter (terminal CLI, future daemon, future voice limb) calls to get a
fully-conscious Mind:

    psyche      JARVIS_PSYCHE_PROMPT — identity + conduct (always; L323
                directive: never ship an entry point that leaves identity
                to the substrate)
    autobiography  prior_self_consult + cognitive_mirror over the real KB,
                memory_semantic_search over ChromaDB when a store is open
    boot inhale ContextInjector block — clock, self-state, next roadmap
                task, cognitive profile, cross-chat activity (L324 gap 2)

The Mind itself is untouched — this is pure composition through ctor seams
that already existed. Store lifecycle stays with the CALLER (it is a context
manager; the orchestrator opens it, holds it through solve, closes it).

=============================================================================
THE FLOW
=============================================================================

STEP 1: build the default toolset (calculator + KB tools; + memory search
        when a store is provided; + caller extras).
        |
STEP 2: compose identity: psyche + available-collections line + inhale block
        (bounded; skipped cleanly when inhale=False or nothing fires).
        |
STEP 3: construct the Mind (mirror off by default — free-tier models bury
        output inside the reflection protocol; per-model toggling is 4.1's
        ModelProfile job) and return it with a BootReport.

=============================================================================
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # standalone-run safety

from jarvis_core.config import KB_PATH
from jarvis_core.agent.mind import Mind, JARVIS_PSYCHE_PROMPT
from jarvis_core.agent.tool import Tool
from jarvis_core.agent.tools.calc import CalculatorTool
from jarvis_core.agent.tools.cognitive import CognitiveMirrorTool, PriorSelfConsultTool
from jarvis_core.agent.tools.memory import MemorySemanticSearchTool
from jarvis_core.brain.context_injector import (
    ContextInjector, InhaleResult, default_providers,
)
from jarvis_core.brain.model_profiles import ModelProfile


# =============================================================================
# Part 1: CONTRACT (frozen)
# =============================================================================

@dataclass(frozen=True)
class BootReport:
    """What this boot actually assembled — printed by hosts, asserted by tests."""
    tools: Tuple[str, ...]
    providers_fired: Tuple[str, ...]
    providers_skipped: Tuple[str, ...]
    inhale_chars: int
    model: str
    collections: Tuple[str, ...]
    profile: str = "none"   # resolved ModelProfile source label, or "none"
    mirror: bool = False    # the enable_mirror actually applied (profile-driven)


# =============================================================================
# Part 2: THE ASSEMBLER
# =============================================================================

def _machine_name() -> str:
    return os.environ.get(
        "JARVIS_MACHINE", os.uname().nodename if hasattr(os, "uname") else "unknown")


def _list_collections(store: Any) -> List[str]:
    try:
        return [c.name for c in store._client.list_collections()]
    except Exception:
        return []


def assemble_mind(
    llm_call: Any,
    store: Optional[Any] = None,
    kb_path: Path = KB_PATH,
    inhale: bool = True,
    injector: Optional[ContextInjector] = None,
    extra_tools: Optional[Dict[str, Tool]] = None,
    enable_mirror: bool = False,
    max_iterations: int = 8,
    clock: Optional[Callable[[], datetime]] = None,
    profile_path: Optional[Path] = None,
    queue_path: Optional[Path] = None,
    profile: Optional[ModelProfile] = None,
    profile_label: str = "none",
) -> Tuple[Mind, BootReport]:
    """
    Compose a fully-conscious Mind from the standard organs.

    EXECUTION FLOW:
    1. Toolset: calculator + prior_self_consult + cognitive_mirror (the KB
       autobiography, L324 gap 1) + memory_semantic_search when a store is
       open + caller extras (extras win on name collision).
    2. Identity: JARVIS_PSYCHE_PROMPT + collections line + boot inhale block.
    3. Conduct: a resolved ModelProfile (Stage 4.1) drives enable_mirror /
       enable_monitor / max_iterations — per-model DATA, not a hardcode. No
       profile -> the caller's args stand (back-compat). Mind itself untouched.

    Returns:
        (mind, BootReport) — the report says what actually got wired.
    """
    # Conduct from the profile when present; else the caller's args (back-compat).
    applied_mirror = profile.mirror_ok if profile else enable_mirror
    applied_monitor = profile.enable_monitor if profile else True
    applied_max_iter = profile.max_iterations if profile else max_iterations
    tools: Dict[str, Tool] = {
        "calculator": CalculatorTool(),
        "prior_self_consult": PriorSelfConsultTool(kb_path=kb_path),
        "cognitive_mirror": CognitiveMirrorTool(kb_path=kb_path),
    }
    collections: List[str] = []
    if store is not None:
        collections = _list_collections(store)
        tools["memory_semantic_search"] = MemorySemanticSearchTool(store=store)
    if extra_tools:
        tools.update(extra_tools)

    model = str(getattr(llm_call, "model", "") or "")
    identity = JARVIS_PSYCHE_PROMPT
    # Tool guidance — the L324 lesson: wiring the autobiography tool is not
    # enough; the Mind must know WHICH organ holds its history, or it reaches
    # for document search and finds nothing (observed live, Gate A 2026-06-12).
    identity += (
        "\n\nTool guidance: prior_self_consult is your AUTOBIOGRAPHY — the "
        "project's own knowledge base (what was built, decisions, failures, "
        "history). For any question about what we built/decided/did, call "
        "prior_self_consult FIRST with a topical query string."
    )
    if collections:
        identity += (
            f" memory_semantic_search searches document collections "
            f"{collections} — pass one of these collection names explicitly; "
            f"it holds documents, NOT the project history."
        )

    result: InhaleResult = InhaleResult(block="", fired=(), skipped=())
    if inhale:
        active = injector or ContextInjector(default_providers(
            clock=clock,
            self_state=f"Runtime brain: {model or '<auto>'} | machine: {_machine_name()}",
            profile_path=profile_path,
            queue_path=queue_path,
        ))
        result = active.inhale()
        if result.block:
            identity += "\n\n" + result.block

    mind = Mind(
        llm_call=llm_call,
        tools=tools,
        max_iterations=applied_max_iter,
        enable_mirror=applied_mirror,
        enable_monitor=applied_monitor,
        allow_replan=True,
        identity_prompt=identity,
    )
    report = BootReport(
        tools=tuple(sorted(tools)),
        providers_fired=result.fired,
        providers_skipped=result.skipped,
        inhale_chars=len(result.block),
        model=model,
        collections=tuple(collections),
        profile=profile_label,
        mirror=applied_mirror,
    )
    return mind, report


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS (offline — scripted LLM, temp artifacts)
# =============================================================================

def _run_self_test() -> None:
    import asyncio
    import json
    import tempfile
    from datetime import timedelta, timezone

    print("=" * 70)
    print("  boot.py -- Smoke Tests")
    print("=" * 70)
    passed = 0
    failed: List[str] = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        nonlocal passed
        if cond:
            passed += 1
        else:
            failed.append(f"FAIL: {name}" + (f" ({hint})" if hint else ""))

    _IST = timezone(timedelta(hours=5, minutes=30))
    FIXED = datetime(2026, 6, 12, 12, 0, tzinfo=_IST)

    def scripted(responses: List[str]):
        idx = [0]
        def llm(messages: List[Dict[str, str]]) -> str:
            i = idx[0]
            if i >= len(responses):
                return "DONE."
            idx[0] += 1
            return responses[i]
        llm.model = "scripted-brain-1"  # type: ignore[attr-defined]
        return llm

    async def scenario() -> None:
        nonlocal passed
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            kb = tdp / "kb.jsonl"
            kb.write_text(json.dumps({
                "id": 1, "timestamp": FIXED.isoformat(), "type": "Decision",
                "tags": ["stage-4", "route-target"], "expiry": "Permanent",
                "content": "Decision: we chose the RouteTarget contract for Stage 4 routing.",
            }) + "\n", encoding="utf-8")
            profile = tdp / "profile.md"
            profile.write_text("PROFILE-MARKER-XYZ: depth over brevity.", encoding="utf-8")
            queue = tdp / "queue.jsonl"
            queue.write_text("", encoding="utf-8")

            # T1-T6: full assembly — psyche + inhale + autobiography all reach the run
            llm = scripted([
                json.dumps([{"tool_name": "prior_self_consult",
                             "description": "consult the KB"}]),
                json.dumps({"name": "prior_self_consult",
                            "arguments": {"query": "RouteTarget contract decision"}}),
                "We decided on the RouteTarget contract.",
            ])
            mind, report = assemble_mind(
                llm_call=llm, kb_path=kb, clock=lambda: FIXED,
                profile_path=profile, queue_path=queue,
            )
            res = await mind.solve("what did we decide about routing?")
            sys_msg = res.react.messages[0]["content"]

            check("T1 psyche present", "You are JARVIS" in sys_msg)
            check("T2 inhale block reaches the system prompt",
                  "LIVE SYSTEM STATE" in sys_msg and "2026-06-12T12:00:00" in sys_msg)
            check("T3 profile inhaled", "PROFILE-MARKER-XYZ" in sys_msg)
            check("T4 self-state line carries the brain id",
                  "Runtime brain: scripted-brain-1" in sys_msg)
            check("T5 autobiography tool wired AND answers from the KB",
                  any(tc.name == "prior_self_consult"
                      and "RouteTarget contract" in str(tr.output)
                      for tc, tr in res.react.tool_calls),
                  str([(tc.name, str(tr.output)[:60]) for tc, tr in res.react.tool_calls]))
            check("T6 report names the standard toolset",
                  {"calculator", "prior_self_consult", "cognitive_mirror"}
                  <= set(report.tools), str(report.tools))

            # T7: report bookkeeping is honest
            check("T7 report providers/chars consistent",
                  "Temporal" in report.providers_fired
                  and report.inhale_chars > 0 and report.model == "scripted-brain-1",
                  str(report))

            # T8: inhale=False -> bare psyche, no live-state block
            mind8, report8 = assemble_mind(llm_call=scripted(["ok"]), kb_path=kb,
                                           inhale=False)
            res8 = await mind8.solve("x")
            check("T8 inhale opt-out", "LIVE SYSTEM STATE" not in res8.react.messages[0]["content"]
                  and report8.inhale_chars == 0 and report8.providers_fired == ())

            # T9: no store -> no memory tool, no collections line (graceful)
            check("T9 storeless boot has no memory tool",
                  "memory_semantic_search" not in report.tools
                  and "Available memory collections" not in sys_msg)

            # T10: extra tools merge and win on collision
            class FakeStore:
                class _client:  # noqa: N801
                    @staticmethod
                    def list_collections():
                        class C:  # noqa: N801
                            name = "research_papers"
                        return [C()]
            mind10, report10 = assemble_mind(
                llm_call=scripted(["ok"]), kb_path=kb, store=FakeStore(), inhale=False,
                extra_tools={"calculator": CalculatorTool()},
            )
            check("T10 store wires memory tool + collections line",
                  "memory_semantic_search" in report10.tools
                  and report10.collections == ("research_papers",), str(report10))

            # T11: psyche is NEVER absent (L323 directive — identity not left
            # to the substrate), even with inhale off and no store
            check("T11 identity never left to the substrate",
                  "You are JARVIS" in res8.react.messages[0]["content"])

            # T12: a ModelProfile drives conduct (Stage 4.1) — mirror/max_iter
            # come from the profile DATA, recorded honestly in the BootReport.
            from jarvis_core.brain.model_profiles import ModelProfile
            prof = ModelProfile(mirror_ok=True, enable_monitor=False,
                                 max_iterations=5, notes="test")
            mind12, report12 = assemble_mind(
                llm_call=scripted(["ok"]), kb_path=kb, inhale=False,
                profile=prof, profile_label="family:test")
            check("T12 profile drives conduct + recorded in report",
                  mind12._enable_mirror is True and mind12._max_iterations == 5
                  and report12.profile == "family:test" and report12.mirror is True,
                  f"{report12.profile}/{report12.mirror}")

            # T13: no profile -> caller args stand (back-compat, mirror off default)
            mind13, report13 = assemble_mind(
                llm_call=scripted(["ok"]), kb_path=kb, inhale=False)
            check("T13 no profile -> back-compat defaults (mirror off)",
                  mind13._enable_mirror is False and report13.profile == "none"
                  and report13.mirror is False)

            # T12: tool guidance names the autobiography organ (Gate A lesson:
            # a wired-but-unlabeled tool still loses to document search)
            check("T12 autobiography tool guidance present",
                  "prior_self_consult is your AUTOBIOGRAPHY" in sys_msg)
            res10 = await mind10.solve("y")
            check("T12b collections guidance present when store open",
                  "research_papers" in res10.react.messages[0]["content"])

    asyncio.run(scenario())

    total = passed + len(failed)
    print(f"\n  Passed: {passed}/{total}")
    if failed:
        for f_ in failed:
            print(f"  {f_}")
        print("=" * 70)
        raise SystemExit(1)
    print(f"  All {total} boot smoke tests passed.")
    print("=" * 70)


if __name__ == "__main__":
    _run_self_test()
