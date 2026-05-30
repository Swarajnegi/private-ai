"""
trace.py

JARVIS Agent Layer (Trace): EventBus pub/sub + TraceStep dataclass for Stage 3.4.2.

Import with:
    from jarvis_core.agent.trace import EventBus, TraceStep, StepType, SubscriptionHandle

LAYER: Agent (Trace)

=============================================================================
THE BIG PICTURE
=============================================================================

Without an EventBus:
    -> Every component that wants to observe the agent (loggers, metrics
       collectors, UI streams, the trace persister) needs to be hard-coded
       into the ReAct loop. The loop ends up tangled with cross-cutting
       concerns it shouldn't know about, and adding a new observer means
       editing executor.py / react.py — risky and viral.
    -> Trace records become opportunistic strings buried in print() calls.
       There's no structured stream a UI can subscribe to, no JSON dump
       a replay tool can consume.

With an EventBus + TraceStep (this module — STEAL #5 from OpenJarvis):
    -> Every meaningful event (reason, tool_call, tool_result, observation,
       replan, error, plan_created/completed/failed, reflection) is emitted
       as an immutable TraceStep with a stable to_dict() shape.
    -> Observers subscribe by event_name. Sync callbacks run inline; async
       callbacks are awaited. A faulty observer cannot kill the loop —
       exceptions are caught and printed to stderr.
    -> Snapshotting subscribers before fan-out means an observer that
       unsubscribes mid-publish (common pattern: "one-shot" listeners)
       does not corrupt the iteration.

=============================================================================
THE FLOW (Step by Step Execution Order)
=============================================================================

STEP 1: Component constructs the bus once and shares it across the agent:
            bus = EventBus()
        |
        v
STEP 2: Observers subscribe to named events; each gets a handle they can
        later use to unsubscribe:
            h1 = bus.subscribe("tool.invoke.end", logger_cb)
            h2 = bus.subscribe("tool.invoke.end", metrics_cb)
        |
        v
STEP 3: The producer (ReAct loop, PlanExecutor, etc.) builds a TraceStep
        and calls publish; sync callbacks fire inline, async are awaited.
        Exceptions in any single subscriber are swallowed (with traceback
        printed to stderr) so siblings still run.
            step = TraceStep(StepType.TOOL_RESULT, {"tool": "calc", ...})
            await bus.publish("tool.invoke.end", step)
        |
        v
STEP 4: Observers process the TraceStep — persist via to_dict(), aggregate
        metrics, stream to a UI, etc. Frozen dataclass guarantees the
        record they hold is exactly what was published.
        |
        v
STEP 5: When an observer is done (UI closed, run finished), it calls
        bus.unsubscribe(handle) — idempotent and concurrent-publish-safe.

=============================================================================

Prep for Stage 3.4.3 (ReAct wire-in): the EventBus instance is created by
the loop owner and passed (not singleton'd) to every component that emits.
Prep for Stage 3.4.4 (trace persister): a subscriber on the catch-all
events flushes step.to_dict() to a JSONL file for post-mortem replay.
"""

from __future__ import annotations

import asyncio
import inspect
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from types import MappingProxyType
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional, Union


# =============================================================================
# Part 1: ID + TIMESTAMP HELPERS
# =============================================================================

_IST = timezone(timedelta(hours=5, minutes=30))


def _ist_now_iso() -> str:
    """ISO 8601 timestamp with +05:30 (matches KB convention)."""
    return datetime.now(_IST).isoformat()


def _short_trace_id() -> str:
    """Short UUID4 hex (8 chars) prefixed for human readability."""
    return f"trace_{uuid.uuid4().hex[:8]}"


# =============================================================================
# Part 2: STEP TYPE ENUM
# =============================================================================

class StepType(str, Enum):
    """Categories of events the agent emits during a run.

    REASONING / TOOL_CALL / TOOL_RESULT / OBSERVATION are the canonical
    ReAct quartet. REPLAN / ERROR / REFLECTION cover failure-driven paths.
    PLAN_* lifecycle events bracket a full Plan's execution.
    """
    REASONING = "reasoning"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    OBSERVATION = "observation"
    REPLAN = "replan"
    ERROR = "error"
    PLAN_CREATED = "plan_created"
    PLAN_COMPLETED = "plan_completed"
    PLAN_FAILED = "plan_failed"
    REFLECTION = "reflection"


