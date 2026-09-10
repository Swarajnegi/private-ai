# JARVIS — The Nervous System, the Inventory, and How to Run It on Any Host

> **What this file is.** Two questions have never had a written answer, and both were asked
> directly on 2026-09-11 while moving primary development to Codex:
> 1. *How does every Claude chat know what the other chats said?*
> 2. *What does NOT travel via `git pull` — and how do I get it back?*
>
> Both had been answered only in conversation, which means they were answered nowhere. This file
> is the answer, and it is tracked so it arrives with the code it describes.
>
> **Audience:** any agent or human operating JARVIS on any machine. Codex-first (that is the host
> that most needs it), but Claude Code and Antigravity are covered too.

---

## 0. How to read this file, and why it has so few numbers

This project has now caught **twelve** instances of *prose declaring X while the code does not-X*.
The list includes `.agent/rules/CLAUDE.md` claiming ChromaDB "is never committed" (it is),
`.gitignore` claiming the research PDFs are ignored (all 24 are tracked), `recall.py` claiming
"the raw queue stays local" (it is committed and pushed), and — most instructively —
`capture_turn.py`'s own docstring describing itself as "~40 lines" with "18 smoke tests" when it
was neither. A file could not describe *itself* accurately, because the description was written
once and the file kept changing.

Every one of those started life *true*. They rotted because a number was written down in a place
nothing re-checks.

**So this document does not hardcode counts, sizes, or line numbers.** It anchors on **function
and constant names**, which drift far more slowly, and gives you a **command to run** for anything
that changes. Where a number appears, it is dated and marked as a snapshot.

If you are about to add a count to this file: don't. Add the command that prints it.

---

## 1. The mechanism — how every chat knows every other chat

**One sentence:** a `Stop` hook appends every turn of every chat to one append-only JSONL file;
three `SessionStart` hooks read that file (plus two derived artifacts) back into the next chat as
`additionalContext`. There is no server, no daemon, and no database.

```
Claude Code turn ends
  └─ Stop ──→ capture_turn.py ──→ capture.py::capture_stop_event()
  │              reads event.transcript_path, appends ONE line
  │              → jarvis_data/observation_queue.jsonl          [git-TRACKED]
  └─ Stop ──→ run_consolidation.py ──→ scripts/consolidate.py
                 drains queue → jarvis_data/life_state_feed.jsonl

New session starts
  ├─ SessionStart → inject_profile.py         → cognitive_profile.md
  ├─ SessionStart → surface_life_state.py     → life_state_feed.jsonl
  └─ SessionStart → inject_recent_activity.py → recall.py digest (7 days)
        all three emit:
        {"hookSpecificOutput": {"hookEventName": …, "additionalContext": …}}
```

**`additionalContext` is the entire injection mechanism.** Nothing else makes the model "know."
If you are porting to a new host, that string is what you must reproduce — whatever channel your
host offers for putting text in front of the model before it answers.

### 1.1 The committed wiring recipe

`.agent/hooks.manifest.json` is the **canonical, committed** declaration of every hook.
`.claude/settings.json` is machine-local and gitignored — the manifest is what it gets rehydrated
*from*, by `python3 scripts/bootstrap_jarvis.py`.

This split exists because hook registrations once lived *only* in the gitignored settings file, so
`git pull` on a new machine produced, in that file's own words, "a brain in a jar."

```bash
python3 scripts/bootstrap_jarvis.py --check   # what is missing here? changes nothing
python3 scripts/bootstrap_jarvis.py           # install missing hooks; idempotent, non-destructive
```

It merges per `(event, matcher)` group, identifies a hook by `(type, command, args)`, and appends
only what is absent — your local permissions, env vars and extra local hooks survive untouched.
It also regenerates `cognitive_profile.md` and `activity_digest.md`, but **only if missing**, and
never blanks a synced digest on a machine with no local capture.

**Rule:** any new awareness feature adds its registration to the manifest — core organ + thin
adapter + committed manifest entry. Never only in local settings.

### 1.2 The seven hooks

