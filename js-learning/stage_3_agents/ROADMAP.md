# PHASE 3: Agent Framework Roadmap

> **Master Plan Position:** Phase 3 of 6 → [JARVIS_MASTER_ROADMAP.md](../JARVIS_MASTER_ROADMAP.md)  
> **Goal:** Build autonomous agents that can plan, use tools, and execute multi-step tasks.  
> **Prerequisites:** Phase 1 (Systems Python), Phase 2 (Memory Layer)

---

## Overview

| Sub-Phase | Name | Core Concept | Definition of Done |
|-----------|------|--------------|-------------------|
| **3.1** | Function Calling & Structured Output | LLMs that invoke structured functions reliably | Agent produces guaranteed-valid JSON tool calls |
| **3.2** | Tool Design & Registration | Build composable tool libraries | 10+ tools registered with type-safe schemas |
| **3.3** | Planning & Decomposition | Break complex queries into steps | Agent decomposes multi-step tasks correctly |
| **3.4** | ReAct Pattern | Reason → Act → Observe loop | Working ReAct agent with trace logging |
| **3.5** | Memory-Augmented Agents (MemGPT) | Self-editing memory with hot/warm/cold tiers | Agent self-manages memory across sessions |

---

## Sub-Phase 3.0: MCP Bridge 🔄 YOU ARE HERE

**Goal:** Build the Model Context Protocol (MCP) bridge to expose JARVIS memory as tools for OpenClaude.

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 3.0.1 | MCP Server Fundamentals | Understand MCP server-client architecture | `@[/learn] Explain Model Context Protocol (MCP) — server architecture, tool registration, JSON-RPC transport.` |
| 3.0.2 | Exposing Memory Primitives | Turn search/expansion/compression into tools | `/dev Build jarvis_core/agent/mcp_bridge.py exposing store / expansion / compression / bm25 / hybrid / rerank as MCP tools.` |
| 3.0.3 | Integration with OpenClaude | Test the bridge with Claude Desktop / Antigravity | `/dev Configure and test JARVIS MCP bridge with Claude.` |

**Practical Exercise:** Successfully retrieve a fact from your private knowledge base using Claude via the JARVIS MCP bridge.

---

## Sub-Phase 3.1: Function Calling & Structured Output ⬜

**Goal:** Understand how LLMs invoke structured functions — and guarantee valid output.

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 3.1.1 | Function Calling Basics | LLM outputs structured tool calls | `@[/learn] Explain function calling in LLMs.` |
| 3.1.2 | JSON Schema for Tools | Define what tools accept | `@[/learn] Explain JSON Schema for tool definitions.` |
| 3.1.3 | Parsing Tool Outputs | Handle LLM function call responses | `/dev Build a function call parser for JARVIS.` |
| 3.1.4 | Error Handling | Gracefully handle malformed calls | `/dev Implement robust error handling for tool calls.` |
| 3.1.5 | Structured Generation (outlines/guidance) | Guarantee valid JSON via constrained decoding | `@[/learn] Explain outlines and guidance for constrained LLM output.` |

**Practical Exercise:** Make an LLM call a `calculator(expr: str)` — with `outlines` guaranteeing valid JSON every time.

> **Why This Matters:** Without constrained decoding, tool-calling agents break
> randomly on malformed output. `outlines.generate.json(model, ToolCallSchema)`
> guarantees valid ToolCall every time. The model literally cannot produce
> invalid JSON.

---

## Sub-Phase 3.2: Tool Design & Registration ⬜

**Goal:** Build a library of composable tools JARVIS can use.

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 3.2.1 | Tool Abstraction | A common interface for all tools | `/dev Design a Tool base class for JARVIS.` |
| 3.2.2 | Built-in Tools | Calculator, web search, code execution | `/dev Implement core tools for JARVIS.` |
| 3.2.3 | Tool Registry | Dynamic tool discovery and registration | `/dev Build a ToolRegistry for JARVIS.` |
| 3.2.4 | Tool Composition | Chain tools together | `@[/learn] Explain tool composition patterns.` |

