# 🚀 PROJECT JARVIS: THE MASTER BLUEPRINT (ENDGAME ARCHITECTURE)

> **Last Updated:** 2026-05-03
> **Referenced by:** `.agent/rules/js-workspace-rule.md` (co-located in rules — auto-loaded every conversation)
> **Knowledge Base:** `jarvis_data/knowledge_base.jsonl` (entries tagged `specialist_roster`, `embedding_clusters`)

---

## 1. THE MISSION (What JARVIS Is)

JARVIS is not a monolithic chatbot or a wrapper around a commercial API. It is a **private, hybrid-hosted "Model of Models" (MoM) Cognitive Orchestrator and Autonomous R&D Lab**.

Its purpose is to act as an intellectual exoskeleton for the user, capable of autonomously executing cross-domain research, writing complex software, and controlling physical hardware (e.g., hologram tech, robotics). It leverages the user's private, highly specific historical data (`knowledge_base.jsonl`) and their unique Cognitive Profile to communicate and problem-solve on the user's exact wavelength.

---

## 2. THE HARDWARE TOPOLOGY (Cloud-First, Edge-Augmented)

JARVIS operates on a **cloud-first, prepaid infrastructure**. Earlier drafts of this document (pre-2026-05-01) projected a hybrid edge-cloud model with local GPU upgrade paths; that has been formally **superseded** (see KB Decisions tagged `runpod`, `cost-control`, `no-local-gpu`).

### The Edge (The Brainstem) — Both Laptops, CPU-Only
- Runs **embedding models** locally (MiniLM today, SPECTER2 / CodeBERT / PubMedBERT in Stage 5) on CPU (~2GB RAM total across cluster)
- Runs **ChromaDB** vector store on disk
- Runs all **Python orchestration code** (routing, chunking, retrieval, agents)
- Runs **Whisper** for voice input (CPU mode, slower but free) — Stage 6
- **Cost:** ₹0/month
- **Privacy:** Documents, embeddings, and the knowledge_base.jsonl never leave the local machine
- **Hardware reality:** work laptop is company-controlled WSL Ubuntu; personal laptop is Windows + WSL Ubuntu. Neither has discrete GPU. No purchase planned.

### The Foundry (The Cloud) — RunPod, Prepaid Credits Only
- **Phase 1-3 (current):** OpenRouter API for cheap/free LLMs (~₹400-2,000/month)
- **Phase 4:** RunPod Serverless GPU endpoints for routing + first specialist inference (~₹2,500-6,500/month)
- **Phase 5:** RunPod Dedicated GPU during fine-tuning + specialist work hours (~₹12,000-30,000/month)
- **Billing model:** prepaid credits ONLY. No post-paid billing, no auto-recharge by credit card. Out-of-credits = jobs fail closed (correct behavior; better than silent overage).
- **Top-up cadence:** manual, on-demand. Set a low-balance email alert at ~20% of last top-up.
- **Privacy:** only the final prompt (query + 5 retrieved chunks) leaves the local machine. The knowledge base, raw research papers, and embeddings stay local.

### Why no local GPU
| Considered | Verdict | Reason |
|---|---|---|
| Used RTX 3060 12GB | ❌ Rejected | Even a quantized 70B doesn't fit; would need 2× cards. Hardware setup overhead on a company-controlled work laptop is non-trivial. |
| Used RTX 3090 24GB | ❌ Rejected | Same reasoning at higher cost. Single-card 70B in Q4 fits but with no headroom for KV cache or specialist loading. |
| Mac Mini M4 Pro 48GB | ❌ Rejected | ₹1.7-2L upfront; bursty workloads make the always-on cost worse than RunPod-on-demand for ~12 months of build time. |
| **RunPod on-demand (prepaid)** | ✅ **Chosen** | Pay only when training/inferring; scale up/down per workload; hard cost ceiling via prepaid balance; zero hardware setup. |

The trade is paid compute in exchange for zero hardware setup overhead. Acceptable for a single-developer R&D project where workload is bursty (heavy during fine-tuning weeks; near-zero between).

### The Brain Base Model (Phase 4+)

**Default:** Kimi K2.6 (1T total / 32B active MoE, MIT license, INT4 native, 384 experts, native agent-swarm pattern). Hosted on RunPod, ~Rs 1.5L/month at heavy use (6 hr/day × 4×H100 INT4 ≈ Rs 1,200/hr × 120 hrs).

**Why Kimi K2.6 over alternatives:**
- vs. DeepSeek V4-Pro (1.6T/49B-active): smaller, fits 4×H100 INT4 instead of needing 8×H100. Same MIT license. ~30% cheaper inference.
- vs. self-hosted Llama 4 (400B/17B-active): loses to Kimi K2.6 on SWE-Bench Pro and agentic tasks by 8-15 points.
- vs. frontier APIs (Opus 4.7 / GPT-5.5): frontier APIs cost ~Rs 11L/month at the same usage AND log queries to third parties. Frontier is the **user-invoked escape valve only**, never the default route.

