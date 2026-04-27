"""
02_chromadb_wrapper.py

JARVIS Memory Layer: Production-grade OOP wrapper for ChromaDB.

Run with:
    python 02_chromadb_wrapper.py

This script demonstrates:
    1. Memory Isolation — Managing multiple discrete specialist collections.
    2. Batch Ingestion — Safely generator-based document insertion.
    3. Filtered Retrieval — Cleanly abstracting Chroma's query API.

=============================================================================
THE BIG PICTURE
=============================================================================

Without `JarvisMemoryLayer`:
    → The Orchestrator interacts directly with ChromaDB primitives.
    → Metadata schemas drift across different scripts.
    → Batching limits are ignored, causing OOM crashes on ingestion.

With `JarvisMemoryLayer`:
    → The Orchestrator says: `memory.recall(query, domain="optics")`.
    → The wrapper handles DB connections, embedding limits, and DB schema.
    → Collections are strictly isolated by domain/specialist.

=============================================================================
THE FLOW (Step by Step Execution Order)
=============================================================================

STEP 1: Instantiate JarvisMemoryLayer (connects to SQLite DB on disk)
        ↓
STEP 2: Request a Collection (e.g., 'chemist_knowledge')
        ↓
STEP 3: Stream chunks into `ingest_stream()` (processes in safe batches)
        ↓
STEP 4: Call `recall()` to project a query string into semantic space and retrieve
        ↓
STEP 5: Return standardized dictionary to the LLM context window

=============================================================================
"""

import os
from typing import Generator, List, Dict, Any, Optional
from itertools import islice

# 3rd Party
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

# =============================================================================
# Part 1: THE MEMORY WRAPPER
# =============================================================================

