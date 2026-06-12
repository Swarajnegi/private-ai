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
STEP 2: group turns by IST calendar day; per day tally turn count + domain mix +
        a few representative, de-duplicated topic snippets (harness wrappers and
        secrets already stripped/redacted at capture; light cleanup here too).
        |
STEP 3: render a compact, source-labeled markdown digest (most-recent day first).

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
# experience that SYNCS to other machines, while the raw queue stays local
# (Consciousness Portability Contract — distilled travels, raw stays home).
_DIGEST_PATH = Path(DATA_ROOT) / "activity_digest.md"

_DEFAULT_DAYS = 7
_SNIPPETS_PER_DAY = 4
_SNIPPET_CHARS = 80
_MAX_DIGEST_CHARS = 3500
_WEEKDAY = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# Light leftover-wrapper cleanup for snippet display (capture strips these going
# forward; older queued turns may still carry them).
_WRAP = re.compile(
    r"</?(ide_opened_file|ide_selection|system-reminder|task-notification|"
    r"local-command-[a-z]+|command-[a-z]+)\b[^>]*>", re.IGNORECASE)


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


def _clean_snippet(text: str) -> str:
    text = _WRAP.sub(" ", text or "")
    text = " ".join(text.split())  # collapse whitespace
    return text


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
        per_day_snippets: Dict[str, List[str]] = defaultdict(list)
        per_day_seen: Dict[str, set] = defaultdict(set)
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

            snippet = _clean_snippet(rec.get("user_text", ""))[:_SNIPPET_CHARS]
            if snippet and len(snippet) >= 12:
                dedup_key = snippet[:40].lower()
                if (dedup_key not in per_day_seen[day]
                        and len(per_day_snippets[day]) < _SNIPPETS_PER_DAY):
                    per_day_seen[day].add(dedup_key)
                    per_day_snippets[day].append(snippet)

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
        for day in sorted(per_day_turns, reverse=True):
            dt = datetime.fromisoformat(day + "T00:00:00").replace(tzinfo=_IST)
            wd = _WEEKDAY[dt.weekday()]
            doms = ", ".join(f"{d}×{c}" for d, c in per_day_domains[day].most_common(3))
            lines.append(f"- {day} ({wd}): {per_day_turns[day]} turns "
                         f"[{len(per_day_sessions[day])} chat(s)] — {doms}")
            for snip in per_day_snippets[day]:
                lines.append(f"    • {snip}")

        digest = "\n".join(lines)
        if len(digest) > _MAX_DIGEST_CHARS:
            digest = digest[:_MAX_DIGEST_CHARS] + "\n    … (truncated)"
        return digest

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
            "> Auto-generated by `jarvis_core/agent/recall.py --write` from the LOCAL\n"
            "> per-prompt capture queue (never git). Committed so JARVIS's recent\n"
            "> experience travels to every machine; the raw queue stays local.\n"
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
              "2026-06-09" in d and "LakehousePlumber" in d, d)
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
