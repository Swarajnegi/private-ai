"""
plan.py

JARVIS Agent Layer (Planning): Plan + Step dataclasses for Stage 3.3.2.

Import with:
    from jarvis_core.agent.plan import Plan, Step, StepStatus, PlanStatus, build_plan

LAYER: Brain (Planning)

=============================================================================
THE BIG PICTURE
=============================================================================

Without a Plan data structure:
    -> The agent emits a sequence of tool calls inline during the ReAct loop.
       There's no commitment, no traceability, no way to replan when a step
       fails. The agent can't tell whether step 3 depends on step 1 — every
       turn is "ad-hoc the next tool call from scratch."
    -> No parallelism: even when steps are independent, they execute serially
       because the agent doesn't see the DAG.

With Plan (this module):
    -> Before invoking tools, the agent commits to an ordered Plan: a DAG of
       Step objects with explicit `depends_on` edges. The PlanExecutor (3.3.3)
       reads this DAG, partitions ready-steps into concurrency-safe batches,
       and runs them in parallel where possible.
    -> Failed steps retry up to `max_attempts`; permanent failure flips the
       Plan to FAILED. Replanning (3.3.4 hook) creates a child Plan with
       `parent_plan_id` lineage so the trace stays auditable.
    -> Cycle detection at construction time via Kahn's algorithm — a malformed
       Plan fails loud at plan-time, never mid-execution.

=============================================================================
THE FLOW (Step by Step Execution Order)
=============================================================================

STEP 1: Brain (or build_plan helper) emits a list of step specs:
            steps = [
                {"tool_name": "memory_hybrid_search", "tool_input": {...}, "depends_on": []},
                {"tool_name": "memory_rerank", "tool_input": {...}, "depends_on": ["step_aaa"]},
                ...
            ]
        plan = build_plan(goal="...", step_specs=steps)
        |
        v
STEP 2: Plan.__post_init__ validates every depends_on points to an existing
        step, then runs Kahn's algorithm to detect cycles. Raises
        StepNotFoundError or PlanCycleError loudly on malformed input.
        |
        v
STEP 3: PlanExecutor (3.3.3) loops:
            ready = plan.ready_steps()    # PENDING + all deps SUCCEEDED
            partition into (concurrency_safe, unsafe)
            asyncio.gather(safe); serial loop(unsafe)
            mutate step.status + step.result + step.attempts
        |
        v
STEP 4: After every step batch, plan.update_status() sets Plan.status to
        RUNNING / SUCCEEDED / FAILED based on aggregate step statuses.
        |
        v
STEP 5: On terminal state, the executor exits. If FAILED, replan_from()
        produces a child Plan retaining downstream context.

=============================================================================

Prep for STEAL #5 (Stage 3.4 trace/EventBus): Plan.to_dict() emits a stable
JSON representation that the EventBus can publish without further translation.

Prep for Stage 3.3.4 (Replanning): replan_from(failed_step_id) is a structural
stub that produces a child Plan with parent_plan_id lineage. LLM-driven
re-step-generation lands when 3.4 ReAct is wired.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

from jarvis_core.agent.tool import ToolResult


# =============================================================================
# Part 1: STATUS ENUMS (Step + Plan)
# =============================================================================

class StepStatus(str, Enum):
    """Lifecycle states of a single Step.

    Transitions:
        PENDING  -> RUNNING                 (executor picks it up)
        RUNNING  -> SUCCEEDED               (invoke ok)
        RUNNING  -> PENDING                 (invoke failed, retries remain)
        RUNNING  -> FAILED                  (invoke failed, retries exhausted)
        any      -> SKIPPED                 (upstream failure cascaded, manual skip)

    Terminal states are SUCCEEDED, FAILED, SKIPPED — see `is_terminal`.
    """
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"

    @property
    def is_terminal(self) -> bool:
        """True if the step will not change state without external action."""
        return self in (StepStatus.SUCCEEDED, StepStatus.FAILED, StepStatus.SKIPPED)


class PlanStatus(str, Enum):
    """Lifecycle states of a Plan.

    Transitions:
        READY     -> RUNNING        (executor starts driving steps)
        RUNNING   -> SUCCEEDED      (all steps terminal AND none FAILED)
        RUNNING   -> FAILED         (any step FAILED after retry exhaustion)
        FAILED    -> REPLANNING     (replan_from() invoked; child Plan in flight)
    """
    READY = "ready"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REPLANNING = "replanning"


# =============================================================================
# Part 2: EXCEPTIONS
# =============================================================================

class PlanCycleError(Exception):
    """Raised when Plan construction detects a dependency cycle."""


class StepNotFoundError(Exception):
    """Raised when a `depends_on` entry references a non-existent step_id."""


# =============================================================================
# Part 3: ID + TIMESTAMP HELPERS
# =============================================================================

_IST = timezone(timedelta(hours=5, minutes=30))


def _ist_now_iso() -> str:
    """ISO 8601 timestamp with +05:30 (matches KB convention)."""
    return datetime.now(_IST).isoformat()


def _short_id(prefix: str) -> str:
    """Short-form UUID4 hex (8 chars) prefixed for human readability."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# =============================================================================
