"""
parser.py

JARVIS Agent Layer: Function Call Parser & Dispatcher.

Import with:
    from jarvis_core.agent.parser import parse_tool_call, dispatch

This module provides:
    1. ToolCall — Frozen dataclass representing a parsed (but not yet executed)
       tool invocation extracted from raw LLM output.
    2. parse_tool_call — Extracts a ToolCall from raw LLM text, handling both
       clean JSON and markdown-fenced JSON.
    3. parse_tool_calls — Extracts multiple ToolCalls from a single LLM turn
       (parallel tool calling support).
    4. dispatch — Resolves a ToolCall against the Tool registry, validates input
       via Pydantic, and executes via safe_invoke.
    5. dispatch_batch — Dispatches multiple ToolCalls, using asyncio.gather for
       concurrency-safe tools and serial execution for unsafe ones.

=============================================================================
THE BIG PICTURE
=============================================================================

Without a parser:
    -> The agent loop does ad-hoc string splitting on LLM output to find
       tool names and arguments. Each model (OpenAI, Anthropic, local)
       returns tool calls in slightly different formats. The dispatcher
       breaks every time we switch providers.
    -> No batch support: if the LLM requests 3 tool calls in one turn,
       they run serially even when all 3 are stateless/read-only.

With this parser:
    -> Single entry point (parse_tool_call) normalizes any LLM output
       format into a clean ToolCall dataclass.
    -> dispatch() resolves the ToolCall against the Tool registry, validates
       input via Pydantic, and returns a ToolResult — always, never raises.
    -> dispatch_batch() partitions calls by is_concurrency_safe and runs
       safe tools in parallel via asyncio.gather — free speedup for
       stateless tools like calculator, web search, memory read.
    -> The observation string (ToolResult.to_observation()) is ready for
       injection back into the LLM prompt for the next ReAct step.

=============================================================================
THE FLOW (Step by Step Execution Order)
=============================================================================

STEP 1: LLM emits raw text containing a tool call:
            '{"name": "calculator", "arguments": {"expression": "2+3"}}'
        or embedded in a markdown fence:
            '```json\\n{"name": "calculator", ...}\\n```'
        |
STEP 2: parse_tool_call(raw_text) extracts and parses the JSON:
            -> Strips markdown fences if present
            -> json.loads() the cleaned string
            -> Returns ToolCall(name="calculator", arguments={"expression": "2+3"})
        |
STEP 3: dispatch(tool_call) resolves and executes:
            -> Tool.get_or_raise(tool_call.name) finds the registered class
            -> Instantiates the tool
            -> safe_invoke(tool, tool_call.arguments) validates + runs
            -> Returns ToolResult
        |
STEP 4: The agent injects result.to_observation() into the next prompt:
            "Observation: 5"
        This closes the Schema -> Call -> Parse -> Execute -> Observe loop.

=============================================================================

Handles Stage 3.1.3 (Parsing Tool Outputs) and prepares for:
    - 3.1.4 (Error Handling): ParseError dataclass for malformed calls
    - 3.4 (ReAct): dispatch_batch with concurrency partitioning (STEAL #8)
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple


from jarvis_core.agent.tool import Tool, ToolResult, safe_invoke


# =============================================================================
# Part 1: PARSED TOOL CALL (Immutable representation of what the LLM requested)
# =============================================================================

@dataclass(frozen=True)
class ToolCall:
    """
    LAYER: Agent -- A parsed, unexecuted tool invocation from LLM output.

    Purpose:
        - Clean separation between parsing (extracting the call from text)
          and dispatching (resolving and executing the tool)
        - Immutable: once parsed, cannot be tampered with before dispatch

    Fields:
        name: The tool name string (must match a registered Tool name).
        arguments: The raw argument dict (validated by Pydantic at dispatch time,
                   not at parse time -- keeping parse cheap and dispatch strict).
        call_id: Optional unique identifier for tracking in multi-call turns.
    """
    name: str
    arguments: Dict[str, Any]
    call_id: Optional[str] = None


# =============================================================================
# Part 2: PARSE ERROR (Structured failure for malformed LLM output)
# =============================================================================

@dataclass(frozen=True)
class ParseError:
    """
    LAYER: Agent -- Structured parse failure.

    Purpose:
        - When the LLM emits malformed JSON or missing fields, we need to
          tell the agent loop exactly what went wrong so it can re-prompt.
        - raw_text preserves the original LLM output for debugging.

    Fields:
        message: Human-readable error description.
        raw_text: The original LLM output that failed to parse.
    """
    message: str
    raw_text: str

    def to_observation(self) -> str:
        """Format for injection into the LLM's next prompt."""
        return f"[PARSE ERROR] {self.message}"


# =============================================================================
# Part 3: JSON EXTRACTION (Handles raw JSON and markdown-fenced JSON)
# =============================================================================

