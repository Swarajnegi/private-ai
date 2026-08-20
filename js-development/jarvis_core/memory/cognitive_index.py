"""
cognitive_index.py

JARVIS Memory Layer: Structured Cognitive-Dimension Index (Decision 2026-08-10).

Import with:
    from jarvis_core.memory.cognitive_index import (
        rebuild_index, query_by_dimension, query_by_type, query_by_tag,
        query_all, IndexStats, IndexedEntry,
    )

=============================================================================
THE BIG PICTURE: making the KB's own brain-inspired taxonomy queryable
=============================================================================

knowledge_base.jsonl already organizes entries by a brain-inspired taxonomy
-- Episodic/Semantic/Procedural is literally the standard cognitive-science
memory model (autobiographical events / facts / skills), and
Cognitive_Pattern entries are literally personality data. The taxonomy was
never missing. It just was never QUERYABLE as structure.

scripts/profile_synth.py -- the only current consumer of this taxonomy --
buckets entries by matching literal substrings in lowercased content
("user has", "background", "expertise", "stage", "anti-pattern"...) inside
4 hardcoded Python buckets, recomputed via a full linear scan on every run.
An entry whose phrasing doesn't happen to contain one of those substrings
silently never lands in the right bucket -- an invisible failure mode. And
asking a genuinely new question ("show me only intellect/skill-gap
entries") means editing that Python matching logic, not writing a query.

Without this index:
    -> "brain regions" stays a metaphor, not a queryable structure
    -> Every new personalization consumer re-implements its own fragile
       substring bucketing from scratch, the way profile_synth already has
    -> No way to ask "how many personality-dimension entries do I have"
       without grepping tags by hand

With this index:
    -> One regenerable SQLite database, one row per KB entry, with an
       explicit cognitive_dimension column derived from the EXISTING
       `type` field (not a new manual classification) -- deterministic,
       documented in _DIMENSION_MAP below, not an inferred guess.
    -> WHERE cognitive_dimension = 'personality' is a real query.
    -> knowledge_base.jsonl remains the durable, git-tracked, cross-machine
       source of truth. This index is derived and disposable -- same
       relationship ChromaDB already has to source documents (gitignored,
       rebuildable any time via rebuild_index()).

=============================================================================
THE FLOW
=============================================================================

STEP 1: rebuild_index() streams knowledge_base.jsonl line by line (never
        materializes the full file), defensively parsing schema-drifted
        entries the same way jarvis_core.specialists.engineer_corpus does
        (earliest entries lack `id` -- falls back to a line-number key).
        |
STEP 2: Each entry's `type` maps to exactly one cognitive_dimension via
        _DIMENSION_MAP. Unknown/future types fall back to "uncategorized"
        rather than crashing or silently dropping the entry.
        |
STEP 3: One row per entry written to `entries`; each tag written to the
        `entry_tags` join table (many-to-many, not a stringly-typed blob).
        |
STEP 4: query_by_dimension() / query_by_type() / query_by_tag() run real
        SQL against indexed columns, yielding IndexedEntry records lazily
        (a live cursor, never a materialized list).

LAYER: Memory (Structured Cognitive Index). Follow-up to Decision
2026-08-10 (KB 463): this is the Memory-layer piece -- the Orchestrator
only CONSUMES the synthesized result via context-injection, it doesn't own
storage or structuring. Wiring this into profile_synth.py (replacing its
substring bucketing) is a natural next step, not done in this pass -- kept
separate to avoid re-testing profile_synth's 9 existing self-tests in the
same change as introducing the index itself.
=============================================================================
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Generator, Optional, Tuple

from jarvis_core.config import COGNITIVE_INDEX_PATH, KB_PATH


# =============================================================================
# Part 1: THE DIMENSION MAP (explicit, documented, not inferred)
# =============================================================================
#
# Five brain-region-style buckets, each a coarser grouping of the KB's own
# 8 existing entry types -- not a new taxonomy, a queryable view onto the
# one that already exists:
#
#   personality  <- Cognitive_Pattern         (how the user thinks/behaves)
#   intellect    <- Procedural, Idea          (skills + generative output)
#   memory       <- Episodic                  (autobiographical events)
#   knowledge    <- Semantic, Reference        (facts, technical truths)
#   executive    <- Decision, System_Protocol, Failure
#                   (standing rules, strategic choices, and lessons that
#                    constrain future behavior -- all "govern what happens
#                    next", same functional role as a directive)
#
_DIMENSION_MAP: Dict[str, str] = {
    "Cognitive_Pattern": "personality",
    "Procedural": "intellect",
    "Idea": "intellect",
    "Episodic": "memory",
    "Semantic": "knowledge",
    "Reference": "knowledge",
    "Decision": "executive",
    "System_Protocol": "executive",
    "Failure": "executive",
}
_UNKNOWN_DIMENSION = "uncategorized"


def _dimension_for(entry_type: str) -> str:
    return _DIMENSION_MAP.get(entry_type, _UNKNOWN_DIMENSION)


# =============================================================================
# Part 2: RECORD SHAPES
# =============================================================================

@dataclass(frozen=True)
class IndexedEntry:
    """One KB entry as read back from the index, tags included."""
    id: str
    type: str
    cognitive_dimension: str
    timestamp: str
    content: str
    tags: Tuple[str, ...]


@dataclass(frozen=True)
class IndexStats:
    """Returned by rebuild_index() -- what actually got indexed."""
    total_entries: int
    per_dimension: Dict[str, int]
    per_type: Dict[str, int]
    db_path: Path


_SCHEMA = """
CREATE TABLE entries (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    cognitive_dimension TEXT NOT NULL,
    timestamp TEXT,
    expiry TEXT,
    content TEXT NOT NULL
);
CREATE TABLE entry_tags (
    entry_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    FOREIGN KEY (entry_id) REFERENCES entries(id)
);
CREATE INDEX idx_entries_dimension ON entries(cognitive_dimension);
CREATE INDEX idx_entries_type ON entries(type);
CREATE INDEX idx_entry_tags_tag ON entry_tags(tag);
"""


# =============================================================================
# Part 3: KB STREAMING (schema-drift-defensive, matches engineer_corpus.py)
# =============================================================================

def _iter_kb_entries(kb_path: Path) -> Generator[Dict[str, Any], None, None]:
    """Streams the KB line by line -- never materializes the full file."""
    try:
        handle = kb_path.open("r", encoding="utf-8")
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
            entry.setdefault("id", f"line{line_no}")
            yield entry


# =============================================================================
# Part 4: REBUILD -- FULL REPLACE, NOT INCREMENTAL
# =============================================================================

def rebuild_index(kb_path: Optional[Path] = None, db_path: Optional[Path] = None) -> IndexStats:
    """
    LAYER: Memory (Structured Cognitive Index)

    Full rebuild every time, not incremental sync. At KB sizes in the low
    thousands a full rebuild is well under a second and sidesteps an
    entire class of incremental-sync bugs (stale rows after a KB edit or
    kb_compact.py run) for free.
    """
    kb = kb_path or KB_PATH
    db = db_path or COGNITIVE_INDEX_PATH
    db.parent.mkdir(parents=True, exist_ok=True)
    if db.exists():
        db.unlink()

    per_dimension: Dict[str, int] = {}
    per_type: Dict[str, int] = {}
    total = 0

    conn = sqlite3.connect(str(db))
    try:
        conn.executescript(_SCHEMA)
        for entry in _iter_kb_entries(kb):
            entry_id = str(entry["id"])
            entry_type = entry.get("type", "")
            dimension = _dimension_for(entry_type)

            conn.execute(
                "INSERT INTO entries (id, type, cognitive_dimension, timestamp, expiry, content) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    entry_id,
                    entry_type,
                    dimension,
                    entry.get("timestamp", ""),
                    entry.get("expiry", ""),
                    entry.get("content", ""),
                ),
            )
            for tag in entry.get("tags", []) or []:
                conn.execute(
                    "INSERT INTO entry_tags (entry_id, tag) VALUES (?, ?)",
                    (entry_id, tag),
                )

            per_dimension[dimension] = per_dimension.get(dimension, 0) + 1
            per_type[entry_type] = per_type.get(entry_type, 0) + 1
            total += 1
        conn.commit()
    finally:
        conn.close()

    return IndexStats(total_entries=total, per_dimension=per_dimension, per_type=per_type, db_path=db)


# =============================================================================
# Part 5: QUERIES -- LAZY, ONE LIVE CURSOR AT A TIME
# =============================================================================

def _row_to_entry(row: sqlite3.Row, conn: sqlite3.Connection) -> IndexedEntry:
    tag_rows = conn.execute(
        "SELECT tag FROM entry_tags WHERE entry_id = ?", (row["id"],)
    ).fetchall()
    return IndexedEntry(
        id=row["id"],
        type=row["type"],
        cognitive_dimension=row["cognitive_dimension"],
        timestamp=row["timestamp"],
        content=row["content"],
        tags=tuple(t["tag"] for t in tag_rows),
    )


def query_by_dimension(
    dimension: str, db_path: Optional[Path] = None
) -> Generator[IndexedEntry, None, None]:
    """LAYER: Memory. e.g. query_by_dimension("personality") -> all Cognitive_Pattern entries."""
    db = db_path or COGNITIVE_INDEX_PATH
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(
            "SELECT * FROM entries WHERE cognitive_dimension = ? ORDER BY timestamp DESC",
            (dimension,),
        )
        for row in cursor:
            yield _row_to_entry(row, conn)
    finally:
        conn.close()


def query_by_type(
    entry_type: str, db_path: Optional[Path] = None
) -> Generator[IndexedEntry, None, None]:
    """LAYER: Memory. The KB's original 8 types, unaggregated."""
    db = db_path or COGNITIVE_INDEX_PATH
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(
            "SELECT * FROM entries WHERE type = ? ORDER BY timestamp DESC", (entry_type,)
        )
        for row in cursor:
            yield _row_to_entry(row, conn)
    finally:
        conn.close()


