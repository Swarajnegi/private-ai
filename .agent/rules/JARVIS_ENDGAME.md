# 🚀 PROJECT JARVIS: THE MASTER BLUEPRINT (ENDGAME ARCHITECTURE)

> **Last Updated:** 2026-05-03 (costs verified against RunPod public pricing page)
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
- **Phase 4:** RunPod Cloud Pods for training + inference (~₹910-1,820/month at 10-20 sessions)
- **Phase 5:** Same pods, heavier usage during fine-tuning weeks (~₹3,000-6,000/month)
- **Billing model:** prepaid credits ONLY. No post-paid billing, no auto-recharge by credit card. Out-of-credits = jobs fail closed (correct behavior; better than silent overage).
- **Top-up cadence:** manual, on-demand. Set a low-balance email alert at ~20% of last top-up.
- **Privacy:** only the final prompt (query + 5 retrieved chunks) leaves the local machine. The knowledge base, raw research papers, and embeddings stay local.

### RunPod GPU Selection (Verified Pricing, May 2026)

Cost minimization strategy: use the cheapest GPU that fits the job. Time is not a constraint.

| GPU | VRAM | Community Cloud $/hr | ₹/hr | Role in JARVIS |
|---|---|---|---|---|
| **RTX A5000** | 24 GB | **$0.27** | **₹23** | ⭐ Default for 7/12 adapter training jobs + Interface fine-tune |
| **A40** | 48 GB | **$0.44** | **₹37** | ⭐ For 5 adapters that distill from large teachers (Engineer, Scientist, Operator, Strategist, Analyst) |
| RTX 3090 | 24 GB | $0.46 | ₹39 | Viable A5000 alternative if A5000 unavailable |
| A6000 | 48 GB | $0.49 | ₹41 | Viable A40 alternative |
| RTX 4090 | 24 GB | $0.69 | ₹58 | Faster training at 2.5× A5000 cost — only if time becomes urgent |
| A100 PCIe | 80 GB | $1.39 | ₹117 | Inference fallback (fits full Kimi K2.6 INT4 on one card) |

**Inference-viable configurations for Kimi K2.6 (1T params, INT4 ≈ 200-400 GB):**

| Config | Cost | Latency | Notes |
|---|---|---|---|
| 4× RTX A5000 (model parallel) | ₹91/hr | Normal | 96GB total VRAM, cheapest viable multi-GPU |
| 1× A100 80GB | ₹117/hr | Normal | Tight fit with KV cache, single-card simplicity |
| 1× A40 + CPU offload | ₹37/hr | 3-5× slower | Cheapest option if latency is acceptable |

### Why no local GPU
| Considered | Verdict | Reason |
|---|---|---|
| Used RTX 3060 12GB | ❌ Rejected | Even a quantized 70B doesn't fit; would need 2× cards. Hardware setup overhead on a company-controlled work laptop is non-trivial. |
| Used RTX 3090 24GB | ❌ Rejected | Same reasoning at higher cost. Single-card 70B in Q4 fits but with no headroom for KV cache or specialist loading. |
| Mac Mini M4 Pro 48GB | ❌ Rejected | ₹1.7-2L upfront; bursty workloads make the always-on cost worse than RunPod-on-demand for ~12 months of build time. |
| **RunPod on-demand (prepaid)** | ✅ **Chosen** | Pay only when training/inferring; scale up/down per workload; hard cost ceiling via prepaid balance; zero hardware setup. |

The trade is paid compute in exchange for zero hardware setup overhead. Acceptable for a single-developer R&D project where workload is bursty (heavy during fine-tuning weeks; near-zero between).

### The Brain Base Model (Phase 4+)

**Default:** Kimi K2.6 (1T total / 32B active MoE, MIT license, INT4 native, 384 experts, native agent-swarm pattern). Hosted on RunPod Cloud Pods. Cold-wake only — no always-on GPU. Cost at 4× A5000: ₹91/hr; at 15 sessions/month averaging 1 hr: **~₹1,365/month**.

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
[Cold-wake RunPod Pod: Kimi K2.6 base + Analyst LoRA on 4× A5000]
  ├── Loads in 60-90 seconds
  ├── Reasons over: portfolio + flagged signal + user's risk profile + trade journal
  └── Generates: alert + recommendation + entry/stop logic
       ↓
[Notification to user — Telegram / email / OS notification]

