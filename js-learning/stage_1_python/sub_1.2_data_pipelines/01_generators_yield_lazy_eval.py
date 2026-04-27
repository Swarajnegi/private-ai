"""
01_generators_yield_lazy_eval.py

JARVIS Learning Module: Generators, Yield, and Lazy Evaluation for Streaming Data.

Run with:
    python 01_generators_yield_lazy_eval.py

This script demonstrates the COMPLETE ingestion pipeline:
    1. StreamingDocumentLoader — Reads one PDF at a time using yield
    2. NoveltyGate — Checks if document already exists in memory (deduplication)
    3. ChunkingEngine — Splits document into smaller pieces for embedding
    4. VectorStore — Stores the chunks (ChromaDB placeholder)

=============================================================================
THE BIG PICTURE: What happens when you tell JARVIS to ingest 500 PDFs?
=============================================================================

Without generators (the naive way):
    → Load ALL 500 PDFs into RAM at once (8 GB+)
    → RAM explodes, Python crashes with "Out of Memory" error

With generators (the smart way):
    → Load PDF #1 into RAM
    → Process it (check if new, chunk it, store it)
    → Delete PDF #1 from RAM
    → Load PDF #2 into RAM
    → Repeat...
    → Peak RAM usage: ~20 MB (only one PDF at a time!)

=============================================================================
THE FLOW (Step by Step Execution Order)
=============================================================================

STEP 1: User asks JARVIS to ingest a folder of documents
        ↓
STEP 2: StreamingDocumentLoader.stream() starts iterating over files
        ↓
STEP 3: For each file:
        a) Read file bytes into RAM
        b) Extract text content
        c) YIELD the document → execution PAUSES here
        ↓
STEP 4: The main loop (consumer) receives one document
        ↓
STEP 5: NoveltyGate checks: "Is this document already in JARVIS's memory?"
        - If YES: Skip it (don't re-store duplicates)
        - If NO: Continue to chunking
        ↓
STEP 6: ChunkingEngine splits the document into smaller pieces
        ↓
STEP 7: VectorStore saves the chunks to ChromaDB
        ↓
STEP 8: Main loop asks for next document → generator RESUMES at yield
        ↓
STEP 9: Previous document's data goes out of scope → garbage collected
        ↓
        (Repeat STEP 3-9 for all 500 documents)

=============================================================================
"""

from pathlib import Path
from dataclasses import dataclass, field
from typing import Generator, Optional
import hashlib


# =============================================================================
# Part 1: DATA STRUCTURES (What gets passed between layers)
# =============================================================================

@dataclass
class Document:
    """
    Holds ONE document's information.
    
    This is like a container that travels through the pipeline.
    At any moment, only ONE Document object is "active" in memory.
    """
    path: Path           # Where the file lives on disk
    content: str         # The actual text content
    content_hash: str    # Fingerprint to detect exact duplicates
    embedding: Optional[list[float]] = None  # Vector for semantic comparison


@dataclass
class Chunk:
    """
    A smaller piece of a document.
    
    Large documents get split into chunks because:
    1. Embedding models have token limits (usually ~512 tokens)
    2. Smaller chunks give more precise search results
    """
    text: str
    source_doc_hash: str
    chunk_index: int


# =============================================================================
# Part 2: THE PRODUCER (StreamingDocumentLoader)
# =============================================================================

