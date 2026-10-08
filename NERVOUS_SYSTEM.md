# JARVIS — The Nervous System, the Inventory, and How to Run It on Any Host

> **What this file is.** Two questions have never had a written answer, and both were asked
> directly on 2026-09-11 while moving primary development to Codex:
> 1. *How does every Claude chat know what the other chats said?*
> 2. *What does NOT travel via `git pull` — and how do I get it back?*
>
> Both had been answered only in conversation, which means they were answered nowhere. This file
> is the answer, and it is tracked so it arrives with the code it describes.
>
> **Audience:** any agent or human operating JARVIS on any machine.
>
> **Find your part and read it — the hosts are genuinely not equivalent:**
>
> | You are | Read | Your situation in one line |
> |---|---|---|
> | **Codex CLI** | §1, §3, §5.2, §6 | Capture works, but ONLY if the hearth is running here — check it. You parse your own turns (§3.2) |
> | **Antigravity** | §1, §3, §5.3, §7.1 | Capture works via `ingest_antigravity_sessions.py` scheduled on the hearth. You parse your own turns (§3.3) |
> | **Claude Code** | §1, §3, §5.1 | Hooks capture every turn automatically; a hook tells you when to parse (§3.1) |
>
> §1 is mandatory for all three — it corrects four misconceptions that otherwise produce confidently
> wrong answers to the user about what JARVIS can and cannot see. **§3, the Memory Contract, is
> mandatory too** — it is what each agent owes the owner's turns.

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

## 1. The mental model — four things people get wrong

Read this before the mechanics. These four misconceptions came up in a real conversation on
2026-09-11, and all four are the kind that quietly produce wrong answers to the user.

### 1.1 The hearth has no senses

The hearth **observes nothing.** It is a process that runs other programs on a schedule — the
heartbeat, not the eyes. What actually observes is different on every host:

| Host | What observes a turn | Automatic? | Needs the hearth? |
|---|---|---|---|
| **Claude Code** | `Stop` hook → `capture.py`, one line per turn | yes, always | **no** — the hook fires on its own |
| **Codex** | `ingest_codex_sessions.py` reading `~/.codex/sessions/` | only if scheduled | **yes** — the hearth is what runs it |
| **Antigravity** | `ingest_antigravity_sessions.py` reading `~/.gemini/antigravity-ide/brain/` | only if scheduled | **yes** — the hearth is what runs it |

So "turn the hearth on and JARVIS sees everything everywhere" is **false in two directions**: Claude
Code already captures without it, and Antigravity captures nothing with it. The hearth's role is to
keep the *Codex* reader firing when nobody remembers to run it, and to keep consolidation,
projections and the digest fresh on a clock rather than on attention.

### 1.2 The hearth is not the sync mechanism either

It binds `127.0.0.1` only and re-checks the peer per request. **One machine's hearth cannot see
another's.** Two hearths are two independent local clocks, not a network.

**Git is the transport, and always was.** The full chain:

```
work in Codex → ingest_codex (hearth clock) → observation_queue.jsonl
              → YOU git push → other machine git pulls
              → its hooks / boot ritual inject it
```

Skip the push/pull and the two machines diverge no matter how many hearths run.

### 1.3 ChromaDB is an index, not a store — this one matters most

`chromadb/` holds **no original information.** It is a rebuilt lookup structure over data that
lives elsewhere.

| Class | Files | Tracked? |
|---|---|---|
| **FACT** — authoritative, append-only, the actual mind | `knowledge_base.jsonl`, `observation_queue.jsonl` | ✅ yes |
| **PROJECTION** — derived, rebuildable, disposable | `chromadb/`, `cognitive_index.sqlite3` | ❌ no |
| **PROJECTION-AS-TRANSPORT** — derived here, consumed by a machine that cannot rebuild it | `cognitive_profile.md`, `activity_digest.md` | ✅ yes, and correctly so |

The proof is in this repo's own history: on 2026-09-11 the entire 25 MB `chromadb/` directory was
removed from version control and **nothing was lost** — every fact intact, search still working
after a rebuild. That is only possible because it stores nothing original. It is the card
catalogue, not the library.

If you ever find yourself worried about "losing ChromaDB", you are worried about the wrong file.
Worry about `knowledge_base.jsonl`.

### 1.4 Time is real; general perception of absence is not (yet)

**Time is genuinely modelled.** Every captured turn is stamped IST; `recall.py` groups by calendar
day; `agent/tension.py` enforces "only the past can be a prior" so a later decision cannot be
contradicted by an earlier one in the wrong direction.

