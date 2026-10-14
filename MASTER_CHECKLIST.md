# JARVIS MASTER CHECKLIST

> Snapshot, not a log. **Update this file, don't append to it.** Global survey 2026-10-08 by Claude
> (Sonnet 5.5) from measured state: `check_pipeline.py`, `pipeline_health.py`, `parse_turns.py --status/--routing`,
> `training_corpus/*.jsonl`, `graph_index.json`, STATUS.md, `commitments.py --list`. Counts are
> a snapshot; the command beside each is the live figure. Where a number could not be
> re-measured it says so. `[x]` done, `[ ]` open, `[~]` partial. **Owner** = only the owner can do it.
> Section J's native Windows cutover verification was updated by Codex on 2026-10-12;
> that partial host setup does not re-measure the older global survey.

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
- [x] GraphRAG v0 built locally (1,098 nodes / 92 edges in `jarvis_data/graph_index.json`, rebuilt by the hearth job `rebuild_graphrag`; `memory_graph_search`); proof of the Context Ledger continuity layer still pending (c009)
- [x] Voice stack rebuilt 2026-09-27 (resident Whisper + Kokoro, streamed single call)
- [x] Pipeline integrity checker (`python3 scripts/check_pipeline.py`): 29 ok / 1 failed / 0 unmeasurable on 2026-10-08; the 1 failure is the retracted-records item in D2
- [x] Research papers and their Chroma collection removed (owner decision, 2026-10-08)

## C. Current breaches and blockers (re-check: `python3 scripts/pipeline_health.py`)

- [ ] **Parse backlog** (`python3 scripts/parse_turns.py --status`): Codex 951, oldest 2026-09-13 (limit 24 h / 200); Antigravity 167, oldest 2026-05-21; Claude 0 (new turns appear every session).
- [x] Active-host memory index refreshed 2026-10-13: 1,133 entries / 1,930 chunks.
- [x] Five generated corpus artifacts rebuilt 2026-10-13; all 30 pipeline invariants passed. The client snapshot is an input, preserved unchanged.
- [ ] `cognitive_profile.md` / `cognitive_index.sqlite3` lag the KB by a few entries until `profile_synth.py` runs (held until parsing settles).
- [ ] **OpenRouter balance negative** → tool-using deep turns return HTTP 402. **Owner.**
- [ ] **Personal laptop dead** → Codex and Antigravity cannot run; Claude parses their backlogs under KB 1009.
- [ ] Tension evaluation positive case failed on a provider connection error at last report (Codex, 2026-09-12). **Not re-checked since.**
- [ ] Exposed-key item c004 still open in the registry. **Owner**; the owner has said to leave it (2026-10-06), no agent action.

## D. Guarded maintenance on the active host (owner approval 2026-10-13)

- [x] Shared exclusive execution for scheduled jobs and the five manual maintenance commands.
- [x] CPU-only resource policy: mains power, 4 GiB available RAM, two threads,
  below-normal priority, bounded timeouts, process-tree cleanup and visible deferrals.
- [x] Real memory-index, domain-label and corpus validation. Thirty pipeline
  invariants passed; 947 client-snapshot records preserved without raw client source.
- [x] Bounded episode validation: three real sources, 254 dense vectors. This is
  not completion of the entire historical index.
- [ ] Remaining historical episode sources: the six-hour incremental job catches up.
- Cadences: memory 12 h; episodes 6 h; labels 24 h; corpora 48 h;
  tests check daily after changes with a weekly fallback. Capture remains unchanged.
- [x] All five jobs enabled after validation; watchdog restart, live cadences,
  UI availability and local voice round trip verified. `.paused_jobs` and
  `/v1/health` remain authoritative for subsequent activation changes.

## D2. Personalization interview (investigated 2026-10-07)