class StreamingDocumentLoader:
    """
    LAYER 1: Reads documents one at a time.
    
    HOW `yield` WORKS (in simple terms):
    
    Normal function with `return`:
        def get_all_docs():
            docs = []
            for f in files:
                docs.append(read_file(f))  # All files loaded into list
            return docs  # Returns EVERYTHING at once, uses tons of RAM
    
    Generator function with `yield`:
        def stream_docs():
            for f in files:
                doc = read_file(f)  # Load ONE file
                yield doc           # Hand it over, then PAUSE here
                # When consumer asks for next, resume from this line
    
    Think of `yield` as "give this one item and wait for the consumer to ask for more"
    """

    def __init__(self, folder: Path):
        self.folder = folder

    def stream(self) -> Generator[Document, None, None]:
        """
        Yields documents one by one.
        
        EXECUTION FLOW:
        1. Find a file
        2. Read its content into RAM
        3. Create a Document object with the content
        4. YIELD it → function PAUSES, control returns to caller
        5. When caller calls next(), execution RESUMES here
        6. Old document data becomes garbage-collectable
        7. Loop continues to next file
        """
        print(f"\n[Loader] Scanning folder: {self.folder}")
        
        for file_path in self.folder.glob("*.txt"):  # Using .txt for demo
            print(f"\n[Loader] Loading: {file_path.name}")
            
            # ─────────────────────────────────────────────────────────────
            # MEMORY ALLOCATION: This is the only time file content is in RAM
            # ─────────────────────────────────────────────────────────────
            content = file_path.read_text(encoding="utf-8")
            content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
            
            doc = Document(
                path=file_path,
                content=content,
                content_hash=content_hash,
            )
            
            # ─────────────────────────────────────────────────────────────
            # YIELD POINT: Execution pauses here until consumer asks for next
            # ─────────────────────────────────────────────────────────────
            yield doc
            
            # ─────────────────────────────────────────────────────────────
            # AFTER YIELD: When we resume here, the consumer is done with `doc`
            # The `doc` variable will be overwritten in the next iteration,
            # making the OLD Document object garbage-collectable
            # ─────────────────────────────────────────────────────────────
            print(f"[Loader] Done with {file_path.name}, memory can be reclaimed")


# =============================================================================
# Part 3: EMBEDDING MODEL (For Semantic Comparison)
# =============================================================================

class MockEmbeddingModel:
    """
    LAYER: Memory (Embedding Subsystem)
    
    Converts text into a vector (list of numbers) that captures its meaning.
    Similar texts will have similar vectors, even if the words are different.
    
    In real JARVIS:
        This would be: SentenceTransformer('all-MiniLM-L6-v2')
    
    For demo:
        We create a fake 5-dimensional vector based on keyword presence.
        This is enough to demonstrate the concept without needing ML libraries.
    """
    
    def embed(self, text: str) -> list[float]:
        """
        Convert text to a vector.
        
        EXECUTION FLOW:
        1. Check which keywords appear in the text
        2. Create a vector: 1.0 if keyword present, 0.0 if not
        3. Normalize to unit length (required for cosine similarity)
        4. Return the vector
        """
        # Keywords that define our "semantic space" for demo
        keywords = ["python", "generator", "yield", "memory", "jarvis", "rag", "async"]
        
        # Create vector: 1.0 if keyword present, 0.0 if not
        vector = [1.0 if kw in text.lower() else 0.0 for kw in keywords]
        
        # Normalize to unit length (so cosine similarity works correctly)
        magnitude = sum(v**2 for v in vector) ** 0.5
        if magnitude > 0:
            vector = [v / magnitude for v in vector]
        
        return vector


# =============================================================================
# Part 4: THE NOVELTY GATE (Hybrid Deduplication Layer)
# =============================================================================

