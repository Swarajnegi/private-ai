"""
tool.py

JARVIS Agent Layer: Tool Abstract Base Class.

Import with:
    from jarvis_core.agent.tool import Tool

This module provides:
    1. ToolInput — Pydantic base model for type-safe tool input schemas
    2. ToolResult — Frozen dataclass for tool invocation results
    3. Tool — Abstract base class that all JARVIS tools implement

=============================================================================
THE BIG PICTURE
=============================================================================

Without a Tool ABC:
    -> Every tool is a loose function with ad-hoc argument parsing.
       The agent emits {"name": "calculator", "args": {"expr": "2+2"}}
       and the dispatcher does a hand-rolled if/elif chain to find it.
    -> No schema discovery: the LLM doesn't know what arguments each tool
       accepts. It guesses — and guesses wrong 30% of the time.
    -> No safety contract: the dispatcher can't tell which tools are safe
       to run in parallel vs. which mutate shared state.

With a Tool ABC:
    -> Every tool is a class with:
       - name: str — unique identifier for the dispatcher
       - description: str — natural language for the LLM system prompt
       - input_schema: Type[ToolInput] — Pydantic model the LLM must fill
       - invoke(input) -> ToolResult — async execution with typed I/O
    -> The agent generates JSON matching input_schema. The Tool validates
       it via Pydantic before execution — malformed calls fail loud.
    -> is_concurrency_safe property tells the dispatcher (3.4, STEAL #8)
       whether this tool can run in parallel with other tools.
    -> Registration uses RegistryBase: @Tool.register("calculator")

=============================================================================
THE FLOW (Step by Step Execution Order)
=============================================================================

STEP 1: Developer defines a tool by subclassing Tool and decorating it:
            @Tool.register("calculator")
            class CalculatorTool(Tool): ...
        ↓
STEP 2: Agent planning phase discovers available tools:
            tools = Tool.list_registered()
            schemas = [Tool.get(name).schema_for_llm() for name in tools]
        The schema dict is injected into the LLM system prompt.
        ↓
STEP 3: LLM emits a tool call:
            {"name": "calculator", "input": {"expression": "2+2"}}
        ↓
STEP 4: Dispatcher resolves and validates:
            tool_cls = Tool.get_or_raise("calculator")
            tool = tool_cls()
            validated_input = tool.input_schema.model_validate(raw_input)
        Pydantic rejects malformed input before any code runs.
        ↓
STEP 5: Dispatcher checks concurrency safety:
            if tool.is_concurrency_safe:
                # batch with other safe tools via asyncio.gather
            else:
                # run serially to protect shared state
        ↓
STEP 6: Dispatcher invokes:
            result = await tool.invoke(validated_input)
        Returns ToolResult(output=..., error=None) on success,
        or ToolResult(output=None, error="...") on failure.

=============================================================================

Prep for STEAL #8 (Stage 3.4): is_concurrency_safe property is included
now so the tool-dispatch partitioning logic in ReAct lands without retrofit.
"""

from __future__ import annotations

import asyncio
from abc import abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar, Dict, List, Optional, Type

from pydantic import BaseModel, ConfigDict

from jarvis_core.agent.registry import RegistryBase


# =============================================================================
# Part 1: TOOL INPUT BASE (Pydantic schema for validated arguments)
# =============================================================================

class ToolInput(BaseModel):
    """
    LAYER: Agent -- Base class for all tool input schemas.

    Purpose:
        - Every tool defines a subclass of ToolInput with typed fields
        - The agent's JSON output is validated against this schema
        - Malformed calls fail at validation, not at execution

    How it works:
        - Pydantic model_validate(dict) parses and validates the raw JSON
        - model_json_schema() produces the JSON Schema dict that gets
          injected into the LLM system prompt for schema-aware generation
    """
    model_config = ConfigDict(extra="forbid")  # Reject unexpected fields


# =============================================================================
# Part 2: TOOL RESULT (Immutable output container)
# =============================================================================

@dataclass(frozen=True)
class ToolResult:
    """
    LAYER: Agent — Immutable result of a tool invocation.

    Purpose:
        - Uniform contract for what invoke() returns
        - Separates success (output set, error None) from failure
        - Frozen: once created, cannot be mutated by downstream code

    Fields:
        output: The tool's return value on success (any serializable type).
                None on failure.
        error:  Error message string on failure. None on success.
        metadata: Optional dict for timing, token counts, or debug info.
    """
    output: Any = None
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    @property
    def is_success(self) -> bool:
        """True if the tool completed without error."""
        return self.error is None

    @property
    def is_error(self) -> bool:
        """True if the tool failed."""
        return self.error is not None

    def to_observation(self) -> str:
        """
        Format as a string for injection into the ReAct observation slot.

        Returns:
            Human-readable representation of the result for the LLM.
        """
        if self.is_success:
            return str(self.output)
        return f"[TOOL ERROR] {self.error}"


