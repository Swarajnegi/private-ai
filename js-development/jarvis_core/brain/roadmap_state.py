"""
roadmap_state.py — Roadmap State Reader (Stage 4.0.2: the Teleological pillar).

LAYER: Brain (Cognitive Control Loop — purpose)

Import with:
    from jarvis_core.brain.roadmap_state import next_pending, pending_tasks

=============================================================================
THE BIG PICTURE
=============================================================================

"What should we work on next?" must be answered from the ROADMAP files the
project actually maintains — not from the model's memory of a stale summary.
This is the Teleological pillar of the Cognitive Control Loop (KB L107):
JARVIS opens every session knowing what is pending because it READS its own
plan, the same way the user does.

Pure stdlib, zero models, sub-millisecond — it runs inside the boot inhale.
It recognizes the three pending-marker conventions this repo actually uses:
    1. Markdown checkboxes:      - [ ] task      (pending)   - [x] (done)
    2. Status table cells:       | 4.1 | name | ⬜ |   (⬜/🔄 pending;
                                 ✅ / [OK] / ⏭ resolved)
    3. Headings flagged pending: ## Sub-Phase 4.0: ... ⬜

=============================================================================
THE FLOW
=============================================================================

STEP 1: pending_tasks(paths): stream each file line by line (lazy — never
        materialize a whole tree of roadmaps).
        |
STEP 2: classify each line: checkbox / table row / flagged heading; extract a
        human-readable label for pending ones.
        |
STEP 3: next_pending(paths) = first pending task in file order — the answer
        the ContextInjector breathes into every boot.

=============================================================================
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # standalone-run safety

from jarvis_core.config import JARVIS_ROOT

_PENDING_GLYPHS = ("⬜", "🔄")
_RESOLVED_GLYPHS = ("✅", "⏭", "[OK]")

_CHECKBOX_RX = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+\[( |x|X)\]\s+(.*)$")
_HEADING_RX = re.compile(r"^(#{1,6})\s+(.*)$")
_TABLE_SEP_RX = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")


# =============================================================================
# Part 1: CONTRACT
# =============================================================================

@dataclass(frozen=True)
class PendingTask:
    """One unchecked item: where it lives and what it says."""
    file: str
    line_no: int
    label: str


# =============================================================================
# Part 2: LINE CLASSIFICATION (pure functions)
# =============================================================================

def _strip_markers(text: str) -> str:
    out = text
    for glyph in _PENDING_GLYPHS + _RESOLVED_GLYPHS:
        out = out.replace(glyph, " ")
    out = re.sub(r"\*\*([^*]*)\*\*", r"\1", out)  # unbold
    return " ".join(out.split()).strip(" -—|")


def _table_row_label(line: str) -> Optional[str]:
    """A pending table row's label, or None if the row is not pending.

    Pending = a ⬜/🔄 glyph in any cell, with no resolving glyph in the SAME
    cell (a row like '⏭ DEFERRED' must not read as pending).
    """
    if "|" not in line or _TABLE_SEP_RX.match(line):
        return None
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    pending = False
    for cell in cells:
        if any(g in cell for g in _PENDING_GLYPHS):
            if not any(g in cell for g in _RESOLVED_GLYPHS):
                pending = True
            break
    if not pending:
        return None
    label_cells = [_strip_markers(c) for c in cells]
    label = " ".join(c for c in label_cells[:2] if c)
    return label or None


def _classify_line(line: str) -> Optional[str]:
    """Label of a pending item on this line, else None."""
    m = _CHECKBOX_RX.match(line)
    if m:
        return _strip_markers(m.group(2)) if m.group(1) == " " else None

    m = _HEADING_RX.match(line)
    if m:
        text = m.group(2)
        if any(g in text for g in _PENDING_GLYPHS):
            return _strip_markers(text)
        return None

    return _table_row_label(line)


# =============================================================================
# Part 3: PUBLIC API
# =============================================================================

def default_roadmap_paths() -> List[Path]:
    """Granular stage roadmap first, master second — the next LESSON beats
    the next STAGE when both are pending."""
    learning = Path(JARVIS_ROOT) / "js-learning"
    return [
        learning / "stage_4_orchestration" / "ROADMAP.md",
        learning / "JARVIS_MASTER_ROADMAP.md",
    ]


def pending_tasks(paths: List[Path]) -> Iterator[PendingTask]:
    """Yield every pending item across the given roadmaps, in file+line order."""
    for path in paths:
        p = Path(path)
        if not p.exists():
            continue
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                for line_no, line in enumerate(f, 1):
                    label = _classify_line(line.rstrip("\n"))
                    if label:
                        yield PendingTask(file=str(p), line_no=line_no, label=label)
        except OSError:
            continue


def next_pending(paths: Optional[List[Path]] = None) -> Optional[PendingTask]:
    """The first unchecked task — what JARVIS should work on next."""
    return next(pending_tasks(paths or default_roadmap_paths()), None)


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS (fixtures + real-file smoke)
# =============================================================================

def _run_self_test() -> None:
    import tempfile

    print("=" * 70)
    print("  roadmap_state.py -- Smoke Tests")
    print("=" * 70)
    passed = 0
    failed: List[str] = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        nonlocal passed
        if cond:
            passed += 1
        else:
            failed.append(f"FAIL: {name}" + (f" ({hint})" if hint else ""))

    FIXTURE = """# Roadmap fixture
