"""
02_pdf_parsing.py

JARVIS Lesson 2.3.2: PDF Parsing with PyMuPDF (Spatial-Aware Text Extraction).

Run with:
    python 02_pdf_parsing.py

This script demonstrates:
    1. PdfPageExtractor    - Rips text + bounding boxes from every PDF page
    2. SpatialBlockMerger  - Reconstructs reading order from raw geometry
    3. StructuredDocument   - The final output: page-aware, block-ordered text
    4. ChunkerIntegration   - Pipes structured output into RecursiveWordChunker

=============================================================================
THE BIG PICTURE: Why PDF text extraction is not "just reading a file"
=============================================================================

A PDF is NOT a text file. It is a set of DRAWING INSTRUCTIONS that
tell a renderer where to place individual characters on a canvas.

Without spatial-aware extraction (the naive way):
    -> page.get_text() dumps text in the ORDER OBJECTS WERE DRAWN
    -> Two-column papers shuffle column A and B text together
    -> Headers get mixed into body paragraphs

With spatial-aware extraction (PyMuPDF geometry):
    -> Every text fragment has a bounding box: (x0, y0, x1, y1)
    -> We sort by Y (top to bottom) then X (left to right)
    -> Correct reading order is reconstructed from raw geometry

=============================================================================
THE FLOW (Step by Step Execution Order)
=============================================================================

STEP 1: Open the PDF via fitz.open(path) — reads binary, not text
        |
STEP 2: For each page, call page.get_text("dict") -> structured dict
        with blocks, lines, spans, each with bbox and font metadata
        |
STEP 3: SpatialBlockMerger sorts blocks by (y0, x0) for reading order
        |
STEP 4: Blocks classified by font size: heading / body / footnote
        |
STEP 5: StructuredDocument stores page-ordered, role-tagged text
        |
STEP 6: Text piped into RecursiveWordChunker for embedding

=============================================================================
"""

import sys
import time
import shutil
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generator, List, Optional, Tuple

import fitz  # PyMuPDF - named after the Fitzwilliam Museum


# =============================================================================
# Part 1: DATA MODELS
# =============================================================================

@dataclass
class TextBlock:
    """
    LAYER: Memory - A single block of text with its spatial position.

    bbox is (x0, y0, x1, y1) in PDF points (1 point = 1/72 inch).
    x0, y0 = top-left corner. x1, y1 = bottom-right corner.
    role is assigned AFTER extraction based on font size vs page median.
    """
    text: str
    bbox: Tuple[float, float, float, float]
    font_size: float
    font_name: str
    page_number: int
    role: str = "body"  # "heading" | "body" | "footnote"


@dataclass
class PageContent:
    """LAYER: Memory - All extracted blocks from a single PDF page."""
    page_number: int
    width: float
    height: float
    blocks: List[TextBlock] = field(default_factory=list)


@dataclass
class StructuredDocument:
    """LAYER: Memory - The full parsed document with page-ordered blocks."""
    source_path: str
    total_pages: int
    pages: List[PageContent] = field(default_factory=list)

    def full_text(self) -> str:
        """Concatenate all block text for chunking."""
        parts: list[str] = []
        for page in self.pages:
            for block in page.blocks:
                if block.text.strip():
                    parts.append(block.text.strip())
        return "\n".join(parts)

    def stats(self) -> dict:
        total_blocks = sum(len(p.blocks) for p in self.pages)
        total_chars = sum(len(b.text) for p in self.pages for b in p.blocks)
        roles: dict[str, int] = {}
        for page in self.pages:
            for block in page.blocks:
                roles[block.role] = roles.get(block.role, 0) + 1
        return {"pages": self.total_pages, "blocks": total_blocks,
                "characters": total_chars, "roles": roles}


# =============================================================================
# Part 2: PDF PAGE EXTRACTOR (The geometry ripper)
# =============================================================================

