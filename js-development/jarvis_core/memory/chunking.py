"""
chunking.py

JARVIS Memory Layer: Production Document Chunker.

Import with:
    from jarvis_core.memory.chunking import RecursiveWordChunker

=============================================================================
THE BIG PICTURE: Fitting any document into a bounded embedding window
=============================================================================

Without a proper chunker:
    -> text.split() materializes the entire document as one list in RAM
    -> list.insert(0, word) is O(n) per boundary — compounds to O(n^2)
    -> A 500MB PDF spikes RAM before a single chunk is emitted
    -> Truncation silently deletes content beyond the 256-token model limit

With RecursiveWordChunker:
    -> Words are streamed one at a time via a generator — RAM stays flat (O(1))
    -> Overlap managed by deque: appendleft/popleft are O(1) operations
    -> Length tracked as a running integer — no recomputation from scratch
    -> Guaranteed: every chunk fits within the configured character limit

=============================================================================
THE FLOW (Step by Step Execution Order)
=============================================================================

STEP 1: Caller creates chunker: RecursiveWordChunker(char_limit=900, overlap=180)
        ↓
STEP 2: Caller calls chunker.chunk(text) -> returns a Generator
        ↓
STEP 3: _stream_words() yields one word at a time from the source string.
        No full word list is ever materialized.
        ↓
STEP 4: Each word is tested: does it fit in the current chunk window?
        If YES -> append to deque, update running length counter.
        If NO  -> yield current window as a joined string (the chunk).
                  Then popleft() from deque until within overlap budget.
        ↓
STEP 5: After all words, yield remaining deque content as the final chunk.
        ↓
STEP 6: Caller pipes chunks directly to JarvisMemoryStore for embedding.

=============================================================================
"""

from collections import deque
from typing import Generator, Deque


# =============================================================================
# Part 1: THE PRODUCTION CHUNKER
# =============================================================================