- [x] Root cause found: on 2026-09-26 the owner asked an off-script question and a free model (`nemotron-3-super:free`) wrote BOTH sides of interview question 6 in the owner's voice (KB 1201 records it).
- [x] Guard shipped: interview-mode rule on the task, one retry, then a fixed fallback (`brain/interview_guard.py`, 105/105 in the orchestrator self-test).
- [x] Poisoned turn retracted (verdict `none`) and a retraction registry (`jarvis_data/retractions.jsonl`) now keeps KB 735 and the raw conversation turn out of every corpus builder and out of the retrieval index.
- [ ] **Corpus rebuild needed** (paused by owner rule): 8 retracted records still sit in the built artifacts. `python3 scripts/check_pipeline.py` reports this as its 1 failed item until the rebuild runs.
- [ ] **Owner: the interview has only Questions 1-5 answered (of 43).** Questions 6-43 are the best remaining personalization data and are TRAINING data; they do not replace the 25 c002 held-out answers.
- [ ] Not unit-tested: the personalization corpus's KB paths (they read through the SQLite cognitive index).

## E. Training readiness (Stage 5 gate)

Measured 2026-10-07 (corpora last built 2026-10-05, unchanged) from `jarvis_data/training_corpus/`:

| Item | Target | Have |
|---|---|---|
| SFT pairs, Engineer | 400 | 367 (331 train + 36 held-out) |
| SFT pairs, Personalization | 200 | 192 (173 train + 19 held-out) |
| Held-out set | enough to measure | 55 total — **too small for the personalization side (19)** |
| Blended corpus | — | 4,134 records |
| Turns routed under rule v1 (`python3 scripts/parse_turns.py --routing`) | — | 1,507 (428 trainable) |

- [~] **c002: adapter-vs-retrieval evaluation (₹0).** Harness BUILT 2026-10-07: `scripts/eval_c002.py` (commit 56884ab; 230 hermetic self-checks; an independent review found 20 defects, all fixed), design in the approved plan. Nothing has been MEASURED yet. Status below:
  - [x] Exclusion registry + canary, wired into the corpus builders, `check_pipeline` invariant (the c002 canary line passes)
  - [x] 72 engineering items (34 recall / 38 apply), machine-checked, deduped across authors; 25 personalization questions; protocol draft + endpoints
  - [x] Leakage audit runs against the real corpora (14 s). It FAILS today, correctly: eval markers sit in `blended_corpus`, `engineer_corpus` and `personalization_corpus` (legacy), and 4 recall TUNING questions (`ms-02`, `ms-08`, `t-01`, `t-12`) appear verbatim in training. None of the 40 frozen held-out items leaked. Fix = rebuild the corpora (paused) after which the audit is re-run; adapter arms refuse to run until it passes.
  - [ ] **Owner: answer the 25 questions** in the private answers file (outside the repo, mode 600, deny-ruled for agents). Edit it in an editor, never in a chat.
  - [ ] **Owner: top up OpenRouter** (judges, validator and the reference arm are paid models)
  - [ ] `validate-rubrics` (API only), set T0, `lock`
  - [ ] New PC / revived laptop: `snapshot`, `freeze-contexts`, arms A, B, B*, O, R, `judge`, `headroom` (Stage 0)
  - [ ] Only if Stage 0 says PILOT: pilot adapter with a training manifest, `audit --manifest`, arms C and D*, `analyze`
  - Known untested on this machine: the real recall-router provider and index builder (`RouterProvider`, `build_snapshot_indexes`), the real tokenizer, and every live endpoint call. They are covered by hermetic fakes only.
- [ ] Re-measure personalization character share. Last figure is 13.7% (2026-09-12) and is stale.
- [ ] Rebuild corpus artifacts after parsing settles. They were rebuilt and quality-audited on 2026-10-14; future parse/review changes still require rebuilding.
- [ ] Grow held-out set, especially personalization.
- [ ] Rebalance blend: by characters, chat history 32.8%, code 24.1%, `client_work` 22.8%; identity/voice/writing sources are single digits.
- [ ] **Owner decision: is `client_work` content allowed in training?** The push rule was relaxed 2026-10-06; training use was never decided.
- [ ] More personalization source material: decision-explanation sessions in the owner's own voice (`SFT_SPEC.md` §6). **Owner.**
- [ ] **Recheck the training-cost plan.** ENDGAME §3.6 budgets Engineer QLoRA on one A40, but §2 says the Kimi K2.6 base needs at least 4×A5000 just to serve. Read-only suspicion, untested.
- [ ] Owner's stated stance (KB 1093): defer RunPod until the data is as rich as possible.