Cost: ~Rs 15-30 per wakeup (10-20 min × ₹91/hr) × ~10 wakeups/day = Rs 4,500-9,000/month
vs. equivalent Opus 4.7 API: ~Rs 24,000-72,000/month AND portfolio data leaks to logs
```

### Pattern (worked example: Hologram R&D session)

Same cold-wake + agent infrastructure, different specialists active in parallel. Kimi K2.6's native agent-swarm support (384 experts → can spawn parallel inference threads) means **Scientist + Engineer + Mathematician adapters reason concurrently** during heavy R&D. The Orchestrator spawns sub-tasks; each adapter swaps in for its sub-domain (physics, code, math); results aggregate via the Aggregator.

### What this is NOT

- **Not a chatbot session.** Specialists are wakeup-on-event, not always-running.
- **Not a single-model wrapper.** The infrastructure layer (cron, triggers, ingestion, notifier) is most of the engineering.
- **Not built before Stage 6.** The model + adapter training comes first (Stage 5); the agentic infrastructure layered on top is Stage 6+.

---

## 3.6. TRAINING & USAGE COST SCHEDULE (Verified May 2026)

**Source:** RunPod public pricing page. All costs in INR ($1 = ₹84).
**Constraint:** No deadline. Minimize capital. Cold-wake only (no idle GPUs).

### Per-Specialist Training Costs (One-Time)

| # | Specialist | GPU | Rank | Epochs | GPU-Hours | Training Cost (₹) |
|---|---|---|---|---|---|---|
| 0 | Base (Kimi K2.6) | — | — | — | — | ₹200 (deploy only) |
| 1 | Orchestrator | A5000 ($0.27) | 16 | 3 | 8-15 | ₹180 – ₹340 |
| 2 | Engineer | A40 ($0.44) | 32 | 5 | 40-80 | ₹1,480 – ₹2,960 |
| 3 | Scientist | A40 ($0.44) | 32 | 5 | 50-100 | ₹1,850 – ₹3,700 |
| 4 | Doctor | A5000 ($0.27) | 16 | 3 | 20-35 | ₹450 – ₹790 |
| 5 | Operator | A40 ($0.44) | 32 | 5 | 60-120 | ₹2,220 – ₹4,440 |
| 6 | Electrician | A5000 ($0.27) | 16 | 4 | 20-35 | ₹450 – ₹790 |
| 7 | Mechanic | A5000 ($0.27) | 16 | 4 | 20-30 | ₹450 – ₹680 |
| 8 | Chemist | A5000 ($0.27) | 16 | 4 | 20-35 | ₹450 – ₹790 |
| 9 | Strategist | A40 ($0.44) | 16 | 4 | 35-60 | ₹1,300 – ₹2,220 |
| 10 | Analyst | A40 ($0.44) | 32 | 5 | 40-70 | ₹1,480 – ₹2,590 |
| 11 | Guardian | A5000 ($0.27) | 16 | 4 | 20-35 | ₹450 – ₹790 |
| 12 | Interface | A5000 ($0.27) | 8-16 | 3 | 12-20 | ₹270 – ₹450 |
| | **TOTAL** | | | | **345-635 hrs** | **₹11,230 – ₹20,540** |

### Training Sequence (ROI-Ordered, Spread Across Build Phases)

| Priority | Specialist | When | Cumulative Spend |
|---|---|---|---|
| 1 | Orchestrator | Stage 3 start | ₹340 |
| 2 | Engineer | Stage 3 | ₹3,300 |
| 3 | Analyst | Stage 4 | ₹5,890 |
| 4 | Scientist | Stage 4 | ₹9,590 |
| 5 | Guardian | Stage 4 | ₹10,380 |
| 6 | Operator | Stage 5 | ₹14,820 |
| 7 | Strategist | Stage 5 | ₹17,040 |
| 8-12 | Rest | Stage 5-6 | ₹20,540 |

**Stage 3 entry ticket (Orchestrator + Engineer): ₹3,300 total.**

### Monthly Usage Cost (Cold-Wake Sessions)

| Inference Config | ₹/hr | 10 sessions/mo (1hr avg) | 20 sessions/mo |
|---|---|---|---|
| 4× A5000 (model parallel) | ₹91 | ₹910 | ₹1,820 |
| 1× A100 80GB | ₹117 | ₹1,170 | ₹2,340 |
| 1× A40 + CPU offload (slow) | ₹37 | ₹370 | ₹740 |

### Year 1 Total Cost Projection

| Scenario | Training | Usage (12 mo) | Storage | Total |
|---|---|---|---|---|
| Conservative (8 sessions/mo, A40 offload) | ₹15,000 | ₹3,600 | ₹3,000 | **₹21,600** (~$257) |
| Moderate (15 sessions/mo, 4× A5000) | ₹15,000 | ₹16,380 | ₹3,000 | **₹34,380** (~$410) |
| Heavy (25 sessions/mo, 4× A5000) | ₹20,000 | ₹27,300 | ₹3,000 | **₹50,300** (~$599) |


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
