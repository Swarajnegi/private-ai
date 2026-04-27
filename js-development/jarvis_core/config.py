"""
config.py

JARVIS Core Configuration — Absolute Path Registry.

All persistent storage paths are defined here as constants.
No module in jarvis_core should ever construct paths inline.
Always import from this file:

    from jarvis_core.config import DB_ROOT, BACKUP_ROOT, KB_PATH

=============================================================================
THE BIG PICTURE: Absolute Path Discipline
=============================================================================

Without a central config:
    -> Each script constructs its own path: Path("../../jarvis_data/chromadb")
    -> Runs fine from one directory, silently creates a new DB in another
    -> After 3 months: 4 different ChromaDB SQLite files on different drives

With this config:
    -> One source of truth: E:/J.A.R.V.I.S/jarvis_data/chromadb
    -> DB_ROOT is imported, never manually typed
    -> Moving the JARVIS install requires editing exactly ONE file

=============================================================================
"""

import os
from pathlib import Path

# =============================================================================
# Part 1: ROOT ANCHOR (The master reference point)
# =============================================================================

# The absolute root of the entire JARVIS project on disk.
# Override per machine via the JARVIS_ROOT environment variable;
# default resolves the repo root from this file's location.
JARVIS_ROOT: Path = Path(
    os.environ.get(
        "JARVIS_ROOT",
        Path(__file__).resolve().parents[2],
    )
).resolve()

# =============================================================================
# Part 2: DATA PATHS (All persistent state lives here)
# =============================================================================

# The parent folder for ALL system data. Never stored inside the source tree.
DATA_ROOT: Path = JARVIS_ROOT / "jarvis_data"

# ChromaDB persistent vector store.
# The JarvisMemoryStore reads this path at startup.
DB_ROOT: Path = DATA_ROOT / "chromadb"

# Compressed tar.gz backups of the ChromaDB SQLite files.
BACKUP_ROOT: Path = DATA_ROOT / "chromadb_backups"

# The JSONL long-term knowledge base (semantic facts, decisions, patterns).
KB_PATH: Path = DATA_ROOT / "knowledge_base.jsonl"

# =============================================================================
# Part 3: MODEL CONFIGURATION (Embedding model constants)
# =============================================================================

# The default general-purpose embedding model.
# Output: 384-dimensional float vectors.
# Hardware: CPU-only, no GPU required (~90MB RAM).
DEFAULT_EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"

# The maximum safe character count to pass to DEFAULT_EMBEDDING_MODEL.
# The model hard-limits at 256 tokens (~1,000 chars). We buffer to ~900
# to prevent edge-case truncation on high-entropy text (code, JSON).
DEFAULT_CHUNK_CHAR_LIMIT: int = 900

# Character overlap between sequential chunks to preserve context at boundaries.
DEFAULT_CHUNK_OVERLAP: int = 180  # ~20% of DEFAULT_CHUNK_CHAR_LIMIT


# =============================================================================
# Part 4: RUNTIME VALIDATION (Fail loud on startup, not silently mid-run)
# =============================================================================

def validate_paths() -> None:
    """
    Ensure JARVIS_ROOT exists. Creates data directories if missing.

    EXECUTION FLOW:
    1. Check that JARVIS_ROOT points to a real directory on disk.
    2. Create DB_ROOT and BACKUP_ROOT if they don't already exist.
    3. Raise a clear error if the project root itself is missing.

    Call this at the top of any script that touches persistent storage.
    """
    if not JARVIS_ROOT.exists():
        raise FileNotFoundError(
            f"[Config] JARVIS_ROOT not found: {JARVIS_ROOT}\n"
            f"Update JARVIS_ROOT in jarvis_core/config.py to match your install path."
        )
    DB_ROOT.mkdir(parents=True, exist_ok=True)
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)


# =============================================================================
# MAIN ENTRY POINT (Self-test: verify paths resolve correctly)
# =============================================================================

if __name__ == "__main__":
    print("=" * 55)
    print("  JARVIS Core Config — Path Validation")
    print("=" * 55)
    try:
        validate_paths()
        print(f"  [OK] JARVIS_ROOT  : {JARVIS_ROOT}")
        print(f"  [OK] DB_ROOT      : {DB_ROOT}")
        print(f"  [OK] BACKUP_ROOT  : {BACKUP_ROOT}")
        print(f"  [OK] KB_PATH      : {KB_PATH}")
        print(f"  [OK] Embed Model  : {DEFAULT_EMBEDDING_MODEL}")
        print(f"  [OK] Chunk Limit  : {DEFAULT_CHUNK_CHAR_LIMIT} chars")
        print(f"  [OK] Chunk Overlap: {DEFAULT_CHUNK_OVERLAP} chars")
    except FileNotFoundError as e:
        print(f"  [FAIL] {e}")
    print("=" * 55)
