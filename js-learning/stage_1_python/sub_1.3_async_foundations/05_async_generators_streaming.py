"""
05_async_generators_streaming.py

JARVIS Learning Module: Async Generators and Async Iteration.

Run with:
    python 05_async_generators_streaming.py

This script demonstrates:
    1. async def + yield = async generator
    2. async for = consuming async generators
    3. Streaming data from async sources with constant RAM
    4. Pipeline composition with async generators
    5. Real-world JARVIS ingestion patterns

=============================================================================
THE BIG PICTURE: Streaming + Concurrency
=============================================================================

Phase 2 gave you STREAMING:    yield (constant RAM, lazy evaluation)
Phase 3 gave you CONCURRENCY:  await (non-blocking I/O)

Async generators combine BOTH:
    - yield items one at a time (no RAM explosion)
    - await I/O between items (event loop stays free)

=============================================================================
THE FLOW (Async Generator Pipeline)
=============================================================================

    async def fetch_documents(urls):
        for url in urls:
            data = await httpx.get(url)   ← non-blocking fetch
            yield data.text               ← stream to consumer
                                            (only 1 doc in RAM)

    async for doc in fetch_documents(urls):
        await process(doc)                ← event loop free here too

=============================================================================
"""

import asyncio
import time
from typing import Any, AsyncIterator


# =============================================================================
# Part 1: BASIC ASYNC GENERATOR
# =============================================================================

async def async_counter(limit: int) -> AsyncIterator[int]:
    """
    The simplest async generator.
    
    Uses 'async def' + 'yield' (not return).
    Each iteration can await before yielding.
    """
    for i in range(limit):
        # Simulate async work (e.g., fetching from API)
        await asyncio.sleep(0.05)
        yield i


async def demo_basic_async_generator() -> None:
    """Demonstrate basic async generator usage."""
    print("=" * 60)
    print("DEMO 1: Basic Async Generator")
    print("=" * 60)
    
    # Must use 'async for' to consume an async generator
    print("\n  Consuming with 'async for':")
    async for number in async_counter(5):
        print(f"    Got: {number}")
    
    print()


# =============================================================================
# Part 2: STREAMING FROM ASYNC SOURCES
# =============================================================================

async def fetch_documents(doc_ids: list[str]) -> AsyncIterator[dict[str, Any]]:
    """
    Simulate streaming documents from an async source.
    
    LAYER: Memory (Ingestion Pipeline)
    
    In production, this would:
        - Read files with aiofiles
        - Fetch from APIs with httpx
        - Query databases with asyncpg
    
    Key property: Only ONE document in memory at a time.
    """
    for doc_id in doc_ids:
        # Simulate async I/O (network fetch, disk read, etc.)
        print(f"    [Fetch] Loading {doc_id}...")
        await asyncio.sleep(0.1)  # Simulate I/O latency
        
        document = {
            "id": doc_id,
            "content": f"Content of {doc_id}",
            "size_kb": 512,
        }
        
        yield document
        # After yield, previous document can be garbage collected
        # Only the CURRENT document is in memory


async def demo_streaming() -> None:
    """Demonstrate streaming from async source."""
    print("=" * 60)
    print("DEMO 2: Streaming Documents (Constant RAM)")
    print("=" * 60)
    
    doc_ids = [f"doc_{i:03d}" for i in range(5)]
    
    print(f"\n  Streaming {len(doc_ids)} documents:")
    
    count = 0
    async for doc in fetch_documents(doc_ids):
        count += 1
        print(f"    [Process] {doc['id']} ({doc['size_kb']}KB)")
        # Only 1 document in memory at this point
    
    print(f"\n  Processed {count} documents with constant RAM\n")


# =============================================================================
# Part 3: ASYNC GENERATOR PIPELINE (Composition)
# =============================================================================

async def read_source(sources: list[str]) -> AsyncIterator[str]:
    """
    Stage 1: Read raw data from sources.
    
    LAYER: Memory (Data Ingestion)
    """
    for source in sources:
        print(f"      [Stage 1] Reading: {source}")
        await asyncio.sleep(0.05)
        yield f"raw_content_of_{source}"