**Frontier escape valve:** Opus 4.7 / GPT-5.5 / Gemini 3.1 Pro are tools the user explicitly hands off to (like calling Wolfram Alpha) for one-off hard problems. Implementation: explicit `/escape-valve` command, never automatic fallback. Budget controlled per session.

---

## 3. THE "MODEL OF MODELS" ROSTER (1 MoE Base + 12 QLoRA Adapters)

**Architecture:** all 12 specialists ship as **QLoRA adapters (~150-500 MB each)** on top of the **shared Kimi K2.6 base**. The Orchestrator loads ONE adapter at a time onto the always-resident base; adapter swap is ~2-5 seconds vs. 10-20s for separate dense model loads. This is the 2026-correct recipe per DeepSeek V4 / Kimi K2.6 / GLM-5.1 distillation patterns and On-Policy Distillation research (arxiv 2602.12125): merged-adapter pattern beats separate dense fine-tunes at ~80% lower training cost.

**The moat is personalization, not parameter count.** Each adapter's value comes from being trained on the user's private corpus — code, KB entries, trade journal, research notes, error logs — not from beating Opus 4.7 zero-shot on MMLU. See KB Decision tagged `specialists, personalization, moat`.

| # | Codename | Domain | Adapter Seed (Public Specialist to Distill From) | Personalization Corpus (User's Private Data) |
|---|----------|--------|------------------------------------------------|----------------------------------------------|
| 1 | **The Orchestrator** | Intent routing, planning, delegation | Kimi K2.6 base + ModernBERT-Large router classifier (separate, CPU-side) | Past routing decisions + user's escape-valve invocations + chat-history attribution |
| 2 | **The Engineer** | Software architecture, pipelines, algorithms (code + DE) | Qwen3-Coder-Next 80B/3B-active distilled in | `jarvis_core/` source, KB entries, chat-history with Claude/Antigravity, DE corpus, past error logs |
| 3 | **The Scientist** | Physics, optics, ArXiv papers, LaTeX math | DeepSeekMath-V2 distilled in for math reasoning | User's hologram-project notes, optics/photonics papers read, /research outputs |
| 4 | **The Doctor** | Medical research, biology, pharmacology | MedGemma 1.5 distilled in (~91 MedQA) | Trusted medical literature + (optionally) user's own health history |
| 5 | **The Operator** | Robotics, hardware control, simulation | OpenVLA + Holo3-35B-A3B distilled in for agentic computer-use | User's CAD files, ROS configs, past simulation outputs |
| 6 | **The Electrician** | Circuit design, EM theory, signal processing, PCB/antenna | Kimi K2.6 base + LoRA on IEEE corpus | User's circuit designs, simulation logs, datasheets read |
| 7 | **The Mechanic** | CAD, FEA, thermal/structural analysis, materials science | Kimi K2.6 base + LoRA on engineering handbooks + MatSciBERT-distilled signals | User's CAD library, material specs, FEA results, hologram structural notes |
| 8 | **The Chemist** | Material properties, reactions, nanotechnology, metallurgy | Kimi K2.6 base + LoRA on PubChem + materials DBs | User's metamaterials research, photonics-relevant chemistry notes |
| 9 | **The Strategist** | Patent analysis, IP landscape, competitive research | SaulLM-141B distilled in for legal reasoning | User's IP filings, prior-art searches, competitive notes |
| 10 | **The Analyst** | Financial modeling, market analysis, BI (the Financier) | Kimi K2.6 base + Qwen 3-235B reasoning + LoRA on Indian markets | Groww trade history, NSE bulk-deals, trade rationale journal, risk profile |
| 11 | **The Guardian** | Cybersecurity, vulnerability analysis, threat modeling | Qwen3-Coder-Next + LoRA on security advisories | User's audit logs, past vuln findings, threat model docs |
| 12 | **The Interface** | Voice input, vision processing, multimodal I/O | Whisper Large-v3 (ASR), Kokoro-82M (TTS), Qwen2.5-VL-7B (vision) — separate models, NOT adapters on Kimi | User's voice recordings (consented), screen/CAD captures |

### What changed from the pre-2026-05-03 framing

| Before | After (Decision 2026-05-03) |
|---|---|
| 12 separate dense fine-tunes (~Rs 17-40L training cost; 12 × 70B model loads) | 1 MoE base (Kimi K2.6) + 12 QLoRA adapters (~Rs 1-2L total training; one base + adapter swap) |
| Brain = Llama-3.3 70B quantized | Brain = Kimi K2.6 (1T/32B-active MoE) |
| "Phase 1-3 cloud APIs as default route, Phase 4 self-host" | Frontier APIs are escape-valve-only; Kimi K2.6 self-hosted on RunPod is the default Brain from Phase 4 onwards |
| Specialist value = beating public benchmarks | Specialist value = personalized on user's private corpus + agentic infrastructure |

