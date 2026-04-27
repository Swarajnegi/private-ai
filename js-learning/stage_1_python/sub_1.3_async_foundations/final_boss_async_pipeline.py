"""
final_boss_async_pipeline.py

JARVIS Phase 3 Final Boss: Async Research Paper Ingestion Pipeline.

Run with:
    python final_boss_async_pipeline.py

=============================================================================
USE CASE: JARVIS Research Paper Ingestion
=============================================================================

You tell JARVIS: "Ingest the latest 10 AI research papers."

JARVIS needs to:
    1. Fetch metadata for 10 papers from API endpoints (concurrently)
    2. Extract title, abstract, and authors from each response
    3. Generate an embedding vector for each paper's content
    4. Store the embedding + metadata in a vector database
    5. Do ALL of this without blocking, with rate limiting, and with
       guaranteed cleanup of every resource

THE 10 URLs (Simulated arXiv-like API):
    Papers cover core JARVIS-relevant topics:
    - Attention mechanisms, transformers, RAG, embeddings, agent loops,
      tool use, reinforcement learning, memory systems, multimodal AI,
      and chain-of-thought reasoning

=============================================================================
ARCHITECTURE (Every Phase 3 Concept Used)
=============================================================================

    asyncio.run(main())              <-- Lesson 3.3: Single entry point
            |
            v
    async with HttpSession()         <-- Lesson 3.4: Async context manager
    async with VectorDB()            <-- Lesson 3.4: Async context manager
            |
            v
    Semaphore(3) rate limiter        <-- Concurrency control
            |
            v
    gather(fetch, fetch, fetch...)   <-- Lesson 3.1: Parallel execution
            |
            v
    async def stream_results()       <-- Lesson 3.5: Async generator
        yield paper                  <-- Lesson 3.5: Streaming results
            |
            v
    async for paper in stream:       <-- Lesson 3.5: Async iteration
        embed(paper)
        store(paper)
            |
            v
    try/finally cleanup              <-- Lesson 3.4: Guaranteed teardown

=============================================================================
DATA FLOW
=============================================================================

    [10 Paper URLs]
          |
          | asyncio.gather() with Semaphore(3)
          | (max 3 concurrent fetches)
          v
    [Raw API Responses]
          |
          | parse_paper_response()
          v
    [Structured Paper Objects]
          |
          | async generator yields one at a time
          v
    [Embedding Generation]
          |
          | simulate 384-dim vector per paper
          v
    [Vector DB Storage]
          |
          | async with db.session()
          v
    [Ingestion Complete - Stats Printed]

=============================================================================
"""

import asyncio
import hashlib
import random
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional


# =============================================================================
# PART 1: DATA MODELS (Type Safety)
# =============================================================================

@dataclass(frozen=True)
class PaperMetadata:
    """
    Immutable container for a research paper's metadata.

    LAYER: Memory (Data Schema)

    frozen=True prevents accidental mutation after creation.
    Every paper flowing through the pipeline is this type.
    """
    paper_id: str
    title: str
    authors: list[str]
    abstract: str
    source_url: str
    fetch_latency_ms: float


@dataclass
class EmbeddedPaper:
    """
    A paper with its embedding vector attached.

    LAYER: Memory (Embedding Schema)

    This is what gets stored in the vector database.
    The embedding is a 384-dimensional float vector
    (matching sentence-transformers/all-MiniLM-L6-v2 output).
    """
    paper: PaperMetadata
    embedding: list[float]
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dim: int = 384


@dataclass
class IngestionStats:
    """Tracks pipeline performance metrics."""
    papers_fetched: int = 0
    papers_embedded: int = 0
    papers_stored: int = 0
    errors: list[str] = field(default_factory=list)
    total_fetch_time_ms: float = 0.0
    total_embed_time_ms: float = 0.0
    total_store_time_ms: float = 0.0


# =============================================================================
# PART 2: SIMULATED PAPER DATABASE
# =============================================================================

# These simulate real arXiv API responses.
# In production, these would be actual HTTP endpoints.

