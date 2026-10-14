# STATUS — read this before starting work, not after

> Written by whichever agent last surveyed the whole build, so the other two don't have to
> re-derive it from scratch on their next session. **Update this file, don't append to it** — it
> is a snapshot, not a log. If something below is stale by the time you read it, fix it and say
> so in your commit message; don't leave a wrong number here because it was true once.

**Last surveyed:** 2026-10-08, by Claude (Sonnet 5.5), from the commands named in each section. Every
number below is a command's output on that day; re-run the command, don't trust the digit.
Companion checklist: [MASTER_CHECKLIST.md](MASTER_CHECKLIST.md) (the fuller to-do view; this file is the cross-agent snapshot).
**Since the 2026-09-29 survey:** the personal laptop died (2026-10-06), heavy jobs were paused on
the work laptop, the c002 evaluation harness was built (nothing measured), JARVIS was caught
answering its own interview question, and the research papers were removed (2026-10-08).

---

## 1. Is anything broken right now?

**Active-host maintenance update, 2026-10-13 (Codex).** The native Windows
host at `D:\J.A.R.V.I.S` is the owner's girlfriend's HP OMEN: i7-10750H,
16 GB RAM, RTX 2060 with 6 GB VRAM. Current model work uses CPU-only Torch.
Voice is restored locally. The 2026-10-13 UI recovery repair separates long
transcripts from engine details and shortcuts, adds Stop, and cancels the old
request before switching sessions. The particle renderer and its geometry are
unchanged. Offline recovery tests, four browser widths and two uncaptured live
voice-path answers passed.

- Memory indexing validated against all 1,133 KB entries (1,930 chunks).
- Domain labelling validated against 2,709 captured turns.
- Corpus rebuilding passed all 30 pipeline invariants, removing the eight
  retracted built records. The 947-record client snapshot is byte-for-byte intact.
- Episode indexing validated on three real sources (254 dense vectors);
  the remaining historical sources still need incremental catch-up.
- The fast-suite runner now selects offline flags and positional self-test
  subcommands correctly, including mail hooks, rather than their live paths.
- All five maintenance jobs are enabled after validation; Hearth was restarted
  through its existing watchdog and local speech synthesis/transcription passed.
- Scheduling now serializes every scheduled job and the five manual maintenance
  commands through a shared lease and Windows process-tree supervision. Heavy
  starts require mains power and 4 GiB free RAM; resource deferrals are visible.

These measurements update maintenance on this host, not the older global
Stage 5 survey below. Codex's individually reviewed backlog remains open;
no bulk verdicts were submitted during this maintenance repair.

**Milestone 1 training protection, 2026-10-14 (Codex).** The independent
review registry and shared eligibility gate are implemented across engineer,
personalization, blend, both SFT exports, pipeline health and the Stage 5
training audit. The existing parse rule, source records and retrieval are
unchanged. Eleven October 13 sources were individually reviewed: eight rejected,
three approved; 122 other JARVIS source identities remain pending. Owner-only
extracts and verified owner-supported facts are preserved. Six behavioural
baseline cases are recorded in `jarvis_data/eval/milestone1/baseline.json`;
five were unresolved at that baseline and ambiguous transcription has no
original audio; the Milestone 2 update below records the verified repairs.

Production verification passed through the exclusive supervisor: all five
exports contain zero ineligible records and all 36 pipeline checks pass. The
final rebuild took 64.11 seconds, with 5.41 GiB minimum available RAM and
248.11 MiB peak process-tree commit. The 947-record client snapshot retains
SHA-256 `2cdeb358d8eb5d4580265673fbc4e514b453e1607fffb72a54615b2a270529f0`.
Codex fixed a shared-metadata alias discovered by the final hash check and added
a regression proving review metadata never changes snapshot bytes. Hearth was
restarted through its watchdog; UI and CPU voice capabilities are available,
with no voice errors. Capture is listed and the dry-run reports no completed
exchanges awaiting ingestion. Live review state is a hold (122 pending), with
all five artifact audits OK. Core renderer and frontend sources are unchanged.
Offline checks: 22 review/export/writer tests plus 20 reviewed Antigravity
regression tests, 33 pipeline tests, 25 pipeline-health tests,
230 Stage 5 harness checks, 46 scheduler checks, 13 maintenance-policy checks,
and nine rebuild-chain checks pass, along with retraction/evaluation exclusions.
Antigravity answered q056 and q057 with 20 passing fixture tests. Codex read the
complete test file, removed its hardcoded root/temp fallback, strengthened the
three-host and all-five-artifact assertions, and reran all 20 successfully.
Only its bounded test source and mail evidence are integrated; it changed no
policy, production records, dependencies or schedules.

