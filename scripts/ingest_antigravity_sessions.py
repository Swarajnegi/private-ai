#!/usr/bin/env python3
"""
ingest_antigravity_sessions.py — Antigravity capture adapter (ROADMAP 6.8.3, Q006).

LAYER: Tools (thin adapter — all logic lives in jarvis_core/agent/capture.py)

Run with:
    python3 scripts/ingest_antigravity_sessions.py --dry-run   # report only, write nothing
    python3 scripts/ingest_antigravity_sessions.py              # ingest new sessions
    python3 scripts/ingest_antigravity_sessions.py --status     # watermark + counts, no parsing
    python3 scripts/ingest_antigravity_sessions.py --self-test  # offline unit tests

=============================================================================
THE BIG PICTURE
=============================================================================

Antigravity has no Stop-hook system. For months on this machine, experience
capture was manual (/memory) or nothing — and "or nothing" is what happened.
Every turn the user spent here was lost from the training and personalization
corpora until now.

As discovered in q_001 and q_006, Antigravity PERSISTS ITS OWN COMPLETE
TRANSCRIPTS on disk under:
    ~/.gemini/antigravity-ide/brain/<conversation-id>/.system_generated/logs/
across three format generations:
    1. transcript_full.jsonl (latest, untruncated)
    2. transcript.jsonl      (mid, May 2026)
    3. overview.txt          (earliest, April 2026 JSONL format)

Audit confirmed: Antigravity does NOT prune, rotate, or garbage-collect these
directories. Sessions dating all the way back to 2026-04-03 remain completely
intact on disk.

This adapter implements the Consciousness Portability Contract for Antigravity:
it parses Antigravity session transcripts into (user_text, assistant_summary,
model, ts) and feeds them into `build_observation(..., ts=turn_ts)` and
`append_observation()`, the exact same organ that Claude Code's Stop hook and
Codex's rollout adapter call.

=============================================================================
THE FLOW
=============================================================================

STEP 1: Discover session directories in ~/.gemini/antigravity-ide/brain/.
        For each directory, pick the highest-fidelity transcript candidate:
        transcript_full.jsonl > transcript.jsonl > overview.txt.
        |
STEP 2: Load append-only per-file watermark (.antigravity_ingest_watermark.jsonl)
        keyed by f"{session_id}/{filename}".
        |
STEP 3: Stream each transcript file, stripping Antigravity's envelope tags
        (<USER_REQUEST>, <ADDITIONAL_METADATA>, etc.) and joining multi-part
        PLANNER_RESPONSE outputs into a clean assistant summary.
        |
STEP 4: Feed each turn to build_observation(..., ts=turn_ts) and
        append_observation().
        |
STEP 5: Advance watermark to the newest ts ingested for that session.
=============================================================================
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "js-development"))

from jarvis_core.agent.capture import (  # noqa: E402
    append_observation, build_observation, redact)
from jarvis_core.config import DATA_ROOT  # noqa: E402

_IST = timezone(timedelta(hours=5, minutes=30))
_MIN_USER_CHARS = 3

BRAIN_ROOT = Path.home() / ".gemini" / "antigravity-ide" / "brain"
WATERMARK_PATH = Path(DATA_ROOT) / ".antigravity_ingest_watermark.jsonl"

_ANTIGRAVITY_METADATA_TAGS = (
    "ADDITIONAL_METADATA", "WORKFLOW", "USER_SETTINGS_CHANGE", "UUID"
)
_METADATA_RE = re.compile(
    r"<(" + "|".join(re.escape(t) for t in _ANTIGRAVITY_METADATA_TAGS) + r")\b[^>]*>.*?</\1>",
    re.DOTALL | re.IGNORECASE)


def strip_antigravity_wrapper(text: str) -> str:
    """Remove Antigravity envelope tags, returning the real user prompt.

    Handles well-formed <USER_REQUEST>...</USER_REQUEST>, unclosed
    <USER_REQUEST> from early truncated logs (overview.txt), and strips
    injected metadata blocks (<ADDITIONAL_METADATA>, <WORKFLOW>, etc.).
    """
    if not text:
        return ""
    # Case 1: Well-formed <USER_REQUEST>...</USER_REQUEST>
    m = re.search(r"<USER_REQUEST>(.*?)</USER_REQUEST>", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()

    # Case 2: Unclosed <USER_REQUEST> (e.g. truncated overview.txt)
    m_start = re.search(r"<USER_REQUEST>(.*)", text, re.DOTALL | re.IGNORECASE)
    if m_start:
        content = m_start.group(1)
        m_meta = re.search(
            r"<(" + "|".join(re.escape(t) for t in _ANTIGRAVITY_METADATA_TAGS) + r")\b",
            content, re.IGNORECASE)
        if m_meta:
            content = content[:m_meta.start()]
        return content.strip()

    # Case 3: No <USER_REQUEST> envelope, but may have metadata blocks
    return _METADATA_RE.sub(" ", text).strip()


def _to_ist(iso_utc: str) -> str:
    """Convert UTC ISO timestamp ('...Z') to IST (+05:30)."""
    if not iso_utc:
        return ""
    try:
        dt = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
    except ValueError:
        return iso_utc
    return dt.astimezone(_IST).isoformat(timespec="seconds")


def load_thread_name(session_dir: Path) -> str:
    """Extract human-readable thread name from task.md or fallback to dirname."""
    task_file = session_dir / "task.md"
    if task_file.exists():
        try:
            for line in task_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("# "):
                    title = line[2:].strip()
                    if title:
                        return title
        except OSError:
            pass
    return session_dir.name


@dataclass(frozen=True)
class AntigravityExchange:
    """One user->assistant exchange extracted from an Antigravity transcript."""
    user_text: str
    assistant_summary: str
    model_hint: str
    ts: str                # ISO 8601, IST — the turn's OWN time, not ingest time
    session_id: str
    cwd: str
    thread_name: str


def iter_session_exchanges(
    path: Path, session_id: str, thread_name: str, cwd: str
) -> Iterator[AntigravityExchange]:
    """Stream one transcript file; yield one AntigravityExchange per user->assistant pair."""
    pending_user: Optional[Tuple[str, str]] = None
    assistant_parts: List[str] = []

    def flush() -> Optional[AntigravityExchange]:
        nonlocal pending_user, assistant_parts
        if pending_user is None:
            return None
        user_text, ts = pending_user
        summary = redact("\n\n".join(assistant_parts).strip())
        pending_user, assistant_parts = None, []
        if len(user_text.strip()) < _MIN_USER_CHARS:
            return None
        return AntigravityExchange(
            user_text=redact(user_text),
            assistant_summary=summary,
            model_hint="",
            ts=ts,
            session_id=session_id,
            cwd=cwd,
            thread_name=thread_name
        )

    try:
        handle = path.open("r", encoding="utf-8")
    except OSError:
        return

    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue

            rec_type = rec.get("type")
            if rec_type == "USER_INPUT":
                content = str(rec.get("content", ""))
                user_text = strip_antigravity_wrapper(content)
                if len(user_text.strip()) < _MIN_USER_CHARS:
                    continue
                out = flush()
                if out is not None:
                    yield out
                raw_ts = str(rec.get("created_at") or rec.get("timestamp") or rec.get("ts") or "")
                pending_user = (user_text, _to_ist(raw_ts))
            elif rec_type == "PLANNER_RESPONSE" and pending_user is not None:
                content = str(rec.get("content", "")).strip()
                if content:
                    assistant_parts.append(content)

    out = flush()
    if out is not None:
        yield out


def find_sessions(root: Optional[Path] = None) -> List[Tuple[str, Path, str]]:
    """Find all valid Antigravity sessions and their primary transcripts.

    Returns:
        List of (session_id, transcript_path, thread_name) sorted chronologically.
    """
    root = Path(root) if root is not None else BRAIN_ROOT
    if not root.exists():
        return []

    found = []
    candidates = (
        Path(".system_generated") / "logs" / "transcript_full.jsonl",
        Path(".system_generated") / "logs" / "transcript.jsonl",
        Path(".system_generated") / "logs" / "overview.txt",
        Path("overview.txt"),
    )

    for session_dir in root.iterdir():
        if not session_dir.is_dir():
            continue
        chosen: Optional[Path] = None
        for rel in candidates:
            p = session_dir / rel
            if p.exists() and p.stat().st_size > 0:
                chosen = p
                break
        if chosen is None:
            continue

        thread_name = load_thread_name(session_dir)
        first_ts = ""
        try:
            with chosen.open("r", encoding="utf-8") as f:
                for line in f:
                    try:
                        rec = json.loads(line.strip())
                        first_ts = str(rec.get("created_at") or rec.get("timestamp") or rec.get("ts") or "")
                        if first_ts:
                            break
                    except json.JSONDecodeError:
                        continue
        except OSError:
            pass

        found.append((first_ts, session_dir.name, chosen, thread_name))

    found.sort(key=lambda x: (x[0], x[1]))
    return [(sid, path, tname) for _, sid, path, tname in found]


# =============================================================================
# Part: WATERMARK (append-only — same discipline as codex & tension watermarks)
# =============================================================================

def read_watermark(path: Optional[Path] = None) -> Dict[str, str]:
    """{session_file_key: newest_ts_ingested}. Folds to max per key."""
    path = Path(path) if path is not None else WATERMARK_PATH
    out: Dict[str, str] = {}
    try:
        handle = path.open("r", encoding="utf-8")
    except (OSError, FileNotFoundError):
        return out
    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = str(rec.get("file") or rec.get("session") or "")
            ts = str(rec.get("ts", ""))
            if key and ts > out.get(key, ""):
                out[key] = ts
    return out


def advance_watermark(key: str, ts: str, path: Optional[Path] = None) -> None:
    """Append one watermark record. Heals a missing newline terminator first."""
    path = Path(path) if path is not None else WATERMARK_PATH
    rec = json.dumps({"file": key, "ts": ts}, ensure_ascii=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as fh:
        try:
            fh.seek(0, 2)
            needs_nl = fh.tell() > 0
            if needs_nl:
                fh.seek(fh.tell() - 1)
                needs_nl = fh.read(1) != "\n"
        except (OSError, ValueError):
            needs_nl = False
        fh.write(("\n" if needs_nl else "") + rec + "\n")
        fh.flush()


# =============================================================================
# Part: RUN
# =============================================================================

def run(
    dry_run: bool = False,
    root: Optional[Path] = None,
    watermark_path: Optional[Path] = None,
    queue_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Ingest Antigravity session exchanges newer than their watermark."""
    root = Path(root) if root is not None else BRAIN_ROOT
    sessions = find_sessions(root)
    if not sessions:
        return {
            "ok": True,
            "sessions_found": 0,
            "exchanges_ingested": 0,
            "reason": f"no session transcripts under {root} — Antigravity has "
                      f"not run on this machine yet, or brain/ moved",
        }

    marks = read_watermark(watermark_path)
    ingested = 0
    per_session: Dict[str, int] = {}

    for sid, path, thread_name in sessions:
        key = f"{sid}/{path.name}"
        watermark = marks.get(key, "")
        newest_seen = watermark
        session_count = 0

        for exch in iter_session_exchanges(path, sid, thread_name, str(_REPO_ROOT)):
            if watermark and exch.ts <= watermark:
                continue
            if not dry_run:
                obs = build_observation(
                    {"session_id": exch.session_id},
                    {"user_text": exch.user_text,
                     "assistant_summary": exch.assistant_summary,
                     "model": exch.model_hint},
                    exch.cwd or str(_REPO_ROOT),
                    ts=exch.ts)
                if obs is not None:
                    obs["chat_label"] = exch.thread_name or obs["chat_label"]
                    kwargs = {"queue_path": queue_path} if queue_path is not None else {}
                    append_observation(obs, **kwargs)

            ingested += 1
            session_count += 1
            if exch.ts > newest_seen:
                newest_seen = exch.ts

        if session_count and not dry_run and newest_seen > watermark:
            advance_watermark(key, newest_seen, watermark_path)
        if session_count:
            per_session[key] = session_count

    return {
        "ok": True,
        "sessions_found": len(sessions),
        "exchanges_ingested": ingested,
        "per_session": per_session,
    }


