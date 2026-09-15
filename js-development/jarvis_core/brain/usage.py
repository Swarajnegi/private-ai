"""
usage.py — days since JARVIS was last USED, as opposed to built.

LAYER: Brain (Cognitive Control Loop — the honest mirror)

Import with:
    from jarvis_core.brain.usage import read_usage, usage_line

=============================================================================
THE BIG PICTURE
=============================================================================

An external audit (2026-09-06) landed the sentence this module exists to
answer: "a platform in search of a repeated job." Checking it took one command
and produced this:

    conversations/           19 real `--ask` sessions, last one 2026-08-03
    observation_queue.jsonl  535 turns of BUILDING JARVIS, including today

The system had not been used in 34 days. Nothing in the repo noticed, and the
reason is structural rather than careless: EVERY instrument here counts
construction. Roadmap rows count sub-phases built. blend_corpus counts records
ingested. The KB counts decisions made. ActivityRecaller reads the capture
queue — which is time spent building. conversations/ was the only usage signal
that existed and it had NO consumer: not one script, hook or roadmap row
opened it.

So disuse was not under-weighted. It was UNREPRESENTABLE — it produced no row,
no counter, no delta, while every metric that did exist kept reporting healthy.

A resolution ("ask about usage next time") would rot exactly like the stale
status headers of KB 527. The fix has to be an instrument that fires on its
own, so this reports into the boot inhale: JARVIS itself says how long it has
been ignored, in the first block of the next session, unprompted.

The number is deliberately uncomfortable. It gets WORSE while you build and
better only when you use. It is the first metric in this repo that does not
reward construction.

=============================================================================
THE FLOW
=============================================================================

STEP 1: read_usage() lists conversations/*.jsonl and takes each session's start
        time from the FILENAME (conv-YYYYMMDDTHHMMSS-pid.jsonl) where one is
        there. The web UI writes conv-web-<uuid>.jsonl with no timestamp in the
        name, so for those it reads the first record's own `ts` — one line, then
        it stops. This line used to end "no file is opened, so this stays cheap"
        and that became false on 2026-09-15 when the fallback was added; the
        cost is a single line per UI session, which is still fine for a boot.
        |
STEP 2: it computes lifetime count, recent-window count, and days since the
        most recent session.
        |
STEP 3: usage_line() renders one line for the inhale; context_injector ships
        it as a provider alongside temporal and self-state.
=============================================================================
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # standalone-run safety

from jarvis_core.config import CONVERSATIONS_ROOT

_IST = timezone(timedelta(hours=5, minutes=30))
_SESSION_NAME = re.compile(r"^conv-(\d{8}T\d{6})-")
_RECENT_WINDOW_DAYS = 30

# Past this, the gap is the story rather than a detail, so the line says so.
_STALE_AFTER_DAYS = 14


@dataclass(frozen=True)
class UsageState:
    """What the only usage log in this repo actually says."""
    lifetime_sessions: int
    recent_sessions: int
    last_session: Optional[datetime]
    days_since: Optional[int]

    @property
    def never_used(self) -> bool:
        return self.lifetime_sessions == 0

    @property
    def stale(self) -> bool:
        return self.days_since is not None and self.days_since >= _STALE_AFTER_DAYS


def _first_record_ts(path: Path) -> Optional[datetime]:
    """The session's own first timestamp, read from inside the file."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    stamp = str(json.loads(line).get("ts", ""))
                except ValueError:
                    return None
                if not stamp:
                    return None
                try:
                    parsed = datetime.fromisoformat(stamp)
                except ValueError:
                    return None
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=_IST)
    except (OSError, FileNotFoundError):
        return None
    return None


def _session_times(root: Path) -> List[datetime]:
    """Every session's start time — from the filename, else from inside the file.

    THE FILENAME-ONLY VERSION WAS BLIND TO THE WEB UI, and it mattered far more
    than a miscount. Terminal sessions are written as
    `conv-20260911T155453-2960.jsonl`, which `_SESSION_NAME` parses. The hearth's
    web UI writes `conv-web-<uuid>.jsonl` — no timestamp anywhere in the name —
    so every UI session hit the `continue` below and vanished silently.

    Measured 2026-09-15: this reported `last_session 2026-09-11` while the user
    was in the UI that same day and the day before, answering a 45-question
    personalization set. `stage_5_specialists/ROADMAP.md` gates a ₹1,480-2,960
    RunPod run partly on this number — citing "0 sessions in the last 30 days,
    training an adapter for a path nobody opens" — so a parser that skipped the
    surface actually in use was arguing against spend with evidence it did not
    have.

    The fallback reads the first record's own `ts`, which every conversation
    record already carries. That is better than mtime for the same reason
    `capture.py` insists a backfilled turn keeps its own timestamp: mtime is
    when the file was last touched, not when the session happened.
    """
    try:
        paths = [p for p in root.iterdir() if p.suffix == ".jsonl"]
    except (OSError, FileNotFoundError):
        return []
    stamps: List[datetime] = []
    for path in paths:
        match = _SESSION_NAME.match(path.name)
        if match:
            try:
                stamps.append(datetime.strptime(match.group(1), "%Y%m%dT%H%M%S")
                              .replace(tzinfo=_IST))
                continue
            except ValueError:
                pass
        from_record = _first_record_ts(path)
        if from_record is not None:
            stamps.append(from_record)
    return sorted(stamps)


