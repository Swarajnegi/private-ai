"""
03_asyncio_run_entry_point.py

JARVIS Learning Module: asyncio.run() and Event Loop Management.

Run with:
    python 03_asyncio_run_entry_point.py

This script demonstrates:
    1. asyncio.run() as the entry point for async programs
    2. What happens internally when asyncio.run() is called
    3. Manual loop control vs asyncio.run() convenience
    4. Graceful shutdown patterns for long-running systems

=============================================================================
THE BIG PICTURE: The Bridge Between Sync and Async
=============================================================================

Python starts synchronous. JARVIS needs to be asynchronous.
asyncio.run() is the ONE bridge between these two worlds.

    ┌──────────────────┐         ┌──────────────────────────┐
    │  SYNCHRONOUS     │         │  ASYNCHRONOUS            │
    │                  │         │                          │
    │  if __name__:    │ ──────→ │  async def main():       │
    │    asyncio.run() │         │    await agent_loop()    │
    │                  │ ←────── │    return results        │
    │  print(result)   │         │                          │
    └──────────────────┘         └──────────────────────────┘
         THE BRIDGE: asyncio.run()

=============================================================================
THE FLOW (What asyncio.run() Does Internally)
=============================================================================

STEP 1: Create a new event loop
        ↓
STEP 2: Set it as the current loop for this thread
        ↓
STEP 3: Run the coroutine until it completes
        ↓
STEP 4: Cancel any leftover pending tasks
        ↓
STEP 5: Shutdown async generators
        ↓
STEP 6: Close the event loop

=============================================================================
"""

import asyncio
import time
from typing import Any


# =============================================================================
# Part 1: BASIC asyncio.run() USAGE
# =============================================================================

async def simple_main() -> str:
    """
    The simplest async main function.
    
    LAYER: Brain (Entry Point)
    
    asyncio.run() will:
        1. Create loop
        2. Run this until return
        3. Close loop
    """
    print("[Main] Starting async program...")
    await asyncio.sleep(0.1)
    print("[Main] Async work complete.")
    return "Success"


def demo_basic_run() -> None:
    """Demonstrate the simplest use of asyncio.run()."""
    print("=" * 60)
    print("DEMO 1: Basic asyncio.run()")
    print("=" * 60)
    
    # This is the ONLY way to start async code from sync code
    result = asyncio.run(simple_main())
    
    # We're back in sync world — result is a plain string
    print(f"[Sync] Got result: '{result}'")
    print(f"[Sync] Type: {type(result)}")
    print()


# =============================================================================
# Part 2: WHAT HAPPENS INTERNALLY
# =============================================================================

async def task_that_takes_time(name: str, seconds: float) -> str:
    """A task that simulates work."""
    print(f"    [{name}] Starting ({seconds}s work)...")
    await asyncio.sleep(seconds)
    print(f"    [{name}] Done!")
    return f"{name} result"


async def main_with_tasks() -> list[str]:
    """
    Main function that spawns multiple tasks.
    
    When asyncio.run() finishes this, it automatically
    cancels any tasks that are still running.
    """
    print("\n  Spawning 3 tasks concurrently...")
    
    results = await asyncio.gather(
        task_that_takes_time("Embed", 0.2),
        task_that_takes_time("Search", 0.3),
        task_that_takes_time("Generate", 0.1),
    )
    
    return list(results)


def demo_internal_mechanics() -> None:
    """Show what asyncio.run() does step by step."""
    print("=" * 60)
    print("DEMO 2: Internal Mechanics of asyncio.run()")
    print("=" * 60)
    
    print("\n  [Step 1] asyncio.run() creates a new event loop")
    print("  [Step 2] Runs main_with_tasks() until complete")
    
    start = time.perf_counter()
    results = asyncio.run(main_with_tasks())
    elapsed = time.perf_counter() - start
    
    print(f"\n  [Step 3] All tasks finished in {elapsed:.2f}s")
    print(f"  [Step 4] Event loop closed automatically")
    print(f"  Results: {results}")
    print()


# =============================================================================
# Part 3: THE MANUAL WAY (Low-Level Loop Control)
# =============================================================================

def demo_manual_loop() -> None:
    """
    Show the manual way to control the event loop.
    
    asyncio.run() does all of this for you.
    This is shown for understanding — DO NOT use in production.
    """
    print("=" * 60)
    print("DEMO 3: Manual Loop Control (What asyncio.run() Replaces)")
    print("=" * 60)
    
    print("""
    # ❌ THE MANUAL WAY (Don't do this — error-prone):
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(main_coroutine())
    finally:
        # Must manually cancel pending tasks
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        # Must manually close the loop
        loop.close()
    
    
    # ✅ THE asyncio.run() WAY (Does all the above automatically):
    
    result = asyncio.run(main_coroutine())
    # Loop created, tasks run, cleanup done, loop closed. Done.
    """)


