"""
projections.py — does every derived artifact still match the log?

LAYER: Brain (Cognitive Control Loop — integrity)

Import with:
    from jarvis_core.brain.projections import run_checks, stale_line

=============================================================================
THE BIG PICTURE
=============================================================================

On 2026-09-08 knowledge_base.jsonl held 544 entries while cognitive_index.sqlite3
held 533 and cognitive_profile.md's own header claimed 533. I called that "the
mind disagrees with itself." Real, but the diagnosis was wrong in a way worth
recording:

    The drift SELF-HEALS. profile_synth.py rebuilds the index whenever it runs,
    and on the next check all three read 556. It was never a fork — it was a
    STALENESS WINDOW that opens on every KB append and closes on the next
    regeneration.

So the defect was never that projections go wrong. It is that **nothing looks**.
In between, the system answers from a stale index and reports nothing. I found
it by accident, and accident is not a detection strategy.

Third instrument of the same family, and the pattern is now explicit: each
exists because something true about the system was UNREPRESENTABLE — it produced
no row, no counter, no delta, so it could not be noticed.

    brain/usage.py        row 0  — is JARVIS reached for at all?
    life_state feed       row 0b — does proactive surfacing produce anything?
    projections.py        this   — do the derived indexes still match the log?

A projection cannot be trusted because it is regenerable. It has to be
regenerated, and something has to say when it wasn't.

WHY COUNTS, MOSTLY. A full content hash would catch in-place edits too, but the
KB is append-only in normal operation, counts are cheap and human-readable, and
the newest timestamp travels alongside as a second signal. Perfect detection is
not the bar — ANY detection is, because today there is none.

THE STORAGE TAXONOMY THIS ENFORCES (KB 548, extended 2026-09-08):
    FACT                    authoritative, append-only     -> knowledge_base.jsonl
    PROJECTION              derived, rebuildable where read -> NOT tracked
    PROJECTION-AS-TRANSPORT derived here, consumed by a machine that CANNOT
                            rebuild it (the personal laptop has no capture
                            hooks) -> tracked, and that is correct

=============================================================================
THE FLOW
=============================================================================

STEP 1: kb_state() reads the FACT — entry count + newest timestamp, streamed.
        |
STEP 2: each projection reports its own view of that fact: the SQLite index's
        row count, the profile header's "(N entries)", and the distinct KB keys
        present in the jarvis_memory collection.
        |
STEP 3: run_checks() returns them with the exact fix command; stale_line()
        renders one sentence for the boot inhale, or None when all match — so a
        healthy system stays silent and only a real problem costs prompt space.
=============================================================================
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # standalone-run safety

from jarvis_core.config import DATA_ROOT, KB_PATH, COGNITIVE_INDEX_PATH

PROFILE_PATH = Path(DATA_ROOT) / "cognitive_profile.md"
_PROFILE_COUNT_RE = re.compile(r"\((\d+)\s+entries\)")
MEMORY_COLLECTION = "jarvis_memory"

# Zero tolerance for the index and profile: both rebuild from the whole KB in
# one pass, so any difference IS staleness. The vector index may lag slightly —
# indexing is a separate, slower, manual step — but not by much, or retrieval
# answers from a different mind than the profile describes.
_VECTOR_LAG_TOLERANCE = 5


@dataclass(frozen=True)
class Check:
    name: str
    expected: int
    actual: Optional[int]
    fix: str
    tolerance: int = 0

    @property
    def stale(self) -> bool:
        return True if self.actual is None else abs(self.expected - self.actual) > self.tolerance

    @property
    def detail(self) -> str:
        if self.actual is None:
            return "unreadable"
        delta = self.actual - self.expected
        return f"{self.actual}" if delta == 0 else f"{self.actual} ({delta:+d})"


def kb_state(kb_path: Optional[Path] = None) -> Tuple[int, str]:
    """(entry count, newest timestamp). Streamed — never materialises the file."""
    path = Path(kb_path) if kb_path else Path(KB_PATH)
    count, newest = 0, ""
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                count += 1
                try:
                    ts = str(json.loads(line).get("timestamp", ""))
                except ValueError:
                    continue
                if ts > newest:
                    newest = ts
    except (OSError, FileNotFoundError):
        return 0, ""
    return count, newest


def id_collisions(kb_path: Optional[Path] = None) -> Dict[int, int]:
    """Integer ids appearing more than once in the KB -> how many times.

    NOT a projection check — this one interrogates the FACT itself, and it
    exists instead of a fix that was planned and then found unnecessary.

    The plan for 2026-09-08 was to replace integer ids with content-addressed
    ones, because `kb_append._next_id` is `max(explicit ids, 300) + 1` and two
    machines computing that independently both mint the same number (the L303
    class). Measured before rewriting: 558 entries, 258 explicit ids, ZERO
    duplicates. fcntl.flock plus the single-user-at-a-time rule have held for
    the whole life of the file.

    So rewriting the widest-reach field in the repo — five consumers read `id`
    — would have been a large, risky change to prevent a failure that has never
    occurred. Detecting it costs one pass over a file already being read. Same
    trade the projection checks make: an instrument is cheaper than a guarantee,
    and it tells you the day the guarantee actually breaks.

    Returns:
        {} when every explicit id is unique. Non-empty is a real fork: two
        entries share an id, so anything joining on id silently picks one.
    """
    path = Path(kb_path) if kb_path else Path(KB_PATH)
    seen: Dict[int, int] = {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                eid = entry.get("id") if isinstance(entry, dict) else None
                if isinstance(eid, int) and not isinstance(eid, bool):
                    seen[eid] = seen.get(eid, 0) + 1
    except (OSError, FileNotFoundError):
        return {}
    return {eid: n for eid, n in seen.items() if n > 1}


def _index_count(path: Path) -> Optional[int]:
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            return int(con.execute("SELECT COUNT(*) FROM entries").fetchone()[0])
        finally:
            con.close()
    except Exception:
        return None


def _profile_count(path: Path) -> Optional[int]:
    try:
        m = _PROFILE_COUNT_RE.search(path.read_text(encoding="utf-8", errors="replace"))
        return int(m.group(1)) if m else None
    except (OSError, FileNotFoundError):
        return None


def _vector_count() -> Optional[int]:
    """Distinct KB entries in jarvis_memory. Chunk ids are '<key>-<n>', so
    stripping the index and de-duplicating yields entries, not chunks — the
    number actually comparable to the KB."""
    try:
        con = sqlite3.connect(
            f"file:{Path(DATA_ROOT) / 'chromadb' / 'chroma.sqlite3'}?mode=ro", uri=True)
        try:
            rows = con.execute(
                """SELECT em.embedding_id FROM embeddings em
                   JOIN segments sg ON em.segment_id = sg.id
                   JOIN collections c ON sg.collection = c.id
                   WHERE c.name = ?""", (MEMORY_COLLECTION,)
            ).fetchall()
        finally:
            con.close()
    except Exception:
        return None
    return len({r[0].rsplit("-", 1)[0] for r in rows if r and r[0]}) or None


def domain_label_health() -> Optional[str]:
    """Is the domain classifier still accurate? None when fine, else the problem.

    NOT a count comparison like the checks below — this one runs the classifier
    against a 28-turn hand-labelled gold set, because accuracy is the thing that
    rots and a row count cannot see it.

    The whole reason it exists: the previous labeller was a keyword matcher that
    returned "general" both for genuinely-general turns AND for "I have no idea",
    so 99 days and ~15% of records went wrong in total silence. An abstention now
    has its own label (`unknown`) and the accuracy has a floor that fails loudly.
    Any classifier drifts as the work moves into new territory; the durable
    property is not being right today, it is saying when it stops being right.

    Returns:
        None when accuracy is at or above the bar, or the classifier cannot be
        loaded at all (a missing embedding model is not a data-integrity fault
        and must never break a boot).
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
        from relabel_domains import GOLD, GOLD_MIN_ACCURACY, score_gold  # type: ignore
        from jarvis_core.agent.domain_classifier import DomainClassifier
        accuracy, misses = score_gold(DomainClassifier())
    except Exception:
        return None
    if accuracy >= GOLD_MIN_ACCURACY:
        return None
    worst = "; ".join(f"{m[0]!r} wanted {m[1]}, got {m[2]}" for m in misses)
    return (f"DOMAIN CLASSIFIER DRIFTED — {accuracy:.0%} on the {len(GOLD)}-turn gold "
            f"set, below the {GOLD_MIN_ACCURACY:.0%} bar. Labels are being assigned "
            f"wrongly right now. Examples: {worst}. Fix the prototypes or add session "
            f"context in agent/domain_classifier.py; do NOT lower the bar. "
            f"Inspect: python3 scripts/relabel_domains.py --gold")


