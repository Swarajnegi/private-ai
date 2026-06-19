"""
model_pool.py — ModelPool + health-scored failover (Stage 4.1.4, STEAL #7).

LAYER: Brain (Orchestration — the owned multi-model pool)

Import with:
    from jarvis_core.brain.model_pool import ModelPool, AllTargetsExhausted

=============================================================================
THE BIG PICTURE
=============================================================================

STEAL #7 — ported from ai_model_repos/OpenClaude/python/smart_router.py. The
pool holds N RouteTargets and, per call, picks the best HEALTHY one by score,
invokes it, and on failure walks to the next-best peer (bounded by the target
count — never an infinite loop). Targets that 429 / error-storm are put in a
COOLDOWN and skipped until it expires; latency is tracked as an EMA so a
slow-but-up target loses to a fast one.

PORT NOTES (faithful to the source, adapted to JARVIS):
  - Source scored `latency/1000 + cost*k + error_rate*500`; we keep the shape
    with latency already in SECONDS and a tunable error penalty.
  - Source used a background asyncio recheck task; we instead check a
    `cooldown_until` timestamp AT SELECT time — no background task, fully
    deterministic, and the CLOCK is injected so tests are time-free.
  - The escape valve (FRONTIER_VALVE) is REFUSED admission: it is never an
    automatic failover peer (an explicit, budgeted user hand-off only).

Each target carries its OWN ledger (its client's), so a failed attempt on A and
a successful one on B both show up per-target in status() — "both attempts on
the ledgers."

=============================================================================
THE FLOW
=============================================================================

acall(messages):
  exclude = {}                       # peers already tried this call
  loop:
    target = select(now, exclude)    # min-score healthy, not excluded/cooled-down
    if none -> raise AllTargetsExhausted
    try: ensure_ready -> invoke -> record success(latency) -> return text
    except: record failure (429 -> cooldown); exclude this target; walk on

=============================================================================
"""

from __future__ import annotations

import inspect
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Union

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # standalone-run safety

from jarvis_core.brain.targets import RouteTarget, TargetKind

LLMCall = Callable[[List[Dict[str, str]]], Union[str, Awaitable[str]]]

_EMA_ALPHA = 0.3            # weight on the newest latency sample (source: 0.3)
_ERROR_PENALTY = 10.0      # score units added per unit error_rate (latency is in s)
_COOLDOWN_S = 60.0         # how long a 429 / error-storm target is benched
_ERROR_TRIP_RATE = 0.7     # error_rate above this (with enough samples) -> cooldown
_ERROR_MIN_REQUESTS = 3    # don't trip on a tiny sample


class AllTargetsExhausted(Exception):
    """Every routable target failed or is cooled-down for this call."""


def _is_rate_limit(exc: BaseException) -> bool:
    s = str(exc).lower()
    return "429" in s or "rate limit" in s or "rate-limit" in s or "too many requests" in s


@dataclass
class _Health:
    """Mutable per-target health record (the pool owns this, not the target)."""
    avg_latency_s: float = 1.0
    request_count: int = 0
    error_count: int = 0
    cooldown_until: float = 0.0     # clock value until which the target is benched

    @property
    def error_rate(self) -> float:
        return self.error_count / self.request_count if self.request_count else 0.0


