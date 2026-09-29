"""
capture.py — Per-Turn Experience Capture (core organ; Portable Mind layer).

LAYER: Agent (Cognitive Synthesis Loop — capture)

Import with:
    from jarvis_core.agent.capture import (
        capture_stop_event, extract_turn, append_observation,
        redact, strip_harness_blocks, guess_domain,
    )

=============================================================================
THE BIG PICTURE
=============================================================================

This logic used to live INSIDE scripts/hooks/capture_turn.py — a Claude Code
Stop-hook on one machine. That made JARVIS's most fundamental sense (capturing
its own experience) a property of one harness on one laptop: the exact
"consciousness is a parasite on the host" failure the Portable Mind audit named
(KB L320/L321). Per the Consciousness Portability Contract, every awareness
feature ships as CORE ORGAN + thin host-adapter:

    organ   (this file, jarvis_core — committed, portable, tested)
    adapter (scripts/hooks/capture_turn.py — Claude Code Stop hook, ~40 lines)
    future  (Antigravity-native limb, server daemon — same organ, new adapters)

The organ owns: transcript parsing (Claude Code JSONL today; the record shapes
are parameterized enough that another runtime's adapter can pre-shape records),
harness-wrapper stripping, secret redaction, domain hinting, model stamping
(runtime SELF-state), and the flock-guarded queue append.

stdlib-only. No model loads, no network — adapters call this on hot paths.

=============================================================================
THE FLOW
=============================================================================

STEP 1: adapter receives a host event (Stop hook stdin today) and calls
        capture_stop_event(event).
        |
STEP 2: extract_turn(transcript) — last REAL user message (skipping sidechains,
        tool_results, and pure harness-wrapper turns) + assistant summary + the
        model that produced the turn.
        |
STEP 3: strip harness wrappers -> redact secrets -> heuristic signals
        (prompt_len, correction markers, keyword domain HINT — the embedding
        classifier re-derives the real domain at synthesis time).
        |
STEP 4: append ONE JSON line to observation_queue.jsonl under flock.
        Any failure returns None — an adapter must never break a user's turn.

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

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # standalone-run safety
from jarvis_core.agent.client_infra import mask as mask_client_infra  # noqa: E402
from jarvis_core.config import DATA_ROOT  # noqa: E402

_IST = timezone(timedelta(hours=5, minutes=30))
QUEUE_PATH = Path(DATA_ROOT) / "observation_queue.jsonl"

# NO CAP on either side (user directive, 2026-09-18). The history stays because
# it records what the ceilings cost, and therefore why re-adding one is a
# regression rather than a tidy-up: at 2000/400 (before 2026-08-19) 335 of 466
# assistant summaries (72%) hit the ceiling exactly; at 2000 (before
# 2026-09-18) 268 of 1420 (18.9%) still did. A cap cannot preserve WHY a
# decision was reached, only that one was — and a row cut mid-thought is the
# single failure this queue exists to prevent.
#
# Two facts make unbounded correct here rather than reckless. FIRST, this queue
# is a DERIVED, FLATTENED view — one row per turn, user text plus joined
# assistant text — so it is not the complete record even with no cap at all:
# tool calls, tool results and thinking blocks were never in it. The complete
# record is Claude Code's own transcript, which extract_turn reads and which is
# already untruncated on disk. SECOND, build_observation — the path every
# non-hook adapter uses — never truncated, so Codex and Antigravity turns have
# always been stored whole. Capping only here made the host with the richest
# transcripts the only one that lost text.
#
# COST, measured before the change: 11 MB across 1424 rows. This file is
# git-TRACKED, pushed, and merge=union across three agents, so if size ever
# becomes a sync problem the fix is to prune or externalize OLD rows — not to
# re-truncate new ones, which loses the reasoning tail permanently.

# --- Secret redaction (same classes as react.py R1/M11 + correlation _scrub) ---
_REDACTORS = [
    re.compile(r"github_pat_[A-Za-z0-9_]+"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]+"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\b[A-Fa-f0-9]{40,}\b"),
    re.compile(r"\b[A-Za-z0-9+/]{50,}={0,2}\b"),
]

_CORRECTION_MARKERS = re.compile(
    r"\b(no,|actually|wait\b|that'?s wrong|not what|instead|nope|incorrect|"
    r"you misunderstood|re-?do|revert)\b",
    re.IGNORECASE,
)

# Coarse keyword HINT only — the embedding nearest-prototype classifier
# (domain_classifier.py) re-derives the authoritative domain at synthesis time.
_DOMAIN_KEYWORDS = {
    "data-engineering": ["spark", "warehouse", "pyspark", "sql", "etl", "dbt", "databricks", "airflow"],
    "finance": ["portfolio", "stock", "sip", "groww", "nse", "investment", "rebalance"],
    "ai-ml": ["transformer", "embedding", "lora", "fine-tune", "gradient", "attention", "rag"],
    "jarvis-build": ["jarvis_core", "react.py", "memory_manager", "tool.py", "stage 3", "react loop"],
}

# The classifier declining, as a value. NOT "general": see guess_domain's docstring
# for the 309-record measurement that made this necessary. Mirrors
# agent/domain_classifier.UNKNOWN — one vocabulary across both classifiers.
UNKNOWN_DOMAIN = "unknown"

# Precompiled per keyword, with boundaries that respect the keywords' own shapes.
# A plain \b fails on the ones containing punctuation ("react.py" would match
# "react-py"), so the dot is escaped and \b is only applied where the edge
# character is a word character — otherwise \b there would never match.
def _kw_pattern(keyword: str) -> "re.Pattern[str]":
    escaped = re.escape(keyword)
    left = r"\b" if keyword[:1].isalnum() or keyword[:1] == "_" else ""
    right = r"\b" if keyword[-1:].isalnum() or keyword[-1:] == "_" else ""
    return re.compile(left + escaped + right)


_DOMAIN_KEYWORD_RE = {kw: _kw_pattern(kw)
                      for kws in _DOMAIN_KEYWORDS.values() for kw in kws}

# Harness wrapper blocks: injected by the host into user turns, NOT user-typed.
# Conservative KNOWN-tag list — never a generic "<...>" strip (would eat pasted code).
_HARNESS_TAGS = (
    "ide_opened_file", "ide_selection", "system-reminder", "task-notification",
    "local-command-caveat", "local-command-stdout", "command-name",
    "command-message", "command-args", "user-prompt-submit-hook",
    # Codex automation envelope: a scheduled run replays stored instructions
    # inside <heartbeat>; nobody typed them at that moment.
    "heartbeat", "automation_id",
)
_HARNESS_PAIRED = re.compile(
    r"<(" + "|".join(_HARNESS_TAGS) + r")\b[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_HARNESS_STANDALONE = re.compile(
    r"</?(" + "|".join(_HARNESS_TAGS) + r")\b[^>]*/?>", re.IGNORECASE)


# =============================================================================
# Part 1: TEXT HYGIENE (pure functions)
# =============================================================================

def redact(text: str) -> str:
    if not text:
        return text
    out = text
    for rx in _REDACTORS:
        out = rx.sub("[REDACTED]", out)
    return out


def strip_harness_blocks(text: str) -> str:
    """Remove host-injected wrapper blocks, leaving only user-typed content."""
    if not text:
        return text
    out = _HARNESS_PAIRED.sub(" ", text)
    out = _HARNESS_STANDALONE.sub(" ", out)
    return out


def guess_domain(cwd: str, blob: str) -> str:
    """A FAST, NON-AUTHORITATIVE domain hint. Returns UNKNOWN when unsure.

    This runs inside the Stop hook on every turn of every chat, so it must stay
    stdlib-only with no model load. It is therefore a keyword matcher, and a
    keyword matcher will always be imprecise. Two changes on 2026-09-08 make that
    imprecision harmless instead of corrosive:

    1. WORD BOUNDARIES. It previously used unanchored `in`, so `nse` matched
       inside "respo(nse)" — 52 of 52 `nse` hits were spurious, and the single
       life-state insight that ever cleared the surfacing floor cited
       "finance volume 0->4", which was almost certainly this. `rag` matched
       "sto(rag)e"/"ave(rag)e" (26 of 28 spurious), `lora` matched
       "exp(lora)tion", `sql` matched "sqlite". Requiring boundaries killed that
       whole class; ~15% of all 583 records were mislabelled by it.

    2. IT ABSTAINS. It used to seed `best="general"` and return that on zero
       matches, so "genuinely general" and "I have no idea" were the SAME token.
       Measured: all 309 "general" records had zero keyword hits — every one was
       a shrug wearing the name of a real category, which is why 99 days of bad
       labels went unnoticed. UNKNOWN is now returned, so abstention is countable.

    THE AUTHORITATIVE LABEL IS NOT THIS. It is the embedding classifier's output
    in jarvis_data/domain_labels.jsonl, which carries a score and is checked
    against a gold set by scripts/check_projections.py. Treat this as a hint for
    anything that cannot wait for that projection, and never as ground truth.
    """
    hay = (cwd + " " + blob).lower()
    best, best_hits = UNKNOWN_DOMAIN, 0
    for domain, kws in _DOMAIN_KEYWORDS.items():
        hits = sum(1 for k in kws if _DOMAIN_KEYWORD_RE[k].search(hay))
        if hits > best_hits:
            best, best_hits = domain, hits
    return best


def ist_now_iso() -> str:
    return datetime.now(_IST).isoformat(timespec="seconds")


# =============================================================================
# Part 2: TRANSCRIPT PARSING (Claude Code JSONL record shapes)
# =============================================================================

def _block_text(content: Any) -> str:
    """Concatenate the 'text' blocks of a message.content (list or str)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text", ""))
        return "\n".join(p for p in parts if p)
    return ""