# Matches ```json ... ``` or ``` ... ``` blocks
_FENCE_PATTERN = re.compile(
    r"```(?:json)?\s*\n?(.*?)\n?\s*```",
    re.DOTALL,
)

# Matches the outermost { ... } in a string
_BRACE_PATTERN = re.compile(
    r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}",
    re.DOTALL,
)


def _extract_json_str(raw: str) -> Optional[str]:
    """
    Extract a JSON string from raw LLM output.

    EXECUTION FLOW:
    1. Try markdown fence extraction first (most structured models).
    2. Fall back to finding the outermost { ... } brace pair.
    3. Return None if no JSON-like content found.

    Args:
        raw: Raw LLM output text.

    Returns:
        Cleaned JSON string, or None if extraction failed.
    """
    stripped = raw.strip()

    # Fast path: the entire string is already clean JSON
    if stripped.startswith("{"):
        return stripped

    # Try markdown fence: ```json\n{...}\n```
    fence_match = _FENCE_PATTERN.search(stripped)
    if fence_match:
        return fence_match.group(1).strip()

    # Last resort: find first { ... } block anywhere in the text
    brace_match = _BRACE_PATTERN.search(stripped)
    if brace_match:
        return brace_match.group(0)

    return None


# =============================================================================
# Part 4: SINGLE TOOL CALL PARSER
# =============================================================================

# Field name normalization: models use inconsistent key names
_ARG_FIELD_ALIASES = {"arguments", "args", "input", "parameters", "params"}


def parse_tool_call(raw_text: str) -> ToolCall | ParseError:
    """
    Parse a single tool call from raw LLM output.

    EXECUTION FLOW:
    1. Extract JSON string from raw text (handles fences, bare JSON).
    2. json.loads() the extracted string.
    3. Validate required field: "name" (string).
    4. Normalize argument field (handles "arguments", "args", "input", etc.).
    5. Return ToolCall on success, ParseError on any failure.

    Args:
        raw_text: Raw LLM output text containing a tool call.

    Returns:
        ToolCall on success, ParseError on failure.
    """
    json_str = _extract_json_str(raw_text)
    if json_str is None:
        return ParseError(
            message="No JSON object found in LLM output.",
            raw_text=raw_text,
        )

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        return ParseError(
            message=f"Invalid JSON: {e}",
            raw_text=raw_text,
        )

    if not isinstance(data, dict):
        return ParseError(
            message=f"Expected JSON object, got {type(data).__name__}.",
            raw_text=raw_text,
        )

    # Extract tool name
    name = data.get("name") or data.get("function")
    if not name or not isinstance(name, str):
        return ParseError(
            message="Missing or invalid 'name' field in tool call.",
            raw_text=raw_text,
        )

    # Extract arguments with alias normalization
    arguments: Dict[str, Any] = {}
    for alias in _ARG_FIELD_ALIASES:
        if alias in data:
            arguments = data[alias]
            break

    if not isinstance(arguments, dict):
        return ParseError(
            message=f"'arguments' must be a dict, got {type(arguments).__name__}.",
            raw_text=raw_text,
        )

    call_id = data.get("call_id") or data.get("id")

    return ToolCall(
        name=name.strip(),
        arguments=arguments,
        call_id=str(call_id) if call_id else None,
    )


# =============================================================================
# Part 5: MULTI-CALL PARSER (for parallel tool calling)
# =============================================================================

def parse_tool_calls(raw_text: str) -> List[ToolCall | ParseError]:
    """
    Parse one or more tool calls from raw LLM output.

    EXECUTION FLOW:
    1. Try to extract a JSON array of tool calls first.
    2. If that fails, fall back to single tool call parsing.

    This handles two LLM output formats:
        A) Single call: {"name": "...", "arguments": {...}}
        B) Multi call:  [{"name": "...", ...}, {"name": "...", ...}]

    Args:
        raw_text: Raw LLM output text.

    Returns:
        List of ToolCall or ParseError instances, one per detected call.
    """
    stripped = raw_text.strip()

    # Check for JSON array (multi-call)
    # Strip markdown fences first
    content = stripped
    fence_match = _FENCE_PATTERN.search(stripped)
    if fence_match:
        content = fence_match.group(1).strip()

    if content.startswith("["):
        try:
            items = json.loads(content)
            if isinstance(items, list):
                results: List[ToolCall | ParseError] = []
                for item in items:
                    # Re-serialize each item and parse individually
                    results.append(parse_tool_call(json.dumps(item)))
                return results
        except json.JSONDecodeError:
            pass  # Fall through to single-call parsing

    # Single call
    result = parse_tool_call(raw_text)
    return [result]


# =============================================================================
# Part 6: DISPATCHER (Resolves ToolCall against registry and executes)
# =============================================================================

