"""
surface_pipeline_health.py — Claude Code SessionStart-hook: raise pipeline breaches at boot.

LAYER: Tools (Memory Contract — health surfacing, Claude Code adapter)

=============================================================================
THE BIG PICTURE
=============================================================================

Measured 2026-09-28: the hourly curator failed 185 of 195 runs in 13 days and
reindex_memory 16 of 17, and no agent noticed, because nothing put job health
in front of one. The fix is not a dashboard someone has to open: every agent
sees breaches at boot. Codex and Antigravity get them from
`bootstrap_jarvis.py --check`; JARVIS from its inhale; this hook is Claude's.

All judgement lives in scripts/pipeline_health.py (`--brief`: one line per
breach, nothing when healthy, exit 1 when breached). This adapter only runs it
and relays what it says. Silent when healthy — a hook that always speaks is
tuned out. A health check that cannot run is itself a breach, so a missing,
crashing or hanging pipeline_health.py is reported, never swallowed.

=============================================================================
THE FLOW
=============================================================================

STEP 1: stdin event (ignored beyond parse). Locate the repo root.
        |
STEP 2: run `pipeline_health.py --brief` with a _TIMEOUT_S ceiling.
        |
STEP 3: rc 0 + no output -> silent. Anything else -> emit every line, whole,
        under a heading telling the agent to raise it with the owner first.
        Always exit 0.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

_TIMEOUT_S = 20.0
_ROOT = Path(__file__).resolve().parents[2]
_HEADING = (
    "JARVIS PIPELINE HEALTH — BREACHED. Raise these with the owner at the START of your "
    "first reply, before anything else, in plain words: what is broken, since when, and the "
    "fix command if one is given. Do not wait to be asked and do not bury it (Memory "
    "Contract, NERVOUS_SYSTEM.md §3). Re-check with `python scripts/pipeline_health.py`.\n"
)


def breaches(root: Path = _ROOT, timeout: float = _TIMEOUT_S) -> List[str]:
    """Breach lines, whole. Empty means healthy."""
    script = root / "scripts" / "pipeline_health.py"
    if not script.is_file():
        return [f"pipeline_health.py is MISSING at {script} — no health check ran, so every "
                "pipeline failure is currently invisible."]
    try:
        proc = subprocess.run(
            [sys.executable, str(script), "--brief"], cwd=str(root),
            capture_output=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired:
        return [f"pipeline_health.py --brief did not finish within {timeout:.0f}s — the health "
                "check itself is hung, so breaches cannot be seen."]
    except Exception as exc:  # noqa: BLE001
        return [f"pipeline_health.py could not be run ({type(exc).__name__}: {exc})."]
    out = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
    err = (proc.stderr or "").strip()
    # An uncaught exception also exits 1, the same code as "breached".
    if proc.returncode not in (0, 1) or "Traceback (most recent call last)" in err:
        return out + [f"pipeline_health.py CRASHED (rc {proc.returncode})"
                      + (f":\n{err}" if err else " with no stderr.")]
    if proc.returncode == 0 and not out:
        return []
    if not out:
        return [f"pipeline_health.py exited {proc.returncode} (breach) without naming the breach"
                + (f"; stderr:\n{err}" if err else ".")]
    return out


def render(lines: List[str]) -> Optional[str]:
    if not lines:
        return None
    return _HEADING + "\n".join(f"- {ln}" for ln in lines)


def main() -> int:
    try:
        raw = sys.stdin.read()
        json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0
    try:
        context = render(breaches())
        if context:
            sys.stdout.write(json.dumps({"hookSpecificOutput": {
                "hookEventName": "SessionStart", "additionalContext": context}}))
    except Exception:
        return 0
    return 0


def _self_test() -> int:
    import tempfile
    failed: List[str] = []

    def check(name: str, ok: bool, hint: str = "") -> None:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  {hint}"))
        if not ok:
            failed.append(name)

    def fake_root(td: str, body: Optional[str]) -> Path:
        root = Path(td)
        (root / "scripts").mkdir(parents=True, exist_ok=True)
        if body is not None:
            (root / "scripts" / "pipeline_health.py").write_text(body, encoding="utf-8")
        return root

    with tempfile.TemporaryDirectory() as td:
        check("T1 healthy (rc 0, no output) is silent",
              render(breaches(fake_root(td, "import sys; sys.exit(0)"))) is None)
    with tempfile.TemporaryDirectory() as td:
        got = breaches(fake_root(td, "print('curate_turns: 185/195 runs failed since 2026-09-15')\n"
                                     "print('backlog claude: 778 pending, oldest 118 days')\n"
                                     "import sys; sys.exit(1)"))
        ctx = render(got) or ""
        check("T2 every breach line is relayed whole under the raise-it heading",
              len(got) == 2 and "185/195" in ctx and "778 pending" in ctx
              and ctx.startswith("JARVIS PIPELINE HEALTH — BREACHED"), ctx)
    with tempfile.TemporaryDirectory() as td:
        check("T3 a missing health check is itself a breach",
              "MISSING" in " ".join(breaches(fake_root(td, None))))
    with tempfile.TemporaryDirectory() as td:
        got = " ".join(breaches(fake_root(td, "raise RuntimeError('kaboom')")))
        check("T4 a crash is reported with its traceback", "CRASHED" in got and "kaboom" in got, got)
    with tempfile.TemporaryDirectory() as td:
        got = " ".join(breaches(fake_root(td, "import time; time.sleep(5)"), timeout=1.0))
        check("T5 a hung health check is reported, not waited on forever", "did not finish" in got, got)
    with tempfile.TemporaryDirectory() as td:
        got = " ".join(breaches(fake_root(td, "import sys; sys.exit(1)")))
        check("T6 a silent breach exit is still loud", "without naming" in got, got)
    json.dumps({"x": render(["→ ok"])}).encode("cp1252")
    print(f"  {6 - len(failed)}/6 passed")
    return 1 if failed else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(_self_test())
    raise SystemExit(main())
