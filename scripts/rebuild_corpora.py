#!/usr/bin/env python3
"""
rebuild_corpora.py — the corpora, rebuilt on the clock instead of by hand.

LAYER: Tools (thin adapter — every step is an existing CLI)

Run with:
    python scripts/rebuild_corpora.py              # the whole chain
    python scripts/rebuild_corpora.py --dry-run    # print the chain, run nothing
    python scripts/rebuild_corpora.py --self-test  # hermetic (injected runner)

=============================================================================
THE BIG PICTURE
=============================================================================

Until 2026-09-28 the five training artifacts were rebuilt only when someone
remembered to, so a turn parsed today reached the corpora whenever a human next
typed the four commands in the right order. The hearth now runs this daily.

Pure code, no LLM: each step is the same CLI a human would run, in the one
order that is correct — each reads what the previous one wrote:

    engineer_corpus -> personalization_corpus -> blend_corpus
                    -> build_sft_pairs -> check_pipeline

It stops at the FIRST failure and prints that step's whole output. Running
blend over a half-written engineer corpus would produce a plausible, wrong
training set; stopping produces a visible failure instead, which the scheduler
records and pipeline_health reports.

=============================================================================
THE FLOW
=============================================================================

STEP 1: build the step list (argv, cwd, env) from the repo root.
        |
STEP 2: run each step; print its whole output under a header.
        |
STEP 3: on the first non-zero exit, stop and exit with that code. Exit 0 only
        when every step, including check_pipeline, passed.
=============================================================================
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

_ROOT = Path(__file__).resolve().parents[1]
_DEV = _ROOT / "js-development"

# argv, cwd, env -> (returncode, whole combined output)
Runner = Callable[[Sequence[str], Path, Dict[str, str]], Tuple[int, str]]


@dataclass(frozen=True)
class Step:
    name: str
    argv: Tuple[str, ...]
    cwd: Path


def _python(root: Path) -> str:
    venv = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python3")
    return str(venv) if venv.is_file() else (sys.executable or "python3")


def steps(root: Path = _ROOT, python: Optional[str] = None) -> List[Step]:
    """The chain, in the only order that is correct."""
    py = python or _python(root)
    dev = root / "js-development"
    return [
        Step("engineer_corpus", (py, "-m", "jarvis_core.specialists.engineer_corpus"), dev),
        Step("personalization_corpus", (py, "-m", "jarvis_core.specialists.personalization_corpus"), dev),
        Step("blend_corpus", (py, "-m", "jarvis_core.specialists.blend_corpus"), dev),
        Step("build_sft_pairs", (py, str(root / "scripts" / "build_sft_pairs.py")), root),
        Step("check_pipeline", (py, str(root / "scripts" / "check_pipeline.py")), root),
    ]


def _subprocess_runner(argv: Sequence[str], cwd: Path, env: Dict[str, str]) -> Tuple[int, str]:
    try:
        proc = subprocess.run(list(argv), cwd=str(cwd), env=env, capture_output=True,
                              text=True, encoding="utf-8", errors="replace")
    except OSError as e:
        return 127, f"spawn failed: {type(e).__name__}: {e}"
    return proc.returncode, ((proc.stdout or "") + (proc.stderr or "")).strip()


def run_chain(chain: Sequence[Step], runner: Runner = _subprocess_runner,
              printer: Callable[[str], None] = print) -> int:
    """Run every step; stop at the first failure. Returns that step's rc, or 0."""
    env = {**os.environ, "PYTHONPATH": str(_DEV), "PYTHONUNBUFFERED": "1",
           "PYTHONIOENCODING": "utf-8"}
    for i, step in enumerate(chain, 1):
        printer(f"=== [{i}/{len(chain)}] {step.name}: {' '.join(step.argv)}")
        started = time.perf_counter()
        rc, out = runner(step.argv, step.cwd, env)
        took = time.perf_counter() - started
        if out:
            printer(out)
        if rc != 0:
            printer(f"=== FAILED at step {i}/{len(chain)} ({step.name}) rc={rc} after {took:.1f}s. "
                    f"Later steps were NOT run, so every artifact after "
                    f"{step.name} is from the previous rebuild.")
            return rc
        printer(f"=== ok {step.name} ({took:.1f}s)")
    printer(f"=== all {len(chain)} steps passed")
    return 0


