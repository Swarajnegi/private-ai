#!/usr/bin/env python3
"""
commitments.py — append-only registry for deliberately deferred decisions.

LAYER: Agent (the Tier 1 absence instrument)

Run with:
    python3 scripts/commitments.py --open --what "Build GraphRAG" \
        --resolves-when "A multi-hop retrieval path is serving" --kb-id 548
    python3 scripts/commitments.py --list
    python3 scripts/commitments.py --due
    python3 scripts/commitments.py --close c001 --note "Delivered in Stage 4.6"
    python3 scripts/commitments.py --self-test

=============================================================================
THE BIG PICTURE
=============================================================================

Without a commitment registry:
    -> A deferred decision is prose in a roadmap or the knowledge base.
    -> Looking for it later means guessing from words such as "deferred".
    -> Closed decisions match those words too, so the result is a noisy list.

With this registry:
    -> A person deliberately records an open commitment and its resolution rule.
    -> A shell check resolves machine-checkable commitments without a model call.
    -> Everything else appears only when its declared review date has passed.

=============================================================================
THE FLOW
=============================================================================

STEP 1: --open appends one full commitment record, linked to its KB reasoning.
        |
STEP 2: --due reads only records deliberately entered into this registry.
        |
STEP 3: A check exiting zero appends an automatic resolution; a past review date is due.
        |
STEP 4: --close appends a small state event. The opening record is never edited.
=============================================================================
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

try:
    import fcntl
except ImportError:  # Windows uses msvcrt below.
    fcntl = None  # type: ignore[assignment]
try:
    import msvcrt
except ImportError:  # POSIX uses fcntl above.
    msvcrt = None  # type: ignore[assignment]


# =============================================================================
# PART 1: Paths, time, and immutable records
# =============================================================================

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_REGISTRY = _REPO_ROOT / "jarvis_data" / "commitments.jsonl"
_DEFAULT_RUN_LOG = _REPO_ROOT / "jarvis_data" / "commitment_runs.jsonl"
_IST = timezone(timedelta(hours=5, minutes=30))
_STATUSES = frozenset({"open", "resolved", "abandoned"})
_CHECK_TIMEOUT_SECONDS = 10


def registry_path() -> Path:
    """Resolve the live path when called so tests never inherit production state."""
    return _DEFAULT_REGISTRY


def ist_now() -> str:
    return datetime.now(_IST).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Commitment:
    """One current commitment state reconstructed from append-only registry events."""

    id: str
    opened: str
    kb_id: int
    what: str
    resolves_when: str
    check: Optional[str]
    review_after: Optional[str]
    status: str
    closed: Optional[str]
    closed_by: Optional[str]
    note: Optional[str]

    def as_open_record(self) -> Dict[str, object]:
        return {
            "id": self.id,
            "opened": self.opened,
            "kb_id": self.kb_id,
            "what": self.what,
            "resolves_when": self.resolves_when,
            "check": self.check,
            "review_after": self.review_after,
            "status": self.status,
            "closed": self.closed,
            "closed_by": self.closed_by,
            "note": self.note,
        }


@dataclass(frozen=True)
class DueItem:
    """A current open commitment that needs no inference to be surfaced."""

    commitment: Commitment
    reason: str
    detail: str


# =============================================================================
# PART 2: Cross-platform append lock and JSONL handling
# =============================================================================

@contextmanager
def exclusive_lock(path: Path) -> Iterator[None]:
    """Lock a sibling runtime file without changing the append-only registry."""
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+b") as lock_file:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        elif msvcrt is not None:
            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"0")
                lock_file.flush()
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        else:
            raise RuntimeError("no supported file-locking primitive on this platform")
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            elif msvcrt is not None:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)


def read_records(path: Optional[Path] = None) -> List[Dict[str, object]]:
    """Read valid JSONL records. An invalid final line is ignored until the next write heals it."""
    source = Path(path) if path is not None else registry_path()
    if not source.exists():
        return []
    records: List[Dict[str, object]] = []
    with open(source, encoding="utf-8") as handle:
        lines = handle.readlines()
    for line_number, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            if line_number == len(lines):
                continue
            raise ValueError(f"invalid JSON at {source}:{line_number}")
        if isinstance(record, dict):
            records.append(record)
    return records


def append_record(record: Dict[str, object], path: Optional[Path] = None) -> None:
    """Append one record under a lock and restore a missing final newline first."""
    target = Path(path) if path is not None else registry_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True)
    with exclusive_lock(target):
        with open(target, "a+", encoding="utf-8") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() > 0:
                handle.seek(handle.tell() - 1)
                if handle.read(1) != "\n":
                    handle.write("\n")
            handle.write(encoded + "\n")
            handle.flush()
            os.fsync(handle.fileno())


# =============================================================================
# PART 3: State reconstruction and validation
# =============================================================================

def _parse_open(record: Dict[str, object]) -> Commitment:
    required = ("id", "opened", "kb_id", "what", "resolves_when", "status")
    missing = [name for name in required if name not in record]
    if missing:
        raise ValueError(f"opening record missing {', '.join(missing)}")
    status = str(record["status"])
    if status != "open":
        raise ValueError("opening record must have status open")
    try:
        kb_id = int(record["kb_id"])
    except (TypeError, ValueError) as error:
        raise ValueError("kb_id must be an integer") from error
    return Commitment(
        id=str(record["id"]), opened=str(record["opened"]), kb_id=kb_id,
        what=str(record["what"]).strip(), resolves_when=str(record["resolves_when"]).strip(),
        check=str(record["check"]).strip() if record.get("check") else None,
        review_after=str(record["review_after"]) if record.get("review_after") else None,
        status="open", closed=None, closed_by=None, note=None,
    )


def load_commitments(path: Optional[Path] = None) -> List[Commitment]:
    """Fold append-only opening and close events into the current state for each id."""
    states: Dict[str, Commitment] = {}
    for record in read_records(path):
        if record.get("event") == "close":
            commitment_id = str(record.get("id", ""))
            prior = states.get(commitment_id)
            status = str(record.get("status", ""))
            if prior is None or status not in _STATUSES - {"open"}:
                continue
            states[commitment_id] = replace(
                prior, status=status, closed=str(record.get("closed") or ""),
                closed_by=str(record.get("closed_by") or ""),
                note=str(record.get("note")) if record.get("note") else None,
            )
            continue
        commitment = _parse_open(record)
        if commitment.id in states:
            raise ValueError(f"duplicate commitment opening id {commitment.id}")
        states[commitment.id] = commitment
    return [states[key] for key in sorted(states)]


def _next_id(commitments: Sequence[Commitment]) -> str:
    highest = 0
    for commitment in commitments:
        if commitment.id.startswith("c") and commitment.id[1:].isdigit():
            highest = max(highest, int(commitment.id[1:]))
    return f"c{highest + 1:03d}"


def _parse_review_after(value: Optional[str]) -> Optional[date]:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("review_after must be YYYY-MM-DD") from error


def open_commitment(
    what: str,
    resolves_when: str,
    kb_id: int,
    check: Optional[str] = None,
    review_after: Optional[str] = None,
    path: Optional[Path] = None,
) -> Commitment:
    """Append one deliberate deferral; nothing is inferred from existing prose."""
    if not what.strip() or not resolves_when.strip():
        raise ValueError("what and resolves_when are required")
    if kb_id < 1:
        raise ValueError("kb_id must be positive")
    _parse_review_after(review_after)
    target = Path(path) if path is not None else registry_path()
    with exclusive_lock(target):
        commitment = Commitment(
            id=_next_id(load_commitments(target)), opened=ist_now(), kb_id=kb_id,
            what=what.strip(), resolves_when=resolves_when.strip(),
            check=check.strip() if check and check.strip() else None,
            review_after=review_after, status="open", closed=None, closed_by=None, note=None,
        )
        # The outer lock covers id selection and append. append_record's lock is not re-entered.
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a+", encoding="utf-8") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() > 0:
                handle.seek(handle.tell() - 1)
                if handle.read(1) != "\n":
                    handle.write("\n")
            handle.write(json.dumps(commitment.as_open_record(), ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    return commitment


def close_commitment(
    commitment_id: str,
    abandoned: bool = False,
    note: Optional[str] = None,
    path: Optional[Path] = None,
) -> Commitment:
    """Append a state event, leaving the original commitment immutable."""
    target = Path(path) if path is not None else registry_path()
    with exclusive_lock(target):
        states = {item.id: item for item in load_commitments(target)}
        current = states.get(commitment_id)
        if current is None:
            raise ValueError(f"unknown commitment {commitment_id}")
        if current.status != "open":
            raise ValueError(f"{commitment_id} is already {current.status}")
        status = "abandoned" if abandoned else "resolved"
        event: Dict[str, object] = {
            "event": "close", "id": commitment_id, "status": status,
            "closed": ist_now(), "closed_by": "manual", "note": note.strip() if note else None,
        }
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a+", encoding="utf-8") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() > 0:
                handle.seek(handle.tell() - 1)
                if handle.read(1) != "\n":
                    handle.write("\n")
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    return replace(current, status=status, closed=str(event["closed"]),
                   closed_by="manual", note=str(event["note"]) if event["note"] else None)


# =============================================================================
# PART 4: Due checks and CLI rendering
# =============================================================================

def run_check(command: str) -> Tuple[bool, str]:
    """Run a deliberately entered check with a bounded wait and no shell output leak."""
    try:
        result = subprocess.run(
            command, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=_CHECK_TIMEOUT_SECONDS, check=False,
        )
    except subprocess.TimeoutExpired:
        return False, f"check timed out after {_CHECK_TIMEOUT_SECONDS}s"
    return result.returncode == 0, f"check exited {result.returncode}"


def due_commitments(
    path: Optional[Path] = None,
    today: Optional[date] = None,
) -> List[DueItem]:
    """Return only explicit open commitments that a date or check makes actionable."""
    current_day = today or datetime.now(_IST).date()
    due: List[DueItem] = []
    for commitment in load_commitments(path):
        if commitment.status != "open":
            continue
        if commitment.check:
            resolved, detail = run_check(commitment.check)
            if resolved:
                due.append(DueItem(commitment, "check-resolved", detail))
                continue
        review = _parse_review_after(commitment.review_after)
        if review is not None and review <= current_day:
            due.append(DueItem(commitment, "review-due", f"review date {review.isoformat()}"))
    return due


def record_due_run(items: List[DueItem], duration_seconds: float, rc: int,
                   path: Optional[Path] = None) -> None:
    """Keep auditable per-run evidence for the Tier 1 quiet-week gate."""
    append_record({
        "ts": ist_now(),
        "due_ids": [item.commitment.id for item in items],
        "review_due_ids": [item.commitment.id for item in items if item.reason == "review-due"],
        "check_resolved_ids": [item.commitment.id for item in items if item.reason == "check-resolved"],
        "duration_seconds": round(duration_seconds, 3),
        "rc": rc,
        "status": "ok" if rc == 0 else "failed",
    }, path or _DEFAULT_RUN_LOG)


def _render_commitment(commitment: Commitment) -> str:
    review = commitment.review_after or "none"
    return f"{commitment.id}  {commitment.status:<9} KB {commitment.kb_id:<4} review {review}  {commitment.what}"


def _run_self_test() -> None:
    """Exercise every write path in a temporary directory, never the live registry."""
    import tempfile

    print("=" * 70)
    print("  commitments.py -- Smoke Tests")
    print("=" * 70)
    passed = 0
    failed: List[str] = []

    def check(name: str, condition: bool, hint: str = "") -> None:
        nonlocal passed
        if condition:
            passed += 1
            print(f"  PASS {name}")
        else:
            failed.append(name)
            print(f"  FAIL {name} {hint}")

    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "commitments.jsonl"
        first = open_commitment("Build GraphRAG", "A graph index serves a multi-hop query", 548,
                                review_after="2030-01-01", path=path)
        check("T1 first opening is c001", first.id == "c001", first.id)
        check("T2 list reconstructs the open state", load_commitments(path) == [first])

        second = open_commitment("Answer transcript question", "The answer file exists", 531,
                                 check=f'"{sys.executable}" -c "raise SystemExit(0)"', path=path)
        due = due_commitments(path, today=date(2029, 1, 1))
        check("T3 successful check is surfaced without guessing", any(item.commitment.id == second.id and item.reason == "check-resolved" for item in due), str(due))

        closed = close_commitment(first.id, note="implemented", path=path)
        check("T4 close appends a resolved state", closed.status == "resolved", str(closed))
        check("T5 closed records do not appear in due", all(item.commitment.id != first.id for item in due_commitments(path, today=date(2031, 1, 1))), "closed commitment surfaced")

        torn = Path(temporary) / "torn.jsonl"
        torn.write_text(json.dumps(first.as_open_record()), encoding="utf-8")
        open_commitment("A second item", "A human closes it", 531, path=torn)
        raw = torn.read_text(encoding="utf-8")
        check("T6 next write heals a missing newline", raw.count("\n") == 2 and len(load_commitments(torn)) == 2, repr(raw))

        try:
            open_commitment("bad", "bad", 1, review_after="not-a-date", path=path)
            check("T7 invalid review date is rejected", False)
        except ValueError:
            check("T7 invalid review date is rejected", True)

        run_log = Path(temporary) / "commitment_runs.jsonl"
        record_due_run(due, 0.125, 0, path=run_log)
        recorded = read_records(run_log)
        check("T8 due run has append-only per-run evidence",
              len(recorded) == 1 and second.id in recorded[0]["check_resolved_ids"]
              and recorded[0]["rc"] == 0)

    total = passed + len(failed)
    print("-" * 70)
    print(f"  {passed}/{total} passed")
    if failed:
        raise SystemExit(1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Track deliberate deferred commitments.")
    parser.add_argument("--open", action="store_true", help="append a new commitment")
    parser.add_argument("--what")
    parser.add_argument("--resolves-when")
    parser.add_argument("--kb-id", type=int)
    parser.add_argument("--check", dest="check_command")
    parser.add_argument("--review-after")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--status", choices=sorted(_STATUSES))
    parser.add_argument("--due", action="store_true")
    parser.add_argument("--record-run", action="store_true", help="append Tier 1 run evidence; use with --due")
    parser.add_argument("--close", metavar="ID")
    parser.add_argument("--abandoned", action="store_true")
    parser.add_argument("--note")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.record_run and not args.due:
        parser.error("--record-run requires --due")

    if args.self_test:
        _run_self_test()
        return 0
    if args.open:
        if not (args.what and args.resolves_when and args.kb_id):
            parser.error("--open needs --what, --resolves-when, and --kb-id")
        commitment = open_commitment(args.what, args.resolves_when, args.kb_id,
                                     args.check_command, args.review_after)
        print(_render_commitment(commitment))
        return 0
    if args.close:
        commitment = close_commitment(args.close, args.abandoned, args.note)
        print(_render_commitment(commitment))
        return 0
    if args.due:
        started = time.monotonic()
        items: List[DueItem] = []
        rc = 1
        try:
            items = due_commitments()
            if not items:
                print("No commitments are due.")
            for item in items:
                if item.reason == "check-resolved":
                    closed = close_commitment(
                        item.commitment.id,
                        note=f"automatic check: {item.detail}",
                    )
                    print(f"{_render_commitment(closed)}  [automatically resolved: {item.detail}]")
                else:
                    print(f"{_render_commitment(item.commitment)}  [{item.reason}: {item.detail}]")
            rc = 0
            return 0
        finally:
            if args.record_run:
                record_due_run(items, time.monotonic() - started, rc)
    if args.list:
        items = load_commitments()
        if args.status:
            items = [item for item in items if item.status == args.status]
        for item in items:
            print(_render_commitment(item))
        if not items:
            print("No commitments found.")
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
