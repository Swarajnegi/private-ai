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

Prep for STEAL #5 (Stage 3.4 trace/EventBus): four lifecycle hooks land here
in Stage 3.2.3 so the EventBus.publish() calls can be added later by touching
only the hook bodies, not tool.py again.
    setup()           -- called once before first invoke (warm caches, indices)
    teardown()        -- called once at shutdown (close handles, kill subprocesses)
    on_invoke_start() -- fires before each invoke (per-call tracing/metrics start)
    on_invoke_end()   -- fires after each invoke (per-call tracing/metrics end)
All four are no-op defaults. safe_invoke() wraps invoke() with the start/end
hooks; hook failures are swallowed so a misbehaving hook never breaks invocation.
"""

from __future__ import annotations

import asyncio
from abc import abstractmethod
from dataclasses import dataclass, replace
from typing import Any, ClassVar, Dict, List, Optional, Type

from pydantic import BaseModel, ConfigDict, Field

from jarvis_core.agent.coercion import coerce_arguments
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

    # ---- Lifecycle hooks (Stage 3.2.3) -----------------------------------
    # All four default to no-op. Override only where there's real value
    # (proactive index warm-up, subprocess hygiene, tracing).
    # safe_invoke() wraps invoke() with on_invoke_start + on_invoke_end and
    # swallows hook exceptions so a buggy hook can never break invocation.

    async def setup(self) -> None:
        """Lifecycle hook: called ONCE by the dispatcher before the first
        invoke. Override to proactively warm caches, build indices, or
        open external connections. Default: no-op.

        STEAL #5 hook (Stage 3.4): EventBus.publish('tool.setup', ...) lands
        here when trace.py is wired; tool.py does not need to change again.
        """
        return None

    async def teardown(self) -> None:
        """Lifecycle hook: called ONCE by the dispatcher at shutdown.
        Override to close handles, kill orphaned subprocesses, flush state.
        Default: no-op.

        STEAL #5 hook (Stage 3.4): EventBus.publish('tool.teardown', ...).
        """
        return None

    async def on_invoke_start(self, tool_input: ToolInput) -> None:
        """Lifecycle hook: fires BEFORE every invoke (after input validation).
        Override for per-call tracing, latency-timer start, or metrics emit.
        Default: no-op.

        STEAL #5 hook (Stage 3.4): EventBus.publish('tool.invoke.start', ...).

        Exceptions raised here are swallowed by safe_invoke -- a buggy hook
        must never break the underlying tool call.
        """
        return None

    async def on_invoke_end(self, result: ToolResult) -> None:
        """Lifecycle hook: fires AFTER every invoke (success OR error).
        Override for per-call tracing close, latency-timer end, metrics
        flush, cleanup. Default: no-op.

        STEAL #5 hook (Stage 3.4): EventBus.publish('tool.invoke.end', ...).

        Exceptions raised here are swallowed by safe_invoke.
        """
        return None

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
    2. Fires on_invoke_start hook (failures swallowed)
    3. Calls tool.invoke() with the validated input
    4. Fires on_invoke_end hook (failures swallowed)
    5. Catches any exception and wraps it in a ToolResult

    Args:
        tool:      An instantiated Tool subclass.
        raw_input: Raw dict from the LLM's tool call output.

    Returns:
        ToolResult — always. Never raises.
    """
    # STEAL #13: tolerant coercion BEFORE validation — a weak model emits valid
    # JSON with near-miss field names (file_name vs path); map them onto the
    # canonical schema fields. Conservative: anything ambiguous is left verbatim
    # so validation still fails cleanly and the repair layer shows the schema.
    coerced_input, coercion_notes = coerce_arguments(raw_input, tool.input_schema)
    try:
        validated = tool.input_schema.model_validate(coerced_input)
    except Exception as e:
        return ToolResult(
            error=f"Input validation failed for '{tool.name}': {e}"
        )

    # Lifecycle hook: on_invoke_start. Hook failures must NEVER propagate;
    # they are deliberately swallowed so a buggy hook can't break invocation.
    try:
        await tool.on_invoke_start(validated)
    except Exception:
        pass

    try:
        result = await tool.invoke(validated)
    except Exception as e:
        result = ToolResult(
            error=f"Tool '{tool.name}' raised: {type(e).__name__}: {e}"
        )

    # Lifecycle hook: on_invoke_end (fires for BOTH success and error paths).
    try:
        await tool.on_invoke_end(result)
    except Exception:
        pass

    # Surface any coercion remaps so the observation isn't a silent operation.
    if coercion_notes:
        result = replace(
            result,
            metadata={**(result.metadata or {}), "coercion_notes": coercion_notes},
        )

    return result