def _self_test() -> int:
    failed: List[str] = []
    passed = 0

    def check(name: str, ok: bool, hint: str = "") -> None:
        nonlocal passed
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  {hint}"))
        if ok:
            passed += 1
        else:
            failed.append(name)

    print("=" * 70)
    print("  rebuild_corpora.py -- self-test (injected runner, nothing executed)")
    print("=" * 70)
    chain = steps(python="py")
    check("T1 the chain is engineer -> personalization -> blend -> sft -> check",
          [s.name for s in chain] == ["engineer_corpus", "personalization_corpus",
                                      "blend_corpus", "build_sft_pairs", "check_pipeline"],
          str([s.name for s in chain]))
    check("T2 every script step points at a file that exists",
          all(Path(s.argv[1]).is_file() for s in chain if s.argv[1] != "-m"))
    check("T3 every module step names a module that exists",
          all((_DEV / (s.argv[2].replace(".", "/") + ".py")).is_file()
              for s in chain if s.argv[1] == "-m"))

    def scripted(codes: Dict[str, int], calls: List[str]) -> Runner:
        def run(argv: Sequence[str], cwd: Path, env: Dict[str, str]) -> Tuple[int, str]:
            name = next(s.name for s in chain if tuple(argv) == s.argv)
            calls.append(name)
            if "PYTHONPATH" not in env:
                return 99, "no PYTHONPATH"
            return codes.get(name, 0), f"START-{name}-" + "x" * 3000 + f"-END-{name}"
        return run

    calls: List[str] = []
    lines: List[str] = []
    rc = run_chain(chain, scripted({}, calls), lines.append)
    check("T4 all steps pass -> exit 0, every step ran in order",
          rc == 0 and calls == [s.name for s in chain], f"rc={rc} {calls}")

    calls, lines = [], []
    rc = run_chain(chain, scripted({"blend_corpus": 3}, calls), lines.append)
    check("T5 a failing step stops the chain with ITS exit code",
          rc == 3 and calls == ["engineer_corpus", "personalization_corpus", "blend_corpus"],
          f"rc={rc} {calls}")
    blob = "\n".join(lines)
    check("T6 the failing step's whole output is printed, nothing cut",
          "START-blend_corpus-" + "x" * 3000 + "-END-blend_corpus" in blob)
    check("T7 the failure names the step and says later steps did not run",
          "FAILED at step 3/5 (blend_corpus) rc=3" in blob and "NOT run" in blob)

    calls, lines = [], []
    rc = run_chain(chain, scripted({"check_pipeline": 1}, calls), lines.append)
    check("T8 a failing check_pipeline makes the whole rebuild fail",
          rc == 1 and calls[-1] == "check_pipeline")

    def exploding(argv: Sequence[str], cwd: Path, env: Dict[str, str]) -> Tuple[int, str]:
        return _subprocess_runner(["definitely-not-a-real-binary-xyz"], cwd, env)
    rc = run_chain(chain[:1], exploding, lambda _l: None)
    check("T9 a step that cannot even spawn is a failure, not a crash", rc == 127, str(rc))

    print("-" * 70)
    print(f"  {passed} passed, {len(failed)} failed")
    print("=" * 70)
    return 1 if failed else 0


def main() -> int:
    p = argparse.ArgumentParser(description="Rebuild every training corpus, in order; stop at the first failure.")
    p.add_argument("--dry-run", action="store_true", help="print the chain, run nothing")
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    if args.self_test:
        return _self_test()
    chain = steps()
    if args.dry_run:
        for i, s in enumerate(chain, 1):
            print(f"[{i}/{len(chain)}] {s.name}: (cwd {s.cwd}) {' '.join(s.argv)}")
        return 0
    return run_chain(chain)


if __name__ == "__main__":
    raise SystemExit(main())
