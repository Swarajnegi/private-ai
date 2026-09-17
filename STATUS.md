# STATUS — read this before starting work, not after

> Written by whichever agent last surveyed the whole build, so the other two don't have to
> re-derive it from scratch on their next session. **Update this file, don't append to it** — it
> is a snapshot, not a log. If something below is stale by the time you read it, fix it and say
> so in your commit message; don't leave a wrong number here because it was true once.

**Last surveyed:** 2026-09-17, by claude (Sonnet 5)
**Since the last survey (2026-09-15):** q_007 (Stage 5 gate) and q_008 (commitments unwired) were
sent to Codex — both are new findings from this file's previous version, so read those two files
in full before doing anything else if you are Codex. a_005 and a_006 came back from Antigravity in
the meantime (curation verdicts audited — sound; Antigravity built its own capture adapter). No
code changed in this session; this is a pure status write.

---

## 1. Is anything broken right now?

**No.** `check_pipeline.py` — 12 invariants, 12 OK, 0 failed, 0 unmeasurable. `run_all_tests.py`
runs every discovered suite on the hearth's clock. If you're arriving fresh and want to verify
that claim yourself rather than trust it: `python3 scripts/check_pipeline.py` and
`python3 scripts/run_all_tests.py --status`.

## 2. What's mid-flight

**Curation is stalled on credits, not on code.** `curate_turns --status`:

```
capture queue        : 1403 turns
curated by an agent  : 533
uncurated            : 870
```

OpenRouter balance is too low to run the curator's judge calls; it has been failing loudly
(HTTP 402) rather than falling back to a weaker free model — that's the user's explicit choice,
not a bug. **Nothing to fix here.** It resumes by itself, on the hourly clock, the moment the
user tops up. Don't build a workaround; don't re-litigate the fail-loudly decision.

**The 45-question personalization interview (JARVIS UI) is in progress.** The user is answering
these directly over several days. `build_sft_pairs.py` now has a dedicated `extract_ui_sessions()`
extractor (shipped 2026-09-15/16) that pairs each real question with the real answer rather than
substituting a synthetic prompt — so answers landing now are captured in their best shape already.
No action needed unless you find the extractor mis-splitting a question; if so, say so here.

## 3. Open commitments (`scripts/commitments.py --list`) — the ones with a task attached

| id | what | who should act |
|---|---|---|
| c002 | Resolve Stage 5 adapter-vs-retrieval decision | **Codex — this is q_007.** Answerable now: the retrieval/surfacing path can be measured against the live 45-question corpus instead of argued about in the abstract. |
| c007 | `a_001.md` exists (Antigravity answered it, built the adapter) but nothing runs this check — it should already be closed | **Codex — this is half of q_008.** Wire commitment checks to a hearth job; this one closes itself the moment that job runs once. |
| c005 | Keep the 12-specialist roster demand-gated | No action — this is a standing policy commitment (re-check on schedule), not a task. |
| GraphRAG (c001/c006/c008/c009) | Same underlying work recorded in **four** inconsistent states (abandoned/resolved/abandoned/open) | **Codex — other half of q_008.** Reconcile to one truthful current state; the build itself (`scripts/build_graphrag.py`, `rebuild_graphrag` hearth job, 648 nodes/55 edges) is real and already shipped, the registry just never caught up. |

Full detail and reasoning for both Codex tasks is in `agents_converse/q_007.md` and
`agents_converse/q_008.md` — this table is a pointer, not a replacement for reading them.

## 4. Decisions waiting on the user (not on any agent)

- Top up OpenRouter — unblocks curation by itself, no rerun needed.
- `personal_life.md` — consent call about named third parties, still parked.
- 312 KB entries counted in both `engineer_corpus` and `personalization_corpus` — may be correct
  (a `Decision` can genuinely be both technical and personal) but nobody has actually decided that;
  it just happens.

Don't chase these — they're listed so nobody re-discovers and re-reports them as new findings.

## 5. Where things stand structurally

- Stages 1–4: complete. Stage 5 (specialists): gated on c002/q_007 above — don't start training
  before that answer lands.
- Stage 6 (voice, vision, unified API, client shells, ambient presence): everything shipped so far
  (hearth, scheduler, capture adapters on all three hosts, curation) is the memory/capture layer
  underneath it. 6.9 (client shells) depends on 6.7 (always-reachable memory), which has a slice
  built but not deployed — `_remote_sync_configured()` returns False on every machine right now.
  Nobody is actively working this; flag it here so the next agent with spare cycles knows it's the
  actual unlock, not a side quest.

## 6. Capture health across the three hosts

All three adapters (Claude Code hooks, `ingest_codex_sessions.py`, `ingest_antigravity_sessions.py`)
are live and scheduled on the hearth. Zero hosts degraded. This was the state of things as of
a_006 (2026-09-14) and hasn't changed since.

---

*If you're the one updating this file: replace §1–2's numbers, don't just add a new dated
section. A status file that grows forever stops being something anyone reads in full.*
