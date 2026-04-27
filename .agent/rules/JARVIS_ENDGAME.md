# 🚀 PROJECT JARVIS: THE MASTER BLUEPRINT (ENDGAME ARCHITECTURE)

> **Last Updated:** 2026-04-26
> **Referenced by:** `.agent/rules/js-workspace-rule.md` (co-located in rules — auto-loaded every conversation)
> **Knowledge Base:** `jarvis_data/knowledge_base.jsonl` (entries tagged `specialist_roster`, `embedding_clusters`)

---

## 1. THE MISSION (What JARVIS Is)

JARVIS is not a monolithic chatbot or a wrapper around a commercial API. It is a **private, hybrid-hosted "Model of Models" (MoM) Cognitive Orchestrator and Autonomous R&D Lab**.

Its purpose is to act as an intellectual exoskeleton for the user, capable of autonomously executing cross-domain research, writing complex software, and controlling physical hardware (e.g., hologram tech, robotics). It leverages the user's private, highly specific historical data (`knowledge_base.jsonl`) and their unique Cognitive Profile to communicate and problem-solve on the user's exact wavelength.

---

## 2. THE HARDWARE TOPOLOGY (Hybrid Edge-Cloud)

JARVIS operates on a **cost-optimized, privacy-first hybrid infrastructure**:

### The Edge (The Brainstem) — Your Laptop/Desktop
- Runs **ALL embedding models** (MiniLM, CodeBERT, SPECTER2, etc.) on CPU (~2GB total)
- Runs **ChromaDB** vector store on disk
- Runs all **Python orchestration code** (routing, chunking, retrieval, agents)
- Runs **Whisper** for voice input (CPU mode, slower but free)
- **Cost:** ₹0/month
- **Privacy:** Documents and embeddings NEVER leave your machine

### The Foundry (The Cloud) — Pay-Per-Use GPUs
- **Phase 1-3:** Free/cheap LLM APIs (Groq, Together.ai, OpenRouter) — ₹200-400/month
- **Phase 4:** Serverless GPU endpoints (RunPod Serverless, Modal) — ₹2,500-6,500/month
- **Phase 5+:** Dedicated cloud GPU during work hours (RunPod/Vast.ai A100 80GB) — ₹12,000-30,000/month
- Spun up only when the Orchestrator needs to query specialist models, then immediately spun down
- **Privacy:** Only the final prompt (query + 5 retrieved chunks) leaves your machine, not the full knowledge base

### Upgrade Path (If Budget Allows)
| Hardware | VRAM | Can Run | Price (₹) |
|----------|------|---------|-----------|
| Used RTX 3060 12GB | 12GB | Orchestrator 8B + 1 specialist | 15,000-20,000 |
| Used RTX 3090 24GB | 24GB | Orchestrator 8B + 3 specialists | 55,000-75,000 |
| Mac Mini M4 Pro 48GB | 48GB unified | Orchestrator 32B + 3 specialists | 1,70,000-2,00,000 |

---

## 3. THE "MODEL OF MODELS" ROSTER (The 12 Specialists)

JARVIS breaks down complex tasks and routes them to the optimal neural network. The Orchestrator decides which ONE specialist to load per query — they never all run simultaneously.

| # | Codename | Domain | LLM (Cloud Phase 1-3) | LLM (Local Phase 4+) | Embedding Model |
|---|----------|--------|-----------------------|----------------------|-----------------|
| 1 | **The Orchestrator** | Intent routing, planning, delegation | DeepSeek-V4 / Gemini 2.5 Flash | Llama-3.3 70B (quantized) | N/A (prompt-based reasoning) |
| 2 | **The Engineer** | Software architecture, pipelines, algorithms | DeepSeek-V4 / Qwen2.5-Coder-32B | DeepSeek-R2-Lite or Qwen2.5-Coder-32B-Q4 | CodeBERT / StarEncoder |
| 3 | **The Scientist** | Physics, optics, ArXiv papers, LaTeX math | DeepSeek-V4 / Gemini 2.5 Pro | SPECTER2-finetuned | SPECTER2 |
| 4 | **The Doctor** | Medical research, biology, pharmacology | DeepSeek-V4 / Claude 3.5 Sonnet | BioMistral / Med42 | PubMedBERT |
| 5 | **The Operator** | Robotics, hardware control, simulation | Gemini 2.5 Pro (vision) | OpenVLA (Vision-Language-Action) | CLIP / SigLIP |
| 6 | **The Electrician** | Circuit design, EM theory, signal processing, PCB/antenna | DeepSeek-V4 | Fine-tuned on IEEE corpus | SciBERT / SPECTER2 |
| 7 | **The Mechanic** | CAD, FEA, thermal/structural analysis, materials science | DeepSeek-V4 | Fine-tuned on engineering handbooks | SPECTER2 / MatSciBERT |
| 8 | **The Chemist** | Material properties, reactions, nanotechnology, metallurgy | DeepSeek-V4 | Fine-tuned on PubChem + materials DBs | MatSciBERT |
| 9 | **The Strategist** | Patent analysis, IP landscape, competitive research | Gemini 2.5 Pro (128K+) | Base LLM + long-context | Legal-BERT / MiniLM |
| 10 | **The Analyst** | Financial modeling, market analysis, business intelligence | DeepSeek-V4 / Gemini 2.5 Flash | Base LLM | FinBERT |
| 11 | **The Guardian** | Cybersecurity, vulnerability analysis, threat modeling | DeepSeek-V4 / Qwen2.5-Coder-32B | CodeLlama / SecureFalcon | CodeBERT (shared) |
| 12 | **The Interface** | Voice input, vision processing, multimodal I/O | Gemini 2.5 Pro (native multimodal) | Whisper V3 (STT) + Qwen-VL (vision) | CLIP (images), MiniLM (transcripts) |

