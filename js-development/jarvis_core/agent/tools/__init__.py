"""
jarvis_core.agent.tools

Tool package marker. Importing this package triggers all `@Tool.register`
decorators across the submodules at import time — so the dispatcher can
discover tools via `Tool.list_registered()` without explicit per-tool
import gymnastics.

Phase A modules (Stage 3.2.2, KB L283 + L289):
    - calc:    1 tool  (calculator)
    - memory:  6 tools (memory_semantic_search, memory_mmr_search,
                         memory_bm25_search, memory_hybrid_search,
                         memory_rerank, memory_unified_retrieve)

Phase B (next):  web, fs, exec, shell        — non-memory base tools
Phase C (next):  cognitive, finance          — identity + finance tools

LAYER: Agent (Tools)
"""

# Import for side-effect (registration). Each module's @Tool.register fires here.
from jarvis_core.agent.tools import calc       # noqa: F401
from jarvis_core.agent.tools import memory     # noqa: F401

__all__: list[str] = []