def is_real_user_text(rec: Dict[str, Any]) -> bool:
    """True for a genuine user-typed message: not a tool_result, not sidechain,
    and NOT just harness wrapper blocks (a wrapper-only turn has no user content
    once stripped, so the caller skips past it to the real turn)."""
    if rec.get("type") != "user" or rec.get("isSidechain"):
        return False
    content = (rec.get("message") or {}).get("content")
    return bool(strip_harness_blocks(_block_text(content)).strip())


def extract_turn(transcript_path: str) -> Optional[Dict[str, str]]:
    """{user_text, assistant_summary, model} for the most recent main-thread
    turn, or None. `model` = the brain that produced the turn (SELF-state)."""
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

    last_user_idx = -1
    for i in range(len(records) - 1, -1, -1):
        if is_real_user_text(records[i]):
            last_user_idx = i
            break
    if last_user_idx == -1:
        return None

    user_text = strip_harness_blocks(
        _block_text((records[last_user_idx].get("message") or {}).get("content"))
    ).strip()

    assistant_parts: List[str] = []
    model = ""
    for rec in records[last_user_idx + 1:]:
        if rec.get("type") == "assistant" and not rec.get("isSidechain"):
            t = _block_text((rec.get("message") or {}).get("content"))
            if t:
                assistant_parts.append(t)
            m = (rec.get("message") or {}).get("model") or ""
            if m and m != "<synthetic>":
                model = m  # keep the LAST real model of the turn
    if not model:
        for rec in reversed(records[:last_user_idx + 1]):
            if rec.get("type") == "assistant" and not rec.get("isSidechain"):
                m = (rec.get("message") or {}).get("model") or ""
                if m and m != "<synthetic>":
                    model = m
                    break

    return {
        "user_text": user_text,
        "assistant_summary": "\n".join(assistant_parts),
        "model": model,
    }