class HybridNoveltyGate:
    """
    LAYER 2: Checks if a document is NEW or already in JARVIS's memory.
    
    THIS IS THE LAYER YOU ASKED ABOUT!
    
    It sits BETWEEN:
        - Yield (document loaded into RAM)
        - Storage (document saved to ChromaDB)
    
    Purpose:
        - Prevent storing duplicate documents
        - Catch EXACT duplicates (same bytes) via hash comparison
        - Catch SEMANTIC duplicates (same meaning) via embedding comparison
        - Save embedding costs and keep ChromaDB clean
    
    How it works (Two-Stage Check):
        STAGE 1 (Fast): Check if content hash exists (catches exact copies)
        STAGE 2 (Smart): Check if embedding is similar to existing docs
        
        Why two stages?
        - Hash check is instant (O(1) lookup)
        - Embedding check is expensive (needs vector math)
        - Hash first = skip expensive check for obvious duplicates
    """

    def __init__(
        self,
        embedding_model: MockEmbeddingModel,
        similarity_threshold: float = 0.85,
    ):
        self._embedding_model = embedding_model
        self._threshold = similarity_threshold
        
        # Stage 1: Hash-based lookup (for exact duplicates)
        self._known_hashes: set[str] = set()
        
        # Stage 2: Embedding-based lookup (for semantic duplicates)
        self._known_embeddings: list[tuple[str, list[float]]] = []  # (doc_name, embedding)

    def is_novel(self, doc: Document) -> bool:
        """
        Check if this document is new to JARVIS.
        
        EXECUTION FLOW:
        1. Check hash set (fast path for exact duplicates)
        2. If not exact duplicate, compute embedding
        3. Compare embedding against all known embeddings
        4. If similarity > threshold, it's a semantic duplicate
        5. Return True only if both checks pass
        
        Returns:
            True if document is NEW and should be stored
            False if document is a DUPLICATE and should be skipped
        """
        # ─────────────────────────────────────────────────────────────
        # STAGE 1: Hash Check (Fast Path)
        # ─────────────────────────────────────────────────────────────
        if doc.content_hash in self._known_hashes:
            print(f"[NoveltyGate] EXACT DUPLICATE: {doc.path.name} (identical bytes)")
            return False
        
        # ─────────────────────────────────────────────────────────────
        # STAGE 2: Semantic Check (Smart Path)
        # ─────────────────────────────────────────────────────────────
        # Compute embedding for the new document
        doc.embedding = self._embedding_model.embed(doc.content)
        
        # Compare against all known embeddings
        for known_name, known_embedding in self._known_embeddings:
            similarity = self._cosine_similarity(doc.embedding, known_embedding)
            
            if similarity >= self._threshold:
                print(
                    f"[NoveltyGate] SEMANTIC DUPLICATE: {doc.path.name} "
                    f"is {similarity:.0%} similar to {known_name}"
                )
                return False
        
        print(f"[NoveltyGate] NOVEL: {doc.path.name} (new content)")
        return True

    def register(self, doc: Document) -> None:
        """Mark a document as known (after successful storage)."""
        self._known_hashes.add(doc.content_hash)
        
        # Ensure embedding exists before storing
        if doc.embedding is None:
            doc.embedding = self._embedding_model.embed(doc.content)
        
        self._known_embeddings.append((doc.path.name, doc.embedding))
    
    def _cosine_similarity(self, vec_a: list[float], vec_b: list[float]) -> float:
        """
        Compute cosine similarity between two vectors.
        
        Cosine similarity measures how similar two vectors are in direction.
        
        Returns:
            1.0 = identical direction (same meaning)
            0.0 = orthogonal (unrelated topics)
           -1.0 = opposite direction (contradictory)
        
        Formula: dot(A, B) / (||A|| * ||B||)
        """
        dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
        magnitude_a = sum(a**2 for a in vec_a) ** 0.5
        magnitude_b = sum(b**2 for b in vec_b) ** 0.5
        
        if magnitude_a == 0 or magnitude_b == 0:
            return 0.0
        
        return dot_product / (magnitude_a * magnitude_b)


# =============================================================================
# Part 5: THE CHUNKING ENGINE
# =============================================================================

class ChunkingEngine:
    """
    LAYER 3: Splits a document into smaller pieces.
    
    Why chunk?
    - Embedding models have limits (e.g., 512 tokens max)
    - Smaller chunks = more precise RAG search results
    - "What did the author say about X?" → returns the exact paragraph
    """

    def __init__(self, chunk_size: int = 200):
        self.chunk_size = chunk_size  # Characters per chunk (simplified)

    def chunk(self, doc: Document) -> Generator[Chunk, None, None]:
        """
        Split document into chunks.
        
        Note: This is ALSO a generator!
        We don't create a list of all chunks at once.
        We yield one chunk at a time.
        """
        text = doc.content
        chunk_index = 0
        
        for i in range(0, len(text), self.chunk_size):
            chunk_text = text[i : i + self.chunk_size]
            
            yield Chunk(
                text=chunk_text,
                source_doc_hash=doc.content_hash,
                chunk_index=chunk_index,
            )
            
            chunk_index += 1
        
        print(f"[Chunker] Split into {chunk_index} chunks")


# =============================================================================
# Part 6: THE VECTOR STORE (ChromaDB Placeholder)
# =============================================================================

class VectorStore:
    """
    LAYER 4: Stores chunks in ChromaDB (this is a demo placeholder).
    
    In real JARVIS:
        - This would connect to ChromaDB
        - Embed each chunk using an embedding model
        - Store the embedding + text in the vector database
    """

    def __init__(self):
        self._storage: list[Chunk] = []  # Demo storage

    def store(self, chunk: Chunk) -> None:
        """Save a chunk to the vector database."""
        self._storage.append(chunk)
        # In real code: chromadb_collection.add(...)

    def count(self) -> int:
        """Return total stored chunks."""
        return len(self._storage)


# =============================================================================
# Part 7: THE ORCHESTRATOR (Puts it all together)
# =============================================================================

