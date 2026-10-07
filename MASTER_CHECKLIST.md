# JARVIS MASTER CHECKLIST

> Snapshot, not a log. **Update this file, don't append to it.** Last written 2026-10-07 by Claude
> (Sonnet 5.5) from measured state: `check_pipeline.py`, `parse_turns.py --status/--routing`,
> `training_corpus/*.jsonl`, STATUS.md, `commitments.py --list`. Where a number could not be
> re-measured it says so. `[x]` done, `[ ]` open, `[~]` partial. **Owner** = only the owner can do it.

Companion files: [STATUS.md](STATUS.md) (cross-agent snapshot), [js-learning/JARVIS_MASTER_ROADMAP.md](js-learning/JARVIS_MASTER_ROADMAP.md) (stage status, authoritative), [.agent/rules/JARVIS_ENDGAME.md](.agent/rules/JARVIS_ENDGAME.md) (§1.1 goal, §1.2 differentiator).

---

## A. The goal, and the distance to it (JARVIS_ENDGAME §1.1)

| Goal | State |
|---|---|
| Trained, not injected (Stage 5 adapter actually trained and deployed) | [ ] zero trained weights; gated on c002 |
| Deployed on every surface (phone, desktop, web) | [~] web UI local only; hosted copy asleep; no phone/desktop shell shipped |
| Wired to the senses (cameras, mics) | [~] voice runs locally (Whisper + Kokoro); no vision, no phone sensors |
| Ambient (present continuously) | [ ] not started; designed as tiered presence in ENDGAME §2 |
| The differentiator: unprompted surfacing over own history (§1.2) | [~] organ built; **no evidence yet it fires usefully on real days** |

## B. Built (Stages 1-4 and the layers under Stage 6)

- [x] Stage 1 Systems Python (1.4/1.5 deliberately deferred)
- [x] Stage 2 Memory Layer (embeddings, Chroma, BM25, hybrid, rerank, KB compaction)
- [x] Stage 3 Agent Framework (built from scratch in `jarvis_core/agent/`)
- [x] Stage 4 Orchestration (router 84% on frozen gate, failover, aggregator, epistemic control; Final Boss 8/8 is an **offline scripted twin**, not live)
- [x] Hearth (always-on process, scheduler, bearer-token API)
- [x] Capture adapters for all three hosts (Claude hooks, Codex, Antigravity)
- [x] Memory Contract live: one parse rule (`parse_rule.py`), no paid background calls
- [x] GraphRAG v0 built locally (625 nodes / 54 evidence-backed edges, `memory_graph_search`); proof of the Context Ledger continuity layer still pending (c009)
- [x] Voice stack rebuilt 2026-09-27 (resident Whisper + Kokoro, streamed single call)
- [x] Pipeline integrity: `check_pipeline.py` 28 ok / 0 failed / 0 unmeasurable (2026-10-07)

## C. Current breaches and blockers (re-check: `python3 scripts/pipeline_health.py`)

- [ ] **Codex parse backlog: 951 turns**, oldest 2026-09-13 (limit 24 h / 200). 188 parsed so far under this effort.
- [ ] **Antigravity parse backlog: 167 turns**, oldest 2026-05-21.
- [ ] Claude backlog ~0 (new turns appear every session).
- [ ] `chromadb/jarvis_memory` stale: 661 indexed vs 1,079 KB entries. Expected while `reindex_memory` is paused.
- [ ] `cognitive_profile.md` / `cognitive_index.sqlite3` lag the KB by a few entries until `profile_synth.py` runs (held until parsing settles).
- [ ] **OpenRouter balance negative** → tool-using deep turns return HTTP 402. **Owner.**
- [ ] **Personal laptop dead** → Codex and Antigravity cannot run; Claude parses their backlogs under KB 1009.
- [ ] Tension evaluation positive case failed on a provider connection error at last report (Codex, 2026-09-12). **Not re-checked since.**
- [ ] Exposed-key item c004 still open in the registry. **Owner**; the owner has said to leave it (2026-10-06), no agent action.

## D. Paused by owner rule (KB 1044/1045, 2026-10-06) — do not run