class ModelPool:
    """Holds N RouteTargets; routes by health-score with bounded failover."""

    def __init__(
        self,
        targets: List[RouteTarget],
        *,
        strategy: str = "balanced",
        clock: Callable[[], float] = time.monotonic,
        cooldown_s: float = _COOLDOWN_S,
        max_failover: Optional[int] = None,
    ) -> None:
        valve = [t.name for t in targets if t.kind == TargetKind.FRONTIER_VALVE]
        if valve:
            raise ValueError(
                f"FRONTIER_VALVE target(s) {valve} cannot join the pool — the escape "
                "valve is an explicit user hand-off, never an automatic failover peer.")
        if not targets:
            raise ValueError("ModelPool needs at least one target.")
        self._targets: Dict[str, RouteTarget] = {t.name: t for t in targets}
        self._order: List[str] = [t.name for t in targets]   # stable tie-break
        self._health: Dict[str, _Health] = {t.name: _Health() for t in targets}
        self._strategy = strategy
        self._clock = clock
        self._cooldown_s = cooldown_s
        self._max_failover = max_failover
        # Last-call introspection for the orchestrator's printer.
        self.last_chosen: Optional[str] = None
        self.last_events: List[str] = []

    # ---- scoring + selection (STEAL #7) -----------------------------------

    def _cost_hint(self, name: str) -> float:
        return float(getattr(self._targets[name], "cost_hint", 0.0) or 0.0)

    def _score(self, name: str, now: float, strategy: str) -> float:
        h = self._health[name]
        if h.cooldown_until > now:
            return float("inf")
        latency_score = h.avg_latency_s
        cost_score = self._cost_hint(name)
        error_penalty = h.error_rate * _ERROR_PENALTY
        if strategy == "latency":
            return latency_score + error_penalty
        if strategy == "cost":
            return cost_score + error_penalty
        return 0.5 * latency_score + 0.5 * cost_score + error_penalty

    def select(
        self, now: Optional[float] = None, exclude: Set[str] = frozenset(),
        strategy: Optional[str] = None,
    ) -> Optional[RouteTarget]:
        now = self._clock() if now is None else now
        strat = strategy or self._strategy
        candidates = [n for n in self._order
                      if n not in exclude and self._health[n].cooldown_until <= now]
        if not candidates:
            return None
        best = min(candidates, key=lambda n: (self._score(n, now, strat), self._order.index(n)))
        return self._targets[best]

    def record_result(
        self, name: str, *, success: bool, latency_s: float = 0.0,
        rate_limited: bool = False, now: Optional[float] = None,
    ) -> None:
        now = self._clock() if now is None else now
        h = self._health[name]
        h.request_count += 1
        if success:
            h.avg_latency_s = _EMA_ALPHA * latency_s + (1 - _EMA_ALPHA) * h.avg_latency_s
            return
        h.error_count += 1
        storm = (h.request_count >= _ERROR_MIN_REQUESTS and h.error_rate > _ERROR_TRIP_RATE)
        if rate_limited or storm:
            h.cooldown_until = now + self._cooldown_s

    # ---- the failover loop -------------------------------------------------

    async def acall(self, messages: List[Dict[str, str]], *,
                    strategy: Optional[str] = None) -> str:
        """Select best healthy target -> invoke -> on failure, walk to the next
        peer (bounded by target count). Raises AllTargetsExhausted if none work."""
        exclude: Set[str] = set()
        attempts = 0  # last_events accumulates across the session (pool is per-ask)
        last_err: Optional[BaseException] = None
        while True:
            target = self.select(exclude=exclude, strategy=strategy)
            if target is None:
                raise AllTargetsExhausted(
                    f"all {len(self._targets)} target(s) failed/cooled-down"
                    + (f"; last error: {last_err}" if last_err else ""))
            name = target.name
            t0 = self._clock()
            try:
                await target.ensure_ready()
                out = target.llm_call(messages)
                if inspect.isawaitable(out):
                    out = await out
                self.record_result(name, success=True, latency_s=self._clock() - t0)
                self.last_chosen = name
                if exclude:
                    self.last_events.append(f"recovered on '{name}' after {len(exclude)} failover(s)")
                return str(out)
            except Exception as e:  # noqa: BLE001 — any target failure -> walk on
                rl = _is_rate_limit(e)
                self.record_result(name, success=False, latency_s=self._clock() - t0,
                                   rate_limited=rl)
                exclude.add(name)
                last_err = e
                attempts += 1
                self.last_events.append(
                    f"'{name}' failed ({'429' if rl else type(e).__name__}) -> failover")
                if self._max_failover is not None and attempts > self._max_failover:
                    raise AllTargetsExhausted(
                        f"max_failover={self._max_failover} exceeded; last error: {e}")

    def as_llm_call(self, strategy: Optional[str] = None) -> LLMCall:
        """A pool-backed LLMCall (messages -> text) the Mind can use unchanged;
        failover happens transparently per call."""
        async def _call(messages: List[Dict[str, str]]) -> str:
            return await self.acall(messages, strategy=strategy)
        return _call

    # ---- introspection -----------------------------------------------------

    @property
    def primary_model(self) -> str:
        """The current best target's model id (for the orchestrator's printer)."""
        t = self.select()
        return str(getattr(t, "name", "") if t else (self._order[0] if self._order else ""))

    def status(self, now: Optional[float] = None) -> Dict[str, Dict[str, Any]]:
        """Per-target health + ledger — the 'both attempts on the ledgers' view."""
        now = self._clock() if now is None else now
        out: Dict[str, Dict[str, Any]] = {}
        for name in self._order:
            h = self._health[name]
            out[name] = {
                "requests": h.request_count,
                "errors": h.error_count,
                "error_rate": round(h.error_rate, 3),
                "avg_latency_s": round(h.avg_latency_s, 3),
                "cooldown_remaining_s": round(max(0.0, h.cooldown_until - now), 1),
                "healthy": h.cooldown_until <= now,
                "ledger": self._targets[name].ledger_summary(),
            }
        return out

    def aggregate_ledger(self) -> Dict[str, Any]:
        """Sum spend across targets (for the orchestrator's single ledger line)."""
        calls = spend = 0.0
        models: List[str] = []
        for name in self._order:
            led = self._targets[name].ledger_summary() or {}
            calls += float(led.get("calls") or 0)
            spend += float(led.get("spend_usd") or 0.0)
            if led.get("model"):
                models.append(str(led["model"]))
        return {"models": models, "calls": int(calls), "spend_usd": round(spend, 6),
                "targets": len(self._order)}


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS (offline — fake targets, injected clock)
# =============================================================================

