"""
executor.py

JARVIS Agent Layer (Planning): PlanExecutor for Stage 3.3.3.

Import with:
    from jarvis_core.agent.executor import PlanExecutor

LAYER: Brain (Planning)

=============================================================================
THE BIG PICTURE
=============================================================================

Without a PlanExecutor:
    -> Plans from 3.3.2 are inert data structures. Nothing drives the DAG
       forward; nothing partitions ready_steps into concurrency-safe batches;
       nothing handles retries on transient tool failures.

With PlanExecutor (this module):
    -> Loops: ready_steps() -> partition (safe vs unsafe) -> dispatch ->
       mutate Step state -> recompute Plan.status -> repeat until terminal.
    -> Concurrency-safe steps run via asyncio.gather (prep for STEAL #8 at 3.4).
    -> Stateful/unsafe steps run serially.
    -> Failed steps with retries remaining are bounced back to PENDING for
       the next iteration; once max_attempts is hit, they go FAILED and
       cascade-block all downstream steps via the DAG.
    -> Lifecycle hooks from 3.2.3 fire: setup() on every used tool at start,
       teardown() on every used tool at end (in finally — even if execution
       throws). Tool hook failures are swallowed, never break the executor.

=============================================================================
THE FLOW (Step by Step Execution Order)
=============================================================================

STEP 1: Caller constructs executor with a dict {tool_name -> tool_instance}.
        The dispatcher pre-wires DI: memory tools get JarvisMemoryStore,
        finance tools get strategy path, etc.
        |
        v
STEP 2: caller calls await executor.execute(plan).
        Plan.status -> RUNNING.
        |
        v
STEP 3: For each tool in plan.steps, await tool.setup() (3.2.3 hook).
        |
        v
STEP 4: LOOP (bounded by max_iterations):
            ready = plan.ready_steps()
            if not ready and not is_complete(): deadlock; break
            partition (safe vs unsafe)
            await asyncio.gather(*[_execute_step(s) for s in safe])
            for s in unsafe: await _execute_step(s)
            plan.update_status()
            if plan terminal: break
        |
        v
STEP 5: finally: for each tool, await tool.teardown() (3.2.3 hook).
        Return the mutated Plan.

=============================================================================

Prep for Stage 3.4 (ReAct): execute() returns the terminated Plan; the
ReAct loop wraps execute() and decides — based on plan.status — whether to
emit an observation back to the LLM, request a replan, or surface failure.

Prep for STEAL #5 (EventBus): the optional on_step_complete callback is the
hook point where EventBus.publish('step.completed', step) lands.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Dict, List, Optional

from jarvis_core.agent.plan import (
    Plan,
    PlanStatus,
    Step,
    StepStatus,
)
from jarvis_core.agent.tool import Tool, ToolResult, safe_invoke


# =============================================================================
# Part 1: TYPES
# =============================================================================

# Optional observer fired after every step transition. Receives (step, plan).
# Returns None or an awaitable (executor awaits if awaitable).
StepObserver = Callable[[Step, Plan], Optional[Awaitable[None]]]


# =============================================================================
# Part 2: EXECUTOR
# =============================================================================

class PlanExecutor:
    """Drives a Plan to terminal state by dispatching Steps through Tools.

    Purpose:
        - Resolve step.tool_name -> Tool instance via injected tool_instances dict
        - Partition ready_steps into concurrency-safe (gather) vs unsafe (serial)
        - Mutate Step state: PENDING -> RUNNING -> SUCCEEDED / FAILED / (back to PENDING for retry)
        - Fire Tool lifecycle hooks (setup at start, teardown at end)
        - Stop on terminal Plan state, deadlock, or max_iterations safety cap

    How it works:
        - tool_instances is supplied by the dispatcher (NOT looked up via
          Tool.get_or_raise) because real tools have DI requirements that
          the registry doesn't know about (memory store, llm_call callable,
          finance strategy path, etc).
        - safe_invoke is the single dispatcher-facing entry point — it runs
          Pydantic validation, fires the start/end lifecycle hooks (3.2.3),
          and converts exceptions to ToolResult.
        - on_step_complete is the EventBus seam (STEAL #5 lands at 3.4).
    """

    def __init__(
        self,
        tool_instances: Dict[str, Tool],
        max_iterations: int = 100,
        on_step_complete: Optional[StepObserver] = None,
    ) -> None:
        self._tools = tool_instances
        self._max_iterations = max_iterations
        self._on_step_complete = on_step_complete

    # ---- Public API ------------------------------------------------------

    async def execute(self, plan: Plan) -> Plan:
        """Drive the plan to terminal state. Returns the (mutated) plan.

        Safety:
            - max_iterations bounds the loop; default 100 is generous for
              even diamond-heavy plans. Increase for deeply chained plans.
            - Tool lifecycle setup/teardown calls are wrapped in try/except —
              a broken hook NEVER prevents tool dispatch or executor return.
        """
        plan.status = PlanStatus.RUNNING

        used_names = {s.tool_name for s in plan.steps.values()}
        await self._setup_tools(used_names)

        try:
            for _iteration in range(self._max_iterations):
                if plan.is_complete() or plan.has_failed():
                    break

                ready = plan.ready_steps()
                if not ready:
                    # No ready steps but plan not terminal -> upstream failure
                    # has cascaded. Mark remaining PENDING as SKIPPED and exit.
                    self._skip_orphaned(plan)
                    break

                safe_steps = [s for s in ready if self._is_safe(s)]
                unsafe_steps = [s for s in ready if not self._is_safe(s)]

                # Concurrency-safe: dispatch in parallel
                if safe_steps:
                    await asyncio.gather(
                        *(self._execute_step(s, plan) for s in safe_steps)
                    )

                # Unsafe: serial dispatch (each may mutate shared state)
                for s in unsafe_steps:
                    await self._execute_step(s, plan)

                plan.update_status()

            # After-loop cascade sweep: if a step FAILED with retries
            # exhausted, downstream PENDING steps starve forever. Mark them
            # SKIPPED here so the plan reaches a fully terminal state.
            if plan.has_failed():
                self._skip_orphaned(plan)
        finally:
            await self._teardown_tools(used_names)
            plan.update_status()

        return plan

    # ---- Internals -------------------------------------------------------

    def _is_safe(self, step: Step) -> bool:
        """A step is concurrency-safe only if its tool is registered AND
        the tool's is_concurrency_safe property is True. Missing tools are
        unsafe (the step will fail in _execute_step, but it does so serially)."""
        tool = self._tools.get(step.tool_name)
        if tool is None:
            return False
        return tool.is_concurrency_safe

    async def _execute_step(self, step: Step, plan: Plan) -> None:
        """Run a single step. Mutates step.status, step.result, step.attempts.

        Failure handling:
            - If invoke fails AND step.attempts < step.max_attempts: status
              bounces back to PENDING so the next iteration of execute()
              picks it up.
            - If invoke fails AND step.attempts >= step.max_attempts: status
              flips to FAILED. Downstream steps will starve via the DAG and
              be SKIPPED in _skip_orphaned().
        """
        tool = self._tools.get(step.tool_name)
        if tool is None:
            step.status = StepStatus.FAILED
            step.result = ToolResult(
                error=f"Tool '{step.tool_name}' not in executor's instance registry"
            )
            step.attempts = step.max_attempts  # block further retries
            await self._fire_observer(step, plan)
            return

        step.status = StepStatus.RUNNING
        step.attempts += 1
        result = await safe_invoke(tool, step.tool_input)
        step.result = result

        if result.is_success:
            step.status = StepStatus.SUCCEEDED
        elif step.attempts < step.max_attempts:
            # Retry: next iteration will pick up this step again
            step.status = StepStatus.PENDING
        else:
            step.status = StepStatus.FAILED

        await self._fire_observer(step, plan)

    async def _setup_tools(self, names: set) -> None:
        for name in names:
            tool = self._tools.get(name)
            if tool is None:
                continue
            try:
                await tool.setup()
            except Exception:
                pass  # broken hook must NEVER prevent execution

    async def _teardown_tools(self, names: set) -> None:
        for name in names:
            tool = self._tools.get(name)
            if tool is None:
                continue
            try:
                await tool.teardown()
            except Exception:
                pass

    def _skip_orphaned(self, plan: Plan) -> None:
        """Mark all remaining PENDING steps as SKIPPED. Called when no steps
        are ready but the plan is not complete — i.e., upstream FAILED.

        This is the cascade behavior: a FAILED step poisons all downstream
        children. They never run, they're never PENDING forever — they're
        explicitly SKIPPED with a synthetic result.
        """
        for s in plan.steps.values():
            if s.status == StepStatus.PENDING:
                s.status = StepStatus.SKIPPED
                s.result = ToolResult(
                    error="Skipped: an upstream dependency failed"
                )

    async def _fire_observer(self, step: Step, plan: Plan) -> None:
        if self._on_step_complete is None:
            return
        try:
            res = self._on_step_complete(step, plan)
            if asyncio.iscoroutine(res):
                await res
        except Exception:
            pass  # observer must NEVER break execution


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS (stub tools, no real Tool registry pollution)
# =============================================================================

if __name__ == "__main__":
    from jarvis_core.agent.plan import build_plan
    from jarvis_core.agent.tool import Tool, ToolInput, ToolResult
    from pydantic import Field

    print("=" * 70)
    print("  executor.py — Smoke Tests (Stage 3.3.3)")
    print("=" * 70)

    passed = 0
    failed: List[str] = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        global passed
        if cond:
            passed += 1
        else:
            failed.append(f"FAIL: {name}" + (f" ({hint})" if hint else ""))

    # -- Stub tools (NOT registered to avoid leaking into the real registry) --

    class _EchoIn(ToolInput):
        value: int = Field(default=0)

    class EchoSafeTool(Tool):
        name = "echo_safe"
        description = "Concurrency-safe stub that doubles value."
        input_schema = _EchoIn

        @property
        def is_concurrency_safe(self) -> bool:
            return True

        async def invoke(self, tool_input: _EchoIn) -> ToolResult:
            return ToolResult(output=tool_input.value * 2)

    class EchoUnsafeTool(Tool):
        name = "echo_unsafe"
        description = "Stateful stub that increments a shared counter."
        input_schema = _EchoIn
        counter = 0  # class-level mutable state on purpose

        @property
        def is_concurrency_safe(self) -> bool:
            return False

        async def invoke(self, tool_input: _EchoIn) -> ToolResult:
            EchoUnsafeTool.counter += 1
            return ToolResult(output=EchoUnsafeTool.counter)

    class _BoomIn(ToolInput):
        pass

    class BoomTool(Tool):
        name = "boom"
        description = "Always-fails stub for testing retry+cascade."
        input_schema = _BoomIn

        @property
        def is_concurrency_safe(self) -> bool:
            return True

        async def invoke(self, tool_input: _BoomIn) -> ToolResult:
            return ToolResult(error="boom: intentional failure")

    class FlakyTool(Tool):
        """Fails N times then succeeds (per-instance counter)."""
        name = "flaky"
        description = "Fails fail_n times then returns ok."
        input_schema = _BoomIn

        def __init__(self, fail_n: int) -> None:
            self._remaining = fail_n

        @property
        def is_concurrency_safe(self) -> bool:
            return True

        async def invoke(self, tool_input: _BoomIn) -> ToolResult:
            if self._remaining > 0:
                self._remaining -= 1
                return ToolResult(error=f"flaky: {self._remaining} more failures")
            return ToolResult(output="flaky: now passing")

    class LifecycleProbe(Tool):
        """Records hook firing for one-instance scope verification."""
        name = "lifecycle_probe"
        description = "Records setup/teardown firing into a class list."
        input_schema = _EchoIn
        events: List[str] = []

        @property
        def is_concurrency_safe(self) -> bool:
            return True

        async def setup(self) -> None:
            LifecycleProbe.events.append("setup")

        async def teardown(self) -> None:
            LifecycleProbe.events.append("teardown")

        async def invoke(self, tool_input: _EchoIn) -> ToolResult:
            LifecycleProbe.events.append(f"invoke({tool_input.value})")
            return ToolResult(output=tool_input.value)

    async def smoke_test() -> None:
        # -- T1: Empty plan -> SUCCEEDED ----------------------------------
        empty_plan = Plan(goal="nothing")
        ex = PlanExecutor(tool_instances={})
        result_plan = await ex.execute(empty_plan)
        check("T1 empty plan -> SUCCEEDED",
              result_plan.status == PlanStatus.SUCCEEDED)

        # -- T2: Linear chain succeeds in order ---------------------------
        order: List[str] = []
        async def observer(step: Step, plan: Plan) -> None:
            if step.status == StepStatus.SUCCEEDED:
                order.append(step.step_id)
        plan2 = build_plan(
            goal="linear",
            step_specs=[
                {"tool_name": "echo_safe", "tool_input": {"value": 1}, "step_id": "a"},
                {"tool_name": "echo_safe", "tool_input": {"value": 2}, "step_id": "b", "depends_on": ["a"]},
                {"tool_name": "echo_safe", "tool_input": {"value": 3}, "step_id": "c", "depends_on": ["b"]},
            ],
        )
        ex2 = PlanExecutor(
            tool_instances={"echo_safe": EchoSafeTool()},
            on_step_complete=observer,
        )
        p2 = await ex2.execute(plan2)
        check("T2a all steps SUCCEEDED",
              all(s.status == StepStatus.SUCCEEDED for s in p2.steps.values()))
        check("T2b execution order respected deps", order == ["a", "b", "c"], hint=str(order))
        check("T2c plan status SUCCEEDED", p2.status == PlanStatus.SUCCEEDED)
        check("T2d step results captured",
              all(s.result is not None and s.result.is_success for s in p2.steps.values()))

        # -- T3: Diamond DAG — b and c dispatched concurrently ------------
        plan3 = build_plan(
            goal="diamond",
            step_specs=[
                {"tool_name": "echo_safe", "tool_input": {"value": 10}, "step_id": "a"},
                {"tool_name": "echo_safe", "tool_input": {"value": 20}, "step_id": "b", "depends_on": ["a"]},
                {"tool_name": "echo_safe", "tool_input": {"value": 30}, "step_id": "c", "depends_on": ["a"]},
                {"tool_name": "echo_safe", "tool_input": {"value": 40}, "step_id": "d", "depends_on": ["b", "c"]},
            ],
        )
        ex3 = PlanExecutor(tool_instances={"echo_safe": EchoSafeTool()})
        p3 = await ex3.execute(plan3)
        check("T3 diamond all SUCCEEDED",
              all(s.status == StepStatus.SUCCEEDED for s in p3.steps.values()))
        check("T3 plan SUCCEEDED", p3.status == PlanStatus.SUCCEEDED)

        # -- T4: Always-fails tool exhausts retries -----------------------
        plan4 = build_plan(
            goal="fail-retries",
            step_specs=[
                {"tool_name": "boom", "tool_input": {}, "step_id": "k", "max_attempts": 3},
            ],
        )
        ex4 = PlanExecutor(tool_instances={"boom": BoomTool()})
        p4 = await ex4.execute(plan4)
        check("T4a step FAILED after retries", p4.steps["k"].status == StepStatus.FAILED)
        check("T4b attempts == max_attempts (3)", p4.steps["k"].attempts == 3)
        check("T4c plan status FAILED", p4.status == PlanStatus.FAILED)

        # -- T5: Flaky tool succeeds within retry budget ------------------
        plan5 = build_plan(
            goal="flaky-recovery",
            step_specs=[
                {"tool_name": "flaky", "tool_input": {}, "step_id": "f", "max_attempts": 4},
            ],
        )
        ex5 = PlanExecutor(tool_instances={"flaky": FlakyTool(fail_n=2)})
        p5 = await ex5.execute(plan5)
        check("T5a flaky step SUCCEEDED via retry",
              p5.steps["f"].status == StepStatus.SUCCEEDED)
        check("T5b attempts == 3 (2 fails + 1 success)", p5.steps["f"].attempts == 3)
        check("T5c plan status SUCCEEDED", p5.status == PlanStatus.SUCCEEDED)

        # -- T6: Upstream failure cascades downstream as SKIPPED -----------
        plan6 = build_plan(
            goal="cascade",
            step_specs=[
                {"tool_name": "boom", "tool_input": {}, "step_id": "bad", "max_attempts": 1},
                {"tool_name": "echo_safe", "tool_input": {"value": 1}, "step_id": "downstream", "depends_on": ["bad"]},
                {"tool_name": "echo_safe", "tool_input": {"value": 2}, "step_id": "further", "depends_on": ["downstream"]},
            ],
        )
        ex6 = PlanExecutor(tool_instances={"boom": BoomTool(), "echo_safe": EchoSafeTool()})
        p6 = await ex6.execute(plan6)
        check("T6a bad step FAILED", p6.steps["bad"].status == StepStatus.FAILED)
        check("T6b downstream SKIPPED", p6.steps["downstream"].status == StepStatus.SKIPPED)
        check("T6c further SKIPPED", p6.steps["further"].status == StepStatus.SKIPPED)
        check("T6d plan FAILED", p6.status == PlanStatus.FAILED)

        # -- T7: Missing tool surfaces as step FAILED ----------------------
        plan7 = build_plan(
            goal="missing-tool",
            step_specs=[
                {"tool_name": "ghost", "tool_input": {}, "step_id": "g"},
            ],
        )
        ex7 = PlanExecutor(tool_instances={})  # no 'ghost' tool
        p7 = await ex7.execute(plan7)
        check("T7a missing tool -> step FAILED", p7.steps["g"].status == StepStatus.FAILED)
        check("T7b error message mentions registry",
              "not in executor's instance registry" in (p7.steps["g"].result.error or ""))

        # -- T8: Unsafe tool serializes (counter strictly increasing) -----
        EchoUnsafeTool.counter = 0  # reset class state
        plan8 = build_plan(
            goal="unsafe",
            step_specs=[
                {"tool_name": "echo_unsafe", "tool_input": {}, "step_id": f"u{i}"}
                for i in range(5)
            ],
        )
        ex8 = PlanExecutor(tool_instances={"echo_unsafe": EchoUnsafeTool()})
        p8 = await ex8.execute(plan8)
        results = [p8.steps[f"u{i}"].result.output for i in range(5)]
        check("T8a all unsafe steps succeeded",
              all(p8.steps[f"u{i}"].status == StepStatus.SUCCEEDED for i in range(5)))
        check("T8b unsafe results all distinct (serialized counter)",
              len(set(results)) == 5, hint=str(results))

        # -- T9: Tool lifecycle setup/teardown fired ----------------------
        LifecycleProbe.events = []  # reset
        plan9 = build_plan(
            goal="lifecycle",
            step_specs=[
                {"tool_name": "lifecycle_probe", "tool_input": {"value": 7}, "step_id": "lp1"},
                {"tool_name": "lifecycle_probe", "tool_input": {"value": 8}, "step_id": "lp2"},
            ],
        )
        ex9 = PlanExecutor(tool_instances={"lifecycle_probe": LifecycleProbe()})
        p9 = await ex9.execute(plan9)
        ev = LifecycleProbe.events
        # setup fires once at start, teardown fires once at end, with N invokes between
        check("T9a setup fired exactly once",
              ev.count("setup") == 1, hint=str(ev))
        check("T9b teardown fired exactly once",
              ev.count("teardown") == 1, hint=str(ev))
        check("T9c teardown is last event", ev[-1] == "teardown", hint=str(ev))
        check("T9d setup is first event", ev[0] == "setup", hint=str(ev))

        # -- T10: replan_from produces executable child plan ---------------
        plan10 = build_plan(
            goal="replan-flow",
            step_specs=[
                {"tool_name": "echo_safe", "tool_input": {"value": 1}, "step_id": "first"},
                {"tool_name": "boom", "tool_input": {}, "step_id": "fail_here", "depends_on": ["first"], "max_attempts": 1},
                {"tool_name": "echo_safe", "tool_input": {"value": 2}, "step_id": "after", "depends_on": ["fail_here"]},
            ],
        )
        ex10 = PlanExecutor(tool_instances={"echo_safe": EchoSafeTool(), "boom": BoomTool()})
        p10 = await ex10.execute(plan10)
        check("T10a first succeeded", p10.steps["first"].status == StepStatus.SUCCEEDED)
        check("T10b fail_here FAILED", p10.steps["fail_here"].status == StepStatus.FAILED)
        check("T10c after SKIPPED", p10.steps["after"].status == StepStatus.SKIPPED)
        # Now spawn child plan that swaps the failing tool for a working one
        child = p10.replan_from("fail_here")
        check("T10d child plan has fail_here + after", set(child.steps.keys()) == {"fail_here", "after"})
        # Rewire fail_here to use echo_safe instead of boom (mimicking what LLM-driven replanning will do)
        child.steps["fail_here"].tool_name = "echo_safe"
        child.steps["fail_here"].tool_input = {"value": 99}
        ex_child = PlanExecutor(tool_instances={"echo_safe": EchoSafeTool()})
        p_child = await ex_child.execute(child)
        check("T10e child plan SUCCEEDED via replan",
              p_child.status == PlanStatus.SUCCEEDED)

        # -- T11: max_iterations safety cap -------------------------------
        # Construct a plan that would loop forever without the cap: an
        # always-failing step with max_attempts higher than max_iterations.
        plan11 = build_plan(
            goal="iteration-cap",
            step_specs=[
                {"tool_name": "boom", "tool_input": {}, "step_id": "loopy", "max_attempts": 999},
            ],
        )
        ex11 = PlanExecutor(tool_instances={"boom": BoomTool()}, max_iterations=5)
        p11 = await ex11.execute(plan11)
        # After 5 iterations, the step is still PENDING (attempts < max_attempts)
        # but the executor exits. Plan status is RUNNING (not yet terminal).
        check("T11a iteration cap enforced (attempts <= 5)",
              p11.steps["loopy"].attempts <= 5, hint=str(p11.steps["loopy"].attempts))

        # -- T12: Observer is called for every transition -----------------
        seen: List[str] = []
        async def obs2(step: Step, plan: Plan) -> None:
            seen.append(f"{step.step_id}:{step.status.value}")
        plan12 = build_plan(
            goal="observer",
            step_specs=[
                {"tool_name": "echo_safe", "tool_input": {"value": 1}, "step_id": "o1"},
                {"tool_name": "echo_safe", "tool_input": {"value": 2}, "step_id": "o2", "depends_on": ["o1"]},
            ],
        )
        ex12 = PlanExecutor(tool_instances={"echo_safe": EchoSafeTool()}, on_step_complete=obs2)
        await ex12.execute(plan12)
        check("T12 observer fired for both steps",
              "o1:succeeded" in seen and "o2:succeeded" in seen, hint=str(seen))

        # -- T13: Broken observer doesn't crash executor ------------------
        def bad_obs(step: Step, plan: Plan) -> None:
            raise RuntimeError("observer on fire")
        plan13 = build_plan(
            goal="bad-observer",
            step_specs=[{"tool_name": "echo_safe", "tool_input": {"value": 5}, "step_id": "x"}],
        )
        ex13 = PlanExecutor(tool_instances={"echo_safe": EchoSafeTool()}, on_step_complete=bad_obs)
        p13 = await ex13.execute(plan13)
        check("T13 broken observer swallowed -> plan SUCCEEDED",
              p13.status == PlanStatus.SUCCEEDED)

        # -- T14: Broken setup hook doesn't crash executor ----------------
        class BadSetupTool(Tool):
            name = "bad_setup"
            description = "Tool whose setup raises."
            input_schema = _EchoIn

            @property
            def is_concurrency_safe(self) -> bool:
                return True

            async def setup(self) -> None:
                raise RuntimeError("setup explodes")

            async def invoke(self, tool_input: _EchoIn) -> ToolResult:
                return ToolResult(output=tool_input.value)

        plan14 = build_plan(
            goal="bad-setup",
            step_specs=[{"tool_name": "bad_setup", "tool_input": {"value": 11}, "step_id": "s"}],
        )
        ex14 = PlanExecutor(tool_instances={"bad_setup": BadSetupTool()})
        p14 = await ex14.execute(plan14)
        check("T14 broken setup swallowed -> step SUCCEEDED",
              p14.steps["s"].status == StepStatus.SUCCEEDED)

        # -- Report -------------------------------------------------------
        total = passed + len(failed)
        print(f"\n  Passed: {passed}/{total}")
        if failed:
            for f_ in failed:
                print(f"  {f_}")
            print("=" * 70)
            raise SystemExit(1)
        print(f"  All {total} executor smoke tests passed.")
        print("=" * 70)

    asyncio.run(smoke_test())
