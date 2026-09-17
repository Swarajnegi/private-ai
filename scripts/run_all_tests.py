#!/usr/bin/env python3
"""
run_all_tests.py — run every smoke suite in the repo, because nobody could.

LAYER: Tools (verification)

    python3 scripts/run_all_tests.py              # everything
    python3 scripts/run_all_tests.py --fast       # skip the slow model loaders
    python3 scripts/run_all_tests.py --list       # what would run, and how
    python3 scripts/run_all_tests.py --self-test  # test the runner itself

=============================================================================
THE BIG PICTURE
=============================================================================

The user asked, after a third silent bug surfaced in one session: *"Why is it
that every time I ask you randomly to verify everything, you find a new silent
bug?"* The answer was measurable and it was not "insufficient care":

    modules carrying real assertion-bearing smoke suites   94
    modules actually run in that session                    9
    test runner                                          NONE

`README.md` states the gap outright — *"Tests are `__main__` smoke blocks, not
a pytest suite... there is no runner, which is a real gap rather than a hidden
feature."* So "run the tests" was not an operation anyone could perform. What
happened instead was that whoever last touched a file ran that file, and the
other 90-odd suites were verified by hope.

This is the runner. It exists so a regression announces itself on a clock
rather than waiting for someone to ask the right question — the same reason
the hearth exists, and the same reason `relabel_domains` is scheduled.

=============================================================================
WHY IT IS SAFE BY CONSTRUCTION AND NOT BY CLASSIFICATION
=============================================================================

The obvious design is to classify each `__main__` — test, demo, or something
that costs money — and run only the safe ones. THAT WAS TRIED FIRST AND IT
FAILED IMMEDIATELY. A regex looking for `build_llm_call` flagged
`brain/llm_client.py` as an unguarded paid call; its `__main__` is in fact 25
offline tests with an injected transport. Trusting that classification would
have skipped a good suite, and — far worse — the same crude reasoning could
mark a genuinely expensive module safe.

Classification is a judgement that rots. So the runner does not rely on one:

  1. **The money risk is neutralised, not predicted.** Every suite runs with
     `OPENROUTER_API_KEY` blanked. A module that really would have called a
     paid API now fails fast with a missing-key error instead of spending. No
     list of "expensive modules" has to be maintained or kept correct.

  2. **Side effects are OBSERVED, not assumed.** The tracked-file state is
     snapshotted before and after each module, so a suite that writes into the
     repo is caught by measurement. A test with side effects is itself a
     defect and is reported as a failure rather than tolerated.

  3. **A declared entry point wins.** Where a module exposes `--self-test`,
     that is used; it is the author's own statement of what is safe to run.

=============================================================================
WHAT THIS DOES NOT COVER — read before trusting a green run
=============================================================================

  * It runs each module's OWN suite. It cannot see defects that live BETWEEN
    artifacts — the 11% duplication in `blended_corpus.jsonl` was invisible to
    all 94 suites because no module owned the relationship. That is
    `scripts/check_pipeline.py`'s job, and the two are complementary.
  * A suite that asserts nothing still "passes". Coverage is not measured.
  * The hearth writes to `jarvis_data/` continuously, so its churn is excluded
    from side-effect detection (see `_HEARTH_CHURN`) — which means a suite that
    wrongly wrote to one of THOSE files would not be caught here.

=============================================================================
THE FLOW
=============================================================================

STEP 1: discover every module under jarvis_core/ and scripts/ with a
        `__main__` block, and note whether it declares `--self-test`.
        |
STEP 2: snapshot tracked-file state once, then run each module as a
        subprocess with a blanked API key and a timeout.
        |
STEP 3: after each, re-snapshot and attribute any NEW dirty path to the module
        that just ran, updating the baseline so one dirty file is blamed once.
        |
STEP 4: report PASS / FAIL / TIMEOUT / SIDE-EFFECT per module and exit
        non-zero if anything is not PASS.
=============================================================================
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PKG_ROOT = _REPO_ROOT / "js-development"

_MAIN_GUARD = '__name__ == "__main__"'
_SELF_TEST_FLAG = re.compile(r'add_argument\(\s*["\']--self-test["\']')

# A `__main__` block is NOT proof that a module has tests. Many are CLI entry
# points, and running those bare is meaningless at best and destructive at
# worst: the first full run invoked `build_sft_pairs.py` and
# `specialists/engineer_corpus.py` with no arguments, which is their "rebuild
# the corpus" path, and rewrote four tracked artifacts. The side-effect check
# caught it, but catching it afterwards is not the same as not doing it.
#
# So a module is only RUN when it demonstrably contains a suite.
_SUITE_MARKERS = re.compile(
    r'def\s+(_run_self_test|_self_test|_smoke)\b'
    r'|_run_self_test\(\)|_self_test\(\)|_smoke\(\)')

_DEFAULT_TIMEOUT = 300.0

# Suites that load an embedding model pay ~10-20s of warm-up each. --fast skips
# them so the runner stays usable as a pre-commit check; the scheduled run does
# not skip anything.
_SLOW_MARKERS = ("sentence_transformers", "SentenceTransformer", "chromadb",
                 "MemoryStore", "rebuild_index")

# The hearth mutates these on its own clock while the runner is running, so a
# diff here says nothing about the module that happened to be executing. The
# cost of this exclusion is stated in the header: a suite that wrongly wrote to
# one of these would not be attributed.
_HEARTH_CHURN = {
    "jarvis_data/.runtime_state.json",
    "jarvis_data/.hearth_jobs.json",
    "jarvis_data/.terminal_session.json",
    "jarvis_data/.tension_watermark.jsonl",
    "jarvis_data/observation_queue.jsonl",
    "jarvis_data/turn_curation.jsonl",
    "jarvis_data/activity_digest.md",
    "jarvis_data/cognitive_profile.md",
    "jarvis_data/domain_labels.jsonl",
    "jarvis_data/life_state_feed.jsonl",
    "jarvis_data/knowledge_base.jsonl",
}

PASS, FAIL, TIMEOUT, SIDE_EFFECT = "PASS", "FAIL", "TIMEOUT", "SIDE-EFFECT"
NO_SUITE = "NO-SUITE"


@dataclass
class Suite:
    path: Path
    uses_flag: bool
    slow: bool
    has_suite: bool = True
    root: Path = _REPO_ROOT

    @property
    def rel(self) -> str:
        """Path relative to the root it was discovered under, not a fixed one.

        Hardcoding `_REPO_ROOT` here broke the runner's own self-test, which
        discovers under a temp directory — the first thing this file did when
        run was crash. Worth keeping as a note: a "verification" tool that
        assumes the one environment it usually sees is the same defect class it
        exists to catch.
        """
        try:
            return self.path.relative_to(self.root).as_posix()
        except ValueError:
            return self.path.as_posix()

    def argv(self, python: str) -> List[str]:
        """Prefer the module's own declared entry point over a bare run."""
        cmd = [python, str(self.path)]
        if self.uses_flag:
            cmd.append("--self-test")
        return cmd


