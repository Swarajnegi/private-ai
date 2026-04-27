"""
02_async_def_await_coroutines.py

JARVIS Learning Module: async def, await, and Coroutine Objects.

Run with:
    python 02_async_def_await_coroutines.py

This script demonstrates:
    1. What calling an async function returns (a coroutine object)
    2. How await extracts the value from a coroutine
    3. Coroutine lifecycle and state transitions
    4. Common mistakes and how to avoid them

=============================================================================
THE BIG PICTURE: Coroutines are State Machines
=============================================================================

An async function is NOT a normal function. When you call it:
    - It does NOT run immediately
    - It returns a coroutine object (like a generator object)
    - You must `await` it to actually run it and get the result

This is CRUCIAL for understanding async Python:
    - Calling an async function = creating a task (not running it)
    - Awaiting a coroutine = running the task and getting the result

=============================================================================
THE FLOW (Coroutine Lifecycle)
=============================================================================

    async def my_coroutine():
        return 42

    coro = my_coroutine()     # CREATED: coroutine object exists
            ↓
    result = await coro       # RUNNING → SUSPENDED → DONE
            ↓
    # result = 42

=============================================================================
"""

import asyncio
import inspect
import time
from typing import Any


# =============================================================================
# Part 1: WHAT async def RETURNS
# =============================================================================

async def simple_async_function() -> str:
    """
    An async function. Calling it returns a coroutine object.
    """
    return "Hello from async function!"


def demo_coroutine_object() -> None:
    """
    Demonstrate that calling async def returns a coroutine, not the result.
    """
    print("=" * 60)
    print("DEMO 1: What async def Returns")
    print("=" * 60)
    
    # Calling an async function does NOT run it!
    coro = simple_async_function()
    
    print(f"\n  Called simple_async_function()")
    print(f"  Type: {type(coro)}")
    print(f"  Repr: {coro}")
    print(f"  Is coroutine? {inspect.iscoroutine(coro)}")
    
    # The value is NOT accessible yet!
    print(f"\n  ❌ Cannot get value without await!")
    print(f"     coro is: {coro}")
    print(f"     NOT: 'Hello from async function!'")
    
    # Clean up (avoid RuntimeWarning)
    coro.close()
    
    print()


# =============================================================================
# Part 2: HOW await WORKS
# =============================================================================

async def demo_await() -> None:
    """
    Demonstrate how await extracts the value from a coroutine.
    """
    print("=" * 60)
    print("DEMO 2: How await Extracts the Value")
    print("=" * 60)
    
    # Step 1: Create the coroutine object
    coro = simple_async_function()
    print(f"\n  Step 1: Created coroutine → {type(coro).__name__}")
    
    # Step 2: Await it to get the actual value
    result = await coro
    print(f"  Step 2: Awaited coroutine → result = '{result}'")
    
    # Common shorthand: call and await in one line
    result2 = await simple_async_function()
    print(f"  Shorthand: await simple_async_function() → '{result2}'")
    
    print()


# =============================================================================
# Part 3: COROUTINE LIFECYCLE
# =============================================================================

async def tracked_coroutine(name: str) -> str:
    """
    A coroutine that prints its lifecycle stages.
    """
    print(f"    [{name}] RUNNING: Start of coroutine")
    
    # This await causes suspension
    print(f"    [{name}] SUSPENDING: About to await sleep...")
    await asyncio.sleep(0.1)
    print(f"    [{name}] RESUMED: After sleep")
    
    print(f"    [{name}] COMPLETING: Returning result")
    return f"Result from {name}"


async def demo_lifecycle() -> None:
    """
    Demonstrate the lifecycle of a coroutine.
    """
    print("=" * 60)
    print("DEMO 3: Coroutine Lifecycle")
    print("=" * 60)
    
    print("\n  Creating coroutine (not yet running)...")
    coro = tracked_coroutine("TaskA")
    print(f"  Coroutine created: {coro}")
    
    print("\n  Now awaiting (this runs the coroutine)...")
    result = await coro
    
    print(f"\n  Final result: '{result}'")
    print()


# =============================================================================
# Part 4: MULTIPLE COROUTINES (Sequential vs Concurrent)
# =============================================================================

async def api_call(name: str, delay: float) -> dict[str, Any]:
    """Simulate an API call with a delay."""
    print(f"    [{name}] Starting...")
    await asyncio.sleep(delay)
    print(f"    [{name}] Complete!")
    return {"name": name, "delay": delay}


async def demo_sequential_vs_concurrent() -> None:
    """
    Show the difference between awaiting one-by-one vs all-at-once.
    """
    print("=" * 60)
    print("DEMO 4: Sequential vs Concurrent Awaiting")
    print("=" * 60)
    
    # SEQUENTIAL: Each await blocks until complete
    print("\n  Sequential (await one by one):")
    start = time.perf_counter()
    
    r1 = await api_call("API-1", 0.2)
    r2 = await api_call("API-2", 0.2)
    r3 = await api_call("API-3", 0.2)
    
    elapsed = time.perf_counter() - start
    print(f"    Total time: {elapsed:.2f}s (expected ~0.6s)")
    
    # CONCURRENT: All coroutines run in parallel
    print("\n  Concurrent (await all together):")
    start = time.perf_counter()
    
    # Create coroutines (not running yet!)
    coro1 = api_call("API-1", 0.2)
    coro2 = api_call("API-2", 0.2)
    coro3 = api_call("API-3", 0.2)
    
    # Await all at once
    results = await asyncio.gather(coro1, coro2, coro3)
    
    elapsed = time.perf_counter() - start
    print(f"    Total time: {elapsed:.2f}s (expected ~0.2s)")
    
    print()


