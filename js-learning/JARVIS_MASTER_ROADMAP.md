# 🚀 JARVIS MASTER ROADMAP

**Mission:** Build a private, locally hosted Multi-Model Cognitive Orchestrator.

**Timeline:** 9-15 months to operational JARVIS

---

## 📍 Current Position

**Stage 3 -- Agent Framework: `jarvis_core/agent/` from scratch** in progress. Stage 2 (Memory Layer) closed 2026-05-03. **Sub-Phase 3.0 Entry Sprint COMPLETE** (2026-05-16): RegistryBase[T] + CostTracker + Tool ABC. **Sub-Phase 3.1 Function Calling & Structured Output COMPLETE** (2026-05-18, all 7 lessons verified by /next audit; parser.py + errors.py + state.py + telemetry.py + exercise_3_1.py shipped). **NOW: Sub-Phase 3.2 Tool Design & Registration** — build 10+ composable tools wrapping `jarvis_core/memory/` primitives + calculator + web search + code exec + file I/O + shell on the 3.0 registry.

---

## The 6 Stages

### Stage 1: Systems Python — The Foundry ✅ COMPLETE
- **Duration:** 2-3 months
- **Output:** Async, memory-safe pipelines (Phases 1-3 done, 4-5 deferred)
- **Roadmap:** [stage_1_python/ROADMAP.md](stage_1_python/ROADMAP.md)

### Stage 2: Memory Layer — The Soul ✅ COMPLETE
- **Duration:** ~9 weeks (Mar–May 2026; 1.13× expected, depth-first justified)
- **Output:** Production RAG + ChromaDB + hybrid (semantic+BM25) + cross-encoder rerank + KB compactor
- **Roadmap:** [stage_2_memory/ROADMAP.md](stage_2_memory/ROADMAP.md)

### Stage 3: Agent Framework — The Mind ⬅️ CURRENT
- **Duration:** 10–14 weeks (2.5–3.5 months; net +8–12 weeks vs. the OpenClaude shortcut, compressed via OpenJarvis STEAL targets)
- **Output:** `jarvis_core/agent/` — Tool ABC + Registry + Cost accounting + ReAct loop + Planner + MemGPT-style memory paging — JARVIS owns the runtime
- **Roadmap:** [stage_3_agents/ROADMAP.md](stage_3_agents/ROADMAP.md) — see also [STAGE_3_OPENCLAUDE_STRATEGY.md](../STAGE_3_OPENCLAUDE_STRATEGY.md) (SUPERSEDED 2026-05-13, kept for historical context)

### Stage 4: Multi-Model Orchestration — The Brain
- **Duration:** 2-3 months
- **Output:** Router + Aggregator + GraphRAG (replaces flat vector search)
- **Roadmap:** [stage_4_orchestration/ROADMAP.md](stage_4_orchestration/ROADMAP.md)

### Stage 5: Domain Specialists — The Experts
- **Duration:** 2-3 months
- **Output:** Fine-tuned code/science/medical models
- **Roadmap:** [stage_5_specialists/ROADMAP.md](stage_5_specialists/ROADMAP.md)

### Stage 6: Integration & Interface — The Voice
- **Duration:** 1-2 months
- **Output:** Voice + Vision + Context Caching (cloud) + JARVIS MVP
- **Roadmap:** [stage_6_integration/ROADMAP.md](stage_6_integration/ROADMAP.md)

---

## Stage 1: Systems Python — The Foundry

**Goal:** Master Python primitives that become JARVIS's nervous system.

| # | Sub-Phase | Status |
|---|-----------|--------|
| 1.1 | Object Model & Memory | ✅ Complete |
| 1.2 | Data Pipelines (Generators) | ✅ Complete |
| 1.3 | Async Foundations | ✅ Complete |
| 1.4 | Concurrent Patterns | ⏭ Deferred (pre-Stage 3) |
| 1.5 | Type Safety | ⏭ Deferred (on demand) |

---

## Stage 2: Memory Layer — The Soul

**Goal:** Build long-term memory: RAG, vector stores, retrieval.

