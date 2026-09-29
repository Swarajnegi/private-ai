#!/usr/bin/env python3
"""
index_episodes.py — build, inspect and measure the episode index (Context Store, Phase 3).

LAYER: Tools (thin CLI — the index is memory/episode_index.py)

Run with:
    python scripts/index_episodes.py                         # incremental: new store records only
    python scripts/index_episodes.py --rebuild               # from scratch (drops `episodes` + the FTS file)
    python scripts/index_episodes.py --status                # units, vectors, sizes, embedder
    python scripts/index_episodes.py --backfill-provenance   # distilled facts -> source turns
    python scripts/index_episodes.py --eval-retrieval        # recall@5/10/20 on recall_eval.jsonl
    python scripts/index_episodes.py --candidates minilm,bge-small,bge-base,nomic
                                                             # each embedder on the CORE units, scratch dir
    python scripts/index_episodes.py --self-test             # hermetic (index self-test + grader)

=============================================================================
THE BIG PICTURE
=============================================================================

The eval in jarvis_data/recall_eval.jsonl measures ANSWERS. Before any model
answers from retrieved context, the retrieval itself has to put the evidence
in front of it: an answer cannot be better than its top-k. --eval-retrieval
measures exactly that: for each question, does the top-k contain a unit that
covers one of the rows the question was checked against?

Evidence ids map onto units like this:
    kb:<id> / kb:line<N>  -> the KB unit of that entry
    file:<path>           -> any section unit of that canon file
    conv:<file>#<n>       -> the store turn whose source line is n in that
                             conversation file, then any unit holding it
    queue:<ts>|<session>  -> the store turn the capture row was written for
                             (queue_to_turn); a session this machine's store
                             does not hold is its own `queue` unit
Evidence that no unit can hold (a file that is not indexed) is reported as
unreachable, never silently counted as a miss or a hit.

=============================================================================
THE FLOW
=============================================================================

STEP 1: try-lock context_store/index (one builder at a time).
STEP 2: backfill fact provenance, then EpisodeIndex.build() (incremental).
STEP 3: --eval-retrieval: for every question, search (dense + FTS + rerank),
        grade hit@k per ability; timings give p50/p95 latency.
=============================================================================
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "js-development"))

from jarvis_core.config import DATA_ROOT, DB_ROOT  # noqa: E402
from jarvis_core.locking import try_exclusive_lock  # noqa: E402
from jarvis_core.memory import episode_index as ei  # noqa: E402

EVAL_PATH = Path(DATA_ROOT) / "recall_eval.jsonl"
RESULTS_DIR = Path(DATA_ROOT) / "recall_eval_results"
ABILITIES = ("information_extraction", "multi_session", "temporal", "knowledge_update", "abstention")
# The questions were written on 2026-09-28 ("this morning" = that morning).
EVAL_NOW = "2026-09-28T21:00:00+05:30"
KS = (5, 10, 20)


# =============================================================================
# Part 1: evidence -> unit targets
# =============================================================================

def _conv_turn(ref: str, store_root: Path) -> Optional[str]:
    """conv:<file>#<n> -> the store turn whose source line is n."""
    name, _, n = ref[len("conv:"):].partition("#")
    stem = name[:-len(".jsonl")] if name.endswith(".jsonl") else name
    path = store_root / "episodes" / "jarvis" / f"{ei.safe_session(stem)}.jsonl"
    for rec in ei._jsonl(path):
        if (rec.get("source") or {}).get("line") == int(n):
            return str(rec["id"])
    return None


def evidence_targets(row: Dict[str, Any], finder: "ei._SessionFinder", store_root: Path,
                     queue_rows: Dict[Tuple[str, str], Dict[str, Any]]) -> List[Tuple[str, Optional[str]]]:
    """(evidence source, the turn_ids member that covers it or None when unmappable)."""
    out: List[Tuple[str, Optional[str]]] = []
    for ev in row["evidence"]:
        src = str(ev["source"])
        if src.startswith(("kb:", "file:")):
            out.append((src, src))
        elif src.startswith("conv:"):
            out.append((src, _conv_turn(src, store_root)))
        elif src.startswith("queue:"):
            ts, _, sid = src[len("queue:"):].partition("|")
            if finder.has(sid):
                q = queue_rows.get((ts, sid), {})
                out.append((src, finder.turn_for(ts, sid, str(q.get("user_text") or ""))))
            else:
                out.append((src, src))
        else:
            out.append((src, None))
    return out