# =============================================================================
# Part 4: GRACEFUL SHUTDOWN PATTERN
# =============================================================================

async def jarvis_main_loop() -> None:
    """
    Simulate JARVIS's main loop with graceful shutdown.
    
    LAYER: Brain (Agent Orchestrator)
    
    In production JARVIS:
        - This loop runs FOREVER (until shutdown signal)
        - It processes user requests as they arrive
        - On shutdown, it cleans up all resources
    """
    shutdown_event = asyncio.Event()
    
    async def request_processor() -> None:
        """Process incoming requests until shutdown."""
        request_count = 0
        while not shutdown_event.is_set():
            # Simulate waiting for a request (with timeout)
            try:
                await asyncio.wait_for(
                    shutdown_event.wait(),
                    timeout=0.2,
                )
            except asyncio.TimeoutError:
                # No shutdown signal — process next request
                request_count += 1
                print(f"    [Agent] Processing request #{request_count}")
                await asyncio.sleep(0.05)  # Simulate work
                
                # Stop after 3 requests for demo
                if request_count >= 3:
                    shutdown_event.set()
        
        print(f"    [Agent] Processed {request_count} requests total")
    
    async def health_monitor() -> None:
        """Background task that monitors system health."""
        while not shutdown_event.is_set():
            print("    [Health] System OK")
            try:
                await asyncio.wait_for(
                    shutdown_event.wait(),
                    timeout=0.3,
                )
            except asyncio.TimeoutError:
                pass
        print("    [Health] Monitor shutting down")
    
    print("\n  Starting JARVIS subsystems...")
    
    # Run both subsystems concurrently
    await asyncio.gather(
        request_processor(),
        health_monitor(),
    )
    
    print("  All subsystems shut down cleanly.")


def demo_graceful_shutdown() -> None:
    """Demonstrate graceful shutdown pattern."""
    print("=" * 60)
    print("DEMO 4: JARVIS Graceful Shutdown Pattern")
    print("=" * 60)
    
    asyncio.run(jarvis_main_loop())
    
    print("\n  [Sync] Back in synchronous world. Process can exit.\n")


# =============================================================================
# Part 5: COMMON MISTAKES WITH asyncio.run()
# =============================================================================

def demo_mistakes() -> None:
    """Show common mistakes with asyncio.run()."""
    print("=" * 60)
    print("DEMO 5: Common Mistakes")
    print("=" * 60)
    
    print("""
    # ❌ MISTAKE 1: Calling asyncio.run() inside async def
    
    async def handler():
        asyncio.run(sub_task())
        # RuntimeError: cannot be called from a running event loop!
    
    # ✅ FIX: Use await instead
    
    async def handler():
        await sub_task()
    
    
    # ─────────────────────────────────────────────────────────────
    
    # ❌ MISTAKE 2: Calling asyncio.run() multiple times
    
    asyncio.run(connect_db())    # Creates loop 1, closes it
    asyncio.run(query_db())      # Creates loop 2 — DB connection lost!
    
    # ✅ FIX: One main() that does everything
    
    async def main():
        db = await connect_db()
        result = await query_db(db)
    
    asyncio.run(main())  # Called ONCE
    
    
    # ─────────────────────────────────────────────────────────────
    
    # ❌ MISTAKE 3: Forgetting to await inside main
    
    async def main():
        fetch_data()  # Missing await! Coroutine never runs!
    
    asyncio.run(main())  # Runs, but fetch_data() never executed
    
    # ✅ FIX: Always await
    
    async def main():
        await fetch_data()
    
    asyncio.run(main())
    """)


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    # Each demo uses its OWN asyncio.run() call
    # This is fine for demos — in production, use ONE asyncio.run()
    
    demo_basic_run()
    demo_internal_mechanics()
    demo_manual_loop()
    demo_graceful_shutdown()
    demo_mistakes()
    
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("""
    | Function                    | Use Case                        |
    |-----------------------------|---------------------------------|
    | asyncio.run(main())         | Start async from sync (once!)   |
    | await coro()                | Run coro inside existing loop   |
    | loop.run_until_complete()   | Low-level, manual loop control  |
    | loop.run_forever()          | Long-running servers/agents     |
    
    RULES:
    1. Call asyncio.run() ONCE at the top level
    2. Never call asyncio.run() inside async code
    3. Never call asyncio.run() multiple times
    4. Use await for everything inside the async world
    """)