# =============================================================================
# Part 3: TRACE STEP (immutable event record)
# =============================================================================

@dataclass(frozen=True)
class TraceStep:
    """A single observable event in an agent run.

    Fields:
        step_type:    StepType discriminator for routing/filtering.
        payload:      Free-form Mapping carrying the event-specific body.
                      Wrapped in MappingProxyType at construction so the
                      top-level keys cannot be added/removed/changed after
                      publish. Caller-side dicts passed in are SHALLOW-copied
                      so subsequent mutation of the caller's dict does not
                      leak into the trace.
        step_id:      Short unique id, auto-generated.
        parent_id:    Optional id of the step that produced this one
                      (e.g., a TOOL_RESULT carries the TOOL_CALL's step_id).
        timestamp:    ISO 8601 IST timestamp at construction.
        duration_ms:  Optional millisecond timing for invoke-style events.

    Note on deep immutability: nested mutable values inside payload (lists,
    dicts) are NOT deep-copied. Producers should treat payload values as
    structural-only (strings, numbers, tuples) where possible.
    """
    step_type: StepType
    payload: Mapping[str, Any] = field(default_factory=dict)
    step_id: str = field(default_factory=_short_trace_id)
    parent_id: Optional[str] = None
    timestamp: str = field(default_factory=_ist_now_iso)
    duration_ms: Optional[float] = None

    def __post_init__(self) -> None:
        # Shallow-copy + freeze the payload so post-publish mutation of the
        # caller's source dict doesn't bleed into the trace, and so that no
        # code downstream can accidentally do `step.payload['k'] = v`.
        if not isinstance(self.payload, MappingProxyType):
            object.__setattr__(
                self, "payload", MappingProxyType(dict(self.payload))
            )

    def to_dict(self) -> Dict[str, Any]:
        """Stable JSON-serializable representation for persistence/streams."""
        return {
            "step_id": self.step_id,
            "parent_id": self.parent_id,
            "step_type": self.step_type.value,
            "timestamp": self.timestamp,
            "payload": dict(self.payload),
            "duration_ms": self.duration_ms,
        }


# =============================================================================
# Part 4: SUBSCRIPTION HANDLE (opaque token for unsubscribe)
# =============================================================================

@dataclass(frozen=True)
class SubscriptionHandle:
    """Returned by EventBus.subscribe; required to later unsubscribe."""
    handle_id: int
    event_name: str


# =============================================================================
# Part 5: EVENT BUS (the pub/sub core)
# =============================================================================

# A subscriber callback returns either None (sync) or an Awaitable[None] (async).
SubscriberCallback = Callable[[TraceStep], Union[None, Awaitable[None]]]


class EventBus:
    """Async-friendly pub/sub for TraceStep events.

    Storage:
        _subs: Dict[event_name, Dict[handle_id, callback]]

    Concurrency:
        publish() snapshots the per-event subscriber dict before iteration so
        an observer that unsubscribes (or subscribes) during dispatch cannot
        corrupt the in-flight fan-out.

    Fault isolation:
        A single subscriber raising does NOT prevent the rest from firing.
        The traceback is printed to stderr so the failure is visible without
        crashing the agent.
    """

    def __init__(self) -> None:
        self._subs: Dict[str, Dict[int, SubscriberCallback]] = {}
        self._next_handle_id: int = 0

    def subscribe(
        self, event_name: str, callback: SubscriberCallback
    ) -> SubscriptionHandle:
        """Register a callback for an event name. Returns a handle for unsubscribe."""
        handle_id = self._next_handle_id
        self._next_handle_id += 1
        bucket = self._subs.setdefault(event_name, {})
        bucket[handle_id] = callback
        return SubscriptionHandle(handle_id=handle_id, event_name=event_name)

    def unsubscribe(self, handle: SubscriptionHandle) -> bool:
        """Remove a previously-registered callback.

        Returns:
            True if the handle was active and removed, False if it was
            already gone (idempotent — safe to call twice).
        """
        bucket = self._subs.get(handle.event_name)
        if not bucket or handle.handle_id not in bucket:
            return False
        del bucket[handle.handle_id]
        if not bucket:
            del self._subs[handle.event_name]
        return True

    async def publish(self, event_name: str, step: TraceStep) -> int:
        """Fan out a TraceStep to every subscriber of event_name.

        Sync callbacks run inline; async callbacks are awaited. Exceptions
        from any subscriber are caught and printed to stderr — siblings still
        run. Returns the number of subscribers fired (including those that
        raised).
        """
        bucket = self._subs.get(event_name)
        if not bucket:
            return 0

        # Snapshot so unsubscribe-during-publish is safe.
        snapshot = list(bucket.values())
        fired = 0
        for cb in snapshot:
            fired += 1
            try:
                result = cb(step)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                traceback.print_exc()
        return fired

    def subscriber_count(self, event_name: str) -> int:
        """Number of active subscribers on an event (0 if none)."""
        bucket = self._subs.get(event_name)
        return len(bucket) if bucket else 0

    def clear(self) -> None:
        """Drop every subscription on every event."""
        self._subs.clear()


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS
# =============================================================================

