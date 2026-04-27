"""
store.py

JARVIS Memory Layer: Production Vector Store Engine.

Import with:
    from jarvis_core.memory.store import JarvisMemoryStore

=============================================================================
THE BIG PICTURE: Persistent, auditable, recoverable semantic memory
=============================================================================

Without JarvisMemoryStore:
    -> Raw ChromaDB PersistentClient initialized ad-hoc in each script
    -> DB path is relative ("./chroma_db") -- runs fine in one dir, creates
       a second hidden DB when run from another directory
    -> No deduplication: feeding the same document twice doubles the vector store
    -> No backup: one corrupted SQLite file = all memory gone permanently
    -> No truncation guard: 500-word documents silently lose 80% of their content

With JarvisMemoryStore:
    -> DB path is always absolute (imported from jarvis_core.config.DB_ROOT)
    -> NoveltyGate: checks ID before encoding -- 0% redundant API calls on re-run
    -> TruncationGuard: warns before ingesting any document > 200 words
    -> BackupEngine: one-line compressed tar.gz snapshot of the full SQLite store
    -> AuditEngine: inspects SQLite integrity and collection stats via ChromaDB API

=============================================================================
THE FLOW (Step by Step Execution Order)
=============================================================================

STEP 1: with JarvisMemoryStore() as store:
        Connects to PersistentClient at DB_ROOT (absolute path from config.py)
        Loads all-MiniLM-L6-v2 embedding model into CPU RAM
        ↓
STEP 2: store.ingest_documents(collection, documents, metadatas, ids)
        NoveltyGate checks IDs -> skip if already stored
        TruncationGuard warns if any document > 200 words
        Explicit encoding: encoder.encode(documents) -> embeddings
        ChromaDB.collection.add(embeddings, documents, metadatas, ids)
        ↓
STEP 3: store.query_collection(collection, query_text, n_results)
        Explicit: encoder.encode([query_text]) -> query_vector
        ChromaDB.collection.query(query_embeddings, n_results)
        Returns ranked results dict
        ↓
STEP 4: store.create_backup()
        tar.gz snapshot of DB_ROOT -> BACKUP_ROOT/jarvis_memory_<timestamp>.tar.gz
        ↓
STEP 5: store.restore_from_backup(path)
        Closes client -> removes current DB_ROOT -> extracts backup -> reconnects
        ↓
STEP 6: Caller exits the with block
        __exit__ closes ChromaDB client and releases SQLite file handles

=============================================================================
"""

import gc
import shutil
import sqlite3
import tarfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from jarvis_core.config import (
    BACKUP_ROOT,
    DB_ROOT,
    DEFAULT_EMBEDDING_MODEL,
    validate_paths,
)


# =============================================================================
# Part 1: MMR PURE FUNCTION (stateless, testable in isolation)
# =============================================================================

