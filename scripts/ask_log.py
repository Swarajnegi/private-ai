#!/usr/bin/env python3
"""
ask_log.py — run a question through `--ask` and log it beside the Claude Code answer.

LAYER: Tools (Experiment harness — row 0 / row 0b evidence gathering)

Run with:
    python3 scripts/ask_log.py "the question" --claude-file /tmp/claude_answer.md

=============================================================================
THE BIG PICTURE
=============================================================================

Two roadmap rows are open questions that only calendar time can answer:

  row 0   Is JARVIS reached for at all?    19 sessions lifetime, 0 in 30 days.
  row 0b  Does proactive surfacing produce anything worth hearing?
          3 insights ever, all 2026-06-18.

The user committed to a 5-day trial (2026-09-07 -> 2026-09-11): every prompt
they send gets answered by Claude Code AND run through `--ask`, both recorded
full-length. This script is the recording half.

It moves BOTH rows, which is why it is worth the latency. Every `--ask` call
boots Mind, which fires the heartbeat, which runs the Consolidator — so the
trial also feeds the surfacing organ that has been starved since June.

WHAT THIS EXPERIMENT MEASURES, AND WHAT IT DOES NOT. The two sides are not
symmetric and pretending otherwise would make the log worthless:

  Claude Code has the full conversation, every file, tool use, and hours of
  accumulated session context. `--ask` gets ONE question cold, plus its boot
  inhale and its own tools.

So `--ask` will lose on continuity, and that is NOT evidence about JARVIS's
architecture. The question the log actually asks is narrower and fairer:

    Did JARVIS surface anything Claude Code did not?

That is the differentiator claim from ENDGAME §1.2 — unprompted recall of the
user's own history — and it is the only thing this trial can honestly test.

=============================================================================
THE FLOW
=============================================================================

STEP 1: Run `--ask` as a subprocess, capturing full stdout and wall-clock time.
        |
STEP 2: Parse the structured tail lines the orchestrator already prints
        (JARVIS/confidence/reasoning/ledger/tools/session) — no new format
        required from the orchestrator, this reads what it already emits.
        |
STEP 3: Append one Markdown entry holding BOTH full answers verbatim, the
        metadata, and an explicit unanswered field for the real measurement.
        Truncating either answer would defeat the point, so nothing is elided.
=============================================================================
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[1]
_IST = timezone(timedelta(hours=5, minutes=30))
_LOG_PATH = _REPO_ROOT / "jarvis_data" / "ask_vs_claude_log.md"
_TIMEOUT = 600

_FIELD_PATTERNS: Dict[str, re.Pattern] = {
    "answer": re.compile(r"^\s*JARVIS\s*:\s*(.*)$"),
    "confidence": re.compile(r"^\s*confidence:\s*(.*)$"),
    "reasoning": re.compile(r"^\s*reasoning\s*:\s*(.*)$"),
    "ledger": re.compile(r"^\s*ledger\s*:\s*(.*)$"),
    "session": re.compile(r"^\s*session\s*:\s*(.*)$"),
    "brain": re.compile(r"^\s*brain\s*:\s*(.*)$"),
}
_TOOL_PATTERN = re.compile(r"^\s*tool\s*:\s*(\S+)")


def _parse(stdout: str) -> Dict[str, object]:
    """Read the structured tail the orchestrator already prints."""
    found: Dict[str, object] = {}
    tools: List[str] = []
    answer_lines: List[str] = []
    capturing = False

    for line in stdout.splitlines():
        m = _TOOL_PATTERN.match(line)
        if m:
            tools.append(m.group(1))
            continue
        for key, pat in _FIELD_PATTERNS.items():
            hit = pat.match(line)
            if not hit:
                continue
            if key == "answer":
                capturing = True
                answer_lines = [hit.group(1)]
            else:
                capturing = False
                found[key] = hit.group(1).strip()
            break
        else:
            # A wrapped answer continues on following indented lines until the
            # next structured field. Preserve it — full length is the point.
            if capturing and line.strip() and not line.strip().startswith("["):
                answer_lines.append(line.strip())

    found["answer"] = "\n".join(answer_lines).strip() or "(no answer parsed)"
    found["tools"] = tools
    return found


def _run_ask(question: str) -> Dict[str, object]:
    cmd = [sys.executable, "-m", "jarvis_core.brain.orchestrator", "--ask", question]
    env_path = str(_REPO_ROOT / "js-development")
    started = time.time()
    try:
        proc = subprocess.run(
            cmd, cwd=str(_REPO_ROOT), capture_output=True, text=True,
            timeout=_TIMEOUT,
            env={**__import__("os").environ, "PYTHONPATH": env_path},
        )
        stdout = proc.stdout
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        return {"answer": f"(TIMED OUT after {_TIMEOUT}s)", "tools": [],
                "latency": float(_TIMEOUT), "rc": -1, "raw": ""}
    parsed = _parse(stdout)
    parsed["latency"] = round(time.time() - started, 1)
    parsed["rc"] = rc
    parsed["raw"] = stdout
    return parsed


def _next_entry_number(log_path: Path) -> int:
    try:
        text = log_path.read_text(encoding="utf-8")
    except (OSError, FileNotFoundError):
        return 1
    nums = [int(n) for n in re.findall(r"^## Entry (\d+)", text, re.MULTILINE)]
    return (max(nums) + 1) if nums else 1


def _render(n: int, question: str, claude_answer: str,
            j: Dict[str, object], now: datetime) -> str:
    tools = j.get("tools") or []
    tool_str = ", ".join(f"`{t}`" for t in tools) if tools else "none"
    return f"""