def query_by_tag(tag: str, db_path: Optional[Path] = None) -> Generator[IndexedEntry, None, None]:
    """LAYER: Memory. Exact tag match via the entry_tags join table."""
    db = db_path or COGNITIVE_INDEX_PATH
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(
            "SELECT entries.* FROM entries "
            "JOIN entry_tags ON entries.id = entry_tags.entry_id "
            "WHERE entry_tags.tag = ? ORDER BY entries.timestamp DESC",
            (tag,),
        )
        for row in cursor:
            yield _row_to_entry(row, conn)
    finally:
        conn.close()


def query_all(db_path: Optional[Path] = None) -> Generator[IndexedEntry, None, None]:
    """
    LAYER: Memory. Every indexed entry, unfiltered.

    Exists for the handful of signals that are genuinely about the TEXT,
    not the type/tag/dimension structure (e.g. "does this literally say
    DIRECTIVE: inline") -- callers needing that still get a real, lazy
    cursor instead of re-reading knowledge_base.jsonl by hand.
    """
    db = db_path or COGNITIVE_INDEX_PATH
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute("SELECT * FROM entries ORDER BY timestamp DESC")
        for row in cursor:
            yield _row_to_entry(row, conn)
    finally:
        conn.close()


# =============================================================================
# MAIN ENTRY POINT (real rebuild against the real KB + correctness checks)
# =============================================================================