# Part 4: STEP (mutable: status/result/attempts flip during execution)
# =============================================================================

@dataclass
class Step:
    """A single tool invocation in a Plan.

    Purpose:
        - Names which tool to invoke and what input to pass
        - Declares dependencies on other steps (DAG edges via step_id)
        - Carries mutable execution state: status, result, attempts

    Fields:
        step_id:       Short unique identifier (auto-generated if not given).
        description:   Natural-language goal of this step (for tracing/LLM context).
        tool_name:     Must match a registered Tool.name (resolved by executor).
        tool_input:    Raw dict passed to safe_invoke; validated against the
                       tool's input_schema there, not at Step construction.
        depends_on:    List of step_ids that must reach SUCCEEDED before this
                       step becomes ready_steps()-eligible.
        status:        Current StepStatus. PENDING at construction.
        result:        Populated after invoke; None until then.
        attempts:      Count of invoke() calls so far.
        max_attempts:  Per-step retry budget. 1 = no retry. Default 1.
    """
    description: str = ""
    tool_name: str = ""
    tool_input: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)
    step_id: str = field(default_factory=lambda: _short_id("step"))
    status: StepStatus = StepStatus.PENDING
    result: Optional[ToolResult] = None
    attempts: int = 0
    max_attempts: int = 1

    def can_retry(self) -> bool:
        """True if the step has failed and at least one retry remains."""
        return self.attempts < self.max_attempts


# =============================================================================
# Part 5: PLAN (DAG of Steps with cycle detection + ready_steps + replan hook)
# =============================================================================

