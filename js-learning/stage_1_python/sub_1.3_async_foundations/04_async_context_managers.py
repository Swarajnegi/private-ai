"""
04_async_context_managers.py

JARVIS Learning Module: Async Context Managers and aiofiles.

Run with:
    python 04_async_context_managers.py

This script demonstrates:
    1. async with — non-blocking resource management
    2. __aenter__ / __aexit__ — the async context manager protocol
    3. @asynccontextmanager — decorator shortcut
    4. aiofiles pattern — async file I/O (simulated)
    5. Real-world JARVIS patterns: async DB, HTTP, GPU sessions

=============================================================================
THE BIG PICTURE: Why async with?
=============================================================================

Phase 2 taught you sync context managers:  with open("file") as f:
But in async code, resource setup/teardown may involve I/O.
If that I/O is synchronous, it BLOCKS the event loop.

async with = context manager where setup and teardown can await.

=============================================================================
THE FLOW (async with Protocol)
=============================================================================

    async with SomeResource() as res:
        await res.do_work()

    Internally:

    1. res = await SomeResource().__aenter__()     ← async setup
    2. await res.do_work()                          ← your code
    3. await SomeResource().__aexit__(exc_info)     ← async cleanup
                                                      (guaranteed!)

=============================================================================
"""

import asyncio
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional


# =============================================================================
# Part 1: CLASS-BASED ASYNC CONTEXT MANAGER
# =============================================================================

class AsyncDatabaseConnection:
    """
    Async context manager for database connections.
    
    LAYER: Memory (Database Access)
    
    Simulates connecting to ChromaDB or PostgreSQL.
    Connection setup and teardown involve network I/O,
    so they MUST be async to avoid blocking the event loop.
    """
    
    def __init__(self, db_name: str) -> None:
        self._db_name = db_name
        self._connected = False
    
    async def __aenter__(self) -> "AsyncDatabaseConnection":
        """
        Async setup — called when entering 'async with'.
        
        In real code, this would do:
            await asyncpg.connect(...)
            or await motor.AsyncIOMotorClient(...)
        """
        print(f"    [DB] Connecting to '{self._db_name}'...")
        await asyncio.sleep(0.1)  # Simulate network handshake
        self._connected = True
        print(f"    [DB] Connected!")
        return self
    
    async def __aexit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> bool:
        """
        Async teardown — GUARANTEED to run, even on exceptions.
        
        Closes connection, releases pool slot back.
        """
        if exc_type is not None:
            print(f"    [DB] Exception during work: {exc_type.__name__}")
        
        print(f"    [DB] Closing connection to '{self._db_name}'...")
        await asyncio.sleep(0.05)  # Simulate graceful disconnect
        self._connected = False
        print(f"    [DB] Connection closed.")
        return False  # Don't suppress exceptions
    
    async def query(self, sql: str) -> list[dict[str, Any]]:
        """Simulate an async database query."""
        if not self._connected:
            raise RuntimeError("Not connected!")
        print(f"    [DB] Executing: {sql}")
        await asyncio.sleep(0.05)  # Simulate query time
        return [{"id": 1, "result": "mock_data"}]


async def demo_class_based() -> None:
    """Demonstrate class-based async context manager."""
    print("=" * 60)
    print("DEMO 1: Class-Based Async Context Manager")
    print("=" * 60)
    
    # The async with ensures connection is closed even if query fails
    async with AsyncDatabaseConnection("jarvis_memory") as db:
        results = await db.query("SELECT * FROM documents LIMIT 5")
        print(f"    [DB] Got {len(results)} results")
    
    # Connection is guaranteed closed here
    print("    [DB] Outside context — connection released\n")


# =============================================================================
# Part 2: DECORATOR-BASED ASYNC CONTEXT MANAGER
# =============================================================================

@asynccontextmanager
async def gpu_memory_scope(model_name: str) -> AsyncIterator[dict[str, Any]]:
    """
    Async context manager for GPU memory allocation.
    
    LAYER: Body (GPU Resource Management)
    
    Allocates VRAM before yielding, frees it after.
    Uses @asynccontextmanager for concise syntax.
    """
    print(f"    [GPU] Allocating VRAM for '{model_name}'...")
    await asyncio.sleep(0.1)  # Simulate CUDA allocation
    
    resource = {"model": model_name, "vram_mb": 4096, "device": "cuda:0"}
    print(f"    [GPU] Allocated {resource['vram_mb']}MB on {resource['device']}")
    
    try:
        yield resource  # Hand control to the 'async with' block
    finally:
        # This runs even if an exception occurs inside the block
        print(f"    [GPU] Freeing VRAM for '{model_name}'...")
        await asyncio.sleep(0.05)  # Simulate CUDA deallocation
        print(f"    [GPU] VRAM freed.")


