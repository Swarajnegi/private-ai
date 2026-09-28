"""
recall.py — Cross-Chat Activity Recall (Stage 3.5 — the missing recall limb).

LAYER: Agent (Cognitive Synthesis Loop — recall)

Import with:
    from jarvis_core.agent.recall import ActivityRecaller

=============================================================================
THE BIG PICTURE
=============================================================================

The Stop hook captures every turn of every chat into observation_queue.jsonl.
But until now NOTHING read it back into a live chat — so when a fresh chat was
asked "what was I up to?", it fell back to `git log`. Git is a PROXY for work
(only what got committed), not the work itself — and leaning on it is exactly
the "not private AI" failure the user called out: the real per-prompt activity
was sitting local the whole time, unread.

This is the recall limb: it reads the ACTUAL capture queue (local, per-prompt,
across ALL chats — never git) and renders a compact day-by-day activity digest.
A SessionStart hook injects it into every chat so each one opens already aware
of what happened across the others — no asking, no git.

stdlib-only (json + datetime + re): the SessionStart hook that calls it must stay
sub-second and never load a model. Coarse stored `domain_guess` is fine for a
digest; the topic snippets carry the real "what was I doing" signal.

=============================================================================
THE FLOW
=============================================================================

STEP 1: stream observation_queue.jsonl, window-bounded by timestamp.
        |
STEP 2: group turns by IST calendar day; per day tally turn count + domain mix,
        and pick ONE representative message per chat: the first turn that is
        mostly the owner's own prose (harness envelopes, auto-approval
        transcripts, compaction summaries, bare image markers skipped).
        |
STEP 3: render a source-labeled markdown digest (most-recent day first).
        Every selected message appears WHOLE — which turns to show is a
        selection policy; cutting the ones shown is not allowed (owner
        directive 2026-09-28: no truncation anywhere).

=============================================================================
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # standalone-run safety
from jarvis_core.config import DATA_ROOT  # noqa: E402

_IST = timezone(timedelta(hours=5, minutes=30))
_QUEUE_PATH = Path(DATA_ROOT) / "observation_queue.jsonl"
# COMMITTED artifact (like cognitive_profile.md): the distilled cross-chat
# experience that SYNCS to other machines.
#
# CORRECTED 2026-09-10: this comment (and the near-identical header line
# _write_digest emits into the file itself) used to claim "the raw queue
# stays local". False — observation_queue.jsonl IS tracked and pushed
# (confirmed: `git check-ignore` exits 1 on it), and has been since it was
# committed with the rest of Stage 6's work. The digest is still worth
# having: it is the DISTILLED, 7-day, cross-machine-readable form, and it is
# what a machine with no local queue (Antigravity; now Codex, until its
# capture adapter lands) reads at boot per js-workspace-rule.md. But the
# reason to keep it is convenience and format, not confidentiality — same
# prose-vs-code drift class as KB 548/CLAUDE.md:123 (the ChromaDB claim).
_DIGEST_PATH = Path(DATA_ROOT) / "activity_digest.md"

_DEFAULT_DAYS = 7
_WEEKDAY = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
# A chat is represented by its first turn with this much owner prose (the
# opening request usually states what the chat is for); failing that, by its
# wordiest turn, provided it clears the floor that rules out "ok"/"continue".
_SUBSTANTIVE_PROSE_CHARS = 40
_MIN_PROSE_CHARS = 12
# A turn whose owner prose is under half its text is mostly a paste or a log;
# another turn from the same chat describes the work better.
_MIN_PROSE_SHARE = 0.5

# Host-injected blocks. Removed WITH their bodies: a task-notification's body
# is the harness talking, not the owner.
_HARNESS_TAGS = (
    r"ide_opened_file|ide_selection|system-reminder|task-notification|"
    r"local-command-[a-z]+|command-[a-z]+|user-prompt-submit-hook|"
    r"codex_internal_context|in-app-browser-context|realtime_delegation|"
    r"turn_aborted|heartbeat|automation_id|automation|"
    r"send_user_message_question_reply|environment_context|user_instructions|"
    r"INSTRUCTIONS|image"
)
_HARNESS_BLOCK = re.compile(r"<(" + _HARNESS_TAGS + r")\b[^>]*>.*?</\1>",
                            re.IGNORECASE | re.DOTALL)
_WRAP = re.compile(r"</?(" + _HARNESS_TAGS + r")\b[^>]*/?>", re.IGNORECASE)
# Whole-turn envelopes: an automated reviewer's transcript, a context-compaction
# summary, a skill body, an interrupt notice. None of it was typed by the owner.
_ENVELOPE_OPENERS = (
    "the following is the codex agent history",
    "this session is being continued from a previous conversation",
    "base directory for this skill",
    "[request interrupted",
    "your previous response had no visible output",
    "# agents.md instructions for",
)
_MARKER_LINE = re.compile(
    r"^\s*\[(?:image[^\]]*|external unsupported block[^\]]*)\]\s*$",
    re.IGNORECASE | re.MULTILINE)
_PASTED = re.compile(r"<pasted_content\b[^>]*>.*?</pasted_content[^>]*>",
                     re.IGNORECASE | re.DOTALL)
_FENCED = re.compile(r"```.*?```", re.DOTALL)
_LOG_LINE = re.compile(
    r"^\s*(?:Traceback|File \"|at |\$ |PS [A-Z]:|>>>|\d{4}-\d{2}-\d{2}[T ]\d{2}:"
    r"|\[\d{2}:\d{2}|(?:INFO|WARN|WARNING|ERROR|DEBUG)\b|[{}\[\]])")
_FILES_REQUEST = re.compile(r"^## My request[^\n]*:[ \t]*$", re.MULTILINE)


def _parse_instant(ts: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None
    return dt.replace(tzinfo=_IST) if dt.tzinfo is None else dt


def _iter_queue(path: Path) -> Iterator[Dict[str, Any]]:
    if not path.exists():
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _owner_message(raw: str) -> str:
    """The owner's message with host envelopes removed, or "" when the whole
    turn is an envelope. Nothing the owner typed is removed."""
    text = raw or ""
    if text.lstrip().lower().startswith(_ENVELOPE_OPENERS):
        return ""
    text = _HARNESS_BLOCK.sub(" ", text)
    text = _WRAP.sub(" ", text)
    request = _FILES_REQUEST.search(text)
    if request:
        # Codex prefixes attachments as "# Files mentioned by the user: ...
        # ## My request:" — the file list is the host's, the request is the owner's.
        text = text[request.end():]
    text = _MARKER_LINE.sub("", text)
    lines = [ln.rstrip() for ln in text.strip().splitlines()]
    return "\n".join(ln for ln in lines if ln.strip())


def _prose_chars(message: str) -> int:
    """Characters of the message that read as the owner writing, not pasting."""
    body = _FENCED.sub("", _PASTED.sub("", message))
    return sum(len(ln.strip()) for ln in body.splitlines() if not _LOG_LINE.match(ln))


class _ChatPick:
    """Streaming choice of the one turn that best says what a chat was about
    on a day: its EARLIEST mostly-prose turn, else its wordiest turn. Holds one
    message per chat, never the chat's whole history."""

    __slots__ = ("dt", "message", "prose", "substantive")

    def __init__(self) -> None:
        self.dt: Optional[datetime] = None
        self.message = ""
        self.prose = 0
        self.substantive = False

    def offer(self, dt: datetime, message: str) -> None:
        prose = _prose_chars(message)
        substantive = (prose >= _SUBSTANTIVE_PROSE_CHARS
                       and prose >= _MIN_PROSE_SHARE * len(message))
        if substantive:
            # The queue is union-merged across machines, so file order is not
            # time order; "earliest" is decided by timestamp.
            if not self.substantive or (self.dt is not None and dt < self.dt):
                self.dt, self.message, self.prose, self.substantive = dt, message, prose, True
        elif not self.substantive and prose > self.prose:
            self.dt, self.message, self.prose = dt, message, prose

    @property
    def chosen(self) -> Optional[str]:
        return self.message if self.prose >= _MIN_PROSE_CHARS else None


