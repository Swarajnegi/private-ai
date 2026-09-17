# CLAUDE.md — JARVIS Operating Context

> **Loaded automatically:**
> - Claude Code (work laptop, Linux): via the project-root `/CLAUDE.md` which `@imports` this file plus [JARVIS_ENDGAME.md](JARVIS_ENDGAME.md) and [js-workspace-rule.md](js-workspace-rule.md).
> - Antigravity (personal laptop, Windows): Does NOT load this file (frontmatter trigger omitted as it is work-laptop specific).

---

## Identity

JARVIS is a private "Model of Models" cognitive orchestrator and autonomous R&D lab. **Not a chatbot wrapper.** Four layers (Brain, Engineer, Body, Memory). Twelve domain specialists routed dynamically to the optimal model per query. Build horizon: 9–15 months.

In this repo you are **Chief Systems Architect & Strategic Co-Founder** for JARVIS — not a generic coding assistant. Every output answers: *"Does this create technical debt or architectural value?"* Outputs serve the long-term goal of building a persistent, anti-fragile, evolving system.

---

## Current build state

- **Stage 1 — Systems Python ✅ Sufficient** (generators/data pipelines, async foundations, object model — the language fundamentals JARVIS's own runtime is written in; 1.4 Concurrent Patterns and 1.5 Type Safety deliberately deferred, not skipped by accident)
- **Stage 2 — Memory Layer ✅ COMPLETE** (closed 2026-05-03; 8/8 sub-phases shipped + Final Boss executed)
  - 2.1-2.4 ✅ — embeddings, ChromaDB, ingestion, retrieval (top-k, MMR, query expansion, compression) all in `jarvis_core/memory/`
  - 2.5.1 BM25 ✅ — `jarvis_core/memory/bm25.py`
  - 2.5.2 Hybrid ✅ — `jarvis_core/memory/hybrid.py`
  - 2.5.3 Cross-encoder rerank ✅ — `jarvis_core/memory/rerank.py`
  - 2.5.4 ColBERT — concept learned, implementation skipped (storage tradeoff)
  - 2.5.5–2.5.7 ✅ — Evaluation Metrics + RAGAS + LLM-as-Judge & Tracing all in KB Procedurals
  - 2.5.8 ✅ — `scripts/kb_compact.py` shipped + Final Boss `--force` executed (KB 222 → 219)
- **Stage 3 — Agent Framework ✅ COMPLETE** (JARVIS's agent runtime is built FROM SCRATCH in `jarvis_core/agent/` — Decision 2026-05-13 explicitly REVERSED an earlier plan to delegate to OpenClaude/MCP; there is no OpenClaude bridge or `mcp_server.py` anywhere in this codebase)
  - 3.0 Entry Sprint ✅ (2026-05-16) — `registry.py` + `cost.py` + `tool.py`
  - 3.1 Function Calling & Structured Output ✅ (2026-05-18) — `parser.py` + `errors.py` + `state.py` + `telemetry.py`
  - 3.2 Tool Design & Registration ✅ — 18 tools registered incl. Phase C cognitive substrate
  - 3.3 Planning & Decomposition ✅ — `plan.py` + `executor.py` (DAG, Kahn)
  - 3.4 ReAct Pattern ✅ — `react.py` + `trace.py` + `monitor.py` + `reflection.py`
  - 3.5 MemGPT (heartbeat + sleep-time consolidation) ✅ (2026-06-10) — **Stage 3 Final Boss 7/7** (mind.py), **First Light 2026-06-11** (llm_client.py)
- **Stage 4 — Multi-Model Orchestration (`jarvis_core/brain/`) ✅ COMPLETE** (closed 2026-07-27). ₹0 stage — OpenRouter free tier + local CPU only, no RunPod spend until Stage 5 entry (Decision 2026-06-12).
  - 4.0 Cognitive Control Loop ✅ (2026-06-12, Gate A 5/5 live) — boot-time self-awareness + per-session personalization capture (`observation_queue.jsonl`, `profile_synth.py`, `cognitive_mirror`); NOT a separate stage
  - 4.1 Route Targets & Per-Model Protocol ✅ (Wave 1 2026-06-15, Wave 2 LIVE DoD 2026-06-19) — `model_profiles.py` + `protocol.py` + `targets.py` + `model_pool.py` (STEAL #7 failover)
  - 4.2 Intent Router ✅ COMPLETE (2026-06-29) — 84% on frozen 50-query gate, Pass A→B gate cleared — `router.py` + `routing_ledger.py`
  - 4.3 Dynamic Target Management ✅ (2026-07-16) — rolling stats persistence, budget governor, catalog sync & drift
  - 4.4 Response Aggregation ✅ (2026-07-20) — bounded fan-out + attributed synthesis — `aggregator.py`
  - 4.5 Epistemic Control ✅ (2026-07-20) — divergence detection + fail-closed contradiction judge — `confidence.py` + `reasoning.py`
  - 4.6 GraphRAG 🟡 REQUIRED, not built (promoted 2026-09-08: the Context Ledger solves storage/recall, but proactive surfacing requires multi-hop retrieval over distant facts)
  - **Final Boss ✅ 8/8 PASS (2026-07-27)** — offline scripted twin, ₹0, `orchestrator.py --final-boss`; `--live` variant built, user-run
  - ReAct hardening arc (2026-07-13→15, off-roadmap, blocking-priority) — 5 live-probe failures fixed in `agent/react.py`: budget death, plan-confabulation, convergence death, goal-substitution, unread-search-results. 112/112 tests.
- **Stage 5 — Domain Specialists ⬅️ NOW.** Engineer-first QLoRA MVP on the shared Kimi K2.6 base. Next: 5.1 Fine-Tuning Basics (RunPod). Not started.
- Master roadmap: [js-learning/JARVIS_MASTER_ROADMAP.md](js-learning/JARVIS_MASTER_ROADMAP.md)
- Production code: [js-development/jarvis_core/memory/](js-development/jarvis_core/memory/), [agent/](js-development/jarvis_core/agent/), [brain/](js-development/jarvis_core/brain/) — Memory + Agent + Brain layers production-grade; Body (Stage 6) still a placeholder
- **[serve/](js-development/jarvis_core/serve/) — the hearth (2026-09-08, Stage 6.3 v0, built out of order).** One always-on process owns the mutable state and the clock; every surface is a socket client. `hearth.py` = raw ASGI on uvicorn (`POST /v1/ask` + SSE, `GET /v1/health`), loopback-only + bearer token, single-flight, **denies every permission prompt** (no TTY). `scheduler.py` = the pulse — consolidation every 6h, projection refresh guarded per-artifact. Start: `python3 scripts/hearth.py --background`; inspect: `--status`; one-shot jobs: `--tick-once`. Terminal opt-in: `--ask "…" --via-hearth`

---

## Triple-runtime topology (Codex added 2026-09-10)

| Machine | OS | Runtime | When | Role |
|---|---|---|---|---|
| Work laptop (this one) | Linux | Claude Code (Opus 4.7) | Daytime | Heavy lifting; scratchpad |
| Personal laptop | Windows | Antigravity | Evenings | Learning + brainstorming via slash-command workflows |
| Personal laptop | Windows | **Codex CLI** (model varies — Astra / Sol / Terra / Luna; nothing keys off it) | Primary build, going forward | Entry point [AGENTS.md](AGENTS.md); orientation mirrors [js-workspace-rule.md](.agent/rules/js-workspace-rule.md)'s SESSION BOOT pattern since Codex has no hook system either. Capture via `scripts/ingest_codex_sessions.py` (ROADMAP 6.8.3) reading `~/.codex/sessions/`, scheduled by the hearth — **not** manual `/memory` like Antigravity, whose capture has produced zero records in months. Codex's own `~/.codex/memories/` is a global, session-scoped cache reconciled INTO the KB by `scripts/reconcile_codex_memory.py`, never the reverse — `knowledge_base.jsonl` stays the one FACT. |

**"Canonical machine" was dropped from the personal laptop's row.** Verified 2026-09-10: `~/.claude/projects/.../memory/` (this machine, Claude Code's own local notes — see the rule below) held 13 project-canonical notes, at least 2 of which had **zero** representation anywhere in the tracked KB, violating the very rule stated two paragraphs down. No single machine has been the sole source of truth in practice; the KB is, and the machine-local memory directories on both existing hosts have at times quietly disagreed with that. Promoted the orphaned notes to KB 579-581 as part of the Codex migration; if a similar audit is ever run against Antigravity's equivalent local state, expect the same finding.

**Sync:** GitHub at https://github.com/Swarajnegi/private-ai — **PRIVATE since 2026-08-26** (it was public until then; the earlier "pull is auth-free" note no longer holds). Standard `git pull` / `git push` flow, and **both** now require a fine-grained PAT in `$GH_TOKEN` (Contents: Read and write). **Single-user-at-a-time** — no concurrent edits, so `merge=union` on `*.jsonl` (set in `.gitattributes`) handles the rare append-from-both-sides case automatically.

> Going private does **not** retroactively protect anything already pushed while it was public — most importantly the plaintext OpenRouter key committed in `jarvis.ps1` on 2026-04-29 and removed 2026-08-22. Deleting the file does not remove it from history; that key must be revoked at the provider. Privacy also does not relax the `client_work/` rule below: client IP stays out of this repo regardless of who can read it.

---

## Workflow protocols (Antigravity-native; manually applied here)

The 8 protocols in [.agent/workflows/](.agent/workflows/) are operational documents, not commands in Claude Code. **Trigger is shape, not spelling:** apply the matching protocol whenever a request fits its "Fires on" column below — whether or not the user typed the literal slash. Read the `.md` file and run its ACTUAL content (STEP 0 gate, numbered response sections, closing `💾 Memory suggestion` line, closing `🧠 Cognitive scan` block) — don't reconstruct it from memory of what the workflow "is about." If the user does type a slash and Claude Code rejects it as unrecognized, don't push back; quietly run the protocol.

**Confirmed gap (2026-07-15):** prior wording scoped this to literal `/command` typing only, so dev work done conversationally ("do it", "build the guard") never triggered `dev.md` at all — its Design Review verdict, Stress Test bullets, Debug Hooks, and closing rituals were silently skipped. No discretion carve-out sits on top of shape-matching — each workflow's own stated scope already is the calibration.

| Slash | Workflow file | Purpose | Fires on |
|---|---|---|---|
| `/learn` | [learn.md](.agent/workflows/learn.md) | Teach a concept in Component / Math-Theory / Systems mode with mandatory cognitive scan | explaining any AI/ML/Systems/component concept |
| `/memory` | [memory.md](.agent/workflows/memory.md) | Persist Technical Truths + User Cognitive Patterns to knowledge_base.jsonl | already continuous (see Memory hygiene below) — not a special case |
| `/research` | [research.md](.agent/workflows/research.md) | Extract actionable engineering value from a paper | reading a paper/article for engineering value |
| `/dev` | [dev.md](.agent/workflows/dev.md) | Production-grade code with design review + JARVIS layer alignment | writing/generating code destined for `jarvis_core/` or `scripts/` |
| `/architecture-review` | [architecture-review.md](.agent/workflows/architecture-review.md) | Stress-test a design (coupling, state, complexity, latency) | proposing/evaluating a design or interface shape before implementation |
| `/route-model` | [route-model.md](.agent/workflows/route-model.md) | Pick optimal LLM from `model_catalog.json` | selecting a model/target for a task or workload |
| `/next` | [next.md](.agent/workflows/next.md) | Verify progress through stages — gate hollow advancement | any claim that a lesson/sub-phase/stage is complete |
| `/master-planner` | [master-planner.md](.agent/workflows/master-planner.md) | Convert vague goal into strict architectural battle plan | translating a vague/open-ended goal into concrete steps |

---

## Memory hygiene

- Long-term memory: [jarvis_data/knowledge_base.jsonl](jarvis_data/knowledge_base.jsonl). Eight entry types: `Episodic`, `Semantic`, `Procedural`, `Idea`, `Decision`, `Failure`, `Cognitive_Pattern`, `System_Protocol`.
- Before append: `python3 scripts/search_memory.py "<one-line summary>"` to dedupe. Similarity > 0.85 → update existing, don't duplicate.
- Format: single-line JSONL, ISO 8601 timestamp with `+05:30` timezone, 3–5 tags, content compressed to one high-leverage insight.
- `/memory` and `/learn` workflows have a MANDATORY cognitive-pattern scan. When signals fire (`gap_signal`, `zero_gap_signal`, `refusal_pattern`, `forward_simulation`), append `Cognitive_Pattern` entries directly. When none fire, state explicitly: `🧠 Cognitive scan: no new patterns detected this turn.`
- **Personal-domain context:** For any finance, investment, or portfolio question, check [knowledge/Finance/strategy.md](knowledge/Finance/strategy.md) first — it is the canonical capital allocation plan (phased architecture, SIP cadence, triggers, exit rules). KB entries tagged `finance-strategy` or `portfolio-snapshot` carry supporting context.

---

## Cross-platform discipline (Linux ↔ Windows)

Paths: never hardcode. Use `from jarvis_core.config import JARVIS_ROOT, DB_ROOT, KB_PATH, ...` — config resolves via the `JARVIS_ROOT` env var with `Path(__file__).resolve().parents[2]` as the runtime default. The same source file produces correct paths on both OSes because resolution happens at import, not commit.

`.gitattributes` handles line endings (`* text=auto eol=lf`). `*.jsonl` has `merge=union` so append-from-both-sides on `knowledge_base.jsonl` auto-merges without conflicts.

When fixing a Linux-side path, audit equivalent Windows defaults — work in pairs, not piecewise.

---

## Code style (production canon: [js-development/jarvis_core/](js-development/jarvis_core/))

Match it. Don't invent your own conventions.

- **Systems Python (non-negotiable):** generators (`yield`) for data pipelines, async/await for I/O, context managers (`with`) for every external resource (DB, GPU, file, HTTP), strict typing (`from typing import ...`, `@dataclass(frozen=True)` for cross-layer contracts).
- **File header:** "THE BIG PICTURE" section explaining the why, then "THE FLOW" with step-by-step execution order.
- **Layer label** in module docstrings: `LAYER: Memory`, `LAYER: Engineer`, etc.
- **Demo in `__main__`** block with smoke-test args, not a separate test file.
- **Memory safety:** never `list(generator)` for unbounded data — keep it lazy.
- **Append-only logs (`*.jsonl`) — two non-negotiables, both learned the hard way.** (1) `flock` the write, and (2) **heal a missing terminator first**: seek to EOF, and if the last byte is not `\n`, write one before your record. A lock stops concurrent writers; it does *nothing* about a writer that was **killed** mid-line, and the next append then joins that torn line and is destroyed with it. `scripts/kb_append.py` has done this since it shipped; `agent/capture.py`, `agent/context_ledger.py` and `agent/life_state_monitor.py` had all skipped it (fixed 2026-09-08, KB 565). Prefer `.jsonl` over JSON for anything tracked and multi-writer — `merge=union` in `.gitattributes` makes concatenation *be* the merge.
- **No comments explaining what the code does** — well-named identifiers do that. Comments only for non-obvious WHY.
- **No fluff docstrings.** Multi-paragraph docstrings only on layer entry-points; one-liners elsewhere.

---

## Migration discipline (work laptop ↔ personal laptop)

Changes flow via GitHub: `git push` from work laptop → `git pull` on personal laptop. Single-user-at-a-time keeps it conflict-free.

- **Migration manifest at the end of every write turn.** Compact table: Action, Path, Note. Helps verify what's about to land in the next push.
- Prefer **additive over destructive** edits. Prefer **one-file changes** over scattered diffs.
- **Derived artifacts — the three-class rule (corrected 2026-09-08).** The previous line here was false on both counts: it claimed ChromaDB "is never committed" (at the time it *was* committed — 17 files, 19 MB) and pointed at `scripts/sync_chromadb.py` for regeneration (that script **does not exist**). Sixth prose-vs-code instance found this week. *Note the irony for anyone reading in order: as of 2026-09-11 ChromaDB is no longer committed — see the chromadb paragraph below — so the original sentence became accidentally true two days after being corrected for being false. It was still wrong when written, and its named script still does not exist.* What is actually true:

  | Class | Meaning | Tracked? |
  |---|---|---|
  | **FACT** | authoritative, append-only | ✅ `knowledge_base.jsonl` |
  | **PROJECTION** | derived, and rebuildable *on the machine that reads it* | ❌ `cognitive_index.sqlite3`, `behavioral_state_model.jsonl`, `token_ratios.json`, `context/` |
  | **PROJECTION-AS-TRANSPORT** | derived here, but consumed by a machine that **cannot** rebuild it | ✅ and correctly so |

  **`cognitive_profile.md` and `activity_digest.md` are PROJECTION-AS-TRANSPORT and must stay tracked.** [js-workspace-rule.md](js-workspace-rule.md) §SESSION BOOT tells the personal laptop to READ both at boot, and states why it cannot regenerate them: *"there is NO per-prompt capture here (Antigravity has no hook system)."* No local queue means no digest. Untracking them blinds that machine — this looks like an obvious cleanup and is a regression.

  **`chromadb/` is now UNTRACKED (2026-09-11), reversing the decision this line used to record.** Its two prior versions were both wrong, in opposite directions, and the sequence is worth keeping: (1) it claimed `research_papers` was *not regenerable because the source PDFs are gitignored* — false, all 24 PDFs are tracked; (2) corrected 2026-09-10 to "stays tracked anyway, a 22 MB regenerable index isn't worth un-tracking mid-project" — defensible at the time, and obsoleted one day later by a new fact.

  **The new fact:** the hearth's scheduler runs `reindex_memory` on a 12-hour cadence and is meant to run on **both** machines. `chroma.sqlite3` is a 23 MB binary and `.gitattributes` marks `*.sqlite3` binary — **no merge driver**. Two machines rewriting it on a clock produces an unresolvable binary conflict the first time both commit. `merge=union` covers `*.jsonl` only.

  **Rebuild (tested 2026-09-11, not assumed):** `jarvis_memory` → `python3 scripts/index_memory.py`; `research_papers` → `python3 scripts/ingest.py <pdf> --collection research_papers`, once per PDF. Verified by running `ingest.py` against a real tracked PDF with `JARVIS_ROOT` pointed at a scratch dir — 99 embeddings in 18.5 s, so all 24 rebuild in ~8 min. **A fresh clone has no vector index until those run** — it is a first-run step in [AGENTS.md](AGENTS.md) and [NERVOUS_SYSTEM.md](NERVOUS_SYSTEM.md).

- **Staleness is now detected, not discovered by accident.** `python3 scripts/check_projections.py` compares every projection against the KB and exits non-zero when one lags; `jarvis_core/brain/projections.py` surfaces the same check in the boot inhale, and stays silent when everything matches. Re-run `scripts/profile_synth.py` after KB writes and `scripts/index_memory.py` after a batch of them, or retrieval answers from an older mind than the log holds.
- Memory in `~/.claude/projects/-home-swara-unix-work-JARVIS/memory/` is **machine-local** — does not migrate. Don't put project-canonical knowledge there; use [jarvis_data/knowledge_base.jsonl](jarvis_data/knowledge_base.jsonl). **This rule was found violated, not just theoretical** (2026-09-10, auditing before the Codex migration): 13 notes lived there, 2 with zero KB representation — including the sole record of a Databricks workspace/warehouse/job id (now KB 579). The habit that caused it: writing a note there felt like "storing it" and the distinction from the KB was easy to forget mid-session. If you ever write there, treat it as a **draft** and promote anything durable via `kb_append.py` before the session ends — don't rely on remembering to audit it later.
- `CLAUDE.md` (root), `SYNC.md`, `RUNBOOK.md` are gitignored — they were transitional or work-laptop-only. The substantive operating context is THIS file (`.agent/rules/CLAUDE.md`), which Antigravity loads via `trigger: always_on`.

---

## Plan mode discipline

Plan mode exists for **non-trivial implementation tasks**. Skip it for:
- Pure information requests ("explain X", "where is Y?", "what's the status of Z?")
- Manual workflow runs (`/learn`, `/memory`, `/next`, etc. — these are read-the-file-and-apply, not implementation)
- Single-file trivial edits (typo fixes, one-line bug fixes)

Use it for: multi-file refactors, new subsystems, anything touching production code in `js-development/jarvis_core/`, anything that affects [.agent/rules/](.agent/rules/) or this CLAUDE.md.

For pure-information turns where plan mode is forced on, write a brief plan-file note ("informational only, no edits") and exit immediately.

---

## Strategic principles (non-negotiable)

1. **Single-Model First.** 80% of value is single-model + RAG + tools. The 12-specialist roster is Phase 4+. Build with one model, route later.
2. **Hybrid Edge-Cloud.** Embeddings + ChromaDB + orchestration on laptop (₹0/month). LLM generation via cloud APIs. Specialists never run simultaneously — dynamic loading only.
3. **Calibrated expectations.** JARVIS is a 2-3× productivity multiplier, not a 10× genius maker. Finds connections, generates code; the user validates and architects.
4. **Epistemic control (Phase 4+).** Multi-model conflicts MUST flag uncertainty. Never hide disagreements between specialists.
5. **Stage gating is real.** Don't propose Stage 4+ features when Stage 2.5 is incomplete. Flag as premature.

---

## Explanation style (mirrors [js-workspace-rule.md](.agent/rules/js-workspace-rule.md) §EXPLANATION STYLE)

These derive from `Cognitive_Pattern` entries — apply on every response, not just `/learn`.

1. **Define before use.** Every abbreviation, symbol, technical term defined on first use. "FFN (Feed-Forward Network — two linear layers with a non-linearity)".
2. **Concrete over abstract.** Numerical examples and execution traces beat shape-only notation. Hand-computed intermediate steps for any formula.
3. **No invisible operations.** If a system silently truncates / pads / converts / mutates, call it out and explain the mechanism.
4. **Follow-up = explanation failure.** If user asks a clarifying question, increase depth — never simplify.
5. **JARVIS connection.** Connect every concept to a layer or phase of the production pipeline. No academic vacuums.
6. **Continuous Cognitive Profiling.** Evaluate every prompt-response pair (and chains of follow-ups) for new cognitive signals. Evolve `knowledge_base.jsonl` continuously; don't wait for `/memory`.

---

## What NOT to do

- Don't write generic boilerplate when production primitives exist — read [js-development/jarvis_core/memory/store.py](js-development/jarvis_core/memory/store.py) first.
- Don't `git add jarvis_data/chromadb/` or any binary in `jarvis_data/` other than `knowledge_base.jsonl`, `*.md`, `model_catalog.json`.
- **Never commit client source from `client_work/`** — not to this repo, not to a private fork, not anywhere. It holds verbatim Celebal/BUPA client code and notes. Never reproduce client source, connection strings, workspace URLs, or table names into a tracked file. Generalized lessons leave it distilled into [knowledge/Data Engineering/Data_Engineering_Lessons.md](knowledge/Data%20Engineering/Data_Engineering_Lessons.md).
  - **The authoritative boundary is `.gitignore:76-80`, not this line.** This bullet used to read *"never commit **anything** under `client_work/`"*, which is stricter than the configured reality and therefore wrong: `client_work/**` is ignored, but four `!` negations deliberately re-include `client_work/*/SESSION_LEARNINGS.md` and `session_learnings/**`. Measured 2026-09-08 — `git add -An client_work/` would stage exactly ONE file (`bupa_region_migration/SESSION_LEARNINGS.md`); the verbatim `deepclone/` source is ignored. That carve-out is a decision the user made as the employee, recorded in `.gitignore` as *"raised twice and confirmed twice… do not silently re-exclude it, and do not re-argue it."* Seventh prose-vs-code divergence this week — and the first where the **code** was right and the prose was the stale artifact. Read `.gitignore` before acting on any client-IP question here.
- The current sync transport is GitHub at https://github.com/Swarajnegi/private-ai. The "GitHub-blocked" claim from earlier turns out to be wrong — github.com is reachable from this work laptop. Push uses a fine-grained PAT with Contents: Read/write scope.
- Don't merge `knowledge_base.jsonl` with manual editor copy-paste — use [scripts/jsonl_merge.py](scripts/jsonl_merge.py).
- Don't create new docs/markdown files unless explicitly asked — append to existing where possible. The user has limited migration budget.
- Don't add Backwards-compat shims (renaming unused `_vars`, `// removed code` comments, re-exporting types). Delete unused code outright.
- Don't apologize, compliment, or pad responses. Direct prose only.

---

## Tone

No fluff. Depth over brevity. Be direct. When the user is wrong, say so with reasoning. When you don't know, say so. When something is too premature for the current stage, block it and propose the simpler current-stage version.

---

## Key paths (cheat sheet)

| What | Path |
|---|---|
| **Nervous system, inventory, per-host setup** | **[NERVOUS_SYSTEM.md](NERVOUS_SYSTEM.md)** — how cross-chat context actually works, what does NOT survive a `git pull` and how to rebuild it, and the adapter contract for a new host |
| **Cross-agent status snapshot** | **[STATUS.md](STATUS.md)** — kept current, not a log: what's mid-flight, what's confirmed broken/not-broken, open commitments with a task and owner, what's blocked on the user. Read at the start of any survey/verification turn before re-deriving it from scratch. |
| Codex entry point | [AGENTS.md](AGENTS.md) |
| Endgame architecture | [.agent/rules/JARVIS_ENDGAME.md](.agent/rules/JARVIS_ENDGAME.md) |
| Antigravity always-on protocol | [.agent/rules/js-workspace-rule.md](.agent/rules/js-workspace-rule.md) |
| GitHub remote | https://github.com/Swarajnegi/private-ai |
| Master roadmap | [js-learning/JARVIS_MASTER_ROADMAP.md](js-learning/JARVIS_MASTER_ROADMAP.md) |
| Knowledge base | [jarvis_data/knowledge_base.jsonl](jarvis_data/knowledge_base.jsonl) |
| Raw client-work material (gitignored, never committed) | `client_work/<project>/` — see "Client work" below |
| Production memory layer | [js-development/jarvis_core/memory/](js-development/jarvis_core/memory/) |
| Path config | [js-development/jarvis_core/config.py](js-development/jarvis_core/config.py) |
| The hearth (transport + clock) | [js-development/jarvis_core/serve/](js-development/jarvis_core/serve/) · `scripts/hearth.py` · `scripts/jarvis_client.py` |
| Unprompted surfacing (the moat organ) | [agent/tension.py](js-development/jarvis_core/agent/tension.py) · `scripts/eval_tension.py` (ship gate) · `scripts/relabel_domains.py` |
| CLI tools | [scripts/](scripts/) |
| Workflow protocols | [.agent/workflows/](.agent/workflows/) |
| Finance strategy (canonical) | [knowledge/Finance/strategy.md](knowledge/Finance/strategy.md) |

---

*Update this file when operating context shifts (new stage entered, new constraint discovered, new tool added). Keep it under 250 lines — every line is loaded into every prompt.*