# =============================================================================
# Part 3: TOOL ABSTRACT BASE CLASS
# =============================================================================

class Tool(RegistryBase["Tool"]):
    """
    LAYER: Agent — Abstract base class for all JARVIS tools.

    Purpose:
        - Define the contract every tool must implement
        - Provide automatic registration via @Tool.register(name)
        - Expose schema_for_llm() for LLM system prompt injection
        - Expose is_concurrency_safe for STEAL #8 dispatch partitioning

    How it works:
        - Subclass this, set name/description/input_schema, implement invoke()
        - The decorator @Tool.register("name") stores the class in the
          Tool._registry dict (inherited from RegistryBase)
        - schema_for_llm() returns the dict format that OpenAI/Anthropic/
          local models expect for tool definitions
    """

    # Subclasses MUST override these three class attributes
    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    input_schema: ClassVar[Type[ToolInput]] = ToolInput

    # STEAL #9 hook (Stage 3.4 permission engine). Tools that mutate state,
    # touch the network, or execute arbitrary code MUST set this True so the
    # permission engine gates them before invocation. Default False = safe.
    requires_permission: ClassVar[bool] = False

    @abstractmethod
    async def invoke(self, tool_input: ToolInput) -> ToolResult:
        """
        Execute the tool with validated input.

        Args:
            tool_input: A validated instance of this tool's input_schema.

        Returns:
            ToolResult with output on success or error message on failure.
        """
        ...

    @property
    def is_concurrency_safe(self) -> bool:
        """
        Whether this tool can safely run in parallel with other tools.

        Override and return True for read-only, stateless tools
        (e.g., calculator, web search, memory read).

        Default is False (conservative): the dispatcher will run this
        tool serially to protect shared state.

        Used by STEAL #8 (Stage 3.4) dispatch partitioning:
            safe_tools = [t for t in batch if t.is_concurrency_safe]
            # -> asyncio.gather(*safe_tools)
            unsafe_tools = [t for t in batch if not t.is_concurrency_safe]
            # -> sequential execution
        """
        return False

    @classmethod
    def schema_for_llm(cls) -> Dict[str, Any]:
        """
        Generate the tool definition dict for LLM system prompts.

        This matches the function-calling schema format used by
        OpenAI, Anthropic, and most local model APIs.

        Returns:
            Dict with: name, description, input_schema (JSON Schema).
        """
        return {
            "name": cls.name,
            "description": cls.description,
            "input_schema": cls.input_schema.model_json_schema(),
        }

    @classmethod
    def all_schemas(cls) -> List[Dict[str, Any]]:
        """
        Generate schemas for ALL registered tools.

        Returns:
            List of schema dicts, one per registered tool, sorted by name.
        """
        schemas = []
        for tool_name in cls.list_registered():
            tool_cls = cls.get_or_raise(tool_name)
            schemas.append(tool_cls.schema_for_llm())
        return schemas


# =============================================================================
# Part 4: SAFE INVOKE WRAPPER (catches exceptions, returns ToolResult)
# =============================================================================

async def safe_invoke(tool: Tool, raw_input: Dict[str, Any]) -> ToolResult:
    """
    Validate input and invoke a tool, catching all exceptions.

    This is the dispatcher-facing entry point. It:
    1. Validates raw_input against the tool's Pydantic schema
    2. Calls tool.invoke() with the validated input
    3. Catches any exception and wraps it in a ToolResult

    Args:
        tool:      An instantiated Tool subclass.
        raw_input: Raw dict from the LLM's tool call output.

    Returns:
        ToolResult — always. Never raises.
    """
    try:
        validated = tool.input_schema.model_validate(raw_input)
    except Exception as e:
        return ToolResult(
            error=f"Input validation failed for '{tool.name}': {e}"
        )

    try:
        return await tool.invoke(validated)
    except Exception as e:
        return ToolResult(
            error=f"Tool '{tool.name}' raised: {type(e).__name__}: {e}"
        )


# =============================================================================
# MAIN ENTRY POINT (Smoke test: define and invoke a calculator tool)
# =============================================================================