async def demo_decorator_based() -> None:
    """Demonstrate decorator-based async context manager."""
    print("=" * 60)
    print("DEMO 2: Decorator-Based (@asynccontextmanager)")
    print("=" * 60)
    
    async with gpu_memory_scope("llama-70b") as gpu:
        print(f"    [Model] Running inference on {gpu['device']}...")
        await asyncio.sleep(0.1)  # Simulate inference
        print(f"    [Model] Inference complete!")
    
    # GPU memory guaranteed freed here
    print("    [GPU] Outside context — VRAM available for other models\n")


# =============================================================================
# Part 3: SIMULATED aiofiles PATTERN
# =============================================================================

class AsyncFileReader:
    """
    Simulate aiofiles behavior for async file I/O.
    
    LAYER: Memory (Ingestion Pipeline)
    
    In production, you'd use:
        import aiofiles
        async with aiofiles.open("file.pdf", "rb") as f:
            data = await f.read()
    
    aiofiles delegates blocking file I/O to a thread pool,
    so the event loop stays free while the OS reads from disk.
    """
    
    def __init__(self, filepath: str, mode: str = "r") -> None:
        self._filepath = filepath
        self._mode = mode
        self._content = ""
    
    async def __aenter__(self) -> "AsyncFileReader":
        """Simulate async file open."""
        print(f"    [File] Opening '{self._filepath}'...")
        await asyncio.sleep(0.05)  # Simulate disk I/O
        self._content = f"[Contents of {self._filepath}]"
        return self
    
    async def __aexit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> bool:
        """Simulate async file close."""
        print(f"    [File] Closing '{self._filepath}'...")
        await asyncio.sleep(0.02)
        self._content = ""
        return False
    
    async def read(self) -> str:
        """Simulate async read."""
        await asyncio.sleep(0.05)  # Simulate disk read
        return self._content
    
    async def read_chunks(self, chunk_size: int = 1024) -> AsyncIterator[str]:
        """Simulate async chunked reading."""
        content = self._content
        for i in range(0, len(content), chunk_size):
            await asyncio.sleep(0.01)  # Simulate disk I/O per chunk
            yield content[i:i + chunk_size]


async def demo_aiofiles_pattern() -> None:
    """Demonstrate async file I/O pattern."""
    print("=" * 60)
    print("DEMO 3: Async File I/O (aiofiles Pattern)")
    print("=" * 60)
    
    # Single file read
    async with AsyncFileReader("research/paper.pdf") as f:
        content = await f.read()
        print(f"    [File] Read: {content}")
    
    print("    [File] File handle released\n")


# =============================================================================
# Part 4: NESTED ASYNC CONTEXT MANAGERS
# =============================================================================

@asynccontextmanager
async def http_session(base_url: str) -> AsyncIterator[dict[str, str]]:
    """Simulate an async HTTP session (like httpx.AsyncClient)."""
    print(f"    [HTTP] Opening session to {base_url}...")
    await asyncio.sleep(0.05)
    session = {"base_url": base_url, "status": "connected"}
    try:
        yield session
    finally:
        print(f"    [HTTP] Closing session to {base_url}...")
        await asyncio.sleep(0.02)


async def demo_nested_contexts() -> None:
    """
    Demonstrate nested async context managers.
    
    LAYER: Brain (Agent Orchestrator)
    
    Real JARVIS request processing needs multiple resources
    simultaneously: DB connection + HTTP session + GPU memory.
    All must be cleaned up in reverse order.
    """
    print("=" * 60)
    print("DEMO 4: Nested Async Contexts (JARVIS Request)")
    print("=" * 60)
    
    print("\n  Simulating a full JARVIS request pipeline:\n")
    
    async with AsyncDatabaseConnection("vector_store") as db:
        async with http_session("https://api.openai.com") as api:
            async with gpu_memory_scope("embedding-model") as gpu:
                # All 3 resources acquired — do the actual work
                print(f"\n    [Agent] All resources ready!")
                print(f"    [Agent] DB: {db._db_name}")
                print(f"    [Agent] API: {api['base_url']}")
                print(f"    [Agent] GPU: {gpu['device']}")
                
                # Simulate the work
                await asyncio.sleep(0.1)
                print(f"    [Agent] Request processed!\n")
    
    # All 3 resources released in REVERSE order: GPU → HTTP → DB
    print("    All resources cleaned up.\n")


