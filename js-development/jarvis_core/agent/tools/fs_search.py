"""
fs_search.py

JARVIS Agent Layer: Filesystem search tool (Category A — Callable).

Import-time registration:
    @Tool.register("file_search")

LAYER: Agent (Tools)

=============================================================================
THE BIG PICTURE
=============================================================================

Without file_search:
    -> The agent can read a file IF it already knows the exact path (file_read),
       but it cannot DISCOVER what files exist or WHERE a symbol lives. "Can you
       see my codebase?" stays a no. The only discovery tool was shell_run
       (ls/grep/find) — dangerous and permission-gated.

With file_search:
    -> Agent emits {"tool":"file_search","input":{"name_glob":"*.py",
       "content_regex":"repair", "subdir":"js-development"}}.
    -> Returns matching file paths (by glob) and/or matching lines (by regex),
       relative to the repo root.
    -> Repo-scoped BY CONSTRUCTION: the search root is clamped to JARVIS_ROOT,
       so it can never traverse out to ~/.ssh or ~/.bashrc. That makes it SAFE
       to run ungated (requires_permission=False) — unlike file_read (arbitrary
       path) and shell_run (arbitrary command), this tool can only ever see the
       project tree. Read-only, no mutation.

=============================================================================
THE FLOW
=============================================================================

STEP 1: resolve root = (JARVIS_ROOT / subdir); reject if it escapes JARVIS_ROOT.
        |
STEP 2: walk the tree, skipping noise dirs (.git, chromadb, .venv, caches,
        vendored repos) and binary files; filter filenames by name_glob.
        |
STEP 3: if content_regex, scan each text file line-by-line (per-file byte cap),
        collecting {path, line_no, line}; else just list the matched paths.
        |
STEP 4: cap at max_results; return {matches, count, truncated, root}.

=============================================================================
"""

from __future__ import annotations

import fnmatch
import os
import re
import sys
from pathlib import Path
from typing import List, Optional

from pydantic import Field

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # standalone-run safety

from jarvis_core.agent.tool import Tool, ToolInput, ToolResult
from jarvis_core.config import JARVIS_ROOT

# Directories never worth searching (noise, binaries, vendored, regenerable).
_SKIP_DIRS = frozenset({
    ".git", "chromadb", "chromadb_backups", "__pycache__", ".venv", "venv",
    "node_modules", "ai_model_repos", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "extracted_images", "research_papers",
})
# Extensions we never scan for content (binary / huge).
_BINARY_EXT = frozenset({
    ".pyc", ".so", ".bin", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip",
    ".gz", ".tar", ".whl", ".sqlite", ".sqlite3", ".db", ".parquet", ".npy", ".faiss",
})


class FileSearchInput(ToolInput):
    name_glob: Optional[str] = Field(
        default=None,
        description="Filename glob to match, e.g. '*.py' or 'boot.py'. None = match all files.",
    )
    content_regex: Optional[str] = Field(
        default=None,
        description="Regex to search WITHIN files. None = list filenames only.",
    )
    subdir: str = Field(
        default=".",
        description="Repo-relative directory to search under (default: whole repo). "
                    "Cannot escape the project root.",
    )
    max_results: int = Field(
        default=50, ge=1, le=500,
        description="Max matches to return (filenames or matching lines).",
    )
    max_file_bytes: int = Field(
        default=1_000_000, ge=1, le=10_000_000,
        description="Skip content-scanning files larger than this (default 1MB).",
    )


