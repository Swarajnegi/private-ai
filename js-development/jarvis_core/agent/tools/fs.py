"""
fs.py

JARVIS Agent Layer: Filesystem read tool (Category A — Callable).

Import-time registration:
    @Tool.register("file_read")

LAYER: Agent (Tools)

=============================================================================
THE BIG PICTURE
=============================================================================

Without file_read:
    -> Agent can't inspect local files. Every file-question requires the user
       to paste the content. Costly for large codebases.

With file_read:
    -> Agent emits {"tool": "file_read", "input": {"path": "...", ...}}.
    -> Returns {"content", "path", "bytes_read"}.
    -> Concurrency-safe (read-only). requires_permission=False at Stage 3.2
       (path-traversal/sensitive-path gating happens at STEAL #9 permission
       engine in 3.4 — that's where the AT-engine knows whether path 'foo'
       is under user-allowed directories).

WHY NO FILE_WRITE here:
    File writes are inherently dangerous (data loss, escalation). They land
    under STEAL #9 in Stage 3.4 with mandatory permission gating, not as a
    Phase B callable. Agent uses Edit/Write tools via the host runtime
    (Claude Code / future JARVIS shell), not via this layer.

=============================================================================
THE FLOW
=============================================================================

STEP 1: Agent emits {"tool":"file_read","input":{"path": "...", "max_bytes": 1_000_000}}.
        |
        v
STEP 2: Pydantic validates path is a string + max_bytes in [1, 10_000_000].
        |
        v
STEP 3: Open file in binary mode, read up to max_bytes, decode with `encoding`.
        |
        v
STEP 4: Return ToolResult(output={"content": str, "path": str, "bytes_read": int}).

=============================================================================
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from jarvis_core.agent.tool import Tool, ToolInput, ToolResult


# =============================================================================
# Part 1: INPUT SCHEMA
# =============================================================================

class FileReadInput(ToolInput):
    path: str = Field(
        description="Exact path to an EXISTING file (absolute, or relative to the "
                    "repo root). If you do not already know the exact path, call "
                    "file_search FIRST to find it — never guess a filename.",
        json_schema_extra={"aliases": [
            "file_path", "filepath", "file_name", "filename", "file", "fname"]})
    encoding: str = Field(default="utf-8", description="Text encoding (default utf-8).")
    max_bytes: int = Field(
        default=1_000_000, ge=1, le=10_000_000,
        description="Max bytes to read (default 1MB; cap 10MB). Larger files are truncated.",
    )


# =============================================================================
# Part 2: TOOL
# =============================================================================

@Tool.register("file_read")
class FileReadTool(Tool):
    """Read a local file (capped at max_bytes). Read-only."""

    name = "file_read"
    description = (
        "Read a local file from disk. Returns content as a decoded string "
        "plus the resolved absolute path and bytes actually read. Capped at "
        "max_bytes (default 1MB); larger files are truncated cleanly. "
        "Read-only — does not modify files. Requires an EXACT path to a file "
        "that exists; if you don't know it, call file_search FIRST to locate it "
        "(by filename or content) — do not guess filenames."
    )
    input_schema = FileReadInput

    @property
    def is_concurrency_safe(self) -> bool:
        return True  # Pure read; no shared state mutation

    async def invoke(self, tool_input: FileReadInput) -> ToolResult:
        path = Path(tool_input.path).expanduser()
        try:
            resolved = path.resolve(strict=True)
        except FileNotFoundError:
            return ToolResult(
                error=f"File not found: {tool_input.path}. Use file_search to "
                      f"locate the file (by name or content), then read the exact "
                      f"path it returns — do not guess another filename.")
        except OSError as e:
            return ToolResult(error=f"OS error resolving path: {e}")

        if not resolved.is_file():
            return ToolResult(error=f"Path is not a regular file: {resolved}")

        try:
            with resolved.open("rb") as f:
                raw = f.read(tool_input.max_bytes)
        except PermissionError as e:
            return ToolResult(error=f"Permission denied: {e}")
        except OSError as e:
            return ToolResult(error=f"OS error reading file: {e}")

        try:
            content = raw.decode(tool_input.encoding)
        except UnicodeDecodeError as e:
            return ToolResult(
                error=f"Decode failed at byte {e.start} with encoding "
                      f"'{tool_input.encoding}': {e.reason}"
            )

        truncated = len(raw) == tool_input.max_bytes
        return ToolResult(output={
            "content": content,
            "path": str(resolved),
            "bytes_read": len(raw),
            "truncated": truncated,
        })


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS  (tempfile-based, no fixtures needed)
# =============================================================================

if __name__ == "__main__":
    import asyncio
    import tempfile
    import os

    from jarvis_core.agent.tool import safe_invoke

    print("=" * 60)
    print("  FileReadTool — Smoke Tests")
    print("=" * 60)

    async def run() -> None:
        tool = FileReadTool()

        # 1. Read a normal file
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8", newline="") as f:
            f.write("Hello JARVIS\nLine 2\n")
            tmp_path = f.name
        try:
            r1 = await safe_invoke(tool, {"path": tmp_path})
            assert r1.is_success, f"got {r1}"
            assert r1.output["content"].startswith("Hello JARVIS")
            assert r1.output["bytes_read"] == len("Hello JARVIS\nLine 2\n")
            assert r1.output["truncated"] is False
            print(f"  [OK] reads normal file ({r1.output['bytes_read']} bytes)")

            # 2. Truncation
            big = "x" * 5000
            with open(tmp_path, "w") as f:
                f.write(big)
            r2 = await safe_invoke(tool, {"path": tmp_path, "max_bytes": 100})
            assert r2.is_success
            assert r2.output["bytes_read"] == 100
            assert r2.output["truncated"] is True
            print(f"  [OK] truncates at max_bytes (100 of 5000)")

            # 3. Non-existent file
            r3 = await safe_invoke(tool, {"path": "/no/such/file/exists.xyz"})
            assert r3.is_error and "not found" in r3.error.lower()
            print(f"  [OK] non-existent file -> error")

            # 4. Directory path
            r4 = await safe_invoke(tool, {"path": os.path.dirname(tmp_path)})
            assert r4.is_error and "not a regular file" in r4.error.lower()
            print(f"  [OK] directory path -> error")

            # 5. Encoding override
            with open(tmp_path, "wb") as f:
                f.write("café".encode("latin-1"))
            r5_bad = await safe_invoke(tool, {"path": tmp_path, "encoding": "utf-8"})
            r5_ok  = await safe_invoke(tool, {"path": tmp_path, "encoding": "latin-1"})
            assert r5_bad.is_error and "Decode failed" in r5_bad.error
            assert r5_ok.is_success and r5_ok.output["content"] == "café"
            print(f"  [OK] encoding override works; bad encoding surfaces clean error")

            # 6. Validation: max_bytes out of range
            r6 = await safe_invoke(tool, {"path": tmp_path, "max_bytes": 999_999_999})
            assert r6.is_error
            print(f"  [OK] out-of-range max_bytes rejected by Pydantic")

            # 7. Concurrency-safe + no permission
            assert tool.is_concurrency_safe is True
            assert FileReadTool.requires_permission is False
            print(f"  [OK] is_concurrency_safe=True, requires_permission=False")

            # 8. Registry + schema
            assert Tool.get_or_raise("file_read") is FileReadTool
            schema = FileReadTool.schema_for_llm()
            assert "path" in schema["input_schema"]["properties"]
            print(f"  [OK] registered + schema valid")

            # 9. Discover-before-read scaffold: the description, the path field,
            # AND the not-found error all steer to file_search (so a weak brain
            # searches instead of guessing a filename — repro 2026-06-18).
            assert "file_search" in FileReadTool.description.lower()
            assert "file_search" in schema["input_schema"]["properties"]["path"]["description"].lower()
            r9 = await safe_invoke(tool, {"path": "workflow_rules.txt"})
            assert r9.is_error and "file_search" in r9.error.lower()
            print(f"  [OK] discover-before-read scaffold present (desc/field/error -> file_search)")
        finally:
            os.unlink(tmp_path)

        print("=" * 60)
        print("  All 9 smoke tests passed.")
        print("=" * 60)

    asyncio.run(run())