**Current production measurement (2026-10-14, Milestone 1 rebuild):** engineer
SFT 370 (333 train + 37 held-out), personalization SFT 192 (173 + 19),
blended corpus 3,963 records. Independent training review holds 122 source
identities pending; eight reviewed sources are rejected and three approved.
This updates artifact counts, not the older c002 experiment or training approval.

## E2. Milestone 1 — baseline and independent training review (2026-10-14)

- [x] Append-only `training_reviews.jsonl`; complete source digests, independent reviewer identity, individual rationale and evidence. Self review, stale/missing sources and corrupt reviews are refused.
- [x] One eligibility gate for queue exchanges, raw assistant turns, legacy session-distill KB records, derived sources and both SFT exports; Stage 5 and pipeline audits use the same policy.
- [x] Preserve capture, history, retrieval, owner-only material and parse rule v1. Review decisions do not override retractions, routing or evaluation exclusions.
- [x] Review seven October 13 exchanges plus four associated KB copies individually: three approvals, eight rejections. Other historical answers remain pending, outside this milestone's review scope.
- [x] Record six baseline cases; hardware/performance/error/reads/continuity were unresolved at the baseline, ambiguous transcription is unmeasured without original audio. Current repair verification is in E3.
- [x] Targeted review, corpus-chain, scheduler, maintenance, pipeline, Stage 5, retraction and exclusion checks pass.
- [x] Production rebuild/audit: all five exports have zero ineligible records; 36 pipeline checks pass. Final run 64.11 s, 5.41 GiB minimum free RAM, 248.11 MiB peak tree commit. Snapshot byte hash and 947 records preserved; metadata-alias regression added.
- [x] Antigravity answered q056/q057 with 20 fixture tests. Codex reviewed the full file, corrected portable fixture paths and strengthened host/artifact assertions; all 20 rerun successfully.
- [x] Live capture/UI/voice verified; live review hold counts 3 approved / 8 rejected / 122 pending. Core/frontend unchanged. Production sign-off complete; local milestone commit only, no push.

## E3. Milestone 2 — trustworthy interactive harness (2026-10-14)

- [x] Timestamped current-host inspection without model loading; measured CPU/RAM/GPU/VRAM and actual CPU voice/embeddings/cloud brain, with explicit unknowns.
- [x] Native PowerShell parser policy, validated arguments before permissions, safe automatic inspection and individual change approval; no `allow_all` bypass.
- [x] Supervised tool process trees with bounded timeouts and fail-closed cleanup; ordinary requests do not acquire the maintenance lock.
- [x] Workspace text create/edit with exact diff, full-file digest, unique replacement, atomic conflict checks and preserved encoding/line endings; authoritative stores protected.
- [x] Accurate typed missing-path/unknown-tool errors and discovery hints; unchanged identical reads reused within each request.
- [x] Authenticated request/session/action-bound one-time approval over HTTP and voice; fixed ten-minute expiry and reconnect retention.
- [x] Visible Terminate including folded dialogue, Escape, local playback stop, exact request cancellation and cleanup before New conversation/fresh question. Completed file changes remain and are reported accurately.
- [x] Antigravity q058/q059: 30 bounded fixture tests reviewed and rerun; Codex added 17 end-to-end checks. No policy/data/dependency/schedule changes by Antigravity.
- [x] Desktop/mobile browser fixtures: 13 checks at 1440x900 and 390x844; TypeScript/build and relevant harness/service/Milestone 1/pipeline/scheduler regressions pass. Served bundle rebuilt, Hearth restarted through its watchdog.
- [x] Live configured-provider inspection, file discovery, approved scratch creation and denied action verified. CPU voice available; no speech benchmark.
- [ ] Additional production approved edit/controlled-command termination check: configured free brain returned OpenRouter 404 `No endpoints found` three times. Real-tool isolated service checks pass; retain this distinction until the live check can be completed. No model replacement performed.
- [x] Uncaptured requests now leave no conversation/session/queue/KB writes; five earlier identifiable test histories preserved intact under `.runtime/milestone2/` with hash manifest.
- [x] Core renderer/geometry/colours, landing, Sessions/System layout, client snapshot, training gate and schedules preserved; local commit only, no push.
- [~] B01 fresh hardware evidence and B03 error handling verified; B04 same-request read reuse verified. General model decisions, B02 calibration, B05 continuity and B06 speech accuracy remain later work. Milestone closure waits for the outstanding live check above.

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
- [ ] Backfill of assistant summaries truncated at 2,000 chars before 2026-09-18, when the cap was removed entirely (design needed; the queue is append-only).
- [ ] Personalization interview: 43 numbered questions, in progress. **Owner.**
- [ ] Codex mail q_046, q_047 and q_048 are open and wait for the personal laptop (`python3 scripts/agent_mail.py --list`).
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

