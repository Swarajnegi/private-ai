#!/usr/bin/env python3
"""Prepare an empty persistent data volume, then start the hosted hearth."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _seed_conversations(data: Path) -> None:
    """Seed an empty hosted volume without overwriting remote conversations.

    The image carries the reviewed local conversation archive; the mounted
    volume is the durable source after first boot. Copying only missing files
    lets a later image add a new imported session without destroying anything
    created through the hosted UI.
    """
    seed_dir = Path("/app/jarvis_data/conversations")
    if not seed_dir.is_dir():
        return
    target_dir = data / "conversations"
    target_dir.mkdir(parents=True, exist_ok=True)
    for source in seed_dir.glob("*.jsonl"):
        target = target_dir / source.name
        if not target.exists():
            shutil.copy2(source, target)


def main() -> int:
    data = Path(os.environ.get("JARVIS_DATA_ROOT", "/data"))
    data.mkdir(parents=True, exist_ok=True)
    for filename in ("knowledge_base.jsonl", "observation_queue.jsonl"):
        (data / filename).touch(exist_ok=True)
    _seed_conversations(data)
    command = [sys.executable, "scripts/hearth.py", "--host", "0.0.0.0",
               "--port", os.environ.get("PORT", "8756")]
    return subprocess.call(command)


if __name__ == "__main__":
    raise SystemExit(main())
