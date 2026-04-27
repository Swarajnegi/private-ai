"""
03_metadata_filtering.py

JARVIS Memory Layer: Mastering Semantic + Structured Retrieval

Run with:
    python 03_metadata_filtering.py

This script demonstrates:
    1. Metadata Assignment — Attaching structured key-value pairs to vectors
    2. Boolean Filtering — Using '$and' and '$or' logic in queries
    3. Field-Specific Queries — Filtering by source, date, and category
    4. Combined Search — Executing semantic search within a metadata-filtered subset

=============================================================================
THE BIG PICTURE: Precision Retrieval
=============================================================================

Without Metadata Filtering (the naive way):
    → You embed a thousand documents.
    → You ask: "How do I use async/await in Python?"
    → The system returns the top 5 most semantically similar chunks.
    → If your DB contains both "Python tutorials" and "C++ concurrency docs",
      you might get C++ results that happen to use similar language.
    → You get noise.

With Metadata Filtering (the smart way):
    → You tag documents: { "language": "python", "type": "tutorial" }.
    → You ask: "How do I use async/await in Python?" + Filter: { "language": "python" }.
    → The system ignores all C++, Java, and Rust docs immediately.
    → You get high-signal, relevant results only.

=============================================================================
THE FLOW (Step by Step Execution Order)
=============================================================================

STEP 1: Initialize local ChromaDB and Embedding Model
        ↓
STEP 2: Populate collection with diverse data (Research, Code, Notes)
        ↓
STEP 3: Perform 'Broad' Semantic Search (No filters)
        ↓
STEP 4: Perform 'Targeted' Semantic Search (Using Metadata filters)
        ↓
STEP 5: Compare results to demonstrate precision gain

=============================================================================
"""

import os
import chromadb
from typing import List, Dict, Any
from datetime import datetime

# =============================================================================
# Part 1: Setup (Initialization)
# =============================================================================