## J. Cutover: work laptop → next host with a personal account (owner decision 2026-10-12)

**Situation.** Celebal moved Claude Team to Enterprise (backup deadline 15 Oct 2026), so JARVIS stops on the work laptop and the company account. The Enterprise account is used only for DE learning, job-switch and RSA prep, in `~/work/Claude Learning/` on the work laptop: a copy made 2026-10-12, with no JARVIS hooks. The next host is the repaired personal laptop or a new machine, **native Windows, no WSL** (WSL was used only because Claude Code had trouble on the work laptop), running Claude Code, Codex or Antigravity. The owner has saved the two hand-carried folders to a personal cloud, and everything is pushed.

**Agent on the next host:** this section tells you what travels and how the setup worked on the work laptop. It does not prescribe the Windows setup; adapt each mechanism to your environment, then prove it works with the checks under "Verify".

**Current cutover verification (2026-10-12, Codex):** native Windows host
`LAPTOP-SMOU1K0D`, 16 GB RAM, repo root `D:\J.A.R.V.I.S`. Python 3.12.4 and the pinned
dependencies are installed in `.venv/`; package/model caches and installation temp
files use `.cache/` and `.runtime/tmp/` on D. The KB has 1,090 entries, including
three evidenced facts from this session; `jarvis_memory` has 1,887 chunks after
rebuilding. Hearth and its supervised Chroma server are up; authenticated health
and the web UI return HTTP 200. On 2026-10-13, after a reboot left the old logon
watchdog absent, it was replaced with the per-user Task Scheduler task
`JARVIS Hearth Watchdog`. Its only trigger is sign-in; it starts the hidden
watchdog, which starts the hearth. Battery operation is allowed, its execution
time is unlimited, and the duplicate HKCU Run entry was removed. Manual task
launch and UI HTTP 200 were verified; the next reboot/sign-in remains untested. Windows
episode-index smoke checks pass 49/49, including both SQLite deletion paths.
Codex capture found this session and seven unique keys were individually parsed;
the inherited backlogs remain Codex 951 / Antigravity 167. `check_pipeline.py`
reports 29 ok / 1 failed: eight retracted records remain in the built training
artifacts. Keep the five job pauses and the existing corpora. On 2026-10-13 the
owner saved a new OpenRouter key in the Windows user environment; authentication
succeeded. The isolated live orchestration check called the calculator and answered
`17 × 19 = 323`, with three model calls and $0 spend, using
`apodex/apodex-1.1-mini:free`, now the user-environment default. Its conversation
store and session state were temporary; capture and KB distillation were disabled.
The generic free-router attempt timed out, and `cohere/north-mini-code:free`
produced a protocol failure. A live answer through the browser UI, fresh hook lifecycle
execution, reboot persistence and the hand-carried private files remain unverified;
the work laptop must not be decommissioned on the strength of these partial checks.

