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
        the original messages verbatim; a corrupt or missing span returns an
        error rather than plausible-looking wrong history.
=============================================================================
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, List, Optional

from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # standalone-run safety

from jarvis_core.agent.tool import Tool, ToolResult

# A span can be large — it is by definition the part of the transcript that did
# not fit. Returning it whole could re-overflow the window we just relieved, so
# the tool caps what it hands back and says how much it withheld.
_DEFAULT_MAX_CHARS = 12_000


class ContextExpandInput(BaseModel):
    handle: str = Field(
        ...,
        description=("The ledger handle to expand, as shown in a compaction "
                     "boundary message, e.g. 'ctx:a1b2c3d4e5f6a7b8'. The "
                     "'ctx:' prefix is optional."),
    )
    max_chars: int = Field(
        _DEFAULT_MAX_CHARS,
        description="Cap on returned characters. Truncation is reported, never silent.",
    )


class ContextExpandTool(Tool):
    """Recover the original messages a compaction boundary replaced."""

    name = "context_expand"
    description = (
        "Recover the ORIGINAL, verbatim messages that a compaction boundary "
        "replaced. When the transcript shows a line like '[compacted N earlier "
        "messages — originals recoverable via context_expand(ctx:...)]' and you "
        "need a detail the summary omitted, call this with that handle. Returns "
        "the exact earlier messages, not a paraphrase. Read-only."
    )
    input_schema = ContextExpandInput

    def __init__(self, ledger: Optional[Any] = None) -> None:
        self._ledger = ledger

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

        cap = max(500, int(tool_input.max_chars or _DEFAULT_MAX_CHARS))
        rendered: List[str] = []
        used = 0
        included = 0
        for m in span:
            line = f"[{m.get('role', '?')}] {m.get('content', '')}"
            if used + len(line) > cap:
                break
            rendered.append(line)
            used += len(line)
            included += 1

        withheld = len(span) - included
        return ToolResult(output={
            "handle": tool_input.handle,
            "messages_in_span": len(span),
            "messages_returned": included,
            "messages_withheld": withheld,
            "truncated": withheld > 0,
            "note": (f"{withheld} further message(s) withheld by the {cap}-char cap; "
                     f"raise max_chars to see more." if withheld else
                     "Full span returned verbatim."),
            "transcript": "\n".join(rendered),
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
            check("T3 reports the full span size",
                  r.output["messages_in_span"] == 2 and not r.output["truncated"],
                  str(r.output))

            r2 = await tool.invoke(ContextExpandInput(handle=h.token))
            check("T4 accepts the ctx: prefixed form", r2.error is None)

            r3 = await tool.invoke(ContextExpandInput(handle="0" * 16))
            check("T5 unknown handle -> ERROR, never invented history",
                  r3.error is not None and "not found" in r3.error, str(r3.error))

            # T6 -- truncation must be REPORTED. A silently clipped span would
            # let the model believe it had seen everything. Needs a span that
            # genuinely exceeds the 500-char floor on max_chars, hence the
            # padding: the earlier 110-char fixture could never truncate.
            big = [{"role": "user", "content": f"MSG-{i} " + "y" * 400}
                   for i in range(5)]
            hb = led.archive_span(big)
            r4 = await tool.invoke(ContextExpandInput(handle=hb.handle, max_chars=500))
            check("T6 truncation is reported, not silent",
                  r4.output["truncated"] is True and r4.output["messages_withheld"] >= 1,
                  str(r4.output.get("note")))
            check("T6b truncated response still returns what it could",
                  r4.output["messages_returned"] >= 1
                  and "MSG-0" in r4.output["transcript"],
                  str(r4.output["messages_returned"]))

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
