"""LAYER: Agent — approval-gated text creation and conflict-checked editing.

THE BIG PICTURE: an approved diff must apply to exactly the bytes reviewed.
THE FLOW: resolve -> protect authoritative sources -> verify -> atomic commit.
"""
from __future__ import annotations

from difflib import unified_diff
import hashlib
import os
from pathlib import Path
import tempfile
from typing import Optional

from pydantic import Field
from jarvis_core.config import JARVIS_ROOT
from jarvis_core.agent.tool import Tool, ToolInput, ToolResult
from jarvis_core.locking import exclusive_lock


def editable_path(root: Path, raw: str) -> Path:
    base = root.resolve()
    candidate = Path(raw).expanduser()
    path = (candidate if candidate.is_absolute() else base / candidate).resolve()
    if path == base or base not in path.parents:
        raise ValueError("File changes must remain inside the workspace")
    relative = path.relative_to(base)
    if relative.parts[0].lower() in {"jarvis_data", "client_work", ".git", ".venv", ".cache", "corpus"}:
        raise ValueError("Protected records/artifacts require their dedicated writer or builder")
    if path.exists() and not path.is_file():
        raise ValueError("Target must be a regular text file")
    if not path.parent.is_dir():
        raise ValueError("Parent directory must already exist")
    return path


class FileCreateInput(ToolInput):
    path: str = Field(json_schema_extra={"aliases": ["file_path", "filename"]})
    content: str
    encoding: str = "utf-8"


class FileEditInput(ToolInput):
    path: str = Field(json_schema_extra={"aliases": ["file_path", "filename"]})
    expected_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    old_text: str = Field(min_length=1)
    new_text: str
    encoding: str = "utf-8"


class _TextTool(Tool):
    requires_permission = True

    def __init__(self, root: Path = JARVIS_ROOT) -> None:
        self.root = Path(root)

    def normalize_input(self, tool_input: ToolInput) -> ToolInput:
        path = editable_path(self.root, tool_input.path)
        return tool_input.model_copy(update={"path": str(path)})

    def proposal(self, arguments: dict) -> dict:
        data = self.input_schema.model_validate(arguments)
        path = editable_path(self.root, data.path)
        if isinstance(data, FileCreateInput):
            old, new = "", data.content
        else:
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != data.expected_sha256:
                raise ValueError("File changed; read and approve the current content")
            old = raw.decode(data.encoding)
            if old.count(data.old_text) != 1:
                raise ValueError("Replacement must match exactly once")
            replacement = data.new_text
            if "\r\n" in old and "\n" not in old.replace("\r\n", ""):
                replacement = replacement.replace("\r\n", "\n").replace("\n", "\r\n")
            new = old.replace(data.old_text, replacement, 1)
        return {"path": str(path), "diff": "".join(unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
                                                    fromfile=str(path), tofile=str(path))), "content": new}

    async def invoke(self, tool_input: ToolInput) -> ToolResult:
        temp: Optional[Path] = None
        try:
            path = editable_path(self.root, tool_input.path)
            lock_root = self.root / ".runtime" / "file-locks"
            lock_root.mkdir(parents=True, exist_ok=True)
            key = hashlib.sha256(str(path).casefold().encode()).hexdigest()
            with exclusive_lock(lock_root / (key + ".lock")):
                if isinstance(tool_input, FileCreateInput) and path.exists():
                    return ToolResult(error="File already exists; creation refused", metadata={"error_code": "conflict"})
                proposed = self.proposal(tool_input.model_dump())
                content = proposed["content"]
                if "\x00" in content:
                    raise ValueError("Binary content is not supported")
                encoded = content.encode(tool_input.encoding)
                if isinstance(tool_input, FileEditInput):
                    original = path.read_bytes()
                    normalized_encoding = tool_input.encoding.lower().replace("_", "-")
                    if normalized_encoding == "utf-16" and original.startswith(b"\xfe\xff"):
                        encoded = b"\xfe\xff" + content.encode("utf-16-be")
                    elif normalized_encoding == "utf-32" and original.startswith(b"\x00\x00\xfe\xff"):
                        encoded = b"\x00\x00\xfe\xff" + content.encode("utf-32-be")
                    elif normalized_encoding == "utf-8-sig" and not original.startswith(b"\xef\xbb\xbf"):
                        encoded = content.encode("utf-8")
                with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".jarvis-edit-", delete=False) as fh:
                    temp = Path(fh.name)
                    fh.write(encoded); fh.flush(); os.fsync(fh.fileno())
                if editable_path(self.root, tool_input.path) != path:
                    raise ValueError("Target changed after approval")
                if isinstance(tool_input, FileCreateInput):
                    os.link(temp, path)
                else:
                    if hashlib.sha256(path.read_bytes()).hexdigest() != tool_input.expected_sha256:
                        raise ValueError("File changed during editing; change refused")
                    os.chmod(temp, path.stat().st_mode)
                    os.replace(temp, path)
                return ToolResult(output={"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "status": "created" if isinstance(tool_input, FileCreateInput) else "edited"})
        except FileNotFoundError as exc:
            return ToolResult(error=str(exc), metadata={"error_code": "path_not_found"})
        except (ValueError, OSError, UnicodeError) as exc:
            return ToolResult(error=str(exc), metadata={"error_code": "conflict"})
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)


@Tool.register("file_create")
class FileCreateTool(_TextTool):
    name = "file_create"
    description = "Create a new text file inside the workspace after approval. Never overwrites existing files. Protected records use their dedicated writers."
    input_schema = FileCreateInput


@Tool.register("file_edit")
class FileEditTool(_TextTool):
    name = "file_edit"
    description = "Apply one unique exact text replacement after approval. Requires SHA-256 of the complete current file; preserves other bytes and refuses stale content."
    input_schema = FileEditInput


if __name__ == "__main__":
    print(FileEditTool.schema_for_llm())
