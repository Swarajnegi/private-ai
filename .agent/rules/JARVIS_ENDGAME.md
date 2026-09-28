# 🚀 PROJECT JARVIS: THE MASTER BLUEPRINT (ENDGAME ARCHITECTURE)

> **Last Updated:** 2026-08-10 (§3 roster gated by demand signal per the two-moats split, NOT personal-data availability — corrected same-day after briefly re-deriving and contradicting the 2026-07-18 REVISED decision; costs below still verified against RunPod public pricing page, May 2026)
> **Referenced by:** `.agent/rules/js-workspace-rule.md` (co-located in rules — auto-loaded every conversation)
> **Knowledge Base:** `jarvis_data/knowledge_base.jsonl` (entries tagged `specialist_roster`, `embedding_clusters`)

---

## 1. THE MISSION (What JARVIS Is)

JARVIS is not a monolithic chatbot or a wrapper around a commercial API. It is a **private, hybrid-hosted "Model of Models" (MoM) Cognitive Orchestrator and Autonomous R&D Lab**.

Its purpose is to act as an intellectual exoskeleton for the user, capable of autonomously executing cross-domain research, writing complex software, and controlling physical hardware (e.g., hologram tech, robotics). It leverages the user's private, highly specific historical data (`knowledge_base.jsonl`) and their unique Cognitive Profile to communicate and problem-solve on the user's exact wavelength.

### 1.1 THE DELIVERED FORM (what "done" actually looks like)

> **Added 2026-08-26.** Everything above describes what JARVIS can **DO**. Nothing described what
> JARVIS **IS TO THE USER**, and that omission was load-bearing: a grep of the entire canon
> (`.agent/rules/`, `JARVIS_MASTER_ROADMAP.md`, `stage_6_integration/ROADMAP.md`) returned **zero
> hits** for phone app, desktop app, web app, android, ios, electron, or "ambient" — the only
> adjacent line anywhere was `6.1.4 Wake Word Detection`. The goal existed solely in the user's
> head. Work therefore drifted toward what the docs *did* measure — corpus statistics — which the
> user corrected directly: *"All we're doing now, having conversations on different topics etc must
> not blind you from the goal."* Written down here so it can anchor the roadmap instead.

The finished system is **a trained model that is present**, not a context-injected assistant that is
summoned. In the user's own framing:

1. **Trained, not injected.** The `cognitive_profile.md` → SessionStart injection path is explicitly
   accepted as good-for-now and explicitly **not** the goal. The deliverable is the QLoRA adapter of
   Stage 5, actually trained and actually deployed.
2. **Deployed on every surface the user lives on** — phone app, desktop app, web app. Not a
   terminal `--ask` and not a chat window in someone else's IDE.
3. **Wired to the senses** — phone camera, laptop camera, and microphones on both.
4. **Ambient.** *"can really live with me, like jarvis in iron man."* Present continuously rather
   than invoked per-question.

**Progress is measured as distance to this, not as corpus depth.** Corpus statistics (record counts,
blend ratios, char share) are *instrumentation for step 1* and must always be framed as such — see
§7's Distance to Goal and `stage_6_integration/ROADMAP.md`.

### 1.2 THE DIFFERENTIATOR — what JARVIS does that a subscription cannot

> **Added 2026-09-06**, after an external audit (GPT 5.6 Terra) concluded JARVIS is not the vehicle
> for three of the four goals above, and forced the question: *what survives the counterfactual of
> simply paying for a frontier model?* Everything the audit tested lost — reasoning, context,
> knowledge, even personalization. **One thing survived.**

**A frontier model does all of it *if you paste the right context*. It cannot fire when you did not
know to ask.** Pasting requires knowing what you forgot. That gap is the entire moat, and it is not
a gap you can subscribe your way out of.

So the capability is **unprompted surfacing over your own history** — and every goal in §1.1
reduces to it:

| Goal | The one sentence JARVIS must say, unprompted |
|---|---|
| Work leverage | *"This reverses your July call. The reason you gave then was Y, and nobody addressed it."* |
| Frontier R&D | *"You tried this optical approach in March. It failed on brightness."* |
| Learning | *"You have been confused by this exact concept twice before."* |
| Ambient presence | — **not a goal.** It is the *delivery channel* for the three above |

**Four goals collapse into one organ plus one channel.** That is dramatically smaller than the
twelve-specialist roster in §3, and it is the part of this architecture that already half-exists:
`agent/consolidator.py` → `life_state_feed.jsonl` → `agent/life_state_monitor.py`.