def main() -> int:
    p = argparse.ArgumentParser(
        description="Ingest Antigravity transcripts into observation_queue.jsonl "
                    "(the Antigravity capture adapter, ROADMAP 6.8.3, Q006).")
    p.add_argument("--dry-run", action="store_true",
                   help="report what WOULD be ingested; write nothing, advance no watermark")
    p.add_argument("--status", action="store_true",
                   help="session/watermark counts only; does not parse any file")
    p.add_argument("--self-test", action="store_true",
                   help="run hermetic offline unit tests")
    args = p.parse_args()

    if args.self_test:
        _run_self_test()
        return 0

    if args.status:
        sessions = find_sessions()
        marks = read_watermark()
        print(f"Antigravity brain dir : {BRAIN_ROOT} "
              f"({'exists' if BRAIN_ROOT.exists() else 'MISSING'})")
        print(f"sessions found        : {len(sessions)}")
        print(f"watermarked sessions  : {len(marks)}")
        if not sessions:
            print("\nNo sessions found — capture from this host has produced nothing yet.")
        return 0

    result = run(dry_run=args.dry_run)
    label = "[dry-run] would ingest" if args.dry_run else "ingested"
    print(f"sessions found      : {result['sessions_found']}")
    print(f"{label:<20}: {result['exchanges_ingested']}")
    if result.get("reason"):
        print(f"reason              : {result['reason']}")
    for key, n in result.get("per_session", {}).items():
        print(f"  {key:<60} {n}")
    if result["exchanges_ingested"] == 0 and result["sessions_found"] > 0:
        print("\n0 new exchanges — either everything is already watermarked, or every "
              "session has no real user turn.")
    return 0


