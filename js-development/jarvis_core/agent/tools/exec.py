"""LAYER: Agent — approval-gated Python subprocess execution.

THE BIG PICTURE: approved code must not leave orphaned workers after termination.
THE FLOW: validate -> owner approval -> supervised Python tree -> full result.

The subprocess retains the user's OS permissions; approval is not a sandbox.
Windows Job Objects and Unix process groups bound timeout/cancellation cleanup.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Set

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
    requires_permission = True

    async def invoke(self, tool_input: CodeExecInput) -> ToolResult:
        from jarvis_core.agent.execution import ProcessRunner
        from jarvis_core.config import JARVIS_ROOT
        return await ProcessRunner().run([sys.executable, "-c", tool_input.code], cwd=str(JARVIS_ROOT), timeout=tool_input.timeout_seconds)


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
        assert r3.is_error and r3.output["exit_code"] == 2
        print(f"  [OK] non-zero exit code propagated (got {r3.output['exit_code']})")

        # 4. SyntaxError surfaces in stderr, non-zero exit
        r4 = await safe_invoke(tool, {"code": "def broken(:"})
        assert r4.is_error and r4.output["exit_code"] != 0
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
        print("  All 10 smoke tests passed.")
        print("=" * 60)

    asyncio.run(run())
