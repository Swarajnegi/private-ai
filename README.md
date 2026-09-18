# JARVIS

A private "Model of Models" cognitive orchestrator and autonomous R&D lab. Not a chatbot wrapper —
a system built to be trained on one person's own corpus and deployed as an ambient presence across
their devices.

---

## Talk to JARVIS in your browser

With the hearth running, open **http://127.0.0.1:8756/**. The web workspace has searchable
conversation history, an animated core, live hearth/job status, Markdown tables and code blocks,
full-message copy and Markdown export, drafts, and a layout that adapts to narrow screens.

On first connection, use **Choose the token file** and select `jarvis_data/.hearth_token`.
This is the local hearth token, not an OpenRouter API key. It stays in the browser tab's session
storage. Existing browser connections are migrated automatically. All UI assets are served locally.

**Enter** sends; **Shift+Enter** adds a line; **Alt+N** starts a conversation; **/** searches titles
and first prompts. Selecting a conversation continues that exact session. A blank model field uses
the configured brain. **Configure** exposes model reasoning and tool settings; gated actions are
opt-in. The system panel shows the complete execution trace and actual scheduler status.

New answers are stored in full and displayed without a character limit. Named terminal sessions
also appear in history. Older answers saved under the former 2,000-character cap cannot recover
their missing text from those transcripts. The model's short-term context budget still uses
explicit excerpts; it does not shorten the saved or displayed answer.

Verification: `python js-development/jarvis_core/serve/hearth.py` and
`python js-development/jarvis_core/brain/conversation.py`. The browser regression in
`scripts/verify_hearth_ui.cjs` uses Playwright with Edge and an isolated local fixture server;
set `JARVIS_UI_LIVE=1` to additionally read the real hearth's session list and history.

---

## ⇢ If you are an AI agent starting work on this repo, read this section first

Four agents' worth of context live in these files. **Read them in this order**, then you are current
— there is no separate onboarding, and nothing important is only in someone's chat history.

### Tier 0 — one command, before anything else

```bash
python3 scripts/bootstrap_jarvis.py --check
```
Reports repo state **and** machine state — venv, dependencies, vector index, hearth, clock
keepalive, unanswered agent mail — with the fix command inline for each gap. Machine state does not
travel with git; on a fresh clone several will be MISSING. Fix those first, then read on.

### Tier 1 — before your first response, every session (~10 min)

| # | Read | Why |
|---|---|---|
| 1 | **your own entry file** — [`AGENTS.md`](AGENTS.md) (Codex) · [`.agent/rules/js-workspace-rule.md`](.agent/rules/js-workspace-rule.md) (Antigravity) · [`CLAUDE.md`](CLAUDE.md) → [`.agent/rules/CLAUDE.md`](.agent/rules/CLAUDE.md) (Claude Code) | Your host's boot ritual. **Auto-loaded** — but read it consciously the first time |
| 2 | [`NERVOUS_SYSTEM.md`](NERVOUS_SYSTEM.md) **§1** | Four misconceptions that otherwise make you tell the user confidently wrong things about what JARVIS can see. Non-optional |
| 3 | [`.agent/rules/CLAUDE.md`](.agent/rules/CLAUDE.md) | **The canon.** Code style, memory hygiene, migration discipline, what not to do. Applies to every host, not just Claude Code |
| 4 | [`jarvis_data/cognitive_profile.md`](jarvis_data/cognitive_profile.md) | The standing model of the user — who they are, how they work, active directives. Replaces ever asking "tell me about yourself" |
| 5 | [`jarvis_data/activity_digest.md`](jarvis_data/activity_digest.md) | What happened on the *other* machines, day by day. Check its `Generated` stamp; say so if stale |
| 6 | [`STATUS.md`](STATUS.md) | What the other agents found since your last session: what's mid-flight, what's confirmed broken or not, open commitments with a task and an owner, what's blocked on the user. A snapshot, kept current — not a log |

Then run your host's live checks — the surfacing organ and your mail:

```bash
cd js-development && python3 -m jarvis_core.agent.life_state_monitor --peek   # anything to raise?
cd .. && python3 scripts/agent_mail.py --check <claude|codex|antigravity>     # questions for you?
```

### Tier 2 — to understand *why* the system is shaped this way (~30 min)

| # | Read | Why |
|---|---|---|
| 6 | [`.agent/rules/JARVIS_ENDGAME.md`](.agent/rules/JARVIS_ENDGAME.md) **§1.1 and §1.2** | The goal, and the one capability a frontier subscription cannot replicate. Everything else is in service of this |
| 7 | [`js-learning/JARVIS_MASTER_ROADMAP.md`](js-learning/JARVIS_MASTER_ROADMAP.md) | **Canonical status.** Anything anywhere that disagrees with it is stale, including this README |
| 8 | [`NERVOUS_SYSTEM.md`](NERVOUS_SYSTEM.md) in full | How cross-chat memory actually works, what does NOT survive a `git pull`, per-host setup, and what is not built |
| 9 | [`agents_converse/README.md`](agents_converse/README.md) | How to ask the other agents questions, and answer theirs |

### Tier 3 — read when the work touches them

| Read | When |
|---|---|
| [`js-learning/stage_*/ROADMAP.md`](js-learning/) | Working inside that stage. Stage 5 and 6 are the live ones |
| [`.agent/workflows/`](.agent/workflows/) | **Always relevant** — 8 protocols that fire by *request shape*, not by typing a slash. See the canon |
| [`js-learning/stage_5_specialists/SFT_SPEC.md`](js-learning/stage_5_specialists/SFT_SPEC.md) | Training-data work |
| [`js-learning/stage_6_integration/VOICE_SPEC.md`](js-learning/stage_6_integration/VOICE_SPEC.md) | Voice / interface work |
| [`knowledge/`](knowledge/) | Domain questions — see the map below |
| [`antigravity_review.md`](antigravity_review.md) | An external audit of the training corpus, and the response to it |

**Never read the whole knowledge base.** It is thousands of entries. Query it:

```bash
python3 scripts/search_memory.py "<topic>"     # semantic search — do this before answering anything uncertain
```

---

## Current state

| Stage | Status |
|---|---|
| 1 — Systems Python | ✅ sufficient (1.4/1.5 deliberately deferred) |
| 2 — Memory Layer | ✅ complete |
| 3 — Agent Framework | ✅ complete — built from scratch, not on a framework |
| 4 — Multi-Model Orchestration | ✅ complete — Final Boss 8/8 |
| **5 — Domain Specialists** | ⬅️ **current.** Engineer-first QLoRA on a shared base. Not started |
| 6 — Integration | scoped; the hearth (6.3) and capture adapters (6.8) shipped early, out of order |

**Where it is going**, in one line each — full detail in `JARVIS_ENDGAME.md`:

- **The deliverable** is a *trained* model that is *present* — on phone, desktop and web, wired to
  camera and mic, ambient rather than summoned. Not a terminal command. (§1.1)
- **The moat** is unprompted surfacing over your own history — *"this reverses your July call, and
  the reason you gave then was never addressed."* A frontier model does everything else if you paste
  the right context; it cannot fire when you did not know to ask. (§1.2)
- **The open question** is whether a trained adapter beats the retrieval path already built. It is
  unanswered, and answering it is cheaper than training anything.

Verify status yourself rather than trusting this table:

```bash
python3 scripts/check_projections.py    # is the mind's index current?
python3 scripts/hearth.py --status      # is the clock running? (work laptop: yes, cron-persisted
                                        #  since 2026-09-11. Personal laptop: set it up — §6.2)
