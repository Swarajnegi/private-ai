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
    -> Returns {"content", "path", "bytes_read", "size_bytes", "next_offset",
       "complete"} — the WHOLE file by default. Nothing is cut: a caller that
       wants a range asks for one (offset + max_bytes) and is told where the
       next range starts. Keeping a huge read inside the context window is the
       ReAct loop's job, and it does it by paging, never by clipping.
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

STEP 1: Agent emits {"tool":"file_read","input":{"path": "..."}} (optionally
        "offset" and "max_bytes" to read one range).
        |
        v
STEP 2: Open file in binary mode, seek to offset, read to EOF (or max_bytes),
        decode with `encoding`. A range that ends inside a multi-byte
        character ends before it, and next_offset points at it.
        |
        v
STEP 3: Return ToolResult(output={"content", "path", "bytes_read",
        "size_bytes", "offset", "next_offset", "complete"}).

=============================================================================
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

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
    offset: int = Field(
        default=0, ge=0,
        description="Byte offset to start reading at (default 0 = start of file).",
    )
    max_bytes: Optional[int] = Field(
        default=None, ge=1,
        description=("Optional: read only this many bytes from offset. Default = "
                     "the whole rest of the file. A partial read returns "
                     "next_offset so the rest can be read with another call."),
    )


# =============================================================================
# Part 2: TOOL
# =============================================================================

@Tool.register("file_read")
class FileReadTool(Tool):
    """Read a local file, whole or by explicit byte range. Read-only."""

    name = "file_read"
    description = (
        "Read a local file from disk. Returns the WHOLE file as a decoded string "
        "plus the resolved absolute path, size_bytes and bytes_read. Optional "
        "offset/max_bytes read one byte range and return next_offset for the rest. "
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
            size = resolved.stat().st_size
            with resolved.open("rb") as f:
                f.seek(tool_input.offset)
                raw = f.read() if tool_input.max_bytes is None else f.read(tool_input.max_bytes)
        except PermissionError as e:
            return ToolResult(error=f"Permission denied: {e}")
        except OSError as e:
            return ToolResult(error=f"OS error reading file: {e}")

        end = tool_input.offset + len(raw)
        try:
            content = raw.decode(tool_input.encoding)
        except UnicodeDecodeError as e:
            # A requested range can end inside a multi-byte character. End the
            # range before it; next_offset then starts the next read ON it.
            if end < size and e.reason == "unexpected end of data":
                raw = raw[:e.start]
                end = tool_input.offset + len(raw)
                content = raw.decode(tool_input.encoding)
            else:
                return ToolResult(
                    error=f"Decode failed at byte {tool_input.offset + e.start} with "
                          f"encoding '{tool_input.encoding}': {e.reason}"
                )

        complete = end >= size
        return ToolResult(output={
            "content": content,
            "path": str(resolved),
            "size_bytes": size,
            "offset": tool_input.offset,
            "bytes_read": len(raw),
            "next_offset": None if complete else end,
            "complete": complete,
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
            assert r1.output["complete"] is True and r1.output["next_offset"] is None
            print(f"  [OK] reads normal file ({r1.output['bytes_read']} bytes)")

            # 2. NO CUT: a 3 MB file (3x the old 1 MB limit) is read whole.
            big = ("0123456789" * 100 + "\n") * 3000 + "TAIL"
            with open(tmp_path, "w", encoding="utf-8", newline="") as f:
                f.write(big)
            r2 = await safe_invoke(tool, {"path": tmp_path})
            assert r2.is_success and r2.output["content"] == big, r2.output.get("bytes_read")
            assert r2.output["complete"] is True
            print(f"  [OK] 3 MB file read WHOLE ({r2.output['bytes_read']} bytes, tail present)")

            # 2b. Explicit ranges page through the whole file, losslessly,
            # including a range boundary that falls inside a multi-byte char.
            text = "\u00e9" * 5001 + "END"
            with open(tmp_path, "w", encoding="utf-8", newline="") as f:
                f.write(text)
            parts, off = [], 0
            while off is not None:
                rp = await safe_invoke(tool, {"path": tmp_path, "offset": off, "max_bytes": 777})
                assert rp.is_success, rp.error
                parts.append(rp.output["content"])
                off = rp.output["next_offset"]
            assert "".join(parts) == text
            print(f"  [OK] {len(parts)} byte ranges reassemble the file exactly (UTF-8 safe)")

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

            # 6. Validation: a non-positive range length is rejected
            r6 = await safe_invoke(tool, {"path": tmp_path, "max_bytes": 0})
            assert r6.is_error
            print(f"  [OK] non-positive max_bytes rejected by Pydantic")

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
        print("  All 10 smoke tests passed.")
        print("=" * 60)

    asyncio.run(run())