def read_usage(root: Optional[Path] = None,
               now: Optional[datetime] = None) -> UsageState:
    """Parse session timestamps from conversations/ filenames."""
    base = Path(root) if root else Path(CONVERSATIONS_ROOT)
    at = now or datetime.now(_IST)
    stamps = _session_times(base)
    if not stamps:
        return UsageState(0, 0, None, None)
    cutoff = at - timedelta(days=_RECENT_WINDOW_DAYS)
    last = stamps[-1]
    return UsageState(
        lifetime_sessions=len(stamps),
        recent_sessions=sum(1 for s in stamps if s >= cutoff),
        last_session=last,
        days_since=max(0, (at - last).days),
    )


def usage_line(root: Optional[Path] = None,
               now: Optional[datetime] = None) -> str:
    """One line for the boot inhale. Never returns None — silence here would
    reproduce the exact blindness this module exists to end."""
    state = read_usage(root=root, now=now)
    if state.never_used:
        return ("Real `--ask` sessions: NONE on record. This system has been "
                "built but never used.")
    stamp = state.last_session.strftime("%Y-%m-%d") if state.last_session else "?"
    line = (f"Real `--ask` sessions: {state.lifetime_sessions} lifetime, "
            f"{state.recent_sessions} in the last {_RECENT_WINDOW_DAYS} days. "
            f"Last used {stamp} ({state.days_since} days ago).")
    if state.stale:
        line += (" NOTE: building JARVIS is not using JARVIS. Say this plainly "
                 "if progress comes up — it is the one metric here that does "
                 "not reward construction.")
    return line


# =============================================================================
# SMOKE TESTS (offline — temp dirs, fake clock, no writes outside tempdir)
# =============================================================================

def _run_self_test() -> None:
    import tempfile

    print("=" * 70)
    print("  usage.py -- Smoke Tests")
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

    now = datetime(2026, 9, 6, 12, 0, tzinfo=_IST)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for stamp in ("20260615T155027", "20260731T120509", "20260803T040735"):
            (root / f"conv-{stamp}-1234.jsonl").write_text("{}", encoding="utf-8")
        (root / "notes.txt").write_text("ignore me", encoding="utf-8")

        st = read_usage(root=root, now=now)
        check("T1 counts only .jsonl session files", st.lifetime_sessions == 3,
              f"got {st.lifetime_sessions}")
        check("T2 days_since measured from the LATEST session",
              st.days_since == 34, f"got {st.days_since}")
        check("T3 30-day window excludes older sessions",
              st.recent_sessions == 0, f"got {st.recent_sessions}")
        check("T4 a 34-day gap is flagged stale", st.stale)

        line = usage_line(root=root, now=now)
        check("T5 line reports the real gap", "34 days ago" in line, line)
        check("T6 stale line names the distinction",
              "building JARVIS is not using JARVIS" in line, line)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "conv-20260905T101500-99.jsonl").write_text("{}", encoding="utf-8")
        st = read_usage(root=root, now=now)
        check("T7 recent use is not flagged stale",
              st.days_since == 1 and not st.stale, f"days={st.days_since}")
        check("T8 recent session counts in the window", st.recent_sessions == 1)
        check("T9 healthy line omits the scolding note",
              "not using JARVIS" not in usage_line(root=root, now=now))

    with tempfile.TemporaryDirectory() as td:
        st = read_usage(root=Path(td), now=now)
        check("T10 empty directory reads as never-used", st.never_used)
        check("T11 never-used says so explicitly",
              "never used" in usage_line(root=Path(td), now=now))

    st = read_usage(root=Path("/nonexistent-conversations"), now=now)
    check("T12 missing directory degrades quietly", st.never_used)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "conv-BADSTAMP-1.jsonl").write_text("{}", encoding="utf-8")
        (root / "conv-20260905T101500-2.jsonl").write_text("{}", encoding="utf-8")
        st = read_usage(root=root, now=now)
        check("T13 unparseable filename skipped, not fatal",
              st.lifetime_sessions == 1, f"got {st.lifetime_sessions}")

    # T14-T16: the web-UI blindness. `conv-web-<uuid>.jsonl` carries no
    # timestamp in its name, so the filename-only parser dropped every UI
    # session in silence — and the number it produced was cited in
    # stage_5_specialists/ROADMAP.md as grounds against a RunPod spend.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "conv-20260911T155453-2960.jsonl").write_text(
            '{"role":"user","content":"terminal","ts":"2026-09-11T15:54:53+05:30"}\n',
            encoding="utf-8")
        (root / "conv-web-cff653a1-415e-417b-ba68-3ac84f621778.jsonl").write_text(
            '{"role":"user","content":"ui","ts":"2026-09-14T12:51:02+05:30"}\n',
            encoding="utf-8")
        st = read_usage(root=root, now=now)
        check("T14 a web-UI session with no timestamp in its name is counted",
              st.lifetime_sessions == 2, f"got {st.lifetime_sessions}")
        check("T15 ...and it wins as the most recent session",
              st.last_session is not None and st.last_session.day == 14,
              f"got {st.last_session}")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "conv-web-nots.jsonl").write_text(
            '{"role":"user","content":"no ts field"}\n', encoding="utf-8")
        (root / "conv-web-bad.jsonl").write_text("not json at all\n", encoding="utf-8")
        (root / "conv-web-empty.jsonl").write_text("", encoding="utf-8")
        st = read_usage(root=root, now=now)
        check("T16 an unreadable UI session is skipped, never counted or fatal",
              st.lifetime_sessions == 0, f"got {st.lifetime_sessions}")

    print("-" * 70)
    print(f"  {passed} passed, {len(failed)} failed")
    if failed:
        for name in failed:
            print(f"    - {name}")
    print("=" * 70)
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    _run_self_test()