- [ ] `run_all_tests`, `rebuild_corpora` (the two heavy ML jobs paused on this machine)
- [ ] `index_episodes`, `reindex_memory`, `relabel_domains` (c011, c012, c013)
- Everything else continues. Anything that can wait for the personal laptop waits for it.

## D2. Personalization interview (investigated 2026-10-07)

- [x] Root cause found: on 2026-09-26 the owner asked an off-script question and a free model (`nemotron-3-super:free`) wrote BOTH sides of interview question 6 in the owner's voice (KB 1201 records it).
- [x] Guard shipped: interview-mode rule on the task, one retry, then a fixed fallback (`brain/interview_guard.py`, 105/105 in the orchestrator self-test).
- [x] Poisoned turn retracted (verdict `none`) and a retraction registry (`jarvis_data/retractions.jsonl`) now keeps KB 735 and the raw conversation turn out of every corpus builder and out of the retrieval index.
- [ ] **Corpus rebuild needed** (paused by owner rule): 8 retracted records still sit in the built artifacts. `check_pipeline` reports this as 1 failed until the rebuild runs.
- [ ] **Owner: the interview has only Questions 1-5 answered (of 43).** Questions 6-43 are the best remaining personalization data and are TRAINING data; they do not replace the 25 c002 held-out answers.
- [ ] Not unit-tested: the personalization corpus's KB paths (they read through the SQLite cognitive index).

## E. Training readiness (Stage 5 gate)

Measured 2026-10-07 from `jarvis_data/training_corpus/`:

| Item | Target | Have |
|---|---|---|
| SFT pairs, Engineer | 400 | 367 (331 train + 36 held-out) |
| SFT pairs, Personalization | 200 | 192 (173 train + 19 held-out) |
| Held-out set | enough to measure | 55 total — **too small for the personalization side (19)** |
| Blended corpus | — | 4,134 records |
| Turns routed under rule v1 | — | 1,497 (425 trainable) |

- [~] **c002: adapter-vs-retrieval evaluation (₹0).** Harness BUILT 2026-10-07: `scripts/eval_c002.py` (self-test 148/148), design in the approved plan. Nothing has been MEASURED yet. Status below:
  - [x] Exclusion registry + canary, wired into the corpus builders, `check_pipeline` invariant (29 ok / 0 failed)
  - [x] 72 engineering items (34 recall / 38 apply), machine-checked, deduped across authors; 25 personalization questions; protocol draft + endpoints
  - [x] Leakage audit runs against the real corpora (14 s). It FAILS today, correctly: eval markers sit in `blended_corpus`, `engineer_corpus` and `personalization_corpus` (legacy), and 4 recall TUNING questions (`ms-02`, `ms-08`, `t-01`, `t-12`) appear verbatim in training. None of the 40 frozen held-out items leaked. Fix = rebuild the corpora (paused) after which the audit is re-run; adapter arms refuse to run until it passes.
  - [ ] **Owner: answer the 25 questions** in the private answers file (outside the repo, mode 600, deny-ruled for agents). Edit it in an editor, never in a chat.
  - [ ] **Owner: top up OpenRouter** (judges, validator and the reference arm are paid models)
  - [ ] `validate-rubrics` (API only), set T0, `lock`
  - [ ] New PC / revived laptop: `snapshot`, `freeze-contexts`, arms A, B, B*, O, R, `judge`, `headroom` (Stage 0)
  - [ ] Only if Stage 0 says PILOT: pilot adapter with a training manifest, `audit --manifest`, arms C and D*, `analyze`
  - Known untested on this machine: the real recall-router provider and index builder (`RouterProvider`, `build_snapshot_indexes`), the real tokenizer, and every live endpoint call. They are covered by hermetic fakes only.
- [ ] Re-measure personalization character share. Last figure is 13.7% (2026-09-12) and is stale.
- [ ] Rebuild corpus artifacts after parsing settles. Current ones date from 2026-10-05.
- [ ] Grow held-out set, especially personalization.
- [ ] Rebalance blend: by characters, chat history 32.8%, code 24.1%, `client_work` 22.8%; identity/voice/writing sources are single digits.
- [ ] **Owner decision: is `client_work` content allowed in training?** The push rule was relaxed 2026-10-06; training use was never decided.
- [ ] More personalization source material: decision-explanation sessions in the owner's own voice (`SFT_SPEC.md` §6). **Owner.**
- [ ] **Recheck the training-cost plan.** ENDGAME §3.6 budgets Engineer QLoRA on one A40, but §2 says the Kimi K2.6 base needs at least 4×A5000 just to serve. Read-only suspicion, untested.
- [ ] Owner's stated stance (KB 1093): defer RunPod until the data is as rich as possible.

