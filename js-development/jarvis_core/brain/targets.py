"""
targets.py — RouteTarget contract (Stage 4.1 Wave 2).

LAYER: Brain (Orchestration — the uniform routable-model contract)

Import with:
    from jarvis_core.brain.targets import (
        RouteTarget, TargetKind, OpenRouterTarget, RunPodTarget, EscapeValveTarget,
    )

=============================================================================
THE BIG PICTURE
=============================================================================

A RouteTarget is ONE thing the Orchestrator can route a query to, behind a
uniform contract, so the 4.2 Router and the 4.1.4 ModelPool never special-case
where a model lives. Three kinds:

  - API_MODEL      — a hosted endpoint (OpenRouter). Always-ready; no lifecycle.
  - POD_ADAPTER    — a cold-wake RunPod pod + QLoRA adapter (Stage 5). STUB here:
                     the ensure_ready/release seam exists, the body does not.
  - FRONTIER_VALVE — an expensive frontier model the USER explicitly hands off to
                     (escape valve). Structurally OUTSIDE the router pool — the
                     ModelPool refuses to admit it; only an explicit flag builds one.

Contract (every target): name / kind / profile (ModelProfile conduct) / llm_call
(the protocol-adapted callable the Mind invokes) / ensure_ready() / release() /
ledger_summary(). The llm_call is already ProtocolAdapter-wrapped, so per-model
wire dialects are absorbed before the Mind ever sees them.

=============================================================================
THE FLOW
=============================================================================

STEP 1: construct a target for a model id. It resolves the model's ModelProfile
        (ProfileRegistry: exact→family→DEFAULT) and wraps its raw LLMCall in a
        ProtocolAdapter (system-fold per profile.system_role_ok).
        |
STEP 2: ensure_ready() — API targets: no-op (lazily pick a free model if unset).
        Pod targets: cold-wake (Stage 5 stub). release() — symmetric teardown.
        |
STEP 3: the pool/orchestrator invokes target.llm_call(messages) -> text, and
        reads target.ledger_summary() for per-target spend.

=============================================================================
"""

from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # standalone-run safety

from jarvis_core.brain.model_profiles import ModelProfile, ProfileRegistry, DEFAULT_PROFILE
from jarvis_core.brain.protocol import adapt

LLMCall = Callable[[List[Dict[str, str]]], Union[str, Awaitable[str]]]


class TargetKind(str, Enum):
    API_MODEL = "API_MODEL"
    POD_ADAPTER = "POD_ADAPTER"
    FRONTIER_VALVE = "FRONTIER_VALVE"


# =============================================================================
# Part 1: CONTRACT (abstract)
# =============================================================================

class RouteTarget(ABC):
    """One routable model behind a uniform contract."""

    name: str
    kind: TargetKind
    profile: ModelProfile

    @property
    @abstractmethod
    def llm_call(self) -> LLMCall:
        """The protocol-adapted callable the Mind invokes (messages -> text)."""

    @abstractmethod
    async def ensure_ready(self) -> None:
        """Make the target callable (cold-wake a pod, pick a free model). No-op for
        always-on API targets. MUST be idempotent."""

    @abstractmethod
    async def release(self) -> None:
        """Tear down any resource ensure_ready acquired. No-op for API targets."""

    @abstractmethod
    def ledger_summary(self) -> Dict[str, Any]:
        """Per-target spend ledger (model, calls, spend_usd, ...)."""

    def __repr__(self) -> str:
        return f"{type(self).__name__}(name={self.name!r}, kind={self.kind.value})"


# =============================================================================
# Part 2: API_MODEL — OpenRouter (live)
# =============================================================================

