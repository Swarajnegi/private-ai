#!/usr/bin/env python3
"""Evaluate the current Tier 1 commitment surfacing against labelled real cases.

This is a snapshot check, not a substitute for the quiet-week run required by
DORMANCY_SPEC.md. It makes the small positive set and missing run history loud.
No model, embedding, Chroma, network, or training call is made.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import tempfile
import time
from datetime import date, datetime
from pathlib import Path

from commitments import due_commitments, load_commitments, registry_path


ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "jarvis_data" / "dormancy_gold.jsonl"
JOBS = ROOT / "jarvis_data" / ".hearth_jobs.json"
RUN_LOG = ROOT / "jarvis_data" / "commitment_runs.jsonl"
WEEK_SECONDS = 7 * 24 * 3600
CHECK_INTERVAL_SECONDS = 6 * 3600
SNAPSHOT_DATE = date(2026, 9, 29)
# Pin the exact labelled registry without copying authored commitments into a
# second store. Git's blob object remains addressable across later commits.
SNAPSHOT_GIT_BLOB = "27f650faed3d60800c696ba98a549d270ee63830"


def evaluate(gold_path: Path = GOLD) -> dict:
    snapshot = subprocess.run(["git", "show", SNAPSHOT_GIT_BLOB], cwd=ROOT,
                              capture_output=True, check=True).stdout
    cases = [json.loads(line) for line in gold_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    ids = [str(case["id"]) for case in cases]
    if len(ids) != len(set(ids)) or any(type(case.get("expect_surface")) is not bool for case in cases):
        raise ValueError("gold cases need unique ids and boolean expect_surface")
    with tempfile.TemporaryDirectory(prefix="jarvis-dormancy-gold-") as tmp:
        registry = Path(tmp) / "commitments.jsonl"
        registry.write_bytes(snapshot)
        states = {item.id: item for item in load_commitments(registry)}
        missing = sorted(set(ids) - set(states))
        if missing:
            raise ValueError(f"gold cases absent from the registry: {missing}")
        due = {item.commitment.id for item in due_commitments(path=registry, today=SNAPSHOT_DATE)}
    labels = {case["id"]: case["expect_surface"] for case in cases}
    unexpected = sorted(due - set(labels))
    if unexpected:
        raise ValueError(f"due commitments have no gold label: {unexpected}")
    rows = [{"id": cid, "expected": labels[cid], "surfaced": cid in due,
             "correct": labels[cid] == (cid in due)} for cid in ids]
    tp = sum(row["expected"] and row["surfaced"] for row in rows)
    fn = sum(row["expected"] and not row["surfaced"] for row in rows)
    fp = sum(not row["expected"] and row["surfaced"] for row in rows)
    tn = sum(not row["expected"] and not row["surfaced"] for row in rows)

    job = json.loads(JOBS.read_text(encoding="utf-8")).get("check_commitments", {}) if JOBS.exists() else {}
    first_seen = float(job.get("first_seen_ts") or 0)
    runs = int(job.get("runs") or 0)
    failures = int(job.get("failures") or 0)
    expected_runs = math.ceil(WEEK_SECONDS / CHECK_INTERVAL_SECONDS)
    events = [json.loads(line) for line in RUN_LOG.read_text(encoding="utf-8").splitlines()
              if line.strip()] if RUN_LOG.exists() else []
    timestamps = sorted(datetime.fromisoformat(str(event["ts"])).timestamp() for event in events
                        if event.get("status") == "ok")
    week_start = time.time() - WEEK_SECONDS
    recent = [timestamp for timestamp in timestamps if timestamp >= week_start]
    bounds = [week_start, *recent, time.time()]
    max_gap = max((right - left for left, right in zip(bounds, bounds[1:])), default=WEEK_SECONDS)
    coverage = len(recent) >= expected_runs and max_gap <= CHECK_INTERVAL_SECONDS * 1.5
    return {
        "snapshot_date": SNAPSHOT_DATE.isoformat(),
        "registry_git_blob": SNAPSHOT_GIT_BLOB,
        "registry_sha256": hashlib.sha256(snapshot).hexdigest(),
        "live_registry_sha256": hashlib.sha256(registry_path().read_bytes()).hexdigest(),
        "gold_sha256": hashlib.sha256(gold_path.read_bytes()).hexdigest(),
        "gold_cases": len(rows), "positive": tp + fn, "negative": tn + fp,
        "tp": tp, "fn": fn, "fp": fp, "tn": tn, "rows": rows,
        "quiet_week": {"covered": coverage, "runs": runs, "expected_runs": expected_runs,
                       "failures": failures, "first_seen_ts": first_seen,
                       "per_run_due_history_available": bool(events),
                       "logged_week_runs": len(recent), "max_gap_seconds": round(max_gap)},
        "tier2_gate_met": False,
        "tier2_gate_reason": "No confirmed Tier 1 miss and no auditable seven-day per-run due history; one positive is too small to infer broad recall.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = evaluate()
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Tier 1 gold: {result['tp']} TP, {result['fn']} FN, {result['fp']} FP, {result['tn']} TN")
        week = result["quiet_week"]
        print(f"Quiet-week coverage: {'yes' if week['covered'] else 'no'} "
              f"({week['logged_week_runs']}/{week['expected_runs']} logged runs; "
              f"{week['runs']} aggregate runs, {week['failures']} failures)")
        print(f"Tier 2/3: GATED — {result['tier2_gate_reason']}")
    return 0 if result["fn"] == 0 and result["fp"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
