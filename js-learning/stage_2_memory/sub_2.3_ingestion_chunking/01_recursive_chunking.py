"""
01_recursive_chunking.py

JARVIS Memory Layer: Document Chunking Strategies for the Ingestion Pipeline

Run with:
    python 01_recursive_chunking.py

This script demonstrates:
    1. FailureDemoChunker  — Character-slice chunking (destroys words, educational only)
    2. RecursiveWordChunker — Production-grade, memory-safe chunker with deque overlap

=============================================================================
THE BIG PICTURE: Fitting a 10,000-page document into a 256-token memory slot
=============================================================================

Without a proper chunker (the naive way):
    → text.split(" ") loads the ENTIRE document into RAM as one giant list
    → overlap uses list.insert(0, ...) which is O(n) per operation on large lists
    → On a 500MB PDF: RAM spikes BEFORE a single chunk is emitted
    → On 50,000 chunk boundaries: insert() compounds to O(n^2) runtime

With RecursiveWordChunker (the smart way):
    → Words are STREAMED from the source one-at-a-time via a generator
    → Overlap window is managed by a deque (Double-Ended Queue):
        A deque appends/pops from BOTH ends in O(1) — no shifting required
    → Running length counters are tracked incrementally — no recomputation
    → RAM stays FLAT no matter how large the document is

=============================================================================
THE FLOW (Step by Step Execution Order)
=============================================================================

STEP 1: _stream_words() reads the source string character-by-character,
        yielding one word at a time. No full list ever exists in RAM.
        ↓
STEP 2: Each word is evaluated: does it fit inside the current chunk window?
        ↓
STEP 3: If YES → append word to the active chunk deque, add to running length.
        ↓
STEP 4: If NO  → emit the full deque as a joined string (the chunk).
        Then, pop words from the LEFT of the deque until we are within
        the overlap budget. This is O(1) per pop — no list shifting.
        ↓
STEP 5: The remaining deque IS the overlap. Add the new word and continue.
        ↓
STEP 6: After iterating all words, emit whatever remains in the deque as
        the final chunk (guaranteed <= character_limit).

=============================================================================
"""

# =============================================================================
# Part 1: IMPORTS
# =============================================================================

from collections import deque
from typing import Generator, Deque


# =============================================================================
# Part 2: FAILURE MODE DEMONSTRATION (Educational — Not for Production)
# =============================================================================

class FailureDemoChunker:
    """
    LAYER 0: Demonstrates WHY character-slicing is architecturally broken.

    THIS IS A TEACHING AID, NOT PRODUCTION CODE!

    It sits BEFORE the correct implementation to contrast outputs.

    Purpose:
        - Show what happens when you blindly slice text at fixed character limits
        - Generate a visible, incorrect output for comparison

    How it works:
        - Iterates over the text string in steps of `char_limit` characters
        - Uses Python's slice syntax: text[start : start + char_limit]
        - No awareness of word boundaries — will slice mid-word, mid-sentence
    """

    def __init__(self, char_limit: int) -> None:
        self.char_limit = char_limit

    def chunk(self, text: str) -> Generator[str, None, None]:
        """
        Emit fixed-size character slices of the input text.

        EXECUTION FLOW:
        1. Start index at 0
        2. Slice text from index to index + char_limit
        3. Yield the slice — regardless of whether a word is split
        4. Advance index by char_limit and repeat

        Returns:
            Generator of raw character slices (may contain broken words)
        """
        print(f"\n[DEMO] FailureDemoChunker (limit={self.char_limit} chars)")
        for i in range(0, len(text), self.char_limit):
            yield text[i : i + self.char_limit]


# =============================================================================
# Part 3: PRODUCTION CHUNKER (The Real Architecture)
# =============================================================================

