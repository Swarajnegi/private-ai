# PHASE 5: Domain Specialists Roadmap

> **Master Plan Position:** Phase 5 of 6 → [JARVIS_MASTER_ROADMAP.md](../JARVIS_MASTER_ROADMAP.md)  
> **Goal:** Ship ONE specialist end-to-end (The Engineer) before templating the recipe to the rest of the roster. Engineer-first MVP per Decision 2026-05-01; QLoRA-on-shared-Kimi-K2.6-base recipe per Decision 2026-05-03.  
> **Prerequisites:** Phase 1-4 (Python, Memory, Agents, Orchestration)  
> **Hardware:** RunPod only, prepaid credits, no local GPU. Engineer adapter trains on A40 ($0.44/hr ≈ ₹37/hr). See `JARVIS_ENDGAME.md` §2 (GPU selection table + "Why no local GPU") and §3.6 (per-specialist cost breakdown).

---

## ⚠️ PRIOR QUESTION, OPENED 2026-09-06: does this stage need to happen at all?

An external audit (GPT 5.6 Terra) forced the counterfactual — *what does JARVIS give the user that a
frontier subscription does not?* — and exactly one answer survived it: **unprompted surfacing over
their own history.** A frontier model matches everything else the moment you paste the right
context; it cannot fire when you did not know to ask. `JARVIS_ENDGAME.md` §1.2 now records this as
the differentiator, and shows all four §1.1 goals collapsing into that single organ.

**That organ requires no trained adapter.** It runs on the KB, `agent/consolidator.py` and
retrieval — Stage 2/3 machinery, already built and now actually running (`scripts/consolidate.py`,
2026-09-06).

So the deliverable in `JARVIS_ENDGAME.md` §1.1 point 1 — *"trained, not injected"* — is
**demoted from settled goal to OPEN QUESTION.** It is not cancelled and this stage is not deleted;
what changed is that the prior question is now unanswered:

> **Does a trained adapter beat the already-built retrieval + surfacing path, on the user's real
> recurring work?**

Nobody has tested it. Testing it costs nothing and is a strict prerequisite to the ₹1,480–2,960
Engineer training run, because a "yes" and a "no" imply completely different next quarters.

Two measurements that make this urgent rather than academic:
- **Measured 2026-09-22: 23 sessions lifetime, 10 in the last 30 days, last used 2026-09-14**
  (`brain/usage.py`, including web-UI sessions by reading their first record timestamp). The old
  19/0 figure was a filename-parser blind spot, not evidence of disuse. This establishes real use,
  but it does not yet establish that an adapter beats retrieval plus proactive surfacing.
- **The Stage-4 Final Boss that "closed" the prerequisite stage is an offline scripted twin** — fake
  embeddings, scripted conflicts, zero live calls. Real end-to-end behaviour is untested.

**Do not start 5.1 on RunPod until the open question above has an evidenced answer.** Everything
below remains the correct recipe *if* the answer is yes.

---

## Overview

| Sub-Phase | Name | Core Concept | Definition of Done |
|-----------|------|--------------|-------------------|
| **5.1** | Fine-Tuning Basics | Adapt models to your domain | Can run LoRA fine-tuning on a 7B model |
| **5.2** | The Engineer QLoRA Adapter | MVP specialist: code_systems + data_engineering, Qwen3-Coder-Next seed | Adapter loads onto the shared Kimi K2.6 base via a RouteTarget registry row |
| **5.3** | Engineer Evaluation | Match base on public benchmarks AND beat it on private-corpus tasks | RAGAS + recall@k gate passes; NOT framed as "beat GPT-5.5" |
| **5.4** | Specialist Templating | Replicate the recipe, ROI-ordered | A second specialist (Analyst) ships faster than Engineer did, using the same template |
| **5.5** | Roster Expansion | Full 12-specialist spec, build on demand only | Next adapter always justified by a real trigger, never "next on the list" |

