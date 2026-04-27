# JARVIS Runbook — Commands and When to Run Them

> **Companion to:** [SYNC.md](SYNC.md) (HDD git sync setup) and [.agent/workflows/](.agent/workflows/) (Antigravity slash-command protocols).
> **Audience:** future-you, picking up this project after time away — or me on a fresh session.
> **Status:** Active reference. Update when commands change.

---

## What this document is

`SYNC.md` covers **how the two laptops stay in sync** (git + HDD).
This file covers **what to actually run** for everything else: ingest a paper, search memory, append to the knowledge base, audit the DB, sync ChromaDB after a pull, troubleshoot common failures.

Treat this as the cookbook. Each section answers "I want to do X — what do I run?"

---

## Conventions

- **Work laptop = Linux** (this machine, paths like `/home/swara_unix/work/JARVIS/`).
- **Personal laptop = Windows** (paths like `E:\J.A.R.V.I.S\` or wherever you cloned).
- All scripts work on both OSes — paths are resolved at runtime via `jarvis_core.config` and the `JARVIS_ROOT` env var.
- `python3` on Linux, `python` on Windows. I'll use `python3` below; substitute on Windows.
- `cd $JARVIS` shorthand → `cd /home/swara_unix/work/JARVIS` or `cd E:\J.A.R.V.I.S`.

---

## 1. Daily sync rituals (cheat sheet)

Full setup in [SYNC.md](SYNC.md). Quick reference:

### Start of work-laptop session

```bash
cd /home/swara_unix/work/JARVIS
git pull hdd main          # only if HDD plugged in (overnight changes from personal)
python3 scripts/sync_chromadb.py    # rebuild any missing ChromaDB chunks
```

### End of work-laptop session

```bash
git status                 # see what changed
git add -A
git commit -m "Day's work: <summary>"
git push hdd main          # plug HDD in if not already
```

### Start of personal-laptop session (HDD plugged in)

```powershell
cd E:\J.A.R.V.I.S
git pull hdd main
python scripts\sync_chromadb.py     # only if Antigravity needs ChromaDB queries
```

### End of personal-laptop session

```powershell
git add -A
git commit -m "Evening: <summary>"
git push hdd main
```

---

## 2. PDF Ingestion

### Ingest a single PDF (production pipeline)

```bash
cd $JARVIS
python3 scripts/ingest.py "research papers/RAGs/<paper>.pdf" --category ai
```

What happens:
- Images extracted to `jarvis_data/extracted_images/<stem>_pageN_imgM.png` (XREF-deduped)
- Text parsed to reading-order, chunked (200-word target), embedded via MiniLM-L6-v2
- Chunks upserted into ChromaDB collection `research_papers` at `jarvis_data/chromadb/`
- Specialist tag derived from `--category` via `SPECIALIST_MAP` in `ingestion.py`
- Runtime: ~16-30 seconds per paper depending on length + first-run model load

`--category` options (auto-route to specialist):

| `--category` | Specialist routed to |
|---|---|
| `ai`, `machine_learning`, `deep_learning`, `nlp`, `robotics`, `physics`, `astrophysics`, `mathematics` | The Scientist |
| `biology`, `medicine`, `neuroscience`, `chemistry` | The Doctor |
| `engineering`, `software`, `code` | The Engineer |
| `research_paper`, `general` (default) | The Orchestrator |

### Always log the ingestion in the manifest

Right now `IngestionPipeline.ingest_pdf` doesn't auto-append to the manifest (TODO). Until it does, append manually after a successful run:

```bash
# After ingest.py finishes, copy chunks_processed and images_saved_to_disk from
# the report it printed, then:
cat >> jarvis_data/ingestion_manifest.jsonl <<EOF
{"timestamp": "$(date -Iseconds)", "machine": "work-linux", "paper": "research papers/RAGs/<paper>.pdf", "chunks": <N>, "images": <M>, "collection": "research_papers", "category": "ai"}
EOF
```

The manifest is critical: it's how the OTHER laptop knows what to re-ingest after a `git pull`.

### Batch ingest a folder of PDFs

```bash
cd $JARVIS
for pdf in "research papers/RAGs"/*.pdf; do
  python3 scripts/ingest.py "$pdf" --category ai
done
```

Manifest entries still need to be appended manually (per file) after each run, until the auto-logging hook is added.

### Verify what's been ingested

```bash
# Count chunks per source paper
python3 -c "
import sys; sys.path.insert(0, 'js-development')
import chromadb
from jarvis_core.config import DB_ROOT
from collections import Counter
c = chromadb.PersistentClient(path=str(DB_ROOT))
col = c.get_collection('research_papers')
metas = col.get(limit=100000, include=['metadatas'])['metadatas']
print(Counter(m['source'] for m in metas))
"
```

### After git pull: bring ChromaDB up to date

```bash
python3 scripts/sync_chromadb.py             # check + replay missing
python3 scripts/sync_chromadb.py --dry-run   # show what would run
python3 scripts/sync_chromadb.py --force     # re-ingest everything (idempotent)
```

The script reads `jarvis_data/ingestion_manifest.jsonl` (which IS git-tracked) and re-runs ingestion only for papers not already present in the local ChromaDB. Deterministic: same code + same paper → same chunks via md5 chunk IDs.

When to use `--force`:
- After upgrading the chunker, parser, or embedding model — chunks won't match by ID, so the local ChromaDB is stale even when sync says "up to date."
- After deleting a ChromaDB by accident.

---

## 3. Memory Operations (knowledge_base.jsonl)

### Semantic search

```bash
python3 scripts/search_memory.py "your query in plain English"
python3 scripts/search_memory.py "RAG silent failures" --type Failure
python3 scripts/search_memory.py "agent loops" --tags asyncio --top_k 10
```

What happens:
- Loads all `knowledge_base.jsonl` entries
- Embeds each entry's `content` (~5 sec on first run, faster after)
- Embeds your query, ranks by cosine similarity
- Filters by `--type` and/or `--tags` if specified
- Prints top-K results above the similarity threshold (default 0.3)

### Append a new entry via the /memory workflow

The Antigravity `/memory` workflow (defined in [.agent/workflows/memory.md](.agent/workflows/memory.md)) does this automatically. To run the protocol manually:

1. **Deduplication check** (ensure novelty):
   ```bash
   python3 scripts/search_memory.py "<one-line summary of the entry>"
   ```
   If similarity > 0.85 to an existing entry, update that one instead of appending.

2. **Classify** the entry per the protocol's 8 types:
   `Episodic` | `Semantic` | `Procedural` | `Idea` | `Decision` | `Failure` | `Cognitive_Pattern` | `System_Protocol`

3. **Compress** the lesson into a single high-leverage line.

4. **Append** as a single-line JSONL entry:
   ```bash
   cat >> jarvis_data/knowledge_base.jsonl <<EOF
   {"timestamp": "$(date -Iseconds)", "type": "Procedural", "tags": ["tag1","tag2","tag3"], "content": "the compressed insight", "expiry": "Permanent"}
   EOF
   ```

5. **Validate retrieval** — the new entry should rank top-1 on a relevant query:
   ```bash
   python3 scripts/search_memory.py "<keyword from the entry>"
   ```

### Bulk-append from a consolidated source doc

When you have a structured source like `Data_Engineering_Lessons.md` and want to extract many entries:

1. Read the source.
2. Scan existing `knowledge_base.jsonl` for tag overlap (skip duplicates).
3. Write a Python script that builds a list of entry dicts, validates them (3-5 tags, content > 50 chars, valid type), and appends each as one line.
4. Run inline retrieval validation on representative queries.

Pattern saved at `/tmp/append_de_lessons.py` from the 2026-04-27 session as a template — when you do another consolidation, copy that pattern.

### Merge two knowledge_base.jsonl files (rare — only if git union merge gets confused)

```bash
python3 scripts/jsonl_merge.py kb_a.jsonl kb_b.jsonl --out merged.jsonl
```

Idempotent: deduplicates by content hash, sorts by timestamp, outputs clean JSONL union.

---

## 4. ChromaDB management

### Audit the DB

```bash
python3 scripts/audit.py                                              # full health check
python3 scripts/audit.py --query "agentic RAG" --collection research_papers --n 5
python3 scripts/audit.py --backup                                     # tar.gz snapshot to chromadb_backups/
```

### Backup before risky changes

```bash
python3 scripts/audit.py --backup
ls -lh jarvis_data/chromadb_backups/
```

The backup goes into `jarvis_data/chromadb_backups/jarvis_memory_<timestamp>.tar.gz`. That directory is gitignored — copy it to `$HDD/jarvis-bulk/` if you want it portable.

### Restore from a backup

```bash
python3 -c "
import sys; sys.path.insert(0, 'js-development')
from jarvis_core.memory.store import JarvisMemoryStore
with JarvisMemoryStore() as s:
    s.restore_from_backup('jarvis_data/chromadb_backups/jarvis_memory_<timestamp>.tar.gz')
"
```

### Drop a collection (clean slate)

```bash
python3 -c "
import sys; sys.path.insert(0, 'js-development')
from jarvis_core.memory.store import JarvisMemoryStore
with JarvisMemoryStore() as s:
    s.delete_collection('research_papers')
"
```

After dropping, run `scripts/sync_chromadb.py` to repopulate from the manifest.

---

## 5. Model / Provider operations

### Sync the OpenRouter model catalog

```bash
python3 scripts/sync_openrouter.py
# Writes jarvis_data/model_catalog.json (~80 models with cost/context/vendor)
```

Run when you want fresh pricing or new model availability.

### Recommend a model for a task

```bash
python3 scripts/suggest_model.py --task "long-context summarization" --top_k 3
python3 scripts/suggest_model.py --task "code generation" --max_cost_input 5 --top_k 5
python3 scripts/suggest_model.py --task "vision multimodal" --min_context 100000
```

Caveat: the script's `evaluate_model` function still has hardcoded boosters for `claude-3.7-sonnet` (model that doesn't exist as of 2026-04). When time permits, update to current Claude 4.x / Opus 4.7 references.

---

## 6. One-time setup (per machine)

### Install Python dependencies

Work laptop (Linux, with `--user` install):
```bash
pip3 install --user PyMuPDF chromadb sentence-transformers
```

Personal laptop (Windows, in your virtualenv or `--user`):
```powershell
pip install PyMuPDF chromadb sentence-transformers
```

Heavy: `sentence-transformers` pulls torch (~2 GB). One-time per machine.

### Configure git on a fresh laptop

Linux work laptop (already done in initial commit):
```bash
git config user.name "swara_unix"
git config user.email "<your-email>"
git config core.autocrlf input          # leave LF in working tree
git config core.fileMode false          # ignore chmod-only diffs
```

Windows personal laptop (one-time, after first clone):
```powershell
git config --global core.autocrlf true        # CRLF in working tree
git config --global core.eol lf
git config --global core.ignorecase true
git config --global core.fileMode false
```

### Override JARVIS_ROOT explicitly (rare)

If `Path(__file__).resolve().parents[2]` doesn't auto-resolve correctly (e.g., you're running scripts from outside the repo), set the env var:

Linux:
```bash
export JARVIS_ROOT=/home/swara_unix/work/JARVIS
```

Windows:
```powershell
$env:JARVIS_ROOT = "E:\J.A.R.V.I.S"
```

Add to `~/.bashrc` or PowerShell profile if you want it persistent.

### Verify config resolves correctly

```bash
python3 js-development/jarvis_core/config.py
# Should print all paths starting with your JARVIS root, no errors
```

---

## 7. Antigravity slash-command workflows (personal laptop)

Defined in `.agent/workflows/*.md`. Antigravity loads them on startup and invokes the protocol when you type the slash command.

| Command | What it does | Source |
|---|---|---|
| `/learn <topic>` | Teach a concept at user's level, connect to JARVIS pipeline, scan for cognitive patterns | [.agent/workflows/learn.md](.agent/workflows/learn.md) |
| `/memory` | Capture a fact/decision/pattern as a `knowledge_base.jsonl` entry per the 8-type schema | [.agent/workflows/memory.md](.agent/workflows/memory.md) |
| `/research <paper or topic>` | Extract actionable engineering value from a paper, log relevance score | [.agent/workflows/research.md](.agent/workflows/research.md) |
| `/dev <task>` | Production-grade code generation with design review + JARVIS layer alignment | [.agent/workflows/dev.md](.agent/workflows/dev.md) |
| `/architecture-review <design>` | Stress-test a design (coupling, state, complexity, latency, JARVIS alignment) | [.agent/workflows/architecture-review.md](.agent/workflows/architecture-review.md) |
| `/route-model <task>` | Pick optimal LLM from `model_catalog.json` given constraints | [.agent/workflows/route-model.md](.agent/workflows/route-model.md) |
| `/next` | Verify progress through stages — gate advancement | [.agent/workflows/next.md](.agent/workflows/next.md) |
| `/master-planner <goal>` | Convert vague goal into strict architectural battle plan | [.agent/workflows/master-planner.md](.agent/workflows/master-planner.md) |

These commands work in **Antigravity only** — they don't fire as commands here on the work laptop in Claude Code. To follow the same protocol manually here, read the workflow file and apply its steps.

---

## 8. Troubleshooting

### `ModuleNotFoundError: No module named 'jarvis_core'`

Scripts in `scripts/` and code in `js-development/jarvis_core/memory/` insert `js-development/` into `sys.path` themselves. If you see this error, you're running the file from an unusual location or Python version. Fix by running from the JARVIS root:

```bash
cd $JARVIS && python3 scripts/<your-script>.py
```

### `FileNotFoundError: [Config] JARVIS_ROOT not found`

The auto-detection failed. Set `JARVIS_ROOT` explicitly:
```bash
JARVIS_ROOT=$PWD python3 scripts/<your-script>.py
```

### `chromadb` or `sentence_transformers` not installed

```bash
pip3 install --user chromadb sentence-transformers PyMuPDF
```

### `git pull` reports merge conflict on `knowledge_base.jsonl`

`*.jsonl` is set to `merge=union` in `.gitattributes`, which auto-merges *new lines from both sides*. Conflicts only happen if both laptops edited the same existing line — rare with single-user-at-a-time. To resolve:

```bash
# Save both versions of the conflicted file
git show :2:jarvis_data/knowledge_base.jsonl > /tmp/kb_ours.jsonl
git show :3:jarvis_data/knowledge_base.jsonl > /tmp/kb_theirs.jsonl

# Merge with the dedup tool
python3 scripts/jsonl_merge.py /tmp/kb_ours.jsonl /tmp/kb_theirs.jsonl \
    --out jarvis_data/knowledge_base.jsonl

# Mark resolved and commit
git add jarvis_data/knowledge_base.jsonl
git commit -m "Merge knowledge_base.jsonl — dedup via jsonl_merge"
```

### `git push hdd main` says "fatal: ... does not appear to be a git repository"

HDD not mounted, or the path drifted (auto-mount on Ubuntu can change the label). Re-check:
```bash
lsblk -f                                                    # find the HDD
git remote -v                                               # see what path is configured
git remote set-url hdd /correct/path/to/jarvis.git          # fix it
```

### Massive spurious diffs every commit on Windows

Line endings. Fix:
```powershell
git config --global core.autocrlf true
cd $JARVIS && git checkout -- .
```

### `git status` shows file mode changes on every checkout

```bash
git config core.fileMode false
```

### `sync_chromadb.py` says "up to date" but I know I just ingested something

The script checks by source filename. If you ingested via a non-standard path or under a different `--collection`, the script won't detect it. Check the manifest first:

```bash
cat jarvis_data/ingestion_manifest.jsonl
```

Then either append the missing manifest entry by hand, or run with `--force` to re-process everything.

### ChromaDB sqlite locked

Another process has the DB open (an Antigravity / Claude Code agent, a stale Python interpreter, etc.). Find and stop it:

```bash
fuser jarvis_data/chromadb/chroma.sqlite3       # Linux
# Then kill the PID it reports.
```

On Windows: close any open Python REPLs, the IDE, and any tool with the file open.

### `sentence-transformers` first-run is slow

The first call downloads the MiniLM-L6-v2 weights (~80 MB) to `~/.cache/huggingface/`. Subsequent runs are fast. Optionally set `HF_HOME` to a portable location and copy across machines.

### Search returns no results when entries clearly exist

Lower the similarity threshold:
```python
# In search_memory.py:
SIMILARITY_THRESHOLD = 0.2   # default 0.3
```

Or rephrase the query to match how the entry's `content` is written. The embedding model rewards literal overlap with the stored text.

### "/memory workflow says path doesn't exist" (Windows path in workflow file)

The workflow files in `.agent/workflows/*.md` reference `E:\J.A.R.V.I.S\...` paths in prose because they were authored in the Windows-only era. They are documentation; the actual scripts they call (`search_memory.py` etc.) now resolve paths via `config.py`. If you re-author a workflow file, replace hardcoded paths with `$JARVIS_ROOT` placeholders for portability.

---

## 9. What NOT to do

- **Don't `git add jarvis_data/chromadb/`** — it's gitignored for a reason. Binary, large, regenerable.
- **Don't edit chunked output files in `jarvis_data/extracted_images/` and commit them** — also gitignored. Re-run ingestion to regenerate.
- **Don't merge `knowledge_base.jsonl` with a plain copy-paste tool** — use `scripts/jsonl_merge.py` to preserve dedup semantics.
- **Don't run `sync_chromadb.py --force` casually** — it re-embeds every paper. For 100 papers that's ~50 minutes.
- **Don't skip the manifest entry after manual ingestion** — the OTHER laptop won't know to ingest the paper, and your two ChromaDBs will silently drift.
- **Don't commit `.env` or any file ending in `.local`** — gitignored, but check before pushing if you have anything sensitive.

---

## 10. Future automation (not built yet)

- **Auto-append to manifest** in `IngestionPipeline.ingest_pdf` so manual logging isn't required. Small edit; deferred to keep current production code untouched.
- **Pre-commit hook** that scans for hardcoded `E:/J.A.R.V.I.S` paths and blocks the commit. Useful once the personal laptop also has commits flowing.
- **`scripts/sync_health.sh`** — one-call check: HDD mounted? Working tree clean? Ahead/behind hdd remote? Last commit timestamp? Last manifest entry?
- **Schedule for `sync_openrouter.py`** — refresh model catalog monthly via cron / Task Scheduler.

Add when there's a problem to solve, not preemptively.

---

## 11. Quick command index

| I want to... | Command |
|---|---|
| Pull overnight changes | `git pull hdd main` |
| Push my changes | `git add -A && git commit -m "..." && git push hdd main` |
| Ingest a paper | `python3 scripts/ingest.py "path/to/paper.pdf" --category ai` |
| Check what's ingested | `python3 scripts/sync_chromadb.py --dry-run` |
| Bring ChromaDB up to date | `python3 scripts/sync_chromadb.py` |
| Search the knowledge base | `python3 scripts/search_memory.py "query"` |
| Filter by entry type | `python3 scripts/search_memory.py "query" --type Failure` |
| Filter by tags | `python3 scripts/search_memory.py "query" --tags databricks` |
| Audit ChromaDB | `python3 scripts/audit.py` |
| Backup ChromaDB | `python3 scripts/audit.py --backup` |
| Merge two JSONLs | `python3 scripts/jsonl_merge.py a.jsonl b.jsonl --out merged.jsonl` |
| Refresh model catalog | `python3 scripts/sync_openrouter.py` |
| Recommend a model | `python3 scripts/suggest_model.py --task "..."` |
| Verify config paths | `python3 js-development/jarvis_core/config.py` |

---

*Last command added: 2026-04-27. Keep this index updated when scripts grow.*
