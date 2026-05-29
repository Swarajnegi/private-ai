# PHASE 3: Agent Framework Roadmap

> **Master Plan Position:** Phase 3 of 6 → [JARVIS_MASTER_ROADMAP.md](../JARVIS_MASTER_ROADMAP.md)
> **Goal:** Build `jarvis_core/agent/` from scratch — autonomous agents that plan, use tools, execute multi-step tasks, and self-manage memory. JARVIS owns the runtime.
> **Prerequisites:** Phase 1 (Systems Python), Phase 2 (Memory Layer)
> **Architectural decision:** Per **Decision 2026-05-13** (reverses 2026-05-01 OpenClaude delegation), JARVIS owns its agent runtime. The earlier "Stage 3 = single mcp_bridge.py" plan from [STAGE_3_OPENCLAUDE_STRATEGY.md](../../STAGE_3_OPENCLAUDE_STRATEGY.md) is SUPERSEDED.

---

## Overview

| Sub-Phase | Name | Core Concept | Definition of Done |
|-----------|------|--------------|--------------------|
| **3.0** | Entry Sprint (Foundations) | Tool ABC + Registry + Cost accounting | `jarvis_core/agent/{registry,cost,tool}.py` shipped with smoke tests |
| **3.1** | Function Calling & Structured Output | LLMs that invoke structured functions reliably | Agent produces guaranteed-valid JSON tool calls; `Cognitive_State_Update` + `TextTelemetry` schemas land |
| **3.2** | Tool Design & Registration | Composable tool libraries built on the 3.0 registry | 10+ tools registered with type-safe schemas |
| **3.3** | Planning & Decomposition | Break complex queries into ordered steps | Agent decomposes multi-step tasks correctly + replans on failure |
| **3.4** | ReAct Pattern + Reflection | Reason → Act → Observe loop with MIRROR-lite reflection | ReAct agent with trace logging + CoT loop detector |
| **3.5** | Memory-Augmented Agents (MemGPT) | Self-editing memory with heartbeat consolidation | Agent self-manages memory; heartbeat writes survive kb_compact |

**Estimated total: 10–14 weeks.** Compressed via OpenJarvis STEAL targets (Apache 2.0 source-copy).

---

## Sub-Phase 3.0: Entry Sprint -- Foundations [OK] COMPLETE