# =============================================================================
# Part 3: OBSERVATION ASSEMBLY + QUEUE APPEND
# =============================================================================

def build_observation(
    event: Dict[str, Any], turn: Dict[str, str], cwd: str,
    ts: Optional[str] = None, host: str = "",
) -> Optional[Dict[str, Any]]:
    """One redacted queue record, or None if nothing capturable.

    `ts` defaults to now (live capture: the Stop hook fires as the turn ends,
    so "now" IS correct). A second-host ADAPTER INGESTING HISTORICAL
    transcripts (agent 6.8.3 — e.g. scripts/ingest_codex_sessions.py reading
    already-completed rollouts from a prior day) must pass the turn's OWN
    timestamp instead, or every backfilled turn stamps in at ingestion time —
    which corrupts every timestamp-ordered consumer downstream: recall.py's
    day-by-day grouping, tension.py's "only the past can be a prior" filter,
    and the domain-label projection's (ts, session_id) key.

    `host` names the agent the owner was talking to (claude / codex /
    antigravity / jarvis). The owner's rule (2026-09-28) is that the agent in
    the chat parses its own turns, so parse_ledger must know whose turn this
    is; written here it is never guessed from cwd or session-id shape.
    """
    # The queue is tracked in git: mask the client's infrastructure identifiers
    # before a pasted pipeline reaches it (specialists keep client CODE by the
    # owner's decision; only the environment names are pseudonymised).
    user_text = mask_client_infra(redact(turn.get("user_text", "")))[0]
    assistant_summary = mask_client_infra(redact(turn.get("assistant_summary", "")))[0]
    if not user_text.strip():
        return None
    obs: Dict[str, Any] = {
        "ts": ts or ist_now_iso(),
        "session_id": event.get("session_id", ""),
        "machine": os.environ.get(
            "JARVIS_MACHINE", os.uname().nodename if hasattr(os, "uname") else "unknown"),
        "model": turn.get("model", ""),
        "cwd": cwd,
        "chat_label": Path(cwd).name or "unknown",
        "user_text": user_text,
        "assistant_summary": assistant_summary,
        "tokens": {
            "input": event.get("input_tokens"),
            "output": event.get("output_tokens"),
        },
        "heuristic_signals": {
            "prompt_len": len(user_text),
            "has_correction_markers": bool(_CORRECTION_MARKERS.search(user_text)),
            "domain_guess": guess_domain(cwd, user_text + " " + assistant_summary),
        },
    }
    if host:
        obs["host"] = host
    return obs


