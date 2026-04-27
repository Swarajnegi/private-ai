# JARVIS Sync — Work Laptop ↔ Personal Laptop via External HDD

> **Status:** Active sync method as of 2026-04-27.
> **Replaces:** Manual zip → Databricks Free roundtrip.

---

## Topology

| Machine | OS | Purpose | When |
|---|---|---|---|
| Work laptop | Linux (WSL/Ubuntu) | Heavy lifting with Claude Code (Opus 4.7) | Daytime |
| Personal laptop | Windows | Learning + brainstorming with Antigravity | Evening |
| External HDD | NTFS or exFAT | Portable git remote + bulk binary store | Plugged into one machine at a time |

**Workflow rule:** one machine at a time. End-of-session `git push hdd main`. Start-of-session `git pull hdd main`. The HDD is the single source of truth between sessions.

---

## What's tracked vs. regenerated

### Tracked in git (small, diffable)

- `js-development/` — production code
- `js-learning/` — curriculum, roadmaps, exercise code
- `scripts/` — CLI tools (ingest, search, audit, suggest_model, sync_openrouter, jsonl_merge)
- `.agent/rules/` — JARVIS_ENDGAME, workspace rule, strategy docs
- `.agent/workflows/` — Antigravity slash-command protocols (/learn, /memory, /research, etc.)
- `jarvis_data/knowledge_base.jsonl` — long-term memory (137+ entries)
- `jarvis_data/Data_Engineering_Lessons.md` — consolidated DE learnings
- `jarvis_data/knowledge.md` — legacy reference
- `jarvis_data/model_catalog.json` — synced LLM catalog
- All root-level `*.md` and config files

### Excluded from git, lives in HDD's `jarvis-bulk/` folder

- `jarvis_data/chromadb/` — vector store, regenerable from `python3 scripts/ingest.py <pdf>`
- `jarvis_data/chromadb_backups/` — periodic snapshots
- `jarvis_data/extracted_images/` — regenerable from PDF re-ingestion
- `research papers/` — ~50 MB, mostly static; one-time bulk copy
- `OpenClaude/` — re-clone via `git clone https://github.com/Gitlawb/openclaude.git`
- `OpenJarvis/`, `Open-Claude-Cowork/` — same; re-clone if needed

**Rationale:** git is bad at large binaries. We track recipes (code) and inputs (papers go in bulk), regenerate outputs (ChromaDB) from recipes + inputs.

---

## One-time setup

### Phase 1 — Work laptop, no HDD needed (already done if you're reading this from the repo)

```bash
cd /home/swara_unix/work/JARVIS
git init
git config user.name "swara_unix"
git config user.email "<your-personal-email>"
git config core.autocrlf input        # leave LF in working tree on Linux
git add -A
git commit -m "Initial JARVIS state — sync setup"
```

### Phase 2 — When the HDD is plugged into the work laptop

```bash
# 1. Find the mount point. On Ubuntu it's usually /media/swara_unix/<LABEL>
lsblk -f
HDD=/media/swara_unix/<LABEL>

# 2. Confirm filesystem is NTFS or exFAT (Windows-readable)
#    If it shows ext4, reformat to exFAT — Windows can't read ext4.

# 3. Create the bare git repo on the HDD
mkdir -p "$HDD/jarvis-bulk"
git init --bare "$HDD/jarvis.git"

# 4. Add as a remote and push
git remote add hdd "$HDD/jarvis.git"
git push -u hdd main

# 5. Bulk-copy binaries (one time, occasional refresh)
cp -r "/home/swara_unix/work/JARVIS/research papers" "$HDD/jarvis-bulk/"
# Optional: snapshot ChromaDB if you want it portable instead of regenerating
# tar -czf "$HDD/jarvis-bulk/chromadb-snapshot-$(date +%F).tar.gz" \
#         /home/swara_unix/work/JARVIS/jarvis_data/chromadb
```

### Phase 3 — Personal laptop bootstrap (Windows, evening, HDD plugged in)

PowerShell from your personal-laptop terminal:

```powershell
# 1. Set Windows-side git config (one-time)
git config --global core.autocrlf true
git config --global core.eol lf
git config --global core.ignorecase true

# 2. Rename your existing JARVIS folder so it isn't lost
Rename-Item E:\J.A.R.V.I.S E:\J.A.R.V.I.S-pre-sync-backup
# (Adjust paths to wherever your existing JARVIS lives)

# 3. Clone from the HDD
git clone E:\jarvis.git E:\J.A.R.V.I.S
#                ^^^^^ adjust to the HDD's actual drive letter
cd E:\J.A.R.V.I.S

# 4. Reconcile any divergent state from the pre-sync backup
#    Most likely candidate: knowledge_base.jsonl entries you appended on
#    the personal laptop after the work-laptop migration.
python scripts\jsonl_merge.py `
    jarvis_data\knowledge_base.jsonl `
    E:\J.A.R.V.I.S-pre-sync-backup\jarvis_data\knowledge_base.jsonl `
    --out jarvis_data\knowledge_base.jsonl

# 5. Bulk: copy research papers and regenerate ChromaDB
Copy-Item -Recurse "E:\jarvis-bulk\research papers" "E:\J.A.R.V.I.S\research papers"
# ChromaDB: regenerate by re-running ingestion locally
python scripts\ingest.py "E:\J.A.R.V.I.S\research papers\RAGs\<paper>.pdf"

