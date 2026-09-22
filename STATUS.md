# STATUS — read this before starting work, not after

> Written by whichever agent last surveyed the whole build, so the other two don't have to
> re-derive it from scratch on their next session. **Update this file, don't append to it** — it
> is a snapshot, not a log. If something below is stale by the time you read it, fix it and say
> so in your commit message; don't leave a wrong number here because it was true once.

**Last surveyed:** 2026-09-22, by codex
**Since the last survey (2026-09-17):** a **second Claude Code host** came online — the user's
personal laptop, running Claude Code inside Antigravity, against this same repo. Most of today's
changes exist to make that host arrive fully-equipped rather than half-blind. Three onboarding
defects were found by measuring rather than reading, and all three are fixed (§6).

---

## 1. Is anything broken right now?

**No.** `check_pipeline.py` — 12 invariants, 12 OK, 0 failed, 0 unmeasurable. Verify rather than
trust: `python3 scripts/check_pipeline.py`, `python3 scripts/run_all_tests.py --status`.

## 2. What's mid-flight

**Curation is stalled on credits, not on code.** 1420 turns captured, 533 curated, **887
uncurated**. OpenRouter balance is too low for the judge calls; it fails loudly (HTTP 402) rather
than silently falling back to a weaker model — the user's explicit choice. **Nothing to fix.** It
resumes by itself on the hourly clock when they top up. Don't build a workaround.

**The 45-question personalization interview (JARVIS UI) is still in progress**, several days in.
`extract_ui_sessions()` already pairs each real question with the real answer, so answers landing
now are captured in their best shape. No action unless you see the extractor mis-split a question.

## 3. Open commitments with a task attached (`scripts/commitments.py --list`)

| id | what | who should act |
|---|---|---|
| c002 | Stage 5 adapter-vs-retrieval decision | **Codex — this is q_007.** Answerable now against the live interview corpus rather than in the abstract |
| c007 | `a_001.md` exists, so this should already be closed — but nothing runs the check | **Codex — half of q_008.** Wire commitment checks to a hearth job; this closes itself on the first run |
| c005 | Keep the 12-specialist roster demand-gated | No action — standing policy, not a task |
| GraphRAG (c001/c006/c008/c009) | One body of work recorded in **four** inconsistent states | **Codex — other half of q_008.** The build shipped (`rebuild_graphrag`, 648 nodes/55 edges); only the registry lagged |

Mail: **q_004 is dead** (Antigravity built that adapter itself — see a_006; ignore it).
**q_007 and q_008 are open and both Codex's.** Read them in full before acting on the table above.

## 4. Decisions waiting on the user (not on any agent)

- Top up OpenRouter — unblocks curation with no rerun needed.
- `personal_life.md` — consent call about named third parties, still parked.
- 312 KB entries counted in both corpora — possibly correct, but never actually decided.

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
