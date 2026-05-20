"""
calc.py

JARVIS Agent Layer: Calculator tool (Category A — Callable).

Import-time registration:
    @Tool.register("calculator") fires when the `tools` package is imported.

LAYER: Agent (Tools)

=============================================================================
THE BIG PICTURE
=============================================================================

The calculator is the simplest concurrency-safe callable Tool. It exists for
three reasons:
    1. Reference implementation — every other callable Tool follows this shape.
    2. Smoke-test target — registry / dispatcher / safe_invoke all exercise it.
    3. Real utility — agent often needs arithmetic without writing Python.

Restricted eval: __builtins__ stripped, no imports, no attribute access via
expression strings. NOT a sandbox in any cryptographic sense — sufficient for
LLM-generated math expressions, INSUFFICIENT for untrusted user input.
For true sandboxing, code_exec (Stage 3.2 Phase B, requires_permission=True)
is the correct tool.
"""

from __future__ import annotations

from jarvis_core.agent.tool import Tool, ToolInput, ToolResult


class CalculatorInput(ToolInput):
    """Input schema for the calculator tool."""
    expression: str


@Tool.register("calculator")
class CalculatorTool(Tool):
    """Evaluate a Python math expression and return the numeric result."""

    name = "calculator"
    description = (
        "Evaluate a Python math expression (numbers, +, -, *, /, **, %, "
        "parentheses) and return the numeric result. No imports, no variables, "
        "no attribute access."
    )
    input_schema = CalculatorInput

    @property
    def is_concurrency_safe(self) -> bool:
        return True

    async def invoke(self, tool_input: CalculatorInput) -> ToolResult:
        try:
            # __builtins__ stripped to None; restricts to literal arithmetic.
            result = eval(tool_input.expression, {"__builtins__": {}})
        except Exception as e:
            return ToolResult(error=f"Eval failed: {type(e).__name__}: {e}")
        return ToolResult(output=result)


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS
# =============================================================================

if __name__ == "__main__":
    import asyncio
    from jarvis_core.agent.tool import safe_invoke

    async def smoke_test() -> None:
        print("=" * 60)
        print("  CalculatorTool — Smoke Test")
        print("=" * 60)

        tool = CalculatorTool()

        # 1. Success
        r1 = await safe_invoke(tool, {"expression": "2 + 3 * 4"})
        assert r1.is_success and r1.output == 14, f"got {r1}"
        print(f"  [OK] '2 + 3 * 4' => {r1.output}")

        # 2. Power and modulo
        r2 = await safe_invoke(tool, {"expression": "(2**10) % 7"})
        assert r2.is_success and r2.output == 2, f"got {r2}"
        print(f"  [OK] '(2**10) % 7' => {r2.output}")

        # 3. Restricted eval rejects import
        r3 = await safe_invoke(tool, {"expression": "__import__('os').system('echo bad')"})
        assert r3.is_error, f"expected error, got {r3}"
        print(f"  [OK] import attempt rejected: {r3.error[:60]}")

        # 4. Bad input shape (Pydantic validation)
        r4 = await safe_invoke(tool, {"wrong_field": "oops"})
        assert r4.is_error and "validation" in r4.error.lower(), f"got {r4}"
        print(f"  [OK] missing field rejected by Pydantic")

        # 5. Concurrency-safe flag
        assert tool.is_concurrency_safe is True
        print(f"  [OK] is_concurrency_safe = True")

        # 6. Permission flag (read-only math)
        assert CalculatorTool.requires_permission is False
        print(f"  [OK] requires_permission = False")

        # 7. Registry lookup
        assert Tool.get_or_raise("calculator") is CalculatorTool
        print(f"  [OK] registered as 'calculator'")

        # 8. Schema for LLM
        schema = CalculatorTool.schema_for_llm()
        assert schema["name"] == "calculator"
        assert "expression" in schema["input_schema"]["properties"]
        print(f"  [OK] schema_for_llm() produces valid tool schema")

        print("=" * 60)
        print("  All 8 smoke tests passed.")
        print("=" * 60)

    asyncio.run(smoke_test())