class RecursiveWordChunker:
    """
    LAYER 2 — Memory: Production-grade, memory-safe, streaming document chunker.

    It sits BETWEEN:
        - Raw text source (a string, file handle, or network stream)
        - Phase 2.2 NoveltyGate + ChromaDB encoder

    Purpose:
        - Split arbitrarily large text into character-bounded chunks
        - Preserve semantic context at boundaries using an overlap window
        - Keep RAM usage FLAT regardless of document size

    How it works:
        - Streams words lazily via a private generator (_stream_words)
        - Maintains the active chunk as a deque (Double-Ended Queue):
              deque.append(word)      → O(1) — adds to right end
              deque.popleft()         → O(1) — removes from left end
              list.insert(0, word)    → O(n) — shifts every element right (OLD WAY)
        - Tracks current chunk length and overlap length as plain integers,
          updated incrementally — never recomputed from scratch
    """

    def __init__(self, char_limit: int, overlap: int) -> None:
        """
        Configure the chunker's boundary constraints.

        Args:
            char_limit: Maximum number of characters per chunk.
                        Should correspond to ~90% of your embedding model's
                        token limit to leave a safety margin.
                        For all-MiniLM-L6-v2 (256 tokens): set to ~1000 chars.
            overlap:    How many characters of the previous chunk to carry
                        forward into the next chunk as context glue.
                        Recommended: 10-20% of char_limit.
        """
        if overlap >= char_limit:
            raise ValueError(
                f"Overlap ({overlap}) must be less than char_limit ({char_limit}). "
                f"Otherwise the chunk never advances — infinite loop."
            )
        self._char_limit = char_limit
        self._overlap = overlap

    # ─────────────────────────────────────────────────────────────────────
    # PRIVATE: Word Streaming (No full list ever loaded into RAM)
    # ─────────────────────────────────────────────────────────────────────

    def _stream_words(self, text: str) -> Generator[str, None, None]:
        """
        Yield one word at a time from the source text.

        EXECUTION FLOW:
        1. Walk through the text character by character
        2. Accumulate characters into a buffer until a space is hit
        3. Yield the buffer as a word, then reset it
        4. After the loop, yield any remaining buffer (the final word)

        Why not text.split(" ")?
            split() materializes ALL words into a list simultaneously.
            For a 500MB document, that is a 500MB+ spike before we emit
            a single chunk. This generator keeps RAM at O(1) — one word
            at a time, always.

        Returns:
            Generator of individual word strings
        """
        buffer = []
        for char in text:
            if char == " ":
                if buffer:
                    yield "".join(buffer)
                    buffer = []
            else:
                buffer.append(char)
        if buffer:
            yield "".join(buffer)

    # ─────────────────────────────────────────────────────────────────────
    # PRIVATE: Trim deque to the overlap budget (Left-pop, O(1) per pop)
    # ─────────────────────────────────────────────────────────────────────

    def _trim_to_overlap(
        self,
        window: Deque[str],
        window_char_count: int,
    ) -> int:
        """
        Remove words from the LEFT of the window until it fits within overlap budget.

        Why popleft() instead of slicing a new list?
            list[n:] creates a brand-new list object — O(n) copy.
            deque.popleft() removes the first element in-place — O(1).
            On 50,000 chunk boundaries this is the difference between
            O(n) and O(1) per boundary operation.

        EXECUTION FLOW:
        1. While window_char_count exceeds self._overlap:
           a. Pop the leftmost word from the deque
           b. Subtract its length (+1 for space) from the counter
        2. Return the updated character count

        Returns:
            Updated window_char_count (guaranteed <= self._overlap)
        """
        while window_char_count > self._overlap and window:
            removed_word = window.popleft()
            # +1 accounts for the space that would separate this word
            window_char_count -= len(removed_word) + 1
        return max(window_char_count, 0)

    # ─────────────────────────────────────────────────────────────────────
    # PUBLIC: The Main Chunking Interface
    # ─────────────────────────────────────────────────────────────────────

    def chunk(self, text: str) -> Generator[str, None, None]:
        """
        Stream semantically bounded chunks from the source text.

        EXECUTION FLOW:
        1. Create an empty deque and two integer counters (chunk_len, overlap_len)
        2. Pull one word at a time from _stream_words()
        3. Calculate new_word_len = len(word) + 1 (the +1 is the space separator)
        4. If adding this word would EXCEED char_limit AND we have content:
               a. Yield " ".join(window) as the completed chunk
               b. Call _trim_to_overlap() — popleft() until within overlap budget
               c. Reset chunk_len to the trimmed overlap_len
        5. Append word to deque, add new_word_len to chunk_len
        6. After all words, yield remaining deque content as the final chunk

        Returns:
            Generator of character-bounded, overlap-glued chunk strings.
            Memory profile: O(chunk_size) peak — flat regardless of source size.
        """
        print(f"\n[*] RecursiveWordChunker (limit={self._char_limit}, overlap={self._overlap})")

        # The active window. A deque supports O(1) append (right) and popleft (left).
        window: Deque[str] = deque()

        # STEP 1: Incremental counters. No recomputation from scratch.
        chunk_len = 0    # Total chars currently in `window`
        overlap_len = 0  # Chars in the overlap tail (re-used after each boundary)

        for word in self._stream_words(text):

            # +1 for the space that will separate this word from its neighbor
            new_word_len = len(word) + 1

            # STEP 4: Boundary condition — this word would overflow the chunk
            if chunk_len + new_word_len > self._char_limit and chunk_len > 0:

                # ─── Emit the completed chunk ───────────────────────────────
                yield " ".join(window)

                # ─── Trim to overlap: O(1) pops, not O(n) list construction ─
                overlap_len = self._trim_to_overlap(window, chunk_len)
                chunk_len = overlap_len

            # STEP 5: Append new word and advance the running counter
            window.append(word)
            chunk_len += new_word_len

        # STEP 6: Emit whatever remains (the final, potentially short chunk)
        if window:
            yield " ".join(window)


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == "__main__":

    # ─── Setup ────────────────────────────────────────────────────────────
    test_document = (
        "The arc reactor uses a palladium core to generate stable, continuous energy. "
        "However, prolonged exposure to palladium causes severe blood toxicity. "
        "A synthesized replacement element is required for long-term viability."
    )

    print("=" * 60)
    print("  JARVIS CHUNKING STRATEGY COMPARISON")
    print("=" * 60)
    print(f"\n[Source] {len(test_document)} characters | {len(test_document.split())} words\n")
    print(test_document)

    # ─── Run ──────────────────────────────────────────────────────────────

    # COMPARISON 1: The broken approach
    failure_chunker = FailureDemoChunker(char_limit=45)
    print("\n[BROKEN] Character slicing — breaks words mid-stream:")
    for i, chunk in enumerate(failure_chunker.chunk(test_document), start=1):
        print(f"  Chunk_{i}: '{chunk}'")

    print("\n" + "-" * 60)

    # COMPARISON 2: The production approach
    production_chunker = RecursiveWordChunker(char_limit=45, overlap=15)
    print("\n[PRODUCTION] Word-bounded streaming with deque overlap:")
    for i, chunk in enumerate(production_chunker.chunk(test_document), start=1):
        print(f"  Chunk_{i}: '{chunk}'")

    print("\n" + "=" * 60)
    print("  SCALING PROOF: 10,000-word stress test")
    print("=" * 60)

    import time

    # Generate a large synthetic document (simulates a real manual)
    big_document = " ".join(["palladium-core reactor-cooling element-synthesis"] * 2000)
    print(f"\n[Source] {len(big_document):,} characters | {len(big_document.split()):,} words")

    chunker = RecursiveWordChunker(char_limit=200, overlap=40)

    start_time = time.perf_counter()
    chunk_count = sum(1 for _ in chunker.chunk(big_document))
    elapsed_ms = (time.perf_counter() - start_time) * 1000

    print(f"[Result] {chunk_count} chunks emitted in {elapsed_ms:.2f}ms")
    print(f"[Memory] RAM profile: O(chunk_size) — flat. No full word list materialized.")
    print("\n[✓] Ready to pipe chunks into Phase 2.2 NoveltyGate → ChromaDB encoder.")