PAPER_ENDPOINTS: list[dict[str, Any]] = [
    {
        "url": "https://api.arxiv.org/papers/2401.001",
        "paper_id": "2401.001",
        "title": "Attention Is All You Need: Revisited",
        "authors": ["A. Vaswani", "N. Shazeer", "J. Uszkoreit"],
        "abstract": (
            "We revisit the transformer architecture and propose efficiency "
            "improvements that reduce compute by 40% while maintaining accuracy "
            "on standard NLP benchmarks."
        ),
    },
    {
        "url": "https://api.arxiv.org/papers/2401.002",
        "paper_id": "2401.002",
        "title": "Retrieval-Augmented Generation for Knowledge-Intensive Tasks",
        "authors": ["P. Lewis", "E. Perez", "A. Piktus"],
        "abstract": (
            "We combine pre-trained language models with a dense retrieval "
            "component to ground generation in external knowledge, reducing "
            "hallucination by 60% on open-domain QA."
        ),
    },
    {
        "url": "https://api.arxiv.org/papers/2401.003",
        "paper_id": "2401.003",
        "title": "Sentence-BERT: Sentence Embeddings using Siamese Networks",
        "authors": ["N. Reimers", "I. Gurevych"],
        "abstract": (
            "We present a modification of BERT that produces semantically "
            "meaningful sentence embeddings for efficient cosine-similarity "
            "search in vector databases."
        ),
    },
    {
        "url": "https://api.arxiv.org/papers/2401.004",
        "paper_id": "2401.004",
        "title": "ReAct: Synergizing Reasoning and Acting in Language Models",
        "authors": ["S. Yao", "J. Zhao", "D. Yu"],
        "abstract": (
            "We propose ReAct, a framework where LLMs interleave reasoning "
            "traces with task-specific actions, enabling robust decision making "
            "in interactive environments."
        ),
    },
    {
        "url": "https://api.arxiv.org/papers/2401.005",
        "paper_id": "2401.005",
        "title": "Tool Use in Large Language Models: A Survey",
        "authors": ["T. Schick", "J. Dwivedi-Yu", "R. Dessi"],
        "abstract": (
            "We survey methods for augmenting LLMs with external tools "
            "including calculators, search engines, and code interpreters, "
            "finding that tool use improves factual accuracy by 35%."
        ),
    },
    {
        "url": "https://api.arxiv.org/papers/2401.006",
        "paper_id": "2401.006",
        "title": "Proximal Policy Optimization for RLHF",
        "authors": ["J. Schulman", "F. Wolski", "P. Dhariwal"],
        "abstract": (
            "We present PPO applied to reinforcement learning from human "
            "feedback, showing stable training dynamics that align model "
            "outputs with human preferences."
        ),
    },
    {
        "url": "https://api.arxiv.org/papers/2401.007",
        "paper_id": "2401.007",
        "title": "MemGPT: Towards LLMs as Operating Systems",
        "authors": ["C. Packer", "S. Wooders", "K. Lin"],
        "abstract": (
            "We propose MemGPT, a system that manages virtual context using "
            "hierarchical memory tiers, enabling LLMs to handle unbounded "
            "conversation histories."
        ),
    },
    {
        "url": "https://api.arxiv.org/papers/2401.008",
        "paper_id": "2401.008",
        "title": "LLaVA: Visual Instruction Tuning for Multimodal Models",
        "authors": ["H. Liu", "C. Li", "Q. Wu"],
        "abstract": (
            "We present Large Language and Vision Assistant, connecting a "
            "vision encoder with an LLM for general-purpose visual and "
            "language understanding."
        ),
    },
    {
        "url": "https://api.arxiv.org/papers/2401.009",
        "paper_id": "2401.009",
        "title": "Chain-of-Thought Prompting Elicits Reasoning",
        "authors": ["J. Wei", "X. Wang", "D. Schuurmans"],
        "abstract": (
            "We show that generating intermediate reasoning steps before the "
            "final answer dramatically improves LLM performance on arithmetic, "
            "commonsense, and symbolic reasoning tasks."
        ),
    },
    {
        "url": "https://api.arxiv.org/papers/2401.010",
        "paper_id": "2401.010",
        "title": "ChromaDB: Open-Source Embedding Database",
        "authors": ["J. Trein", "A. Athalye", "L. Van Ness"],
        "abstract": (
            "We present Chroma, an open-source embedding database designed "
            "for AI applications. It provides fast similarity search with "
            "automatic embedding management and metadata filtering."
        ),
    },
]


# =============================================================================
# PART 3: ASYNC HTTP SESSION (async with)
# =============================================================================

