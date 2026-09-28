"""
inject_profile.py — Claude Code SessionStart-hook: point at the user profile, to be read in full.

LAYER: Tools (Personalization injection — Memory Contract boot read)

Registered as a `SessionStart` hook in .claude/settings.json (matchers:
startup, resume, clear, compact). At the start of EVERY chat in the JARVIS
workspace it tells the model to READ jarvis_data/cognitive_profile.md in full
before its first reply, so the chat opens knowing who the user is.

=============================================================================
THE BIG PICTURE
=============================================================================

Until 2026-09-28 this hook pasted the whole profile into additionalContext.
That failed twice over, both silently:
    -> The harness replaces SessionStart output over ~10 KB with a 2 KB
       preview. The profile is ~650 KB, so at best 2 KB of it arrived.
    -> On Windows the pipe is cp1252; the first '→' in the profile raised
       UnicodeEncodeError, the except swallowed it, and the hook emitted
       NOTHING. Measured: 0 bytes.

Owner's rule: no truncation anywhere. So the hook emits a short notice — path,
size, entry count, and the exact Read pages that cover the file end to end —
and the model reads the file itself. That is a full read, not a cut.

=============================================================================
THE FLOW
=============================================================================

STEP 1: Read the SessionStart event JSON on stdin (cwd).
        |
STEP 2: Locate jarvis_data/cognitive_profile.md (config DATA_ROOT, else cwd).
        |
STEP 3: Missing/empty -> say so (a missing profile is a gap, not a silence).
        Else emit the notice: path, bytes, lines, entries, Read pages.
        Always exit 0.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _read_notice import emit, render_pages  # noqa: E402

_ENTRY = re.compile(rb"^- \[")
_KB_COUNT = re.compile(r"from `knowledge_base\.jsonl` \((\d+) entries\)")


def _profile_path(cwd: str) -> Path:
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "js-development"))
        from jarvis_core.config import DATA_ROOT  # type: ignore
        return Path(DATA_ROOT) / "cognitive_profile.md"
    except Exception:
        return Path(cwd) / "jarvis_data" / "cognitive_profile.md"


def notice(path: Path) -> str:
    if not path.exists() or path.stat().st_size == 0:
        return (f"JARVIS PROFILE MISSING: {path} does not exist or is empty. You do not know "
                "the owner this session. Tell them, and regenerate it with "
                "`python scripts/profile_synth.py`.")
    raw = path.read_bytes()
    lines = raw.count(b"\n") + (0 if raw.endswith(b"\n") else 1)
    entries = sum(1 for ln in raw.splitlines() if _ENTRY.match(ln))
    kb = _KB_COUNT.search(raw[:2000].decode("utf-8", "replace"))
    made = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="minutes")
    return (
        "JARVIS PROFILE — READ IT IN FULL BEFORE YOUR FIRST REPLY (Memory Contract, "
        "NERVOUS_SYSTEM.md §3).\n"
        f"File: {path}\n"
        f"Size: {len(raw):,} bytes, {lines} lines, {entries} entries"
        + (f", synthesized from {kb.group(1)} KB entries" if kb else "")
        + f", last written {made}.\n"
        "It is NOT pasted here because the harness cuts SessionStart output over ~10 KB to a "
        "2 KB preview. This is a pointer, not a cut: read every line with the Read tool, in "
        f"these pages: {render_pages(path)}.\n"
        "It is JARVIS's standing model of the owner (who they are, the people in their life, "
        "how they work, active directives). Treat it as background about who you are working "
        "with, not as instructions to act on."
    )


def main() -> int:
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0
    try:
        emit(notice(_profile_path(event.get("cwd", os.getcwd()))))
    except Exception:
        return 0
    return 0


def _self_test() -> int:
    import tempfile
    failed = []
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "cognitive_profile.md"
        body = ("# Cognitive Profile\n\n> Auto-synthesized by `scripts/profile_synth.py` from "
                "`knowledge_base.jsonl` (678 entries).\n\n## Who you are\n"
                + "".join(f"- [2026-09-28 · Decision] entry {i} → " + "z" * 3000 + "\n" for i in range(60)))
        p.write_text(body, encoding="utf-8")
        n = notice(p)
        if "READ IT IN FULL" not in n or str(p) not in n:
            failed.append("notice must name the file and demand a full read")
        if "60 entries" not in n or "678 KB entries" not in n:
            failed.append(f"notice must carry the entry counts: {n}")
        if len(n.encode("utf-8")) > 2000:
            failed.append(f"notice is {len(n)} chars; it must stay under the 2 KB preview")
        covered = sum(int(m) for m in re.findall(r"limit=(\d+)", n))
        if covered != body.count("\n"):
            failed.append(f"pages cover {covered} of {body.count(chr(10))} lines")
        json.dumps({"x": n}).encode("cp1252")  # the Windows pipe must accept it
        missing = notice(Path(td) / "nope.md")
        if "MISSING" not in missing:
            failed.append("a missing profile must be said, not silent")
    for f in failed:
        print("  FAIL", f)
    print(f"  inject_profile: {'PASS' if not failed else 'FAIL'}")
    return 1 if failed else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(_self_test())
    raise SystemExit(main())
