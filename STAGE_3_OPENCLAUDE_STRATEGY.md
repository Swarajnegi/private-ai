# Stage 3 Strategy: Delegate Agent Runtime to OpenClaude, Keep Cognitive Layer in JARVIS

> **Status:** Strategic decision document, awaiting integration kickoff.
> **Authored:** 2026-04-27.
> **Affects:** Stage 3 (Agent Framework) and the foundational pieces of Stage 4 (Multi-Model Orchestration) per [JARVIS_MASTER_ROADMAP.md](../../js-learning/JARVIS_MASTER_ROADMAP.md).
> **Companion docs:** [JARVIS_ENDGAME.md](JARVIS_ENDGAME.md), [js-workspace-rule.md](js-workspace-rule.md), [stage_3_agents/ROADMAP.md](../../js-learning/stage_3_agents/ROADMAP.md).

---

## 1. Executive Summary

**The decision:** Adopt [OpenClaude](https://github.com/Gitlawb/openclaude) — a multi-provider fork of Anthropic's Claude Code CLI — as the agent runtime for JARVIS. Build a thin Python bridge from `jarvis_core` to OpenClaude via MCP and gRPC. Keep the JARVIS-specific cognitive layer (memory tiering, knowledge_base.jsonl, cognitive profiling, specialist routing) in pure Python.

**What this saves:** ~80% of Stage 3 (Agent Framework: function calling, tool registry, ReAct loops, planning, sub-agents) is provided by OpenClaude out-of-the-box. ~30–40% of Stage 4 (provider routing, model selection by latency/cost) is also covered via OpenClaude's `smart_router.py` and `agentRouting` configuration.

**What is still owned by JARVIS:** the bridge to `jarvis_core.memory`, MemGPT-style hot/warm/cold memory tiering tied to the local ChromaDB + JSONL knowledge base, the cognitive profiling pipeline that feeds `knowledge_base.jsonl`, the 12-specialist domain router, and the Stage 4.0 Cognitive Control Loop.

**Effort estimate:** 2–4 weeks of focused integration to land Stage 3 closure. An additional 1–2 weeks to remap OpenClaude's per-sub-agent-type routing into JARVIS's per-domain specialist routing.

**Honest framing for the roadmap:** Stage 3 sub-phases 3.1–3.4 are marked **🔗 Delegated** rather than ✅ Complete. Sub-phase 3.5 (MemGPT) is **🔗 Partial-delegate** + ⬜ JARVIS-specific tiering still required.

**The gate:** at the 2-week mark, ask "am I shipping JARVIS features or fighting the bridge?" If the latter, fall back to building Stage 3 in pure Python.

---

## 2. Background and Motivation

### 2.1 Why this question came up

The JARVIS roadmap allocates 1–2 months to Stage 3, with five substages: function calling + structured output, tool registry, planning + decomposition, ReAct loops, and MemGPT-style memory-augmented agents. From scratch, this is real engineering — easily 1500–2500 LOC of agent runtime, plus learning curves on `outlines`/`guidance`, MCP, ReAct trace persistence, etc.

In April 2026, two third-party repos surfaced as candidates:
- **[Open-Claude-Cowork](../../Open-Claude-Cowork/)** — a Composio + Claude Agent SDK chat-app frontend. **Rejected.** It's an Electron desktop UI that wraps Anthropic's official `Claude Agent SDK` — the agent loop is hidden inside Anthropic's SDK, the tool registry comes from Composio's catalog, and there is no integration point with the JARVIS memory layer. It's a *consumer* of pre-built agent infrastructure, not an agent runtime we can extend.
- **[OpenClaude](../../OpenClaude/)** — an open-source fork of the Claude Code CLI itself, opened up to OpenAI, Gemini, DeepSeek, Ollama, Groq, OpenRouter, etc. **Adopted.** It is the actual agent runtime, with ~40 production tools, sub-agent routing, MCP, gRPC, and a smart provider router.

### 2.2 Why we are not building Stage 3 from scratch

The roadmap was written before OpenClaude existed. Three reasons to delegate:

1. **OpenClaude is battle-tested.** It is a fork of the Claude Code codebase — the same agent loop that ships in Anthropic's official CLI. Reimplementing it in JARVIS-Python would take months and would still be inferior on every metric except "we wrote it ourselves."
2. **The hard parts of Stage 3 are not the parts that get learned by reimplementing.** Function calling, tool dispatch, ReAct trace logging — these are well-trodden mechanics. The genuinely novel JARVIS contributions live in 3.5 (MemGPT against your ChromaDB), 4.0 (Cognitive Control Loop), and the 12-specialist routing. Those still get hand-built.
3. **Time-to-MVP matters.** The endgame for JARVIS is the autonomous R&D loop and cognitive sovereignty — neither of which is gated on us writing our own ReAct implementation. Inheriting the agent runtime moves the MVP forward by ~1 month.

### 2.3 Tradeoff: educational arc

The original roadmap was partly a learning curriculum. Inheriting OpenClaude means we don't *learn* function calling, structured generation, ReAct internals, or tool-registry design by building them. If learning those is the point, this strategy is wrong. If shipping JARVIS is the point, this strategy is right.

The reasonable compromise is a `/learn` workflow pass over the OpenClaude internals at some later date — read the agent loop, read `smart_router.py`, read the MCP plumbing. Curriculum-by-reading rather than curriculum-by-doing.

---

## 3. What OpenClaude Actually Is

### 3.1 Provenance and license

From [OpenClaude/README.md:357–360](../../OpenClaude/README.md):

> "OpenClaude is an independent community project and is not affiliated with, endorsed by, or sponsored by Anthropic. OpenClaude originated from the Claude Code codebase and has since been substantially modified to support multiple providers and open use."

License: MIT. Active fork (28 KB CHANGELOG.md, ongoing releases). Maintained by `Gitlawb` (GitHub). Mirror at `gitlawb.com/node/repos/z6MkqDnb/openclaude`.

### 3.2 Stack

| Layer | Tech |
|---|---|
| Runtime | Bun (preferred) or Node.js ≥20 |
| Language | TypeScript + React (Ink for TUI rendering) |
| Helpers | Python ([OpenClaude/python/](../../OpenClaude/python/)) |
| IPC | gRPC headless server ([OpenClaude/src/grpc/](../../OpenClaude/src/grpc/), [src/proto/](../../OpenClaude/src/proto/)) |
| Plugins | MCP (Model Context Protocol) servers |
| Distribution | `npm install -g @gitlawb/openclaude` + binary in [bin/](../../OpenClaude/bin/) |
| IDE integration | VS Code extension at [vscode-extension/openclaude-vscode/](../../OpenClaude/vscode-extension/openclaude-vscode/) |

### 3.3 Tool inventory

[OpenClaude/src/tools/](../../OpenClaude/src/tools/) contains 40+ tools, each with zod schemas and per-tool permission gates. Categories:

| Category | Tools |
|---|---|
| **Code** | `BashTool`, `PowerShellTool`, `FileReadTool`, `FileWriteTool`, `FileEditTool`, `GlobTool`, `GrepTool`, `LSPTool`, `REPLTool`, `NotebookEditTool` |
| **Agents & tasks** | `AgentTool`, `TaskCreateTool`, `TaskUpdateTool`, `TaskGetTool`, `TaskListTool`, `TaskOutputTool`, `TaskStopTool`, `TeamCreateTool`, `TeamDeleteTool`, `MonitorTool`, `SleepTool` |
| **Plan / control** | `EnterPlanModeTool`, `ExitPlanModeTool`, `EnterWorktreeTool`, `ExitWorktreeTool`, `VerifyPlanExecutionTool`, `TodoWriteTool` |
| **MCP / extension** | `MCPTool`, `ListMcpResourcesTool`, `ReadMcpResourceTool`, `McpAuthTool`, `SkillTool`, `ToolSearchTool` |
| **Web / external** | `WebSearchTool`, `WebFetchTool`, `BriefTool`, `TungstenTool` |
| **UX / scheduling** | `AskUserQuestionTool`, `SendMessageTool`, `RemoteTriggerTool`, `ScheduleCronTool`, `ConfigTool`, `SuggestBackgroundPRTool` |
| **Synthetic / debug** | `SyntheticOutputTool` |

This is materially **more** than what JARVIS Stage 3.2 ("≥10 tools registered with type-safe schemas") asks for. We inherit them all for free.

### 3.4 Agent runtime

Three orthogonal subsystems handle agent coordination:

- **[src/coordinator/](../../OpenClaude/src/coordinator/)** — top-level agent dispatch and lifecycle management.
- **[src/bridge/](../../OpenClaude/src/bridge/)** — inter-process bridge for invoking sub-agents and MCP servers.
- **[src/utils/swarm/](../../OpenClaude/src/utils/swarm/)** — multi-agent swarm coordination (parallel sub-agent execution).
- **[src/tasks/](../../OpenClaude/src/tasks/)** — concrete task implementations: `LocalAgentTask`, `RemoteAgentTask`, `InProcessTeammateTask`, `LocalShellTask`, `MonitorMcpTask`, `DreamTask`.

The **DreamTask** ([src/tasks/DreamTask/](../../OpenClaude/src/tasks/DreamTask/)) is particularly interesting — it appears to be an autonomous background-thinking loop, conceptually overlapping with our autonomous R&D loop ambitions. Worth a deeper read once integration is underway.

### 3.5 Memory subsystems (already present, but session-scoped)

| Path | Purpose | JARVIS overlap? |
|---|---|---|
| [src/services/SessionMemory/](../../OpenClaude/src/services/SessionMemory/) | Per-chat-session memory | Partial — chat context, not knowledge graph |
| [src/services/extractMemories/](../../OpenClaude/src/services/extractMemories/) | Auto-extract facts from conversation | Conceptually adjacent to our cognitive profiling, but feeds different store |
| [src/services/teamMemorySync/](../../OpenClaude/src/services/teamMemorySync/) | Cross-session memory sync | Multi-user feature; not directly relevant |
| [src/utils/memory/](../../OpenClaude/src/utils/memory/) | Memory utilities | Implementation primitives |
| [src/memdir/](../../OpenClaude/src/memdir/) | Memory directory (likely on-disk persistence) | TBD on integration read |
| [src/commands/memory](../../OpenClaude/src/commands/memory/) | `/memory` slash command | Conceptually overlaps with our `/memory` workflow but writes to OpenClaude's store |
| [src/commands/knowledge](../../OpenClaude/src/commands/knowledge/) | `/knowledge` slash command | Worth reading; our knowledge_base.jsonl is the JARVIS counterpart |

**Key insight:** OpenClaude has memory machinery, but it is *not* bound to our ChromaDB or `knowledge_base.jsonl`. We will replace or complement these subsystems via MCP tools that route memory operations to JARVIS-side services.

### 3.6 Multi-provider support

OpenClaude supports the following providers out of the box ([README.md:138–148](../../OpenClaude/README.md)):

| Provider | Setup |
|---|---|
| OpenAI-compatible (OpenAI, OpenRouter, DeepSeek, Groq, Mistral, LM Studio) | `/provider` or env vars |
| Gemini | `/provider`, env vars, or local ADC |
| GitHub Models | `/onboard-github` |
| Codex OAuth | `/provider` with browser sign-in |
| Codex CLI | Existing Codex auth |
| Ollama | `/provider`, env vars, or `ollama launch openclaude --model …` |
| Atomic Chat | Local provider with auto-detection |
| Bedrock / Vertex / Foundry | Env vars |

This directly supports the JARVIS principle of *vendor-agnostic LLM access*. Phase 1–3 of JARVIS uses cloud APIs; Phase 4+ adds local models. OpenClaude's provider abstraction supports both.

### 3.7 The smart router — Stage 4 partially delivered

[OpenClaude/python/smart_router.py](../../OpenClaude/python/smart_router.py) implements:

- A `Provider` dataclass tracking: name, ping_url, api_key_env, cost_per_1k_tokens, big_model, small_model, latency_ms, healthy flag, request_count, error_count, avg_latency_ms.
- A `score(strategy)` method that returns lower-is-better composite scores by `latency`, `cost`, or `balanced`. Strategy `balanced` is `latency_score + cost_score + error_penalty`. Unhealthy providers score `inf`.
- A `SmartRouter` class that pings all configured providers on startup, learns from real request timings (rolling average), routes per-request to the lowest-score provider, and falls back automatically on failure.
- Configuration via env: `ROUTER_MODE=smart|fixed`, `ROUTER_STRATEGY=latency|cost|balanced`, `ROUTER_FALLBACK=true|false`.

**Mapping to JARVIS Stage 4:**
- 4.1 (Model loading & serving): partial — supports remote endpoints; local serving via Ollama is supported.
- 4.2 (Intent classification & routing): **the smart router is doing per-request scoring, not intent classification.** Intent classification is JARVIS-specific.
- 4.3 (Dynamic model management): partial — provider/model swapping per request is supported; local model load/unload is not.

We inherit the *mechanism* (scoring + per-request routing); we still need to add the *intent classification* layer that picks which JARVIS specialist (Scientist, Doctor, Engineer, …) handles a query, then maps that specialist to a model + provider.

### 3.8 Sub-agent routing — `agentRouting`

From [OpenClaude/README.md:170–197](../../OpenClaude/README.md):

```json
{
  "agentModels": {
    "deepseek-v4-flash": {
      "base_url": "https://api.deepseek.com/v1",
      "api_key": "sk-…"
    },
    "gpt-4o": {
      "base_url": "https://api.openai.com/v1",
      "api_key": "sk-…"
    }
  },
  "agentRouting": {
    "Explore":         "deepseek-v4-flash",
    "Plan":            "gpt-4o",
    "general-purpose": "gpt-4o",
    "frontend-dev":    "deepseek-v4-flash",
    "default":         "gpt-4o"
  }
}
```

Mechanism: each sub-agent type maps to a different model. JARVIS adapts this by replacing keys with specialist names: `"The Engineer"` → Qwen2.5-Coder, `"The Scientist"` → DeepSeek-V4, `"The Doctor"` → Claude Sonnet, etc. Effectively a 12-key map covering the entire roster from [JARVIS_ENDGAME.md](JARVIS_ENDGAME.md) §3.

**Caveat:** This routes by sub-agent *type*, not by query intent. JARVIS still needs an intent classifier *before* the routing step — that classifier picks which specialist owns the query, then `agentRouting` resolves that specialist to a model.

### 3.9 gRPC headless mode

[OpenClaude/src/grpc/](../../OpenClaude/src/grpc/) + [src/proto/openclaude.proto](../../OpenClaude/src/proto/) provide a headless agent server. Start with `bun run dev:grpc` (binds `localhost:50051` by default). A Python client can send chat messages, receive streamed text chunks + tool-call events + permission requests, all over gRPC bidirectional streams.

This is the cleanest integration surface: `jarvis_core` Python remains pristine, and OpenClaude is just a service we drive over gRPC for the agent-loop machinery.

### 3.10 MCP server registration

OpenClaude consumes MCP servers — the same protocol Anthropic's Claude Desktop and Claude Code use. We register a JARVIS MCP server at [js-development/jarvis_core/mcp/server.py](../../js-development/jarvis_core/mcp/server.py) (to be created), expose 4–6 memory tools (`jarvis_query`, `jarvis_ingest`, `jarvis_kb_append`, `jarvis_kb_search`, `jarvis_specialist_route`, `jarvis_memgpt_promote`), and the agent loop calls them as ordinary tools. Permission gates apply.

---

## 4. Stage-by-Stage Mapping

The load-bearing section. For each Stage 3 sub-phase from [stage_3_agents/ROADMAP.md](../../js-learning/stage_3_agents/ROADMAP.md), we score what OpenClaude provides and what remains.

### 4.1 Sub-phase 3.1 — Function Calling & Structured Output

| Roadmap requirement | OpenClaude provides | Gap | Status |
|---|---|---|---|
| LLM invokes structured tool calls | `Tool` interface with zod schemas, multi-provider support | `outlines` / `guidance` constrained decoding *not* used (the roadmap specifies it for guaranteed valid JSON) | 🔗 **Delegated**. Constrained decoding is a nice-to-have, not a blocker; OpenClaude handles malformed tool calls gracefully via retry. |
| JSON Schema for tools | zod schemas in every tool's definition | None | ✅ Effectively complete via delegation |
| Parsing tool outputs | Built into OpenClaude agent loop | None | ✅ |
| Error handling for malformed calls | Tool retry + error events streamed back | None | ✅ |
| Structured generation (`outlines`/`guidance`) | Not used; provider-side reliability instead | If you specifically want constrained decoding, build a JARVIS MCP tool that wraps `outlines` and exposes it as a structured-generation primitive | 🟡 Partial — sufficient in practice |

**Net:** 🔗 Delegated. Skip building this from scratch.

### 4.2 Sub-phase 3.2 — Tool Design & Registration

| Roadmap requirement | OpenClaude provides | Gap | Status |
|---|---|---|---|
| Tool abstraction (base class) | Each tool is a TypeScript module with `definition`, `validateInput`, `permissions`, `call` | If you need a Python `Tool` base class, build it on the JARVIS side and expose via MCP | ✅ |
| Built-in tools (calculator, web, code execution) | Bash, REPL, file edit, web search, web fetch, etc. | None | ✅ |
| Tool registry | OpenClaude has dynamic discovery + MCP tool merging | None | ✅ |
| Tool composition | Sub-agents can chain tools; `AgentTool` enables nested agent calls | None | ✅ |
| 10+ tools registered | OpenClaude ships 40+ | None — overflows requirement | ✅ |

**Net:** 🔗 Delegated. Overshoots the requirement by 4×.

### 4.3 Sub-phase 3.3 — Planning & Decomposition

| Roadmap requirement | OpenClaude provides | Gap | Status |
|---|---|---|---|
| Task decomposition | `AgentTool` + `TaskCreateTool` + sub-agent dispatch | None | ✅ |
| Plan representation | `EnterPlanModeTool` / `ExitPlanModeTool` produce structured plan files | None | ✅ |
| Plan execution | Built into agent loop; `VerifyPlanExecutionTool` validates | None | ✅ |
| Replanning on failure | Agent loop handles error states; user can re-issue plans | Replan policy is implicit — JARVIS may want explicit replan triggers (e.g., "if confidence < threshold, replan") | 🟡 Mostly there |

**Net:** 🔗 Delegated. Replan policies become a future enhancement.

### 4.4 Sub-phase 3.4 — ReAct Pattern

| Roadmap requirement | OpenClaude provides | Gap | Status |
|---|---|---|---|
| ReAct overview / Reason→Act→Observe | The entire OpenClaude agent loop is ReAct | None | ✅ |
| Trace logging | Tool calls, observations, tokens are all streamed via SSE/gRPC | Trace persistence to `knowledge_base.jsonl` is not automatic — JARVIS must consume the stream and append `Episodic` / `Failure` entries | 🟡 Partial |
| Observation parsing | Built into the loop | None | ✅ |
| Loop termination | Built-in stop conditions (token limits, tool errors, user interrupt) | JARVIS may want custom termination (confidence-gate: stop if `confidence < 0.6` and escalate) | 🟡 Partial |

**Net:** 🔗 Delegated. Trace persistence to the JARVIS knowledge base is the integration work (TASK-6 below).

### 4.5 Sub-phase 3.5 — Memory-Augmented Agents (MemGPT)

This is the half-delegated, half-JARVIS-owned sub-phase.

| Roadmap requirement | OpenClaude provides | Gap | Status |
|---|---|---|---|
| Working memory (current task context) | Built into agent context window management | None | ✅ |
| Long-term memory (persist to vector store) | `extractMemories` writes to OpenClaude's session store, **not** to JARVIS ChromaDB | Build MCP `jarvis_kb_append` and `jarvis_query` so the agent reads/writes JARVIS memory | ⬜ JARVIS work |
| RAG inside agent loop | OpenClaude doesn't auto-RAG against external stores; depends on tools | Same as above — exposed via MCP `jarvis_query` | ⬜ JARVIS work |
| MemGPT hot/warm/cold tiers | Not implemented | **Pure JARVIS-side build.** Hot = current chat context (in-OpenClaude). Warm = `knowledge_base.jsonl` rows pinned in ChromaDB. Cold = archived JSONL on disk. | ⬜ JARVIS work |
| Self-editing memory (insert/update/delete by agent) | Not implemented as a primitive — would require explicit tools | Build MCP tools: `jarvis_kb_append`, `jarvis_kb_update`, `jarvis_kb_delete`, `jarvis_kb_promote`, `jarvis_kb_demote` | ⬜ JARVIS work |
| Agent evaluation (RAGAS, LLM-as-Judge) | Not built in | Pure JARVIS-side; depends on Stage 2.5 RAGAS integration | ⬜ JARVIS work |

**Net:** 🔗 Partial-delegate (working memory) + ⬜ JARVIS-specific (MemGPT tiering, self-editing, eval).

### 4.6 Stage 4 spillover — what we get for free or nearly free

| Stage 4 sub-phase | OpenClaude coverage | JARVIS work remaining |
|---|---|---|
| **4.0 Cognitive Control Loop** | None | Full build: ContextInjector, RoadmapStateReader, Confidence Gate, SessionMemoryWriter |
| **4.1 Model loading & serving** | Provider abstraction, multi-provider, smart router | Local model serving (vLLM, Ollama beyond default) is partial — OpenClaude supports Ollama natively but not arbitrary vLLM endpoints out of the box |
| **4.2 Intent classification & routing** | `agentRouting` config provides the *resolution* layer (specialist → model). `smart_router.py` provides per-provider scoring. **Intent classifier (query → specialist) is not provided.** | Build a Python intent classifier; output feeds OpenClaude's `agentRouting` keys |
| **4.3 Dynamic model management** | Provider-level model selection per request | Quantization, speculative decoding, GPU-side load/unload — JARVIS work for Phase 4+ |
| **4.4 Response aggregation** | None | Full build: synthesis across multiple specialists, source attribution, conflict flags |
| **4.5 Epistemic control** | None | Full build: confidence scoring, conflict detection, human escalation |
| **4.6 GraphRAG** | None | Full build: Phase 7+ optional |

**Net:** Stage 4 is ~30–40% reduced. The hardest piece (4.0 Cognitive Control Loop) is still entirely on JARVIS.

---

## 5. What JARVIS Still Owns (the 20% No SDK Can Provide)

The five JARVIS-specific subsystems that no third-party agent runtime ships with. These define what makes JARVIS distinct from "Claude Code with a custom prompt."

### 5.1 Bridge from OpenClaude to `jarvis_core.memory`

**What:** An MCP server in Python that exposes JARVIS memory operations as agent tools.

**Where:** [js-development/jarvis_core/mcp/server.py](../../js-development/jarvis_core/mcp/server.py) (to be created).

**Tools to expose:**

| Tool | Purpose | Input schema | Output |
|---|---|---|---|
| `jarvis_query` | Semantic + metadata-filtered query of ChromaDB | `{collection, query_text, n_results, where?}` | List of chunks with metadata |
| `jarvis_ingest` | Ingest a document via `IngestionPipeline` | `{path, source_category}` | Ingestion report |
| `jarvis_kb_append` | Append to `knowledge_base.jsonl` | `{type, tags[], content, expiry?}` | Entry ID |
| `jarvis_kb_search` | Semantic search over knowledge_base entries (loaded into ChromaDB collection `kb`) | `{query, type?, tags?, top_k}` | List of entries |
| `jarvis_specialist_route` | Given a query, return the recommended specialist + model | `{query}` | `{specialist, model, provider, confidence}` |
| `jarvis_memgpt_promote` | Promote a chat-context fact into warm memory | `{content, type, tags}` | Entry ID |

**Why it lives JARVIS-side:** The memory layer is the heart of JARVIS. Putting it inside OpenClaude couples our cognitive sovereignty to a third-party runtime. Keeping it Python-side preserves the option to swap OpenClaude out without losing memory.

**Effort:** ~3–5 days. The wrappers are thin; `JarvisMemoryStore` already exposes the right primitives.

### 5.2 MemGPT-Style Hot/Warm/Cold Memory Tiering

**What:** A Python service that manages memory tier transitions:

- **Hot memory:** Lives in OpenClaude's chat context (current conversation tokens). Managed by OpenClaude's context window logic.
- **Warm memory:** Lives in ChromaDB (`jarvis_data/chromadb/`), keyed by access frequency and recency. The MemGPT manager promotes hot facts here when the chat closes, demotes back into hot via retrieval when relevant queries come in.
- **Cold memory:** Lives as JSONL on disk (`jarvis_data/knowledge_base.jsonl`), archived entries that haven't been retrieved in N days. Periodically re-vectorized into ChromaDB if query patterns change.

**Where:** New module at [js-development/jarvis_core/brain/memgpt.py](../../js-development/jarvis_core/brain/memgpt.py).

**Triggers:**
- **Hot → Warm:** at session end or token-budget pressure, the MemGPT manager extracts decisions/learnings from the chat trace and writes to ChromaDB. Inputs come via MCP `jarvis_kb_append`.
- **Warm → Cold:** nightly cron — entries with `last_accessed > 30d AND access_count < 3` move from ChromaDB to a separate cold-archive JSONL (`jarvis_data/knowledge_base_cold.jsonl`).
- **Cold → Warm:** on retrieval, if a cold entry matches a query, lazily re-embed and reinsert into ChromaDB.

**Why it lives JARVIS-side:** This is JARVIS's signature feature. OpenClaude's memory is session-scoped; JARVIS's memory is lifetime-scoped.

**Effort:** ~1.5–2 weeks (the algorithm is non-trivial; needs proper tier-promotion policies and metrics).

### 5.3 Cognitive Profiling Pipeline

**What:** Auto-detection of user-specific learning signals from each (user_msg, agent_response) pair, persisted to `knowledge_base.jsonl` as `Cognitive_Pattern` entries.

**Signals to detect:**
- `gap_signals` — user clarifies, indicating a comprehension gap; tag with subtype (`jargon_gap`, `abstraction_gap`, `missing_prerequisite`, `scale_confusion`, `analogy_needed`, `connection_gap`)
- `zero_gap_signals` — user proceeds without clarification, indicating instant comprehension
- `refusal_patterns` — user rejects a suggestion; tag the failure mode
- `forward_simulation` — user projects to a future scenario, signaling architectural intuition

**Where:** New service at [js-development/jarvis_core/brain/cognitive_profiler.py](../../js-development/jarvis_core/brain/cognitive_profiler.py).

**How OpenClaude integrates:** Every completed agent turn POSTs `(user_msg, agent_response, trace)` to a JARVIS HTTP endpoint, which runs the cognitive profiler async and appends new patterns to `knowledge_base.jsonl`. OpenClaude's [src/hooks/](../../OpenClaude/src/hooks/) directory likely exposes the right injection point.

**Why it lives JARVIS-side:** This is the second of JARVIS's signature features. OpenClaude doesn't know about gap-signal taxonomy or the user's learning history.

**Effort:** ~1 week (LLM-judged classification of signals; small prompt-engineered taxonomy).

### 5.4 12-Specialist Domain Routing

**What:** Replace OpenClaude's per-sub-agent-type `agentRouting` keys (`Explore`, `Plan`, `general-purpose`, …) with per-domain specialist keys (`The Scientist`, `The Doctor`, `The Engineer`, …).

**Where:** Two pieces:
1. **Intent classifier** (Python, JARVIS-side): given a query, return `{specialist: str, confidence: float}`. Lives at [js-development/jarvis_core/brain/router.py](../../js-development/jarvis_core/brain/router.py).
2. **`agentRouting` config** (OpenClaude-side, in `~/.claude/settings.json`): maps each specialist to a model + provider.

**Flow:**
```
user query
   ↓
JARVIS intent classifier (MCP tool: jarvis_specialist_route)
   ↓
returns {specialist: "The Scientist", confidence: 0.87}
   ↓
OpenClaude reads `agentRouting["The Scientist"]` → "deepseek-v4"
   ↓
OpenClaude routes the agent run to deepseek-v4 via configured provider
   ↓
agent_models["deepseek-v4"] resolves to base_url + api_key
   ↓
provider call, tool calls, response stream
```

**Why this layering?** OpenClaude's `agentRouting` is great for resolution but bad for classification — it's a static map, not a learned classifier. The classifier belongs in JARVIS (uses query embeddings against specialist domain centroids); the resolution stays in OpenClaude (where the provider creds live anyway).

**Effort:** Classifier ~3–4 days (lightweight: embed query, compare against 12 specialist domain centroids, return argmax + softmax confidence). Config remap ~2 hours.

### 5.5 Cognitive Control Loop (Stage 4.0)

**What:** Four-pillar self-awareness layer that injects state into every agent turn.

| Pillar | Implementation | Where |
|---|---|---|
| **Temporal** (timestamp, session age) | `ContextInjector` prepends to system prompt | [js-development/jarvis_core/brain/context_injector.py](../../js-development/jarvis_core/brain/context_injector.py) |
| **Identity** (user, history, patterns) | RAG fetch from `knowledge_base.jsonl` for `Cognitive_Pattern` and `Decision` entries | Same module |
| **Teleological** (current pending task) | `RoadmapStateReader` parses `js-learning/*/ROADMAP.md` for first unchecked `[ ]` task | [js-development/jarvis_core/brain/roadmap_reader.py](../../js-development/jarvis_core/brain/roadmap_reader.py) |
| **Metacognitive** (confidence) | `ConfidenceGate` evaluates draft response against knowledge_base; below threshold → flag uncertainty rather than hallucinate | [js-development/jarvis_core/brain/confidence_gate.py](../../js-development/jarvis_core/brain/confidence_gate.py) |

**How OpenClaude integrates:** Pre-prompt injection. OpenClaude has a system-prompt extension mechanism — likely [src/services/extractMemories/](../../OpenClaude/src/services/extractMemories/) or [src/utils/context.ts](../../OpenClaude/src/utils/) — that we configure to call back into JARVIS for the four-pillar context block before each model call.

**Why it lives JARVIS-side:** This is *the* keystone of JARVIS architecture per [JARVIS_ENDGAME.md](JARVIS_ENDGAME.md). It cannot be delegated.

**Effort:** ~2–3 weeks. This is the most architecturally important JARVIS-specific build, and is technically Stage 4.0 — but pulling it forward (to before Stages 3.5 and 4.1+) is recommended in the prior R&D gap analysis.

---

## 6. Three Architectural Options

### 6.1 Option A — Fork OpenClaude, add JARVIS code inline

**How:** Create a JARVIS branch in `OpenClaude/`. Inject JARVIS-specific TypeScript modules: a memory hook in the agent loop, a domain router, a cognitive profiler client. Build → publish a JARVIS-flavored binary.

**Effort:** 4–6 weeks initial; ongoing upstream merge cost (~1 day/month).

**Pros:**
- Tightest integration; JARVIS can hook directly into the agent loop without IPC overhead.
- Single binary to install.

**Cons:**
- We own a fork. Every upstream release means a merge.
- TypeScript expertise required — the JARVIS team is Python-first.
- Reversibility is poor — once forked, going back to vanilla OpenClaude means rewriting our injections.
- Cognitive sovereignty is muddied — JARVIS is no longer pure Python.

**Risk:** High maintenance cost; high TypeScript surface area.

### 6.2 Option B — OpenClaude as External Runtime, JARVIS via gRPC + MCP (RECOMMENDED)

**How:** Run OpenClaude unmodified as a gRPC service. Build a Python MCP server in `jarvis_core` that exposes memory/routing tools. Configure OpenClaude to use the JARVIS MCP server. JARVIS-specific cognitive layer (MemGPT, profiling, control loop) lives in pure Python and is invoked via MCP tools.

**Effort:** 2–4 weeks total.

**Pros:**
- Cleanest separation — `jarvis_core` stays pure Python; OpenClaude stays vanilla TypeScript.
- Reversibility is high — if OpenClaude breaks, swap in any other MCP-aware agent runtime (Claude Desktop, Claude Code, future SDKs).
- Upstream merges are free — we don't fork.
- Polyglot is unavoidable for any JARVIS that ever wants cloud-deployed specialists, so investing in gRPC/MCP infrastructure pays off twice.

**Cons:**
- Two runtimes to keep alive (Python + Bun/Node).
- gRPC bridge has latency (~5–20ms per round-trip).
- Some hooks may not have clean injection points without forking (e.g., the four-pillar context injection might need a fork after all — see §6.4).

**Risk:** Bridge latency and hook-availability gaps. Mitigated by 2-week re-evaluation gate.

**This is the recommended option.**

### 6.3 Option C — Hybrid: Lightly Fork + Mostly External

**How:** Fork OpenClaude only for one or two essential injections that have no MCP/hook surface (likely: the pre-prompt context-injector for the Cognitive Control Loop). Everything else stays external via MCP/gRPC.

**Effort:** 3–4 weeks.

**Pros:** Fixes the hook-gap from Option B without adopting Option A's full fork burden.

**Cons:** Maintains a small fork — same merge debt as Option A but smaller surface.

**When to adopt:** Only if Option B hits a clear, unfixable hook-availability wall. Default to B and escalate to C if needed.

### 6.4 Hook-availability research is needed before Option B is fully de-risked

We have not yet read `OpenClaude/src/hooks/`, the system-prompt construction path, or the pre-/post-tool-call extension points in detail. Before week-1 of integration, do a focused read of:
- [OpenClaude/src/hooks/](../../OpenClaude/src/hooks/) — what hooks exist, what events fire
- [OpenClaude/src/services/extractMemories/](../../OpenClaude/src/services/extractMemories/) — does it expose the message stream we'd consume
- [OpenClaude/src/proto/openclaude.proto](../../OpenClaude/src/proto/) — what events are streamed over gRPC
- [OpenClaude/docs/hook-chains.md](../../OpenClaude/docs/hook-chains.md) — the hook-chain documentation already exists

If we find clean hook surfaces for system-prompt injection and for response post-processing, Option B is fully viable. If not, fall back to Option C.

---

## 7. Recommended Path: Option B with Defined Fork Escape Hatch

### 7.1 Architectural diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                      USER (terminal / IDE)                       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│            OpenClaude CLI / gRPC server (TypeScript)             │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────┐    │
│  │ Agent loop   │  │ Tool registry│  │ Provider router     │    │
│  │ (ReAct)      │  │ (40+ tools)  │  │ (smart_router.py)   │    │
│  └──────────────┘  └──────────────┘  └─────────────────────┘    │
│         │                                      │                 │
│         │  agentRouting config                 │                 │
│         ▼                                      ▼                 │
│  ┌───────────────────────────────┐  ┌─────────────────────┐    │
│  │ Sub-agents / TaskCreate / MCP │  │ LLM provider calls  │    │
│  │ (incl. JARVIS MCP tools)      │  │ (OpenAI/Gemini/...) │    │
│  └───────────────────────────────┘  └─────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                  │                    │
                  │ MCP                │ HTTP webhook
                  │ (stdio or HTTP)    │ (cognitive profiler)
                  ▼                    ▼
┌─────────────────────────────────────────────────────────────────┐
│         JARVIS Python services (jarvis_core)                     │
│                                                                  │
│  ┌──────────────────────┐  ┌──────────────────────────────┐    │
│  │ MCP server           │  │ Cognitive profiler endpoint   │    │
│  │ - jarvis_query       │  │ - Detects gap_signals         │    │
│  │ - jarvis_ingest      │  │ - Writes Cognitive_Pattern    │    │
│  │ - jarvis_kb_append   │  │   to knowledge_base.jsonl     │    │
│  │ - jarvis_kb_search   │  └──────────────────────────────┘    │
│  │ - jarvis_specialist_ │                                       │
│  │   route              │  ┌──────────────────────────────┐    │
│  │ - jarvis_memgpt_     │  │ Cognitive Control Loop (4.0)  │    │
│  │   promote            │  │ - ContextInjector             │    │
│  └──────────────────────┘  │ - RoadmapStateReader          │    │
│           │                │ - ConfidenceGate              │    │
│           ▼                └──────────────────────────────┘    │
│  ┌──────────────────────┐                                       │
│  │ JarvisMemoryStore    │  ┌──────────────────────────────┐    │
│  │ - ChromaDB           │  │ MemGPT manager                │    │
│  │   (research_papers,  │  │ - Hot/warm/cold tiers         │    │
│  │    knowledge_base,   │  │ - Promotion / demotion logic  │    │
│  │    code_repos)       │  └──────────────────────────────┘    │
│  └──────────────────────┘                                       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                   jarvis_data/ (ChromaDB, JSONL,
                   extracted_images, model_catalog)
```

### 7.2 Key invariants

1. **`jarvis_core` is Python-only.** No TypeScript or JavaScript leaks into `js-development/`.
2. **OpenClaude is unmodified.** All extension is via MCP or gRPC.
3. **Memory operations go through MCP.** OpenClaude never touches `jarvis_data/` directly.
4. **Specialist routing has two stages.** JARVIS classifies (intent → specialist); OpenClaude resolves (specialist → model). No bypassing.
5. **Cognitive profiling is async.** OpenClaude doesn't wait for profiler results; it POSTs and forgets.
6. **Knowledge_base.jsonl is single-writer.** Only the Python side mutates it. OpenClaude reads via MCP (`jarvis_kb_search`).

### 7.3 Escape hatch

If after 2 weeks of integration the bridge is consuming more time than feature work, fall back: rebuild Stage 3.1–3.4 in pure Python using `outlines` for structured generation, a simple `Tool` base class, and a hand-rolled ReAct loop. Cost: 4–6 weeks. The MemGPT and cognitive profiling work transfers cleanly (it lives JARVIS-side regardless).

---

## 8. Concrete Integration Tasks

Numbered, executable. Each task has: ID, name, deliverable, files, dependencies, definition-of-done.

### TASK-1 — Boot OpenClaude on Linux

- **Deliverable:** OpenClaude installed and running on the dev machine.
- **Files:** [OpenClaude/](../../OpenClaude/) (existing clone)
- **Steps:**
  ```bash
  cd /home/swara_unix/work/JARVIS/OpenClaude
  bun install
  bun run build
  bun run dev:grpc      # binds localhost:50051
  ```
  In a separate terminal:
  ```bash
  bun run dev:grpc:cli  # test client
  ```
- **Dependencies:** Bun ≥1.x installed.
- **Definition of done:** gRPC server listens on :50051; test CLI roundtrips a "hello" message; provider configured via env vars or `/provider`.
- **Effort:** 1 day.

### TASK-2 — Define MCP tool schemas

- **Deliverable:** `tools.json` (or zod schemas in Python) defining 6 JARVIS MCP tools.
- **Files:** [js-development/jarvis_core/mcp/schemas.py](../../js-development/jarvis_core/mcp/schemas.py) (new)
- **Tools:** `jarvis_query`, `jarvis_ingest`, `jarvis_kb_append`, `jarvis_kb_search`, `jarvis_specialist_route`, `jarvis_memgpt_promote` (per §5.1).
- **Dependencies:** `mcp` Python package, `pydantic` for input validation.
- **Definition of done:** All 6 schemas defined with input + output shapes; schemas pass `mcp` package validation.
- **Effort:** 1 day.

### TASK-3 — Implement MCP server stub

- **Deliverable:** Python MCP server that exposes the 6 tools and stubs return values.
- **Files:** [js-development/jarvis_core/mcp/server.py](../../js-development/jarvis_core/mcp/server.py) (new)
- **Dependencies:** TASK-2 complete; `mcp` package installed.
- **Implementation:**
  - `jarvis_query` → calls `JarvisMemoryStore.query_collection(...)`
  - `jarvis_ingest` → calls `IngestionPipeline.ingest_pdf(...)`
  - `jarvis_kb_append` → appends a JSON line to `knowledge_base.jsonl`
  - `jarvis_kb_search` → loads `knowledge_base.jsonl` into ChromaDB collection `kb` (lazy index), then queries
  - `jarvis_specialist_route` → stub initially (returns `"The Orchestrator"` always); real implementation in TASK-7
  - `jarvis_memgpt_promote` → stub initially; real implementation in TASK-5
- **Definition of done:** MCP server starts, responds to `tools/list`, executes each tool with correct return shape against a real ChromaDB instance.
- **Effort:** 3–5 days.

### TASK-4 — Wire MCP server into OpenClaude

- **Deliverable:** OpenClaude calls the JARVIS MCP server's tools end-to-end.
- **Files:** `~/.claude/settings.json` or [OpenClaude/server/opencode.json](../../OpenClaude/server/opencode.json)
- **Configuration sketch:**
  ```json
  {
    "mcp": {
      "jarvis": {
        "type": "stdio",
        "command": "python3",
        "args": ["/home/swara_unix/work/JARVIS/js-development/jarvis_core/mcp/server.py"]
      }
    }
  }
  ```
- **Dependencies:** TASK-3 complete; OpenClaude running (TASK-1).
- **Definition of done:** Inside OpenClaude, ask "What papers do I have on agentic RAG?" — agent calls `jarvis_query`, receives ChromaDB results, summarizes. Tool call appears in OpenClaude's tool log.
- **Effort:** 1 day.

### TASK-5 — Implement MemGPT manager

- **Deliverable:** Python service for hot/warm/cold tier transitions.
- **Files:** [js-development/jarvis_core/brain/memgpt.py](../../js-development/jarvis_core/brain/memgpt.py) (new)
- **Dependencies:** TASK-3 complete; ChromaDB collection `kb` populated.
- **Behaviors:**
  - **Hot → Warm:** `MemGPTManager.promote(content, type, tags) -> entry_id` writes to `knowledge_base.jsonl` + indexes into ChromaDB `kb` collection.
  - **Warm → Cold:** nightly script (cron or systemd timer) scans `kb` collection, archives entries with `last_accessed > 30d AND access_count < 3` to `jarvis_data/knowledge_base_cold.jsonl`, removes from `kb`.
  - **Cold → Warm:** on retrieval miss in `kb`, search cold archive; if hit, re-embed and reinsert.
- **Definition of done:** Unit tests pass for promote/demote/restore cycles. Cron runs daily without errors.
- **Effort:** 1.5–2 weeks.

### TASK-6 — Cognitive profiling endpoint + OpenClaude hook

- **Deliverable:** JARVIS HTTP endpoint that ingests (msg, response, trace) and writes `Cognitive_Pattern` entries.
- **Files:** [js-development/jarvis_core/brain/cognitive_profiler.py](../../js-development/jarvis_core/brain/cognitive_profiler.py) (new); a webhook configuration on the OpenClaude side (read [docs/hook-chains.md](../../OpenClaude/docs/hook-chains.md) first to identify the right hook).
- **Dependencies:** TASK-3 complete; `fastapi` + `httpx`.
- **Behaviors:**
  - HTTP POST `/profile` with `{user_msg, agent_response, trace}`.
  - Profiler runs an LLM call (using OpenClaude's provider via direct API or via a JARVIS-side OpenAI-compat call) to classify signals using a small prompt-engineered taxonomy.
  - Detected patterns appended to `knowledge_base.jsonl` as `Cognitive_Pattern` entries.
- **Definition of done:** Five sample interactions produce reasonable `Cognitive_Pattern` entries; entries are retrievable via `jarvis_kb_search`.
- **Effort:** 1 week.

### TASK-7 — Specialist routing

- **Deliverable:** Real implementation of `jarvis_specialist_route`.
- **Files:**
  - [js-development/jarvis_core/brain/router.py](../../js-development/jarvis_core/brain/router.py) (new)
  - Update `jarvis_specialist_route` in [mcp/server.py](../../js-development/jarvis_core/mcp/server.py) to call it.
- **Algorithm:**
  - Maintain 12 specialist domain centroids (one embedding per specialist, computed from a small corpus per specialist's domain — e.g., 50 sentences each).
  - On query, embed the query, compute cosine similarity to each centroid, return argmax + softmax confidence.
- **OpenClaude integration:** The agent loop calls `jarvis_specialist_route(query)` early in the turn. OpenClaude reads `agentRouting[<returned_specialist>]` from settings.json to pick the model.
- **Dependencies:** Specialist domain corpora exist (need to write or scrape).
- **Definition of done:** Top-1 routing accuracy > 80% on a hand-labeled validation set of 50 queries.
- **Effort:** 3–4 days for classifier; 2 days for centroid corpus prep.

### TASK-8 — Update Stage 3 ROADMAP

- **Deliverable:** [stage_3_agents/ROADMAP.md](../../js-learning/stage_3_agents/ROADMAP.md) updated with delegated/partial-delegate status markers and a cross-link to this strategy doc.
- **Files:** [js-learning/stage_3_agents/ROADMAP.md](../../js-learning/stage_3_agents/ROADMAP.md)
- **Edits:**
  - Add a header note: "Status updated 2026-04-27 — Stage 3 sub-phases 3.1–3.4 are 🔗 Delegated to OpenClaude per [STAGE_3_OPENCLAUDE_STRATEGY.md](../../.agent/rules/STAGE_3_OPENCLAUDE_STRATEGY.md)."
  - Update the Progress Tracker table:

    | Sub-Phase | Status |
    |---|---|
    | 3.1 | 🔗 Delegated (OpenClaude) |
    | 3.2 | 🔗 Delegated (OpenClaude, 40+ tools) |
    | 3.3 | 🔗 Delegated (EnterPlanMode + AgentTool) |
    | 3.4 | 🔗 Delegated (OpenClaude agent loop) |
    | 3.5 | 🔗 Partial-delegate + ⬜ JARVIS MemGPT tiering |

- **Dependencies:** None.
- **Definition of done:** ROADMAP shows accurate status; cross-link works.
- **Effort:** 30 minutes.

### TASK-9 — End-to-end acceptance test

- **Deliverable:** A scripted scenario that exercises the full stack.
- **Scenario:**
  1. User (in OpenClaude) asks: "Summarize the agentic RAG paper I ingested."
  2. Agent loop calls `jarvis_query` (MCP) → ChromaDB returns top-5 chunks from `2501.09136v3.pdf`.
  3. Agent loop calls `jarvis_specialist_route` → returns `"The Scientist"`.
  4. OpenClaude resolves `agentRouting["The Scientist"]` → model `deepseek-v4` (or whatever is configured).
  5. Agent generates a summary, streams to user.
  6. Cognitive profiler webhook fires, writes a `Cognitive_Pattern` entry (e.g., "user prefers concrete numbers in summaries").
  7. MemGPT manager triggered at session end → promotes the summary as a `Procedural` entry.
- **Definition of done:** All 7 steps complete without errors; `knowledge_base.jsonl` has at least one new entry; ChromaDB `kb` collection has the promoted entry.
- **Effort:** 2–3 days (writing the test, fixing integration bugs).

### Total estimated effort

| Phase | Tasks | Effort |
|---|---|---|
| Setup | TASK-1 to TASK-4 | 5–8 days |
| Core JARVIS work | TASK-5 to TASK-7 | 2.5–3.5 weeks |
| Polish | TASK-8, TASK-9 | 3–4 days |
| **Total** | | **3.5–5.5 weeks** |

The lower end is achievable if hook-availability research goes cleanly. The upper end accounts for likely friction at TASK-4 (MCP wiring) and TASK-6 (hook injection).

---

## 9. Tradeoffs and Risks

### 9.1 Educational loss

**Risk:** The original roadmap was partly a curriculum. Skipping 3.1–3.4 means we don't learn `outlines`/`guidance` constrained decoding, ReAct internals, or tool-call parsing by building them.

**Mitigation:** Schedule a `/learn` workflow pass over OpenClaude internals at the end of integration. Pair it with [docs/hook-chains.md](../../OpenClaude/docs/hook-chains.md). Curriculum-by-reading rather than curriculum-by-doing.

**Severity:** Low if the goal is shipping JARVIS; high if the goal is mastering agent internals.

### 9.2 Upstream dependency

**Risk:** OpenClaude is a community fork with active development (28 KB CHANGELOG.md). Tracking upstream means periodic merges or pinning to a known-good commit.

**Mitigation:**
- Pin to a specific commit hash in any production install.
- Review upstream every 4–6 weeks.
- If maintenance burden exceeds 1 day/quarter, escape to Option C (light fork) or fall back to pure Python.

**Severity:** Medium. The fork is well-maintained but is one person's project (Gitlawb).

### 9.3 Polyglot complexity

**Risk:** TypeScript + Python = two runtimes, two dependency graphs, two testing toolchains.

**Mitigation:**
- Keep the boundary at MCP/gRPC — both are well-defined contracts.
- Any cloud-deployed JARVIS will have polyglot infrastructure anyway (specialists may be served from different runtimes); investing in MCP/gRPC plumbing pays off twice.
- All JARVIS-specific logic stays Python; OpenClaude is a thin shell.

**Severity:** Low if MCP boundary holds; medium if it leaks (e.g., we end up with TypeScript JARVIS code).

### 9.4 We don't own the agent loop

**Risk:** When OpenClaude's ReAct misbehaves (bad tool retry, infinite loop, malformed parsing), we debug community TypeScript code we didn't write.

**Mitigation:**
- Keep the bridge thin so reverting to pure Python is a 1–2 week revert.
- Document every customization to OpenClaude (settings.json, MCP config) so the interface to `jarvis_core` is reproducible.
- Treat upstream OpenClaude bugs as "out of JARVIS scope" — file upstream, work around, don't fix in-tree.

**Severity:** Medium. Worst case: a bug we can't reproduce or fix, 1 week of frustration.

### 9.5 Architectural alignment with workspace-rule.md "Single-Model First"

**Risk:** [js-workspace-rule.md](js-workspace-rule.md) §3 says: "Build complete JARVIS with ONE powerful model first." OpenClaude ships multi-provider as the headline feature, biasing toward provider-switching.

**Mitigation:**
- Configure OpenClaude with one provider only (e.g., DeepSeek-V4 via OpenRouter) for Phase 1–3.
- Disable `smart_router` and `agentRouting` until Stage 4 is ready.
- The 12-specialist domain routing is Phase 4+ work — don't activate until then.

**Severity:** Low. Configuration discipline solves this.

### 9.6 API key surface area

**Risk:** OpenClaude's `agentRouting` and `smart_router` store API keys in plaintext in `settings.json`. The README explicitly warns about this.

**Mitigation:**
- Use environment variables for API keys, not settings.json.
- Add `~/.claude/settings.json` to `.gitignore` if not already.
- Use secret management (1Password CLI, age, sops) for production.

**Severity:** Medium-high. A leaked OpenAI key is real money loss. Treat seriously.

### 9.7 Latency from gRPC/MCP bridge

**Risk:** Each MCP tool call adds 5–20ms of round-trip latency. For agent loops that issue 5–10 tool calls per query, that's 25–200ms extra.

**Mitigation:**
- Profile early. If latency is a problem, switch from `stdio` MCP to HTTP MCP with persistent connections.
- Batch operations when possible (e.g., one `jarvis_query` returning 5 results vs. 5 separate calls).

**Severity:** Low. Sub-second total agent latency is dominated by LLM calls (1–10 seconds), not bridge overhead.

### 9.8 Loss of granular control over tool permissions

**Risk:** OpenClaude has its own tool-permission system. JARVIS's tool-permission philosophy may differ.

**Mitigation:**
- Read [src/utils/permissions/](../../OpenClaude/src/utils/permissions/) carefully during integration.
- For any JARVIS-specific permission rules (e.g., "never delete from knowledge_base.jsonl without explicit user approval"), enforce them in the MCP tool implementations themselves, not in the OpenClaude permission layer.

**Severity:** Low. Defense-in-depth at the MCP layer is straightforward.

---

## 10. Decision Criteria — When to Adopt vs. Reject

### 10.1 Adopt this strategy if:

- Time-to-MVP matters more than learning every primitive yourself.
- You're comfortable maintaining a Python ↔ TypeScript bridge.
- You're willing to pin to a known commit and review upstream periodically (~1 day/quarter).
- The JARVIS endgame (autonomous R&D loop, cognitive sovereignty) matters more than the educational arc.
- You expect to ship JARVIS within 6 months.

### 10.2 Reject (or defer) this strategy if:

- The educational arc *is* the point of JARVIS for you.
- You want every line of the agent loop to be JARVIS-owned and Python-native.
- The 12-specialist mental model differs enough from OpenClaude's that the bridge becomes leaky abstraction (revisit at week 2 of integration).
- You don't have time for the Python ↔ TypeScript polyglot setup.
- The JARVIS goal is to be a research artifact rather than a working tool.

### 10.3 Currently leaning toward adopt because:

- The previously-completed memory layer (Stage 2) is production-quality but isolated. Without an agent runtime, it has no consumer.
- Building Stage 3 from scratch costs 1–2 months. OpenClaude collapses it to 3–5 weeks.
- The JARVIS-specific pieces (MemGPT, profiling, control loop) cost the same in either path; only the agent runtime differs.
- 80% delegation of Stage 3 + 30% delegation of Stage 4 is real time savings — ~1.5–2 months recovered.

---

## 11. Re-Evaluation Gate

**At the 2-week mark of integration (after TASK-4 should be complete):**

- **Question:** Am I shipping JARVIS features (Stage 3.5 MemGPT, cognitive profiler, specialist routing), or am I fighting the OpenClaude bridge (MCP debugging, hook-availability gaps, settings.json wrangling)?
- **Pass:** Continue. Aim for full Stage 3 closure by week 4.
- **Fail:** Fall back. Rebuild Stage 3.1–3.4 in pure Python using:
  - `outlines` for structured generation
  - A simple `JarvisTool` base class with `pydantic` schemas
  - A hand-rolled ReAct loop (~300 LOC)
  - Direct provider calls via `openai` / `anthropic` / `httpx`

The MemGPT manager, cognitive profiler, and Cognitive Control Loop work transfers cleanly — they live JARVIS-side regardless of agent runtime choice.

**Cost of fallback:** ~4–6 additional weeks. Acceptable.

---

## 12. Definition of "Stage 3: Delegated, not Complete"

The roadmap update in TASK-8 introduces a new status marker. Three statuses:

| Symbol | Meaning |
|---|---|
| ✅ **Complete** | Built in JARVIS; production-grade; tested. |
| 🔗 **Delegated** | Provided by OpenClaude with a working bridge in place. JARVIS *uses* it but does not *own* the implementation. |
| 🔗 **Partial-delegate** | Some of the requirement is delegated; the rest is JARVIS-owned. |
| ⬜ **Not started** | No work yet. |

**Stage 3 status after this strategy lands:**

| Sub-phase | Status | Owner |
|---|---|---|
| 3.1 Function calling + structured output | 🔗 Delegated | OpenClaude (constrained-decoding nice-to-have skipped) |
| 3.2 Tool design + registry | 🔗 Delegated | OpenClaude (40+ tools, plus JARVIS MCP tools) |
| 3.3 Planning + decomposition | 🔗 Delegated | OpenClaude (`EnterPlanMode`, `AgentTool`) |
| 3.4 ReAct pattern | 🔗 Delegated | OpenClaude (full agent loop) |
| 3.5 Memory-augmented agents | 🔗 Partial-delegate + ⬜ | OpenClaude session-memory + JARVIS MemGPT manager |

**Stage 4 status after this strategy lands:**

| Sub-phase | Status | Owner |
|---|---|---|
| 4.0 Cognitive Control Loop | ⬜ Not started | JARVIS (keystone) |
| 4.1 Model loading + serving | 🔗 Partial-delegate | OpenClaude (provider abstraction) + JARVIS (Phase 4+ local serving) |
| 4.2 Intent classification + routing | 🔗 Partial-delegate | JARVIS classifier + OpenClaude `agentRouting` resolver |
| 4.3 Dynamic model management | 🔗 Partial-delegate | OpenClaude (per-request) + JARVIS (Phase 4+ quantization) |
| 4.4 Response aggregation | ⬜ | JARVIS |
| 4.5 Epistemic control | ⬜ | JARVIS |
| 4.6 GraphRAG | ⬜ | JARVIS (Phase 7+) |

**Honesty principle:** Don't mark anything ✅ Complete that isn't actually built and tested in JARVIS. Delegation is a real status but it isn't completion.

---

## 13. Appendix: File-by-File Reference Map

### OpenClaude paths to know

| Path | Purpose |
|---|---|
| [OpenClaude/src/tools/](../../OpenClaude/src/tools/) | 40+ tool implementations |
| [OpenClaude/src/coordinator/](../../OpenClaude/src/coordinator/) | Top-level agent dispatch |
| [OpenClaude/src/bridge/](../../OpenClaude/src/bridge/) | IPC bridge for sub-agents and MCP |
| [OpenClaude/src/utils/swarm/](../../OpenClaude/src/utils/swarm/) | Multi-agent swarm coordination |
| [OpenClaude/src/tasks/](../../OpenClaude/src/tasks/) | LocalAgentTask, RemoteAgentTask, DreamTask, etc. |
| [OpenClaude/src/services/SessionMemory/](../../OpenClaude/src/services/SessionMemory/) | Chat-session memory |
| [OpenClaude/src/services/extractMemories/](../../OpenClaude/src/services/extractMemories/) | Auto-fact extraction |
| [OpenClaude/src/services/mcp/](../../OpenClaude/src/services/mcp/) | MCP integration |
| [OpenClaude/src/grpc/](../../OpenClaude/src/grpc/) | gRPC headless server |
| [OpenClaude/src/proto/](../../OpenClaude/src/proto/) | gRPC contract |
| [OpenClaude/src/hooks/](../../OpenClaude/src/hooks/) | Hook system |
| [OpenClaude/src/utils/permissions/](../../OpenClaude/src/utils/permissions/) | Tool permission gates |
| [OpenClaude/python/smart_router.py](../../OpenClaude/python/smart_router.py) | Multi-provider scorer |
| [OpenClaude/docs/hook-chains.md](../../OpenClaude/docs/hook-chains.md) | Hook documentation (read first during integration) |
| [OpenClaude/README.md](../../OpenClaude/README.md) | Setup, providers, agentRouting |

### JARVIS paths to be created

| Path | Purpose | Task |
|---|---|---|
| [js-development/jarvis_core/mcp/server.py](../../js-development/jarvis_core/mcp/server.py) | MCP server exposing JARVIS memory tools | TASK-3 |
| [js-development/jarvis_core/mcp/schemas.py](../../js-development/jarvis_core/mcp/schemas.py) | Tool schemas | TASK-2 |
| [js-development/jarvis_core/brain/memgpt.py](../../js-development/jarvis_core/brain/memgpt.py) | Hot/warm/cold memory manager | TASK-5 |
| [js-development/jarvis_core/brain/cognitive_profiler.py](../../js-development/jarvis_core/brain/cognitive_profiler.py) | Auto-profiles user from conversation | TASK-6 |
| [js-development/jarvis_core/brain/router.py](../../js-development/jarvis_core/brain/router.py) | 12-specialist intent classifier | TASK-7 |
| [js-development/jarvis_core/brain/context_injector.py](../../js-development/jarvis_core/brain/context_injector.py) | Stage 4.0 four-pillar injection | Future |
| [js-development/jarvis_core/brain/roadmap_reader.py](../../js-development/jarvis_core/brain/roadmap_reader.py) | Parses ROADMAP.md for next-task | Future |
| [js-development/jarvis_core/brain/confidence_gate.py](../../js-development/jarvis_core/brain/confidence_gate.py) | Confidence-based escalation | Future |

### JARVIS paths to be updated

| Path | Update | Task |
|---|---|---|
| [js-learning/stage_3_agents/ROADMAP.md](../../js-learning/stage_3_agents/ROADMAP.md) | Mark sub-phases as 🔗 Delegated | TASK-8 |
| `~/.claude/settings.json` | MCP server registration + agentRouting | TASK-4 |

### Existing JARVIS files referenced

| Path | Purpose |
|---|---|
| [js-development/jarvis_core/config.py](../../js-development/jarvis_core/config.py) | Path registry (already portable as of 2026-04-27) |
| [js-development/jarvis_core/memory/store.py](../../js-development/jarvis_core/memory/store.py) | `JarvisMemoryStore` — wrapped by `jarvis_query`, `jarvis_kb_search` |
| [js-development/jarvis_core/memory/ingestion.py](../../js-development/jarvis_core/memory/ingestion.py) | `IngestionPipeline` — wrapped by `jarvis_ingest` |
| [jarvis_data/knowledge_base.jsonl](../../jarvis_data/knowledge_base.jsonl) | Long-term memory (137 entries today) |
| [jarvis_data/chromadb/](../../jarvis_data/chromadb/) | Vector store |
| [.agent/rules/JARVIS_ENDGAME.md](JARVIS_ENDGAME.md) | 12-specialist roster, 4-layer architecture |
| [.agent/rules/js-workspace-rule.md](js-workspace-rule.md) | Single-Model-First principle |

---

## 14. Open Questions (Resolve Before TASK-1 Kickoff)

1. **Hook availability:** Does OpenClaude expose a pre-prompt extension point for the four-pillar context injector (Stage 4.0)? Read [docs/hook-chains.md](../../OpenClaude/docs/hook-chains.md) to determine if Option B is fully viable or if we need Option C.
2. **MCP transport:** stdio (simple, fork-per-call overhead) or HTTP (persistent, more complex)? Default to stdio; switch to HTTP if latency profiling demands it.
3. **Single-provider Phase 1–3:** Which provider/model? Recommendation: DeepSeek-V4 via OpenRouter — cheap, capable, supported by OpenClaude.
4. **Knowledge_base.jsonl indexing:** Materialize as a ChromaDB collection (fast, requires re-indexing on every append) or query lazily on each `jarvis_kb_search` (slow, no re-index needed)? Recommendation: lazy materialization — index on first `jarvis_kb_search` call per process, dirty-flag on append, re-index on next call.
5. **MemGPT cold archive format:** Single rotating JSONL or sharded by month? Recommendation: monthly shards (`knowledge_base_cold_2026-04.jsonl`) — easier to back up, smaller restore footprint.
6. **Cognitive profiler LLM choice:** Same model as agent runtime (cheap, consistent) or a smaller dedicated model (cost-optimized, can run async on a separate process)? Recommendation: same model initially; revisit if cognitive profiling cost > 10% of total LLM spend.

---

## 15. Glossary

| Term | Definition |
|---|---|
| **MCP** | Model Context Protocol. Anthropic's open standard for tool/resource exposure to agent runtimes. |
| **gRPC** | High-performance RPC framework. Used by OpenClaude for headless mode. |
| **ReAct** | Reasoning + Acting agent pattern (Yao et al., 2022). Core loop of OpenClaude. |
| **MemGPT** | Memory architecture treating LLM context like virtual memory (Packer et al., 2023, paper 2310.08560). Hot/warm/cold tiering with self-paging. |
| **RAGAS** | Evaluation framework for RAG pipelines (faithfulness, relevance, context recall, correctness). |
| **Cognitive Pattern** | A `knowledge_base.jsonl` entry type capturing user-specific learning signals (gap_signals, zero_gap_signals, refusal_patterns, forward_simulation). |
| **Specialist** | A JARVIS domain expert (Scientist, Doctor, Engineer, Operator, Electrician, Mechanic, Chemist, Strategist, Analyst, Guardian, Interface, Orchestrator). |
| **`agentRouting`** | OpenClaude config that maps sub-agent type → model. JARVIS reuses with specialist names. |
| **smart_router** | OpenClaude's per-request provider scorer (latency + cost + error rate). Conceptually adjacent to but distinct from JARVIS specialist routing. |

---

*End of strategy document. Length: ~720 lines, ~30 KB.*
