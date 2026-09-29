#!/usr/bin/env python3
"""Deliver Codex-authored agent mail queued on this machine.

The hook does no reasoning. Codex writes complete question/answer JSONL rows;
this adapter creates immutable mail files, commits only those files, and pushes.
Failures leave a retryable row and are surfaced to the active Codex session.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict

from agent_mail import answer, ask, list_threads

ROOT = Path(__file__).resolve().parents[1]
OUTBOX = ROOT / "jarvis_data" / ".codex_agent_mail_outbox.jsonl"
STATE = ROOT / "jarvis_data" / ".codex_agent_mail_delivery.json"
ID = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=20, check=False)


def _state() -> Dict[str, Dict[str, Any]]:
    try:
        value = json.loads(STATE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(state: Dict[str, Dict[str, Any]]) -> None:
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(STATE)


def _existing(message_id: str) -> Path | None:
    marker = f"<!-- codex-outbox-id: {message_id} -->"
    for thread in list_threads():
        for message in (thread.question, thread.answer):
            if message and marker in message.body:
                return message.path
    return None


def _create(row: Dict[str, Any]) -> Path:
    message_id = str(row["id"])
    found = _existing(message_id)
    if found:
        return found
    body = str(row["body"]).strip()
    if not body:
        raise ValueError("mail body is empty")
    body += f"\n\n<!-- codex-outbox-id: {message_id} -->"
    if row.get("kind") == "question":
        if row.get("to") != "claude" or not str(row.get("subject") or "").strip():
            raise ValueError("Codex questions require to=claude and a subject")
        return ask("claude", str(row["subject"]), body, "codex")
    if row.get("kind") == "answer":
        number = int(row["number"])
        thread = next((t for t in list_threads() if t.number == number), None)
        if not thread or thread.question.addressee != "codex":
            raise ValueError(f"q_{number:03d} is not addressed to Codex")
        return answer(number, body, "codex")
    raise ValueError("kind must be question or answer")


def dispatch() -> str:
    if not OUTBOX.exists():
        return ""
    state = _state()
    lines = OUTBOX.read_text(encoding="utf-8").splitlines()
    reports = []
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            message_id = str(row["id"])
            if not ID.fullmatch(message_id):
                raise ValueError("invalid mail id")
            if state.get(message_id, {}).get("pushed"):
                continue
            path = Path(state.get(message_id, {}).get("path") or _create(row))
            relative = path.relative_to(ROOT).as_posix()
            state[message_id] = {"path": str(path), "pushed": False}
            _save(state)
            staged = _run("git", "add", "--", relative)
            if staged.returncode:
                raise RuntimeError(f"git add: {staged.stderr.strip()}")
            changed = _run("git", "status", "--porcelain", "--", relative)
            if changed.stdout.strip():
                committed = _run("git", "commit", "--only", "-m",
                                 f"Agent mail from Codex: {path.stem}", "--", relative)
                if committed.returncode:
                    raise RuntimeError(f"git commit: {committed.stderr.strip() or committed.stdout.strip()}")
            pushed = _run("git", "push", "origin", "HEAD")
            if pushed.returncode:
                raise RuntimeError(f"git push: {pushed.stderr.strip() or pushed.stdout.strip()}")
            state[message_id]["pushed"] = True
            _save(state)
            reports.append(f"Delivered {relative} to Claude via Git.")
        except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as exc:
            reports.append(f"Agent-mail outbox line {line_number} needs attention: {type(exc).__name__}: {exc}")
            break
    return "\n".join(reports)


if __name__ == "__main__":
    print(dispatch())
