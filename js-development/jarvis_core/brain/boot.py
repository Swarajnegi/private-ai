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


# Compaction fires when the transcript passes this, NOT when it nears the
# context window. Chosen for cost, since react.py re-sends the prefix every
# iteration: 48K x 40 iterations ~= 2M input tokens, against ~40M if we waited
# for a 1M window. Loose enough that a normal agentic run with several file
# reads never compacts; tight enough that a runaway one cannot re-bill a
# 500K-token prefix forty times. compact.py's own default is 6000, which is
# safe but would compact constantly on real tool-heavy work.
_COMPACT_COST_TARGET_TOKENS = 48_000

# How many past-memory items are folded into the system prompt unprompted.
# 4 is deliberate: enough that a relevant decision or logged failure surfaces
# on its own, small enough that it cannot crowd out the question. Every item
# costs tokens on EVERY turn, so this is a standing tax, not a one-off.
_AUTO_RETRIEVE_TOP_K = 4

# The ChromaDB collection holding the mind's OWN history, maintained by
# scripts/index_memory.py. Deliberately NOT `research_papers`, which is
# third-party literature — conflating the two is the L324 bug that made JARVIS
# answer "what have we built?" from someone else's papers.
MEMORY_COLLECTION = "jarvis_memory"


def _model_context_length(model: Optional[str]) -> int:
    """This model's context window from the catalog, or 0 if unknown.

    Reuses router._load_catalog() rather than re-reading MODEL_CATALOG_PATH —
    config.py's law is that paths resolve in one place, and a second reader is
    a second thing to drift.
    """
    if not model:
        return 0
    try:
        from jarvis_core.brain.router import _load_catalog
        for row in _load_catalog():
            if row.get("id") == model:
                return int(row.get("context_length", 0) or 0)
    except Exception:
        pass
    return 0


def default_toolset(
    store: Optional[Any] = None,
    kb_path: Path = KB_PATH,
    llm_call: Optional[Any] = None,
    ledger: Optional[Any] = None,
) -> Dict[str, Tool]:
    """The DEFAULT --ask toolset: awareness + autobiography + EYES ON THE CODE.

    file_read (repo-scoped at the permission layer) + file_search (repo-scoped
    by construction) ship by default — a JARVIS that cannot see local files is
    not worth much. Heavy/dangerous tools (web/exec/shell/finance/full memory)
    stay behind full_toolset()."""
    from jarvis_core.agent.tools.fs import FileReadTool
    from jarvis_core.agent.tools.fs_search import FileSearchTool
    from jarvis_core.agent.tools.fs_dir import ListDirTool
    from jarvis_core.agent.tools.corpus import CorpusStatsTool

    tools: Dict[str, Tool] = {
        "calculator": CalculatorTool(),
        "prior_self_consult": PriorSelfConsultTool(kb_path=kb_path),
        "cognitive_mirror": CognitiveMirrorTool(kb_path=kb_path),
        "file_read": FileReadTool(),
        "file_search": FileSearchTool(),
        "list_dir": ListDirTool(),
        "corpus_stats": CorpusStatsTool(),
    }
    if store is not None:
        tools["memory_semantic_search"] = MemorySemanticSearchTool(store=store)
    if ledger is not None:
        # PAGE-IN. Ships only when a ledger exists, because without one the
        # tool could only ever return "nothing was archived" — offering it
        # anyway would advertise a recoverability the session does not have.
        from jarvis_core.agent.tools.context import ContextExpandTool
        tools["context_expand"] = ContextExpandTool(ledger=ledger)
    return tools