async def transform_content(
    raw_stream: AsyncIterator[str],
) -> AsyncIterator[dict[str, str]]:
    """
    Stage 2: Transform raw content into structured documents.
    
    LAYER: Memory (Data Processing)
    
    Takes an async generator as input, yields transformed output.
    This is async generator COMPOSITION — piping one into another.
    """
    async for raw in raw_stream:
        print(f"      [Stage 2] Transforming: {raw[:30]}...")
        await asyncio.sleep(0.03)
        yield {
            "original": raw,
            "processed": raw.upper(),
            "word_count": len(raw.split("_")),
        }


async def embed_and_store(
    doc_stream: AsyncIterator[dict[str, str]],
) -> AsyncIterator[dict[str, Any]]:
    """
    Stage 3: Embed and store in vector database.
    
    LAYER: Memory (Vector Store)
    """
    doc_count = 0
    async for doc in doc_stream:
        doc_count += 1
        print(f"      [Stage 3] Embedding doc #{doc_count}...")
        await asyncio.sleep(0.05)
        yield {
            "doc_id": f"vec_{doc_count:04d}",
            "embedding": [0.1, 0.2, 0.3],  # Mock embedding
            "stored": True,
        }


async def demo_pipeline() -> None:
    """
    Demonstrate async generator pipeline composition.
    
    This is the JARVIS ingestion pipeline pattern:
    Read -> Transform -> Embed -> Store
    
    Each stage is an async generator.
    Data flows through ONE ITEM AT A TIME.
    No stage loads everything into memory.
    """
    print("=" * 60)
    print("DEMO 3: Async Generator Pipeline")
    print("=" * 60)
    
    sources = ["paper_a.pdf", "paper_b.pdf", "paper_c.pdf"]
    
    print(f"\n  Pipeline: Read -> Transform -> Embed")
    print(f"  Sources: {len(sources)} files\n")
    
    start = time.perf_counter()
    
    # Compose the pipeline — each stage wraps the previous
    stage_1 = read_source(sources)
    stage_2 = transform_content(stage_1)
    stage_3 = embed_and_store(stage_2)
    
    # Consume the final stage — drives the entire pipeline
    results = []
    async for result in stage_3:
        results.append(result)
        print(f"      [Done] {result['doc_id']} stored!")
    
    elapsed = time.perf_counter() - start
    print(f"\n  Pipeline complete: {len(results)} docs in {elapsed:.2f}s\n")


# =============================================================================
# Part 4: ASYNC GENERATOR WITH CLEANUP (async finally)
# =============================================================================

async def managed_stream(
    source_name: str,
    item_count: int,
) -> AsyncIterator[str]:
    """
    Async generator with guaranteed cleanup.
    
    The 'try/finally' ensures resources are released
    even if the consumer stops early (break, exception).
    """
    print(f"    [Stream] Opening connection to '{source_name}'")
    
    try:
        for i in range(item_count):
            await asyncio.sleep(0.03)
            yield f"{source_name}_item_{i}"
    finally:
        # This runs even if consumer breaks out early
        print(f"    [Stream] Closing connection to '{source_name}'")


async def demo_cleanup() -> None:
    """Demonstrate async generator cleanup on early exit."""
    print("=" * 60)
    print("DEMO 4: Async Generator Cleanup")
    print("=" * 60)
    
    # Full consumption
    print("\n  Full consumption:")
    async for item in managed_stream("api_v1", 3):
        print(f"      Got: {item}")
    
    # Early exit with break
    print("\n  Early exit (break after 2 items):")
    async for item in managed_stream("api_v2", 10):
        print(f"      Got: {item}")
        if "item_1" in item:
            print("      Breaking early!")
            break  # finally block STILL runs!
    
    print()


# =============================================================================
# Part 5: ASYNC GENERATOR vs ALTERNATIVES
# =============================================================================

