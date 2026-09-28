"""
inject_recent_activity.py — Claude Code SessionStart-hook: cross-chat recall, read in full.

LAYER: Tools (Personalization — recall; Memory Contract boot read)

The THIRD SessionStart hook, alongside inject_profile.py (who you are) and
surface_life_state.py (raise an insight). It answers "what have I been doing?"
across ALL chats and hosts from the local capture queue — never git.

=============================================================================
THE BIG PICTURE
=============================================================================

Until 2026-09-28 this hook pasted the 7-day digest (~16 KB) into
additionalContext, and the harness replaced it with a 2 KB preview: the chat
opened knowing the first two days at most. Owner's rule: no truncation. So the
hook now (1) makes sure jarvis_data/activity_digest.md is fresh — rewritten
through agent/recall.py whenever the capture queue has turns newer than it —
and (2) emits a short notice with its path, size, counts and the exact Read
pages, telling the model to read it in full. The same file is what Codex and
Antigravity read at boot, so all three see one digest.

=============================================================================
THE FLOW
=============================================================================

STEP 1: Read the SessionStart event JSON on stdin (cwd).
        |
STEP 2: queue newer than the digest -> rewrite the digest (tmp + os.replace,
        so a reader never sees half a file; an empty local queue never
        overwrites a synced digest).
        |
STEP 3: emit the notice. Refresh failure -> the notice says the digest may be
        stale and why. Always exit 0.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _read_notice import emit, render_pages  # noqa: E402

_DAYS = 7
_TOTALS = re.compile(r"last (\d+) days \((\d+) turns, (\d+) chats\)")
_DAY_LINE = re.compile(r"^- \d{4}-\d{2}-\d{2} ", re.MULTILINE)


def _recaller_cls(cwd: str):
    for base in (Path(__file__).resolve().parents[2], Path(cwd)):
        sys.path.insert(0, str(base / "js-development"))
        try:
            from jarvis_core.agent.recall import ActivityRecaller  # type: ignore
            return ActivityRecaller
        except Exception:
            continue
    return None


def refresh(digest: Path, queue: Path, recaller) -> Optional[str]:
    """Rewrite the digest when the queue holds newer turns. Returns an error line, or None."""
    try:
        if digest.exists() and queue.exists() and digest.stat().st_mtime >= queue.stat().st_mtime:
            return None
        if not queue.exists():
            return None if digest.exists() else f"no capture queue at {queue} and no digest"
        tmp = digest.with_name("." + digest.name + ".tmp")
        try:
            recaller.write_digest(days=_DAYS, out_path=tmp)
            if "no captured turns" in tmp.read_text(encoding="utf-8") and digest.exists():
                return None  # an empty local window never blanks the synced digest
            os.replace(tmp, digest)
        finally:
            if tmp.exists():
                tmp.unlink()
        return None
    except Exception as exc:  # noqa: BLE001
        return f"refresh failed ({type(exc).__name__}: {exc})"


def _counts(text: str) -> Tuple[str, int]:
    m = _TOTALS.search(text)
    totals = f"{m.group(2)} turns in {m.group(3)} chats over {m.group(1)} days" if m else "counts unreadable"
    return totals, len(_DAY_LINE.findall(text))


def notice(digest: Path, error: Optional[str]) -> str:
    if not digest.exists() or digest.stat().st_size == 0:
        return (f"JARVIS ACTIVITY DIGEST MISSING: {digest}"
                + (f" — {error}" if error else "")
                + ". You do not know what the owner did in their other chats. Tell them; "
                  "regenerate with `python js-development/jarvis_core/agent/recall.py --write`.")
    raw = digest.read_bytes()
    text = raw.decode("utf-8", "replace")
    totals, days = _counts(text)
    lines = raw.count(b"\n")
    made = datetime.fromtimestamp(digest.stat().st_mtime).isoformat(timespec="minutes")
    stale = (f"\nWARNING: the digest could not be refreshed and may be stale: {error}. "
             "Say so to the owner.") if error else ""
    return (
        "JARVIS ACTIVITY DIGEST — READ IT IN FULL BEFORE YOUR FIRST REPLY (Memory Contract, "
        "NERVOUS_SYSTEM.md §3).\n"
        f"File: {digest}\n"
        f"Size: {len(raw):,} bytes, {lines} lines; "
        f"{totals}, {days} day section(s); last written {made}.\n"
        "It is NOT pasted here because the harness cuts SessionStart output over ~10 KB to a "
        "2 KB preview. This is a pointer, not a cut: read every line with the Read tool, in "
        f"these pages: {render_pages(digest)}.\n"
        "It is the owner's own captured turns across ALL chats and hosts (local capture, NOT "
        "git). Treat it as background on what they have been working on elsewhere."
        + stale
    )


def main() -> int:
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0
    try:
        cwd = event.get("cwd", os.getcwd())
        cls = _recaller_cls(cwd)
        if cls is None:
            digest = Path(cwd) / "jarvis_data" / "activity_digest.md"
            emit(notice(digest, "jarvis_core.agent.recall could not be imported"))
            return 0
        from jarvis_core.config import DATA_ROOT  # type: ignore
        digest = Path(DATA_ROOT) / "activity_digest.md"
        queue = Path(DATA_ROOT) / "observation_queue.jsonl"
        emit(notice(digest, refresh(digest, queue, cls(queue_path=queue))))
    except Exception:
        return 0
    return 0


def _self_test() -> int:
    import tempfile
    import time
    failed = []

    class FakeRecaller:
        def __init__(self, body: str) -> None:
            self.body, self.calls = body, 0

        def write_digest(self, days: int, out_path: Path) -> Path:
            self.calls += 1
            out_path.write_text(self.body, encoding="utf-8")
            return out_path

    fresh_body = ("# Activity Digest\n\nRECENT ACTIVITY — your own captured turns across ALL chats, "
                  "last 7 days (120 turns, 9 chats). Source: local\n\n"
                  "- 2026-09-28 (Mon): 50 turns — a → b\n- 2026-09-27 (Sun): 70 turns\n")
    with tempfile.TemporaryDirectory() as td:
        d, q = Path(td) / "activity_digest.md", Path(td) / "q.jsonl"
        d.write_text("old digest\n", encoding="utf-8")
        q.write_text("{}\n", encoding="utf-8")
        old = time.time() - 100
        os.utime(d, (old, old))
        r = FakeRecaller(fresh_body)
        err = refresh(d, q, r)
        if err or r.calls != 1 or "120 turns" not in d.read_text(encoding="utf-8"):
            failed.append(f"a digest older than the queue must be rewritten (err={err})")
        if refresh(d, q, r) is not None or r.calls != 1:
            failed.append("a digest newer than the queue must not be rewritten")
        os.utime(d, (old, old))
        if refresh(d, q, FakeRecaller("RECENT ACTIVITY: no captured turns in the last 7 days")) \
                or "120 turns" not in d.read_text(encoding="utf-8"):
            failed.append("an empty window must never blank a real digest")
        if list(Path(td).glob(".*.tmp")):
            failed.append("tmp file left behind")
        n = notice(d, None)
        if "READ IT IN FULL" not in n or "120 turns in 9 chats over 7 days" not in n \
                or "2 day section(s)" not in n or "offset=1 limit=" not in n:
            failed.append(f"notice incomplete: {n}")
        if len(n) > 2000:
            failed.append("notice must stay under the 2 KB preview")
        json.dumps({"x": n}).encode("cp1252")
        if "may be stale" not in notice(d, "refresh failed (OSError: x)"):
            failed.append("a refresh failure must be said")

        class Boom:
            def write_digest(self, **_):
                raise OSError("disk full")
        os.utime(d, (old, old))
        if "disk full" not in (refresh(d, q, Boom()) or ""):
            failed.append("a refresh exception must come back as an error line")
        if "MISSING" not in notice(Path(td) / "none.md", None):
            failed.append("a missing digest must be said")
    for f in failed:
        print("  FAIL", f)
    print(f"  inject_recent_activity: {'PASS' if not failed else 'FAIL'}")
    return 1 if failed else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(_self_test())
    raise SystemExit(main())
