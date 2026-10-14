"""LAYER: Agent — request-local verified read reuse.

THE BIG PICTURE: do not spend repeated model turns rediscovering unchanged bytes.
THE FLOW: identify exact range -> verify file digest -> reuse or execute.
"""
from __future__ import annotations
from dataclasses import replace
import hashlib
from pathlib import Path
from jarvis_core.agent.tool import ToolResult


class ReadCoverage:
    def __init__(self) -> None:
        self._reads: dict[tuple, ToolResult] = {}

    def _key(self, arguments: dict) -> tuple:
        path = Path(arguments["path"]).resolve()
        with path.open("rb") as fh:
            digest = hashlib.file_digest(fh, "sha256").hexdigest()
        return str(path), digest, arguments.get("encoding", "utf-8"), arguments.get("offset", 0), arguments.get("max_bytes")

    def get(self, arguments: dict) -> ToolResult | None:
        try:
            result = self._reads.get(self._key(arguments))
        except (OSError, ValueError):
            return None
        if result is None:
            return None
        return replace(result, metadata={**(result.metadata or {}), "reused": True, "execution": "prior verified read"})

    def remember(self, arguments: dict, result: ToolResult) -> None:
        if result.is_success:
            try:
                key = self._key(arguments)
                if isinstance(result.output, dict) and result.output.get("sha256") != key[1]:
                    return
                self._reads[key] = result
            except (OSError, ValueError):
                pass


if __name__ == "__main__":
    print("ReadCoverage is request-local; no persistent cache")