def _run_self_test() -> None:
    import asyncio

    print("=" * 66)
    print("  model_pool.py — Smoke Tests")
    print("=" * 66)
    passed = 0
    failed: List[str] = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        nonlocal passed
        if cond:
            passed += 1
        else:
            failed.append(f"FAIL: {name}" + (f" ({hint})" if hint else ""))

    def run(coro):
        return asyncio.run(coro)

    class FakeTarget(RouteTarget):
        """A scriptable RouteTarget: behavior in {'ok','raise','429'}."""
        def __init__(self, name, behavior="ok", kind=TargetKind.API_MODEL, cost_hint=0.0):
            self.name = name
            self.kind = kind
            self.profile = None
            self._behavior = behavior
            self.cost_hint = cost_hint
            self.calls = 0
            self.ready_calls = 0
        @property
        def llm_call(self):
            def _c(messages):
                self.calls += 1
                if self._behavior == "raise":
                    raise RuntimeError("boom")
                if self._behavior == "429":
                    raise RuntimeError("HTTP 429 Too Many Requests")
                return f"{self.name}:ANSWER"
            return _c
        async def ensure_ready(self):
            self.ready_calls += 1
        async def release(self):
            pass
        def ledger_summary(self):
            return {"model": self.name, "calls": self.calls, "spend_usd": 0.001 * self.calls}

    clk = {"t": 0.0}
    def clock():
        return clk["t"]

    # T1: single healthy target -> returns its answer
    a = FakeTarget("A")
    p1 = ModelPool([a], clock=clock)
    check("T1 single target answers", run(p1.acall([{"role": "user", "content": "q"}])) == "A:ANSWER")
    check("T1b status records the request", p1.status()["A"]["requests"] == 1)
    check("T1c chosen recorded", p1.last_chosen == "A")

    # T2: primary raises -> failover to peer B; BOTH attempts recorded
    a2 = FakeTarget("A", behavior="raise"); b2 = FakeTarget("B", behavior="ok")
    p2 = ModelPool([a2, b2], clock=clock)
    out2 = run(p2.acall([{"role": "user", "content": "q"}]))
    st2 = p2.status()
    check("T2 fails over to B", out2 == "B:ANSWER", out2)
    check("T2b A recorded an error, B a success",
          st2["A"]["errors"] == 1 and st2["B"]["requests"] == 1 and st2["B"]["errors"] == 0, str(st2))
    check("T2c failover event surfaced", any("failover" in e for e in p2.last_events), str(p2.last_events))

    # T3: 429 on A -> A cooled down, skipped until cooldown expires
    a3 = FakeTarget("A", behavior="429"); b3 = FakeTarget("B", behavior="ok")
    p3 = ModelPool([a3, b3], clock=clock, cooldown_s=60.0)
    run(p3.acall([{"role": "user", "content": "q"}]))
    check("T3 A in cooldown after 429", p3.status()["A"]["cooldown_remaining_s"] > 0, str(p3.status()["A"]))
    check("T3b A not selectable while cooled down", p3.select().name == "B")
    clk["t"] = 61.0  # advance past cooldown
    check("T3c A recovers after cooldown window", p3.status()["A"]["healthy"] is True)
    clk["t"] = 0.0

    # T4: ALL targets fail -> AllTargetsExhausted (bounded, no infinite loop)
    pf = ModelPool([FakeTarget("A", "raise"), FakeTarget("B", "raise")], clock=clock)
    raised = False
    try:
        run(pf.acall([{"role": "user", "content": "q"}]))
    except AllTargetsExhausted:
        raised = True
    check("T4 all-fail -> AllTargetsExhausted (bounded)", raised)

    # T5: scoring — a high-error target loses to a clean peer
    p5 = ModelPool([FakeTarget("A"), FakeTarget("B")], clock=clock)
    p5.record_result("A", success=False)  # A now has an error; B clean
    p5.record_result("B", success=True, latency_s=1.0)
    check("T5 clean peer outscores errored peer", p5.select().name == "B", str(p5.status()))

    # T6: EMA latency updates on success
    p6 = ModelPool([FakeTarget("A")], clock=clock)
    p6.record_result("A", success=True, latency_s=5.0)
    ema = p6.status()["A"]["avg_latency_s"]
    check("T6 EMA latency moved toward sample", 1.0 < ema < 5.0, str(ema))  # 0.3*5+0.7*1=2.2

    # T7: FRONTIER_VALVE refused admission
    refused = False
    try:
        ModelPool([FakeTarget("V", kind=TargetKind.FRONTIER_VALVE)], clock=clock)
    except ValueError as e:
        refused = "FRONTIER_VALVE" in str(e)
    check("T7 escape valve refused from pool", refused)

    # T8: as_llm_call is a working LLMCall with failover
    llm = ModelPool([FakeTarget("A", "raise"), FakeTarget("B", "ok")], clock=clock).as_llm_call()
    check("T8 as_llm_call works with failover", run(llm([{"role": "user", "content": "q"}])) == "B:ANSWER")

    # T9: exclude set respected
    p9 = ModelPool([FakeTarget("A"), FakeTarget("B")], clock=clock)
    check("T9 exclude respected", p9.select(exclude={"A"}).name == "B")
    check("T9b exclude-all -> None", p9.select(exclude={"A", "B"}) is None)

    # T10: max_failover cap honored
    pcap = ModelPool([FakeTarget("A", "raise"), FakeTarget("B", "raise"), FakeTarget("C", "ok")],
                     clock=clock, max_failover=1)
    capped = False
    try:
        run(pcap.acall([{"role": "user", "content": "q"}]))
    except AllTargetsExhausted as e:
        capped = "max_failover" in str(e)
    check("T10 max_failover cap stops the walk early", capped)

    # T11: aggregate_ledger sums per-target spend
    pa = ModelPool([FakeTarget("A"), FakeTarget("B")], clock=clock)
    run(pa.acall([{"role": "user", "content": "q"}]))
    agg = pa.aggregate_ledger()
    check("T11 aggregate ledger", agg["targets"] == 2 and agg["calls"] >= 1, str(agg))

    # T12 (verify-fix #1): under strategy='cost', the CHEAPER cost_hint wins (not
    # declaration order). Pricey declared first must NOT win. Free (0.0) beats paid.
    pricey = FakeTarget("pricey", cost_hint=2.0)
    cheap = FakeTarget("cheap", cost_hint=0.0)
    pcost = ModelPool([pricey, cheap], strategy="cost", clock=clock)
    check("T12 cost strategy picks the cheaper target despite declaration order",
          pcost.select(strategy="cost").name == "cheap", str(pcost.status()))
    check("T12b balanced also penalizes the pricey target",
          pcost.select(strategy="balanced").name == "cheap")

    total = passed + len(failed)
    print(f"\n  Passed: {passed}/{total}")
    if failed:
        for f_ in failed:
            print(f"  {f_}")
        print("=" * 66)
        raise SystemExit(1)
    print(f"  All {total} model_pool smoke tests passed.")
    print("=" * 66)


if __name__ == "__main__":
    _run_self_test()
