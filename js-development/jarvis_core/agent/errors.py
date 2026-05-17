"""
errors.py

JARVIS Agent Layer: Tool Call Error Classification & Recovery Policy.

Import with:
    from jarvis_core.agent.errors import (
        ToolErrorKind, ClassifiedError, RetryPolicy, RecoveryAction,
        RecoveryDecision, ErrorHandler, classify_error,
    )

This module provides:
    1. ToolErrorKind — Enum of the 5 failure categories a tool call can hit.
    2. ClassifiedError — Frozen dataclass: the parsed failure + repair hint
       for the LLM.
    3. RetryPolicy — Frozen dataclass: which error kinds are retryable and
       how many times.
    4. RecoveryAction — Enum: RETRY_WITH_HINT or ABORT.
    5. RecoveryDecision — Frozen dataclass: the decision produced by
       ErrorHandler.handle(), including the formatted repair prompt.
    6. ErrorHandler — Stateful per-agent-turn handler: tracks retry counts,
       classifies errors, and returns recovery decisions.
    7. classify_error — Stateless top-level function for quick classification
       without retry tracking.

=============================================================================
THE BIG PICTURE
=============================================================================

Without error handling:
    -> parse_tool_call() returns a ParseError. The agent loop doesn't know
       whether to retry or abort, or what to tell the LLM to fix.
    -> dispatch() returns ToolResult(error=...). The agent loop injects the
       raw error string back into the LLM -- which then guesses randomly.
    -> No retry budget: a broken LLM call loops forever or crashes.

With this module:
    -> Every failure from parser.py or tool.py is classified into one of
       5 specific ToolErrorKinds (PARSE_FAILED, UNKNOWN_TOOL, etc.).
    -> Each kind has a targeted repair_hint: a one-sentence instruction
       to the LLM that explains EXACTLY what it did wrong and how to fix it.
    -> RetryPolicy gates which errors are worth retrying (parse errors and
       validation errors can be self-corrected by the LLM; unknown tools
       and execution failures cannot).
    -> ErrorHandler tracks retry counts per call and returns ABORT once the
       budget is exhausted -- preventing infinite loops.

=============================================================================
THE FLOW (Step by Step Execution Order)
=============================================================================

STEP 1: Agent loop calls parse_tool_call(raw_text).
        If ParseError returned:
            handler.handle(parse_error) -> RecoveryDecision
        |
STEP 2: If ToolCall returned, agent calls dispatch(tool_call).
        If ToolResult(error=...) returned:
            handler.handle(tool_result) -> RecoveryDecision
        |
STEP 3: RecoveryDecision.action is checked:
            RETRY_WITH_HINT -> inject repair_prompt as Observation, re-call LLM
            ABORT           -> return terminal error to user, stop the loop
        |
STEP 4: On next LLM call, repair_prompt appears as:
            "Observation: [TOOL ERROR] ..."
        The LLM reads it, self-corrects, emits new tool call JSON.
        |
STEP 5: handler.reset() is called at the start of each new tool call batch
        to clear per-call retry counters.

=============================================================================

Prepares for Stage 3.4 (ReAct loop): ErrorHandler plugs directly into the
Thought -> Act -> Observe cycle. The repair_prompt IS the Observation when
a tool call fails.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, FrozenSet, Optional, Union

from jarvis_core.agent.parser import ParseError, ToolCall
from jarvis_core.agent.tool import Tool, ToolResult


# =============================================================================
# Part 1: ERROR TAXONOMY (5 mutually exclusive failure categories)
# =============================================================================

class ToolErrorKind(str, Enum):
    """
    LAYER: Agent -- The 5 failure categories a tool call can produce.

    PARSE_FAILED:
        The LLM output contained no valid JSON, or the JSON was malformed,
        or it was missing the required 'name' field.
        -> Retryable: the LLM can emit better JSON if told what went wrong.

    UNKNOWN_TOOL:
        The JSON parsed correctly, but the 'name' field does not match any
        registered tool in Tool._registry.
        -> NOT retryable by default: if the tool doesn't exist, retrying
           with a hint (listing available tools) is the fix -- but this
           requires HUMAN or PLANNER intervention, not blind retry.
           Override RetryPolicy.retryable_kinds to change this.

    VALIDATION_FAILED:
        The tool was found, but the 'arguments' dict failed Pydantic
        validation (missing required field, wrong type, extra field).
        -> Retryable: the LLM can re-emit with the correct schema once told
           what field was wrong.

    EXECUTION_FAILED:
        The tool ran but raised an exception inside invoke().
        -> NOT retryable by default: a broken tool is a code bug, not an
           LLM output bug. Retrying will hit the same failure.

    BUDGET_EXCEEDED:
        The retry count for this tool call has exceeded RetryPolicy.max_retries.
        -> Synthetic: set by ErrorHandler, not by parse/dispatch. Always ABORT.
    """
    PARSE_FAILED       = "parse_failed"
    UNKNOWN_TOOL       = "unknown_tool"
    VALIDATION_FAILED  = "validation_failed"
    EXECUTION_FAILED   = "execution_failed"
    BUDGET_EXCEEDED    = "budget_exceeded"


# =============================================================================
# Part 2: CLASSIFIED ERROR (Failure + targeted LLM repair hint)
# =============================================================================

@dataclass(frozen=True)
class ClassifiedError:
    """
    LAYER: Agent -- A classified failure with a targeted LLM repair hint.

    Purpose:
        - Separate the raw error message (from parser/dispatcher) from the
          instruction to the LLM (what to do differently next time).
        - repair_hint is what gets injected as the Observation in the ReAct
          loop -- it must be actionable in one sentence.

    Fields:
        kind:         The failure category (ToolErrorKind).
        raw_message:  Original error string from ParseError or ToolResult.
        tool_name:    The attempted tool name, if extractable.
        repair_hint:  One sentence telling the LLM how to self-correct.
    """
    kind: ToolErrorKind
    raw_message: str
    tool_name: Optional[str]
    repair_hint: str

    def to_observation(self) -> str:
        """Format as LLM-facing Observation for the next ReAct step."""
        return f"[TOOL ERROR: {self.kind.value}] {self.repair_hint}"


# =============================================================================
# Part 3: RETRY POLICY (Which errors to retry and how many times)
# =============================================================================

# Default: only parse and validation errors are worth retrying.
# Unknown tool requires knowing which tools exist (planner decision).
# Execution failure is a code bug, not an LLM bug.
_DEFAULT_RETRYABLE: FrozenSet[ToolErrorKind] = frozenset({
    ToolErrorKind.PARSE_FAILED,
    ToolErrorKind.VALIDATION_FAILED,
})


@dataclass(frozen=True)
class RetryPolicy:
    """
    LAYER: Agent -- Governs retry behaviour for failed tool calls.

    Purpose:
        - Prevent infinite retry loops.
        - Distinguish retryable failures (bad JSON, wrong args) from
          terminal failures (unknown tool, broken implementation).

    Fields:
        max_retries:     Maximum number of retry attempts per tool call.
        retryable_kinds: Set of ToolErrorKind values that trigger retry.
                         All others immediately trigger ABORT.
    """
    max_retries: int = 3
    retryable_kinds: FrozenSet[ToolErrorKind] = _DEFAULT_RETRYABLE


# =============================================================================
# Part 4: RECOVERY ACTION & DECISION
# =============================================================================

class RecoveryAction(str, Enum):
    """
    LAYER: Agent -- What the agent loop should do after a tool call failure.

    RETRY_WITH_HINT:
        Inject repair_prompt as the next Observation and re-call the LLM.
        The LLM reads the hint and self-corrects.

    ABORT:
        Stop retrying. Return the error to the caller (user or planner).
        Used when: budget exhausted, non-retryable error, or unknown tool.
    """
    RETRY_WITH_HINT = "retry_with_hint"
    ABORT           = "abort"


@dataclass(frozen=True)
class RecoveryDecision:
    """
    LAYER: Agent -- The decision produced by ErrorHandler.handle().

    Purpose:
        - Single object the agent loop inspects to decide what to do next.
        - Carries both the action and all context needed to execute it.

    Fields:
        action:           RETRY_WITH_HINT or ABORT.
        classified_error: The classified failure that triggered this decision.
        attempt:          Which attempt this is (1-indexed).
        max_attempts:     Maximum attempts allowed by RetryPolicy.
        repair_prompt:    Observation string to inject on RETRY_WITH_HINT.
                          None on ABORT (no retry will happen).
    """
    action: RecoveryAction
    classified_error: ClassifiedError
    attempt: int
    max_attempts: int
    repair_prompt: Optional[str]

    @property
    def should_retry(self) -> bool:
        """True if the agent loop should retry the LLM call."""
        return self.action == RecoveryAction.RETRY_WITH_HINT

    def summary(self) -> str:
        """One-line summary for logging."""
        return (
            f"[Recovery] attempt={self.attempt}/{self.max_attempts} "
            f"action={self.action.value} "
            f"kind={self.classified_error.kind.value}"
        )


# =============================================================================
# Part 5: ERROR CLASSIFIER (Stateless mapping from raw failure to ClassifiedError)
# =============================================================================

def _build_repair_hint_for_parse(error: ParseError) -> str:
    """Craft a targeted hint based on the parse failure message."""
    msg = error.message.lower()
    if "no json" in msg or "not found" in msg:
        return (
            "Your response did not contain a JSON object. "
            "Output ONLY a JSON object with 'name' (string) and "
            "'arguments' (object) fields. No surrounding text."
        )
    if "invalid json" in msg or "decode" in msg:
        return (
            "Your JSON was malformed (syntax error). Ensure all strings "
            "use double quotes, no trailing commas, and properly nested braces."
        )
    if "missing" in msg or "invalid 'name'" in msg:
        return (
            "Your JSON object is missing the required 'name' field. "
            "Include 'name' as a string matching one of the available tool names."
        )
    # Generic fallback
    return (
        "Your tool call could not be parsed. Output ONLY a JSON object: "
        '{"name": "<tool_name>", "arguments": {<key>: <value>}}'
    )


def _build_repair_hint_for_unknown_tool(tool_name: str) -> str:
    """List available tools so the LLM can pick the correct name."""
    available = Tool.list_registered()
    if available:
        available_str = ", ".join(f'"{t}"' for t in sorted(available))
        return (
            f"Tool '{tool_name}' does not exist. "
            f"Available tools: {available_str}. "
            "Use one of these names exactly in the 'name' field."
        )
    return f"Tool '{tool_name}' does not exist and no tools are currently registered."


def _build_repair_hint_for_validation(tool_name: str, raw_message: str) -> str:
    """Include the schema in the hint so the LLM knows what args are required."""
    tool_cls = Tool.get(tool_name)
    if tool_cls is not None:
        try:
            schema = tool_cls.input_schema.model_json_schema()
            required = schema.get("required", [])
            props = list(schema.get("properties", {}).keys())
            return (
                f"Tool '{tool_name}' received invalid arguments. "
                f"Required fields: {required}. All fields: {props}. "
                f"Validation error: {raw_message}"
            )
        except Exception:
            pass
    return (
        f"Tool '{tool_name}' received invalid arguments: {raw_message}. "
        "Check the tool schema and retry with the correct field names and types."
    )


def classify_error(
    failure: Union[ParseError, ToolResult],
    attempted_tool_name: Optional[str] = None,
) -> ClassifiedError:
    """
    Classify a raw failure into a ClassifiedError with repair hint.

    This is stateless — it does not track retries. Use ErrorHandler for
    stateful retry tracking.

    EXECUTION FLOW:
    1. Identify whether failure is a ParseError or ToolResult.
    2. For ParseError: always PARSE_FAILED.
    3. For ToolResult: inspect error string to distinguish UNKNOWN_TOOL,
       VALIDATION_FAILED, and EXECUTION_FAILED.
    4. Build targeted repair_hint for each category.

    Args:
        failure:              A ParseError or a ToolResult with error set.
        attempted_tool_name:  The tool name from the ToolCall, if available.
                              Used to look up the tool schema for hints.

    Returns:
        ClassifiedError with kind and repair_hint set.
    """
    if isinstance(failure, ParseError):
        return ClassifiedError(
            kind=ToolErrorKind.PARSE_FAILED,
            raw_message=failure.message,
            tool_name=None,
            repair_hint=_build_repair_hint_for_parse(failure),
        )

    # ToolResult with error
    assert isinstance(failure, ToolResult) and failure.is_error
    raw_msg = failure.error or "Unknown error"
    tool_name = (
        attempted_tool_name
        or (failure.metadata or {}).get("tool_name")
    )

    raw_lower = raw_msg.lower()

    # Unknown tool: dispatcher wraps KeyError from get_or_raise
    if "unknown tool" in raw_lower or "not found" in raw_lower:
        extracted_name = tool_name or "unknown"
        return ClassifiedError(
            kind=ToolErrorKind.UNKNOWN_TOOL,
            raw_message=raw_msg,
            tool_name=extracted_name,
            repair_hint=_build_repair_hint_for_unknown_tool(extracted_name),
        )

    # Validation failure: safe_invoke wraps Pydantic ValidationError
    if "validation" in raw_lower or "input validation failed" in raw_lower:
        return ClassifiedError(
            kind=ToolErrorKind.VALIDATION_FAILED,
            raw_message=raw_msg,
            tool_name=tool_name,
            repair_hint=_build_repair_hint_for_validation(
                tool_name or "unknown", raw_msg
            ),
        )

    # Execution failure: tool.invoke() raised
    return ClassifiedError(
        kind=ToolErrorKind.EXECUTION_FAILED,
        raw_message=raw_msg,
        tool_name=tool_name,
        repair_hint=(
            f"Tool '{tool_name}' failed during execution: {raw_msg}. "
            "This is a tool execution error, not an argument error. "
            "Try a different approach or use a different tool."
        ),
    )


# =============================================================================
# Part 6: ERROR HANDLER (Stateful per-agent-turn recovery orchestrator)
# =============================================================================

class ErrorHandler:
    """
    LAYER: Agent -- Stateful per-agent-turn tool call recovery manager.

    Purpose:
        - Track retry counts per tool call name within a single agent turn.
        - Classify errors via classify_error().
        - Apply RetryPolicy to decide RETRY_WITH_HINT or ABORT.
        - Produce RecoveryDecision objects for the agent loop to act on.

    How it works:
        - Instantiate once per agent turn (or once globally and call reset()
          between turns).
        - Call handle() on every ParseError or failed ToolResult.
        - Check decision.should_retry to decide next step.
        - The repair_prompt in the decision is injected as the next
          Observation in the ReAct prompt.

    Lifecycle:
        handler = ErrorHandler(policy=RetryPolicy(max_retries=3))
        for each LLM call:
            result = parse_tool_call(raw)
            if isinstance(result, ParseError):
                decision = handler.handle(result)
                if decision.should_retry:
                    inject decision.repair_prompt as Observation, re-call LLM
                else:
                    return terminal error
            handler.reset()  <- reset between distinct tool call batches
    """

    def __init__(self, policy: Optional[RetryPolicy] = None) -> None:
        self._policy = policy or RetryPolicy()
        # Maps tool_name (or "_parse" for parse errors) -> attempt count
        self._attempt_counts: Dict[str, int] = {}

    def handle(
        self,
        failure: Union[ParseError, ToolResult],
        attempted_tool_name: Optional[str] = None,
    ) -> RecoveryDecision:
        """
        Classify a failure and return a recovery decision.

        EXECUTION FLOW:
        1. Classify the raw failure into a ClassifiedError.
        2. Determine the tracking key (tool name or "_parse").
        3. Increment attempt count for this key.
        4. If kind is not retryable OR budget exhausted -> ABORT.
        5. Otherwise -> RETRY_WITH_HINT with repair_prompt.

        Args:
            failure:              ParseError or ToolResult with error set.
            attempted_tool_name:  Tool name from ToolCall, if available.

        Returns:
            RecoveryDecision with action and optional repair_prompt.
        """
        classified = classify_error(failure, attempted_tool_name)

        # Use tool name as tracking key, or "_parse" for parse-level errors
        key = classified.tool_name or "_parse"
        self._attempt_counts[key] = self._attempt_counts.get(key, 0) + 1
        attempt = self._attempt_counts[key]
        max_attempts = self._policy.max_retries

        # Budget exhausted: synthetic BUDGET_EXCEEDED wraps the original error
        if attempt > max_attempts:
            budget_error = ClassifiedError(
                kind=ToolErrorKind.BUDGET_EXCEEDED,
                raw_message=classified.raw_message,
                tool_name=classified.tool_name,
                repair_hint=(
                    f"Maximum retry attempts ({max_attempts}) exceeded for "
                    f"'{classified.tool_name or 'tool call'}'. Aborting."
                ),
            )
            return RecoveryDecision(
                action=RecoveryAction.ABORT,
                classified_error=budget_error,
                attempt=attempt,
                max_attempts=max_attempts,
                repair_prompt=None,
            )

        # Non-retryable error kind: ABORT immediately
        if classified.kind not in self._policy.retryable_kinds:
            return RecoveryDecision(
                action=RecoveryAction.ABORT,
                classified_error=classified,
                attempt=attempt,
                max_attempts=max_attempts,
                repair_prompt=None,
            )

        # Retryable: produce repair prompt for LLM re-injection
        repair_prompt = classified.to_observation()
        return RecoveryDecision(
            action=RecoveryAction.RETRY_WITH_HINT,
            classified_error=classified,
            attempt=attempt,
            max_attempts=max_attempts,
            repair_prompt=repair_prompt,
        )

    def reset(self, key: Optional[str] = None) -> None:
        """
        Reset retry counters.

        Args:
            key: If given, reset only this tool's counter.
                 If None, reset all counters (call between turns).
        """
        if key is not None:
            self._attempt_counts.pop(key, None)
        else:
            self._attempt_counts.clear()

    @property
    def attempt_counts(self) -> Dict[str, int]:
        """Read-only snapshot of current attempt counts (for logging)."""
        return dict(self._attempt_counts)


# =============================================================================
# MAIN ENTRY POINT (Smoke test: all error kinds + retry policy)
# =============================================================================

if __name__ == "__main__":
    import asyncio
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

    from jarvis_core.agent.tool import Tool, ToolInput, ToolResult, safe_invoke
    from jarvis_core.agent.parser import (
        ParseError, ToolCall, parse_tool_call, dispatch,
    )
    from jarvis_core.agent.errors import (
        ToolErrorKind, ClassifiedError, RetryPolicy, RecoveryAction,
        RecoveryDecision, ErrorHandler, classify_error,
    )

    # -- Register a test tool -----------------------------------------------

    class CalcInput(ToolInput):
        expression: str

    @Tool.register("calculator")
    class CalcTool(Tool):
        name = "calculator"
        description = "Evaluate a math expression."
        input_schema = CalcInput

        @property
        def is_concurrency_safe(self) -> bool:
            return True

        async def invoke(self, tool_input: CalcInput) -> ToolResult:
            if tool_input.expression == "BOOM":
                raise RuntimeError("Intentional failure for testing.")
            try:
                result = eval(tool_input.expression, {"__builtins__": {}})
                return ToolResult(output=result)
            except Exception as e:
                return ToolResult(error=f"Eval failed: {e}")

    async def smoke_test() -> None:
        print("=" * 65)
        print("  ErrorHandler & Recovery -- Smoke Test")
        print("=" * 65)

        handler = ErrorHandler(policy=RetryPolicy(max_retries=2))

        # --- Test 1: PARSE_FAILED (no JSON in output) ---
        raw_garbage = "I don't think I need any tools here."
        parse_result = parse_tool_call(raw_garbage)
        assert isinstance(parse_result, ParseError)
        decision = handler.handle(parse_result)
        assert decision.classified_error.kind == ToolErrorKind.PARSE_FAILED
        assert decision.action == RecoveryAction.RETRY_WITH_HINT
        assert decision.attempt == 1
        print(f"\n  [1] PARSE_FAILED -> {decision.action.value}")
        print(f"      Repair: {decision.repair_prompt}")

        # --- Test 2: Second parse failure -> still retryable (attempt 2/2) ---
        decision2 = handler.handle(parse_result)
        assert decision2.attempt == 2
        assert decision2.action == RecoveryAction.RETRY_WITH_HINT
        print(f"  [2] PARSE_FAILED (attempt 2) -> {decision2.action.value}")

        # --- Test 3: Third parse failure -> budget exceeded, ABORT ---
        decision3 = handler.handle(parse_result)
        assert decision3.action == RecoveryAction.ABORT
        assert decision3.classified_error.kind == ToolErrorKind.BUDGET_EXCEEDED
        print(f"  [3] PARSE_FAILED (attempt 3) -> {decision3.action.value} (budget exhausted)")

        # --- Test 4: UNKNOWN_TOOL -> ABORT immediately (not retryable) ---
        handler.reset()
        tc_unknown = ToolCall(name="nonexistent", arguments={})
        result_unknown = await dispatch(tc_unknown)
        assert result_unknown.is_error
        decision4 = handler.handle(result_unknown, attempted_tool_name="nonexistent")
        assert decision4.classified_error.kind == ToolErrorKind.UNKNOWN_TOOL
        assert decision4.action == RecoveryAction.ABORT
        print(f"\n  [4] UNKNOWN_TOOL -> {decision4.action.value}")
        print(f"      Hint: {decision4.classified_error.repair_hint}")

        # --- Test 5: VALIDATION_FAILED -> RETRY_WITH_HINT ---
        handler.reset()
        tc_bad_args = ToolCall(name="calculator", arguments={"wrong_field": "oops"})
        result_bad = await dispatch(tc_bad_args)
        assert result_bad.is_error
        decision5 = handler.handle(result_bad, attempted_tool_name="calculator")
        assert decision5.classified_error.kind == ToolErrorKind.VALIDATION_FAILED
        assert decision5.action == RecoveryAction.RETRY_WITH_HINT
        print(f"\n  [5] VALIDATION_FAILED -> {decision5.action.value}")
        print(f"      Hint: {decision5.classified_error.repair_hint}")

        # --- Test 6: EXECUTION_FAILED -> ABORT immediately (code bug) ---
        handler.reset()
        tc_boom = ToolCall(name="calculator", arguments={"expression": "BOOM"})
        result_boom = await dispatch(tc_boom)
        assert result_boom.is_error
        decision6 = handler.handle(result_boom, attempted_tool_name="calculator")
        assert decision6.classified_error.kind == ToolErrorKind.EXECUTION_FAILED
        assert decision6.action == RecoveryAction.ABORT
        print(f"\n  [6] EXECUTION_FAILED -> {decision6.action.value}")
        print(f"      Hint: {decision6.classified_error.repair_hint}")

        # --- Test 7: Successful dispatch (no handler needed) ---
        handler.reset()
        tc_good = ToolCall(name="calculator", arguments={"expression": "6 * 7"})
        result_good = await dispatch(tc_good)
        assert result_good.is_success
        assert result_good.output == 42
        print(f"\n  [7] Success (no error): output={result_good.output}")

        # --- Test 8: summary() format ---
        print(f"\n  [8] Decision summary: '{decision5.summary()}'")
        assert "attempt=1/2" in decision5.summary()

        # --- Test 9: attempt_counts snapshot ---
        handler.reset()
        handler.handle(parse_result)
        handler.handle(parse_result)
        counts = handler.attempt_counts
        assert counts.get("_parse") == 2
        print(f"  [9] Attempt counts: {counts}")

        # --- Test 10: Selective reset ---
        handler.reset(key="_parse")
        assert "_parse" not in handler.attempt_counts
        print(f"  [10] After selective reset: {handler.attempt_counts}")

        print("\n" + "=" * 65)
        print("  All smoke tests passed.")
        print("=" * 65)

    asyncio.run(smoke_test())
