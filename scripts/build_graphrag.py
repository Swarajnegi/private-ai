#!/usr/bin/env python3
"""Build JARVIS's rebuildable evidence-backed GraphRAG relationship index."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "js-development"))

from jarvis_core.memory.graph import build_graph


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild the derived JARVIS GraphRAG index.")
    parser.add_argument("--stats", action="store_true", help="Print the resulting node and edge counts.")
    args = parser.parse_args()
    stats = build_graph()
    if args.stats:
        print(f"GraphRAG rebuilt: {stats.nodes} nodes, {stats.edges} evidence-backed edges -> {stats.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