| Event | Script | What it does |
|---|---|---|
| `UserPromptSubmit` | `notice_runtime_change.py` | Tail-reads the transcript to detect a mid-session `/model` swap; emits a `RUNTIME SELF-STATE` line **only on change**. State in `.runtime_state.json`, flock'd. |
| `UserPromptSubmit` | `capture_gap_nudge.py` | Counts queue turns newer than the newest KB timestamp; nudges once the uncaptured gap crosses `_NUDGE_THRESHOLD`, escalating at `_ESCALATE_AT`. Reads only. |
| `Stop` | `capture_turn.py` | The write path. Thin adapter → the organ. |
| `Stop` | `run_consolidation.py` | Fire-and-forget `consolidate.py`; drains the queue into insights so the surfacing channel has fuel. Emits nothing. |
| `SessionStart` | `inject_profile.py` | Injects `cognitive_profile.md`, truncated at `_MAX_PROFILE_CHARS`, framed as background *not* instructions. |
| `SessionStart` | `surface_life_state.py` | Asks the organ for one unsurfaced high-confidence insight and advances the never-nag watermark. |
| `SessionStart` | `inject_recent_activity.py` | Injects the `_DAYS`-window cross-chat digest; **suppressed entirely** if there are no captured turns. |

Two details that are easy to get wrong:

- **`surface_life_state.py` does not build the `additionalContext` envelope.** The organ does —
  `life_state_monitor.session_start_payload()`. The hook only serializes what it is handed. That
  is the organ/adapter split working correctly, and it is why the surfacing capability is portable
  to a host with no hooks at all (see §4.2).
- **`run_consolidation.py`'s internal timeout is not the manifest's timeout.** The manifest grants
  the hook a larger budget than the subprocess is given, deliberately, so the subprocess loses the
  race and the hook always exits cleanly. Do not "simplify" them to the same number.

Every hook reads stdin JSON, **swallows all exceptions, and exits 0 unconditionally.** A broken
hook must never disrupt a turn. Preserve that discipline in any port.

### 1.3 What actually gets written

One line per turn, appended to `jarvis_data/observation_queue.jsonl`. Top-level keys:

```
ts · session_id · machine · model · cwd · chat_label
user_text · assistant_summary
tokens{input,output}
heuristic_signals{prompt_len, has_correction_markers, domain_guess}
```

- `ts` is **IST** (`+05:30`), hardcoded, not the host's timezone.
- `machine` = `$JARVIS_MACHINE` else the node name.
- `chat_label` = the basename of `cwd`. **This is what makes it "cross-chat":** chats are
  distinguished by `cwd` + `session_id`, not by any Claude-specific chat identifier — which is
  precisely why the schema ported to Codex unchanged.
- `domain_guess` is a **non-authoritative** keyword hint that abstains to `unknown`. The
  authoritative label is the embedding classifier's output in `domain_labels.jsonl`. (Legacy
  records may still carry `general` — that is history, not a live code path.)
- `tokens` are read optimistically from the event and are `null` in practice; Claude Code does not
  send them on the Stop payload.

Writes are `flock`-guarded **and** heal a missing trailing newline first. Both matter: a lock stops
concurrent writers, but does nothing about a writer that was *killed* mid-line — the next append
then joins the torn line and is destroyed with it.

```bash
wc -l jarvis_data/observation_queue.jsonl          # how many turns are captured
tail -1 jarvis_data/observation_queue.jsonl | python3 -m json.tool   # the live schema
```

---

## 2. The adapter contract — porting to a host with no hooks

This is no longer theoretical. `scripts/ingest_codex_sessions.py` is a **second working
implementation** against a different host, a different transcript format, and a different
lifecycle (no hooks at all — a scheduled reader instead). It proved the organ genuinely is
host-independent rather than merely designed to be. That closed ROADMAP 6.8.1–6.8.4.

### 2.1 Reuse this — it is host-agnostic

