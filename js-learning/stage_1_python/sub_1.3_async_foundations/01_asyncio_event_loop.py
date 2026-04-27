"""
01_asyncio_event_loop.py

JARVIS Learning Module: The asyncio Event Loop.

Run with:
    python 01_asyncio_event_loop.py

This script demonstrates:
    1. What the event loop is and how it schedules tasks
    2. async def and await — defining and calling coroutines
    3. asyncio.run() — the entry point for async programs
    4. Sequential vs concurrent execution

=============================================================================
THE BIG PICTURE: Why Event Loop?
=============================================================================

JARVIS makes many I/O calls:
    - LLM API (OpenAI, Anthropic)
    - Vector DB (ChromaDB)
    - File system
    - Network requests

Each call involves WAITING (network latency, disk latency).
The event loop lets us do OTHER work during that wait.

=============================================================================
THE FLOW (Event Loop Scheduling)
=============================================================================

    ┌─────────────────────────────────────────────────────────────┐
    │                     EVENT LOOP                               │
    │                                                              │
    │  Task Queue:  [Task A] [Task B] [Task C]                     │
    │                   ↓                                          │
    │  1. Run Task A until it hits `await`                         │
    │  2. Task A pauses, waiting for I/O                           │
    │  3. Run Task B until it hits `await`                         │
    │  4. Task B pauses, waiting for I/O                           │
    │  5. I/O completes for Task A → resume Task A                 │
    │  6. Repeat until all tasks complete                          │
    │                                                              │
    └─────────────────────────────────────────────────────────────┘

=============================================================================
"""

import asyncio
import time
from typing import Any


# =============================================================================
# Part 1: SIMULATING ASYNC I/O
# =============================================================================

async def mock_api_call(name: str, delay: float) -> dict[str, Any]:
    """
    Simulate an async API call (like calling OpenAI or ChromaDB).
    
    LAYER: External I/O
    
    In real JARVIS:
        This would be `await openai.chat.completions.create(...)`
        or `await httpx.get(...)`
    
    The key insight:
        `await asyncio.sleep()` is NON-BLOCKING.
        The event loop can run other tasks during this sleep.
        Compare to `time.sleep()` which BLOCKS the entire thread.
    """
    print(f"[{name}] Starting API call... (will take {delay}s)")
    
    # This is where the magic happens:
    # - The coroutine PAUSES here
    # - Control returns to the event loop
    # - Event loop runs OTHER tasks
    # - After `delay` seconds, this coroutine RESUMES
    await asyncio.sleep(delay)
    
    print(f"[{name}] API call complete!")
    return {"name": name, "status": "success", "latency": delay}


# =============================================================================
# Part 2: SEQUENTIAL vs CONCURRENT EXECUTION
# =============================================================================

async def sequential_execution() -> None:
    """
    Run API calls ONE AT A TIME.
    
    This is what happens if you don't understand async properly.
    Each call waits for the previous one to finish.
    
    Total time = sum of all call times.
    """
    print("\n" + "=" * 60)
    print("DEMO 1: Sequential Execution (SLOW)")
    print("=" * 60)
    
    start = time.perf_counter()
    
    # These run ONE AT A TIME because we await each one immediately
    result1 = await mock_api_call("LLM-1", 0.5)
    result2 = await mock_api_call("LLM-2", 0.5)
    result3 = await mock_api_call("LLM-3", 0.5)
    
    elapsed = time.perf_counter() - start
    print(f"\n[Sequential] Total time: {elapsed:.2f}s (expected: ~1.5s)")
    print(f"[Sequential] Results: {[r['name'] for r in [result1, result2, result3]]}")


async def concurrent_execution() -> None:
    """
    Run API calls IN PARALLEL.
    
    This is the RIGHT way. All calls start immediately.
    We await them all together.
    
    Total time = max of all call times (not sum).
    """
    print("\n" + "=" * 60)
    print("DEMO 2: Concurrent Execution (FAST)")
    print("=" * 60)
    
    start = time.perf_counter()
    
    # Create tasks (start all coroutines immediately)
    task1 = asyncio.create_task(mock_api_call("LLM-1", 0.5))
    task2 = asyncio.create_task(mock_api_call("LLM-2", 0.5))
    task3 = asyncio.create_task(mock_api_call("LLM-3", 0.5))
    
    # Wait for ALL to complete (they run in parallel)
    results = await asyncio.gather(task1, task2, task3)
    
    elapsed = time.perf_counter() - start
    print(f"\n[Concurrent] Total time: {elapsed:.2f}s (expected: ~0.5s)")
    print(f"[Concurrent] Results: {[r['name'] for r in results]}")