---

## Entry {n:03d} — {now.strftime('%Y-%m-%d %H:%M')} IST

**Prompt**

> {question.strip().replace(chr(10), chr(10) + '> ')}

### Claude Code (this session — full conversation context, tools, files)

{claude_answer.strip()}

### JARVIS `--ask` (cold: one question + boot inhale + its own tools)

{str(j.get('answer', '')).strip()}

**Run metadata**

| | |
|---|---|
| latency | {j.get('latency')}s |
| model | {j.get('brain', '?')} |
| session | {j.get('session', '?')} |
| tools called | {tool_str} |
| confidence | {j.get('confidence', '?')} |
| reasoning audit | {j.get('reasoning', '?')} |
| ledger | {j.get('ledger', '?')} |
| exit code | {j.get('rc')} |

**Did JARVIS surface anything Claude Code did not?** _(the actual measurement —
fill in honestly; "no" is the expected default and a useful result)_

- [ ] yes — what:
- [ ] no
"""


def main() -> int:
    p = argparse.ArgumentParser(
        description="Run a question through --ask and log it against the Claude Code answer.")
    p.add_argument("question", help="the prompt to send to --ask")
    p.add_argument("--claude-file", type=str, default=None,
                   help="path to a file holding the full Claude Code answer")
    p.add_argument("--log", type=str, default=None, help="override log path")
    p.add_argument("--raw-out", type=str, default=None,
                   help="also dump the raw --ask stdout here (fidelity check)")
    args = p.parse_args()

    log_path = Path(args.log) if args.log else _LOG_PATH
    claude_answer = "_(not supplied)_"
    if args.claude_file:
        try:
            claude_answer = Path(args.claude_file).read_text(encoding="utf-8")
        except (OSError, FileNotFoundError) as e:
            print(f"[ask_log] could not read --claude-file: {e}", file=sys.stderr)

    print(f"[ask_log] running --ask ... (expect ~90s)")
    j = _run_ask(args.question)
    print(f"[ask_log] done in {j.get('latency')}s, rc={j.get('rc')}")

    if args.raw_out:
        Path(args.raw_out).write_text(str(j.get("raw", "")), encoding="utf-8")

    n = _next_entry_number(log_path)
    entry = _render(n, args.question, claude_answer, j, datetime.now(_IST))
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(entry)
    print(f"[ask_log] appended Entry {n:03d} -> {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
