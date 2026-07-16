"""
model_stats.py — Rolling per-target health persistence (Stage 4.3.1).

LAYER: Brain (Orchestration — ModelPool health survives across `ask()` calls)

Import with:
    from jarvis_core.brain.model_stats import ModelStatsRecord, ModelStatsStore

=============================================================================
THE BIG PICTURE
=============================================================================

Without this module:
    -> ModelPool is rebuilt from scratch on every single orchestrator.ask()
       call (Stage 4.1). Its _Health dict -- avg_latency_s, error counts,
       cooldown_until -- lives only in that instance's memory. The moment
       ask() returns, the process has no idea target X was slow, or target
       Y just got rate-limited 30 seconds ago. Every call re-learns the
       pool's health from zero, even across back-to-back CLI invocations
       seconds apart.
    -> A target still mid-cooldown from a 429 gets tried again immediately
       on the very next call, because the fresh pool has never heard of it.

With this module (mirrors brain/routing_ledger.py's append-only JSONL
pattern -- same fail-soft write, same fcntl guard -- but adds a
replay-latest LOAD path routing_ledger.py doesn't need, because routing
decisions are an immutable event stream while health is current STATE):
    -> Step 1: at the end of ask(), the orchestrator calls
       ModelStatsStore().flush(ts, pool.snapshot_health()) -- one JSON line
       per target, appended to jarvis_data/model_stats.jsonl.
    -> Step 2: at the start of the NEXT ask(), it calls
       ModelStatsStore().load_latest() and passes the result into
       ModelPool(initial_health=...) -- each target's _Health seeds from
       wherever it was left, instead of a fresh default.
    -> Step 3: a target still mid-cooldown from the last call stays
       benched; a target with a bad recent error_rate keeps scoring worse
       until enough clean calls bring its EMA back down.

=============================================================================
THE FLOW
=============================================================================

flush(ts, health_snapshot):
    for each (target_name, health_dict) -> append one ModelStatsRecord line
        |
        v
load_latest() -> replay every line in the file, keep ONLY the last one seen
                 per target_name (latest-wins) -> return {name: health_dict}
        |
        v
ModelPool(initial_health=that_dict) seeds _Health(**health_dict) per target
instead of _Health() defaults.

=============================================================================
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # standalone-run safety

from jarvis_core.config import MODEL_STATS_PATH

try:
    import fcntl
    _HAS_FCNTL = True
except Exception:  # pragma: no cover - Windows
    _HAS_FCNTL = False

_HEALTH_FIELDS = ("avg_latency_s", "request_count", "error_count", "cooldown_until")


@dataclass(frozen=True)
class ModelStatsRecord:
    """One target's health snapshot at flush time. `ts` is caller-supplied
    (ISO 8601) -- this module never reads the clock, so it stays import-safe
    and deterministic in tests (mirrors RoutingRecord's convention)."""
    ts: str
    target: str
    avg_latency_s: float
    request_count: int
    error_count: int
    cooldown_until: float

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


@dataclass
class ModelStatsStore:
    """Append-only per-target health log + replay-latest loader. Mirrors
    RoutingLedger's fail-soft append; adds the load path RoutingLedger
    doesn't need -- the pool only ever wants the LAST snapshot per target,
    never the full history."""
    path: Path = MODEL_STATS_PATH

    def flush(self, ts: str, health_snapshot: Dict[str, Dict[str, float]]) -> None:
        """Append one line per target in health_snapshot. Fail-soft: a write
        error is swallowed so a logging hiccup never breaks the ask it
        observes (same contract as RoutingLedger.record)."""
        try:
            p = Path(self.path)
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                if _HAS_FCNTL:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    for name, h in health_snapshot.items():
                        rec = ModelStatsRecord(
                            ts=ts,
                            target=name,
                            avg_latency_s=float(h.get("avg_latency_s", 1.0)),
                            request_count=int(h.get("request_count", 0)),
                            error_count=int(h.get("error_count", 0)),
                            cooldown_until=float(h.get("cooldown_until", 0.0)),
                        )
                        f.write(rec.to_json() + "\n")
                    f.flush()
                finally:
                    if _HAS_FCNTL:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass  # fail-soft: never crash the ask over a stats write

    def load_latest(self) -> Dict[str, Dict[str, float]]:
        """Replay the file, keeping only the LAST line seen per target name
        (latest-wins, never merged/averaged). Returns {} if the file doesn't
        exist yet, is unreadable, or every line fails to parse -- a cold
        start is always a safe fallback, never a crash."""
        p = Path(self.path)
        if not p.exists():
            return {}
        latest: Dict[str, Dict[str, float]] = {}
        try:
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                        latest[row["target"]] = {k: row[k] for k in _HEALTH_FIELDS}
                    except Exception:
                        continue  # one corrupt line never poisons the rest
        except Exception:
            return {}
        return latest


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS
# =============================================================================

def _run_self_test() -> None:
    import tempfile

    print("=" * 70)
    print("  model_stats.py -- Smoke Tests")
    print("=" * 70)
    passed = 0
    failed: List[str] = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        nonlocal passed
        if cond:
            passed += 1
        else:
            failed.append(f"FAIL: {name}" + (f" ({hint})" if hint else ""))

    # T1: ModelStatsRecord is frozen + serializes
    rec = ModelStatsRecord(ts="2026-07-15T10:00:00+05:30", target="A",
                            avg_latency_s=1.2, request_count=5, error_count=1,
                            cooldown_until=0.0)
    try:
        rec.target = "x"  # type: ignore[misc]
        frozen = False
    except Exception:
        frozen = True
    check("T1 ModelStatsRecord frozen", frozen)
    check("T1b to_json round-trips", json.loads(rec.to_json())["target"] == "A")

    with tempfile.TemporaryDirectory() as d:
        stats_path = Path(d) / "model_stats.jsonl"
        store = ModelStatsStore(path=stats_path)

        # T2: load_latest on a missing file is a safe cold start
        check("T2 missing file -> {}", store.load_latest() == {})

        # T3: flush appends one line per target
        store.flush("2026-07-15T10:00:00+05:30", {
            "A": {"avg_latency_s": 1.0, "request_count": 1, "error_count": 0, "cooldown_until": 0.0},
            "B": {"avg_latency_s": 2.0, "request_count": 1, "error_count": 1, "cooldown_until": 0.0},
        })
        lines = stats_path.read_text(encoding="utf-8").strip().splitlines()
        check("T3 two jsonl lines on disk", len(lines) == 2, str(len(lines)))

        # T4: load_latest reconstructs both targets after one flush
        loaded = store.load_latest()
        check("T4 both targets present", set(loaded) == {"A", "B"}, str(loaded))
        check("T4b values round-trip",
              loaded["A"]["avg_latency_s"] == 1.0 and loaded["B"]["error_count"] == 1)

        # T5: a SECOND flush for A must WIN on load (latest, not first, not merged)
        store.flush("2026-07-15T10:05:00+05:30", {
            "A": {"avg_latency_s": 3.3, "request_count": 4, "error_count": 2, "cooldown_until": 999.0},
        })
        loaded2 = store.load_latest()
        check("T5 A shows the SECOND flush's values", loaded2["A"]["avg_latency_s"] == 3.3, str(loaded2["A"]))
        check("T5b B untouched by A's second flush", loaded2["B"]["avg_latency_s"] == 2.0)
        check("T5c file has 3 lines (append-only, never rewritten)",
              len(stats_path.read_text(encoding="utf-8").strip().splitlines()) == 3)

        # T6: a corrupt line is skipped, not fatal to the rest of the file
        with open(stats_path, "a", encoding="utf-8") as f:
            f.write("not valid json\n")
        loaded3 = store.load_latest()
        check("T6 corrupt line skipped, good data survives", loaded3["A"]["avg_latency_s"] == 3.3)

    # T7: fail-soft -- flush to an unwritable path does NOT raise
    bad = ModelStatsStore(path=Path("/proc/nonexistent_dir/cannot/write.jsonl"))
    try:
        bad.flush("2026-07-15T10:00:00+05:30",
                  {"A": {"avg_latency_s": 1.0, "request_count": 1, "error_count": 0, "cooldown_until": 0.0}})
        soft = True
    except Exception:
        soft = False
    check("T7 fail-soft on unwritable path (no raise)", soft)

    total = passed + len(failed)
    print(f"\n  Passed: {passed}/{total}")
    if failed:
        for f_ in failed:
            print(f"  {f_}")
        print("=" * 70)
        raise SystemExit(1)
    print(f"  All {total} model_stats smoke tests passed.")
    print("=" * 70)


if __name__ == "__main__":
    _run_self_test()
