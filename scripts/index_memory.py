#!/usr/bin/env python3
"""
index_memory.py — put the mind's own history into the vector store.

LAYER: Memory (indexing — a PROJECTION over the append-only log)

Run with:
    python3 scripts/index_memory.py --dry-run
    python3 scripts/index_memory.py

=============================================================================
THE BIG PICTURE
=============================================================================

Measured 2026-09-08: ChromaDB held exactly ONE collection — `research_papers`,
156 embeddings. The knowledge base (546 entries), the conversations and the
observation queue were NOT in the vector store at all.

That is boot.py's own founding bug, still live. Its header records the L324
repro verbatim: "asked 'what have we built till now?', the terminal Mind
searched one ChromaDB collection of research papers and honestly found nothing
— while knowledge_base.jsonl (the actual autobiography) sat unread." The fix
then was to add prior_self_consult as a TOOL, which works but requires the
model to CHOOSE to call it. That is exactly ENDGAME §1.2's stated failure:
"it cannot fire when you did not know to ask."

So semantic auto-retrieval over the user's own history was impossible — not
because MemoryManager was unwired (it was), but because there was nothing
indexed for it to retrieve. Wiring auto-retrieve without this step would have
silently auto-retrieved RESEARCH PAPERS and looked like the feature worked.

WHAT THIS IS, in the storage taxonomy (KB 548): a PROJECTION. The authoritative
record stays knowledge_base.jsonl; this is a derived, disposable index over it.
Safe to delete, safe to re-run — ingest_documents() upserts by deterministic id,
so re-running updates in place rather than duplicating.

=============================================================================
THE FLOW
=============================================================================

STEP 1: stream knowledge_base.jsonl (never load it whole — the file is the
        mind's autobiography and grows without bound).
        |
STEP 2: render each entry to a retrieval-friendly text: type + tags + content,
        so a semantic hit carries its own provenance.
        |
STEP 3: chunk through RecursiveWordChunker (900 chars, 180 overlap) — the
        existing policy that respects MiniLM's 256-token ceiling. Without it
        long entries are silently truncated at embed time (the KB 508 bug).
        |
STEP 4: upsert into the `jarvis_memory` collection with a deterministic id
        (kb-<entry id>-<chunk index>) so re-runs are idempotent.
=============================================================================
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, Generator, List, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "js-development"))

from jarvis_core.config import (  # noqa: E402
    KB_PATH, DEFAULT_CHUNK_CHAR_LIMIT, DEFAULT_CHUNK_OVERLAP,
)
from jarvis_core.memory.chunking import RecursiveWordChunker  # noqa: E402
from jarvis_core.memory.store import JarvisMemoryStore  # noqa: E402

# The collection MemoryManager and auto-retrieve read. Named for what it is —
# the mind's own memory — as distinct from `research_papers`, which is
# third-party literature and must not be conflated with the user's history.
MEMORY_COLLECTION = "jarvis_memory"

_BATCH = 256


def _iter_kb(path: Path) -> Generator[Dict[str, Any], None, None]:
    """Stream KB entries. Never materialises the file (config.py's law)."""
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    yield json.loads(line)
                except ValueError:
                    continue          # a malformed line must not abort the index
    except (OSError, FileNotFoundError):
        return


def _render(entry: Dict[str, Any]) -> str:
    """Entry -> embeddable text carrying its own provenance.

    Type and tags are prepended deliberately: a semantic hit then arrives
    already labelled ("this is a Failure tagged permissions"), which is what
    lets a retrieved chunk be *acted on* rather than merely read.
    """
    etype = str(entry.get("type", "?"))
    tags = ", ".join(str(t) for t in (entry.get("tags") or []))
    ts = str(entry.get("timestamp", ""))[:10]
    content = str(entry.get("content", "")).strip()
    head = f"[{etype}]"
    if tags:
        head += f" (tags: {tags})"
    if ts:
        head += f" [{ts}]"
    return f"{head}\n{content}"


def stable_key(entry: Dict[str, Any]) -> str:
    """A deterministic key for any KB entry, of EITHER schema generation.

    MEASURED 2026-09-08: the KB holds two schemas. 250 entries carry `id` (and
    `source_machine`); 281 older ones carry only content/expiry/tags/timestamp/
    type. Keying on `id` alone skipped 300 of 554 entries — 54% of the mind's
    memory — and the resulting count (254) was plausible enough to pass
    unnoticed. Same silent-partial-coverage class as the KB 508 truncation bug.

    So: use `id` when present, otherwise content-address the entry. Both are
    stable across re-runs, which is what keeps the upsert idempotent.
    """
    eid = entry.get("id")
    if eid is not None:
        return f"kb-{eid}"
    basis = (f"{entry.get('timestamp','')}|{entry.get('type','')}|"
             f"{str(entry.get('content',''))[:400]}")
    return "kbh-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def build_records(
    kb_path: Path, chunker: RecursiveWordChunker
) -> Generator[Tuple[str, str, Dict[str, Any]], None, None]:
    """(id, document, metadata) per chunk. Covers BOTH KB schema generations."""
    for entry in _iter_kb(kb_path):
        if not str(entry.get("content", "")).strip():
            continue          # nothing embeddable; skipping is correct here
        key = stable_key(entry)
        eid = entry.get("id")
        text = _render(entry)
        for i, chunk in enumerate(chunker.chunk(text)):
            yield (
                f"{key}-{i}",
                chunk,
                {
                    # WARM is the correct tier and this field is LOAD-BEARING:
                    # MemoryManager.retrieve queries ChromaDB with
                    # where={"tier": tier.value}, so a record without it is
                    # invisible to auto-retrieval. Measured: 1030 chunks
                    # indexed without it returned 0 hits. WARM (not HOT) because
                    # HOT is an in-process LRU that dies with the process;
                    # WARM is durable and semantically searchable, which is
                    # exactly what the knowledge base is.
                    "tier": "warm",
                    "source": "knowledge_base",
                    "entry_id": int(eid) if str(eid).isdigit() else -1,
                    "key": key,
                    "entry_type": str(entry.get("type", "?")),
                    "tags": ", ".join(str(t) for t in (entry.get("tags") or [])),
                    "timestamp": str(entry.get("timestamp", "")),
                    "chunk_index": i,
                },
            )


