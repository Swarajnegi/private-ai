"""Exclusive maintenance execution, resource admission and process-tree ownership.

LAYER: Engineer (runtime supervision). Scheduled and direct CLI work share a
lease. A child may reuse it only when the recorded owner is its actual ancestor;
an environment flag alone is never permission to bypass the lock.
"""
from __future__ import annotations

import asyncio
import ctypes
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Optional, Sequence

from jarvis_core.config import JARVIS_ROOT
from jarvis_core.locking import try_exclusive_lock

HEAVY = frozenset({"reindex_memory", "index_episodes", "relabel_domains",
                   "rebuild_corpora", "run_all_tests"})
GIB = 1024 ** 3
BUSY = 75
RESOURCE_ABORT = 76
LEASE_ENV = "JARVIS_MAINTENANCE_LEASE"


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


@dataclass(frozen=True)
class Resources:
    available_bytes: Optional[int]
    on_ac: Optional[bool]


def resources() -> Resources:
    """Native measurements; unknown measurements fail closed for heavy work."""
    if os.name == "nt":
        class Memory(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong) for name in
                ("total", "available", "page_total", "page_available", "virtual_total",
                 "virtual_available", "extended")]
        class Power(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ubyte) for name in
                        ("ac", "flags", "percent", "reserved")] + [
                            ("life", ctypes.c_ulong), ("full", ctypes.c_ulong)]
        mem, power = Memory(), Power()
        mem.length = ctypes.sizeof(mem)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        available = int(mem.available) if kernel.GlobalMemoryStatusEx(ctypes.byref(mem)) else None
        ac = (power.ac == 1) if kernel.GetSystemPowerStatus(ctypes.byref(power)) and power.ac != 255 else None
        return Resources(available, ac)
    try:
        lines = Path("/proc/meminfo").read_text(encoding="utf-8").splitlines()
        available = next(int(line.split()[1]) * 1024 for line in lines if line.startswith("MemAvailable:"))
        supplies = [p for p in Path("/sys/class/power_supply").glob("*")
                    if (p / "type").read_text(encoding="utf-8").strip() in ("Mains", "USB", "USB_C")]
        ac = any((p / "online").read_text(encoding="utf-8").strip() == "1" for p in supplies) if supplies else None
        return Resources(available, ac)
    except (OSError, StopIteration, ValueError):
        return Resources(None, None)


def admission(sample: Resources) -> str:
    if sample.available_bytes is None or sample.on_ac is None:
        return "resource measurements unavailable"
    if not sample.on_ac:
        return "waiting for mains power"
    if sample.available_bytes < 4 * GIB:
        return f"waiting for 4 GiB available RAM ({sample.available_bytes / GIB:.2f} GiB available)"
    return ""


def _parent(pid: int) -> int:
    if os.name != "nt":
        try:
            return int(Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            return 0
    from ctypes import wintypes as w
    class Entry(ctypes.Structure):
        _fields_ = [("size", w.DWORD), ("usage", w.DWORD), ("pid", w.DWORD),
                    ("heap", ctypes.c_size_t), ("module", w.DWORD), ("threads", w.DWORD),
                    ("parent", w.DWORD), ("priority", w.LONG), ("flags", w.DWORD),
                    ("exe", w.WCHAR * 260)]
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateToolhelp32Snapshot.restype = w.HANDLE
    k.Process32FirstW.argtypes = k.Process32NextW.argtypes = [w.HANDLE, ctypes.POINTER(Entry)]
    k.CloseHandle.argtypes = [w.HANDLE]
    handle = k.CreateToolhelp32Snapshot(2, 0)
    if handle == ctypes.c_void_p(-1).value:
        return 0
    entry = Entry(); entry.size = ctypes.sizeof(entry)
    try:
        ok = k.Process32FirstW(handle, ctypes.byref(entry))
        while ok:
            if entry.pid == pid:
                return int(entry.parent)
            ok = k.Process32NextW(handle, ctypes.byref(entry))
    finally:
        k.CloseHandle(handle)
    return 0


def _birth(pid: int) -> int:
    """Process creation identity prevents a recycled PID from inheriting a lease."""
    if os.name != "nt":
        try:
            return int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19])
        except (OSError, ValueError, IndexError):
            return 0
    from ctypes import wintypes as w
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]; k.OpenProcess.restype = w.HANDLE
    k.GetProcessTimes.argtypes = [w.HANDLE] + [ctypes.POINTER(w.FILETIME)] * 4
    k.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
    k.CloseHandle.argtypes = [w.HANDLE]
    handle = k.OpenProcess(0x1000, False, pid)
    if not handle:
        return 0
    try:
        code = w.DWORD()
        times = [w.FILETIME() for _ in range(4)]
        if (k.GetExitCodeProcess(handle, ctypes.byref(code)) and code.value == 259
                and k.GetProcessTimes(handle, *(ctypes.byref(t) for t in times))):
            return int(times[0].dwHighDateTime) << 32 | int(times[0].dwLowDateTime)
    finally:
        k.CloseHandle(handle)
    return 0