| Component | Where |
|---|---|
| `build_observation`, `append_observation`, `redact`, `guess_domain` | `jarvis_core/agent/capture.py` |
| The queue record schema itself | same |
| `ActivityRecaller` (digest generation) — takes a path, returns markdown | `jarvis_core/agent/recall.py` |
| `ContextInjector` + `default_providers()` — the **non-hook** injection twin, provider-based | `jarvis_core/brain/context_injector.py` |
| `LifeStateMonitor.surface()` / `session_start_payload()` | `jarvis_core/agent/life_state_monitor.py` |
| `append_entry` (KB write + dedup) | `scripts/kb_append.py` |

**No Python file anywhere resolves a `~/.claude/` path.** Everything goes through
`jarvis_core/config.py` (`JARVIS_ROOT` env var, else `parents[2]`), which is why the same source
produces correct paths on Windows and Linux without edits. Verify:

```bash
grep -rn '~/\.claude\|\.claude/projects' --include=*.py . | grep -v '^\./\.venv'
```

The only hit is a **comment in the Codex ingester asserting this very fact** — not a path. If you
ever see a second hit, the portability contract has been broken and capture has become
host-locked.

### 2.2 Re-derive this — it is Claude-Code-specific

1. **Lifecycle event names** — `Stop`, `SessionStart` (matcher `startup|resume|clear|compact`),
   `UserPromptSubmit`. `compact` in particular is a Claude Code concept.
2. **Stdin payload keys** — `transcript_path`, `session_id`, `cwd`, `stop_hook_active`.
   The hard one is `transcript_path`: capture has no other source of turn text. If your host does
   not hand you a transcript, there is nothing to parse.
3. **Transcript record shape** — `type` ∈ {user, assistant}, `isSidechain`,
   `message.content[].text`, `message.model`, and the literal `"<synthetic>"` sentinel.
4. **`_HARNESS_TAGS`** — the wrapper tags the host injects into user turns. **Codex's set is
   completely different** (`_CODEX_WRAPPER_TAGS` in the ingester). Get this wrong and the queue
   fills with harness noise instead of user prompts, because a pure-wrapper turn will look like
   real user text.

### 2.3 The one change the organ needed, and why

`build_observation` originally hardcoded "now" as the timestamp — correct for a **live** Stop hook
(the turn just ended), and wrong for **ingesting a historical transcript** written weeks ago.
Backdating every ingested turn to "now" would corrupt every timestamp-ordered consumer:
`recall.py`'s day grouping, `tension.py`'s "only the past can be a prior" filter, and the
`(ts, session_id)` key of the domain-label projection.

Rather than fork the schema by duplicating the dict construction, `build_observation` gained an
optional `ts=` override. Every existing call site is unaffected.

**Generalize this:** when a second host needs a variation, extend the organ by one optional
parameter — do not copy it. A forked schema diverges the first time either copy changes.

### 2.4 Two bugs this pattern produced — do not repeat them

Both are in the KB with full mechanisms (search `def-time binding`, `regex closed set`):

- **A test that looked isolated silently read production.** Four functions used
  `def f(path: Path = MODULE_CONSTANT)`. A default argument is evaluated **once, at definition
  time** — so the test's `mod.SESSIONS_ROOT = tmpdir` had no effect, and the "offline" test read
  the real `~/.codex/sessions/` and the real watermark. It nearly appended synthetic test data to
  the live queue. **Fix:** resolve module constants *inside the function body*, where the lookup
  happens fresh on every call.
- **A regex written to approximate strings that were already known exactly.** The placeholder
  filter needed to match five specific template sentences — all five quoted verbatim three lines
  above the regex that then failed to match two of them. **Fix:** when the string set is genuinely
  closed, enumerate it; a generalized pattern for a closed set only adds a place to drift.

---

## 3. The inventory — what does NOT travel via `git pull`

The repo **is** the mind: the knowledge base, the cognitive profile, the activity digest, the
training corpus, `.agent/rules/`, the research PDFs, and the ChromaDB SQLite file are all tracked.
What follows is everything that is not, in four classes.

```bash
git status --ignored --short          # ground truth for this machine, right now
git check-ignore -v <path>            # why is this ignored? (silence = it is NOT)
```

### Class 1 — Ignored, and fully regenerable

