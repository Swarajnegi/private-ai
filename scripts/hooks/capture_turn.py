"""
capture_turn.py — Claude Code Stop-hook: redacted per-turn capture.

LAYER: Tools (Personalization capture)

Registered as a `Stop` hook in .claude/settings.json. Fires after EVERY
assistant turn in EVERY chat opened in the JARVIS workspace. Appends one
redacted, compact JSON line to jarvis_data/observation_queue.jsonl — the
raw signal buffer the Stage 3.5.7 consolidator later drains for deep
"who is this user" inference.

=============================================================================
THE BIG PICTURE
=============================================================================

Without this hook:
    -> The KB only grows when a model REMEMBERS to run the cognitive-profiling
       instruction mid-turn. A pure coding turn in the warehouse chat writes
       nothing. Growth is best-effort and lossy.

With this hook:
    -> Every turn of every chat is captured automatically — guaranteed,
       even when the model never ran a /memory scan. Nothing is lost.
    -> stdlib-only (no sentence-transformers, no network) so it stays well
       under a second. It NEVER blocks or errors out a turn (always exit 0).
    -> Redacts secrets (PAT / sk- / Bearer / AWS / long blobs) before writing,
       because the transcript can contain a pasted token.

=============================================================================
THE FLOW
=============================================================================

STEP 1: Read the Stop event JSON on stdin (session_id, transcript_path,
        cwd, stop_hook_active).
        |
        v
STEP 2: If stop_hook_active -> exit 0 (loop guard; we never block anyway).
        |
        v
STEP 3: Parse transcript JSONL. Extract the last real USER text message
        (skip tool_results + sidechain/subagent turns) and the assistant
        text that followed it (compact summary).
        |
        v
STEP 4: Redact secrets. Compute cheap heuristic signals.
        |
        v
STEP 5: Append ONE JSON line to observation_queue.jsonl under flock.
        |
        v
STEP 6: Always exit 0. Any error is swallowed.

=============================================================================
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import fcntl
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False

_IST = timezone(timedelta(hours=5, minutes=30))

# --- Secret redaction patterns (same classes as the react.py R1/M11 fixes) ---
_REDACTORS = [
    re.compile(r"github_pat_[A-Za-z0-9_]+"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgho_[A-Za-z0-9]{20,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]+"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),       # slack tokens
    re.compile(r"\b[A-Fa-f0-9]{40,}\b"),                  # long hex (sha/keys)
    re.compile(r"\b[A-Za-z0-9+/]{50,}={0,2}\b"),          # long base64-ish blobs
]

_CORRECTION_MARKERS = re.compile(
    r"\b(no,|actually|wait\b|that'?s wrong|not what|instead|nope|incorrect|"
    r"you misunderstood|re-?do|revert)\b",
    re.IGNORECASE,
)

# Coarse domain guess from cwd + content keywords. Best-effort labeling only.
_DOMAIN_KEYWORDS = {
    "data-engineering": ["spark", "warehouse", "pyspark", "sql", "etl", "dbt", "databricks", "airflow"],
    "finance": ["portfolio", "stock", "sip", "groww", "nse", "investment", "rebalance"],
    "ai-ml": ["transformer", "embedding", "lora", "fine-tune", "gradient", "attention", "rag"],
    "jarvis-build": ["jarvis_core", "react.py", "memory_manager", "tool.py", "stage 3", "react loop"],
}

_MAX_USER_CHARS = 2000
_MAX_ASSISTANT_CHARS = 400


def _ist_now_iso() -> str:
    return datetime.now(_IST).isoformat(timespec="seconds")


def _redact(text: str) -> str:
    if not text:
        return text
    out = text
    for rx in _REDACTORS:
        out = rx.sub("[REDACTED]", out)
    return out


# --- Harness wrapper blocks: injected by Claude Code into the user turn, NOT
# user-typed. Stripped before storing so they don't pollute the synthesis signal
# (e.g. <ide_opened_file> paths contain "JARVIS" and mis-classify as jarvis-build).
# KB L315. Conservative known-tag list only — never a generic "<...>" strip, which
# would eat legitimate code/HTML the user pasted. ---
_HARNESS_TAGS = (
    "ide_opened_file", "ide_selection", "system-reminder", "task-notification",
    "local-command-caveat", "local-command-stdout", "command-name",
    "command-message", "command-args", "user-prompt-submit-hook",
)
_HARNESS_PAIRED = re.compile(
    r"<(" + "|".join(_HARNESS_TAGS) + r")\b[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_HARNESS_STANDALONE = re.compile(
    r"</?(" + "|".join(_HARNESS_TAGS) + r")\b[^>]*/?>", re.IGNORECASE)


def _strip_harness_blocks(text: str) -> str:
    """Remove harness-injected wrapper blocks, leaving only user-typed content."""
    if not text:
        return text
    out = _HARNESS_PAIRED.sub(" ", text)      # paired <tag>...</tag>
    out = _HARNESS_STANDALONE.sub(" ", out)   # any leftover/standalone tag
    return out


def _block_text(content: Any) -> str:
    """Concatenate the 'text' blocks of a message.content (list or str).
    Ignores tool_use / tool_result blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text", ""))
        return "\n".join(p for p in parts if p)
    return ""


