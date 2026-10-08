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
STEP 3: if content_regex, stream each text file line-by-line (any size),
        collecting {path, line_no, line} with the WHOLE line; else just list
        the matched paths.
        |
STEP 4: return EVERY match — or, when the caller passes max_results as a page
        size, one page plus total and next_offset. Never a silent cut.

=============================================================================
"""

from __future__ import annotations

import fnmatch
import os
import re
import sys
from pathlib import Path
from typing import Iterator, List, Optional

from pydantic import Field

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # standalone-run safety

from jarvis_core.agent.tool import Tool, ToolInput, ToolResult
from jarvis_core.config import JARVIS_ROOT

# Directories never worth searching (noise, binaries, vendored, regenerable).
_SKIP_DIRS = frozenset({
    ".git", "chromadb", "chromadb_backups", "__pycache__", ".venv", "venv",
    "node_modules", "ai_model_repos", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "extracted_images",
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
        json_schema_extra={"aliases": [
            "glob", "name_pattern", "filename_glob", "file_glob", "name"]},
    )
    content_regex: Optional[str] = Field(
        default=None,
        description="Regex to search WITHIN files. None = list filenames only.",
        json_schema_extra={"aliases": ["regex", "content_pattern", "grep", "content"]},
    )
    subdir: str = Field(
        default=".",
        description="Repo-relative directory to search under (default: whole repo). "
                    "Cannot escape the project root.",
        json_schema_extra={"aliases": ["dir", "directory", "subdirectory", "search_dir"]},
    )
    max_results: Optional[int] = Field(
        default=None, ge=1,
        description=("Optional page size. Default = return ALL matches. With a page "
                     "size, pass back next_offset as offset for the next page."),
    )
    offset: int = Field(
        default=0, ge=0,
        description="Index of the first match to return (for paging; default 0).",
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
        "to DISCOVER where code/docs live, then file_read to read a specific file in "
        "full. To LIST a directory's files, pass name_glob='*' (e.g. subdir='.agent/"
        "rules') with no content_regex."
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

        total = 0
        page: List[dict] = []
        stop = None if tool_input.max_results is None else tool_input.offset + tool_input.max_results
        for m in self._iter_matches(root, root_base, tool_input.name_glob, pattern):
            if total >= tool_input.offset and (stop is None or total < stop):
                page.append(m)
            total += 1

        end = tool_input.offset + len(page)
        return ToolResult(output={
            "matches": page,
            "count": len(page),
            "total_matches": total,
            "offset": tool_input.offset,
            "next_offset": None if end >= total else end,
            "complete": end >= total,
            "root": str(root.relative_to(root_base)) or ".",
        })

    @staticmethod
    def _iter_matches(
        root: Path, root_base: Path, name_glob: Optional[str],
        pattern: Optional["re.Pattern[str]"],
    ) -> Iterator[dict]:
        """Every match, in a stable order (sorted walk) so offsets page reliably."""
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
            for fname in sorted(filenames):
                if name_glob and not fnmatch.fnmatch(fname, name_glob):
                    continue
                fpath = Path(dirpath) / fname
                rel = str(fpath.relative_to(root_base))
                if pattern is None:
                    yield {"path": rel}
                    continue
                if fpath.suffix.lower() in _BINARY_EXT:
                    continue
                try:
                    with fpath.open("r", encoding="utf-8", errors="ignore") as fh:
                        for line_no, line in enumerate(fh, 1):
                            if pattern.search(line):
                                yield {"path": rel, "line_no": line_no,
                                       "line": line.rstrip("\n")}
                except (OSError, ValueError):
                    continue


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

        # T6: NO CUT — by default every match is returned; with a page size,
        # paging by next_offset returns every match exactly once.
        r6 = await safe_invoke(tool, {"name_glob": "*.py", "subdir": "js-development"})
        all_py = [m["path"] for m in r6.output["matches"]] if r6.is_success else []
        check("T6a default returns ALL matches (old default cut at 50)",
              r6.is_success and r6.output["complete"] and len(all_py) > 50
              and r6.output["total_matches"] == len(all_py), str(len(all_py)))
        paged: List[str] = []
        off: Optional[int] = 0
        while off is not None:
            rp = await safe_invoke(tool, {"name_glob": "*.py", "subdir": "js-development",
                                          "max_results": 17, "offset": off})
            paged += [m["path"] for m in rp.output["matches"]]
            off = rp.output["next_offset"]
        check("T6b paging covers every match exactly once, in order",
              paged == all_py, f"{len(paged)} vs {len(all_py)}")

        # T6c: a matching line is returned WHOLE (old cut: 300 chars).
        import tempfile as _tf
        with _tf.TemporaryDirectory(dir=str(Path(JARVIS_ROOT))) as td:
            long_line = "NEEDLE-" + "L" * 5_000 + "-END"
            (Path(td) / "long.txt").write_text(long_line + "\n", encoding="utf-8")
            sub = str(Path(td).relative_to(Path(JARVIS_ROOT).resolve()))
            rl = await safe_invoke(tool, {"subdir": sub, "content_regex": "NEEDLE"})
            check("T6c a 5,000-char matching line is returned whole",
                  rl.is_success and rl.output["matches"]
                  and rl.output["matches"][0]["line"] == long_line,
                  str(rl.error or len(rl.output["matches"][0]["line"])))

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