**It also does not require the trained adapter** — it runs on the KB, the consolidator and
retrieval, all Stage 2/3 machinery already built. Which is why §1.1 point 1's *"trained, not
injected"* is now recorded as a genuinely **open question** rather than a settled deliverable. See
`stage_5_specialists/ROADMAP.md`.

**The deadlock this was found in (fixed 2026-09-06, KB 531/532).** The organ had surfaced 3 insights
ever, all on 2026-06-18, then went silent — because `Consolidator` ran only inside `Mind`'s
heartbeat, `Mind` boots only on `--ask`, and `--ask` had not been used in 35 days. The feed froze,
the daemon fail-closed, JARVIS had nothing proactive to say, and so there was no reason to open
`--ask`. **The capability that justifies the system was starved by not using the system.** Broken by
`scripts/consolidate.py` + a `Stop` hook, driving the same consolidator from the capture stream that
is written every turn; `Mind`'s heartbeat is untouched and still feeds the same organ.

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
- **Privacy — CORRECTED 2026-09-06, this line was false for months.** It previously read *"only the final prompt (query + 5 retrieved chunks) leaves the local machine."* An external audit checked it against the code and it was not true. What actually leaves on every real `--ask` call is the query, the retrieved chunks, **and the boot inhale** — up to ~4.3 KB composed by `brain/context_injector.py`, of which ~2.5 KB is the cognitive profile and ~2.4 KB is the cross-chat activity digest. `boot.py` puts that in the system prompt; `mind.py` sends it to OpenRouter.
  - **This is deliberate and it is the product.** A JARVIS that does not know its owner is a worse ChatGPT. The user's own self-assessments, cognitive patterns and working style are theirs to send, and sending them is the point — measured 2026-09-06, the shipped slice then contained zero third-party names. **Changed 2026-09-28 by the user's decision ("in context only"):** after JARVIS could not say who their girlfriend was, `personal_life.md` became an inhale provider and the profile stopped redacting people, so the people in the user's life now reach the provider as context. They are still redacted from every training artifact (`third_parties.py` at blend/SFT time).
  - **The line that IS enforced** is not personal/impersonal but *yours to send / not yours to send*: `brain/outbound_policy.py` strips employer and client identifiers from every provider's output before it leaves, and reports what it removed via `InhaleResult.redacted`. Terms derive from `client_work/` directory names, so a new client project is covered without editing code. That is an employment and contract boundary, the same one `client_work/` already draws — not a privacy preference.
  - **Why the guarantee rotted:** it existed only as prose, with no place in the code that could enforce or violate it, while `context_injector.py` carried a *passing* test asserting the profile reaches the prompt. Both artifacts looked true for months. The enforcement point now exists and `outbound_policy.py`'s T1 canary fails if a client identifier survives — the guarantee is testable rather than merely written. Same failure class as KB 521/527.
- Local and never sent: the knowledge base as a file, raw research papers, embeddings and `client_work/`. (`personal_life.md` was on this list until 2026-09-28; its body is now sent as context, see above.)

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

#### ⚠️ Cold-wake vs. §1.1's ambient presence — the conflict, and the resolution

"Cold-wake only" and *"can really live with me"* are in **direct contradiction**, and the gap is not
marginal. Stated here rather than left implicit, because the two claims previously sat in different
sections and were never read against each other:

| Mode | Cost | vs. Year-1 envelope (₹21.6K–50.3K) |
|---|---|---|
| Cold-wake, 15 sessions/mo | ₹1,365/mo ≈ **₹16K/yr** | within budget |
| Agentic wake-ups, ~10/day (§3.5) | ₹4.5K–9K/mo ≈ **₹54K–108K/yr** | already 1–2× over |
| Continuous 4× A5000, 24/7 | ₹91/hr × 8,760 ≈ **₹8.0 lakh/yr** | **16–38× over** |

**Ambient presence cannot be delivered by a single-tier architecture at any acceptable cost.** And
Kimi K2.6 at 1T params (INT4 ≈ 200–400 GB) does not run on a handset — **the phone is a client, not
a host.** Anyone planning on-device inference of the base model is planning something impossible.

**RESOLUTION — tiered presence.** Always-on and expensive-reasoning are separated so that only the
cheap tier never sleeps:

| Tier | Where | Cost | What it does | Sleeps? |
|---|---|---|---|---|
| **0** | Device (phone + laptop CPU) | **₹0** | Wake word, VAD, small-Whisper ASR, camera frame gating | **Never** |
| **1** | Device | ~₹0 | Intent routing + trivial queries answered locally. The ModernBERT-Large router already specified for the Orchestrator (§3, row 1) is the existing primitive — it was scoped CPU-side for exactly this reason | Never |
| **2** | RunPod cold-wake | ₹91/hr | Kimi K2.6 + adapter. Woken **only** on intent Tier 1 cannot serve | Aggressively |

This preserves the cold-wake economics of the table above *while* delivering continuous presence,
and it is how the Iron Man metaphor actually decomposes: the house always hears you; the heavy
reasoning happens elsewhere and only when summoned. Build targets live at
`stage_6_integration/ROADMAP.md` §6.10.

**Why Kimi K2.6 over alternatives:**
- vs. DeepSeek V4-Pro (1.6T/49B-active): smaller, fits 4×H100 INT4 instead of needing 8×H100. Same MIT license. ~30% cheaper inference.
- vs. self-hosted Llama 4 (400B/17B-active): loses to Kimi K2.6 on SWE-Bench Pro and agentic tasks by 8-15 points.
- vs. frontier APIs (Opus 4.7 / GPT-5.5): frontier APIs cost ~Rs 11L/month at the same usage AND log queries to third parties. Frontier is the **user-invoked escape valve only**, never the default route.

**Frontier escape valve:** Opus 4.7 / GPT-5.5 / Gemini 3.1 Pro are tools the user explicitly hands off to (like calling Wolfram Alpha) for one-off hard problems. Implementation: explicit `/escape-valve` command, never automatic fallback. Budget controlled per session.

---

## 3. THE "MODEL OF MODELS" ROSTER (1 MoE Base + 12 QLoRA Adapters)

**Architecture:** all 12 specialists ship as **QLoRA adapters (~150-500 MB each)** on top of the **shared Kimi K2.6 base**. The Orchestrator loads ONE adapter at a time onto the always-resident base; adapter swap is ~2-5 seconds vs. 10-20s for separate dense model loads. This is the 2026-correct recipe per DeepSeek V4 / Kimi K2.6 / GLM-5.1 distillation patterns and On-Policy Distillation research (arxiv 2602.12125): merged-adapter pattern beats separate dense fine-tunes at ~80% lower training cost.

**The moat is personalization, not parameter count.** Each adapter's value comes from being trained on the user's private corpus — code, KB entries, trade journal, research notes, error logs — not from beating Opus 4.7 zero-shot on MMLU. See KB Decision tagged `specialists, personalization, moat`.

> **⚠️ THE WHOLE ROSTER IS NOW AN OPEN QUESTION (2026-09-06).** §1.2 established that all four
> §1.1 goals reduce to **one organ** — unprompted surfacing over the user's own history — which
> needs **no adapter at all**, let alone twelve. Nothing below has a demand signal except Engineer
> (real day-to-day use) and possibly Analyst; ten of the twelve have been ⏸️ Deferred since
> 2026-08-10 and none has moved since.
>
> Read this section as **architecture that would be correct IF a specialist were justified**, not as
> a build plan. The prior question — whether *any* trained adapter beats the already-built retrieval
> and surfacing path — is unanswered, and answering it is cheaper than training anything. Do not
> cite roster completeness as a reason to build.

**TWO SEPARATE MOATS (Decision 2026-07-18, REVISED — corrected here 2026-08-10 after this doc briefly re-derived and contradicted it):**
1. **Domain genius** = seed model + PUBLIC corpus (MedGemma, IEEE standards, PubChem, DeepSeekMath-V2, etc. — the Adapter Seed column below). Needs **zero personal data** — a specialist can be genuinely competent from public distillation alone, any time.
2. **Personalization** = the Orchestrator's context layer (`cognitive_profile.md`, KB, decision history) — a separate, continuously-growing, ₹0 layer that makes the whole system feel personal even for specialists that never saw private data during training.