**Absence is only detected where an instrument was built for it**: `parse_ledger.backlog()` (turns
a host's agent has not parsed — surfaced by `capture_gap_nudge.py` and `pipeline_health.py`),
`pipeline_health.py` (a job with no recent success), `check_projections.py` (a projection that
stopped being refreshed), and the digest's day-by-day view (a visible gap between days).

There is **no general faculty** for noticing "you stopped working on X." Measured 2026-09-11: across
100 days and 607 captured turns, all six domains were active within 0–2 days, so a domain-level
dormancy detector would never fire at all. Do not claim this capability to the user. See §7.3 for
what it would actually take.

---

## 2. The mechanism — how every chat knows every other chat

**One sentence:** a `Stop` hook appends every turn of every chat to one append-only JSONL file;
`SessionStart` hooks put health, the insight to raise and pointers to the profile and digest in
front of the next chat as `additionalContext`, and the chat reads those two files in full. There
is no server, no daemon, and no database on this path.

```
Claude Code turn ends
  └─ Stop ──→ capture_turn.py ──→ capture.py::capture_stop_event()
  │              reads event.transcript_path, appends ONE line
  │              → jarvis_data/observation_queue.jsonl          [git-TRACKED]
  └─ Stop ──→ run_consolidation.py ──→ scripts/consolidate.py
                 drains queue → jarvis_data/life_state_feed.jsonl

New session starts
  ├─ SessionStart → surface_pipeline_health.py → pipeline_health.py --brief (silent when healthy)
  ├─ SessionStart → inject_profile.py          → notice: READ cognitive_profile.md in full
  ├─ SessionStart → surface_life_state.py      → life_state_feed.jsonl
  ├─ SessionStart → inject_recent_activity.py  → refresh digest, notice: READ activity_digest.md in full
  └─ SessionStart → check_agent_mail.py        → agents_converse/
        each emits:
        {"hookSpecificOutput": {"hookEventName": …, "additionalContext": …}}

Every prompt
  └─ UserPromptSubmit → capture_gap_nudge.py → parse backlog >= 10 → "parse before answering" (§3.1)
```

**`additionalContext` is the entire injection mechanism.** Nothing else makes the model "know."
If you are porting to a new host, that string is what you must reproduce — whatever channel your
host offers for putting text in front of the model before it answers. **Keep it short:** the
Claude Code harness replaces SessionStart output over ~10 KB with a 2 KB preview, so a large file
goes in as a pointer plus an instruction to read it in full, never as pasted text.

### 2.1 The committed wiring recipe

`.agent/hooks.manifest.json` is the **canonical, committed** declaration of every hook.
`.claude/settings.json` is **tracked as of 2026-09-18** and carries the shared permission
allowlist (164 entries) as well as the hook registrations. The manifest remains canonical for the
*hooks*: `python3 scripts/bootstrap_jarvis.py` rehydrates them into whatever settings file exists,
so a host that somehow lacks the tracked file still self-heals.

**The invariant that makes tracking it safe:** no credential may appear in that file. It was
untracked in the first place because a live `github_pat_` rode into commit b7bfbe6 inside an
allowlist entry — `Bash(GH_TOKEN="...")` — i.e. through an approved command *string*, where no
secret-shaped config key would ever show up in an audit. `GH_TOKEN` belongs in the shell
environment or a credential helper. Before committing a change to it:

```bash
grep -E 'github_pat_|ghp_|sk-or-v1-|AKIA' .claude/settings.json   # must print nothing
```

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

### 2.2 The hooks

List them rather than trusting a count: `python3 -c "import json;[print(e,h['args'][-1]) for e,g in json.load(open('.agent/hooks.manifest.json'))['hooks'].items() for x in g for h in x['hooks']]"`

| Event | Script | What it does |
|---|---|---|
| `UserPromptSubmit` | `notice_runtime_change.py` | Tail-reads the transcript to detect a mid-session `/model` swap; emits a `RUNTIME SELF-STATE` line **only on change**. State in `.runtime_state.json`, flock'd. |
| `UserPromptSubmit` | `capture_gap_nudge.py` | The parse trigger (§3.1): at `_NUDGE_THRESHOLD` or more unparsed Claude Code turns (`parse_ledger.backlog()`), tells Claude to run `parse_turns.py --pending --host claude` and `--submit` before answering, with the count and oldest age. Reads only. |
| `Stop` | `capture_turn.py` | The write path. Thin adapter → the organ. |
| `Stop` | `run_consolidation.py` | Fire-and-forget `consolidate.py`; drains the queue into insights so the surfacing channel has fuel. Emits nothing. |
| `SessionStart` | `surface_pipeline_health.py` | Runs `pipeline_health.py --brief`; relays every breach whole under "raise these with the owner first". Silent when healthy; a missing, crashing or hung health check is itself reported. |
| `SessionStart` | `inject_profile.py` | A short notice: path, size, entry count and the Read pages covering `cognitive_profile.md` end to end, with the instruction to read it in full before the first reply. Framed as background, *not* instructions. |
| `SessionStart` | `surface_life_state.py` | Asks the organ for one unsurfaced high-confidence insight and advances the never-nag watermark. |
| `SessionStart` | `inject_recent_activity.py` | Rewrites `activity_digest.md` when the queue is newer (atomic; never blanks a synced digest), then the same read-in-full notice for it. |
| `SessionStart` | `check_agent_mail.py` | Delivers questions/answers from the other agents in `agents_converse/`. Silent when there is no mail. |

**Output encoding on Windows.** A hook's stdout pipe there is cp1252. Until 2026-09-28
`inject_profile.py` wrote raw UTF-8 JSON; the first `→` in the profile raised
`UnicodeEncodeError`, the swallow-everything `except` ate it, and the hook emitted **nothing** —
measured 0 bytes. Emit ASCII-escaped JSON (`json.dumps` default), never `ensure_ascii=False`.

Two details that are easy to get wrong:

- **`surface_life_state.py` does not build the `additionalContext` envelope.** The organ does —
  `life_state_monitor.session_start_payload()`. The hook only serializes what it is handed. That
  is the organ/adapter split working correctly, and it is why the surfacing capability is portable
  to a host with no hooks at all (see §5.2).
- **`run_consolidation.py`'s internal timeout is not the manifest's timeout.** The manifest grants
  the hook a larger budget than the subprocess is given, deliberately, so the subprocess loses the
  race and the hook always exits cleanly. Do not "simplify" them to the same number.

Every hook reads stdin JSON, **swallows all exceptions, and exits 0 unconditionally.** A broken
hook must never disrupt a turn. Preserve that discipline in any port.

### 2.3 What actually gets written

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

### 2.4 Curation — what decides a turn is FOR (added 2026-09-14)

Capture answers *what happened*. Until this shipped, **nothing answered *what it was for***, and the
consequence was not subtle: `engineer_corpus` and `personalization_corpus` read the **same**
`observation_queue.jsonl`, so **every captured turn went into both**. The only difference was which
half of the exchange each took. The sole thing standing between a three-word `continue` and the
training corpus was a character-count floor — and `continue` appears 35 times in the queue, `go` 13,
`hi` 9.

**Who decides changed on 2026-09-28.** From 2026-09-14 an hourly hearth job (`curate_turns`) asked a
paid model; it failed 185 of 195 runs on HTTP 402 and was removed. The verdict is now made by the
agent the owner was chatting with, under the Memory Contract (§3), by the one rule in
`parse_rule.py`, which extends the four fields below with knowledge extraction and tension.
`curator.py` keeps the verdict parsing and folding (`parse_verdict`, `fold_events`, `routes_to`).
The fields it settles, **with the conversation in hand**:

| field | what it settles |
|---|---|
| `corpora` | `engineer` / `personalization` / `none` — `none` is a real and common answer |
| `domain` | the same label set as `domain_classifier.py`, so the two are comparable |
| `trainable` | whether a model should learn from this turn at all |
| `responds_to` | one sentence: what the user's prompt was **replying to** |

**Why an agent and not a better classifier.** `relabel_domains.py` marks 314 of 583 turns `unknown`,
which looks broken and is not — it scores 89% against its gold set, above its 80% bar. It is
*abstaining*, correctly, and its own header predicted this and prescribed the cure: *"No classifier
reading one turn alone can label those… the fix is to classify a turn WITH its session neighbours —
not to lower the threshold."* All three of its gold-set misses are that shape. The agent in the
conversation already holds that context and is the only participant that knows what a prompt was
replying to. Worked example from the live log: `"What is wrong in my first ans"` is meaningless
alone; `responds_to` resolved it to *"feedback on their mistake about PySpark's withColumnRenamed"*.

**Verdicts are appended, never edited.** `jarvis_data/turn_curation.jsonl` is an event log folded on
read — newest verdict per `(ts, session_id)` wins, every superseded one stays readable **with its
author**. That is what makes *"check whether JARVIS routed this correctly"* a real operation. The
embedding label rides **alongside** the agent's verdict rather than replacing it, so disagreement is
a query rather than something a human must happen to notice.

**It is TRACKED**, and `*.jsonl` already carries `merge=union`, so both laptops curate independently
without conflicting. It is a *judgement*, not a projection: regenerating it costs model calls, so
losing it is not free. Known property — after a union merge, if both machines curated the same turn
the winner is whichever line sorts last, not whichever was written later. Harmless, because both are
genuine verdicts; it would **not** be harmless for facts, which is why the queue itself is never
written here.

**Uncurated turns are ADMITTED, not dropped.** Absence means "nobody has looked yet". Defaulting to
exclusion would silently collapse the corpus to whatever the backlog had reached.

```bash
python3 scripts/parse_turns.py --status      # unparsed backlog per host (§3)
python3 scripts/parse_turns.py --routing    # what routing actually results
python3 scripts/parse_turns.py --review     # disagreements + low confidence: where to look
```

---

## 3. THE MEMORY CONTRACT — what every agent does with the owner's turns

> **Owner's decisions, 2026-09-28.** Every chat with Claude Code, Codex, Antigravity and JARVIS is
> parsed into training data and live context by **one rule**. **The agent the owner is chatting
> with parses those turns** — Claude parses Claude chats, Codex Codex, Antigravity Antigravity,
> JARVIS its own. **No paid background LLM calls.** **No truncation anywhere.** **Failures are
> loud, to all four agents.** People in the owner's life reach JARVIS **as context, never as
> training**. **Test prompts only in ephemeral sessions.**

**Why the contract exists.** Measured 2026-09-28: capture was automatic everywhere and worked, but
everything after it depended on something nobody watched. The hourly paid curator failed 185 of 195
runs (HTTP 402, credits) and left the backlog uncurated; turning chats into KB knowledge depended
on each agent remembering (Antigravity's `/memory` produced zero records — which is why the
interview answers and the people in the owner's life never reached JARVIS); `reindex_memory`
failed 16 of 17 runs behind a guard-skip that overwrote the failure; and the Claude Code harness
cut SessionStart output to a 2 KB preview, so a session "injected" with the 650 KB profile saw
2 KB of it. Reliability now comes from machinery around the agents: one rule text, one tool that
hands each agent its pending turns and validates what it submits, a trigger about every 10 turns,
and a per-host backlog count that every agent and JARVIS itself sees at boot.

### 3.0 The one rule

`js-development/jarvis_core/agent/parse_rule.py` holds `PARSE_RULE` (the text), `PARSE_SCHEMA`
and `PARSE_RULE_VERSION`. **It is the single source** — the agent tool, JARVIS's own parser and
`curator.py` all import it, so four agents cannot drift into four rules. Print it:

```bash
cd js-development && PYTHONPATH=. python -m jarvis_core.agent.parse_rule --print
```

- **Per turn, one verdict:** training routing (`corpora`, `domain`, `trainable`, `responds_to`,
  `confidence`, `rationale`), durable `knowledge` about the owner (identity / person / decision /
  preference / correction / project-fact, each with a **verbatim** evidence quote from the owner —
  a quote not in the owner's text rejects the verdict), and an optional `tension` against the
  priors listed with the turn. Trivial turns ("do it", "go ahead") are `none` with no knowledge.
- **A version bump re-offers every older verdict.** `parse_ledger.is_parsed` counts a turn as
  parsed only under the current `PARSE_RULE_VERSION`; the pre-rule Gemini verdicts still route
  training (the log folds newest-wins) but are offered again for knowledge extraction.
- **v1 was written by Claude (2026-09-28).** Codex and Antigravity review it over agent mail;
  their changes land in `parse_rule.py` as v2. Never paraphrase the rule into a host file — point
  at it.

**The tool, identical on every host** — `scripts/parse_turns.py`:

```bash
python scripts/parse_turns.py --status                                 # backlog per host
python scripts/parse_turns.py --pending --host <host> --limit 10       # packet: rule + whole turns + context + priors
python scripts/parse_turns.py --submit verdicts.json --agent <host>/<model>   # strict validation, then write
```

`--submit` writes the verdicts to `turn_curation.jsonl` (with `curated_by` and `rule_version`),
the knowledge to the KB through `kb_append.append_entry` (dedup; tags `distilled`, the fact type,
`source:<host>`, `person:<name>`), and tension through the consolidator's KB/feed path. It is
idempotent. Test sessions (`conv-web-voicegate-*` and every other ephemeral session) are never
offered. Which host a turn belongs to is `parse_ledger.host_of` — the capture `host` field, else
evidence, else `unknown`, which is reported and never silently assigned.

**People are context, not training.** A `person` fact goes to the KB and so to the profile and the
inhale; `specialists/third_parties.py` redacts names at blend/SFT time, so no person reaches a
training artifact.

### 3.1 Claude Code

| Duty | How |
|---|---|
| **Capture** | Automatic. `Stop` hook → `capture_turn.py` → `capture.py`, every turn. |
| **Parse** | Claude, in the session. `UserPromptSubmit` hook `capture_gap_nudge.py` fires once `parse_ledger.backlog()["claude"]["pending"] >= 10` and tells Claude, before the user's request, to run `python scripts/parse_turns.py --pending --host claude --limit 10`, judge each turn by the packet's rule, write `{"verdicts":[...]}` to a scratch file and `python scripts/parse_turns.py --submit <file> --agent claude/<model>`. |
| **Boot reads** | SessionStart hooks: `surface_pipeline_health.py` (breaches, silent when healthy), `inject_profile.py` and `inject_recent_activity.py` — **short notices** naming `cognitive_profile.md` and `activity_digest.md` with sizes, counts and the exact Read pages; Claude **reads both in full** before its first reply. The digest is refreshed first if the queue is newer. Nothing is pasted, because the harness cuts SessionStart output over ~10 KB to a 2 KB preview. |
| **Health surfaces** | `surface_pipeline_health.py` at SessionStart, headed "raise these with the owner first". |

### 3.2 Codex

| Duty | How |
|---|---|
| **Capture** | Automatic when the hearth runs here: `ingest_codex` reads `~/.codex/sessions/` hourly. |
| **Parse** | Codex, in the session, **at boot and about every 10 turns**: `python scripts/ingest_codex_sessions.py` first, then `python scripts/parse_turns.py --pending --host codex --limit 10`, read every complete offered turn and judge, `--submit <file> --agent codex/<model>`. At boot, offer up to 20. The hook never supplies verdicts or uses a background model. |
| **Boot reads** | `.codex/hooks.json` runs `scripts/hooks/codex_parse_nudge.py` on `SessionStart` (`startup` or `resume`): it runs `bootstrap_jarvis.py --check`, ingests Codex transcripts, and points to the full `AGENTS.md`, `cognitive_profile.md`, `activity_digest.md`, life-state peek and mail reads. The agent performs those reads, not the hook. |
| **Ten-turn reminder** | The same fail-soft script runs on `UserPromptSubmit` and announces `parse_ledger.backlog()["codex"]["pending"] >= 10`. It preserves the pre-existing Corpus `PostToolUse` hook in `.codex/hooks.json`. |
| **Trust / verification** | Codex project hooks are skipped until the current definitions are reviewed and trusted via `/hooks` in a fresh Codex session. The script's `--self-test` and synthetic stdin invocation verify local behavior only; they do not prove lifecycle execution. Until that trust and a fresh-session run are observed, the manual `AGENTS.md` boot ritual remains mandatory. |
| **Health surfaces** | `bootstrap_jarvis.py --check`; the hook surfaces its summary at startup once trusted. |

### 3.3 Antigravity

| Duty | How |
|---|---|
| **Capture** | Automatic when the hearth runs here: `ingest_antigravity` reads `~/.gemini/antigravity-ide/brain/` hourly. |
| **Parse** | Antigravity, in the session, **at boot and about every 10 turns** (a written duty in `js-workspace-rule.md`): Execute `.agent/workflows/parse.md` to automate the manual loop (`ingest_antigravity_sessions.py`, `parse_turns.py --pending --limit 10`, judge, `--submit <file> --agent antigravity/<model>`). At boot, drain up to 20 backlog turns. |
| **Mail** | Antigravity has no hooks, so it runs `python scripts/hooks/mail_watch.py --agent antigravity --no-auto-ask --plain` at the start of every reply and at boot (`.agent/workflows/mail.md`). Questions addressed to Antigravity are answered immediately via `python scripts/agent_mail.py --answer <N> --from antigravity --body "..."` before user requests. |
| **Boot reads** | `python scripts/bootstrap_jarvis.py --check`, then `cognitive_profile.md` and `activity_digest.md` **in full**. |
| **Health surfaces** | `bootstrap_jarvis.py --check`. |

### 3.4 JARVIS (its own sessions: terminal `--ask`, web UI, voice)

| Duty | How |
|---|---|
| **Capture** | Automatic, in-process, `host=jarvis`. |
| **Parse** | JARVIS itself, on the hearth every 15 minutes: `python scripts/parse_turns.py --host jarvis --auto`, on JARVIS's own model chain — never a separate paid judge. |
| **Boot reads** | The inhale (`brain/context_injector.py`) carries the whole profile, `personal_life.md` and the digest; a "Pipeline health" provider appears **only when something is broken**, so JARVIS tells the owner. |
| **Health surfaces** | The inhale, and the web UI's System page. |

### 3.5 Rules for all four

- **Never truncate.** Select which records to show if you must; never cut one that is shown. A
  preview is not a read — when a tool or harness hands you a preview or a saved-output file, read
  the file in full. `check_pipeline.py` enforces it: every KB entry selected into the profile
  appears whole, both inhales carry the whole profile and `personal_life.md`, session distills
  equal the full Q/A, parse packets carry whole turns.
- **Test prompts only in ephemeral sessions** (`verify_voice_live.py` opens the socket
  `ephemeral`). A test prompt in a real session becomes a training turn and a KB candidate.
- **Failures are loud.** `scripts/pipeline_health.py` (`--brief`: one line per breach, nothing
  when healthy, exit 1 when breached; `--json`) watches: each hearth job's last *success* within
  2× its interval; the unparsed backlog per host and its oldest turn; corpus age; projection
  freshness (`check_projections`); inhale size against the smallest context window in the model
  chain; the no-truncation invariants. It surfaces at Claude's SessionStart, in
  `bootstrap_jarvis.py --check`, in JARVIS's inhale and on the System page. A health check that
  cannot run is itself a breach.

### 3.6 The adapter contract — porting to a host with no hooks

*(These were §3.1–§3.4 before 2026-09-28; older agent mail cites them by those numbers.)*

This is no longer theoretical. `scripts/ingest_codex_sessions.py` is a **second working
implementation** against a different host, a different transcript format, and a different
lifecycle (no hooks at all — a scheduled reader instead). It proved the organ genuinely is
host-independent rather than merely designed to be. That closed ROADMAP 6.8.1–6.8.4. A new host
must also meet §3.0–§3.5: capture feeds the queue, and the chatting agent parses.

### 3.6.1 Reuse this — it is host-agnostic

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

### 3.6.2 Re-derive this — it is Claude-Code-specific

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

### 3.6.3 The one change the organ needed, and why

`build_observation` originally hardcoded "now" as the timestamp — correct for a **live** Stop hook
(the turn just ended), and wrong for **ingesting a historical transcript** written weeks ago.
Backdating every ingested turn to "now" would corrupt every timestamp-ordered consumer:
`recall.py`'s day grouping, `tension.py`'s "only the past can be a prior" filter, and the
`(ts, session_id)` key of the domain-label projection.

Rather than fork the schema by duplicating the dict construction, `build_observation` gained an
optional `ts=` override. Every existing call site is unaffected.

**Generalize this:** when a second host needs a variation, extend the organ by one optional
parameter — do not copy it. A forked schema diverges the first time either copy changes.

### 3.6.4 Two bugs this pattern produced — do not repeat them

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

## 4. The inventory — what does NOT travel via `git pull`

The repo **is** the mind: the knowledge base, the cognitive profile, the activity digest, the
training corpus and `.agent/rules/` are tracked. The ChromaDB files are not (see §4.2).
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
| `__pycache__/`, caches, OS junk | automatic |

### Class 2 — The whole vector store, and why it stopped being tracked

**`jarvis_data/chromadb/` is gitignored as of 2026-09-11.** A fresh clone has **no vector index**,
and semantic search returns nothing until you rebuild it:

```bash
python3 scripts/index_memory.py                                    # jarvis_memory (from the KB)
```

(A second collection, `research_papers`, existed until 2026-10-08; the owner removed it and its PDFs as
unused.)

**Why it was un-tracked**, since this reverses an earlier recorded decision: `chroma.sqlite3` is a
23 MB binary, `.gitattributes` marks `*.sqlite3` binary, and so it has **no merge driver**. The
hearth's `reindex_memory` job rewrites it every 12 hours and is meant to run on *both* machines —
which produces an unresolvable binary conflict the first time both sides commit. `merge=union`
rescues `*.jsonl` only, not this.

**The rebuild was tested, not assumed** (2026-09-11), because an earlier version of this claim was
wrong. Run the command above and check the collection count.

> **Historical note for anyone reading old commits:** until 2026-09-11 most of `chromadb/` was
> tracked while the `jarvis_memory` vector segment alone was untracked-but-not-gitignored — so a
> pull got the SQLite file without the index it described, and `git add -A` would have committed a
> binary the no-binaries rule forbids. That asymmetry is gone; the whole directory is ignored now.

### Class 3 — Genuinely does not travel

- **`~/.claude/projects/<project>/memory/`** — Claude Code's own machine-local notes.
  `.agent/rules/CLAUDE.md` says not to keep project-canonical knowledge here. **On 2026-09-10 that
  rule was found violated:** 13 notes lived there, at least 2 with zero representation anywhere in
  the KB — including the only surviving record of a Databricks workspace host, warehouse id, job
  id, and a serverless-jobs gotcha. Rescued into the KB before the migration. If you write there,
  treat it as a **draft** and promote anything durable with `kb_append.py` before the session ends.
- **`.claude/settings.local.json`** — 247 KB of per-host accumulated approvals. Gitignored and
  *not* rehydratable; `bootstrap_jarvis.py` restores only `settings.json`. Claude-Code-only, so
  irrelevant to Codex. Accept the loss — but note this is now the *only* settings file that does
  not travel: `.claude/settings.json`, with the shared 164-entry allowlist, IS tracked (§2.1).
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

## 5. Per-host setup

### 5.1 Claude Code — automatic, *once the machine itself is set up*

On a host that already has the venv and the vector index:
```bash
python3 scripts/bootstrap_jarvis.py --check   # verify all manifest hooks are live
```
Capture is then per-turn and automatic. Nothing else to do.

**On a FRESH clone, that is not enough** — and this section said "nothing else to do" without
qualification until 2026-09-18, which is wrong for a new machine. Hooks are only one of the four
things that do not travel; the venv and ChromaDB do not either (Class 1 and Class 2 below). Run the
same first-run block as §5.2 — it is host-agnostic, not a Codex step:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 scripts/bootstrap_jarvis.py     # rehydrates hooks from the manifest; safe to re-run
python3 scripts/index_memory.py         # rebuild jarvis_memory — chromadb/ does NOT travel
```

`bootstrap_jarvis.py --check` does report every one of these as MISSING with its fix inline, so the
gap is recoverable rather than silent — but read the report, do not assume the hook check alone
means the machine is ready.

### 5.2 Codex CLI — scheduled capture, manual boot ritual

Codex has **no hook system**, but it **persists its own session transcripts** to
`~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` whether or not anything reads them. That is enough
for a real adapter rather than a manual process.

**First run on a new machine:**
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 scripts/bootstrap_jarvis.py     # safe to re-run
python3 scripts/index_memory.py         # rebuild jarvis_memory — chromadb/ does NOT travel (Class 2)
```

**Also on a new machine — set Codex's own model.** `~/.codex/config.toml` is outside the repo, so
it does **not** travel and each machine needs it set independently:
```toml
# model = whichever you are using — GPT-6 Astra, or GPT-5.6 Sol/Terra/Luna.
# JARVIS does not care which; nothing in this repo keys off the model name.
model = "<your-model>"
model_reasoning_effort = "xhigh"

[features]
memories = true

[memories]
generate_memories = true
use_memories = true
```
`memories = true` is deliberate: Codex's native memory is a cheap per-session cache that matters
given a 258 K context window. It is **not** a second mind — see the reconciler note below for why
that is safe.

**Then make capture automatic — this is the step that decides whether any of it works.**
```bash
python3 scripts/hearth.py --background   # start the clock; run this ON THIS MACHINE
python3 scripts/hearth.py --status       # confirm ingest_codex is in the job list
```
Without a running hearth, `ingest_codex` fires **only when a human runs it**, which makes Codex
capture manual in practice — and manual capture is the thing that has already been measured to
produce zero records over months on the other hookless host (§5.3). The adapter existing is not
the same as the adapter running. **Start the hearth on whichever machine you actually work on.**

**Every session** — this is `AGENTS.md`'s SESSION BOOT, and it is the whole orientation:
`bootstrap_jarvis.py --check` (health), read `cognitive_profile.md` and `activity_digest.md` **in
full** (check the digest's `Generated` stamp), **check for something to raise**, run the parse loop
of §3.2 (ingest, then drain up to 20 of this host's pending turns), then use `search_memory.py` for
topic recall. Repeat the parse loop about every 10 turns.

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

### 5.3 Antigravity — captured via native adapter (ROADMAP 6.8.3, closed 2026-09-14)

**Capture is live and automatic here.** Antigravity persists its transcripts to
`~/.gemini/antigravity-ide/brain/<conversation-id>/.system_generated/logs/` (and earliest sessions in `overview.txt`).
Audit confirmed Antigravity **never prunes or rotates** these directories — records back to April 2026
remain intact.

`scripts/ingest_antigravity_sessions.py` runs on the hearth's schedule (hourly, `initial_delay_seconds=240.0`),
reading transcripts, stripping envelope tags (`<USER_REQUEST>`, `<ADDITIONAL_METADATA>`, etc.), and
feeding them into the shared `observation_queue.jsonl` via `capture.py`'s `build_observation` and
`append_observation` under an append-only per-session watermark.

**Historical backfill completed on 2026-09-14:** 359 turns from April 2026 to September 2026 harvested.
This closes the final host that previously lost turns.

Check capture status at any time:
```bash
python3 scripts/ingest_antigravity_sessions.py --status     # session and watermark counts
python3 scripts/ingest_antigravity_sessions.py --dry-run    # un-ingested turns preview
python3 scripts/ingest_antigravity_sessions.py --self-test   # offline unit tests (19/19)
```

Orientation remains the same read-at-boot ritual — see `.agent/rules/js-workspace-rule.md` — plus
the parse loop of §3.3 at boot and about every 10 turns. The hourly ingest keeps capture
automatic; running it yourself before a parse only makes this session's latest turns available.

---

## 6. Keeping it running — the hearth

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

### 6.1 The scheduled jobs

`serve/scheduler.py::default_jobs()`. Read the list, don't trust a count:

```bash
grep -oP 'Job\(name="\K[^"]+' js-development/jarvis_core/serve/scheduler.py
```

Roughly: `consolidate` (the pulse for the surfacing organ), `refresh_profile` and `reindex_memory`
(guarded), `rebuild_graphrag`, `ingest_codex` and `ingest_antigravity` (capture on hookless hosts),
`reconcile_codex_memory`, `refresh_digest`, `relabel_domains`, `check_pipeline`, and JARVIS's own
parse (`parse_turns.py --host jarvis --auto`, every 15 minutes, §3.4).

**`curate_turns` was removed on 2026-09-28.** It was the hourly paid judge that decided what turns
were FOR (§2.4); it failed 185 of 195 runs on HTTP 402 and 1,833 turns sat uncurated for 13 days
with no agent noticing. The owner's decision replaced it with the Memory Contract (§3): the
chatting agent parses, by one rule, and background jobs make no paid LLM calls. The lesson it
taught is kept in the contract rather than lost: a duty that depends on discipline needs a
trigger and a visible backlog, which is what `capture_gap_nudge.py`, the host rule files and
`pipeline_health.py` provide.

**`relabel_domains` is scheduled because it is the verdicts' reviewer**, and it was found six days
stale covering 583 of 989 turns on 2026-09-14 with nothing scheduling it at all — so the independent
second opinion the agent verdict gets checked against was silently degrading.

**A job's status must never hide its failure.** Measured 2026-09-28: `reindex_memory` failed 16 of
17 runs (a ChromaDB `InternalError` in compaction), but a later guard-skip overwrote
`last_status`, so `--status` read "skipped — guard reports nothing to do". `pipeline_health.py`
judges each job by its last *success*, not its last status line.

> **THE HEARTH RUNS THE CODE IT BOOTED WITH.** Adding a job to `default_jobs()` does nothing to a
> running hearth — and `--status` looks perfectly healthy while the new job silently does not exist.
> This bit twice on 2026-09-14 alone: once after pulling Codex's `rebuild_graphrag`, once after
> adding `curate_turns`. **After any scheduler change, restart it and confirm the job is listed:**
> ```bash
> python3 scripts/hearth.py --stop && python3 scripts/hearth.py --background
> python3 scripts/hearth.py --status          # the new job MUST appear here
> ```

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

### 6.2 Keeping it alive — ONE hearth per MACHINE, not per agent

**There are two machines, so there are two hearths.** Codex and Antigravity both run on the personal
laptop and **share** its hearth; you do not run one per agent. A hearth serves whatever runs beside
it on the same box.

| Machine | Hearth | Serves |
|---|---|---|
| Work laptop | #1 — **live since 2026-09-11, cron-persisted** | Claude Code |
| Personal laptop | #2 — **not yet set up** | Codex **and** Antigravity |

**Why it was off for three days, which is the instructive part.** It was started on 2026-09-08 with
`--background`. That double-forks, so it survives the *shell* closing — but not the *VM* closing.
WSL shuts its VM down once the last terminal exits, and `last reboot` shows WSL restarted three
times between then and 2026-09-11. Nothing registered the hearth to start again, so it simply never
came back. **A process whose entire purpose is to run unattended failed unattended, silently, for
three days** — and the `--status` command that would have revealed it was never run by anything.
Starting it by hand is not setup; it is a one-shot that expires at the next reboot.

**PREFLIGHT — do this first on a new machine; none of it is a WSL default.** The work laptop
happened to have all three already, which is luck, not a given:

```bash
ps -p 1 -o comm=                       # expect "systemd". If it says "init", see the wsl.conf note
command -v crontab || sudo apt install -y cron    # cron is often absent on a fresh Ubuntu WSL
pgrep -x cron || sudo service cron start          # installed != running; @reboot never fires if down
```

If PID 1 is **not** systemd, cron will not be started for you at boot. Enable it once:
```ini
# /etc/wsl.conf   (needs sudo; then from Windows: wsl --shutdown, and reopen the terminal)
[boot]
systemd=true
```
Skipping this is the quiet failure mode: `crontab -e` succeeds, the entry looks installed,
and nothing ever runs it.

**The fix on this machine (cron, no privileges needed):**
```bash
crontab -e     # then add both lines:
@reboot      cd /path/to/JARVIS && .venv/bin/python3 scripts/hearth.py --background >> jarvis_data/hearth.log 2>&1
*/10 * * * * cd /path/to/JARVIS && .venv/bin/python3 scripts/hearth.py --background >> jarvis_data/hearth.log 2>&1
```
Two triggers, one command. `@reboot` covers WSL starting; the 10-minute entry is the self-heal —
it covers a crash, a missed `@reboot`, and a machine that was asleep. **Firing it repeatedly is
safe**: `--background` refuses when a live pid already holds the port, so the recurring entry is a
no-op whenever the hearth is already up. Verified by killing it and watching cron revive it.

Why cron and not systemd here: systemd *is* PID 1 (`/etc/wsl.conf` has `systemd=true`), but
`systemctl --user` has no session bus in a non-login shell, and a system unit needs `sudo`, which is
not passwordless on this box. cron is already running and a **user** crontab needs no privilege.
Use `~/.venv/bin/python3` (an absolute interpreter path) — cron does not inherit your `PATH`.

**On the personal laptop (Windows) — choose by where Codex actually runs:**
- **Inside WSL** (recommended, and what this repo assumes): identical to the above. `crontab -e`,
  same two lines with that machine's path.
- **Native Windows Python**: `--background` **cannot work** — it needs `os.fork`, and the script
  says so and exits. Prefer Task Scheduler when the account permits it. On a managed Windows
  account where Scheduler is denied, install the tracked per-user fallback once:

  ```powershell
  python scripts/windows_hearth_watchdog.py --install
  python scripts/windows_hearth_watchdog.py --status
  ```

  It writes one `HKCU\\...\\Run` value — no administrator permission, service, or scheduled task —
  so Windows launches a hidden watchdog directly at logon. The watchdog owns a foreground native
  `hearth.py` child and restarts it after a crash. It is intentionally per-user: it runs while the
  user is logged in, not while Windows is powered off. Remove it with `--uninstall`.

**The honest ceiling: "always on" means "whenever the machine is on and WSL is up."** A hearth
cannot run while the laptop is asleep or shut down, and WSL is not running when no terminal or
scheduled task has started it. Jobs are cadence-based rather than wall-clock exact, so a missed
window is caught on the next tick rather than skipped — but a machine that is off for a week does a
week of catching up when it returns, not nothing.

**Check, never assume:**
```bash
python3 scripts/hearth.py --status      # UP/DOWN plus per-job last-run
crontab -l                              # is the keepalive actually installed?
tail jarvis_data/hearth.log             # what cron's attempts did
```
A stale `.hearth_jobs.json` reports the last tick, which may be weeks old — that file existing does
**not** mean the clock is running.

---

## 7. What is not built

### 7.1 An Antigravity capture adapter — **BUILT & SHIPPED 2026-09-14 (`scripts/ingest_antigravity_sessions.py`)**

**Closed 2026-09-14 by Antigravity under Q006.**
Claude Code asked in `q_004` / `q_006`:
1. *Does Antigravity ever prune or rotate old conversation directories?*
   **Answer: NO.** Audit of `~/.gemini/antigravity-ide/brain/` confirmed 17 valid sessions dating
   from 2026-04-03 all the way to present, completely intact. There is no pruning, rotation, or
   garbage-collection.
2. *Can the adapter backfill history and run automatically?*
   **Answer: YES.** `scripts/ingest_antigravity_sessions.py` was built, self-tested (19/19 offline tests),
   and backfilled 359 historical exchanges into `observation_queue.jsonl`.
3. *Is it scheduled?*
   **Answer: YES.** Added to `default_jobs()` in `serve/scheduler.py` as `ingest_antigravity`
   (`interval_seconds=1 * HOUR`, `initial_delay_seconds=240.0`). The hearth now runs it hourly alongside
   `ingest_codex`.

**Adapter architecture details:**
- Formats handled across 3 generations: `transcript_full.jsonl` (modern, untruncated) > `transcript.jsonl` (mid) > `overview.txt` (April 2026 JSONL format).
- Envelope stripping: `strip_antigravity_wrapper` removes `<USER_REQUEST>`, `<ADDITIONAL_METADATA>`, `<WORKFLOW>`, `<USER_SETTINGS_CHANGE>`, `<UUID>`, while preserving code blocks and user XML.
- Assistant summarization: joins multi-step `PLANNER_RESPONSE` outputs into unified markdown summaries.
- Timestamps: converts UTC ISO timestamps to IST (+05:30) and passes `ts=turn_ts` to `build_observation()`.
- Watermarking: append-only per-session log at `jarvis_data/.antigravity_ingest_watermark.jsonl`.
- Verification: `python3 scripts/ingest_antigravity_sessions.py --self-test` (hermetic tempdir tests, zero `~/` access).

### 7.2 Codex and Antigravity have no hook-driven parse trigger

Neither host has hooks, so the "parse about every 10 turns" duty (§3.2, §3.3) is written in
`AGENTS.md` and `js-workspace-rule.md` rather than fired by a hook. What keeps it honest is the
backlog count: `bootstrap_jarvis.py --check` and `pipeline_health.py` show each host's unparsed
turns and their oldest age, so a skipped parse is visible at every boot on every host, including
to Claude and to JARVIS. `notice_runtime_change` stays unported — low value on a host that runs one
model per session.

---

### 7.3 General perception of absence — requested 2026-09-11, designed, not built

The user asked for it directly: *"JARVIS doesn't notice you stopped working on the finance thing
unless something measures that — I want this general perception of absence."*

It is the natural sibling of `agent/tension.py`. That organ surfaces **contradiction** over your
own history; this one would surface **silence**. Both answer "what would JARVIS say that you did
not ask for," which ENDGAME §1.2 names as the whole moat.

**Two measurements were run first, and both killed an obvious design. Read them before building.**

*Measurement 1 — domain-level dormancy has no signal.* Across 100 days and 607 captured turns, all
six domains (`general`, `data-engineering`, `finance`, `jarvis-build`, `ai-ml`, `unknown`) were last
active **0–2 days ago**. A "domain has gone quiet" detector would fire **never**, or would need a
threshold so short it becomes noise. *You do not stop touching finance; you stop touching one
specific question inside it.* The granularity is wrong, not the idea.

*Measurement 2 — keyword-matched "open loops" are mostly false positives.* Scanning the KB for
deferral language (`deferred`, `revisit`, `pending`, `still need`, `TODO`, `not yet`, …) matched 70
entries, 51 of them older than 30 days — which looks like a rich signal until you read the rows.
The top hits include `"Decision: Skip Phase 1.4 … as standalone study"` and `"/next verdict:
Sub-phase 2.4 COMPLETE"` — **closed** decisions that merely contain deferral vocabulary. This is the
fourth time keyword matching against an open vocabulary has failed in this repo (see `nse` matching
inside "response", the SFT reason gate, the Codex placeholder regex). Do not build the detector
this way. It will look like it works and quietly generate noise.

**What the measurements imply.** The signal is not absence of *activity*; it is absence of
*resolution*. And resolution state should be **recorded, not inferred** — the same move that
replaced `domain_guess` (a keyword hint) with `domain_labels.jsonl` (an explicit projection).

**Tier 1 — a commitment registry (build this first; it is the cheap part).**
When a decision defers something, write it as a structured record rather than prose: what was
deferred, the condition that would resolve it, and a review horizon. The repo *already does this
informally* and those cases are machine-checkable today — GraphRAG was originally a trigger-gated
open loop and is now a required follow-on behind the always-reachable Context Ledger foundation.
That reversal is itself why the registry matters: the new fact and its revised resolution condition
are recorded instead of leaving stale prose to be inferred. Make that shape first-class and absence
detection becomes a boring scan with no inference and no false positives. Stop inferring what you
can record.

**Tier 2 — a dormancy detector over that registry**, mirroring `tension.py`'s proven architecture:
candidate selection → LLM judge with an **abstention option** → confidence floor → append-only
watermark so nothing nags twice. Crucially, `tension.py` shipped with `scripts/eval_tension.py`, a
labelled gold set where a positive case *must* surface and a negative case *must stay silent*.
**Build the equivalent gold set before the detector**, or you cannot tell a working detector from a
broken one — which is exactly how the previous volume-based detector died after producing zero
insights for months without anyone noticing.

**Tier 3 — statistical dormancy over topic clusters.** Only if Tiers 1–2 prove insufficient.
Measurement 1 says the data is bursty and coarse-grained, so this is speculative; it needs finer
clustering than `domain_guess` provides and would have to clear the same anti-inductive test —
a threshold whose satisfiability does **not** decay as the corpus grows.

**The one thing not to do:** ship a detector that reports "you have 51 stale items." Most of them
are finished work. A false-positive firehose trains the user to ignore the channel, and an ignored
channel is indistinguishable from a broken one — which is the failure this whole organ exists to
prevent.

---

## 8. Maintaining this file

Update it when a host is added, a capture mechanism changes, or a degraded-mode statement stops
being true. Substantive **rules** land in `.agent/rules/CLAUDE.md`; this file explains **mechanism
and operations**.

And the rule from §0, restated because it is the one this document exists to break: **if you are
about to write down a number, write down the command that prints it instead.**
