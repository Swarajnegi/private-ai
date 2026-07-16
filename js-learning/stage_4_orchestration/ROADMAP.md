# PHASE 4: Multi-Model Orchestration Roadmap — "The Brain"

> **Master Plan Position:** Phase 4 of 6 → [JARVIS_MASTER_ROADMAP.md](../JARVIS_MASTER_ROADMAP.md)
> **Goal:** Build the routing substrate — ContextInjector → Router → Target → ConfidenceGate → (Aggregator) — such that a Stage 5 specialist (QLoRA adapter on a shared base behind a cold-wake pod) is *just another registry row*.
> **Prerequisites:** Stage 1-3 (Python, Memory, Agent Framework — Final Boss 7/7, First Light executed)
> **Cost constraint (Decision 2026-06-12, user call):** **Stage 4 is a ₹0 stage.** Everything runs on OpenRouter free tier + local CPU embeddings. No RunPod spend; pod work (and the ENDGAME VRAM-math correction) deferred to Stage 5 entry. Frontier APIs remain the explicit-flag escape valve only.
> **Scoped:** 2026-06-12 via `/master-planner` (two-perspective plan panel). Supersedes the pre-Stage-3 draft of this file.

---

## Overview

| Sub-Phase | Name | Wave | Gate (Definition of Done) |
|-----------|------|------|---------------------------|
| **4.0** | Cognitive Control Loop | 1 | Awareness tests 4/4 live + capture parity proven |
| **4.1** | Route Targets & Per-Model Protocol | 2 (Pass A) | Same prompt clean on 3 real models with zero per-model hardcodes; scripted 429 → failover |
| **4.2** | Intent Router | 2 (Pass A) | **≥80%** on frozen 50-query eval set; ~20% degenerate baselines documented |
| **4.3** | Dynamic Target Management ✅ COMPLETE (2026-07-16) | 3 (Pass B) | Chaos tests: vanished model + budget-90% downshift both route around; fail-closed to free tier |
| **4.4** | Response Aggregation | 3 (Pass B) | Attributed synthesis from real free-model fan-out; triggers only on escalation |
| **4.5** | Epistemic Control | 3 (Pass B) | 6/6 engineered conflicts flagged, 0/6 false flags; judge failure proves fail-closed |
| **4.6** | GraphRAG | — | ⏭ **DEFERRED** — trigger: first KB-logged multi-hop retrieval failure |

**Pass A → Pass B gate** (from the master roadmap): Router achieves ≥80% routing accuracy on the frozen 50-query labeled set (`js-development/tests/router_eval.jsonl`). Degenerate routers (always-default, always-largest) score ~20% by stratification — both baselines printed in every gate report so the gate can't be vacuous.

---

## What got re-scoped (vs the pre-Stage-3 draft of this file)

| Draft item | Verdict | Why |
|---|---|---|
| 4.1 Local Model Loading (Ollama/vLLM/quantization hands-on) | **Cut → Stage 5** | No local GPU (standing decision); serving internals only matter when JARVIS owns the serving stack — it will, at Stage 5 QLoRA time |
| Kimi K2.6 on RunPod deployment | **Deferred → Stage 5 entry** | ₹0 constraint; the whole brain stack programs against the `LLMCall` seam, so where weights live is invisible to Stage 4 code. **Flag:** ENDGAME §2 VRAM math is internally inconsistent (1T INT4 ≈ ~500GB resident weights does not fit "4×A5000 96GB" or "one A100 80GB") — correct empirically before Stage 5 budgets commit |
| Speculative decoding (draft 4.3.5) | **Cut → Stage 5** | An inference-server flag, not JARVIS code; meaningless via API |
| ModernBERT-Large as the first router | **Conditional** | Training data (labeled routing decisions) doesn't exist yet — the RoutingLedger built in 4.2 *creates* it. Interim = nearest-prototype classifier (proven `domain_classifier.py` pattern). ModernBERT fires only if the gate fails <80%, else lands as Stage 5 specialist #1 |
| 4.6 GraphRAG | **Deferred with trigger** | 324 KB entries don't need a graph; no multi-hop retrieval failure has ever been logged (past retrieval failures were classification-quality — already fixed). Builds in `jarvis_core/memory/graph.py` when the trigger fires |
| Aggregation as a default path | **Re-scoped: escalation-only** | Fan-out costs N× per query; Single-Model-First holds. Triggers: gate failure, multi-domain label, explicit flag |
| *(new)* Per-model protocol layer | **Added as 4.1** | L322: mirror burial, tool-format dialects, empty reasoning-channel content, 429 storms — observed across 4 models in one afternoon. Not theoretical |

