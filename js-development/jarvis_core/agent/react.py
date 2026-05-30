"""
react.py

JARVIS Agent Layer (ReAct): the main Reason -> Act -> Observe loop.

LAYER: Brain (Orchestration)

Import with:
    from jarvis_core.agent.react import ReActLoop, ReActResult

=============================================================================
THE BIG PICTURE
=============================================================================

Without ReActLoop:
    -> The 18 callable tools, the Plan/Executor DAG (3.3), the EventBus (3.4.2),
       the MIRROR-Lite prompt (3.4.5), the CoT loop detector (3.4.6), the
       permission engine (3.4.8), and the bash classifier (3.4.9) all sit on
       the floor as separate parts. Nothing turns them into an agent.
    -> The dispatcher knows how to RUN one tool call. It does not know how
       to drive a multi-turn conversation where the LLM reasons, picks a
       tool, sees the result, and decides whether to keep going or stop.

With ReActLoop (this module, Stage 3.4 orchestrator):
    -> Step 1: User query arrives. We inject MIRROR-Lite into the system
       prompt so the model reflects on Goals / Reasoning / Memory before
       emitting its answer (Stage 3.4.5).
    -> Step 2: The LLM emits text. We parse tool calls out of it via
       parse_tool_calls (Stage 3.1.3). Concurrency-safe calls are batched
       via asyncio.gather; unsafe ones run serially -- this is STEAL #8 at
       the dispatch boundary (Stage 3.4.7).
    -> Step 3: BEFORE each tool fires, the permission engine (3.4.8) is
       consulted. shell_run goes through the BashClassifier (3.4.9) which
       auto-ALLOWs safe ops (grep, ls, cat) and DENIes structural CVEs
       (array-subscript cmd-sub). DENY short-circuits to a TOOL ERROR
       observation; ASK escalates to the configured ask_handler.
    -> Step 4: Tool results are formatted into LLM-readable observations
       via format_observation (Stage 3.4.3) and appended to the message
       history for the next LLM turn.
    -> Step 5: After every LLM emission, we run MetaR1Monitor on the raw
       text (Stage 3.4.6). Three "wait" or "actually" tokens flag the
       reasoning as unstable; the loop can abort or escalate.
    -> Step 6: Every transition (REASONING, TOOL_CALL, TOOL_RESULT,
       OBSERVATION, REFLECTION, ERROR, REPLAN, PLAN_COMPLETED) is published
       to the EventBus (3.4.2) so external observers (the trace persister
       in 3.5, the cost ledger in 3.0.2) can subscribe without coupling.
    -> Step 7: The loop terminates on (a) LLM emits no tool calls (final
       answer reached), (b) max_iterations hit, (c) CoT monitor flags
       instability and abort_on_instability=True, or (d) hard error.

=============================================================================
THE FLOW (Step by Step Execution Order)
=============================================================================

STEP 1: User passes a query into ReActLoop.run().
        |
        v
STEP 2: System prompt is built. MIRROR-Lite is injected (idempotent).
        Initial messages = [{role:system, content:...}, {role:user, content:query}]
        |
        v
STEP 3: Loop iteration:
            a. EventBus publish REASONING(payload={messages})
            b. raw = await llm_call(messages)
            c. Run MetaR1Monitor.from_cot_trace(raw). If unstable AND
               abort_on_instability: publish ERROR, exit.
            d. EventBus publish OBSERVATION(payload={raw}) for trace.
            e. Extract MIRROR-Lite reflection (best-effort).
               Publish REFLECTION if found.
            f. Parse tool calls. If none -> final answer; publish
               PLAN_COMPLETED, return ReActResult.
            g. For each tool call:
                  - PermissionContext.check(name, input)
                  - DENY -> synthetic error observation; do NOT dispatch.
                  - ASK -> ask_handler(name, input) decides ALLOW/DENY.
                  - ALLOW -> partition into safe/unsafe batches.
            h. Dispatch: safe via asyncio.gather, unsafe serial.
               Each result becomes a Step + ToolResult; publish
               TOOL_CALL + TOOL_RESULT for each.
            i. Append observations to messages as a user-role turn:
                  {"role": "user", "content": <formatted observations>}
        |
        v
STEP 4: Bounded by max_iterations. Final ReActResult carries:
            final_text (the last LLM emission without tool calls),
            messages (full transcript),
            tool_results (list of (call, result) pairs),
            iterations_used, terminated_reason, reflections.

=============================================================================

Prep for Stage 3.5 (MemGPT heartbeat consolidation): the EventBus stream is
the input. A heartbeat subscriber listens for PLAN_COMPLETED events and
runs the consolidation agent against the recent context window.
"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, Union

from jarvis_core.agent.monitor import InstabilityReport, MetaR1Monitor
from jarvis_core.agent.observation import (
    DEFAULT_MAX_OBSERVATION_CHARS,
    format_observation,
    truncate,
)
from jarvis_core.agent.parser import ParseError, ToolCall, parse_tool_calls
from jarvis_core.agent.permissions import PermissionContext, PermissionDecision
from jarvis_core.agent.plan import Step, StepStatus
from jarvis_core.agent.reflection import (
    MirrorReflection,
    extract_mirror_reflection,
    inject_mirror_lite,
)
from jarvis_core.agent.tool import Tool, ToolResult, safe_invoke
from jarvis_core.agent.trace import EventBus, StepType, TraceStep


# =============================================================================
# Part 1: TYPES
# =============================================================================

# LLM call protocol: takes a list of {role, content} messages and returns
# the assistant's raw text response. Sync or async; the loop handles both.
LLMCall = Callable[
    [List[Dict[str, str]]],
    Union[str, Awaitable[str]],
]

# ASK escalation handler. Called when permission engine returns ASK and the
# loop is running autonomously. Sync or async. Returns ALLOW or DENY.
AskHandler = Callable[
    [str, Dict[str, Any]],
    Union[PermissionDecision, Awaitable[PermissionDecision]],
]


# =============================================================================
# Part 2: TERMINATION REASONS
# =============================================================================

TERMINATED_FINAL_ANSWER = "final_answer"
TERMINATED_MAX_ITERATIONS = "max_iterations_reached"
TERMINATED_INSTABILITY = "cot_instability_detected"
TERMINATED_ERROR = "loop_error"


# =============================================================================
# Part 3: RESULT DATACLASS
# =============================================================================

@dataclass
class ReActResult:
    """The outcome of a ReActLoop.run() invocation.

    Fields:
        final_text:        The last LLM emission without a tool call, i.e.,
                           the answer the model committed to. Empty string
                           when the loop terminated for any other reason.
        messages:          The full transcript (system + user + assistant + tool
                           observations) in order.
        tool_calls:        List of (ToolCall, ToolResult) pairs across all iterations.
        iterations_used:   How many ReAct iterations ran (lower of max_iterations
                           and natural termination).
        terminated_reason: One of the TERMINATED_* constants above.
        reflections:       Every MIRROR-Lite reflection extracted, in emission order.
        instability:       Last InstabilityReport seen (None if monitor disabled).
        error:             Free-form error string when terminated_reason == ERROR.
    """
    final_text: str = ""
    messages: List[Dict[str, str]] = field(default_factory=list)
    tool_calls: List[Tuple[ToolCall, ToolResult]] = field(default_factory=list)
    iterations_used: int = 0
    terminated_reason: str = TERMINATED_MAX_ITERATIONS
    reflections: List[MirrorReflection] = field(default_factory=list)
    instability: Optional[InstabilityReport] = None
    error: Optional[str] = None


# =============================================================================
# Part 4: REACT LOOP
# =============================================================================

class ReActLoop:
    """Reason -> Act -> Observe driver.

    Constructor binds collaborators once; run(query) is a per-query invocation
    that can be re-called many times against the same loop instance.

    Concurrency partitioning (STEAL #8): when the LLM emits multiple tool
    calls in one turn, this loop partitions them by Tool.is_concurrency_safe:
        - safe tools fire via asyncio.gather (parallel)
        - unsafe tools fire serially (sequential)
    This is the Stage 3.4.7 hook -- the same logic exists in PlanExecutor
    (3.3.3); this method routes single-turn batches the same way.
    """

    def __init__(
        self,
        llm_call: LLMCall,
        tool_instances: Dict[str, Tool],
        system_prompt: str = "",
        event_bus: Optional[EventBus] = None,
        permission_context: Optional[PermissionContext] = None,
        ask_handler: Optional[AskHandler] = None,
        max_iterations: int = 10,
        enable_mirror_lite: bool = True,
        enable_cot_monitor: bool = True,
        abort_on_instability: bool = False,
        observation_max_chars: int = DEFAULT_MAX_OBSERVATION_CHARS,
        trace_arguments: bool = False,
    ) -> None:
        self._llm_call = llm_call
        self._tools = tool_instances
        self._system_prompt = system_prompt
        self._trace_arguments = trace_arguments
        self._bus = event_bus
        self._perms = permission_context
        self._ask_handler = ask_handler
        self._max_iterations = max_iterations
        self._enable_mirror = enable_mirror_lite
        self._enable_monitor = enable_cot_monitor
        self._abort_on_instability = abort_on_instability
        self._obs_max_chars = observation_max_chars

    # ---- Public API ------------------------------------------------------

    async def run(self, query: str) -> ReActResult:
        """Drive one user query through the ReAct loop."""
        result = ReActResult()

        system_text = self._system_prompt or ""
        if self._enable_mirror:
            system_text = inject_mirror_lite(system_text)

        messages: List[Dict[str, str]] = []
        if system_text:
            messages.append({"role": "system", "content": system_text})
        messages.append({"role": "user", "content": query})
        result.messages = messages

        # Fire tool setup hooks once at loop start. teardown in finally.
        used_tool_names = set(self._tools.keys())
        await self._fire_setup(used_tool_names)

        try:
            for iteration in range(self._max_iterations):
                result.iterations_used = iteration + 1

                await self._publish(StepType.REASONING, {
                    "iteration": iteration,
                    "messages_so_far": len(messages),
                })

                raw = await self._call_llm(messages)
                messages.append({"role": "assistant", "content": raw})
                await self._publish(StepType.OBSERVATION, {
                    "iteration": iteration,
                    "raw_len": len(raw),
                })

                # Stage 3.4.6: CoT loop detection
                if self._enable_monitor:
                    report = MetaR1Monitor.from_cot_trace(raw)
                    result.instability = report
                    if report.is_unstable and self._abort_on_instability:
                        await self._publish(StepType.ERROR, {
                            "reason": "cot_instability",
                            "flagged_tokens": report.flagged_tokens,
                        })
                        result.terminated_reason = TERMINATED_INSTABILITY
                        result.error = (
                            f"CoT instability detected: {report.flagged_tokens}"
                        )
                        return result

                # Stage 3.4.5: extract MIRROR-Lite reflection (best-effort)
                if self._enable_mirror:
                    reflection = extract_mirror_reflection(raw)
                    if reflection is not None:
                        result.reflections.append(reflection)
                        await self._publish(StepType.REFLECTION, {
                            "goals_alignment": reflection.goals_alignment,
                        })

                # Stage 3.1.3: parse tool calls.
                # CRITICAL: strip <mirror>...</mirror> before parsing -- the
                # MIRROR-Lite template encourages JSON-in-mirror, which the
                # bare-JSON brace-finder in parser._BRACE_PATTERN would otherwise
                # match FIRST (producing a ParseError for the no-name JSON and
                # making real tool calls vanish). Strip first; then parse.
                parsable_raw = self._strip_reflection(raw)
                parsed = parse_tool_calls(parsable_raw)
                tool_calls = [p for p in parsed if isinstance(p, ToolCall)]

                if not tool_calls:
                    # No tool calls => final answer reached.
                    result.final_text = self._strip_reflection(raw)
                    result.terminated_reason = TERMINATED_FINAL_ANSWER
                    await self._publish(StepType.PLAN_COMPLETED, {
                        "iterations": iteration + 1,
                    })
                    return result

                # Stage 3.4.7 + 3.4.8 + 3.4.9: check permissions, partition,
                # dispatch, format observations.
                observations: List[str] = []
                for tc in tool_calls:
                    await self._publish(
                        StepType.TOOL_CALL, self._tool_call_payload(tc)
                    )

                # Concurrency partition + permission check happens per-call
                safe_calls: List[ToolCall] = []
                unsafe_calls: List[ToolCall] = []
                blocked: List[Tuple[ToolCall, str]] = []

                for tc in tool_calls:
                    if tc.name not in self._tools:
                        blocked.append((tc, f"tool '{tc.name}' not registered"))
                        continue
                    decision = await self._check_permission(tc.name, tc.arguments)
                    if decision == PermissionDecision.DENY:
                        blocked.append((tc, f"permission DENY for '{tc.name}'"))
                        continue
                    if decision == PermissionDecision.ASK:
                        # Escalate via ask_handler. FAIL-CLOSED: only an
                        # explicit ALLOW from the handler dispatches. ASK,
                        # DENY, None, or any non-ALLOW value blocks.
                        resolved = await self._call_ask_handler(tc.name, tc.arguments)
                        if resolved != PermissionDecision.ALLOW:
                            blocked.append((
                                tc,
                                f"permission ASK->{resolved.value} for '{tc.name}'",
                            ))
                            continue
                    # ALLOW: partition by concurrency safety
                    tool = self._tools[tc.name]
                    if tool.is_concurrency_safe:
                        safe_calls.append(tc)
                    else:
                        unsafe_calls.append(tc)

                # Run safe calls concurrently
                safe_results: List[Tuple[ToolCall, ToolResult]] = []
                if safe_calls:
                    coros = [
                        safe_invoke(self._tools[tc.name], dict(tc.arguments))
                        for tc in safe_calls
                    ]
                    raw_results = await asyncio.gather(*coros, return_exceptions=False)
                    safe_results = list(zip(safe_calls, raw_results))

                # Run unsafe calls serially
                unsafe_results: List[Tuple[ToolCall, ToolResult]] = []
                for tc in unsafe_calls:
                    res = await safe_invoke(self._tools[tc.name], dict(tc.arguments))
                    unsafe_results.append((tc, res))

                # Synthesize blocked results (no dispatch)
                blocked_results: List[Tuple[ToolCall, ToolResult]] = [
                    (tc, ToolResult(error=f"[BLOCKED] {reason}"))
                    for tc, reason in blocked
                ]

                # Preserve original order: rebuild iterating over tool_calls
                results_by_call: Dict[int, ToolResult] = {}
                for tc, res in safe_results + unsafe_results + blocked_results:
                    results_by_call[id(tc)] = res
                ordered_pairs: List[Tuple[ToolCall, ToolResult]] = []
                for tc in tool_calls:
                    res = results_by_call.get(id(tc))
                    if res is None:
                        res = ToolResult(error="internal: missing dispatch result")
                    ordered_pairs.append((tc, res))

                # Per-observation budget so N tool results don't drop the
                # tail when joined+truncated globally. Floor at 256 chars so
                # tiny budgets still surface a meaningful snippet.
                per_obs_budget = max(
                    256, self._obs_max_chars // max(1, len(ordered_pairs))
                )

                # Publish + format
                for tc, res in ordered_pairs:
                    await self._publish(StepType.TOOL_RESULT, {
                        "name": tc.name,
                        "is_success": res.is_success,
                        "error": res.error,
                    })
                    obs_text = self._format_tool_observation(
                        tc, res, max_chars=per_obs_budget
                    )
                    observations.append(obs_text)
                    result.tool_calls.append((tc, res))

                # Append all observations as one user turn so the LLM sees
                # them coherently in the next iteration. Per-obs budgets above
                # mean joined length is already bounded; the global cap below
                # is a final safety net.
                joined = truncate("\n\n".join(observations), self._obs_max_chars)
                messages.append({"role": "user", "content": joined})

            # Loop completed without natural termination -> max iterations.
            result.terminated_reason = TERMINATED_MAX_ITERATIONS
            await self._publish(StepType.PLAN_FAILED, {
                "reason": "max_iterations_reached",
                "iterations": self._max_iterations,
            })
            return result

        except Exception as exc:
            # Default trace payload carries only the exception TYPE so that
            # tool-input echoes (which may contain secrets) don't reach the
            # persisted trace file. The full message goes to result.error
            # for the caller; opt in to trace via trace_arguments=True.
            err_payload: Dict[str, Any] = {"type": type(exc).__name__}
            if self._trace_arguments:
                err_payload["msg"] = str(exc)
            await self._publish(StepType.ERROR, err_payload)
            result.terminated_reason = TERMINATED_ERROR
            result.error = f"{type(exc).__name__}: {exc}"
            return result
        finally:
            await self._fire_teardown(used_tool_names)

    # ---- Internals -------------------------------------------------------

    async def _call_llm(self, messages: List[Dict[str, str]]) -> str:
        out = self._llm_call(list(messages))
        if inspect.isawaitable(out):
            out = await out
        return str(out)

    async def _check_permission(
        self, tool_name: str, tool_input: Dict[str, Any]
    ) -> PermissionDecision:
        if self._perms is None:
            return PermissionDecision.ALLOW
        return await self._perms.check(tool_name, tool_input)

    async def _call_ask_handler(
        self, tool_name: str, tool_input: Dict[str, Any]
    ) -> PermissionDecision:
        if self._ask_handler is None:
            return PermissionDecision.DENY  # safe default in autonomous mode
        try:
            out = self._ask_handler(tool_name, tool_input)
            if inspect.isawaitable(out):
                out = await out
            if isinstance(out, PermissionDecision):
                return out
        except Exception:
            pass
        return PermissionDecision.DENY

    def _format_tool_observation(
        self,
        tc: ToolCall,
        res: ToolResult,
        max_chars: Optional[int] = None,
    ) -> str:
        """Turn a ToolResult into an LLM-readable observation via the
        observation module's format_observation, by wrapping in a synthetic
        Step so we get uniform formatting."""
        if res.is_success:
            status = StepStatus.SUCCEEDED
        else:
            status = StepStatus.FAILED
        synthetic = Step(
            description=f"tool {tc.name}",
            tool_name=tc.name,
            tool_input=dict(tc.arguments),
            step_id=tc.call_id or f"call_{id(tc):x}",
            status=status,
            result=res,
            attempts=1,
        )
        budget = max_chars if max_chars is not None else self._obs_max_chars
        return format_observation(synthetic, max_chars=budget)

    def _tool_call_payload(self, tc: ToolCall) -> Dict[str, Any]:
        """Build a TOOL_CALL event payload.

        By default, publishes only the tool name + the argument KEY names --
        argument VALUES are NOT included because they often carry LLM-injected
        content that the trace persister flushes to disk verbatim. A future
        secret in tc.arguments (API key surfaced from prior context, file
        path, OAuth token) would leak into the trace file.

        Set ReActLoop(trace_arguments=True) to opt back in to full argument
        dumping for debugging.
        """
        payload: Dict[str, Any] = {"name": tc.name}
        if self._trace_arguments:
            payload["arguments"] = dict(tc.arguments)
        else:
            payload["arg_keys"] = sorted(tc.arguments.keys())
        return payload

    def _strip_reflection(self, raw: str) -> str:
        """Remove the <mirror>...</mirror> reflection block from the
        user-facing final text. Best-effort; keeps the rest verbatim."""
        import re as _re
        return _re.sub(r"<mirror>.*?</mirror>", "", raw, flags=_re.DOTALL).strip()

    async def _publish(self, step_type: StepType, payload: Dict[str, Any]) -> None:
        if self._bus is None:
            return
        try:
            await self._bus.publish(
                event_name=step_type.value,
                step=TraceStep(step_type=step_type, payload=payload),
            )
        except Exception:
            pass  # bus failure must never break the loop

    async def _fire_setup(self, names: set) -> None:
        for n in names:
            t = self._tools.get(n)
            if t is None:
                continue
            try:
                await t.setup()
            except Exception:
                pass

    async def _fire_teardown(self, names: set) -> None:
        for n in names:
            t = self._tools.get(n)
            if t is None:
                continue
            try:
                await t.teardown()
            except Exception:
                pass


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS
# =============================================================================

if __name__ == "__main__":
    import json
    from jarvis_core.agent.tool import Tool, ToolInput, ToolResult
    from jarvis_core.agent.permissions import PermissionRule
    from pydantic import Field

    print("=" * 70)
    print("  react.py -- Smoke Tests (Stage 3.4 ReAct Loop)")
    print("=" * 70)

    passed = 0
    failed: List[str] = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        global passed
        if cond:
            passed += 1
        else:
            failed.append(f"FAIL: {name}" + (f" ({hint})" if hint else ""))

    # -- Stub tools (NOT registered; instance-based so the test is hermetic) --

    class _CalcIn(ToolInput):
        a: int = Field(description="left")
        b: int = Field(description="right")

    class StubAdd(Tool):
        name = "stub_add"
        description = "Add two integers."
        input_schema = _CalcIn

        @property
        def is_concurrency_safe(self) -> bool:
            return True

        async def invoke(self, tool_input: _CalcIn) -> ToolResult:
            return ToolResult(output=tool_input.a + tool_input.b)

    class StubMul(Tool):
        name = "stub_mul"
        description = "Multiply two integers."
        input_schema = _CalcIn

        @property
        def is_concurrency_safe(self) -> bool:
            return True

        async def invoke(self, tool_input: _CalcIn) -> ToolResult:
            return ToolResult(output=tool_input.a * tool_input.b)

    class StubMutate(Tool):
        """Unsafe stateful tool: serial execution required."""
        name = "stub_mutate"
        description = "Increment a shared counter."
        input_schema = _CalcIn
        counter = 0

        @property
        def is_concurrency_safe(self) -> bool:
            return False

        async def invoke(self, tool_input: _CalcIn) -> ToolResult:
            StubMutate.counter += 1
            return ToolResult(output=StubMutate.counter)

    # -- Scripted LLM (deterministic) ----------------------------------------

    def make_scripted_llm(responses: List[str]):
        """Return an LLM call that emits the next response in the queue."""
        idx = [0]

        def llm(messages: List[Dict[str, str]]) -> str:
            i = idx[0]
            if i >= len(responses):
                # Out of script -> return a benign final answer.
                return "DONE (script exhausted)"
            idx[0] += 1
            return responses[i]
        return llm

    async def smoke_test() -> None:
        # ---- T1: No tool call -> immediate final answer -----------------
        llm1 = make_scripted_llm(["The answer is 42."])
        loop1 = ReActLoop(
            llm_call=llm1,
            tool_instances={},
            enable_mirror_lite=False,
            enable_cot_monitor=False,
        )
        r1 = await loop1.run("What is the meaning of life?")
        check("T1a terminated final_answer",
              r1.terminated_reason == TERMINATED_FINAL_ANSWER)
        check("T1b final_text echoed",
              "42" in r1.final_text, hint=r1.final_text)
        check("T1c one iteration used", r1.iterations_used == 1)
        check("T1d zero tool calls", len(r1.tool_calls) == 0)

        # ---- T2: Single tool call then final answer ---------------------
        llm2 = make_scripted_llm([
            json.dumps({"name": "stub_add", "arguments": {"a": 2, "b": 3}}),
            "The sum is 5.",
        ])
        loop2 = ReActLoop(
            llm_call=llm2,
            tool_instances={"stub_add": StubAdd()},
            enable_mirror_lite=False,
            enable_cot_monitor=False,
        )
        r2 = await loop2.run("Add 2 and 3.")
        check("T2a final answer reached",
              r2.terminated_reason == TERMINATED_FINAL_ANSWER)
        check("T2b two iterations", r2.iterations_used == 2)
        check("T2c one tool call recorded", len(r2.tool_calls) == 1)
        check("T2d tool returned 5",
              r2.tool_calls[0][1].output == 5,
              hint=str(r2.tool_calls[0][1].output))
        check("T2e final_text has 5", "5" in r2.final_text, hint=r2.final_text)

        # ---- T3: Multiple safe tool calls in one turn (concurrency) -----
        llm3 = make_scripted_llm([
            json.dumps([
                {"name": "stub_add", "arguments": {"a": 1, "b": 2}},
                {"name": "stub_mul", "arguments": {"a": 3, "b": 4}},
            ]),
            "Sum = 3, product = 12.",
        ])
        loop3 = ReActLoop(
            llm_call=llm3,
            tool_instances={"stub_add": StubAdd(), "stub_mul": StubMul()},
            enable_mirror_lite=False,
            enable_cot_monitor=False,
        )
        r3 = await loop3.run("Compute 1+2 and 3*4 in parallel.")
        check("T3a two tool calls dispatched", len(r3.tool_calls) == 2)
        outs = sorted([p[1].output for p in r3.tool_calls])
        check("T3b results are 3 and 12", outs == [3, 12], hint=str(outs))

        # ---- T4: Unsafe tool serializes (counter increments deterministically)
        StubMutate.counter = 0
        # 3 mutate calls in one turn, then final.
        bulk_calls = json.dumps([
            {"name": "stub_mutate", "arguments": {"a": 0, "b": 0}}
            for _ in range(3)
        ])
        llm4 = make_scripted_llm([bulk_calls, "Counter advanced."])
        loop4 = ReActLoop(
            llm_call=llm4,
            tool_instances={"stub_mutate": StubMutate()},
            enable_mirror_lite=False,
            enable_cot_monitor=False,
        )
        r4 = await loop4.run("Bump 3x")
        results = [p[1].output for p in r4.tool_calls]
        check("T4a 3 unsafe calls executed", len(results) == 3)
        check("T4b results strictly increasing (serialized)",
              results == sorted(results), hint=str(results))
        check("T4c final counter == 3", StubMutate.counter == 3)

        # ---- T5: max_iterations cap fires --------------------------------
        # Force the LLM to always emit a tool call (no final).
        always_call = json.dumps(
            {"name": "stub_add", "arguments": {"a": 1, "b": 1}}
        )
        llm5 = make_scripted_llm([always_call] * 10)
        loop5 = ReActLoop(
            llm_call=llm5,
            tool_instances={"stub_add": StubAdd()},
            enable_mirror_lite=False,
            enable_cot_monitor=False,
            max_iterations=4,
        )
        r5 = await loop5.run("Loop forever.")
        check("T5a hit max_iterations",
              r5.terminated_reason == TERMINATED_MAX_ITERATIONS)
        check("T5b iterations == 4", r5.iterations_used == 4)

        # ---- T6: Permission DENY blocks dispatch -------------------------
        perm6 = PermissionContext(
            rules=[PermissionRule("stub_add", PermissionDecision.DENY)],
            default=PermissionDecision.ASK,
        )
        llm6 = make_scripted_llm([
            json.dumps({"name": "stub_add", "arguments": {"a": 1, "b": 1}}),
            "Cannot complete.",
        ])
        loop6 = ReActLoop(
            llm_call=llm6,
            tool_instances={"stub_add": StubAdd()},
            permission_context=perm6,
            enable_mirror_lite=False,
            enable_cot_monitor=False,
        )
        r6 = await loop6.run("Try forbidden add.")
        check("T6a tool call recorded but blocked",
              len(r6.tool_calls) == 1)
        check("T6b result is error",
              r6.tool_calls[0][1].is_error)
        check("T6c error mentions BLOCKED",
              "BLOCKED" in (r6.tool_calls[0][1].error or ""),
              hint=str(r6.tool_calls[0][1].error))

        # ---- T7: Permission ASK + no ask_handler -> safe DENY ------------
        perm7 = PermissionContext(default=PermissionDecision.ASK)
        llm7 = make_scripted_llm([
            json.dumps({"name": "stub_add", "arguments": {"a": 1, "b": 1}}),
            "Done.",
        ])
        loop7 = ReActLoop(
            llm_call=llm7,
            tool_instances={"stub_add": StubAdd()},
            permission_context=perm7,
            enable_mirror_lite=False,
            enable_cot_monitor=False,
        )
        r7 = await loop7.run("Add with ASK default.")
        check("T7 ASK without handler -> DENY (safe default)",
              r7.tool_calls[0][1].is_error,
              hint=str(r7.tool_calls[0][1].error))

        # ---- T8: ASK + handler ALLOW -> dispatch -------------------------
        async def allow_all(name: str, args: Dict[str, Any]) -> PermissionDecision:
            return PermissionDecision.ALLOW
        loop8 = ReActLoop(
            llm_call=make_scripted_llm([
                json.dumps({"name": "stub_add", "arguments": {"a": 2, "b": 5}}),
                "Done.",
            ]),
            tool_instances={"stub_add": StubAdd()},
            permission_context=PermissionContext(default=PermissionDecision.ASK),
            ask_handler=allow_all,
            enable_mirror_lite=False,
            enable_cot_monitor=False,
        )
        r8 = await loop8.run("Add with ASK->ALLOW.")
        check("T8 ASK handler ALLOW -> result computed",
              r8.tool_calls[0][1].output == 7,
              hint=str(r8.tool_calls[0][1].output))

        # ---- T9: EventBus receives StepType.PLAN_COMPLETED --------------
        bus = EventBus()
        events: List[StepType] = []
        bus.subscribe(StepType.PLAN_COMPLETED.value,
                      lambda step: events.append(step.step_type))
        bus.subscribe(StepType.TOOL_CALL.value,
                      lambda step: events.append(step.step_type))

        loop9 = ReActLoop(
            llm_call=make_scripted_llm([
                json.dumps({"name": "stub_add", "arguments": {"a": 1, "b": 1}}),
                "Done.",
            ]),
            tool_instances={"stub_add": StubAdd()},
            event_bus=bus,
            enable_mirror_lite=False,
            enable_cot_monitor=False,
        )
        await loop9.run("Trace this.")
        check("T9a PLAN_COMPLETED published",
              StepType.PLAN_COMPLETED in events)
        check("T9b TOOL_CALL published",
              StepType.TOOL_CALL in events)

        # ---- T10: CoT instability detection + abort ---------------------
        # 4 'wait' tokens -> unstable. abort_on_instability=True -> aborts.
        llm10 = make_scripted_llm([
            "wait, wait actually, wait but, wait hmm. Let me think.",
        ])
        loop10 = ReActLoop(
            llm_call=llm10,
            tool_instances={},
            enable_mirror_lite=False,
            enable_cot_monitor=True,
            abort_on_instability=True,
        )
        r10 = await loop10.run("Unstable trace.")
        check("T10a terminated by instability",
              r10.terminated_reason == TERMINATED_INSTABILITY,
              hint=r10.terminated_reason)
        check("T10b instability report attached",
              r10.instability is not None and r10.instability.is_unstable)

        # ---- T11: MIRROR-Lite injection + extraction --------------------
        # The system prompt should get MIRROR-Lite. The LLM's response
        # contains a <mirror> JSON block; the loop extracts it.
        mirror_response = (
            'Here is my answer.\n'
            '<mirror>{"goals_alignment": "ok", '
            '"reasoning_critique": "sound", '
            '"memory_relevance": "n/a"}</mirror>'
        )
        llm11 = make_scripted_llm([mirror_response])
        loop11 = ReActLoop(
            llm_call=llm11,
            tool_instances={},
            enable_mirror_lite=True,
            enable_cot_monitor=False,
        )
        r11 = await loop11.run("Reflect please.")
        check("T11a reflection extracted",
              len(r11.reflections) == 1,
              hint=str(len(r11.reflections)))
        check("T11b reflection has goals_alignment",
              r11.reflections[0].goals_alignment == "ok"
              if r11.reflections else False)
        check("T11c final_text strips <mirror> block",
              "<mirror>" not in r11.final_text)

        # ---- T12: Unknown tool -> BLOCKED observation -------------------
        llm12 = make_scripted_llm([
            json.dumps({"name": "ghost_tool", "arguments": {}}),
            "Cannot proceed.",
        ])
        loop12 = ReActLoop(
            llm_call=llm12,
            tool_instances={},
            enable_mirror_lite=False,
            enable_cot_monitor=False,
        )
        r12 = await loop12.run("Use ghost.")
        check("T12 unknown tool -> BLOCKED",
              r12.tool_calls[0][1].is_error and
              "BLOCKED" in (r12.tool_calls[0][1].error or ""))

        # ---- T13: Async LLM call also works -----------------------------
        async def async_llm(messages: List[Dict[str, str]]) -> str:
            await asyncio.sleep(0)
            return "Async final."
        loop13 = ReActLoop(
            llm_call=async_llm,
            tool_instances={},
            enable_mirror_lite=False,
            enable_cot_monitor=False,
        )
        r13 = await loop13.run("Async test.")
        check("T13 async LLM call returns",
              r13.terminated_reason == TERMINATED_FINAL_ANSWER)
        check("T13b final_text propagated",
              "Async" in r13.final_text)

        # ---- T14: ReActResult.messages preserves transcript ----------
        llm14 = make_scripted_llm([
            json.dumps({"name": "stub_add", "arguments": {"a": 4, "b": 4}}),
            "Eight.",
        ])
        loop14 = ReActLoop(
            llm_call=llm14,
            tool_instances={"stub_add": StubAdd()},
            system_prompt="You are a calculator.",
            enable_mirror_lite=False,
            enable_cot_monitor=False,
        )
        r14 = await loop14.run("4 + 4?")
        roles = [m["role"] for m in r14.messages]
        check("T14a messages includes system",
              roles[0] == "system")
        check("T14b messages includes user query",
              any(m["role"] == "user" and "4 + 4" in m["content"]
                  for m in r14.messages))
        check("T14c assistant turn captured",
              any(m["role"] == "assistant" for m in r14.messages))

        # ---- T15: Loop handles LLM raising -----------------------------
        def bad_llm(messages: List[Dict[str, str]]) -> str:
            raise RuntimeError("LLM is on fire")
        loop15 = ReActLoop(
            llm_call=bad_llm,
            tool_instances={},
            enable_mirror_lite=False,
            enable_cot_monitor=False,
        )
        r15 = await loop15.run("Crash plz.")
        check("T15a terminated_reason == ERROR",
              r15.terminated_reason == TERMINATED_ERROR)
        check("T15b error mentions LLM is on fire",
              "on fire" in (r15.error or ""))

        # ---- T16: REGRESSION GUARD (CRITICAL fix) ------------------------
        # MIRROR-Lite + bare-JSON tool call: previously the bare JSON inside
        # <mirror> was matched by parser._BRACE_PATTERN FIRST, treated as a
        # malformed tool call (ParseError), filtered out, and the real tool
        # call was silently lost. Now we strip <mirror> before parsing.
        mirror_then_call = (
            '<mirror>{"goals_alignment": "ok", "reasoning_critique": "n/a", '
            '"memory_relevance": "n/a"}</mirror>\n'
            '{"name": "stub_add", "arguments": {"a": 7, "b": 8}}'
        )
        llm16 = make_scripted_llm([mirror_then_call, "The sum is 15."])
        loop16 = ReActLoop(
            llm_call=llm16,
            tool_instances={"stub_add": StubAdd()},
            enable_mirror_lite=True,    # critical: mirror enabled
            enable_cot_monitor=False,
        )
        r16 = await loop16.run("Reflect and compute 7+8.")
        check("T16a tool call NOT lost when wrapped after <mirror>",
              len(r16.tool_calls) == 1,
              hint=f"got {len(r16.tool_calls)} tool calls")
        check("T16b stub_add returned 15",
              r16.tool_calls[0][1].output == 15
              if r16.tool_calls else False,
              hint=str(r16.tool_calls[0][1].output) if r16.tool_calls else "no result")
        check("T16c reflection extracted alongside tool call",
              len(r16.reflections) == 1)
        check("T16d final answer reached after tool call",
              r16.terminated_reason == TERMINATED_FINAL_ANSWER)

        # ---- T17: REGRESSION GUARD (HIGH fix: fail-closed ASK gate) -----
        # ask_handler returning ASK (or any non-ALLOW value) must NOT dispatch.
        async def hedge_handler(name: str, args: Dict[str, Any]) -> PermissionDecision:
            return PermissionDecision.ASK  # explicit abstention
        loop17 = ReActLoop(
            llm_call=make_scripted_llm([
                json.dumps({"name": "stub_add", "arguments": {"a": 1, "b": 1}}),
                "Cannot complete.",
            ]),
            tool_instances={"stub_add": StubAdd()},
            permission_context=PermissionContext(default=PermissionDecision.ASK),
            ask_handler=hedge_handler,
            enable_mirror_lite=False,
            enable_cot_monitor=False,
        )
        r17 = await loop17.run("Hedge me.")
        check("T17a ASK-returning handler -> BLOCKED (not ALLOW)",
              r17.tool_calls[0][1].is_error,
              hint=str(r17.tool_calls[0][1].error))
        check("T17b error mentions ASK->ask",
              "ASK->ask" in (r17.tool_calls[0][1].error or ""),
              hint=str(r17.tool_calls[0][1].error))

        # ---- T18: REGRESSION GUARD (HIGH fix: per-observation budget) ---
        # N tool calls with large outputs: each must survive the join+truncate.
        # Previously the joined string truncation at obs_max_chars dropped
        # everything after the first observation.
        class BigOut(Tool):
            name = "big_out"
            description = "Returns a large output."
            input_schema = _CalcIn

            @property
            def is_concurrency_safe(self) -> bool:
                return True

            async def invoke(self, tool_input: _CalcIn) -> ToolResult:
                # Each call returns 1000 chars
                return ToolResult(output="x" * 1000)

        loop18 = ReActLoop(
            llm_call=make_scripted_llm([
                json.dumps([
                    {"name": "big_out", "arguments": {"a": 1, "b": 1}},
                    {"name": "big_out", "arguments": {"a": 2, "b": 2}},
                    {"name": "big_out", "arguments": {"a": 3, "b": 3}},
                ]),
                "Done with all three.",
            ]),
            tool_instances={"big_out": BigOut()},
            enable_mirror_lite=False,
            enable_cot_monitor=False,
            observation_max_chars=3000,  # fits 3 x ~1000 char observations
        )
        r18 = await loop18.run("3 big calls.")
        check("T18a all 3 big-output tools dispatched",
              len(r18.tool_calls) == 3)
        # Find the joined observation user message
        last_user_msg = next(
            (m for m in reversed(r18.messages) if m["role"] == "user"),
            None,
        )
        check("T18b joined observations exist", last_user_msg is not None)
        # All three OK lines must be present (no silent drop)
        ok_count = last_user_msg["content"].count("[step") if last_user_msg else 0
        check("T18c all three tool observations visible (no silent drop)",
              ok_count == 3, hint=f"got {ok_count} step markers")

        # ---- T19: REGRESSION GUARD (HIGH fix: trace arg redaction) ------
        # By default, TOOL_CALL events publish arg_keys only, NOT values.
        events_captured: List[Dict[str, Any]] = []
        bus19 = EventBus()
        bus19.subscribe(StepType.TOOL_CALL.value,
                        lambda step: events_captured.append(dict(step.payload)))

        secret_args = {"a": 1, "b": 2, "api_key": "sk-SECRET-must-not-leak"}
        loop19 = ReActLoop(
            llm_call=make_scripted_llm([
                json.dumps({"name": "stub_add", "arguments": secret_args}),
                "Done.",
            ]),
            tool_instances={"stub_add": StubAdd()},
            event_bus=bus19,
            enable_mirror_lite=False,
            enable_cot_monitor=False,
            # trace_arguments defaults to False
        )
        await loop19.run("Secret args.")
        check("T19a TOOL_CALL event captured", len(events_captured) >= 1)
        first_payload = events_captured[0] if events_captured else {}
        check("T19b payload omits 'arguments' by default",
              "arguments" not in first_payload,
              hint=str(first_payload))
        check("T19c payload includes arg_keys", "arg_keys" in first_payload)
        check("T19d arg_keys is a list of key names",
              first_payload.get("arg_keys") == sorted(secret_args.keys()))
        # The secret value must NOT appear anywhere in the serialized payload
        serialized = json.dumps(first_payload, default=str)
        check("T19e secret value NOT in serialized payload",
              "sk-SECRET-must-not-leak" not in serialized,
              hint=serialized[:200])

        # ---- T20: trace_arguments=True opts in (debug mode) -------------
        events_v2: List[Dict[str, Any]] = []
        bus20 = EventBus()
        bus20.subscribe(StepType.TOOL_CALL.value,
                        lambda step: events_v2.append(dict(step.payload)))
        loop20 = ReActLoop(
            llm_call=make_scripted_llm([
                json.dumps({"name": "stub_add", "arguments": {"a": 1, "b": 1}}),
                "Done.",
            ]),
            tool_instances={"stub_add": StubAdd()},
            event_bus=bus20,
            enable_mirror_lite=False,
            enable_cot_monitor=False,
            trace_arguments=True,  # explicit opt-in
        )
        await loop20.run("Opt-in debug.")
        check("T20a trace_arguments=True includes 'arguments'",
              "arguments" in events_v2[0] if events_v2 else False,
              hint=str(events_v2[0]) if events_v2 else "no events")

        # ---- Report -----------------------------------------------------
        total = passed + len(failed)
        print(f"\n  Passed: {passed}/{total}")
        if failed:
            for f_ in failed:
                print(f"  {f_}")
            print("=" * 70)
            raise SystemExit(1)
        print(f"  All {total} react smoke tests passed.")
        print("=" * 70)

    asyncio.run(smoke_test())
