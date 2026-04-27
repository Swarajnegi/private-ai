"""
01_chromadb_basics.py

JARVIS Memory Layer: Persistent Vector Storage with ChromaDB

Run with:
    python 01_chromadb_basics.py

This script demonstrates:
    1. PersistentClient — Creating a database that survives restarts
    2. Collection — The "table" that holds your vectors and text
    3. Explicit Embeddings — Using our own MiniLM instead of Chroma's default
    4. Metadata — Tagging vectors for filtered retrieval
    5. Querying — Semantic search via cosine distance

=============================================================================
THE BIG PICTURE: Vector Persistence
=============================================================================

Without ChromaDB (the naive way):
    → You embed a document into a 384-dim array
    → You store it in a Python list `knowledge_base.append(vec)`
    → You close the script. The array is deleted from RAM.
    → Next time JARVIS boots, he has amnesia. He must re-embed everything.

With ChromaDB (the smart way):
    → You embed a document into a 384-dim array
    → You call `collection.add()`
    → ChromaDB saves the vector to an HNSW index on disk (SSD)
    → Next time JARVIS boots, the memory is instantly available to query.

=============================================================================
THE FLOW (Step by Step Execution Order)
=============================================================================

STEP 1: Initialize the embedding model (MiniLM)
        ↓
STEP 2: Initialize ChromaDB (PersistentClient pointing to a local folder)
        ↓
STEP 3: Create a collection ("jarvis_general_knowledge")
        ↓
STEP 4: Add documents, assigning explicit IDs, embeddings, and metadata
        ↓
STEP 5: Query the collection using a new question's embedding

=============================================================================
"""

import os
import shutil
import time
from typing import List, Dict, Any

from sentence_transformers import SentenceTransformer
import chromadb
from chromadb.config import Settings

# =============================================================================
# Part 1: SETUP (Paths and Clean Initialization)
# =============================================================================

# Define where ChromaDB will save its files on disk
# Resolve relative to script location for 'Locality'
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jarvis_chroma_db")

def clean_database():
    """
    Utility function to wipe the database so we start fresh every time 
    we run this demo script. In production JARVIS, you would NOT do this!
    """
    if os.path.exists(DB_PATH):
        shutil.rmtree(DB_PATH)
        print(f"[*] Cleared old database at {DB_PATH}")

# =============================================================================
# Part 2: THE MEMORY MANAGER
# =============================================================================

class JarvisMemory:
    """
    LAYER 2 (The Soul): Manages persistent vector storage.
    
    THIS IS THE CORE OF RAG!
    
    It sits BETWEEN:
        - The Ingestion Pipeline (which chunks documents)
        - The Orchestrator (which asks questions)
    
    Purpose:
        - Take text chunks and their embeddings
        - Save them to disk permanently
        - Retrieve the Top-K most relevant chunks for a given query
    
    How it works:
        - Uses sentence-transformers to convert text -> 384-dim vector
        - Uses ChromaDB to store that vector + the original text
        - Uses Cosine Distance to find the closest vectors in math space
    """
    def __init__(self, db_path: str, collection_name: str):
        # ─────────────────────────────────────────────────────────────────────
        # 1. INITIALIZE EMBEDDER
        # ─────────────────────────────────────────────────────────────────────
        # We MUST use the exact same model for adding data and querying data.
        print("[*] Loading embedding model (all-MiniLM-L6-v2)...")
        self.encoder = SentenceTransformer('all-MiniLM-L6-v2')
        
        # ─────────────────────────────────────────────────────────────────────
        # 2. INITIALIZE DATABASE
        # ─────────────────────────────────────────────────────────────────────
        # PersistentClient means data is written to SQLite/HNSW files on disk.
        # EphemeralClient would mean data only lives in RAM.
        print(f"[*] Connecting to ChromaDB at {db_path}...")
        self.client = chromadb.PersistentClient(path=db_path)
        
        # ─────────────────────────────────────────────────────────────────────
        # 3. CREATE COLLECTION
        # ─────────────────────────────────────────────────────────────────────
        # Think of a collection like a SQL Table.
        # 'hnsw:space': 'cosine' forces it to use Cosine Distance instead of L2.
        print(f"[*] Getting or creating collection: '{collection_name}'...")
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )
        print("[*] Memory initialized successfully.\n")

    def store_knowledge(self, documents: List[str], metadatas: List[Dict[str, Any]], ids: List[str]):
        """
        Takes raw text, embeds it, and saves it to disk.
        
        EXECUTION FLOW:
        1. Model converts N strings into an (N, 384) numpy matrix.
        2. Matrix is converted to a python list of lists (Chroma requires this).
        3. Data is pushed to the SQLite/HNSW backend.
        """
        print(f"[>] Embedding {len(documents)} documents...")
        start_time = time.time()
        
        # Model returns a NumPy array. We convert to standard Python lists.
        # This is the compute-heavy step.
        embeddings_array = self.encoder.encode(documents)
        embeddings_list = embeddings_array.tolist()
        
        print(f"[>] Storing in ChromaDB...")
        # ⚠️ CRITICAL RULE: Always pass `embeddings=` explicitly.
        # If you omit it, Chroma silently downloads its own default model
        # from the internet and uses that instead!
        self.collection.add(
            ids=ids,
            documents=documents,
            embeddings=embeddings_list,
            metadatas=metadatas
        )
        
        elapsed = time.time() - start_time
        print(f"[✓] Added {len(documents)} items in {elapsed:.2f} seconds.\n")

    def search_memory(self, query: str, top_k: int = 2) -> Dict:
        """
        Finds the most similar documents to the query.
        
        EXECUTION FLOW:
        1. Query string is converted to a single (384,) vector.
        2. Vector is sent to ChromaDB.
        3. ChromaDB calculates cosine distance against ALL stored vectors.
        4. Returns the `top_k` results.
        """
        print(f"[?] Querying memory for: '{query}'")
        
        # 1. Embed the query using the EXACT SAME model
        query_vector = self.encoder.encode(query).tolist()
        
        # 2. Perform the semantic search
        results = self.collection.query(
            query_embeddings=[query_vector],
            n_results=top_k
        )
        
        return results

# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    # Start fresh for the demo
    clean_database()
    
    # 1. Boot up JARVIS's memory
    memory = JarvisMemory(db_path=DB_PATH, collection_name="iron_man_lore")
    
    # 2. Prepare some knowledge to store
    # Real JARVIS will read this from PDFs, but we hardcode for the demo.
    docs = [
        "The Mark I armor was built in a cave using palladium from scrapped missiles.",
        "The Mark XLIV (Hulkbuster) was co-designed by Tony Stark and Bruce Banner.",
        "Vibranium is an element found in Wakanda, capable of absorbing kinetic energy.",
        "J.A.R.V.I.S. stands for Just A Rather Very Intelligent System.",
        "The Arc Reactor generates 3 gigajoules per second."
    ]
    
    # Metadata lets us filter later (e.g., "only search docs tagged 'engineering'")
    metas = [
        {"topic": "armor", "mark": 1},
        {"topic": "armor", "mark": 44},
        {"topic": "materials", "source": "wakanda"},
        {"topic": "software", "type": "ai"},
        {"topic": "power", "type": "reactor"}
    ]
    
    # Every doc needs a unique ID string.
    doc_ids = ["fact_1", "fact_2", "fact_3", "fact_4", "fact_5"]
    
    # 3. Store it! (This does the matrix math and writes to disk)
    memory.store_knowledge(documents=docs, metadatas=metas, ids=doc_ids)
    
    # 4. Prove persistence (Optional, just to show it works)
    print(f"VERIFY: Total items in database: {memory.collection.count()}\n")
    
    # 5. Query 1: Semantic meaning
    print("--- TEST 1: SEMANTIC RETRIEVAL ---")
    res1 = memory.search_memory("What powers the suits?", top_k=2)
    
    for i in range(len(res1['ids'][0])):
        doc = res1['documents'][0][i]
        dist = res1['distances'][0][i]
        meta = res1['metadatas'][0][i]
        # In cosine space, distance = (1.0 - similarity)
        # So distance 0.2 means 80% similarity. Lower is better.
        print(f"Match {i+1}: (Dist: {dist:.4f}) {doc}")
        print(f"       Metadata: {meta}")

    print("\n--- TEST 2: VOCABULARY MISMATCH ---")
    # Even though we don't use the words "Mark I", "cave", or "scrapped missiles",
    # the embeddings know that "origin", "first", and "suit" are semantically close.
    res2 = memory.search_memory("Who designed what with Tony Stark?", top_k=1)
    print(f"Match 1: (Dist: {res2['distances'][0][0]:.4f}) {res2['documents'][0][0]}")
    
    print("\n[✓] Memory Layer offline.")
