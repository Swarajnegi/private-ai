"""
fs_dir.py

JARVIS Agent Layer: Filesystem Directory Listing tool (Category A — Callable).

Import-time registration:
    @Tool.register("list_dir")

LAYER: Agent (Tools)

Returns EVERY entry within max_depth. A listing is never silently cut: a
caller that wants it in pieces passes max_entries (a page size) and offset,
and every page reports total_entries and next_offset.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import Field

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from jarvis_core.config import JARVIS_ROOT
from jarvis_core.agent.tool import Tool, ToolInput, ToolResult


_EXCLUDE_DIR_NAMES = frozenset({
    ".git", "__pycache__", ".venv", "venv", "node_modules",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "chromadb",
    ".cache", "dist", "build", ".idea", ".vscode",
})


class ListDirInput(ToolInput):
    path: str = Field(
        default=".",
        description="Relative directory path to list (e.g. '.' for repo root, 'js-development', 'jarvis_data'). "
                    "Must be inside the repo root.",
        json_schema_extra={"aliases": ["dir_path", "directory", "folder"]}
    )
    max_depth: int = Field(
        default=2, ge=1, le=4,
        description="Maximum depth of subdirectories to inspect (default 2, max 4)."
    )
    max_entries: Optional[int] = Field(
        default=None, ge=1,
        description=("Optional page size. Default = return ALL entries. With a page "
                     "size, pass back next_offset as offset to get the next page.")
    )
    offset: int = Field(
        default=0, ge=0,
        description="Index of the first entry to return (for paging; default 0)."
    )


@Tool.register("list_dir")
class ListDirTool(Tool):
    """List directory contents and explore package/module hierarchy. Read-only."""

    name = "list_dir"
    description = (
        "List files and subdirectories within a repository folder up to max_depth. "
        "Returns directory structure, file counts, and byte sizes. Use this to discover "
        "codebase packages, inspect physical project layouts, and find modules without "
        "guessing filenames. Read-only and repo-scoped."
    )
    input_schema = ListDirInput

    @property
    def is_concurrency_safe(self) -> bool:
        return True

    def _resolve_safe(self, rel: str) -> Path:
        base = Path(JARVIS_ROOT).resolve()
        candidate = (base / rel).resolve()
        try:
            candidate.relative_to(base)
        except ValueError:
            raise PermissionError(f"path {rel!r} escapes repo root {base}")
        return candidate

    async def invoke(self, tool_input: ListDirInput) -> ToolResult:
        try:
            target_dir = self._resolve_safe(tool_input.path or ".")
        except PermissionError as e:
            return ToolResult(error=str(e))
        except Exception as e:
            return ToolResult(error=f"Invalid path: {e}")

        if not target_dir.exists():
            return ToolResult(error=f"Directory does not exist: {tool_input.path}")
        if not target_dir.is_dir():
            return ToolResult(error=f"Path is a file, not a directory: {tool_input.path}. Use file_read instead.")

        base = Path(JARVIS_ROOT).resolve()
        entries: List[Dict[str, Any]] = []
        dirs_found = 0
        files_found = 0

        def walk(current: Path, current_depth: int) -> None:
            nonlocal dirs_found, files_found
            if current_depth > tool_input.max_depth:
                return

            try:
                children = sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            except (PermissionError, OSError):
                return

            for child in children:
                if child.name in _EXCLUDE_DIR_NAMES or child.name.startswith("."):
                    continue

                rel_child = str(child.relative_to(base)).replace("\\", "/")
                if child.is_dir():
                    dirs_found += 1
                    sub_count = 0
                    try:
                        sub_count = sum(1 for sub in child.iterdir() if sub.name not in _EXCLUDE_DIR_NAMES)
                    except OSError:
                        pass
                    entries.append({
                        "path": rel_child,
                        "type": "dir",
                        "children": sub_count,
                        "depth": current_depth,
                    })
                    if current_depth < tool_input.max_depth:
                        walk(child, current_depth + 1)
                else:
                    files_found += 1
                    try:
                        sz = child.stat().st_size
                    except OSError:
                        sz = 0
                    entries.append({
                        "path": rel_child,
                        "type": "file",
                        "size_bytes": sz,
                        "depth": current_depth,
                    })

        walk(target_dir, 1)

        rel_target = str(target_dir.relative_to(base)).replace("\\", "/") or "."
        total = len(entries)
        start = min(tool_input.offset, total)
        end = total if tool_input.max_entries is None else min(total, start + tool_input.max_entries)
        return ToolResult(output={
            "root": rel_target,
            "total_entries": total,
            "total_listed": end - start,
            "dirs_count": dirs_found,
            "files_count": files_found,
            "offset": start,
            "next_offset": None if end >= total else end,
            "complete": end >= total,
            "entries": entries[start:end],
        })


# =============================================================================
# SMOKE TESTS (temp tree under a patched JARVIS_ROOT)
# =============================================================================

if __name__ == "__main__":
    import asyncio
    import tempfile

    from jarvis_core.agent.tool import safe_invoke

    print("=" * 60)
    print("  ListDirTool -- Smoke Tests")
    print("=" * 60)
    passed = 0
    failed: List[str] = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        global passed
        if cond:
            passed += 1
        else:
            failed.append(f"FAIL: {name}" + (f" ({hint})" if hint else ""))

    async def run() -> None:
        global JARVIS_ROOT
        with tempfile.TemporaryDirectory() as td:
            for i in range(250):
                (Path(td) / f"file_{i:03d}.txt").write_text("x", encoding="utf-8")
            JARVIS_ROOT = Path(td)
            tool = ListDirTool()
            r1 = await safe_invoke(tool, {"path": "."})
            check("T1 all 250 entries returned (old default cut at 80, cap 200)",
                  r1.is_success and r1.output["total_entries"] == 250
                  and len(r1.output["entries"]) == 250 and r1.output["complete"],
                  str(r1.error or r1.output["total_listed"]))
            seen: List[str] = []
            off: Optional[int] = 0
            pages = 0
            while off is not None and pages < 50:
                rp = await safe_invoke(tool, {"path": ".", "max_entries": 60, "offset": off})
                seen += [e["path"] for e in rp.output["entries"]]
                off = rp.output["next_offset"]
                pages += 1
            check("T2 paging returns every entry exactly once",
                  pages == 5 and len(seen) == 250 and len(set(seen)) == 250,
                  f"pages={pages} seen={len(seen)}")
            r3 = await safe_invoke(tool, {"path": "../.."})
            check("T3 escaping the root is refused", r3.is_error)

    asyncio.run(run())
    total_checks = passed + len(failed)
    print(f"\n  Passed: {passed}/{total_checks}")
    if failed:
        for f_ in failed:
            print(f"  {f_}")
        raise SystemExit(1)
    print(f"  All {total_checks} ListDirTool smoke tests passed.")
    print("=" * 60)
