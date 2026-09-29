# STATUS — read this before starting work, not after

> Written by whichever agent last surveyed the whole build, so the other two don't have to
> re-derive it from scratch on their next session. **Update this file, don't append to it** — it
> is a snapshot, not a log. If something below is stale by the time you read it, fix it and say
> so in your commit message; don't leave a wrong number here because it was true once.

**Last surveyed:** 2026-09-29, by codex for the memory-contract and dormancy sections. Other sections retain the 2026-09-28 Claude survey and must be rechecked before use.
**Since the last survey (2026-09-22):** the owner found that JARVIS did not know them — interview
answers and the people in their life never reached it — and that training was fed by turns
nobody had judged. Measuring why produced **the Memory Contract** (NERVOUS_SYSTEM.md §3), now
live: the agent the owner chats with parses those turns by one rule, no paid background calls,
no truncation, failures loud to all four agents.

---

## 1. Is anything broken right now?

**Yes.** The 2026-09-29 bootstrap reports 1,169 unparsed Codex turns, other-host backlogs, and a stale `chromadb/jarvis_memory` projection (814 KB entries versus 769 indexed). Heavy Chroma jobs are paused after a Windows memory crash; do not treat this as a retrieval success. Re-check with `python scripts/pipeline_health.py`
(one line per breach, silent when healthy) and `python3 scripts/check_pipeline.py`.

- **Curation had stalled for 13 days, invisibly.** The hourly `curate_turns` job (paid Gemini via
  OpenRouter) failed **185 of 195 runs** since 2026-09-15 on HTTP 402 (credits); 1,833 turns sat
  uncurated and flowed into both corpora. Root cause was structural, not the balance: the only
  writer of verdicts was a paid background job, and no agent ever saw job health. **Resolved by
  design:** the job is removed and parsing moved to the agents (below).
- **`reindex_memory` fails, and the failure was hidden.** 16 of 17 runs failed with ChromaDB
  `InternalError: Error in compaction: Failed to apply logs to the metadata segment` (Windows
  host). A later guard-skip overwrote `last_status` with "skipped — guard reports nothing to
  do", so `hearth.py --status` looked healthy. The scheduler change in this contract keeps
  `last_success_ts` / `consecutive_failures`, and `pipeline_health.py` judges jobs by last success.
  The index itself is **still not rebuilt** — unclaimed. `chromadb/` is a projection (NERVOUS_SYSTEM §1.3),
  so rebuilding it from scratch with `scripts/index_memory.py` loses nothing.
- **Fixed today: on Windows the profile never reached Claude Code at all.** `inject_profile.py`
  wrote raw UTF-8 to a cp1252 pipe; the first `→` raised, the `except` swallowed it, the hook
  emitted 0 bytes. And where it did work, the harness cuts SessionStart output over ~10 KB to a
  2 KB preview of a ~650 KB profile. Both SessionStart injectors now emit a short read-in-full
  notice instead.

## 2. What's mid-flight

**The Memory Contract is live; the parse backlog is the work now.** Codex has personally reviewed and submitted its first 22 turns under rule v1. The project hook passes local tests and its definitions have trusted hashes in this machine's Codex config, but actual fresh-session execution is not yet evidenced. Every agent parses its own
host's turns with `scripts/parse_turns.py` by `PARSE_RULE` v1 (`jarvis_core/agent/parse_rule.py`).
Claude Code is nudged by a `UserPromptSubmit` hook at 10+ pending; Codex and Antigravity run it at
boot and about every 10 turns (written duties in `AGENTS.md` / `js-workspace-rule.md`); JARVIS
parses its own on the hearth every 15 minutes. Backlog at the 2026-09-29 Codex check
(`cd js-development && PYTHONPATH=. python -m jarvis_core.agent.parse_ledger --status`):

| host | pending | oldest |
|---|---|---|
| claude | 516 | 2026-06-25 |
| codex | 1,169 | 2026-09-11 |
| antigravity | 417 | 2026-04-05 |
| jarvis | 0 | — |