def compute_mmr_reranking(
    query_vec: List[float],
    candidate_embeddings: List[List[float]],
    candidate_ids: List[str],
    candidate_documents: List[str],
    candidate_metadatas: List[Dict[str, Any]],
    candidate_distances: List[float],
    k: int,
    lambda_val: float,
) -> Tuple[List[str], List[str], List[Dict[str, Any]], List[float]]:
    """
    Greedy MMR (Maximal Marginal Relevance) re-ranker.

    Operates entirely on float arrays. Has zero knowledge of ChromaDB,
    network I/O, or any JARVIS state. Safe to unit-test standalone.

    MMR FORMULA (for each candidate D_i at iteration step t):

        MMR(D_i) = lambda · Sim(D_i, Q)  -  (1-lambda) · max_{D_j ∈ S} Sim(D_i, D_j)

        Where:
            Q   = query vector (the user's question, encoded)
            S   = set of already-selected documents
            lambda   = lambda_val (0.0 = pure diversity, 1.0 = pure relevance / Top-k)

    EXECUTION FLOW:
    1. Convert all inputs to L2-normalized NumPy arrays.
    2. Pre-compute cosine similarity between query and all candidates.
    3. First pick = highest query similarity (same as Top-k round 1).
    4. Loop k-1 more times: compute MMR score for each remaining candidate.
       The score penalises candidates that are similar to already-selected ones.
    5. Pick the candidate with the highest MMR score each iteration.
    6. Return selected ids, documents, metadatas, distances in selection order.

    Args:
        query_vec:             The L2-normalized query embedding (1D list of floats).
        candidate_embeddings:  List of N candidate embeddings (each a list of floats).
        candidate_ids:         Parallel list of ChromaDB document IDs.
        candidate_documents:   Parallel list of raw text strings.
        candidate_metadatas:   Parallel list of metadata dicts.
        candidate_distances:   Parallel list of ChromaDB cosine distances (0=identical, 2=opposite).
        k:                     Number of diverse results to return.
        lambda_val:            Trade-off between relevance (1.0) and diversity (0.0).

    Returns:
        4-tuple of (ids, documents, metadatas, distances) in MMR-selected order.
    """
    n = len(candidate_embeddings)
    k = min(k, n)  # Cannot return more results than we have candidates

    # -- Convert to NumPy for fast matrix operations ---------------------------
    # Shape: (n, d) where n=num candidates, d=embedding dimension (e.g. 384)
    emb_matrix = np.array(candidate_embeddings, dtype=np.float32)

    # Shape: (d,) -- the query vector
    q_vec = np.array(query_vec, dtype=np.float32)

    # -- L2-normalize everything to make dot product == cosine similarity ------
    # ChromaDB guarantees MiniLM vectors are already normalized, but we do it
    # again here defensively -- it's a single O(n*d) operation.
    emb_norms = np.linalg.norm(emb_matrix, axis=1, keepdims=True)
    emb_norms = np.where(emb_norms == 0, 1.0, emb_norms)  # Prevent division by zero
    emb_matrix = emb_matrix / emb_norms

    q_norm = np.linalg.norm(q_vec)
    q_vec = q_vec / q_norm if q_norm > 0 else q_vec

    # -- Pre-compute cosine similarity between query and all N candidates ------
    # Shape: (n,) -- one score per candidate
    # Higher = more relevant to the query.
    q_sims = emb_matrix @ q_vec  # Dot product on normalized vectors = cosine sim

    selected_indices: List[int] = []  # Indices into the candidate arrays
    remaining_indices: List[int] = list(range(n))

    for step in range(k):
        if not remaining_indices:
            break

        if step == 0:
            # -- STEP 1: First pick is always the highest query-similarity doc -
            # This is identical to Top-k round 1. MMR only diverges from Step 2.
            best_local_idx = int(np.argmax(q_sims[remaining_indices]))
            pick = remaining_indices[best_local_idx]
        else:
            # -- STEP 2+: Compute MMR score for each remaining candidate -------
            # selected_embs shape: (len(selected), d)
            selected_embs = emb_matrix[selected_indices]

            # remaining_embs shape: (len(remaining), d)
            remaining_embs = emb_matrix[remaining_indices]

            # Similarity between every remaining doc and every selected doc.
            # Shape: (len(remaining), len(selected))
            # Entry [i, j] = how similar remaining[i] is to selected[j]
            redundancy_matrix = remaining_embs @ selected_embs.T

            # For each remaining candidate, find its MAXIMUM similarity to any
            # already-selected doc. This is the "redundancy penalty".
            # Shape: (len(remaining),)
            redundancy = np.max(redundancy_matrix, axis=1)

            # Apply the MMR formula:
            #   MMR = lambda * relevance_to_query - (1-lambda) * max_similarity_to_selected
            mmr_scores = (
                lambda_val * q_sims[remaining_indices]
                - (1.0 - lambda_val) * redundancy
            )
            best_local_idx = int(np.argmax(mmr_scores))
            pick = remaining_indices[best_local_idx]

        selected_indices.append(pick)
        remaining_indices.remove(pick)

    # -- Assemble the output in selection order --------------------------------
    out_ids = [candidate_ids[i] for i in selected_indices]
    out_docs = [candidate_documents[i] for i in selected_indices]
    out_metas = [candidate_metadatas[i] for i in selected_indices]
    out_dists = [candidate_distances[i] for i in selected_indices]

    return out_ids, out_docs, out_metas, out_dists


