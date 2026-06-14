"""
permgate.py — Permission Gate for the full-capability terminal (Stage 4.1).

LAYER: Brain (host safety policy — who may run what, decided here)

Import with:
    from jarvis_core.brain.permgate import build_permission_context, terminal_ask_handler

=============================================================================
THE BIG PICTURE
=============================================================================

Wiring the FULL toolset into --ask hands a weak, flaky free model `shell_run`,
`code_exec`, and `file_read`. The ReActLoop gates EVERY tool through
PermissionContext.check() (react.py) — but only if a context is wired; with
none, everything dispatches freely. So the full harness REQUIRES a policy.

This module is that policy, composed from the Stage 3 engine (permissions.py +
bash_classifier.py), with two principles:

  - DERIVED, not hardcoded. The ASK rules come from each tool's own
    `requires_permission` flag, so a future dangerous tool self-gates without
    editing a list here.
  - The cloud-leak guard. `file_read` is read-only and declares no permission,
    BUT its output is fed back into the prompt sent to the cloud LLM — so a
    model reading ~/.bashrc would ship the OpenRouter API key off-box. We
    repo-scope file_read: in-repo reads auto-allow; anything else asks the human.

The human-in-the-loop is `terminal_ask_handler` — it prints the proposed call
and waits for [y/N]. FAIL-CLOSED: no TTY / EOF / error -> DENY, so piped, test,
and background runs can never auto-approve a shell command.

=============================================================================
THE FLOW
=============================================================================

STEP 1: build_permission_context(tools): ASK rule per requires_permission tool;
        register the bash classifier for shell_run and the repo-scope classifier
        for file_read; default ALLOW for the safe majority.
        |
STEP 2: check() priority (permissions.py): classifier -> rules -> default. So
        shell_run/file_read decisions come from their classifiers; code_exec
        from its ASK rule; everything else ALLOWs.
        |
STEP 3: on ASK, ReActLoop calls terminal_ask_handler -> [y/N] -> ALLOW | DENY.
        Non-ALLOW blocks dispatch (fail-closed).

=============================================================================
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # standalone-run safety

from jarvis_core.config import JARVIS_ROOT
from jarvis_core.agent.permissions import PermissionContext, PermissionDecision, PermissionRule
from jarvis_core.agent.bash_classifier import BashClassifier


def _repo_scoped_file_read_classifier(repo_root: Path):
    """ALLOW a file_read whose path resolves inside the repo; ASK otherwise.

    The guard: file_read output is sent to the cloud LLM, so an out-of-repo read
    (~/.bashrc, ~/.ssh) would exfiltrate secrets. In-repo source is safe to read
    freely; anything else needs the human."""
    root = repo_root.resolve()

    async def classify(tool_input: Dict[str, Any]) -> Optional[PermissionDecision]:
        raw = str((tool_input or {}).get("path", "")).strip()
        if not raw:
            return PermissionDecision.ASK
        try:
            target = Path(raw).expanduser()
            if not target.is_absolute():
                target = root / target
            target = target.resolve()
        except (OSError, RuntimeError, ValueError):
            return PermissionDecision.ASK
        if target == root or root in target.parents:
            return PermissionDecision.ALLOW
        return PermissionDecision.ASK  # out-of-repo -> human decides (cloud-leak guard)

    return classify


def build_permission_context(
    tools: Dict[str, Any], repo_root: Path = JARVIS_ROOT
) -> PermissionContext:
    """Derive the safety policy from the toolset itself.

    - ASK rule for every tool that declares requires_permission=True (shell_run,
      code_exec today; future dangerous tools self-gate).
    - default ALLOW for the safe majority (memory / cognitive / finance / calc / web).
    - classifiers (priority over rules): bash AST for shell_run, repo-scope for file_read.
    """
    rules = [
        PermissionRule(name, PermissionDecision.ASK,
                       description="requires_permission tool — gated to the human")
        for name, tool in tools.items()
        if getattr(tool, "requires_permission", False)
    ]
    ctx = PermissionContext(rules=rules, default=PermissionDecision.ALLOW)
    if "shell_run" in tools:
        ctx.register_classifier("shell_run", BashClassifier().classify_async)
    if "file_read" in tools:
        ctx.register_classifier("file_read", _repo_scoped_file_read_classifier(repo_root))
    return ctx


def terminal_ask_handler(tool_name: str, tool_input: Dict[str, Any]) -> PermissionDecision:
    """Human-in-the-loop [y/N]. FAIL-CLOSED: no TTY / EOF / error -> DENY."""
    try:
        if not sys.stdin or not sys.stdin.isatty():
            sys.stderr.write(
                f"  [permission] {tool_name} needs approval but no TTY -> DENY\n")
            return PermissionDecision.DENY
        preview = str(tool_input)
        if len(preview) > 300:
            preview = preview[:300] + "…"
        sys.stderr.write(f"\n  [permission] JARVIS wants to run '{tool_name}': {preview}\n")
        sys.stderr.write("  Allow? [y/N] ")
        sys.stderr.flush()
        answer = input().strip().lower()
        return PermissionDecision.ALLOW if answer in ("y", "yes") else PermissionDecision.DENY
    except (EOFError, KeyboardInterrupt, OSError):
        return PermissionDecision.DENY


def allow_all_ask_handler(tool_name: str, tool_input: Dict[str, Any]) -> PermissionDecision:
    """YOLO handler for unattended power use (--allow-all). DANGEROUS: a weak model
    gets shell/exec with no human gate. Only for trusted, sandboxed batch runs."""
    return PermissionDecision.ALLOW


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS (offline)
# =============================================================================

def _run_self_test() -> None:
    import asyncio

    print("=" * 70)
    print("  permgate.py -- Smoke Tests")
    print("=" * 70)
    passed = 0
    failed = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        nonlocal passed
        if cond:
            passed += 1
        else:
            failed.append(f"FAIL: {name}" + (f" ({hint})" if hint else ""))

    class _Tool:
        def __init__(self, rp): self.requires_permission = rp

    tools = {
        "calculator": _Tool(False), "memory_semantic_search": _Tool(False),
        "file_read": _Tool(False), "shell_run": _Tool(True), "code_exec": _Tool(True),
    }
    ctx = build_permission_context(tools, repo_root=JARVIS_ROOT)

    async def scenario() -> None:
        nonlocal passed
        # T1: safe tool -> ALLOW (default)
        check("T1 safe tool ALLOW",
              await ctx.check("calculator", {}) == PermissionDecision.ALLOW)
        check("T1b memory tool ALLOW",
              await ctx.check("memory_semantic_search", {"query": "x"}) == PermissionDecision.ALLOW)

        # T2: code_exec -> ASK (derived from requires_permission)
        check("T2 code_exec ASK (derived)",
              await ctx.check("code_exec", {"code": "print(1)"}) == PermissionDecision.ASK)

        # T3: shell_run classifier — safe cmd ALLOW, dangerous ASK/DENY
        d_ls = await ctx.check("shell_run", {"command": "ls -la"})
        d_rm = await ctx.check("shell_run", {"command": "rm -rf /tmp/x"})
        check("T3 shell safe ALLOW", d_ls == PermissionDecision.ALLOW, str(d_ls))
        check("T3b shell dangerous not ALLOW", d_rm != PermissionDecision.ALLOW, str(d_rm))

        # T4: file_read repo-scope — in-repo ALLOW, out-of-repo ASK
        in_repo = str(JARVIS_ROOT / "js-development" / "jarvis_core" / "brain" / "boot.py")
        check("T4 in-repo file_read ALLOW",
              await ctx.check("file_read", {"path": in_repo}) == PermissionDecision.ALLOW)
        check("T4b out-of-repo file_read ASK",
              await ctx.check("file_read", {"path": "/etc/passwd"}) == PermissionDecision.ASK)
        check("T4c home-secret file_read ASK (cloud-leak guard)",
              await ctx.check("file_read", {"path": "~/.bashrc"}) == PermissionDecision.ASK)
        check("T4d relative in-repo path ALLOW",
              await ctx.check("file_read", {"path": "README.md"}) == PermissionDecision.ALLOW)
        check("T4e empty path -> ASK",
              await ctx.check("file_read", {"path": ""}) == PermissionDecision.ASK)

    asyncio.run(scenario())

    # T5: no requires_permission tools -> no ASK rules, all default ALLOW
    safe_ctx = build_permission_context({"calculator": _Tool(False)})
    import asyncio as _a
    check("T5 all-safe toolset -> ALLOW default",
          _a.run(safe_ctx.check("calculator", {})) == PermissionDecision.ALLOW)

    # T6: terminal_ask_handler fail-closed on non-TTY (test stdin is not a TTY)
    check("T6 ask_handler DENY without a TTY",
          terminal_ask_handler("shell_run", {"command": "rm -rf /"}) == PermissionDecision.DENY)

    # T7: allow_all handler always ALLOW
    check("T7 allow_all -> ALLOW",
          allow_all_ask_handler("shell_run", {"command": "anything"}) == PermissionDecision.ALLOW)

    total = passed + len(failed)
    print(f"\n  Passed: {passed}/{total}")
    if failed:
        for f_ in failed:
            print(f"  {f_}")
        print("=" * 70)
        raise SystemExit(1)
    print(f"  All {total} permgate smoke tests passed.")
    print("=" * 70)


if __name__ == "__main__":
    _run_self_test()