def valid_lease(root: Path = JARVIS_ROOT) -> bool:
    token = os.environ.get(LEASE_ENV, "")
    if not token:
        return False
    try:
        raw = json.loads((Path(root) / ".runtime" / "maintenance-lease.json").read_text(encoding="utf-8"))
        if raw.get("token") != token:
            return False
        owner = int(raw["pid"])
        if not raw.get("birth") or _birth(owner) != raw["birth"]:
            return False
        pid = os.getpid()
        seen = set()
        while pid > 1 and pid not in seen:
            seen.add(pid)
            if pid == owner:
                return True
            pid = _parent(pid)
    except (OSError, ValueError, KeyError):
        pass
    return False


class WindowsTree:
    """A named kill-on-close Job Object; children are assigned while suspended."""
    def __init__(self, name: str, *, existing: bool = False) -> None:
        from ctypes import wintypes as w
        self.k = ctypes.WinDLL("kernel32", use_last_error=True)
        self.k.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        self.k.CreateJobObjectW.restype = w.HANDLE
        self.k.OpenJobObjectW.argtypes = [w.DWORD, w.BOOL, w.LPCWSTR]
        self.k.OpenJobObjectW.restype = w.HANDLE
        self.k.CloseHandle.argtypes = [w.HANDLE]
        self.k.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        self.k.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
        self.k.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        self.k.QueryInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.c_void_p]
        self.handle = self.k.OpenJobObjectW(0x1F003F, False, name) if existing else self.k.CreateJobObjectW(None, name)
        if not self.handle:
            if existing and ctypes.get_last_error() == 2:
                return
            raise ctypes.WinError(ctypes.get_last_error())
        class Basic(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
                        ("flags", w.DWORD), ("min_working", ctypes.c_size_t), ("max_working", ctypes.c_size_t),
                        ("active_limit", w.DWORD), ("affinity", ctypes.c_size_t),
                        ("priority", w.DWORD), ("scheduling", w.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(f"counter{i}", ctypes.c_ulonglong) for i in range(6)]
        class Extended(ctypes.Structure):
            _fields_ = [("basic", Basic), ("io", IO), ("process_limit", ctypes.c_size_t),
                        ("job_limit", ctypes.c_size_t), ("peak_process", ctypes.c_size_t),
                        ("peak_job", ctypes.c_size_t)]
        self.Extended = Extended
        if not existing:
            limits = Extended(); limits.basic.flags = 0x2000
            if not self.k.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                self.close()
                raise ctypes.WinError(ctypes.get_last_error())

    def assign_resume(self, proc: subprocess.Popen) -> None:
        from ctypes import wintypes as w
        if not self.k.AssignProcessToJobObject(self.handle, int(proc._handle)):
            proc.kill(); proc.wait()
            raise ctypes.WinError(ctypes.get_last_error())
        class Thread(ctypes.Structure):
            _fields_ = [("size", w.DWORD), ("usage", w.DWORD), ("tid", w.DWORD),
                        ("pid", w.DWORD), ("base", w.LONG), ("delta", w.LONG), ("flags", w.DWORD)]
        self.k.CreateToolhelp32Snapshot.restype = w.HANDLE
        self.k.Thread32First.argtypes = self.k.Thread32Next.argtypes = [w.HANDLE, ctypes.POINTER(Thread)]
        self.k.OpenThread.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        self.k.OpenThread.restype = w.HANDLE
        self.k.ResumeThread.argtypes = [w.HANDLE]
        self.k.ResumeThread.restype = w.DWORD
        snap = self.k.CreateToolhelp32Snapshot(4, 0)
        entry = Thread(); entry.size = ctypes.sizeof(entry)
        resumed = False
        try:
            ok = self.k.Thread32First(snap, ctypes.byref(entry))
            while ok:
                if entry.pid == proc.pid:
                    thread = self.k.OpenThread(2, False, entry.tid)
                    if thread:
                        try:
                            resumed = self.k.ResumeThread(thread) != 0xFFFFFFFF
                        finally:
                            self.k.CloseHandle(thread)
                    break
                ok = self.k.Thread32Next(snap, ctypes.byref(entry))
        finally:
            self.k.CloseHandle(snap)
        if not resumed:
            self.kill()
            proc.wait()
            raise RuntimeError("could not resume assigned maintenance worker")

    def active(self) -> int:
        class Accounting(ctypes.Structure):
            _fields_ = [(f"time{i}", ctypes.c_longlong) for i in range(4)] + [
                (name, ctypes.c_ulong) for name in ("faults", "total", "active", "terminated")]
        info = Accounting()
        if not self.k.QueryInformationJobObject(self.handle, 1, ctypes.byref(info), ctypes.sizeof(info), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(info.active)

    def peak_bytes(self) -> int:
        info = self.Extended()
        if not self.k.QueryInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info), None):
            return 0
        return int(info.peak_job)

    def kill(self) -> None:
        if self.handle and not self.k.TerminateJobObject(self.handle, 124):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self) -> None:
        if self.handle:
            self.k.CloseHandle(self.handle); self.handle = None


