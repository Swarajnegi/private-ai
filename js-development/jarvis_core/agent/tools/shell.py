"""
shell.py

JARVIS Agent Layer: Shell command tool (Category A — Callable, UNSAFE).

Import-time registration:
    @Tool.register("shell_run")

LAYER: Agent (Tools)

=============================================================================
THE BIG PICTURE
=============================================================================

Without shell_run:
    -> Agent can't invoke system utilities (git, ls, grep, find, curl, etc.).
       Many real-world tasks require shell glue that's painful to reimplement
       as Python tools.

With shell_run:
    -> Agent emits {"tool":"shell_run","input":{"command":"git status","timeout_seconds":30}}.
    -> We spawn the command via asyncio.create_subprocess_shell with a hard
       timeout and capture stdout/stderr/exit_code.
    -> NOT concurrency-safe — shell commands mutate everything: filesystem,
       network, environment, git state.
    -> requires_permission=True — STEAL #9 permission engine (Stage 3.4)
       gates by command. STEAL #10 bash-AST classifier auto-approves the safe
       allowlist (grep/cat/ls/head/tail/wc/find) before the user is prompted.

WHY create_subprocess_SHELL and not _EXEC:
    Shell pipelines (cmd1 | cmd2), redirections (> file), globs (*.py), and
    environment expansion ($HOME) need the shell. _exec gives us tighter
    process isolation but loses these features. The tradeoff is captured
    via permission gating + the AST classifier — the shell flexibility is
    intentional, the safety is checked above this layer.

SECURITY NOTE:
    Shell injection is a concern at the permission layer, NOT here. This
    tool is purpose-built to run shell commands. The defense is "only let
    the agent invoke it through STEAL #9 + STEAL #10".

=============================================================================
THE FLOW
=============================================================================

STEP 1: Agent emits {"tool":"shell_run","input":{"command":"...","timeout_seconds":30}}.
        |
        v
STEP 2: (Stage 3.4+) permission engine + bash AST classifier decide allow/ask/deny.
        At Stage 3.2 this is a no-op; gate fires when 3.4 ships.
        |
        v
STEP 3: asyncio.create_subprocess_shell(cmd, stdout=PIPE, stderr=PIPE).
        |
        v
STEP 4: asyncio.wait_for(proc.communicate(), timeout=N).
        TimeoutError -> kill + ToolResult(error="timeout").
        |
        v
STEP 5: Return ToolResult(output={"stdout","stderr","exit_code"}).

=============================================================================
"""

from __future__ import annotations

import asyncio
import os
import signal

from pydantic import Field

from jarvis_core.agent.tool import Tool, ToolInput, ToolResult


# =============================================================================
# Part 1: INPUT SCHEMA
# =============================================================================

class ShellRunInput(ToolInput):
    command: str = Field(description="Shell command line (subject to shell interpretation: pipes, globs, redirects).")
    timeout_seconds: int = Field(
        default=30, ge=1, le=300,
        description="Hard timeout. Process killed if exceeded.",
    )
    cwd: str = Field(
        default="",
        description="Working directory. Empty string = inherit caller's cwd.",
    )


# =============================================================================
# Part 2: TOOL
# =============================================================================

