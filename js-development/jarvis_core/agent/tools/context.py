"""
context.py — the page-in tool: recover evicted context on demand.

LAYER: Tools (Memory — model-driven page-in)

=============================================================================
THE BIG PICTURE
=============================================================================

The Context Ledger archives every span before compaction evicts it, and the
boundary message left behind carries the handle. This tool is the other half:
it lets the MODEL decide to page a span back in.

Without it the ledger is only an audit trail — history is recoverable in
principle but not by the thing that needs it mid-reasoning. With it the loop
closes, and eviction becomes genuinely reversible:

    compaction  -> archive verbatim -> boundary carries ctx:<handle>
    model reads boundary, needs the detail -> context_expand(ctx:<handle>)
    -> originals return, byte-identical

This is what separates "we summarised your history" from "your history is one
bounded hop away". It is also the honest answer to the infinite-context ask:
attention stays bounded, addressable history does not.

READ-ONLY BY CONSTRUCTION. It reads one append-only file keyed by a
content-addressed handle and can neither write nor delete. That is why it is
safe to declare read-only in permgate's allowlist.

=============================================================================
THE FLOW
=============================================================================

STEP 1: The model sees "[compacted 12 earlier messages — originals recoverable
        via context_expand(ctx:abc123...)]" in its own transcript.
        |
STEP 2: It calls context_expand with that handle.
        |
STEP 3: The ledger verifies the span still hashes to its handle and returns
        the original messages verbatim, one page at a time: each page carries
        total_chars and next_offset, so the model reads the whole span however
        large it is. A corrupt or missing span returns an error rather than
        plausible-looking wrong history.
=============================================================================
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # standalone-run safety

from jarvis_core.agent.tool import Tool, ToolResult

# A span can be larger than the window it was evicted to relieve, so it is read
# in PAGES rather than returned whole: every page states the span's total size
# and the offset of the next page, so any span can be read completely across
# calls. A page is a unit of reading, never a cut — nothing is withheld that a
# following call cannot return.
DEFAULT_PAGE_CHARS = 12_000
# Upper bound on a page the MODEL may ask for. Without it a single page request
# could re-overflow the window; with it the rest simply arrives on the next page.
DEFAULT_MAX_PAGE_CHARS = 48_000
_MIN_PAGE_CHARS = 1_000


def render_span(span: List[Dict[str, Any]]) -> str:
    """The one text form of a span that page offsets index into."""
    return "\n".join(f"[{m.get('role', '?')}] {m.get('content', '')}" for m in span)


class ContextExpandInput(BaseModel):
    handle: str = Field(
        ...,
        description=("The ledger handle to expand, as shown in a compaction "
                     "boundary or a paged-observation notice, e.g. "
                     "'ctx:a1b2c3d4e5f6a7b8'. The 'ctx:' prefix is optional."),
    )
    offset: int = Field(
        0,
        ge=0,
        description=("Character offset to start reading at. Start at 0; each "
                     "page returns next_offset — pass it back to read the next "
                     "page. Repeat until complete is true."),
    )
    page_chars: Optional[int] = Field(
        None,
        description="Characters per page (optional; the tool has a default).",
    )


class ContextExpandTool(Tool):
    """Recover, page by page, the original content a ledger handle points at."""

    name = "context_expand"
    description = (
        "Read the ORIGINAL, verbatim content behind a ledger handle (ctx:...). "
        "Handles appear in compaction boundaries ('[compacted N earlier messages "
        "— originals recoverable via context_expand(ctx:...)]') and in notices "
        "for tool observations too large to include inline. Content is returned "
        "in pages: call with offset=0, then pass back next_offset until complete "
        "is true. Returns the exact earlier content, not a paraphrase. Read-only."
    )
    input_schema = ContextExpandInput

    def __init__(
        self,
        ledger: Optional[Any] = None,
        page_chars: int = DEFAULT_PAGE_CHARS,
        max_page_chars: int = DEFAULT_MAX_PAGE_CHARS,
    ) -> None:
        self._ledger = ledger
        self._max_page = max(_MIN_PAGE_CHARS, int(max_page_chars))
        self._page = min(self._max_page, max(_MIN_PAGE_CHARS, int(page_chars)))

    def fit_pages(self, max_page_chars: int) -> None:
        """Bound pages to what the caller's window can take in one observation.

        The ReAct loop calls this with its paging threshold, so a page can never
        itself be too large to include — a smaller page means more pages, never
        less content.
        """
        self._max_page = max(_MIN_PAGE_CHARS, min(self._max_page, int(max_page_chars)))
        self._page = min(self._page, self._max_page)

    def is_concurrency_safe(self) -> bool:
        return True

    async def invoke(self, tool_input: ContextExpandInput) -> ToolResult:
        if self._ledger is None:
            return ToolResult(error=(
                "No context ledger is active for this session, so evicted "
                "context was not archived and cannot be recovered."))
        try:
            span = self._ledger.expand_span(tool_input.handle)
        except Exception as e:
            return ToolResult(error=f"Ledger read failed: {type(e).__name__}: {e}")

        if not span:
            return ToolResult(error=(
                f"Handle '{tool_input.handle}' not found in this session's "
                f"ledger, or its stored content failed its own checksum. No "
                f"partial or reconstructed history is returned."))

        text = render_span(span)
        total = len(text)
        page = self._page if tool_input.page_chars is None else min(
            self._max_page, max(_MIN_PAGE_CHARS, int(tool_input.page_chars)))
        offset = int(tool_input.offset or 0)
        if offset > total:
            return ToolResult(error=(
                f"offset {offset} is past the end of this span "
                f"({total} chars). Valid offsets are 0..{total}."))
        end = min(total, offset + page)
        complete = end >= total
        return ToolResult(output={
            "handle": tool_input.handle,
            "messages_in_span": len(span),
            "total_chars": total,
            "offset": offset,
            "returned_chars": end - offset,
            "next_offset": None if complete else end,
            "complete": complete,
            "note": ("End of span reached." if complete else
                     f"Page covers chars {offset}-{end} of {total}. Call "
                     f"context_expand again with offset={end} for the next page."),
            "transcript": text[offset:end],
        })


# =============================================================================
# SMOKE TESTS (offline — temp dirs only)
# =============================================================================

def _run_self_test() -> None:
    import asyncio
    import tempfile
    from jarvis_core.agent.context_ledger import ContextLedger

    print("=" * 70)
    print("  tools/context.py -- Smoke Tests")
    print("=" * 70)
    passed = 0
    failed: List[str] = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        nonlocal passed
        if cond:
            passed += 1
            print(f"  PASS  {name}")
        else:
            failed.append(name)
            print(f"  FAIL  {name}  {hint}")

    span = [
        {"role": "user", "content": "the retention threshold was what exactly?"},
        {"role": "assistant", "content": "720 hours — the framework overrode the 168 default."},
    ]

    async def go() -> None:
        nonlocal passed
        with tempfile.TemporaryDirectory() as td:
            led = ContextLedger("tool-test", root=Path(td))
            h = led.archive_span(span)
            tool = ContextExpandTool(ledger=led)

            r = await tool.invoke(ContextExpandInput(handle=h.handle))
            check("T1 expands a real handle", r.error is None, str(r.error))
            check("T2 returns the VERBATIM detail, not a paraphrase",
                  "720 hours" in r.output["transcript"], r.output["transcript"][:80])
            check("T3 small span arrives complete in one page",
                  r.output["messages_in_span"] == 2 and r.output["complete"] is True
                  and r.output["next_offset"] is None
                  and r.output["total_chars"] == len(r.output["transcript"]),
                  str(r.output))

            r2 = await tool.invoke(ContextExpandInput(handle=h.token))
            check("T4 accepts the ctx: prefixed form", r2.error is None)

            r3 = await tool.invoke(ContextExpandInput(handle="0" * 16))
            check("T5 unknown handle -> ERROR, never invented history",
                  r3.error is not None and "not found" in r3.error, str(r3.error))

            # T6 -- PAGING, not truncation: a span far larger than a page, with
            # one message larger than a page on its own, must be readable in
            # full by following next_offset, and reassemble byte-identical.
            from jarvis_core.agent.tools.context import render_span
            big = ([{"role": "user", "content": "HEAD-MARKER " + "a" * 30_000}]
                   + [{"role": "tool", "content": f"MSG-{i} " + "y" * 400}
                      for i in range(50)]
                   + [{"role": "assistant", "content": "z" * 5_000 + " TAIL-MARKER"}])
            hb = led.archive_span(big)
            pages: List[str] = []
            offset: Optional[int] = 0
            calls = 0
            first = None
            while offset is not None and calls < 100:
                rp = await tool.invoke(ContextExpandInput(handle=hb.token, offset=offset))
                if rp.error:
                    break
                first = first or rp.output
                pages.append(rp.output["transcript"])
                offset = rp.output["next_offset"]
                calls += 1
            whole = "".join(pages)
            check("T6 a large span is read COMPLETELY across pages",
                  whole == render_span(big) and offset is None,
                  f"got {len(whole)} of {len(render_span(big))} in {calls} calls")
            check("T6b every page reports total size and the next offset",
                  first is not None and first["total_chars"] == len(render_span(big))
                  and first["next_offset"] == DEFAULT_PAGE_CHARS
                  and first["complete"] is False and calls > 3,
                  str({k: v for k, v in (first or {}).items() if k != "transcript"}))
            check("T6c both ends of the span are reachable (head and tail)",
                  "HEAD-MARKER" in whole and whole.endswith("TAIL-MARKER"))
            r6 = await tool.invoke(ContextExpandInput(handle=hb.token, offset=10**9))
            check("T6d an offset past the end is an honest error",
                  r6.error is not None and "past the end" in r6.error, str(r6.error))
            r6e = await tool.invoke(ContextExpandInput(handle=hb.token, page_chars=10**9))
            check("T6e an oversized page request is bounded, and says where to resume",
                  r6e.output["returned_chars"] == DEFAULT_MAX_PAGE_CHARS
                  and r6e.output["next_offset"] == DEFAULT_MAX_PAGE_CHARS,
                  str(r6e.output["returned_chars"]))

            no_led = ContextExpandTool(ledger=None)
            r5 = await no_led.invoke(ContextExpandInput(handle=h.handle))
            check("T7 no ledger -> honest error about no archive",
                  r5.error is not None and "ledger" in r5.error.lower(), str(r5.error))

            check("T8 declared concurrency-safe (read-only)", tool.is_concurrency_safe())
            check("T9 does not require permission (read-only)",
                  not getattr(tool, "requires_permission", False))

    asyncio.run(go())

    print("-" * 70)
    print(f"  {passed} passed, {len(failed)} failed")
    if failed:
        for name in failed:
            print(f"    - {name}")
    print("=" * 70)
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    _run_self_test()
