"""
image_extractor.py

JARVIS Memory Layer: Production PDF Image Extractor.

Import with:
    from jarvis_core.memory.image_extractor import PdfImageExtractor, ExtractedImage

=============================================================================
THE BIG PICTURE: Ripping images from PDFs without data loss or noise
=============================================================================

Without a hardened extractor:
    -> Duplicate XREF IDs (same logo per page) inflate storage by 10-15x
    -> 1x1 pixel decoration artifacts are saved alongside real figures
    -> Images are extracted without page position (no link to nearby text)

With this module:
    -> Seen XREF IDs are tracked in a set: each image saved exactly once
    -> Images under MIN_IMAGE_BYTES (5KB) are discarded as decoration noise
    -> Each ExtractedImage carries a bbox (x0, y0, x1, y1) in PDF points,
       enabling future Phase 4 caption-to-text linking via spatial proximity

=============================================================================
THE FLOW (Step by Step Execution Order)
=============================================================================

STEP 1: Open the PDF via fitz.open() in a context manager
        |
STEP 2: For each page, call page.get_images(full=True)
        Returns a list of image descriptors including the XREF ID
        |
STEP 3: Skip if XREF already seen (deduplication)
        |
STEP 4: Skip if image bytes < MIN_IMAGE_BYTES (noise filter)
        |
STEP 5: Pull bounding box via page.get_image_rects(xref)
        |
STEP 6: Yield ExtractedImage with bytes, bbox, extension, page number

=============================================================================
"""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generator, Optional, Tuple

import fitz  # PyMuPDF: pip install PyMuPDF


# =============================================================================
# Part 1: CONSTANTS
# =============================================================================

# Images smaller than this byte threshold are almost certainly decoration:
# background textures, 1x1 spacers, icon glyphs.
# 5KB is the empirical safe floor for real figures in academic papers.
MIN_IMAGE_BYTES: int = 5_000


# =============================================================================
# Part 2: DATA MODEL
# =============================================================================

@dataclass
class ExtractedImage:
    """
    LAYER: Memory - A single image ripped from a PDF with spatial metadata.

    It sits BETWEEN:
        - PdfImageExtractor (upstream: raw bytes from XREF table)
        - Phase 4 Vision Specialist (downstream: caption generation)

    Purpose:
        - Hold the raw bytes of the image ready for disk save or API upload
        - Track the page number and bounding box for spatial text linking
        - Carry the native format extension (png, jpeg, jp2, etc.)

    How it works:
        - bbox is (x0, y0, x1, y1) in PDF points (1 point = 1/72 inch).
          If PyMuPDF cannot determine position, bbox is None.
        - xref_id is the internal PDF cross-reference ID. Used for dedup.
    """
    page_number: int
    image_bytes: bytes
    extension: str                              # e.g. "png", "jpeg"
    xref_id: int                                # PDF internal reference ID
    size_bytes: int                             # len(image_bytes)
    bbox: Optional[Tuple[float, float, float, float]] = field(default=None)


# =============================================================================
# Part 3: PDF IMAGE EXTRACTOR
# =============================================================================

