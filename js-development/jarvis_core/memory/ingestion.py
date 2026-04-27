"""
ingestion.py

JARVIS Memory Layer: Master Document Ingestion Pipeline.

Import with:
    from jarvis_core.memory.ingestion import IngestionPipeline

Run (smoke test):
    python -m jarvis_core.memory.ingestion

=============================================================================
THE BIG PICTURE: One function to ingest a document into JARVIS memory
=============================================================================

Without a coordinator:
    -> Each caller must manually wire pdf_parser -> chunker -> store -> images
    -> One caller forgets to hash IDs -> NoveltyGate never fires -> duplicates
    -> Another caller forgets images -> figures are lost forever

With IngestionPipeline:
    -> Single call: pipeline.ingest_pdf("paper.pdf")
    -> Deterministic chunk IDs (md5 of filename + chunk index) ensure
       the NoveltyGate correctly rejects all duplicate chunks on re-run
    -> Text flows: Parser -> Chunker -> Vector DB (jarvis_data/chromadb)
    -> Images flow: Extractor -> Disk (jarvis_data/extracted_images)

=============================================================================
THE FLOW (Step by Step Execution Order)
=============================================================================

STEP 1: IngestionPipeline.__init__ — connect store, init chunker, ensure dirs
        |
STEP 2: ingest_pdf(pdf_path) called
        |
STEP 3: Route images: PdfImageExtractor -> jarvis_data/extracted_images/
        |
STEP 4: Route text: parse_pdf -> full_text() -> RecursiveWordChunker
        |
STEP 5: Generate deterministic chunk IDs: md5(filename + chunk_idx)
        |
STEP 6: store.ingest_documents(collection, chunks, ids)
        NoveltyGate checks ids[0] against DB — skips batch if found
        |
STEP 7: Return ingestion report dict

=============================================================================
"""

import hashlib
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

from jarvis_core.config import DATA_ROOT, DEFAULT_CHUNK_CHAR_LIMIT, DEFAULT_CHUNK_OVERLAP
from jarvis_core.memory.chunking import RecursiveWordChunker
from jarvis_core.memory.image_extractor import extract_images
from jarvis_core.memory.pdf_parser import parse_pdf
from jarvis_core.memory.store import JarvisMemoryStore


# =============================================================================
# Part 1: CONSTANTS
# =============================================================================

# The ChromaDB collection name where all research paper chunks are stored.
# Change this to namespace different document types (e.g., "code_docs").
DEFAULT_COLLECTION: str = "jarvis_core_knowledge"

# =============================================================================
# Part 1b: SPECIALIST MAP
# =============================================================================

# Maps a source_category string to the JARVIS specialist who owns that domain.
# This populates the 'specialist' metadata field on every chunk so the Brain
# can issue WHERE-filtered queries at inference time:
#   e.g. store.query_collection("research_papers", query, where={"specialist": "The Doctor"})
#
# PHASE NOTE: Specialist names here are Phase 2 scaffolding.
# In Phase 5, each specialist will have its own domain-tuned embedding model
# and the collection split will be re-evaluated at that point.
SPECIALIST_MAP: Dict[str, str] = {
    # AI / ML / Systems
    "ai":               "The Scientist",
    "machine_learning": "The Scientist",
    "deep_learning":    "The Scientist",
    "nlp":              "The Scientist",
    "robotics":         "The Scientist",
    # Life Sciences
    "biology":          "The Doctor",
    "medicine":         "The Doctor",
    "neuroscience":     "The Doctor",
    "chemistry":        "The Doctor",
    # Physical Sciences
    "physics":          "The Scientist",
    "astrophysics":     "The Scientist",
    "mathematics":      "The Scientist",
    # Engineering / Code
    "engineering":      "The Engineer",
    "software":         "The Engineer",
    "code":             "The Engineer",
    # Default: any uncategorized paper goes to The Orchestrator (general Brain)
    "research_paper":   "The Orchestrator",
    "general":          "The Orchestrator",
}

# Fallback when category is not found in SPECIALIST_MAP.
_DEFAULT_SPECIALIST: str = "The Orchestrator"


# =============================================================================
# Part 2: THE INGESTION PIPELINE
# =============================================================================