@dataclass
class Plan:
    """A DAG of Steps representing the agent's committed sequence of tool calls.

    Construction validates: every depends_on references an existing step_id,
    and the dependency graph is acyclic (Kahn's algorithm).

    The shape (which steps exist + their edges) is logically immutable after
    construction. Use add_step() to extend BEFORE execution begins; do not
    mutate `steps` directly while the executor is running.

    Step state (status/result/attempts) IS mutable during execution.
    """
    goal: str = ""
    steps: Dict[str, Step] = field(default_factory=dict)
    plan_id: str = field(default_factory=lambda: _short_id("plan"))
    status: PlanStatus = PlanStatus.READY
    parent_plan_id: Optional[str] = None
    created_at: str = field(default_factory=_ist_now_iso)

    def __post_init__(self) -> None:
        if self.steps:
            self._validate_dependencies()
            self._detect_cycle()

    # ---- Validation ------------------------------------------------------

    def _validate_dependencies(self) -> None:
        for s in self.steps.values():
            for dep in s.depends_on:
                if dep not in self.steps:
                    raise StepNotFoundError(
                        f"Step '{s.step_id}' depends on missing step_id '{dep}'"
                    )

    def _detect_cycle(self) -> None:
        """Kahn's topological-sort algorithm: if we can't process every node,
        there's a cycle. O(V+E) where V=steps, E=total dependencies."""
        in_degree = {sid: len(s.depends_on) for sid, s in self.steps.items()}
        queue = [sid for sid, deg in in_degree.items() if deg == 0]
        visited = 0
        while queue:
            sid = queue.pop(0)
            visited += 1
            for s in self.steps.values():
                if sid in s.depends_on:
                    in_degree[s.step_id] -= 1
                    if in_degree[s.step_id] == 0:
                        queue.append(s.step_id)
        if visited != len(self.steps):
            raise PlanCycleError(
                f"Plan '{self.plan_id}' has a dependency cycle "
                f"(reached {visited}/{len(self.steps)} steps)"
            )

    # ---- Query API -------------------------------------------------------

    def ready_steps(self) -> List[Step]:
        """Steps eligible for immediate dispatch: PENDING + all deps SUCCEEDED.

        If any dep is FAILED, the dependent step is NOT returned — it stays
        PENDING indefinitely (the executor treats this as deadlock and exits).
        """
        ready: List[Step] = []
        for s in self.steps.values():
            if s.status != StepStatus.PENDING:
                continue
            if all(self.steps[d].status == StepStatus.SUCCEEDED for d in s.depends_on):
                ready.append(s)
        return ready

    def topological_order(self) -> List[Step]:
        """Return steps in a dependency-respecting order (deps first).

        Determinism: when multiple steps have the same in-degree, order is
        insertion-order of `self.steps`. Useful for printing/debugging.
        """
        order: List[Step] = []
        in_degree = {sid: len(s.depends_on) for sid, s in self.steps.items()}
        queue = [sid for sid in self.steps if in_degree[sid] == 0]
        while queue:
            sid = queue.pop(0)
            order.append(self.steps[sid])
            for s in self.steps.values():
                if sid in s.depends_on:
                    in_degree[s.step_id] -= 1
                    if in_degree[s.step_id] == 0:
                        queue.append(s.step_id)
        return order

    def is_complete(self) -> bool:
        """True if every step has reached a terminal state."""
        return all(s.status.is_terminal for s in self.steps.values())

    def has_failed(self) -> bool:
        """True if any step is FAILED with retries exhausted."""
        return any(
            s.status == StepStatus.FAILED and s.attempts >= s.max_attempts
            for s in self.steps.values()
        )

    # ---- Mutation API ----------------------------------------------------

    def add_step(self, step: Step) -> Step:
        """Add a Step BEFORE execution begins. Re-validates dependencies + cycles.

        Raises ValueError if step_id already exists.
        """
        if step.step_id in self.steps:
            raise ValueError(f"Step '{step.step_id}' already exists in plan '{self.plan_id}'")
        self.steps[step.step_id] = step
        self._validate_dependencies()
        self._detect_cycle()
        return step

    def update_status(self) -> None:
        """Recompute Plan.status from aggregate step state. Called by executor
        after every step transition."""
        if self.has_failed():
            self.status = PlanStatus.FAILED
        elif self.is_complete():
            self.status = PlanStatus.SUCCEEDED
        elif any(s.status == StepStatus.RUNNING for s in self.steps.values()):
            self.status = PlanStatus.RUNNING

    # ---- Replanning hook (3.3.4) -----------------------------------------

    def replan_from(self, failed_step_id: str) -> "Plan":
        """Produce a child Plan retaining the failed step + downstream subgraph.

        Stage 3.3.2 stub: clones the failed step and every transitive descendant
        with status reset to PENDING, attempts reset to 0. parent_plan_id is set
        for lineage. The current Plan flips to REPLANNING.

        At 3.4 ReAct, the LLM will REPLACE this stub: rather than cloning the
        same failed step, it will emit alternative tool sequences targeting
        the same goal. The structural lineage (parent_plan_id) stays the same.

        Raises:
            StepNotFoundError: if failed_step_id is not in self.steps.
        """
        if failed_step_id not in self.steps:
            raise StepNotFoundError(failed_step_id)

        downstream_ids = self._descendants_of(failed_step_id)
        new_steps: Dict[str, Step] = {}
        for sid in downstream_ids:
            old = self.steps[sid]
            new_steps[sid] = Step(
                description=old.description,
                tool_name=old.tool_name,
                tool_input=dict(old.tool_input),
                depends_on=[d for d in old.depends_on if d in downstream_ids],
                step_id=old.step_id,  # preserve id for trace continuity
                status=StepStatus.PENDING,
                attempts=0,
                max_attempts=old.max_attempts,
            )
        self.status = PlanStatus.REPLANNING
        return Plan(
            goal=self.goal,
            steps=new_steps,
            parent_plan_id=self.plan_id,
        )

    def _descendants_of(self, step_id: str) -> List[str]:
        """BFS to return step_id + every transitively dependent step_id."""
        visited: set = set()
        queue = [step_id]
        while queue:
            sid = queue.pop(0)
            if sid in visited:
                continue
            visited.add(sid)
            for s in self.steps.values():
                if sid in s.depends_on and s.step_id not in visited:
                    queue.append(s.step_id)
        return list(visited)

    # ---- Serialization (3.4 EventBus hook) -------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Stable JSON-serializable representation for tracing + persistence."""
        return {
            "plan_id": self.plan_id,
            "goal": self.goal,
            "status": self.status.value,
            "parent_plan_id": self.parent_plan_id,
            "created_at": self.created_at,
            "steps": [
                {
                    "step_id": s.step_id,
                    "description": s.description,
                    "tool_name": s.tool_name,
                    "tool_input": s.tool_input,
                    "depends_on": list(s.depends_on),
                    "status": s.status.value,
                    "attempts": s.attempts,
                    "max_attempts": s.max_attempts,
                    "error": (s.result.error if s.result and s.result.is_error else None),
                }
                for s in self.steps.values()
            ],
        }


