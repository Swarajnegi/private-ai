#!/usr/bin/env python3
"""
pipeline_health.py — every way JARVIS's memory pipeline can be quietly broken, in one place.

LAYER: Tools (verification) — module + CLI

Run with:
    python scripts/pipeline_health.py            # human report; exit 1 on any breach
    python scripts/pipeline_health.py --brief    # one line per breach; NOTHING when healthy
    python scripts/pipeline_health.py --json     # the whole report, machine-readable
    python scripts/pipeline_health.py --self-test

=============================================================================
THE BIG PICTURE
=============================================================================

Measured 2026-09-28: `curate_turns` had FAILED 185 of 195 runs since 09-15,
`reindex_memory` 16 of 17 (hidden behind a guard-skip that overwrote its
status), 1,833 turns were uncurated, and the only boot check any agent ran
asked whether the hearth answered HTTP 200. Every one of those was recorded
somewhere. None was in front of anyone.

This is the one implementation of "is the pipeline actually working?", and it
is read from four places so no agent can miss it:

    Claude Code  — SessionStart hook (scripts/hooks/surface_pipeline_health.py)
    Codex, Antigravity — scripts/bootstrap_jarvis.py --check, run at boot
    JARVIS       — the "Pipeline health" inhale provider (context_injector)
    the web UI   — GET /v1/health -> the System page

A breach is a sentence a person can act on. It is never cut, and a check that
crashes is itself a breach — a check that cannot run proves nothing.

=============================================================================
THRESHOLDS (and why each is where it is)
=============================================================================

    job stale        last success older than 2x the job's interval. One missed
                     run is noise; two in a row is a stopped job. A job that
                     never succeeded gets its initial delay + one interval.
    job failing      ANY consecutive failure. The owner's rule is that every
                     failure is impossible to miss, so the bar is one.
    clock stopped    no job ran in 2 h (the most frequent jobs run every 15-60 min).
    parse backlog    per host: oldest unparsed turn older than 24 h, or more
                     than 200 pending. Parsing happens every ~10 turns, so a
                     day-old turn means the host's agent skipped its parse.
    corpora          a training_corpus/*.jsonl older than 48 h (rebuilt daily).
    projections      whatever brain/projections.run_checks says is stale.
    no truncation    check_pipeline's truncation invariants, any FAIL.
    chroma server   the hearth is up but the Chroma server it supervises (the ONE owner of
                     jarvis_data/chromadb, memory/chroma_access.py) is not answering its
                     heartbeat. Silent when the hearth is down: direct mode is legal then.
    inhale size      the whole voice inhale above 80% of the smallest context
                     window in the voice chain — past that there is no room
                     left for the conversation and the answer.

=============================================================================
THE FLOW
=============================================================================

STEP 1: run each check inside its own try: a crash becomes a breach naming it.
        |
STEP 2: collect breaches [{check, detail}] plus per-check detail for the UI.
        |
STEP 3: healthy = no breaches. CLI exit 0 healthy, 1 breached.
=============================================================================
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = _ROOT / "scripts"
for _p in (str(_ROOT / "js-development"), str(_SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_IST = timezone(timedelta(hours=5, minutes=30))

JOB_STALE_FACTOR = 2.0
CONSECUTIVE_FAILURE_LIMIT = 1
CLOCK_STOPPED_S = 2 * 3600.0
BACKLOG_MAX_AGE_H = 24.0
BACKLOG_MAX_PENDING = 200
CORPUS_MAX_AGE_H = 48.0
INHALE_WINDOW_FRACTION = 0.8

Breach = Dict[str, Any]


def _ago(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds < 3600:
        return f"{seconds / 60:.0f} min"
    if seconds < 48 * 3600:
        return f"{seconds / 3600:.1f} h"
    return f"{seconds / 86400:.1f} d"


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, _IST).isoformat(timespec="seconds") if ts else ""


def _parse_iso(ts: str) -> Optional[float]:
    try:
        dt = datetime.fromisoformat(str(ts))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_IST)
    return dt.timestamp()


# =============================================================================
# Part 1: SOURCES (every input injectable, so the self-test never reads the repo)
# =============================================================================

@dataclass
class Sources:
    root: Path = _ROOT
    state_path: Optional[Path] = None
    jobs: Optional[Callable[[], List[Any]]] = None
    backlog: Optional[Callable[[], Dict[str, Dict[str, Any]]]] = None
    inhales: Optional[Callable[[Path], Dict[str, str]]] = None
    truncation: Optional[Callable[[Path, Dict[str, str]], List[Any]]] = None
    projections: Optional[Callable[[], List[Dict[str, Any]]]] = None
    chroma: Optional[Callable[[], Dict[str, Any]]] = None
    chain: Optional[Callable[[], List[str]]] = None
    catalog_path: Optional[Path] = None
    count_tokens: Optional[Callable[[str, str], int]] = None
    system_prefix: Optional[Callable[[], str]] = None


def _default_jobs() -> List[Any]:
    from jarvis_core.serve.scheduler import default_jobs
    return default_jobs()


def _default_state_path() -> Path:
    from jarvis_core.serve.scheduler import STATE_PATH
    return Path(STATE_PATH)


def _default_backlog() -> Dict[str, Dict[str, Any]]:
    from jarvis_core.agent.parse_ledger import backlog
    return backlog()


def _default_inhales(root: Path) -> Dict[str, str]:
    import check_pipeline
    return check_pipeline.default_inhales(root)


def _default_truncation(root: Path, inhales: Dict[str, str]) -> List[Any]:
    import check_pipeline
    return check_pipeline.truncation_findings(root, inhales)


def _default_projections() -> List[Dict[str, Any]]:
    """run_checks + id collisions. The domain-classifier accuracy check is left
    to check_projections.py: it loads an embedding model (~100 s cold), which a
    boot-time health check cannot afford."""
    from jarvis_core.brain.projections import id_collisions, run_checks
    checks, expected, _newest = run_checks()
    out = [{"name": c.name, "stale": c.stale, "detail": c.detail, "fix": c.fix,
            "expected": expected} for c in checks]
    collisions = id_collisions()
    if collisions:
        out.append({"name": "kb id uniqueness", "stale": True,
                    "detail": f"{len(collisions)} duplicated id(s): "
                              + ", ".join(f"id {i} x{n}" for i, n in sorted(collisions.items())),
                    "fix": "python scripts/kb_append.py --audit", "expected": expected})
    return out


def _default_chroma() -> Dict[str, Any]:
    """Is the hearth up, and is the Chroma server it supervises answering?"""
    import socket
    from jarvis_core.config import DB_ROOT
    from jarvis_core.memory.chroma_access import lock_holder, lock_path, server_state
    from jarvis_core.serve.hearth import DEFAULT_HOST, DEFAULT_PORT
    try:
        with socket.create_connection((DEFAULT_HOST, DEFAULT_PORT), timeout=1):
            hearth_up = True
    except OSError:
        hearth_up = False
    st = server_state(Path(DB_ROOT))
    holder = lock_holder(lock_path(Path(DB_ROOT)))
    return {"hearth_up": hearth_up, "server_up": st.up, "has_descriptor": st.has_descriptor,
            "pid": st.pid, "port": st.port, "started": st.started,
            "owner": f"pid {holder.get('pid')} ({holder.get('role')}, {holder.get('argv0')})" if holder else ""}


def _default_chain() -> List[str]:
    from jarvis_core.brain.voice_path import free_chain, load_chain
    chain = load_chain()
    return list(dict.fromkeys(chain + free_chain(chain)))


def _default_count_tokens(text: str, model: str) -> int:
    from jarvis_core.agent.tokens import shared_counter
    return shared_counter().count(text, model)


def _default_system_prefix() -> str:
    from jarvis_core.agent.mind import JARVIS_PSYCHE_PROMPT
    from jarvis_core.brain.voice_path import VOICE_REGISTER
    return JARVIS_PSYCHE_PROMPT + "\n\n" + VOICE_REGISTER + "\n\n"


# =============================================================================
# Part 2: THE CHECKS — each returns (breaches, detail for the report)
# =============================================================================

def check_jobs(now: float, jobs: List[Any], state_path: Path) -> Tuple[List[Breach], Any]:
    from jarvis_core.serve.scheduler import JobState
    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    breaches: List[Breach] = []
    rows: List[Dict[str, Any]] = []
    newest_run = 0.0
    from jarvis_core.serve.scheduler import paused_jobs
    paused = paused_jobs(state_path.parent)
    for job in jobs:
        interval = float(job.interval_seconds)
        if job.name in paused:
            rows.append({"name": job.name, "status": "paused by owner (jarvis_data/.paused_jobs)",
                         "healthy": True})
            continue
        entry = raw.get(job.name)
        if entry is None:
            breaches.append({"check": f"job:{job.name}",
                             "detail": f"never scheduled — no run of {job.name} has ever been "
                                       f"recorded by a hearth on this machine. If it was added "
                                       f"recently the running hearth predates it: restart the hearth."})
            rows.append({"name": job.name, "status": "never scheduled", "healthy": False})
            continue
        st = JobState.from_dict(entry)
        newest_run = max(newest_run, st.last_run)
        problems: List[str] = []
        output = ""
        if st.consecutive_failures >= CONSECUTIVE_FAILURE_LIMIT:
            problems.append(
                f"{st.consecutive_failures} consecutive failure(s), last rc={st.last_rc} "
                f"{_ago(now - st.last_failure_ts) if st.last_failure_ts else '(time unknown)'} ago; "
                f"{st.failures} of {st.runs} runs failed in total. Whole output: "
                f"python scripts/pipeline_health.py --json")
            output = st.last_output
        allowed = JOB_STALE_FACTOR * interval
        if st.last_success_ts:
            age = now - st.last_success_ts
            if age > allowed:
                problems.append(f"last success {_ago(age)} ago, allowed {_ago(allowed)} "
                                f"(2x its {_ago(interval)} interval)")
        else:
            since = st.first_seen_ts or st.last_run
            grace = float(getattr(job, "initial_delay_seconds", 0.0)) + interval
            if not since or now - since > grace:
                problems.append("has never succeeded" + (
                    f" in the {_ago(now - since)} since it was first scheduled "
                    f"(grace: initial delay + one interval = {_ago(grace)})" if since else ""))
        if problems:
            b: Breach = {"check": f"job:{job.name}", "detail": "; ".join(problems)}
            if output:
                b["output"] = output
            breaches.append(b)
        rows.append({"name": job.name, "status": st.last_status, "healthy": not problems,
                     "last_rc": st.last_rc, "consecutive_failures": st.consecutive_failures,
                     "last_success": _iso(st.last_success_ts), "last_failure": _iso(st.last_failure_ts),
                     "every_hours": round(interval / 3600, 2)})
    if jobs and (not newest_run or now - newest_run > CLOCK_STOPPED_S):
        breaches.insert(0, {"check": "clock",
                            "detail": ("no scheduled job has run in "
                                       + (_ago(now - newest_run) if newest_run else "recorded history")
                                       + " — the hearth's clock appears stopped. Start it: "
                                         "python scripts/hearth.py --background (Windows: "
                                         "python scripts/windows_hearth_watchdog.py --install)")})
    return breaches, rows


def check_backlog(now: float, backlog: Dict[str, Dict[str, Any]]) -> Tuple[List[Breach], Any]:
    breaches: List[Breach] = []
    detail: Dict[str, Dict[str, Any]] = {}
    for host, slot in backlog.items():
        pending = int(slot.get("pending") or 0)
        oldest = str(slot.get("oldest") or "")
        oldest_ts = _parse_iso(oldest) if oldest else None
        age_h = round((now - oldest_ts) / 3600, 1) if oldest_ts else None
        detail[host] = {"pending": pending, "oldest": oldest, "oldest_age_h": age_h}
        if not pending:
            continue
        problems: List[str] = []
        if age_h is not None and age_h > BACKLOG_MAX_AGE_H:
            problems.append(f"oldest is {_ago(age_h * 3600)} old (limit {BACKLOG_MAX_AGE_H:.0f} h)")
        if pending > BACKLOG_MAX_PENDING:
            problems.append(f"{pending} pending (limit {BACKLOG_MAX_PENDING})")
        if host == "unknown":
            problems.append("no host can be attributed to these turns, so no agent will parse them")
        if problems:
            fix = ("fix host attribution in jarvis_core/agent/parse_ledger.py host_of()"
                   if host == "unknown" else f"python scripts/parse_turns.py --pending --host {host}")
            breaches.append({"check": f"backlog:{host}",
                             "detail": f"{pending} unparsed turn(s), oldest {oldest or 'unknown'} — "
                                       + "; ".join(problems) + f". Fix: {fix}"})
    return breaches, detail


def check_corpora(now: float, root: Path) -> Tuple[List[Breach], Any]:
    corpus_dir = root / "jarvis_data" / "training_corpus"
    files = sorted(corpus_dir.glob("*.jsonl")) if corpus_dir.is_dir() else []
    if not files:
        return ([{"check": "corpora", "detail": f"no training corpora in {corpus_dir}. "
                                                "Build: python scripts/rebuild_corpora.py"}], {})
    breaches: List[Breach] = []
    detail: Dict[str, Any] = {}
    for f in files:
        age = now - f.stat().st_mtime
        detail[f.name] = {"age_h": round(age / 3600, 1), "bytes": f.stat().st_size}
        if age > CORPUS_MAX_AGE_H * 3600:
            breaches.append({"check": f"corpus:{f.name}",
                             "detail": f"last rebuilt {_ago(age)} ago (limit {CORPUS_MAX_AGE_H:.0f} h). "
                                       "Fix: python scripts/rebuild_corpora.py"})
    return breaches, detail


def check_projections(rows: List[Dict[str, Any]]) -> Tuple[List[Breach], Any]:
    breaches = [{"check": f"projection:{r['name']}",
                 "detail": f"stale — knowledge base has {r.get('expected')} entries, "
                           f"{r['name']} at {r['detail']}. Fix: {r['fix']}"}
                for r in rows if r.get("stale")]
    return breaches, rows


def check_chroma(state: Dict[str, Any]) -> Tuple[List[Breach], Any]:
    """The hearth is what starts and supervises the Chroma server, so a hearth
    that is up with no answering server means every job is failing (or, worse,
    was left to open the store itself)."""
    if not state.get("hearth_up") or state.get("server_up"):
        return [], state
    if state.get("has_descriptor"):
        why = (f"the descriptor names pid {state.get('pid')} on port {state.get('port')} "
               f"but its heartbeat does not answer")
    else:
        why = "there is no descriptor, so the server never started or was stopped"
    owner = state.get("owner")
    return ([{"check": "chroma server",
              "detail": f"the hearth is up but the Chroma server is not answering — {why}"
                        + (f"; the store's owner lock says {owner}" if owner else "")
                        + ". Every memory read and write from the hearth and its jobs is failing. "
                          "Look at jarvis_data/chroma_server.log; the hearth's monitor retries every "
                          "10 s, a direct-mode script holding the files blocks it. "
                          "Inspect: python -m jarvis_core.serve.chroma_server --status; or restart "
                          "the hearth (python scripts/hearth.py --stop, then start it)."}], state)


def check_truncation(findings: List[Any]) -> Tuple[List[Breach], Any]:
    rows = [{"name": f.name, "status": f.status, "detail": f.detail} for f in findings]
    breaches = [{"check": "no-truncation", "detail": f"{f.name}: {f.detail}"}
                for f in findings if f.status == "FAIL"]
    return breaches, rows


def check_inhale(voice_block: str, prefix: str, chain: List[str], catalog_path: Path,
                 count: Callable[[str, str], int]) -> Tuple[List[Breach], Any]:
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    windows = {str(m.get("id")): int(m.get("context_length") or 0)
               for m in catalog if isinstance(m, dict)}
    text = prefix + voice_block
    models: List[Dict[str, Any]] = []
    unknown: List[str] = []
    for model in chain:
        window = windows.get(model) or windows.get(model.split(":")[0]) or 0
        if not window:
            unknown.append(model)
            continue
        tokens = count(text, model)
        models.append({"model": model, "context_length": window, "tokens": tokens,
                       "fraction": round(tokens / window, 3)})
    detail = {"chars": len(text), "inhale_chars": len(voice_block), "models": models,
              "unknown_context": unknown}
    if not models:
        return ([{"check": "inhale", "detail": "no voice-chain model has a known context length "
                                               f"in {catalog_path.name}: " + ", ".join(chain)}], detail)
    smallest = min(models, key=lambda m: m["context_length"])
    detail["smallest"] = smallest
    breaches = [{"check": "inhale",
                 "detail": f"the whole voice inhale is {m['tokens']:,} tokens ({len(text):,} chars), "
                           f"{m['fraction']:.0%} of {m['model']}'s {m['context_length']:,}-token window "
                           f"(limit {INHALE_WINDOW_FRACTION:.0%}) — no room is left for the conversation "
                           f"and the answer. Page the profile; never cut it."}
                for m in models if m["tokens"] > INHALE_WINDOW_FRACTION * m["context_length"]]
    return breaches, detail


# =============================================================================
# Part 3: THE REPORT
# =============================================================================

def health_report(sources: Optional[Sources] = None, now: Optional[float] = None) -> Dict[str, Any]:
    """Every check, each isolated. Never raises."""
    src = sources or Sources()
    t0 = time.perf_counter()
    moment = time.time() if now is None else now
    breaches: List[Breach] = []
    sections: Dict[str, Any] = {}
    errors: List[str] = []

    def guarded(name: str, fn: Callable[[], Tuple[List[Breach], Any]]) -> None:
        try:
            found, detail = fn()
            breaches.extend(found)
            sections[name] = detail
        except Exception as e:                                      # noqa: BLE001
            tb = traceback.format_exc()
            errors.append(f"{name}: {tb}")
            breaches.append({"check": name,
                             "detail": f"the {name} check itself crashed ({type(e).__name__}: {e}) — "
                                       f"its subject is UNVERIFIED, not healthy",
                             "output": tb})

    guarded("jobs", lambda: check_jobs(moment, (src.jobs or _default_jobs)(),
                                       src.state_path or _default_state_path()))
    guarded("backlog", lambda: check_backlog(moment, (src.backlog or _default_backlog)()))
    guarded("corpora", lambda: check_corpora(moment, src.root))
    guarded("projections", lambda: check_projections((src.projections or _default_projections)()))
    guarded("chroma", lambda: check_chroma((src.chroma or _default_chroma)()))

    inhales: Dict[str, str] = {}

    def build_inhales() -> Tuple[List[Breach], Any]:
        inhales.update((src.inhales or _default_inhales)(src.root))
        return [], {name: len(block) for name, block in inhales.items()}

    guarded("inhales", build_inhales)
    if inhales:
        guarded("truncation", lambda: check_truncation(
            (src.truncation or _default_truncation)(src.root, inhales)))
        guarded("inhale", lambda: check_inhale(
            inhales.get("voice inhale", ""), (src.system_prefix or _default_system_prefix)(),
            (src.chain or _default_chain)(),
            src.catalog_path or (src.root / "jarvis_data" / "model_catalog.json"),
            src.count_tokens or _default_count_tokens))
    return {
        "healthy": not breaches,
        "generated_at": _iso(moment),
        "elapsed_s": round(time.perf_counter() - t0, 2),
        "breaches": breaches,
        "backlog": sections.get("backlog", {}),
        "sections": sections,
        "errors": errors,
        "thresholds": {
            "job_stale_factor": JOB_STALE_FACTOR,
            "consecutive_failure_limit": CONSECUTIVE_FAILURE_LIMIT,
            "clock_stopped_h": CLOCK_STOPPED_S / 3600,
            "backlog_max_age_h": BACKLOG_MAX_AGE_H,
            "backlog_max_pending": BACKLOG_MAX_PENDING,
            "corpus_max_age_h": CORPUS_MAX_AGE_H,
            "inhale_window_fraction": INHALE_WINDOW_FRACTION,
        },
    }


def brief_lines(report: Optional[Dict[str, Any]]) -> List[str]:
    """One line per breach, whole. Empty when healthy or not yet computed."""
    if not report:
        return []
    return [f"[{b.get('check')}] {' '.join(str(b.get('detail', '')).split())}"
            for b in report.get("breaches", [])]


_CACHE: Dict[str, Any] = {"at": 0.0, "report": None, "refreshing": False}
_CACHE_LOCK = threading.Lock()


def _refresh_cache() -> None:
    try:
        report = health_report()
    except Exception as e:                                          # noqa: BLE001  (health_report never raises; belt and braces)
        report = {"healthy": False, "breaches": [{"check": "pipeline_health",
                                                  "detail": f"crashed: {type(e).__name__}: {e}"}]}
    with _CACHE_LOCK:
        _CACHE.update(at=time.monotonic(), report=report, refreshing=False)


def cached_report(max_age_s: float = 60.0, block: bool = True) -> Optional[Dict[str, Any]]:
    """The last report if younger than max_age_s, else a fresh one.

    block=False never waits: it returns whatever is cached (None before the
    first report exists) and refreshes on a daemon thread. That is the form
    /v1/health uses, so a health probe stays instant.
    """
    with _CACHE_LOCK:
        fresh = _CACHE["report"] is not None and time.monotonic() - _CACHE["at"] < max_age_s
        if fresh:
            return _CACHE["report"]
        if not block:
            if not _CACHE["refreshing"]:
                _CACHE["refreshing"] = True
                threading.Thread(target=_refresh_cache, daemon=True, name="pipeline-health").start()
            return _CACHE["report"]
    _refresh_cache()
    return _CACHE["report"]


def _print_human(report: Dict[str, Any]) -> None:
    print("=" * 78)
    n = len(report["breaches"])
    headline = "HEALTHY" if report["healthy"] else f"{n} BREACH(ES)"
    print(f"  PIPELINE HEALTH — {headline}   ({report['generated_at']}, {report['elapsed_s']} s)")
    print("=" * 78)
    for b in report["breaches"]:
        print(f"  BREACH {b['check']}")
        print(f"         {b['detail']}")
        if b.get("output"):
            print("         --- whole output of the last failed run ---")
            for line in str(b["output"]).splitlines():
                print(f"         | {line}")
    backlog = report.get("backlog") or {}
    if backlog:
        print("-" * 78)
        print("  parse backlog per host:")
        for host, slot in backlog.items():
            age = f"{slot['oldest_age_h']} h" if slot.get("oldest_age_h") is not None else "-"
            print(f"    {host:<12} {slot['pending']:>6} pending   oldest {slot['oldest'] or '-'} ({age})")
    inhale = (report.get("sections") or {}).get("inhale") or {}
    if inhale.get("smallest"):
        s = inhale["smallest"]
        print(f"  voice inhale: {inhale['chars']:,} chars = {s['tokens']:,} tokens, "
              f"{s['fraction']:.0%} of the smallest window ({s['model']}, {s['context_length']:,})")
    print("=" * 78)


# =============================================================================
# SELF-TEST (temp fixtures only; never reads the real repo's data)
# =============================================================================

def _self_test() -> int:
    import os
    import tempfile
    from types import SimpleNamespace

    passed, failed = 0, []

    def check(name: str, ok: bool, hint: str = "") -> None:
        nonlocal passed
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  {hint}"))
        if ok:
            passed += 1
        else:
            failed.append(name)

    print("=" * 70)
    print("  pipeline_health.py -- self-test (temp fixtures)")
    print("=" * 70)
    H = 3600.0
    now = 2_000_000_000.0

    def job(name: str, every_h: float, delay_s: float = 60.0) -> Any:
        return SimpleNamespace(name=name, interval_seconds=every_h * H, initial_delay_seconds=delay_s)

    Finding = SimpleNamespace
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        corpus = root / "jarvis_data" / "training_corpus"
        corpus.mkdir(parents=True)
        for n in ("engineer_corpus.jsonl", "blended_corpus.jsonl"):
            (corpus / n).write_text("{}\n", encoding="utf-8")
            os.utime(corpus / n, (now - H, now - H))
        catalog = root / "jarvis_data" / "model_catalog.json"
        catalog.write_text(json.dumps([{"id": "big/model", "context_length": 1_000_000},
                                       {"id": "small/model", "context_length": 1000}]), encoding="utf-8")
        state = root / "jobs.json"
        healthy_state = {
            "ok_job": {"last_run": now - 60, "last_rc": 0, "last_status": "ok",
                       "last_success_ts": now - 60, "consecutive_failures": 0, "first_seen_ts": now - 9 * H},
        }
        state.write_text(json.dumps(healthy_state), encoding="utf-8")

        def sources(**over: Any) -> Sources:
            base = dict(
                root=root, state_path=state, jobs=lambda: [job("ok_job", 1)],
                backlog=lambda: {"claude": {"pending": 3, "oldest": _iso(now - H)},
                                 "codex": {"pending": 0, "oldest": ""}},
                inhales=lambda r: {"voice inhale": "PROFILE", "boot inhale": "PROFILE"},
                truncation=lambda r, i: [Finding(name="profile whole", status="OK", detail="fine")],
                projections=lambda: [{"name": "cognitive_profile.md", "stale": False,
                                      "detail": "5", "fix": "x", "expected": 5}],
                chroma=lambda: {"hearth_up": True, "server_up": True, "has_descriptor": True},
                chain=lambda: ["big/model"], catalog_path=catalog,
                count_tokens=lambda text, model: len(text) // 4, system_prefix=lambda: "SYS ")
            base.update(over)
            return Sources(**base)

        r = health_report(sources(), now=now)
        check("T1 a healthy fixture reports healthy with no breaches",
              r["healthy"] and r["breaches"] == [], json.dumps(r["breaches"]))
        check("T2 --brief form of a healthy report is empty", brief_lines(r) == [])

        def breached(r: Dict[str, Any], check_name: str) -> List[Breach]:
            return [b for b in r["breaches"] if b["check"] == check_name]

        # T3: a failure hidden behind a guard-skip (the reindex_memory shape).
        state.write_text(json.dumps({"reindex": {
            "last_run": now - 60, "last_rc": 1, "last_status": "skipped — guard reports nothing to do",
            "last_output": "Traceback ... chromadb upsert failed " + "y" * 4000 + " END",
            "runs": 17, "failures": 16, "skipped": 14}}), encoding="utf-8")
        r = health_report(sources(jobs=lambda: [job("reindex", 12)]), now=now)
        b = breached(r, "job:reindex")
        check("T3 a failure masked by a legacy guard-skip is a breach",
              bool(b) and "consecutive failure" in b[0]["detail"] and "16 of 17" in b[0]["detail"],
              json.dumps(r["breaches"])[:300])
        check("T4 the breach carries the whole failed output", bool(b) and b[0].get("output", "").endswith("END")
              and "y" * 4000 in b[0]["output"])

        # T5: stale job (last success > 2x interval).
        state.write_text(json.dumps({"digest": {"last_run": now - 20 * H, "last_rc": 0, "last_status": "ok",
                                                "last_success_ts": now - 20 * H, "consecutive_failures": 0,
                                                "first_seen_ts": now - 99 * H}}), encoding="utf-8")
        r = health_report(sources(jobs=lambda: [job("digest", 6)]), now=now)
        check("T5 a job whose last success is older than 2x its interval is a breach",
              bool(breached(r, "job:digest")) and "last success" in breached(r, "job:digest")[0]["detail"])
        check("T5b ...and with every job that old, the stopped clock is called out",
              bool(breached(r, "clock")))

        # T6-T7: never succeeded — inside vs outside its grace.
        state.write_text(json.dumps({"fresh": {"last_run": 0, "last_rc": None, "last_status": "never run",
                                               "consecutive_failures": 0, "first_seen_ts": now - 60},
                                     "ok_job": healthy_state["ok_job"]}), encoding="utf-8")
        r = health_report(sources(jobs=lambda: [job("fresh", 1, 600), job("ok_job", 1)]), now=now)
        check("T6 a new job inside initial delay + interval is not yet a breach",
              not breached(r, "job:fresh"), json.dumps(r["breaches"]))
        state.write_text(json.dumps({"fresh": {"last_run": 0, "last_rc": None, "last_status": "never run",
                                               "consecutive_failures": 0, "first_seen_ts": now - 3 * H},
                                     "ok_job": healthy_state["ok_job"]}), encoding="utf-8")
        r = health_report(sources(jobs=lambda: [job("fresh", 1, 600), job("ok_job", 1)]), now=now)
        check("T7 a job that never succeeded past its grace IS a breach",
              bool(breached(r, "job:fresh")) and "never succeeded" in breached(r, "job:fresh")[0]["detail"])
        r = health_report(sources(jobs=lambda: [job("ok_job", 1), job("ghost", 1)]), now=now)
        check("T7b a scheduled job with no recorded state is a breach (hearth predates it)",
              bool(breached(r, "job:ghost")) and "restart the hearth" in breached(r, "job:ghost")[0]["detail"])

        state.write_text(json.dumps(healthy_state), encoding="utf-8")
        # T8-T10: parse backlog per host.
        r = health_report(sources(backlog=lambda: {
            "claude": {"pending": 250, "oldest": _iso(now - 2 * H)},
            "codex": {"pending": 5, "oldest": _iso(now - 30 * H)},
            "jarvis": {"pending": 4, "oldest": _iso(now - H)},
            "unknown": {"pending": 2, "oldest": _iso(now - H)}}), now=now)
        check("T8 more than 200 pending on a host is a breach, with the count",
              bool(breached(r, "backlog:claude")) and "250 pending" in breached(r, "backlog:claude")[0]["detail"])
        check("T9 an oldest turn older than 24 h is a breach, with its age",
              bool(breached(r, "backlog:codex")) and "30.0 h old" in breached(r, "backlog:codex")[0]["detail"])
        check("T10 a small fresh backlog is fine; unattributable turns are not",
              not breached(r, "backlog:jarvis") and bool(breached(r, "backlog:unknown")))
        check("T10b the per-host backlog is in the report for the UI",
              r["backlog"]["codex"]["pending"] == 5 and r["backlog"]["codex"]["oldest_age_h"] == 30.0,
              json.dumps(r["backlog"]))

        # T11: corpus older than 48 h.
        os.utime(corpus / "blended_corpus.jsonl", (now - 50 * H, now - 50 * H))
        r = health_report(sources(), now=now)
        check("T11 a corpus older than 48 h is a breach; a fresh one is not",
              bool(breached(r, "corpus:blended_corpus.jsonl")) and not breached(r, "corpus:engineer_corpus.jsonl"))
        os.utime(corpus / "blended_corpus.jsonl", (now - H, now - H))

        # T12: stale projection.
        r = health_report(sources(projections=lambda: [{"name": "chromadb/jarvis_memory", "stale": True,
                                                         "detail": "600 (-78)", "fix": "python scripts/index_memory.py",
                                                         "expected": 678}]), now=now)
        check("T12 a stale projection is a breach with its fix",
              bool(breached(r, "projection:chromadb/jarvis_memory"))
              and "index_memory.py" in breached(r, "projection:chromadb/jarvis_memory")[0]["detail"])

        # T12b: the hearth is up but its Chroma server is not.
        r = health_report(sources(chroma=lambda: {"hearth_up": True, "server_up": False, "has_descriptor": True,
                                                  "pid": 4242, "port": 8759, "owner": "pid 4242 (server, x)"}), now=now)
        cb = breached(r, "chroma server")
        check("T12b hearth up + Chroma server down is a breach naming the pid and the log",
              len(cb) == 1 and "4242" in cb[0]["detail"] and "chroma_server.log" in cb[0]["detail"], json.dumps(cb)[:300])
        r = health_report(sources(chroma=lambda: {"hearth_up": False, "server_up": False, "has_descriptor": False}),
                          now=now)
        check("T12c hearth down is not a Chroma breach (direct mode is legal without the hearth)",
              not breached(r, "chroma server"))

        # T13: a truncation invariant failing.
        r = health_report(sources(truncation=lambda root_, i: [
            Finding(name="voice inhale carries whole cognitive_profile.md", status="FAIL", detail="present but CUT"),
            Finding(name="session distills", status="UNKNOWN", detail="none")]), now=now)
        check("T13 a FAILing truncation invariant is a breach; UNKNOWN is reported, not breached",
              len(breached(r, "no-truncation")) == 1
              and "present but CUT" in breached(r, "no-truncation")[0]["detail"])

        # T14: inhale above 80% of the smallest window.
        r = health_report(sources(chain=lambda: ["big/model", "small/model", "router/free"],
                                  inhales=lambda root_: {"voice inhale": "x" * 4000, "boot inhale": "x"}), now=now)
        inh = breached(r, "inhale")
        check("T14 an inhale above 80% of the smallest context window is a breach",
              len(inh) == 1 and "small/model" in inh[0]["detail"], json.dumps(inh))
        check("T14b the smallest window and unknown-context models are reported",
              r["sections"]["inhale"]["smallest"]["model"] == "small/model"
              and r["sections"]["inhale"]["unknown_context"] == ["router/free"])

        # T15: an exception in one check becomes a breach; the others still run.
        def boom() -> Dict[str, Dict[str, Any]]:
            raise RuntimeError("queue unreadable")
        r = health_report(sources(backlog=boom), now=now)
        check("T15 a crashing check is a breach naming it, and the rest still ran",
              bool(breached(r, "backlog")) and "crashed (RuntimeError: queue unreadable)"
              in breached(r, "backlog")[0]["detail"] and "corpora" in r["sections"], json.dumps(r["breaches"])[:300])

        # T16: brief lines are whole, one per breach, single-line.
        long_detail = "d" * 3000
        lines = brief_lines({"breaches": [{"check": "a", "detail": long_detail + "\nsecond line"},
                                          {"check": "b", "detail": "x"}]})
        check("T16 brief: one whole line per breach, newlines folded, nothing cut",
              len(lines) == 2 and long_detail in lines[0] and "\n" not in lines[0])

        # T17: the non-blocking cache returns at once and refreshes in the background.
        calls = {"n": 0}
        real = globals()["health_report"]

        def slow_report(*_a: Any, **_k: Any) -> Dict[str, Any]:
            calls["n"] += 1
            time.sleep(0.3)
            return {"healthy": True, "breaches": []}
        globals()["health_report"] = slow_report
        try:
            _CACHE.update(at=0.0, report=None, refreshing=False)
            t = time.perf_counter()
            first = cached_report(block=False)
            waited = time.perf_counter() - t
            check("T17 block=False never waits (None before the first report)",
                  first is None and waited < 0.1, f"{first} {waited:.2f}s")
            time.sleep(0.5)
            check("T17b ...and the background refresh lands in the cache",
                  cached_report(block=False) == {"healthy": True, "breaches": []})
            cached_report(max_age_s=60.0)
            check("T17c a fresh cache is served without recomputing", calls["n"] == 1, str(calls))
        finally:
            globals()["health_report"] = real
            _CACHE.update(at=0.0, report=None, refreshing=False)

    print("-" * 70)
    print(f"  {passed} passed, {len(failed)} failed")
    print("=" * 70)
    return 1 if failed else 0


def main() -> int:
    p = argparse.ArgumentParser(description="Is JARVIS's memory pipeline actually working? Exit 1 on any breach.")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--json", action="store_true", help="the whole report as JSON")
    g.add_argument("--brief", action="store_true", help="one line per breach; prints nothing when healthy")
    g.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    if args.self_test:
        return _self_test()
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    report = health_report()
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    elif args.brief:
        for line in brief_lines(report):
            print(line)
    else:
        _print_human(report)
    return 0 if report["healthy"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