def _is_real_user_text(rec: Dict[str, Any]) -> bool:
    """True for a genuine user-typed message: not a tool_result, not sidechain, and
    NOT just harness wrapper blocks (an <ide_opened_file>-only or <task-notification>-
    only turn has no user content once stripped, so we skip past it to the real turn)."""
    if rec.get("type") != "user" or rec.get("isSidechain"):
        return False
    content = (rec.get("message") or {}).get("content")
    return bool(_strip_harness_blocks(_block_text(content)).strip())


def _extract_turn(transcript_path: str) -> Optional[Dict[str, str]]:
    """Return {user_text, assistant_summary} for the most recent main-thread
    turn, or None if nothing capturable."""
    p = Path(transcript_path)
    if not p.exists():
        return None
    records: List[Dict[str, Any]] = []
    try:
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return None

    # Find the last real user-text message index.
    last_user_idx = -1
    for i in range(len(records) - 1, -1, -1):
        if _is_real_user_text(records[i]):
            last_user_idx = i
            break
    if last_user_idx == -1:
        return None

    user_text = _strip_harness_blocks(
        _block_text((records[last_user_idx].get("message") or {}).get("content"))
    ).strip()

    # Collect assistant text emitted AFTER that user message (this turn).
    assistant_parts: List[str] = []
    for rec in records[last_user_idx + 1:]:
        if rec.get("type") == "assistant" and not rec.get("isSidechain"):
            t = _block_text((rec.get("message") or {}).get("content"))
            if t:
                assistant_parts.append(t)
    assistant_summary = "\n".join(assistant_parts)

    return {
        "user_text": user_text[:_MAX_USER_CHARS],
        "assistant_summary": assistant_summary[:_MAX_ASSISTANT_CHARS],
    }


def _guess_domain(cwd: str, blob: str) -> str:
    hay = (cwd + " " + blob).lower()
    best, best_hits = "general", 0
    for domain, kws in _DOMAIN_KEYWORDS.items():
        hits = sum(1 for k in kws if k in hay)
        if hits > best_hits:
            best, best_hits = domain, hits
    return best