class PdfImageExtractor:
    """
    LAYER: Memory - Extracts deduplicated, noise-filtered images from PDF pages.

    It sits BETWEEN:
        - Raw PDF binary on disk
        - Disk storage (save to jarvis_data) or Vision Specialist (Phase 4)

    Purpose:
        - Extract only real figures (no decoration noise)
        - Ensure each image is stored exactly once (no XREF duplicates)
        - Preserve spatial position for future caption-text linking

    How it works:
        - page.get_images(full=True) returns all image objects on a page
        - Each object has an XREF ID (the PDF's internal pointer to the image)
        - We track seen XREFs in a set to prevent duplicate extraction
        - We check image byte size against MIN_IMAGE_BYTES to discard noise
        - We call page.get_image_rects(xref) to retrieve the bounding box
    """

    def __init__(self, pdf_path: str, min_image_bytes: int = MIN_IMAGE_BYTES) -> None:
        """
        Prepare the extractor. Does NOT open the file yet.

        Args:
            pdf_path:        Absolute path to the PDF file.
            min_image_bytes: Discard images smaller than this byte count.

        Raises:
            FileNotFoundError: If the PDF does not exist on disk.
        """
        self._path = Path(pdf_path)
        if not self._path.exists():
            raise FileNotFoundError(f"PDF not found: {self._path}")
        self._min_bytes = min_image_bytes
        self._doc: Optional[fitz.Document] = None

    def __enter__(self) -> "PdfImageExtractor":
        self._doc = fitz.open(str(self._path))
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if self._doc:
            self._doc.close()
            self._doc = None
        return False

    @property
    def page_count(self) -> int:
        if self._doc is None:
            raise RuntimeError("Extractor not open.")
        return len(self._doc)

    def stream_images(self) -> Generator[ExtractedImage, None, None]:
        """
        Yield one real, deduplicated image at a time from the PDF.

        EXECUTION FLOW:
        1. Maintain a set of seen XREF IDs and seen image hashes (empty at start).
        2. For each page, call get_images(full=True).
        3. For each image descriptor, read the XREF from index 0.
        4. Skip if XREF is already in seen set (duplicate across pages).
        5. Extract raw bytes via doc.extract_image(xref).
        6. Skip if byte count < self._min_bytes (decoration noise).
        7. Calculate MD5 hash of the image bytes and skip if already seen.
        8. Pull bounding box via page.get_image_rects(xref).
        9. Add XREF and hash to seen sets. Yield ExtractedImage.

        Returns:
            Generator of ExtractedImage. One unique real image per yield.
        """
        if self._doc is None:
            raise RuntimeError("Use 'with PdfImageExtractor(path) as ext:'")

        # ─────────────────────────────────────────────────────────────────────
        # FIX 1: XREF & Hash deduplication — prevents saving logos 15 times
        # ─────────────────────────────────────────────────────────────────────
        seen_xrefs: set[int] = set()
        seen_hashes: set[str] = set()

        for page_idx in range(len(self._doc)):
            page = self._doc[page_idx]

            # get_images(full=True) returns a list of tuples:
            # (xref, smask, width, height, bpc, colorspace, alt_colorspace,
            #  name, filter, referencer)
            image_list = page.get_images(full=True)

            for img_info in image_list:
                xref: int = img_info[0]

                # ─────────────────────────────────────────────────────────
                # FIX 1a: Skip if we've already seen this XREF
                # ─────────────────────────────────────────────────────────
                if xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)

                # Extract raw bytes from the internal XREF object
                base_image = self._doc.extract_image(xref)
                if not base_image:
                    continue

                raw_bytes: bytes = base_image["image"]

                # ─────────────────────────────────────────────────────────
                # FIX 2: Size filter — discard decoration noise (<5KB)
                # ─────────────────────────────────────────────────────────
                if len(raw_bytes) < self._min_bytes:
                    continue

                # ─────────────────────────────────────────────────────────
                # FIX 1b: Hash deduplication — catches identical images with diff XREFs
                # ─────────────────────────────────────────────────────────
                img_hash = hashlib.md5(raw_bytes).hexdigest()
                if img_hash in seen_hashes:
                    continue
                seen_hashes.add(img_hash)

                # ─────────────────────────────────────────────────────────
                # FIX 3: Bounding box — record WHERE on the page this is
                # ─────────────────────────────────────────────────────────
                bbox: Optional[Tuple[float, float, float, float]] = None
                rects = page.get_image_rects(xref)
                if rects:
                    r = rects[0]
                    bbox = (r.x0, r.y0, r.x1, r.y1)

                yield ExtractedImage(
                    page_number=page_idx,
                    image_bytes=raw_bytes,
                    extension=base_image.get("ext", "png"),
                    xref_id=xref,
                    size_bytes=len(raw_bytes),
                    bbox=bbox,
                )


# =============================================================================
# Part 4: CONVENIENCE FUNCTION
# =============================================================================

def extract_images(
    pdf_path: str,
    output_dir: str,
    min_image_bytes: int = MIN_IMAGE_BYTES,
) -> list[Path]:
    """
    Extract all real images from a PDF and save them to output_dir.

    Filename Convention (the Metadata Foreign Key):
        {source_stem}_page{page_number}_img{counter}.{ext}

        Example: 1706.03762v7_page4_img1.png

        Why this naming scheme?
            The JARVIS Brain resolves images purely from the filesystem.
            When Chroma returns a text chunk with metadata
            {'source': '1706.03762v7.pdf', 'page': 4}, the Brain runs:
                glob('extracted_images/1706.03762v7_page4_*.png')
            ...and finds all figures from that page instantly.
            No secondary database. No JOIN. Just a glob on a predictable name.

    Args:
        pdf_path:        Absolute path to the PDF file.
        output_dir:      Directory to save extracted images.
        min_image_bytes: Discard images smaller than this byte count.

    Returns:
        List of Path objects pointing to saved image files.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    source_stem = Path(pdf_path).stem  # e.g. '1706.03762v7'
    saved: list[Path] = []

    # Counter per page to handle multiple images on the same page
    page_counters: dict[int, int] = {}

    with PdfImageExtractor(pdf_path, min_image_bytes) as extractor:
        for img in extractor.stream_images():
            # Increment the per-page counter (images on page 4 -> img1, img2, ...)
            page_counters[img.page_number] = page_counters.get(img.page_number, 0) + 1
            counter = page_counters[img.page_number]

            # Stable, glob-friendly filename: source_stem_pageN_imgM.ext
            filename = (
                f"{source_stem}_page{img.page_number}_img{counter}.{img.extension}"
            )
            save_path = out / filename
            with open(save_path, "wb") as f:
                f.write(img.image_bytes)
            saved.append(save_path)

    return saved


# =============================================================================
# MAIN ENTRY POINT (smoke test)
# =============================================================================

if __name__ == "__main__":
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from jarvis_core.config import DATA_ROOT

    print("=" * 55)
    print("  PdfImageExtractor - Smoke Test")
    print("=" * 55)

    if len(_sys.argv) > 1:
        pdf_file = _sys.argv[1]
        output = _sys.argv[2] if len(_sys.argv) > 2 else str(DATA_ROOT / "extracted_images")
        print(f"  PDF    : {pdf_file}")
        print(f"  Output : {output}")
        saved = extract_images(pdf_file, output)
        print(f"  [OK] Extracted {len(saved)} real images:")
        for p in saved:
            print(f"    - {p.name}")
    else:
        print("  Usage: python image_extractor.py <path_to_pdf> [output_dir]")
        print("  No args provided. Import test only.")

    print("=" * 55)
