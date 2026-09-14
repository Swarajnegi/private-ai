"""
fs_dir.py

JARVIS Agent Layer: Filesystem Directory Listing tool (Category A — Callable).

Import-time registration:
    @Tool.register("list_dir")

LAYER: Agent (Tools)
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

_MAX_ENTRIES_DEFAULT = 80


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
    max_entries: int = Field(
        default=_MAX_ENTRIES_DEFAULT, ge=1, le=200,
        description="Maximum number of items to return (default 80, cap 200)."
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
        truncated = False

        def walk(current: Path, current_depth: int) -> None:
            nonlocal dirs_found, files_found, truncated
            if current_depth > tool_input.max_depth or len(entries) >= tool_input.max_entries:
                if len(entries) >= tool_input.max_entries:
                    truncated = True
                return

            try:
                children = sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            except (PermissionError, OSError):
                return

            for child in children:
                if len(entries) >= tool_input.max_entries:
                    truncated = True
                    return
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
        return ToolResult(output={
            "root": rel_target,
            "total_listed": len(entries),
            "dirs_count": dirs_found,
            "files_count": files_found,
            "truncated": truncated,
            "entries": entries,
        })