def _queue_path(cwd: str) -> Path:
    """Resolve the observation queue path. Prefer jarvis_core.config.DATA_ROOT;
    fall back to <cwd>/jarvis_data so the hook works even if the import fails."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "js-development"))
        from jarvis_core.config import DATA_ROOT  # type: ignore
        return Path(DATA_ROOT) / "observation_queue.jsonl"
    except Exception:
        return Path(cwd) / "jarvis_data" / "observation_queue.jsonl"


def _append_line(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(obj, ensure_ascii=False)
    with open(path, "a", encoding="utf-8") as f:
        if _HAS_FCNTL:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write(line + "\n")
            f.flush()
        finally:
            if _HAS_FCNTL:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def main() -> int:
    # Everything wrapped: a Stop hook must NEVER break a turn. Always exit 0.
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0

    try:
        if event.get("stop_hook_active"):
            return 0

        cwd = event.get("cwd", os.getcwd())
        transcript_path = event.get("transcript_path", "")
        turn = _extract_turn(transcript_path) if transcript_path else None
        if turn is None:
            return 0  # nothing capturable this turn

        user_text = _redact(turn["user_text"])
        assistant_summary = _redact(turn["assistant_summary"])
        if not user_text.strip():
            return 0

        chat_label = Path(cwd).name or "unknown"
        domain = _guess_domain(cwd, user_text + " " + assistant_summary)

        record = {
            "ts": _ist_now_iso(),
            "session_id": event.get("session_id", ""),
            "machine": os.environ.get("JARVIS_MACHINE", os.uname().nodename if hasattr(os, "uname") else "unknown"),
            "cwd": cwd,
            "chat_label": chat_label,
            "user_text": user_text,
            "assistant_summary": assistant_summary,
            "tokens": {
                "input": event.get("input_tokens"),
                "output": event.get("output_tokens"),
            },
            "heuristic_signals": {
                "prompt_len": len(user_text),
                "has_correction_markers": bool(_CORRECTION_MARKERS.search(user_text)),
                "domain_guess": domain,
            },
        }
        _append_line(_queue_path(cwd), record)
    except Exception:
        # Swallow everything — never disrupt the user's turn.
        return 0
    return 0


def _run_self_test() -> None:
    import tempfile

    print("=" * 70)
    print("  capture_turn.py -- Smoke Tests (harness-block stripping)")
    print("=" * 70)
    passed = 0
    failed: List[str] = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        nonlocal passed
        if cond:
            passed += 1
        else:
            failed.append(f"FAIL: {name}" + (f" ({hint})" if hint else ""))

    # --- strip behavior ---
    check("T1 paired ide_opened_file stripped, real question kept",
          _strip_harness_blocks(
              "<ide_opened_file>The user opened /home/x/JARVIS/y.py</ide_opened_file>\nwhat is AQE?"
          ).strip() == "what is AQE?")
    check("T2 task-notification-only -> empty",
          _strip_harness_blocks(
              "<task-notification><task-id>w19</task-id></task-notification>").strip() == "")
    check("T3 system-reminder stripped mid-text",
          (lambda s: "actual question" in s and "noise" not in s)(
              _strip_harness_blocks("hi <system-reminder>noise here</system-reminder> actual question")))
    check("T4 plain text untouched", _strip_harness_blocks("hello world").strip() == "hello world")
    check("T5 code with < and > NOT stripped (no harness tag)",
          _strip_harness_blocks("if x < y and a > b: return [i for i in xs]")
          == "if x < y and a > b: return [i for i in xs]")
    check("T6 command wrappers stripped",
          _strip_harness_blocks("<command-name>/next</command-name><command-args></command-args>").strip() == "")

    # --- is_real_user_text now skips pure-wrapper turns ---
    wrap = {"type": "user", "message": {"content": [
        {"type": "text", "text": "<task-notification><task-id>w1</task-id></task-notification>"}]}}
    real = {"type": "user", "message": {"content": [
        {"type": "text", "text": "<ide_opened_file>f /JARVIS/z</ide_opened_file>\nexplain shuffle partitions"}]}}
    tres = {"type": "user", "message": {"content": [{"type": "tool_result", "content": "out"}]}}
    check("T7 pure-wrapper user msg is NOT real", _is_real_user_text(wrap) is False)
    check("T8 wrapper+question IS real", _is_real_user_text(real) is True)
    check("T9 tool_result is not real", _is_real_user_text(tres) is False)

    # --- extract_turn skips a trailing pure-wrapper turn, strips the inline wrapper ---
    with tempfile.TemporaryDirectory() as td:
        tp = Path(td) / "t.jsonl"
        recs = [real,
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "Shuffle partitions are..."}]}},
                wrap]  # trailing pure-wrapper turn
        tp.write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
        turn = _extract_turn(str(tp))
        check("T10 extract finds the real question past the trailing wrapper, inline wrapper stripped",
              turn is not None and turn["user_text"].strip() == "explain shuffle partitions", str(turn))

    total = passed + len(failed)
    print(f"\n  Passed: {passed}/{total}")
    if failed:
        for f_ in failed:
            print(f"  {f_}")
        print("=" * 70)
        raise SystemExit(1)
    print(f"  All {total} capture_turn smoke tests passed.")
    print("=" * 70)


if __name__ == "__main__":
    # The Stop hook is invoked with NO args (stdin only); --self-test is dev-only.
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        _run_self_test()
    else:
        raise SystemExit(main())
