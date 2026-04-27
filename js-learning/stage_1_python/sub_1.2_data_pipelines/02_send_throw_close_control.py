"""
02_send_throw_close_control.py

JARVIS Learning Module: Bidirectional Generator Control with send(), throw(), close().

Run with:
    python 02_send_throw_close_control.py

This script demonstrates:
    1. send() — Inject values into a running generator
    2. throw() — Inject exceptions for error handling
    3. close() — Graceful shutdown with cleanup

=============================================================================
THE BIG PICTURE: Why Bidirectional Control?
=============================================================================

One-way generator (basic):
    → Producer yields data OUT
    → Consumer just receives

Two-way generator (coroutine):
    → Producer yields data OUT
    → Consumer can send commands/values IN
    → Consumer can inject errors IN
    → Consumer can request graceful shutdown

This enables DYNAMIC CONTROL of long-running pipelines without restarting.

=============================================================================
THE FLOW (Bidirectional Communication)
=============================================================================

STEP 1: Generator yields a document
        ↓
STEP 2: Orchestrator processes the document
        ↓
STEP 3: Orchestrator decides what to do next:
        - send(new_config) → Generator receives config update
        - throw(error) → Generator handles error internally
        - close() → Generator runs cleanup and exits
        ↓
STEP 4: Generator resumes with injected value/exception

=============================================================================
"""

from typing import Generator, Optional
from dataclasses import dataclass


# =============================================================================
# Part 1: DATA STRUCTURES
# =============================================================================

@dataclass
class Document:
    """A simple document for demo purposes."""
    name: str
    content: str


@dataclass
class PipelineConfig:
    """Configuration that can be updated mid-stream."""
    similarity_threshold: float = 0.85
    skip_duplicates: bool = True


# =============================================================================
# Part 2: THE CONTROLLABLE GENERATOR
# =============================================================================

def controllable_document_processor(
    documents: list[Document],
) -> Generator[Document, Optional[PipelineConfig], None]:
    """
    A bidirectional generator that processes documents.
    
    This generator:
        - YIELDS documents one at a time (outbound)
        - RECEIVES config updates via send() (inbound)
        - HANDLES errors via throw() (inbound)
        - CLEANS UP via close() (inbound)
    
    Type signature breakdown:
        Generator[YieldType, SendType, ReturnType]
        Generator[Document, Optional[PipelineConfig], None]
                  ^^^^^^^^  ^^^^^^^^^^^^^^^^^^^^^^^  ^^^^
                  yields    receives via send()      returns
    """
    # Default configuration
    config = PipelineConfig()
    
    print(f"[Processor] Starting with threshold={config.similarity_threshold}")
    
    try:
        for doc in documents:
            print(f"\n[Processor] Processing: {doc.name}")
            
            # ─────────────────────────────────────────────────────────────
            # YIELD POINT: Pause here and wait for consumer
            # The consumer can:
            #   1. Call next() → received_config will be None
            #   2. Call send(new_config) → received_config will be the config
            #   3. Call throw(error) → An exception will be raised HERE
            #   4. Call close() → GeneratorExit will be raised HERE
            # ─────────────────────────────────────────────────────────────
            received_config: Optional[PipelineConfig] = yield doc
            
            # ─────────────────────────────────────────────────────────────
            # AFTER YIELD: Check if consumer sent us a new config
            # ─────────────────────────────────────────────────────────────
            if received_config is not None:
                config = received_config
                print(f"[Processor] Config updated: threshold={config.similarity_threshold}")
    
    except GeneratorExit:
        # ─────────────────────────────────────────────────────────────────
        # CLEANUP: close() was called. Do graceful shutdown here.
        # ─────────────────────────────────────────────────────────────────
        print("\n[Processor] GeneratorExit received. Running cleanup...")
        print("[Processor] Closing file handles, committing transactions...")
        # In real JARVIS: close DB connections, flush buffers, etc.
        return
    
    except Exception as e:
        # ─────────────────────────────────────────────────────────────────
        # ERROR HANDLING: throw() was called with an exception
        # ─────────────────────────────────────────────────────────────────
        print(f"\n[Processor] Exception injected: {type(e).__name__}: {e}")
        print("[Processor] Handling error and attempting to continue...")
        # In real JARVIS: log error, skip document, notify monitoring
        raise  # Re-raise to let caller know we couldn't recover
    
    print("\n[Processor] All documents processed normally.")


# =============================================================================
# Part 3: DEMO - Using send()
# =============================================================================

def demo_send() -> None:
    """Demonstrate sending values INTO a running generator."""
    print("=" * 60)
    print("DEMO 1: Using send() to update config mid-stream")
    print("=" * 60)
    
    documents = [
        Document("doc1.txt", "Content about Python"),
        Document("doc2.txt", "Content about generators"),
        Document("doc3.txt", "Content about async"),
    ]
    
    processor = controllable_document_processor(documents)
    
    # First call MUST be next() or send(None) to start the generator
    doc = next(processor)
    print(f"[Orchestrator] Received: {doc.name}")
    
    # Second call: send a new config
    new_config = PipelineConfig(similarity_threshold=0.95, skip_duplicates=False)
    doc = processor.send(new_config)  # Inject config AND get next doc
    print(f"[Orchestrator] Received: {doc.name}")
    
    # Third call: normal next()
    doc = next(processor)
    print(f"[Orchestrator] Received: {doc.name}")
    
    # Generator exhausted
    try:
        next(processor)
    except StopIteration:
        print("\n[Orchestrator] Generator exhausted normally.")


# =============================================================================
# Part 4: DEMO - Using throw()
# =============================================================================

def demo_throw() -> None:
    """Demonstrate injecting exceptions INTO a running generator."""
    print("\n" + "=" * 60)
    print("DEMO 2: Using throw() to inject an error")
    print("=" * 60)
    
    documents = [
        Document("doc1.txt", "Content 1"),
        Document("doc2.txt", "Content 2"),
    ]
    
    processor = controllable_document_processor(documents)
    
    # Start the generator
    doc = next(processor)
    print(f"[Orchestrator] Received: {doc.name}")
    
    # Inject an error (simulating network failure)
    print("\n[Orchestrator] Simulating network error...")
    try:
        processor.throw(ConnectionError("ChromaDB connection lost"))
    except ConnectionError:
        print("[Orchestrator] Generator propagated the error (couldn't recover).")


# =============================================================================
# Part 5: DEMO - Using close()
# =============================================================================

def demo_close() -> None:
    """Demonstrate graceful shutdown of a generator."""
    print("\n" + "=" * 60)
    print("DEMO 3: Using close() for graceful shutdown")
    print("=" * 60)
    
    documents = [
        Document("doc1.txt", "Content 1"),
        Document("doc2.txt", "Content 2"),
        Document("doc3.txt", "Content 3"),
    ]
    
    processor = controllable_document_processor(documents)
    
    # Process first document
    doc = next(processor)
    print(f"[Orchestrator] Received: {doc.name}")
    
    # User clicks "Cancel" — request graceful shutdown
    print("\n[Orchestrator] User requested cancellation. Calling close()...")
    processor.close()
    
    print("[Orchestrator] Generator closed gracefully.")


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    demo_send()
    demo_throw()
    demo_close()
    
    print("\n" + "=" * 60)
    print("ALL DEMOS COMPLETE")
    print("=" * 60)
