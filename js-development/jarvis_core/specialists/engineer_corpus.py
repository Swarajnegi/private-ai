"""
engineer_corpus.py

Stage 5.2.2: Engineer Specialist — Training Corpus Assembly.

Run with:
    python jarvis_core/specialists/engineer_corpus.py

=============================================================================
THE BIG PICTURE: A QLoRA adapter is only as personal as its corpus
=============================================================================

The Engineer adapter (Qwen3-Coder-Next seed, distilled onto the shared
Kimi K2.6 base — JARVIS_ENDGAME.md Sec 3) is what's supposed to make JARVIS
answer jarvis_core/ questions the way THIS user would, not the way a
generic coding assistant would. That only happens if the training corpus
is actually this user's material — their code, their KB, their chat
history, their DE notes — not a synthetic stand-in.

Without a real assembly step:
    -> "Training corpus" stays a roadmap bullet point, never an artifact
    -> 5.1.3 (Unsloth) and 5.2.3 (adapter training) have nothing to load
    -> Someone eventually hand-waves a corpus together at training time,
       under time pressure, with no record of what was included or why

With this module:
    -> One command produces one inspectable JSONL file
    -> Every record is traceable back to its exact source (file path,
       KB entry id, conversation file + line, etc.) — nothing anonymous
    -> Sources that don't exist yet (past error logs — verified 2026-08-03:
       nothing in this codebase persists an error to disk) show up as an
       explicit zero, not a silent gap

=============================================================================
THE FLOW
=============================================================================

STEP 1: Six source iterators, one per corpus source (jarvis_core/ code, KB
        entries, chat-history, DE corpus, client production work, error
        logs). Five are the set named in JARVIS_MASTER_ROADMAP.md Sec 5.2;
        client_work was added 2026-08-22 when real client material first
        landed on disk, and it is the only source carrying production data
        engineering the user was PAID to write rather than notes about it.
        Each is a generator — no source is ever fully materialized in
        memory.
        ↓
STEP 2: kb_entry and chat_history are capped for near-duplicates first
        (verified 2026-08-03: the same question gets asked repeatedly
        across separate sessions — e.g. 6 near-identical KB entries about
        one RunPod decision, a test conversation opening recurring across
        2 files — none exact-duplicate text, so exact dedup misses them).
        Keeps the first _MAX_PER_CLUSTER occurrences per near-identical
        opening, drops the rest, so one repeated interaction can't
        dominate training signal. See _cluster_key().
        ↓
STEP 3: Oversized sources (code files, KB entries, DE notes) are chunked
        through RecursiveWordChunker (jarvis_core.memory.chunking), reused
        with fine-tuning-sized bounds instead of the RAG-tuned 900/180
        embedding defaults — a training sequence can hold far more than
        one embedding chunk's worth of text.
        ↓
STEP 4: assemble_corpus() streams every generator through ONE open file
        handle, writing one JSON line per record and tallying per-source
        stats (including what got capped) as a byproduct of the write
        loop — never a separate pass, never a fully materialized record
        list.
        ↓
STEP 5: __main__ runs the assembly and prints the stats table — this IS
        the smoke test. Output stays model-agnostic (raw text + source
        tags, not a rendered chat template): which chat template applies
        depends on the tokenizer chosen at training time, not chosen yet.

Known remaining gap (not fixed by capping, flagged 2026-08-03): single-
occurrence low-value content — trivial or off-topic exchanges asked only
once (e.g. "is the earth flat?", "what is 2+2?") — isn't caught, since
there's nothing to compare it against. Filtering that reliably needs a
content-quality judgment call, not a repetition count; deliberately left
for manual review rather than guessed at with a fragile heuristic.

LAYER: Specialists (Corpus Assembly) — Stage 5.2.2
=============================================================================
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Generator, Optional

from jarvis_core.agent.capture import redact
from jarvis_core.config import DATA_ROOT, JARVIS_ROOT, KB_PATH, SPECIALIST_CORPUS_ROOT
from jarvis_core.memory.chunking import RecursiveWordChunker


# =============================================================================
# Part 1: CONSTANTS
# =============================================================================

# Fine-tuning sequences hold far more text than one embedding chunk
# (DEFAULT_CHUNK_CHAR_LIMIT=900 exists to fit all-MiniLM-L6-v2's 256-token
# ceiling — an unrelated constraint). Reuse the same chunker class, larger
# bounds, tuned for this purpose specifically.
_CORPUS_CHUNK_CHAR_LIMIT = 4000
_CORPUS_CHUNK_OVERLAP = 400

_JARVIS_CORE_ROOT = JARVIS_ROOT / "js-development" / "jarvis_core"
_CONVERSATIONS_DIR = DATA_ROOT / "conversations"
_OBSERVATION_QUEUE_PATH = DATA_ROOT / "observation_queue.jsonl"

_DE_CORPUS_ROOT = JARVIS_ROOT / "knowledge" / "Data Engineering"

# The user's own authored DE notes — deliberately excludes the
# Databricks_DE_Pro_Cert/ exam bank, Interview_Tests/ notebooks, and the
# generated HTML export (redundant with the .md files). Adjust this list
# if that scoping call is wrong — it's a judgment call, not a fact.
_DE_CORPUS_FILES = (
    "Data_Engineering_Lessons.md",
    "ADF_Deep_Dive.md",
    "DE_Interview_Prep.md",
    "Databricks_Costing.md",
    "SDP_Syntax.md",
)

# --- Source 6: real client production work (added 2026-08-22) ----------------
# Gitignored quarantine (see client_work/README.md). Read from here, never
# committed. Before this source the whole corpus held ZERO production data
# engineering the user was paid to write: de_corpus contributed 125 of 1,356
# records and every one was notes ABOUT the work, not the work.
_CLIENT_WORK_ROOT = JARVIS_ROOT / "client_work"

_CLIENT_WORK_EXTENSIONS = (".py", ".yml", ".yaml", ".sql", ".md")

# The client repo arrived via a VDI export, which litters it with Windows
# download markers and DLP sidecar files -- 615 of them, more files than the
# real content. Substring match, not suffix: the marker is appended after the
# real extension ("settings.json:Zone.Identifier"), so an extension allowlist
# alone does not catch them.
_CLIENT_WORK_JUNK_MARKERS = (":Zone.Identifier", ":sec.endpointdlp")
_CLIENT_WORK_SKIP_DIRS = frozenset({
    ".git", "__pycache__", ".pytest_cache", ".vscode", ".idea", "node_modules",
})

# ATTRIBUTION TIER, recorded per record rather than resolved by including or
# excluding. The client repo is a TEAM repo: `git log` on it shows 48/39/19/13/12
# commits across six authors, and only the paths below are the user's own slice
# (17 commits, split between their two git identities -- the client VDI labels
# them differently from this machine, which is itself mislabelled).
#
# Why tier instead of filter: the team-authored `src/` is ~324K tokens of
# genuinely excellent production DE -- the clone engine, failover strategies,
# recon, grant replication -- and it is real context for what the user's own
# test framework validates. But it is NOT their voice, and the Engineer adapter
# is supposed to learn their voice (KB 492). Those two facts pull opposite ways
# and the right weighting is not knowable until a training run exists. So both
# go in, tagged, and the decision stays reversible at training time instead of
# being burned in here by an include/exclude call made blind.
_CLIENT_WORK_AUTHORED_MARKERS = (
    "gld_deepclone/test_cases/",
    "test_cases_orchestrator_job.yml",
    "SESSION_LEARNINGS.md",
)

_DEFAULT_OUTPUT_PATH = SPECIALIST_CORPUS_ROOT / "engineer_corpus.jsonl"

# Verified 2026-08-03 (spot-check after a user question about corpus quality):
# the KB and conversation logs contain the same question asked repeatedly across
# separate sessions (e.g. 6 near-identical "Terminal session distill" KB entries
# about one RunPod decision; a "yes/no logic-inversion" test conversation
# recurring across 2 files). None are exact-duplicate text, so exact dedup
# misses them -- but letting one repeated interaction appear 6-9x would still
# dominate training signal relative to genuinely diverse examples. Cap instead
# of drop entirely: keep the first _MAX_PER_CLUSTER occurrences (chronological,
# since files/lines are processed in sorted order), drop the rest.
_DEDUP_PREFIX_LEN = 100
_MAX_PER_CLUSTER = 2


def _chunker() -> RecursiveWordChunker:
    return RecursiveWordChunker(char_limit=_CORPUS_CHUNK_CHAR_LIMIT, overlap=_CORPUS_CHUNK_OVERLAP)


def _cluster_key(text: str) -> str:
    """Normalized prefix used to group near-identical repeated interactions."""
    return " ".join(text.split()).lower()[:_DEDUP_PREFIX_LEN]


# =============================================================================
# Part 2: RECORD SHAPE
# =============================================================================

@dataclass(frozen=True)
class CorpusRecord:
    """One training example, traceable back to its exact origin."""
    source_type: str
    source_path: str
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CorpusStats:
    """Per-source-type record/char counts, returned by assemble_corpus()."""
    per_source: Dict[str, Dict[str, int]]
    total_records: int
    output_path: Path
    dropped_near_duplicates: Dict[str, int] = field(default_factory=dict)


# =============================================================================
# Part 3: SOURCE 1 — jarvis_core/ SOURCE CODE
# =============================================================================

def iter_jarvis_core_records(root: Optional[Path] = None) -> Generator[CorpusRecord, None, None]:
    """
    LAYER: Specialists (Corpus Assembly)

    Every .py file under jarvis_core/, chunked. Teaches the adapter this
    project's own naming conventions, docstring style, and architecture —
    not generic Python idioms.
    """
    base = root or _JARVIS_CORE_ROOT
    chunker = _chunker()
    for path in sorted(base.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if not text.strip():
            continue
        rel = path.relative_to(base.parent)
        for i, chunk in enumerate(chunker.chunk(text)):
            yield CorpusRecord(
                source_type="jarvis_core_code",
                source_path=f"{rel}#chunk{i}",
                text=chunk,
                metadata={"file": str(rel)},
            )


# =============================================================================
# Part 4: SOURCE 2 — KNOWLEDGE BASE
# =============================================================================

def iter_kb_records(
    kb_path: Optional[Path] = None,
    dropped: Optional[Dict[str, int]] = None,
) -> Generator[CorpusRecord, None, None]:
    """
    LAYER: Specialists (Corpus Assembly)

    Streams knowledge_base.jsonl line by line — never materializes the
    full file. Schema drifted over the KB's lifetime (earliest entries
    lack `id`; some types add `source`/`subtype`/`topic`), so every field
    read here is defensive (.get()), never assumed present.

    Capped at _MAX_PER_CLUSTER per near-identical opening (see module
    docstring) BEFORE chunking, so a repeated interaction can't inflate
    its share of the corpus via extra chunks either.
    """
    path = kb_path or KB_PATH
    chunker = _chunker()
    cluster_counts: Dict[str, int] = {}
    try:
        handle = path.open("r", encoding="utf-8")
    except OSError:
        return
    with handle:
        for line_no, raw_line in enumerate(handle):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                entry = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            content = entry.get("content", "")
            if not content:
                continue

            key = _cluster_key(content)
            cluster_counts[key] = cluster_counts.get(key, 0) + 1
            if cluster_counts[key] > _MAX_PER_CLUSTER:
                if dropped is not None:
                    dropped["kb_entry"] = dropped.get("kb_entry", 0) + 1
                continue

            entry_id = entry.get("id", f"line{line_no}")
            metadata = {
                "type": entry.get("type"),
                "tags": entry.get("tags"),
                "timestamp": entry.get("timestamp"),
            }
            for i, chunk in enumerate(chunker.chunk(content)):
                yield CorpusRecord(
                    source_type="kb_entry",
                    source_path=f"kb#{entry_id}#chunk{i}",
                    text=chunk,
                    metadata=metadata,
                )


# =============================================================================
# Part 5: SOURCE 3 — CHAT HISTORY (two independent real sources)
# =============================================================================

def _iter_conversation_store_records(
    dropped: Optional[Dict[str, int]] = None,
) -> Generator[CorpusRecord, None, None]:
    """
    Real ask() Q&A turns written by brain/conversation.py's ConversationStore.

    Capped at the FILE level (see module docstring): two conversation files
    can open with the near-identical first user message (e.g. a repeated
    test prompt) without any turn-level text matching, so this reads each
    file's turns first, keys on its first user turn, and skips the whole
    file if that opening has already appeared _MAX_PER_CLUSTER times --
    dropping only whole, self-contained conversations, never a partial one.
    """
    if not _CONVERSATIONS_DIR.is_dir():
        return
    cluster_counts: Dict[str, int] = {}
    for path in sorted(_CONVERSATIONS_DIR.glob("*.jsonl")):
        try:
            with path.open("r", encoding="utf-8") as handle:
                turns = [json.loads(line) for line in handle if line.strip()]
        except (OSError, json.JSONDecodeError):
            continue
        if not turns:
            continue

        first_user = next((t.get("content", "") for t in turns if t.get("role") == "user"), "")
        key = _cluster_key(first_user)
        cluster_counts[key] = cluster_counts.get(key, 0) + 1
        if cluster_counts[key] > _MAX_PER_CLUSTER:
            if dropped is not None:
                dropped["chat_history"] = dropped.get("chat_history", 0) + len(turns)
            continue

        for line_no, turn in enumerate(turns):
            content = turn.get("content", "")
            if not content:
                continue
            yield CorpusRecord(
                source_type="chat_history",
                source_path=f"{path.name}#L{line_no}",
                text=content,
                metadata={
                    "sub_source": "conversation_store",
                    "role": turn.get("role"),
                    "ts": turn.get("ts"),
                },
            )


def _iter_observation_queue_records(
    dropped: Optional[Dict[str, int]] = None,
) -> Generator[CorpusRecord, None, None]:
    """
    Broader per-prompt capture across ALL chats (not just ask()).

    Each line is already one full user+assistant unit, so capping (see
    module docstring) keys directly on the normalized `user_text`, one
    line at a time -- no file-level grouping needed, unlike ConversationStore.
    """
    if not _OBSERVATION_QUEUE_PATH.is_file():
        return
    cluster_counts: Dict[str, int] = {}
    try:
        handle = _OBSERVATION_QUEUE_PATH.open("r", encoding="utf-8")
    except OSError:
        return
    with handle:
        for line_no, raw_line in enumerate(handle):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                obs = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            user_text = obs.get("user_text", "")
            assistant_summary = obs.get("assistant_summary", "")
            if not user_text and not assistant_summary:
                continue

            key = _cluster_key(user_text)
            cluster_counts[key] = cluster_counts.get(key, 0) + 1
            if cluster_counts[key] > _MAX_PER_CLUSTER:
                if dropped is not None:
                    dropped["chat_history"] = dropped.get("chat_history", 0) + 1
                continue

            text = f"USER: {user_text}\nASSISTANT: {assistant_summary}".strip()
            yield CorpusRecord(
                source_type="chat_history",
                source_path=f"observation_queue.jsonl#L{line_no}",
                text=text,
                metadata={
                    "sub_source": "observation_queue",
                    "chat_label": obs.get("chat_label"),
                    "machine": obs.get("machine"),
                    "ts": obs.get("ts"),
                },
            )


def iter_chat_history_records(
    dropped: Optional[Dict[str, int]] = None,
) -> Generator[CorpusRecord, None, None]:
    """
    LAYER: Specialists (Corpus Assembly)

    Merges two independent capture mechanisms that exist today — both are
    work-laptop/Claude-Code only; "Antigravity" appears nowhere as a
    captured chat_label/machine value yet (JARVIS_ENDGAME.md's planned
    second client, not built). This source grows automatically once that
    capture exists — no redesign needed here.
    """
    yield from _iter_conversation_store_records(dropped=dropped)
    yield from _iter_observation_queue_records(dropped=dropped)


# =============================================================================
# Part 6: SOURCE 4 — DATA ENGINEERING CORPUS
# =============================================================================

def iter_de_corpus_records(root: Optional[Path] = None) -> Generator[CorpusRecord, None, None]:
    """
    LAYER: Specialists (Corpus Assembly)

    Reads the user's own authored DE notes named in _DE_CORPUS_FILES —
    deliberately not the whole knowledge/Data Engineering/ tree (see that
    constant's comment for what's excluded and why).
    """
    base = root or _DE_CORPUS_ROOT
    chunker = _chunker()
    for filename in _DE_CORPUS_FILES:
        path = base / filename
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for i, chunk in enumerate(chunker.chunk(text)):
            yield CorpusRecord(
                source_type="de_corpus",
                source_path=f"{filename}#chunk{i}",
                text=chunk,
                metadata={"file": filename},
            )


# =============================================================================
# Part 6b: SOURCE 6 — REAL CLIENT PRODUCTION WORK
# =============================================================================

def iter_client_work_records(root: Optional[Path] = None) -> Generator[CorpusRecord, None, None]:
    """
    LAYER: Specialists (Corpus Assembly)

    Production data engineering from client_work/ — the gitignored quarantine
    holding verbatim client repos and raw project notes.

    This is the only source carrying code the user was PAID to write, on an
    estate of 20k+ tables, against constraints (Unity Catalog masking, Azure
    vCPU quota, cross-region auth, spot eviction) that no amount of personal-
    project work produces. Every other source is either JARVIS's own code or
    notes about work done elsewhere.

    Records carry `attribution`: "authored" for the user's own slice, "team"
    for the surrounding repo. See _CLIENT_WORK_AUTHORED_MARKERS for why that
    is a tag rather than a filter.

    Every record is redacted through agent.capture.redact() before it is
    yielded — this corpus is uploaded to RunPod for training, so it is the
    last point at which anything leaves the machine under our control. The
    quarantine is trusted not to be committed; it is NOT trusted to be free
    of a credential someone pasted into a notebook.
    """
    base = root or _CLIENT_WORK_ROOT
    if not base.is_dir():
        return
    chunker = _chunker()
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        if _CLIENT_WORK_SKIP_DIRS & set(path.parts):
            continue
        name = path.name
        if any(marker in name for marker in _CLIENT_WORK_JUNK_MARKERS):
            continue
        if path.suffix.lower() not in _CLIENT_WORK_EXTENSIONS:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if not text.strip():
            continue
        rel = path.relative_to(base).as_posix()
        attribution = (
            "authored"
            if any(m in rel for m in _CLIENT_WORK_AUTHORED_MARKERS)
            else "team"
        )
        for i, chunk in enumerate(chunker.chunk(redact(text))):
            yield CorpusRecord(
                source_type="client_work",
                source_path=f"{rel}#chunk{i}",
                text=chunk,
                metadata={
                    "file": rel,
                    "attribution": attribution,
                    "language": path.suffix.lstrip("."),
                },
            )


# =============================================================================
# Part 7: SOURCE 5 — PAST ERROR LOGS (does not exist yet)
# =============================================================================

def iter_error_log_records() -> Generator[CorpusRecord, None, None]:
    """
    LAYER: Specialists (Corpus Assembly)

    Verified 2026-08-03: no persistent error log exists anywhere in this
    codebase. agent/errors.py's ErrorHandler tracks retries in an
    in-memory dict only; agent/telemetry.py analyzes user-message TEXT
    (typos, sentiment), not exceptions; zero *.log files exist in the repo.

    Yields nothing on purpose — kept as its own source (not deleted) so
    the gap stays visible in CorpusStats as an explicit zero, not a
    quietly-dropped item from the roadmap's stated 5-source design.
    """
    yield from ()


# =============================================================================
# Part 8: ASSEMBLY — MERGE ALL SOURCES, WRITE ONE JSONL FILE
# =============================================================================

_SOURCE_ITERATORS = (
    ("jarvis_core_code", lambda dropped: iter_jarvis_core_records()),
    ("kb_entry", lambda dropped: iter_kb_records(dropped=dropped)),
    ("chat_history", lambda dropped: iter_chat_history_records(dropped=dropped)),
    ("de_corpus", lambda dropped: iter_de_corpus_records()),
    ("client_work", lambda dropped: iter_client_work_records()),
    ("error_log", lambda dropped: iter_error_log_records()),
)


def assemble_corpus(output_path: Optional[Path] = None) -> CorpusStats:
    """
    LAYER: Specialists (Corpus Assembly)

    Streams every source generator through ONE open file handle — writes
    one JSON line per record as it's produced and tallies per-source
    stats as a byproduct of the write loop. The full record set is never
    held in memory at once, regardless of corpus size.

    A single `dropped` dict is threaded through every source that applies
    near-duplicate capping (kb_entry, chat_history — see module docstring)
    so CorpusStats reports exactly what was filtered, not just a smaller
    total — dropped records are a fact worth surfacing, not hiding.
    """
    path = output_path or _DEFAULT_OUTPUT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    per_source: Dict[str, Dict[str, int]] = {
        name: {"records": 0, "chars": 0} for name, _ in _SOURCE_ITERATORS
    }
    dropped: Dict[str, int] = {}
    total_records = 0

    with path.open("w", encoding="utf-8") as handle:
        for source_name, iterator_fn in _SOURCE_ITERATORS:
            for record in iterator_fn(dropped):
                handle.write(json.dumps({
                    "source_type": record.source_type,
                    "source_path": record.source_path,
                    "text": record.text,
                    "metadata": record.metadata,
                }, ensure_ascii=False) + "\n")
                per_source[source_name]["records"] += 1
                per_source[source_name]["chars"] += len(record.text)
                total_records += 1

    return CorpusStats(
        per_source=per_source,
        total_records=total_records,
        output_path=path,
        dropped_near_duplicates=dropped,
    )


# =============================================================================
# MAIN ENTRY POINT (Self-test: assemble the corpus, print a summary)
# =============================================================================

def main() -> None:
    """Assemble the Engineer corpus and print a per-source stats table."""
    print("=" * 70)
    print("  JARVIS Stage 5.2.2: Engineer Corpus Assembly")
    print("=" * 70)

    stats = assemble_corpus()

    print(f"\n  {'Source':<18} {'Records':>10} {'Chars':>12} {'Dropped (dup)':>14}")
    print("  " + "-" * 58)
    for name, counts in stats.per_source.items():
        note = "  (no source exists yet)" if counts["records"] == 0 else ""
        dropped = stats.dropped_near_duplicates.get(name, 0)
        print(f"  {name:<18} {counts['records']:>10,} {counts['chars']:>12,} {dropped:>14,}{note}")
    print("  " + "-" * 58)
    print(f"  {'TOTAL':<18} {stats.total_records:>10,}")

    size = stats.output_path.stat().st_size
    print(f"\n  Output: {stats.output_path} ({size:,} bytes)")
    print("=" * 70)


if __name__ == "__main__":
    main()
