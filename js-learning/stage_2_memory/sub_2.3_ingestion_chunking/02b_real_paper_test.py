"""
02b_real_paper_test.py

JARVIS Memory Layer: Production Pipeline Integration Test

Run with:
    python 02b_real_paper_test.py

This script demonstrates:
    1. Integration — Connecting pdf_parser to chunking on a real PDF
    2. Real-World Extraction — Handling multi-column, math-heavy research papers

=============================================================================
THE BIG PICTURE
=============================================================================

Without integration testing:
    → We assume our clean-room demo PDF represents reality.
    → We crash in production when handed a 2-column IEEE format paper.

With this integration test:
    → We prove that `jarvis_core` absolute imports work securely.
    → We verify that spatial merging correctly unravels columns.
    → We confirm the generator chunker doesn't OOM on real data.

=============================================================================
THE FLOW (Step by Step Execution Order)
=============================================================================

STEP 1: Target a real PDF (e.g., 2407.19813v3.pdf) from the JARVIS Data folder
        ↓
STEP 2: Parse the PDF using jarvis_core.memory.pdf_parser
        ↓
STEP 3: Extract the full reading-order text from the StructuredDocument
        ↓
STEP 4: Pipe the text into jarvis_core.memory.chunking
        ↓
STEP 5: Print chunk boundaries to visually verify semantic integrity

=============================================================================
"""

import sys
from pathlib import Path
import time

# ─────────────────────────────────────────────────────────────────────
# STEP 0: Path Injection for Production Imports
# ─────────────────────────────────────────────────────────────────────
# We must dynamically add js-development to sys.path so we can import jarvis_core
DEV_DIR = Path(__file__).resolve().parents[3] / "js-development"
sys.path.insert(0, str(DEV_DIR))

from jarvis_core.memory.pdf_parser import parse_pdf
from jarvis_core.memory.chunking import RecursiveWordChunker
from jarvis_core.config import DEFAULT_CHUNK_CHAR_LIMIT, DEFAULT_CHUNK_OVERLAP

# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  Production Pipeline Test: Local Research Paper")
    print("=" * 60)

    # 1. Target a local research paper (Attention Is All You Need)
    pdf_path = Path("E:/J.A.R.V.I.S/Research Papers/J.A.R.V.I.S specific/1706.03762v7.pdf")
    
    if not pdf_path.exists():
        print(f"Error: Could not find {pdf_path}")
        sys.exit(1)
        
    print(f"  Target: {pdf_path.name}")
    
    # 2. Parse the PDF
    print("\n[Step 1] Parsing PDF...")
    t0 = time.perf_counter()
    document = parse_pdf(str(pdf_path))
    parse_time = (time.perf_counter() - t0) * 1000
    print(f"  [OK] Parsed {document.total_pages} pages in {parse_time:.2f}ms")
    
    # 3. Extract Text
    print("\n[Step 2] Extracting Reading-Order Text...")
    full_text = document.full_text()
    print(f"  [OK] Extracted {len(full_text):,} total characters")
    
    # 4. Chunk the Text
    print("\n[Step 3] Chunking Text (O(1) memory)...")
    t1 = time.perf_counter()
    chunker = RecursiveWordChunker(
        char_limit=DEFAULT_CHUNK_CHAR_LIMIT,
        overlap=DEFAULT_CHUNK_OVERLAP
    )
    
    chunks = []
    for chunk in chunker.chunk(full_text):
        chunks.append(chunk)
        
    chunk_time = (time.perf_counter() - t1) * 1000
    print(f"  [OK] Generated {len(chunks)} chunks in {chunk_time:.2f}ms")
    
    # 5. Verification
    print("\n[Step 4] Verification (First 2 Chunks):")
    if len(chunks) >= 1:
        print(f"\n  --- CHUNK 1 ({len(chunks[0])} chars) ---")
        # Print first 200 chars to avoid overwhelming the console
        preview_1 = chunks[0][:200].replace('\n', ' ')
        print(f"  {preview_1}...")
        
    if len(chunks) >= 2:
        print(f"\n  --- CHUNK 2 ({len(chunks[1])} chars) ---")
        preview_2 = chunks[1][:200].replace('\n', ' ')
        print(f"  {preview_2}...")
        
        # Verify Overlap Logic visually
        # Find the overlap string and display it
        # Overlap is the start of Chunk 2
        overlap_preview = chunks[1][:DEFAULT_CHUNK_OVERLAP].replace('\n', ' ')
        print(f"\n  [Overlap Verify] Chunk 2 starts with:")
        print(f"  ... {overlap_preview[:100]} ...")
    
    print("\n" + "=" * 60)