async def demo_comparison() -> None:
    """Compare async generators to alternatives."""
    print("=" * 60)
    print("DEMO 5: Why Async Generators Win")
    print("=" * 60)
    
    items = list(range(10))
    
    # APPROACH 1: Collect everything into a list (bad for large data)
    print("\n  Approach 1: Collect all (memory-heavy):")
    start = time.perf_counter()
    
    async def collect_all() -> list[int]:
        results = []
        for item in items:
            await asyncio.sleep(0.02)
            results.append(item * 2)
        return results  # ALL items in memory at once
    
    all_results = await collect_all()
    elapsed = time.perf_counter() - start
    print(f"    {len(all_results)} items, {elapsed:.2f}s, ALL in RAM")
    
    # APPROACH 2: Async generator (memory-efficient)
    print("\n  Approach 2: Async generator (memory-safe):")
    start = time.perf_counter()
    
    async def stream_items() -> AsyncIterator[int]:
        for item in items:
            await asyncio.sleep(0.02)
            yield item * 2  # ONE item at a time
    
    count = 0
    async for result in stream_items():
        count += 1
    elapsed = time.perf_counter() - start
    print(f"    {count} items, {elapsed:.2f}s, 1 in RAM at a time")
    
    print()


# =============================================================================
# Part 6: COMMON MISTAKES
# =============================================================================

async def demo_mistakes() -> None:
    """Show common mistakes with async generators."""
    print("=" * 60)
    print("DEMO 6: Common Mistakes")
    print("=" * 60)
    
    print("""
    # [X] MISTAKE 1: Using 'for' instead of 'async for'
    
    async def gen():
        yield 1
    
    for item in gen():     # TypeError! Must use async for
        print(item)
    
    # [OK] FIX:
    async for item in gen():
        print(item)
    
    
    # ---------------------------------------------------------
    
    # [X] MISTAKE 2: Using 'yield' in a regular function for async data
    
    def bad_generator():
        data = await fetch()  # SyntaxError! Can't await in def
        yield data
    
    # [OK] FIX: Use async def
    
    async def good_generator():
        data = await fetch()  # Works in async def
        yield data
    
    
    # ---------------------------------------------------------
    
    # [X] MISTAKE 3: Collecting async generator into a list
    
    async def stream():
        for i in range(1_000_000):
            yield i
    
    all_items = [item async for item in stream()]  # 1M items in RAM!
    
    # [OK] FIX: Process one at a time
    
    async for item in stream():
        process(item)  # Only 1 item in RAM
    
    
    # ---------------------------------------------------------
    
    # [OK] MISTAKE 4 (Fixed): Forgetting cleanup in async generators
    
    async def leaky_stream():
        conn = await connect_db()
        try:
            async for row in conn.fetch_all():
                yield row
        finally:
            await conn.close()  # Ensures cleanup
    
    # [OK] FIX: Use try/finally
    
    async def safe_stream():
        conn = await connect_db()
        try:
            async for row in conn.fetch_all():
                yield row
        finally:
            await conn.close()  # Always runs, even on break
    """)


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

async def main() -> None:
    """Main entry point."""
    await demo_basic_async_generator()
    await demo_streaming()
    await demo_pipeline()
    await demo_cleanup()
    await demo_comparison()
    await demo_mistakes()
    
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("""
    EVOLUTION OF DATA HANDLING IN JARVIS:
    
    Phase 2 (sync generators):
        def gen():  yield item  ->  for x in gen()
        Streaming: YES | Non-blocking: NO
    
    Phase 3 (async generators):
        async def gen():  yield item  ->  async for x in gen()
        Streaming: YES | Non-blocking: YES
    
    | Pattern              | Use When                           |
    |----------------------|------------------------------------|
    | async def + yield    | Stream data from async I/O sources |
    | async for            | Consume async generators           |
    | Pipeline composition | Chain async generators together    |
    | try/finally in gen   | Guarantee cleanup on early exit    |
    
    JARVIS INGESTION PIPELINE:
    +----------+   +-----------+   +---------+   +-------+
    | Read     |-->| Transform |-->| Embed   |-->| Store |
    | (async   |   | (async    |   | (async  |   |       |
    |  yield)  |   |  yield)   |   |  yield) |   |       |
    +----------+   +-----------+   +---------+   +-------+
    One document flows through at a time. Constant RAM.
    Event loop free between each step. JARVIS stays responsive.
    
    THIS COMPLETES PHASE 3: ASYNC FOUNDATIONS
    """)


if __name__ == "__main__":
    asyncio.run(main())