### Embedding Model Clusters (Memory Layer — orthogonal to specialists)

The embedding stack stays on the **local laptop** (CPU, ~Rs 0/month). Specialists query the same shared embedding space; the LoRA adapters do NOT change embeddings. Stage 2.5 cutover: MiniLM-L6-v2 → EmbeddingGemma-300M (better instruction-retrieval, multilingual, sub-22 ms latency, drop-in replacement).

```
Cluster A: EmbeddingGemma 300M (768d)   → General text, conversation, Strategist, Analyst, default
Cluster B: SPECTER2 (768d)              → Scientist, Electrician, Mechanic (papers — still SOTA for science)
Cluster C: CodeRankEmbed / Voyage-Code-3 → Engineer, Guardian (code embeddings)
Cluster D: PubMedBERT (768d)            → Doctor, Chemist (biomedical)
Cluster E: SigLIP-2 (vision)            → Operator, Interface
Cluster F: MatSciBERT (768d)            → Mechanic, Chemist (materials)

Total VRAM for ALL embedding models: ~2GB (fit permanently on any machine, CPU-only, Rs 0)

Reranker (Stage 2.5.3): mxbai-rerank-large-v2 (1.5B Apache-2.0, ~150ms CPU for 20 chunks)
```

---

## 3.5. AGENTIC SPECIALIST INFRASTRUCTURE (Stage 6+)

Specialists are not just models. The valuable ones (Analyst/Financier, Operator, Scientist for hologram R&D) are **always-on agentic systems** layered on top of the model. The model is one piece; the cron + ingestion + trigger + cold-wake pipeline is the bigger engineering project.

### Pattern (worked example: The Analyst / Financier watching markets)

```
[Continuous data ingestion — runs on local laptop, Rs 0/month]
  ├── Cron pulls NSE bulk-deals (daily after market close)
  ├── Webhook listens to Groww portfolio updates
  ├── RSS / NewsAPI / Twitter scraper for sentiment + catalysts
  └── Market data feeds (yfinance / kite-connect for India)
       ↓ embeds + structured-DB indexes locally
[Local ChromaDB + structured DB (DuckDB or SQLite for tabular)]
       ↓ trigger conditions
[Trigger evaluator (CPU, runs every N minutes)]
  ├── Price-spike thresholds (user-defined per holding)
  ├── Bulk-deal volume anomalies (e.g., MTAR-class breakouts)
  ├── Sentiment shift on user's watchlist
  └── Predicted-event catalysts (earnings, Fed announcements, etc.)
       ↓ on trigger
[Cold-wake RunPod endpoint: Kimi K2.6 base + Analyst LoRA]
  ├── Loads in 30-60 seconds
  ├── Reasons over: portfolio + flagged signal + user's risk profile + trade journal
  └── Generates: alert + recommendation + entry/stop logic
       ↓
[Notification to user — Telegram / email / OS notification]

Cost: ~Rs 25-80 per wakeup × ~10 wakeups/day = Rs 7,500-25,000/month
vs. equivalent Opus 4.7 API: ~Rs 24,000-72,000/month AND portfolio data leaks to logs
```

### Pattern (worked example: Hologram R&D session)

Same cold-wake + agent infrastructure, different specialists active in parallel. Kimi K2.6's native agent-swarm support (384 experts → can spawn parallel inference threads) means **Scientist + Engineer + Mathematician adapters reason concurrently** during heavy R&D. The Orchestrator spawns sub-tasks; each adapter swaps in for its sub-domain (physics, code, math); results aggregate via the Aggregator.

### What this is NOT

- **Not a chatbot session.** Specialists are wakeup-on-event, not always-running.
- **Not a single-model wrapper.** The infrastructure layer (cron, triggers, ingestion, notifier) is most of the engineering.
- **Not built before Stage 6.** The model + adapter training comes first (Stage 5); the agentic infrastructure layered on top is Stage 6+.

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

**Current Position:** Stage 2, Sub-phase 2.5 (Hybrid Search & Reranking) — 2.5.1-2.5.6 complete; 2.5.7 (LLM-as-Judge) and 2.5.8 (KB Compaction & Expiry) pending.

---

## APPENDIX: Fine-Tuning Failure Diagnostic Map

Stored in `knowledge_base.jsonl` (tagged: `fine_tuning, diagnostic_map`). Maps training failure symptoms to required math prerequisites. See entry for 7 symptom→study mappings.