The scheduled episode-index catch-up reached the existing 30-minute limit,
recorded rc=124 and confirmed process-tree cleanup; its partial progress is
retained and its six-hour failure retry remains in force. That warning is
accurate and was not cleared by the corpus repair. Codex parse backlog and
older training-readiness/evaluation work remain separate. Milestone 1's quality
gate, reviewed exclusions, production audits and behavioural baseline are closed;
behavioural repairs continue below. Generated corpus files and unrelated
memory updates remain unstaged; only reviewed milestone sources/records/docs are
included in the local commit.

**Milestone 2 harness closed, 2026-10-14 (Codex).** Interactive
requests now construct runtime inspection, native PowerShell, text creation/
editing and public-web tools. Arguments are normalized before permission;
verified read-only inspection runs automatically and mutations need individual
approval. PowerShell uses its native parser and uncertain pipelines need
approval. File edits bind the complete SHA-256 and unique replacement, preserve
line endings/encoding, and cannot directly rewrite authoritative stores.
Current host inspection measured i7-10750H, 15.842 GiB RAM, RTX 2060 with
6,144 MiB VRAM, cloud brain and CPU voice/embeddings. Unavailable measurements
stay unknown. Optional web-search SDK absence uses the tested native RSS
fallback; no dependencies, CUDA or models were installed.

Authenticated HTTP/voice approvals bind the exact action, request and session;
one-time decisions expire ten minutes after issuance. Reconnect restores the
same pending approval. Terminal prompts follow the same policy, unattended
changes are denied and API/CLI `allow_all` cannot bypass approval. The dialogue
header now has Terminate, also visible when folded. Escape and New conversation
use the same cancellation/cleanup path. Windows Job Objects supervise tool
trees; unconfirmed cleanup keeps Hearth busy rather than admitting another
request. Completed file changes are reported accurately after termination and
are retained; cancellation is not rollback. Identical unchanged reads reuse
verified observations within a request.
Core renderer/size, landing and Sessions/System layouts remain unchanged.

Verification: 30 reviewed Antigravity tool tests (q058/q059), 19 Codex harness
tests, 124 ReAct, 105 orchestrator, 42 Hearth, 46 scheduler, 25 health, 33
pipeline, nine live-voice and six recovery checks pass. Desktop 1440x900 and
mobile 390x844 browser fixtures passed all 13 approval/reconnect/keyboard/
Terminate/New conversation checks using real dispatch, broker and processes.
TypeScript and production build pass; the served bundle was rebuilt. Live
Hearth verified file discovery, approved scratch creation, accurate denial and
current runtime inspection. The provider blocker is repaired: Apodex's free ID
is absent from the current public catalog and its endpoint list is empty;
the same key successfully calls `openrouter/free` at zero cost. Environment-
default free-model requests now use the existing fallback pool. The configured
primary remains unchanged; no paid fallback was added. Injected clients,
explicit targets and paid defaults preserve their existing contracts; built
pool targets now retain the requested reasoning effort and shared budget.
Runtime inspection reports the configured primary and active API route
separately; a router alias is not claimed to identify its underlying model.
Added checks prove default 404 recovery and preserved routing/cost policy;
16 target, 41 model-pool and 34 LLM-client checks pass.