**Practical Exercise:** Build a registry with 5 tools and let the agent choose which to use.

---

## Sub-Phase 3.3: Planning & Decomposition ⬜

**Goal:** Teach agents to break complex queries into steps.

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 3.3.1 | Task Decomposition | Break "research X" into sub-tasks | `@[/learn] Explain task decomposition in agents.` |
| 3.3.2 | Plan Representation | How to structure a multi-step plan | `/dev Design a Plan data structure for JARVIS.` |
| 3.3.3 | Plan Execution | Execute steps in order with state | `/dev Implement a PlanExecutor for JARVIS.` |
| 3.3.4 | Replanning | Adjust when steps fail | `@[/learn] Explain replanning strategies.` |

**Practical Exercise:** Agent correctly decomposes "Find papers on X and summarize top 3."

---

## Sub-Phase 3.4: ReAct Pattern ⬜

**Goal:** Implement the Reason → Act → Observe loop.

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 3.4.1 | ReAct Overview | The core agent loop | `@[/learn] Explain the ReAct pattern.` |
| 3.4.2 | Trace Logging | Record all reasoning and actions | `/dev Implement ReAct trace logging.` |
| 3.4.3 | Observation Parsing | Handle tool outputs in the loop | `/dev Build an observation parser for ReAct.` |
| 3.4.4 | Loop Termination | Know when to stop | `@[/learn] Explain stopping conditions in agents.` |

**Practical Exercise:** ReAct agent answers a multi-hop question with tool use.

---

## Sub-Phase 3.5: Memory-Augmented Agents (MemGPT) ⬜

**Goal:** Agents that self-manage memory — hot/warm/cold tiers, auto-eviction, self-editing.

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 3.5.1 | Working Memory | Short-term context for current task | `@[/learn] Explain working memory in agents.` |
| 3.5.2 | Long-Term Memory | Persist to Phase 2 vector store | `/dev Connect agent to ChromaDB memory.` |
| 3.5.3 | Memory Retrieval in Loop | RAG inside the agent loop | `/dev Implement memory-augmented ReAct.` |
| 3.5.4 | MemGPT Architecture | Hot/warm/cold memory hierarchy | `/research Analyze paper 2310.08560 (MemGPT) for JARVIS memory self-management.` |
| 3.5.5 | Self-Editing Memory | Agent decides what to remember/forget/update | `/dev Implement MemGPT-style memory manager for JARVIS.` |
| 3.5.6 | Agent Evaluation | RAGAS + LLM-as-Judge for agent quality | `@[/learn] Explain agent evaluation with RAGAS and LLM-as-Judge.` |

**Practical Exercise:** Agent self-manages memory: promotes important facts, evicts stale entries,
rembers user preferences — all without manual `/memory` commands.

> **Key Paper:** `2310.08560v2.pdf` (MemGPT) — already in your Research Papers folder.
> The agent treats memory like an OS virtual memory system:
> Hot = current context, Warm = pinned in ChromaDB, Cold = archived on disk.

---

## Final Boss: The Mind

Build a complete agent that:
1. [ ] Decomposes "Research topic X and write a summary" into steps
2. [ ] Uses tools: web search, memory retrieval, code execution
3. [ ] Follows ReAct loop with trace logging
4. [ ] Persists new learnings to long-term memory
5. [ ] Handles failures and replans

**When this works, JARVIS can think.**

---

## Progress Tracker

| Sub-Phase | Status | Lessons Complete |
|-----------|--------|------------------|
| 3.1 Function Calling & Structured Output | ⬜ Not Started | 0/5 |
| 3.2 Tool Design & Registration | ⬜ Not Started | 0/4 |
| 3.3 Planning & Decomposition | ⬜ Not Started | 0/4 |
| 3.4 ReAct Pattern | ⬜ Not Started | 0/4 |
| 3.5 Memory-Augmented Agents (MemGPT) | ⬜ Not Started | 0/6 |

---

## After This Phase

→ Proceed to **Phase 4: Multi-Model Orchestration** → [PHASE_04_ROADMAP.md](../orchestration-learning/PHASE_04_ROADMAP.md)
