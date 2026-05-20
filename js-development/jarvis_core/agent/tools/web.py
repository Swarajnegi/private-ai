"""
web.py

JARVIS Agent Layer: Web search tool (Category A — Callable).

Import-time registration:
    @Tool.register("web_search")

LAYER: Agent (Tools)

=============================================================================
THE BIG PICTURE
=============================================================================

Without a web_search tool:
    -> The agent is locked to JARVIS Memory (private corpus). It cannot
       answer questions about current events, find new research papers,
       or check the state of external systems.

With web_search:
    -> Agent emits {"tool": "web_search", "input": {"query": "...", "max_results": 5}}.
    -> Tool returns a list of {url, title, snippet} dicts.
    -> Concurrency-safe (read-only network). No permission gating —
       reading the public web is safe by default. Stage 3.4 STEAL #9
       permission engine can later add per-domain allowlists if needed.

=============================================================================
THE FLOW
=============================================================================

STEP 1: Dispatcher instantiates WebSearchTool() at app startup.
        Optional: pass `client` callable for testing or alternate backends.
        |
        v
STEP 2: Agent emits a tool call with {query, max_results}.
        |
        v
STEP 3: invoke() calls self._client(query, max_results).
        Default client lazy-imports duckduckgo-search.
        |
        v
STEP 4: Returns ToolResult(output={"results": [...]}).

=============================================================================
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from pydantic import Field

from jarvis_core.agent.tool import Tool, ToolInput, ToolResult


# Type alias for the pluggable search backend.
SearchClient = Callable[[str, int], List[Dict[str, str]]]


# =============================================================================
# Part 1: DEFAULT BACKEND (lazy duckduckgo-search; fail-loud if missing)
# =============================================================================

def _default_ddg_client(query: str, max_results: int) -> List[Dict[str, str]]:
    """Default backend using duckduckgo-search. Lazy-imports so missing dep
    only fails when the tool is actually invoked, not at module load.

    Returns a list of dicts with keys {url, title, snippet}.
    Raises ImportError with install instruction if duckduckgo-search missing.
    """
    try:
        from duckduckgo_search import DDGS  # type: ignore
    except ImportError as e:
        raise ImportError(
            "duckduckgo-search not installed. Install with: "
            "pip install duckduckgo-search"
        ) from e

    results: List[Dict[str, str]] = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=max_results):
            results.append({
                "url": str(r.get("href") or r.get("url") or ""),
                "title": str(r.get("title") or ""),
                "snippet": str(r.get("body") or r.get("snippet") or ""),
            })
    return results


# =============================================================================
# Part 2: TOOL
# =============================================================================

class WebSearchInput(ToolInput):
    query: str = Field(description="Web search query.")
    max_results: int = Field(
        default=5, ge=1, le=20,
        description="Max number of results to return.",
    )


@Tool.register("web_search")
class WebSearchTool(Tool):
    """Web search via DuckDuckGo (no API key required)."""

    name = "web_search"
    description = (
        "Search the public web via DuckDuckGo. Returns a list of "
        "{url, title, snippet} results for the given query. Use when the "
        "agent needs information NOT in JARVIS Memory (current events, "
        "external state, recent research)."
    )
    input_schema = WebSearchInput

    def __init__(self, client: Optional[SearchClient] = None) -> None:
        self._client: SearchClient = client or _default_ddg_client

    @property
    def is_concurrency_safe(self) -> bool:
        return True  # Read-only external HTTP

    async def invoke(self, tool_input: WebSearchInput) -> ToolResult:
        try:
            results = self._client(tool_input.query, tool_input.max_results)
        except ImportError as e:
            return ToolResult(error=str(e))
        except Exception as e:
            return ToolResult(error=f"Web search failed: {type(e).__name__}: {e}")
        return ToolResult(output={"results": results, "count": len(results)})


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS  (use mock client; no network)
# =============================================================================

if __name__ == "__main__":
    import asyncio
    from jarvis_core.agent.tool import safe_invoke

    print("=" * 60)
    print("  WebSearchTool — Smoke Tests (mock client)")
    print("=" * 60)

    def mock_client(query: str, max_results: int) -> List[Dict[str, str]]:
        return [
            {"url": f"https://example.com/{i}", "title": f"Result {i} for {query}",
             "snippet": f"Snippet body {i}."}
            for i in range(max_results)
        ]

    def failing_client(query: str, max_results: int) -> List[Dict[str, str]]:
        raise RuntimeError("simulated network failure")

    async def run() -> None:
        tool = WebSearchTool(client=mock_client)

        # 1. Success
        r1 = await safe_invoke(tool, {"query": "JARVIS architecture", "max_results": 3})
        assert r1.is_success and r1.output["count"] == 3, f"got {r1}"
        assert all(set(h.keys()) == {"url", "title", "snippet"} for h in r1.output["results"])
        print(f"  [OK] returns 3 results in {{url,title,snippet}} shape")

        # 2. Max results boundary
        r2 = await safe_invoke(tool, {"query": "x", "max_results": 20})
        assert r2.output["count"] == 20
        print(f"  [OK] max_results=20 respected")

        # 3. Validation rejects out-of-range
        r3 = await safe_invoke(tool, {"query": "x", "max_results": 999})
        assert r3.is_error, f"got {r3}"
        print(f"  [OK] max_results=999 rejected by Pydantic")

        # 4. Missing query rejected
        r4 = await safe_invoke(tool, {"max_results": 5})
        assert r4.is_error
        print(f"  [OK] missing query rejected")

        # 5. Backend failure surfaces as ToolResult error (never raises)
        failing_tool = WebSearchTool(client=failing_client)
        r5 = await safe_invoke(failing_tool, {"query": "x", "max_results": 5})
        assert r5.is_error and "simulated network failure" in r5.error
        print(f"  [OK] backend exceptions become ToolResult errors")

        # 6. Concurrency-safe + no permission
        assert tool.is_concurrency_safe is True
        assert WebSearchTool.requires_permission is False
        print(f"  [OK] is_concurrency_safe=True, requires_permission=False")

        # 7. Registered
        assert Tool.get_or_raise("web_search") is WebSearchTool
        print(f"  [OK] registered as 'web_search'")

        # 8. Schema generation
        schema = WebSearchTool.schema_for_llm()
        assert schema["input_schema"]["properties"]["max_results"]["maximum"] == 20
        print(f"  [OK] schema includes max_results constraint")

        print("=" * 60)
        print("  All 8 smoke tests passed.")
        print("=" * 60)

    asyncio.run(run())
