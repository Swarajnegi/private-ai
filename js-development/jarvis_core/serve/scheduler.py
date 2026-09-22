"""
scheduler.py — the clock the mind never had.

LAYER: Brain (transport shell — a timer, not a thinker)

Run with:
    python3 -m jarvis_core.serve.scheduler        # smoke tests (offline)

=============================================================================
THE BIG PICTURE
=============================================================================

ENDGAME §1.2 records a closed loop that starved JARVIS's one differentiator:

    Consolidator ran only inside Mind's heartbeat
      -> Mind booted only on --ask
        -> --ask went unused for 35 days
          -> the life-state feed froze at 3 entries
            -> the monitor fail-closed and JARVIS had nothing to say
              -> so there was no reason to open --ask.

`scripts/consolidate.py` broke the *coupling* (the consolidator can now be
driven from the capture stream, which is written every turn). It did NOT supply
a pulse: something still has to invoke it. A Stop hook fires only when a Claude
Code session ends, so JARVIS's heartbeat is still borrowed from the user's
attention.

Without a scheduler:
    -> JARVIS notices things only while being used, which is exactly when the
       user least needs to be told what they forgot.

With a scheduler:
    -> the hearth process holds a clock. Consolidation and index freshness
       happen on a cadence, whether or not anyone is looking.

WHY SUBPROCESSES AND NOT IN-PROCESS CALLS. Each job shells out to the SAME CLI
a human would run. Two reasons, both load-bearing: a job that segfaults or leaks
cannot take the server down with it, and there is exactly ONE implementation of
consolidation rather than a scheduler-flavoured copy. Core organ, thin adapter.

WHY GUARDS. A job may declare a `guard` command. The guard runs first and the
job runs only if the guard exits NON-ZERO — "fix it only if the check says it is
broken." That makes an hourly reindex cost one cheap comparison on the days
nothing changed, and it reuses the step-6 detectors instead of duplicating their
logic here.

=============================================================================
THE FLOW
=============================================================================

STEP 1: Scheduler loads .hearth_jobs.json — the last run time per job. A
        projection: delete it and the worst case is one extra early run.
        |
STEP 2: start() spawns ONE asyncio task. Every _POLL_SECONDS it calls tick().
        |
STEP 3: tick() asks each job if it is due (now - last_run >= interval, and the
        initial delay has elapsed). Due jobs run sequentially, never in
        parallel — they write the same files.
        |
STEP 4: A job with a guard runs the guard first; exit 0 means "nothing to do"
        and the job is skipped but still marked as checked.
        |
STEP 5: The result (rc, duration, tail of output) lands in the job's state and
        surfaces through GET /v1/health, so a silent scheduler is impossible.
=============================================================================
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # standalone-run safety

from jarvis_core.config import DATA_ROOT, JARVIS_ROOT

STATE_PATH = Path(DATA_ROOT) / ".hearth_jobs.json"

_POLL_SECONDS = 60.0
_DEFAULT_TIMEOUT = 1800.0
_OUTPUT_TAIL_CHARS = 400

HOUR = 3600.0


def _runtime_python(base: Path) -> str:
    """Prefer the repo virtualenv over the watchdog's base interpreter.

    On Windows ``pythonw`` may report the global Python executable even when
    the watchdog was launched from ``.venv``.  Scheduled jobs then lose the
    project dependency set and, on managed installs, can fail to spawn the
    global executable at all.  The repository venv is the explicit runtime
    contract, so select it when it exists.
    """
    candidate = base / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python3")
    return str(candidate) if candidate.is_file() else (sys.executable or "python3")


def _remote_sync_configured() -> bool:
    """Whether the local host has both machine-local sync settings.

    On native Windows the watchdog may predate a user environment update. Read
    HKCU as a narrow fallback so a restart is sufficient; on POSIX normal
    process environment inheritance remains the only mechanism.
    """
    if os.environ.get("JARVIS_REMOTE_URL") and os.environ.get("JARVIS_REMOTE_TOKEN"):
        return True
    if os.name != "nt":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
            url, _ = winreg.QueryValueEx(key, "JARVIS_REMOTE_URL")
            token, _ = winreg.QueryValueEx(key, "JARVIS_REMOTE_TOKEN")
        return bool(str(url).strip() and str(token).strip())
    except (ImportError, OSError):
        return False

# An async callable: argv, timeout -> (returncode, output tail)
Runner = Callable[[Sequence[str], float], Awaitable[Tuple[int, str]]]


# =============================================================================
# Part 1: JOB (what to run, and how often)
# =============================================================================

@dataclass(frozen=True)
class Job:
    """
    LAYER Brain: one periodic command.

    Purpose:
        - Name a command, a cadence, and (optionally) a guard that decides
          whether the command is needed at all.

    How it works:
        `argv` is run as a subprocess from JARVIS_ROOT. If `guard` is set it
        runs first; a zero exit means "already fine", so `argv` is skipped.
    """
    name: str
    argv: Tuple[str, ...]
    interval_seconds: float
    guard: Tuple[str, ...] = ()
    timeout_seconds: float = _DEFAULT_TIMEOUT
    initial_delay_seconds: float = 0.0
    description: str = ""

    def is_due(self, now: float, last_run: float, started_at: float) -> bool:
        """True when the cadence has elapsed and the startup delay has passed."""
        if now - started_at < self.initial_delay_seconds:
            return False
        return (now - last_run) >= self.interval_seconds


@dataclass
class JobState:
    """Mutable bookkeeping for one job. Serialised to .hearth_jobs.json."""
    last_run: float = 0.0
    last_rc: Optional[int] = None
    last_status: str = "never run"
    last_duration_s: float = 0.0
    last_output: str = ""
    runs: int = 0
    failures: int = 0
    skipped: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "last_run": self.last_run, "last_rc": self.last_rc,
            "last_status": self.last_status, "last_duration_s": self.last_duration_s,
            "last_output": self.last_output, "runs": self.runs,
            "failures": self.failures, "skipped": self.skipped,
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "JobState":
        s = cls()
        if not isinstance(raw, dict):
            return s
        s.last_run = float(raw.get("last_run", 0.0) or 0.0)
        s.last_rc = raw.get("last_rc")
        s.last_status = str(raw.get("last_status", "never run"))
        s.last_duration_s = float(raw.get("last_duration_s", 0.0) or 0.0)
        s.last_output = str(raw.get("last_output", ""))
        s.runs = int(raw.get("runs", 0) or 0)
        s.failures = int(raw.get("failures", 0) or 0)
        s.skipped = int(raw.get("skipped", 0) or 0)
        return s


# =============================================================================
# Part 2: THE DEFAULT JOB SET
# =============================================================================

def default_jobs(python: Optional[str] = None,
                 root: Optional[Path] = None) -> List[Job]:
    """Everything that must happen whether or not anyone is looking.

    EXECUTION FLOW:
    1. consolidate — the pulse for the surfacing organ (ENDGAME §1.2).
    2. profile/index refresh — guarded by check_projections, so it is nearly
       free on a day when the knowledge base did not change.
    3. capture + reconcile for hosts with no hook system (Codex), and the
       digest refresh that no host regenerates on its own.

    Deliberately not stating a count: this docstring said "The three things"
    while returning six, because the count was never updated when jobs 4-6 were
    added on 2026-09-10. Read the returned list, not this sentence.

    Returns:
        Jobs with absolute script paths, so cwd cannot change their meaning.
    """
    base = Path(root or JARVIS_ROOT)
    py = python or _runtime_python(base)
    scripts = base / "scripts"
    checker = str(scripts / "check_projections.py")

    # Each job guards on the projection IT can fix, via --only. A shared
    # unfiltered guard was measured broken on 2026-09-08: check_projections
    # exits non-zero if ANY projection is stale, so refresh_profile ran first,
    # fixed the two it owns, and reindex_memory then saw exit 0 and skipped —
    # meaning the vector index would never be rebuilt no matter how far it drifted.
    def guard_for(name: str) -> Tuple[str, ...]:
        return (py, checker, "--only", name)

    return [
        Job(name="consolidate",
            argv=(py, str(scripts / "consolidate.py")),
            interval_seconds=6 * HOUR,
            # Raised from 900s on 2026-09-09: this job now runs the tension
            # detector, which makes one judge call per candidate (capped at
            # --scan-limit). Embedding load plus up to 40 judged candidates does
            # not fit in 15 minutes, and a timeout would look like "no findings".
            timeout_seconds=2400.0,
            initial_delay_seconds=120.0,
            description="tension detection -> life_state_feed (the moat organ); "
                        "also persists the per-domain activity telemetry"),
        Job(name="refresh_profile",
            argv=(py, str(scripts / "profile_synth.py")),
            guard=guard_for("cognitive_profile"),
            interval_seconds=1 * HOUR,
            timeout_seconds=600.0,
            initial_delay_seconds=60.0,
            description="rebuild cognitive_index + cognitive_profile when stale"),
        Job(name="reindex_memory",
            argv=(py, str(scripts / "index_memory.py")),
            guard=guard_for("chromadb"),
            interval_seconds=12 * HOUR,
            timeout_seconds=1800.0,
            initial_delay_seconds=300.0,
            description="re-embed the knowledge base into chromadb when stale"),
        Job(name="rebuild_graphrag",
            argv=(py, str(scripts / "build_graphrag.py"), "--stats"),
            interval_seconds=6 * HOUR,
            timeout_seconds=300.0,
            initial_delay_seconds=360.0,
            description="rebuild the derived evidence-backed GraphRAG index from canonical JSONL facts"),
        # --- Added 2026-09-10: the Codex migration (ROADMAP 6.8.3) ---
        Job(name="ingest_codex",
            argv=(py, str(scripts / "ingest_codex_sessions.py")),
            interval_seconds=1 * HOUR,
            timeout_seconds=300.0,
            initial_delay_seconds=180.0,
            description="Codex capture adapter -> observation_queue.jsonl "
                        "(this job is WHY capture keeps working when this host "
                        "has no Stop-hook equivalent: see AGENTS.md CAPTURE STATUS)"),
        # --- Added 2026-09-14: Antigravity capture adapter (ROADMAP 6.8.3, Q006) ---
        Job(name="ingest_antigravity",
            argv=(py, str(scripts / "ingest_antigravity_sessions.py")),
            interval_seconds=1 * HOUR,
            timeout_seconds=300.0,
            initial_delay_seconds=240.0,
            description="Antigravity capture adapter -> observation_queue.jsonl "
                        "(closes the final host without automatic capture)"),
        Job(name="reconcile_codex_memory",
            argv=(py, str(scripts / "reconcile_codex_memory.py")),
            interval_seconds=12 * HOUR,
            timeout_seconds=300.0,
            initial_delay_seconds=420.0,
            description="promote JARVIS-relevant items from Codex's own "
                        "(global, session-scoped) memory into the one "
                        "authoritative knowledge_base.jsonl"),
        Job(name="refresh_digest",
            argv=(py, str(base / "js-development" / "jarvis_core" / "agent" / "recall.py"),
                 "--write"),
            interval_seconds=6 * HOUR,
            timeout_seconds=300.0,
            initial_delay_seconds=540.0,
            description="regenerate activity_digest.md — found 2.5 MONTHS "
                        "stale on 2026-09-10 because nothing had ever "
                        "scheduled this; Antigravity reads it at every boot"),
        # --- Added 2026-09-14: per-turn curation (the routing decision) ---
        Job(name="curate_turns",
            argv=(py, str(scripts / "curate_turns.py"), "--backlog", "40"),
            interval_seconds=1 * HOUR,
            timeout_seconds=900.0,
            initial_delay_seconds=480.0,
            description="an agent WITH conversation context decides each turn's "
                        "corpus and domain. On a clock and not on anyone's "
                        "discipline: Antigravity's manual /memory produced ZERO "
                        "records in months, which is what per-turn discipline is "
                        "worth. Batched at 40 so a cold start drains the backlog "
                        "over hours instead of one enormous bill"),
        # --- Added 2026-09-16: verification on a clock, not on attention ---
        Job(name="check_pipeline",
            argv=(py, str(scripts / "check_pipeline.py")),
            interval_seconds=6 * HOUR,
            timeout_seconds=600.0,
            initial_delay_seconds=900.0,
            description="invariants BETWEEN corpus artifacts — the class of "
                        "defect all 94 module suites are structurally blind to, "
                        "because no module owns a relationship. Caught 11.2% "
                        "duplication in blended_corpus on its first run"),
        Job(name="run_all_tests",
            argv=(py, str(scripts / "run_all_tests.py"), "--fast"),
            interval_seconds=12 * HOUR,
            timeout_seconds=1800.0,
            initial_delay_seconds=1020.0,
            description="every smoke suite in the repo. Before this existed "
                        "there was no runner at all, so 'run the tests' was not "
                        "an operation anyone could perform and 85 of 94 suites "
                        "went unrun in a working session"),
        Job(name="relabel_domains",
            argv=(py, str(scripts / "relabel_domains.py")),
            interval_seconds=12 * HOUR,
            timeout_seconds=900.0,
            initial_delay_seconds=780.0,
            description="the context-free second opinion the curator is checked "
                        "against. Found 6 days stale and covering 583 of 989 "
                        "turns on 2026-09-14 — nothing had ever scheduled it, so "
                        "the disagreement signal was silently degrading"),
        Job(name="check_commitments",
            argv=(py, str(scripts / "commitments.py"), "--due"),
            interval_seconds=6 * HOUR,
            timeout_seconds=120.0,
            initial_delay_seconds=1140.0,
            description="resolve machine-checkable commitments and surface only "
                        "explicit review-due open loops; no prose inference"),
    ] + ([
        Job(name="sync_remote_memory",
            argv=(py, str(scripts / "sync_remote_memory.py")),
            interval_seconds=15 * 60.0,
            timeout_seconds=600.0,
            initial_delay_seconds=660.0,
            description="bidirectional union-sync of authoritative facts with the hosted Context Ledger"),
    ] if _remote_sync_configured() else [])


# =============================================================================
# Part 3: THE SCHEDULER
# =============================================================================

async def _subprocess_runner(argv: Sequence[str], timeout: float) -> Tuple[int, str]:
    """Run argv from JARVIS_ROOT; return (rc, tail of combined output).

    EXECUTION FLOW:
    1. Spawn with stdout+stderr piped so a chatty job cannot fill a terminal.
    2. Wait with a timeout; on expiry kill the process group child and report
       rc 124 (the conventional timeout code) rather than hanging the clock.

    Returns:
        (returncode, last _OUTPUT_TAIL_CHARS of output). rc 127 if spawn failed.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=str(JARVIS_ROOT),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            env={**os.environ, "PYTHONUNBUFFERED": "1"})
    except (OSError, ValueError) as e:
        # Some managed Windows hosts deny a Python process spawning another
        # Python process (WinError 5), despite allowing the same entry point
        # from an interactive shell.  GraphRAG rebuild is the one scheduled
        # job that is a small, deterministic, side-effect-contained projection;
        # safely rebuild it in-process rather than silently leaving it stale.
        # Do NOT generalize this to consolidating, capture, or model work: their
        # subprocess isolation is intentionally load-bearing.
        if isinstance(e, PermissionError) and any(
            Path(part).name == "build_graphrag.py" for part in argv
        ):
            try:
                from jarvis_core.memory.graph import build_graph
                stats = build_graph()
                return 0, (f"in-process fallback after WinError 5: "
                           f"{stats.nodes} nodes, {stats.edges} edges -> {stats.path}")
            except Exception as fallback_error:
                return 127, (f"spawn failed: {type(e).__name__}: {e}; "
                             f"GraphRAG fallback failed: {type(fallback_error).__name__}: {fallback_error}")
        return 127, f"spawn failed: {type(e).__name__}: {e}"
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return 124, f"timed out after {timeout:.0f}s"
    text = (out or b"").decode("utf-8", errors="replace").strip()
    return int(proc.returncode or 0), text[-_OUTPUT_TAIL_CHARS:]


