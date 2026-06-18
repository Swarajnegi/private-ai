"""
llm_client.py — OpenRouter LLM adapter (First Light: the first real brain wire).

LAYER: Brain (adapter)

Run with:
    PYTHONPATH=js-development python3 js-development/jarvis_core/brain/llm_client.py            # offline smoke tests
    PYTHONPATH=js-development python3 js-development/jarvis_core/brain/llm_client.py --live    # real ping (needs OPENROUTER_API_KEY)
    PYTHONPATH=js-development python3 js-development/jarvis_core/brain/llm_client.py --first-thought
                                                                       # live Final Boss: Mind + real model + real tool

=============================================================================
THE BIG PICTURE
=============================================================================

Every Stage 3 surface was built against the `LLMCall` DI seam and tested on
scripted stubs. This module is the seam's first REAL implementation — the
moment the agent framework stops simulating thought and starts thinking.

One client lights five already-built surfaces unchanged:
    mind.py (the Mind), consolidator synthesis, correlation epistemic gate,
    evals LLMJudgeScorer, compact summarizer — all take `llm_call`; this IS one.

Engineering posture (per JARVIS_ENDGAME Phase 1-3 + cost.py STEAL #2):
    - Key from OPENROUTER_API_KEY env var ONLY — never a file, never the repo.
      repr() masks it; it cannot leak through logs.
    - METERED: every call accumulates cost from OpenRouter's LIVE per-model
      pricing (the /models catalog — authoritative; cost.py's PRICING dict
      returns $0 for unknown ids, so the client owns the ledger and feeds an
      optional CostTracker the token counts as a secondary ledger).
    - BUDGET-GATED: a session ceiling (default $0.50) — a call that would
      exceed it raises LLMBudgetExceeded BEFORE spending. Fail-closed.
    - Brain-swap-proof in both directions: model id is config (env
      OPENROUTER_MODEL) or auto-discovered (cheapest free chat model). The
      self-model limb tracks which brain answered; Stage 4's router will sit
      on exactly this ledger.
    - Transport is injected (httpx by default) so every test runs OFFLINE.

=============================================================================
THE FLOW
=============================================================================

STEP 1: ctor reads key/model/budget from env (or args). No network yet.
        |
STEP 2: first __call__: if no model configured, auto-pick a free chat model
        from /models (cached, one fetch per session).
        |
STEP 3: budget pre-gate (projected cost vs ceiling) -> POST /chat/completions
        with retries (429/5xx/network: backoff; other 4xx: raise immediately).
        |
STEP 4: parse choices[0].message.content; meter usage against live pricing;
        update ledger (+ optional CostTracker). Return the text — a plain
        awaitable str, exactly what every Stage 3 surface expects.

=============================================================================
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # standalone-run safety

_BASE_URL = "https://openrouter.ai/api/v1"
_DEFAULT_BUDGET_USD = 0.50
_DEFAULT_TIMEOUT_S = 90.0
_DEFAULT_MAX_RETRIES = 2
_EST_OUTPUT_TOKENS = 600          # conservative pre-gate assumption
_CHARS_PER_TOKEN = 4

# Injected transport: (url, headers, json_payload, timeout_s) -> (status, body_dict)
Transport = Callable[[str, Dict[str, str], Optional[Dict[str, Any]], float],
                     Awaitable[Tuple[int, Dict[str, Any]]]]


class LLMCallError(Exception):
    """The provider returned an unrecoverable error."""


class LLMBudgetExceeded(Exception):
    """The session budget gate refused the call BEFORE spending."""


async def _httpx_transport(url: str, headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]],
                           timeout_s: float) -> Tuple[int, Dict[str, Any]]:
    import httpx
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        if payload is None:
            r = await client.get(url, headers=headers)
        else:
            r = await client.post(url, headers=headers, json=payload)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {"raw": r.text[:2000]}


class OpenRouterClient:
    """An `LLMCall` — async callable: messages in, assistant text out. Metered."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        budget_usd: Optional[float] = _DEFAULT_BUDGET_USD,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        cost_tracker: Optional[Any] = None,
        transport: Optional[Transport] = None,
        base_url: str = _BASE_URL,
    ) -> None:
        self._api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        if not self._api_key:
            raise LLMCallError(
                "No API key. Set OPENROUTER_API_KEY in the environment "
                "(machine-local secret — never commit it).")
        self._model = model or os.environ.get("OPENROUTER_MODEL", "")
        self._budget = budget_usd
        self._timeout = float(timeout_s)
        self._retries = max(0, int(max_retries))
        self._tracker = cost_tracker
        self._transport = transport or _httpx_transport
        self._base = base_url.rstrip("/")
        self._pricing: Optional[Dict[str, Tuple[float, float]]] = None  # id -> ($/tok in, $/tok out)
        self._spend_usd = 0.0
        self._calls = 0

    def __repr__(self) -> str:  # key can never leak through logs/repr
        return (f"OpenRouterClient(model={self._model or '<auto>'}, "
                f"key=***{self._api_key[-4:]}, spend=${self._spend_usd:.4f}, "
                f"calls={self._calls})")

    # ---- properties (the self-model / router ledger seed) -----------------

    @property
    def model(self) -> str:
        return self._model

    @property
    def spend_usd(self) -> float:
        return self._spend_usd

    @property
    def call_count(self) -> int:
        return self._calls

    def ledger_summary(self) -> Dict[str, Any]:
        return {"model": self._model, "calls": self._calls,
                "spend_usd": round(self._spend_usd, 6),
                "budget_usd": self._budget,
                "remaining_usd": (None if self._budget is None
                                  else round(max(0.0, self._budget - self._spend_usd), 6))}

    # ---- catalog ----------------------------------------------------------

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "X-Title": "JARVIS"}

    async def list_models(self) -> List[Dict[str, Any]]:
        status, body = await self._transport(f"{self._base}/models", self._headers(),
                                             None, self._timeout)
        if status != 200:
            raise LLMCallError(f"/models returned {status}: {str(body)[:200]}")
        return body.get("data", [])

    async def _ensure_pricing(self) -> Dict[str, Tuple[float, float]]:
        if self._pricing is None:
            pricing: Dict[str, Tuple[float, float]] = {}
            for m in await self.list_models():
                p = m.get("pricing", {}) or {}
                try:
                    pricing[m.get("id", "")] = (float(p.get("prompt", 0) or 0),
                                                float(p.get("completion", 0) or 0))
                except (TypeError, ValueError):
                    continue
            self._pricing = pricing
        return self._pricing

    # Stealth/preview/media models often speak proprietary tool-call formats
    # (first contact: owl-alpha answered in <longcat_tool_call> markup instead of
    # the JSON our parser requests). Exclude them from auto-pick.
    _AVOID_SUBSTRINGS = ("alpha", "beta", "preview", "clip", "lyria", "owl")

    async def pick_free_model(self) -> str:
        """Cheapest viable default: a $0, MAINSTREAM, instruct-tuned chat model."""
        models = await self.list_models()
        free = [m for m in models
                if float((m.get("pricing", {}) or {}).get("prompt", 1) or 1) == 0.0
                and float((m.get("pricing", {}) or {}).get("completion", 1) or 1) == 0.0]
        if not free:
            raise LLMCallError("No free models in the catalog; set OPENROUTER_MODEL explicitly.")
        safe = [m for m in free
                if not any(s in m.get("id", "").lower() for s in self._AVOID_SUBSTRINGS)]
        pool = safe or free
        instruct = [m for m in pool if "instruct" in m.get("id", "").lower()]
        tier = instruct or pool
        tier.sort(key=lambda m: int(m.get("context_length", 0) or 0), reverse=True)
        self._model = tier[0]["id"]
        return self._model

    # ---- the LLMCall protocol ---------------------------------------------

    async def __call__(self, messages: List[Dict[str, str]]) -> str:
        if not self._model:
            await self.pick_free_model()
        pricing = await self._ensure_pricing()
        in_price, out_price = pricing.get(self._model, (0.0, 0.0))

        est_in_tokens = sum(len(m.get("content", "")) for m in messages) // _CHARS_PER_TOKEN
        projected = self._spend_usd + est_in_tokens * in_price + _EST_OUTPUT_TOKENS * out_price
        if self._budget is not None and projected > self._budget:
            raise LLMBudgetExceeded(
                f"projected ${projected:.4f} > budget ${self._budget:.2f} "
                f"(spent ${self._spend_usd:.4f} over {self._calls} calls)")

        payload = {"model": self._model, "messages": list(messages)}
        last_err = ""
        for attempt in range(self._retries + 1):
            if attempt:
                await asyncio.sleep(0.5 * (3 ** (attempt - 1)))
            try:
                status, body = await self._transport(
                    f"{self._base}/chat/completions", self._headers(), payload, self._timeout)
            except Exception as e:
                last_err = f"transport: {type(e).__name__}: {e}"
                continue
            if status == 200:
                try:
                    text = body["choices"][0]["message"]["content"] or ""
                except (KeyError, IndexError, TypeError):
                    raise LLMCallError(f"malformed response: {str(body)[:300]}")
                if not text.strip() and attempt < self._retries:
                    # Reasoning-channel quirk: some providers return an empty final
                    # channel (all tokens spent in `reasoning`). Burn a retry.
                    last_err = "empty content (reasoning-channel quirk)"
                    continue
                usage = body.get("usage", {}) or {}
                in_tok = int(usage.get("prompt_tokens", est_in_tokens) or 0)
                out_tok = int(usage.get("completion_tokens",
                                        len(text) // _CHARS_PER_TOKEN) or 0)
                self._spend_usd += in_tok * in_price + out_tok * out_price
                self._calls += 1
                if self._tracker is not None:
                    try:
                        self._tracker.record(self._model, in_tok, out_tok)
                    except Exception:
                        pass  # secondary ledger must never break a call
                return text
            if status == 429 or status >= 500:
                last_err = f"HTTP {status}: {str(body)[:200]}"
                continue
            raise LLMCallError(f"HTTP {status}: {str(body)[:300]}")  # other 4xx: no retry
        raise LLMCallError(f"exhausted {self._retries + 1} attempts; last: {last_err}")


def build_llm_call(budget_usd: Optional[float] = _DEFAULT_BUDGET_USD,
                   model: Optional[str] = None,
                   cost_tracker: Optional[Any] = None) -> OpenRouterClient:
    """The one-line factory every surface uses: a ready LLMCall from env config."""
    return OpenRouterClient(model=model, budget_usd=budget_usd, cost_tracker=cost_tracker)


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS (offline — transport injected)
# =============================================================================

def _run_self_test() -> None:
    print("=" * 70)
    print("  llm_client.py -- Smoke Tests (offline, injected transport)")
    print("=" * 70)
    passed = 0
    failed: List[str] = []

    # Env isolation: a real OPENROUTER_MODEL (e.g. from ~/.bashrc) would pre-set
    # the model and silently skip the auto-pick path under test (T9).
    _saved_model_env = os.environ.pop("OPENROUTER_MODEL", None)

    def check(name: str, cond: bool, hint: str = "") -> None:
        nonlocal passed
        if cond:
            passed += 1
        else:
            failed.append(f"FAIL: {name}" + (f" ({hint})" if hint else ""))

    CATALOG = {"data": [
        {"id": "stealth/owl-alpha", "context_length": 1000000,
         "pricing": {"prompt": "0", "completion": "0"}},      # must be excluded
        {"id": "freebie/chat-large-instruct:free", "context_length": 128000,
         "pricing": {"prompt": "0", "completion": "0"}},
        {"id": "freebie/chat-small:free", "context_length": 8000,
         "pricing": {"prompt": "0", "completion": "0"}},
        {"id": "paid/model", "context_length": 200000,
         "pricing": {"prompt": "0.000001", "completion": "0.000002"}},
    ]}

    def make_transport(script: List[Tuple[int, Dict[str, Any]]]):
        calls = {"n": 0, "urls": []}
        async def t(url, headers, payload, timeout):
            calls["urls"].append(url)
            if url.endswith("/models"):
                return 200, CATALOG
            i = min(calls["n"], len(script) - 1)
            calls["n"] += 1
            return script[i]
        return t, calls

    OK = (200, {"choices": [{"message": {"content": "Hello from the model."}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50}})

    async def scenario() -> None:
        nonlocal passed

        # T1: protocol conformance — awaitable str
        t1, _ = make_transport([OK])
        c1 = OpenRouterClient(api_key="sk-test", model="paid/model", transport=t1)
        out = await c1([{"role": "user", "content": "hi"}])
        check("T1 returns assistant text", out == "Hello from the model.")

        # T2: metering from usage x live pricing (100*1e-6 + 50*2e-6 = $0.0002)
        check("T2 spend metered from live pricing",
              abs(c1.spend_usd - 0.0002) < 1e-9, str(c1.spend_usd))
        check("T2b call_count tracked", c1.call_count == 1)

        # T3: budget gate refuses BEFORE spending
        t3, calls3 = make_transport([OK])
        c3 = OpenRouterClient(api_key="sk-test", model="paid/model",
                              budget_usd=0.0000001, transport=t3)
        try:
            await c3([{"role": "user", "content": "x" * 4000}])
            check("T3 budget gate raises", False)
        except LLMBudgetExceeded:
            check("T3 budget gate raises", True)
        check("T3b refused BEFORE any completion call",
              not any(u.endswith("/chat/completions") for u in calls3["urls"]))

        # T4: 500 then success -> retry succeeds
        t4, _ = make_transport([(500, {"error": "boom"}), OK])
        c4 = OpenRouterClient(api_key="sk-test", model="paid/model", transport=t4)
        check("T4 retries 5xx then succeeds",
              await c4([{"role": "user", "content": "hi"}]) == "Hello from the model.")

        # T5: 401 -> immediate raise, no retry
        t5, calls5 = make_transport([(401, {"error": "bad key"})])
        c5 = OpenRouterClient(api_key="sk-test", model="paid/model", transport=t5)
        try:
            await c5([{"role": "user", "content": "hi"}])
            check("T5 4xx raises immediately", False)
        except LLMCallError:
            check("T5 4xx raises immediately", True)
        check("T5b no retry on 4xx",
              sum(1 for u in calls5["urls"] if u.endswith("/chat/completions")) == 1)

        # T6: 429 retried
        t6, _ = make_transport([(429, {"error": "slow down"}), OK])
        c6 = OpenRouterClient(api_key="sk-test", model="paid/model", transport=t6)
        check("T6 429 retried", await c6([{"role": "user", "content": "hi"}]) != "")

        # T7: repr masks the key
        check("T7 repr masks key", "sk-test" not in repr(c1) and "***" in repr(c1))

        # T8: CostTracker pass-through gets token counts
        class FakeTracker:
            def __init__(self): self.recs = []
            def record(self, model, input_tokens, output_tokens, cached_tokens=0):
                self.recs.append((model, input_tokens, output_tokens))
        ft = FakeTracker()
        t8, _ = make_transport([OK])
        c8 = OpenRouterClient(api_key="sk-test", model="paid/model",
                              cost_tracker=ft, transport=t8)
        await c8([{"role": "user", "content": "hi"}])
        check("T8 CostTracker fed tokens", ft.recs == [("paid/model", 100, 50)], str(ft.recs))

        # T9: auto-pick prefers mainstream instruct free model; excludes stealth/alpha
        t9, _ = make_transport([OK])
        c9 = OpenRouterClient(api_key="sk-test", transport=t9)  # no model
        await c9([{"role": "user", "content": "hi"}])
        check("T9 auto-picks the instruct free model",
              c9.model == "freebie/chat-large-instruct:free", c9.model)
        check("T9b free model spends $0", c9.spend_usd == 0.0)
        check("T9c stealth/alpha excluded despite biggest context", "alpha" not in c9.model)

        # T10: malformed success body -> clear error
        t10, _ = make_transport([(200, {"unexpected": True})])
        c10 = OpenRouterClient(api_key="sk-test", model="paid/model", transport=t10)
        try:
            await c10([{"role": "user", "content": "hi"}])
            check("T10 malformed body raises LLMCallError", False)
        except LLMCallError:
            check("T10 malformed body raises LLMCallError", True)

        # T11: ledger summary shape
        s = c1.ledger_summary()
        check("T11 ledger summary", s["calls"] == 1 and s["budget_usd"] == _DEFAULT_BUDGET_USD)

    # T12: missing key -> clear construction error
    old = os.environ.pop("OPENROUTER_API_KEY", None)
    try:
        OpenRouterClient(api_key="")
        failed.append("FAIL: T12 missing key should raise")
    except LLMCallError:
        passed += 1
    finally:
        if old:
            os.environ["OPENROUTER_API_KEY"] = old

    asyncio.run(scenario())

    if _saved_model_env is not None:
        os.environ["OPENROUTER_MODEL"] = _saved_model_env

    total = passed + len(failed)
    print(f"\n  Passed: {passed}/{total}")
    if failed:
        for f_ in failed:
            print(f"  {f_}")
        print("=" * 70)
        raise SystemExit(1)
    print(f"  All {total} llm_client smoke tests passed.")
    print("=" * 70)


async def _live_ping() -> None:
    client = build_llm_call(budget_usd=0.05)
    models = await client.list_models()
    chosen = await client.pick_free_model()
    print(f"  catalog        : {len(models)} models")
    print(f"  auto-picked    : {chosen} (free tier)")
    text = await client([{"role": "user",
                          "content": "Reply with exactly: JARVIS first light confirmed."}])
    print(f"  model said     : {text.strip()[:120]}")
    print(f"  ledger         : {client.ledger_summary()}")


async def _first_thought() -> None:
    """THE moment: the Final Boss (Mind) thinking on a REAL model with a REAL tool."""
    from jarvis_core.agent.mind import Mind
    from jarvis_core.agent.tools.calc import CalculatorTool

    client = build_llm_call(budget_usd=0.10)
    if not client.model:
        await client.pick_free_model()
    # MIRROR-lite off: free-tier models follow the plain ReAct format reliably but
    # bury their output inside the layered reflection protocol (verified live —
    # content came back empty after mirror-stripping). Per-model protocol routing
    # is exactly Stage 4's job; First Light proves the loop, not the reflection.
    mind = Mind(
        llm_call=client,
        tools={"calculator": CalculatorTool()},
        max_iterations=8,
        enable_mirror=False,
        enable_monitor=True,
        allow_replan=True,
    )
    task = ("You MUST use the calculator tool (never compute mentally) to evaluate "
            "7919 * 6841 - 123456, then state the final number plainly.")
    expected = "54050423"  # 7919*6841=54173879; -123456 -> 54050423
    print(f"  brain          : {client.model}")
    print(f"  task           : {task}")
    result = await mind.solve(task)
    print(f"  tool calls     : {[(tc.name, tr.output) for tc, tr in result.react.tool_calls]}")
    print(f"  iterations     : {result.react.iterations_used}")
    print(f"  answer         : {result.answer.strip()[:300]}")
    print(f"  criteria       : {result.criteria_met}")
    print(f"  ledger         : {client.ledger_summary()}")
    ok = expected in result.answer.replace(",", "")
    used_tool = len(result.react.tool_calls) >= 1
    print(f"\n  >>> FIRST REAL THOUGHT: "
          f"{'CORRECT (' + expected + ')' if ok else 'completed — verify answer above'}"
          f"{' via REAL TOOL CALL' if used_tool else ' (no tool call)'} <<<")


def main() -> int:
    # The interactive `--ask` entry point moved to jarvis_core.brain.orchestrator
    # (Stage 4.0.4): the spine boot-assembles the Mind there; brain composes
    # agent, never the reverse.
    p = argparse.ArgumentParser(description="OpenRouter LLM adapter (First Light)")
    p.add_argument("--live", action="store_true", help="Real ping (needs OPENROUTER_API_KEY)")
    p.add_argument("--first-thought", action="store_true",
                   help="Live Final Boss: Mind + real model + calculator tool")
    args = p.parse_args()
    if args.live:
        asyncio.run(_live_ping())
        return 0
    if args.first_thought:
        asyncio.run(_first_thought())
        return 0
    _run_self_test()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