class OpenRouterTarget(RouteTarget):
    """An OpenRouter-hosted model. Always-ready; lifecycle hooks are no-ops
    (ensure_ready lazily picks a free model only if none was configured)."""

    kind = TargetKind.API_MODEL

    def __init__(
        self,
        model: str = "",
        *,
        budget_usd: float = 0.10,
        name: Optional[str] = None,
        client: Optional[Any] = None,
        registry: Optional[ProfileRegistry] = None,
        use_profile: bool = True,
    ) -> None:
        self._registry = registry or ProfileRegistry()
        self._use_profile = use_profile
        if client is None:
            from jarvis_core.brain.llm_client import build_llm_call
            client = build_llm_call(budget_usd=budget_usd, model=model)
        self._client = client
        self.name = name or (str(getattr(client, "model", "")) or model or "openrouter")
        self._resolve_profile()

    def _resolve_profile(self) -> None:
        model_id = str(getattr(self._client, "model", "") or "")
        if self._use_profile:
            self.profile, self._profile_label = self._registry.get(model_id)
        else:
            self.profile, self._profile_label = DEFAULT_PROFILE, "none"
        # Re-wrap the adapter for the (possibly newly resolved) profile.
        self._adapter = adapt(self._client, self.profile, label=self.name)

    @property
    def llm_call(self) -> LLMCall:
        return self._adapter

    @property
    def profile_label(self) -> str:
        return self._profile_label

    async def ensure_ready(self) -> None:
        # API model is always reachable. Only lazy work: pick a free model + (re)
        # resolve its profile if none was configured.
        if hasattr(self._client, "pick_free_model") and not getattr(self._client, "model", ""):
            await self._client.pick_free_model()
            self._resolve_profile()
            if self.name in ("openrouter", ""):
                self.name = str(getattr(self._client, "model", "")) or self.name

    async def release(self) -> None:
        return None

    def ledger_summary(self) -> Dict[str, Any]:
        if hasattr(self._client, "ledger_summary"):
            try:
                return self._client.ledger_summary()
            except Exception:
                pass
        return {"model": self.name, "calls": 0}


# =============================================================================
# Part 3: POD_ADAPTER — RunPod cold-wake (Stage 5 STUB)
# =============================================================================

class PodHandle:
    """Stage-5 seam: a cold-wakeable RunPod pod hosting Kimi K2.6 + one QLoRA
    adapter. Contract only — the cold-wake/release bodies land in Stage 5."""

    def __init__(self, adapter_id: str, gpu: str = "A5000") -> None:
        self.adapter_id = adapter_id
        self.gpu = gpu
        self.awake = False


class RunPodTarget(RouteTarget):
    """A cold-wake pod + QLoRA adapter. STUB: the contract + adapter_id seam exist
    so the pool/router can be written against it now; the cold-wake body is Stage 5."""

    kind = TargetKind.POD_ADAPTER

    def __init__(self, adapter_id: str, *, name: Optional[str] = None,
                 profile: Optional[ModelProfile] = None) -> None:
        self.name = name or f"pod:{adapter_id}"
        self.profile = profile or DEFAULT_PROFILE
        self.handle = PodHandle(adapter_id)

    @property
    def llm_call(self) -> LLMCall:
        raise NotImplementedError(
            "RunPodTarget.llm_call requires a woken pod — RunPod cold-wake inference "
            "lands in Stage 5 (QLoRA adapters). This is a contract stub.")

    async def ensure_ready(self) -> None:
        raise NotImplementedError(
            "RunPodTarget.ensure_ready (cold-wake) is a Stage-5 stub — no pod is "
            f"provisioned for adapter '{self.handle.adapter_id}' yet.")

    async def release(self) -> None:
        self.handle.awake = False

    def ledger_summary(self) -> Dict[str, Any]:
        return {"model": self.name, "calls": 0, "note": "stub (Stage 5)"}


# =============================================================================
# Part 4: FRONTIER_VALVE — escape valve (OUTSIDE the pool)
# =============================================================================

class EscapeValveTarget(OpenRouterTarget):
    """An expensive frontier model the USER explicitly invokes (e.g. Opus/GPT-5).
    Reuses the OpenRouter wiring but is marked FRONTIER_VALVE so the ModelPool
    REFUSES to admit it — it is never an automatic failover peer. Constructed only
    behind an explicit user flag (a deliberate, budgeted hand-off)."""

    kind = TargetKind.FRONTIER_VALVE


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS (offline — injected fake clients)
# =============================================================================