class IngestionPipeline:
    """
    LAYER: Memory - The master coordinator for all document ingestion.

    It sits BETWEEN:
        - The JARVIS Brain (hands it a file path, expects memory to be updated)
        - The Memory modules: pdf_parser, chunking, image_extractor, store

    Purpose:
        - Provide a single entry point for ingesting a PDF into JARVIS memory
        - Route text chunks into ChromaDB with deterministic IDs for deduplication
        - Route extracted images onto disk for future Vision Specialist consumption

    How it works:
        - Uses JarvisMemoryStore as a context manager for safe DB lifecycle
        - Generates chunk IDs as md5(filename + chunk_index) so re-running
          ingest on the same file produces identical IDs and NoveltyGate fires
    """

    def __init__(
        self,
        collection_name: str = DEFAULT_COLLECTION,
    ) -> None:
        """
        Connect to the ChromaDB store and initialize all ingestion components.

        Args:
            collection_name: The ChromaDB namespace to ingest documents into.
        """
        self._collection_name = collection_name
        self._chunker = RecursiveWordChunker(
            char_limit=DEFAULT_CHUNK_CHAR_LIMIT,
            overlap=DEFAULT_CHUNK_OVERLAP,
        )
        self._image_dir: Path = DATA_ROOT / "extracted_images"
        self._image_dir.mkdir(parents=True, exist_ok=True)

    # ─────────────────────────────────────────────────────────────────────────
    # Private: Build page-aware chunks with their source page number
    # ─────────────────────────────────────────────────────────────────────────

    def _chunk_with_pages(
        self,
        document: Any,
    ) -> List[Tuple[str, int]]:
        """
        Chunk the document and track which PDF page each chunk came from.

        EXECUTION FLOW:
        1. Iterate over each page in the StructuredDocument.
        2. Chunk the text of each individual page.
        3. Tag every resulting chunk with its source page number.

        Why per-page chunking instead of full-document chunking?
            If we chunk the full concatenated text, we lose page boundary
            information. Chunk 37 might span pages 4-5, making the image
            Foreign Key ambiguous. Chunking per page guarantees each chunk
            maps to exactly one page number — enabling a precise glob.

        Returns:
            List of (chunk_text, page_number) tuples.
        """
        page_chunks: List[Tuple[str, int]] = []
        for page in document.pages:
            page_text = " ".join(
                b.text.strip() for b in page.blocks if b.text.strip()
            )
            if not page_text:
                continue
            for chunk in self._chunker.chunk(page_text):
                page_chunks.append((chunk, page.page_number))
        return page_chunks

    # ─────────────────────────────────────────────────────────────────────────
    # Private: Generate stable chunk IDs for the NoveltyGate
    # ─────────────────────────────────────────────────────────────────────────

    def _make_chunk_ids(self, filename: str, chunk_count: int) -> List[str]:
        """
        Generate deterministic IDs: md5(filename + chunk_index).

        Why md5(filename + idx) instead of sequential doc_N?
            Sequential IDs drift. If the DB already has 50 docs, the next
            auto-generated ID is doc_50. But on a re-run, collection.count()
            is still 50, so ids start at doc_50 again — and the NoveltyGate's
            probe finds doc_50 already exists and skips the batch.
            Wait: actually that WOULD work — but only if nothing else ran between.
            A content-hash ID is independent of collection size.
            Same file + same chunk index = same ID, always, on any machine.

        Returns:
            List of hex strings, one per chunk.
        """
        ids: List[str] = []
        for i in range(chunk_count):
            raw = f"{filename}::chunk_{i}".encode("utf-8")
            chunk_id = hashlib.md5(raw).hexdigest()[:16]
            ids.append(chunk_id)
        return ids

    # ─────────────────────────────────────────────────────────────────────────
    # Public: The main ingestion entry point
    # ─────────────────────────────────────────────────────────────────────────

    def ingest_pdf(
        self,
        pdf_path: str,
        source_category: str = "research_paper",
    ) -> Dict[str, Any]:
        """
        Ingest a PDF: extract images to disk, parse + chunk text into ChromaDB.

        EXECUTION FLOW:
        1. Validate the file exists.
        2. Extract real images (deduplicated, noise-filtered) to disk.
        3. Parse the PDF into reading-order text.
        4. Chunk the text into bounded segments.
        5. Generate deterministic chunk IDs from filename + index.
        6. Open JarvisMemoryStore context manager.
        7. Build metadata (source filename, category, page_count) per chunk.
        8. Call store.ingest_documents() — NoveltyGate guards against re-runs.
        9. Return a report dict.

        Args:
            pdf_path:        Absolute path to the PDF file.
            source_category: Tag stored in ChromaDB metadata (e.g. "research_paper").

        Returns:
            Dict with: status, filename, chunks_stored, chunks_skipped, images_saved.

        Raises:
            FileNotFoundError: If pdf_path does not exist.
        """
        path = Path(pdf_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"[IngestionPipeline] File not found: {path}")

        print(f"\n[IngestionPipeline] Starting ingestion: {path.name}")
        t_start = time.perf_counter()

        # ── STEP 1: Route images to disk ──────────────────────────────────────
        print(f"  [1/4] Extracting images...")
        saved_images = extract_images(
            pdf_path=str(path),
            output_dir=str(self._image_dir),
        )
        print(f"        {len(saved_images)} real images saved to {self._image_dir}")

        # ── STEP 2: Parse PDF into reading-order StructuredDocument ───────────
        print(f"  [2/4] Parsing PDF structure...")
        document = parse_pdf(str(path))
        full_text = document.full_text()
        print(f"        {document.total_pages} pages -> {len(full_text):,} chars extracted")

        # ── STEP 3: Chunk per page to preserve page-number tracking ───────────
        #           Each chunk carries the exact page it came from.
        #           This is what makes image Foreign Keys work:
        #               metadata['page'] + metadata['source'] -> glob on disk
        print(f"  [3/4] Chunking text (per-page, with page tracking)...")
        page_chunks: List[Tuple[str, int]] = self._chunk_with_pages(document)
        chunks: List[str]  = [pc[0] for pc in page_chunks]
        pages:  List[int]  = [pc[1] for pc in page_chunks]
        print(f"        {len(chunks)} chunks generated")

        # ── STEP 4: Store in ChromaDB via upsert ─────────────────────────────
        print(f"  [4/4] Storing in ChromaDB (upsert — safe to re-run)...")
        chunk_ids = self._make_chunk_ids(path.name, len(chunks))

        # Metadata: source + page enables Brain to glob images from disk.
        # category + specialist enable WHERE-clause filtering at query time.
        # specialist is derived from source_category via SPECIALIST_MAP.
        specialist: str = SPECIALIST_MAP.get(source_category, _DEFAULT_SPECIALIST)

        metadatas: List[Dict[str, Any]] = [
            {
                "source":      path.name,           # e.g. '1706.03762v7.pdf'
                "page":        pages[i],             # e.g. 4  <- the Foreign Key
                "category":    source_category,      # e.g. 'astrophysics'
                "specialist":  specialist,            # e.g. 'The Scientist'
                "page_count":  document.total_pages,
                "chunk_index": i,
            }
            for i in range(len(chunks))
        ]

        with JarvisMemoryStore() as store:
            stored = store.ingest_documents(
                collection_name=self._collection_name,
                documents=chunks,
                metadatas=metadatas,
                ids=chunk_ids,
            )

        elapsed_ms = (time.perf_counter() - t_start) * 1000

        report: Dict[str, Any] = {
            "status":                   "complete",
            "filename":                 path.name,
            "pages":                    document.total_pages,
            "specialist":               specialist,
            "chunks_processed":         stored,
            "images_saved_to_disk":     len(saved_images),
            "elapsed_ms":               round(elapsed_ms, 1),
        }

        print(f"\n[IngestionPipeline] Done in {elapsed_ms:.0f}ms")
        print(f"  Specialist         : {specialist}")
        print(f"  Text -> ChromaDB   : {self._collection_name}")
        print(f"  Images -> Disk     : {self._image_dir}")
        return report


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

    print("=" * 60)
    print("  JARVIS IngestionPipeline — Live Run")
    print("=" * 60)

    pipeline = IngestionPipeline(collection_name="research_papers")
    target   = "E:/J.A.R.V.I.S/Research Papers/RAGs/2407.19813v3.pdf"

    print(f"\n  Target     : {Path(target).name}")
    print(f"  Collection : research_papers")
    print(f"  Category   : ai")
    print(f"  Specialist : {SPECIALIST_MAP.get('ai', _DEFAULT_SPECIALIST)}")

    # RUN 1: Inserts or updates all chunks.
    # With upsert, re-running is always safe — metadata is refreshed.
    print("\n--- RUN 1 (expect: all chunks processed, new or replaced) ---")
    r1 = pipeline.ingest_pdf(target, source_category="ai")
    print(f"  chunks_processed : {r1['chunks_processed']}")
    print(f"  specialist       : {r1['specialist']}")
    print(f"  images_saved     : {r1['images_saved_to_disk']}")
    print(f"  elapsed_ms       : {r1['elapsed_ms']}")

    # RUN 2: Re-run to demonstrate idempotency.
    # MemoryStore will report: '0 new, 93 replaced' — no data loss, no duplicates.
    print("\n--- RUN 2 (expect: 0 new, all replaced, same total count) ---")
    r2 = pipeline.ingest_pdf(target, source_category="ai")
    print(f"  chunks_processed : {r2['chunks_processed']}")

    print("\n" + "=" * 60)
    print("  Data Locations:")
    print(f"  Text Vectors -> E:/J.A.R.V.I.S/jarvis_data/chromadb/")
    print(f"  Raw Images   -> E:/J.A.R.V.I.S/jarvis_data/extracted_images/")
    print("=" * 60)