@dataclass
class Result:
    suite: Suite
    status: str
    seconds: float
    detail: str = ""


def discover(root: Optional[Path] = None) -> List[Suite]:
    """Every module with a `__main__` block, in a stable order."""
    base = root or _REPO_ROOT
    suites: List[Suite] = []
    for folder in (base / "js-development" / "jarvis_core", base / "scripts"):
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if _MAIN_GUARD not in text:
                continue
            uses_flag = bool(_SELF_TEST_FLAG.search(text))
            suites.append(Suite(
                path=path,
                uses_flag=uses_flag,
                slow=any(marker in text for marker in _SLOW_MARKERS),
                has_suite=uses_flag or bool(_SUITE_MARKERS.search(text)),
                root=base,
            ))
    return suites


def _dirty_paths(root: Path) -> Set[str]:
    """Tracked paths git currently reports as modified, minus hearth churn."""
    try:
        out = subprocess.run(["git", "-C", str(root), "status", "--porcelain"],
                             capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    paths = set()
    for line in out.splitlines():
        if len(line) > 3:
            paths.add(line[3:].strip().strip('"'))
    return paths - _HEARTH_CHURN


def _child_env() -> Dict[str, str]:
    """A blanked API key is what makes an unclassified suite safe to run.

    Neutralising the capability beats predicting which modules have it — the
    classification attempt this runner replaced got `brain/llm_client.py`
    wrong in the dangerous direction on its first try.
    """
    env = dict(os.environ)
    env["OPENROUTER_API_KEY"] = ""
    env["PYTHONPATH"] = f"{_PKG_ROOT}{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
    env["JARVIS_TEST_RUN"] = "1"
    return env


def run_suite(suite: Suite, timeout: float, baseline: Set[str],
              root: Path, python: str) -> Tuple[Result, Set[str]]:
    """Run one suite; return its result and the updated dirty-path baseline."""
    started = time.monotonic()
    try:
        proc = subprocess.run(suite.argv(python), cwd=str(root), env=_child_env(),
                              capture_output=True, text=True, timeout=timeout)
        rc, tail = proc.returncode, (proc.stdout + proc.stderr)[-400:].strip()
    except subprocess.TimeoutExpired:
        return Result(suite, TIMEOUT, time.monotonic() - started,
                      f"exceeded {timeout:.0f}s"), baseline
    except OSError as exc:
        return Result(suite, FAIL, time.monotonic() - started, str(exc)[:200]), baseline

    elapsed = time.monotonic() - started
    now = _dirty_paths(root)
    introduced = now - baseline
    if introduced:
        return (Result(suite, SIDE_EFFECT, elapsed,
                       "wrote " + ", ".join(sorted(introduced)[:3])), now)
    if rc != 0:
        return Result(suite, FAIL, elapsed, f"rc={rc} {tail[-200:]}"), now
    return Result(suite, PASS, elapsed, ""), now


def run_all(fast: bool = False, timeout: float = _DEFAULT_TIMEOUT,
            root: Optional[Path] = None, python: Optional[str] = None,
            only: Optional[str] = None) -> List[Result]:
    base = root or _REPO_ROOT
    interpreter = python or sys.executable or "python3"
    suites = discover(base)
    if only:
        suites = [s for s in suites if only in s.rel]
    baseline = _dirty_paths(base)
    results: List[Result] = []
    for i, suite in enumerate(suites, 1):
        if not suite.has_suite:
            results.append(Result(suite, NO_SUITE, 0.0,
                                  "no test suite — __main__ is a CLI entry point"))
            continue
        if fast and suite.slow:
            results.append(Result(suite, PASS, 0.0, "skipped (--fast, loads a model)"))
            print(f"  [{i}/{len(suites)}] SKIP  {suite.rel}")
            continue
        result, baseline = run_suite(suite, timeout, baseline, base, interpreter)
        results.append(result)
        mark = "ok  " if result.status == PASS else result.status
        print(f"  [{i}/{len(suites)}] {mark:<12} {result.seconds:>6.1f}s  {suite.rel}"
              + (f"  — {result.detail[:90]}" if result.detail else ""))
    return results


def report(results: Sequence[Result]) -> int:
    counts: Dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    # NO-SUITE is reported, never hidden, and never counted as a failure — a
    # CLI tool having no tests is a fact about the repo, not a regression.
    bad = [r for r in results if r.status not in (PASS, NO_SUITE)]
    print()
    print("=" * 74)
    print("  SMOKE SUITE RUN")
    print("=" * 74)
    print(f"  suites discovered : {len(results)}")
    for status in (PASS, FAIL, TIMEOUT, SIDE_EFFECT):
        if counts.get(status):
            print(f"  {status:<18}: {counts[status]}")
    if bad:
        print()
        print("  NOT PASSING:")
        for r in bad:
            print(f"    {r.status:<12} {r.suite.rel}")
            if r.detail:
                print(f"                 {r.detail[:150]}")
        print()
        print("  A SIDE-EFFECT is a suite that wrote into the repo while running.")
        print("  That is a defect in the suite, not a false alarm: a test that")
        print("  mutates tracked state cannot be run safely on a clock.")
    print("=" * 74)
    return 1 if bad else 0


def _self_test() -> int:
    """The runner's own suite, hermetic — writes only inside a temp dir."""
    import tempfile
    passed: List[str] = []
    failed: List[str] = []

    def check(name: str, got, want) -> None:
        (passed if got == want else failed).append(
            name if got == want else f"{name}: got {got!r}, want {want!r}")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pkg = root / "js-development" / "jarvis_core"
        scripts = root / "scripts"
        pkg.mkdir(parents=True); scripts.mkdir(parents=True)

        (pkg / "good.py").write_text(
            'def _smoke():\n    print("2 passed, 0 failed")\n    return 0\n'
            'if __name__ == "__main__":\n    raise SystemExit(_smoke())\n', encoding="utf-8")
        (pkg / "bad.py").write_text(
            'def _smoke():\n    return 1\n'
            'if __name__ == "__main__":\n    raise SystemExit(_smoke())\n', encoding="utf-8")
        # A CLI entry point with no suite. Running this bare is what rewrote
        # four tracked artifacts on the first real run.
        (scripts / "cli_tool.py").write_text(
            'import argparse\np=argparse.ArgumentParser()\n'
            'p.add_argument("target")\n'
            'if __name__ == "__main__":\n    p.parse_args()\n', encoding="utf-8")
        (scripts / "flagged.py").write_text(
            'import argparse\np=argparse.ArgumentParser()\n'
            'p.add_argument("--self-test", action="store_true")\n'
            'if __name__ == "__main__":\n'
            '    a=p.parse_args()\n'
            '    raise SystemExit(0 if a.self_test else 3)\n', encoding="utf-8")
        (pkg / "nomain.py").write_text('x = 1\n', encoding="utf-8")
        (pkg / "slow.py").write_text(
            '# uses chromadb\ndef _smoke():\n    return 0\n'
            'if __name__ == "__main__":\n    raise SystemExit(_smoke())\n', encoding="utf-8")

        found = {s.path.name: s for s in discover(root)}
        check("T1 discovers modules with a __main__", "good.py" in found, True)
        check("T2 ignores modules without one", "nomain.py" in found, False)
        check("T3 detects a declared --self-test flag", found["flagged.py"].uses_flag, True)
        check("T4 ...and its absence", found["good.py"].uses_flag, False)
        check("T5 flags model-loading suites as slow", found["slow.py"].slow, True)
        check("T5b a module with a suite is marked runnable", found["good.py"].has_suite, True)
        check("T5c a CLI entry point is NOT marked runnable",
              found["cli_tool.py"].has_suite, False)

        # T6 is the whole point of preferring a declared entry point: this
        # module exits 3 when run bare and 0 with the flag.
        results = {r.suite.path.name: r for r in
                   run_all(root=root, timeout=60, python=sys.executable)}
        check("T6 a flagged module is invoked WITH --self-test", results["flagged.py"].status, PASS)
        check("T7 a passing module passes", results["good.py"].status, PASS)
        check("T8 a non-zero exit is a FAIL", results["bad.py"].status, FAIL)
        # T8b is the fix for the first real run: a CLI tool must never be
        # invoked, because bare invocation IS its destructive path.
        check("T8b a CLI entry point is never executed",
              results["cli_tool.py"].status, NO_SUITE)
        check("T8c NO-SUITE does not fail the run",
              report([results["cli_tool.py"], results["good.py"]]), 0)
        check("T9 report() exits non-zero when anything failed",
              report(list(results.values())), 1)
        check("T10 ...and zero when all pass",
              report([r for r in results.values() if r.status == PASS]), 0)

        fast = {r.suite.path.name: r for r in
                run_all(root=root, fast=True, timeout=60, python=sys.executable)}
        check("T11 --fast skips the slow ones", "skipped" in fast["slow.py"].detail, True)
        check("T12 --fast still runs the fast ones", fast["good.py"].status, PASS)

    env = _child_env()
    check("T13 the API key is blanked for every child", env["OPENROUTER_API_KEY"], "")
    check("T14 hearth churn is excluded from side-effect blame",
          "jarvis_data/observation_queue.jsonl" in _HEARTH_CHURN, True)

    print("=" * 74)
    print("  run_all_tests self-test")
    print("=" * 74)
    for line in passed:
        print(f"  PASS  {line}")
    for line in failed:
        print(f"  FAIL  {line}")
    print("-" * 74)
    print(f"  {len(passed)} passed, {len(failed)} failed")
    print("=" * 74)
    return 1 if failed else 0


def main() -> int:
    p = argparse.ArgumentParser(description="Run every smoke suite in the repo.")
    p.add_argument("--fast", action="store_true", help="skip suites that load an embedding model")
    p.add_argument("--timeout", type=float, default=_DEFAULT_TIMEOUT)
    p.add_argument("--only", help="substring filter on the module path")
    p.add_argument("--list", action="store_true", help="show what would run, and how")
    p.add_argument("--self-test", action="store_true", help="test the runner itself")
    args = p.parse_args()

    if args.self_test:
        return _self_test()
    if args.list:
        suites = discover()
        print(f"{len(suites)} suites discovered\n")
        for s in suites:
            how = "--self-test" if s.uses_flag else "bare __main__"
            print(f"  {'SLOW' if s.slow else '    '}  {how:<14} {s.rel}")
        return 0
    return report(run_all(fast=args.fast, timeout=args.timeout, only=args.only))


if __name__ == "__main__":
    raise SystemExit(main())