def append_observation(record: Dict[str, Any], queue_path: Path = QUEUE_PATH) -> None:
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False)
    with open(queue_path, "a+", encoding="utf-8") as f:
        if _HAS_FCNTL:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            # Heal a missing terminator before appending. A process killed
            # mid-write leaves a line with no "\n"; the next append then lands
            # on that same line, so the torn record destroys the GOOD record
            # written after it instead of only itself. kb_append.py has done
            # this since it shipped; this call site had not copied it.
            f.write(("" if _ends_with_newline(f) else "\n") + line + "\n")
            f.flush()
        finally:
            if _HAS_FCNTL:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _ends_with_newline(handle: Any) -> bool:
    """True when the file is empty or already ends in a newline."""
    try:
        handle.seek(0, 2)
        if handle.tell() == 0:
            return True
        handle.seek(handle.tell() - 1)
        return handle.read(1) == "\n"
    except (OSError, ValueError):
        return True


def capture_stop_event(event: Dict[str, Any], queue_path: Path = QUEUE_PATH,
                       host: str = "") -> Optional[Dict[str, Any]]:
    """The one-call organ entry an adapter uses. Returns the appended record,
    or None (nothing capturable / loop guard). NEVER raises."""
    try:
        if event.get("stop_hook_active"):
            return None
        cwd = event.get("cwd", os.getcwd())
        transcript_path = event.get("transcript_path", "")
        turn = extract_turn(transcript_path) if transcript_path else None
        if turn is None:
            return None
        record = build_observation(event, turn, cwd, host=host)
        if record is None:
            return None
        append_observation(record, queue_path)
        return record
    except Exception:
        return None


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS (moved with the logic from capture_turn.py)
# =============================================================================