class PdfPageExtractor:
    """
    LAYER: Memory - Extracts text blocks with spatial bounding boxes.

    It sits BETWEEN:
        - The raw PDF binary file on disk
        - SpatialBlockMerger (sorts blocks into reading order)

    How it works:
        - page.get_text("dict") returns blocks -> lines -> spans
        - A span is the atomic unit: characters with same font
        - We aggregate spans per block, pick dominant font size
        - Pages are streamed via generator for flat RAM usage
    """

    def __init__(self, pdf_path: str) -> None:
        self._path = Path(pdf_path)
        if not self._path.exists():
            raise FileNotFoundError(f"PDF not found: {self._path}")
        self._doc: Optional[fitz.Document] = None

    def __enter__(self) -> "PdfPageExtractor":
        self._doc = fitz.open(str(self._path))
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if self._doc:
            self._doc.close()
            self._doc = None
        return False

    def stream_pages(self) -> Generator[PageContent, None, None]:
        """
        Yield one PageContent at a time from the PDF.

        EXECUTION FLOW:
        1. Iterate pages. For each, call get_text("dict").
        2. For each text block (type 0), aggregate spans.
        3. Pick dominant font size via Counter.most_common(1).
        4. Yield PageContent. Previous page can be GC'd.
        """
        if self._doc is None:
            raise RuntimeError("Use 'with PdfPageExtractor(path) as ext:'")

        for page_idx in range(len(self._doc)):
            page = self._doc[page_idx]
            page_dict = page.get_text("dict")
            page_content = PageContent(
                page_number=page_idx,
                width=page_dict.get("width", 0.0),
                height=page_dict.get("height", 0.0),
            )

            for block in page_dict.get("blocks", []):
                if block.get("type") != 0:  # Skip image blocks
                    continue

                text_parts: list[str] = []
                font_sizes: list[float] = []
                font_names: list[str] = []

                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = span.get("text", "")
                        if text.strip():
                            text_parts.append(text)
                            font_sizes.append(span.get("size", 0.0))
                            font_names.append(span.get("font", "unknown"))

                if not text_parts:
                    continue

                size_counts = Counter(round(s, 1) for s in font_sizes)
                dominant_size = size_counts.most_common(1)[0][0]

                page_content.blocks.append(TextBlock(
                    text=" ".join(text_parts),
                    bbox=tuple(block.get("bbox", (0, 0, 0, 0))),
                    font_size=dominant_size,
                    font_name=font_names[0] if font_names else "unknown",
                    page_number=page_idx,
                ))

            yield page_content


# =============================================================================
# Part 3: SPATIAL BLOCK MERGER (Reading order reconstruction)
# =============================================================================

