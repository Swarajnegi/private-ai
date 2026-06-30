"""
routing_ledger.py — Append-only routing decision log (Stage 4.2.4).

LAYER: Brain (Orchestration — the routing audit trail / Stage-5 training corpus)

Import with:
    from jarvis_core.brain.routing_ledger import RoutingRecord, RoutingLedger

=============================================================================
THE BIG PICTURE
=============================================================================

Every routing decision the IntentRouter makes is a labelled example: "this query
-> this specialist codename -> this target -> it worked / failed over / errored,
for this cost". Logged append-only, that stream IS the supervised corpus the
Stage-5 Orchestrator adapter trains on — the router teaches its own successor.

Mirrors agent/cost.py CostTracker (a @dataclass record + a thin accumulator with
record()/summary()), but persists to JSONL like agent/capture.py's
append_observation (fail-soft, never crashes the ask it is observing). The raw
query is NEVER written — only a sha1 hash — so the corpus is privacy-clean and
de-dupable without leaking prompt text.

=============================================================================
THE FLOW
=============================================================================

STEP 1: orchestrator.ask() routes -> builds a RoutingRecord (codename, confidence,
        chosen target, outcome, cost) with a sha1 query-hash, never the query.
        |
STEP 2: RoutingLedger.record(rec) appends one JSON line (fail-soft: a write error
        is swallowed so a logging hiccup never breaks the answer).
        |
STEP 3: summary() reads the accumulated in-memory records for a per-session rollup
        (counts, per-label distribution, mean confidence, failover/error rates).

=============================================================================
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # standalone-run safety

from jarvis_core.config import ROUTING_LEDGER_PATH

try:
    import fcntl
    _HAS_FCNTL = True
except Exception:  # pragma: no cover - Windows
    _HAS_FCNTL = False


def query_hash(query: str) -> str:
    """sha1 of the raw query — the only form ever persisted (privacy + de-dup)."""
    return hashlib.sha1((query or "").encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RoutingRecord:
    """One routed query. `ts` is caller-supplied (ISO 8601) — this module never
    reads the clock, so it stays import-safe and deterministic in tests."""
    ts: str
    query_hash: str
    label: str
    confidence: float
    target: str
    outcome: str = "ok"        # ok | failover | error
    cost_usd: float = 0.0

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


@dataclass
class RoutingLedger:
    """Append-only routing log + in-memory rollup. Mirrors CostTracker's shape."""
    path: Path = ROUTING_LEDGER_PATH
    _records: List[RoutingRecord] = field(default_factory=list)

    def record(self, rec: RoutingRecord) -> RoutingRecord:
        """Append one decision. Fail-soft: a write error is swallowed (logging must
        never break the ask it observes); the in-memory rollup still gets it."""
        self._records.append(rec)
        try:
            p = Path(self.path)
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                if _HAS_FCNTL:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    f.write(rec.to_json() + "\n")
                    f.flush()
                finally:
                    if _HAS_FCNTL:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass  # fail-soft: never crash the routed answer over a log write
        return rec

    @property
    def count(self) -> int:
        return len(self._records)

    def summary(self) -> Dict[str, Any]:
        """Per-session rollup: counts, per-label distribution, mean confidence,
        failover/error rates, total cost."""
        n = len(self._records)
        by_label: Dict[str, int] = {}
        outcomes: Dict[str, int] = {}
        for r in self._records:
            by_label[r.label] = by_label.get(r.label, 0) + 1
            outcomes[r.outcome] = outcomes.get(r.outcome, 0) + 1
        mean_conf = round(sum(r.confidence for r in self._records) / n, 4) if n else 0.0
        return {
            "count": n,
            "by_label": by_label,
            "outcomes": outcomes,
            "mean_confidence": mean_conf,
            "total_cost_usd": round(sum(r.cost_usd for r in self._records), 6),
        }


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS
# =============================================================================

def _run_self_test() -> None:
    import tempfile

    print("=" * 70)
    print("  routing_ledger.py -- Smoke Tests")
    print("=" * 70)
    passed = 0
    failed: List[str] = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        nonlocal passed
        if cond:
            passed += 1
        else:
            failed.append(f"FAIL: {name}" + (f" ({hint})" if hint else ""))

    # T1: query_hash is sha1, deterministic, never the raw text
    h = query_hash("rebalance my portfolio")
    check("T1 query_hash sha1 hex (40 chars), not the raw query",
          len(h) == 40 and h != "rebalance my portfolio")
    check("T1b query_hash deterministic", h == query_hash("rebalance my portfolio"))

    # T2: RoutingRecord is frozen + serializes
    rec = RoutingRecord(ts="2026-06-29T10:00:00+05:30", query_hash=h, label="analyst",
                        confidence=0.71, target="vendor/model", outcome="ok", cost_usd=0.0)
    try:
        rec.label = "x"  # type: ignore[misc]
        frozen = False
    except Exception:
        frozen = True
    check("T2 RoutingRecord frozen", frozen)
    check("T2b to_json round-trips", json.loads(rec.to_json())["label"] == "analyst")

    with tempfile.TemporaryDirectory() as d:
        ledger_path = Path(d) / "routing_ledger.jsonl"
        led = RoutingLedger(path=ledger_path)

        # T3: append-only growth + on-disk round-trip
        led.record(rec)
        led.record(RoutingRecord("2026-06-29T10:01:00+05:30", query_hash("x"),
                                 "engineer", 0.55, "vendor/coder", "failover", 0.0012))
        led.record(RoutingRecord("2026-06-29T10:02:00+05:30", query_hash("y"),
                                 "engineer", 0.61, "vendor/coder2", "ok", 0.0))
        check("T3 in-memory count", led.count == 3)
        lines = ledger_path.read_text(encoding="utf-8").strip().splitlines()
        check("T3b three jsonl lines on disk", len(lines) == 3, str(len(lines)))
        check("T3c raw query never persisted",
              all("rebalance my portfolio" not in ln for ln in lines))

        # T4: summary rollup
        s = led.summary()
        check("T4 count", s["count"] == 3)
        check("T4b by_label distribution", s["by_label"] == {"analyst": 1, "engineer": 2}, str(s["by_label"]))
        check("T4c outcomes", s["outcomes"].get("failover") == 1 and s["outcomes"].get("ok") == 2)
        check("T4d mean confidence", abs(s["mean_confidence"] - round((0.71 + 0.55 + 0.61) / 3, 4)) < 1e-9)
        check("T4e total cost", abs(s["total_cost_usd"] - 0.0012) < 1e-9, str(s["total_cost_usd"]))

    # T5: fail-soft — a bad path does NOT raise (logging never breaks the ask)
    bad = RoutingLedger(path=Path("/proc/nonexistent_dir/cannot/write.jsonl"))
    try:
        bad.record(rec)
        soft = True
    except Exception:
        soft = False
    check("T5 fail-soft on unwritable path (no raise)", soft and bad.count == 1)

    total = passed + len(failed)
    print(f"\n  Passed: {passed}/{total}")
    if failed:
        for f_ in failed:
            print(f"  {f_}")
        print("=" * 70)
        raise SystemExit(1)
    print(f"  All {total} routing_ledger smoke tests passed.")
    print("=" * 70)


if __name__ == "__main__":
    _run_self_test()
