"""
sync_chromadb.py — bring local ChromaDB up to date by replaying missing
ingestions from the manifest.

Why this exists:
    knowledge_base.jsonl syncs cleanly via git, but ChromaDB is a binary store
    that's gitignored. After a `git pull`, the local ChromaDB may be missing
    chunks from papers ingested on the OTHER laptop. This script reads
    `jarvis_data/ingestion_manifest.jsonl` (which IS git-tracked) and re-runs
    `IngestionPipeline.ingest_pdf` for any paper not yet present in the local
    ChromaDB.

How it works:
    1. Reads the manifest (one JSON line per ingestion event).
    2. For each unique (collection, paper) pair, queries the local ChromaDB
       for that source filename. If chunks already exist, skip. If not,
       re-ingest using the recorded category.
    3. Ingestion is deterministic — md5(filename + chunk_index) chunk IDs
       mean the result is byte-identical to the original ingestion.

Usage:
    python3 scripts/sync_chromadb.py              # check + replay missing
    python3 scripts/sync_chromadb.py --dry-run    # show plan, don't ingest
    python3 scripts/sync_chromadb.py --force      # re-ingest everything

Manifest entry shape:
    {"timestamp": "2026-04-27T10:35:00+05:30",
     "machine": "work-linux",
     "paper": "research papers/RAGs/2501.09136v3.pdf",
     "chunks": 156, "images": 24,
     "collection": "research_papers", "category": "ai"}

The `paper` field is relative to JARVIS_ROOT so the manifest is portable
across machines.
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Set

# Make jarvis_core importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "js-development"))

from jarvis_core.config import DATA_ROOT, DB_ROOT, JARVIS_ROOT
from jarvis_core.memory.ingestion import IngestionPipeline

MANIFEST_PATH = DATA_ROOT / "ingestion_manifest.jsonl"


def read_manifest() -> List[Dict]:
    if not MANIFEST_PATH.exists():
        return []
    entries: List[Dict] = []
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"[warn] {MANIFEST_PATH}:{lineno} unparseable, skipping: {e}",
                      file=sys.stderr)
    return entries


def get_ingested_papers(collection_name: str) -> Set[str]:
    """Return the set of paper filenames that already have chunks in the local
    ChromaDB collection. Uses chromadb directly to avoid coupling to internals
    of JarvisMemoryStore."""
    try:
        import chromadb
    except ImportError:
        print("[error] chromadb not installed: pip install --user chromadb",
              file=sys.stderr)
        sys.exit(2)

    if not DB_ROOT.exists():
        return set()

    client = chromadb.PersistentClient(path=str(DB_ROOT))
    try:
        col = client.get_collection(collection_name)
    except Exception:
        return set()  # Collection doesn't exist yet — everything is "missing"

    # Pull metadatas in chunks of 10k. For 100s of papers this is one call.
    all_meta = col.get(limit=100000, include=["metadatas"])
    return {
        m.get("source")
        for m in (all_meta.get("metadatas") or [])
        if m and m.get("source")
    }


def build_plan(entries: List[Dict], force: bool) -> List[Dict]:
    """Determine which manifest entries need (re-)ingestion locally."""
    by_collection: Dict[str, List[Dict]] = {}
    for e in entries:
        col = e.get("collection", "research_papers")
        by_collection.setdefault(col, []).append(e)

    plan: List[Dict] = []
    for col_name, evts in by_collection.items():
        present = set() if force else get_ingested_papers(col_name)
        for evt in evts:
            paper_rel = evt.get("paper")
            if not paper_rel:
                continue
            paper_path = JARVIS_ROOT / paper_rel
            paper_name = paper_path.name

            if paper_name in present and not force:
                continue
            if not paper_path.exists():
                print(f"[warn] paper missing on disk: {paper_path}", file=sys.stderr)
                continue

            plan.append({
                "path": str(paper_path),
                "category": evt.get("category", "research_paper"),
                "collection": col_name,
                "expected_chunks": evt.get("chunks"),
                "expected_images": evt.get("images"),
            })
    return plan


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--dry-run", action="store_true",
                   help="Print the plan without ingesting")
    p.add_argument("--force", action="store_true",
                   help="Re-ingest every paper in the manifest (idempotent)")
    args = p.parse_args()

    entries = read_manifest()
    if not entries:
        print(f"[info] no manifest at {MANIFEST_PATH} — nothing to sync")
        return 0
    print(f"[info] manifest: {len(entries)} ingestion event(s)")

    plan = build_plan(entries, force=args.force)
    if not plan:
        print("[ok] ChromaDB is up to date — no ingestion needed")
        return 0

    print(f"[info] {len(plan)} paper(s) to ingest:")
    for item in plan:
        exp = ""
        if item["expected_chunks"] is not None:
            exp = f"  (expect ~{item['expected_chunks']} chunks, {item['expected_images']} images)"
        print(f"  - {Path(item['path']).name}  -> {item['collection']}{exp}")

    if args.dry_run:
        print("\n[dry-run] not running ingestion; remove --dry-run to execute")
        return 0

    print()
    failures = 0
    for item in plan:
        try:
            pipeline = IngestionPipeline(collection_name=item["collection"])
            r = pipeline.ingest_pdf(item["path"], source_category=item["category"])
            actual_chunks = r["chunks_processed"]
            actual_images = r["images_saved_to_disk"]
            mark = "[ok]"
            if item["expected_chunks"] is not None and actual_chunks != item["expected_chunks"]:
                mark = "[warn]"
            print(f"{mark} {Path(item['path']).name}: "
                  f"{actual_chunks} chunks, {actual_images} images")
        except Exception as e:
            failures += 1
            print(f"[error] {Path(item['path']).name}: {e}", file=sys.stderr)

    print(f"\n[done] {len(plan) - failures}/{len(plan)} ingestion(s) successful")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
