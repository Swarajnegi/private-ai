"""
final_boss_v2_sync_vs_async.py

JARVIS Phase 3 Final Boss v2: Real PDF Pipeline -- Sync vs Async Comparison.

Run with:
    python final_boss_v2_sync_vs_async.py

=============================================================================
USE CASE
=============================================================================

You tell JARVIS: "Ingest my 11 research papers and summarize them."

This script reads REAL PDF files from disk, extracts text, generates a
summary for each paper, simulates embedding generation, and writes a
combined summary .txt file.

It runs the ENTIRE pipeline TWICE:
    1. SYNC  -- context managers, generators, yield (Phase 2 patterns)
    2. ASYNC -- async with, async generators, async for (Phase 3 patterns)

Then it prints a head-to-head comparison of time and memory usage.

=============================================================================
THE 11 PAPERS
=============================================================================

| arXiv ID        | Paper                                          |
|-----------------|------------------------------------------------|
| 1603.09320v4    | Deep Networks with Stochastic Depth             |
| 1706.03762v7    | Attention Is All You Need                        |
| 1707.06347v2    | Proximal Policy Optimization                     |
| 1908.10084v1    | Sentence-BERT                                    |
| 1909.08593v2    | BART: Denoising Sequence-to-Sequence Pretraining |
| 2005.11401v4    | RAG for Knowledge-Intensive Tasks                |
| 2201.11903v6    | Chain-of-Thought Prompting                       |
| 2210.03629v3    | ReAct: Synergizing Reasoning and Acting          |
| 2302.04761v1    | Toolformer                                       |
| 2304.08485v2    | LLaVA: Visual Instruction Tuning                 |
| 2310.08560v2    | MemGPT: LLMs as Operating Systems                |

=============================================================================
ARCHITECTURE
=============================================================================

    SYNC PIPELINE (Phase 2 patterns):
    
    for paper in sync_extract_papers(pdf_paths):    <-- generator + yield
        with open(file) as f:                       <-- context manager
            text = extract_text(f)
        summary = summarize(text)
        embedding = generate_embedding(text)        <-- simulated (blocking)
        write_to_output(summary)


    ASYNC PIPELINE (Phase 3 patterns):

    async for paper in async_extract_papers(paths): <-- async generator
        async with aiofiles.open(file) as f:        <-- async context mgr
            text = await extract_text(f)
        summary = summarize(text)
        embedding = await generate_embedding(text)  <-- simulated (non-blocking)
        await write_to_output(summary)

=============================================================================
"""

import asyncio
import hashlib
import os
import random
import time
import tracemalloc
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Generator, Iterator, Optional

import aiofiles
import fitz  # PyMuPDF


# =============================================================================
# CONFIGURATION
# =============================================================================

PAPERS_DIR = Path(r"e:\Jarvis\For Jarvis\Research Papers")
OUTPUT_DIR = Path(r"e:\Jarvis\js-learning\stage_1_python\sub_1.3_async_foundations")
SYNC_OUTPUT = OUTPUT_DIR / "sync_paper_summaries.txt"
ASYNC_OUTPUT = OUTPUT_DIR / "async_paper_summaries.txt"

# Simulated embedding parameters
EMBEDDING_DIM = 384
EMBED_LATENCY_SEC = 0.15  # Simulates real model inference time


# =============================================================================
# PART 1: DATA MODELS
# =============================================================================

@dataclass
class PaperSummary:
    """
    Structured summary of a single research paper.

    LAYER: Memory (Data Schema)
    """
    filename: str
    title: str
    page_count: int
    word_count: int
    abstract_snippet: str
    embedding: list[float] = field(default_factory=list)
    extract_time_ms: float = 0.0
    embed_time_ms: float = 0.0


@dataclass
class PipelineStats:
    """Performance metrics for a pipeline run."""
    pipeline_name: str
    papers_processed: int = 0
    total_wall_time_ms: float = 0.0
    total_extract_time_ms: float = 0.0
    total_embed_time_ms: float = 0.0
    total_write_time_ms: float = 0.0
    peak_memory_kb: float = 0.0
    errors: list[str] = field(default_factory=list)


# =============================================================================
# PART 2: SHARED UTILITIES (Used by both pipelines)
# =============================================================================

