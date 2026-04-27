"""
03_context_managers_resource_safety.py

JARVIS Learning Module: Context Managers for Resource Safety.

Run with:
    python 03_context_managers_resource_safety.py

This script demonstrates:
    1. Basic context manager protocol (__enter__, __exit__)
    2. Class-based context manager for database connections
    3. @contextmanager decorator for lightweight contexts
    4. Exception handling within context managers

=============================================================================
THE BIG PICTURE: Why Context Managers?
=============================================================================

JARVIS is a LONG-RUNNING system. It runs for days, weeks, months.
Every resource leak accumulates until the system crashes.

Context managers provide AUTOMATIC CLEANUP:
    - Files always closed
    - Connections always released
    - Locks always freed
    - GPU memory always reclaimed

=============================================================================
THE FLOW (Resource Lifecycle)
=============================================================================

STEP 1: Enter context → __enter__() → acquire resource
        ↓
STEP 2: Execute code block → your code runs
        ↓
STEP 3: Exit context → __exit__() → release resource (ALWAYS runs)

=============================================================================
"""

from typing import Optional, Any
from contextlib import contextmanager
from dataclasses import dataclass
import time


# =============================================================================
# Part 1: CLASS-BASED CONTEXT MANAGER
# =============================================================================

class ChromaDBConnection:
    """
    LAYER: Memory (Database Connection Pool)
    
    A context manager for ChromaDB connections.
    Ensures connections are ALWAYS returned to the pool.
    
    In real JARVIS:
        This would wrap chromadb.Client() with connection pooling.
    """
    
    def __init__(self, collection_name: str = "documents"):
        self.collection_name = collection_name
        self._connection = None
    
    def __enter__(self) -> "ChromaDBConnection":
        """
        Called when entering the `with` block.
        
        EXECUTION FLOW:
        1. Acquire connection from pool
        2. Return self (so `as db` gets this object)
        """
        print(f"[ChromaDB] Acquiring connection for '{self.collection_name}'...")
        self._connection = {"status": "connected", "collection": self.collection_name}
        # In real code: self._connection = chromadb.Client()
        return self
    
    def __exit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> bool:
        """
        Called when exiting the `with` block — ALWAYS, even on exception.
        
        Args:
            exc_type: Type of exception (or None if no exception)
            exc_val: Exception instance (or None)
            exc_tb: Traceback (or None)
        
        Returns:
            True to suppress the exception, False to propagate it.
            (Usually return False — let exceptions propagate)
        
        EXECUTION FLOW:
        1. Check if exception occurred
        2. Release connection back to pool (ALWAYS)
        3. Return False to let exception propagate
        """
        if exc_type is not None:
            print(f"[ChromaDB] Exception occurred: {exc_type.__name__}: {exc_val}")
        
        print(f"[ChromaDB] Releasing connection...")
        self._connection = None
        # In real code: self._connection.close()
        
        return False  # Don't suppress exceptions
    
    def query(self, text: str) -> list[str]:
        """Simulate a database query."""
        if self._connection is None:
            raise RuntimeError("Not connected! Use 'with' statement.")
        print(f"[ChromaDB] Querying: '{text}'")
        return [f"Result for '{text}'"]


# =============================================================================
# Part 2: DECORATOR-BASED CONTEXT MANAGER (@contextmanager)
# =============================================================================

@contextmanager
def gpu_memory_scope(model_name: str):
    """
    LAYER: Body (GPU Resource Management)
    
    A lightweight context manager using the @contextmanager decorator.
    Simpler than class-based when you just need setup/teardown.
    
    Usage:
        with gpu_memory_scope("llama-7b"):
            # GPU memory allocated
            run_inference()
        # GPU memory freed
    """
    print(f"[GPU] Allocating VRAM for '{model_name}'...")
    # In real code: model = load_model(model_name)
    
    try:
        yield {"model": model_name, "vram_mb": 4096}  # This is what `as model` receives
    finally:
        # This ALWAYS runs, even on exception
        print(f"[GPU] Freeing VRAM for '{model_name}'...")
        # In real code: del model; torch.cuda.empty_cache()


# =============================================================================
# Part 3: NESTED CONTEXT MANAGERS
# =============================================================================

def demo_nested_contexts() -> None:
    """
    Demonstrate multiple resources managed together.
    
    In JARVIS, a single operation might need:
        - Database connection
        - GPU memory
        - Rate limiter lock
    """
    print("\n" + "=" * 60)
    print("DEMO: Nested Context Managers")
    print("=" * 60)
    
    # All resources are guaranteed to be released in reverse order
    with ChromaDBConnection("documents") as db:
        with gpu_memory_scope("embedding-model") as gpu:
            print(f"\n[Pipeline] Resources acquired:")
            print(f"           DB: {db.collection_name}")
            print(f"           GPU: {gpu['model']} ({gpu['vram_mb']}MB)")
            
            # Simulate work
            results = db.query("tax documents")
            print(f"[Pipeline] Query results: {results}")
    
    print("\n[Pipeline] All resources released.\n")


# =============================================================================
# Part 4: EXCEPTION SAFETY DEMO
# =============================================================================

def demo_exception_safety() -> None:
    """
    Demonstrate that cleanup happens even when exceptions occur.
    """
    print("=" * 60)
    print("DEMO: Exception Safety")
    print("=" * 60)
    
    try:
        with ChromaDBConnection("documents") as db:
            print("\n[Pipeline] About to crash...")
            raise ValueError("Simulated database error!")
            # This line never runs
            results = db.query("test")
    except ValueError as e:
        print(f"\n[Pipeline] Caught exception: {e}")
    
    print("[Pipeline] Notice: Connection was STILL released!\n")


# =============================================================================
# Part 5: ANTI-PATTERN DEMO (What NOT to do)
# =============================================================================

def demo_antipattern() -> None:
    """
    Show the dangerous pattern that context managers prevent.
    """
    print("=" * 60)
    print("DEMO: Anti-Pattern (Resource Leak)")
    print("=" * 60)
    
    print("""
    # ❌ DANGEROUS — Don't do this:
    
    db = ChromaDBConnection("documents")
    db.__enter__()
    results = db.query("test")
    # If query() raises an exception, connection is NEVER released!
    db.__exit__(None, None, None)
    
    
    # ✅ SAFE — Always use `with`:
    
    with ChromaDBConnection("documents") as db:
        results = db.query("test")
    # Connection is ALWAYS released
    """)


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    demo_nested_contexts()
    demo_exception_safety()
    demo_antipattern()
    
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("""
    | Resource        | Context Manager Pattern           |
    |-----------------|-----------------------------------|
    | File            | with open(...) as f:              |
    | Database        | with DBConnection() as db:        |
    | GPU Memory      | with gpu_scope() as model:        |
    | Lock/Mutex      | with threading.Lock():            |
    | HTTP Session    | with requests.Session() as s:     |
    
    RULE: If it needs cleanup, wrap it in a context manager.
    """)