class SpatialBlockMerger:
    """
    LAYER: Memory - Sorts blocks into human reading order.

    It sits BETWEEN:
        - PdfPageExtractor (raw blocks in draw order)
        - StructuredDocument (blocks in reading order)

    How it works:
        - Sort by y0 (top to bottom)
        - Group blocks into rows (y-proximity within tolerance)
        - Sort each row by x0 (left to right)
        - Classify roles by font size relative to median
    """

    def __init__(self, row_tolerance: float = 5.0) -> None:
        self._row_tolerance = row_tolerance

    def sort_blocks(self, page: PageContent) -> List[TextBlock]:
        """Sort blocks: top-to-bottom, then left-to-right within rows."""
        if not page.blocks:
            return []

        sorted_by_y = sorted(page.blocks, key=lambda b: b.bbox[1])
        rows: list[list[TextBlock]] = []
        current_row: list[TextBlock] = [sorted_by_y[0]]
        current_y = sorted_by_y[0].bbox[1]

        for block in sorted_by_y[1:]:
            if abs(block.bbox[1] - current_y) <= self._row_tolerance:
                current_row.append(block)
            else:
                rows.append(current_row)
                current_row = [block]
                current_y = block.bbox[1]
        rows.append(current_row)

        result: list[TextBlock] = []
        for row in rows:
            row.sort(key=lambda b: b.bbox[0])
            result.extend(row)
        return result

    def classify_roles(self, blocks: List[TextBlock]) -> None:
        """Tag blocks as heading/body/footnote based on font size vs median."""
        if not blocks:
            return
        sizes = sorted(b.font_size for b in blocks)
        median = sizes[len(sizes) // 2]
        for block in blocks:
            if block.font_size >= median * 1.3:
                block.role = "heading"
            elif block.font_size <= median * 0.8:
                block.role = "footnote"
            else:
                block.role = "body"


# =============================================================================
# Part 4: THE FULL PARSING PIPELINE
# =============================================================================

def parse_pdf(pdf_path: str) -> StructuredDocument:
    """Parse a PDF into a StructuredDocument with spatial reading order."""
    merger = SpatialBlockMerger(row_tolerance=5.0)
    with PdfPageExtractor(pdf_path) as extractor:
        doc = StructuredDocument(
            source_path=pdf_path,
            total_pages=len(extractor._doc),
        )
        for page_content in extractor.stream_pages():
            sorted_blocks = merger.sort_blocks(page_content)
            merger.classify_roles(sorted_blocks)
            page_content.blocks = sorted_blocks
            doc.pages.append(page_content)
    return doc


# =============================================================================
# Part 5: DEMO PDF GENERATOR
# =============================================================================

def create_demo_pdf(output_path: str) -> str:
    """Create a multi-page PDF with known structure for testing."""
    doc = fitz.open()

    # Page 1: heading + body + footnote
    p1 = doc.new_page(width=595, height=842)
    p1.insert_text((72, 72), "Arc Reactor Technical Manual",
                   fontsize=24, fontname="helv")
    p1.insert_text((72, 120),
        "The palladium core generates a sustained output of 3 gigajoules "
        "per second. This energy density exceeds any known conventional "
        "power source by a factor of approximately 47,000.",
        fontsize=11, fontname="helv")
    p1.insert_text((72, 220),
        "Containment is achieved through a toroidal magnetic field generated "
        "by twelve superconducting coils arranged in a Halbach array. Field "
        "strength at the plasma boundary measures 4.7 Tesla.",
        fontsize=11, fontname="helv")
    p1.insert_text((72, 780),
        "Note: All measurements at Stark Industries R&D Lab. Level 7.",
        fontsize=8, fontname="helv")

    # Page 2: section heading + body + sub-heading
    p2 = doc.new_page(width=595, height=842)
    p2.insert_text((72, 72), "Chapter 2: Vibranium Integration",
                   fontsize=20, fontname="helv")
    p2.insert_text((72, 120),
        "Replacing the palladium core with vibranium eliminates blood "
        "toxicity entirely. Vibranium absorbs and re-emits kinetic energy "
        "with 99.97 percent efficiency.",
        fontsize=11, fontname="helv")
    p2.insert_text((72, 220), "2.1 Synthesis Protocol",
                   fontsize=16, fontname="helv")
    p2.insert_text((72, 260),
        "The element must be synthesized using a particle accelerator at "
        "1.21 gigawatts. The beam must trace the atomic structure from "
        "Howard Stark's city model.",
        fontsize=11, fontname="helv")

    doc.save(output_path)
    doc.close()
    return output_path


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("  JARVIS Lesson 2.3.2: PDF Parsing with PyMuPDF")
    print("=" * 70)

    # Step 1: Create demo PDF
    demo_dir = Path(tempfile.mkdtemp(prefix="jarvis_pdf_demo_"))
    demo_pdf = str(demo_dir / "arc_reactor_manual.pdf")
    print(f"\n  [1] Creating demo PDF...")
    create_demo_pdf(demo_pdf)
    print(f"  [OK] Created: {demo_pdf}")

    # Step 2: Parse
    print(f"\n  [2] Parsing with spatial-aware extraction...")
    t0 = time.perf_counter()
    document = parse_pdf(demo_pdf)
    ms = (time.perf_counter() - t0) * 1000
    print(f"  [OK] Parsed in {ms:.1f}ms")

    # Step 3: Stats
    s = document.stats()
    print(f"\n  [3] Results:")
    print(f"  Pages: {s['pages']} | Blocks: {s['blocks']} | "
          f"Chars: {s['characters']:,} | Roles: {s['roles']}")

    # Step 4: Block details
    print(f"\n  [4] Block Details:")
    print(f"  {'Pg':>2} | {'Role':>9} | {'Font':>5} | {'BBox(x0,y0)':>12} | Text")
    print(f"  {'-'*2}-+-{'-'*9}-+-{'-'*5}-+-{'-'*12}-+-{'-'*35}")
    for page in document.pages:
        for block in page.blocks:
            x0, y0 = block.bbox[0], block.bbox[1]
            preview = block.text[:40].replace("\n", " ")
            print(f"  {block.page_number:>2} | {block.role:>9} | "
                  f"{block.font_size:>5.1f} | ({x0:>4.0f},{y0:>4.0f}) | {preview}...")

    # Step 5: Chunker integration
    print(f"\n  [5] Chunker Integration:")
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "js-development"))
        from jarvis_core.memory.chunking import RecursiveWordChunker
        from jarvis_core.config import DEFAULT_CHUNK_CHAR_LIMIT, DEFAULT_CHUNK_OVERLAP
        full_text = document.full_text()
        chunker = RecursiveWordChunker(DEFAULT_CHUNK_CHAR_LIMIT, DEFAULT_CHUNK_OVERLAP)
        for i, chunk in enumerate(chunker.chunk(full_text), 1):
            print(f"  Chunk {i}: {len(chunk):>4} chars | \"{chunk[:60]}...\"")
        print("  Ready for JarvisMemoryStore.ingest_documents()")
    except ImportError as e:
        print(f"  [SKIP] {e}")
        print(f"  Full text: {document.full_text()[:200]}...")

    # Cleanup
    try:
        shutil.rmtree(demo_dir, ignore_errors=True)
    except Exception:
        pass

    print("\n" + "=" * 70)
    print("  LESSON COMPLETE: PDF -> Blocks -> Reading Order -> Chunks -> Memory")
    print("=" * 70)
