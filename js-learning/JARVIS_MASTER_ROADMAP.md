# 🚀 JARVIS MASTER ROADMAP

**Mission:** Build a private, locally hosted Multi-Model Cognitive Orchestrator.

**Timeline:** 9-15 months to operational JARVIS

---

## 📍 Current Position

**Stage 3 — Agent Framework: OpenClaude MCP bridge** ⬅️ next entry. Stage 2 (Memory Layer) closed 2026-05-03 — all 8 sub-phases shipped, Final Boss kb_compact.py --force executed (KB 222 → 219). Single Stage 3 deliverable per Decision 2026-05-01: `jarvis_core/agent/mcp_bridge.py` exposing store / expansion / compression / bm25 / hybrid as MCP tools.

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
- **Duration:** 1-2 months
- **Output:** OpenClaude MCP bridge (`jarvis_core/agent/mcp_bridge.py`) — exposes Memory primitives as tools; OpenClaude handles ReAct/planning/tool-calling
- **Roadmap:** [stage_3_agents/ROADMAP.md](stage_3_agents/ROADMAP.md) + [STAGE_3_OPENCLAUDE_STRATEGY.md](../STAGE_3_OPENCLAUDE_STRATEGY.md)

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

## Stage 3: Agent Framework — The Mind (DELEGATED to OpenClaude)

**Goal:** Expose the JARVIS Memory layer as MCP tools that OpenClaude can invoke. The 5 traditional sub-phases below are **internal design notes**, not code-to-write — OpenClaude already ships function-calling, planning, ReAct, and memory-augmented agent patterns. Per Decision 2026-05-01 (split-brain resolved): Stage 3 single deliverable is `jarvis_core/agent/mcp_bridge.py`. See [STAGE_3_OPENCLAUDE_STRATEGY.md](../STAGE_3_OPENCLAUDE_STRATEGY.md).

| # | Sub-Phase | Status | Note |
|---|-----------|--------|------|
| 3.0 | **MCP Bridge** (the actual deliverable) | 🔄 Starting | Wraps store / expansion / compression / bm25 / hybrid as MCP tools |
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
| 4.1 | Brain Base Model: Kimi K2.6 on RunPod (1T/32B-active MoE, MIT, INT4 native) — frontier APIs as escape valve only | ⬜ |
| 4.2 | Intent Classification & Routing (ModernBERT-Large CPU classifier, NOT small-LLM router) | ⬜ |

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
| 3 | Agent Framework (OpenClaude MCP bridge) | 🔄 Starting |
| 4 | Orchestration (Kimi K2.6 brain + 12 QLoRA adapters) | ⬜ 0% |
| 5 | Specialists (Engineer-first MVP) | ⬜ 0% |
| 6 | Integration | ⬜ 0% |

---

## Next Action

**Start:** Stage 3, OpenClaude MCP bridge (single deliverable per Decision 2026-05-01)
**File:** [STAGE_3_OPENCLAUDE_STRATEGY.md](../STAGE_3_OPENCLAUDE_STRATEGY.md) + new module `js-development/jarvis_core/agent/mcp_bridge.py`
**Command:** `@[/learn] Explain Model Context Protocol (MCP) — server architecture, tool registration, JSON-RPC transport.` then `@[/dev] Build jarvis_core/agent/mcp_bridge.py exposing store / expansion / compression / bm25 / hybrid / rerank as MCP tools.`
