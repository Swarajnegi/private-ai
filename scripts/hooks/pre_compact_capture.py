"""
pre_compact_capture.py — Claude Code PreCompact hook: store the session before it compacts.

LAYER: Tools (Context Store — host adapter)

Registered as a `PreCompact` hook in .claude/settings.json. Claude Code sends
{session_id, transcript_path, trigger, ...} on stdin just before it replaces
the conversation with a summary. This adapter ingests that transcript (and its
subagent transcripts) into the episode store immediately, incrementally from
the manifest offset, and writes this machine's shard member.

Claude Code keeps pre-compaction lines in the transcript file, so the hourly
hearth job would reach them too; this hook removes the window in which the
only full copy of a long session is a file the host may later prune. It is
fail-soft and never waits: if another ingest holds the lock it exits at once
(that run covers this transcript), and every error is swallowed — a hook must
never block compaction. Always exit 0.

Run `python scripts/hooks/pre_compact_capture.py --self-test` for the e2e check.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "js-development"))


def capture(event: Dict[str, Any], root: Optional[Path] = None) -> int:
    """Ingest the event's transcript; returns new events stored (0 on skip/failure)."""
    try:
        from jarvis_core.locking import try_exclusive_lock
        from jarvis_core.memory.episode_sources import ingest_claude_transcript
        from jarvis_core.memory.episode_store import EpisodeStore

        tp = event.get("transcript_path")
        if not tp or not Path(tp).is_file():
            return 0
        store = EpisodeStore(root=root)
        store.root.mkdir(parents=True, exist_ok=True)
        with try_exclusive_lock(store.root / "ingest") as got:
            if not got:
                return 0
            return ingest_claude_transcript(store, Path(tp))
    except Exception:
        return 0


def main() -> int:
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0
    capture(event)
    return 0


def _run_self_test() -> None:
    import tempfile

    from jarvis_core.memory.episode_store import iter_episode

    print("=" * 70)
    print("  pre_compact_capture.py -- Adapter e2e Smoke Tests")
    print("=" * 70)
    passed, failed = 0, []

    def check(name: str, cond: bool, hint: str = "") -> None:
        nonlocal passed
        if cond:
            passed += 1
            print(f"  PASS  {name}")
        else:
            failed.append(name)
            print(f"  FAIL  {name}  {hint}")

    with tempfile.TemporaryDirectory() as td:
        proj = Path(td) / "projects" / "E--repo"
        (proj / "s1" / "subagents").mkdir(parents=True)
        tp = proj / "s1.jsonl"
        tp.write_text(json.dumps({"type": "user", "timestamp": "2026-09-28T10:00:00Z",
                                  "message": {"content": "remember this"}}) + "\n", encoding="utf-8")
        (proj / "s1" / "subagents" / "agent-x.jsonl").write_text(
            json.dumps({"type": "user", "isSidechain": True, "timestamp": "2026-09-28T10:00:00Z",
                        "message": {"content": "sub"}}) + "\n", encoding="utf-8")
        root = Path(td) / "cs"
        n = capture({"session_id": "s1", "transcript_path": str(tp), "trigger": "auto"}, root=root)
        check("T1 the transcript and its subagent are stored", n == 2, str(n))
        check("T2 the event is readable by episode id",
              [r["content"] for r in iter_episode("ep:claude:s1", root)] == ["remember this"])
        check("T3 a second PreCompact adds nothing",
              capture({"transcript_path": str(tp)}, root=root) == 0)
        check("T4 junk events never raise",
              capture({"transcript_path": 5}, root=root) == 0 and capture({}, root=root) == 0)
    total = passed + len(failed)
    print(f"  {passed}/{total} passed")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        _run_self_test()
    raise SystemExit(main())
