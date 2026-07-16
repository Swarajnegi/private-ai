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

Stage 4.3.1: health is otherwise lost every time a fresh pool is built (once
per orchestrator.ask() call). `initial_health` (ctor) and `snapshot_health()`
(read) are the seam brain/model_stats.py's persistence hooks into — a target
still cooling down from the last call stays benched instead of getting
retried cold.

Stage 4.3.2 (budget governor): given a SHARED CostTracker (`cost_tracker`),
select() benches every paid target once aggregate spend crosses
_DOWNSHIFT_THRESHOLD of the budget and routes free-tier peers only; if none
remain the pool fails CLOSED (AllTargetsExhausted) rather than overspend. The
tracker is shared with every target's llm_client, whose per-call budget gate
then reads the same aggregate — closing the failover-resets-per-client-spend
hole a per-client budget can't.

Stage 4.3.3 (catalog drift): `_is_not_found()` classifies a 404/"model not
found"-shaped failure and `record_result(..., not_found=True)` cools it down
on the FIRST occurrence — unlike a transient error, a vanished model will not
recover this call, so it shouldn't need `_ERROR_MIN_REQUESTS` attempts before
getting benched. Cross-restart avoidance (never even BUILDING a target for a
model that's gone) is `scripts/sync_openrouter.py`'s job, not this pool's.

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
_DOWNSHIFT_THRESHOLD = 0.9  # aggregate spend >= this fraction of budget -> free-tier only


class AllTargetsExhausted(Exception):
    """Every routable target failed or is cooled-down for this call."""


def _is_rate_limit(exc: BaseException) -> bool:
    s = str(exc).lower()
    return "429" in s or "rate limit" in s or "rate-limit" in s or "too many requests" in s


def _is_not_found(exc: BaseException) -> bool:
    """Stage 4.3.3: a VANISHED model (free-tier churn, ~weekly) reads differently
    from a transient failure -- it will not recover THIS call, so it shouldn't
    need _ERROR_MIN_REQUESTS attempts before record_result cools it down."""
    s = str(exc).lower()
    return ("404" in s or "not found" in s or "no such model" in s
            or "model_not_found" in s or "invalid model" in s)


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
        initial_health: Optional[Dict[str, Dict[str, float]]] = None,
        cost_tracker: Optional[Any] = None,
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
        # Stage 4.3.1: a target present in initial_health (persisted by
        # model_stats.py from a PRIOR ask() call) seeds from there instead of
        # a cold _Health() default. Malformed/stale persisted shapes fall back
        # to the default rather than ever crashing pool construction.
        self._health: Dict[str, _Health] = {}
        for t in targets:
            seed = (initial_health or {}).get(t.name)
            if seed is not None:
                try:
                    self._health[t.name] = _Health(**seed)
                    continue
                except TypeError:
                    pass  # unknown/missing keys in persisted data -> cold default
            self._health[t.name] = _Health()
        self._strategy = strategy
        self._clock = clock
        self._cooldown_s = cooldown_s
        self._max_failover = max_failover
        self._cost_tracker = cost_tracker   # Stage 4.3.2 budget governor (or None)
        # Last-call introspection for the orchestrator's printer.
        self.last_chosen: Optional[str] = None
        self.last_events: List[str] = []
        self._downshifted = False           # latch so the downshift note prints once

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

    def _budget_downshift_active(self) -> bool:
        """Stage 4.3.2: has cumulative aggregate spend crossed the soft ceiling?
        Reads should_downshift on the SHARED CostTracker (fed live-priced spend
        by every target's client), so the whole pool sees one running total —
        the failover-safe aggregate a per-client budget could never see."""
        t = self._cost_tracker
        if t is None:
            return False
        try:
            return bool(t.should_downshift(_DOWNSHIFT_THRESHOLD))
        except Exception:
            return False  # a governor hiccup must never break selection

    def select(
        self, now: Optional[float] = None, exclude: Set[str] = frozenset(),
        strategy: Optional[str] = None,
    ) -> Optional[RouteTarget]:
        now = self._clock() if now is None else now
        strat = strategy or self._strategy
        candidates = [n for n in self._order
                      if n not in exclude and self._health[n].cooldown_until <= now]
        # Budget governor: once aggregate spend nears the ceiling, bench every
        # paid target (cost_hint > 0) and route only free-tier peers. If that
        # empties the field, select() returns None -> acall() raises
        # AllTargetsExhausted = fail CLOSED (never silently overspend). Free-tier
        # detection is cost_hint == 0.0, which also matches models absent from
        # the catalog; at the ₹0 stage every target is genuinely free so this is
        # the safe direction, and the per-client aggregate gate backstops any
        # mis-classified paid model regardless.
        if candidates and self._budget_downshift_active():
            free = [n for n in candidates if self._cost_hint(n) <= 0.0]
            if not self._downshifted:
                self.last_events.append(
                    f"budget downshift: aggregate spend >= {int(_DOWNSHIFT_THRESHOLD * 100)}% "
                    f"of budget -> restricting to free tier ({len(free)} peer(s))")
                self._downshifted = True
            candidates = free
        if not candidates:
            return None
        best = min(candidates, key=lambda n: (self._score(n, now, strat), self._order.index(n)))
        return self._targets[best]

    def record_result(
        self, name: str, *, success: bool, latency_s: float = 0.0,
        rate_limited: bool = False, not_found: bool = False, now: Optional[float] = None,
    ) -> None:
        now = self._clock() if now is None else now
        h = self._health[name]
        h.request_count += 1
        if success:
            h.avg_latency_s = _EMA_ALPHA * latency_s + (1 - _EMA_ALPHA) * h.avg_latency_s
            return
        h.error_count += 1
        storm = (h.request_count >= _ERROR_MIN_REQUESTS and h.error_rate > _ERROR_TRIP_RATE)
        # Stage 4.3.3: not_found trips the cooldown on the FIRST occurrence,
        # bypassing the storm minimum. A vanished model (catalog churn) will not
        # recover THIS call the way a transient error might — unlike a 429,
        # waiting for _ERROR_MIN_REQUESTS failures before benching it just wastes
        # attempts on something already known to be gone.
        if rate_limited or storm or not_found:
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
                nf = _is_not_found(e)
                self.record_result(name, success=False, latency_s=self._clock() - t0,
                                   rate_limited=rl, not_found=nf)
                exclude.add(name)
                last_err = e
                attempts += 1
                tag = "429" if rl else ("404" if nf else type(e).__name__)
                self.last_events.append(f"'{name}' failed ({tag}) -> failover")
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

    def snapshot_health(self) -> Dict[str, Dict[str, float]]:
        """Read-only view of current per-target health, in the exact shape
        ModelStatsStore.flush()/ModelPool(initial_health=...) expect (Stage
        4.3.1) -- callers persist/reload state through this, never by
        reaching into _health directly."""
        return {
            name: {
                "avg_latency_s": h.avg_latency_s,
                "request_count": h.request_count,
                "error_count": h.error_count,
                "cooldown_until": h.cooldown_until,
            }
            for name, h in self._health.items()
        }

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
        """A scriptable RouteTarget: behavior in {'ok','raise','429','404'}."""
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
                if self._behavior == "404":
                    raise RuntimeError("HTTP 404: model_not_found — no such model on OpenRouter")
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

    # T13 (Stage 4.3.1): initial_health seeds _Health from persisted state —
    # a target still "cooling down" from a prior ask() stays benched cold.
    seeded = ModelPool(
        [FakeTarget("A"), FakeTarget("B")], clock=clock,
        initial_health={"A": {"avg_latency_s": 4.0, "request_count": 10,
                              "error_count": 8, "cooldown_until": 500.0}},
    )
    st13 = seeded.status()
    check("T13 seeded target's cooldown carries over", st13["A"]["cooldown_remaining_s"] > 0, str(st13["A"]))
    check("T13b seeded target not selectable while its persisted cooldown holds",
          seeded.select().name == "B")
    check("T13c un-seeded target (B) still gets a cold default", st13["B"]["requests"] == 0)

    # T13d: malformed persisted health (unknown key) falls back to a cold
    # default instead of crashing pool construction.
    tolerant = ModelPool([FakeTarget("A")], clock=clock,
                        initial_health={"A": {"bogus_key": 1.0}})
    check("T13d malformed seed falls back to default, no crash",
          tolerant.status()["A"]["requests"] == 0)

    # T14 (Stage 4.3.1): snapshot_health() round-trips through a real
    # flush/load_latest cycle (the model_stats.py seam), not just a shape check.
    from jarvis_core.brain.model_stats import ModelStatsStore
    import tempfile as _tempfile
    p14 = ModelPool([FakeTarget("A"), FakeTarget("B", behavior="raise")], clock=clock)
    run(p14.acall([{"role": "user", "content": "q"}]))  # A succeeds, B never tried (A scores first)
    p14.record_result("B", success=False)  # force some B history directly
    snap = p14.snapshot_health()
    check("T14 snapshot has both targets", set(snap) == {"A", "B"}, str(snap))
    with _tempfile.TemporaryDirectory() as d:
        store = ModelStatsStore(path=Path(d) / "model_stats.jsonl")
        store.flush("2026-07-15T10:00:00+05:30", snap)
        reloaded = ModelPool([FakeTarget("A"), FakeTarget("B")], clock=clock,
                             initial_health=store.load_latest())
        check("T14b reloaded pool's health matches the flushed snapshot",
              reloaded.status()["A"]["requests"] == snap["A"]["request_count"], str(reloaded.status()))

    # T15 (Stage 4.3.2): budget governor benches paid targets past the ceiling.
    from jarvis_core.agent.cost import CostTracker
    paid = FakeTarget("paid", cost_hint=2.0)
    free = FakeTarget("free", cost_hint=0.0)
    # A fresh tracker (spend 0) -> no downshift: the paid target is still a
    # candidate (proven by excluding the free one and still getting paid back).
    ct_lo = CostTracker(budget_usd=1.0)
    p15 = ModelPool([paid, free], clock=clock, cost_tracker=ct_lo)
    check("T15 below ceiling, paid target still selectable",
          p15.select(exclude={"free"}).name == "paid", str(p15.status()))
    # Push aggregate to 95% of a $1 budget -> downshift active.
    ct_hi = CostTracker(budget_usd=1.0)
    ct_hi.record("x", 0, 0, cost_usd=0.95)
    p15b = ModelPool([paid, free], clock=clock, cost_tracker=ct_hi)
    check("T15b past ceiling, paid target benched (governor removed it)",
          p15b.select(exclude={"free"}) is None)
    check("T15c past ceiling, the free peer is still routed",
          p15b.select().name == "free")
    check("T15d downshift note logged once", any("budget downshift" in e for e in p15b.last_events),
          str(p15b.last_events))

    # T16 (Stage 4.3.2): past ceiling with NO free peer -> fail CLOSED.
    ct_hi2 = CostTracker(budget_usd=1.0)
    ct_hi2.record("x", 0, 0, cost_usd=0.99)
    p16 = ModelPool([FakeTarget("paid1", cost_hint=2.0), FakeTarget("paid2", cost_hint=3.0)],
                    clock=clock, cost_tracker=ct_hi2)
    check("T16 no free peer past ceiling -> select() None (fail closed)", p16.select() is None)
    exhausted = False
    try:
        run(p16.acall([{"role": "user", "content": "q"}]))
    except AllTargetsExhausted:
        exhausted = True
    check("T16b acall fails closed with AllTargetsExhausted (never overspends)", exhausted)

    # T17 (Stage 4.3.2): no tracker -> governor inert, behavior unchanged.
    p17 = ModelPool([paid, free], clock=clock)  # cost_tracker defaults None
    check("T17 no cost_tracker -> paid still selectable (governor off)",
          p17.select(exclude={"free"}).name == "paid")

    # T18 (Stage 4.3.3): a vanished model (404) trips cooldown on the FIRST
    # failure — NOT after _ERROR_MIN_REQUESTS=3 like a generic error would.
    a18 = FakeTarget("A", behavior="404"); b18 = FakeTarget("B", behavior="ok")
    p18 = ModelPool([a18, b18], clock=clock, cooldown_s=60.0)
    out18 = run(p18.acall([{"role": "user", "content": "q"}]))
    st18 = p18.status()
    check("T18 fails over to the healthy peer", out18 == "B:ANSWER", out18)
    check("T18b vanished target cooled down after ONE 404 (request_count == 1)",
          st18["A"]["cooldown_remaining_s"] > 0 and st18["A"]["requests"] == 1, str(st18["A"]))
    check("T18c failover event tagged 404, not a generic exception name",
          any("404" in e for e in p18.last_events), str(p18.last_events))
    check("T18d raw 404 never surfaced as the answer", "404" not in out18)

    # T18e: contrast — a GENERIC single failure (not 404, not 429) must NOT trip
    # cooldown yet (still needs the storm minimum). Confirms the 404 fast-path is
    # additive, not a relaxation of the existing storm-detection bar.
    a18e = FakeTarget("A", behavior="raise"); b18e = FakeTarget("B", behavior="ok")
    p18e = ModelPool([a18e, b18e], clock=clock, cooldown_s=60.0)
    run(p18e.acall([{"role": "user", "content": "q"}]))
    check("T18e one generic failure does NOT cooldown (needs the storm minimum)",
          p18e.status()["A"]["cooldown_remaining_s"] == 0, str(p18e.status()["A"]))

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