class AsyncHttpSession:
    """
    Simulated async HTTP client session.

    LAYER: Engineer (Network I/O)

    In production, replace with:
        import httpx
        async with httpx.AsyncClient() as session:
            response = await session.get(url)

    This class demonstrates the async context manager protocol
    (__aenter__ / __aexit__) for resource lifecycle management.
    """

    def __init__(self, base_timeout_ms: int = 5000) -> None:
        self._timeout_ms = base_timeout_ms
        self._active = False
        self._request_count = 0

    async def __aenter__(self) -> "AsyncHttpSession":
        """Open the HTTP connection pool."""
        print("  [HTTP] Opening connection pool...")
        await asyncio.sleep(0.05)  # Simulate TCP handshake
        self._active = True
        print("  [HTTP] Connection pool ready.")
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> bool:
        """
        Close the connection pool.
        Guaranteed to run even if exceptions occur inside the block.
        """
        if exc_type is not None:
            print(f"  [HTTP] Error during session: {exc_type.__name__}")
        print(
            f"  [HTTP] Closing connection pool "
            f"({self._request_count} requests served)."
        )
        await asyncio.sleep(0.03)  # Simulate graceful shutdown
        self._active = False
        return False  # Don't suppress exceptions

    async def get(self, url: str) -> dict[str, Any]:
        """
        Simulate an async HTTP GET request.

        In production: response = await self._client.get(url)
        """
        if not self._active:
            raise RuntimeError("Session not open. Use 'async with'.")

        self._request_count += 1

        # Simulate variable network latency (50-300ms)
        latency_ms = random.uniform(50, 300)
        await asyncio.sleep(latency_ms / 1000)

        # Find the matching paper from our simulated database
        for paper in PAPER_ENDPOINTS:
            if paper["url"] == url:
                return {
                    "status": 200,
                    "latency_ms": latency_ms,
                    "data": paper,
                }

        return {"status": 404, "latency_ms": latency_ms, "data": None}


# =============================================================================
# PART 4: ASYNC VECTOR DATABASE (async with)
# =============================================================================

class AsyncVectorDB:
    """
    Simulated async vector database client.

    LAYER: Memory (Vector Store)

    In production, replace with:
        import chromadb
        client = chromadb.AsyncClient()
        collection = await client.get_or_create_collection("papers")

    Demonstrates async context manager for database lifecycle.
    """

    def __init__(self, collection_name: str) -> None:
        self._collection = collection_name
        self._connected = False
        self._stored_count = 0
        self._store: list[dict[str, Any]] = []

    async def __aenter__(self) -> "AsyncVectorDB":
        """Connect to the vector database."""
        print(f"  [VectorDB] Connecting to collection '{self._collection}'...")
        await asyncio.sleep(0.08)  # Simulate DB connection
        self._connected = True
        print(f"  [VectorDB] Connected.")
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> bool:
        """Disconnect from the database, flush pending writes."""
        if self._connected:
            print(
                f"  [VectorDB] Flushing and disconnecting "
                f"({self._stored_count} documents stored)."
            )
            await asyncio.sleep(0.05)  # Simulate flush
            self._connected = False
        return False

    async def upsert(
        self,
        doc_id: str,
        embedding: list[float],
        metadata: dict[str, Any],
    ) -> bool:
        """
        Store an embedding with metadata in the vector database.

        In production:
            await collection.upsert(
                ids=[doc_id],
                embeddings=[embedding],
                metadatas=[metadata],
            )
        """
        if not self._connected:
            raise RuntimeError("Not connected. Use 'async with'.")

        await asyncio.sleep(random.uniform(0.02, 0.08))  # Simulate write
        self._stored_count += 1
        self._store.append({
            "id": doc_id,
            "embedding_dim": len(embedding),
            "metadata": metadata,
        })
        return True

    def get_stats(self) -> dict[str, int]:
        """Return storage statistics."""
        return {
            "total_stored": self._stored_count,
            "collection": self._collection,
        }


# =============================================================================
# PART 5: EMBEDDING SERVICE (Simulated)
# =============================================================================

async def generate_embedding(text: str, dim: int = 384) -> list[float]:
    """
    Simulate generating a text embedding vector.

    LAYER: Memory (Embedding Generation)

    In production, replace with:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2")
        embedding = model.encode(text)

    Or async via:
        embedding = await asyncio.to_thread(model.encode, text)

    We simulate the ~50ms inference time and produce a
    deterministic pseudo-random vector based on text hash.
    """
    await asyncio.sleep(random.uniform(0.03, 0.08))  # Simulate inference

    # Produce deterministic "embedding" from text hash
    # (real embeddings capture semantic meaning; this is structural only)
    seed = int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    return [rng.uniform(-1.0, 1.0) for _ in range(dim)]


# =============================================================================
# PART 6: CORE PIPELINE (The Integration Layer)
# =============================================================================

