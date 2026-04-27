# PHASE 1: Systems Python Roadmap

> **Master Plan Position:** Phase 1 of 6 → [JARVIS_MASTER_ROADMAP.md](../JARVIS_MASTER_ROADMAP.md)  
> **Goal:** Build the engineering capacity to write async, memory-safe, type-safe Python systems.  
> **Your Position:** Track your progress through each sub-phase. Mark lessons as ✅ when complete.

---

## Master Plan (5 Phases)

| Phase | Name | Core Concept | Definition of Done |
|-------|------|--------------|-------------------|
| **1** | Object Model & Memory | How Python manages objects in RAM | You can explain `is` vs `==`, use sentinels, and debug with `id()` |
| **2** | Data Pipelines | Streaming data without loading it all into memory | You can process a 10GB file with constant RAM usage |
| **3** | Async Foundations | Non-blocking I/O and the event loop | You can run 100 API calls concurrently without threads |
| **4** | Concurrent Patterns | Orchestrating multiple async tasks | You can build fault-tolerant parallel workflows with cancellation |
| **5** | Type Safety | Static typing for large codebases | You can enforce contracts between JARVIS components |

---

## Phase 1: Object Model & Memory ✅

**Status:** COMPLETE

| Lesson | Topic | What You Learned |
|--------|-------|------------------|
| 1.1 | `id()` vs `is` vs `==` | Identity (same object in RAM) vs Equality (same value) |
| 1.2 | Interning | Small integers (-5 to 256) and identifier-like strings are cached |
| 1.3 | Sentinel Pattern | Distinguish "key not found" from "key exists with value None" |
| 1.4 | Mutable vs Immutable | Why `frozen=True` on dataclasses prevents accidental mutation |

**Archived to:** `jarvis_data/knowledge_base.jsonl`

---

## Phase 2: Data Pipelines ✅

**Status:** COMPLETE

| Lesson | Topic | Status | Script |
|--------|-------|--------|--------|
| 2.1 | Generators & `yield` | ✅ | `01_generators_yield_lazy_eval.py` |
| 2.2 | Generator Expressions | ✅ | (merged with 2.1) |
| 2.3 | `send()` & Coroutine Control | ✅ | `02_send_throw_close_control.py` |
| 2.4 | Context Managers (`with`) | ✅ | `03_context_managers_resource_safety.py` |
| 2.5 | Custom Context Managers | ✅ | (merged with 2.4) |
| 2.6 | Pipeline Composition | ✅ | (covered in 2.1 — 4-layer pipeline) |

**Final Boss:** ✅ COMPLETE — `01_generators_yield_lazy_eval.py` implements:
1. ✅ Opens files with context manager (auto-closes on error)
2. ✅ Yields chunks via generator (constant RAM)
3. ✅ Accepts `send()` commands (HybridNoveltyGate pattern)
4. ✅ Writes to mock vector store

**Archived to:** `jarvis_data/knowledge_base.jsonl`

---

## Phase 3: Async Foundations ✅

**Status:** COMPLETE

| Lesson | Topic | Status | Script |
|--------|-------|--------|--------|
| 3.1 | The Event Loop | ✅ | `01_asyncio_event_loop.py` |
| 3.2 | `async def` & `await` | ✅ | `02_async_def_await_coroutines.py` |
| 3.3 | `asyncio.run()` | ✅ | `03_asyncio_run_entry_point.py` |
| 3.4 | Async Context Managers | ✅ | `04_async_context_managers.py` |
| 3.5 | Async Generators | ✅ | `05_async_generators_streaming.py` |

**Final Boss v1:** ✅ `final_boss_async_pipeline.py` — 10 simulated papers, gather + semaphore + async generators
**Final Boss v2:** ✅ `final_boss_v2_sync_vs_async.py` — 11 REAL PDFs, sync vs async comparison (1.9x speedup, 9.9x on embedding)

**Archived to:** `jarvis_data/knowledge_base.jsonl` (entries #6, #7, #10, #11, #12)

---

## Phase 4: Concurrent Patterns -- DEFERRED

**Status:** DEFERRED to pre-Stage 3 (Agents)

**Rationale:** `gather()` and `Semaphore` already demonstrated in Final Boss scripts. Remaining skills (TaskGroup, timeouts, cancellation) are Stage 3/4 prerequisites and will be learned when real use cases exist.

**Already covered:**
- `asyncio.gather()` -- Final Boss v1 (10 concurrent fetches) + v2 (11 concurrent embeddings)
- `asyncio.Semaphore` -- Final Boss v1 (rate limiting to 3 concurrent)

**Deferred to pre-Stage 3:**
- `asyncio.TaskGroup` (structured concurrency)
- `asyncio.timeout` / `wait_for` (cancellation)
- `ExceptionGroup` handling (error propagation)

---

## Phase 5: Type Safety -- DEFERRED

**Status:** DEFERRED (learn on demand)

**Rationale:** Basic typing and dataclasses already used throughout all scripts. Advanced patterns (`Protocol`, `TypeVar`, Pydantic) are Stage 3/4 prerequisites.

**Already covered:**
- Basic type hints (`int`, `str`, `list[T]`, `Optional[T]`) -- used in every script
- `@dataclass` -- used in Final Boss v1 + v2

**Learn on demand:**
- `Protocol` -- when building Agent interfaces (Stage 3)
- `TypeVar` / Generics -- when building Router (Stage 4)
- Pydantic -- when validating ingestion inputs (Stage 2.3)

---

## Progress Tracker

| Phase | Status | Lessons Complete |
|-------|--------|------------------|
| 1. Object Model & Memory | ✅ Complete | 4/4 |
| 2. Data Pipelines | ✅ Complete | 6/6 |
| 3. Async Foundations | ✅ Complete | 5/5 + 2 Final Bosses |
| 4. Concurrent Patterns | ⏭ Deferred | gather + semaphore covered |
| 5. Type Safety | ⏭ Deferred | typing + dataclass covered |

**STAGE 1 STATUS: SUFFICIENT FOR STAGE 2**

---

## How to Use This Roadmap

1. **Start a lesson:** Copy the command from the table and run it.
2. **Complete a lesson:** Mark it as done in this file.
3. **Archive understanding:** Use `/memory` to store key insights.
4. **Move to next phase:** When all lessons in a phase are done, update the Progress Tracker.

---

**Next Action:**
> Proceed to **Stage 2: Memory Layer** -> [stage_2_memory/ROADMAP.md](../stage_2_memory/ROADMAP.md)
> First lesson: `@[/learn] Explain embeddings and why they matter for RAG.`
