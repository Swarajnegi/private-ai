"""
jsonl_merge.py — fallback merge tool for knowledge_base.jsonl.

Use this when git's `merge=union` strategy on *.jsonl gets confused
(rare; usually only if both sides edited the SAME line, which is very
unlikely with single-user-at-a-time workflow).

What it does:
  1. Reads two JSONL files.
  2. Parses each line as JSON.
  3. Deduplicates entries by content hash (timestamp + type + first 300 chars
     of content + sorted tags).
  4. Preserves all unique entries from both inputs.
  5. Sorts by timestamp ascending.
  6. Writes merged JSONL to stdout (or --out).

Usage:
    python3 scripts/jsonl_merge.py knowledge_base_a.jsonl knowledge_base_b.jsonl > merged.jsonl
    python3 scripts/jsonl_merge.py a.jsonl b.jsonl --out merged.jsonl
    python3 scripts/jsonl_merge.py a.jsonl b.jsonl --out a.jsonl   # in-place merge into A

The merge is idempotent: running it twice on the same inputs produces the
same output.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, Iterator


def read_entries(path: Path) -> Iterator[Dict]:
    """Yield parsed JSON entries from a JSONL file, skipping blanks/garbage."""
    with open(path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                print(f"[warn] {path}:{lineno} unparseable, skipping: {e}", file=sys.stderr)


def entry_key(entry: Dict) -> str:
    """Stable dedup key — collisions only on truly identical entries."""
    parts = [
        entry.get("timestamp", ""),
        entry.get("type", ""),
        str(sorted(entry.get("tags", []))),
        entry.get("content", "")[:300],
    ]
    blob = "|".join(parts).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def merge(file_a: Path, file_b: Path) -> list:
    """Merge two JSONL files into a sorted, deduplicated list of entries."""
    seen = {}
    for entry in read_entries(file_a):
        seen[entry_key(entry)] = entry
    a_count = len(seen)

    for entry in read_entries(file_b):
        seen[entry_key(entry)] = entry  # later wins on identical keys (same data)
    total = len(seen)
    b_unique = total - a_count

    print(
        f"[info] {file_a.name}: {a_count} unique  |  "
        f"{file_b.name}: +{b_unique} new  |  total: {total}",
        file=sys.stderr,
    )

    # Sort by timestamp; entries without timestamp go last.
    return sorted(seen.values(), key=lambda e: e.get("timestamp", "9999"))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("file_a", type=Path, help="First JSONL file")
    p.add_argument("file_b", type=Path, help="Second JSONL file")
    p.add_argument("--out", type=Path, default=None, help="Output path (default: stdout)")
    args = p.parse_args()

    if not args.file_a.exists():
        print(f"[error] not found: {args.file_a}", file=sys.stderr)
        return 1
    if not args.file_b.exists():
        print(f"[error] not found: {args.file_b}", file=sys.stderr)
        return 1

    merged = merge(args.file_a, args.file_b)

    if args.out is None:
        for entry in merged:
            print(json.dumps(entry, ensure_ascii=False))
    else:
        with open(args.out, "w", encoding="utf-8") as f:
            for entry in merged:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print(f"[ok] wrote {len(merged)} entries -> {args.out}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
