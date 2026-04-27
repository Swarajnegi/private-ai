"""
pdf_parser.py

JARVIS Memory Layer: Production PDF Text Extractor.

Import with:
    from jarvis_core.memory.pdf_parser import parse_pdf, PdfPageExtractor

=============================================================================
THE BIG PICTURE: Spatial-aware PDF text extraction for JARVIS Memory
=============================================================================

Without spatial-aware extraction:
    -> page.get_text() dumps text in draw order, not reading order
    -> Two-column papers shuffle columns together
    -> Headings, body, and footnotes are indistinguishable

With this module:
    -> Every text block carries its (x0, y0, x1, y1) bounding box
    -> Blocks sorted by Y then X to reconstruct reading order
    -> Font size analysis tags blocks as heading / body / footnote
    -> Pages streamed via generator for flat RAM on large PDFs

=============================================================================
THE FLOW (Step by Step Execution Order)
=============================================================================

STEP 1: PdfPageExtractor opens the PDF binary via fitz.open()
        |
STEP 2: stream_pages() yields one PageContent at a time (generator)
        |
STEP 3: SpatialBlockMerger sorts blocks by (y0, x0) reading order
        |
STEP 4: Blocks classified by font size relative to page median
        |
STEP 5: parse_pdf() returns StructuredDocument ready for chunking

=============================================================================
"""

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generator, List, Optional, Tuple

import fitz  # PyMuPDF: pip install PyMuPDF


# =============================================================================
# Part 1: DATA MODELS
# =============================================================================

@dataclass
class TextBlock:
    """
    LAYER: Memory - A text block with spatial position from a PDF page.

    bbox: (x0, y0, x1, y1) in PDF points (1 point = 1/72 inch).
    role: assigned post-extraction based on font size vs page median.
    """
    text: str
    bbox: Tuple[float, float, float, float]
    font_size: float
    font_name: str
    page_number: int
    role: str = "body"


@dataclass
class PageContent:
    """LAYER: Memory - All extracted blocks from a single PDF page."""
    page_number: int
    width: float
    height: float
    blocks: List[TextBlock] = field(default_factory=list)


@dataclass
class StructuredDocument:
    """
    LAYER: Memory - The parsed document with page-ordered, role-tagged blocks.

    Purpose:
        - Represent the full document as ordered pages with classified blocks
        - Provide full_text() for direct input to RecursiveWordChunker
    """
    source_path: str
    total_pages: int
    pages: List[PageContent] = field(default_factory=list)

    def full_text(self) -> str:
        """Concatenate all block text across all pages for chunking."""
        parts: list[str] = []
        for page in self.pages:
            for block in page.blocks:
                stripped = block.text.strip()
                if stripped:
                    parts.append(stripped)
        return "\n".join(parts)

    def heading_text(self) -> str:
        """Extract only heading blocks (for metadata / summaries)."""
        return "\n".join(
            b.text.strip() for p in self.pages for b in p.blocks
            if b.role == "heading" and b.text.strip()
        )

    def stats(self) -> dict:
        """Return extraction statistics."""
        total_blocks = sum(len(p.blocks) for p in self.pages)
        total_chars = sum(len(b.text) for p in self.pages for b in p.blocks)
        roles: dict[str, int] = {}
        for page in self.pages:
            for block in page.blocks:
                roles[block.role] = roles.get(block.role, 0) + 1
        return {"pages": self.total_pages, "blocks": total_blocks,
                "characters": total_chars, "roles": roles}


# =============================================================================
# Part 2: PDF PAGE EXTRACTOR
# =============================================================================

class PdfPageExtractor:
    """
    LAYER: Memory - Extracts text blocks with bounding boxes from PDF pages.

    It sits BETWEEN:
        - Raw PDF binary on disk
        - SpatialBlockMerger (reading order reconstruction)

    How it works:
        - page.get_text("dict") returns blocks -> lines -> spans
        - Spans aggregated per block with dominant font size
        - Pages streamed via generator: O(largest_page) RAM, not O(doc)
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

    @property
    def page_count(self) -> int:
        """Return total pages without consuming the generator."""
        if self._doc is None:
            raise RuntimeError("Extractor not open.")
        return len(self._doc)

    def stream_pages(self) -> Generator[PageContent, None, None]:
        """
        Yield one PageContent at a time from the PDF.

        EXECUTION FLOW:
        1. For each page, call get_text("dict") for structured data.
        2. For each text block (type 0), aggregate spans.
        3. Pick dominant font size via Counter.most_common(1).
        4. Yield PageContent. Previous page eligible for GC.
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
                if block.get("type") != 0:
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
# Part 3: SPATIAL BLOCK MERGER
# =============================================================================

class SpatialBlockMerger:
    """
    LAYER: Memory - Sorts blocks into human reading order.

    How it works:
        - Sort by y0 (top to bottom)
        - Group into rows (blocks within row_tolerance of each other)
        - Sort each row by x0 (left to right)
        - Classify roles by font size relative to page median
    """

    def __init__(self, row_tolerance: float = 5.0) -> None:
        self._row_tolerance = row_tolerance

    def sort_blocks(self, page: PageContent) -> List[TextBlock]:
        """Sort blocks: top-to-bottom, left-to-right within rows."""
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
        """Tag blocks as heading/body/footnote by font size vs median."""
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
# Part 4: TOP-LEVEL PIPELINE FUNCTION
# =============================================================================

def parse_pdf(
    pdf_path: str,
    row_tolerance: float = 5.0,
) -> StructuredDocument:
    """
    Parse a PDF into a StructuredDocument with spatial reading order.

    EXECUTION FLOW:
    1. Open PDF via PdfPageExtractor (context manager).
    2. Stream pages lazily via generator.
    3. Sort blocks into reading order per page.
    4. Classify roles by font size.
    5. Return complete StructuredDocument.

    Args:
        pdf_path: Absolute path to the PDF file.
        row_tolerance: Max vertical distance (PDF points) for same-row grouping.

    Returns:
        StructuredDocument with sorted, role-tagged blocks.
    """
    merger = SpatialBlockMerger(row_tolerance=row_tolerance)
    with PdfPageExtractor(pdf_path) as extractor:
        doc = StructuredDocument(
            source_path=pdf_path,
            total_pages=extractor.page_count,
        )
        for page_content in extractor.stream_pages():
            sorted_blocks = merger.sort_blocks(page_content)
            merger.classify_roles(sorted_blocks)
            page_content.blocks = sorted_blocks
            doc.pages.append(page_content)
    return doc


# =============================================================================
# MAIN ENTRY POINT (smoke test only)
# =============================================================================

if __name__ == "__main__":
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

    print("=" * 55)
    print("  PdfParser - Smoke Test")
    print("=" * 55)

    if len(_sys.argv) > 1:
        # Parse a real PDF passed as argument
        pdf_file = _sys.argv[1]
        print(f"  Parsing: {pdf_file}")
        result = parse_pdf(pdf_file)
        s = result.stats()
        print(f"  Pages: {s['pages']} | Blocks: {s['blocks']} | "
              f"Chars: {s['characters']:,}")
        print(f"  Roles: {s['roles']}")
        print(f"  Headings: {result.heading_text()[:200]}")
        print(f"  Full text (first 300 chars): {result.full_text()[:300]}...")
    else:
        print("  Usage: python pdf_parser.py <path_to_pdf>")
        print("  No PDF provided. Smoke test passed (imports OK).")

    print("=" * 55)
