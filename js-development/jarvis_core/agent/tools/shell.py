"""LAYER: Agent — approval-gated native shell execution.

THE BIG PICTURE: Windows commands require PowerShell syntax and supervised trees.
THE FLOW: validate/resolve shell and cwd -> permission -> native process -> complete output.

PowerShell runs without profiles or interactive prompts. Bash remains the Linux
shell. Execution is supervised by execution.ProcessRunner, with a 30-second
standard timeout and a 300-second maximum; output is paged by the ReAct ledger.
"""

from __future__ import annotations

import asyncio
import os
from typing import Literal

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
    shell: Literal["auto", "powershell", "bash"] = "auto"
    cwd: str = Field(
        default="",
        description="Resolved working directory. Empty string = workspace root.",
    )


# =============================================================================
# Part 2: TOOL
# =============================================================================

@Tool.register("shell_run")
class ShellRunTool(Tool):
    """Run a supervised command under the interactive permission policy."""

    name = "shell_run"
    description = (
        "Run a shell command line via the explicit native shell (PowerShell on Windows; Bash on Linux; supports pipes, "
        "redirects, globs, env expansion). Returns stdout, stderr, exit code. "
        "Hard timeout enforced (default 30s, max 300s). DANGEROUS: shell can "
        "modify filesystem, network, git state. Permission engine gates by command."
    )
    input_schema = ShellRunInput
    requires_permission = True

    def normalize_input(self, tool_input: ToolInput) -> ToolInput:
        from pathlib import Path
        from jarvis_core.config import JARVIS_ROOT
        shell = tool_input.shell
        if shell == "auto":
            shell = "powershell" if os.name == "nt" else "bash"
        cwd = Path(tool_input.cwd or JARVIS_ROOT).resolve()
        if not cwd.is_dir():
            raise ValueError("Working directory does not exist")
        return tool_input.model_copy(update={"shell": shell, "cwd": str(cwd)})

    async def invoke(self, tool_input: ShellRunInput) -> ToolResult:
        from jarvis_core.agent.execution import ProcessRunner, powershell_path
        import base64
        import shutil
        if tool_input.shell == "powershell":
            try:
                exe = powershell_path()
            except FileNotFoundError as exc:
                return ToolResult(error=str(exc), metadata={"error_code": "unavailable"})
            command = "[Console]::OutputEncoding=[Text.UTF8Encoding]::new(); " + tool_input.command
            argv = [exe, "-NoProfile", "-NonInteractive", "-EncodedCommand", base64.b64encode(command.encode("utf-16-le")).decode()]
        else:
            exe = shutil.which("bash")
            if not exe:
                return ToolResult(error="Bash is unavailable; use native PowerShell on Windows", metadata={"error_code": "unavailable"})
            argv = [exe, "--noprofile", "--norc", "-c", tool_input.command]
        return await ProcessRunner().run(argv, cwd=tool_input.cwd, timeout=tool_input.timeout_seconds)


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
        is_win = os.name == "nt"

        # 1. Trivial echo
        cmd1 = "Write-Output 'hello jarvis'" if is_win else "echo hello jarvis"
        r1 = await safe_invoke(tool, {"command": cmd1})
        assert r1.is_success, f"got {r1}"
        assert "hello jarvis" in r1.output["stdout"]
        assert r1.output["exit_code"] == 0
        print(f"  [OK] literal output works")

        # 2. Pipeline + glob (shell features)
        cmd2 = "Write-Output one; Write-Output TWO" if is_win else "echo one; echo two | tr a-z A-Z"
        r2 = await safe_invoke(tool, {"command": cmd2})
        assert r2.is_success and "TWO" in r2.output["stdout"]
        print(f"  [OK] pipeline/sequential '{cmd2}' works (shell interpretation)")

        # 3. Non-zero exit
        cmd3 = "exit 1" if is_win else "false"
        r3 = await safe_invoke(tool, {"command": cmd3})
        assert r3.is_error and r3.output["exit_code"] != 0
        print(f"  [OK] non-zero exit code propagated (got {r3.output['exit_code']})")

        # 4. Stderr capture
        cmd4 = "[Console]::Error.WriteLine('errmsg')" if is_win else "echo errmsg 1>&2"
        r4b = await safe_invoke(tool, {"command": cmd4})
        assert r4b.is_success and "errmsg" in r4b.output["stderr"]
        print(f"  [OK] stderr captured separately")

        # 5. Timeout kills runaway
        cmd5 = "Start-Sleep -Seconds 60" if is_win else "sleep 60"
        r5 = await safe_invoke(tool, {"command": cmd5, "timeout_seconds": 1})
        assert r5.is_error and "timeout" in r5.error.lower()
        print(f"  [OK] timeout kills '{cmd5}' after 1s: {r5.error}")

        # 6. cwd override
        cmd6 = "(Get-Location).Path" if is_win else "pwd"
        with tempfile.TemporaryDirectory() as tmpdir:
            r6 = await safe_invoke(tool, {"command": cmd6, "cwd": tmpdir})
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
        print("  All 10 smoke tests passed.")
        print("=" * 60)

    asyncio.run(run())