def _indexed_members(index: "ei.EpisodeIndex") -> set:
    members = set()
    for (tids,) in index.db.execute("SELECT turn_ids FROM units"):
        members.update(json.loads(tids))
    return members


# =============================================================================
# Part 2: the retrieval eval
# =============================================================================

def eval_retrieval(index: "ei.EpisodeIndex", rows: Sequence[Dict[str, Any]], rerank: bool = True,
                   sources: Optional[Sequence[str]] = None, now: str = EVAL_NOW,
                   log=print, tool_weight: float = 0.3, exclude_sessions: Sequence[str] = ()) -> Dict[str, Any]:
    finder = ei._SessionFinder(index.store_root)
    queue_rows = {(str(r.get("ts")), str(r.get("session_id"))): r for r in ei._jsonl(index.queue_path)}
    members = _indexed_members(index)
    when = datetime.fromisoformat(now)
    per_q: List[Dict[str, Any]] = []
    lat: List[float] = []
    for row in rows:
        targets = evidence_targets(row, finder, index.store_root, queue_rows)
        reachable = [t for _, t in targets if t and t in members]
        t0 = time.perf_counter()
        res = index.search(row["question"], k=max(KS) + (60 if exclude_sessions else 0), rerank=rerank,
                           sources=sources, now=when, tool_weight=tool_weight)
        if exclude_sessions:
            res = [r for r in res if not r.session_id.startswith(tuple(exclude_sessions))][:max(KS)]
        lat.append(time.perf_counter() - t0)
        first = None
        covered_at: Dict[str, int] = {}
        for rank, r in enumerate(res):
            for t in reachable:
                if t in r.turn_ids and t not in covered_at:
                    covered_at[t] = rank
                    first = rank if first is None else first
        per_q.append({"id": row["id"], "ability": row["ability"], "first_hit": first,
                      "targets": len(targets), "reachable": len(reachable),
                      "unreachable": [s for s, t in targets if not t or t not in members],
                      "covered_at": covered_at, "top": [r.unit_id for r in res[:5]]})
        mark = "-" if first is None else str(first + 1)
        log(f"  {row['id']:<6} hit@{mark:<3} reach {len(reachable)}/{len(targets)}  {row['question'][:70]}")
    return {"rows": per_q, "latency": lat, "summary": summarize(per_q), "rerank": rerank,
            "sources": list(sources) if sources else "all"}


def summarize(per_q: List[Dict[str, Any]]) -> Dict[str, Any]:
    def block(sub: List[Dict[str, Any]]) -> Dict[str, Any]:
        out: Dict[str, Any] = {"n": len(sub), "unreachable_q": sum(1 for q in sub if not q["reachable"])}
        for k in KS:
            hits = sum(1 for q in sub if q["first_hit"] is not None and q["first_hit"] < k)
            out[f"r@{k}"] = round(hits / len(sub), 3) if sub else None
            cov = [sum(1 for v in q["covered_at"].values() if v < k) / q["reachable"]
                   for q in sub if q["reachable"]]
            out[f"cov@{k}"] = round(sum(cov) / len(cov), 3) if cov else None
        return out
    s = {a: block([q for q in per_q if q["ability"] == a]) for a in ABILITIES}
    s["overall"] = block(per_q)
    s["answerable"] = block([q for q in per_q if q["ability"] != "abstention"])
    return s


def format_summary(s: Dict[str, Any]) -> str:
    head = f"{'ability':<24}{'n':>4}" + "".join(f"{'r@' + str(k):>8}" for k in KS) + \
        "".join(f"{'cov@' + str(k):>9}" for k in KS) + f"{'unreach':>9}"
    lines = [head, "-" * len(head)]
    for name in (*ABILITIES, "answerable", "overall"):
        b = s.get(name) or {}
        if not b.get("n"):
            continue
        pct = lambda v: "-" if v is None else f"{v * 100:.1f}%"   # noqa: E731
        lines.append(f"{name:<24}{b['n']:>4}" + "".join(f"{pct(b['r@' + str(k)]):>8}" for k in KS)
                     + "".join(f"{pct(b['cov@' + str(k)]):>9}" for k in KS) + f"{b['unreachable_q']:>9}")
    return "\n".join(lines)