async def dispatch(tool_call: ToolCall) -> ToolResult:
    """
    Resolve a parsed ToolCall against the Tool registry and execute it.

    EXECUTION FLOW:
    1. Look up tool_call.name in Tool._registry via get_or_raise().
    2. Instantiate the tool class.
    3. Delegate to safe_invoke() which handles Pydantic validation + execution.
    4. Attach timing metadata to the result.

    Args:
        tool_call: A parsed ToolCall (from parse_tool_call).

    Returns:
        ToolResult -- always. Never raises. Errors are wrapped in ToolResult.
    """
    start = time.perf_counter()

    try:
        tool_cls = Tool.get_or_raise(tool_call.name)
    except KeyError as e:
        return ToolResult(
            error=f"Unknown tool '{tool_call.name}': {e}",
            metadata={"tool_name": tool_call.name, "elapsed_ms": 0.0},
        )

    tool_instance = tool_cls()
    result = await safe_invoke(tool_instance, tool_call.arguments)

    elapsed_ms = (time.perf_counter() - start) * 1000

    # Attach dispatch metadata without mutating the frozen result
    meta = dict(result.metadata or {})
    meta["tool_name"] = tool_call.name
    meta["call_id"] = tool_call.call_id
    meta["elapsed_ms"] = round(elapsed_ms, 2)

    return ToolResult(
        output=result.output,
        error=result.error,
        metadata=meta,
    )


# =============================================================================
# Part 7: BATCH DISPATCHER (Concurrency partitioning for STEAL #8)
# =============================================================================

async def dispatch_batch(
    tool_calls: Sequence[ToolCall],
) -> List[ToolResult]:
    """
    Dispatch multiple tool calls with concurrency partitioning.

    EXECUTION FLOW:
    1. Partition calls into concurrency-safe and unsafe buckets.
    2. Run all safe calls in parallel via asyncio.gather().
    3. Run unsafe calls serially to protect shared state.
    4. Return results in the SAME ORDER as the input calls.

    Args:
        tool_calls: Sequence of parsed ToolCalls.

    Returns:
        List of ToolResults, one per input call, order-preserving.
    """
    if not tool_calls:
        return []

    # Partition into (index, call, is_safe) triples
    indexed: List[Tuple[int, ToolCall, bool]] = []
    for i, tc in enumerate(tool_calls):
        try:
            tool_cls = Tool.get_or_raise(tc.name)
            is_safe = tool_cls().is_concurrency_safe
        except KeyError:
            is_safe = False  # Unknown tools run serially (will error in dispatch)
        indexed.append((i, tc, is_safe))

    safe_items = [(i, tc) for i, tc, s in indexed if s]
    unsafe_items = [(i, tc) for i, tc, s in indexed if not s]

    # Pre-allocate result slots
    results: List[Optional[ToolResult]] = [None] * len(tool_calls)

    # Safe tools: parallel via asyncio.gather
    if safe_items:
        safe_coros = [dispatch(tc) for _, tc in safe_items]
        safe_results = await asyncio.gather(*safe_coros)
        for (idx, _), result in zip(safe_items, safe_results):
            results[idx] = result

    # Unsafe tools: serial execution
    for idx, tc in unsafe_items:
        results[idx] = await dispatch(tc)

    # Type narrowing: all slots filled
    return [r for r in results if r is not None]


# =============================================================================
# MAIN ENTRY POINT (Smoke test: parse and dispatch tool calls)
# =============================================================================