| Path | Rebuild with |
|---|---|
| `.venv/` | `python3 -m venv .venv && pip install -r requirements.txt` |
| `rfm/` | separate repo — `git clone …/dadfinanceapp.git rfm` |
| `jarvis_data/cognitive_index.sqlite3` | `python3 scripts/profile_synth.py` |
| `jarvis_data/behavioral_state_model.jsonl` | `python3 scripts/consolidate.py` |
| `jarvis_data/domain_labels.jsonl` | `python3 scripts/relabel_domains.py` |
| `jarvis_data/token_ratios.json` | self-heals from provider usage; starts empty |
| `jarvis_data/.hearth_token` | auto-minted on next hearth start, `0600` |
| `jarvis_data/.hearth_jobs.json`, `.hearth.pid`, `hearth.log` | recreated by the hearth |
| `jarvis_data/.codex_ingest_watermark.jsonl` | machine-local by nature — it indexes *this* machine's rollout filenames |
| `.claude/settings.json` | `python3 scripts/bootstrap_jarvis.py` (from the committed manifest) |
| `__pycache__/`, caches, OS junk | automatic |

### Class 2 — Untracked but **not** gitignored (the trap)

**`jarvis_data/chromadb/<jarvis_memory-collection-uuid>/`** — the HNSW vector index for the
`jarvis_memory` collection. `git check-ignore` matches nothing: it is absent from the repo only
because nobody ever staged it. **`git add -A` would commit it.**

This is a different situation from every row in Class 1, and it cuts both ways: a pull gets
`chroma.sqlite3` but **not** this index, silently, and a careless `git add -A` commits ~2 MB of
binary that the no-binaries rule forbids.

```bash
python3 scripts/index_memory.py      # rebuilds it; idempotent, safe to delete and re-run
```

Note the asymmetry: the **`research_papers`** collection's vector segment *is* tracked. Do not
assume both halves of `chromadb/` behave the same way.

### Class 3 — Genuinely does not travel

- **`~/.claude/projects/<project>/memory/`** — Claude Code's own machine-local notes.
  `.agent/rules/CLAUDE.md` says not to keep project-canonical knowledge here. **On 2026-09-10 that
  rule was found violated:** 13 notes lived there, at least 2 with zero representation anywhere in
  the KB — including the only surviving record of a Databricks workspace host, warehouse id, job
  id, and a serverless-jobs gotcha. Rescued into the KB before the migration. If you write there,
  treat it as a **draft** and promote anything durable with `kb_append.py` before the session ends.
- **`.claude/settings.local.json`** — the accumulated permission allowlist. Gitignored and *not*
  rehydratable; `bootstrap_jarvis.py` restores only `settings.json`. Claude-Code-only, so
  irrelevant to Codex. Accept the loss.
- **Claude Code session transcripts** (`~/.claude/projects/<project>/*.jsonl`, tens of MB) —
  deliberately not migrated. Their distilled signal is already in the KB and the queue.
- **`client_work/*/deepclone/`** — verbatim client source, re-obtainable only from the client.
  The one entry in this entire inventory with no regeneration command.

### Class 4 — `client_work/`: read the config, never a paraphrase

The directory itself is **not** ignored. `client_work/**` is, with explicit `!` re-inclusions that
deliberately re-admit `SESSION_LEARNINGS.md` and `session_learnings/**`. Net effect: exactly one
tracked file today.

**`.gitignore` is the authority here — not this file, and not `CLAUDE.md`.** That carve-out is a
decision the user made as the employee, recorded in `.gitignore` as *"raised twice and confirmed
twice… do not silently re-exclude it, and do not re-argue it."* CLAUDE.md already records the
mistake of stating this rule *more strictly* than the config; do not repeat it in either direction.

```bash
git add -An client_work/    # dry run: shows exactly what would be staged
```

---

## 4. Per-host setup

### 4.1 Claude Code — automatic

```bash
python3 scripts/bootstrap_jarvis.py --check   # verify all manifest hooks are live
```
Capture is per-turn and automatic. Nothing else to do.

### 4.2 Codex CLI — scheduled capture, manual boot ritual

