#!/usr/bin/env python3
"""
check_agent_mail.py — SessionStart adapter for the agent-to-agent channel.

LAYER: Tools (thin host adapter — all logic lives in scripts/agent_mail.py)

Fires at SessionStart. If another agent (Codex, Antigravity) has left a
question addressed to Claude Code in `agents_converse/`, or has answered one
Claude asked, this puts it in front of the model as `additionalContext`.

WHY A HOOK AND NOT A REMINDER. Codex and Antigravity have no hook system, so
their side of this channel is a documented boot step someone has to follow.
Claude Code does have one, so on this host the check is automatic — nobody has
to remember, and a question cannot sit unseen because the session got busy.
That asymmetry is the same one that makes capture automatic here and scheduled
there; see NERVOUS_SYSTEM.md §1.1.

Emits nothing when there is no mail — a hook that speaks when it has nothing
to say trains the reader to ignore it. Always exits 0: a broken hook must never
disrupt a turn.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _load_organ(cwd: str):
    """Import agent_mail from the repo, whether or not cwd is the repo root."""
    for base in (Path(__file__).resolve().parents[2], Path(cwd)):
        candidate = base / "scripts" / "agent_mail.py"
        if candidate.exists():
            sys.path.insert(0, str(base / "scripts"))
            import agent_mail  # noqa: E402
            return agent_mail
    return None


def main() -> int:
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
        organ = _load_organ(event.get("cwd", os.getcwd()))
        if organ is None:
            return 0
        body = organ.render_check("claude")
        if not body:
            return 0
        context = (
            "The following is mail from the OTHER agents working on this repo "
            "(Codex / Antigravity), left in agents_converse/ and delivered via git. "
            "Raise it with the user and answer it in this session if you can — an "
            "unanswered question blocks the other agent's work until its next "
            "session.\n\n" + body
        )
        out = {"hookSpecificOutput": {"hookEventName": "SessionStart",
                                      "additionalContext": context}}
        sys.stdout.write(json.dumps(out, ensure_ascii=False))
    except Exception:
        pass  # swallow everything — never disrupt the user's session
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