| # | Sub-Phase | Status |
|---|-----------|--------|
| 2.1 | Embeddings & Similarity | ✅ Complete |
| 2.2 | Vector Databases (ChromaDB) | ✅ Complete |
| 2.3 | Document Ingestion | ✅ Complete |
| 2.4 | Retrieval Strategies | ✅ Complete |
| 2.5 | Hybrid Search & Reranking | ✅ Complete |

---

## Stage 3: Agent Framework — The Mind (BUILD FROM SCRATCH per Decision 2026-05-13)

**Goal:** Build `jarvis_core/agent/` from scratch. JARVIS owns its agent runtime — no external dependency on Anthropic-hosted runtimes. Reverses 2026-05-01 OpenClaude delegation (Decisions 177 + 222): privacy, fixed-training-cost economic model, customization for 12-specialist routing, and the canonical learning arc all argue against outsourcing. Compressed via OpenJarvis STEAL targets (Apache 2.0 source-copy) for foundations.

| # | Sub-Phase | Status | Note |
|---|-----------|--------|------|
| 3.0 | **Entry Sprint** -- `agent/registry.py` (STEAL #1 RegistryBase) + `agent/cost.py` (STEAL #2 PRICING dict + STEAL #11 cache tiers) + `agent/tool.py` (Tool ABC) | [OK] Complete (2026-05-16) | Foundations landed. 3/3 lessons. |
| 3.1 | Function Calling & Structured Output (+ `Cognitive_State_Update` Pydantic schema, `TextTelemetry` dataclass) | ✅ Complete (2026-05-18) | parser.py + errors.py + state.py + telemetry.py |
| 3.2 | Tool Design & Registration | ✅ Complete | 18 tools registered incl. Phase C cognitive substrate |
| 3.3 | Planning & Decomposition | ✅ Complete | plan.py + executor.py (DAG, Kahn) |
| 3.4 | ReAct Pattern (+ MIRROR-lite system prompt, CoT loop detector regex) | ✅ Complete | react.py + trace.py + monitor.py + reflection.py |
| 3.5 | Memory-Augmented Agents/MemGPT (+ heartbeat loop, sleep-time consolidation) | ✅ Complete (2026-06-10) | Waves 1-3 + Cognitive Synthesis Loop; **Stage 3 Final Boss 7/7 (mind.py), First Light 2026-06-11 (llm_client.py)** |

---

## Stage 4: Multi-Model Orchestration — The Brain (split into 4.A and 4.B per Decision 2026-05-01; re-scoped via /master-planner per Decision 2026-06-12)

**Goal:** Build the routing substrate — ContextInjector → Router → RouteTarget → ConfidenceGate → (Aggregator) — so a Stage 5 specialist is just another registry row. **₹0 stage** (Decision 2026-06-12): everything on OpenRouter free tier + local CPU embeddings. Detail: [stage_4_orchestration/ROADMAP.md](stage_4_orchestration/ROADMAP.md).

### Stage 4.A — Orchestration (Pass A)
| # | Sub-Phase | Status |
|---|-----------|--------|
| 4.0 | Cognitive Control Loop (boot inhale, autobiography wiring, RoadmapStateReader, Confidence Gate v1, capture parity — closes L324; blocks all other sub-phases per L107) | ✅ Complete (2026-06-12, Gate A 5/5 live) |
| 4.1 | Route Targets & Per-Model Protocol (L322: ModelProfile registry + ProtocolAdapter middleware + RouteTarget contract + **STEAL #7** OpenClaude SmartRouter failover). Kimi K2.6 RunPod deployment DEFERRED to Stage 5 entry per Decision 2026-06-12 — `RunPodTarget` ships as offline contract stub; frontier APIs = explicit-flag escape valve, structurally outside the router pool | ⬜ |
| 4.2 | Intent Router (interim nearest-prototype classifier on specialist-codename labels; ModernBERT-Large CPU classifier = conditional on gate failure, else Stage 5 specialist #1 trained on the RoutingLedger) | ⬜ |

**Pass A → Pass B Gate:** Router achieves ≥80% routing accuracy on a 50-query labeled test set (`js-development/tests/router_eval.jsonl`, frozen). Failure modes (always-default, always-largest) score ~20%. Cannot advance to 4.3 without a documented Router quality measurement.

### Stage 4.B — Specialists (Pass B)
| # | Sub-Phase | Status |
|---|-----------|--------|
| 4.3 | Dynamic Target Management (rolling stats, budget governor, catalog drift) | ⬜ |
| 4.4 | Response Aggregation (escalation-only fan-out, attributed synthesis) | ⬜ |
| 4.5 | Epistemic Control (conflict detection, fail-closed judge, human escalation) | ⬜ |
| 4.6 | GraphRAG | ⏭ DEFERRED — trigger: first KB-logged multi-hop retrieval failure → `jarvis_core/memory/graph.py` |

---

## Stage 5: Domain Specialists — The Experts (Engineer-first MVP per Decision 2026-05-01; recipe revised 2026-05-03 to QLoRA-on-Kimi-K2.6)

**Goal:** Ship ONE specialist end-to-end before scaling to 12. First (and currently only locked-in) specialist: **The Engineer**, sub-domains = `code_systems` + `data_engineering` (frontend / backend deferred until stack is locked-in). Training corpus: jarvis_core/ (code), Data_Engineering_Lessons.md (DE).

**Recipe (Decision 2026-05-03):** All specialists ship as **QLoRA adapters on the shared Kimi K2.6 base** (1T/32B-active MoE), NOT separate dense fine-tunes. ~80% lower training cost; one base + adapter swap instead of 12 dense loads. Adapter seed = distillation from public domain specialist (e.g., Qwen3-Coder-Next for Engineer, MedGemma 1.5 for Doctor). Personalization corpus = user's private data (jarvis_core/, KB, chat history, error logs).

| # | Sub-Phase | Status | Note |
|---|-----------|--------|------|
| 5.1 | Fine-Tuning Basics (QLoRA on RunPod, Kimi K2.6 base) | ⬜ | RunPod prepaid only; no local GPU |
| 5.2 | The Engineer QLoRA Adapter (Code+Systems + DE on user's private corpus) | ⬜ | MVP — sub-domain isolation discipline applied; adapter seed = Qwen3-Coder-Next 80B/3B-active distilled |
| 5.3 | Engineer Evaluation (RAGAS + recall@k on engineer-domain test set) | ⬜ | Gate: match Kimi K2.6 base on public benchmarks AND outperform on user's private-corpus tasks (code style, KB recall, error-pattern recognition). NOT "beat GPT-5.5" — that's the wrong frame per Decision 2026-05-03. |
| 5.4 | Specialist Templating (only after Engineer ships) | ⬜ | Replicate adapter recipe to Doctor / Scientist / Analyst only after Engineer MVP validated |
| 5.5 | Roster Expansion (Idea [42] full 12-specialist plan) | ⬜ | Spec preserved; build only on demand. Always 1 base + N adapters, never N dense. |

---

## Stage 6: Integration & Interface — The Voice

**Goal:** Unify all components into complete JARVIS.

| # | Sub-Phase | Status |
|---|-----------|--------|
| 6.1 | Voice Input (Whisper) | ⬜ |
| 6.2 | Vision Input (LLaVA) | ⬜ |
| 6.3 | Unified API Layer | ⬜ |
| 6.4 | Conversation Memory | ⬜ |
| 6.5 | Context Caching (optional cloud-assisted code) | ⬜ |
| 6.6 | JARVIS MVP | ⬜ |

---

## Progress Overview

| Stage | Name | Status |
|-------|------|--------|
| 1 | Systems Python | ✅ Sufficient |
| 2 | Memory Layer | ✅ Complete (8/8 sub-phases; Final Boss executed 2026-05-03) |
| 3 | Agent Framework (`jarvis_core/agent/` from scratch — Decision 2026-05-13) | 🔄 Starting |
| 4 | Orchestration (Kimi K2.6 brain + 12 QLoRA adapters) | ⬜ 0% |
| 5 | Specialists (Engineer-first MVP) | ⬜ 0% |
| 6 | Integration | ⬜ 0% |

---

## Next Action

**Start:** Stage 3.1 -- Function Calling & Structured Output.
**First Lesson:** 3.1.1 -- Function Calling Basics (`@[/learn] Explain function calling in LLMs.`)
**Files:** `js-development/jarvis_core/agent/` (3.0 foundations already landed).
**References:** [stage_3_agents/ROADMAP.md](stage_3_agents/ROADMAP.md)