if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

    # Re-import after path fix (for standalone execution)
    from jarvis_core.agent.tool import Tool, ToolInput, ToolResult, safe_invoke
    from jarvis_core.agent.parser import (
        ToolCall, ParseError, parse_tool_call, parse_tool_calls,
        dispatch, dispatch_batch,
    )

    # -- Register test tools (same as tool.py smoke test) ------------------

    class CalculatorInput(ToolInput):
        expression: str

    @Tool.register("calculator")
    class CalculatorTool(Tool):
        name = "calculator"
        description = "Evaluate a math expression."
        input_schema = CalculatorInput

        @property
        def is_concurrency_safe(self) -> bool:
            return True

        async def invoke(self, tool_input: CalculatorInput) -> ToolResult:
            try:
                result = eval(tool_input.expression, {"__builtins__": {}})
                return ToolResult(output=result)
            except Exception as e:
                return ToolResult(error=f"Eval failed: {e}")

    class EchoInput(ToolInput):
        message: str
        uppercase: bool = False

    @Tool.register("echo")
    class EchoTool(Tool):
        name = "echo"
        description = "Echo a message back."
        input_schema = EchoInput

        async def invoke(self, tool_input: EchoInput) -> ToolResult:
            msg = tool_input.message
            if tool_input.uppercase:
                msg = msg.upper()
            return ToolResult(output=msg)

    # -- Smoke tests -------------------------------------------------------

    async def smoke_test() -> None:
        print("=" * 60)
        print("  Parser & Dispatcher -- Smoke Test")
        print("=" * 60)

        # --- Test 1: Clean JSON parsing ---
        raw_clean = '{"name": "calculator", "arguments": {"expression": "7 * 6"}}'
        result1 = parse_tool_call(raw_clean)
        assert isinstance(result1, ToolCall)
        assert result1.name == "calculator"
        assert result1.arguments == {"expression": "7 * 6"}
        print(f"\n  [1] Clean JSON parse: {result1.name}({result1.arguments})")

        # --- Test 2: Markdown-fenced JSON ---
        raw_fenced = '```json\n{"name": "echo", "arguments": {"message": "hello"}}\n```'
        result2 = parse_tool_call(raw_fenced)
        assert isinstance(result2, ToolCall)
        assert result2.name == "echo"
        print(f"  [2] Fenced JSON parse: {result2.name}({result2.arguments})")

        # --- Test 3: JSON with surrounding text ---
        raw_mixed = 'I will use the calculator tool.\n{"name": "calculator", "arguments": {"expression": "2 + 3"}}\nLet me compute that.'
        result3 = parse_tool_call(raw_mixed)
        assert isinstance(result3, ToolCall)
        assert result3.name == "calculator"
        print(f"  [3] Mixed text parse: {result3.name}({result3.arguments})")

        # --- Test 4: Alias normalization ("input" instead of "arguments") ---
        raw_alias = '{"name": "echo", "input": {"message": "alias test"}}'
        result4 = parse_tool_call(raw_alias)
        assert isinstance(result4, ToolCall)
        assert result4.arguments == {"message": "alias test"}
        print(f"  [4] Alias 'input' parse: {result4.arguments}")

        # --- Test 5: ParseError on garbage ---
        raw_garbage = "I don't need any tools for this."
        result5 = parse_tool_call(raw_garbage)
        assert isinstance(result5, ParseError)
        print(f"  [5] Garbage input: {result5.message}")

        # --- Test 6: ParseError on malformed JSON ---
        raw_malformed = '{"name": "calculator", "arguments": {broken}'
        result6 = parse_tool_call(raw_malformed)
        assert isinstance(result6, ParseError)
        print(f"  [6] Malformed JSON: {result6.message}")

        # --- Test 7: ParseError on missing name ---
        raw_no_name = '{"arguments": {"expression": "2+2"}}'
        result7 = parse_tool_call(raw_no_name)
        assert isinstance(result7, ParseError)
        print(f"  [7] Missing name: {result7.message}")

        # --- Test 8: Dispatch a parsed call ---
        tc = parse_tool_call(raw_clean)
        assert isinstance(tc, ToolCall)
        dr = await dispatch(tc)
        assert dr.is_success
        assert dr.output == 42
        print(f"\n  [8] Dispatch calculator('7 * 6') => {dr.output}")
        print(f"       Metadata: {dr.metadata}")

        # --- Test 9: Dispatch unknown tool ---
        tc_unknown = ToolCall(name="nonexistent", arguments={})
        dr_unknown = await dispatch(tc_unknown)
        assert dr_unknown.is_error
        print(f"  [9] Dispatch unknown tool: {dr_unknown.error}")

        # --- Test 10: Multi-call parsing ---
        raw_multi = '[{"name": "calculator", "arguments": {"expression": "1+1"}}, {"name": "echo", "arguments": {"message": "batch"}}]'
        multi = parse_tool_calls(raw_multi)
        assert len(multi) == 2
        assert all(isinstance(m, ToolCall) for m in multi)
        print(f"\n  [10] Multi-call parse: {[m.name for m in multi]}")

        # --- Test 11: Batch dispatch with concurrency partitioning ---
        batch_calls = [
            ToolCall(name="calculator", arguments={"expression": "10 * 10"}),
            ToolCall(name="calculator", arguments={"expression": "3 + 4"}),
            ToolCall(name="echo", arguments={"message": "serial", "uppercase": True}),
        ]
        batch_results = await dispatch_batch(batch_calls)
        assert len(batch_results) == 3
        assert batch_results[0].output == 100
        assert batch_results[1].output == 7
        assert batch_results[2].output == "SERIAL"
        print(f"  [11] Batch dispatch results: {[r.output for r in batch_results]}")
        print(f"       Timings: {[r.metadata['elapsed_ms'] for r in batch_results]}ms")

        # --- Test 12: Observation formatting round-trip ---
        obs_success = batch_results[0].to_observation()
        obs_error = dr_unknown.to_observation()
        print(f"\n  [12] Observation (success): '{obs_success}'")
        print(f"       Observation (error):   '{obs_error}'")

        print("\n" + "=" * 60)
        print("  All smoke tests passed.")
        print("=" * 60)

    asyncio.run(smoke_test())
