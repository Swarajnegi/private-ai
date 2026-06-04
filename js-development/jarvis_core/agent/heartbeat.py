"""
heartbeat.py — Async Heartbeat Scheduler (Stage 3.5.6).

LAYER: Agent (Cognitive Synthesis Loop — the trigger)

Import with:
    from jarvis_core.agent.heartbeat import HeartbeatScheduler, HeartbeatEvent

=============================================================================
THE BIG PICTURE
=============================================================================

The consolidator (3.5.7) is the brain; this is its pulse. Per the metacognitive
review's hardware-reality check (cold-wake cloud inference makes per-second
clock polling 36-72x over budget), consolidation is EVENT-DRIVEN, not
clock-driven: a tool call that sets `request_heartbeat=true` marks the loop
"dirty," and the scheduler fires consolidation at the NEXT turn boundary —
debounced so a burst of requests collapses into ONE consolidation pass.

  request("tool:memory_write")  ─┐
  request("tool:file_write")    ─┼─►  pending + coalesced=3
  request("end_of_turn")        ─┘
            │  (turn boundary)
            ▼
       maybe_fire()  ── cooldown elapsed? ──► await on_heartbeat(HeartbeatEvent)
                          │ no
                          └──► no-op (stays pending for the next boundary)

The callback failing NEVER breaks the turn (errors swallowed). The clock is
injected, so the debounce logic is deterministically testable with no sleeps.

OBSOLESCENCE-PROOF: the scheduler knows nothing about WHAT it triggers — the
callback is injected. Today it wakes the local consolidator; tomorrow it can
cold-wake a RunPod pod. Zero change here.

=============================================================================
THE FLOW
=============================================================================

STEP 1: A tool whose result carries request_heartbeat=True -> scheduler.request().
        |
STEP 2: At the turn boundary the ReAct loop calls await scheduler.maybe_fire().
        |
STEP 3: If pending AND >= min_interval since the last fire -> await the callback
        with a HeartbeatEvent (reason + coalesce count). Reset pending.
        |
STEP 4: (optional) scheduler.run(stop_event) polls maybe_fire on a slow tick as a
        belt-and-suspenders backstop for long idle sessions.

=============================================================================
"""

from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, List, Optional, Union

HeartbeatCallback = Callable[["HeartbeatEvent"], Union[None, Awaitable[None]]]
Clock = Callable[[], float]

_DEFAULT_MIN_INTERVAL_S = 300.0  # debounce: at most one consolidation per 5 min


@dataclass(frozen=True)
class HeartbeatEvent:
    """One fired heartbeat — handed to the consolidation callback."""
    reason: str
    requested_at: float    # monotonic seconds of the FIRST request in this batch
    fired_at: float        # monotonic seconds when it fired
    coalesced: int         # how many request() calls collapsed into this fire