# =============================================================================
# Part 5: SYNC vs ASYNC COMPARISON
# =============================================================================

async def demo_sync_vs_async() -> None:
    """Show the performance difference between sync and async patterns."""
    print("=" * 60)
    print("DEMO 5: Why Async Matters for I/O")
    print("=" * 60)
    
    # SEQUENTIAL: Each file blocks
    print("\n  Sequential file processing:")
    start = time.perf_counter()
    
    for name in ["file1.pdf", "file2.pdf", "file3.pdf"]:
        async with AsyncFileReader(name) as f:
            await f.read()
    
    elapsed = time.perf_counter() - start
    print(f"    Total: {elapsed:.2f}s\n")
    
    # CONCURRENT: All files processed in parallel
    print("  Concurrent file processing:")
    start = time.perf_counter()
    
    async def read_file(name: str) -> str:
        async with AsyncFileReader(name) as f:
            return await f.read()
    
    results = await asyncio.gather(
        read_file("file1.pdf"),
        read_file("file2.pdf"),
        read_file("file3.pdf"),
    )
    
    elapsed = time.perf_counter() - start
    print(f"    Total: {elapsed:.2f}s (concurrent!)")
    print(f"    Results: {len(results)} files read\n")


# =============================================================================
# Part 6: COMMON MISTAKES
# =============================================================================

async def demo_mistakes() -> None:
    """Show common mistakes with async context managers."""
    print("=" * 60)
    print("DEMO 6: Common Mistakes")
    print("=" * 60)
    
    print("""
    # ❌ MISTAKE 1: Using sync 'with' for async resources
    
    with AsyncDatabaseConnection("db") as conn:   # TypeError!
        # __enter__ is not defined, only __aenter__
    
    # ✅ FIX: Use 'async with'
    
    async with AsyncDatabaseConnection("db") as conn:
        await conn.query("SELECT 1")
    
    
    # ─────────────────────────────────────────────────────────────
    
    # ❌ MISTAKE 2: Opening resource without context manager
    
    conn = AsyncDatabaseConnection("db")
    await conn.__aenter__()          # Manual enter
    await conn.query("SELECT 1")
    # Forgot __aexit__! Connection leaks if query raises!
    
    # ✅ FIX: Always use async with
    
    async with AsyncDatabaseConnection("db") as conn:
        await conn.query("SELECT 1")  # Cleanup guaranteed
    
    
    # ─────────────────────────────────────────────────────────────
    
    # ❌ MISTAKE 3: Blocking file I/O in async code
    
    async def bad_read():
        with open("big_file.pdf", "rb") as f:
            data = f.read()    # BLOCKS event loop!
    
    # ✅ FIX: Use aiofiles
    
    async def good_read():
        async with aiofiles.open("big_file.pdf", "rb") as f:
            data = await f.read()  # Non-blocking!
    """)


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

async def main() -> None:
    """Main entry point."""
    await demo_class_based()
    await demo_decorator_based()
    await demo_aiofiles_pattern()
    await demo_nested_contexts()
    await demo_sync_vs_async()
    await demo_mistakes()
    
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("""
    | Pattern                 | Use When                          |
    |-------------------------|-----------------------------------|
    | __aenter__/__aexit__    | Complex async resource lifecycle  |
    | @asynccontextmanager    | Simple async setup/teardown       |
    | async with aiofiles     | Non-blocking file I/O             |
    | async with httpx        | Non-blocking HTTP sessions        |
    | async with db.connect() | Non-blocking DB connections       |
    
    SYNC vs ASYNC CONTEXT MANAGERS:
    ┌──────────────────────────────┬──────────────────────────────┐
    │  with (sync)                 │  async with (async)          │
    │  __enter__ / __exit__        │  __aenter__ / __aexit__      │
    │  Blocks during setup/close   │  Non-blocking setup/close    │
    │  Use for: simple files, locks│  Use for: DB, HTTP, GPU, I/O │
    └──────────────────────────────┴──────────────────────────────┘
    
    GOLDEN RULE: If resource involves network or disk I/O,
                 use async with, not with.
    """)


if __name__ == "__main__":
    asyncio.run(main())