class Scheduler:
    """
    LAYER Brain: runs jobs on a cadence inside the hearth process.

    Purpose:
        - Give JARVIS a pulse that does not depend on the user's attention.
        - Make what it did visible via status() (and therefore /v1/health).

    How it works:
        One asyncio task polls every _POLL_SECONDS and runs whatever is due,
        sequentially. Every outcome is recorded; nothing fails silently.
    """

    def __init__(
        self,
        jobs: Optional[List[Job]] = None,
        state_path: Path = STATE_PATH,
        runner: Optional[Runner] = None,
        clock: Callable[[], float] = time.time,
        poll_seconds: float = _POLL_SECONDS,
        logger: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._jobs = list(jobs) if jobs is not None else default_jobs()
        self._state_path = Path(state_path)
        self._runner = runner or _subprocess_runner
        self._clock = clock
        self._poll = float(poll_seconds)
        self._log = logger or (lambda m: print(f"[hearth/clock] {m}", flush=True))
        self._states: Dict[str, JobState] = self._load()
        self._task: Optional[asyncio.Task] = None
        self._stopping = asyncio.Event()
        self._started_at = clock()

    # ---- persistence (a PROJECTION: losing it costs one early run) -------

    def _load(self) -> Dict[str, JobState]:
        try:
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, FileNotFoundError, ValueError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {str(k): JobState.from_dict(v) for k, v in raw.items()}

    def _save(self) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(
                {name: st.to_dict() for name, st in self._states.items()},
                indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._state_path)      # atomic: a crash mid-write cannot corrupt
        except OSError as e:
            self._log(f"state save failed ({type(e).__name__}) — continuing")

    def _state(self, name: str) -> JobState:
        return self._states.setdefault(name, JobState())

    # ---- one pass --------------------------------------------------------

    async def tick(self, ignore_stagger: bool = False) -> List[str]:
        """Run every due job once, sequentially. Returns the names that ran.

        EXECUTION FLOW:
        1. Snapshot the clock ONCE so all due-checks in this pass agree.
        2. For each due job: guard (if any), then the command.
        3. Persist state after each job, so a crash loses at most one result.

        Args:
            ignore_stagger: skip each job's initial_delay_seconds. That delay
                exists ONLY to avoid a thundering herd when the daemon boots;
                for a deliberate one-shot run (`hearth.py --tick-once`) it is
                pure obstruction — every job would report "not due" and the
                command would appear to work while doing nothing. Interval
                cadence is still honoured, so a one-shot cannot force a
                needless reindex.

        Returns:
            Job names actually executed (a guard-skipped job is not included).
        """
        now = self._clock()
        ready_from = 0.0 if ignore_stagger else self._started_at
        ran: List[str] = []
        for job in self._jobs:
            st = self._state(job.name)
            if not job.is_due(now, st.last_run, ready_from):
                continue
            if job.guard:
                rc, out = await self._run_one(job.guard, job.timeout_seconds, job.name)
                if rc == 0:
                    st.last_run = now
                    st.skipped += 1
                    st.last_status = "skipped — guard reports nothing to do"
                    self._save()
                    continue
                self._log(f"{job.name}: guard exit {rc} -> work needed")
            started = self._clock()
            rc, out = await self._run_one(job.argv, job.timeout_seconds, job.name)
            st.last_run = self._clock()
            st.last_duration_s = round(st.last_run - started, 2)
            st.last_rc = rc
            st.last_output = out
            st.runs += 1
            if rc == 0:
                st.last_status = "ok"
            else:
                st.failures += 1
                st.last_status = f"FAILED rc={rc}"
                self._log(f"{job.name}: FAILED rc={rc} — {out[:160]}")
            ran.append(job.name)
            self._save()
        return ran

    async def _run_one(self, argv: Sequence[str], timeout: float,
                       job_name: str) -> Tuple[int, str]:
        """Never let a job's failure escape as an exception — it is a result."""
        try:
            return await self._runner(argv, timeout)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            return 1, f"runner raised: {type(e).__name__}: {e}"

    # ---- lifecycle -------------------------------------------------------

    def start(self) -> None:
        """Spawn the polling task. Idempotent."""
        if self._task is not None and not self._task.done():
            return
        self._stopping.clear()
        self._started_at = self._clock()
        self._task = asyncio.ensure_future(self._loop())
        self._log(f"clock started — {len(self._jobs)} job(s): "
                  f"{', '.join(j.name for j in self._jobs)}")

    async def _loop(self) -> None:
        while not self._stopping.is_set():
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as e:            # the clock must never die
                self._log(f"tick raised {type(e).__name__}: {e} — continuing")
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self._poll)
            except asyncio.TimeoutError:
                continue

    async def stop(self) -> None:
        """Signal the loop and wait briefly for the in-flight job to finish."""
        self._stopping.set()
        task, self._task = self._task, None
        if task is None:
            return
        try:
            await asyncio.wait_for(task, timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            task.cancel()
        self._log("clock stopped")

    # ---- observability ---------------------------------------------------

    def status(self) -> List[Dict[str, Any]]:
        """Per-job state for GET /v1/health. A silent scheduler is a bug."""
        now = self._clock()
        out: List[Dict[str, Any]] = []
        for job in self._jobs:
            st = self._state(job.name)
            out.append({
                "name": job.name,
                "every_hours": round(job.interval_seconds / HOUR, 2),
                "guarded": bool(job.guard),
                "status": st.last_status,
                "runs": st.runs, "failures": st.failures, "skipped": st.skipped,
                "last_run_age_s": (round(now - st.last_run, 1) if st.last_run else None),
                "last_duration_s": st.last_duration_s,
                "description": job.description,
            })
        return out


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS (offline — fake runner, temp state)
# =============================================================================

def _run_self_test() -> None:
    import tempfile

    print("=" * 70)
    print("  scheduler.py -- Smoke Tests (offline: fake runner, virtual clock)")
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

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    class FakeClock:
        def __init__(self) -> None:
            self.t = 1_000_000.0

        def __call__(self) -> float:
            return self.t

        def advance(self, seconds: float) -> None:
            self.t += seconds

    def recording_runner(script: Dict[str, int]) -> Tuple[Runner, List[str]]:
        """A runner that returns scripted exit codes and logs what it ran."""
        calls: List[str] = []

        async def run(argv: Sequence[str], timeout: float) -> Tuple[int, str]:
            key = Path(argv[-1]).name if argv else "?"
            calls.append(key)
            return script.get(key, 0), f"output of {key}"

        return run, calls

    with tempfile.TemporaryDirectory() as td:
        state = Path(td) / "jobs.json"
        clock = FakeClock()

        # T1-T3: due logic.
        job = Job("j", ("true",), interval_seconds=100.0, initial_delay_seconds=10.0)
        check("T1 a job is not due before its initial delay elapses",
              not job.is_due(now=1005.0, last_run=0.0, started_at=1000.0))
        check("T2 a never-run job is due once the delay passes",
              job.is_due(now=1011.0, last_run=0.0, started_at=1000.0))
        check("T3 a just-run job is not due again",
              not job.is_due(now=1100.0, last_run=1090.0, started_at=1000.0))

        # T4-T6: tick runs due jobs and records the outcome.
        runner, calls = recording_runner({})
        sched = Scheduler(jobs=[Job("alpha", ("py", "alpha.py"), interval_seconds=100.0)],
                          state_path=state, runner=runner, clock=clock,
                          logger=lambda m: None)
        ran = loop.run_until_complete(sched.tick())
        check("T4 a due job runs on the first tick", ran == ["alpha"], str(ran))
        check("T5 it does NOT run again on an immediate second tick",
              loop.run_until_complete(sched.tick()) == [], str(calls))
        clock.advance(101.0)
        check("T6 it runs again once the interval elapses",
              loop.run_until_complete(sched.tick()) == ["alpha"])

        # T7-T8: state survives a restart (it is on disk, not in memory).
        reborn = Scheduler(jobs=[Job("alpha", ("py", "alpha.py"), interval_seconds=100.0)],
                           state_path=state, runner=runner, clock=clock,
                           logger=lambda m: None)
        check("T7 a fresh Scheduler reads the previous run time from disk",
              loop.run_until_complete(reborn.tick()) == [], "ran again after restart")
        check("T8 the run counter persisted",
              reborn.status()[0]["runs"] == 2, str(reborn.status()[0]))

        # T9-T11: guards.
        guarded = Job("fix", ("py", "fix.py"), interval_seconds=10.0,
                      guard=("py", "check.py"))
        runner_clean, calls_clean = recording_runner({"check.py": 0})
        s_clean = Scheduler(jobs=[guarded], state_path=Path(td) / "g1.json",
                            runner=runner_clean, clock=clock, logger=lambda m: None)
        ran = loop.run_until_complete(s_clean.tick())
        check("T9 guard exit 0 means the job is SKIPPED", ran == [] and "fix.py" not in calls_clean,
              str(calls_clean))
        check("T10 the skip is counted, not invisible",
              s_clean.status()[0]["skipped"] == 1
              and "guard" in s_clean.status()[0]["status"], str(s_clean.status()[0]))

        runner_dirty, calls_dirty = recording_runner({"check.py": 1})
        s_dirty = Scheduler(jobs=[guarded], state_path=Path(td) / "g2.json",
                            runner=runner_dirty, clock=clock, logger=lambda m: None)
        ran = loop.run_until_complete(s_dirty.tick())
        check("T11 guard exit 1 means the job RUNS",
              ran == ["fix"] and calls_dirty == ["check.py", "fix.py"], str(calls_dirty))

        # T12-T13: a failing job is recorded, and does not stop its siblings.
        runner_fail, _ = recording_runner({"bad.py": 3})
        s_fail = Scheduler(
            jobs=[Job("bad", ("py", "bad.py"), interval_seconds=10.0),
                  Job("good", ("py", "good.py"), interval_seconds=10.0)],
            state_path=Path(td) / "f.json", runner=runner_fail, clock=clock,
            logger=lambda m: None)
        ran = loop.run_until_complete(s_fail.tick())
        check("T12 a failing job does not prevent the next job from running",
              ran == ["bad", "good"], str(ran))
        bad_state = [j for j in s_fail.status() if j["name"] == "bad"][0]
        check("T13 the failure is recorded with its exit code",
              bad_state["failures"] == 1 and "rc=3" in bad_state["status"],
              str(bad_state))

        # T14: an exploding runner becomes a result, never an escaped exception.
        async def exploding(argv: Sequence[str], timeout: float) -> Tuple[int, str]:
            raise RuntimeError("no such interpreter")

        s_boom = Scheduler(jobs=[Job("boom", ("py", "x.py"), interval_seconds=10.0)],
                           state_path=Path(td) / "b.json", runner=exploding,
                           clock=clock, logger=lambda m: None)
        ran = loop.run_until_complete(s_boom.tick())
        boom_state = s_boom._state("boom")
        check("T14 a runner exception is captured as a failed run, with its message",
              ran == ["boom"] and boom_state.failures == 1
              and "runner raised" in boom_state.last_output
              and "no such interpreter" in boom_state.last_output,
              f"{boom_state.failures} / {boom_state.last_output[:80]}")

        # T15: corrupt state degrades to "never run" rather than crashing.
        bad_state_path = Path(td) / "corrupt.json"
        bad_state_path.write_text("{not json at all", encoding="utf-8")
        s_corrupt = Scheduler(jobs=[Job("z", ("py", "z.py"), interval_seconds=10.0)],
                              state_path=bad_state_path, runner=runner, clock=clock,
                              logger=lambda m: None)
        check("T15 corrupt state file is ignored, not fatal",
              s_corrupt.status()[0]["status"] == "never run")

        # T16: the real default job set is well-formed.
        jobs = default_jobs()
        names = [j.name for j in jobs]
        # T16 ASSERTS MEMBERSHIP, NOT POSITION, and that is a correction.
        # It previously pinned the exact list and index of every job, so it
        # broke twice from legitimate additions — curation on 2026-09-14 and
        # Antigravity's capture adapter on 2026-09-15 — each time reporting a
        # failure that was really just "someone added a job". A test that cries
        # wolf on correct changes gets edited to shut it up, which is how it
        # stops catching the thing it was written for. What actually matters is
        # that nothing SILENTLY DISAPPEARS, so the required set is asserted and
        # ordering is left alone.
        required = {"consolidate", "refresh_profile", "reindex_memory",
                    "rebuild_graphrag", "ingest_codex", "reconcile_codex_memory",
                    "refresh_digest", "curate_turns", "relabel_domains",
                    "check_commitments"}
        check("T16 no required job has silently disappeared",
              required <= set(names), f"missing: {sorted(required - set(names))}")
        check("T16a consolidate still leads (it is the unguarded pulse)",
              names[0] == "consolidate", str(names[:1]))
        # T16b: curation and its reviewer must BOTH be scheduled. Shipping the
        # curator without relabel_domains would leave the agent's verdict with
        # nothing to be checked against, which is how domain_labels.jsonl came
        # to be six days stale and unnoticed in the first place.
        check("T16b the curator and its independent second opinion are both scheduled",
              {"curate_turns", "relabel_domains"} <= set(names), str(names))
        # T16c: verification must run unprompted. Both instruments existed as
        # scripts before they were scheduled, which is exactly how
        # relabel_domains went six days stale while calling itself authoritative.
        check("T16c both verification instruments are scheduled",
              {"check_pipeline", "run_all_tests"} <= set(names), str(names))
        check("T17 consolidate is UNguarded (its whole point is to run anyway)",
              not jobs[0].guard and jobs[1].guard and jobs[2].guard)
        check("T17b each guarded job scopes its guard to the artifact IT fixes",
              jobs[1].guard[-1] == "cognitive_profile"
              and jobs[2].guard[-1] == "chromadb"
              and jobs[1].guard[-2] == jobs[2].guard[-2] == "--only",
              f"{jobs[1].guard} / {jobs[2].guard}")
        # argv[1] (right after the interpreter), not argv[-1]: refresh_digest's
        # argv carries a trailing "--write" flag after its script path, and
        # checking argv[-1] broke the moment that job was added (2026-09-10) —
        # argv[1] is the invariant every job actually satisfies, flags or not.
        check("T18 every default job points at a script that exists",
              all(Path(j.argv[1]).exists() for j in jobs),
              str([j.argv[1] for j in jobs if not Path(j.argv[1]).exists()]))
        check("T19 the jobs are staggered so startup is not a thundering herd",
              len({j.initial_delay_seconds for j in jobs}) == len(jobs))

        # T19d-T19f -- the capture and reconciliation jobs specifically.
        by_name = {j.name: j for j in jobs}
        check("T19d ingest_codex and ingest_antigravity are unguarded — they must always attempt to read "
              "new rollouts/transcripts, there is nothing to guard them on",
              not by_name["ingest_codex"].guard and not by_name["ingest_antigravity"].guard)
        check("T19e refresh_digest points at recall.py, not a scripts/ wrapper "
              "— recall.py self-inserts its own import path (verified "
              "standalone-run safe) so no PYTHONPATH env is needed here",
              "recall.py" in by_name["refresh_digest"].argv[-2]
              and by_name["refresh_digest"].argv[-1] == "--write")
        check("T19f reconcile_codex_memory runs at the same 12h cadence as "
              "reindex_memory — both are 'catch up periodically' jobs, not "
              "urgent ones",
              by_name["reconcile_codex_memory"].interval_seconds == 12 * HOUR)

        # T19b -- the stagger must not silence a DELIBERATE one-shot run. Before
        # ignore_stagger existed, `hearth.py --tick-once` printed "nothing was
        # due" and did nothing: a command that looked like it worked.
        staggered = Job("late", ("py", "late.py"), interval_seconds=10.0,
                        initial_delay_seconds=600.0)
        s_stag = Scheduler(jobs=[staggered], state_path=Path(td) / "s.json",
                           runner=runner, clock=clock, logger=lambda m: None)
        check("T19b a staggered job is NOT due on a normal first tick",
              loop.run_until_complete(s_stag.tick()) == [])
        check("T19c the same job IS due when the stagger is deliberately ignored",
              loop.run_until_complete(s_stag.tick(ignore_stagger=True)) == ["late"])

        # T20-T21: start/stop lifecycle.
        async def lifecycle() -> Tuple[bool, bool]:
            s = Scheduler(jobs=[Job("ticky", ("py", "t.py"), interval_seconds=0.01)],
                          state_path=Path(td) / "l.json", runner=runner,
                          clock=time.time, poll_seconds=0.02, logger=lambda m: None)
            s.start()
            first = s._task is not None
            await asyncio.sleep(0.08)
            await s.stop()
            return first, s._task is None

        started, stopped = loop.run_until_complete(lifecycle())
        check("T20 start() spawns the polling task", started)
        check("T21 stop() joins it and clears the handle", stopped)

    loop.close()
    print("-" * 70)
    print(f"  {passed} passed, {len(failed)} failed")
    if failed:
        for name in failed:
            print(f"    - {name}")
    print("=" * 70)
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    _run_self_test()