# =============================================================================
# Part 3: UNDERSTANDING THE EVENT LOOP DIRECTLY
# =============================================================================

async def demo_event_loop_inspection() -> None:
    """
    Demonstrate how to access and inspect the event loop.
    """
    print("\n" + "=" * 60)
    print("DEMO 3: Event Loop Inspection")
    print("=" * 60)
    
    # Get the currently running event loop
    loop = asyncio.get_running_loop()
    
    print(f"\n[Loop] Event loop object: {loop}")
    print(f"[Loop] Is running: {loop.is_running()}")
    print(f"[Loop] Is closed: {loop.is_closed()}")
    
    # Show what happens during await
    print("\n[Loop] About to await (control returns to event loop)...")
    await asyncio.sleep(0.1)
    print("[Loop] Resumed after await!")


# =============================================================================
# Part 4: THE ANTI-PATTERN (Blocking calls inside async)
# =============================================================================

async def demo_antipattern() -> None:
    """
    Show what NOT to do: blocking calls inside async code.
    """
    print("\n" + "=" * 60)
    print("DEMO 4: Anti-Pattern (Blocking in Async)")
    print("=" * 60)
    
    print("""
    # ❌ WRONG: Using time.sleep() blocks the ENTIRE event loop
    
    async def bad_api_call():
        time.sleep(1)    # BLOCKS! No other task can run!
        return "result"
    
    
    # ✅ CORRECT: Using await asyncio.sleep() is non-blocking
    
    async def good_api_call():
        await asyncio.sleep(1)  # Yields control to event loop
        return "result"
    
    
    # ❌ WRONG: Using requests (sync library) in async code
    
    async def bad_http_call():
        response = requests.get(url)  # BLOCKS!
    
    
    # ✅ CORRECT: Using httpx or aiohttp (async libraries)
    
    async def good_http_call():
        async with httpx.AsyncClient() as client:
            response = await client.get(url)  # Non-blocking!
    """)


# =============================================================================
# Part 5: JARVIS AGENT LOOP PATTERN
# =============================================================================

async def jarvis_agent_loop() -> None:
    """
    Simulate how JARVIS's main loop would use async.
    
    LAYER: Brain (Agent Orchestrator)
    
    The agent loop must:
        1. Listen for user input
        2. Process requests concurrently
        3. Never block on any single operation
    """
    print("\n" + "=" * 60)
    print("DEMO 5: JARVIS Agent Loop Pattern")
    print("=" * 60)
    
    async def process_user_request(request: str) -> str:
        """Simulate processing a user request."""
        print(f"\n[Agent] Processing: '{request}'")
        
        # Run multiple async operations concurrently
        embedding_task = asyncio.create_task(
            mock_api_call("Embedding", 0.3)
        )
        search_task = asyncio.create_task(
            mock_api_call("ChromaDB", 0.2)
        )
        
        # Wait for both
        embedding, search = await asyncio.gather(embedding_task, search_task)
        
        # Now call LLM with results
        llm_result = await mock_api_call("LLM", 0.4)
        
        return f"Response to '{request}': {llm_result['status']}"
    
    # Simulate processing multiple requests
    start = time.perf_counter()
    
    # In real JARVIS, these would come from a queue
    requests = [
        "What is Python?",
        "Summarize this PDF",
    ]
    
    # Process all requests concurrently
    tasks = [process_user_request(req) for req in requests]
    responses = await asyncio.gather(*tasks)
    
    elapsed = time.perf_counter() - start
    
    print(f"\n[Agent] All requests processed in {elapsed:.2f}s")
    for response in responses:
        print(f"[Agent] {response}")


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

async def main() -> None:
    """
    The main async entry point.
    
    asyncio.run(main()) does:
        1. Create a new event loop
        2. Run main() until complete
        3. Close the event loop
    """
    await sequential_execution()
    await concurrent_execution()
    await demo_event_loop_inspection()
    await demo_antipattern()
    await jarvis_agent_loop()
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("""
    | Concept          | What It Does                            |
    |------------------|-----------------------------------------|
    | Event Loop       | Scheduler that runs async tasks         |
    | async def        | Defines a coroutine (pausable function) |
    | await            | Pause here, let other tasks run         |
    | asyncio.run()    | Entry point — creates and runs loop     |
    | create_task()    | Schedule coroutine for concurrent run   |
    | gather()         | Wait for multiple tasks in parallel     |
    
    GOLDEN RULE: Never block the event loop.
                 Use async libraries for I/O.
    """)


if __name__ == "__main__":
    # This is THE entry point for async Python programs
    # It creates an event loop, runs main(), then closes the loop
    asyncio.run(main())
