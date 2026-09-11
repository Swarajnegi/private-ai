#!/usr/bin/env python3
"""Prepare an empty persistent data volume, then start the hosted hearth."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    data = Path(os.environ.get("JARVIS_DATA_ROOT", "/data"))
    data.mkdir(parents=True, exist_ok=True)
    for filename in ("knowledge_base.jsonl", "observation_queue.jsonl"):
        (data / filename).touch(exist_ok=True)
    command = [sys.executable, "scripts/hearth.py", "--host", "0.0.0.0",
               "--port", os.environ.get("PORT", "8756")]
    return subprocess.call(command)


if __name__ == "__main__":
    raise SystemExit(main())