@Tool.register("shell_run")
class ShellRunTool(Tool):
    """Run a shell command with timeout. UNSAFE — gated by STEAL #9 + #10 at 3.4."""

    name = "shell_run"
    description = (
        "Run a shell command line via the system shell (supports pipes, "
        "redirects, globs, env expansion). Returns stdout, stderr, exit code. "
        "Hard timeout enforced (default 30s, max 300s). DANGEROUS: shell can "
        "modify filesystem, network, git state. Permission engine gates by command."
    )
    input_schema = ShellRunInput
    requires_permission = True  # STEAL #9 + #10 gate at 3.4

    @property
    def is_concurrency_safe(self) -> bool:
        return False  # Mutates everything

    async def invoke(self, tool_input: ShellRunInput) -> ToolResult:
        cwd = tool_input.cwd or None  # asyncio uses None to mean "caller's cwd"
        try:
            # start_new_session=True puts the shell in its own process group
            # so we can SIGKILL the entire tree on timeout (preventing orphaned
            # children like `sleep 60` from leaking subprocess transports).
            proc = await asyncio.create_subprocess_shell(
                tool_input.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                start_new_session=True,
            )
        except OSError as e:
            return ToolResult(error=f"Failed to spawn shell: {e}")

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=tool_input.timeout_seconds,
            )
        except asyncio.TimeoutError:
            # Kill the entire process group, not just the shell process.
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()  # Fallback if pgid lookup fails
            # Drain remaining output so the asyncio subprocess transport
            # closes cleanly (avoids 3.10 __del__ noise on interpreter exit).
            try:
                await asyncio.wait_for(proc.communicate(), timeout=2.0)
            except (asyncio.TimeoutError, Exception):
                pass
            return ToolResult(error=f"shell_run timeout after {tool_input.timeout_seconds}s; process group killed")

        return ToolResult(output={
            "stdout": stdout_bytes.decode("utf-8", errors="replace"),
            "stderr": stderr_bytes.decode("utf-8", errors="replace"),
            "exit_code": proc.returncode if proc.returncode is not None else -1,
        })


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS
# =============================================================================

if __name__ == "__main__":
    import tempfile
    from jarvis_core.agent.tool import safe_invoke

    print("=" * 60)
    print("  ShellRunTool — Smoke Tests")
    print("=" * 60)

    async def run() -> None:
        tool = ShellRunTool()

        # 1. Trivial echo
        r1 = await safe_invoke(tool, {"command": "echo hello jarvis"})
        assert r1.is_success, f"got {r1}"
        assert "hello jarvis" in r1.output["stdout"]
        assert r1.output["exit_code"] == 0
        print(f"  [OK] 'echo hello jarvis' works")

        # 2. Pipeline + glob (shell features)
        r2 = await safe_invoke(tool, {"command": "echo one; echo two | tr a-z A-Z"})
        assert r2.is_success and "TWO" in r2.output["stdout"]
        print(f"  [OK] pipeline 'echo two | tr a-z A-Z' works (shell interpretation)")

        # 3. Non-zero exit
        r3 = await safe_invoke(tool, {"command": "false"})
        assert r3.is_success and r3.output["exit_code"] != 0
        print(f"  [OK] non-zero exit code propagated (got {r3.output['exit_code']})")

        # 4. Stderr capture
        r4 = await safe_invoke(tool, {"command": "ls /no/such/path/xyz 2>&1 1>/dev/null"})
        # On most systems the redirection here means the error appears on stdout.
        # Use a cleaner pure-stderr test:
        r4b = await safe_invoke(tool, {"command": "echo errmsg 1>&2"})
        assert r4b.is_success and "errmsg" in r4b.output["stderr"]
        print(f"  [OK] stderr captured separately")

        # 5. Timeout kills runaway
        r5 = await safe_invoke(tool, {"command": "sleep 60", "timeout_seconds": 1})
        assert r5.is_error and "timeout" in r5.error.lower()
        print(f"  [OK] timeout kills 'sleep 60' after 1s: {r5.error}")

        # 6. cwd override
        with tempfile.TemporaryDirectory() as tmpdir:
            r6 = await safe_invoke(tool, {"command": "pwd", "cwd": tmpdir})
            assert r6.is_success
            # On macOS /tmp may be symlinked to /private/tmp; compare resolved
            from pathlib import Path
            assert Path(r6.output["stdout"].strip()).resolve() == Path(tmpdir).resolve()
            print(f"  [OK] cwd override works ({tmpdir})")

        # 7. Concurrency-unsafe + requires permission
        assert tool.is_concurrency_safe is False
        assert ShellRunTool.requires_permission is True
        print(f"  [OK] is_concurrency_safe=False, requires_permission=True")

        # 8. Registry + schema
        assert Tool.get_or_raise("shell_run") is ShellRunTool
        schema = ShellRunTool.schema_for_llm()
        assert "command" in schema["input_schema"]["properties"]
        print(f"  [OK] registered + schema valid")

        print("=" * 60)
        print("  All 8 smoke tests passed.")
        print("=" * 60)

    asyncio.run(run())