**This means personal-corpus availability is NOT a build gate.** It briefly became one in this doc (see the reverted table below) — that was the exact "mark specialists provisional until personal corpus exists" premise 2026-07-18 already retracted as wrong. The correct gate is **demand signal** (5.5.2's existing discipline: what justifies training the NEXT adapter, vs. premature roster completionism), not data availability. Personal data, when it happens to be rich (Engineer, plausibly Analyst), is a **bonus layer on top of** domain genius — not a prerequisite for a specialist to exist.

| # | Codename | Domain | Adapter Seed (Public Specialist to Distill From) | Personalization Corpus (User's Private Data) | Build Priority (demand-gated, not corpus-gated — 2026-08-10) |
|---|----------|--------|------------------------------------------------|----------------------------------------------|------------------------------------------|
| 1 | **The Orchestrator** | Intent routing, planning, delegation | Kimi K2.6 base + ModernBERT-Large router classifier (separate, CPU-side) | Past routing decisions + user's escape-valve invocations + chat-history attribution | ⏸️ Deferred — role splits in two: routing/delegation intelligence has no signal with only 1 specialist (degenerate 1-choice problem); its personalization half is already served by the free `cognitive_profile.md` context-injection per the two-moats split above, so there's nothing left to train here specifically |
| 2 | **The Engineer** | Software architecture, pipelines, algorithms (code + DE) | Qwen3-Coder-Next 80B/3B-active distilled in | `jarvis_core/` source, KB entries, chat-history with Claude/Antigravity, DE corpus, past error logs | 🟢 **Active** — real day-to-day demand (this build + client DE work), corpus assembled (Stage 5.2.2); rich personal data is a bonus on top of the demand case, not the reason it's first |
| 3 | **The Scientist** | Physics, optics, ArXiv papers, LaTeX math | DeepSeekMath-V2 distilled in for math reasoning | User's hologram-project notes, optics/photonics papers read, /research outputs | ⏸️ Deferred — no demand signal evidenced yet; buildable any time on public ArXiv/math corpus alone if that changes, personal hologram notes are a bonus if/when that project resumes |
| 4 | **The Doctor** | Medical research, biology, pharmacology | MedGemma 1.5 distilled in (~91 MedQA) | Trusted medical literature + (optionally) user's own health history | ⏸️ Deferred — no demand signal; separately, feeding it personal health history is the user's consent call whenever this is revisited, not a default |
| 5 | **The Operator** | Robotics, hardware control, simulation | OpenVLA + Holo3-35B-A3B distilled in for agentic computer-use | User's CAD files, ROS configs, past simulation outputs | ⏸️ Deferred — no demand signal evidenced |
| 6 | **The Electrician** | Circuit design, EM theory, signal processing, PCB/antenna | Kimi K2.6 base + LoRA on IEEE corpus | User's circuit designs, simulation logs, datasheets read | ⏸️ Deferred — no demand signal evidenced |
| 7 | **The Mechanic** | CAD, FEA, thermal/structural analysis, materials science | Kimi K2.6 base + LoRA on engineering handbooks + MatSciBERT-distilled signals | User's CAD library, material specs, FEA results, hologram structural notes | ⏸️ Deferred — no demand signal evidenced |
| 8 | **The Chemist** | Material properties, reactions, nanotechnology, metallurgy | Kimi K2.6 base + LoRA on PubChem + materials DBs | User's metamaterials research, photonics-relevant chemistry notes | ⏸️ Deferred — no demand signal evidenced |
| 9 | **The Strategist** | Patent analysis, IP landscape, competitive research | SaulLM-141B distilled in for legal reasoning | User's IP filings, prior-art searches, competitive notes | ⏸️ Deferred — no demand signal evidenced |
| 10 | **The Analyst** | Financial modeling, market analysis, BI (the Financier) | Kimi K2.6 base + Qwen 3-235B reasoning + LoRA on Indian markets | Groww trade history, NSE bulk-deals, trade rationale journal, risk profile | 🟡 **Plausible** — real demand signal (active personal-finance management); buildable on public Indian-markets distillation regardless, trade-journal corpus is a bonus layer worth confirming but not a prerequisite |
| 11 | **The Guardian** | Cybersecurity, vulnerability analysis, threat modeling | Qwen3-Coder-Next + LoRA on security advisories | User's audit logs, past vuln findings, threat model docs | ⏸️ Deferred, re-check first if a 3rd slot opens — DE client work increasingly touches access/security questions, so demand may materialize here before the rest |
| 12 | **The Interface** | Voice input, vision processing, multimodal I/O | Whisper Large-v3 (ASR), Kokoro-82M (TTS), Qwen2.5-VL-7B (vision) — separate models, NOT adapters on Kimi | User's voice recordings (consented), screen/CAD captures | Stage 6 concern, not a Stage-5 QLoRA adapter — doesn't compete for the same training budget at all |

**Personal-data capture, corrected:** client-VDI-sourced work (e.g. BUPA client environments, protected by DLP) reaches the corpus via the user manually distilling it into chat afterward — this is not a permanent unsolved gap, it's an already-working, already-used channel (see the BUPA — Region Migration lessons capture, `Data_Engineering_Lessons.md`). The open engineering question is what happens *downstream* of that manual capture — structuring, indexing, and (for Engineer/Analyst-tier specialists) training-time embedding of what's provided — not the capture step itself. See the Memory-layer structured-index plan (Decision 2026-08-10) for the downstream piece.


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

Specialists are not just models. The valuable ones are **always-on agentic systems** layered on top of the model. The model is one piece; the cron + ingestion + trigger + cold-wake pipeline is the bigger engineering project. Of the two worked examples below, Analyst/Financier is the near-term-relevant one (§3's Build Priority: 🟡 Plausible, real demand signal today) — the hologram R&D pattern for Scientist/Operator is preserved as valid future architecture, buildable any time on public corpus per the two-moats split, but has no demand signal driving it yet (§3, Decision 2026-08-10).

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

**Superseded as a blind sequence by Decision 2026-08-10 (see §3's Near-Term Status column) — this table still answers "which is cheapest," but §3 now answers "which has a real corpus to train on," and §3 is the gate that actually applies.** Kept here unedited as the cost reference for whenever each row's status flips to Active.

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

**Real near-term ticket, per the demand-signal gate (not a corpus gate — see §3's two-moats correction): Engineer alone (₹1,480-2,960), then Analyst once a real build decision is made (+₹1,480-2,590). Everything else waits for a demand signal, not for personal data to materialize — any of rows 3-9/11 could be built on public-corpus domain genius alone whenever there's an actual reason to.**

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

> **⚠️ THIS FILE OWNS ARCHITECTURE, NOT PROGRESS.** Corrected 2026-09-03. Until that date this
> section read *"Current Position: Stage 2, Sub-phase 2.5"* — four months and three stages stale,
> because nothing re-checks a status sentence when the status changes. An external audit
> (GPT 5.6 Terra, 2026-09-03) tripped on exactly this and reported a wrong project state.
>
> **The single source of truth for stage status is
> [`js-learning/JARVIS_MASTER_ROADMAP.md`](../../js-learning/JARVIS_MASTER_ROADMAP.md)** and the
> per-stage `ROADMAP.md` files under `js-learning/stage_*/`. The table below is a summary that will
> drift again; when it disagrees with the roadmap, **the roadmap wins.** Sections 1–6 above are
> architecture and remain current — they do not carry status.

| Phase | Status | What Gets Built |
|-------|--------|----------------|
| **1 (Systems Python)** | ✅ Sufficient | Async, generators, context managers, object model (1.4/1.5 deliberately deferred) |
| **2 (Memory Layer)** | ✅ Complete — closed 2026-05-03 | Embeddings, ChromaDB, chunking, hybrid search, cross-encoder rerank, KB compaction |
| **3 (Agent Framework)** | ✅ Complete | Tool ABC + registry, planner (DAG/Kahn), ReAct loop, MemGPT paging. Built from scratch in `jarvis_core/agent/` per Decision 2026-05-13 |
| **4 (Orchestration)** | ✅ Shipped scope closed 2026-07-27 | Router (84% frozen gate), model-pool failover, aggregator, epistemic control. Final Boss 8/8 PASS offline, ₹0. 4.6 GraphRAG is required but not built: it was promoted 2026-09-08 because proactive surfacing needs multi-hop retrieval over distant facts. |
| **5 (Specialists)** | ⬅️ **CURRENT — not started** | Engineer-first QLoRA adapter on a shared Kimi K2.6 base. Next task: 5.1 Fine-Tuning Basics on RunPod |
| **6 (Integration)** | Scoped, not started | Voice, vision, unified API, client shells (6.9), ambient presence tier (6.10). 6.1–6.6 self-flagged as stale pre-Stage-3 drafts |

**Current Position:** Stage 5 — Domain Specialists. Stages 1–4 complete. Stage 5 not yet started;
the gate is deliberate (corpus richness before RunPod spend), not a blocker.

---

## APPENDIX: Fine-Tuning Failure Diagnostic Map

Stored in `knowledge_base.jsonl` (tagged: `fine_tuning, diagnostic_map`). Maps training failure symptoms to required math prerequisites. See entry for 7 symptom→study mappings.