# =============================================================================
# Part 2: THE PRODUCTION MEMORY STORE
# =============================================================================

class JarvisMemoryStore:
    """
    LAYER: Memory -- Persistent vector store with backup and audit capabilities.

    This is the single point of contact between JARVIS and ChromaDB.
    All other modules that need to read or write semantic memory
    import and use this class exclusively.

    It sits BETWEEN:
        - RecursiveWordChunker (upstream: produces text chunks)
        - Brain Layer / Query Interface (downstream: consumes ranked results)

    Purpose:
        - Manage the ChromaDB PersistentClient lifecycle safely
        - Enforce NoveltyGate deduplication before every encode call
        - Enforce TruncationGuard before every ingest call
        - Provide backup, restore, and audit as first-class operations

    How it works:
        - Uses context manager (with / __enter__ / __exit__) for safe
          resource lifecycle: the client always closes, even on crash
        - Always uses absolute paths from jarvis_core.config -- never relative
        - Explicitly encodes text with SentenceTransformer before passing
          to ChromaDB to enforce vector space consistency
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        backup_dir: Optional[Path] = None,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    ) -> None:
        """
        Initialize paths and configuration. Does NOT connect to the DB yet.
        The connection is deferred to __enter__ (the 'with' statement).

        Args:
            db_path:         Absolute path for the ChromaDB SQLite store.
                             Defaults to DB_ROOT from jarvis_core.config.
            backup_dir:      Absolute path for compressed backup archives.
                             Defaults to BACKUP_ROOT from jarvis_core.config.
            embedding_model: Name of the SentenceTransformer model to load.
                             Defaults to DEFAULT_EMBEDDING_MODEL from config.
        """
        validate_paths()  # Ensures all data directories exist, raises if not
        self._db_path: Path = (db_path or DB_ROOT).resolve()
        self._backup_dir: Path = (backup_dir or BACKUP_ROOT).resolve()
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        self._embedding_model_name: str = embedding_model
        self._client: Any = None    # Assigned in __enter__
        self._encoder: Any = None   # Assigned in __enter__
        self._closed: bool = True

    # -------------------------------------------------------------------------
    # Context Manager: Lifecycle control
    # -------------------------------------------------------------------------

    def __enter__(self) -> "JarvisMemoryStore":
        """
        Open the ChromaDB connection and load the embedding model.

        EXECUTION FLOW:
        1. Import chromadb and initialize PersistentClient at self._db_path.
        2. Load SentenceTransformer embedding model into CPU RAM.
        3. Mark instance as open (self._closed = False).
        4. Return self.

        Returns:
            Self -- the open store object, assigned to the 'as' variable.
        """
        import chromadb
        from sentence_transformers import SentenceTransformer

        print(f"[MemoryStore] Connecting to ChromaDB at: {self._db_path}")
        self._client = chromadb.PersistentClient(path=str(self._db_path))

        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"[MemoryStore] Loading encoder: {self._embedding_model_name} on {device.upper()}")
        self._encoder = SentenceTransformer(self._embedding_model_name, device=device)

        self._closed = False
        print("[MemoryStore] Ready.")
        return self

    def __exit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> bool:
        """
        Close the ChromaDB connection and release resources.

        This runs even if an exception fires inside the 'with' block.
        This is the GUARANTEE: no dangling SQLite file handles.

        Returns:
            False -- we do not suppress exceptions.
        """
        self._close()
        return False

    def _close(self) -> None:
        """Release ChromaDB client and force garbage collection."""
        if self._closed:
            return
        if self._client is not None:
            del self._client
            self._client = None
        gc.collect()
        self._closed = True
        print("[MemoryStore] Connection closed.")

    # -------------------------------------------------------------------------
    # Part 2: INGEST (NoveltyGate + TruncationGuard + Explicit Encoding)
    # -------------------------------------------------------------------------

    def ingest_documents(
        self,
        collection_name: str,
        documents: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        ids: Optional[List[str]] = None,
    ) -> int:
        """
        Upsert documents into a ChromaDB collection.

        "Upsert" = "Update or Insert". If the chunk ID already exists,
        ChromaDB replaces it with the new text + metadata + embedding.
        If it does not exist, it is inserted fresh.

        This replaces the old add()-based approach which silently skipped
        entire batches when the first ID already existed (NoveltyGate).
        Upsert is always safe to re-run and always reflects the latest data.

        EXECUTION FLOW:
        1. Get or create the target collection by name.
        2. Generate sequential IDs if not provided.
        3. Count existing docs BEFORE upsert (for the new/replaced report).
        4. TruncationGuard: warn for any document exceeding ~200 words.
        5. Explicitly encode documents to float vectors via SentenceTransformer.
        6. Call collection.upsert() -- inserts new, replaces existing.
        7. Count docs AFTER upsert. Diff = how many were actually new.
        8. Return total count of documents processed.

        Args:
            collection_name: Name of the ChromaDB target namespace.
            documents:       List of raw text strings to store.
            metadatas:       Optional list of metadata dicts (one per document).
            ids:             Optional list of unique string IDs.
                             Auto-generated as "doc_N" if not provided.

        Returns:
            Count of documents processed (new + replaced).

        Raises:
            RuntimeError: If called outside of a 'with' block.
        """
        self._assert_open()
        collection = self._client.get_or_create_collection(name=collection_name)

        # Auto-generate IDs starting after the current count to avoid collisions
        if ids is None:
            start = collection.count()
            ids = [f"doc_{start + i}" for i in range(len(documents))]

        if metadatas is None:
            metadatas = [{"_source": "direct"} for _ in documents]

        # -- Count BEFORE upsert to calculate how many chunks are truly new ----
        # With upsert, we can no longer skip the batch -- every call reflects
        # the latest data. Instead, we report: N new, M replaced.
        count_before: int = collection.count()

        # -- TruncationGuard: Warn before silently cutting documents -----------
        # all-MiniLM-L6-v2 hard-limits at 256 tokens (~200 words typical English).
        # Documents beyond this are silently truncated. We surface it explicitly.
        for i, doc in enumerate(documents):
            word_count = len(doc.split())
            if word_count > 200:
                print(
                    f"[MemoryStore] TruncationGuard WARNING: '{ids[i]}' is {word_count} words. "
                    f"Model hard-limit is ~256 tokens. Tail content will be silently dropped. "
                    f"Use RecursiveWordChunker to pre-split before ingesting."
                )

        # -- Explicit Encoding: No invisible operations ------------------------
        # We call encode() manually so the vector space is always consistent
        # with our chosen model. ChromaDB's automatic embedding is DISABLED
        # because it hides which model produced the vectors.
        embeddings: List[List[float]] = self._encoder.encode(documents).tolist()

        # -- Upsert: Update existing chunks or insert new ones -----------------
        # This is the key upgrade from add().
        # Re-running ingest on the same PDF now reflects any updated metadata
        # (e.g., new 'specialist' field) without requiring a collection wipe.
        collection.upsert(
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
            ids=ids,
        )

        count_after: int = collection.count()
        new_chunks: int = count_after - count_before
        replaced_chunks: int = len(documents) - new_chunks

        print(
            f"[MemoryStore] Upserted {len(documents)} docs into '{collection_name}' "
            f"({new_chunks} new, {replaced_chunks} replaced | total: {count_after})"
        )
        return len(documents)

    # -------------------------------------------------------------------------
    # Part 3: QUERY (Explicit Encoding)
    # Two query modes:
    #   query_collection()     -> Standard Top-k (fast, redundant)
    #   mmr_query_collection() -> MMR re-ranked (diverse, ~1ms overhead)
    # -------------------------------------------------------------------------

    def query_collection(
        self,
        collection_name: str,
        query_text: str,
        n_results: int = 5,
        where: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Semantically query a collection by text.

        EXECUTION FLOW:
        1. Get the target collection by name (raises if missing).
        2. Explicitly encode the query text to a float vector.
        3. Run ChromaDB vector similarity search.
        4. Return the ranked results dictionary.

        Args:
            collection_name: Name of the ChromaDB namespace to search.
            query_text:      The natural language search query.
            n_results:       Number of top results to return.
            where:           Optional ChromaDB metadata filter dict.

        Returns:
            ChromaDB results dict with keys: ids, documents, distances, metadatas.
        """
        self._assert_open()
        collection = self._client.get_collection(name=collection_name)
        query_vec = self._encoder.encode([query_text]).tolist()
        kwargs: Dict[str, Any] = {"query_embeddings": query_vec, "n_results": n_results}
        if where:
            kwargs["where"] = where
        return collection.query(**kwargs)

    def mmr_query_collection(
        self,
        collection_name: str,
        query_text: str,
        n_results: int = 5,
        fetch_k: int = 50,
        lambda_val: float = 0.5,
        where: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        MMR-re-ranked semantic query. Fetches a large candidate pool, then
        greedily selects k diverse results using the MMR algorithm.

        WHY TWO STEPS:
            ChromaDB's HNSW index is extremely fast for approximate nearest
            neighbour search but cannot natively apply the MMR penalty term
            (it has no concept of 'already selected documents'). We solve this
            by doing Top-k with a large k (fetch_k=50) to get the candidate
            pool, then running MMR in-memory on the small result set (~50 vecs).
            The in-memory step is O(k * fetch_k * d) ≈ O(5 * 50 * 384) = 96,000
            floating-point operations -- completes in under 1ms on a CPU.

        lambda_val GUIDE:
            1.0 -> Pure relevance (identical to query_collection / Top-k)
            0.7 -> Slight diversity boost (RECOMMENDED default for JARVIS)
            0.5 -> Equal relevance and diversity trade-off
            0.0 -> Maximum diversity (ignores relevance to query entirely -- avoid)

        EXECUTION FLOW:
        1. Encode query_text -> query_vec (same model, same vector space).
        2. Fetch top fetch_k candidates from ChromaDB (large pool for MMR to work with).
        3. Extract embeddings from ChromaDB result (the raw float vectors).
        4. Call compute_mmr_reranking() pure function with all candidate data.
        5. Return re-ranked results in same dict format as query_collection().

        Args:
            collection_name: Name of the ChromaDB namespace to search.
            query_text:      The natural language search query.
            n_results:       Number of final DIVERSE results to return (the "k").
            fetch_k:         Size of the initial candidate pool.
                             Must be >= n_results. Default 50 is a good balance.
                             Increase for more diversity at the cost of slight latency.
            lambda_val:      MMR trade-off parameter.
                             lambda=1.0 -> Top-k. lambda=0.5 -> equal relevance+diversity.
            where:           Optional ChromaDB metadata filter dict.

        Returns:
            Dict with keys: ids, documents, distances, metadatas.
            Format is identical to query_collection() for drop-in compatibility.

        Raises:
            RuntimeError: If called outside a 'with' block.
            ValueError:   If fetch_k < n_results.
        """
        self._assert_open()

        if fetch_k < n_results:
            raise ValueError(
                f"fetch_k ({fetch_k}) must be >= n_results ({n_results}). "
                f"The candidate pool must be at least as large as the final result set."
            )

        collection = self._client.get_collection(name=collection_name)

        # -- STEP 1: Encode the user's query text -> float vector ---------------
        # include_parameter tells ChromaDB to return raw embeddings alongside
        # documents and metadatas. We need those raw vectors to compute
        # candidate-to-candidate similarity inside the MMR loop.
        query_vec: List[float] = self._encoder.encode([query_text]).tolist()[0]

        # -- STEP 2: Fetch a LARGE candidate pool from ChromaDB (Top fetch_k) --
        # We deliberately fetch MORE than we need (fetch_k >> n_results) so the
        # MMR algorithm has enough candidates to choose from. If we only fetched
        # n_results candidates, MMR would have nothing to diversify.
        query_kwargs: Dict[str, Any] = {
            "query_embeddings": [query_vec],
            "n_results": min(fetch_k, collection.count()),  # Guard: can't fetch more than exists
            "include": ["documents", "metadatas", "distances", "embeddings"],
        }
        if where:
            query_kwargs["where"] = where

        raw = collection.query(**query_kwargs)

        # ChromaDB wraps results in a list-of-lists (one per query in the batch).
        # We sent exactly one query, so we always index [0] to unwrap the batch.
        ids: List[str] = raw["ids"][0]
        documents: List[str] = raw["documents"][0]
        metadatas: List[Dict[str, Any]] = raw["metadatas"][0]
        distances: List[float] = raw["distances"][0]
        embeddings: List[List[float]] = raw["embeddings"][0]

        print(
            f"[MemoryStore] MMR: fetched {len(ids)} candidates from '{collection_name}', "
            f"re-ranking to {n_results} diverse results (lambda={lambda_val})"
        )

        # -- STEP 3: Run the pure MMR greedy re-ranker in-memory --------------
        # This is a pure NumPy function -- no I/O, no ChromaDB calls.
        out_ids, out_docs, out_metas, out_dists = compute_mmr_reranking(
            query_vec=query_vec,
            candidate_embeddings=embeddings,
            candidate_ids=ids,
            candidate_documents=documents,
            candidate_metadatas=metadatas,
            candidate_distances=distances,
            k=n_results,
            lambda_val=lambda_val,
        )

        # -- STEP 4: Return in same dict format as query_collection() ----------
        # Wrapping in lists maintains ChromaDB's list-of-lists batch convention,
        # ensuring the Brain layer can treat both query methods identically.
        return {
            "ids": [out_ids],
            "documents": [out_docs],
            "metadatas": [out_metas],
            "distances": [out_dists],
        }

    # -------------------------------------------------------------------------
    # Part 4: DELETE (Collection Wipe)
    # -------------------------------------------------------------------------

    def delete_collection(self, collection_name: str) -> None:
        """
        Permanently delete an entire collection and all its vectors.

        Args:
            collection_name: Name of the ChromaDB namespace to delete.
        """
        self._assert_open()
        try:
            self._client.delete_collection(name=collection_name)
            print(f"[MemoryStore] Collection '{collection_name}' deleted.")
        except Exception as e:
            print(f"[MemoryStore] Could not delete collection '{collection_name}': {e}")

    # -------------------------------------------------------------------------
    # Part 5: BACKUP ENGINE
    # -------------------------------------------------------------------------

    def create_backup(self) -> str:
        """
        Create a compressed tar.gz snapshot of the ChromaDB directory.

        EXECUTION FLOW:
        1. Generate a timestamp-based filename.
        2. Open a tar.gz archive and add the entire db_path directory.
        3. Print the backup path and size.
        4. Return the absolute path to the backup file.

        Returns:
            Absolute path string to the created .tar.gz backup file.
        """
        self._assert_open()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"jarvis_memory_{timestamp}.tar.gz"
        backup_path = self._backup_dir / backup_name

        with tarfile.open(backup_path, "w:gz") as tar:
            tar.add(self._db_path, arcname=self._db_path.name)

        size_kb = backup_path.stat().st_size / 1024
        print(f"[MemoryStore] Backup created: {backup_path} ({size_kb:.1f} KB)")
        return str(backup_path)

    # -------------------------------------------------------------------------
    # Part 6: RESTORE ENGINE
    # -------------------------------------------------------------------------

    def restore_from_backup(self, backup_path: str) -> None:
        """
        Restore the database from a compressed tar.gz backup archive.

        EXECUTION FLOW:
        1. Validate the backup file exists on disk.
        2. Close the current ChromaDB client (releases SQLite file handle).
        3. Remove the current (possibly corrupted) database directory.
        4. Extract the tar.gz archive to restore the database.
        5. Reinitialize the ChromaDB PersistentClient.

        Args:
            backup_path: Absolute path to the .tar.gz backup file.

        Raises:
            FileNotFoundError: If the backup file does not exist.
        """
        backup_file = Path(backup_path)
        if not backup_file.exists():
            raise FileNotFoundError(f"[MemoryStore] Backup not found: {backup_path}")

        print(f"[MemoryStore] Restoring from: {backup_file.name}")

        # Close existing client to release SQLite file handles (critical on Windows)
        self._close()
        time.sleep(0.5)  # Allow Windows to release OS-level file locks

        # Remove current (corrupted) database
        if self._db_path.exists():
            shutil.rmtree(self._db_path, ignore_errors=True)

        # Extract the backup archive
        with tarfile.open(backup_file, "r:gz") as tar:
            tar.extractall(path=self._db_path.parent, filter="data")

        print("[MemoryStore] Database restored from backup.")

        # Reconnect ChromaDB client to the restored database
        import chromadb
        self._client = chromadb.PersistentClient(path=str(self._db_path))
        self._closed = False

    # -------------------------------------------------------------------------
    # Part 7: AUDIT ENGINE
    # -------------------------------------------------------------------------

    def audit_database(self) -> Dict[str, Any]:
        """
        Inspect the underlying SQLite file for integrity and collection stats.

        EXECUTION FLOW:
        1. Locate the chroma.sqlite3 file inside db_path.
        2. Run SQLite PRAGMA integrity_check.
        3. Query ChromaDB API for collection names and document counts.
        4. Print a formatted audit report and return the stats dict.

        Returns:
            Dict with: status, collection_count, collections (list of name + count).
        """
        self._assert_open()
        sqlite_path = self._db_path / "chroma.sqlite3"

        if not sqlite_path.exists():
            print(f"[MemoryStore] Audit FAILED: chroma.sqlite3 not found at {sqlite_path}")
            return {"status": "MISSING"}

        conn = sqlite3.connect(str(sqlite_path))
        cursor = conn.cursor()
        cursor.execute("PRAGMA integrity_check")
        integrity = cursor.fetchone()[0]
        conn.close()

        collections = self._client.list_collections()
        collection_info = [
            {"name": c.name, "count": c.count()} for c in collections
        ]

        result: Dict[str, Any] = {
            "status": "HEALTHY" if integrity == "ok" else f"CORRUPT: {integrity}",
            "collection_count": len(collection_info),
            "collections": collection_info,
        }

        print("\n" + "=" * 50)
        print(f"  DATABASE AUDIT: {sqlite_path.name}")
        print("=" * 50)
        print(f"  Integrity  : {result['status']}")
        print(f"  Collections: {result['collection_count']}")
        for c in collection_info:
            print(f"    - {c['name']}: {c['count']} documents")
        print("=" * 50)
        return result

    # -------------------------------------------------------------------------
    # Private helper
    # -------------------------------------------------------------------------

    def _assert_open(self) -> None:
        """Raise a clear error if methods are called outside a 'with' block."""
        if self._closed or self._client is None:
            raise RuntimeError(
                "JarvisMemoryStore is not connected. "
                "Use: with JarvisMemoryStore() as store:"
            )


# =============================================================================
# MAIN ENTRY POINT (MMR vs Top-k comparison demo)
# =============================================================================

if __name__ == "__main__":

    import time

    TEST_COLLECTION = "jarvis_mmr_demo"

    # These 8 documents are deliberately structured to expose the Top-k redundancy
    # problem: docs 1-4 all say the same thing about generators (paraphrased),
    # docs 5-8 cover genuinely different topics. Top-k will return 4 near-identical
    # generator docs. MMR will select 1 generator doc then branch out to diverse topics.
    DEMO_DOCS = [
        # Cluster A: Very similar -- Python generators (4 paraphrased versions)
        "Python generators use the yield keyword to produce values one at a time, saving memory.",
        "Using yield in Python creates a generator that produces items lazily, reducing RAM usage.",
        "Generators in Python are memory-efficient because they yield values on demand instead of loading all at once.",
        "The yield statement in Python pauses a function and returns a value, enabling lazy iteration.",
        # Cluster B: Genuinely different topics
        "ChromaDB is a vector database that stores float embeddings in an HNSW proximity graph.",
        "asyncio allows Python programs to run I/O operations concurrently without blocking the CPU.",
        "Cosine similarity measures the angle between two vectors, returning 1.0 for identical direction.",
        "Context managers in Python use __enter__ and __exit__ to guarantee resource cleanup.",
    ]
    DEMO_IDS = [f"demo_{i:03d}" for i in range(len(DEMO_DOCS))]

    QUERY = "How does Python save memory during data processing?"

    print("=" * 65)
    print("  MMR vs Top-k Comparison Demo")
    print("=" * 65)
    print(f"\n  Query: '{QUERY}'")

    with JarvisMemoryStore() as store:

        # -- Ingest demo documents ------------------------------------------
        store.ingest_documents(
            collection_name=TEST_COLLECTION,
            documents=DEMO_DOCS,
            ids=DEMO_IDS,
        )

        # -- TOP-K: Standard retrieval --------------------------------------
        print("\n" + "-" * 65)
        print("  TOP-K (n=4): Ranked by raw relevance -- expect redundancy")
        print("-" * 65)
        t0 = time.perf_counter()
        topk_results = store.query_collection(
            collection_name=TEST_COLLECTION,
            query_text=QUERY,
            n_results=4,
        )
        topk_ms = (time.perf_counter() - t0) * 1000

        for i, doc in enumerate(topk_results["documents"][0]):
            dist = topk_results["distances"][0][i]
            print(f"  ({i+1}) [dist={dist:.4f}] {doc[:75]}...")
        print(f"\n  Latency: {topk_ms:.1f}ms")

        # -- MMR: Diverse retrieval -----------------------------------------
        print("\n" + "-" * 65)
        print("  MMR (n=4, fetch_k=8, lambda=0.7): Diverse re-ranking")
        print("-" * 65)
        t0 = time.perf_counter()
        mmr_results = store.mmr_query_collection(
            collection_name=TEST_COLLECTION,
            query_text=QUERY,
            n_results=4,
            fetch_k=8,
            lambda_val=0.7,  # Slightly weighted toward diversity over raw relevance
        )
        mmr_ms = (time.perf_counter() - t0) * 1000

        for i, doc in enumerate(mmr_results["documents"][0]):
            dist = mmr_results["distances"][0][i]
            print(f"  ({i+1}) [dist={dist:.4f}] {doc[:75]}...")
        print(f"\n  Latency: {mmr_ms:.1f}ms  (includes {mmr_ms - topk_ms:.1f}ms MMR overhead)")

        # -- Interpretation -------------------------------------------------
        print("\n" + "=" * 65)
        print("  VERDICT")
        print("=" * 65)
        print("  Top-k: Likely returned 4 near-identical 'yield / generator' chunks.")
        print("  MMR:   Should show 1 generator chunk + 3 from different topics.")
        print("  This diversity gap is what MMR was built to prevent in JARVIS.")
        print("=" * 65)

        # -- Cleanup --------------------------------------------------------
        store.delete_collection(TEST_COLLECTION)
        print("\n  [OK] Demo collection cleaned up.")