class JarvisMemoryLayer:
    """
    LAYER 4: The Vector Store Wrapper for JARVIS long-term memory.
    
    Purpose:
        - Abstract raw ChromaDB interactions away from the Brain (LLMs).
        - Enforce batch-size limits to prevent RAM explosion during ingestion.
        - Implicitly handle embedding generation so the Orchestrator just sends strings.
    
    How it works:
        - Connects to a persistent Chroma SQLite file.
        - Maintains a local memory instance of `all-MiniLM-L6-v2` for on-the-fly embedding.
        - Provides generator-friendly ingestion to keep memory footprints completely flat.
    """
    
    def __init__(self, db_path: str = "./jarvis_chroma_db", model_name: str = "all-MiniLM-L6-v2"):
        """
        Connect to the DB and load the embedding model.
        
        EXECUTION FLOW:
        1. Initialize Chroma PersistentClient to target directory.
        2. Load SentenceTransformer model into RAM/VRAM.
        """
        print(f"[SYSTEM] Booting Memory Layer at {db_path}...")
        
        # Disable telemetry and set strict persistence
        self.client = chromadb.PersistentClient(
            path=db_path,
            settings=Settings(anonymized_telemetry=False)
        )
        
        print(f"[SYSTEM] Loading Embedding Engine: {model_name}...")
        self.encoder = SentenceTransformer(model_name)
    
    def _create_batches(self, iterable, batch_size: int) -> Generator[List[Any], None, None]:
        """
        Memory-safe batching for infinite streams.
        Yields chunks of size `batch_size` without materializing the whole list.
        """
        iterator = iter(iterable)
        while batch := list(islice(iterator, batch_size)):
            yield batch

    def ingest_stream(self, collection_name: str, document_stream: Generator[Dict[str, Any], None, None], batch_size: int = 100) -> None:
        """
        Safely ingest an infinite stream of documents into a collection.
        
        EXECUTION FLOW:
        1. Get or create the target collection.
        2. Read `batch_size` items from the generator.
        3. Vectorize the batch of text.
        4. Push to SQLite queue.
        5. Repeat until stream is exhausted.
        
        Args:
            collection_name: Target namespace (e.g., "science_papers").
            document_stream: Yields dicts with keys: 'id', 'text', 'metadata'
            batch_size: Max vectors to process simultaneously.
        """
        collection = self.client.get_or_create_collection(name=collection_name)
        
        print(f"[MEMORY] Beginning ingestion into '{collection_name}' (Batch size: {batch_size})")
        
        for batch_index, batch in enumerate(self._create_batches(document_stream, batch_size)):
            ids = [doc['id'] for doc in batch]
            texts = [doc['text'] for doc in batch]
            metadatas = [doc.get('metadata', {}) for doc in batch]
            
            # Embed the batch
            embeddings = self.encoder.encode(texts).tolist()
            
            # Add to vector DB
            collection.add(
                ids=ids,
                documents=texts,
                embeddings=embeddings,
                metadatas=metadatas
            )
            print(f"  -> Ingested batch {batch_index + 1} ({len(batch)} items)")
            
    def recall(self, collection_name: str, query: str, top_k: int = 3, where_filter: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Retrieve context for the LLM.
        
        EXECUTION FLOW:
        1. Check if collection exists.
        2. Convert query string -> 384-dim vector.
        3. Have ChromaDB SQLite apply `where_filter` to drop irrelevant rows.
        4. Calculate Cosine Distance on remaining vectors.
        5. Format and return highest matches.
        """
        try:
            collection = self.client.get_collection(name=collection_name)
        except Exception:
            print(f"[WARNING] Collection '{collection_name}' does not exist.")
            return []
            
        # 1. Embed query
        query_vector = self.encoder.encode(query).tolist()
        
        # 2. Search DB
        results = collection.query(
            query_embeddings=[query_vector],
            n_results=top_k,
            where=where_filter
        )
        
        # 3. Restructure for easy LLM consumption
        # results structure: {'documents': [['doc1', 'doc2']], 'metadatas': [[{...}, {...}]], 'distances': [[0.1, 0.2]]}
        retrieved_context = []
        if results['documents'] and results['documents'][0]:
            for i in range(len(results['documents'][0])):
                doc = {
                    "text": results['documents'][0][i],
                    "metadata": results['metadatas'][0][i],
                    "distance": results['distances'][0][i]
                }
                retrieved_context.append(doc)
                
        return retrieved_context


# =============================================================================
# MAIN ENTRY POINT (CLI Demonstration)
# =============================================================================

if __name__ == "__main__":
    import argparse
    import time
    
    # Simple CLI argument parsing
    parser = argparse.ArgumentParser(description="JARVIS Memory Layer Sandbox")
    parser.add_argument("--mode", choices=["inject", "query"], required=True, help="Inject mock data or query the DB")
    parser.add_argument("--query", type=str, help="Search term if mode is 'query'")
    args = parser.parse_args()
    
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(SCRIPT_DIR, "jarvis_chroma_wrapper_db")
    
    # Boot the memory layer
    memory = JarvisMemoryLayer(db_path=db_path)
    collection = "jarvis_specialist_mechanic"
    
    if args.mode == "inject":
        print("\n=== STARTING INJECTION PHASE ===")
        # We use a generator to simulate an infinite firehose of documents from the web/PDFs
        def mock_document_stream():
            docs = [
                {"id": "doc1", "text": "Titanium alloy Grade 5 (Ti-6Al-4V) has a tensile strength of 895 MPa.", "metadata": {"source": "handbook", "topic": "materials"}},
                {"id": "doc2", "text": "To prevent galvanic corrosion between aluminum and steel, use a dialectric barrier like teflon.", "metadata": {"source": "handbook", "topic": "corrosion"}},
                {"id": "doc3", "text": "Carbon fiber composites are highly anisotropic; their strength depends entirely on weave direction.", "metadata": {"source": "handbook", "topic": "materials"}},
                {"id": "doc4", "text": "The arc reactor conceptual design uses palladium as a core catalytic medium to sustain the reaction.", "metadata": {"source": "stark_files", "topic": "energy"}},
                {"id": "doc5", "text": "Thermal expansion in aerospace grade aluminum can cause micro-fractures if heated unevenly past 200C.", "metadata": {"source": "handbook", "topic": "thermal"}},
            ]
            for doc in docs:
                # Simulating processing time from a PDF parser
                time.sleep(0.1)
                yield doc
                
        # Inject the generator (batch size 2 to prove batching works)
        memory.ingest_stream(collection_name=collection, document_stream=mock_document_stream(), batch_size=2)
        print("✅ Injection complete.\n")
        
    elif args.mode == "query":
        if not args.query:
            print("❌ Error: Must provide --query when using query mode.")
            exit(1)
            
        print(f"\n=== SEARCHING FOR: '{args.query}' ===")
        start_time = time.time()
        
        # Test semantic search without filters
        print("\n--- GENERAL SEARCH ---")
        results = memory.recall(collection, args.query, top_k=2)
        for i, res in enumerate(results):
            print(f"[{i+1}] (Dist: {res['distance']:.3f}) {res['text']}")
            print(f"    Tags: {res['metadata']}")
            
        # Test semantic search WITH SQLite metadata filters (Domain boundaries)
        print("\n--- FILTERED SEARCH (topic = 'materials') ---")
        filtered_results = memory.recall(collection, args.query, top_k=2, where_filter={"topic": "materials"})
        for i, res in enumerate(filtered_results):
            print(f"[{i+1}] (Dist: {res['distance']:.3f}) {res['text']}")
            print(f"    Tags: {res['metadata']}")
            
        elapsed = time.time() - start_time
        print(f"\n⏱️ Query completed in {elapsed:.3f} seconds.\n")