# =============================================================================
# MAIN ENTRY POINT (Smoke test: define and invoke a calculator tool)
# =============================================================================

if __name__ == "__main__":

    # -- Define a concrete tool: Calculator --------------------------------

    class CalculatorInput(ToolInput):
        """Input schema for the calculator tool."""
        expression: str = Field(json_schema_extra={"aliases": ["expr", "formula"]})

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

        # -- STEAL #13 coercion: a DECLARED ALIAS ('expr' -> 'expression') is
        #    remapped onto the canonical field, so the call reaches invoke and
        #    surfaces a coercion note. (A semantically-unknown key is NOT guessed
        #    — see the validation case below.)
        result_coerced = await safe_invoke(calc, {"expr": "6 * 7"})
        print(f"  calculator(expr='6 * 7') => {result_coerced.output} "
              f"(coerced; notes={(result_coerced.metadata or {}).get('coercion_notes')})")
        assert result_coerced.is_success and result_coerced.output == 42
        assert (result_coerced.metadata or {}).get("coercion_notes")

        # -- Genuine validation failure coercion CANNOT mask: an extra unknown
        #    field alongside the correct one (required already filled -> no bind).
        result_bad = await safe_invoke(calc, {"expression": "1+1", "bogus": "x"})
        print(f"  calculator(expression + bogus) => {result_bad.error}")
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

        # -- Lifecycle hooks (Stage 3.2.3) ---------------------------------

        # Tracer tool: records firing order of every hook + invoke.
        events: List[str] = []

        class TracerInput(ToolInput):
            value: int

        @Tool.register("_smoketest_tracer")
        class TracerTool(Tool):
            name = "_smoketest_tracer"
            description = "Lifecycle tracer for smoke test."
            input_schema = TracerInput

            async def setup(self) -> None:
                events.append("setup")

            async def teardown(self) -> None:
                events.append("teardown")

            async def on_invoke_start(self, tool_input: TracerInput) -> None:
                events.append(f"start(v={tool_input.value})")

            async def on_invoke_end(self, result: ToolResult) -> None:
                events.append(f"end(ok={result.is_success})")

            async def invoke(self, tool_input: TracerInput) -> ToolResult:
                events.append(f"invoke(v={tool_input.value})")
                return ToolResult(output=tool_input.value * 2)

        tracer = TracerTool()
        # Dispatcher contract: setup() once, N invocations, teardown() once.
        await tracer.setup()
        r_t1 = await safe_invoke(tracer, {"value": 7})
        r_t2 = await safe_invoke(tracer, {"value": 9})
        await tracer.teardown()

        assert r_t1.output == 14
        assert r_t2.output == 18
        expected = [
            "setup",
            "start(v=7)", "invoke(v=7)", "end(ok=True)",
            "start(v=9)", "invoke(v=9)", "end(ok=True)",
            "teardown",
        ]
        assert events == expected, f"hook order mismatch: {events} != {expected}"
        print(f"\n  Lifecycle hook firing order verified: setup -> (start->invoke->end)x2 -> teardown")

        # Hook failures must NEVER break invocation (deliberately swallowed)
        class _BadHookInput(ToolInput):
            x: int

        @Tool.register("_smoketest_bad_hook")
        class BadHookTool(Tool):
            name = "_smoketest_bad_hook"
            description = "Hook that raises -- invocation must still succeed."
            input_schema = _BadHookInput

            async def on_invoke_start(self, tool_input: _BadHookInput) -> None:
                raise RuntimeError("hook is on fire")

            async def on_invoke_end(self, result: ToolResult) -> None:
                raise RuntimeError("also on fire")

            async def invoke(self, tool_input: _BadHookInput) -> ToolResult:
                return ToolResult(output=tool_input.x + 1)

        bad = BadHookTool()
        r_bad = await safe_invoke(bad, {"x": 41})
        assert r_bad.is_success and r_bad.output == 42, f"buggy hook broke invocation: {r_bad}"
        print(f"  Buggy lifecycle hook swallowed -- invoke still succeeded ({r_bad.output})")

        # Default no-op hooks: existing tools (e.g., CalculatorTool above)
        # gain hook calls for free via safe_invoke; no override required.
        # Already covered by the result, result_err checks at top of test.

        print("\n" + "=" * 60)
        print("  All smoke tests passed.")
        print("=" * 60)

    asyncio.run(smoke_test())