def main() -> int:
    p = argparse.ArgumentParser(
        description="Index knowledge_base.jsonl into ChromaDB for auto-retrieval.")
    p.add_argument("--dry-run", action="store_true",
                   help="count what would be indexed and write nothing")
    p.add_argument("--collection", default=MEMORY_COLLECTION)
    p.add_argument("--kb", default=str(KB_PATH))
    args = p.parse_args()

    kb_path = Path(args.kb)
    chunker = RecursiveWordChunker(
        char_limit=DEFAULT_CHUNK_CHAR_LIMIT, overlap=DEFAULT_CHUNK_OVERLAP)

    if args.dry_run:
        entries = chunks = 0
        seen = set()
        for cid, _doc, meta in build_records(kb_path, chunker):
            chunks += 1
            seen.add(meta["key"])
        entries = len(seen)
        print(f"[index_memory] DRY RUN")
        print(f"  kb            : {kb_path}")
        print(f"  entries       : {entries}")
        print(f"  chunks        : {chunks}  (avg {chunks/max(1,entries):.1f} per entry)")
        print(f"  collection    : {args.collection}")
        print(f"  chunk policy  : {DEFAULT_CHUNK_CHAR_LIMIT} chars / "
              f"{DEFAULT_CHUNK_OVERLAP} overlap")
        print("  nothing written")
        return 0

    ids: List[str] = []
    docs: List[str] = []
    metas: List[Dict[str, Any]] = []
    total = 0
    with JarvisMemoryStore() as store:
        for cid, doc, meta in build_records(kb_path, chunker):
            ids.append(cid); docs.append(doc); metas.append(meta)
            if len(ids) >= _BATCH:
                total += store.ingest_documents(args.collection, docs, metas, ids)
                print(f"  ... {total} chunks upserted")
                ids, docs, metas = [], [], []
        if ids:
            total += store.ingest_documents(args.collection, docs, metas, ids)
    print(f"[index_memory] upserted {total} chunks into '{args.collection}'")
    print("  (a PROJECTION — idempotent, safe to re-run, safe to delete)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