def _run_self_test() -> None:
    import tempfile

    print("=" * 70)
    print("  capture.py -- Smoke Tests (core organ)")
    print("=" * 70)
    passed = 0
    failed: List[str] = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        nonlocal passed
        if cond:
            passed += 1
        else:
            failed.append(f"FAIL: {name}" + (f" ({hint})" if hint else ""))

    # --- harness stripping ---
    check("T1 paired ide_opened_file stripped, real question kept",
          strip_harness_blocks(
              "<ide_opened_file>The user opened /home/x/JARVIS/y.py</ide_opened_file>\nwhat is AQE?"
          ).strip() == "what is AQE?")
    check("T2 task-notification-only -> empty",
          strip_harness_blocks(
              "<task-notification><task-id>w19</task-id></task-notification>").strip() == "")
    check("T3 system-reminder stripped mid-text",
          (lambda s: "actual question" in s and "noise" not in s)(
              strip_harness_blocks("hi <system-reminder>noise here</system-reminder> actual question")))
    check("T3c a Codex automation heartbeat is an envelope, not owner text",
          strip_harness_blocks("<heartbeat>\r\n  <automation_id>daily-x</automation_id>\r\n"
                               "  <instructions>\r\nrefresh the desk\r\n  </instructions>\r\n"
                               "</heartbeat>\n").strip() == "")
    check("T4 plain text untouched", strip_harness_blocks("hello world").strip() == "hello world")
    check("T5 code with < and > NOT stripped",
          strip_harness_blocks("if x < y and a > b: return [i for i in xs]")
          == "if x < y and a > b: return [i for i in xs]")
    check("T6 command wrappers stripped",
          strip_harness_blocks("<command-name>/next</command-name><command-args></command-args>").strip() == "")

    # --- real-user detection ---
    wrap = {"type": "user", "message": {"content": [
        {"type": "text", "text": "<task-notification><task-id>w1</task-id></task-notification>"}]}}
    real = {"type": "user", "message": {"content": [
        {"type": "text", "text": "<ide_opened_file>f /JARVIS/z</ide_opened_file>\nexplain shuffle partitions"}]}}
    tres = {"type": "user", "message": {"content": [{"type": "tool_result", "content": "out"}]}}
    check("T7 pure-wrapper user msg is NOT real", is_real_user_text(wrap) is False)
    check("T8 wrapper+question IS real", is_real_user_text(real) is True)
    check("T9 tool_result is not real", is_real_user_text(tres) is False)

    with tempfile.TemporaryDirectory() as td:
        # --- extract_turn: skip trailing wrapper, strip inline wrapper ---
        tp = Path(td) / "t.jsonl"
        recs = [real,
                {"type": "assistant", "message": {"model": "claude-fable-5",
                                                  "content": [{"type": "text", "text": "Shuffle partitions are..."}]}},
                wrap]
        tp.write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
        turn = extract_turn(str(tp))
        check("T10 extract finds real question past trailing wrapper",
              turn is not None and turn["user_text"].strip() == "explain shuffle partitions", str(turn))
        check("T11 model stamped", turn is not None and turn["model"] == "claude-fable-5")

        # --- synthetic fallback ---
        tp3 = Path(td) / "t3.jsonl"
        recs3 = [
            {"type": "assistant", "message": {"model": "claude-opus-4-8",
                                              "content": [{"type": "text", "text": "earlier"}]}},
            {"type": "user", "message": {"content": [{"type": "text", "text": "quick q"}]}},
            {"type": "assistant", "message": {"model": "<synthetic>",
                                              "content": [{"type": "text", "text": "interim"}]}},
        ]
        tp3.write_text("\n".join(json.dumps(r) for r in recs3) + "\n", encoding="utf-8")
        turn3 = extract_turn(str(tp3))
        check("T12 synthetic-only falls back to last real model",
              turn3 is not None and turn3["model"] == "claude-opus-4-8", str(turn3))

        # --- redaction + full organ path ---
        tp4 = Path(td) / "t4.jsonl"
        recs4 = [
            {"type": "user", "message": {"content": [
                {"type": "text", "text": "my token is github_pat_ABCDEFGHIJKLMNOPQRSTUV please use it for spark etl"}]}},
            {"type": "assistant", "message": {"model": "claude-fable-5",
                                              "content": [{"type": "text", "text": "Done."}]}},
        ]
        tp4.write_text("\n".join(json.dumps(r) for r in recs4) + "\n", encoding="utf-8")
        q = Path(td) / "queue.jsonl"
        event = {"session_id": "s1", "transcript_path": str(tp4), "cwd": "/home/x/proj",
                 "stop_hook_active": False}
        rec = capture_stop_event(event, queue_path=q)
        check("T13 organ captures end-to-end", rec is not None and q.exists())
        line = json.loads(q.read_text().splitlines()[0])
        check("T14 secret REDACTED in queue", "github_pat_" not in line["user_text"]
              and "[REDACTED]" in line["user_text"])
        check("T15 domain hint + model + machine stamped",
              line["heuristic_signals"]["domain_guess"] == "data-engineering"
              and line["model"] == "claude-fable-5" and bool(line["machine"]), str(line))

        # --- T15b-T15d: the domain hint's two 2026-09-08 guarantees ---
        # These pin the change that killed 15% of all historical mislabels. A
        # regression here is silent and corrupts everything downstream of the
        # label, so it is asserted rather than trusted.
        spurious = {
            "the response was fine": "nse inside 'respo(nse)' — 52 of 52 real hits",
            "storage and average leverage": "rag inside 'sto(rag)e'/'ave(rag)e'",
            "exploration of colorado": "lora inside 'exp(lora)tion'",
            "we use sqlite locally": "sql inside 'sqlite'",
            "a sparkline chart": "spark inside 'sparkline'",
        }
        bad = {t: guess_domain("", t) for t in spurious
               if guess_domain("", t) != UNKNOWN_DOMAIN}
        check("T15b substring false positives all abstain now", not bad, str(bad))
        check("T15c a genuinely unrelated turn abstains, it is not called 'general'",
              guess_domain("", "what time should we meet for lunch") == UNKNOWN_DOMAIN)
        real = {
            "explain spark AQE skew in databricks": "data-engineering",
            "rebalance my SIP portfolio on the NSE": "finance",
            "LoRA fine-tune a transformer": "ai-ml",
            "the jarvis_core react loop": "jarvis-build",
        }
        missed = {t: guess_domain("", t) for t, want in real.items()
                  if guess_domain("", t) != want}
        check("T15d real matches still classify — boundaries did not overcorrect",
              not missed, str(missed))

        # --- guards ---
        check("T16 stop_hook_active -> None",
              capture_stop_event({"stop_hook_active": True}, queue_path=q) is None)
        check("T17 missing transcript -> None",
              capture_stop_event({"transcript_path": str(Path(td) / "no.jsonl"), "cwd": td},
                                 queue_path=q) is None)
        check("T18 organ never raises on junk event",
              capture_stop_event({"transcript_path": 123}, queue_path=q) is None)

        # --- T19-T20: build_observation's ts override (agent 6.8.3 — a second
        # host ingesting HISTORICAL transcripts must be able to backfill the
        # turn's OWN time, not the ingest-time "now") ---
        historical_ts = "2026-01-15T09:30:00+05:30"
        obs = build_observation(
            {"session_id": "s9"}, {"user_text": "old turn", "assistant_summary": "old answer"},
            "/some/repo", ts=historical_ts)
        check("T19 an explicit ts is used verbatim, not overwritten with now",
              obs is not None and obs["ts"] == historical_ts, str(obs and obs["ts"]))
        obs_default = build_observation(
            {"session_id": "s9"}, {"user_text": "new turn", "assistant_summary": "new answer"},
            "/some/repo")
        check("T20 omitting ts still defaults to live capture's now (unchanged behavior)",
              obs_default is not None and obs_default["ts"] != historical_ts
              and obs_default["ts"].startswith("20"), str(obs_default and obs_default["ts"]))
        check("T21 an explicit host is recorded; omitting it writes no host key",
              build_observation({"session_id": "s"}, {"user_text": "x"}, "/r", host="codex")["host"]
              == "codex" and "host" not in obs_default)
        q21 = Path(td) / "q21.jsonl"
        rec21 = capture_stop_event(dict(event), queue_path=q21, host="claude")
        check("T22 capture_stop_event threads host into the queue row",
              rec21 is not None and json.loads(q21.read_text().splitlines()[0]).get("host") == "claude")

    total = passed + len(failed)
    print(f"\n  Passed: {passed}/{total}")
    if failed:
        for f_ in failed:
            print(f"  {f_}")
        print("=" * 70)
        raise SystemExit(1)
    print(f"  All {total} capture organ smoke tests passed.")
    print("=" * 70)


if __name__ == "__main__":
    _run_self_test()
