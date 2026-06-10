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

## Sub-Phase 3.3: Planning & Decomposition 🔄 (2/4 builds shipped 2026-05-29)

**Build steps 3.3.2 + 3.3.3 shipped this commit.** Per user directive (skip-concept-prefer-build), the two concept lessons (3.3.1 + 3.3.4) are DEFERRED pending build-phase closure of Stage 3.

**Goal:** Teach agents to break complex queries into steps.

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 3.3.1 | Task Decomposition | Break "research X" into sub-tasks | ⊘ Deferred (concept lesson) |
| 3.3.2 | Plan Representation | Structure a multi-step plan (Plan dataclass) | **[OK] COMPLETE** -- `plan.py` (350+ LOC): StepStatus + PlanStatus enums, Step dataclass (mutable status/result/attempts), Plan dataclass (DAG with Kahn's-algorithm cycle detection at construction), ready_steps()/topological_order()/is_complete()/has_failed()/update_status() API, replan_from() lineage hook for 3.3.4, to_dict() serialization for 3.4 EventBus, build_plan() convenience helper. 32/32 smoke tests pass (linear chain, diamond DAG, cycle detection, self-cycle, missing deps, retry semantics, incremental add_step, replan_from clone behavior, to_dict, terminal-state property). |
| 3.3.3 | Plan Execution | Execute steps in order with state | **[OK] COMPLETE** -- `executor.py` (300+ LOC): PlanExecutor partitions ready_steps into concurrency-safe batch (asyncio.gather) vs serial unsafe (STEAL #8 prep), fires Tool lifecycle setup() at start + teardown() in finally, handles retries by bouncing failed steps back to PENDING within max_attempts budget, cascades upstream FAILED to downstream SKIPPED, max_iterations safety cap, optional StepObserver for STEAL #5 EventBus seam, swallows broken observer/hook exceptions. 34/34 smoke tests pass. |
| 3.3.4 | Replanning | Adjust when steps fail | ⊘ Deferred (concept lesson; structural hook `Plan.replan_from()` already in `plan.py`) |

**Practical Exercise:** Agent correctly decomposes "Find papers on X and summarize top 3." (deferred to 3.4 ReAct integration where LLM-driven plan construction lands)

---

## Sub-Phase 3.4: ReAct Pattern + Reflection 🔄 (7/9 builds shipped 2026-05-30; concept lessons deferred per L301)

**Build closure 2026-05-30 (commit pending — see KB L302).** Workflow-orchestrated parallel build of 6 foundation modules + adversarial review across 4 lenses surfaced 4 critical + 15 high findings; all applied. react.py orchestrator built solo with 36 baseline smoke tests; Workflow 2 review surfaced 1 critical + 4 high more (MIRROR-Lite + bare-JSON tool-call interaction breaking parse; ASK→ALLOW promotion in ask_handler path; per-observation budget dropping later results; LLM-controlled tool args leaking verbatim to trace persister). All 5 fixed + regression-guarded.

**Total Stage 3.4 build:** ~3,500 LOC across 7 modules, 203 smoke tests, 18-module agent registry passes regression sweep.

**Goal:** Implement the Reason → Act → Observe loop. Absorb metacognitive review's MIRROR-lite + CoT loop detector here (Decision 2026-05-13).

| Lesson | Topic | JARVIS Use Case | Status |
|--------|-------|-----------------|--------|
| 3.4.1 | ReAct Overview | The core agent loop | ⊘ Deferred (concept lesson, per L301) |
| 3.4.2 | Trace Logging (STEAL #5) | Port OpenJarvis TraceStep + StepType + EventBus pattern | **[OK] COMPLETE** — `trace.py` (442 LOC, 28 smoke tests). EventBus pub/sub with snapshot-during-publish, fault-isolated subscriber callbacks (sync+async), SubscriptionHandle for unsubscribe, MappingProxyType-wrapped payload (immutable post-construction). |
| 3.4.3 | Observation Parsing | Handle tool outputs in the loop | **[OK] COMPLETE** — `observation.py` (329 LOC, 19 smoke tests). format_observation wraps Step/ToolResult into LLM-readable text; hits-shape compact format; defensive coercion for score=None / non-numeric; newline sanitation in hit content. |
| 3.4.4 | Loop Termination | Know when to stop | ⊘ Deferred (concept lesson, per L301; termination logic landed in react.py via max_iterations + final_text branch + abort_on_instability) |
| **3.4.5** | **MIRROR-lite system prompt** | Single-pass structured reflection — Goals/Reasoning/Memory before responding. | **[OK] COMPLETE** — `reflection.py` (331 LOC, 12 smoke tests). MIRROR_LITE_PROMPT_TEMPLATE constant + inject_mirror_lite (idempotent) + extract_mirror_reflection (robust to code fences). Integrated in react.py system prompt injection + per-turn extraction. |
| **3.4.6** | **CoT loop detector** | Regex over `<think>` tag content; frequency > 2 per token-class = unstable. | **[OK] COMPLETE** — `monitor.py` (411 LOC, 34 smoke tests). MetaR1Monitor.from_cot_trace; patterns precompiled at class-load (no per-call regex compile); longer-phrase-first masking prevents double counting (e.g., "wait but" no longer double-counts "wait"); word-boundary protection. |
| **3.4.7** | **Tool concurrency partitioning (STEAL #8)** | Partition tool-calls into safe (asyncio.gather) vs stateful (serial). ~50% latency reduction. | **[OK] COMPLETE** — Implemented in BOTH `executor.py` (Stage 3.3.3 plan-driven path) AND `react.py` lines 332-353 (single-turn LLM tool-call dispatch path). Tool.is_concurrency_safe drives the partition; results re-ordered via id(tc) keyed dict to preserve LLM emission order. |
| **3.4.8** | **Hook-driven permission engine (STEAL #9)** | Declarative allow/ask/deny rules + async classifiers per tool. CRITICAL safety layer. | **[OK] COMPLETE** — `permissions.py` (551 LOC, 30 smoke tests). PermissionRule with regex-validate-at-construction; PermissionContext with first-match-wins rules + async classifier override; 16KB serialized-input cap to defend against ReDoS; json.dumps failure swallow; non-PermissionDecision classifier return validated. **Fail-closed by design**: default=ASK, ask_handler returning non-ALLOW blocks (react.py T17 regression guard). |
| **3.4.9** | **Bash AST safe-command classifier (STEAL #10)** | Parse bash AST; auto-approve safe ops; block CVE patterns. | **[OK] COMPLETE** — `bash_classifier.py` (471 LOC, 29 smoke tests). Walks bashlex AST recursively (pipelines, substitutions, redirects). Auto-DENY for write redirects on safe commands, find -fprint/-fls/-exec, sed/awk dropped from SAFE_COMMANDS (Turing-complete attack surface via system()/getline/e-cmd), CVE regex tightened for whitespace inside subscript. Registered as classifier for `shell_run` via PermissionContext.register_classifier. |
| (orchestrator) | **react.py — ReActLoop** | Wires all above into the Reason→Act→Observe loop. | **[OK] COMPLETE** — `react.py` (883 LOC + fixes; 51 smoke tests). MIRROR-Lite stripped before parse (CRITICAL fix), per-observation budget on join, redact-by-default trace events (`arg_keys` only unless trace_arguments=True), sync/async LLM call dispatch, sync/async ask_handler dispatch with fail-closed semantics, broken-observer/hook swallowed, max_iterations safety cap, full ReActResult with messages + tool_calls + reflections + instability report. |

**Practical Exercise:** ReAct agent answers a multi-hop question with tool use; trace records all reasoning, the loop detector flags any circular pattern, concurrency partitioning batches 3 read-only tool-calls in parallel, and the permission engine auto-approves `grep -n foo bar` while prompting for `rm -rf /tmp/`. *(Deferred to Stage 3.5 integration where heartbeat-driven consolidation will exercise the full loop against real KB queries.)*

---

## Sub-Phase 3.5: Memory-Augmented Agents (MemGPT) ✅ BUILD-COMPLETE (9/11; Wave 1 2026-05-30 + Wave 2 Cognitive Synthesis Loop + Wave 3 evals/compact 2026-06-04; the 2 remaining lessons are concept-only, deferred per L301)

**Wave 1 closure 2026-05-30.** Foundation MemGPT-style three-tier MemoryManager landed + ReActLoop wired for auto-retrieval before each query. Workflow 3 (8 reviewers across 4 lenses) stalled in flight; fell back to solo internal review — found 4 high-severity issues (cross-tier id collision in add(), ASCII-only tokenization in HOT retrieval, missing anti-injection guardrail on auto-retrieved memory, two separate system-role messages violating Anthropic Messages API). All 4 fixed with regression-guard smoke tests.

**Total Wave 1:** ~1,000 LOC across 2 files (memory_manager.py NEW + react.py MOD), 122 smoke tests (51 + 71). 19-module agent regression sweep clean.

**Scope expansion 2026-06-04 (KB L310).** The user tested whether JARVIS could independently notice that their Stage-3 learning engagement dropped *because* their attention shifted to DE/Spark/SQL interview-prep across the partitioned chats. It could not — the failure was **synthesis, not information** (the signals were already in the injected profile). Root cause: three missing loops — (1) no read-path joins cross-chat captures into a live turn, (2) the consolidator is unbuilt **and** was scoped per-turn rather than cross-domain-over-time, (3) no proactive-surfacing path (insights inject as *background*, never *raised*). Per user directive (2026-06-04) this is a **first-class production capability**, not a temporary script: Wave 2 is re-scoped from `{3.5.6, 3.5.7}` to the full **Cognitive Synthesis Loop** `{3.5.6 heartbeat, 3.5.7 consolidator (widened), 3.5.10 correlation engine, 3.5.11 surfacing daemon}`. The design below is the canonical contract; it MUST satisfy the IMPREGNABLE + OBSOLESCENCE-PROOF definition-of-done.

**Wave 2 closure 2026-06-04.** All four modules shipped (~1,750 LOC, 77 smoke tests: correlation 28 + consolidator 16 + heartbeat 16 + life_state_monitor 17) + the `surface_life_state.py` SessionStart hook, registered. A 5-lens adversarial impregnability review (8 agents, each high/critical finding independently verified) raised 12 findings; **no live exploit** — the structural defenses (anti-injection whitelist, local-only privacy invariant, no-tool-access, flock concurrency) held under attack. 3 confirmed-serious + 7 hardening items were ALL applied with regression guards: (#1) `_AFFECTED_MIN_TURNS` kills an N=1 hallucinated link (fail-closed); (#2/#5) instant-based offset-agnostic windowing/day-keys (obsolescence-proof under a future non-IST capture limb); (#3) the surfacing hook was unregistered — loop 3 would never have fired — now wired; (#4) `build_injection` 2nd-order-injection guardrail; (#6) word-less-turn classifier; (#7) bounded domain vocab; (#8) DoD-mandated secret re-scrub; (#9) cost-control dedup-before-synthesis; (#10/#11) index persistence + empty-prose filter. 23-module agent regression sweep clean. **The Cross-Domain Awareness Test now has a live path end-to-end.** Wave 3 (`3.5.8` evals + `3.5.9` /compact) remains.

**Goal:** Agents that self-manage memory — heartbeat consolidation, hot/warm/cold tiers, self-editing.

> **PRE-3.5 DEPENDENCY (BLOCKING):** Patch `scripts/kb_compact.py` to exclude entries tagged `heartbeat-emitted` from structural-rule displacement. ✅ **LANDED** Stage 2.5.8 (kb_compact.py:450 `HEARTBEAT_EXEMPT_TAG = "heartbeat-emitted"`).

| Lesson | Topic | JARVIS Use Case | Status |
|--------|-------|-----------------|--------|
| 3.5.1 | Working Memory | Short-term context for current task | ⊘ Deferred (concept, per L301) |
| 3.5.2 | Long-Term Memory | Persist to Phase 2 vector store | **[OK] COMPLETE** — `react.py` ctor accepts `memory_manager: Optional[MemoryManager]`; downstream Tool wrappers from 3.2 still callable via the existing `tool_instances` dict. |
| 3.5.3 | Memory Retrieval in Loop | RAG inside the agent loop | **[OK] COMPLETE** — `react.py` adds `auto_retrieve_top_k: int` ctor arg + pre-loop `_format_memory_context()` hook that folds top-k hits into the single system message (Anthropic-compatible) with anti-injection guardrail. |
| 3.5.4 | MemGPT Architecture | Hot/warm/cold memory hierarchy | ⊘ Deferred (research lesson, per L301; structural pattern already encoded in `memory_manager.py`) |
| 3.5.5 | Self-Editing Memory | Agent decides what to remember/forget/update | **[OK] COMPLETE** — `memory_manager.py` (858 LOC, 51 smoke tests). `MemoryManager` with HOT (in-memory OrderedDict LRU, Unicode token-overlap retrieval), WARM/COLD (shared Chroma collection differentiated by `metadata.tier`), self-editing API: add/promote/demote/evict/clear_hot; tier-weighted score merge (+0.2 HOT, -0.1 COLD); cross-tier id collision check on add; metadata sanitization for Chroma. |
| **3.5.6** | **Async heartbeat event loop** (metacognitive integration) | `request_heartbeat=true` flag on tool calls triggers async consolidation — event-driven, NOT clock-driven (per metacognitive review Section 2.2 hardware reality check) | **[OK] COMPLETE 2026-06-04** — `heartbeat.py` (16 smoke tests). `HeartbeatScheduler`: event-driven `request()` marks dirty + coalesces a burst, debounced `maybe_fire()` at turn boundary, injected clock (deterministic tests), sync/async callback dispatch with error-swallow, optional `run()` backstop loop. `note_tool_result()` reads the request_heartbeat flag. |
| **3.5.7** | **Sleep-time consolidation agent** (metacognitive integration; **WIDENED for cross-domain synthesis**) | Heartbeat-triggered LLM brain. Drains `observation_queue.jsonl`, calls the 3.5.10 correlation engine, reasons over the behavioral state model + recent KB. Writes deduped per-domain `Cognitive_Pattern` **AND** cross-domain `life_state` synthesis entries via **kb_append ONLY**, all tagged `heartbeat-emitted`. Anti-injection: captured text is untrusted DATA; no tool access beyond whitelisted kb_append. | **[OK] COMPLETE 2026-06-04** — `consolidator.py` (16 smoke tests). kb_append-only with hard-coded `Cognitive_Pattern`/`life-state` whitelist (LLM influences prose only — anti-injection proven: a poisoned observation cannot mint an arbitrary entry type/tag); fail-closed confidence floor; stable insight_id feed dedup BEFORE synthesis (cost-control); persists the 3.5.10 index. |
| 3.5.8 | Agent Evaluation (STEAL #6) | Port OpenJarvis EvalRecord → EvalResult → RunSummary framework | **[OK] COMPLETE 2026-06-04** — `evals.py` (23 smoke tests). EvalRecord → EvalResult → RunSummary; pluggable Scorer Protocol (ExactMatch / Substring / LLMJudge fail-closed); MetricStats **p50/p95/p99** (tail, not just mean); async bounded-concurrency EvalRunner with per-record exception isolation. (Single-file consolidation of OpenJarvis's 3 files per YAGNI.) |
| **3.5.9** | **/compact-style working-memory compressor (STEAL #12)** | Async coroutine that, when context > N tokens, calls LLM with structured summarization prompt over the truncation window; emits `SystemCompactBoundaryMessage` dataclass replacing truncated history. TWIN PROCESS with heartbeat-emitted consolidation: /compact writes to short-term working memory, heartbeat writes long-term insights to KB. | **[OK] COMPLETE 2026-06-04** — `compact.py` (17 smoke tests). `WorkingMemoryCompactor` → `SystemCompactBoundaryMessage`; leading-system + last-keep_recent preserved verbatim, stale middle distilled into one boundary; **fail-safe** (summarizer error/empty → originals returned untouched); transcript framed as untrusted DATA; injected `llm_call` (brain-swap-proof). |
| **3.5.10** | **Cross-Domain Behavioral Correlation Engine** (NEW — closes loop 1+2 of KB L310) | The missing inference substrate. Deterministic feature layer (no LLM, pure generators) turns `observation_queue.jsonl` into a per-domain time-series (volume, cadence, engagement-mode interrogative-vs-dispatch, gaps); epistemic-gated LLM layer proposes cross-domain causal links with confidence + evidence + a **correlation-vs-causation flag**. Emits `behavioral_state_model.jsonl` (regenerable index, gitignored). | **[OK] COMPLETE 2026-06-04** — `correlation.py` (28 smoke tests). Instant-based (offset-agnostic) windowing; `_AFFECTED_MIN_TURNS` guard so an N=1 ratio can't fabricate a max-confidence link (fail-closed); deterministic confidence capped 0.70, never relabels causation; bounded domain vocab + secret re-scrub on derived strings (DoD #2); optional LLM gate via injected `llm_call`. **+ 2026-06-10 (L314/L315):** embedding **nearest-prototype** domain reclassification (`domain_classifier.py`, 18 tests) re-derives each turn's domain from text at synthesis time (off the hook's hot path) — fixed the coarse-keyword `general`-bucket signal-starvation; exposed the hook's `finance` tags as DE mis-tags and consolidated DE 31→40 on the real queue. |
| **3.5.11** | **Proactive Life-State Surfacing Daemon** (NEW — closes loop 3 of KB L310; generalizes `failure_pattern_alarm`) | The RAISE-don't-just-HOLD channel. On session-start, drains the consolidator's `life_state_feed.jsonl` for insights newer than the surfaced-watermark with confidence ≥ floor; if found, emits a distinct **SURFACE-THIS** injection (separate from the background profile injection) instructing JARVIS to volunteer the connection THIS session. Watermark-dedup + rate-limit (never nag). | **[OK] COMPLETE 2026-06-04** — `life_state_monitor.py` (17 smoke tests) + `scripts/hooks/surface_life_state.py` (registered as a 2nd SessionStart hook). Fail-closed (no qualifying insight → emit nothing); one-surface-per-insight watermark (flock); the injection carries the do-not-follow guardrail + quotes the synthesized prose as untrusted data (2nd-order-injection defense); empty-prose insights never selected. |

**Practical Exercise:** Agent self-manages memory: heartbeat triggers consolidation between user turns, promotes important facts, evicts stale entries, remembers user preferences — all without manual `/memory` commands. `kb_compact.py` runs without displacing legitimate transient state observations. `/compact`-style working-memory compressor kicks in when context exceeds threshold, replacing old turns with a single summary boundary message.

> **Key Paper:** `2310.08560v2.pdf` (MemGPT) — already in your Research Papers folder. The agent treats memory like an OS virtual memory system: Hot = current context, Warm = pinned in ChromaDB, Cold = archived on disk.

---

### Wave 2 Production Design: The Cognitive Synthesis Loop

> **Canonical contract for `{3.5.6, 3.5.7, 3.5.10, 3.5.11}`.** Authored 2026-06-04 per user directive: *"a proper production solution… impregnable and obsolescence-proof,"* not a temporary script. Closes the three loops named in KB L310.

**The capability (Definition of the feature):** Across the 7 partitioned chats and over time, JARVIS detects that activity in one domain explains a behavior change in another — and **volunteers** it. The target line: *"You've been ~2 weeks heavy on Spark/SQL interview prep; your JARVIS-build engagement shifted from interrogative to execution-mode — consistent with deliberate learning-deferral, not disengagement."* Said unprompted, at session start, in any chat.

**Architecture — four components on the MemGPT heartbeat backbone:**

```
observation_queue.jsonl                         [DONE — Stop-hook, per-turn, redacted, domain-tagged]
  │  raw signal · LOCAL-ONLY · never leaves the laptop
  ▼
[3.5.10] CrossDomainCorrelationEngine           jarvis_core/agent/correlation.py
  │  DETERMINISTIC layer (pure generators, CPU, ₹0): per-domain time-series —
  │    volume, cadence, engagement-mode (interrogative vs dispatch), gap detection
  │  INFERENCE layer (epistemic-gated, via injected llm_call): candidate cross-domain
  │    links {domain_a, domain_b, direction, window, confidence, evidence, causation_flag}
  │  emits  behavioral_state_model.jsonl         [regenerable index · gitignored · --backfill]
  ▼
[3.5.7]  Consolidator (widened)                 jarvis_core/agent/consolidator.py
  │  heartbeat-triggered LLM brain · drains queue · reasons over the state model + KB
  │  writes per-domain Cognitive_Pattern + cross-domain life_state entries
  │  via scripts/kb_append.py ONLY · tagged heartbeat-emitted
  ▼
[profile_synth] → cognitive_profile.md          [BACKGROUND injection — "don't act on this"]
  │
[3.5.11] LifeStateMonitor                        jarvis_core/agent/life_state_monitor.py
  │  RAISE-don't-HOLD channel · generalizes failure_pattern_alarm
  │  session-start: unsurfaced life_state entry, confidence ≥ floor → emit SURFACE-THIS injection
  ▼
SessionStart hook → JARVIS volunteers the connection in chat       [the Iron-Man line]

[3.5.6] Heartbeat scheduler                      jarvis_core/agent/heartbeat.py
         event-driven (request_heartbeat flag), NOT clock-driven — drives the consolidator

[RECALL limb, 2026-06-10, L316]  recall.py + scripts/hooks/inject_recent_activity.py
         reads observation_queue.jsonl (NEVER git) → day-by-day cross-chat activity digest
         → 3rd SessionStart hook → every chat opens knowing what you did across all chats.
         Fixes the gap where a fresh chat fell back to `git log` and missed no-commit days.
```

**IMPREGNABLE — security/privacy definition-of-done (non-negotiable):**
1. **Local-only.** `observation_queue.jsonl` + `behavioral_state_model.jsonl` never leave the laptop. Only distilled insights reach the KB (also local). Honors the ENDGAME privacy invariant.
2. **Redact-at-capture + re-validate.** Secrets redacted at the Stop-hook; the correlation engine re-scans derived features — no secret ever reaches an LLM call or the index.
3. **Injection-resistant.** Captured user text is *data*, never instructions. Consolidator + correlation LLM prompts wrap all user content in an anti-injection guardrail (same class as react.py M11). The consolidator has **no tool access** beyond `kb_append` constrained to a type+tag whitelist — a poisoned observation cannot execute tools, write arbitrary entry types, or exfiltrate.
4. **Fail-closed.** Below the confidence floor → surface **nothing**. No hallucinated "I sense you're stressed." Epistemic control (Strategic Principle #4): correlation ≠ causation is always flagged.
5. **Single write path.** All KB writes via `kb_append` (flock + content/semantic dedup + collision-proof id + source_machine stamp). Already enforced; the consolidator MUST NOT hand-roll an append.
6. **Rate-limited surfacing.** Watermark-dedup; one surface per insight; never nag. Trust erosion is the failure mode.

**OBSOLESCENCE-PROOF — future-proof definition-of-done (non-negotiable):**
1. **Brain-swap-proof.** Every LLM call goes through the injected `llm_call` DI boundary (already in react.py). Cloud API today → Kimi K2.6 local (RTX Spark / RunPod) tomorrow → zero rewrite. The deterministic feature layer is model-independent.
2. **Cross-runtime.** `behavioral_state_model.jsonl` is regenerable (`--backfill`); synthesized `life_state` KB entries sync via git and are **readable by the personal-laptop Antigravity** (which can't run hooks). Shared data contract; an Antigravity-native capture limb is additive later, not a rewrite.
3. **Schema-evolution-proof.** Observations + index are **timestamp-keyed, not line-numbered** → compaction-stable; KB uses the stable 8-type schema; `heartbeat-emitted` exemption protects entries from `kb_compact`.
4. **Scale-proof.** Generator-based sliding-window over the queue (never `list()` the full history); the queue is rotatable/archivable to cold storage without losing derived KB insights.
5. **Hardware-independent.** Deterministic layer is CPU-only (₹0); the inference layer is the only cloud/GPU touch and is cold-wake/heartbeat-gated.

**DEFINITION OF DONE — the Cross-Domain Awareness Test** (mirrors the Phase 4.0 Cognitive Control Loop's 4-awareness-tests): at session start in **any** chat, JARVIS answers UNPROMPTED, with a confidence score and a correlation-vs-causation flag: *"What has the user been doing across all domains lately, and how is it affecting this domain?"* — correctly surfacing the Spark-prep ↔ JARVIS-engagement link from the example above, **and** failing closed (saying nothing) when uncertain. When both hold, the Cognitive Synthesis Loop is production-complete.

---

## Final Boss: The Mind ✅ PASSED 2026-06-04

Assembled in `jarvis_core/agent/mind.py` (`Mind` class — pure composition over the
tested parts). Its `__main__` is the capstone integration test (12 checks, 7/7
criteria, driven by a scripted LLM against the REAL modules):
1. [x] Decomposes "Research topic X and write a summary" into steps — `_decompose` → `build_plan` (3 steps)
2. [x] Uses tools: web search, memory retrieval, code execution — ReActLoop dispatch (all 3 fired)
3. [x] Follows ReAct loop with trace logging + MIRROR-lite reflection — `ReActLoop` (≥4 iterations)
4. [x] Detects reasoning loops via CoT regex — `MetaR1Monitor` flagged `is_unstable` on a looping trace (real detection, not just "ran")
5. [x] Persists new learnings via heartbeat-driven sleep-time consolidation — heartbeat-gated `consolidator.consolidate` (`kb_writes ≥ 1`)
6. [x] Handles failures and replans — caught a thrown loop failure → re-decomposed → recovered
7. [x] Survives kb_compact.py without losing heartbeat state — consolidation writes carry `heartbeat=True` → `heartbeat-emitted` tag → kb_compact.py:450 exempts them

**JARVIS can think.** Stage 3 build-complete.

---

## Progress Tracker

| Sub-Phase | Status | Lessons Complete |
|-----------|--------|------------------|
| 3.0 Entry Sprint (Registry + Cost-with-STEAL-#11 + Tool ABC-with-#8-prep) | [OK] Complete | 3/3 |
| 3.1 Function Calling + Cognitive_State_Update + TextTelemetry | [OK] Complete | 7/7 |
| 3.2 Tool Design & Registration (Phases A/B/C shipped — 18 callable tools; 3.2.3 lifecycle hooks shipped) | 🔄 In Progress | 3/4 |
| 3.3 Planning & Decomposition (3.3.2 plan.py + 3.3.3 executor.py shipped; concept lessons deferred) | 🔄 In Progress | 2/4 |
| 3.4 ReAct + MIRROR-lite + CoT detector + STEAL #5/#8/#9/#10 (trace, observation, monitor, reflection, permissions, bash_classifier, react.py) | 🔄 In Progress | 7/9 |
| 3.5 Memory-Augmented Agents + Heartbeat + /compact + **Cognitive Synthesis Loop** (Wave 1 + Wave 2 + Wave 3 evals/compact; concept lessons deferred per L301) | ✅ Build-Complete | 9/11 |
| **Final Boss: The Mind** (mind.py — full integration, 7/7 criteria) | ✅ PASSED | 7/7 |
| **STAGE 3 — Agent Framework** | ✅ **BUILD-COMPLETE 2026-06-04** | all build lessons shipped |

---

## What Got Reversed

The earlier "Stage 3 = single deliverable `mcp_bridge.py` exposing Memory primitives as MCP tools for OpenClaude" plan (Decision 2026-05-01, [STAGE_3_OPENCLAUDE_STRATEGY.md](../../STAGE_3_OPENCLAUDE_STRATEGY.md)) is SUPERSEDED per Decision 2026-05-13. The MCP bridge survives only as **optional Stage 5+ work** — *publishing* JARVIS Memory to external tools (Claude Desktop, Antigravity, third-party agents), not as the agent runtime.

---

## After This Phase

→ Proceed to **Phase 4: Multi-Model Orchestration** → [PHASE_04_ROADMAP.md](../orchestration-learning/PHASE_04_ROADMAP.md)
