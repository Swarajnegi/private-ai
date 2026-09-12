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
| **4.4** | Response Aggregation ✅ COMPLETE (2026-07-20) | 3 (Pass B) | Attributed synthesis from real free-model fan-out; triggers only on escalation |
| **4.5** | Epistemic Control ✅ COMPLETE (2026-07-20) | 3 (Pass B) | 6/6 engineered conflicts flagged, 0/6 false flags; judge failure proves fail-closed |
| **4.6** | GraphRAG | — | 🟡 **REQUIRED, NOT BUILT** — promoted 2026-09-08 because the proactive-surfacing moat needs multi-hop retrieval, not only a larger context ledger |

**Pass A → Pass B gate** (from the master roadmap): Router achieves ≥80% routing accuracy on the frozen 50-query labeled set (`js-development/tests/router_eval.jsonl`). Degenerate routers (always-default, always-largest) score ~20% by stratification — both baselines printed in every gate report so the gate can't be vacuous.

---

## What got re-scoped (vs the pre-Stage-3 draft of this file)

| Draft item | Verdict | Why |
|---|---|---|
| 4.1 Local Model Loading (Ollama/vLLM/quantization hands-on) | **Cut → Stage 5** | No local GPU (standing decision); serving internals only matter when JARVIS owns the serving stack — it will, at Stage 5 QLoRA time |
| Kimi K2.6 on RunPod deployment | **Deferred → Stage 5 entry** | ₹0 constraint; the whole brain stack programs against the `LLMCall` seam, so where weights live is invisible to Stage 4 code. **Flag:** ENDGAME §2 VRAM math is internally inconsistent (1T INT4 ≈ ~500GB resident weights does not fit "4×A5000 96GB" or "one A100 80GB") — correct empirically before Stage 5 budgets commit |
| Speculative decoding (draft 4.3.5) | **Cut → Stage 5** | An inference-server flag, not JARVIS code; meaningless via API |
| ModernBERT-Large as the first router | **Conditional** | Training data (labeled routing decisions) doesn't exist yet — the RoutingLedger built in 4.2 *creates* it. Interim = nearest-prototype classifier (proven `domain_classifier.py` pattern). ModernBERT fires only if the gate fails <80%, else lands as Stage 5 specialist #1 |
| 4.6 GraphRAG | **Required follow-on** | The original incident trigger did not fire, but the architecture changed: an always-reachable Context Ledger makes stored facts reachable, while GraphRAG is what can connect distant facts when neither was named in a query. Builds in `jarvis_core/memory/graph.py` after the ledger foundation is proven. |
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

## Sub-Phase 4.4: Response Aggregation ✅ COMPLETE (2026-07-20) — Wave 3 (Pass B)
<!-- Built INTERLEAVED with 4.5 (architecture-review before implementation found
     4.4/4.5.1/4.5.2 share ONE contract, SourcedAnswer -- the roadmap's 4.5.1/4.5.2
     ("across SourcedAnswers") are structurally impossible without 4.4's fan-out
     existing first; they are a DIFFERENT organ from the single-answer reasoning.py
     gate that shipped ahead of sequence as "4.5 Wave 1"). Design = post-hoc
     escalation fan-out (the primary answer comes from the normal single-model
     spine unchanged; fan-out only fires on trigger, reusing the primary's already-
     gathered tool evidence) — NOT upfront N-parallel-Minds (N× full agent cost,
     violates the ₹0 stage constraint). -->

**Goal:** Combine sources *when warranted* — **never as the default path** (fan-out costs N×; Single-Model-First).

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 4.4.1 | Bounded fan-out ✅ | `SourcedAnswer` (frozen) + `fan_out()`: `asyncio.gather(..., return_exceptions=True)` over the pool's OTHER targets, capped at 3 peers — NEVER raises, a failed peer just reads `ok=False` while its sibling still returns. `brain/aggregator.py` | shipped |
| 4.4.2 | Attribution synthesis ✅ | ₹0 voting first (unanimous short-form answers need no LLM call); an injected synthesizer merges long-form survivors into ONE attributed answer, explicitly instructed to PRESERVE disagreement rather than average it away | shipped |
| 4.4.3 | Quality filter ✅ | Drops `ok=False`/degenerate (raw tool-call shape) sources before voting/synthesis, LOGS every drop (no silent truncation); 0 survivors → passthrough (primary untouched), 1 → single | shipped |