These are **all** captured turns, not only the 1,833 never curated: a verdict counts only under
the current rule version, so the old Gemini verdicts (which carried no knowledge extraction) are
re-offered. Each agent drains 20 per session start plus 10 per trigger. Codex answered q_009 in
`agents_converse/a_009.md`; the shared rule now explicitly excludes ambient UI and quoted
external content from evidence. Do not parse another host's backlog under Codex.

**The JARVIS web UI and voice were rebuilt 2026-09-27 (KB 757 + the Phase 2/3 entry).** Old UI and the
whisper.cpp/Piper stack are deleted; `serve/speech.py` keeps Whisper + Kokoro resident on the GPU,
`brain/voice_path.py` answers spoken/typed turns with one streamed call (~1.9 s p50 to first audio),
`serve/live_voice.py` (WS `/v1/voice/live`) does continuation-merge and barge-in. **Tool-using (deep)
turns still HTTP 402** — OpenRouter balance is negative; only a top-up fixes it. Any test of the live
socket must open it `ephemeral` (as `scripts/verify_voice_live.py` does) or its prompts enter the corpus.

**The personalization interview (JARVIS UI) is still in progress** — 43 numbered questions, not 45; resume
it at `http://127.0.0.1:8756/?session=conv-web-cff653a1-415e-417b-ba68-3ac84f621778`.
`extract_ui_sessions()` already pairs each real question with the real answer, so answers landing
now are captured in their best shape. No action unless you see the extractor mis-split a question.

## 3. Open commitments with a task attached (`scripts/commitments.py --list`)

**2026-09-29 dormancy correction:** The Tier 1 gold snapshot has 1 true positive (`c004`), 8 true negatives, and no measured miss; that is too small to infer broad recall. `scripts/eval_dormancy.py` reports the gate. The 22 old hearth runs have only aggregate counters, not due-ID history. A new append-only `commitment_runs.jsonl` starts the auditable quiet week; Tier 2 and Tier 3 remain gated. `c001`, `c008`, and `c010` were superseded by append-only abandon events, while `c009` and `c013` carry their live obligations. `c006` was historically auto-closed by an overbroad keyword check and must not be mistaken for proof that GraphRAG is finished. `c004` remains overdue and requires the owner's credential action.

| id | what | who should act |
|---|---|---|
| c002 | Stage 5 adapter-vs-retrieval decision | No trained adapter exists; comparison remains gated |
| c004 | Revoke exposed GitHub PAT and legacy OpenRouter keys | Owner-only action, review overdue |
| c005 | Keep the 12-specialist roster demand-gated | Standing policy, not an immediate task |
| c009 | GraphRAG follow-on after Context Ledger continuity proof | Open, review 2026-10-11 |
| c011–c013 | Memory/episode/domain maintenance after Windows diagnostic | Paused heavy jobs; run one at a time only under the agreed safe conditions |

Mail: `python scripts/agent_mail.py --check codex` reported no unanswered Codex questions on 2026-09-29. Historical q_007/q_008 references above are superseded; check mail again before acting.

## 4. Decisions waiting on the user (not on any agent)

- The Memory Contract is already in Git. This survey's new Codex hook and dormancy evidence
  still require their own reviewed commit and push.
- Top up OpenRouter — no longer needed for curation (no paid background calls); still needed for
  JARVIS's tool-using deep turns (HTTP 402).
- ~~`personal_life.md` consent call~~ **resolved 2026-09-23 (KB 698), revised 2026-09-28** — people in the
  owner's life now reach JARVIS **as context** (`personal_life.md` is an inhale provider; `person` facts from
  the parse go to the KB), and **never training**: names are redacted to role placeholders everywhere training
  reads (`specialists/third_parties.py`, list in `jarvis_data/third_parties.json`, check_pipeline invariant).