**Goal:** Land the three foundation files that everything else builds on. These are direct ports from OpenJarvis (Apache 2.0 reference implementation, see KB Decisions L231–L236 for STEAL #1–#6).

| Lesson | Topic | Source / Reference | Command |
|--------|-------|--------------------|---------|
| 3.0.1 | `jarvis_core/agent/registry.py` (STEAL #1) | `OpenJarvis/src/openjarvis/core/registry.py:19-172` -- `RegistryBase[T]` decorator pattern with per-subclass isolation | **COMPLETE** -- RegistryBase[T] with per-subclass isolation, decorator registration, get/list/count API. Smoke tests pass. |
| 3.0.2 | `jarvis_core/agent/cost.py` (STEAL #2 + **STEAL #11**) | OpenJarvis `engine/cloud.py:22-48,165-176` PRICING dict + OpenClaude `src/utils/modelCost.ts` MODEL_COSTS (cache-tier model, web-search fees) + `src/cost-tracker.ts` per-session accumulator + RunPod GPU-hour rates from `JARVIS_ENDGAME.md` Section 2 | **COMPLETE** -- ModelPricing frozen dataclass, PRICING dict (10 models, cache tiers), RUNPOD_GPU_RATES (6 GPUs), CostTracker per-session accumulator with budget gating. Smoke tests pass. |
| 3.0.3 | `jarvis_core/agent/tool.py` (Tool ABC, prep for **STEAL #8**) | Tool ABC: `name`, `description`, `input_schema` (Pydantic), `invoke()` async, **`is_concurrency_safe()` predicate** (preset now for STEAL #8 in 3.4) | **COMPLETE** -- Tool ABC with Pydantic ToolInput, ToolResult frozen dataclass, async invoke(), is_concurrency_safe predicate, schema_for_llm(), safe_invoke() dispatcher wrapper. Smoke tests pass. |

**Practical Exercise:** Register a `calculator(expr: str) -> float` tool via the new registry and call it through cost-accounting wrappers. Smoke test in `__main__` block.

**Why this slot:** The original Stage 3.1–3.5 lessons all reference "tools" and "registry" without owning them. Pulling foundations forward into 3.0 means every subsequent lesson lands code rather than reinventing primitives.

---

## Sub-Phase 3.1: Function Calling & Structured Output [OK] COMPLETE

**Goal:** Understand how LLMs invoke structured functions — and guarantee valid output. Land the metacognitive schemas while constrained-generation is on the table.

| Lesson | Topic | JARVIS Use Case | Status |
|--------|-------|-----------------|--------|
| 3.1.1 | Function Calling Basics | LLM outputs structured tool calls | **COMPLETE** -- concept covered via KB L19 (agent reliability gaps) + L272 (parse_tool_call architecture). |
| 3.1.2 | JSON Schema for Tools | Define what tools accept | **COMPLETE** -- `parser.py` (573 lines) + KB L273 Procedural (robust JSON extraction: fence/brace fallback regex). |
| 3.1.3 | Parsing Tool Outputs | Handle LLM function call responses | **COMPLETE** -- `parser.py` parse_tool_call + dispatch + dispatch_batch (concurrency partition via asyncio.gather). KB L272. |
| 3.1.4 | Error Handling | Gracefully handle malformed calls | **COMPLETE** -- `errors.py` (656 lines): ErrorHandler recovery-policy layer, 5 ToolErrorKinds, per-tool RetryPolicy budgets, BUDGET_EXCEEDED abort. KB L275. |
| 3.1.5 | Structured Generation (outlines/guidance) | Guarantee valid JSON via constrained decoding | **COMPLETE** -- Pydantic schemas in `state.py` are the constrained-generation contract; KB L19 (concept) + L175 (deferral history reversed). |
| **3.1.6** | **`Cognitive_State_Update` Pydantic schema** (metacognitive integration, Decision 2026-05-13) | Typed contract for what the metacognitive daemon writes — defined NOW even though writes start in 3.5 | **COMPLETE** -- `state.py` (493 lines): CognitiveStateUpdate + UserTelemetryState (TextTelemetrySnapshot + acoustic stub). KB L276. |
| **3.1.7** | **`TextTelemetry` dataclass** (metacognitive integration) | Text-only user-state inference (no voice until Stage 6): prompt_brevity, typo_density, correction_rate, rephrasing, sentiment_shift | **COMPLETE** -- `telemetry.py` (690 lines): TextTelemetry + analyzers. KB L277 (QWERTY adjacency heuristic 48% FP, replaced with specific transpositions + anomalous endings). |

**Practical Exercise:** ✅ `scripts/exercise_3_1.py` (142 lines) wires all 3.1 concepts together — calculator tool registered, parser handling tool-call JSON, error recovery, telemetry analyzers, and Cognitive_State_Update emission.

> **Why This Matters:** Without constrained decoding, tool-calling agents break randomly on malformed output. `outlines.generate.json(model, ToolCallSchema)` guarantees valid ToolCall every time. The model literally cannot produce invalid JSON. The metacognitive schemas land here because they ARE constrained-generation contracts.

---

## Sub-Phase 3.2: Tool Design & Registration <-- YOU ARE HERE (3/4 complete)

**Lessons 3.2.1 [OK] (concept, audited 2026-05-19 via /next) + 3.2.2 [OK] (18 callable tools shipped across Phases A/B/C) + 3.2.3 [OK] (lifecycle hooks landed 2026-05-29).**
**Next:** 3.2.4 Tool Composition (concept lesson).

**Phase A (commit 87f82c3, 2026-05-19):** Tool.requires_permission flag + temporal_resolver utility + 6 memory wrappers + calculator.
**Phase B (commit e865d18, 2026-05-19; refined eaa4a75):** web_search + file_read + code_exec + shell_run.
**Phase C (commit 346d232, 2026-05-22):** 4 cognitive tools (cognitive_mirror, prior_self_consult, bear_case_devil, writing_voice_check) + 3 finance tools (portfolio_state, trigger_monitor, incentive_planner).
**3.2.3 (this commit, 2026-05-29):** 4 lifecycle hooks on Tool ABC (setup/teardown/on_invoke_start/on_invoke_end) + safe_invoke() wraps invoke with hook calls (failures swallowed). MemoryBM25SearchTool.setup() proactive index warm; CodeExecTool + ShellRunTool teardown() subprocess hygiene.

Total 18 callable: 16 concurrency-safe, 2 unsafe + requires_permission (code_exec, shell_run).


**Goal:** Build a library of composable tools JARVIS can use, leveraging the 3.0 registry.

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 3.2.1 | Tool Abstraction Patterns | Composition strategies for the Tool ABC from 3.0 | `@[/learn] Explain Tool composition patterns.` |
| 3.2.2 | Built-in Tools | Calculator, web search, code execution, memory primitives | `/dev Implement core tools wrapping jarvis_core/memory/ store/hybrid/rerank as Tool implementations.` |
| 3.2.3 | Tool Lifecycle | Init, invoke, error handling, cleanup | **[OK] COMPLETE** -- 4 hooks on Tool ABC; safe_invoke wraps invoke with on_invoke_start + on_invoke_end (hook failures swallowed). MemoryBM25SearchTool.setup() proactive index; CodeExecTool + ShellRunTool teardown() subprocess hygiene. Smoke tests verify firing order setup -> (start->invoke->end)xN -> teardown. STEAL #5 hook points reserved in docstrings -- 3.4 EventBus wiring touches only hook bodies, not tool.py. |
| 3.2.4 | Tool Composition | Chain tools together; pipe outputs | `@[/learn] Explain tool composition patterns.` |

**Practical Exercise:** Build 10+ tools (5 memory primitives wrapped + calculator + web search + code exec + file I/O + shell) and let the agent choose which to use.

---

## Sub-Phase 3.3: Planning & Decomposition ⬜

**Goal:** Teach agents to break complex queries into steps.

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 3.3.1 | Task Decomposition | Break "research X" into sub-tasks | `@[/learn] Explain task decomposition in agents.` |
| 3.3.2 | Plan Representation | Structure a multi-step plan (Plan dataclass) | `/dev Design a Plan data structure for JARVIS.` |
| 3.3.3 | Plan Execution | Execute steps in order with state | `/dev Implement a PlanExecutor for JARVIS.` |
| 3.3.4 | Replanning | Adjust when steps fail | `@[/learn] Explain replanning strategies.` |

**Practical Exercise:** Agent correctly decomposes "Find papers on X and summarize top 3."

---

## Sub-Phase 3.4: ReAct Pattern + Reflection ⬜

**Goal:** Implement the Reason → Act → Observe loop. Absorb metacognitive review's MIRROR-lite + CoT loop detector here (Decision 2026-05-13).

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 3.4.1 | ReAct Overview | The core agent loop | `@[/learn] Explain the ReAct pattern.` |
| 3.4.2 | Trace Logging (STEAL #5) | Port OpenJarvis TraceStep + StepType + EventBus pattern | `/dev Port OpenJarvis traces/collector.py TraceStep + StepType enum + EventBus to jarvis_core/agent/trace.py for the ReAct loop.` |
| 3.4.3 | Observation Parsing | Handle tool outputs in the loop | `/dev Build an observation parser for ReAct.` |
| 3.4.4 | Loop Termination | Know when to stop | `@[/learn] Explain stopping conditions in agents.` |
| **3.4.5** | **MIRROR-lite system prompt** (metacognitive integration) | Single-pass structured reflection — instruct the model to evaluate Goals / Reasoning / Memory in one pass before responding. Zero extra inference cost. | `/dev Add MIRROR_LITE_PROMPT_TEMPLATE to jarvis_core/agent/react.py and inject it into the system prompt of every ReAct iteration.` |
| **3.4.6** | **CoT loop detector** (metacognitive integration) | Regex over `<think>` tag content for transition tokens (wait, alternatively, re-evaluate, actually, no,). Frequency > 2 per token-class = reasoning instability flag. | `/dev Implement MetaR1Monitor.from_cot_trace() in jarvis_core/agent/observer.py per metacognitive review Section 4 part C.` |
| **3.4.7** | **Tool concurrency partitioning (STEAL #8)** | Between LLM tool-call emission and dispatch: partition the tool-calls into `is_concurrency_safe=True` (batch via `asyncio.gather`) vs. stateful (serial). ~50% latency reduction on multi-tool turns. | `/dev Port OpenClaude src/services/tools/toolOrchestration.ts runTools partition logic to jarvis_core/agent/react.py dispatch step.` |
| **3.4.8** | **Hook-driven permission engine (STEAL #9)** | Declarative `allow/ask/deny` rules with wildcard/regex, loaded from settings JSON. Async classifiers per tool. Plan-mode equivalent gate. CRITICAL safety layer before Bash/Write/Edit. | `/dev Port OpenClaude src/hooks/toolPermission/PermissionContext.ts + src/utils/permissions/PermissionRule.ts to jarvis_core/agent/permissions.py. Schema + matcher + interactive CLI prompt.` |
| **3.4.9** | **Bash AST safe-command classifier (STEAL #10)** | Parse bash AST (via `bashlex`), auto-approve safe ops (grep/cat/ls/head/tail/wc/find) BEFORE permission UX. Block command substitution in array subscript position (per OpenClaude fix `4a98a4a`). | `/dev Port OpenClaude src/tools/BashTool/bashPermissions.ts as a BashClassifier hook inside the STEAL #9 PermissionContext. Use Python bashlex library.` |

**Practical Exercise:** ReAct agent answers a multi-hop question with tool use; trace records all reasoning, the loop detector flags any circular pattern, concurrency partitioning batches 3 read-only tool-calls in parallel, and the permission engine auto-approves `grep -n foo bar` while prompting for `rm -rf /tmp/`.

---

## Sub-Phase 3.5: Memory-Augmented Agents (MemGPT) ⬜

**Goal:** Agents that self-manage memory — heartbeat consolidation, hot/warm/cold tiers, self-editing.

> **PRE-3.5 DEPENDENCY (BLOCKING):** Patch `scripts/kb_compact.py` to exclude entries tagged `heartbeat-emitted` from structural-rule displacement. Without this, sleep-time consolidation writes get pruned as near-duplicates. See KB Decision 2026-05-13 metacognitive-integration.

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 3.5.1 | Working Memory | Short-term context for current task | `@[/learn] Explain working memory in agents.` |
| 3.5.2 | Long-Term Memory | Persist to Phase 2 vector store | `/dev Connect agent to ChromaDB memory via the Tool wrappers from 3.2.` |
| 3.5.3 | Memory Retrieval in Loop | RAG inside the agent loop | `/dev Implement memory-augmented ReAct.` |
| 3.5.4 | MemGPT Architecture | Hot/warm/cold memory hierarchy | `/research Analyze paper 2310.08560 (MemGPT) for JARVIS memory self-management.` |
| 3.5.5 | Self-Editing Memory | Agent decides what to remember/forget/update | `/dev Implement MemGPT-style memory manager for JARVIS.` |
| **3.5.6** | **Async heartbeat event loop** (metacognitive integration) | `request_heartbeat=true` flag on tool calls triggers async consolidation — event-driven, NOT clock-driven (per metacognitive review Section 2.2 hardware reality check) | `/dev Implement heartbeat scheduler in jarvis_core/agent/heartbeat.py with request_heartbeat flag on tool-call interface.` |
| **3.5.7** | **Sleep-time consolidation agent** (metacognitive integration) | Heartbeat-triggered task: read recent context, extract Cognitive_State_Update, write tagged `heartbeat-emitted` to KB | `/dev Implement consolidation agent in jarvis_core/agent/consolidator.py. Writes use Cognitive_State_Update schema from 3.1.6. ALL entries carry tag heartbeat-emitted.` |
| 3.5.8 | Agent Evaluation (STEAL #6) | Port OpenJarvis EvalRecord → EvalResult → RunSummary framework | `/dev Port OpenJarvis evals/core/{types,runner,scorer}.py to jarvis_core/agent/evals/ for p50/p95/p99 latency + cost reporting.` |
| **3.5.9** | **/compact-style working-memory compressor (STEAL #12)** | Async coroutine that, when context > N tokens, calls LLM with structured summarization prompt over the truncation window; emits `SystemCompactBoundaryMessage` dataclass replacing truncated history. TWIN PROCESS with heartbeat-emitted consolidation: /compact writes to short-term working memory, heartbeat writes long-term insights to KB. | `/dev Port OpenClaude src/services/compact/compact.ts pattern. Replace fork with async coroutine. Reuse jarvis_core/memory/compression.py LLM-filter as the summarization primitive.` |

**Practical Exercise:** Agent self-manages memory: heartbeat triggers consolidation between user turns, promotes important facts, evicts stale entries, remembers user preferences — all without manual `/memory` commands. `kb_compact.py` runs without displacing legitimate transient state observations. `/compact`-style working-memory compressor kicks in when context exceeds threshold, replacing old turns with a single summary boundary message.

> **Key Paper:** `2310.08560v2.pdf` (MemGPT) — already in your Research Papers folder. The agent treats memory like an OS virtual memory system: Hot = current context, Warm = pinned in ChromaDB, Cold = archived on disk.

---

## Final Boss: The Mind

Build a complete agent that:
1. [ ] Decomposes "Research topic X and write a summary" into steps
2. [ ] Uses tools: web search, memory retrieval, code execution
3. [ ] Follows ReAct loop with trace logging + MIRROR-lite reflection
4. [ ] Detects reasoning loops via CoT regex
5. [ ] Persists new learnings via heartbeat-driven sleep-time consolidation
6. [ ] Handles failures and replans
7. [ ] Survives kb_compact.py without losing heartbeat state observations

**When this works, JARVIS can think.**

---

## Progress Tracker

| Sub-Phase | Status | Lessons Complete |
|-----------|--------|------------------|
| 3.0 Entry Sprint (Registry + Cost-with-STEAL-#11 + Tool ABC-with-#8-prep) | [OK] Complete | 3/3 |
| 3.1 Function Calling + Cognitive_State_Update + TextTelemetry | [OK] Complete | 7/7 |
| 3.2 Tool Design & Registration (Phases A/B/C shipped — 18 callable tools; 3.2.3 lifecycle hooks shipped) | 🔄 In Progress | 3/4 |
| 3.3 Planning & Decomposition | ⬜ Not Started | 0/4 |
| 3.4 ReAct + MIRROR-lite + CoT detector + STEAL #8/#9/#10 | ⬜ Not Started | 0/9 |
| 3.5 Memory-Augmented Agents + Heartbeat Consolidation + /compact (STEAL #12) | ⬜ Not Started | 0/9 |

---

## What Got Reversed

The earlier "Stage 3 = single deliverable `mcp_bridge.py` exposing Memory primitives as MCP tools for OpenClaude" plan (Decision 2026-05-01, [STAGE_3_OPENCLAUDE_STRATEGY.md](../../STAGE_3_OPENCLAUDE_STRATEGY.md)) is SUPERSEDED per Decision 2026-05-13. The MCP bridge survives only as **optional Stage 5+ work** — *publishing* JARVIS Memory to external tools (Claude Desktop, Antigravity, third-party agents), not as the agent runtime.

---

## After This Phase

→ Proceed to **Phase 4: Multi-Model Orchestration** → [PHASE_04_ROADMAP.md](../orchestration-learning/PHASE_04_ROADMAP.md)
