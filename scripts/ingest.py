"""
ingest.py

JARVIS Memory Layer: Canonical PDF Ingestion Runner.

Run with (activate venv first):
    python scripts/ingest.py <path_to_pdf> [--category ai] [--collection research_papers]

Examples:
    python scripts/ingest.py "research papers/RAGs/2407.19813v3.pdf"
    python scripts/ingest.py "research papers/RAGs/2407.19813v3.pdf" --category biology
    python scripts/ingest.py "/absolute/path/to/paper.pdf" --category physics --collection research_papers

=============================================================================
THE BIG PICTURE
=============================================================================

Without this script:
    -> One-off scratch scripts get created each time, lose upgrades over time
    -> Caller must manually know the collection name, category, and sys.path

With this script:
    -> Single permanent entry point for all PDF ingestion
    -> SPECIALIST_MAP is auto-applied from the category flag
    -> Images + text both routed correctly via IngestionPipeline
    -> Re-running is always safe (upsert — 0 duplicates, metadata refreshed)

=============================================================================
THE FLOW (Step by Step Execution Order)
=============================================================================

STEP 1: Parse CLI args: pdf_path, category, collection
        |
STEP 2: Validate the PDF exists on disk
        |
STEP 3: IngestionPipeline.ingest_pdf(pdf_path, source_category)
        -> Images -> jarvis_data/extracted_images/{stem}_page{N}_img{M}.ext
        -> Text chunks -> ChromaDB collection with {source, page, category, specialist}
        |
STEP 4: Print ingestion report

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
        prog="ingest.py",
        description="JARVIS — Ingest a PDF into the vector database.",
    )
    parser.add_argument(
        "pdf_path",
        type=str,
        help="Absolute path to the PDF file to ingest.",
    )
    parser.add_argument(
        "--category",
        type=str,
        default="research_paper",
        help=(
            "Domain category of the document. Controls which specialist owns it. "
            "Examples: ai, biology, physics, chemistry, engineering, mathematics. "
            "Default: research_paper (routes to The Orchestrator)."
        ),
    )
    parser.add_argument(
        "--collection",
        type=str,
        default="research_papers",
        help="ChromaDB collection name to ingest into. Default: research_papers.",
    )
    return parser


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    parser = _build_parser()
    args = parser.parse_args()

    # Validate file exists before importing heavy libraries
    pdf = Path(args.pdf_path).resolve()
    if not pdf.exists():
        print(f"[ingest.py] ERROR: File not found: {pdf}")
        sys.exit(1)

    # Import pipeline only after path check (avoids slow torch load on bad input)
    from jarvis_core.memory.ingestion import IngestionPipeline, SPECIALIST_MAP, _DEFAULT_SPECIALIST

    specialist = SPECIALIST_MAP.get(args.category, _DEFAULT_SPECIALIST)

    print("=" * 60)
    print("  JARVIS — PDF Ingestion")
    print("=" * 60)
    print(f"  File       : {pdf.name}")
    print(f"  Category   : {args.category}")
    print(f"  Specialist : {specialist}")
    print(f"  Collection : {args.collection}")
    print("=" * 60)

    pipeline = IngestionPipeline(collection_name=args.collection)
    report = pipeline.ingest_pdf(str(pdf), source_category=args.category)

    print("\n" + "=" * 60)
    print("  Ingestion Report")
    print("=" * 60)
    print(f"  Status          : {report['status']}")
    print(f"  Pages           : {report['pages']}")
    print(f"  Chunks processed: {report['chunks_processed']}")
    print(f"  Images saved    : {report['images_saved_to_disk']}")
    print(f"  Specialist      : {report['specialist']}")
    print(f"  Elapsed         : {report['elapsed_ms']:.0f}ms")
    print("=" * 60)