*(Re-scoped 2026-08-03 to match `JARVIS_MASTER_ROADMAP.md`'s authoritative Stage 5 table — this file previously described 5.2-5.5 as three parallel Code/Science/Medical specialists on the wrong seed models, a pre-pivot draft that predated the Engineer-first-MVP decision. Original text: `git log -p -- js-learning/stage_5_specialists/ROADMAP.md`.)*

---

## Sub-Phase 5.1: Fine-Tuning Basics ⬜

**Goal:** Learn to adapt base models to specific domains.

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 5.1.1 | LoRA/QLoRA Overview | Efficient fine-tuning | `@[/learn] Explain LoRA and QLoRA for fine-tuning.` |
| 5.1.2 | Dataset Preparation | Format data for training | `@[/learn] Explain dataset formats for fine-tuning.` |
| 5.1.3 | Training with Unsloth | Fast local fine-tuning | `/dev Set up Unsloth for local fine-tuning.` |
| 5.1.4 | Merging & Exporting | Merge LoRA weights into base | `/dev Implement LoRA merge and export pipeline.` |

**Practical Exercise:** Fine-tune a 7B model on 1000 examples.

---

## Sub-Phase 5.2: The Engineer QLoRA Adapter ⬜

**Goal:** Ship the first specialist end-to-end. Sub-domains = `code_systems` + `data_engineering` (frontend/backend deferred until that stack is locked in). Adapter seed = Qwen3-Coder-Next 80B/3B-active, distilled onto the shared Kimi K2.6 base. Personalization corpus: `jarvis_core/` source, KB entries, chat-history with Claude/Antigravity, DE corpus, past error logs (`JARVIS_ENDGAME.md` §3 roster row 2; `JARVIS_MASTER_ROADMAP.md` Stage 5 goal line).

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 5.2.1 | Sub-Domain Isolation Discipline | Why code_systems+DE ship together, frontend/backend deferred | `@[/learn] Explain sub-domain isolation for the Engineer adapter.` |
| 5.2.2 | Corpus Assembly | Build the training set from jarvis_core/, KB, chat history, DE corpus, error logs | `/dev Build the Engineer adapter's training corpus pipeline.` |
| 5.2.3 | Qwen3-Coder-Next Adapter Training | QLoRA train on RunPod (A40, rank 32, ~5 epochs, 40-80 GPU-hrs per ENDGAME §3.6) | `/dev Train the Engineer QLoRA adapter on RunPod.` |
| 5.2.4 | Base+Adapter Integration | Wire the adapter into Kimi K2.6 as a RouteTarget registry row (Stage 4 substrate) | `/dev Integrate the Engineer adapter as a RouteTarget registry row.` |

**Practical Exercise:** Engineer adapter loads onto the shared Kimi K2.6 base and correctly answers a JARVIS-codebase question the base model alone gets wrong.

**Progress (2026-08-03):** 5.2.1 + 5.2.2 done. 5.2.1 satisfied by design, not separate code — the corpus builder only pulls `code_systems` (jarvis_core/) + `data_engineering` (DE corpus) + cross-cutting personalization (KB, chat-history) sources, no frontend/backend material exists to accidentally include. 5.2.2 shipped as `jarvis_core/specialists/engineer_corpus.py` — verified run: 402 jarvis_core_code + 453 kb_entry + 493 chat_history + 125 de_corpus records (1,473 total) written to `jarvis_data/training_corpus/engineer_corpus.jsonl`. Two honest gaps carried forward: the `error_log` source correctly yields 0 (nothing persists errors to disk anywhere in this codebase yet); DE-corpus scope is 5 hand-picked authored files, not the whole `knowledge/Data Engineering/` tree (exam-bank/interview-test material excluded as a judgment call — see the module's own comments). 5.2.3 (RunPod training) and 5.2.4 (RouteTarget integration) remain blocked on an actual RunPod account existing.

**Data-quality fix (2026-08-03, same day):** user pushed back on whether the extracted data was actually correct and sufficient. Verification found real (non-hallucinated) near-duplication: the same question asked repeatedly across separate debugging sessions produced 6 near-identical KB entries about one RunPod decision and 5+5 conversation files repeating "tell me what jarvis is about"/"consult your own knowledge base" verbatim — none exact-duplicate text, so exact dedup wouldn't have caught them. Added prefix-based near-duplicate capping (keep first 2 occurrences per near-identical opening, drop the rest) to `iter_kb_records` (entry-level, pre-chunk) and both chat-history iterators (file-level for ConversationStore, so a capped conversation is dropped whole, never partially). Verified precisely: both KB clusters correctly reduced to 2 survivors each, both conversation-file clusters correctly reduced from 5 to 2 each. 122 near-duplicate records removed (19 kb_entry + 103 chat_history); corpus now 1,356 records. **Known remaining gap, not fixed:** single-occurrence low-value content (trivial/off-topic exchanges asked only once, e.g. "is the earth flat?", "what is 2+2?") isn't caught by repetition-based capping — deliberately left for manual review rather than guessed at with a fragile content-quality heuristic.

**Separately raised, not yet resolved:** whether the *volume* of even a clean corpus (1,356 raw text records, ~3MB) is enough for a QLoRA adapter, and whether Qwen3-Coder-Next's own baseline competence is sufficient such that personalization-only fine-tuning is the right call at all (vs. needing a better seed or more volume). Per `JARVIS_ENDGAME.md`'s own philosophy ("the moat is personalization, not parameter count"), general software-engineering competence is supposed to come from the seed model, not this corpus — but that assumption is untested until Stage 5.3's evaluation gate (match base on public benchmarks AND beat it on private-corpus tasks) actually runs, which requires 5.2.3 training first.

---

## Sub-Phase 5.3: Engineer Evaluation ⬜

**Goal:** Prove the adapter is worth the training cost. Gate: match Kimi K2.6 base on public benchmarks AND outperform it on the user's private-corpus tasks (code style, KB recall, error-pattern recognition). Explicitly NOT "beat GPT-5.5" — that's the wrong frame (`JARVIS_MASTER_ROADMAP.md` Decision 2026-05-03).

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 5.3.1 | RAGAS for Specialist Eval | Reuse the Stage 2.5.6 RAGAS harness against Engineer-domain queries | `@[/learn] Explain applying RAGAS to specialist evaluation.` |
| 5.3.2 | recall@k on Engineer-Domain Test Set | Build a held-out test set from jarvis_core/ + KB | `/dev Build the Engineer-domain recall@k test set.` |
| 5.3.3 | Public Benchmark Parity Check | Confirm the adapter doesn't regress general code benchmarks vs. base | `/dev Run public code benchmarks: adapter vs. Kimi K2.6 base.` |
| 5.3.4 | Private-Corpus Outperformance Gate | Code style, KB recall, error-pattern recognition — adapter must beat base here | `/dev Implement the private-corpus outperformance gate.` |

**Practical Exercise:** Engineer adapter matches base on public benchmarks AND beats it by a measurable margin on the private-corpus test set.

---

## Sub-Phase 5.4: Specialist Templating ⬜

**Goal:** Only after Engineer ships — replicate the adapter recipe to the next specialists, ROI-ordered per `JARVIS_ENDGAME.md` §3.6: Analyst (cumulative ₹5,890) → Scientist (₹9,590) → Guardian (₹10,380).

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 5.4.1 | Recipe Extraction | Generalize the Engineer pipeline (corpus assembly → QLoRA train → RouteTarget wiring → eval gate) into a reusable template | `@[/learn] Explain what's specialist-agnostic vs. Engineer-specific in the adapter recipe.` |
| 5.4.2 | Analyst Adapter (ROI #3) | Qwen 3-235B reasoning seed + LoRA on Indian markets; corpus = Groww trade history, NSE bulk-deals, trade journal, risk profile | `/dev Train the Analyst QLoRA adapter on RunPod.` |
| 5.4.3 | Scientist Adapter (ROI #4) | DeepSeekMath-V2 seed; corpus = hologram-project notes, optics/photonics papers, /research outputs | `/dev Train the Scientist QLoRA adapter on RunPod.` |
| 5.4.4 | Guardian Adapter (ROI #5) | Qwen3-Coder-Next + LoRA on security advisories; corpus = audit logs, past vuln findings, threat model docs | `/dev Train the Guardian QLoRA adapter on RunPod.` |

**Practical Exercise:** A second specialist (Analyst) ships end-to-end using the templated recipe, in less wall-clock time than Engineer took — proving the template actually works.

---

## Sub-Phase 5.5: Roster Expansion ⬜

**Goal:** Spec preserved for the full 12-specialist roster (`JARVIS_ENDGAME.md` §3). Build remaining adapters only on demand — never all at once, always 1 base + N adapters, never N dense fine-tunes.

**Corrected 2026-08-10 (same day):** an earlier version of this note gated the roster on personal-corpus availability (passive vs. active corpus generation). That directly contradicted `JARVIS_ENDGAME.md` §3's 2026-07-18 REVISED decision — personal data was never a build gate; a specialist gets domain genius from its PUBLIC adapter seed regardless (Qwen3-Coder-Next, MedGemma, IEEE corpus, etc.), personal data is a bonus layer on top when it exists. The actual gate is exactly 5.5.2 below: demand signal, not corpus signal. `JARVIS_ENDGAME.md` §3's "Build Priority" column reflects this correctly now — most of 5.5.1's "remaining roster" is deferred because nothing is asking for them yet, not because they're technically unbuildable. Guardian is worth re-checking first if a 3rd slot opens, since DE client work increasingly touches security/access questions.

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 5.5.1 | Remaining Roster Review | Operator, Electrician, Mechanic, Chemist, Strategist, Interface — confirm seed models + corpora still match ENDGAME §3 | `@[/learn] Explain the remaining roster's seed models and corpora.` |
| 5.5.2 | Demand-Trigger Definition | What signal justifies training the NEXT adapter, vs. premature roster completionism | `@[/learn] Explain the demand-trigger discipline for roster expansion.` |
| 5.5.3 | Multi-Adapter Swap Testing | Confirm ~2-5s adapter-swap time holds with 5+ adapters resident on one base | `/dev Benchmark adapter-swap latency at 5+ resident adapters.` |
| 5.5.4 | Cost Ledger Reconciliation | Actual RunPod spend vs. ENDGAME §3.6 projected training-cost table | `/dev Reconcile actual vs. projected specialist training costs.` |

**Practical Exercise:** A 4th or 5th specialist ships because a real trigger fired — not because "it was next on the list" — and the cost ledger still tracks within ENDGAME §3.6 projections.

---

## Final Boss: The Experts

Have the Engineer-first MVP fully proven out:
1. [ ] Engineer adapter: Qwen3-Coder-Next seed, integrated as a RouteTarget, outperforms base on private-corpus tasks
2. [ ] Evaluation gate passed: RAGAS + recall@k, public-benchmark parity confirmed, no regression
3. [ ] Recipe templated to at least one more specialist (Analyst, ROI #3)
4. [ ] Cost ledger matches ENDGAME §3.6 projections within reason
5. [ ] Specialists integrate with the Phase 4 orchestrator (RouteTarget / model_pool substrate)

**When this works, JARVIS has its first Expert — and a proven recipe for the rest.**

---

## Progress Tracker

| Sub-Phase | Status | Lessons Complete |
|-----------|--------|------------------|
| 5.1 Fine-Tuning Basics | 🔄 In Progress | 1/4 |
| 5.2 The Engineer QLoRA Adapter | 🔄 In Progress | 2/4 |
| 5.3 Engineer Evaluation | ⬜ Not Started | 0/4 |
| 5.4 Specialist Templating | ⬜ Not Started | 0/4 |
| 5.5 Roster Expansion | ⬜ Not Started | 0/4 |

---

## After This Phase

→ Proceed to **Phase 6: Integration & Interface** → [stage_6_integration/ROADMAP.md](../stage_6_integration/ROADMAP.md)