# =============================================================================
# Part 5: COMMON MISTAKES
# =============================================================================

async def demo_common_mistakes() -> None:
    """
    Demonstrate common mistakes with async/await.
    """
    print("=" * 60)
    print("DEMO 5: Common Mistakes")
    print("=" * 60)
    
    print("""
    # ❌ MISTAKE 1: Forgetting to await
    
    async def bad_code():
        result = some_async_function()  # Missing await!
        print(result)  # Prints coroutine object, not result
    
    
    # ✅ FIX: Always await async functions
    
    async def good_code():
        result = await some_async_function()
        print(result)  # Prints actual result
    
    
    # ─────────────────────────────────────────────────────────────
    
    # ❌ MISTAKE 2: Using await outside async def
    
    def sync_function():
        result = await async_function()  # SyntaxError!
    
    
    # ✅ FIX: Use asyncio.run() or make the function async
    
    async def async_wrapper():
        result = await async_function()
    
    asyncio.run(async_wrapper())
    
    
    # ─────────────────────────────────────────────────────────────
    
    # ❌ MISTAKE 3: Creating coroutines but not awaiting
    
    async def wasted_work():
        api_call("test", 1.0)  # Creates coroutine, never runs!
        # RuntimeWarning: coroutine was never awaited
    
    
    # ✅ FIX: Either await directly or use create_task
    
    async def proper_work():
        await api_call("test", 1.0)           # Direct await
        # OR
        task = asyncio.create_task(api_call("test", 1.0))
        await task                             # Await later
    
    
    # ─────────────────────────────────────────────────────────────
    
    # ❌ MISTAKE 4: Awaiting the same coroutine twice
    
    async def double_await():
        coro = some_async_function()
        result1 = await coro
        result2 = await coro  # RuntimeError: cannot reuse coroutine!
    
    
    # ✅ FIX: Create a new coroutine for each await
    
    async def correct_multiple():
        result1 = await some_async_function()
        result2 = await some_async_function()  # New coroutine each time
    """)


# =============================================================================
# Part 6: JARVIS PATTERN - Request Handler
# =============================================================================

async def jarvis_request_handler() -> None:
    """
    Demonstrate how JARVIS's request handler uses coroutines.
    
    LAYER: Brain (Agent Orchestrator)
    """
    print("=" * 60)
    print("DEMO 6: JARVIS Request Handler Pattern")
    print("=" * 60)
    
    async def embed_query(query: str) -> list[float]:
        """Simulate embedding API call."""
        print(f"    [Embed] Creating embedding for: '{query}'")
        await asyncio.sleep(0.1)
        return [0.1, 0.2, 0.3]  # Mock embedding
    
    async def search_vectors(embedding: list[float]) -> list[str]:
        """Simulate vector database search."""
        print(f"    [Search] Searching with embedding...")
        await asyncio.sleep(0.1)
        return ["doc_001", "doc_002"]  # Mock results
    
    async def generate_response(query: str, docs: list[str]) -> str:
        """Simulate LLM response generation."""
        print(f"    [LLM] Generating response...")
        await asyncio.sleep(0.2)
        return f"Based on {docs}, answer to '{query}'"
    
    async def process_user_request(query: str) -> str:
        """
        The main request handler.
        
        This function coordinates multiple async operations.
        Each await allows other requests to be processed.
        """
        print(f"\n  Processing request: '{query}'")
        
        # Step 1: Embed the query
        embedding = await embed_query(query)
        
        # Step 2: Search for relevant documents
        docs = await search_vectors(embedding)
        
        # Step 3: Generate response
        response = await generate_response(query, docs)
        
        return response
    
    # Process a request
    result = await process_user_request("What is Python?")
    print(f"\n  Final response: '{result}'")
    print()


# =============================================================================
# Part 7: COROUTINE OBJECT INSPECTION
# =============================================================================

async def demo_coroutine_inspection() -> None:
    """
    Demonstrate how to inspect coroutine objects.
    """
    print("=" * 60)
    print("DEMO 7: Coroutine Object Inspection")
    print("=" * 60)
    
    async def sample_coroutine(x: int) -> int:
        await asyncio.sleep(0.01)
        return x * 2
    
    # Create coroutine object
    coro = sample_coroutine(21)
    
    print(f"\n  Coroutine object: {coro}")
    print(f"  Name: {coro.__name__}")
    print(f"  Qualname: {coro.__qualname__}")
    
    # Check if it's a coroutine
    print(f"\n  inspect.iscoroutine(coro): {inspect.iscoroutine(coro)}")
    print(f"  inspect.iscoroutinefunction(sample_coroutine): {inspect.iscoroutinefunction(sample_coroutine)}")
    
    # Get the result
    result = await coro
    print(f"\n  Result after await: {result}")
    
    print()


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

async def main() -> None:
    """Main entry point."""
    # Run sync demo first (doesn't need await)
    demo_coroutine_object()
    
    # Run async demos
    await demo_await()
    await demo_lifecycle()
    await demo_sequential_vs_concurrent()
    await demo_common_mistakes()
    await jarvis_request_handler()
    await demo_coroutine_inspection()
    
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("""
    | Concept         | What It Is                               |
    |-----------------|------------------------------------------|
    | async def       | Declares a coroutine function            |
    | Coroutine object| A paused computation (call async def)   |
    | await           | Run coroutine, get result, yield control |
    | asyncio.gather  | Run multiple coroutines concurrently     |
    
    KEY INSIGHT:
        Calling async def returns a coroutine object.
        The code doesn't run until you await it.
    
    GOLDEN RULE:
        Every async function call needs an await.
        If you forget, the code never runs.
    """)


if __name__ == "__main__":
    asyncio.run(main())