class HeartbeatScheduler:
    """Event-driven, debounced trigger for sleep-time consolidation."""

    def __init__(
        self,
        on_heartbeat: HeartbeatCallback,
        min_interval_s: float = _DEFAULT_MIN_INTERVAL_S,
        clock: Clock = time.monotonic,
    ) -> None:
        self._on_heartbeat = on_heartbeat
        self._min_interval = float(min_interval_s)
        self._clock = clock
        self._pending = False
        self._coalesced = 0
        self._first_request_at: Optional[float] = None
        self._reason = ""
        # Allow the very first request to fire immediately (no artificial wait).
        self._last_fired_at: float = self._clock() - self._min_interval
        self._lock = asyncio.Lock()
        self._fires: int = 0

    # ---- properties ------------------------------------------------------

    @property
    def pending(self) -> bool:
        return self._pending

    @property
    def coalesced(self) -> int:
        return self._coalesced

    @property
    def fire_count(self) -> int:
        return self._fires

    # ---- event intake ----------------------------------------------------

    def request(self, reason: str = "tool_request") -> None:
        """Mark the loop dirty. Cheap, sync, called from anywhere (e.g. when a
        tool result has request_heartbeat=True). Coalesces a burst."""
        now = self._clock()
        if not self._pending:
            self._first_request_at = now
            self._coalesced = 0
        self._pending = True
        self._coalesced += 1
        self._reason = reason

    def note_tool_result(self, result: object) -> None:
        """Convenience: if a tool result object/dict signals request_heartbeat,
        mark pending. Accepts a dict or any object with a request_heartbeat attr."""
        flag = False
        if isinstance(result, dict):
            flag = bool(result.get("request_heartbeat"))
        else:
            flag = bool(getattr(result, "request_heartbeat", False))
        if flag:
            self.request("tool_request_heartbeat")

    # ---- firing ----------------------------------------------------------

    def _cooldown_elapsed(self) -> bool:
        return (self._clock() - self._last_fired_at) >= self._min_interval

    async def maybe_fire(self) -> Optional[HeartbeatEvent]:
        """Fire iff pending AND the debounce window has elapsed. Returns the
        event if it fired, else None. Callback errors are swallowed."""
        async with self._lock:
            if not self._pending or not self._cooldown_elapsed():
                return None
            now = self._clock()
            event = HeartbeatEvent(
                reason=self._reason or "tool_request",
                requested_at=self._first_request_at if self._first_request_at is not None else now,
                fired_at=now,
                coalesced=self._coalesced,
            )
            # Reset BEFORE awaiting the callback so requests during consolidation
            # are not lost (they re-mark pending for the next boundary).
            self._pending = False
            self._coalesced = 0
            self._first_request_at = None
            self._last_fired_at = now
            self._fires += 1
        await self._dispatch(event)
        return event

    async def force_fire(self, reason: str = "forced") -> HeartbeatEvent:
        """Fire now, ignoring the debounce window (e.g. session-end flush)."""
        async with self._lock:
            now = self._clock()
            event = HeartbeatEvent(
                reason=reason,
                requested_at=self._first_request_at if self._first_request_at is not None else now,
                fired_at=now,
                coalesced=max(self._coalesced, 1),
            )
            self._pending = False
            self._coalesced = 0
            self._first_request_at = None
            self._last_fired_at = now
            self._fires += 1
        await self._dispatch(event)
        return event

    async def _dispatch(self, event: HeartbeatEvent) -> None:
        try:
            out = self._on_heartbeat(event)
            if inspect.isawaitable(out):
                await out
        except Exception:
            # A broken consolidation must NEVER break the user's turn.
            pass

    # ---- optional background loop ----------------------------------------

    async def run(
        self,
        stop_event: asyncio.Event,
        tick_s: float = 60.0,
        max_iterations: Optional[int] = None,
    ) -> int:
        """Belt-and-suspenders backstop for long idle sessions. Polls maybe_fire
        on a slow tick until stop_event is set. Returns the iteration count."""
        iters = 0
        while not stop_event.is_set():
            await self.maybe_fire()
            iters += 1
            if max_iterations is not None and iters >= max_iterations:
                break
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=tick_s)
            except asyncio.TimeoutError:
                pass
        return iters


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS
# =============================================================================