**Practical Exercise:** offline-scripted 2-peer fan-out (resistor-value question) exercises vote / synthesis / passthrough / single paths deterministically.
**DoD:** aggregation triggers ONLY on gate failure (ESCALATE verdict) / low route confidence / explicit `aggregate=True` flag — verified OFF by default even under the exact trigger condition (T46 regression guard); attributed synthesis from a real (offline-scripted) free-model fan-out (T47/T49). 18/18 `aggregator.py`, full `orchestrator.py` regression (91/91, see 4.5). Live free-model fan-out leg is user-run (same precedent as every prior Stage 4 sub-phase's live DoD leg).

---

## Sub-Phase 4.5: Epistemic Control ✅ COMPLETE (2026-07-20) — Wave 3 (Pass B)
<!-- The single-answer reasoning.py gate ("is THIS answer's own logic right?")
     shipped ahead of sequence as "4.5 Wave 1" -- a DIFFERENT organ from what
     this sub-phase builds ("do TWO models' answers to the SAME question
     actually contradict?"). detect_divergence (4.5.1) is deliberately NOT a
     logical-contradiction detector -- "yes" vs "no" on the same claim can embed
     as near-identical (embeddings blur negation) and carries no extractable
     number; that class is EXACTLY why ContradictionJudge (4.5.2, an LLM asked
     directly) exists as a second, separate layer on top. -->

**Goal:** JARVIS knows when it doesn't know, and says so. (Strategic Principle 4: conflicts MUST flag uncertainty, never hide it.)

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 4.5.1 | Disagreement detection ✅ | `detect_divergence()`: pairwise embedding cosine (injected embed_fn, min 0.60) + unit-normalized numeric-claim diff (shared-topic-gated: >=2 common content words before comparing any numbers) across SourcedAnswers. `<2 usable answers -> not measurable, diverged=False` (honest floor). `brain/confidence.py` | shipped |
| 4.5.2 | Fail-closed contradiction judge ✅ | `ContradictionJudge`: LLM judge over ONE divergence-flagged pair -> CONTRADICTION / COMPATIBLE / UNCHECKED. `resolve_conflict()` combines with 4.5.1: the judge may only DOWNGRADE a flagged divergence (COMPATIBLE clears it); CONTRADICTION **or an ERRORED/UNCHECKED judge** both leave the conflict STANDING — an audit that couldn't run is never read as agreement. `brain/reasoning.py` | shipped |
| 4.5.3 | Escalation policy ✅ | A confirmed conflict rewrites the answer into one that attributes both sources, names the specific unresolved claim, and offers `/escape-valve` as suggestion text ONLY (never auto-invoked, the standing escape-valve rule). `orchestrator.ask()` — new params `aggregate`/`aggregate_gate`/`synthesizer`/`contradiction_judge`/`contradiction_judge_llm`/`divergence_embed_fn`, new `AskResult` fields `conflict_detected`/`conflict_detail`/`escalation_question` | shipped |

**Practical Exercise:** offline-scripted 2-model resistor-value conflict (220 vs 330 ohms) — unjudged: fail-closed, conflict stands, attributed question returned (T48); scripted-COMPATIBLE judge: conflict clears, synthesis proceeds (T49).
**DoD:** frozen 12-fixture gate (`tests/divergence_eval.jsonl`) — **6/6 engineered conflicts flagged, 6/6 engineered agreements NOT flagged, exact** (deterministic, offline, ₹0). Judge-failure path proves fail-closed (T31: divergence + UNCHECKED judge → conflict still stands). Full regression: 18/18 `aggregator.py`, 20/20 `confidence.py`, 48/48 `reasoning.py`, 39/39 `model_pool.py` (new `peers()` seam), 91/91 `orchestrator.py` (11 new checks T46-T49b). Live spot-check surfacing a real disagreement is user-run (same precedent as every prior Stage 4 sub-phase's live DoD leg).

**Honest scope note:** the roadmap's literal "multi-domain label" trigger does not exist as a `RoutingDecision` field today (it carries one `label`, not several) — substituted with a low-route-confidence threshold (`_AGG_ROUTE_CONF = 0.35`, just above `router.ROUTE_THRESHOLD = 0.28`), documented in `orchestrator.py`. The unified `--final-boss` CLI entry point (8-leg Stage-4-wide harness) referenced in this file's own "Final Boss" section below does not exist yet — it is a Stage-4-CLOSING ritual spanning 4.0-4.6, not a 4.4/4.5-scoped task, and was correctly out of scope for this dev pass. `--awareness` (legs 1-2) and `router.py --gate` (leg 3) already exist as separate entry points; unifying all 8 legs under one `--final-boss` flag remains open. **UPDATE (2026-07-27): shipped** — see this file's own "Final Boss" section below, now 8/8 PASS offline.

---

## Sub-Phase 4.6: GraphRAG 🟡 REQUIRED, NOT BUILT

Row kept for master-roadmap traceability. **Trigger:** first KB-logged retrieval failure requiring entity-hop reasoning. Lands in `jarvis_core/memory/graph.py` (NetworkX in-process; no graph database at this corpus size). Rationale: 324 KB entries, zero logged multi-hop failures — every past retrieval failure was classification-quality, already fixed by `domain_classifier.py`.

---

## Final Boss: The Brain ✅ COMPLETE (2026-07-27, offline leg)

`python3 -m jarvis_core.brain.orchestrator --final-boss` — offline scripted-LLM twin, **8/8 PASS**, ₹0, re-runnable every commit (`orchestrator.py`'s `_final_boss_offline()`). Full 91/91 regression held after adding it; a deliberate leg-6 break was spot-checked to confirm the harness fails closed (7/8, non-zero exit) rather than false-passing.

1. [x] Boot inhale → awareness answers, unprompted — `providers_fired` includes `"Temporal"` on a scripted spine pass
2. [x] Autobiography — "what have we built?" via `prior_self_consult` on the (tempdir) KB
3. [x] Router gate re-run ≥80% with degenerate baselines printed — reuses `router._gate()` verbatim (84.00%, `always-general 20%` baseline)
4. [x] Protocol routing — `ProtocolAdapter`/`adapt()` fold-system dialect fixture + data-driven mirror resolution via `ProfileRegistry`. **Honest scope note:** "empty-reasoning model" (the other half of this leg's original wording) is already retried unconditionally in `llm_client`, not profile-gated — not re-tested here, same substitution style as 4.5's own honest-scope note
5. [x] Induced 429 storm → failover to peer; both attempts on per-target ledgers — mirrors `model_pool.py`'s own T3 fixture (cooldown trips immediately, `select()` picks the healthy peer)
6. [x] ConfidenceGate — weakly-grounded draft (empty evidence) flagged ESCALATE, fail-closed. **Honest scope note:** the "escalation returns a question" half of this leg's wording is only actually wired for the cross-model conflict path (leg 7's `escalation_question` field) — single-answer weak-grounding stops at the verdict stamp, it does not itself generate a follow-up question
7. [x] Engineered conflict (220 vs 330 ohms) → flagged + attributed, never silently merged — reuses `_run_self_test`'s own T48 fixture verbatim
8. [x] Session lands in observation queue + `SessionMemoryWriter` distills to KB — same call as legs 1/2 (one scripted spine pass proves all three together)

**Criterion zero:** every leg above is scripted/offline — a `live_api_calls_made` counter (not a synthetic-fixture-cost sum) is printed and reads `0 live API calls this run → ₹0`.

**`--final-boss --live` (budget-capped ≤$0.10):** built as a thin wrapper (`_final_boss_live()` — reuses the existing live `_awareness()` for legs 1-2, `router._gate()` for leg 3, one real routed+aggregated `ask()` call for legs 4/7/8) but **not executed by the assistant** — same precedent as every prior Stage 4 sub-phase's live DoD leg (user-run). Legs 5/6 are flagged as NOT independently forced in live mode (a single budget-capped call can't reliably induce a real 429 or a real weak-grounding case on demand) — verified offline only, an explicit honest-scope note rather than a silent gap.

**8/8 pass (offline). JARVIS has its Brain — Stage 4 is CLOSED.**

---

## Progress Tracker

| Sub-Phase | Wave | Status | Lessons Complete |
|-----------|------|--------|------------------|
| 4.0 Cognitive Control Loop | 1 | ✅ Complete (2026-06-12; Gate A 5/5 live on nemotron free tier, ₹0; capture parity + KB distill proven) | 5/5 |
| 4.1 Route Targets & Per-Model Protocol | 2 (Pass A) | ✅ Complete (W1 + W2: protocol/targets/pool, STEAL #7, llm_client re-homed; live DoD met 2026-06-19 — clean multi-model routing + failover/recover + cost-routing free-over-paid) | 5/5 |
| 4.2 Intent Router | 2 (Pass A) | ✅ Complete (router.py + frozen eval + RoutingLedger + ask() wiring; **gate PASSED 84%** 2026-06-29; 4.2.5 not needed) | 4/4 |
| 4.3 Dynamic Target Management | 3 (Pass B) | ✅ Complete (2026-07-16; rolling stats persistence + budget governor + catalog drift; 38/38 model_pool, 20/20 llm_client) | 3/3 |
| 4.4 Response Aggregation | 3 (Pass B) | ✅ Complete (2026-07-20; bounded fan-out + voting/synthesis + quality filter; 18/18 aggregator.py) | 3/3 |
| 4.5 Epistemic Control | 3 (Pass B) | ✅ Complete (2026-07-20; divergence gate 6/6+6/6 exact + fail-closed contradiction judge + escalation policy; 20/20 confidence.py, 48/48 reasoning.py, 91/91 orchestrator.py) | 3/3 |
| 4.6 GraphRAG | — | 🟡 Required after Context Ledger foundation | — |
| Final Boss | 3 (Pass B closing) | ✅ Complete (2026-07-27; offline 8/8 PASS in `orchestrator.py`; 91/91 full regression held; `--live` variant built, not assistant-run) | 8/8 |

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
| GraphRAG | required follow-on | Context Ledger proves remote facts are authoritative; GraphRAG then enables multi-hop proactive retrieval over them → `jarvis_core/memory/graph.py` |
| Voice/vision (Interface), always-on daemons, agent swarms | Stage 6 | Stage 6 reuses `ensure_ready()/release()` as its cold-wake primitive |
| $10 OpenRouter limit-raise (50 → 1000 req/day) | when 429s bite | The only recommended spend before the Final Boss, and optional |

---

## After This Phase

→ Proceed to **Phase 5: Domain Specialists** — Engineer-first MVP, QLoRA on the shared base, trained on the RoutingLedger + private corpus this stage starts accruing.