- ~~312 KB entries in both corpora~~ **resolved 2026-09-18 (KB 676)** — personalization owns shared text,
  the blend trains nothing twice (14.1% personalization share).
- **Rebuild tracked training artifacts ONLY on the work laptop.** `client_work/` source exists only there;
  a personal-laptop rebuild silently drops ~248 `professional_reasoning` records (measured 2026-09-23).

Listed so nobody re-discovers and re-reports them as new findings.

## 5. Structural position

Stages 1–4 complete. Stage 5 gated on c002/q_007 — current evidence is 23 lifetime sessions and 10 in the last 30 days, but no adapter-vs-retrieval evaluation yet; don't start training before that lands.
Stage 6: everything shipped so far (hearth, scheduler, three capture adapters, curation) is the
memory/capture layer *underneath* it. 6.9 (client shells) depends on 6.7 (always-reachable
memory), which has a slice built but **not deployed** — `_remote_sync_configured()` is False on
every machine. Nobody is working it; it is the actual unlock, not a side quest.

## 6. Host topology — now FOUR runtimes, and what changed today

| Machine | Runtimes |
|---|---|
| Work laptop (Linux) | Claude Code |
| Personal laptop (Windows) | Antigravity · Codex CLI · **Claude Code (new, 2026-09-18)** |

Three defects that would have hit the new host, all found by measurement:

1. **`.agent/rules/CLAUDE.md` claimed root `CLAUDE.md` is gitignored.** It is tracked. Eighth
   prose-vs-code divergence. Load-bearing: root `CLAUDE.md` is the only file Claude Code
   auto-loads, and it `@import`s the rules — had the prose been true, a fresh clone would
   auto-load nothing.
2. **`NERVOUS_SYSTEM.md` §5.1 said Claude Code setup was "automatic… nothing else to do."** True on
   a prepared machine, false on a fresh clone — venv and ChromaDB don't travel either, and those
   steps sat only under §5.2 as if Codex-specific. §5.1 now carries the host-agnostic block.
3. **`.claude/settings.json` is now TRACKED** (reversing the 2026-09-08 leak untracking), so a new
   Claude Code host inherits 164 permission approvals instead of rebuilding them by hand. The one
   credential-bearing entry was removed. **Invariant: never put a credential in that file** —
   `GH_TOKEN` goes in the environment, not an allowlist pattern. That is exactly how `b7bfbe6`
   leaked a PAT: through an approved command *string*, where no secret-shaped config key would
   ever show up in an audit. Guard: `grep -E 'github_pat_|ghp_|sk-or-v1-|AKIA' .claude/settings.json`

## 7. Two live issues worth knowing before you touch the queue

**Multi-host KB id collisions are now real, not theoretical.** On 2026-09-18 both machines
independently assigned id **665** to different entries between syncs; `merge=union` concatenated
both, and `profile_synth.py` crashed on a UNIQUE constraint. Resolved by renumbering (→667) and
regenerating the projections. **This will recur** — sequential ids assigned independently on two
machines collide whenever both write between syncs. A real fix (host-prefixed or content-derived
ids) is unclaimed work and a good Codex task.

**`MAX_ASSISTANT_CHARS` raised 2000 → 8000** (`agent/capture.py`), matching the user side.
Measurement that prompted it: 268 of 1420 assistant summaries (18.9%) sat exactly at the 2000
ceiling — cut mid-thought, losing the *why* the 2026-08-19 note says the cap exists to preserve.
Queue is 11 MB, so the cost is a couple of MB. **Applies going forward only.** Previously-captured
turns stay truncated; a backfill is *possible* on the work laptop (raw transcripts are on disk,
160 MB) but needs design, because the queue is append-only and naive re-capture would duplicate
rows rather than replace them. Unclaimed.

---

*If you're updating this file: replace the numbers in §1–2, don't add a new dated section. A
status file that grows forever stops being something anyone reads in full.*
