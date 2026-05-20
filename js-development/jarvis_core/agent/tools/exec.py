"""
exec.py

JARVIS Agent Layer: Code execution tool (Category A — Callable, UNSAFE).

Import-time registration:
    @Tool.register("code_exec")

LAYER: Agent (Tools)

=============================================================================
THE BIG PICTURE
=============================================================================

Without code_exec:
    -> Agent can't run arbitrary Python. Every computation beyond `calculator`
       requires the user to run code manually.

With code_exec:
    -> Agent emits a Python source string; we spawn `python -c <code>` in a
       subprocess with a timeout, capture stdout/stderr, return as ToolResult.
    -> NOT concurrency-safe — code can mutate the filesystem, install packages,
       open network sockets. Tools that mutate global state must run serially.
    -> requires_permission=True — STEAL #9 permission engine (Stage 3.4) must
       gate this before invocation. At Stage 3.2 (now) the flag exists; the
       gate doesn't fire yet (no permission engine until 3.4).

WHY a subprocess and not in-process eval/exec:
    1. Isolation: a crash, infinite loop, or sys.exit() inside the subprocess
       cannot kill JARVIS itself.
    2. Timeout: we can asyncio.wait_for the subprocess and kill it cleanly.
    3. Honest sandbox: in-process exec gives the false impression of safety.
       The subprocess is at least bounded by OS process limits + timeout.
       (For true cryptographic sandboxing, gVisor / Firecracker — Stage 6.)

=============================================================================
THE FLOW
=============================================================================

STEP 1: Agent emits {"tool":"code_exec","input":{"code":"...","timeout_seconds":30}}.
        |
        v
STEP 2: Pydantic validates code (str) + timeout in [1, 300].
        |
        v
STEP 3: asyncio.create_subprocess_exec(sys.executable, "-c", code, ...) with
        stdout=PIPE, stderr=PIPE.
        |
        v
STEP 4: asyncio.wait_for(proc.communicate(), timeout=timeout_seconds).
        TimeoutError -> proc.kill() + wait for exit + ToolResult(error="timeout").
        |
        v
STEP 5: Return ToolResult(output={"stdout","stderr","exit_code"}).

=============================================================================
"""

from __future__ import annotations

import asyncio
import sys

from pydantic import Field

from jarvis_core.agent.tool import Tool, ToolInput, ToolResult


# =============================================================================
# Part 1: INPUT SCHEMA
# =============================================================================

class CodeExecInput(ToolInput):
    code: str = Field(description="Python source code to execute (passed via `python -c`).")
    timeout_seconds: int = Field(
        default=30, ge=1, le=300,
        description="Hard timeout. Process is killed if it exceeds this.",
    )


# =============================================================================
# Part 2: TOOL
# =============================================================================

@Tool.register("code_exec")
class CodeExecTool(Tool):
    """Execute Python source in an isolated subprocess with timeout.

    UNSAFE: process can read/write filesystem, open sockets, install packages.
    Permission engine (STEAL #9, Stage 3.4) gates this before invocation.
    """

    name = "code_exec"
    description = (
        "Execute Python source code in an isolated subprocess and return stdout, "
        "stderr, and exit code. Hard timeout enforced (default 30s, max 300s). "
        "DANGEROUS: the code runs with the agent's user permissions and can "
        "read/write files and open network connections."
    )
    input_schema = CodeExecInput
    requires_permission = True  # STEAL #9 will gate at 3.4

    @property
    def is_concurrency_safe(self) -> bool:
        return False  # Mutates state, filesystem, processes

    async def invoke(self, tool_input: CodeExecInput) -> ToolResult:
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-c", tool_input.code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as e:
            return ToolResult(error=f"Failed to spawn subprocess: {e}")

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=tool_input.timeout_seconds,
            )
        except asyncio.TimeoutError:
            proc.kill()
            # Drain pipes via communicate() so the subprocess transport
            # closes cleanly (avoids asyncio 3.10 __del__ noise on exit).
            try:
                await asyncio.wait_for(proc.communicate(), timeout=2.0)
            except (asyncio.TimeoutError, Exception):
                pass
            return ToolResult(error=f"code_exec timeout after {tool_input.timeout_seconds}s; process killed")

        return ToolResult(output={
            "stdout": stdout_bytes.decode("utf-8", errors="replace"),
            "stderr": stderr_bytes.decode("utf-8", errors="replace"),
            "exit_code": proc.returncode if proc.returncode is not None else -1,
        })


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS  (real subprocess, fast cases only)
# =============================================================================

if __name__ == "__main__":
    from jarvis_core.agent.tool import safe_invoke

    print("=" * 60)
    print("  CodeExecTool — Smoke Tests")
    print("=" * 60)

    async def run() -> None:
        tool = CodeExecTool()

        # 1. Success: print hello
        r1 = await safe_invoke(tool, {"code": "print('hello jarvis')"})
        assert r1.is_success, f"got {r1}"
        assert r1.output["stdout"].strip() == "hello jarvis"
        assert r1.output["exit_code"] == 0
        print(f"  [OK] 'print(\\'hello jarvis\\')' -> stdout='hello jarvis', exit=0")

        # 2. Stderr capture
        r2 = await safe_invoke(tool, {"code": "import sys; sys.stderr.write('warn\\n')"})
        assert r2.is_success
        assert "warn" in r2.output["stderr"]
        print(f"  [OK] stderr captured")

        # 3. Non-zero exit
        r3 = await safe_invoke(tool, {"code": "import sys; sys.exit(2)"})
        assert r3.is_success and r3.output["exit_code"] == 2
        print(f"  [OK] non-zero exit code propagated (got {r3.output['exit_code']})")

        # 4. SyntaxError surfaces in stderr, non-zero exit
        r4 = await safe_invoke(tool, {"code": "def broken(:"})
        assert r4.is_success and r4.output["exit_code"] != 0
        assert "SyntaxError" in r4.output["stderr"]
        print(f"  [OK] SyntaxError surfaces in stderr with non-zero exit")

        # 5. Timeout kills process
        r5 = await safe_invoke(tool, {"code": "import time; time.sleep(60)", "timeout_seconds": 1})
        assert r5.is_error and "timeout" in r5.error.lower()
        print(f"  [OK] timeout kills runaway process: {r5.error}")

        # 6. Concurrency-unsafe + requires permission
        assert tool.is_concurrency_safe is False
        assert CodeExecTool.requires_permission is True
        print(f"  [OK] is_concurrency_safe=False, requires_permission=True")

        # 7. Validation: timeout out of range
        r7 = await safe_invoke(tool, {"code": "pass", "timeout_seconds": 99999})
        assert r7.is_error
        print(f"  [OK] timeout_seconds=99999 rejected by Pydantic")

        # 8. Registry + schema
        assert Tool.get_or_raise("code_exec") is CodeExecTool
        schema = CodeExecTool.schema_for_llm()
        assert "code" in schema["input_schema"]["properties"]
        print(f"  [OK] registered + schema valid")

        print("=" * 60)
        print("  All 8 smoke tests passed.")
        print("=" * 60)

    asyncio.run(run())
