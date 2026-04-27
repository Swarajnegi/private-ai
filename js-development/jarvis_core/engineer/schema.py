"""
schema.py

JARVIS Engineer Layer: Canonical Data Type Definitions.

Import with:
    from jarvis_core.engineer.schema import PaperMetadata, EmbeddedPaper, IngestionStats

=============================================================================
THE BIG PICTURE: Type-safe data contracts between JARVIS layers
=============================================================================

Without typed schemas:
    -> Functions pass dicts between layers: {"title": ..., "abstract": ...}
    -> A typo in a key ("titel") causes a silent KeyError at runtime
    -> The Brain layer has no idea what shape of data the Memory layer expects
    -> Debugging requires reading 3 files to understand what "data" contains

With this schema module:
    -> Every cross-layer data object is a frozen dataclass (immutable after creation)
    -> IDEs provide autocomplete: embedded_paper.paper.title
    -> Type errors are caught at development time, not at 3am in production
    -> The Engineer/Memory boundary is self-documenting

=============================================================================
THE FLOW (Data Transit Path)
=============================================================================

STEP 1: Engineer layer fetches raw API response (dict)
        ↓
STEP 2: Response is validated and packed into PaperMetadata (immutable)
        ↓
STEP 3: Memory layer generates embedding vector for paper.title + paper.abstract
        ↓
STEP 4: Embedding + metadata packed into EmbeddedPaper
        ↓
STEP 5: EmbeddedPaper sent to JarvisMemoryStore.ingest_documents()
        ↓
STEP 6: IngestionStats tracks throughput across the full pipeline run

=============================================================================
"""

from dataclasses import dataclass, field
from typing import List


# =============================================================================
# Part 1: ENGINEER -> MEMORY DATA CONTRACTS
# =============================================================================

@dataclass(frozen=True)
class PaperMetadata:
    """
    LAYER: Engineer (Data Schema) — Immutable research paper descriptor.

    frozen=True means this object cannot be modified after creation.
    This prevents accidental mutation as the object passes through
    the async fetch -> embed -> store pipeline.

    Purpose:
        - Carry the raw structured data extracted from a document source
        - Serve as the input to the embedding step

    How it works:
        - Created once by the fetch layer (engineer.async_net)
        - Read-only as it flows through the Memory layer for embedding and storage
    """
    paper_id: str           # Unique identifier (e.g., arXiv ID or file hash)
    title: str              # Document title
    authors: List[str]      # List of author names
    abstract: str           # Full abstract or summary text
    source_url: str         # Origin URL or file path
    fetch_latency_ms: float # How long the fetch took (for pipeline metrics)


@dataclass
class EmbeddedPaper:
    """
    LAYER: Memory (Embedding Schema) — Paper with its vector representation attached.

    This is the final form before ChromaDB storage.
    The embedding field holds the raw float vector output of the
    all-MiniLM-L6-v2 model (384 floats by default).

    Purpose:
        - Bundle the source metadata and its vector for atomic DB writes
        - Ensure embedding_model and dim are always traceable alongside the vector

    How it works:
        - Created by the embedding step after calling model.encode(text)
        - Passed to JarvisMemoryStore.ingest_documents() for final storage
    """
    paper: PaperMetadata    # The original source metadata (immutable)
    embedding: List[float]  # The 384-dim float vector from the embedding model
    embedding_model: str = "all-MiniLM-L6-v2"  # Which model produced this vector
    embedding_dim: int = 384                     # Sanity-check dimension field


@dataclass
class IngestionStats:
    """
    LAYER: Engineer (Pipeline Metrics) — Mutable counter for a pipeline run.

    Tracks how many objects were fetched, embedded, and stored,
    plus any errors encountered. Passed by reference through the
    pipeline so each stage can update it without return values.

    Purpose:
        - Provide end-of-run observability without adding logging boilerplate
        - Surface error messages for post-run diagnosis

    How it works:
        - Initialized once at pipeline start with all fields = 0
        - Each stage increments its relevant counter
        - Printed as a summary after the pipeline completes
    """
    documents_fetched: int = 0
    documents_embedded: int = 0
    documents_stored: int = 0
    errors: List[str] = field(default_factory=list)  # Default: empty list (not shared)
    total_fetch_ms: float = 0.0
    total_embed_ms: float = 0.0
    total_store_ms: float = 0.0

    def report(self) -> None:
        """Print a formatted pipeline summary to stdout."""
        print("\n" + "=" * 50)
        print("  INGESTION STATS")
        print("=" * 50)
        print(f"  Fetched  : {self.documents_fetched}")
        print(f"  Embedded : {self.documents_embedded}")
        print(f"  Stored   : {self.documents_stored}")
        print(f"  Errors   : {len(self.errors)}")
        print("-" * 50)
        print(f"  Fetch  time : {self.total_fetch_ms:.0f}ms")
        print(f"  Embed  time : {self.total_embed_ms:.0f}ms")
        print(f"  Store  time : {self.total_store_ms:.0f}ms")
        if self.errors:
            print("\n  ERRORS:")
            for e in self.errors:
                print(f"    - {e}")
        print("=" * 50)


# =============================================================================
# MAIN ENTRY POINT (type contract demonstration)
# =============================================================================

if __name__ == "__main__":
    print("=" * 50)
    print("  JARVIS Schema — Type Contract Demo")
    print("=" * 50)

    # Demonstrate frozen immutability
    paper = PaperMetadata(
        paper_id="2401.001",
        title="Attention Is All You Need",
        authors=["Vaswani", "Shazeer"],
        abstract="We propose a new simple network architecture...",
        source_url="https://arxiv.org/abs/1706.03762",
        fetch_latency_ms=142.3,
    )

    embedded = EmbeddedPaper(
        paper=paper,
        embedding=[0.12, -0.34, 0.56] + [0.0] * 381,  # 384-dim placeholder
    )

    stats = IngestionStats(documents_fetched=1, documents_embedded=1, documents_stored=1)

    print(f"  Paper ID     : {paper.paper_id}")
    print(f"  Embed dim    : {len(embedded.embedding)}")
    print(f"  Model        : {embedded.embedding_model}")

    # Demonstrate frozen=True: this will raise FrozenInstanceError
    try:
        paper.title = "Modified Title"  # type: ignore
    except Exception as e:
        print(f"  Mutation blocked: {type(e).__name__} (frozen=True working)")

    stats.report()
    print("  [OK] Schema validated.")