class ActivityRecaller:
    """Renders a day-by-day activity digest from the real capture queue."""

    def __init__(self, queue_path: Path = _QUEUE_PATH) -> None:
        self._queue_path = Path(queue_path)

    def digest(self, days: int = _DEFAULT_DAYS, now: Optional[datetime] = None) -> str:
        now = now or datetime.now(_IST)
        win_start = now - timedelta(days=days)

        per_day_turns: Dict[str, int] = defaultdict(int)
        per_day_domains: Dict[str, Counter] = defaultdict(Counter)
        per_day_sessions: Dict[str, set] = defaultdict(set)
        per_chat: Dict[tuple, _ChatPick] = defaultdict(_ChatPick)
        model_sightings: List[tuple] = []  # (dt, model) — runtime SELF-state
        machine = ""
        total = 0

        for rec in _iter_queue(self._queue_path):
            dt = _parse_instant(rec.get("ts", ""))
            if dt is None or dt < win_start:
                continue
            day = dt.astimezone(_IST).date().isoformat()
            sig = rec.get("heuristic_signals", {}) or {}
            domain = sig.get("domain_guess") or "general"
            per_day_turns[day] += 1
            per_day_domains[day][domain] += 1
            per_day_sessions[day].add(rec.get("session_id", ""))
            if rec.get("model"):
                model_sightings.append((dt, rec["model"]))
            if rec.get("machine"):
                machine = rec["machine"]
            total += 1

            message = _owner_message(rec.get("user_text", ""))
            if message:
                per_chat[(day, rec.get("session_id", ""))].offer(dt, message)

        if total == 0:
            return ("RECENT ACTIVITY: no captured turns in the last "
                    f"{days} days (observation_queue.jsonl is empty or new).")

        n_sessions = len({s for d in per_day_sessions.values() for s in d})
        lines: List[str] = [
            f"RECENT ACTIVITY — your own captured turns across ALL chats, last {days} days "
            f"({total} turns, {n_sessions} chats). Source: local observation_queue.jsonl — "
            "this is your actual per-prompt activity log, NOT git. Use it to stay aware of "
            "what you have been working on across chats.",
            "",
        ]

        # SELF-STATE (Identity pillar): which brain produced the turns, and any swaps.
        self_line = self._self_state_line(model_sightings, machine)
        if self_line:
            lines.insert(1, self_line)
        per_day_picks: Dict[str, List[tuple]] = defaultdict(list)
        for (day, _), pick in per_chat.items():
            if pick.chosen is not None:
                per_day_picks[day].append((pick.dt, pick.chosen))

        for day in sorted(per_day_turns, reverse=True):
            dt = datetime.fromisoformat(day + "T00:00:00").replace(tzinfo=_IST)
            wd = _WEEKDAY[dt.weekday()]
            doms = ", ".join(f"{d}×{c}" for d, c in per_day_domains[day].most_common())
            lines.append(f"- {day} ({wd}): {per_day_turns[day]} turns "
                         f"[{len(per_day_sessions[day])} chat(s)] — {doms}")
            seen: set = set()
            for _, message in sorted(per_day_picks[day], key=lambda t: t[0]):
                key = " ".join(message.split()).lower()
                if key in seen:
                    continue
                seen.add(key)
                lines.append("    • " + message.replace("\n", "\n      "))

        return "\n".join(lines)

    def write_digest(
        self, days: int = _DEFAULT_DAYS, now: Optional[datetime] = None,
        out_path: Path = _DIGEST_PATH,
    ) -> Path:
        """Render the digest to the COMMITTED activity_digest.md so the distilled
        experience syncs cross-machine. Refuses to overwrite a real digest with an
        empty one (a fresh machine with no local queue must not blank the synced
        artifact from the machine that lived the week)."""
        now = now or datetime.now(_IST)
        body = self.digest(days=days, now=now)
        if "no captured turns" in body and out_path.exists():
            return out_path  # preserve the synced digest; nothing local to add
        header = (
            "# Activity Digest — distilled cross-chat experience\n\n"
            "> Auto-generated by `jarvis_core/agent/recall.py --write` from the\n"
            "> per-prompt capture queue. Committed so JARVIS's recent experience\n"
            "> travels to every machine even before a full queue sync — this is\n"
            "> the DISTILLED, 7-day, human-readable form (observation_queue.jsonl\n"
            "> itself is also tracked; corrected 2026-09-10, this line used to\n"
            "> falsely claim otherwise).\n"
            f"> Generated {now.isoformat(timespec='seconds')} on "
            f"{os.environ.get('JARVIS_MACHINE', os.uname().nodename if hasattr(os, 'uname') else 'unknown')}.\n\n"
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(header + body + "\n", encoding="utf-8")
        return out_path

    @staticmethod
    def _self_state_line(model_sightings: List[tuple], machine: str) -> str:
        """One line of runtime SELF-state: current model + brain swaps in the window.
        Older queue records predate model telemetry (no 'model' field) — they are
        simply absent from the chain; no line at all if nothing carries a model."""
        if not model_sightings:
            return ""
        model_sightings.sort(key=lambda t: t[0])
        chain: List[tuple] = []
        for dt, m in model_sightings:
            if not chain or chain[-1][1] != m:
                chain.append((dt, m))
        current = chain[-1][1]
        # "latest captured", NOT "current brain": the queue spans hosts (Claude
        # Code + terminal), so the newest sighting is whichever runtime spoke
        # last anywhere — asserting it as THIS host's brain was live-wrong on
        # 2026-06-12 (a fable-5 session read "nemotron (current brain)").
        parts = [f"SELF-STATE: latest captured turn was produced by {current}"]
        if machine:
            parts.append(f"on {machine}")
        if len(chain) > 1:
            swaps = "; ".join(
                f"{prev_m} -> {m} ({dt.astimezone(_IST).date().isoformat()})"
                for (_, prev_m), (dt, m) in zip(chain, chain[1:])
            )
            parts.append(f"— brain swaps this window: {swaps}")
        return " ".join(parts) + "."


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS
# =============================================================================

def _run_self_test() -> None:
    import tempfile

    print("=" * 70)
    print("  recall.py -- Smoke Tests")
    print("=" * 70)
    passed = 0
    failed: List[str] = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        nonlocal passed
        if cond:
            passed += 1
        else:
            failed.append(f"FAIL: {name}" + (f" ({hint})" if hint else ""))

    now = datetime(2026, 6, 10, 18, 0, tzinfo=_IST)

    def obs(ts: datetime, domain: str, text: str, sid: str) -> str:
        return json.dumps({
            "ts": ts.isoformat(), "session_id": sid, "user_text": text,
            "heuristic_signals": {"prompt_len": len(text), "has_correction_markers": False,
                                  "domain_guess": domain},
        })

    with tempfile.TemporaryDirectory() as td:
        q = Path(td) / "queue.jsonl"
        lines = [
            # June 9 — DE Lessons chat (session s_de)
            obs(now - timedelta(days=1), "data-engineering", "LakehousePlumber pipeline ext_stg flow", "s_de"),
            obs(now - timedelta(days=1), "data-engineering", "auto cdc flags not received in the data", "s_de"),
            obs(now - timedelta(days=1), "general", "union vs union all", "s_de"),
            # June 10 — JARVIS build chat (session s_jv) + a finance chat (s_fin)
            obs(now, "jarvis-build", "do the upgrade", "s_jv"),
            obs(now, "jarvis-build", "run a full synthesis", "s_jv"),
            obs(now, "finance", "rebalance my portfolio", "s_fin"),
            # old turn outside a 3-day window
            obs(now - timedelta(days=20), "general", "ancient turn", "s_old"),
        ]
        q.write_text("\n".join(lines) + "\n", encoding="utf-8")

        rec = ActivityRecaller(queue_path=q)
        d = rec.digest(days=3, now=now)

        check("T1 sourced from queue not git", "NOT git" in d and "observation_queue" in d)
        check("T2 June 9 DE present (the chat the review missed)",
              "2026-06-09" in d and ("LakehousePlumber" in d or "auto cdc flags" in d), d)
        check("T3 June 9 recognized as data-engineering", "data-engineering" in d)
        check("T4 June 10 present with jarvis-build", "2026-06-10" in d and "jarvis-build" in d)
        check("T5 cross-chat: counts multiple chats", "chats)" in d and "3 chats" in d.replace("  ", " ") or "3 chats" in d, d[:200])
        check("T6 most-recent day first", d.index("2026-06-10") < d.index("2026-06-09"))
        check("T7 20-day-old turn excluded by 3d window", "ancient turn" not in d)
        check("T8 weekday rendered", "(Tue)" in d or "(Wed)" in d)

        # empty queue -> graceful
        eq = Path(td) / "empty.jsonl"
        eq.write_text("", encoding="utf-8")
        check("T9 empty queue -> graceful message",
              "no captured turns" in ActivityRecaller(queue_path=eq).digest(days=7, now=now))

        # harness-wrapper leftover gets cleaned in snippet display
        wq = Path(td) / "wrap.jsonl"
        wq.write_text(obs(now, "general",
                          "<ide_opened_file>/home/x/JARVIS/y</ide_opened_file> real question here about spark", "s1") + "\n",
                      encoding="utf-8")
        dw = ActivityRecaller(queue_path=wq).digest(days=2, now=now)
        check("T10 wrapper stripped from snippet", "ide_opened_file" not in dw and "real question here" in dw, dw)

        # --- no cuts: the selected message appears whole, however long ---
        long_msg = ("I want the insights screen to show the monthly movement first, "
                    + "and then every holding in order of weight " * 150 + "FINAL-WORD")
        lq = Path(td) / "long.jsonl"
        lq.write_text("\n".join([
            obs(now - timedelta(hours=3), "finance", long_msg, "s_long"),
            obs(now - timedelta(hours=2), "finance", "second shorter turn in the same chat", "s_long"),
        ]) + "\n", encoding="utf-8")
        dl = ActivityRecaller(queue_path=lq).digest(days=2, now=now)
        check("T15 a 6,000-char message appears whole, to its last word",
              "FINAL-WORD" in dl and "truncated" not in dl
              and " ".join(dl.split()).count("every holding in order of weight") == 150, dl[-200:])
        check("T16 one message per chat per day (the opening request)",
              "second shorter turn" not in dl)

        # --- envelopes are never chosen; the owner's own prose is ---
        eq2 = Path(td) / "envelopes.jsonl"
        eq2.write_text("\n".join([
            obs(now - timedelta(hours=5), "general",
                "The following is the Codex agent history whose request action you are "
                "assessing. >>> TRANSCRIPT START [1] user: something", "s_env"),
            obs(now - timedelta(hours=4), "general",
                "This session is being continued from a previous conversation that ran "
                "out of context. Summary: lots of things", "s_env"),
            obs(now - timedelta(hours=3), "general",
                "<task-notification>agent finished with a long report body</task-notification>",
                "s_env"),
            obs(now - timedelta(hours=2), "general",
                "[Image: source: C:\\tmp\\1.png]\n[external unsupported block: image]", "s_env"),
            obs(now - timedelta(hours=1), "general",
                "# AGENTS.md instructions for E:\\J.A.R.V.I.S\n<INSTRUCTIONS>rules</INSTRUCTIONS>",
                "s_env"),
            obs(now - timedelta(minutes=30), "general",
                "# Files mentioned by the user:\n\n## shot.png: C:/tmp/shot.png\n\n"
                "## My request for Codex:\n"
                "the graph needs to show the whole year, not just this month", "s_env"),
        ]) + "\n", encoding="utf-8")
        de = ActivityRecaller(queue_path=eq2).digest(days=2, now=now)
        check("T17 harness envelopes skipped; the owner's request chosen",
              "the graph needs to show the whole year" in de
              and "TRANSCRIPT START" not in de and "being continued" not in de
              and "long report body" not in de and "shot.png" not in de
              and "AGENTS.md" not in de, de)

        # a chat whose opener is a pasted log is represented by its prose turn
        pq = Path(td) / "paste.jsonl"
        log = "\n".join(f"2026-06-10T10:00:{i:02d} ERROR worker {i} failed" for i in range(40))
        pq.write_text("\n".join([
            obs(now - timedelta(hours=2), "general", log, "s_paste"),
            obs(now - timedelta(hours=1), "general",
                "why does the worker pool keep failing after the deploy?", "s_paste"),
        ]) + "\n", encoding="utf-8")
        dp = ActivityRecaller(queue_path=pq).digest(days=2, now=now)
        check("T18 a pasted log loses to the owner's prose", "why does the worker pool" in dp
              and "ERROR worker" not in dp, dp)

        # --- SELF-STATE (Identity pillar) ---
        def obs_m(ts: datetime, model: str, sid: str = "s1") -> str:
            return json.dumps({
                "ts": ts.isoformat(), "session_id": sid, "machine": "HRM5472-NEW",
                "model": model, "user_text": "a real question with enough length",
                "heuristic_signals": {"prompt_len": 30, "has_correction_markers": False,
                                      "domain_guess": "general"},
            })
        mq = Path(td) / "models.jsonl"
        mq.write_text("\n".join([
            obs_m(now - timedelta(days=2), "claude-opus-4-8"),
            obs_m(now - timedelta(days=1), "claude-opus-4-8"),
            obs_m(now, "claude-fable-5"),
        ]) + "\n", encoding="utf-8")
        dm = ActivityRecaller(queue_path=mq).digest(days=3, now=now)
        check("T11 SELF-STATE names the latest captured brain",
              "SELF-STATE" in dm
              and "latest captured turn was produced by claude-fable-5" in dm, dm[:300])
        check("T11b swap chain rendered",
              "claude-opus-4-8 -> claude-fable-5" in dm, dm[:300])
        check("T11c machine included", "HRM5472-NEW" in dm)

        # records WITHOUT model (pre-telemetry) -> no SELF line, no crash
        check("T12 no model fields -> SELF line omitted gracefully",
              "SELF-STATE" not in ActivityRecaller(queue_path=q).digest(days=3, now=now))

        # --- write_digest (Portable Mind: the committed travel artifact) ---
        dig = Path(td) / "activity_digest.md"
        out = ActivityRecaller(queue_path=mq).write_digest(days=3, now=now, out_path=dig)
        check("T13 write_digest creates the committed artifact",
              out.exists() and "Activity Digest" in dig.read_text()
              and "SELF-STATE" in dig.read_text())
        # fresh machine (empty queue) must NOT blank a synced digest
        before = dig.read_text()
        empty_q = Path(td) / "noq.jsonl"
        empty_q.write_text("", encoding="utf-8")
        ActivityRecaller(queue_path=empty_q).write_digest(days=3, now=now, out_path=dig)
        check("T14 empty queue preserves the synced digest (no blanking)",
              dig.read_text() == before)

    total = passed + len(failed)
    print(f"\n  Passed: {passed}/{total}")
    if failed:
        for f_ in failed:
            print(f"  {f_}")
        print("=" * 70)
        raise SystemExit(1)
    print(f"  All {total} recall smoke tests passed.")
    print("=" * 70)


def main() -> int:
    p = argparse.ArgumentParser(description="Cross-chat activity recall digest (from the capture queue, not git)")
    p.add_argument("--days", type=int, default=_DEFAULT_DAYS)
    p.add_argument("--write", action="store_true",
                   help="Render to the COMMITTED jarvis_data/activity_digest.md (the travel artifact)")
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    if args.self_test:
        _run_self_test()
        return 0
    if args.write:
        path = ActivityRecaller().write_digest(days=args.days)
        print(f"[recall] wrote {path}")
        return 0
    print(ActivityRecaller().digest(days=args.days))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
