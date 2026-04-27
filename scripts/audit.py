"""
audit.py

JARVIS Memory Layer: Database Health Check and Query Tester.

Run with (activate venv first):
    python scripts/audit.py                          # Full DB audit
    python scripts/audit.py --query "attention mechanism"
    python scripts/audit.py --query "multi-head attention" --specialist "The Scientist"
    python scripts/audit.py --backup                 # Create compressed backup

=============================================================================
THE BIG PICTURE
=============================================================================

Without this script:
    -> Must write ad-hoc Python to inspect ChromaDB state
    -> No standard way to test retrieval quality before plugging into the Brain

With this script:
    -> One command shows collection health, doc count, and SQLite integrity
    -> Test any query and see what JARVIS would actually retrieve
    -> Filter by specialist to validate metadata tagging is working correctly

=============================================================================
THE FLOW (Step by Step Execution Order)
=============================================================================

STEP 1: Parse CLI args
        |
STEP 2: Open JarvisMemoryStore context manager
        |
STEP 3a: If --query supplied -> run semantic search, print ranked results
STEP 3b: Always run audit_database() for health report
STEP 3c: If --backup supplied -> create compressed tar.gz snapshot
        |
STEP 4: Store closes cleanly

=============================================================================
"""

import argparse
import sys
from pathlib import Path

# Ensure jarvis_core is importable regardless of where the script is called from
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "js-development"))


# =============================================================================
# Part 1: CLI ARGUMENT PARSER
# =============================================================================

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="audit.py",
        description="JARVIS — ChromaDB health check and query tester.",
    )
    parser.add_argument(
        "--query",
        type=str,
        default=None,
        help="Run a semantic query against the collection and print top results.",
    )
    parser.add_argument(
        "--collection",
        type=str,
        default="research_papers",
        help="ChromaDB collection to query/audit. Default: research_papers.",
    )
    parser.add_argument(
        "--specialist",
        type=str,
        default=None,
        help=(
            "Filter query results by specialist metadata. "
            "Example: 'The Scientist', 'The Doctor', 'The Engineer'."
        ),
    )
    parser.add_argument(
        "--n",
        type=int,
        default=5,
        help="Number of query results to return. Default: 5.",
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="Create a compressed backup of the ChromaDB directory.",
    )
    return parser


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    parser = _build_parser()
    args = parser.parse_args()

    from jarvis_core.memory.store import JarvisMemoryStore
    from typing import Optional, Dict, Any

    with JarvisMemoryStore() as store:

        # ── Always run the health audit ───────────────────────────────────────
        store.audit_database()

        # ── Optional: semantic query test ─────────────────────────────────────
        if args.query:
            print(f"\n  Query   : '{args.query}'")
            print(f"  Collection: {args.collection}")

            where: Optional[Dict[str, Any]] = None
            if args.specialist:
                where = {"specialist": args.specialist}
                print(f"  Filter  : specialist = '{args.specialist}'")

            print()
            try:
                results = store.query_collection(
                    collection_name=args.collection,
                    query_text=args.query,
                    n_results=args.n,
                    where=where,
                )

                docs = results["documents"][0]
                metas = results["metadatas"][0]
                dists = results["distances"][0]

                print(f"  Top {len(docs)} results:")
                print("  " + "-" * 56)
                for i, (doc, meta, dist) in enumerate(zip(docs, metas, dists)):
                    source = meta.get("source", "unknown")
                    page = meta.get("page", "?")
                    specialist = meta.get("specialist", "?")
                    category = meta.get("category", "?")
                    # Cosine distance: 0.0 = identical, 2.0 = opposite
                    similarity = round(1 - dist, 4)
                    print(f"\n  [{i+1}] score={similarity:.4f} | {source} p.{page} | {specialist} ({category})")
                    print(f"       {doc[:200].strip()}...")

            except Exception as e:
                print(f"  [ERROR] Query failed: {e}")
                print(f"  Likely cause: collection '{args.collection}' does not exist yet.")
                print(f"  Fix: Run 'python scripts/ingest.py <pdf_path>' first.")

        # ── Optional: backup ──────────────────────────────────────────────────
        if args.backup:
            backup_path = store.create_backup()
            print(f"\n  [OK] Backup saved to: {backup_path}")