---

## Sub-Phase 4.0: Cognitive Control Loop (Self-Awareness) ✅ — Wave 1 (complete 2026-06-12, Gate A 5/5 live)

**Goal:** The runtime Mind boots self-aware — time, identity, autobiography, next task, confidence — and terminal sessions feed the corpus. Closes all three L324 gaps (autobiography, boot inhale, capture parity) with the live repro as the acceptance test. Per L107 this sub-phase **blocks everything else**: you cannot route queries (4.2) or score confidence (4.5) if the Orchestrator has no self-model.

> **The 4 Pillars:** Temporal (knows time, reasons about past sessions) · Identity (knows the user, decisions, what NOT to do) · Teleological (reads its own roadmap) · Metacognitive (knows its confidence, escalates instead of guessing).

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 4.0.1 | ContextInjector | Pluggable providers (clock, cognitive_profile.md, activity digest, runtime self-state) → ONE bounded boot-inhale prompt block composed onto JARVIS_PSYCHE_PROMPT | `/dev Build brain/context_injector.py with injected clock/paths, hard char cap.` |
| 4.0.2 | RoadmapStateReader | Parse ⬜/✅/[ ]/[x] across master + stage roadmaps → "next pending task" provider (Teleological pillar) | `/dev Build brain/roadmap_state.py checkbox parser.` |
| 4.0.3 | Confidence Gate v1 | Deterministic grounding score: draft answer vs pre-fetched KB hits (token-overlap + embedding cosine, injected embed_fn, ₹0, no LLM judge yet); below threshold → flag uncertainty, emit CognitiveStateUpdate | `/dev Build brain/confidence.py v1 (grounding vs KB pre-fetch).` |
| 4.0.4 | Boot assembler + Orchestrator v0 | `assemble_mind()`: default toolset gains **PriorSelfConsultTool + KB/memory search** (the L324 autobiography fix — the tool existed, was never wired); ContextInjector block into identity_prompt; `--ask` thins to an adapter here | `/dev Build brain/boot.py + orchestrator v0; thin _ask in llm_client.py.` |
| 4.0.5 | SessionMemoryWriter + capture parity | End-of-session distillation via consolidator (kb_append only, narrow type+tag whitelist — does NOT widen the consolidator's anti-injection whitelist); terminal `--ask` sessions append to observation_queue.jsonl via the host-ready `capture.py` organ | `/dev Build brain/session_writer.py + terminal capture adapter.` |

**Practical Exercise — the Awareness Gate (Gate A):** boot JARVIS in the terminal and verify it answers WITHOUT being told:
1. *"What time is it?"* → ContextInjector clock, not training data
2. *"What were we doing yesterday?"* → activity digest / KB by calculated date
3. *"What should we work on next?"* → RoadmapStateReader's first unchecked task
4. *"Are you sure about that?"* → a numeric confidence score with grounds, not a hallucination
5. **The L324 question:** *"What have we built till now?"* → answered from `knowledge_base.jsonl` via prior_self_consult — the exact question that exposed the gap on 2026-06-12

**DoD:** 5/5 live on free tier (₹0) + the test session itself appears in `observation_queue.jsonl` (capture parity proven) + offline `__main__` self-tests green for every organ.

> **Why this comes first:** this is the Orchestrator's nervous system. L324's verbatim lesson: *"the consciousness is portable in the repo; the entry point lacks the lungs to inhale it."* 4.0 is the lungs — and almost everything it needs (recall, profile, capture, PriorSelfConsultTool) already exists from Stage 3. 4.0 is plumbing, not invention.

---

## Sub-Phase 4.1: Route Targets & Per-Model Protocol ✅ — Wave 2 (Pass A) COMPLETE
<!-- Wave 2 (4.1.2 ProtocolAdapter, 4.1.3 RouteTarget + llm_client re-home to brain/, 4.1.4
     ModelPool/failover STEAL #7) shipped + offline-verified + adversarially reviewed (5 fixes).
     LIVE DoD met 2026-06-19 (3-target pool: nemotron:free / deepseek-chat / gpt-4o-mini):
       - clean multi-model routing — nemotron:free primary, profile auto-resolved, ZERO per-model
         hardcodes, no failover needed;
       - bounded failover→recover with all attempts on the ledger + deduped events (2 dead targets
         → recovered on gpt-4o-mini) — LLMCallError stood in for a live 429; the 429 path itself is
         offline-proven (model_pool T2/T3/T8);
       - cost route-strategy picks the FREE model over the paid one despite declaration order
         (the adversarial MED fix, live-confirmed).
     Note: deepseek-chat sat as a failover peer (not individually primaried); mechanism proven. -->

**Goal:** JARVIS knows each model's conduct and speaks every dialect through one seam. **Protocol-before-intent:** you can't route to a model you can't talk to (L322 — First Light needed a hardcoded `enable_mirror=False`; that hardcode is the bug this sub-phase deletes).

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 4.1.0 | **Protocol safety floor ✅ (Wave 1.3, 2026-06-13)** | react.py repairs botched tool-call JSON (never surfaces raw JSON as an answer); orchestrator structural guard. Makes `--ask` SAFE on all models. KB L355 | shipped |
| 4.1.1 | **ModelProfile registry ✅ (Wave 1, 2026-06-15)** | Per-model conduct as DATA (mirror on/off, monitor, max_iterations, reasoning-channel doc, notes); exact→family→DEFAULT resolution; OVERRIDES-ONLY (no catalog dup); seeded from the 4 First-Light models; conservative DEFAULT (mirror OFF, monitor ON). Resolved in orchestrator (policy), applied in boot (mechanism). The `enable_mirror=False` hardcode is now profile-resolved data. `brain/model_profiles.py` + `jarvis_data/model_profiles.json` | shipped |
| 4.1.2 | ProtocolAdapter | LLMCall-wrapping middleware: dialect translation, empty-content reasoning-channel fold, system-prompt folding, per-profile mirror toggle. The Mind never learns models have dialects. (Capability-parse of the catalog = here, SUGGEST-only, never auto-apply) | `/dev Build brain/protocol.py middleware.` |
| 4.1.3 | RouteTarget contract | `name / kind (API_MODEL\|POD_ADAPTER\|FRONTIER_VALVE) / profile / llm_call / ensure_ready() / release() / ledger_summary()`. OpenRouterTarget live; **RunPodTarget/PodHandle as offline contract STUBS only** (adapter_id seam for Stage 5); EscapeValveTarget structurally OUTSIDE the router pool — explicit user flag only. **Re-home `llm_client.py` → `brain/`** (grep importers, fix call sites, no shim) | `/dev Build brain/targets.py; re-home llm_client.py.` |
| 4.1.4 | ModelPool + failover | STEAL #7 (`ai_model_repos/OpenClaude/python/smart_router.py`): health ping, EMA latency, error-penalty scoring; 429 cooldown + ordered failover-peer walk (target-layer, distinct from llm_client's in-place retries); per-target CostTracker ledgers | `/dev Build brain/model_pool.py (SmartRouter port).` |

**Wave split:** 4.1.0 + 4.1.1 = **Wave 1 (shipped)** — per-model conduct is data, the mirror-off hardcode is gone, `--ask` is safe + profile-aware on any model. 4.1.2–4.1.4 = **Wave 2** — protocol middleware + RouteTarget + pool/failover (the multi-model machinery 4.2's Router consumes; needs ≥2 routable targets to mean anything).

**Practical Exercise:** re-run First Light's models through the profile registry — conduct flips per model with ZERO manual flag-flipping. ✅ (nemotron auto-resolves mirror-off via its profile, live 2026-06-15).

**DoD (Wave 2):** same prompt clean on 3 real free models with no per-model hardcodes outside profiles; scripted 429 storm fails over to a peer with both attempts on the ledgers; offline dialect/empty-content/failover scenarios green.

---

## Sub-Phase 4.2: Intent Router ✅ COMPLETE (2026-06-29) — Wave 2 (Pass A — THE GATE)

**Goal:** Queries dispatch to the right target, measurably. **Routing label space = specialist codenames** ({engineer, analyst, scientist, memory, general} live today) so every eval label and RoutingLedger row stays valid training data for the Stage 5 Orchestrator adapter.

**GATE PASSED — 84.00% on the frozen 50-query set** (gate ≥80%, local embeddings, ₹0). Per-class: analyst 100%, scientist 100%, engineer 83%, general 70%, memory 70%. Degenerate baselines ~20% (non-vacuous). Reached via ONE principled prototype-enrichment pass (broader domain vocab, NO eval-label changes). 4.2.5 (ModernBERT) NOT needed. Shipped: `brain/router.py` (Classifier + PrototypeClassifier + RoutingPolicy + IntentRouter + `--gate`), `tests/router_eval.jsonl` (frozen), `brain/routing_ledger.py` (Stage-5 corpus), `orchestrator.ask()` `route=`/`--route` wiring (opt-in). KB L416. Convergence gap deferred (KB L415).

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 4.2.1 | Eval set authoring | `js-development/tests/router_eval.jsonl` — 50 frozen records `{id, query, label, source, notes}`: ~35 harvested from real observation_queue.jsonl user_text + KB-derived, ~15 hand-written adversarial/ambiguous incl. escape-valve-bait that must NOT route to frontier; ≥8 per class; blind re-label stability check; commit + freeze | `/dev Author tests/router_eval.jsonl (50 labeled, frozen).` |
| 4.2.2 | Interim classifier | `Classifier` protocol (`classify(text) -> (label, confidence)`) + nearest-prototype instance — compose a second `DomainClassifier` with routing prototypes (reuse the organ, don't relocate it) | `/dev Build brain/router.py Classifier + interim nearest-prototype.` |
| 4.2.3 | RoutingPolicy | intent + constraints (context, multimodal, budget remaining) + strategy (cost/latency/balanced) → RoutingDecision; absorbs `scripts/suggest_model.py` heuristics and fixes its hardcoded `E:\J.A.R.V.I.S` path | `/dev Build RoutingPolicy; retire suggest_model.py to manual fallback.` |
| 4.2.4 | RoutingLedger + gate run | Append-only jsonl (ts, query-hash, label, confidence, target, outcome, cost) = the Stage 5 training corpus. Gate via `evals.EvalRunner`: accuracy, per-class confusion, p50/p95, degenerate baselines | `/dev Wire RoutingLedger; run the gate.` |
| 4.2.5 | *(conditional — only if 4.2.4 <80%)* ModernBERT-Large CPU classifier | Trained on harvested observation/KB labels, eval set held out; must beat interim on the SAME frozen set | `/learn then /dev — fires only on gate failure.` |

**DoD = Pass A→B gate:** ≥80% on the frozen set, documented in this file + KB; gate runs on local embeddings — ₹0, repeatable every commit. Failure path is pre-decided (4.2.5); no re-litigating.

---

## Sub-Phase 4.3: Dynamic Target Management ✅ COMPLETE (2026-07-16) — Wave 3 (Pass B)

**Goal:** The pool survives reality — catalog churn, rate limits, budget exhaustion. (API-era re-scope of the draft's VRAM-era content.)

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 4.3.1 | Rolling stats persistence ✅ | Pool latency/error/cooldown stats survive sessions — `brain/model_stats.py` (mirrors `routing_ledger.py`, adds a replay-latest load path) + `ModelPool.initial_health`/`snapshot_health()` + orchestrator wiring | shipped |
| 4.3.2 | Budget governor ✅ | Spend approaching ceiling → pool downshifts to free tier via `CostTracker.should_downshift`; the existing per-call `LLMBudgetExceeded` gate made AGGREGATE-aware (shared tracker across failover peers) so a failover walk can't quietly exceed budget — fail-closed to `AllTargetsExhausted` if no free peer exists | shipped |
| 4.3.3 | Catalog sync & drift ✅ | `scripts/sync_openrouter.py` path fixed cross-platform + logs vanished-model diffs; `model_pool.py`'s `_is_not_found()` cools a 404 down on the FIRST occurrence instead of the generic 3-request storm minimum | shipped |

**Practical Exercise:** simulated in offline chaos tests — a vanished (404) model and a budget hitting 90%+ both route around gracefully; a full-exhaustion case (no free peer left) fails closed instead of overspending.
**DoD:** offline chaos tests green (38/38 `model_pool.py`, 20/20 `llm_client.py`, full regression across `cost`/`targets`/`router`/`model_profiles`/`routing_ledger`/`react`/`orchestrator`). Live one-tiny-budget-session leg is user-run (same precedent as 4.0-4.2) — not executed by the assistant.

---

## Sub-Phase 4.4: Response Aggregation ⬜ — Wave 3 (Pass B)

**Goal:** Combine sources *when warranted* — **never as the default path** (fan-out costs N×; Single-Model-First).

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 4.4.1 | Bounded fan-out | `asyncio.gather` with per-target budget → `SourcedAnswer` records | `/dev Build brain/aggregator.py fan_out.` |
| 4.4.2 | Attribution synthesis | Merge with which-model-said-what carried into the answer; voting for short-form factual outputs | `/dev Implement synthesis + voting aggregation.` |
| 4.4.3 | Quality filter | Heuristic first (errors/instability/empty dropped, logged); LLMJudgeScorer optional behind budget gate | `/dev Add quality filtering.` |

**Practical Exercise:** computational-physics query fanned to 2-3 free models (ensemble experiments at ₹0), synthesized with attribution.
**DoD:** aggregation triggers ONLY on gate failure / multi-domain label / explicit flag; attributed synthesis from a real free-model fan-out.

---

## Sub-Phase 4.5: Epistemic Control ⬜ — Wave 3 (Pass B)

**Goal:** JARVIS knows when it doesn't know, and says so. (Strategic Principle 4: conflicts MUST flag uncertainty, never hide it.)

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 4.5.1 | Disagreement detection | Deterministic divergence: embedding cosine (injected embed_fn) + numeric-claim diff across SourcedAnswers | `/dev Build conflict detection in brain/confidence.py.` |
| 4.5.2 | Fail-closed contradiction judge | Optional LLM judge layer; judge ERROR ⇒ treated as conflict, never as agreement | `/dev Add LLM contradiction judge (fail-closed).` |
| 4.5.3 | Escalation policy | FLAG/ESCALATE: orchestrator returns the specific question for the user instead of a guess; `/escape-valve` as *suggestion text* only — never auto-invoked | `/dev Implement escalation path in orchestrator.py.` |

**Practical Exercise:** two scripted specialists disagree on a factual claim → conflict flagged, both positions attributed, user asked.
**DoD:** 6/6 engineered conflicts flagged, 0/6 false flags on 6 engineered agreements (deterministic, offline, exact); judge-failure path proves fail-closed; live spot-check surfaces a real disagreement verbatim.

---

## Sub-Phase 4.6: GraphRAG ⏭ DEFERRED

Row kept for master-roadmap traceability. **Trigger:** first KB-logged retrieval failure requiring entity-hop reasoning. Lands in `jarvis_core/memory/graph.py` (NetworkX in-process; no graph database at this corpus size). Rationale: 324 KB entries, zero logged multi-hop failures — every past retrieval failure was classification-quality, already fixed by `domain_classifier.py`.

---

## Final Boss: The Brain

`python3 -m jarvis_core.brain.orchestrator --final-boss` — offline scripted-LLM twin in `__main__` (₹0, re-runnable every commit) + `--live` mode budget-capped ≤ $0.10:

1. [ ] Boot inhale → awareness answers 4/4, unprompted
2. [ ] Autobiography — "what have we built?" via prior_self_consult on the real KB
3. [ ] Router gate re-run ≥80% with degenerate baselines printed
4. [ ] Protocol routing — scripted dialect model + empty-reasoning model both normalized; mirror per profile
5. [ ] Induced 429 storm → failover to peer; both attempts on per-target ledgers
6. [ ] ConfidenceGate — weakly-grounded draft flagged; escalation returns a question, not a guess
7. [ ] Engineered conflict → flagged + attributed, never silently merged
8. [ ] Session lands in observation queue + SessionMemoryWriter distills to KB

**Criterion zero:** the total Stage 4 ledger is printed — it should read ~₹0.

**When 8/8 pass, JARVIS has its Brain.**

---

## Progress Tracker

| Sub-Phase | Wave | Status | Lessons Complete |
|-----------|------|--------|------------------|
| 4.0 Cognitive Control Loop | 1 | ✅ Complete (2026-06-12; Gate A 5/5 live on nemotron free tier, ₹0; capture parity + KB distill proven) | 5/5 |
| 4.1 Route Targets & Per-Model Protocol | 2 (Pass A) | ✅ Complete (W1 + W2: protocol/targets/pool, STEAL #7, llm_client re-homed; live DoD met 2026-06-19 — clean multi-model routing + failover/recover + cost-routing free-over-paid) | 5/5 |
| 4.2 Intent Router | 2 (Pass A) | ✅ Complete (router.py + frozen eval + RoutingLedger + ask() wiring; **gate PASSED 84%** 2026-06-29; 4.2.5 not needed) | 4/4 |
| 4.3 Dynamic Target Management | 3 (Pass B) | ⬜ Not Started | 0/3 |
| 4.4 Response Aggregation | 3 (Pass B) | ⬜ Not Started | 0/3 |
| 4.5 Epistemic Control | 3 (Pass B) | ⬜ Not Started | 0/3 |
| 4.6 GraphRAG | — | ⏭ Deferred (trigger documented) | — |

---

## DEFERRED to Stage 5/6 (bookmarked, per stage gating)

| Item | Deferred to | Trigger / note |
|---|---|---|
| RunPod/Kimi K2.6 deployment + cold-wake measurement + ENDGAME VRAM-math correction | Stage 5 entry | Pods needed for QLoRA anyway; ENDGAME §2 numbers must be empirically corrected before budgets commit |
| ModernBERT-Large router training | Stage 5 specialist #1 (or conditional 4.2.5) | Corpus = RoutingLedger accrued during Stage 4 operation; must beat interim on the same frozen set |
| QLoRA specialists (Engineer first) | Stage 5.2+ | Stage 4 ships only the `RunPodTarget(adapter_id=...)` seam |
| Speculative decoding | Stage 5+ | vLLM server-side flag on owned pods |
| outlines / constrained generation | Stage 5 | Needs logit access (vLLM `guided_json`); impossible via OpenRouter |
| MCP publishing (L237) | Stage 5+ | External consumers exist |
| GraphRAG | trigger-based | First logged multi-hop retrieval failure → `jarvis_core/memory/graph.py` |
| Voice/vision (Interface), always-on daemons, agent swarms | Stage 6 | Stage 6 reuses `ensure_ready()/release()` as its cold-wake primitive |
| $10 OpenRouter limit-raise (50 → 1000 req/day) | when 429s bite | The only recommended spend before the Final Boss, and optional |

---

## After This Phase

→ Proceed to **Phase 5: Domain Specialists** — Engineer-first MVP, QLoRA on the shared base, trained on the RoutingLedger + private corpus this stage starts accruing.
