# 🚀 JARVIS MASTER ROADMAP

**Mission:** Build a private, locally hosted Multi-Model Cognitive Orchestrator.

**Timeline:** 9-15 months to operational JARVIS

---

## 📍 Current Position

**Stage 3 — Agent Framework: build `jarvis_core/agent/` from scratch** ⬅️ next entry. Stage 2 (Memory Layer) closed 2026-05-03 — all 8 sub-phases shipped, Final Boss kb_compact.py --force executed (KB 222 → 219). **Per Decision 2026-05-13 (reverses 2026-05-01 OpenClaude delegation):** JARVIS owns its agent runtime. Build the original 5 sub-phases (3.1 Function Calling, 3.2 Tool Registry, 3.3 Planning, 3.4 ReAct, 3.5 MemGPT) preceded by a 3.0 Entry Sprint (Registry + Cost + Tool ABC from OpenJarvis STEAL targets, Apache 2.0). Metacognitive review's NOW-phase items (Cognitive_State_Update schema, TextTelemetry, MIRROR-lite prompt, CoT loop detector, heartbeat loop, sleep-time consolidation) absorb into 3.1/3.4/3.5.

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
| 3.0 | **Entry Sprint** — `agent/registry.py` (STEAL #1 RegistryBase) + `agent/cost.py` (STEAL #2 PRICING dict) + `agent/tool.py` (Tool ABC) | 🔄 Starting | Foundations land *before* lesson 3.1. ~2-3 days. |
| 3.1 | Function Calling & Structured Output (+ `Cognitive_State_Update` Pydantic schema, `TextTelemetry` dataclass) | ⬜ | outlines + Pydantic schemas; metacognitive schemas absorbed here |
| 3.2 | Tool Design & Registration | ⬜ | Builds on 3.0 registry; adds Tool composition + lifecycle |
| 3.3 | Planning & Decomposition | ⬜ | Plan dataclass, PlanExecutor, replanning |
| 3.4 | ReAct Pattern (+ MIRROR-lite system prompt, CoT loop detector regex) | ⬜ | Includes STEAL #5 TraceStep+EventBus trace path; metacognitive reflection absorbed here |
| 3.5 | Memory-Augmented Agents/MemGPT (+ heartbeat loop, sleep-time consolidation) | ⬜ | Requires `kb_compact.py` exclusion rule for `heartbeat-emitted` tag landed *first* |

---

## Stage 4: Multi-Model Orchestration — The Brain (split into 4.A and 4.B per Decision 2026-05-01)

**Goal:** Build Router → Specialist → Aggregator pattern. Two passes with a deliberate quality gate between them.

### Stage 4.A — Orchestration (Pass A)
| # | Sub-Phase | Status |
|---|-----------|--------|
| 4.1 | Brain Base Model: Kimi K2.6 on RunPod (1T/32B-active MoE, MIT, INT4 native) — frontier APIs as escape valve only | ⬜ |
| 4.2 | Intent Classification & Routing (ModernBERT-Large CPU classifier, NOT small-LLM router) + **STEAL #7** OpenClaude SmartRouter (`python/smart_router.py` — already Python; 3 strategies latency/cost/balanced) | ⬜ |

**Pass A → Pass B Gate:** Router achieves ≥80% routing accuracy on a 50-query labeled test set (`tests/router_eval.jsonl`). Failure modes (always-default, always-largest) score ~20%. Cannot advance to 4.3 without a documented Router quality measurement.

### Stage 4.B — Specialists (Pass B)
| # | Sub-Phase | Status |
|---|-----------|--------|
| 4.3 | Dynamic Model Management | ⬜ |
| 4.4 | Response Aggregation | ⬜ |
| 4.5 | Epistemic Control | ⬜ |
| 4.6 | GraphRAG (upgrade flat vectors to knowledge graph) | ⬜ |

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

**Start:** Stage 3.0 Entry Sprint — port OpenJarvis STEAL targets to `jarvis_core/agent/` (RegistryBase + PRICING + Tool ABC).
**Files:** `js-development/jarvis_core/agent/registry.py`, `cost.py`, `tool.py` (new).
**References:** [stage_3_agents/ROADMAP.md](stage_3_agents/ROADMAP.md), OpenJarvis source at `OpenJarvis/src/openjarvis/core/registry.py:19-172` (STEAL #1) and `engine/cloud.py:22-48,165-176` (STEAL #2). License: Apache 2.0, source-copy permitted.
**Pre-3.5 dependency:** `scripts/kb_compact.py` patched to exclude entries with tag `heartbeat-emitted` from structural-rule displacement (sleep-time consolidation requirement).
**Command:** `@[/dev] Build jarvis_core/agent/registry.py porting OpenJarvis RegistryBase[T] pattern. Build jarvis_core/agent/cost.py porting the PRICING dict + RunPod GPU-hour rates from JARVIS_ENDGAME Section 2. Build jarvis_core/agent/tool.py defining the Tool ABC.`