def latency(lat: List[float]) -> Dict[str, float]:
    if not lat:
        return {}
    xs = sorted(lat[1:] or lat)                       # the first query pays the model loads
    return {"p50_ms": round(1000 * statistics.median(xs), 1),
            "p95_ms": round(1000 * xs[min(len(xs) - 1, int(0.95 * len(xs)))], 1),
            "first_ms": round(1000 * lat[0], 1)}


def load_eval(path: Path = EVAL_PATH) -> List[Dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# =============================================================================
# Part 3: builds
# =============================================================================

def real_index(embedder_name: Optional[str] = None) -> "ei.EpisodeIndex":
    name = embedder_name or ei.DEFAULT_EMBEDDER
    cand = Path(DATA_ROOT) / "context_store" / "candidates"
    seed = (cand / f"{name}.fts.sqlite3", cand / f"{name}.vec.npz")
    return ei.EpisodeIndex(embedder=ei.Embedder(ei.EMBEDDERS[name]),
                           vector_seed=seed if all(p.exists() for p in seed) else None)


def scratch_index(directory: Path, embedder_name: str, sources: Sequence[str]) -> "ei.EpisodeIndex":
    directory.mkdir(parents=True, exist_ok=True)
    return ei.EpisodeIndex(fts_path=directory / f"{embedder_name}.fts.sqlite3",
                           backend=ei.NumpyBackend(directory / f"{embedder_name}.vec.npz"),
                           embedder=ei.Embedder(ei.EMBEDDERS[embedder_name]), sources=sources)


def _dir_bytes(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0


def run_build(index: "ei.EpisodeIndex", rebuild: bool, quiet: bool = False) -> Dict[str, Any]:
    with try_exclusive_lock(ei.STORE_ROOT / "index") as got:
        if not got:
            print("another index build holds the lock; exiting without work")
            return {"busy": True}
        prov = ei.backfill_provenance()
        print(f"provenance: {prov}")
        import torch
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
        stats = index.build(rebuild=rebuild, log=(lambda s: None) if quiet else print)
        stats["vram_peak_mb"] = index.embedder.vram_peak_mb() if hasattr(index.embedder, "vram_peak_mb") else None
        return stats


# =============================================================================
# Part 4: self-test (hermetic: grading logic over a fixture index)
# =============================================================================

def _self_test() -> int:
    import subprocess
    rc = subprocess.call([sys.executable, "-m", "jarvis_core.memory.episode_index"],
                         cwd=str(_REPO_ROOT / "js-development"))
    per_q = [
        {"id": "a", "ability": "temporal", "first_hit": 3, "reachable": 2, "covered_at": {"x": 3, "y": 12}},
        {"id": "b", "ability": "temporal", "first_hit": None, "reachable": 1, "covered_at": {}},
        {"id": "c", "ability": "abstention", "first_hit": 0, "reachable": 1, "covered_at": {"z": 0}},
    ]
    s = summarize(per_q)
    ok = (s["temporal"]["r@5"] == 0.5 and s["temporal"]["r@20"] == 0.5 and s["temporal"]["cov@20"] == 0.5
          and s["answerable"]["n"] == 2 and s["overall"]["r@5"] == round(2 / 3, 3))
    print(f"  {'PASS' if ok else 'FAIL'}  G1 hit@k and coverage@k per ability, answerable excludes abstention")
    lat = latency([5.0, 0.1, 0.2, 0.3])
    ok2 = lat["p50_ms"] == 200.0 and lat["first_ms"] == 5000.0
    print(f"  {'PASS' if ok2 else 'FAIL'}  G2 latency excludes the model-loading first query")
    return 0 if rc == 0 and ok and ok2 else 1


# =============================================================================
# CLI
# =============================================================================

def main() -> int:
    ap = argparse.ArgumentParser(description="Build and measure the episode index.")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--backfill-provenance", action="store_true")
    ap.add_argument("--eval-retrieval", action="store_true")
    ap.add_argument("--candidates", default="", help="comma list of embedders to measure on the CORE units")
    ap.add_argument("--scratch", type=Path, default=Path(DATA_ROOT) / "context_store" / "candidates",
                    help="where --candidates builds (numpy vectors + FTS; gitignored)")
    ap.add_argument("--embedder", default=None, help=f"one of {sorted(ei.EMBEDDERS)}")
    ap.add_argument("--no-rerank", action="store_true")
    ap.add_argument("--sources", default="", help="restrict eval search to these unit sources (comma list)")
    ap.add_argument("--tool-weight", type=float, default=0.3,
                    help="RRF weight of the keyword-only tool-output lane (0 = exclude it)")
    ap.add_argument("--exclude-session-prefix", default="",
                    help="drop results from sessions with these id prefixes (comma list). The session that "
                         "AUTHORED the eval quotes every question verbatim, so its own turns are not recall")
    ap.add_argument("--only", default="", help="comma list of question ids")
    ap.add_argument("--now", default=EVAL_NOW, help="reference time for relative expressions")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    if args.self_test:
        return _self_test()
    if args.backfill_provenance:
        print(json.dumps(ei.backfill_provenance(), indent=1))
        return 0

    rows = load_eval()
    if args.only:
        wanted = {x.strip() for x in args.only.split(",") if x.strip()}
        rows = [r for r in rows if r["id"] in wanted]
    sources = [s for s in args.sources.split(",") if s] or None
    log = (lambda s: None) if args.quiet else print

    if args.candidates:
        report: Dict[str, Any] = {}
        for name in [c.strip() for c in args.candidates.split(",") if c.strip()]:
            idx = scratch_index(args.scratch, name, ei.CORE_SOURCES)
            try:
                idx.embedder.tokenizer
            except Exception as exc:                          # noqa: BLE001 — e.g. a gated repo
                print(f"== {name}: SKIPPED — cannot load {ei.EMBEDDERS[name].model}: {type(exc).__name__}: {exc}")
                report[name] = {"skipped": f"{type(exc).__name__}: {str(exc)[:200]}"}
                continue
            import torch
            if torch.cuda.is_available():
                torch.cuda.reset_peak_memory_stats()
            t0 = time.perf_counter()
            st = idx.build(rebuild=not (args.scratch / f"{name}.fts.sqlite3").exists(), log=lambda s: None)
            build_s = time.perf_counter() - t0
            print(f"== {name}: build {build_s:.0f}s  {idx.status()['units']} units  "
                  f"embedded {st.get('embedded', 0)}  overflow {st.get('overflow_windows')}  "
                  f"vram {idx.embedder.vram_peak_mb()} MB")
            res = eval_retrieval(idx, rows, rerank=not args.no_rerank, sources=sources, now=args.now, log=log)
            print(format_summary(res["summary"]))
            print(f"latency {latency(res['latency'])}")
            report[name] = {"build_s": round(build_s), "stats": st, "status": idx.status(),
                            "summary": res["summary"], "latency": latency(res["latency"]), "rows": res["rows"]}
            idx.close()
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        out = RESULTS_DIR / f"retrieval-candidates-{datetime.now().strftime('%Y-%m-%dT%H%M')}.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nreport: {out}")
        return 0

    index = real_index(args.embedder)
    if args.status:
        st = index.status()
        st["chromadb_bytes"] = _dir_bytes(Path(DB_ROOT))
        print(json.dumps(st, indent=1))
        return 0
    if args.eval_retrieval:
        res = eval_retrieval(index, rows, rerank=not args.no_rerank, sources=sources, now=args.now, log=log,
                             tool_weight=args.tool_weight,
                             exclude_sessions=[x for x in args.exclude_session_prefix.split(",") if x])
        print(format_summary(res["summary"]))
        lat = latency(res["latency"])
        print(f"latency (search incl. {'rerank' if not args.no_rerank else 'no rerank'}): {lat}")
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        tag = f"{index.embedder.spec.name}{'-norerank' if args.no_rerank else ''}-tw{args.tool_weight:g}{'-clean' if args.exclude_session_prefix else ''}"
        out = RESULTS_DIR / f"retrieval-{tag}-{datetime.now().strftime('%Y-%m-%dT%H%M')}.json"
        out.write_text(json.dumps({"embedder": index.embedder.spec.model, "status": index.status(),
                                   "latency": lat, **res}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"report: {out}")
        return 0
    st = run_build(index, rebuild=args.rebuild, quiet=args.quiet)
    print(json.dumps(st, indent=1))
    print(json.dumps(index.status(), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