## F. Open commitments (`python3 scripts/commitments.py --list`)

- [~] c002 Stage 5 adapter-vs-retrieval decision (review 2026-10-11): harness built, no measurement yet; see section E
- [ ] c004 Revoke exposed GitHub PAT and legacy OpenRouter keys — overdue, owner-only
- [ ] c005 Keep the 12-specialist roster demand-gated (standing policy)
- [ ] c009 GraphRAG follow-on after Context Ledger proof (review 2026-10-11)
- [ ] c011 / c012 / c013 maintenance jobs (see D)

## G. Always-reachable memory, hosting and shells (Stage 6)

- [~] 6.7 shared memory backend: code exists (hosted ledger endpoints + `sync_remote_memory.py`), **deployed and then put to sleep** 2026-09-12 to avoid cost (KB 1190). The Railway volume (500 MB, 618 KB records uploaded) was kept.
- [ ] Decide hosting: pay for always-on, tunnel to a home machine, or self-host on the planned PC build (section I; gated on its tests).
- [ ] 6.9 client shells (phone, desktop) — depend on 6.7. The Corpus app design work (Stitch, dark screens) is separate and was in progress 2026-10-06.
- [ ] Ambient presence tier 0/1 on device (ENDGAME §2); nothing built.
- [ ] Vision and camera input; nothing built.

## H. Housekeeping nobody has claimed

- [ ] Multi-host KB id collisions will recur (host-prefixed or content-derived ids needed).
- [ ] Backfill of assistant summaries truncated at 2,000 chars before 2026-09 (design needed; the queue is append-only).
- [ ] Personalization interview: 43 numbered questions, in progress. **Owner.**
- [ ] Codex reminders q_047 / q_048 wait for the personal laptop.
- [ ] `git push origin main` after each local run of commits. **Owner** (classifier blocks agent pushes; never push `backup-local-main`).

## I. Custom PC build (owner concept, 2026-10-07) — NOT purchased, gated on tests

Owner's V1 list is a **price snapshot and partly outdated**; confirm every item at checkout. Corrections from the owner (2026-10-07): the 1200W PSU is deliberate, sized for the planned upgrade to an **RTX 5090 or a 60-series card**, not a second 5060 Ti; the machine is also meant for **gaming at max settings**, so **Windows stays the primary OS**.

- [ ] **Gate 1 (₹0): corpus and evaluation first.** Nothing is bought until c002 has an evaluation harness and the surfacing organ has shown it helps on real days.
- [ ] **Gate 2 (~₹200-500): rent a cloud GPU (RunPod A5000, ₹23/hr in ENDGAME) for an evening and run a 7B/14B LoRA pilot** on the current SFT pairs. Answers whether local fine-tuning is worth building before spending ₹3L+. **Owner approves the spend.**
- [ ] Owner confirms the money is available without touching job-switch runway (KB 1189: no spare money for subscriptions).
- [ ] Decide dual role: gaming rig and always-on JARVIS host compete for the GPU. Resolve with scheduling (hearth voice/embeddings are small), dual-boot, or WSL2. The 2026-09 Windows failures were native-Windows ones (full C:, scheduler subprocess blocks).
- [ ] Verify before buying: ProArt in stock and its slot layout, case room and cooler thickness for the 5090-class card, 5090 power connector fit on the 1200W unit, RAM price (₹52K for 32GB looked high), SSD stock.
- [ ] If bought: amend ENDGAME §2 ("no local GPU") and §3.6; add a KB decision; record that **Kimi K2.6 (1T) still cannot run locally** and RunPod remains the path for it, unless the owner retargets Stage 5 to a 7-14B base.
- [ ] UPS for an always-on host (power cuts corrupt append-only logs).
- Local capability by GPU (from memory of specs, not measured): 16GB = 8B QLoRA comfortable, 14B tight; **5090 32GB** = 32B Q4 inference fits and 32B QLoRA becomes plausible.