Codex has **no hook system**, but it **persists its own session transcripts** to
`~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` whether or not anything reads them. That is enough
for a real adapter rather than a manual process.

**First run on a new machine:**
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 scripts/bootstrap_jarvis.py     # safe to re-run
python3 scripts/index_memory.py         # rebuild the vector index — it does NOT travel (Class 2)
```

**Every session** — this is `AGENTS.md`'s SESSION BOOT, and it is the whole orientation:
read `cognitive_profile.md`, read `activity_digest.md` (check its `Generated` stamp), **check for
something to raise**, then use `search_memory.py` for topic recall.

**The step people skip, and must not:**
```bash
cd js-development && python3 -m jarvis_core.agent.life_state_monitor --peek
```
`--peek` shows what would surface without consuming it; re-run without `--peek` to mark it
surfaced. On Claude Code this is a hook and happens whether anyone remembers or not. **On Codex,
skipping it means JARVIS's one irreplaceable capability — unprompted surfacing, `JARVIS_ENDGAME.md`
§1.2 — silently does not happen.** This step was missing from `AGENTS.md` until 2026-09-11 and was
found by audit, not by anyone noticing the silence. That is exactly how this capability dies.

**Is capture actually running?** Ask, don't assume:
```bash
python3 scripts/ingest_codex_sessions.py --status     # watermark + rollout counts
python3 scripts/ingest_codex_sessions.py --dry-run    # how many un-ingested turns exist now
python3 scripts/ingest_codex_sessions.py              # ingest them
```
If neither the hearth nor a manual run has happened recently, **this session's turns are not
captured yet.** Say so plainly if asked whether JARVIS "remembers" this conversation. That honesty
requirement is ROADMAP 6.8.4, and it is not optional politeness — a silent capture failure is
indistinguishable from a working system until months of history are missing.

**Codex's own memory is not JARVIS's mind.** `~/.codex/memories/` is a **global, cross-project**
cache that exists so Codex does not re-ask things given a 258 K context window.
`scripts/reconcile_codex_memory.py` promotes JARVIS-relevant items **one way** into the KB:

```bash
python3 scripts/reconcile_codex_memory.py --dry-run
```

The arbitration between "Codex's line" and "the KB's line" is `kb_append.py`'s existing embedding
dedup gate — a candidate too similar to an existing entry is refused. No new judgment layer was
built, because the mechanical one already existed and is deterministic. The reverse direction
(KB → Codex) needs no code at all: Codex reads `cognitive_profile.md` at boot.

The relevance filter is not optional either — `~/.codex/memories/` is global, so without it
another project's memories leak into this KB the first time this runs on a machine where Codex did
unrelated work.

> Both Codex scripts accept `--self-test`, but it is checked directly from `sys.argv` and so does
> **not** appear in `--help`. It runs entirely on temp directories and never touches `~/`.

### 4.3 Antigravity — degraded, and honest about it

**Capture does not run here.** Antigravity has no hook system, and unlike Codex it is *not yet
established* whether it persists any transcript to disk that an adapter could read after the fact.
Until someone checks, this machine's experience enters the corpus **only** via explicit
`kb_append.py` writes.

This is not a hypothetical gap. Measured 2026-09-10: every captured turn in the queue came from one
machine, and Antigravity's manual path had produced **zero** records across months of real use.
**Automatic beats manual, empirically.** Be proactive about capturing durable insights here;
nothing is recording for you.

Orientation is the same read-at-boot ritual — see `.agent/rules/js-workspace-rule.md`.

---

## 5. Keeping it running — the hearth

One always-on process owns the mutable state and the clock; every surface is a client.

```bash
python3 scripts/hearth.py --background   # start detached (POSIX only)
python3 scripts/hearth.py --status       # is it up? per-job table
python3 scripts/hearth.py --tick-once    # run every DUE job once, then exit
python3 scripts/hearth.py --stop
python3 scripts/jarvis_client.py "what did I decide about the roster?"
```

`--tick-once` bypasses the startup stagger but **still honours interval cadence**, so it cannot
force a needless expensive rebuild.

**Three fail-closed security gates**, all in `serve/hearth.py`:
1. Loopback only — and the peer address is re-checked **per request**, so a bind misconfiguration
   alone cannot expose the mind.
2. Bearer token required **even on loopback** — other local processes exist; loopback is not a
   trust boundary. Compared with `hmac.compare_digest`.
3. **No token configured = refuse everything.** An "open" hearth is impossible by construction.

The hearth also **denies every permission prompt** — it has no TTY, so it reports the denial and
tells you to re-run through `--ask` where a human is reachable.

### 5.1 The scheduled jobs

`serve/scheduler.py::default_jobs()`. Read the list, don't trust a count:

```bash
grep -oP 'Job\(name="\K[^"]+' js-development/jarvis_core/serve/scheduler.py
```

Roughly: `consolidate` (the pulse for the surfacing organ), `refresh_profile` and `reindex_memory`
(guarded), `ingest_codex` (capture on a hookless host), `reconcile_codex_memory`, and
`refresh_digest`.

**Why guard scoping is load-bearing.** Guarded jobs run `check_projections.py --only <artifact>`
first; exit 0 means "nothing to do" and the job is skipped. A *shared, unscoped* guard was measured
broken on 2026-09-08: `check_projections` exits non-zero if **any** projection is stale, so
`refresh_profile` ran first, fixed the two it owns, and `reindex_memory` then saw exit 0 and
skipped — meaning the vector index would never rebuild no matter how far it drifted. Each job now
guards on the artifact **it** can fix.

**`refresh_digest` exists because of a real 2.5-month silence.** `activity_digest.md` is written
only by an explicit `recall.py --write`; nothing regenerated it, and the personal laptop — which
reads it at boot and *cannot* rebuild it, having no local queue — was booting on months-old state.
That is the `PROJECTION-AS-TRANSPORT` class: derived here, consumed by a machine that cannot derive
it. Untracking such a file looks like obvious cleanup and is a regression.

> **Honest status:** the hearth is **not** currently running as a persistent daemon on the work
> laptop. Check with `--status` before assuming any scheduled job has fired recently.

---

## 6. What is not built

### 6.1 An Antigravity capture adapter

**Blocked on a question, not on architecture:** does Antigravity persist a readable transcript to
disk at all? If it does, the adapter is a near-copy of the Codex one and the contract in §2 already
proves it generalizes. If it does not, capture there cannot be automated after the fact and the
honest answer is to keep §4.3's degraded-mode statement.

**If you build it, follow the shape that worked:**
1. Find the transcript. Confirm the real on-disk format by *reading actual files* — do not build a
   parser against a guessed schema.
2. Re-derive the host's wrapper-tag vocabulary from real transcripts. Do not reuse `_HARNESS_TAGS`.
3. Parse to `{user_text, assistant_summary, model, ts}` and call the **same organ** —
   `build_observation(..., ts=<the turn's own time>)` then `append_observation`.
4. Keep a **per-file, append-only watermark** so re-runs never double-ingest. Per-file, not
   global: a long-lived transcript keeps growing, and a global watermark either re-scans forever
   or misses late turns appended to an older file.
5. Write offline self-tests that **never touch `~/`** — and re-read §2.4 first, because the
   obvious way to write those tests has a bug that makes them read production instead.
6. Add it to `default_jobs()` with a unique `initial_delay_seconds`.
7. Update §4.3 here and in `js-workspace-rule.md` the moment it works.

### 6.2 Codex has no `notice_runtime_change` or `capture_gap_nudge` equivalent

Low value on Codex (it runs one model, so self-state barely changes), and the capture-gap question
is answered on demand by `ingest_codex_sessions.py --dry-run`, which `AGENTS.md` now instructs.
Build only if the manual check proves insufficient in practice.

---

## 7. Maintaining this file

Update it when a host is added, a capture mechanism changes, or a degraded-mode statement stops
being true. Substantive **rules** land in `.agent/rules/CLAUDE.md`; this file explains **mechanism
and operations**.

And the rule from §0, restated because it is the one this document exists to break: **if you are
about to write down a number, write down the command that prints it instead.**
