# PHASE 4: Multi-Model Orchestration Roadmap

> **Master Plan Position:** Phase 4 of 6 → [JARVIS_MASTER_ROADMAP.md](../JARVIS_MASTER_ROADMAP.md)  
> **Goal:** Build the Router → Specialist → Aggregator pattern for multi-model dispatch.  
> **Prerequisites:** Phase 1-3 (Python, Memory, Agents)  
> **Hardware:** Hybrid — Local CPU (embeddings/ChromaDB) + Cloud GPU (LLM serving via RunPod/Vast.ai). See `JARVIS_ENDGAME.md` Section 2.

---

## Overview

| Sub-Phase | Name | Core Concept | Definition of Done |
|-----------|------|--------------|-------------------|
| **4.0** | Cognitive Control Loop | Self-awareness: time, identity, goals, confidence | Orchestrator passes all 4 awareness tests |
| **4.1** | Model Loading & Serving | Run LLMs via cloud GPU (quantization, MoE, serverless) | Can load/unload 70B-4bit on cloud GPU endpoint |
| **4.2** | Intent Classification & Routing | Dispatch queries to the right specialist | Router correctly classifies 90%+ of queries |
| **4.3** | Dynamic Model Management | Load/unload models + speculative decoding | Models swap in <20s, speculative decoding gives 2-3x speedup |
| **4.4** | Response Aggregation | Combine specialist outputs | Aggregator produces coherent unified response |
| **4.5** | Epistemic Control | Handle conflicts and uncertainty | Confidence scoring and disagreement detection |
| **4.6** | GraphRAG | Upgrade flat vectors to knowledge graph | Multi-hop reasoning across research papers |

---

## Sub-Phase 4.0: Cognitive Control Loop (Self-Awareness) ⬜

**Goal:** Make JARVIS aware of time, identity, goals, and its own confidence before any model exchange occurs. This is the foundational layer all other sub-phases depend on. Without this, JARVIS is a stateless chatbot. With it, JARVIS is an agent.

> **The 4 Pillars of JARVIS Self-Awareness:**
> 1. **Temporal** — knows what time and date it is, can reason about past sessions
> 2. **Identity** — knows who the user is, what decisions were made, what to NOT do
> 3. **Teleological** — knows what it must do next and why (reads its own roadmap)
> 4. **Metacognitive** — knows how confident it is and when to escalate to the user

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 4.0.1 | ContextInjector Class | Prepend system state (timestamp, workspace, hardware, memory count) to every prompt | `/dev Build ContextInjector class for JARVIS Orchestrator.` |
| 4.0.2 | Pre-fetch RAG Hook | Before answering, silently search knowledge_base for user identity, past decisions, and personality protocol | `/dev Implement pre-fetch RAG hook in Orchestrator.` |
| 4.0.3 | ROADMAP State Reader | Parse ROADMAP.md to identify next unchecked task. JARVIS opens every session knowing what is pending | `/dev Build RoadmapStateReader that parses [ ] vs [x] checkboxes.` |
| 4.0.4 | Confidence Gate | Internal critic evaluates draft response against knowledge_base. If confidence < threshold, JARVIS flags uncertainty instead of guessing | `/dev Implement Confidence Gate with fallback escalation.` |
| 4.0.5 | Session Memory Writer | At end of every session, auto-extract decisions/failures/patterns and append to knowledge_base.jsonl | `/dev Build SessionMemoryWriter for end-of-session distillation.` |

**Practical Exercise:** Boot JARVIS and verify it can answer the following WITHOUT being told:
1. *"What time is it?"* → Reads from ContextInjector
2. *"What were we doing yesterday?"* → Queries knowledge_base by calculated date
3. *"What should we work on next?"* → Reads ROADMAP.md, returns first unchecked task
4. *"Are you sure about that?"* → Returns a confidence score, not a hallucination

> **Why this comes before model loading:** You cannot route queries intelligently (4.2) or aggregate responses with confidence scoring (4.5) if the Orchestrator has no self-model. This is the Orchestrator's nervous system — it must exist before the brain.

---

## Sub-Phase 4.1: Local Model Loading ⬜

**Goal:** Run large language models on cloud GPU endpoints (RunPod Serverless / Vast.ai).

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 4.1.1 | Ollama Basics | Run models with simple CLI | `@[/learn] Explain Ollama and local model serving.` |
| 4.1.2 | vLLM for Production | High-throughput model serving | `@[/learn] Explain vLLM and when to use it.` |
| 4.1.3 | Quantization (AWQ/GPTQ/GGUF) | Fit 70B in cloud GPU VRAM (CRITICAL) | `@[/learn] Explain quantization: AWQ vs GPTQ vs GGUF, quality loss, VRAM savings.` |
| 4.1.4 | Mixture of Experts (MoE) Models | 70B quality at 12B VRAM cost | `@[/learn] Explain MoE architecture: Mixtral 8x7B activates 2/8 experts per token, 46B total but 12B active.` |
| 4.1.5 | Cloud GPU Serving | Deploy models on RunPod/Vast.ai endpoints | `/dev Configure vLLM for cloud GPU serving.` |