git log --oneline -15                   # what actually happened recently
```

---

## The full map

### Code

| Path | What |
|---|---|
| [`js-development/jarvis_core/memory/`](js-development/jarvis_core/memory/) | ChromaDB + BM25 hybrid retrieval, cross-encoder rerank, chunking, compaction |
| [`js-development/jarvis_core/agent/`](js-development/jarvis_core/agent/) | Tool ABC + registry, DAG planner, ReAct loop, MemGPT paging, **capture**, **tension** (the surfacing organ), recall, consolidation |
| [`js-development/jarvis_core/brain/`](js-development/jarvis_core/brain/) | Intent router, model-pool failover, aggregator, epistemic control, context injection, permission gate |
| [`js-development/jarvis_core/serve/`](js-development/jarvis_core/serve/) | **The hearth** — one always-on process owning the clock; loopback HTTP + scheduler |
| [`js-development/jarvis_core/specialists/`](js-development/jarvis_core/specialists/) | Corpus building for Stage 5 |
| `js-development/jarvis_core/body/` | Placeholder — Stage 6 |
| [`js-development/jarvis_core/config.py`](js-development/jarvis_core/config.py) | **Every path resolves here.** Never hardcode one |
| [`scripts/`](scripts/) | CLI tools + the hook adapters in `scripts/hooks/` |

### Data — and which class each file is

The storage taxonomy matters more than the file list. Getting it wrong means either losing something
irreplaceable or committing 25 MB of rebuildable binary:

| Class | Files | Tracked? |
|---|---|---|
| **FACT** — authoritative, append-only, *the actual mind* | `knowledge_base.jsonl`, `observation_queue.jsonl` | ✅ |
| **PROJECTION** — derived, rebuildable, disposable | `chromadb/`, `cognitive_index.sqlite3`, `domain_labels.jsonl` | ❌ |
| **PROJECTION-AS-TRANSPORT** — derived here, consumed by a machine that *cannot* rebuild it | `cognitive_profile.md`, `activity_digest.md` | ✅ and correctly so |

Also in [`jarvis_data/`](jarvis_data/): `life_state_feed.jsonl` (surfaced insights),
`training_corpus/` (Stage 5 corpora + SFT pairs), `experience_map.md`, `personal_life.md`,
`model_catalog.json`, `conversations/`.

### Knowledge and learning

| Path | What |
|---|---|
| [`js-learning/`](js-learning/) | Master roadmap + one per stage. **Ground truth for status** |
| [`knowledge/Data Engineering/`](knowledge/Data%20Engineering/) | Distilled DE lessons, interview prep, ADF deep-dive |
| [`knowledge/AI ML/`](knowledge/AI%20ML/) | ML notes and interview prep |
| [`knowledge/Finance/`](knowledge/Finance/) | **`strategy.md` is canonical** — check it first for any finance question |
| [`knowledge/literature/`](knowledge/literature/), [`knowledge/Job Switch/`](knowledge/Job%20Switch/) | Reading notes; career material |
| [`research_papers/`](research_papers/) | 24 source PDFs, tracked. Rebuild their index with `scripts/ingest.py` |

### Coordination

| Path | What |
|---|---|
| [`agents_converse/`](agents_converse/) | Agent-to-agent questions and answers, delivered by git |
| [`.agent/hooks.manifest.json`](.agent/hooks.manifest.json) | The committed hook wiring. `.claude/settings.json` hooks are rehydrated *from* this |
| [`.claude/settings.json`](.claude/settings.json) | **Tracked since 2026-09-18** — the shared permission allowlist, so a new Claude Code host does not re-approve 164 commands by hand. **Invariant: never put a credential in it** (`GH_TOKEN` goes in the environment, not an allowlist pattern — that is exactly how `b7bfbe6` leaked a PAT). `.claude/settings.local.json` stays per-host and ignored |
| [`NERVOUS_SYSTEM.md`](NERVOUS_SYSTEM.md) | Mechanism, inventory, per-host setup |

---

## First run on a fresh machine

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 scripts/bootstrap_jarvis.py     # rehydrates hooks from the committed manifest; safe to re-run
python3 scripts/index_memory.py         # REQUIRED — chromadb/ is gitignored, so a fresh clone has
                                        # no vector index and semantic search returns nothing
python3 scripts/hearth.py --background  # start the clock (see NERVOUS_SYSTEM.md §6)
```