def run_checks(kb_path: Optional[Path] = None) -> Tuple[List[Check], int, str]:
    expected, newest = kb_state(kb_path)
    checks = [
        Check("cognitive_index.sqlite3", expected,
              _index_count(Path(COGNITIVE_INDEX_PATH)),
              "python3 scripts/profile_synth.py"),
        Check("cognitive_profile.md", expected, _profile_count(PROFILE_PATH),
              "python3 scripts/profile_synth.py"),
        Check(f"chromadb/{MEMORY_COLLECTION}", expected, _vector_count(),
              "python3 scripts/index_memory.py", tolerance=_VECTOR_LAG_TOLERANCE),
    ]
    return checks, expected, newest


def stale_line() -> Optional[str]:
    """One sentence for the boot inhale, or None when everything matches.

    None (not "all good") is deliberate: a healthy system should cost zero
    prompt tokens. The provider only speaks when there is a problem.
    """
    try:
        checks, expected, _ = run_checks()
        collisions = id_collisions()
    except Exception:
        return None                      # integrity checking must never break a boot
    stale = [c for c in checks if c.stale]
    parts: List[str] = []
    drift = domain_label_health()
    if drift:
        parts.append(drift)
    if collisions:
        worst = ", ".join(f"id {eid} x{n}" for eid, n in sorted(collisions.items()))
        parts.append(
            f"KB ID COLLISION — {len(collisions)} duplicated id(s) ({worst}). Two "
            f"entries share an id, so anything joining on id silently picks one. "
            f"Inspect: python3 scripts/kb_append.py --audit")
    if stale:
        names = ", ".join(f"{c.name} at {c.detail}" for c in stale)
        fixes = "; ".join(sorted({c.fix for c in stale}))
        parts.append(
            f"STALE PROJECTIONS — the knowledge base has {expected} entries but "
            f"{names}. Retrieval and the injected profile are describing an older "
            f"version of the mind than the log holds. Fix: {fixes}")
    return " ".join(parts) if parts else None