class Runtime:
    def __init__(self, root: Path = JARVIS_ROOT, *, runtime_dir: Optional[Path] = None,
                 probe: Callable[[], Resources] = resources, clock: Callable[[], float] = time.time):
        self.root = Path(root)
        self.directory = runtime_dir or self.root / ".runtime"
        self.probe, self.clock = probe, clock
        self.lease_path = self.directory / "maintenance-lease.json"
        self.policy_path = self.directory / "maintenance-policy.json"
        self.token = ""
        self.metrics: dict = {}

    def policy(self) -> dict:
        try:
            return json.loads(self.policy_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}

    def deferred(self, job: str) -> str:
        policy = self.policy()
        if self.clock() < policy.get("retry", {}).get(job, 0):
            return "waiting for failure retry"
        if self.clock() < policy.get("cooldown_until", 0):
            return "heavy-job cooldown"
        return admission(self.probe())

    @contextmanager
    def lease(self, job: str) -> Iterator[bool]:
        with try_exclusive_lock(self.directory / "maintenance") as acquired:
            if not acquired:
                yield False
                return
            # An interrupted supervisor may have left a dying group. Finish
            # its cleanup while holding the lock before admitting another job.
            recovered_output = ""
            if self.lease_path.exists():
                old = json.loads(self.lease_path.read_text(encoding="utf-8"))
                output_path = Path(old.get("output_file", ""))
                name = old.get("tree", "")
                prefix = "Local\\JARVIS-maintenance-" + hashlib.sha256(str(self.root).encode()).hexdigest()[:12] + "-"
                if os.name == "nt" and name:
                    if not name.startswith(prefix):
                        raise RuntimeError("unrecognized previous execution tree; maintenance deferred")
                    tree = WindowsTree(name, existing=True)
                    if tree.handle:
                        try:
                            tree.kill()
                            deadline = time.monotonic() + 15
                            while tree.active() and time.monotonic() < deadline:
                                time.sleep(.05)
                            if tree.active():
                                raise RuntimeError("previous execution tree cleanup unconfirmed")
                        finally:
                            tree.close()
                if output_path.is_file() and output_path.resolve().is_relative_to(self.directory.resolve()):
                    recovered_output = output_path.read_text(encoding="utf-8", errors="replace")
                self._recover_state(old, recovered_output)
            self.token = uuid.uuid4().hex
            self.metrics = {"recovered_output": recovered_output} if recovered_output else {}
            birth = _birth(os.getpid())
            if not birth:
                raise RuntimeError("maintenance owner identity unavailable")
            atomic_json(self.lease_path, {"pid": os.getpid(), "birth": birth, "token": self.token,
                                        "job": job, "tree": "", "started": self.clock()})
            try:
                yield True
            finally:
                self.token = ""
                # Keep metadata on failed cleanup for the next lock holder.
                if not self.metrics.get("cleanup_unconfirmed") and not self.metrics.get("state_commit_failed"):
                    self.lease_path.unlink(missing_ok=True)

    def _recover_state(self, previous: dict, output: str) -> None:
        """Record the interrupted owner before a different command takes its lease."""
        from jarvis_core.serve.scheduler import JobState
        path = self.root / "jarvis_data" / ".hearth_jobs.json"
        if not path.is_file():
            return
        raw = json.loads(path.read_text(encoding="utf-8"))
        name = previous.get("job", "")
        state = JobState.from_dict(raw.get(name, {}))
        if not state.running:
            return
        now = self.clock()
        state.running = False
        state.last_rc = 130
        state.last_status = "FAILED rc=130 — previous supervisor interrupted"
        state.last_output = (output or state.last_output) + "\nPrevious supervisor interrupted; process tree recovered."
        state.runs += 1
        state.failures += 1
        state.consecutive_failures += 1
        state.last_failure_ts = state.last_run = state.last_checked_ts = now
        state.next_attempt_ts = now + 6 * 3600
        raw[name] = state.to_dict()
        atomic_json(path, raw)

    async def run(self, argv: Sequence[str], timeout: float, *, heavy: bool = False) -> tuple[int, str]:
        """Run under an already-held lease; retain output on interruption."""
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1", LEASE_ENV: self.token}
        env.update({name: str(self.root / relative) for name, relative in {
            "TEMP": ".runtime/tmp", "TMP": ".runtime/tmp", "PIP_CACHE_DIR": ".cache/pip",
            "HF_HOME": ".cache/huggingface", "HF_HUB_CACHE": ".cache/huggingface/hub",
            "HUGGINGFACE_HUB_CACHE": ".cache/huggingface/hub",
            "SENTENCE_TRANSFORMERS_HOME": ".cache/sentence-transformers", "TORCH_HOME": ".cache/torch",
            "XDG_CACHE_HOME": ".cache", "NUMBA_CACHE_DIR": ".cache/numba",
            "UV_CACHE_DIR": ".cache/uv", "TRITON_CACHE_DIR": ".cache/triton",
        }.items()})
        (self.root / ".runtime" / "tmp").mkdir(parents=True, exist_ok=True)
        if heavy:
            env.update({name: "2" for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS")})
            env.update({"RAYON_NUM_THREADS": "2", "TOKENIZERS_PARALLELISM": "false"})
        flags = (0x4 | 0x08000000 | (0x4000 if heavy else 0)) if os.name == "nt" else 0
        tree = None
        proc = None
        output_task = None
        started = time.monotonic()
        low_since = None
        minimum = None
        rc_override = None
        reason = ""
        self.metrics = {}
        output_path = self.directory / f"maintenance-output-{self.token}-{time.time_ns()}.log"
        output_handle = output_path.open("wb")
        lease = json.loads(self.lease_path.read_text(encoding="utf-8"))
        lease["output_file"] = str(output_path)
        atomic_json(self.lease_path, lease)
        try:
            if os.name == "nt":
                name = "Local\\JARVIS-maintenance-" + hashlib.sha256(str(self.root).encode()).hexdigest()[:12] + "-" + self.token
                tree = WindowsTree(name)
                lease = json.loads(self.lease_path.read_text(encoding="utf-8")); lease["tree"] = name
                atomic_json(self.lease_path, lease)
            proc = subprocess.Popen(list(argv), cwd=self.root, env=env, stdout=output_handle,
                                    stderr=subprocess.STDOUT, creationflags=flags,
                                    start_new_session=os.name != "nt")
            if tree:
                tree.assign_resume(proc)
            output_task = asyncio.create_task(asyncio.to_thread(proc.wait))
            while not output_task.done():
                elapsed = time.monotonic() - started
                if elapsed >= timeout:
                    rc_override, reason = 124, f"timed out after {timeout:.0f}s"
                    break
                if heavy:
                    sample = self.probe()
                    if sample.available_bytes is None:
                        rc_override, reason = RESOURCE_ABORT, "RAM measurement became unavailable"
                        break
                    minimum = sample.available_bytes if minimum is None else min(minimum, sample.available_bytes)
                    if sample.available_bytes < 2 * GIB:
                        low_since = time.monotonic() if low_since is None else low_since
                        if time.monotonic() - low_since >= 10:
                            rc_override, reason = RESOURCE_ABORT, "available RAM stayed below 2 GiB for ten seconds"
                            break
                    else:
                        low_since = None
                await asyncio.wait({output_task}, timeout=min(5.0 if heavy else .25, max(.01, timeout - elapsed)))
            if rc_override is not None:
                if tree:
                    tree.kill()
                else:
                    os.killpg(proc.pid, signal.SIGKILL)
            await asyncio.shield(output_task)
            rc = rc_override if rc_override is not None else int(proc.returncode or 0)
            text = output_path.read_text(encoding="utf-8", errors="replace").strip()
            return rc, text + ("\n" + reason if reason else "")
        except asyncio.CancelledError:
            if proc:
                if tree:
                    tree.kill()
                elif proc.poll() is None:
                    os.killpg(proc.pid, signal.SIGKILL)
                if output_task:
                    await asyncio.shield(output_task)
                    self.metrics["interrupted_output"] = output_path.read_text(encoding="utf-8", errors="replace")
            raise
        finally:
            output_handle.close()
            if tree:
                self.metrics["cleanup_unconfirmed"] = True
                try:
                    self.metrics["peak_tree_bytes"] = tree.peak_bytes()
                    if tree.active():
                        tree.kill()
                    deadline = time.monotonic() + 15
                    while tree.active() and time.monotonic() < deadline:
                        await asyncio.sleep(.05)
                    if tree.active():
                        raise RuntimeError("process-tree cleanup unconfirmed")
                    self.metrics["cleanup_unconfirmed"] = False
                finally:
                    tree.close()
            self.metrics.update({"duration_s": round(time.monotonic() - started, 2),
                                 "minimum_available_bytes": minimum, "output_file": str(output_path)})
            if heavy and proc:
                policy = self.policy()
                policy["cooldown_until"] = self.clock() + 120
                if rc_override is not None or proc.returncode not in (None, 0):
                    policy.setdefault("retry", {})[self.metrics.get("job", self._job())] = self.clock() + 6 * 3600
                atomic_json(self.policy_path, policy)

    def _job(self) -> str:
        return str(json.loads(self.lease_path.read_text(encoding="utf-8"))["job"])


def cli_entry(job: str, script: str) -> None:
    """Called before a maintenance CLI imports its model-dependent modules."""
    if valid_lease():
        return
    if any(arg in sys.argv for arg in ("--help", "-h")):
        return
    runtime = Runtime()
    diagnostic = any(arg in sys.argv for arg in ("--self-test", "--dry-run", "--report", "--status", "--list"))
    production = not diagnostic and not any(arg in sys.argv for arg in (
        "--kb", "--collection", "--queue", "--out", "--candidates", "--scratch",
        "--only", "--sources", "--threshold", "--gold", "--eval-retrieval",
        "--backfill-provenance", "--embedder"))
    with runtime.lease(job if production else "diagnostic:" + job) as acquired:
        if not acquired:
            print("Maintenance busy: another scheduled or manual job owns the lease.")
            raise SystemExit(BUSY)
        reason = "" if diagnostic else runtime.deferred(job)
        if reason:
            print(f"Maintenance deferred: {reason}")
            raise SystemExit(BUSY)
        before = fingerprint(job) if production and job in {"relabel_domains", "rebuild_corpora", "run_all_tests"} else ""
        started = time.time()
        if production:
            _manual_state(job, running=True)
        try:
            rc, output = asyncio.run(runtime.run([sys.executable, script, *sys.argv[1:]],
                                             900 if job == "relabel_domains" else 1800,
                                             heavy=not diagnostic))
        except BaseException:
            if production:
                _manual_state(job, rc=130, output=runtime.metrics.get("interrupted_output", "") + "\nManual supervisor interrupted.", started=started,
                              metrics=runtime.metrics)
            raise
        if production:
            after = fingerprint(job) if before and rc == 0 else ""
            try:
                _manual_state(job, rc=rc, output=output, started=started, metrics=runtime.metrics,
                              signature=before if before == after else "")
            except OSError:
                runtime.metrics["state_commit_failed"] = True
                raise
        print(output)
        print("Maintenance measurements: " + json.dumps(runtime.metrics))
        raise SystemExit(rc)


def _manual_state(job: str, *, running: bool = False, rc: Optional[int] = None,
                  output: str = "", started: float = 0, metrics: Optional[dict] = None,
                  signature: str = "") -> None:
    """Same execution history as the clock, written only while owning its lease."""
    from jarvis_core.serve.scheduler import STATE_PATH, JobState
    raw = json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.exists() else {}
    state = JobState.from_dict(raw.get(job, {}))
    now = time.time()
    state.first_seen_ts = state.first_seen_ts or now
    state.running = running
    if rc is not None:
        state.last_run = state.last_checked_ts = now
        state.last_rc, state.last_output = rc, output
        state.last_duration_s = round(now - started, 2)
        state.measurements = metrics or {}
        state.runs += 1
        state.deferred_reason = ""
        state.next_attempt_ts = 0
        if rc == 0:
            state.last_status = "ok"
            state.last_success_ts = now
            if job not in {"relabel_domains", "rebuild_corpora", "run_all_tests"} or signature:
                state.last_fresh_ts = now
            state.consecutive_failures = 0
            state.input_fingerprint = signature
        else:
            state.last_status = f"FAILED rc={rc}"
            state.failures += 1
            state.consecutive_failures += 1
            state.last_failure_ts = now
            state.next_attempt_ts = now + 6 * 3600
    raw[job] = state.to_dict()
    atomic_json(STATE_PATH, raw)


def fingerprint(job: str, root: Path = JARVIS_ROOT) -> str:
    """Conservative source-only content fingerprints, never generated outputs."""
    root = Path(root)
    paths = set()
    for directory in ("js-development/jarvis_core", "scripts"):
        paths.update(p for p in (root / directory).rglob("*.py") if "ui" not in p.parts)
    paths.update(root.glob("requirements*.txt"))
    paths.update(root.glob("pyproject.toml"))
    paths.update((root / ".venv" / "Lib" / "site-packages").glob("*.dist-info/METADATA"))
    paths.update((root / ".venv" / "lib").glob("python*/site-packages/*.dist-info/METADATA"))
    if job != "run_all_tests":
        names = ("observation_queue.jsonl",) if job == "relabel_domains" else (
            "knowledge_base.jsonl", "observation_queue.jsonl", "turn_curation.jsonl",
            "retractions.jsonl", "training_reviews.jsonl", "experience_map.md", "eval/c002/exclusions.json",
            "training_corpus/client_work_snapshot.jsonl")
        paths.update(root / "jarvis_data" / name for name in names)
        if job == "rebuild_corpora":
            for directory in ("knowledge", "client_work", "jarvis_data/conversations"):
                paths.update(p for p in (root / directory).rglob("*") if p.is_file() and p.suffix in
                             (".py", ".md", ".json", ".jsonl", ".sql", ".txt", ".yaml", ".yml"))
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(str(path.relative_to(root)).encode())
        try:
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
        except FileNotFoundError:
            digest.update(b"<missing>")
    return digest.hexdigest()


def outputs_exist(job: str, root: Path = JARVIS_ROOT) -> bool:
    data = Path(root) / "jarvis_data"
    if job == "relabel_domains":
        return (data / "domain_labels.jsonl").is_file()
    if job == "rebuild_corpora":
        return all((data / "training_corpus" / name).is_file() for name in (
            "engineer_corpus.jsonl", "personalization_corpus.jsonl", "blended_corpus.jsonl",
            "sft_pairs.jsonl", "sft_pairs_heldout.jsonl"))
    return True
