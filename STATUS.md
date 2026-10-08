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

**Yes: 10 breaches** (`python3 scripts/pipeline_health.py`, silent when healthy). They reduce to four causes:

- **Parse backlog, by design of the host topology.** `python3 scripts/parse_turns.py --status`:
  claude 0, codex 951 (oldest 2026-09-13), antigravity 167 (oldest 2026-05-21), jarvis 0. The
  Codex and Antigravity hosts live on the dead laptop; Claude parses their backlogs by reading
  (KB 1009, 1045). Codex's own session may only parse Codex turns.
- **Corpora 2.9 days old (limit 48 h), six artifacts, and a stale vector index.** `rebuild_corpora`,
  `reindex_memory`, `index_episodes`, `relabel_domains` and `run_all_tests` are paused (section 4).
  `chromadb/jarvis_memory` holds 661 entries against 1085 in the KB. Search results come from an older mind than the log holds.
- **`check_pipeline.py` reports 1 failed** (`python3 scripts/check_pipeline.py`; 29 ok, 0 unmeasurable):
  8 retracted records are still inside the built corpora. Only the paused rebuild clears it. This is also why the hearth job `check_pipeline` shows FAILED.
- **OpenRouter balance is negative.** Tool-using deep turns return HTTP 402. Owner.

Hearth (`python3 scripts/hearth.py --status`): UP on 127.0.0.1:8756, Chroma supervised by it on
127.0.0.1:8759 (single-owner design); every other clocked job reports ok except the paused or
failing ones named above. `python3 scripts/bootstrap_jarvis.py --check` shows the machine view.

## 2. What's mid-flight

**The Memory Contract is live.** One parse rule (`jarvis_core/agent/parse_rule.py`), no paid background
calls. `python3 scripts/parse_turns.py --routing`: 1507 turns routed, 428 trainable; verdicts under
rule v1 by agent: claude 1103, antigravity 320, codex 50, jarvis 31.

**The personal laptop has been dead since 2026-10-06 (KB 1044).** The work laptop is under an owner
rule not to take heavy load (7.6 GB RAM, no GPU). `jarvis_data/.paused_jobs` pauses `run_all_tests`,
`rebuild_corpora`, `index_episodes`, `reindex_memory`, `relabel_domains`; light jobs, shard archiving and the web UI run on.

**Hosting.** Railway was deployed, then put to sleep 2026-09-12 to avoid cost (KB 1190); its volume was kept.
The hearth and web UI run locally at 127.0.0.1:8756, restarted by cron (every 10 min and at reboot); token is `jarvis_data/.hearth_token`.
Nothing is reachable from a phone. The hosting strategy is the owner's call (section 4).

**The personalization interview.** 43 numbered questions; only Q1-Q5 are answered. On 2026-09-26 a free
model wrote both sides of Q6 in the owner's voice (KB 1201). `brain/interview_guard.py` now prevents it. The
poisoned copies (KB 735 and one conversation turn) are listed in `jarvis_data/retractions.jsonl`, and every corpus builder and
the retrieval index skip them. The already-built corpora still contain them until the rebuild runs (section 1).

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
| c011-c013 | Run `index_episodes`, `relabel_domains`, `reindex_memory` by hand, one at a time | paused by owner rule; c013 explicitly does not rebuild `research_papers` |

c001, c008 and c010 were abandoned by append-only events; c006 was auto-closed by an overbroad keyword
check and is not proof GraphRAG is finished. Dormancy: `scripts/eval_dormancy.py` reports the Tier 1 gate; `commitment_runs.jsonl` is the quiet-week record.

**Mail** (`python3 scripts/agent_mail.py --list`): q_046, q_047 and q_048, all Claude to Codex, are open and wait for the dead laptop. Everything else is answered.

## 4. Decisions waiting on the user (not on any agent)

- **Answer the 25 c002 personalization questions** in the private answers file (outside the repo; agents are denied access). Edit it in an editor, never in a chat.
- **Top up OpenRouter.** The c002 judges and reference arm are paid, and deep turns fail with 402 without it.
- **Set c002 T0, and decide whether `client_work` content may be used in training.** The push rule was relaxed 2026-10-06; training use was never decided.
- **Rebuild versus pause (conflict, not resolved here).** Rule A (measured 2026-09-23): tracked training artifacts must be rebuilt only on the work laptop, because `client_work/` source exists only there and a personal-laptop rebuild silently drops about 248 `professional_reasoning` records. Rule B (KB 1044/1045, 2026-10-06): the work laptop must not take heavy load, so `rebuild_corpora` is paused there, and the personal laptop is dead. Result today: nobody can rebuild, the corpora are 2.9 days old, 8 retracted records remain in them, and the c002 leakage audit cannot pass.
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