if __name__ == "__main__":

    print("=" * 70)
    print("  trace.py -- Smoke Tests (Stage 3.4.2)")
    print("=" * 70)

    passed = 0
    failed: List[str] = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        global passed
        if cond:
            passed += 1
        else:
            failed.append(f"FAIL: {name}" + (f" ({hint})" if hint else ""))

    async def smoke() -> None:
        global passed

        # ---- T1: TraceStep auto fields --------------------------------------
        s1 = TraceStep(step_type=StepType.REASONING, payload={"thought": "hi"})
        check("T1a step_id auto-generated", isinstance(s1.step_id, str) and s1.step_id.startswith("trace_"))
        check("T1b timestamp present", isinstance(s1.timestamp, str) and len(s1.timestamp) > 0)

        # ---- T2: to_dict has expected keys ----------------------------------
        d = s1.to_dict()
        expected_keys = {"step_id", "parent_id", "step_type", "timestamp", "payload", "duration_ms"}
        check("T2 to_dict keys", set(d.keys()) == expected_keys, hint=str(set(d.keys())))

        # ---- T3: to_dict step_type is string value --------------------------
        check("T3 step_type serialized as string", d["step_type"] == "reasoning", hint=str(d["step_type"]))

        # ---- T4: StepType enumerates 10 values ------------------------------
        check("T4 StepType has 10 members", len(list(StepType)) == 10, hint=str(len(list(StepType))))

        # ---- T5: sync callback fires ----------------------------------------
        bus = EventBus()
        sync_received: List[TraceStep] = []

        def sync_cb(step: TraceStep) -> None:
            sync_received.append(step)

        h_sync = bus.subscribe("evt.a", sync_cb)
        fired = await bus.publish("evt.a", TraceStep(step_type=StepType.OBSERVATION, payload={"k": 1}))
        check("T5a sync callback fired", len(sync_received) == 1 and sync_received[0].payload["k"] == 1)
        check("T5b publish returned 1", fired == 1, hint=str(fired))

        # ---- T6: async callback awaited -------------------------------------
        async_received: List[TraceStep] = []

        async def async_cb(step: TraceStep) -> None:
            await asyncio.sleep(0)
            async_received.append(step)

        h_async = bus.subscribe("evt.b", async_cb)
        await bus.publish("evt.b", TraceStep(step_type=StepType.TOOL_CALL, payload={"tool": "calc"}))
        check("T6 async callback awaited", len(async_received) == 1 and async_received[0].payload["tool"] == "calc")

        # ---- T7: two subscribers same event both fire -----------------------
        bus2 = EventBus()
        hits: List[str] = []
        bus2.subscribe("evt.c", lambda s: hits.append("A"))
        bus2.subscribe("evt.c", lambda s: hits.append("B"))
        fired2 = await bus2.publish("evt.c", TraceStep(step_type=StepType.ERROR))
        check("T7a both subscribers fired", sorted(hits) == ["A", "B"], hint=str(hits))
        check("T7b publish returned 2", fired2 == 2, hint=str(fired2))

        # ---- T8: subscriber A raising does not block subscriber B -----------
        bus3 = EventBus()
        b_called: List[bool] = []

        def bad_cb(step: TraceStep) -> None:
            raise RuntimeError("boom")

        def good_cb(step: TraceStep) -> None:
            b_called.append(True)

        bus3.subscribe("evt.d", bad_cb)
        bus3.subscribe("evt.d", good_cb)
        fired3 = await bus3.publish("evt.d", TraceStep(step_type=StepType.REFLECTION))
        check("T8a good callback still fired despite bad sibling", b_called == [True])
        check("T8b publish counted both", fired3 == 2, hint=str(fired3))

        # ---- T9: unsubscribe returns True then False ------------------------
        first = bus.unsubscribe(h_sync)
        second = bus.unsubscribe(h_sync)
        check("T9a first unsubscribe True", first is True)
        check("T9b second unsubscribe False", second is False)

        # ---- T10: after unsubscribe callback no longer fires ----------------
        sync_received.clear()
        await bus.publish("evt.a", TraceStep(step_type=StepType.OBSERVATION, payload={"k": 2}))
        check("T10 unsubscribed callback silent", sync_received == [])

        # ---- T11: subscriber_count accurate ---------------------------------
        bus4 = EventBus()
        check("T11a empty count 0", bus4.subscriber_count("evt.e") == 0)
        h_e1 = bus4.subscribe("evt.e", lambda s: None)
        h_e2 = bus4.subscribe("evt.e", lambda s: None)
        check("T11b two subscribers", bus4.subscriber_count("evt.e") == 2)
        bus4.unsubscribe(h_e1)
        check("T11c after one unsub -> 1", bus4.subscriber_count("evt.e") == 1)
        bus4.unsubscribe(h_e2)
        check("T11d after all unsub -> 0", bus4.subscriber_count("evt.e") == 0)

        # ---- T12: clear empties everything ----------------------------------
        bus5 = EventBus()
        bus5.subscribe("x", lambda s: None)
        bus5.subscribe("y", lambda s: None)
        bus5.subscribe("y", lambda s: None)
        check("T12a pre-clear x=1", bus5.subscriber_count("x") == 1)
        check("T12b pre-clear y=2", bus5.subscriber_count("y") == 2)
        bus5.clear()
        check("T12c post-clear x=0", bus5.subscriber_count("x") == 0)
        check("T12d post-clear y=0", bus5.subscriber_count("y") == 0)

        # ---- T13: publish to event with no subscribers returns 0 ------------
        bus6 = EventBus()
        fired6 = await bus6.publish("nobody", TraceStep(step_type=StepType.REPLAN))
        check("T13 publish to empty event returns 0", fired6 == 0, hint=str(fired6))

        # ---- T14: TraceStep payload is frozen (MappingProxyType wrap) -------
        # The original dict passed in must NOT alias the trace's payload, so
        # post-construction mutation of the source doesn't bleed in.
        src = {"key": "original"}
        step14 = TraceStep(step_type=StepType.REASONING, payload=src)
        src["key"] = "mutated"  # mutate AFTER construction
        check("T14a source mutation does not leak into trace",
              step14.payload["key"] == "original",
              hint=f"got {step14.payload.get('key')}")
        # Direct mutation of the trace's payload should raise (MappingProxy).
        try:
            step14.payload["new"] = "x"  # type: ignore[index]
            check("T14b trace payload is read-only", False, hint="no error")
        except TypeError:
            check("T14b trace payload is read-only", True)

        # ---- T15: to_dict returns a fresh mutable dict ----------------------
        step15 = TraceStep(step_type=StepType.OBSERVATION, payload={"k": 1})
        d15 = step15.to_dict()
        check("T15a to_dict payload is dict (mutable for callers)",
              isinstance(d15["payload"], dict))
        d15["payload"]["k"] = 999
        check("T15b mutating to_dict result does not affect trace",
              step15.payload["k"] == 1)

        # ---- Report ---------------------------------------------------------
        total = passed + len(failed)
        print(f"\n  Passed: {passed}/{total}")
        if failed:
            for f_ in failed:
                print(f"  {f_}")
            print("=" * 70)
            raise SystemExit(1)
        print(f"  All {total} trace smoke tests passed.")
        print("=" * 70)

    asyncio.run(smoke())
