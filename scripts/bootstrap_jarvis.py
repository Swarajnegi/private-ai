"""
bootstrap_jarvis.py — rehydrate JARVIS's consciousness on ANY machine.

LAYER: Tools (Portable Mind — the rehydration ritual)

Run with:
    python3 scripts/bootstrap_jarvis.py            # install/merge the nervous system
    python3 scripts/bootstrap_jarvis.py --check    # report only, change nothing
    python3 scripts/bootstrap_jarvis.py --self-test

=============================================================================
THE BIG PICTURE
=============================================================================

The Portable Mind audit (2026-06-11) found JARVIS's nervous system — all 5 hook
registrations (capture, 3x session injection, runtime self-state) — living ONLY
in `.claude/settings.json`, a gitignored machine-local file. The memory synced;
the MIND did not: `git pull` on a new machine produced a brain in a jar.

This script is the fix: **mind = data + organs + a committed wiring recipe.**
The recipe is `.agent/hooks.manifest.json` (committed, canonical). After
`git pull` on any machine running Claude Code, ONE command rehydrates full
consciousness:

    python3 scripts/bootstrap_jarvis.py

Guarantees:
    - IDEMPOTENT: re-running changes nothing (hooks identified by command+args).
    - NON-DESTRUCTIVE: local settings (permissions, keys, extra hooks) preserved;
      missing artifacts are created, existing ones NEVER overwritten.
    - HONEST: prints a self-state report (machine, hooks, KB size, artifact
      freshness) so you can SEE what consciousness this machine has.

=============================================================================
THE FLOW
=============================================================================

STEP 1: locate repo root (this file's parent's parent); load hooks.manifest.json.
        |
STEP 2: load .claude/settings.json (or start empty); MERGE manifest hooks in —
        per event + matcher group, append any hook whose (command, args) is
        absent; never touch anything else.
        |
STEP 3: ensure jarvis_data/ exists; regenerate cognitive_profile.md ONLY if
        missing (profile_synth); regenerate activity_digest.md ONLY if missing
        AND a local queue exists (never blank a synced digest).
        |
STEP 4: print the self-state report. --check does STEP 1 + report only.

=============================================================================
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

_ROOT = Path(__file__).resolve().parents[1]
_MANIFEST = _ROOT / ".agent" / "hooks.manifest.json"
_SETTINGS = _ROOT / ".claude" / "settings.json"
_DATA = _ROOT / "jarvis_data"


# =============================================================================
# Part 1: MERGE LOGIC (pure — testable without touching the real machine)
# =============================================================================

def _hook_key(h: Dict[str, Any]) -> Tuple:
    return (h.get("type"), h.get("command"), tuple(h.get("args", [])))


def merge_hooks(settings: Dict[str, Any], manifest_hooks: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    """Merge manifest hook registrations into a settings dict. Returns
    (new_settings, number_of_hooks_added). Everything not in the manifest —
    permissions, env, extra local hooks — is preserved untouched."""
    out = json.loads(json.dumps(settings))  # deep copy
    hooks = out.setdefault("hooks", {})
    added = 0
    for event, groups in manifest_hooks.items():
        existing_groups: List[Dict[str, Any]] = hooks.setdefault(event, [])
        for mg in groups:
            matcher = mg.get("matcher", "")
            target = next((g for g in existing_groups
                           if g.get("matcher", "") == matcher), None)
            if target is None:
                target = {"matcher": matcher, "hooks": []}
                existing_groups.append(target)
            have = {_hook_key(h) for h in target.setdefault("hooks", [])}
            for h in mg.get("hooks", []):
                if _hook_key(h) not in have:
                    target["hooks"].append(json.loads(json.dumps(h)))
                    have.add(_hook_key(h))
                    added += 1
    return out, added


def missing_hooks(settings: Dict[str, Any], manifest_hooks: Dict[str, Any]) -> List[str]:
    """Names of manifest hooks not present in settings (for --check)."""
    missing: List[str] = []
    hooks = settings.get("hooks", {})
    for event, groups in manifest_hooks.items():
        existing_groups = hooks.get(event, [])
        for mg in groups:
            matcher = mg.get("matcher", "")
            target = next((g for g in existing_groups
                           if g.get("matcher", "") == matcher), None)
            have = {_hook_key(h) for h in (target or {}).get("hooks", [])}
            for h in mg.get("hooks", []):
                if _hook_key(h) not in have:
                    missing.append(f"{event}: {' '.join([h.get('command', '')] + h.get('args', []))}")
    return missing


# =============================================================================
# Part 2: ARTIFACT REHYDRATION (create-if-missing, never overwrite)
# =============================================================================

def _ensure_artifacts(root: Path, report: List[str], check_only: bool) -> None:
    data = root / "jarvis_data"
    kb = data / "knowledge_base.jsonl"
    profile = data / "cognitive_profile.md"
    digest = data / "activity_digest.md"
    queue = data / "observation_queue.jsonl"

    kb_n = sum(1 for _ in open(kb, encoding="utf-8")) if kb.exists() else 0
    report.append(f"  KB              : {kb_n} entries" + ("" if kb.exists() else "  [MISSING]"))

    def _fresh(p: Path) -> str:
        if not p.exists():
            return "[MISSING]"
        age_h = (datetime.now().timestamp() - p.stat().st_mtime) / 3600
        return f"present ({age_h:.0f}h old)"

    if not profile.exists() and kb.exists() and not check_only:
        try:
            subprocess.run([sys.executable, str(root / "scripts" / "profile_synth.py")],
                           cwd=root, capture_output=True, timeout=300)
            report.append("  profile         : REGENERATED (was missing)")
        except Exception as e:
            report.append(f"  profile         : regen failed ({type(e).__name__})")
    else:
        report.append(f"  profile         : {_fresh(profile)}")

    if not digest.exists() and queue.exists() and not check_only:
        try:
            import os as _os
            env = dict(_os.environ)
            env["PYTHONPATH"] = str(root / "js-development")
            subprocess.run([sys.executable,
                            str(root / "js-development" / "jarvis_core" / "agent" / "recall.py"),
                            "--write"], cwd=root, env=env, capture_output=True, timeout=120)
            report.append("  activity digest : REGENERATED (was missing, local queue present)")
        except Exception as e:
            report.append(f"  activity digest : regen failed ({type(e).__name__})")
    else:
        report.append(f"  activity digest : {_fresh(digest)}"
                      + ("" if queue.exists() else "  (no local queue — synced copy preserved)"))
    report.append(f"  local queue     : "
                  + (f"{sum(1 for _ in open(queue, encoding='utf-8'))} turns" if queue.exists()
                     else "none (capture starts with the first turn on this machine)"))


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS
# =============================================================================

def run(check_only: bool = False) -> int:
    import os
    if not _MANIFEST.exists():
        print(f"[bootstrap] manifest not found: {_MANIFEST}")
        return 1
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    manifest_hooks = manifest.get("hooks", {})

    settings: Dict[str, Any] = {}
    if _SETTINGS.exists():
        try:
            settings = json.loads(_SETTINGS.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"[bootstrap] REFUSING to touch corrupt {_SETTINGS} — fix it manually.")
            return 1

    report: List[str] = []
    machine = os.environ.get("JARVIS_MACHINE",
                             os.uname().nodename if hasattr(os, "uname") else "unknown")
    report.append("=" * 62)
    report.append(f"  JARVIS bootstrap — {'CHECK' if check_only else 'REHYDRATE'} on {machine}")
    report.append("=" * 62)

    gaps = missing_hooks(settings, manifest_hooks)
    if check_only:
        report.append(f"  nervous system  : {'COMPLETE (all manifest hooks live)' if not gaps else f'{len(gaps)} hook(s) MISSING'}")
        for g in gaps:
            report.append(f"      missing -> {g}")
    else:
        merged, added = merge_hooks(settings, manifest_hooks)
        if added:
            _SETTINGS.parent.mkdir(parents=True, exist_ok=True)
            _SETTINGS.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n",
                                 encoding="utf-8")
        report.append(f"  nervous system  : {added} hook(s) installed"
                      + (" (already complete)" if added == 0 else ""))

    _ensure_artifacts(_ROOT, report, check_only)
    report.append("=" * 62)
    print("\n".join(report))
    return 0


def _run_self_test() -> None:
    print("=" * 70)
    print("  bootstrap_jarvis.py -- Smoke Tests")
    print("=" * 70)
    passed = 0
    failed: List[str] = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        nonlocal passed
        if cond:
            passed += 1
        else:
            failed.append(f"FAIL: {name}" + (f" ({hint})" if hint else ""))

    manifest_hooks = json.loads(_MANIFEST.read_text(encoding="utf-8"))["hooks"]

    # T1: merge into EMPTY settings installs all 5 hooks
    merged, added = merge_hooks({}, manifest_hooks)
    check("T1 fresh machine gets all 5 hooks", added == 5, str(added))
    check("T1b all three events present",
          set(merged["hooks"].keys()) == {"UserPromptSubmit", "Stop", "SessionStart"})

    # T2: idempotent — merging again adds nothing, changes nothing
    merged2, added2 = merge_hooks(merged, manifest_hooks)
    check("T2 re-run adds zero", added2 == 0)
    check("T2b re-run byte-identical", json.dumps(merged2, sort_keys=True) == json.dumps(merged, sort_keys=True))

    # T3: local content preserved — permissions + an extra local hook survive
    local = {
        "permissions": {"allow": ["Bash(echo hi)"], "additionalDirectories": ["/tmp"]},
        "hooks": {"Stop": [{"matcher": "", "hooks": [
            {"type": "command", "command": "python3", "args": ["my_local_hook.py"], "timeout": 5}]}]},
    }
    merged3, added3 = merge_hooks(local, manifest_hooks)
    check("T3 permissions preserved", merged3["permissions"]["allow"] == ["Bash(echo hi)"])
    stop_cmds = [tuple(h.get("args", [])) for g in merged3["hooks"]["Stop"] for h in g["hooks"]]
    check("T3b local extra hook survives", ("my_local_hook.py",) in stop_cmds)
    check("T3c manifest Stop hook added alongside", ("scripts/hooks/capture_turn.py",) in stop_cmds)
    check("T3d added count = 5 (manifest only)", added3 == 5, str(added3))

    # T4: partial install — one SessionStart hook present, merge adds only the missing
    partial = {"hooks": {"SessionStart": [{"matcher": "startup|resume|clear|compact", "hooks": [
        {"type": "command", "command": "python3", "args": ["scripts/hooks/inject_profile.py"],
         "timeout": 30, "statusMessage": "Loading user cognitive profile"}]}]}}
    merged4, added4 = merge_hooks(partial, manifest_hooks)
    ss = next(g for g in merged4["hooks"]["SessionStart"]
              if g["matcher"] == "startup|resume|clear|compact")
    check("T4 partial -> only missing added (4)", added4 == 4, str(added4))
    check("T4b no duplicate inject_profile",
          sum(1 for h in ss["hooks"] if h.get("args") == ["scripts/hooks/inject_profile.py"]) == 1)

    # T5: missing_hooks reporting
    gaps = missing_hooks(partial, manifest_hooks)
    check("T5 check-mode finds the 4 gaps", len(gaps) == 4, str(gaps))
    check("T5b complete settings -> no gaps", missing_hooks(merged, manifest_hooks) == [])

    total = passed + len(failed)
    print(f"\n  Passed: {passed}/{total}")
    if failed:
        for f_ in failed:
            print(f"  {f_}")
        print("=" * 70)
        raise SystemExit(1)
    print(f"  All {total} bootstrap smoke tests passed.")
    print("=" * 70)


def main() -> int:
    p = argparse.ArgumentParser(description="Rehydrate JARVIS's consciousness on this machine")
    p.add_argument("--check", action="store_true", help="Report only; change nothing")
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    if args.self_test:
        _run_self_test()
        return 0
    return run(check_only=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