@Tool.register("file_search")
class FileSearchTool(Tool):
    """Search the project tree by filename glob and/or content regex. Repo-scoped, read-only."""

    name = "file_search"
    description = (
        "Search the project codebase. Give a filename glob (name_glob, e.g. '*.py') "
        "to find files, and/or a content_regex to find matching lines inside files. "
        "Scoped to the project root (cannot read outside it). Returns relative paths "
        "and, for content matches, the line number + line text. Read-only. Use this "
        "to DISCOVER where code lives, then file_read to read a specific file in full."
    )
    input_schema = FileSearchInput

    @property
    def is_concurrency_safe(self) -> bool:
        return True  # pure read

    async def invoke(self, tool_input: FileSearchInput) -> ToolResult:
        root_base = Path(JARVIS_ROOT).resolve()
        try:
            root = (root_base / tool_input.subdir).resolve()
        except (OSError, RuntimeError, ValueError) as e:
            return ToolResult(error=f"bad subdir: {e}")
        if root != root_base and root_base not in root.parents:
            return ToolResult(error=f"subdir escapes the project root: {tool_input.subdir}")
        if not root.exists():
            return ToolResult(error=f"subdir not found: {tool_input.subdir}")

        try:
            pattern = re.compile(tool_input.content_regex) if tool_input.content_regex else None
        except re.error as e:
            return ToolResult(error=f"invalid content_regex: {e}")

        matches: List[dict] = []
        truncated = False
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for fname in filenames:
                if tool_input.name_glob and not fnmatch.fnmatch(fname, tool_input.name_glob):
                    continue
                fpath = Path(dirpath) / fname
                rel = str(fpath.relative_to(root_base))
                if pattern is None:
                    matches.append({"path": rel})
                    if len(matches) >= tool_input.max_results:
                        truncated = True
                        break
                    continue
                # content scan
                if fpath.suffix.lower() in _BINARY_EXT:
                    continue
                try:
                    if fpath.stat().st_size > tool_input.max_file_bytes:
                        continue
                    with fpath.open("r", encoding="utf-8", errors="ignore") as fh:
                        for line_no, line in enumerate(fh, 1):
                            if pattern.search(line):
                                matches.append({
                                    "path": rel, "line_no": line_no,
                                    "line": line.rstrip("\n")[:300],
                                })
                                if len(matches) >= tool_input.max_results:
                                    truncated = True
                                    break
                except (OSError, ValueError):
                    continue
                if truncated:
                    break
            if truncated:
                break

        return ToolResult(output={
            "matches": matches,
            "count": len(matches),
            "truncated": truncated,
            "root": str(root.relative_to(root_base)) or ".",
        })


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS
# =============================================================================

if __name__ == "__main__":
    import asyncio
    from jarvis_core.agent.tool import safe_invoke

    print("=" * 60)
    print("  FileSearchTool — Smoke Tests")
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
        tool = FileSearchTool()

        # T1: name_glob finds this very file under the repo
        r1 = await safe_invoke(tool, {"name_glob": "fs_search.py"})
        check("T1 name_glob finds fs_search.py",
              r1.is_success and any(m["path"].endswith("fs_search.py")
                                    for m in r1.output["matches"]), str(r1.output if r1.is_success else r1.error)[:120])

        # T2: content_regex finds a known line in this file
        r2 = await safe_invoke(tool, {"name_glob": "fs_search.py",
                                      "content_regex": "Repo-scoped BY CONSTRUCTION"})
        check("T2 content_regex finds a matching line",
              r2.is_success and r2.output["count"] >= 1
              and "line_no" in r2.output["matches"][0])

        # T3: scoped to a subdir
        r3 = await safe_invoke(tool, {"name_glob": "boot.py", "subdir": "js-development"})
        check("T3 subdir scoping works",
              r3.is_success and any("boot.py" in m["path"] for m in r3.output["matches"]))

        # T4: out-of-repo subdir rejected (no traversal to secrets)
        r4 = await safe_invoke(tool, {"subdir": "../../../../etc"})
        check("T4 escaping subdir rejected", r4.is_error and "escapes" in r4.error.lower(), str(r4.error))

        # T5: noise dirs skipped (no chromadb / .git paths)
        r5 = await safe_invoke(tool, {"name_glob": "*", "max_results": 500})
        check("T5 noise dirs skipped",
              r5.is_success and not any("/.git/" in m["path"] or "chromadb" in m["path"]
                                        for m in r5.output["matches"]))

        # T6: max_results cap + truncation flag
        r6 = await safe_invoke(tool, {"name_glob": "*.py", "max_results": 3})
        check("T6 max_results cap", r6.is_success and r6.output["count"] == 3
              and r6.output["truncated"] is True)

        # T7: invalid regex -> clean error
        r7 = await safe_invoke(tool, {"content_regex": "([unclosed"})
        check("T7 invalid regex -> error", r7.is_error and "regex" in r7.error.lower())

        # T8: flags
        check("T8 concurrency-safe + no permission",
              tool.is_concurrency_safe is True and FileSearchTool.requires_permission is False)
        check("T8b registered + schema", Tool.get_or_raise("file_search") is FileSearchTool
              and "name_glob" in FileSearchTool.schema_for_llm()["input_schema"]["properties"])

    asyncio.run(run())

    total = passed + len(failed)
    print(f"\n  Passed: {passed}/{total}")
    if failed:
        for f_ in failed:
            print(f"  {f_}")
        print("=" * 60)
        raise SystemExit(1)
    print(f"  All {total} FileSearchTool smoke tests passed.")
    print("=" * 60)