def extract_text_from_pdf(pdf_path: Path) -> tuple[str, int]:
    """
    Extract all text from a PDF using PyMuPDF.

    LAYER: Engineer (File I/O)

    PyMuPDF (fitz) is the fastest Python PDF library.
    Returns (full_text, page_count).
    """
    text_parts: list[str] = []
    page_count = 0

    # fitz.open is a context manager -- guaranteed to close the PDF
    with fitz.open(str(pdf_path)) as doc:
        page_count = len(doc)
        for page in doc:
            text_parts.append(page.get_text())

    return "\n".join(text_parts), page_count


def build_summary(
    filename: str,
    full_text: str,
    page_count: int,
) -> PaperSummary:
    """
    Build a structured summary from extracted text.

    LAYER: Memory (Data Processing)

    Extracts the title (first non-empty line) and an abstract snippet
    (first ~500 words after any "Abstract" heading).
    """
    lines = full_text.strip().split("\n")

    # Title: first non-empty line
    title = "Unknown Title"
    for line in lines:
        cleaned = line.strip()
        if len(cleaned) > 5:
            title = cleaned
            break

    # Abstract: find "Abstract" section or use first 500 words
    abstract_snippet = ""
    full_lower = full_text.lower()
    abs_idx = full_lower.find("abstract")

    if abs_idx != -1:
        # Found an abstract heading -- take the next ~500 words
        after_abs = full_text[abs_idx + len("abstract"):].strip()
        words = after_abs.split()[:500]
        abstract_snippet = " ".join(words)
    else:
        # No explicit abstract -- use first 500 words
        words = full_text.split()[:500]
        abstract_snippet = " ".join(words)

    # Clean up the abstract snippet (remove excessive whitespace)
    abstract_snippet = " ".join(abstract_snippet.split())
    if len(abstract_snippet) > 2000:
        abstract_snippet = abstract_snippet[:2000] + "..."

    word_count = len(full_text.split())

    return PaperSummary(
        filename=filename,
        title=title,
        page_count=page_count,
        word_count=word_count,
        abstract_snippet=abstract_snippet,
    )


def generate_embedding_sync(text: str, dim: int = EMBEDDING_DIM) -> list[float]:
    """
    Simulate generating a text embedding (BLOCKING).

    LAYER: Memory (Embedding)

    In production: model.encode(text) -- runs on GPU, takes ~50-200ms.
    We simulate the latency to demonstrate why async matters.
    """
    time.sleep(EMBED_LATENCY_SEC)  # BLOCKS the thread!

    seed = int(hashlib.sha256(text[:500].encode("utf-8", errors="ignore")).hexdigest()[:8], 16)
    rng = random.Random(seed)
    return [round(rng.uniform(-1.0, 1.0), 4) for _ in range(dim)]


async def generate_embedding_async(text: str, dim: int = EMBEDDING_DIM) -> list[float]:
    """
    Simulate generating a text embedding (NON-BLOCKING).

    LAYER: Memory (Embedding)

    In production: await asyncio.to_thread(model.encode, text)
    The event loop stays free while "inference" runs.
    """
    await asyncio.sleep(EMBED_LATENCY_SEC)  # Does NOT block the loop

    seed = int(hashlib.sha256(text[:500].encode("utf-8", errors="ignore")).hexdigest()[:8], 16)
    rng = random.Random(seed)
    return [round(rng.uniform(-1.0, 1.0), 4) for _ in range(dim)]


def format_summary_text(summary: PaperSummary, index: int) -> str:
    """Format a single paper summary for the output .txt file."""
    separator = "=" * 70
    return (
        f"{separator}\n"
        f"  Paper {index}: {summary.filename}\n"
        f"{separator}\n"
        f"  Title:      {summary.title}\n"
        f"  Pages:      {summary.page_count}\n"
        f"  Words:      {summary.word_count:,}\n"
        f"  Embed dim:  {len(summary.embedding)}\n"
        f"  Extract:    {summary.extract_time_ms:.0f}ms\n"
        f"  Embed:      {summary.embed_time_ms:.0f}ms\n"
        f"\n"
        f"  ABSTRACT SNIPPET:\n"
        f"  {summary.abstract_snippet[:800]}\n"
        f"\n"
    )


# =============================================================================
# PART 3: SYNC PIPELINE (Phase 2 Patterns)
# =============================================================================
#
# Uses:
#   - Context managers (with) for file handles
#   - Generators (yield) for lazy paper streaming
#   - Sequential blocking I/O
#
# =============================================================================