# =============================================================================
# Part 6: BUILDER HELPER (turn list of dicts into a validated Plan in one call)
# =============================================================================

def build_plan(goal: str, step_specs: List[Dict[str, Any]]) -> Plan:
    """Convenience builder: convert a list of step-spec dicts into a Plan.

    Each spec is a dict with keys:
        - tool_name (required)
        - tool_input (optional, default {})
        - description (optional, default "")
        - depends_on (optional, default [])
        - max_attempts (optional, default 1)
        - step_id (optional, auto-generated if absent)

    All validation (missing deps, cycles) runs once at Plan construction.
    """
    steps_dict: Dict[str, Step] = {}
    for spec in step_specs:
        s = Step(
            description=spec.get("description", ""),
            tool_name=spec["tool_name"],
            tool_input=dict(spec.get("tool_input", {})),
            depends_on=list(spec.get("depends_on", [])),
            step_id=spec.get("step_id") or _short_id("step"),
            max_attempts=int(spec.get("max_attempts", 1)),
        )
        steps_dict[s.step_id] = s
    return Plan(goal=goal, steps=steps_dict)


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS
# =============================================================================

if __name__ == "__main__":

    print("=" * 70)
    print("  plan.py — Smoke Tests (Stage 3.3.2)")
    print("=" * 70)

    passed = 0
    failed: List[str] = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        global passed
        if cond:
            passed += 1
        else:
            failed.append(f"FAIL: {name}" + (f" ({hint})" if hint else ""))

    # ---- T1: Empty plan ok ----------------------------------------------
    p_empty = Plan(goal="nothing")
    check("T1 empty plan constructs", p_empty.is_complete() and not p_empty.has_failed())

    # ---- T2: Linear chain (a -> b -> c) ---------------------------------
    p_linear = build_plan(
        goal="linear",
        step_specs=[
            {"tool_name": "calculator", "tool_input": {"expression": "1+1"}, "step_id": "a"},
            {"tool_name": "calculator", "tool_input": {"expression": "2+2"}, "step_id": "b", "depends_on": ["a"]},
            {"tool_name": "calculator", "tool_input": {"expression": "3+3"}, "step_id": "c", "depends_on": ["b"]},
        ],
    )
    check("T2 linear: only 'a' ready", [s.step_id for s in p_linear.ready_steps()] == ["a"])
    topo = [s.step_id for s in p_linear.topological_order()]
    check("T2 linear topo a->b->c", topo == ["a", "b", "c"], hint=str(topo))

    # ---- T3: Diamond DAG ------------------------------------------------
    #          a
    #         / \
    #        b   c
    #         \ /
    #          d
    p_diamond = build_plan(
        goal="diamond",
        step_specs=[
            {"tool_name": "calculator", "tool_input": {"expression": "0"}, "step_id": "a"},
            {"tool_name": "calculator", "tool_input": {"expression": "0"}, "step_id": "b", "depends_on": ["a"]},
            {"tool_name": "calculator", "tool_input": {"expression": "0"}, "step_id": "c", "depends_on": ["a"]},
            {"tool_name": "calculator", "tool_input": {"expression": "0"}, "step_id": "d", "depends_on": ["b", "c"]},
        ],
    )
    check("T3 diamond: only 'a' ready", [s.step_id for s in p_diamond.ready_steps()] == ["a"])
    # Simulate a -> SUCCEEDED, then b+c should both be ready (parallel!)
    p_diamond.steps["a"].status = StepStatus.SUCCEEDED
    ready_after_a = sorted(s.step_id for s in p_diamond.ready_steps())
    check("T3 diamond: after 'a' done, b+c ready (parallel)", ready_after_a == ["b", "c"], hint=str(ready_after_a))
    # 'd' should NOT be ready until both b and c succeed
    p_diamond.steps["b"].status = StepStatus.SUCCEEDED
    check("T3 diamond: 'd' waits for 'c'", [s.step_id for s in p_diamond.ready_steps()] == ["c"])
    p_diamond.steps["c"].status = StepStatus.SUCCEEDED
    check("T3 diamond: now 'd' ready", [s.step_id for s in p_diamond.ready_steps()] == ["d"])

    # ---- T4: Cycle detection --------------------------------------------
    try:
        build_plan(
            goal="cycle",
            step_specs=[
                {"tool_name": "calculator", "tool_input": {}, "step_id": "x", "depends_on": ["y"]},
                {"tool_name": "calculator", "tool_input": {}, "step_id": "y", "depends_on": ["x"]},
            ],
        )
        check("T4 cycle detected", False, hint="no error raised")
    except PlanCycleError:
        check("T4 cycle detected", True)
    except Exception as e:
        check("T4 cycle detected", False, hint=f"wrong error: {type(e).__name__}")

    # ---- T5: Self-cycle ------------------------------------------------
    try:
        build_plan(
            goal="self",
            step_specs=[
                {"tool_name": "calculator", "tool_input": {}, "step_id": "loopy", "depends_on": ["loopy"]},
            ],
        )
        check("T5 self-cycle detected", False, hint="no error raised")
    except PlanCycleError:
        check("T5 self-cycle detected", True)

    # ---- T6: Missing dep raises StepNotFoundError ------------------------
    try:
        build_plan(
            goal="missing",
            step_specs=[
                {"tool_name": "calculator", "tool_input": {}, "step_id": "a", "depends_on": ["nope"]},
            ],
        )
        check("T6 missing dep detected", False)
    except StepNotFoundError:
        check("T6 missing dep detected", True)

    # ---- T7: is_complete / has_failed ------------------------------------
    p_terminal = build_plan(
        goal="terminal",
        step_specs=[{"tool_name": "calculator", "tool_input": {}, "step_id": "only"}],
    )
    check("T7a not complete on construction", not p_terminal.is_complete())
    check("T7b not failed on construction", not p_terminal.has_failed())
    p_terminal.steps["only"].status = StepStatus.SUCCEEDED
    p_terminal.update_status()
    check("T7c complete after SUCCEEDED", p_terminal.is_complete() and not p_terminal.has_failed())
    check("T7d plan status SUCCEEDED", p_terminal.status == PlanStatus.SUCCEEDED)

    # ---- T8: Failure with retries exhausted --------------------------------
    p_fail = build_plan(
        goal="fail",
        step_specs=[{"tool_name": "calculator", "tool_input": {}, "step_id": "x", "max_attempts": 2}],
    )
    p_fail.steps["x"].attempts = 2
    p_fail.steps["x"].status = StepStatus.FAILED
    p_fail.update_status()
    check("T8 retries exhausted -> Plan FAILED",
          p_fail.has_failed() and p_fail.status == PlanStatus.FAILED)

    # ---- T9: Step.can_retry ----------------------------------------------
    p_can = build_plan(
        goal="can",
        step_specs=[{"tool_name": "calculator", "tool_input": {}, "step_id": "y", "max_attempts": 3}],
    )
    s9 = p_can.steps["y"]
    s9.attempts = 1
    check("T9a can_retry when attempts<max", s9.can_retry())
    s9.attempts = 3
    check("T9b cannot retry when exhausted", not s9.can_retry())

    # ---- T10: add_step incremental -------------------------------------
    p_inc = Plan(goal="incremental")
    p_inc.add_step(Step(step_id="s1", tool_name="calculator", tool_input={"expression": "1"}))
    p_inc.add_step(Step(step_id="s2", tool_name="calculator", tool_input={"expression": "2"}, depends_on=["s1"]))
    check("T10a incremental construction works", len(p_inc.steps) == 2)
    try:
        p_inc.add_step(Step(step_id="s1", tool_name="calculator", tool_input={}))
        check("T10b duplicate step_id rejected", False)
    except ValueError:
        check("T10b duplicate step_id rejected", True)

    # ---- T11: replan_from clones failed + downstream --------------------
    p_orig = build_plan(
        goal="replan",
        step_specs=[
            {"tool_name": "calculator", "tool_input": {}, "step_id": "p1"},
            {"tool_name": "calculator", "tool_input": {}, "step_id": "p2", "depends_on": ["p1"]},
            {"tool_name": "calculator", "tool_input": {}, "step_id": "p3", "depends_on": ["p2"]},
        ],
    )
    p_orig.steps["p1"].status = StepStatus.SUCCEEDED
    p_orig.steps["p2"].status = StepStatus.FAILED
    p_orig.steps["p2"].attempts = 1
    child = p_orig.replan_from("p2")
    check("T11a child has parent_plan_id", child.parent_plan_id == p_orig.plan_id)
    child_ids = sorted(child.steps.keys())
    check("T11b child contains failed step + downstream (p2, p3)",
          child_ids == ["p2", "p3"], hint=str(child_ids))
    check("T11c child steps reset to PENDING",
          all(s.status == StepStatus.PENDING for s in child.steps.values()))
    check("T11d child attempts reset",
          all(s.attempts == 0 for s in child.steps.values()))
    check("T11e original flips to REPLANNING", p_orig.status == PlanStatus.REPLANNING)

    # ---- T12: replan_from on bad id -------------------------------------
    try:
        p_orig.replan_from("nope")
        check("T12 replan_from missing -> error", False)
    except StepNotFoundError:
        check("T12 replan_from missing -> error", True)

    # ---- T13: to_dict serialization ------------------------------------
    d = p_orig.to_dict()
    check("T13a to_dict has plan_id", d["plan_id"] == p_orig.plan_id)
    check("T13b to_dict has steps list", isinstance(d["steps"], list) and len(d["steps"]) == 3)
    check("T13c to_dict status is string", isinstance(d["status"], str))

    # ---- T14: Status terminal property ---------------------------------
    check("T14a SUCCEEDED is terminal", StepStatus.SUCCEEDED.is_terminal)
    check("T14b FAILED is terminal", StepStatus.FAILED.is_terminal)
    check("T14c PENDING not terminal", not StepStatus.PENDING.is_terminal)
    check("T14d RUNNING not terminal", not StepStatus.RUNNING.is_terminal)

    # ---- Report ---------------------------------------------------------
    total = passed + len(failed)
    print(f"\n  Passed: {passed}/{total}")
    if failed:
        for f_ in failed:
            print(f"  {f_}")
        print("=" * 70)
        raise SystemExit(1)
    print(f"  All {total} plan smoke tests passed.")
    print("=" * 70)
