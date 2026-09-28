"""
_read_notice.py — shared by the SessionStart read-in-full notices.

LAYER: Tools (Memory Contract — Claude Code boot reads)

Not a hook. The Claude Code harness replaces SessionStart output over ~10 KB
with a 2 KB preview, so a file the agent must know whole is never pasted into
the hook output: the hook points at it and names the exact Read pages that
cover it end to end. A pointer plus a full read is not a cut; a pasted file
that the harness trims is.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List, Tuple

# Well under the Read tool's per-call ceiling, so no page is refused for size.
PAGE_BYTES = 40_000


def pages(path: Path, page_bytes: int = PAGE_BYTES) -> List[Tuple[int, int]]:
    """(offset, limit) Read-tool pages, 1-based lines, covering every line once."""
    out: List[Tuple[int, int]] = []
    start, count, size = 1, 0, 0
    with path.open("rb") as fh:
        for line in fh:
            if count and size + len(line) > page_bytes:
                out.append((start, count))
                start, count, size = start + count, 0, 0
            count += 1
            size += len(line)
    if count:
        out.append((start, count))
    return out


def render_pages(path: Path) -> str:
    return "; ".join(f"offset={o} limit={n}" for o, n in pages(path))


def emit(context: str) -> None:
    """ASCII-escaped JSON: a Windows pipe is cp1252, and one non-cp1252 character
    in a raw write raised, was swallowed, and the hook emitted nothing at all."""
    sys.stdout.write(json.dumps({"hookSpecificOutput": {
        "hookEventName": "SessionStart", "additionalContext": context}}))


def _self_test() -> int:
    import tempfile
    failed: List[str] = []
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "f.md"
        p.write_text("".join(f"line {i} " + "x" * 90 + "\n" for i in range(1, 1001)), encoding="utf-8")
        got = pages(p, page_bytes=10_000)
        covered = [n for o, n in got]
        if sum(covered) != 1000 or got[0][0] != 1:
            failed.append(f"pages do not cover every line once: {got}")
        if any(b[0] != a[0] + a[1] for a, b in zip(got, got[1:])):
            failed.append(f"pages are not contiguous: {got}")
        big = Path(td) / "g.md"
        big.write_text("y" * 50_000 + "\nshort\n", encoding="utf-8")
        if pages(big, page_bytes=10_000) != [(1, 1), (2, 1)]:
            failed.append("a single line longer than a page must still get its own page")
    print("  PASS read-notice pages" if not failed else "\n".join("  FAIL " + f for f in failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