Optional, for research-paper retrieval (~8 min):
```bash
for p in research_papers/*/*.pdf; do python3 scripts/ingest.py "$p" --collection research_papers; done
```

---

## Conventions worth knowing before reading the code

- **Tests are `__main__` smoke blocks, not a pytest suite** — run a module directly to test it
  (`python3 -m jarvis_core.agent.capture`). Deliberate, and there is **no runner**, which is a real
  gap rather than a hidden feature.
- **Paths never hardcoded** — everything through `config.py`, so one source works on Linux and Windows.
- **Systems Python is non-negotiable**: generators for pipelines, async for I/O, context managers for
  every external resource, strict typing on cross-layer contracts.
- **Append-only logs heal a torn line before writing**, and take the lock. A `flock` stops concurrent
  writers; it does nothing about a writer that was *killed* mid-line.
- **Write to the KB only via `scripts/kb_append.py`** — it locks, dedups at >0.85 similarity, and
  mints a collision-free id. Never hand-append a line.
- **Prose rots.** This repo has caught a dozen cases of a comment confidently describing something
  the code no longer does — including a file mis-describing *itself*. Prefer a command that prints
  the answer over a number typed into a document. If you find such a case, fix it *and* say so.

---

## Not in this repository

`client_work/` holds employer/client material and is excluded by [`.gitignore`](.gitignore) —
permanently, regardless of repo visibility. **`.gitignore` is the authority on that boundary, not a
paraphrase of it**; it carries deliberate re-inclusions. Note that `jarvis_data/training_corpus/`
**is** tracked and does contain client-derived text; that tradeoff is documented in the `.gitignore`
header and was confirmed twice.

Also absent from a fresh clone: the vector index, the venv, and every machine-local projection —
see [`NERVOUS_SYSTEM.md`](NERVOUS_SYSTEM.md) §4 for the complete inventory and how to rebuild each.
