"""
codex_parse_nudge.py — Codex's visible Memory Contract trigger.

LAYER: Memory (Codex host adapter)

THE BIG PICTURE
Codex captures turns on the hearth, but only the chatting agent can judge
them under PARSE_RULE. This hook runs cheap boot checks and tells that agent
when to parse; it never submits verdicts or invokes a background judge.

THE FLOW
SessionStart checks machine health, ingests transcripts, then offers a
20-turn boot batch. UserPromptSubmit offers ten turns when the backlog is
at least ten. Failures become context, never a blocked user prompt.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[2]
THRESHOLD = 10


def _python() -> Path:
    candidate = ROOT / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python3")
    return candidate if candidate.is_file() else Path(sys.executable)


def _run(script: str, *args: str, timeout: int = 90) -> str:
    result = subprocess.run(
        [str(_python()), str(ROOT / "scripts" / script), *args],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, check=False,
    )
    if result.returncode and script != "bootstrap_jarvis.py":
        detail = (result.stderr or result.stdout).strip().splitlines()
        return f"{script} failed (rc={result.returncode}): {detail[-1] if detail else 'no detail'}"
    return result.stdout


def _pending() -> int:
    sys.path.insert(0, str(ROOT / "js-development"))
    from jarvis_core.agent.parse_ledger import backlog
    return int(backlog()["codex"]["pending"])


def _notice(pending: int, limit: int) -> str:
    return (
        f"CODEX PARSE BACKLOG: {pending} turn(s) pending under the shared PARSE_RULE. "
        "Before continuing, read the complete packet and judge every offered turn in this chat:\n"
        f"  python scripts/parse_turns.py --pending --host codex --limit {limit}\n"
        "  python scripts/parse_turns.py --submit <verdicts.json> --agent codex/<model>\n"
        "A preview is not a full read. Never invent or silently skip a verdict. "
        "The hook only reminds you; it does not judge."
    )


def context(event: Dict[str, Any]) -> str:
    name = event.get("hook_event_name")
    if name == "SessionStart":
        health = _run("bootstrap_jarvis.py", "--check")
        ingested = _run("ingest_codex_sessions.py")
        health_line = next((line.strip() for line in health.splitlines()
                            if "pipeline health" in line), "bootstrap health unavailable")
        pending = _pending()
        base = (f"JARVIS BOOT: {health_line}. Capture: {ingested.strip() or 'no new rollouts'}. "
                "Read AGENTS.md, cognitive_profile.md and activity_digest.md in full; "
                "check life-state surfacing and agent mail. "
                + (_notice(pending, 20) if pending else "No Codex turns await parsing."))
        delivered = _run("agent_mail_outbox.py", timeout=20).strip()
        return "\n".join(part for part in (base, delivered) if part)
    if name == "UserPromptSubmit":
        pending = _pending()
        delivered = _run("agent_mail_outbox.py", timeout=20).strip()
        return "\n".join(part for part in (
            _notice(pending, 10) if pending >= THRESHOLD else "", delivered
        ) if part)
    return ""


def main() -> int:
    try:
        event = json.load(sys.stdin)
        message = context(event)
        if message:
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": event["hook_event_name"],
                "additionalContext": message,
            }}, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"systemMessage": f"JARVIS Codex parse hook failed: {type(exc).__name__}: {exc}. "
                                           "Run python scripts/bootstrap_jarvis.py --check manually."}))
    return 0


def _self_test() -> None:
    assert "--limit 20" in _notice(20, 20)
    assert "--limit 10" in _notice(10, 10)
    assert "--submit" in _notice(10, 10)
    assert ROOT.name == "J.A.R.V.I.S"
    print("codex_parse_nudge: 4/4 passed")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        _self_test()
    else:
        raise SystemExit(main())