Production closure passed using the configured default path: approved edit
preserved CRLF, the exact PowerShell worker was observed under Hearth, cancellation
removed that worker, and a fresh question returned 323. Hearth is idle with
confirmed cleanup and warm CPU voice. These live checks are uncaptured and
all artifacts remain on D. Evidence: `openrouter-diagnosis.json` and
`live-execution-results.json` under `.runtime/milestone2/`.

Verification also repaired `capture=False`: it now skips conversation history
and terminal-state persistence as well as queue/KB writes. Five identifiable
test conversation files from the earlier bug were moved intact, with hashes,
to `.runtime/milestone2/captured-test-records/`; no owner conversation was
changed. Baseline B01's fresh-inspection route and B03's error distinction are
verified; B04's duplicate-read subcase is repaired, broader search/task loops
remain open. Performance calibration, durable continuity and speech accuracy
remain later milestones. A model that exhausts its loop with another tool call
now returns an honest incomplete result; this does not repair its decision
quality. Training review protections, client snapshot and maintenance schedules
are preserved. Evidence is under `.runtime/milestone2/`; local commit only.
An extra live probe produced a promise to execute a command without a tool
call. This remains a model-decision regression for the later decision-quality
milestone, recorded in the baseline; successful tool/cancellation checks do not
prove that every model follows every natural-language instruction.

## 2. What's mid-flight

**The Memory Contract is live.** One parse rule (`jarvis_core/agent/parse_rule.py`), no paid background
calls. `python3 scripts/parse_turns.py --routing`: 1507 turns routed, 428 trainable; verdicts under
rule v1 by agent: claude 1103, antigravity 320, codex 50, jarvis 31.

**The work laptop is retired as a JARVIS host.** Codex and Antigravity now
use the native Windows D-drive checkout. The owner authorized enabling the
five maintenance jobs after bounded validation on 2026-10-13. The pause registry
and live health report are authoritative for activation and any subsequent pause.

**Hosting.** Railway was deployed, then put to sleep 2026-09-12 to avoid cost (KB 1190); its volume was kept.
The hearth and web UI run locally at 127.0.0.1:8756, restarted by the existing Windows watchdog at sign-in; token is `jarvis_data/.hearth_token`.
Nothing is reachable from a phone. The hosting strategy is the owner's call (section 4).

**The personalization interview.** 43 numbered questions; only Q1-Q5 are answered. On 2026-09-26 a free
model wrote both sides of Q6 in the owner's voice (KB 1201). `brain/interview_guard.py` now prevents it. The
poisoned copies (KB 735 and one conversation turn) are listed in `jarvis_data/retractions.jsonl`, and every corpus builder and
the retrieval index skip them. The 2026-10-13 rebuild removed the retracted material from the built corpora.

**c002, the Stage 5 adapter-versus-retrieval test (₹0): harness built, nothing measured.**
`scripts/eval_c002.py` landed 2026-10-07 in commit 56884ab: 230 hermetic self-checks; an independent review
found 20 defects, all fixed. `jarvis_data/eval/c002/` holds the protocol (unlocked), endpoints, 72 engineering items,
25 personalization questions and the exclusions registry. The leakage audit FAILS today, correctly: eval
markers sit in three corpora (legacy), and four recall tuning questions (`ms-02`, `ms-08`, `t-01`, `t-12`) appear
verbatim in training. None of the 40 frozen held-out items leaked. Adapter arms refuse to run until the audit passes.
Never tested here: the real router provider, index builder, tokenizer, live endpoints.

**Research papers and their Chroma collection were removed 2026-10-08 (owner decision).** `research_papers` is no longer rebuilt anywhere.

**GraphRAG v0** is built locally: 1,098 nodes, 92 edges (`jarvis_data/graph_index.json`, rebuilt by the hearth job `rebuild_graphrag`).
Proof that the Context Ledger carries continuity is still pending (c009).

## 3. Open commitments (`python3 scripts/commitments.py --list`)

