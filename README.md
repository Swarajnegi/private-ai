# JARVIS

A private "Model of Models" cognitive orchestrator and autonomous R&D lab. Not a chatbot wrapper —
a system built to be trained on one person's own corpus and deployed as an ambient presence across
their devices.

**Current stage: 5 — Domain Specialists. Stages 1–4 complete.** Status lives in
[`js-learning/JARVIS_MASTER_ROADMAP.md`](js-learning/JARVIS_MASTER_ROADMAP.md); it is canonical, and
anything here that disagrees with it is stale.

---

## Where things are

| Path | What |
|---|---|
| [`js-development/jarvis_core/`](js-development/jarvis_core/) | Production code — the system itself |
| [`js-learning/`](js-learning/) | Roadmaps: master + one per stage. **Ground truth for status** |
| [`.agent/rules/`](.agent/rules/) | Operating context loaded into every agent session |
| [`.agent/workflows/`](.agent/workflows/) | 8 protocols (`/learn`, `/dev`, `/next`, …) |
| [`jarvis_data/`](jarvis_data/) | Knowledge base, cognitive profile, capture queue, training corpus |
| [`scripts/`](scripts/) | CLI tools — memory search, KB append, profile synthesis, compaction |
| [`knowledge/`](knowledge/) | Distilled notes: data engineering, finance, literature |

## The four layers

| Layer | Module | State |
|---|---|---|
| **Memory** | `jarvis_core/memory/` | ChromaDB + BM25 hybrid, cross-encoder rerank, KB compaction |
| **Agent** | `jarvis_core/agent/` | Tool ABC + registry, DAG planner, ReAct loop, MemGPT paging |
| **Brain** | `jarvis_core/brain/` | Intent router, model-pool failover, aggregator, epistemic control |
| **Body** | `jarvis_core/body/` | Placeholder — Stage 6 |

## Conventions worth knowing before reading the code

- **Tests are `__main__` smoke blocks, not a pytest suite.** 75 of 83 modules carry one. This is
  deliberate and documented in [`.agent/rules/CLAUDE.md`](.agent/rules/CLAUDE.md); there is
  currently **no runner**, which is a real gap rather than a hidden feature.
- **Paths are never hardcoded** — everything resolves through
  [`jarvis_core/config.py`](js-development/jarvis_core/config.py) so the same source works on Linux
  and Windows.
- **Systems Python is non-negotiable**: generators for pipelines, async for I/O, context managers
  for every external resource, strict typing on cross-layer contracts.

## Not in this repository

`client_work/` holds employer/client material and is excluded by
[`.gitignore`](.gitignore) — permanently, regardless of repo visibility. Only *generalized* lessons
leave it. Note that `jarvis_data/training_corpus/` **is** tracked and does contain client-derived
text; the tradeoff is documented in the `.gitignore` header.

## Quick start

```bash
pip install -r requirements.txt
python3 scripts/search_memory.py "<topic>"     # semantic search over the knowledge base
python3 scripts/profile_synth.py               # regenerate the cognitive profile
```
