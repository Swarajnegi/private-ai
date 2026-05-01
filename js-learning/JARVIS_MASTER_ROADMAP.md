# 🚀 JARVIS MASTER ROADMAP

**Mission:** Build a private, locally hosted Multi-Model Cognitive Orchestrator.

**Timeline:** 9-15 months to operational JARVIS

---

## 📍 Current Position

**Stage 2, Sub-phase 2.5: Hybrid Search, Reranking & Evaluation** — In Progress (2.5.1 ✅; 2.5.2–2.5.7 pending)

---

## The 6 Stages

### Stage 1: Systems Python — The Foundry ✅ COMPLETE
- **Duration:** 2-3 months
- **Output:** Async, memory-safe pipelines (Phases 1-3 done, 4-5 deferred)
- **Roadmap:** [stage_1_python/ROADMAP.md](stage_1_python/ROADMAP.md)

### Stage 2: Memory Layer — The Soul ⬅️ CURRENT
- **Duration:** 1-2 months
- **Output:** RAG + ChromaDB retrieval
- **Roadmap:** [stage_2_memory/ROADMAP.md](stage_2_memory/ROADMAP.md)

### Stage 3: Agent Framework — The Mind
- **Duration:** 1-2 months
- **Output:** Tool-calling, planning agents
- **Roadmap:** [stage_3_agents/ROADMAP.md](stage_3_agents/ROADMAP.md)

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
| 2.5 | Hybrid Search & Reranking | 🔄 In Progress |

---

## Stage 3: Agent Framework — The Mind (DELEGATED to OpenClaude)

**Goal:** Expose the JARVIS Memory layer as MCP tools that OpenClaude can invoke. The 5 traditional sub-phases below are **internal design notes**, not code-to-write — OpenClaude already ships function-calling, planning, ReAct, and memory-augmented agent patterns. Per Decision 2026-05-01 (split-brain resolved): Stage 3 single deliverable is `jarvis_core/agent/mcp_bridge.py`. See [STAGE_3_OPENCLAUDE_STRATEGY.md](../STAGE_3_OPENCLAUDE_STRATEGY.md).

| # | Sub-Phase | Status | Note |
|---|-----------|--------|------|
| 3.0 | **MCP Bridge** (the actual deliverable) | ⬜ | Wraps store / expansion / compression / bm25 / hybrid as MCP tools |
| 3.1 | Function Calling | (design note) | OpenClaude provides |
| 3.2 | Tool Design & Registration | (design note) | OpenClaude provides |
| 3.3 | Planning & Decomposition | (design note) | OpenClaude provides |
| 3.4 | ReAct Pattern | (design note) | OpenClaude provides |
| 3.5 | Memory-Augmented Agents | (design note) | OpenClaude + our MCP bridge |

---

## Stage 4: Multi-Model Orchestration — The Brain (split into 4.A and 4.B per Decision 2026-05-01)

**Goal:** Build Router → Specialist → Aggregator pattern. Two passes with a deliberate quality gate between them.

### Stage 4.A — Orchestration (Pass A)
| # | Sub-Phase | Status |
|---|-----------|--------|
| 4.1 | Local Model Loading (RunPod prepaid; no local GPU) | ⬜ |
| 4.2 | Intent Classification & Routing | ⬜ |

**Pass A → Pass B Gate:** Router achieves ≥80% routing accuracy on a 50-query labeled test set (`tests/router_eval.jsonl`). Failure modes (always-default, always-largest) score ~20%. Cannot advance to 4.3 without a documented Router quality measurement.

### Stage 4.B — Specialists (Pass B)
| # | Sub-Phase | Status |
|---|-----------|--------|
| 4.3 | Dynamic Model Management | ⬜ |
| 4.4 | Response Aggregation | ⬜ |
| 4.5 | Epistemic Control | ⬜ |
| 4.6 | GraphRAG (upgrade flat vectors to knowledge graph) | ⬜ |

---

## Stage 5: Domain Specialists — The Experts (Engineer-first MVP per Decision 2026-05-01)

**Goal:** Ship ONE specialist end-to-end before scaling to 12. First (and currently only locked-in) specialist: **The Engineer**, sub-domains = `code_systems` + `data_engineering` (frontend / backend deferred until stack is locked-in). Training corpus: jarvis_core/ (code), Data_Engineering_Lessons.md (DE).

| # | Sub-Phase | Status | Note |
|---|-----------|--------|------|
| 5.1 | Fine-Tuning Basics (LoRA on RunPod) | ⬜ | RunPod prepaid only; no local GPU |
| 5.2 | The Engineer Specialist (Code+Systems + DE) | ⬜ | MVP — sub-domain isolation discipline applied |
| 5.3 | Engineer Evaluation (RAGAS + recall@k on engineer-domain test set) | ⬜ | Gate: must outperform GPT-4 baseline on user's DE corpus |
| 5.4 | Specialist Templating (only after Engineer ships) | ⬜ | Replicate to Scientist / Doctor / etc. only after MVP validated |
| 5.5 | Roster Expansion (Idea [42] full 12-specialist plan) | ⬜ | Spec preserved; build only on demand |

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
| 2 | Memory Layer | 🔄 Starting |
| 3 | Agent Framework | ⬜ 0% |
| 4 | Orchestration | ⬜ 0% |
| 5 | Specialists | ⬜ 0% |
| 6 | Integration | ⬜ 0% |

---

## Next Action

**Start:** Stage 2, Sub-phase 2.5, Lesson 2 (Hybrid Search)  
**File:** [stage_2_memory/ROADMAP.md](stage_2_memory/ROADMAP.md)  
**Command:** `/dev Implement hybrid search for JARVIS memory.`