async def fetch_paper(
    session: AsyncHttpSession,
    url: str,
    semaphore: asyncio.Semaphore,
) -> Optional[PaperMetadata]:
    """
    Fetch a single paper's metadata from the API.

    Uses a semaphore to limit concurrent requests.
    This prevents overwhelming the API with all 10 requests at once.
    """
    async with semaphore:
        # Semaphore limits how many fetches run simultaneously
        try:
            response = await session.get(url)

            if response["status"] != 200:
                print(f"    [Fetch] FAILED: {url} (HTTP {response['status']})")
                return None

            data = response["data"]
            paper = PaperMetadata(
                paper_id=data["paper_id"],
                title=data["title"],
                authors=data["authors"],
                abstract=data["abstract"],
                source_url=url,
                fetch_latency_ms=response["latency_ms"],
            )
            print(
                f"    [Fetch] OK: {paper.paper_id} "
                f"({paper.fetch_latency_ms:.0f}ms) "
                f"- {paper.title[:50]}..."
            )
            return paper

        except Exception as e:
            print(f"    [Fetch] ERROR: {url} - {e}")
            return None


async def fetch_all_papers(
    session: AsyncHttpSession,
    urls: list[str],
    max_concurrent: int = 3,
) -> list[PaperMetadata]:
    """
    Fetch all papers concurrently with rate limiting.

    LAYER: Engineer (Parallel I/O)

    asyncio.gather() fires all fetches simultaneously.
    The semaphore limits to max_concurrent active requests.

    With 10 URLs and semaphore(3):
        Batch 1: URLs 0, 1, 2 (concurrent)
        Batch 2: URLs 3, 4, 5 (as slots free up)
        Batch 3: URLs 6, 7, 8 (as slots free up)
        Batch 4: URL 9 (last one)
    """
    semaphore = asyncio.Semaphore(max_concurrent)

    print(f"\n  [Pipeline] Fetching {len(urls)} papers "
          f"(max {max_concurrent} concurrent)...\n")

    # gather() runs ALL fetch_paper calls concurrently
    # The semaphore inside each call controls actual parallelism
    results = await asyncio.gather(
        *(fetch_paper(session, url, semaphore) for url in urls)
    )

    # Filter out None (failed fetches)
    return [paper for paper in results if paper is not None]


async def stream_embedded_papers(
    papers: list[PaperMetadata],
) -> AsyncIterator[EmbeddedPaper]:
    """
    Async generator that yields papers with embeddings one at a time.

    LAYER: Memory (Embedding Pipeline)

    Only ONE paper + embedding is in memory at any time.
    After yield, the previous paper can be garbage collected.

    This is the bridge between fetch (batch) and store (streaming).
    """
    for paper in papers:
        # Generate embedding for the paper's content
        text_to_embed = f"{paper.title} {paper.abstract}"
        start = time.perf_counter()
        embedding = await generate_embedding(text_to_embed)
        embed_ms = (time.perf_counter() - start) * 1000

        embedded = EmbeddedPaper(
            paper=paper,
            embedding=embedding,
        )

        print(
            f"    [Embed] {paper.paper_id}: "
            f"{len(embedding)}-dim vector ({embed_ms:.0f}ms)"
        )

        yield embedded
        # Previous EmbeddedPaper can be garbage collected here


async def ingest_papers(
    db: AsyncVectorDB,
    paper_stream: AsyncIterator[EmbeddedPaper],
    stats: IngestionStats,
) -> None:
    """
    Consume the embedding stream and store each paper in the vector DB.

    LAYER: Memory (Storage)

    Uses 'async for' to pull from the async generator.
    Each paper is stored immediately after embedding --
    no need to wait for all embeddings to complete.
    """
    async for embedded in paper_stream:
        start = time.perf_counter()

        # Store in vector database
        success = await db.upsert(
            doc_id=embedded.paper.paper_id,
            embedding=embedded.embedding,
            metadata={
                "title": embedded.paper.title,
                "authors": ", ".join(embedded.paper.authors),
                "abstract": embedded.paper.abstract[:200],
                "source": embedded.paper.source_url,
                "embedding_model": embedded.embedding_model,
            },
        )

        store_ms = (time.perf_counter() - start) * 1000

        if success:
            stats.papers_stored += 1
            stats.total_store_time_ms += store_ms
            print(
                f"    [Store] {embedded.paper.paper_id}: "
                f"saved to '{db._collection}' ({store_ms:.0f}ms)"
            )
        else:
            stats.errors.append(
                f"Failed to store {embedded.paper.paper_id}"
            )


# =============================================================================
# PART 7: MAIN ORCHESTRATOR
# =============================================================================