if __name__ == "__main__":

    # -- Define a concrete tool: Calculator --------------------------------

    class CalculatorInput(ToolInput):
        """Input schema for the calculator tool."""
        expression: str

    @Tool.register("calculator")
    class CalculatorTool(Tool):
        """Evaluate a mathematical expression."""
        name = "calculator"
        description = "Evaluate a Python math expression and return the result."
        input_schema = CalculatorInput

        @property
        def is_concurrency_safe(self) -> bool:
            return True  # Stateless, read-only — safe to parallelize

        async def invoke(self, tool_input: CalculatorInput) -> ToolResult:
            try:
                # eval() is intentionally restricted in scope here.
                # In production (3.2), this will use a sandboxed evaluator.
                result = eval(tool_input.expression, {"__builtins__": {}})
                return ToolResult(output=result)
            except Exception as e:
                return ToolResult(error=f"Eval failed: {e}")

    # -- Define a second tool: Echo (not concurrency-safe) -----------------

    class EchoInput(ToolInput):
        """Input schema for the echo tool."""
        message: str
        uppercase: bool = False

    @Tool.register("echo")
    class EchoTool(Tool):
        """Echo a message back, optionally uppercased."""
        name = "echo"
        description = "Echo the input message back. Optionally uppercase it."
        input_schema = EchoInput

        async def invoke(self, tool_input: EchoInput) -> ToolResult:
            msg = tool_input.message
            if tool_input.uppercase:
                msg = msg.upper()
            return ToolResult(output=msg)

    # -- Run smoke tests ---------------------------------------------------

    async def smoke_test() -> None:
        print("=" * 60)
        print("  Tool ABC -- Smoke Test")
        print("=" * 60)

        # -- Registry discovery --------------------------------------------

        registered = Tool.list_registered()
        print(f"\n  Registered tools: {registered}")
        assert "calculator" in registered
        assert "echo" in registered

        # -- Schema generation for LLM prompt ------------------------------

        schemas = Tool.all_schemas()
        print(f"  Schemas generated: {len(schemas)}")
        for s in schemas:
            print(f"    {s['name']}: {s['description'][:50]}...")

        # -- Invoke calculator (success) -----------------------------------

        calc = CalculatorTool()
        result = await safe_invoke(calc, {"expression": "2 + 3 * 4"})
        print(f"\n  calculator('2 + 3 * 4') => {result.output} (success={result.is_success})")
        assert result.output == 14

        # -- Invoke calculator (error) -------------------------------------

        result_err = await safe_invoke(calc, {"expression": "import os"})
        print(f"  calculator('import os') => {result_err.error}")
        assert result_err.is_error

        # -- Invoke with bad input (validation failure) --------------------

        result_bad = await safe_invoke(calc, {"wrong_field": "oops"})
        print(f"  calculator(wrong_field) => {result_bad.error}")
        assert result_bad.is_error
        assert "validation" in result_bad.error.lower()

        # -- Invoke echo ---------------------------------------------------

        echo = EchoTool()
        result_echo = await safe_invoke(echo, {"message": "hello jarvis", "uppercase": True})
        print(f"  echo('hello jarvis', uppercase=True) => '{result_echo.output}'")
        assert result_echo.output == "HELLO JARVIS"

        # -- Concurrency safety check --------------------------------------

        print(f"\n  CalculatorTool.is_concurrency_safe = {calc.is_concurrency_safe}")
        print(f"  EchoTool.is_concurrency_safe       = {echo.is_concurrency_safe}")
        assert calc.is_concurrency_safe is True
        assert echo.is_concurrency_safe is False

        # -- Permission flag (STEAL #9 hook prep) --------------------------

        print(f"  CalculatorTool.requires_permission = {CalculatorTool.requires_permission}")
        print(f"  EchoTool.requires_permission       = {EchoTool.requires_permission}")
        assert CalculatorTool.requires_permission is False
        assert EchoTool.requires_permission is False

        # Subclass that opts in
        class UnsafeShellInput(ToolInput):
            command: str

        @Tool.register("_smoketest_shell")
        class UnsafeShellTool(Tool):
            name = "_smoketest_shell"
            description = "Smoke-test tool: opts into requires_permission."
            input_schema = UnsafeShellInput
            requires_permission = True
            async def invoke(self, tool_input: UnsafeShellInput) -> ToolResult:
                return ToolResult(output="never reached in smoke test")

        assert UnsafeShellTool.requires_permission is True
        print(f"  UnsafeShellTool.requires_permission = {UnsafeShellTool.requires_permission}")

        # -- Observation formatting ----------------------------------------

        print(f"\n  Success observation: '{result.to_observation()}'")
        print(f"  Error observation:   '{result_err.to_observation()}'")

        print("\n" + "=" * 60)
        print("  All smoke tests passed.")
        print("=" * 60)

    asyncio.run(smoke_test())