def _run_self_test() -> None:
    import asyncio

    print("=" * 66)
    print("  targets.py — Smoke Tests")
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

    # A fake OpenRouterClient: an LLMCall with .model, .ledger_summary, .pick_free_model.
    class FakeClient:
        def __init__(self, model="vendor/m", picks="picked/free"):
            self.model = model
            self._picks = picks
            self.seen = None
            self.calls = 0
        def __call__(self, messages):
            self.seen = messages
            self.calls += 1
            return "ANSWER"
        def ledger_summary(self):
            return {"model": self.model, "calls": self.calls, "spend_usd": 0.001}
        async def pick_free_model(self):
            self.model = self._picks
            return self.model

    # A registry that returns a known profile for a given model.
    reg = ProfileRegistry()

    # T1: OpenRouterTarget contract surface
    t1 = OpenRouterTarget(client=FakeClient("vendor/m"), registry=reg)
    check("T1 kind API_MODEL", t1.kind == TargetKind.API_MODEL)
    check("T1b name from client model", t1.name == "vendor/m", t1.name)
    check("T1c has a ModelProfile", isinstance(t1.profile, ModelProfile))
    check("T1d llm_call works (messages->text)",
          run(t1.llm_call([{"role": "user", "content": "q"}])) == "ANSWER")
    check("T1e ledger forwards client ledger", t1.ledger_summary()["spend_usd"] == 0.001)
    check("T1f ensure_ready/release no-op on a ready model", run(t1.ensure_ready()) is None
          and run(t1.release()) is None)

    # T2: system-role-averse profile -> the target's llm_call FOLDS system (via adapter)
    class _Reg:
        def get(self, mid):
            return ModelProfile(system_role_ok=False, notes="fold test"), "test"
    fc = FakeClient("fold/model")
    t2 = OpenRouterTarget(client=fc, registry=_Reg())
    run(t2.llm_call([{"role": "system", "content": "SYS"}, {"role": "user", "content": "u"}]))
    check("T2 target folds system per profile.system_role_ok=False",
          all(m["role"] != "system" for m in fc.seen) and "SYS" in fc.seen[0]["content"],
          str(fc.seen))

    # T3: ensure_ready picks a free model + re-resolves when none configured
    fc3 = FakeClient(model="", picks="free/x")
    t3 = OpenRouterTarget(client=fc3, registry=reg)
    run(t3.ensure_ready())
    check("T3 ensure_ready picks a free model when unset", fc3.model == "free/x", fc3.model)

    # T4: RunPodTarget is a clear Stage-5 stub
    t4 = RunPodTarget("engineer-lora")
    check("T4 kind POD_ADAPTER + adapter_id seam",
          t4.kind == TargetKind.POD_ADAPTER and t4.handle.adapter_id == "engineer-lora")
    raised = False
    try:
        run(t4.ensure_ready())
    except NotImplementedError as e:
        raised = "Stage-5" in str(e) or "Stage 5" in str(e)
    check("T4b ensure_ready raises a clear Stage-5 NotImplementedError", raised)
    llm_raised = False
    try:
        _ = t4.llm_call
    except NotImplementedError:
        llm_raised = True
    check("T4c llm_call raises (no woken pod)", llm_raised)

    # T5: EscapeValveTarget is FRONTIER_VALVE (the pool-exclusion marker)
    t5 = EscapeValveTarget(client=FakeClient("frontier/opus"), registry=reg)
    check("T5 EscapeValve kind FRONTIER_VALVE", t5.kind == TargetKind.FRONTIER_VALVE)
    check("T5b still a working target (callable)",
          run(t5.llm_call([{"role": "user", "content": "q"}])) == "ANSWER")

    # T6: repr is informative
    check("T6 repr", "API_MODEL" in repr(t1) and "vendor/m" in repr(t1), repr(t1))

    total = passed + len(failed)
    print(f"\n  Passed: {passed}/{total}")
    if failed:
        for f_ in failed:
            print(f"  {f_}")
        print("=" * 66)
        raise SystemExit(1)
    print(f"  All {total} targets smoke tests passed.")
    print("=" * 66)


if __name__ == "__main__":
    _run_self_test()