# =============================================================================
# SMOKE TESTS (offline — temp files, no writes to real data)
# =============================================================================

def _run_self_test() -> None:
    import tempfile

    print("=" * 70)
    print("  projections.py -- Smoke Tests")
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

    with tempfile.TemporaryDirectory() as td:
        kb = Path(td) / "kb.jsonl"
        kb.write_text("".join(
            json.dumps({"id": i, "type": "Semantic", "timestamp": f"2026-09-0{i%9+1}",
                        "content": f"entry {i}"}) + "\n" for i in range(1, 6)
        ), encoding="utf-8")
        n, newest = kb_state(kb)
        check("T1 kb_state counts entries", n == 5, str(n))
        check("T2 kb_state finds the newest timestamp", newest == "2026-09-06", newest)

        kb.write_text('{"id":1}\nNOT JSON\n{"id":2}\n', encoding="utf-8")
        n2, _ = kb_state(kb)
        check("T3 a malformed line is counted but does not abort", n2 == 3, str(n2))

    missing, _ = kb_state(Path("/nonexistent/kb.jsonl"))
    check("T4 missing KB degrades to 0, never raises", missing == 0)

    # T5-T8 -- the Check contract, which is where the tolerance logic lives.
    c_ok = Check("x", 100, 100, "fix")
    c_off = Check("x", 100, 99, "fix")
    c_tol = Check("x", 100, 97, "fix", tolerance=5)
    c_over = Check("x", 100, 90, "fix", tolerance=5)
    c_none = Check("x", 100, None, "fix")
    check("T5 exact match is not stale", not c_ok.stale)
    check("T6 off by one with zero tolerance IS stale", c_off.stale)
    check("T7 within tolerance is not stale", not c_tol.stale)
    check("T8 beyond tolerance is stale", c_over.stale)
    check("T9 unreadable projection counts as stale, not as OK", c_none.stale)
    check("T10 detail shows the signed delta", c_off.detail == "99 (-1)", c_off.detail)
    check("T11 detail on a match omits the delta", c_ok.detail == "100", c_ok.detail)
    check("T12 unreadable renders honestly", c_none.detail == "unreadable")

    # T14-T17 -- FACT integrity: duplicate integer ids.
    with tempfile.TemporaryDirectory() as td:
        clean = Path(td) / "clean.jsonl"
        clean.write_text("".join(
            json.dumps({"id": i, "content": "x"}) + "\n" for i in (301, 302, 303)
        ), encoding="utf-8")
        check("T14 unique ids report no collisions", id_collisions(clean) == {},
              str(id_collisions(clean)))

        forked = Path(td) / "forked.jsonl"
        forked.write_text("".join(
            json.dumps({"id": i, "content": c}) + "\n"
            for i, c in ((301, "a"), (303, "work laptop"), (303, "personal laptop"),
                         (304, "d"), (304, "e"), (304, "f"))
        ), encoding="utf-8")
        found = id_collisions(forked)
        check("T15 the L303 collision class is detected with its multiplicity",
              found == {303: 2, 304: 3}, str(found))

        no_ids = Path(td) / "implicit.jsonl"
        no_ids.write_text('{"content":"pre-id era"}\n{"content":"also"}\n', encoding="utf-8")
        check("T16 entries with no explicit id are not collisions",
              id_collisions(no_ids) == {}, str(id_collisions(no_ids)))

        check("T17 a missing KB yields no collisions rather than raising",
              id_collisions(Path("/nonexistent/kb.jsonl")) == {})

    # T13 -- silence when healthy is a DESIGN choice, not an oversight.
    line = stale_line()
    check("T13 stale_line returns a str or None, never raises",
          line is None or isinstance(line, str), repr(line)[:60])
    if line is not None:
        check("T13b a stale line names both the problem and the fix",
              "Fix:" in line and "entries" in line, line[:80])
    else:
        passed += 1
        print("  PASS  T13b live projections currently match (nothing to report)")

    print("-" * 70)
    print(f"  {passed} passed, {len(failed)} failed")
    if failed:
        for name in failed:
            print(f"    - {name}")
    print("=" * 70)
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    _run_self_test()