# 6. Commit any merge work and push back
git add -A
git commit -m "Personal-laptop divergence merged"
git push hdd main
```

---

## Daily ritual

### End of work-laptop session (with Claude Code)

```bash
cd /home/swara_unix/work/JARVIS
git status                          # see what changed
git diff                            # review (optional but recommended)
git add -A
git commit -m "Day's work: <one-line summary>"
# If HDD is plugged in:
git push hdd main
# If not, the commit waits locally — push when you next plug in
```

### Start of personal-laptop session (HDD plugged in)

```powershell
cd E:\J.A.R.V.I.S
git pull hdd main                   # apply day's changes
# Work via Antigravity normally — /learn, /memory, /research, etc.
git add -A
git commit -m "Evening: <summary>"
git push hdd main
```

### Next morning on work laptop (HDD plugged in)

```bash
cd /home/swara_unix/work/JARVIS
git pull hdd main                   # apply evening's changes
# Carry on with the day
```

---

## knowledge_base.jsonl conflict playbook

`*.jsonl` is configured with `merge=union` in `.gitattributes`, which means git auto-merges **append-only** divergence. If both laptops added entries during their respective sessions, both sets land in the merged file. No manual work.

**When manual merge is needed:** if both sides edited the *same line* of `knowledge_base.jsonl` (rare with single-user-at-a-time, but possible if you ever update an existing entry rather than append). Symptoms: `git pull` reports a conflict, `<<<<<<<` markers in the file.

**Resolution:**
```bash
# 1. Save both sides
git show :2:jarvis_data/knowledge_base.jsonl > /tmp/kb_ours.jsonl
git show :3:jarvis_data/knowledge_base.jsonl > /tmp/kb_theirs.jsonl

# 2. Merge with the dedup tool
python3 scripts/jsonl_merge.py /tmp/kb_ours.jsonl /tmp/kb_theirs.jsonl \
    --out jarvis_data/knowledge_base.jsonl

# 3. Mark resolved and commit
git add jarvis_data/knowledge_base.jsonl
git commit -m "Merge knowledge_base.jsonl — dedup via jsonl_merge"
```

---

## HDD layout reference

```
/media/swara_unix/<LABEL>/                    (Linux mount)
or E:\                                         (Windows drive letter)
│
├── jarvis.git/                                # bare git repo, ~10–50 MB
│   ├── HEAD
│   ├── config
│   ├── objects/
│   └── refs/
│
└── jarvis-bulk/                               # plain folders, GBs
    ├── research papers/                       # ~50 MB, copy once
    ├── chromadb-snapshot-YYYY-MM-DD.tar.gz   # optional periodic snapshots
    └── third-party-clones/                    # if you want OpenClaude portable
        └── OpenClaude/
```

---

## Backups (HDD failure protection)

The HDD is a single point of failure. Back up `jarvis.git/` periodically:

```bash
# On the work laptop, with HDD plugged in:
tar -czf ~/jarvis-git-backup-$(date +%F).tar.gz "$HDD/jarvis.git"
# Then move that tarball to a second drive or upload via Databricks Free
```

The bare repo is small (tens of MB even after months of commits) — backups are cheap.

`jarvis-bulk/` doesn't need a backup if its contents are regenerable (research papers can be re-downloaded; ChromaDB can be re-built).

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `lsblk -f` shows the HDD as `ext4` | Reformatted by Linux at some point | Reformat to `exFAT` (cross-platform) — backup contents first |
| `git push` says "fatal: '/path/jarvis.git' does not appear to be a git repository" | Wrong path or HDD not mounted | Re-check `lsblk` / `df -h` and adjust the remote URL: `git remote set-url hdd <correct-path>` |
| Massive spurious diffs on every commit on Windows | Line-ending conversion misconfigured | Re-run `git config --global core.autocrlf true` and `git checkout -- .` |
| `git pull` reports "untracked working tree files would be overwritten" | Files exist on disk but not in source — usually `__pycache__` | `find . -name __pycache__ -exec rm -rf {} +` then retry |
| Permission errors on Linux mount | NTFS without write permission | `sudo mount -o remount,rw,uid=$(id -u),gid=$(id -g) $HDD` |
| `git status` shows file mode changes (chmod) on Windows | Filesystem can't preserve POSIX modes | `git config core.fileMode false` |
| ChromaDB out of sync between machines | Different ingestion runs | Re-run `python3 scripts/ingest.py` with the same papers; or restore from `jarvis-bulk/chromadb-snapshot-*.tar.gz` |
| HDD label changes between mounts | Auto-mount on Linux uses the volume label | Use a stable mount: `sudo mount /dev/sdX1 /mnt/jarvis-hdd` and update `git remote set-url hdd /mnt/jarvis-hdd/jarvis.git` |

---

## When NOT to use this sync

- For test runs or experiments you don't want the other laptop to see — use a feature branch: `git checkout -b experiment-foo`. Push it as needed; merge to `main` only when ready.
- For sensitive credentials — never commit. Use the `.env` pattern (already in `.gitignore`).
- For binary artifacts — they go in `jarvis-bulk/`, not git.

---

## Future enhancements (not built yet)

- A `scripts/sync_health.sh` that checks: HDD mounted? Working tree clean? Ahead/behind hdd remote? Last commit timestamp?
- Optional `pre-commit` hook that prevents committing files matching common secret patterns.
- Encryption: BitLocker on Windows / LUKS on Linux for the HDD itself.

Add when there's an actual problem to solve, not preemptively.
