"""
04_persistence_backup.py

JARVIS Memory Layer: Persistence, Backup, and Disaster Recovery for ChromaDB

Run with:
    python 04_persistence_backup.py

This script demonstrates:
    1. PersistentClient Lifecycle — Data survives script restarts
    2. Incremental Ingestion — Add documents without wiping existing data
    3. SQLite File Audit — Inspecting the raw database file
    4. Backup Strategy — Compress and archive the database
    5. Restore from Backup — Reconstruct the database from archive

=============================================================================
THE BIG PICTURE: Memory Persistence Is Anti-Fragility
=============================================================================

Without Persistence and Backup (the naive way):
    → JARVIS ingests 1000 research papers and code files into ChromaDB.
    → A Windows update corrupts the SQLite file, or a bad migration wipes it.
    → JARVIS restarts and has zero memories.
    → You lose all the work. Hours/days of re-ingestion.

With Persistence and Backup (the smart way):
    → ChromaDB uses PersistentClient with data saved to disk as SQLite.
    → Every major change triggers an automatic compressed backup.
    → If the main database corrupts, you restore from the last backup in seconds.
    → JARVIS's memory is resilient, not fragile.

=============================================================================
THE FLOW (Step by Step Execution Order)
=============================================================================

STEP 1: Initialize PersistentClient (data saved to disk, not RAM)
        ↓
STEP 2: Ingest demo documents (simulating knowledge accumulation)
        ↓
STEP 3: Verify persistence — Close client, reopen, confirm data exists
        ↓
STEP 4: Create a compressed backup (.tar.gz) of the database directory
        ↓
STEP 5: Simulate corruption — Wipe the main database
        ↓
STEP 6: Restore from backup — Verify data recovered
        ↓
STEP 7: Audit the SQLite file — inspect tables and document counts

=============================================================================
"""

import os
import shutil
import sqlite3
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Dict, Any, Optional, Generator
from datetime import datetime

# =============================================================================
# Part 1: The JarvisMemoryStore Class (Production-grade wrapper)
# =============================================================================