def _run_self_test() -> None:
    """Toy-data correctness invariants -- mirrors jarvis_core.memory.bm25's smoke-test style."""
    import tempfile

    print("=" * 70)
    print("  cognitive_index.py -- Smoke Tests")
    print("=" * 70)

    with tempfile.TemporaryDirectory() as td:
        kb = Path(td) / "kb.jsonl"
        db = Path(td) / "index.sqlite3"
        fake = [
            {"id": 1, "type": "Cognitive_Pattern", "tags": ["learning-style"],
             "timestamp": "2026-01-01T00:00:00+05:30", "content": "User prefers depth."},
            {"id": 2, "type": "Procedural", "tags": ["sql", "gaps-and-islands"],
             "timestamp": "2026-01-02T00:00:00+05:30", "content": "Gaps-and-islands trick."},
            {"type": "Episodic", "tags": ["session"],  # no id -- schema drift
             "timestamp": "2026-01-03T00:00:00+05:30", "content": "Shipped Stage 3."},
            {"id": 4, "type": "NotARealType", "tags": [],
             "timestamp": "2026-01-04T00:00:00+05:30", "content": "Future type."},
        ]
        with open(kb, "w", encoding="utf-8") as f:
            for e in fake:
                f.write(json.dumps(e) + "\n")

        stats = rebuild_index(kb, db)
        assert stats.total_entries == 4, f"expected 4, got {stats.total_entries}"
        assert stats.per_dimension.get("personality") == 1
        assert stats.per_dimension.get("intellect") == 1
        assert stats.per_dimension.get("memory") == 1
        assert stats.per_dimension.get("uncategorized") == 1, "unknown type must not crash or vanish"
        print(f"  T1 rebuild counts correct: {stats.per_dimension}  PASS")

        personality = list(query_by_dimension("personality", db))
        assert len(personality) == 1 and personality[0].content == "User prefers depth."
        print("  T2 query_by_dimension exact match  PASS")

        sql_tagged = list(query_by_tag("sql", db))
        assert len(sql_tagged) == 1 and sql_tagged[0].type == "Procedural"
        print("  T3 query_by_tag join correctness  PASS")

        no_id_entry = list(query_by_type("Episodic", db))
        assert len(no_id_entry) == 1 and no_id_entry[0].id == "line2", no_id_entry
        print("  T4 schema-drift fallback id (line2) survives round-trip  PASS")

        stats2 = rebuild_index(kb, db)
        assert stats2.total_entries == stats.total_entries
        print("  T5 rebuild is idempotent (same KB -> same counts)  PASS")

        everything = list(query_all(db))
        assert len(everything) == 4, f"expected 4, got {len(everything)}"
        assert {e.id for e in everything} == {"1", "2", "line2", "4"}
        print("  T6 query_all returns every entry, ids included  PASS")

    print("\n  All 6 smoke tests passed.")
    print("=" * 70)


def main() -> None:
    _run_self_test()

    print()
    print("#" * 70)
    print("  Rebuilding cognitive_index.sqlite3 from the real KB")
    print("#" * 70)

    stats = rebuild_index()

    print(f"\n  Total entries indexed: {stats.total_entries}")
    print(f"\n  {'Dimension':<16} {'Count':>8}")
    print("  " + "-" * 26)
    for dim, count in sorted(stats.per_dimension.items(), key=lambda kv: -kv[1]):
        print(f"  {dim:<16} {count:>8}")

    print(f"\n  {'Type':<20} {'Count':>8}")
    print("  " + "-" * 30)
    for t, count in sorted(stats.per_type.items(), key=lambda kv: -kv[1]):
        print(f"  {t:<20} {count:>8}")

    print(f"\n  DB: {stats.db_path}")

    print("\n" + "#" * 70)
    print("  Example: 3 most recent 'personality' entries")
    print("#" * 70)
    for entry in list(query_by_dimension("personality"))[:3]:
        print(f"\n  [{entry.timestamp}] tags={entry.tags}")
        print(f"  {entry.content[:160]}")
    print()
    print("#" * 70)


if __name__ == "__main__":
    main()
