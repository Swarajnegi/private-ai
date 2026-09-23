"""
run_hook.py — Universal, fail-closed Claude Code hook dispatcher for JARVIS.

LAYER: Tools (Claude Code adapter / nervous system runner)

Why this exists:
1. Claude Code on Windows does NOT expand bash-style `$CLAUDE_PROJECT_DIR` in hook args.
2. Bare relative paths like `scripts/hooks/<hook>.py` break whenever Claude navigates
   into a subfolder (e.g. `rfm_2.0/`).
3. Hardcoded paths (`E:\\J.A.R.V.I.S` vs `/home/swara_unix/work/JARVIS`) break cross-host sync.
4. KB L486: "Fails silent and always exits 0 -- a broken nudge must never cost a turn."
   Any non-zero exit code from a UserPromptSubmit hook blocks the user prompt and locks
   them out.

This dispatcher:
- Resolves repo root dynamically via CLAUDE_PROJECT_DIR or by walking up cwd parents.
- Sets cwd to repo root and adds js-development to sys.path.
- Dispatches to scripts/hooks/<hook_name>.
- Catches ALL exceptions (including BaseException) and exits 0.
"""

from __future__ import annotations

import os
import pathlib
import runpy
import sys
from typing import Optional


def find_repo_root() -> Optional[pathlib.Path]:
    """Dynamically resolve the JARVIS repository root."""
    env_dir = os.environ.get("CLAUDE_PROJECT_DIR", "").strip()
    if env_dir:
        p = pathlib.Path(env_dir)
        if (p / "scripts" / "hooks").is_dir():
            return p

    cwd = pathlib.Path.cwd()
    for directory in [cwd, *cwd.parents]:
        if (directory / "scripts" / "hooks").is_dir():
            return directory

    return None


def run_hook(hook_name: str) -> int:
    """Execute target hook inside repo root, failing closed to exit 0."""
    try:
        root = find_repo_root()
        if not root:
            return 0

        os.chdir(str(root))
        js_dev = str(root / "js-development")
        if js_dev not in sys.path:
            sys.path.insert(0, js_dev)

        hook_path = root / "scripts" / "hooks" / hook_name
        if hook_path.is_file():
            runpy.run_path(str(hook_path), run_name="__main__")
    except BaseException:
        pass  # Never disrupt a turn (KB L486)
    return 0


def _self_test() -> None:
    print("=" * 60)
    print("  run_hook.py -- Smoke Tests")
    print("=" * 60)
    root = find_repo_root()
    assert root is not None, "Failed to resolve repo root"
    assert (root / "scripts" / "hooks").is_dir(), "scripts/hooks not found"
    print(f"  PASS repo root resolved: {root}")

    # Test running with nonexistent hook - must return 0
    res = run_hook("nonexistent_test_hook.py")
    assert res == 0, f"Expected 0, got {res}"
    print("  PASS nonexistent hook exits 0")

    print("  All smoke tests passed.")
    print("=" * 60)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        _self_test()
        sys.exit(0)

    if len(sys.argv) > 1:
        sys.exit(run_hook(sys.argv[1]))

    sys.exit(0)