**Travels via git:** KB, profile, digest, observation queue, parse verdicts, retractions, c002 harness, context-store shards (verbatim Claude Code transcripts, compressed), `.agent/` (rules, workflows, hook manifest), `.claude/settings.json` (hooks, home-relative deny rules), `.codex/hooks.json`, `jarvis_data/.paused_jobs`.
**Carried by hand (owner's personal cloud):** `.jarvis_private/` (c002 owner answers; restore it in the home folder) and `claude_chats_backup_2026-10-08/` (raw Claude Code chats, incl. RSA and Job Switch; an archive that nothing reads, the shards already cover them).
**Recreate, never copy:** OpenRouter key, GitHub PAT. **Rebuild:** the Python environment, `jarvis_data/chromadb/`, the episode index. **Lost on purpose:** `.claude/settings.local.json`, Claude Code's machine-local memory notes (their durable content is in the KB, incl. KB 1202-1203). **Stays off personal machines:** `client_work/` raw repos.

### How it worked on the work laptop (adapt to your environment)

| Piece | How it ran on the work laptop (Linux, WSL Ubuntu 22.04) |
|---|---|
| Python | A venv at `.venv/` (`.venv/bin/python3`), packages from `requirements.txt`. Scripts were run as `python3 scripts/<name>.py` from the repo root; library code is imported with `js-development` on the path. |
| Claude Code hooks | Declared in `.agent/hooks.manifest.json`; `scripts/bootstrap_jarvis.py` merges them into `.claude/settings.json`. Each hook runs the command `python3 -c "<runner>" <hook>.py`: the runner finds the repo (via `CLAUDE_PROJECT_DIR` or the nearest folder holding `scripts/hooks/`), adds `js-development` to the path, runs `scripts/hooks/<hook>.py`, **swallows every error and always exits 0**. Hooks use whatever `python3` is on the PATH, not the venv. A broken interpreter therefore fails silently: no error, no capture. |
| The 11 hooks | UserPromptSubmit: `notice_runtime_change` (model-change notice), `capture_gap_nudge` (PARSE BACKLOG nudge), `mail_watch` (agent mail). Stop: `capture_turn` (writes the turn to `observation_queue.jsonl`), `run_consolidation` (feeds the surfacing organ). SessionStart: `surface_pipeline_health`, `inject_profile` and `inject_recent_activity` (the "read the profile and digest in full" pointers), `surface_life_state` (proactive surfacing), `check_agent_mail`. PreCompact: `pre_compact_capture` (stores the session before compaction). |
| Codex / Antigravity capture | No per-turn hooks. The hearth's hourly `ingest_codex` / `ingest_antigravity` jobs read their transcript folders (`~/.codex/sessions/`, `~/.gemini/antigravity-ide/brain/`) into the same queue. NERVOUS_SYSTEM.md §5.2-§5.3. |
| The hearth | `scripts/hearth.py`: one process per machine that owns the clocked jobs (`--status` lists them), serves the web UI and `/v1/*` on `127.0.0.1:8756` (bearer token auto-minted in `jarvis_data/.hearth_token`) and supervises a single-owner Chroma server on `127.0.0.1:8759` (`memory/chroma_access.py`). Kept alive by two user-crontab lines, `@reboot` and `*/10`, each running `.venv/bin/python3 scripts/hearth.py --background`; `--background` detaches by double `os.fork` and refuses when a hearth already holds the port, so the 10-minute line is a harmless self-heal. NERVOUS_SYSTEM.md §6.2 also documents a Windows watchdog (`scripts/windows_hearth_watchdog.py`) built for the personal laptop. |
| Heavy jobs | Listed in `jarvis_data/.paused_jobs` (owner rule KB 1044/1045: the work laptop had 7.6 GB RAM and no GPU). The hearth skips them. Delete a line on a machine that can take the load. |
| Secrets | `OPENROUTER_API_KEY` and `OPENROUTER_MODEL` exported in `~/.bashrc`; the GitHub PAT in `~/.git-credentials`. |
| Private c002 answers | `~/.jarvis_private/c002/owner_answers.md` (folder 700, file 600). Agents must never read it; `.claude/settings.json` denies `Read/Edit/Write(~/.jarvis_private/**)` and any Bash command mentioning `jarvis_private`. |
| File locking | Append-only logs are locked through `jarvis_core/locking.py` (`fcntl` on POSIX, `msvcrt` on Windows) or local equivalents, and every append heals a missing final newline first (CLAUDE.md, Code style). |
| Memory flow | turn → `observation_queue.jsonl` → parse loop (`parse_turns.py`, the rule in `agent/parse_rule.py`) → KB and `turn_curation.jsonl` → `profile_synth.py` → `cognitive_profile.md`; `refresh_digest` → `activity_digest.md`; `ingest_episodes` archives transcripts into the context-store shards; `index_memory.py` / `index_episodes.py` build the vector indexes for recall. |

**Linux-specific on the work laptop (facts to account for, not fixes):** every hook calls `python3`; `bootstrap_jarvis.py --check` looks for `.venv/bin/python3`; the hearth's keepalive is cron and `--background` needs `os.fork`; `scripts/parse_turns.py`, `brain/routing_ledger.py` and `brain/model_stats.py` lock with `fcntl` only, and skip locking where it is missing; paths in docs and commands use `/`.

### Steps

**On the next host**
- [ ] Personal Claude account (Pro, or Max if limits bite) or the Codex/Antigravity equivalent; log in.
- [ ] New fine-grained GitHub PAT (Contents: read and write); clone `https://github.com/Swarajnegi/private-ai.git` to a short path without spaces; set `git config user.name/user.email`.
- [x] New OpenRouter key and model as Windows user environment variables; authentication and an isolated free-model orchestration answer verified 2026-10-13.
- [ ] Restore `.jarvis_private/` into the home folder (owner-only permissions) and keep the chat backup with it.
- [x] Python environment, `pip install -r requirements.txt`, `scripts/bootstrap_jarvis.py`, `scripts/index_memory.py` — verified on the native Windows host above.
- [ ] Decide `jarvis_data/.paused_jobs` for that machine; if the heavy jobs may run, run `scripts/rebuild_corpora.py` and `scripts/index_episodes.py` once.
- [~] Keep the hearth alive across reboots with that OS's scheduler — Task Scheduler logon watchdog installed and running; the next reboot/logon cycle has not been tested.

**Verify nothing was lost**
- [ ] `scripts/bootstrap_jarvis.py --check`, `scripts/pipeline_health.py`, `scripts/check_pipeline.py`, `scripts/parse_turns.py --status`.
- [ ] **Capture works:** a new Claude Code session shows the profile and digest pointers at start, and `observation_queue.jsonl` grows by one row after one turn.
- [ ] KB line count matches GitHub; `scripts/search_memory.py "RSA prep"` returns results; the web UI at http://127.0.0.1:8756/ answers a question.
- [ ] The private-answer deny rules resolve to that machine's home folder (`/permissions` in Claude Code).

**Decommission the work laptop (only after the checks above pass)**
- [ ] `crontab -e`: remove the two hearth lines; stop the hearth and its Chroma server (`python3 scripts/hearth.py --status` gives the pids).
- [ ] Remove the OpenRouter lines from `~/.bashrc` and the GitHub entry from `~/.git-credentials`; revoke the old OpenRouter key and the old PAT at the providers.
- [ ] Delete `~/work/JARVIS`, `~/.jarvis_private`, `~/.claude/projects/-home-swara-unix-work-JARVIS` and `~/claude_chats_backup_2026-10-08`.
- [ ] Only then log Claude Code into the Enterprise account.