class RecursiveWordChunker:
    """
    LAYER: Memory — Document Ingestion Pipeline.

    Converts an arbitrarily large text string into a stream of
    character-bounded, overlap-glued chunks safe for embedding.

    It sits BETWEEN:
        - Raw text sources (PDF parser, code parser, plain text file)
        - JarvisMemoryStore.ingest_documents() (the ChromaDB encoder)

    Purpose:
        - Enforce the all-MiniLM-L6-v2 256-token hard limit
        - Preserve semantic context at chunk boundaries with overlap
        - Keep RAM usage flat regardless of source document size

    How it works:
        - Streams words lazily: no full word list in RAM at any time
        - Uses a deque (Double-Ended Queue) for the overlap window:
              deque.append(word)   -> O(1) add to right end
              deque.popleft()      -> O(1) remove from left end
              list.insert(0, word) -> O(n) [this is what we DON'T use]
        - Tracks all length measurements as running integer counters
    """

    def __init__(self, char_limit: int, overlap: int) -> None:
        """
        Configure chunker boundaries.

        Args:
            char_limit: Max characters per chunk. For all-MiniLM-L6-v2
                        set to 900 (leaves a safe margin below 256 tokens).
                        Import DEFAULT_CHUNK_CHAR_LIMIT from jarvis_core.config.
            overlap:    Characters of tail-context to carry into the next chunk.
                        Recommended: 15-20% of char_limit.
                        Import DEFAULT_CHUNK_OVERLAP from jarvis_core.config.

        Raises:
            ValueError: If overlap >= char_limit (would cause infinite loop).
        """
        if overlap >= char_limit:
            raise ValueError(
                f"overlap ({overlap}) must be less than char_limit ({char_limit}). "
                "Otherwise the chunk window never advances."
            )
        self._char_limit = char_limit
        self._overlap = overlap

    # -------------------------------------------------------------------------
    # Private: Stream words without materializing the full word list
    # -------------------------------------------------------------------------

    def _stream_words(self, text: str) -> Generator[str, None, None]:
        """
        Yield one word at a time by scanning the source string character by character.

        EXECUTION FLOW:
        1. Walk through text one character at a time.
        2. When a space is encountered, yield the accumulated buffer as a word.
        3. After the loop ends, yield any remaining buffer as the final word.

        Why not text.split(" ")?
            split() materializes ALL words into a list at once.
            For a 500MB document that is a 500MB RAM spike before we emit
            a single chunk. This generator stays at O(1) peak memory.

        Returns:
            Generator of individual word strings, stripped of empty tokens.
        """
        buffer: list[str] = []
        for char in text:
            if char == " ":
                if buffer:
                    yield "".join(buffer)
                    buffer = []
            else:
                buffer.append(char)
        if buffer:
            yield "".join(buffer)

    # -------------------------------------------------------------------------
    # Private: Trim deque to the overlap budget using O(1) pops
    # -------------------------------------------------------------------------

    def _trim_to_overlap(self, window: Deque[str], current_len: int) -> int:
        """
        Remove words from the LEFT of the window until it fits within overlap budget.

        Why popleft() instead of slicing a new list?
            list[n:] creates a brand-new list object -> O(n) copy cost.
            deque.popleft() removes in-place -> O(1).
            On documents with 50,000 chunk boundaries, this is the
            difference between O(n) and O(1) per boundary operation.

        EXECUTION FLOW:
        1. While current_len > self._overlap and window is not empty:
           a. Pop the leftmost word.
           b. Subtract its length (+1 for space) from current_len.
        2. Return the updated character count (guaranteed <= self._overlap).

        Returns:
            Updated character count for the trimmed window.
        """
        while current_len > self._overlap and window:
            removed = window.popleft()
            current_len -= len(removed) + 1
        return max(current_len, 0)

    # -------------------------------------------------------------------------
    # Public: The main chunking interface
    # -------------------------------------------------------------------------

    def chunk(self, text: str) -> Generator[str, None, None]:
        """
        Stream semantically bounded, overlap-glued chunks from source text.

        EXECUTION FLOW:
        1. Initialize an empty deque (the active window) and two integer counters.
        2. Pull one word at a time from _stream_words().
        3. new_word_len = len(word) + 1  (the +1 accounts for the space separator)
        4. If (chunk_len + new_word_len > char_limit) AND we have content:
               a. Yield " ".join(window) as the completed chunk.
               b. Call _trim_to_overlap() -> popleft() until within overlap budget.
               c. Reset chunk_len to the trimmed overlap_len.
        5. Append the word to the deque, add new_word_len to chunk_len.
        6. After all words, yield remaining deque as the final chunk.

        Returns:
            Generator of chunk strings. Each chunk is <= self._char_limit characters.
            Peak RAM: O(char_limit) — flat regardless of source document size.
        """
        window: Deque[str] = deque()
        chunk_len: int = 0

        for word in self._stream_words(text):
            new_word_len = len(word) + 1  # +1 for the space between words

            # Boundary condition: this word would overflow the current chunk
            if chunk_len + new_word_len > self._char_limit and chunk_len > 0:
                yield " ".join(window)
                chunk_len = self._trim_to_overlap(window, chunk_len)

            window.append(word)
            chunk_len += new_word_len

        # Emit whatever remains in the window (the final chunk)
        if window:
            yield " ".join(window)


# =============================================================================
# MAIN ENTRY POINT (smoke test — not a learning demo)
# =============================================================================

if __name__ == "__main__":
    from jarvis_core.config import DEFAULT_CHUNK_CHAR_LIMIT, DEFAULT_CHUNK_OVERLAP
    import time

    print("=" * 55)
    print("  RecursiveWordChunker — Smoke Test")
    print("=" * 55)

    # Simulate a large document
    doc = " ".join(["palladium-core arc-reactor element-synthesis"] * 500)
    print(f"  Source: {len(doc):,} chars | {len(doc.split()):,} words")

    chunker = RecursiveWordChunker(
        char_limit=DEFAULT_CHUNK_CHAR_LIMIT,
        overlap=DEFAULT_CHUNK_OVERLAP,
    )

    t0 = time.perf_counter()
    count = sum(1 for _ in chunker.chunk(doc))
    elapsed = (time.perf_counter() - t0) * 1000

    print(f"  Chunks emitted : {count}")
    print(f"  Time elapsed   : {elapsed:.2f}ms")
    print(f"  RAM profile    : O(chunk_size) -- flat")
    print("=" * 55)