**Practical Exercise:** Deploy Llama-3-70B-4bit on RunPod Serverless, compare with Mixtral-8x7B. Benchmark latency and cost per query.

> **CRITICAL:** Without quantization, JARVIS cannot run. FP16 70B = 140GB.
> AWQ 4-bit = 35GB with ~0.3% quality loss. This is not optional.

---

## Sub-Phase 4.2: Intent Classification & Routing ⬜

**Goal:** Direct queries to the appropriate specialist model.

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 4.2.1 | Router Architecture | Lightweight classifier + dispatch | `@[/learn] Explain router design for MoM systems.` |
| 4.2.2 | Intent Categories | Code, Research, General, Medical | `/dev Design intent taxonomy for JARVIS.` |
| 4.2.3 | Classifier Training | Fine-tune small model for routing | `@[/learn] Explain training a router classifier.` |
| 4.2.4 | Fallback Strategies | When classification is uncertain | `@[/learn] Explain fallback routing strategies.` |

**Practical Exercise:** Router correctly dispatches to code vs. research specialist.

---

## Sub-Phase 4.3: Dynamic Model Management ⬜

**Goal:** Load/unload models efficiently, speed up inference with speculative decoding.

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 4.3.1 | Model Lifecycle | Load → Serve → Unload pattern | `/dev Design a ModelManager for JARVIS.` |
| 4.3.2 | VRAM Management | Monitor and cleanup GPU memory | `/dev Implement VRAM monitoring and cleanup.` |
| 4.3.3 | Caching Strategy | Keep frequently-used models warm | `@[/learn] Explain model caching strategies.` |
| 4.3.4 | Concurrent Loading | Prepare next model while serving | `/dev Implement async model preloading.` |
| 4.3.5 | Speculative Decoding | 2-3x speedup via draft+verifier | `@[/learn] Explain speculative decoding: small draft model generates candidates, large model verifies in one pass.` |

**Practical Exercise:** Swap between code and general model in <20s. Benchmark speculative decoding throughput.

> **How Speculative Decoding Works:**
> Run Llama 3B (draft) to generate 8 candidate tokens instantly.
> 70B (verifier) checks all 8 in ONE forward pass.
> If 6/8 correct, you got 6 tokens for 1 forward pass cost = 2-3x free speedup.

---

## Sub-Phase 4.4: Response Aggregation ⬜

**Goal:** Combine outputs from multiple specialists into coherent responses.

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 4.4.1 | Aggregation Patterns | Synthesis, voting, chain | `@[/learn] Explain response aggregation patterns.` |
| 4.4.2 | Synthesis Prompting | Merge multiple specialist outputs | `/dev Implement synthesis aggregator for JARVIS.` |
| 4.4.3 | Source Attribution | Track which specialist said what | `/dev Add source tracking to aggregator.` |
| 4.4.4 | Quality Filtering | Discard low-quality outputs | `@[/learn] Explain output quality filtering.` |

**Practical Exercise:** Aggregate physics + code specialist for a computational physics query.

---

## Sub-Phase 4.5: Epistemic Control ⬜

**Goal:** Handle uncertainty, conflicts, and confidence scoring.

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 4.5.1 | Confidence Scoring | How certain is each output? | `@[/learn] Explain confidence estimation in LLMs.` |
| 4.5.2 | Conflict Detection | Specialists disagree — now what? | `/dev Implement conflict detection in aggregator.` |
| 4.5.3 | Uncertainty Propagation | Mark tentative conclusions | `@[/learn] Explain uncertainty propagation.` |
| 4.5.4 | Human Escalation | Know when to ask the user | `/dev Implement human-in-the-loop escalation.` |

**Practical Exercise:** Aggregator correctly flags conflicting specialist outputs.

---

## Final Boss: The Brain

Build a complete orchestrator that:
1. [ ] Classifies intent and routes to appropriate specialist
2. [ ] Dynamically loads/unloads models on cloud GPU endpoints (cost-optimized spin-up/spin-down)
3. [ ] Aggregates specialist outputs into coherent response
4. [ ] Scores confidence and flags conflicts
5. [ ] Escalates to human when uncertain

**When this works, JARVIS has its Brain.**

---

## Progress Tracker

| Sub-Phase | Status | Lessons Complete |
|-----------|--------|------------------|
| 4.0 Cognitive Control Loop (Self-Awareness) | ⬜ Not Started | 0/5 |
| 4.1 Local Model Loading | ⬜ Not Started | 0/5 |
| 4.2 Intent Classification & Routing | ⬜ Not Started | 0/4 |
| 4.3 Dynamic Model Management | ⬜ Not Started | 0/5 |
| 4.4 Response Aggregation | ⬜ Not Started | 0/4 |
| 4.5 Epistemic Control | ⬜ Not Started | 0/4 |
| 4.6 GraphRAG | ⬜ Not Started | 0/0 |

---

## After This Phase

→ Proceed to **Phase 5: Domain Specialists** → [PHASE_05_ROADMAP.md](../specialist-learning/PHASE_05_ROADMAP.md)