### Embedding Model Clusters (6 unique models serving 12 specialists)

```
Cluster A: MiniLM 384-dim     → General text, conversation, Strategist, Analyst
Cluster B: SPECTER2 768-dim   → Scientist, Electrician, Mechanic (papers)
Cluster C: CodeBERT 768-dim   → Engineer, Guardian (code)
Cluster D: PubMedBERT 768-dim → Doctor, Chemist (biomedical)
Cluster E: CLIP/SigLIP 512-dim → Operator, Interface (vision)
Cluster F: MatSciBERT 768-dim → Mechanic, Chemist (materials)

Total VRAM for ALL embedding models: ~2GB (fit permanently on any machine)
```

---

## 4. THE MEMORY ARCHITECTURE (Beyond VectorDBs)

JARVIS does not rely on naive "dumb" chunking. Its memory stack is OS-grade:

### 4-Layer Retrieval Stack
```
Query hits all 4 layers → results merged via Reciprocal Rank Fusion + Reranker

LAYER 1: Semantic Search (ChromaDB + domain embedding model)
  → Good for: General knowledge, conversation, documentation

LAYER 2: Token-Level Search (ColBERT late interaction)
  → Good for: Code syntax, API signatures, LaTeX formulas, exact terms

LAYER 3: Graph Search (GraphRAG — explicit entity relationships)
  → Good for: Multi-hop reasoning, "which paper cited X and used method Y?"

LAYER 4: Keyword Search (BM25 — term frequency)
  → Good for: Exact string matches, error codes, chemical names, part numbers
```

### Memory Management
- **MemGPT (Autonomous Paging):** The orchestrator manages its own memory like an OS, promoting hot facts to context and demoting cold facts to disk.
- **KV-Caching:** Massive context windows for ingesting entire codebases at once.
- **Cognitive Profile:** JARVIS continually updates a psychological map of the user via `knowledge_base.jsonl` entries with `type: "Cognitive_Pattern"`.

### Chunking Pipeline (Pre-Embedding)
- **Strategy 1 (Default):** Fixed-size ~200 word chunks with ~50 word overlap
- **Strategy 2:** Semantic chunking — split on paragraph/topic boundaries
- **Strategy 3:** Sentence-level — for specialized high-precision retrieval
- MiniLM software limit: 256 tokens. Physical table: 512 rows. Documents MUST be chunked before encoding.

---

## 5. THE ENGINEERING ENGINE (Speed & Safety)

To run massive intelligence on limited hardware, JARVIS utilizes:

- **Speculative Decoding (MTP):** Multiplying token generation speed by having models draft and verify tokens in parallel.
- **Quantization (AWQ/GGUF/GPTQ):** Compressing 70B models to fit available VRAM with <1% degradation.
- **Structured Generation (Outlines/Guidance):** Forcing agent outputs into strict Pydantic JSON schemas. JARVIS never hallucinates a tool call or breaks an agent loop.
- **Dynamic Model Loading:** Orchestrator loads ONE specialist at a time (~10-20s swap time on cloud, ~5s on local GPU).

---

## 6. THE AUTONOMOUS R&D LOOP (The "Iron Man" Standard)

JARVIS does not just "run cron jobs." It executes intelligent loops while the user sleeps:

1. **Execute:** Triggers a physical simulation or hardware test.
2. **Analyze:** Reads the output logs/visuals and detects failures (e.g., thermal drift).
3. **Hypothesize:** Cross-references `knowledge_base.jsonl` to find past similar failures and constructs a physics-based hypothesis.
4. **Rewrite:** The Engineer specialist rewrites the control script to compensate.
5. **Rerun:** JARVIS initiates the next test, iterating until a breakthrough is found.

---

## 7. BUILD PHASES

| Phase | Duration | What Gets Built |
|-------|----------|----------------|
| **1 (Systems Python)** ✅ | 2-3 months | Async, generators, context managers |
| **2 (Memory Layer)** 🔄 | 1-2 months | Embeddings, ChromaDB, chunking, hybrid search |
| **3 (Agent Framework)** | 1-2 months | Tool-calling, planning agents, ReAct pattern |
| **4 (Orchestration)** | 2-3 months | Router, Aggregator, GraphRAG, dynamic model loading |
| **5 (Specialists)** | 2-3 months | Fine-tuning (LoRA), domain-specific models |
| **6 (Integration)** | 1-2 months | Voice, vision, unified API, JARVIS MVP |

**Current Position:** Stage 2, Sub-phase 2.4 (Retrieval Strategies) — Sub-phases 2.1, 2.2, 2.3 complete.

---

## APPENDIX: Fine-Tuning Failure Diagnostic Map

Stored in `knowledge_base.jsonl` (tagged: `fine_tuning, diagnostic_map`). Maps training failure symptoms to required math prerequisites. See entry for 7 symptom→study mappings.