| id | what | state |
|---|---|---|
| c002 | Stage 5 adapter-vs-retrieval decision (review 2026-10-11) | harness built, no measurement; needs owner input (section 4) |
| c004 | Revoke exposed GitHub PAT and legacy OpenRouter keys | owner-only; review overdue since 2026-09-12; owner said to leave it (2026-10-06) |
| c005 | Keep the 12-specialist roster demand-gated | standing policy, not a task |
| c009 | GraphRAG follow-on after Context Ledger proof (review 2026-10-11) | open |
| c011-c013 | Run `index_episodes`, `relabel_domains`, `reindex_memory` by hand, one at a time | guarded CPU maintenance authorized 2026-10-13; initial episode catch-up remains; c013 does not rebuild `research_papers` |

c001, c008 and c010 were abandoned by append-only events; c006 was auto-closed by an overbroad keyword
check and is not proof GraphRAG is finished. Dormancy: `scripts/eval_dormancy.py` reports the Tier 1 gate; `commitment_runs.jsonl` is the quiet-week record.

**Mail** (`python3 scripts/agent_mail.py --list`): q_046, q_047 and q_048, all Claude to Codex, are open and wait for the dead laptop. Everything else is answered.

## 4. Decisions waiting on the user (not on any agent)

- **Answer the 25 c002 personalization questions** in the private answers file (outside the repo; agents are denied access). Edit it in an editor, never in a chat.
- **Top up OpenRouter.** The c002 judges and reference arm are paid, and deep turns fail with 402 without it.
- **Set c002 T0, and decide whether `client_work` content may be used in training.** The push rule was relaxed 2026-10-06; training use was never decided.
- **Rebuild versus pause is resolved on the active host.** The owner approved
  guarded CPU maintenance on 2026-10-13. The corpus rebuild preserves the client
  snapshot when raw client source is absent. It does not authorize training.
- **Finish the interview** (Q6-Q43). It is training data; it does not replace the 25 c002 answers.
- **Custom PC build gates** (see MASTER_CHECKLIST section I): nothing is bought until the evaluation and a cloud pilot say so.
- **Hosting strategy** (pay for always-on, tunnel to a home machine, or self-host on the planned PC).
- `git push origin main` after each run of commits. Agent pushes are blocked by the classifier; never push `backup-local-main`.

Settled, listed so nobody re-reports them: `personal_life.md` reaches JARVIS as context but never training (KB 698, revised 2026-09-28); shared KB text is owned by personalization so the blend trains nothing twice (KB 676).

## 5. Structural position

Stages 1-4 complete. Stage 5 is gated on c002: `usage.read_usage()` (from `jarvis_core.brain`) prints lifetime
`--ask` sessions 3, last 2026-09-14, 23 days ago; no adapter exists and the comparison has not been run, so do not start training.
Stage 6: the hearth, scheduler, three capture adapters and the voice stack are the memory/capture layer underneath it. 6.9 (client shells) depends on 6.7
(always-reachable memory), which exists as code and as a sleeping hosted copy (above). Nobody is working it.

## 6. Host topology

| Machine | Runtimes | State |
|---|---|---|
| Work laptop (Linux) | Claude Code | the only live host; hearth + web UI run here |
| Personal laptop (Windows) | Antigravity, Codex CLI, Claude Code | dead since 2026-10-06 |

`.claude/settings.json` is tracked, so a new Claude Code host inherits its permission approvals.
**Invariant: never put a credential in that file** (`GH_TOKEN` belongs in the environment). Guard:
`grep -E 'github_pat_|ghp_|sk-or-v1-|AKIA' .claude/settings.json` (0 hits on 2026-10-08).

## 7. Live issues worth knowing before you touch the queue

**Multi-host KB id collisions will recur.** On 2026-09-18 both machines assigned id 665 independently;
`merge=union` kept both and `profile_synth.py` crashed on a UNIQUE constraint. Host-prefixed or content-derived ids are unclaimed work.

**No cap on captured assistant text** (`agent/capture.py`, since 2026-09-18). The old ceiling was removed
rather than raised, and re-adding one is a regression. Turns captured before then (about 19% were cut at 2000
characters) stay truncated; backfilling needs design because the queue is append-only. Unclaimed.

---

*If you're updating this file: replace the numbers in §1-2, don't add a new dated section. A
status file that grows forever stops being something anyone reads in full.*