def sync_extract_papers(pdf_paths: list[Path]) -> Generator[PaperSummary, None, None]:
    """
    Generator that yields paper summaries one at a time.

    LAYER: Memory (Sync Ingestion Pipeline)

    This is a GENERATOR -- only one paper in memory at a time.
    Each yield lets the caller process and discard before loading the next.
    But ALL I/O is BLOCKING -- each PDF blocks until fully read.
    """
    for path in pdf_paths:
        start = time.perf_counter()
        try:
            full_text, page_count = extract_text_from_pdf(path)
            extract_ms = (time.perf_counter() - start) * 1000

            summary = build_summary(path.name, full_text, page_count)
            summary.extract_time_ms = extract_ms

            print(f"    [Sync Extract] {path.name}: "
                  f"{page_count} pages, {summary.word_count:,} words "
                  f"({extract_ms:.0f}ms)")

            yield summary

        except Exception as e:
            print(f"    [Sync Extract] ERROR on {path.name}: {e}")


def run_sync_pipeline(pdf_paths: list[Path]) -> PipelineStats:
    """
    Run the complete SYNC pipeline.

    Flow:
        Generator yields papers --> embed each (blocking) --> write to file

    Every step blocks the thread. Nothing runs in parallel.
    """
    stats = PipelineStats(pipeline_name="SYNC")

    print("\n" + "=" * 70)
    print("  SYNC PIPELINE")
    print("=" * 70)

    tracemalloc.start()
    wall_start = time.perf_counter()

    # Open output file with context manager (guaranteed close)
    with open(SYNC_OUTPUT, "w", encoding="utf-8") as outfile:
        outfile.write("JARVIS Research Paper Summaries (SYNC Pipeline)\n")
        outfile.write(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        outfile.write("=" * 70 + "\n\n")

        index = 0

        # Generator streams papers one at a time
        for summary in sync_extract_papers(pdf_paths):
            index += 1
            stats.total_extract_time_ms += summary.extract_time_ms

            # Blocking embedding
            embed_start = time.perf_counter()
            summary.embedding = generate_embedding_sync(
                summary.abstract_snippet
            )
            embed_ms = (time.perf_counter() - embed_start) * 1000
            summary.embed_time_ms = embed_ms
            stats.total_embed_time_ms += embed_ms

            print(f"    [Sync Embed]   {summary.filename}: "
                  f"{len(summary.embedding)}-dim ({embed_ms:.0f}ms)")

            # Write summary to output file
            write_start = time.perf_counter()
            outfile.write(format_summary_text(summary, index))
            write_ms = (time.perf_counter() - write_start) * 1000
            stats.total_write_time_ms += write_ms

            stats.papers_processed += 1

        outfile.write(f"\nTotal papers: {index}\n")

    # Capture memory stats
    _, peak_memory = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    stats.total_wall_time_ms = (time.perf_counter() - wall_start) * 1000
    stats.peak_memory_kb = peak_memory / 1024

    print(f"\n  [Sync] Complete: {stats.papers_processed} papers, "
          f"{stats.total_wall_time_ms:.0f}ms total")
    print(f"  [Sync] Output: {SYNC_OUTPUT.name}")

    return stats


# =============================================================================
# PART 4: ASYNC PIPELINE (Phase 3 Patterns)
# =============================================================================
#
# Uses:
#   - async with for file handles (aiofiles)
#   - async generators (async def + yield) for lazy paper streaming
#   - async for to consume the stream
#   - asyncio.gather() for concurrent embedding
#   - Non-blocking I/O throughout
#
# =============================================================================

async def async_extract_papers(
    pdf_paths: list[Path],
) -> AsyncIterator[PaperSummary]:
    """
    Async generator that yields paper summaries one at a time.

    LAYER: Memory (Async Ingestion Pipeline)

    PDF text extraction (fitz) is CPU-bound and runs synchronously,
    but we offload it to a thread via asyncio.to_thread() so the
    event loop stays free.
    """
    for path in pdf_paths:
        start = time.perf_counter()
        try:
            # Offload CPU-bound PDF parsing to thread pool
            full_text, page_count = await asyncio.to_thread(
                extract_text_from_pdf, path
            )
            extract_ms = (time.perf_counter() - start) * 1000

            summary = build_summary(path.name, full_text, page_count)
            summary.extract_time_ms = extract_ms

            print(f"    [Async Extract] {path.name}: "
                  f"{page_count} pages, {summary.word_count:,} words "
                  f"({extract_ms:.0f}ms)")

            yield summary

        except Exception as e:
            print(f"    [Async Extract] ERROR on {path.name}: {e}")


async def async_embed_batch(
    summaries: list[PaperSummary],
) -> list[PaperSummary]:
    """
    Embed multiple papers CONCURRENTLY using asyncio.gather().

    LAYER: Memory (Embedding)

    In sync: 11 papers * 150ms = 1,650ms (sequential)
    In async: 11 papers * 150ms = ~150ms (all concurrent via gather!)

    This is WHERE async wins big.
    """
    async def embed_one(summary: PaperSummary) -> PaperSummary:
        start = time.perf_counter()
        summary.embedding = await generate_embedding_async(
            summary.abstract_snippet
        )
        summary.embed_time_ms = (time.perf_counter() - start) * 1000
        print(f"    [Async Embed]  {summary.filename}: "
              f"{len(summary.embedding)}-dim ({summary.embed_time_ms:.0f}ms)")
        return summary

    # Fire ALL embeddings concurrently
    return list(await asyncio.gather(*(embed_one(s) for s in summaries)))


async def run_async_pipeline(pdf_paths: list[Path]) -> PipelineStats:
    """
    Run the complete ASYNC pipeline.

    Flow:
        Async generator yields papers
            --> Collect batch
            --> Embed ALL concurrently (gather)
            --> Write to file with aiofiles
    """
    stats = PipelineStats(pipeline_name="ASYNC")

    print("\n" + "=" * 70)
    print("  ASYNC PIPELINE")
    print("=" * 70)

    tracemalloc.start()
    wall_start = time.perf_counter()

    # Phase A: Extract all papers via async generator
    summaries: list[PaperSummary] = []
    extract_start = time.perf_counter()

    async for summary in async_extract_papers(pdf_paths):
        summaries.append(summary)
        stats.total_extract_time_ms += summary.extract_time_ms

    stats.papers_processed = len(summaries)

    # Phase B: Embed ALL papers concurrently (the big async win)
    print(f"\n    [Async] Embedding {len(summaries)} papers concurrently...")
    embed_start = time.perf_counter()
    summaries = await async_embed_batch(summaries)
    stats.total_embed_time_ms = (time.perf_counter() - embed_start) * 1000

    # Phase C: Write output file with aiofiles
    write_start = time.perf_counter()

    async with aiofiles.open(ASYNC_OUTPUT, "w", encoding="utf-8") as outfile:
        await outfile.write("JARVIS Research Paper Summaries (ASYNC Pipeline)\n")
        await outfile.write(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        await outfile.write("=" * 70 + "\n\n")

        for index, summary in enumerate(summaries, 1):
            await outfile.write(format_summary_text(summary, index))

        await outfile.write(f"\nTotal papers: {len(summaries)}\n")

    stats.total_write_time_ms = (time.perf_counter() - write_start) * 1000

    # Capture memory stats
    _, peak_memory = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    stats.total_wall_time_ms = (time.perf_counter() - wall_start) * 1000
    stats.peak_memory_kb = peak_memory / 1024

    print(f"\n  [Async] Complete: {stats.papers_processed} papers, "
          f"{stats.total_wall_time_ms:.0f}ms total")
    print(f"  [Async] Output: {ASYNC_OUTPUT.name}")

    return stats


# =============================================================================
# PART 5: COMPARISON REPORT
# =============================================================================

def print_comparison(sync_stats: PipelineStats, async_stats: PipelineStats) -> None:
    """
    Print a head-to-head comparison of sync vs async pipeline performance.

    LAYER: Brain (Observability)
    """
    print("\n")
    print("#" * 70)
    print("  COMPARISON REPORT: SYNC vs ASYNC")
    print("#" * 70)

    # Time comparison
    print("\n  TIMING (milliseconds)")
    print("  " + "-" * 66)
    print(f"  {'Metric':<30} {'SYNC':>12} {'ASYNC':>12} {'Speedup':>10}")
    print("  " + "-" * 66)

    rows = [
        ("PDF Extraction", sync_stats.total_extract_time_ms,
         async_stats.total_extract_time_ms),
        ("Embedding Generation", sync_stats.total_embed_time_ms,
         async_stats.total_embed_time_ms),
        ("File Writing", sync_stats.total_write_time_ms,
         async_stats.total_write_time_ms),
        ("TOTAL WALL TIME", sync_stats.total_wall_time_ms,
         async_stats.total_wall_time_ms),
    ]

    for label, sync_val, async_val in rows:
        speedup = sync_val / async_val if async_val > 0 else 0
        marker = " <-- WINNER" if label == "TOTAL WALL TIME" and speedup > 1 else ""
        print(f"  {label:<30} {sync_val:>10.0f}ms {async_val:>10.0f}ms "
              f"{speedup:>8.1f}x{marker}")

    print("  " + "-" * 66)

    # Memory comparison
    print("\n  MEMORY (peak)")
    print("  " + "-" * 66)
    print(f"  {'SYNC peak':<30} {sync_stats.peak_memory_kb:>10.0f} KB")
    print(f"  {'ASYNC peak':<30} {async_stats.peak_memory_kb:>10.0f} KB")
    print("  " + "-" * 66)

    # Papers processed
    print(f"\n  Papers processed:  SYNC={sync_stats.papers_processed}  "
          f"ASYNC={async_stats.papers_processed}")

    # Output files
    sync_size = SYNC_OUTPUT.stat().st_size if SYNC_OUTPUT.exists() else 0
    async_size = ASYNC_OUTPUT.stat().st_size if ASYNC_OUTPUT.exists() else 0
    print(f"  Output file sizes: SYNC={sync_size:,} bytes  "
          f"ASYNC={async_size:,} bytes")

    # The lesson
    print("\n  " + "=" * 66)
    print("  WHY ASYNC WINS ON EMBEDDING:")
    print("  " + "=" * 66)
    print(f"""
  SYNC embedding:  {sync_stats.papers_processed} papers x {EMBED_LATENCY_SEC}s 
                   = {sync_stats.papers_processed * EMBED_LATENCY_SEC:.1f}s SEQUENTIAL
                   (each paper waits for the previous one)

  ASYNC embedding: {async_stats.papers_processed} papers x {EMBED_LATENCY_SEC}s 
                   = ~{EMBED_LATENCY_SEC}s CONCURRENT via gather()
                   (all papers embedded simultaneously)

  WHY PDF EXTRACTION IS SIMILAR:
  PDF parsing is CPU-bound (not I/O-bound). async doesn't speed up
  CPU work -- it speeds up WAITING. Both pipelines call the same
  fitz.open() under the hood. The async version offloads to a thread
  so the event loop stays free, but total CPU time is the same.

  TAKEAWAY FOR JARVIS:
  Use SYNC generators for CPU-bound streaming (data pipelines).
  Use ASYNC for I/O-bound work (API calls, DB queries, embeddings).
  The real JARVIS pipeline will use ASYNC for everything that WAITS.
    """)

    # Errors
    if sync_stats.errors or async_stats.errors:
        print("\n  ERRORS:")
        for err in sync_stats.errors:
            print(f"    [SYNC]  {err}")
        for err in async_stats.errors:
            print(f"    [ASYNC] {err}")

    print("#" * 70)


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def main() -> None:
    """
    Orchestrate both pipelines and print comparison.

    Note: asyncio.run() is called ONCE for the async pipeline.
    The sync pipeline runs in regular Python.
    """
    # Discover all PDFs
    pdf_paths = sorted(PAPERS_DIR.glob("*.pdf"))

    if not pdf_paths:
        print(f"  ERROR: No PDFs found in {PAPERS_DIR}")
        return

    print("=" * 70)
    print("  JARVIS Phase 3 Final Boss v2")
    print("  Sync vs Async PDF Ingestion Pipeline")
    print("=" * 70)
    print(f"  Papers directory: {PAPERS_DIR}")
    print(f"  Papers found:     {len(pdf_paths)}")
    print(f"  Embed latency:    {EMBED_LATENCY_SEC}s per paper (simulated)")
    print(f"  Embed dimensions: {EMBEDDING_DIM}")
    for p in pdf_paths:
        size_kb = p.stat().st_size / 1024
        print(f"    - {p.name} ({size_kb:.0f} KB)")
    print("=" * 70)

    # Run SYNC pipeline first
    sync_stats = run_sync_pipeline(pdf_paths)

    # Run ASYNC pipeline second
    async_stats = asyncio.run(run_async_pipeline(pdf_paths))

    # Print comparison
    print_comparison(sync_stats, async_stats)


if __name__ == "__main__":
    main()
