#!/usr/bin/env python3
"""
ingest_codex_sessions.py — the Codex capture adapter (ROADMAP 6.8.3).

LAYER: Tools (thin adapter — all logic lives in jarvis_core/agent/capture.py)

Run with:
    python3 scripts/ingest_codex_sessions.py --dry-run   # report only, write nothing
    python3 scripts/ingest_codex_sessions.py              # ingest new rollouts
    python3 scripts/ingest_codex_sessions.py --status     # watermark + counts, no parsing

=============================================================================
THE BIG PICTURE
=============================================================================

Claude Code has a `Stop` hook: a turn ends, `capture_turn.py` fires, one line
lands in `observation_queue.jsonl`. Antigravity and now Codex have no hook
system, so capture there has always been "manual `/memory`, or nothing" — and
measured on 2026-09-10, "or nothing" is what actually happened: all 592
captured turns in the live queue come from ONE machine. The personal laptop's
contribution, across months of real Antigravity use, is zero.

Codex changes what's possible, not because it has hooks, but because it
PERSISTS ITS OWN TRANSCRIPTS to `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`
regardless of whether anything reads them. That is enough to build a REAL
capture adapter instead of a manual one — this is ROADMAP 6.8.3, "build a
second reference adapter, prove the contract generalizes."

WHY THIS FEEDS THE SAME ORGAN RATHER THAN A NEW STORE. `agent/capture.py`'s
`build_observation` / `append_observation` / `redact` / `guess_domain` are
already host-agnostic per the module's own design (verified: zero `~/.claude/`
paths in any of them). The only Claude-specific parts were the STOP-HOOK EVENT
SHAPE and the TRANSCRIPT JSONL FORMAT — both of which live in `extract_turn`
and `capture_stop_event`, NOT in the organ this file calls. So the adapter
contract is: parse your host's format into `{user_text, assistant_summary,
model}`, then call the same two functions Claude Code's hook calls. One queue,
one schema, one place every downstream consumer (recall.py, tension.py,
domain labeling) already knows how to read.

ONE REAL CHANGE WAS NEEDED IN THE ORGAN, not worked around here:
`build_observation` hardcoded `ist_now_iso()` for `ts` — correct for a LIVE
Stop hook (the turn just ended, "now" IS its timestamp) and wrong for
ingesting a HISTORICAL rollout written days or weeks ago. Backdating every
ingested turn to "now" would corrupt every timestamp-ordered consumer:
recall.py's day-by-day grouping, tension.py's "only the past can be a prior"
filter, the domain-label projection's (ts, session_id) key. Rather than
duplicate `build_observation`'s dict construction here — which would fork the
schema the moment either copy changed — `build_observation` gained an
optional `ts` override (capture.py, 2026-09-10). Every existing call site is
unaffected; this is the only caller that uses it.

DEGRADED MODE (ROADMAP 6.8.4): a host with no adapter must say so, not
silently lose turns. `AGENTS.md`'s CAPTURE STATUS section tells Codex to run
`--status` before assuming capture is live. This script itself never pretends
success: `--dry-run` and `--status` report exact counts, and a run that
ingests 0 says why (no new rollouts vs. no rollouts directory at all).

=============================================================================
THE FLOW
=============================================================================

STEP 1: Load session_index.jsonl for {id: thread_name} — Codex's own registry
        of session titles, keyed by the same uuid the rollout filename embeds.
        |
STEP 2: Load the append-only watermark: the newest timestamp already ingested
        PER ROLLOUT FILE (not global — a long-lived rollout keeps growing, and
        a global watermark would either re-scan it forever or miss late turns
        appended to an old file after a newer file was already watermarked).
        |
STEP 3: For each rollout file newer than its watermark: stream it once,
        extract (user_text, assistant_summary, model, ts) per real exchange —
        skipping `role="developer"` entirely (harness/system prompts) and
        stripping Codex's own injected wrapper tags from user turns.
        |
STEP 4: Feed each exchange to build_observation(ts=<the turn's own time>) then
        append_observation() — the SAME organ Claude Code's Stop hook uses.
        |
STEP 5: Advance the per-file watermark to the newest ts actually ingested.
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

CODEX_HOME = Path.home() / ".codex"
SESSIONS_ROOT = CODEX_HOME / "sessions"
SESSION_INDEX_PATH = CODEX_HOME / "session_index.jsonl"
WATERMARK_PATH = Path(DATA_ROOT) / ".codex_ingest_watermark.jsonl"

# Codex's own injected wrapper blocks inside a role="user" message — the
# equivalent of capture.py's _HARNESS_TAGS, but a DIFFERENT vocabulary because
# it is a different host. Measured against two real rollouts (2026-07,
# 2026-09): recommended_plugins and environment_context appear on nearly every
# session's first user message; multi_agent_mode appears on role="developer"
# instead in the sessions checked, but is included here too since nothing
# guarantees that stays true across Codex versions.
_CODEX_WRAPPER_TAGS = (
    "recommended_plugins", "environment_context", "multi_agent_mode",
    "skills_instructions", "permissions instructions",
)
_WRAPPER_RE = re.compile(
    r"<(" + "|".join(re.escape(t) for t in _CODEX_WRAPPER_TAGS) + r")\b[^>]*>.*?</\1>",
    re.DOTALL | re.IGNORECASE)

_MIN_USER_CHARS = 3        # a real exchange needs SOME user text; not a content filter


def strip_codex_wrapper(text: str) -> str:
    """Remove Codex's injected context blocks, leaving user-typed content.

    Mirrors capture.py's strip_harness_blocks for a different host's tag
    vocabulary. Deliberately narrow (a KNOWN-tag allowlist), same reasoning as
    the Claude Code version: a blanket `<...>` strip would eat pasted code or
    XML the user typed on purpose.
    """
    if not text:
        return text
    return _WRAPPER_RE.sub(" ", text).strip()


@dataclass(frozen=True)
class CodexExchange:
    """One user->assistant exchange extracted from a rollout."""
    user_text: str
    assistant_summary: str
    model_hint: str
    ts: str                # ISO 8601, IST — the turn's OWN time, not ingest time
    session_id: str
    cwd: str
    thread_name: str


def _to_ist(iso_utc: str) -> str:
    """Codex timestamps are ISO-8601 UTC ('...Z'). The rest of the queue is
    IST throughout (capture.py, recall.py, tension.py) — convert once here so
    every downstream consumer keeps its single-timezone assumption."""
    try:
        dt = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
    except ValueError:
        return iso_utc  # unparseable -> pass through rather than raise
    return dt.astimezone(_IST).isoformat(timespec="seconds")


def _message_text(payload: Dict[str, Any]) -> str:
    """Join a response_item message's content blocks into one string.

    Content is a list of {"type": "input_text"|"output_text", "text": ...}
    blocks (verified against real rollouts); anything else (tool calls,
    images) is skipped — this adapter captures conversational text only, the
    same scope capture.py's extract_turn has for Claude Code.
    """
    content = payload.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") in ("input_text", "output_text"):
            parts.append(str(block.get("text", "")))
    return "\n".join(p for p in parts if p)


def iter_rollout_exchanges(path: Path, thread_name: str) -> Iterator[CodexExchange]:
    """Stream one rollout file; yield one CodexExchange per user->assistant pair.

    A rollout may contain MANY real exchanges (unlike a Claude Code Stop-hook
    event, which only ever reports the LAST one) — this walks the whole file
    once, in order, accumulating each user turn and flushing it once the next
    real user turn (or end of file) closes it off.
    """
    session_id = ""
    cwd = ""
    pending_user: Optional[Tuple[str, str]] = None   # (text, ts)
    assistant_parts: List[str] = []

    def flush() -> Optional[CodexExchange]:
        nonlocal pending_user, assistant_parts
        if pending_user is None:
            return None
        user_text, ts = pending_user
        summary = redact("\n".join(assistant_parts).strip())
        pending_user, assistant_parts = None, []
        if len(user_text.strip()) < _MIN_USER_CHARS:
            return None
        return CodexExchange(
            user_text=redact(user_text), assistant_summary=summary,
            model_hint="", ts=ts, session_id=session_id, cwd=cwd,
            thread_name=thread_name)

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
                continue  # a torn/corrupt line must not abort the whole file

            if rec.get("type") == "session_meta":
                meta = rec.get("payload", {})
                session_id = str(meta.get("session_id") or meta.get("id") or "")
                cwd = str(meta.get("cwd") or "")
                continue

            if rec.get("type") != "response_item":
                continue
            payload = rec.get("payload", {})
            if payload.get("type") != "message":
                continue

            role = payload.get("role")
            if role == "developer":
                continue  # harness/system prompt, never user content

            text = _message_text(payload)
            if role == "user":
                text = strip_codex_wrapper(text)
                if not text.strip():
                    continue  # was ENTIRELY wrapper content — not a real turn
                out = flush()
                if out is not None:
                    yield out
                pending_user = (text, _to_ist(str(rec.get("timestamp", ""))))
            elif role == "assistant" and pending_user is not None:
                if text.strip():
                    assistant_parts.append(text)

    out = flush()
    if out is not None:
        yield out


def load_thread_names(path: Optional[Path] = None) -> Dict[str, str]:
    """{session_uuid: thread_name} from Codex's own session index.

    `path` defaults via a body-level lookup, not a `= SESSION_INDEX_PATH`
    parameter default — a default is bound ONCE at function-definition time,
    so a later `module.SESSION_INDEX_PATH = other_path` (exactly what a test
    needs to stay offline) would be silently ignored. Same fix applied to
    every function below; see the T21 failure this caught, in this module's
    own self-test history.
    """
    path = Path(path) if path is not None else SESSION_INDEX_PATH
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
            sid = str(rec.get("id", ""))
            if sid:
                out[sid] = str(rec.get("thread_name", "") or "codex-session")
    return out


def find_rollouts(root: Optional[Path] = None) -> List[Path]:
    root = Path(root) if root is not None else SESSIONS_ROOT
    if not root.exists():
        return []
    return sorted(root.rglob("rollout-*.jsonl"))


def _session_id_from_filename(path: Path) -> str:
    """The uuid embedded in `rollout-<timestamp>-<uuid>.jsonl`."""
    m = re.search(
        r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$",
        path.name, re.IGNORECASE)
    return m.group(1) if m else path.stem


# =============================================================================
# Part: WATERMARK (append-only — same discipline as .tension_watermark.jsonl
# and .surfaced_watermark.jsonl: a rewritten value loses cross-process safety
# the moment two writers touch it; concatenation never does)
# =============================================================================

def read_watermark(path: Optional[Path] = None) -> Dict[str, str]:
    """{rollout_filename: newest_ts_ingested}. Folds to the max per file."""
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
            fname, ts = str(rec.get("file", "")), str(rec.get("ts", ""))
            if fname and ts > out.get(fname, ""):
                out[fname] = ts
    return out


def advance_watermark(fname: str, ts: str, path: Optional[Path] = None) -> None:
    """Append one record. Heals a missing terminator first (KB 565 — the same
    torn-line defect found in three other append-only logs on 2026-09-08)."""
    path = Path(path) if path is not None else WATERMARK_PATH
    rec = json.dumps({"file": fname, "ts": ts}, ensure_ascii=False)
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
# Part: THE RUN
# =============================================================================

def run(dry_run: bool = False) -> Dict[str, Any]:
    """Ingest every rollout exchange newer than its file's watermark.

    Returns a summary dict — always, including on a totally empty environment
    (no ~/.codex/sessions/ at all), because a silent zero is the exact failure
    this adapter exists to avoid (ROADMAP 6.8.4).
    """
    rollouts = find_rollouts()
    if not rollouts:
        return {"ok": True, "rollouts_found": 0, "exchanges_ingested": 0,
                "reason": f"no rollouts under {SESSIONS_ROOT} — Codex has not "
                          f"run on this machine yet, or sessions/ moved"}

    thread_names = load_thread_names()
    marks = read_watermark()
    ingested = 0
    per_file: Dict[str, int] = {}

    for path in rollouts:
        sid = _session_id_from_filename(path)
        thread_name = thread_names.get(sid, path.stem)
        watermark = marks.get(path.name, "")
        newest_seen = watermark
        file_count = 0

        for exch in iter_rollout_exchanges(path, thread_name):
            if exch.ts <= watermark:
                continue  # already ingested on a prior run
            if not dry_run:
                obs = build_observation(
                    {"session_id": exch.session_id or sid},
                    {"user_text": exch.user_text,
                     "assistant_summary": exch.assistant_summary,
                     "model": exch.model_hint},
                    exch.cwd or str(_REPO_ROOT),
                    ts=exch.ts, host="codex")
                if obs is not None:
                    obs["chat_label"] = exch.thread_name or obs["chat_label"]
                    append_observation(obs)
            ingested += 1
            file_count += 1
            if exch.ts > newest_seen:
                newest_seen = exch.ts

        if file_count and not dry_run and newest_seen > watermark:
            advance_watermark(path.name, newest_seen)
        if file_count:
            per_file[path.name] = file_count

    return {"ok": True, "rollouts_found": len(rollouts),
            "exchanges_ingested": ingested, "per_file": per_file}


def main() -> int:
    p = argparse.ArgumentParser(
        description="Ingest Codex rollout transcripts into observation_queue.jsonl "
                    "(the Codex capture adapter, ROADMAP 6.8.3).")
    p.add_argument("--dry-run", action="store_true",
                   help="report what WOULD be ingested; write nothing, advance no watermark")
    p.add_argument("--status", action="store_true",
                   help="rollout/watermark counts only; does not parse any file")
    args = p.parse_args()

    if args.status:
        rollouts = find_rollouts()
        marks = read_watermark()
        print(f"Codex sessions dir : {SESSIONS_ROOT} "
              f"({'exists' if SESSIONS_ROOT.exists() else 'MISSING'})")
        print(f"rollout files       : {len(rollouts)}")
        print(f"watermarked files   : {len(marks)}")
        if not rollouts:
            print("\nNo rollouts found — capture from this host has produced nothing yet.")
        return 0

    result = run(dry_run=args.dry_run)
    label = "[dry-run] would ingest" if args.dry_run else "ingested"
    print(f"rollouts found      : {result['rollouts_found']}")
    print(f"{label:<20}: {result['exchanges_ingested']}")
    if result.get("reason"):
        print(f"reason              : {result['reason']}")
    for fname, n in result.get("per_file", {}).items():
        print(f"  {fname:<70} {n}")
    if result["exchanges_ingested"] == 0 and result["rollouts_found"] > 0:
        print("\n0 new exchanges — either everything is already watermarked, or every "
              "rollout is developer/tool-only content with no real user turn.")
    return 0


# =============================================================================
# SMOKE TESTS (offline — synthetic rollouts, temp dirs, no ~/.codex touched)
# =============================================================================

def _run_self_test() -> None:
    import tempfile

    print("=" * 70)
    print("  ingest_codex_sessions.py -- Smoke Tests")
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

    # --- strip_codex_wrapper ---
    check("T1 strips a known wrapper tag",
          strip_codex_wrapper("<environment_context>cwd=/x</environment_context>real") == "real")
    check("T2 leaves plain text untouched",
          strip_codex_wrapper("what is a broadcast join?") == "what is a broadcast join?")
    check("T3 a turn that is ONLY wrapper content strips to empty",
          strip_codex_wrapper("<recommended_plugins>list</recommended_plugins>").strip() == "")
    check("T4 does not eat unrelated angle brackets (e.g. pasted XML)",
          "<foo>bar</foo>" in strip_codex_wrapper("<foo>bar</foo>"))

    # --- _to_ist ---
    check("T5 UTC Z-suffix converts to +05:30",
          _to_ist("2026-07-15T10:47:43Z").endswith("+05:30"))
    check("T6 an unparseable timestamp passes through rather than raising",
          _to_ist("not-a-date") == "not-a-date")

    # --- _message_text ---
    check("T7 extracts input_text blocks",
          _message_text({"content": [{"type": "input_text", "text": "hello"}]}) == "hello")
    check("T8 joins multiple output_text blocks",
          _message_text({"content": [{"type": "output_text", "text": "a"},
                                     {"type": "output_text", "text": "b"}]}) == "a\nb")
    check("T9 non-text blocks (tool calls) are skipped, not stringified",
          _message_text({"content": [{"type": "function_call", "name": "x"}]}) == "")
    check("T10 a bare string content is passed through",
          _message_text({"content": "plain"}) == "plain")

    # --- _session_id_from_filename ---
    check("T11 extracts the uuid from a real rollout filename",
          _session_id_from_filename(Path(
              "rollout-2026-07-15T10-45-47-019f6433-da9c-7691-b1fd-e0fc193c3e7b.jsonl"))
          == "019f6433-da9c-7691-b1fd-e0fc193c3e7b")

    def _rec(**kw) -> str:
        return json.dumps(kw, ensure_ascii=False)

    def _msg(role: str, text: str, ts: str, kind: str = None) -> str:
        return _rec(type="response_item", timestamp=ts,
                    payload={"type": "message", "role": role,
                            "content": [{"type": kind or ("input_text" if role != "assistant"
                                                          else "output_text"), "text": text}]})

    with tempfile.TemporaryDirectory() as td:
        # --- T12-T16: iter_rollout_exchanges end to end ---
        rollout = Path(td) / "rollout-2026-01-01T00-00-00-aaaaaaaa-0000-0000-0000-000000000000.jsonl"
        lines = [
            _rec(type="session_meta", timestamp="2026-01-01T00:00:00Z",
                payload={"session_id": "aaaaaaaa-0000-0000-0000-000000000000",
                         "cwd": "/repo"}),
            _msg("developer", "you are codex, a system prompt", "2026-01-01T00:00:01Z"),
            _msg("user", "<environment_context>cwd</environment_context>", "2026-01-01T00:00:02Z"),
            _msg("user", "explain the shuffle write", "2026-01-01T00:00:03Z"),
            _msg("assistant", "Shuffle write spills partitions to disk", "2026-01-01T00:00:04Z"),
            _msg("assistant", " before the next stage reads them.", "2026-01-01T00:00:05Z"),
            _msg("user", "and AQE?", "2026-01-01T00:00:06Z"),
            _msg("assistant", "AQE re-plans at runtime using shuffle stats.",
                "2026-01-01T00:00:07Z"),
        ]
        rollout.write_text("\n".join(lines) + "\n", encoding="utf-8")

        exchanges = list(iter_rollout_exchanges(rollout, "Test Thread"))
        check("T12 wrapper-only user turn produces NO exchange, and developer is skipped",
              len(exchanges) == 2, str(len(exchanges)))
        check("T13 exchanges are in chronological order",
              exchanges[0].ts < exchanges[1].ts, str([e.ts for e in exchanges]))
        check("T14 multi-block assistant output is joined",
              "spills partitions" in exchanges[0].assistant_summary
              and "next stage reads" in exchanges[0].assistant_summary,
              exchanges[0].assistant_summary)
        check("T15 session_id and cwd come from session_meta, thread_name from the caller",
              exchanges[0].session_id == "aaaaaaaa-0000-0000-0000-000000000000"
              and exchanges[0].cwd == "/repo" and exchanges[0].thread_name == "Test Thread",
              str(exchanges[0]))
        check("T16 timestamps converted to IST",
              exchanges[0].ts.endswith("+05:30"), exchanges[0].ts)

        # --- T17: a torn/corrupt line does not abort the file ---
        rollout2 = Path(td) / "rollout-2026-01-02T00-00-00-bbbbbbbb-0000-0000-0000-000000000000.jsonl"
        rollout2.write_text(
            _rec(type="session_meta", timestamp="2026-01-02T00:00:00Z",
                payload={"session_id": "b", "cwd": "/repo"}) + "\n"
            + "{not json at all\n"
            + _msg("user", "does this still work", "2026-01-02T00:00:01Z") + "\n"
            + _msg("assistant", "yes, the good line survives", "2026-01-02T00:00:02Z") + "\n",
            encoding="utf-8")
        ex2 = list(iter_rollout_exchanges(rollout2, "T2"))
        check("T17 a corrupt line is skipped, the surrounding good lines are not lost",
              len(ex2) == 1 and "still work" in ex2[0].user_text, str(ex2))

        # --- T18-T20: watermark (append-only, per-file, torn-line healing) ---
        wm = Path(td) / ".wm.jsonl"
        advance_watermark("fileA.jsonl", "2026-01-01T00:00:05+05:30", wm)
        advance_watermark("fileB.jsonl", "2026-01-02T00:00:00+05:30", wm)
        advance_watermark("fileA.jsonl", "2026-01-01T00:00:01+05:30", wm)  # older, must not win
        marks = read_watermark(wm)
        check("T18 the watermark folds to the NEWEST per file",
              marks == {"fileA.jsonl": "2026-01-01T00:00:05+05:30",
                        "fileB.jsonl": "2026-01-02T00:00:00+05:30"}, str(marks))
        torn = Path(td) / ".torn.jsonl"
        torn.write_text('{"file":"x.jsonl","ts":"2026-01-01T00:00:00+05:30"}',
                        encoding="utf-8")  # no trailing newline
        advance_watermark("y.jsonl", "2026-01-02T00:00:00+05:30", torn)
        check("T19 appending after a line with no newline does not destroy it",
              read_watermark(torn) == {"x.jsonl": "2026-01-01T00:00:00+05:30",
                                       "y.jsonl": "2026-01-02T00:00:00+05:30"},
              str(read_watermark(torn)))
        check("T20 a missing watermark file reads as empty, not an error",
              read_watermark(Path(td) / "nope.jsonl") == {})

        # --- T21-T24: run() end to end, and its idempotency ---
        sessions_dir = Path(td) / "sessions" / "2026" / "01" / "01"
        sessions_dir.mkdir(parents=True)
        real_rollout = sessions_dir / rollout.name
        real_rollout.write_text(rollout.read_text(encoding="utf-8"), encoding="utf-8")

        queue = Path(td) / "queue.jsonl"
        run_wm = Path(td) / "run_watermark.jsonl"
        import ingest_codex_sessions as mod
        orig_sessions, orig_wm = mod.SESSIONS_ROOT, mod.WATERMARK_PATH
        orig_append = mod.append_observation
        captured: List[Dict[str, Any]] = []
        mod.SESSIONS_ROOT, mod.WATERMARK_PATH = Path(td) / "sessions", run_wm
        mod.append_observation = lambda obs, **kw: (
            captured.append(obs), orig_append(obs, queue_path=queue))[-1]
        try:
            result = mod.run(dry_run=False)
            check("T21 run() ingests both real exchanges from the synthetic session",
                  result["exchanges_ingested"] == 2, str(result))
            check("T22 the queue actually received the records",
                  queue.exists() and len(queue.read_text().splitlines()) == 2)
            check("T23 chat_label reflects the Codex thread_name, not just cwd basename",
                  all(c.get("chat_label") for c in captured), str(captured))
            check("T23b every ingested row names its host, so parse_ledger never guesses",
                  all(c.get("host") == "codex" for c in captured), str(captured))

            result2 = mod.run(dry_run=False)
            check("T24 a second run ingests 0 — the watermark actually prevents re-ingestion",
                  result2["exchanges_ingested"] == 0, str(result2))
        finally:
            mod.SESSIONS_ROOT, mod.WATERMARK_PATH = orig_sessions, orig_wm
            mod.append_observation = orig_append

        # --- T25: no sessions directory at all -> honest zero, not a crash ---
        mod.SESSIONS_ROOT = Path(td) / "does_not_exist"
        try:
            empty_result = mod.run(dry_run=False)
            check("T25 a missing sessions dir reports WHY, not a silent/crashed zero",
                  empty_result["rollouts_found"] == 0 and "reason" in empty_result,
                  str(empty_result))
        finally:
            mod.SESSIONS_ROOT = orig_sessions

    total = passed + len(failed)
    print("-" * 70)
    print(f"  {passed}/{total} passed")
    if failed:
        for name in failed:
            print(f"    - {name}")
    print("=" * 70)
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        _run_self_test()
    else:
        raise SystemExit(main())
