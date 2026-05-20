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

Phase B modules (Stage 3.2.2, KB L283):
    - web:     1 tool  (web_search; DuckDuckGo)
    - fs:      1 tool  (file_read; 1MB cap)
    - exec:    1 tool  (code_exec;  subprocess + timeout, requires_permission=True)
    - shell:   1 tool  (shell_run;  asyncio.subprocess_shell, requires_permission=True)

Phase C (next):  cognitive, finance          — identity + finance tools

LAYER: Agent (Tools)
"""

# Import for side-effect (registration). Each module's @Tool.register fires here.
from jarvis_core.agent.tools import calc       # noqa: F401
from jarvis_core.agent.tools import memory     # noqa: F401
from jarvis_core.agent.tools import web        # noqa: F401
from jarvis_core.agent.tools import fs         # noqa: F401
from jarvis_core.agent.tools import exec as _exec_mod  # noqa: F401  (`exec` is builtin name)
from jarvis_core.agent.tools import shell      # noqa: F401

__all__: list[str] = []