def run_ingestion_pipeline(folder: Path) -> None:
    """
    The main pipeline that coordinates all layers.
    
    EXECUTION ORDER (numbered to match the diagram above):
    """
    # Initialize all components
    loader = StreamingDocumentLoader(folder)                    # Layer 1
    embedding_model = MockEmbeddingModel()                      # For semantic comparison
    novelty_gate = HybridNoveltyGate(embedding_model)           # Layer 2 (hash + semantic)
    chunker = ChunkingEngine(chunk_size=100)                    # Layer 3
    store = VectorStore()                                       # Layer 4

    docs_processed = 0
    docs_skipped = 0

    print("=" * 60)
    print("STARTING INGESTION PIPELINE")
    print("=" * 60)

    # ─────────────────────────────────────────────────────────────────────
    # THE MAIN LOOP: This is where the magic happens
    # ─────────────────────────────────────────────────────────────────────
    # The `for` loop automatically calls next() on the generator.
    # Each iteration:
    #   1. Generator runs until it hits `yield`
    #   2. Yielded value becomes `doc`
    #   3. We process `doc`
    #   4. Loop asks for next item → generator resumes
    # ─────────────────────────────────────────────────────────────────────
    
    for doc in loader.stream():  # ← This calls the generator
        
        # STEP 5: Check if document is new
        if not novelty_gate.is_novel(doc):
            docs_skipped += 1
            continue  # Skip to next document
        
        # STEP 6: Split into chunks
        for chunk in chunker.chunk(doc):  # ← This is also a generator!
            # STEP 7: Store each chunk
            store.store(chunk)
        
        # Mark document as known (for future deduplication)
        novelty_gate.register(doc)
        docs_processed += 1
        
        # STEP 8-9: Loop continues, old doc becomes garbage-collectable

    # ─────────────────────────────────────────────────────────────────────
    # SUMMARY
    # ─────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("PIPELINE COMPLETE")
    print("=" * 60)
    print(f"Documents processed: {docs_processed}")
    print(f"Documents skipped (duplicates): {docs_skipped}")
    print(f"Total chunks stored: {store.count()}")


# =============================================================================
# Part 8: DEMO SETUP
# =============================================================================

def create_demo_files(demo_folder: Path) -> None:
    """Create some test files for the demo."""
    demo_folder.mkdir(exist_ok=True)
    
    # Create 3 unique documents
    (demo_folder / "doc1.txt").write_text(
        "JARVIS is a private cognitive operating system. "
        "It uses RAG (Retrieval Augmented Generation) to remember everything. "
        "The memory layer stores embeddings in ChromaDB."
    )
    
    (demo_folder / "doc2.txt").write_text(
        "Generators in Python use the yield keyword. "
        "They produce values one at a time, saving memory. "
        "This is called lazy evaluation."
    )
    
    (demo_folder / "doc3.txt").write_text(
        "The Brain component handles reasoning and planning. "
        "It orchestrates multiple LLM calls and tools. "
        "The Body component interfaces with robotics."
    )
    
    # Create a DUPLICATE of doc1 with a different name (EXACT duplicate)
    (demo_folder / "doc1_copy.txt").write_text(
        "JARVIS is a private cognitive operating system. "
        "It uses RAG (Retrieval Augmented Generation) to remember everything. "
        "The memory layer stores embeddings in ChromaDB."
    )
    
    # Create a SEMANTIC duplicate of doc2 (same meaning, different words)
    (demo_folder / "doc4_paraphrase.txt").write_text(
        "Python's yield statement creates generator functions. "
        "These generators output values lazily, one at a time. "
        "This approach conserves memory by not loading everything at once."
    )
    
    print("[Setup] Created 5 demo files:")
    print("        - doc1.txt (original about JARVIS)")
    print("        - doc2.txt (original about generators)")
    print("        - doc3.txt (original about Brain/Body)")
    print("        - doc1_copy.txt (EXACT duplicate of doc1)")
    print("        - doc4_paraphrase.txt (SEMANTIC duplicate of doc2)")


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    # Setup demo folder
    demo_folder = Path(__file__).parent / "demo_documents"
    create_demo_files(demo_folder)
    
    # Run the pipeline
    run_ingestion_pipeline(demo_folder)
    
    # Cleanup
    print("\n[Cleanup] Removing demo files...")
    for f in demo_folder.glob("*.txt"):
        f.unlink()
    demo_folder.rmdir()
    print("[Cleanup] Done")