## Sub-Phase 9.0: The Lungs ⬜ — Wave 1
| # | Sub-Phase | Status |
|---|-----------|--------|
| 9.0 | Cognitive Control Loop | ⬜ |
| 9.1 | Done thing | ✅ Complete |
| 9.2 | Entry sprint | [OK] Complete (2026-05-16) |
| 9.3 | In flight | 🔄 In progress |
| 9.4 | GraphRAG | ⏭ DEFERRED — trigger documented |
1. [ ] first boss criterion
2. [x] second boss criterion
- [ ] loose pending checkbox
- [X] loose done checkbox
## Sub-Phase 9.5: Closed ✅
"""

    with tempfile.TemporaryDirectory() as td:
        fx = Path(td) / "fixture.md"
        fx.write_text(FIXTURE, encoding="utf-8")
        tasks = list(pending_tasks([fx]))
        labels = [t.label for t in tasks]

        check("T1 heading with pending glyph found",
              any("Sub-Phase 9.0: The Lungs" in l for l in labels), str(labels))
        check("T2 pending table row found (label = number + name)",
              "9.0 Cognitive Control Loop" in labels, str(labels))
        check("T3 in-progress row counts as pending", "9.3 In flight" in labels)
        check("T4 completed rows excluded",
              not any("Done thing" in l or "Entry sprint" in l for l in labels))
        check("T5 deferred row excluded", not any("GraphRAG" in l for l in labels))
        check("T6 numbered checkbox pending", "first boss criterion" in labels)
        check("T7 checked items excluded",
              not any("second boss" in l or "loose done" in l for l in labels))
        check("T8 dash checkbox pending", "loose pending checkbox" in labels)
        check("T9 completed heading excluded",
              not any("Closed" in l for l in labels))
        check("T10 next_pending = first in file order",
              next_pending([fx]).label.startswith("Sub-Phase 9.0"))
        check("T11 line numbers tracked", tasks[0].line_no == 2, str(tasks[0]))

        # T12: missing file tolerated
        check("T12 missing file -> no tasks, no crash",
              next_pending([Path(td) / "nope.md"]) is None)

        # T13: table separator rows never classify
        check("T13 separator row ignored",
              _classify_line("|---|-----------|--------|") is None)

    # T14: real-repo smoke — the live roadmaps must yield a pending task
    real = next_pending()
    check("T14 real roadmaps yield a next task", real is not None and bool(real.label),
          str(real))
    if real:
        print(f"\n  next_pending (live): {real.label}  [{Path(real.file).name}:{real.line_no}]")

    total = passed + len(failed)
    print(f"\n  Passed: {passed}/{total}")
    if failed:
        for f_ in failed:
            print(f"  {f_}")
        print("=" * 70)
        raise SystemExit(1)
    print(f"  All {total} roadmap_state smoke tests passed.")
    print("=" * 70)


if __name__ == "__main__":
    _run_self_test()