# =============================================================================
# SMOKE TESTS (offline — synthetic transcripts, temp dirs, no ~/.gemini touched)
# =============================================================================

def _run_self_test() -> None:
    import tempfile

    print("=" * 70)
    print("  ingest_antigravity_sessions.py -- Smoke Tests")
    print("=" * 70)
    passed = 0
    failed: List[str] = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        nonlocal passed
        if cond:
            passed += 1
            print(f"  PASS  {name}")
        else:
            failed.append(name)
            print(f"  FAIL  {name}  {hint}")

    # --- strip_antigravity_wrapper ---
    check("T1 well-formed USER_REQUEST extracted cleanly",
          strip_antigravity_wrapper("<USER_REQUEST>hello world</USER_REQUEST>") == "hello world")
    check("T2 strips metadata block outside USER_REQUEST",
          strip_antigravity_wrapper("<USER_REQUEST>do task</USER_REQUEST><ADDITIONAL_METADATA>time</ADDITIONAL_METADATA>") == "do task")
    check("T3 unclosed USER_REQUEST truncated before metadata",
          strip_antigravity_wrapper("<USER_REQUEST>revert changes<ADDITIONAL_METADATA>meta") == "revert changes")
    check("T4 preserves code blocks and angle brackets inside user text",
          "<div>test</div>" in strip_antigravity_wrapper("<USER_REQUEST>how to fix <div>test</div></USER_REQUEST>"))
    check("T5 empty content strips to empty",
          strip_antigravity_wrapper("<USER_REQUEST>\n\n</USER_REQUEST>") == "")

    # --- _to_ist ---
    check("T6 converts UTC Z timestamp to IST (+05:30)",
          _to_ist("2026-05-21T06:07:11Z") == "2026-05-21T11:37:11+05:30")
    check("T7 passthrough on invalid date",
          _to_ist("not-a-date") == "not-a-date")

    def _rec(**kw) -> str:
        return json.dumps(kw, ensure_ascii=False)

    with tempfile.TemporaryDirectory() as td:
        temp_dir = Path(td)
        session_id = "test-session-001"
        sdir = temp_dir / session_id
        logs_dir = sdir / ".system_generated" / "logs"
        logs_dir.mkdir(parents=True)

        (sdir / "task.md").write_text("# Test Task Checklist\n- [ ] step 1", encoding="utf-8")

        # --- T8: load_thread_name ---
        check("T8 extracts thread name from task.md header",
              load_thread_name(sdir) == "Test Task Checklist")

        # --- T9-T13: iter_session_exchanges ---
        tf = logs_dir / "transcript_full.jsonl"
        lines = [
            _rec(type="USER_INPUT", created_at="2026-09-01T10:00:00Z",
                 content="<USER_REQUEST>what is qlora?</USER_REQUEST><ADDITIONAL_METADATA>meta</ADDITIONAL_METADATA>"),
            _rec(type="PLANNER_RESPONSE", created_at="2026-09-01T10:00:05Z",
                 content="QLoRA quantizes base weights to 4-bit"),
            _rec(type="PLANNER_RESPONSE", created_at="2026-09-01T10:00:10Z",
                 content=" and attaches 16-bit LoRA adapters."),
            _rec(type="USER_INPUT", created_at="2026-09-01T10:05:00Z",
                 content="<USER_REQUEST>does it save VRAM?</USER_REQUEST>"),
            _rec(type="PLANNER_RESPONSE", created_at="2026-09-01T10:05:05Z",
                 content="Yes, significantly."),
        ]
        tf.write_text("\n".join(lines) + "\n", encoding="utf-8")

        exchanges = list(iter_session_exchanges(tf, session_id, "Test Task Checklist", "/test"))
        check("T9 extracts correct number of exchanges", len(exchanges) == 2, str(len(exchanges)))
        check("T10 joins multi-part PLANNER_RESPONSE",
              "quantizes base weights" in exchanges[0].assistant_summary
              and "attaches 16-bit LoRA" in exchanges[0].assistant_summary)
        check("T11 timestamps converted to IST",
              exchanges[0].ts == "2026-09-01T15:30:00+05:30")
        check("T12 thread_name attached to exchange",
              exchanges[0].thread_name == "Test Task Checklist")

        # --- T13: torn/corrupt JSON line does not abort ---
        tf_corrupt = logs_dir / "transcript_corrupt.jsonl"
        tf_corrupt.write_text(
            _rec(type="USER_INPUT", created_at="2026-09-01T10:00:00Z",
                 content="<USER_REQUEST>turn 1</USER_REQUEST>") + "\n"
            + "{corrupt line\n"
            + _rec(type="PLANNER_RESPONSE", created_at="2026-09-01T10:00:05Z",
                 content="answer 1") + "\n",
            encoding="utf-8"
        )
        ex_corrupt = list(iter_session_exchanges(tf_corrupt, session_id, "Test", "/test"))
        check("T13 torn JSON line is safely skipped", len(ex_corrupt) == 1 and ex_corrupt[0].user_text == "turn 1")

        # --- T14-T17: Watermark logic ---
        wm_path = temp_dir / ".wm.jsonl"
        key = f"{session_id}/transcript_full.jsonl"
        advance_watermark(key, "2026-09-01T15:30:00+05:30", wm_path)
        advance_watermark(key, "2026-09-01T15:35:00+05:30", wm_path)
        advance_watermark(key, "2026-09-01T15:20:00+05:30", wm_path)  # older, must not win
        wm = read_watermark(wm_path)
        check("T14 watermark folds to max ts per key",
              wm.get(key) == "2026-09-01T15:35:00+05:30", str(wm))

        torn_wm = temp_dir / ".torn_wm.jsonl"
        torn_wm.write_text('{"file":"a","ts":"2026-01-01T00:00:00+05:30"}', encoding="utf-8")
        advance_watermark("b", "2026-01-02T00:00:00+05:30", torn_wm)
        check("T15 heals missing newline in watermark",
              len(read_watermark(torn_wm)) == 2)

        # --- T16-T19: run() end-to-end and watermark idempotency ---
        queue = temp_dir / "queue.jsonl"
        run_wm = temp_dir / "run_wm.jsonl"

        res1 = run(dry_run=False, root=temp_dir, watermark_path=run_wm, queue_path=queue)
        check("T16 run() ingests both exchanges",
              res1["exchanges_ingested"] == 2, str(res1))
        check("T17 observation queue received records",
              queue.exists() and len(queue.read_text(encoding="utf-8").splitlines()) == 2)

        res2 = run(dry_run=False, root=temp_dir, watermark_path=run_wm, queue_path=queue)
        check("T18 second run ingests 0 (watermark prevents re-ingest)",
              res2["exchanges_ingested"] == 0, str(res2))

        # --- T19: missing directory returns clean reason without crashing ---
        empty_res = run(root=temp_dir / "nonexistent", watermark_path=run_wm, queue_path=queue)
        check("T19 missing brain directory reports clean reason",
              empty_res["sessions_found"] == 0 and "reason" in empty_res)

    total = passed + len(failed)
    print("-" * 70)
    print(f"  {passed}/{total} passed")
    if failed:
        for name in failed:
            print(f"    - {name}")
    print("=" * 70)
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    raise SystemExit(main())