async def jarvis_research_ingest() -> IngestionStats:
    """
    Main orchestrator for the research paper ingestion pipeline.

    LAYER: Brain (Orchestrator)

    This function demonstrates EVERY Phase 3 concept working together:
        1. async with    -> HTTP session + VectorDB lifecycle
        2. gather()      -> Concurrent fetching with semaphore
        3. async def     -> Non-blocking I/O throughout
        4. yield         -> Streaming embeddings one at a time
        5. async for     -> Consuming the embedding stream
        6. try/finally   -> Guaranteed cleanup of all resources
    """
    stats = IngestionStats()
    urls = [paper["url"] for paper in PAPER_ENDPOINTS]

    print("=" * 65)
    print("  JARVIS Research Paper Ingestion Pipeline")
    print("=" * 65)
    print(f"  Papers to ingest: {len(urls)}")
    print(f"  Embedding model:  all-MiniLM-L6-v2 (384-dim)")
    print(f"  Vector store:     jarvis_research_papers")
    print(f"  Rate limit:       3 concurrent fetches")
    print("=" * 65)

    pipeline_start = time.perf_counter()

    # NESTED ASYNC CONTEXT MANAGERS (Lesson 3.4)
    # Both resources are guaranteed to clean up, even on crash
    async with AsyncHttpSession() as session:
        async with AsyncVectorDB("jarvis_research_papers") as db:

            # PHASE A: Fetch all papers concurrently (Lesson 3.1 + 3.3)
            fetch_start = time.perf_counter()
            papers = await fetch_all_papers(session, urls, max_concurrent=3)
            fetch_time = (time.perf_counter() - fetch_start) * 1000

            stats.papers_fetched = len(papers)
            stats.total_fetch_time_ms = fetch_time

            print(f"\n  [Pipeline] Fetched {len(papers)}/{len(urls)} papers "
                  f"in {fetch_time:.0f}ms\n")

            if not papers:
                print("  [Pipeline] No papers fetched. Aborting.")
                return stats

            # PHASE B: Stream embeddings + store (Lesson 3.5)
            print("  [Pipeline] Embedding and storing...\n")
            embed_start = time.perf_counter()

            # Create the async generator (doesn't run yet)
            embedding_stream = stream_embedded_papers(papers)

            # Consume the stream -- each paper is embedded then stored
            # Only 1 paper in memory at a time during this phase
            try:
                await ingest_papers(db, embedding_stream, stats)
            finally:
                # Ensure the async generator is properly closed
                await embedding_stream.aclose()

            embed_time = (time.perf_counter() - embed_start) * 1000
            stats.total_embed_time_ms = embed_time
            stats.papers_embedded = stats.papers_stored

            # PHASE C: Report results
            db_stats = db.get_stats()

    # Both session and db are now closed (exited async with blocks)
    pipeline_time = (time.perf_counter() - pipeline_start) * 1000

    print()
    print("=" * 65)
    print("  INGESTION COMPLETE")
    print("=" * 65)
    print(f"  Papers fetched:    {stats.papers_fetched}/{len(urls)}")
    print(f"  Papers embedded:   {stats.papers_embedded}")
    print(f"  Papers stored:     {stats.papers_stored}")
    print(f"  Errors:            {len(stats.errors)}")
    print("-" * 65)
    print(f"  Fetch time:        {stats.total_fetch_time_ms:.0f}ms "
          f"(concurrent, 3 at a time)")
    print(f"  Embed+Store time:  {stats.total_embed_time_ms:.0f}ms "
          f"(streamed, 1 at a time)")
    print(f"  Total pipeline:    {pipeline_time:.0f}ms")
    print("-" * 65)
    print(f"  DB collection:     {db_stats['collection']}")
    print(f"  DB total docs:     {db_stats['total_stored']}")
    print("=" * 65)

    if stats.errors:
        print("\n  ERRORS:")
        for error in stats.errors:
            print(f"    - {error}")

    return stats


# =============================================================================
# ENTRY POINT (asyncio.run called ONCE)
# =============================================================================

if __name__ == "__main__":
    # asyncio.run() is the SINGLE bridge from sync to async world.
    # It creates the event loop, runs the orchestrator, cleans up, closes loop.
    # Called exactly ONCE. Everything else uses await.

    stats = asyncio.run(jarvis_research_ingest())

    # Back in sync world. Process can exit.
    print(f"\n  [Sync] Pipeline returned {stats.papers_stored} papers.")
    print("  [Sync] Process exiting.")