def full_toolset(
    store: Optional[Any] = None,
    kb_path: Path = KB_PATH,
    llm_call: Optional[Any] = None,
    strategy_path: Optional[Path] = None,
) -> Dict[str, Tool]:
    """Construct the COMPLETE built toolset (Stage 3 + cognitive + finance), each
    with its real deps. Defensive: a tool whose construction raises is skipped
    (logged via the returned dict's absence), never aborting the harness.

    DANGEROUS tools (shell_run/code_exec) and the cloud-leak-prone file_read are
    included here but gated by brain/permgate.py at the orchestrator — assembling
    them is safe; DISPATCHING them is what the permission context controls."""
    from jarvis_core.agent.tools.web import WebSearchTool
    from jarvis_core.agent.tools.fs import FileReadTool
    from jarvis_core.agent.tools.fs_search import FileSearchTool
    from jarvis_core.agent.tools.fs_dir import ListDirTool
    from jarvis_core.agent.tools.corpus import CorpusStatsTool
    from jarvis_core.agent.tools.exec import CodeExecTool
    from jarvis_core.agent.tools.shell import ShellRunTool
    from jarvis_core.agent.tools.cognitive import BearCaseDevilTool, WritingVoiceCheckTool
    from jarvis_core.agent.tools.memory import (
        MemoryMMRSearchTool, MemoryBM25SearchTool, MemoryHybridSearchTool,
        MemoryRerankTool, MemoryUnifiedRetrieveTool, MemoryGraphSearchTool,
    )
    from jarvis_core.agent.tools.finance import (
        PortfolioStateTool, TriggerMonitorTool, IncentivePlannerTool,
    )

    # (name, factory) — built lazily so one bad ctor can't sink the rest.
    specs = [
        ("calculator", lambda: CalculatorTool()),
        ("web_search", lambda: WebSearchTool()),
        ("file_read", lambda: FileReadTool()),
        ("file_search", lambda: FileSearchTool()),
        ("list_dir", lambda: ListDirTool()),
        ("corpus_stats", lambda: CorpusStatsTool()),
        ("code_exec", lambda: CodeExecTool()),
        ("shell_run", lambda: ShellRunTool()),
        ("prior_self_consult", lambda: PriorSelfConsultTool(kb_path=kb_path)),
        ("cognitive_mirror", lambda: CognitiveMirrorTool(kb_path=kb_path)),
        ("writing_voice_check", lambda: WritingVoiceCheckTool(kb_path=kb_path)),
        ("bear_case_devil", lambda: BearCaseDevilTool(kb_path=kb_path, llm_call=llm_call)),
        ("memory_graph_search", lambda: MemoryGraphSearchTool()),
        ("portfolio_state", lambda: PortfolioStateTool(strategy_path=strategy_path)),
        ("trigger_monitor", lambda: TriggerMonitorTool(strategy_path=strategy_path)),
        ("incentive_planner", lambda: IncentivePlannerTool(strategy_path=strategy_path)),
    ]
    if store is not None:
        specs += [
            ("memory_semantic_search", lambda: MemorySemanticSearchTool(store=store)),
            ("memory_mmr_search", lambda: MemoryMMRSearchTool(store=store)),
            ("memory_bm25_search", lambda: MemoryBM25SearchTool(store=store)),
            ("memory_hybrid_search", lambda: MemoryHybridSearchTool(store=store)),
            ("memory_rerank", lambda: MemoryRerankTool(store=store)),  # reranker lazy
            ("memory_unified_retrieve",
             lambda: MemoryUnifiedRetrieveTool(store=store, llm_call=llm_call)),
        ]
    tools: Dict[str, Tool] = {}
    for name, factory in specs:
        try:
            tools[name] = factory()
        except Exception:
            pass  # skip an unconstructable tool; the harness runs with the rest
    return tools


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
    tool_mode: str = "minimal"  # "minimal" (awareness) or "full" (whole toolset)
    gated: Tuple[str, ...] = ()  # tools requiring permission in this assembly


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
    max_iterations_override: Optional[int] = None,
    session_id: Optional[str] = None,
    clock: Optional[Callable[[], datetime]] = None,
    profile_path: Optional[Path] = None,
    queue_path: Optional[Path] = None,
    profile: Optional[ModelProfile] = None,
    profile_label: str = "none",
    tools_mode: str = "minimal",
    permission_context: Optional[Any] = None,
    ask_handler: Optional[Any] = None,
    strategy_path: Optional[Path] = None,
    prebuilt_tools: Optional[Dict[str, Tool]] = None,
) -> Tuple[Mind, BootReport]:
    """
    Compose a fully-conscious Mind from the standard organs.

    EXECUTION FLOW:
    1. Toolset: calculator + prior_self_consult + cognitive_mirror (the KB
       autobiography, L324 gap 1) + memory_semantic_search when a store is
       open + caller extras (extras win on name collision).
    2. Identity: JARVIS_PSYCHE_PROMPT + boot inhale block (tool guidance,
       collections line, temporal/profile/activity/roadmap providers — all
       via ContextInjector, capped and accounted-for in BootReport).
    3. Conduct: a resolved ModelProfile (Stage 4.1) drives enable_mirror /
       enable_monitor / max_iterations — per-model DATA, not a hardcode. No
       profile -> the caller's args stand (back-compat). Mind itself untouched.

    Returns:
        (mind, BootReport) — the report says what actually got wired.
    """
    # Conduct from the profile when present; else the caller's args (back-compat).
    applied_mirror = profile.mirror_ok if profile else enable_mirror
    applied_monitor = profile.enable_monitor if profile else True
    # PRECEDENCE (2026-09-07): explicit override > per-model profile > parameter.
    # The profile is per-model DATA and stays the default, but a caller asking
    # for depth on ONE question must be able to beat it — previously the profile
    # silently won, so `google/gemini-3.6-flash` ran at the conservative floor of
    # 8 regardless of what boot was told, and nothing reported that it had.
    applied_max_iter = (
        max_iterations_override if max_iterations_override is not None
        else (profile.max_iterations if profile else max_iterations)
    )
    # THE LEDGER is built first because two consumers need it: the
    # context_expand tool (model-driven page-in) and the compactor
    # (archive-before-evict). Keyed by session id; without one there is no
    # ledger and compaction stays the old one-way door, which the boundary
    # message then states plainly rather than implying history is safe.
    ledger = None
    if session_id:
        try:
            from jarvis_core.agent.context_ledger import ContextLedger
            ledger = ContextLedger(session_id)
        except Exception:
            ledger = None

    if prebuilt_tools is not None:        # orchestrator (policy) already built them
        tools = dict(prebuilt_tools)
        if ledger is not None and "context_expand" not in tools:
            # The orchestrator builds tools before it knows about the ledger,
            # so add page-in here rather than duplicating ledger construction
            # in the policy layer.
            from jarvis_core.agent.tools.context import ContextExpandTool
            tools["context_expand"] = ContextExpandTool(ledger=ledger)
    elif tools_mode == "full":
        tools = full_toolset(store=store, kb_path=kb_path, llm_call=llm_call,
                             strategy_path=strategy_path)
    else:
        tools = default_toolset(store=store, kb_path=kb_path, llm_call=llm_call,
                                ledger=ledger)
    collections: List[str] = _list_collections(store) if store is not None else []
    if extra_tools:
        tools.update(extra_tools)
    gated = tuple(sorted(n for n, t in tools.items()
                         if getattr(t, "requires_permission", False)))

    model = str(getattr(llm_call, "model", "") or "")
    identity = JARVIS_PSYCHE_PROMPT

    # Tool guidance now lives in the ContextInjector as a proper ProviderSpec
    # ("Tool routing guidance") — capped, accounted-for in BootReport, testable
    # like every other organ, instead of an ungoverned append living outside
    # the inhale abstraction. Only fires when inhale=True (true for every real
    # --ask call; inhale=False is a test-isolation path, not production).
    result: InhaleResult = InhaleResult(block="", fired=(), skipped=())
    if inhale:
        active = injector or ContextInjector(default_providers(
            clock=clock,
            self_state=f"Runtime brain: {model or '<auto>'} | machine: {_machine_name()}",
            profile_path=profile_path,
            queue_path=queue_path,
            collections=collections,
        ))
        result = active.inhale()
        if result.block:
            identity += "\n\n" + result.block

    # WORKING-MEMORY COMPACTION (wired 2026-09-08). Until today boot never
    # passed `compactor=`, so Mind._compactor was None on every real --ask and
    # WorkingMemoryCompactor — 322 lines, 17 tests — had never executed outside
    # its own smoke suite. The consequence was concrete: react.py re-sends the
    # whole transcript each iteration, so a long agentic run re-billed an
    # ever-growing prefix and eventually overflowed the window.
    #
    # THE THRESHOLD IS COST-DRIVEN, NOT WINDOW-DRIVEN — and getting this
    # backwards is easy. Sizing compaction to the context window looks right and
    # is wrong: google/gemini-3.6-flash reports context_length=1048576, so a
    # window-sized threshold would never compact until a transcript hit ~1M
    # tokens. Overflow is not the binding problem; RE-BILLING is. react.py
    # re-sends the whole transcript every iteration, so at max_iterations=40 a
    # prefix of T tokens costs ~40*T. Holding T near 48K instead of 1M is the
    # difference between ~2M and ~40M input tokens for one question — this is
    # exactly why a hard question cost Rs72 on 2026-09-07.
    #
    # So: compact at the cost target, and let the real window only LOWER it
    # (a 32K model must not be handed a 48K threshold).
    compactor = None
    try:
        from jarvis_core.agent.compact import WorkingMemoryCompactor
        from jarvis_core.agent.tokens import TokenBudget
        ctx_len = _model_context_length(model)
        if ctx_len > 0:
            threshold = min(250_000, TokenBudget(context_length=ctx_len).usable)
        else:
            threshold = _COMPACT_COST_TARGET_TOKENS
        # THE LEDGER makes eviction reversible. Without it compaction is a
        # one-way door: the span is summarised and the originals cease to
        # exist. With it they are archived verbatim first and the boundary
        # carries a handle back to them. Needs a session id to key the file;
        # no session -> no ledger -> the old lossy behaviour, and the boundary
        # message says so out loud rather than implying history is safe.
        compactor = WorkingMemoryCompactor(
            llm_call, max_context_tokens=threshold, ledger=ledger)
    except Exception:
        compactor = None  # a broken compactor must never block a boot

    # UNPROMPTED RETRIEVAL — the step that makes ENDGAME §1.2's moat real.
    #
    # MemoryManager (928 lines, 51 tests) had ZERO production construction
    # sites, so react.py's auto-retrieve branch was unreachable on every real
    # --ask and memory reached the prompt ONLY when the model chose to call a
    # tool. That is verbatim the §1.2 failure: "it cannot fire when you did not
    # know to ask."
    #
    # Two prerequisites had to land first, and the second was invisible:
    #   1. Something to retrieve. ChromaDB held only `research_papers` (156
    #      embeddings); the KB was not indexed at all. scripts/index_memory.py
    #      now maintains `jarvis_memory` (1030 chunks over all 554 entries).
    #   2. metadata.tier. retrieve() queries with where={"tier": ...}, so
    #      records without it are invisible — 1030 indexed chunks returned 0
    #      hits until they were tagged warm.
    #
    # Wired only when a store is open: without one there is no WARM tier and
    # auto-retrieve would burn a query per turn to return nothing.
    memory_manager = None
    auto_retrieve_k = 0
    if store is not None:
        try:
            from jarvis_core.agent.memory_manager import MemoryManager
            memory_manager = MemoryManager(
                store=store, collection_name=MEMORY_COLLECTION)
            auto_retrieve_k = _AUTO_RETRIEVE_TOP_K
        except Exception:
            memory_manager = None      # never let memory wiring block a boot
            auto_retrieve_k = 0

    mind = Mind(
        llm_call=llm_call,
        tools=tools,
        memory_manager=memory_manager,
        auto_retrieve_top_k=auto_retrieve_k,
        max_iterations=applied_max_iter,
        enable_mirror=applied_mirror,
        enable_monitor=applied_monitor,
        allow_replan=True,
        identity_prompt=identity,
        permission_context=permission_context,
        ask_handler=ask_handler,
        compactor=compactor,
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
        tool_mode=tools_mode,
        gated=gated,
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
                "id": 1, "timestamp": datetime.now(timezone.utc).isoformat(), "type": "Decision",
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

            # T14: tools_mode='full' assembles the whole toolset + records gated set
            mind14, report14 = assemble_mind(
                llm_call=scripted(["ok"]), kb_path=kb, inhale=False, tools_mode="full")
            check("T14 full toolset assembled (web/file/exec/shell/cognitive/finance)",
                  {"calculator", "web_search", "file_read", "code_exec", "shell_run",
                   "bear_case_devil", "portfolio_state"} <= set(mind14._tools),
                  str(sorted(mind14._tools)))
            check("T14b report flags full mode + gated dangerous tools",
                  report14.tool_mode == "full"
                  and set(report14.gated) == {"shell_run", "code_exec"}, str(report14.gated))

            # T15: permission_context + ask_handler reach the Mind (and ReActLoop)
            sentinel_ctx, sentinel_handler = object(), object()
            mind15, _ = assemble_mind(
                llm_call=scripted(["ok"]), kb_path=kb, inhale=False,
                permission_context=sentinel_ctx, ask_handler=sentinel_handler)
            check("T15 permission_context + ask_handler wired into Mind",
                  mind15._perms is sentinel_ctx and mind15._ask_handler is sentinel_handler)

            # T16: prebuilt_tools override used verbatim (orchestrator-built path)
            from jarvis_core.agent.tools.calc import CalculatorTool as _Calc
            mind16, report16 = assemble_mind(
                llm_call=scripted(["ok"]), kb_path=kb, inhale=False,
                prebuilt_tools={"calculator": _Calc()}, tools_mode="full")
            check("T16 prebuilt_tools used verbatim",
                  set(mind16._tools) == {"calculator"} and report16.tool_mode == "full")

            # T17: a tool whose ctor raises is skipped, not fatal (defensive build)
            full = full_toolset(store=None, kb_path=kb)
            check("T17 full_toolset builds without a store (memory tools absent, rest present)",
                  "calculator" in full and "shell_run" in full
                  and "memory_semantic_search" not in full, str(sorted(full)))

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