class JarvisMetadataEngine:
    """
    LAYER: Memory (Sub-layer: Vector Storage)

    Purpose:
        Demonstrate combining semantic similarity with structured metadata filtering.
        Enforces 'Novelty Gate' (Deduplication) and 'Truncation Guards' (Window safety).

    How it works:
        - Creates a persistent ChromaDB instance.
        - Verifies document length before embedding to prevent silent data loss.
        - Checks for existing content to skip redundant computations.
    """

    def __init__(self, db_path: str = "./demo_metadata_db"):
        self.db_path = db_path
        self._closed = False
        # ─────────────────────────────────────────────────────────────────────
        # SECTION: Resource Setup
        # ─────────────────────────────────────────────────────────────────────
        from sentence_transformers import SentenceTransformer
        self.client = chromadb.PersistentClient(path=self.db_path)
        self.encoder = SentenceTransformer("all-MiniLM-L6-v2")
        self.collection = self.client.get_or_create_collection(name="metadata_demo_collection")

        # Clear previous demo data to ensure clean run
        self.client.delete_collection("metadata_demo_collection")
        self.collection = self.client.get_or_create_collection(name="metadata_demo_collection")

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensures cleanup."""
        self.close()

    def __del__(self):
        """Destructor - final cleanup."""
        self.close()

    def close(self):
        """Forcefully close ChromaDB resources."""
        if self._closed:
            return

        try:
            # Force ChromaDB cleanup
            if hasattr(self, 'collection'):
                del self.collection
            if hasattr(self, 'client'):
                del self.client
            self._closed = True
        except:
            pass

    def ingest_demo_data(self):
        """
        Populates the database with varied knowledge to test filtering.

        EXECUTION FLOW:
        1. Define a set of heterogeneous documents.
        2. Attach rich metadata (source, type, year, language).
        3. Batch add to ChromaDB.
        """
        print("[*] Ingesting heterogeneous demo data...")

        documents = [
            "Python's asyncio provides a way to write concurrent code using async/await syntax.",
            "In C++, concurrency is handled via std::thread and mutexes.",
            "The transformer architecture relies on self-attention mechanisms to weight input importance.",
            "Research paper: Attention is All You Need (2017) introduced the Transformer.",
            "A quick note on my grocery list: milk, eggs, and coffee.",
            "Python decorators allow you to wrap functions with extra logic.",
            "The Rust ownership model prevents memory safety issues at compile time.",
            "A research paper on LLM efficiency: Scaling Laws for Neural Language Models (2020)."
        ]

        metadatas = [
            {"source": "tutorial", "type": "code", "language": "python", "year": 2023},
            {"source": "tutorial", "type": "code", "language": "cpp", "year": 2022},
            {"source": "research", "type": "theory", "topic": "transformers", "year": 2017},
            {"source": "research", "type": "theory", "topic": "transformers", "year": 2017},
            {"source": "note", "type": "personal", "category": "shopping", "year": 2024},
            {"source": "tutorial", "type": "code", "language": "python", "year": 2024},
            {"source": "tutorial", "type": "code", "language": "rust", "year": 2023},
            {"source": "research", "type": "theory", "topic": "llm", "year": 2020},
        ]

        ids = [f"id_{i}" for i in range(len(documents))]

        # ─────────────────────────────────────────────────────────────────────
        # STEP 1: NOVELTY GATE (Deduplication)
        # ─────────────────────────────────────────────────────────────────────
        if self.collection.count() > 0:
            print(f"    [!] Novelty Gate: {self.collection.count()} documents already exist. Skipping redundant ingestion.")
            return

        # ─────────────────────────────────────────────────────────────────────
        # STEP 2: TRUNCATION CHECK (Window Safety)
        # ─────────────────────────────────────────────────────────────────────
        for i, doc in enumerate(documents):
            word_count = len(doc.split())
            if word_count > 200:
                print(f"    [WARNING] Silent Truncation Risk: Doc {i} is {word_count} words. Limit is ~200.")

        # ─────────────────────────────────────────────────────────────────────
        # STEP 3: EXPLICIT EMBEDDINGS (Origin Tracing)
        # ─────────────────────────────────────────────────────────────────────
        embeddings = self.encoder.encode(documents).tolist()

        self.collection.add(
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )
        print(f"    [+] Ingested {len(documents)} documents.")

    def run_queries(self, query_text: str):
        """
        Executes different tiers of retrieval.

        EXECUTION FLOW:
        1. Perform un-filtered semantic search.
        2. Perform filtered search (e.g., language='python').
        3. Perform complex logical search (e.g., research AND transformers).
        """
        print(f"\n{'='*60}")
        print(f"QUERY: '{query_text}'")
        print(f"{'='*60}")

        # 1. BROAD SEMANTIC SEARCH (No Filter)
        print("\n[1] BROAD SEMANTIC SEARCH (Unfiltered):")
        query_embeddings = self.encoder.encode([query_text]).tolist()
        results = self.collection.query(query_embeddings=query_embeddings, n_results=3)
        self._print_results(results)

        # 2. TARGETED FILTERED SEARCH (Single Field)
        # Note: Since we are looking for "concurrency/async", we want to restrict to python
        print("\n[2] TARGETED SEARCH (Filter: language == 'python'):")
        try:
            query_embeddings = self.encoder.encode([query_text]).tolist()
            results = self.collection.query(
                query_embeddings=query_embeddings,
                n_results=3,
                where={"language": "python"}
            )
            self._print_results(results)
        except Exception as e:
            print(f"    [!] Filter error: {e}")

        # 3. COMPLEX LOGICAL SEARCH (Boolean Logic)
        # Let's look for research papers specifically about Transformers
        print("\n[3] COMPLEX SEARCH (Filter: type == 'theory' AND topic == 'transformers'):")
        try:
            query_embeddings = self.encoder.encode(["transformer architecture"]).tolist()
            results = self.collection.query(
                query_embeddings=query_embeddings,
                n_results=2,
                where={
                    "$and": [
                        {"type": "theory"},
                        {"topic": "transformers"}
                    ]
                }
            )
            self._print_results(results)
        except Exception as e:
            print(f"    [!] Boolean error: {e}")

    def _print_results(self, results: Dict[str, Any]):
        """Helper to format ChromaDB output."""
        if not results['documents'][0]:
            print("    [-] No results found.")
            return

        for i in range(len(results['documents'][0])):
            doc = results['documents'][0][i]
            meta = results['metadatas'][0][i]
            dist = results['distances'][0][i]
            print(f"    ({i+1}) [Dist: {dist:.4f}] {doc}")
            print(f"        Metadata: {meta}")

    def cleanup(self):
        """Removes the demo database with Windows file handle cleanup."""
        print(f"\n[*] Cleaning up demo database at {self.db_path}")
        if not os.path.exists(self.db_path):
            return

        # Force close ChromaDB client and connections
        if hasattr(self, 'client'):
            del self.client
            self.client = None

        import gc
        gc.collect()
        import time
        time.sleep(0.5)  # Allow Windows to release file handles

        import shutil
        max_retries = 5
        for attempt in range(max_retries):
            try:
                shutil.rmtree(self.db_path)
                print(f"    [✓] Cleanup successful (attempt {attempt + 1})")
                break
            except PermissionError as e:
                if attempt < max_retries - 1:
                    print(f"    [!] Retry {attempt + 1}/{max_retries} after delay...")
                    time.sleep(1.0)
                    gc.collect()
                else:
                    print(f"    [!] Warning: Could not remove {self.db_path}: {e}")
                    print(f"    [*] Suggestion: Restart Python or delete manually")

# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    # Setup
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    DEMO_DIR = os.path.join(SCRIPT_DIR, "demo_metadata_db")

    # Cleanup any existing database first
    import shutil
    if os.path.exists(DEMO_DIR):
        try:
            shutil.rmtree(DEMO_DIR, ignore_errors=True)
        except:
            print("[*] Could not remove existing database, continuing...")

    # Use context manager for proper resource cleanup
    try:
        with JarvisMetadataEngine(db_path=DEMO_DIR) as demo:
            # Run
            demo.ingest_demo_data()

            # Scenario 1: Concurrency/Async (Testing Python vs C++)
            demo.run_queries("How is concurrency handled?")

            # Scenario 2: Transformers (Testing Topic/Type)
            demo.run_queries("Tell me about transformers")
    except Exception as e:
        print(f"[!!!] CRITICAL ERROR: {e}")
    finally:
        # Manual cleanup as fallback
        try:
            if os.path.exists(DEMO_DIR):
                import time
                time.sleep(0.5)  # Allow Windows to release handles
                shutil.rmtree(DEMO_DIR, ignore_errors=True)
        except:
            pass
        print("\n[*] Demo complete. (On Windows, test directory may remain due to file locking)")
