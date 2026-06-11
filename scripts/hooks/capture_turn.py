"""
capture_turn.py — Claude Code Stop-hook: thin adapter over the capture organ.

LAYER: Tools (Personalization capture — host adapter)

Registered as a `Stop` hook in .claude/settings.json (and in the committed
.agent/hooks.manifest.json — the canonical wiring any machine rehydrates via
scripts/bootstrap_jarvis.py). Fires after EVERY assistant turn in EVERY chat in
this workspace.

ALL capture logic lives in the core organ — jarvis_core/agent/capture.py
(transcript parsing, harness-wrapper stripping, secret redaction, domain hint,
model stamping, flock'd queue append) — per the Consciousness Portability
Contract: core organ + thin host-adapter, so a future Antigravity limb or server
daemon reuses the organ, not this file. This adapter only: reads the Stop event
from stdin, locates the organ, calls capture_stop_event(). Always exit 0 — a
broken hook must NEVER disrupt a turn.

Run `python3 scripts/hooks/capture_turn.py --self-test` for the adapter e2e
check; the organ's 18 smoke tests live with the organ.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _load_organ(cwd: str):
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "js-development"))
        from jarvis_core.agent import capture  # type: ignore
        return capture
    except Exception:
        try:
            sys.path.insert(0, str(Path(cwd) / "js-development"))
            from jarvis_core.agent import capture  # type: ignore
            return capture
        except Exception:
            return None


def main() -> int:
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0
    try:
        organ = _load_organ(event.get("cwd", os.getcwd()))
        if organ is not None:
            organ.capture_stop_event(event)
    except Exception:
        pass  # swallow everything — never disrupt the user's turn
    return 0


def _run_self_test() -> None:
    import tempfile

    print("=" * 70)
    print("  capture_turn.py -- Adapter e2e Smoke Tests")
    print("=" * 70)
    passed = 0
    failed = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        nonlocal passed
        if cond:
            passed += 1
        else:
            failed.append(f"FAIL: {name}" + (f" ({hint})" if hint else ""))

    organ = _load_organ(os.getcwd())
    check("T1 organ import resolves", organ is not None)

    with tempfile.TemporaryDirectory() as td:
        tp = Path(td) / "t.jsonl"
        tp.write_text("\n".join(json.dumps(r) for r in [
            {"type": "user", "message": {"content": [{"type": "text", "text": "explain spark shuffle"}]}},
            {"type": "assistant", "message": {"model": "claude-fable-5",
                                              "content": [{"type": "text", "text": "It is..."}]}},
        ]) + "\n", encoding="utf-8")
        q = Path(td) / "q.jsonl"
        rec = organ.capture_stop_event(
            {"session_id": "s", "transcript_path": str(tp), "cwd": td,
             "stop_hook_active": False},
            queue_path=q)
        check("T2 e2e capture through adapter path", rec is not None and q.exists())
        check("T3 model stamped via organ", rec is not None and rec.get("model") == "claude-fable-5")

    total = passed + len(failed)
    print(f"\n  Passed: {passed}/{total}")
    if failed:
        for f_ in failed:
            print(f"  {f_}")
        raise SystemExit(1)
    print(f"  All {total} adapter smoke tests passed.")
    print("=" * 70)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        _run_self_test()
    else:
        raise SystemExit(main())