def _run_self_test() -> None:
    print("=" * 70)
    print("  heartbeat.py -- Smoke Tests")
    print("=" * 70)
    passed = 0
    failed: List[str] = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        nonlocal passed
        if cond:
            passed += 1
        else:
            failed.append(f"FAIL: {name}" + (f" ({hint})" if hint else ""))

    # Controllable fake clock.
    class FakeClock:
        def __init__(self) -> None:
            self.t = 1000.0
        def __call__(self) -> float:
            return self.t
        def advance(self, dt: float) -> None:
            self.t += dt

    async def scenario() -> None:
        nonlocal passed
        clk = FakeClock()
        fired: List[HeartbeatEvent] = []
        def cb(evt: HeartbeatEvent) -> None:
            fired.append(evt)

        sched = HeartbeatScheduler(cb, min_interval_s=300.0, clock=clk)

        check("T1 starts not pending", sched.pending is False)

        # First request can fire immediately (last_fired initialized in the past).
        sched.request("tool:a")
        check("T2 request sets pending", sched.pending is True)
        evt = await sched.maybe_fire()
        check("T3 first request fires immediately", evt is not None and len(fired) == 1)
        check("T4 pending cleared after fire", sched.pending is False)

        # Within cooldown: requests coalesce, do NOT fire.
        sched.request("tool:b")
        sched.request("tool:c")
        check("T5 coalesced count == 2", sched.coalesced == 2)
        evt2 = await sched.maybe_fire()
        check("T6 no fire within cooldown", evt2 is None and len(fired) == 1)
        check("T7 still pending after suppressed fire", sched.pending is True)

        # Advance past cooldown -> the coalesced batch fires ONCE.
        clk.advance(301.0)
        evt3 = await sched.maybe_fire()
        check("T8 fires after cooldown elapses", evt3 is not None and len(fired) == 2)
        check("T9 coalesced burst reported", evt3.coalesced == 2, str(evt3.coalesced))

        # maybe_fire with nothing pending -> no-op
        evt4 = await sched.maybe_fire()
        check("T10 no pending -> no fire", evt4 is None and len(fired) == 2)

        # force_fire ignores cooldown
        sched.request("x")
        before = len(fired)
        evt5 = await sched.force_fire("session_end")
        check("T11 force_fire fires regardless of cooldown",
              len(fired) == before + 1 and evt5.reason == "session_end")

        # note_tool_result with dict flag
        sched2 = HeartbeatScheduler(cb, min_interval_s=0.0, clock=clk)
        sched2.note_tool_result({"request_heartbeat": True})
        check("T12 note_tool_result(dict) marks pending", sched2.pending is True)
        sched3 = HeartbeatScheduler(cb, min_interval_s=0.0, clock=clk)
        sched3.note_tool_result({"request_heartbeat": False})
        check("T13 note_tool_result(False) leaves clean", sched3.pending is False)

        # async callback dispatched
        afired: List[HeartbeatEvent] = []
        async def acb(evt: HeartbeatEvent) -> None:
            afired.append(evt)
        asched = HeartbeatScheduler(acb, min_interval_s=0.0, clock=clk)
        asched.request("async")
        await asched.maybe_fire()
        check("T14 async callback awaited", len(afired) == 1)

        # callback error swallowed
        def boom(evt: HeartbeatEvent) -> None:
            raise RuntimeError("consolidation blew up")
        bsched = HeartbeatScheduler(boom, min_interval_s=0.0, clock=clk)
        bsched.request("boom")
        try:
            evt6 = await bsched.maybe_fire()
            check("T15 callback error swallowed, fire reported", evt6 is not None)
        except Exception:
            check("T15 callback error swallowed, fire reported", False, "exception escaped")

        # run() backstop: pending + elapsed cooldown -> fires within one iteration
        rfired: List[HeartbeatEvent] = []
        rsched = HeartbeatScheduler(lambda e: rfired.append(e), min_interval_s=0.0, clock=clk)
        rsched.request("idle")
        stop = asyncio.Event()
        iters = await rsched.run(stop, tick_s=0.01, max_iterations=1)
        check("T16 run() fires the pending heartbeat", len(rfired) == 1 and iters == 1)

    asyncio.run(scenario())

    total = passed + len(failed)
    print(f"\n  Passed: {passed}/{total}")
    if failed:
        for f_ in failed:
            print(f"  {f_}")
        print("=" * 70)
        raise SystemExit(1)
    print(f"  All {total} heartbeat smoke tests passed.")
    print("=" * 70)


if __name__ == "__main__":
    _run_self_test()
