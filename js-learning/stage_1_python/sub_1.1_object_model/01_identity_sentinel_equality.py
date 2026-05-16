"""
chroma_concepts_demo.py

JARVIS Learning Module: Where id(), is, ==, and sentinels appear
in a real ChromaDB-style workflow.

Run with:
    py -3.11 chroma_concepts_demo.py

NOTE: This script does NOT require ChromaDB installed.
      It simulates the patterns you'll encounter.
"""

from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Tuple


# =============================================================================
# CONCEPT 1: Sentinel Pattern — Distinguishing "not found" from "empty result"
# =============================================================================

_NOT_FOUND = object()  # Unique sentinel


def query_mock_database(doc_id: str) -> Any:
    """
    Simulates a ChromaDB query.
    
    WHY SENTINEL MATTERS:
    - ChromaDB can return `None` as a valid metadata value.
    - We need to distinguish "document not found" from "document found, 
      but its metadata field is None."
    """
    mock_db: Dict[str, Optional[str]] = {
        "doc_001": "Password reset instructions.",
        "doc_002": None,  # Valid document with no content (e.g., deleted)
    }
    
    return mock_db.get(doc_id, _NOT_FOUND)


def demo_sentinel_in_retrieval() -> None:
    print("=" * 60)
    print("CONCEPT 1: Sentinel Pattern in Document Retrieval")
    print("=" * 60)
    
    for doc_id in ["doc_001", "doc_002", "doc_999"]:
        result = query_mock_database(doc_id)
        
        if result is _NOT_FOUND:
            # CORRECT: Identity check for sentinel
            print(f"  {doc_id}: NOT IN DATABASE (would trigger re-indexing)")
        elif result is None:
            # CORRECT: Identity check for None
            print(f"  {doc_id}: EXISTS but content is None (tombstone record)")
        else:
            print(f"  {doc_id}: '{result}'")
    
    print()


# =============================================================================
# CONCEPT 2: `is None` vs `== None` — Checking Optional Fields
# =============================================================================

@dataclass
class DocumentChunk:
    """A chunk of text ready for embedding."""
    text: str
    source: str
    page_number: Optional[int] = None  # May be None for web sources


def demo_none_check() -> None:
    print("=" * 60)
    print("CONCEPT 2: `is None` for Optional Metadata Fields")
    print("=" * 60)
    
    chunks = [
        DocumentChunk(text="Hello", source="manual.pdf", page_number=42),
        DocumentChunk(text="World", source="website.com", page_number=None),
    ]
    
    for chunk in chunks:
        # CORRECT: Use `is None` for Optional checks.
        # Why? Some objects override `__eq__` and `x == None` may behave unexpectedly.
        if chunk.page_number is None:
            print(f"  '{chunk.source}': No page number (web source)")
        else:
            print(f"  '{chunk.source}': Page {chunk.page_number}")
    
    print()


# =============================================================================
# CONCEPT 3: `==` for Value Comparison — Deduplication Before Ingestion
# =============================================================================

def demo_deduplication() -> None:
    print("=" * 60)
    print("CONCEPT 3: `==` for Deduplication (Value Comparison)")
    print("=" * 60)
    
    # Two chunks with identical content but created separately.
    chunk_a = DocumentChunk(text="Reset your password via Settings.", source="faq.md")
    chunk_b = DocumentChunk(text="Reset your password via Settings.", source="help.md")
    
    print(f"  chunk_a.text: '{chunk_a.text}'")
    print(f"  chunk_b.text: '{chunk_b.text}'")
    print()
    
    # WRONG: `is` checks identity (same object in RAM)
    print(f"  chunk_a.text is chunk_b.text → {chunk_a.text is chunk_b.text}")
    print("    ^ May be True due to string interning, but UNRELIABLE!")
    print()
    
    # CORRECT: `==` checks value (same content)
    print(f"  chunk_a.text == chunk_b.text → {chunk_a.text == chunk_b.text}")
    print("    ^ Always correct for deduplication.")
    print()
    
    # DEDUPLICATION LOGIC:
    seen_texts = set()
    for chunk in [chunk_a, chunk_b]:
        if chunk.text in seen_texts:  # Uses __hash__ and __eq__
            print(f"  SKIP: Duplicate content from '{chunk.source}'")
        else:
            seen_texts.add(chunk.text)
            print(f"  ADD: Ingesting from '{chunk.source}'")
    
    print()


# =============================================================================
# CONCEPT 4: id() for Debugging — Tracking Object Identity
# =============================================================================

def demo_id_for_debugging() -> None:
    print("=" * 60)
    print("CONCEPT 4: id() for Debugging Object Mutations")
    print("=" * 60)
    
    # Simulating a cache that stores embeddings.
    embedding_cache: Dict[str, Tuple[float, ...]] = {}
    
    # Create an embedding vector.
    embedding_v1 = (0.1, 0.2, 0.3)
    embedding_cache["doc_001"] = embedding_v1
    
    print(f"  Stored embedding at id: {id(embedding_v1):#x}")
    
    # Later, another part of the code retrieves it...
    retrieved = embedding_cache["doc_001"]
    
    print(f"  Retrieved embedding at id: {id(retrieved):#x}")
    print(f"  Same object? {retrieved is embedding_v1}")
    print()
    
    # SAFELY CREATE A NEW OBJECT: Mutation no longer affects the cached object!
    new_embedding = retrieved + (0.4,)  # Creates a new tuple
    
    print(f"  After modification: embedding_v1 = {embedding_v1}")
    print(f"  New embedding      = {new_embedding}")
    print("    ^ The cache remains uncorrupted!")
    print()


# =============================================================================
# CONCEPT 5: Interning Trap — Why `is` Fails for Computed Strings
# =============================================================================

def demo_interning_trap() -> None:
    print("=" * 60)
    print("CONCEPT 5: String Interning Trap")
    print("=" * 60)
    
    # Static strings may be interned.
    id_a = "doc_001"
    id_b = "doc_001"
    print(f"  Static: 'doc_001' is 'doc_001' → {id_a is id_b}  (often True, interned)")
    
    # Dynamically constructed strings are NOT interned.
    id_c = "doc_" + "001"
    id_d = f"doc_{1:03d}"
    
    print(f"  Dynamic: 'doc_' + '001' → {id_c}")
    print(f"  Dynamic: f'doc_{{1:03d}}' → {id_d}")
    print(f"  id_c is id_d → {id_c is id_d}  (often False! different objects)")
    print(f"  id_c == id_d → {id_c == id_d}  (True, same value)")
    print()
    
    print("  RULE: NEVER use `is` to compare document IDs. Use `==`.")
    print()


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    demo_sentinel_in_retrieval()
    demo_none_check()
    demo_deduplication()
    demo_id_for_debugging()
    demo_interning_trap()
    
    print("=" * 60)
    print("SUMMARY: When to Use What")
    print("=" * 60)
    print("""
  | Use Case                          | Operator     |
  |-----------------------------------|--------------|
  | Check if variable is None         | `is None`    |
  | Check for sentinel (missing key)  | `is SENTINEL`|
  | Compare document IDs or content   | `==`         |
  | Debug object identity in logs     | `id(obj)`    |
  | NEVER use `is` for:               | Values!      |
""")