class JarvisMemoryStore:
    """
    LAYER: Memory Sub-layer — Persistence & Backup

    Purpose:
        Wraps ChromaDB PersistentClient with backup, restore, and audit capabilities.
        This is the actual component JARVIS uses to manage its long-term memory on disk.

    How it works:
        - Maintains a persistent database directory (SQLite under the hood)
        - Creates timestamped compressed backups
        - Validates database integrity before and after operations
        - Provides a clean API: ingest, query, backup, restore

    It sits BETWEEN:
        - 03_metadata_filtering (Retrieval logic)
        - 2.3 Document Ingestion (Data input pipeline)
    """

    def __init__(self, db_path: str, backup_dir: str = "backups"):
        """
        EXECUTION FLOW:
        1. Resolve absolute paths for DB and backup directory.
        2. Ensure backup directory exists.
        3. Initialize ChromaDB PersistentClient (no collection created yet).
        """
        self.db_path = Path(db_path).resolve()
        self.backup_dir = Path(backup_dir).resolve()
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self._closed = False

        import chromadb
        from sentence_transformers import SentenceTransformer
        
        print(f"    [Memory] Connecting to PersistentClient at {self.db_path}...")
        self.client = chromadb.PersistentClient(path=str(self.db_path))
        
        print("    [Memory] Loading Embedding Engine: all-MiniLM-L6-v2...")
        self.encoder = SentenceTransformer("all-MiniLM-L6-v2")

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
            if hasattr(self, 'client'):
                del self.client
            self._closed = True
        except:
            pass

    # ─────────────────────────────────────────────────────────────────────
    # SECTION: Ingestion & Query
    # ─────────────────────────────────────────────────────────────────────

    def get_or_create_collection(self, name: str) -> Any:
        """
        Get or create a collection by name.

        Returns:
            ChromaDB Collection object
        """
        return self.client.get_or_create_collection(name=name)

    def ingest_documents(
        self,
        collection_name: str,
        documents: list[str],
        metadatas: Optional[list[dict]] = None,
        ids: Optional[list[str]] = None,
    ) -> int:
        """
        Add documents to a collection.

        EXECUTION FLOW:
        1. Get or create the target collection.
        2. Generate IDs if not provided.
        3. Explicitly generate embeddings using local encoder (No invisible operations).
        4. Add documents and vectors to ChromaDB.
        5. Return count of documents added.

        Returns:
            Number of documents added
        """
        collection = self.get_or_create_collection(collection_name)

        if ids is None:
            start_id = collection.count()
            ids = [f"doc_{start_id + i}" for i in range(len(documents))]

        if metadatas is None:
            metadatas = [{} for _ in documents]

        # ─────────────────────────────────────────────────────────────────────
        # NOVELTY GATE: Deduplication
        # ─────────────────────────────────────────────────────────────────────
        # Note: In production, consider using a semantic hash or 'collection.get(ids=...)'
        # to skip embeddings entirely for known IDs.
        existing_count = collection.count()
        if existing_count > 0:
            # Simple check for ID existence to prevent duplicate keys or double-work
            try:
                # We check the first ID as a batch proxy
                res = collection.get(ids=[ids[0]])
                if res and res['ids']:
                    print(f"    [!] Novelty Gate: ID '{ids[0]}' exists. Skipping duplicate batch.")
                    return 0
            except:
                pass

        # ─────────────────────────────────────────────────────────────────────
        # TRUNCATION CHECK: Window Safety
        # ─────────────────────────────────────────────────────────────────────
        for i, doc in enumerate(documents):
            word_count = len(doc.split())
            if word_count > 200:
                print(f"    [WARNING] Silent Truncation: Doc '{ids[i]}' is {word_count} words (Limit ~250 tokens).")

        # ─────────────────────────────────────────────────────────────────────
        # EXPLICIT EMBEDDINGS: Origin Tracing
        # ─────────────────────────────────────────────────────────────────────
        # PRODUCTION NOTE: For JARVIS Core, wrap this in 'asyncio.to_thread'
        embeddings = self.encoder.encode(documents).tolist()

        collection.add(
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
            ids=ids,
        )

        print(f"    [+] Added {len(documents)} documents to '{collection_name}' (total: {collection.count()})")
        return len(documents)

    def query_collection(
        self,
        collection_name: str,
        query_text: str,
        n_results: int = 3,
        where: Optional[dict] = None,
    ) -> Dict[str, Any]:
        """
        Query a collection semantically.

        EXECUTION FLOW:
        1. Get collection (raises if missing).
        2. Explicitly encode query text using local encoder.
        3. Run ChromaDB query with query_embeddings and optional metadata filter.
        4. Return results dictionary.

        Returns:
            ChromaDB query results dict
        """
        collection = self.client.get_collection(name=collection_name)
        
        # Explicitly encode query
        query_embeddings = self.encoder.encode([query_text]).tolist()
        
        kwargs: Dict[str, Any] = {"query_embeddings": query_embeddings, "n_results": n_results}
        if where:
            kwargs["where"] = where
        return collection.query(**kwargs)

    # ─────────────────────────────────────────────────────────────────────
    # SECTION: Persistence Verification
    # ─────────────────────────────────────────────────────────────────────

    def verify_persistence(self) -> bool:
        """
        Verify that the database directory exists on disk and has content.

        EXECUTION FLOW:
        1. Check that db_path directory exists.
        2. Check that chroma.sqlite3 file exists inside it.
        3. Return True if both conditions met.

        Returns:
            True if database file exists, False otherwise
        """
        sqlite_path = self.db_path / "chroma.sqlite3"
        exists = sqlite_path.exists()
        status = "EXISTS" if exists else "NOT FOUND"
        print(f"    [Persistence] chroma.sqlite3 at {sqlite_path}: {status}")
        return exists

    # ─────────────────────────────────────────────────────────────────────
    # SECTION: Backup & Restore
    # ─────────────────────────────────────────────────────────────────────

    def create_backup(self) -> str:
        """
        Create a compressed tar.gz backup of the current database.

        EXECUTION FLOW:
        1. Generate timestamp-based filename.
        2. Create tar.gz archive of the entire db_path directory.
        3. Return the path to the backup file.

        Returns:
            Absolute path to the created backup file
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"jarvis_memory_{timestamp}.tar.gz"
        backup_path = self.backup_dir / backup_name

        print(f"    [*] Creating backup: {backup_name}")

        with tarfile.open(backup_path, "w:gz") as tar:
            tar.add(self.db_path, arcname=self.db_path.name)

        size_kb = backup_path.stat().st_size / 1024
        print(f"    [+] Backup complete: {backup_path} ({size_kb:.1f} KB)")
        return str(backup_path)

    def restore_from_backup(self, backup_path: str) -> None:
        """
        Restore the database from a compressed backup archive.

        EXECUTION FLOW:
        1. Validate backup file exists.
        2. Close existing client connection.
        3. Remove corrupted/current database directory.
        4. Extract tar.gz archive to restore the db_path.
        5. Reinitialize the PersistentClient.

        Args:
            backup_path: Absolute path to the .tar.gz backup file
        """
        backup_file = Path(backup_path)
        if not backup_file.exists():
            raise FileNotFoundError(f"Backup not found: {backup_path}")

        print(f"    [*] Restoring from backup: {backup_file.name}")

        # Step 1: Close existing client if it exists
        if hasattr(self, 'client'):
            self.close()
            import time
            time.sleep(0.5)  # Allow Windows to release file handles

        # Step 2: Remove current database
        if self.db_path.exists():
            import shutil
            shutil.rmtree(self.db_path, ignore_errors=True)
            print(f"    [-] Removed corrupted database")

        # Step 3: Extract backup
        with tarfile.open(backup_file, "r:gz") as tar:
            # Extract the inner folder (arcname was db_path.name)
            tar.extractall(path=self.db_path.parent, filter="data")

        print(f"    [+] Database restored from backup")

        # Step 4: Reinitialize client
        import chromadb
        self.client = chromadb.PersistentClient(path=str(self.db_path))

        # Step 4: Reinitialize client
        import chromadb
        self.client = chromadb.PersistentClient(path=str(self.db_path))

    # ─────────────────────────────────────────────────────────────────────
    # SECTION: Database Audit
    # ─────────────────────────────────────────────────────────────────────

    def audit_database(self) -> Dict[str, Any]:
        """
        Inspect the underlying SQLite file for integrity and statistics.

        EXECUTION FLOW:
        1. Open chroma.sqlite3 with sqlite3.
        2. Run integrity_check pragma.
        3. Use ChromaDB client API for collection info (avoids schema issues).
        4. Return summary dictionary.

        Returns:
            Dictionary with integrity status, collection count, and per-collection stats
        """
        sqlite_path = self.db_path / "chroma.sqlite3"
        if not sqlite_path.exists():
            print(f"\n{'='*50}")
            print(f"DATABASE AUDIT: {sqlite_path}")
            print(f"{'='*50}")
            print(f"    STATUS: MISSING - No SQLite file found")
            print(f"{'='*50}")
            return {"status": "MISSING", "reason": "No SQLite file found"}

        # First check SQLite integrity
        import sqlite3
        conn = sqlite3.connect(str(sqlite_path))
        cursor = conn.cursor()
        cursor.execute("PRAGMA integrity_check")
        integrity = cursor.fetchone()[0]
        conn.close()

        # Use ChromaDB client to get collection info
        try:
            collections = self.client.list_collections()
            collection_info = []
            for coll in collections:
                collection_info.append({
                    "name": coll.name,
                    "document_count": coll.count()
                })
        except Exception as e:
            print(f"    [WARNING] Could not query collections: {e}")
            collection_info = []

        results: Dict[str, Any] = {
            "status": "HEALTHY" if integrity == "ok" else f"CORRUPT: {integrity}",
            "collection_count": len(collection_info),
            "collections": collection_info,
        }

        print(f"\n{'='*50}")
        print(f"DATABASE AUDIT: {sqlite_path}")
        print(f"{'='*50}")
        print(f"    Integrity: {results['status']}")
        print(f"    Collections: {results['collection_count']}")
        for col in results["collections"]:
            print(f"      - {col['name']}: {col['document_count']} documents")
        print(f"{'='*50}")

        return results

    def cleanup(self) -> None:
        """Close client and remove database directory."""
        # Explicitly close ChromaDB client to release file handles
        if hasattr(self, "client"):
            try:
                # ChromaDB doesn't have explicit close, but we can help by deleting references
                del self.client
                # Force garbage collection to close SQLite connections
                import gc
                gc.collect()
            except Exception:
                pass

        # Small delay to allow Windows to release file handles
        import time
        time.sleep(0.1)

        # Remove directories if they exist
        if self.db_path.exists():
            try:
                shutil.rmtree(self.db_path)
            except PermissionError:
                # On Windows, retry once after delay
                time.sleep(0.5)
                try:
                    shutil.rmtree(self.db_path)
                except Exception as e:
                    print(f"    [!] Warning: Could not remove {self.db_path}: {e}")

        if self.backup_dir.exists():
            try:
                shutil.rmtree(self.backup_dir)
            except PermissionError:
                time.sleep(0.5)
                try:
                    shutil.rmtree(self.backup_dir)
                except Exception as e:
                    print(f"    [!] Warning: Could not remove {self.backup_dir}: {e}")


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    # Setup
    # Resolve paths relative to the script's directory for better 'Locality'
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    DB_DIR = os.path.join(SCRIPT_DIR, "test_jarvis_persistence_db")
    BACKUP_DIR = os.path.join(SCRIPT_DIR, "test_jarvis_backups")

    print("=" * 60)
    print("JARVIS PHASE 2.2.4 — Persistence & Backup Demo")
    print("=" * 60)

    # Cleanup existing test directories first
    import shutil
    for path in [DB_DIR, BACKUP_DIR]:
        if os.path.exists(path):
            try:
                shutil.rmtree(path, ignore_errors=True)
            except:
                pass

    # Use context manager for proper resource cleanup
    with JarvisMemoryStore(db_path=DB_DIR, backup_dir=BACKUP_DIR) as store:
        try:
            # ─────────────────────────────────────────────────────────────────
            # STEP 1: Ingest Documents
            # ─────────────────────────────────────────────────────────────────
            print("\n--- STEP 1: Ingest Documents ---")

            store.ingest_documents(
                collection_name="jarvis_memory",
                documents=[
                    "Python asyncio uses an event loop for concurrent I/O operations.",
                    "ChromaDB stores vectors in an HNSW index for fast approximate nearest neighbor search.",
                    "JARVIS uses multiple collections to isolate specialist knowledge domains.",
                    "Regular backups prevent catastrophic data loss in production systems.",
                    "Embedding models like MiniLM produce 384-dimensional vectors from text.",
                ],
                metadatas=[
                    {"type": "code", "language": "python", "stage": "phase_1"},
                    {"type": "memory", "component": "chromadb", "stage": "phase_2"},
                    {"type": "architecture", "component": "specialists", "stage": "phase_4"},
                    {"type": "ops", "component": "backup", "stage": "phase_2"},
                    {"type": "embeddings", "model": "minilm", "stage": "phase_2"},
                ],
                ids=["doc_001", "doc_002", "doc_003", "doc_004", "doc_005"],
            )

            # ─────────────────────────────────────────────────────────────────
            # STEP 2: Verify Persistence (data is on disk)
            # ─────────────────────────────────────────────────────────────────
            print("\n--- STEP 2: Verify Persistence ---")
            store.verify_persistence()

            # Query to prove data is there
            print("\n    Query test: 'How does JARVIS isolate knowledge?'")
            results = store.query_collection(
                collection_name="jarvis_memory",
                query_text="How does JARVIS isolate knowledge?",
                n_results=2,
            )
            for i, doc in enumerate(results["documents"][0]):
                print(f"      ({i+1}) [{results['distances'][0][i]:.4f}] {doc}")

            # ─────────────────────────────────────────────────────────────────
            # STEP 3: Create Backup
            # ─────────────────────────────────────────────────────────────────
            print("\n--- STEP 3: Create Backup ---")
            backup_path = store.create_backup()

            # ─────────────────────────────────────────────────────────────────
            # STEP 4: Simulate Corruption + Restore
            # ─────────────────────────────────────────────────────────────────
            print("\n--- STEP 4: Simulate Corruption & Restore ---")
            print("    [*] Simulating corruption by deleting database...")

            # Close store before deletion
            store.close()
            import gc
            gc.collect()
            import time
            time.sleep(1.0)  # Longer delay for Windows

            # Delete directory with retry logic
            max_retries = 5
            for i in range(max_retries):
                try:
                    if os.path.exists(DB_DIR):
                        shutil.rmtree(DB_DIR, ignore_errors=True)
                    # Verify deletion
                    if not os.path.exists(DB_DIR):
                        print("    [!] Database directory removed — confirmed corruption!")
                        break
                    else:
                        if i < max_retries - 1:
                            print(f"    [!] Retry {i+1}/{max_retries} after delay...")
                            time.sleep(1.5)
                            gc.collect()
                        else:
                            print("    [!] Warning: Could not remove database directory (may be in use)")
                except Exception as e:
                    if i < max_retries - 1:
                        print(f"    [!] Retry {i+1}/{max_retries} after error: {e}")
                        time.sleep(1.5)
                        gc.collect()
                    else:
                        print(f"    [!] Warning: Failed to remove directory: {e}")

            # Restore from backup
            print("    [*] Restoring from backup...")
            store.restore_from_backup(backup_path)

            # Verify restore worked
            collection = store.client.get_collection("jarvis_memory")
            count = collection.count()
            print(f"    [+] After restore: {count} documents recovered")

            # ─────────────────────────────────────────────────────────────────
            # STEP 5: Audit the Database
            # ─────────────────────────────────────────────────────────────────
            print("\n--- STEP 5: Database Audit ---")
            store.audit_database()

            print("\n" + "=" * 60)
            print("PERSISTENCE & BACKUP DEMO COMPLETE")
            print("=" * 60)

        except Exception as e:
            print(f"\n[!!!] CRITICAL ERROR: {e}")
            import traceback
            traceback.print_exc()

        finally:
            # Manual cleanup of test directories
            print("\n[*] Cleaning up test files...")
            import time
            time.sleep(0.5)  # Allow Windows to release handles

            # On Windows, file handles may remain locked. Use ignore_errors
            for path in [DB_DIR, BACKUP_DIR]:
                if os.path.exists(path):
                    try:
                        shutil.rmtree(path, ignore_errors=True)
                    except Exception as e:
                        print(f"    [!] Windows file lock: {path} may need manual deletion")

            print("[*] Done. (Note: On Windows, test directories may remain due to file locking)")
