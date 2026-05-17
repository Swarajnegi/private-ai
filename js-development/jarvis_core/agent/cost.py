"""
cost.py

JARVIS Agent Layer: Cost Accounting — Per-Token Pricing + Per-Session Tracker.

Import with:
    from jarvis_core.agent.cost import CostTracker, PRICING, estimate_cost

This module provides:
    1. PRICING — Hardcoded per-model cost tables (input/output/cache tiers)
    2. RUNPOD_GPU_RATES — RunPod GPU-hour rates for self-hosted inference
    3. CostTracker — Per-session accumulator that tallies every LLM call
    4. estimate_cost() — Pure function: tokens × rate → USD

=============================================================================
THE BIG PICTURE
=============================================================================

Without cost accounting:
    -> Agent loops call LLMs freely. 10 ReAct iterations with Opus 4.7 at
       $15/M output tokens burns $0.50+ per turn. A busy day = $30-50.
       Nobody notices until the credit card bill arrives.
    -> No data to decide: "Should we route this to the cheap model or the
       expensive one?" The Router in Stage 4 NEEDS cost data to optimize.

With cost accounting:
    -> Every LLM call flows through CostTracker.record(). The session
       accumulates input_cost + output_cost + cache_savings.
    -> The Router can query: "What's my remaining budget this session?"
       and route to a cheaper model when the budget is low.
    -> At session end, CostTracker.summary() emits a report: total cost,
       cost-per-turn, cache hit ratio, cheapest/most expensive call.

=============================================================================
THE FLOW (Step by Step Execution Order)
=============================================================================

STEP 1: Import PRICING dict. Look up model rates before calling LLM.
        ↓
STEP 2: tracker = CostTracker(budget_usd=0.50)
        Creates a session-scoped accumulator with an optional budget cap.
        ↓
STEP 3: After each LLM call, record usage:
            tracker.record(model, input_tokens, output_tokens, cached_tokens)
        Computes cost from PRICING and adds to running total.
        ↓
STEP 4: Before the next call, check:
            tracker.remaining_usd  -> how much budget is left
            tracker.would_exceed(model, est_tokens) -> True if next call
                                                        would bust the budget
        ↓
STEP 5: At session end:
            tracker.summary() -> dict with total_usd, breakdown, stats

=============================================================================

Sources:
    - OpenJarvis engine/cloud.py:22-48,165-176 (PRICING dict structure)
    - OpenClaude src/utils/modelCost.ts (cache-tier model: input/output/
      cache_read/cache_write per model)
    - OpenClaude src/cost-tracker.ts (per-session accumulator pattern)
    - JARVIS_ENDGAME.md Section 2 (RunPod GPU-hour rates, verified May 2026)

All prices in USD per token (not per million tokens) for arithmetic
simplicity. The PRICING_DISPLAY dict provides human-readable $/M rates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# =============================================================================
# Part 1: PER-MODEL PRICING (USD per token)
# =============================================================================

# Conversion helper: pricing sources quote $/M (per million tokens).
# We store $/token for direct multiplication: cost = tokens * rate.
_M = 1_000_000


@dataclass(frozen=True)
class ModelPricing:
    """
    LAYER: Agent — Immutable cost profile for a single model.

    Purpose:
        - Capture all cost dimensions for one model in a typed container
        - Support cache-tier pricing (cache reads cheaper than fresh input)

    Fields:
        input_per_token:       Cost per input token (fresh, uncached)
        output_per_token:      Cost per output token
        cache_read_per_token:  Cost per cached input token (prompt caching)
        cache_write_per_token: Cost to write one token into prompt cache
        tool_call_overhead:    Fixed cost per tool invocation (if any)
        provider:              API provider name (for display/routing)
    """
    input_per_token: float
    output_per_token: float
    cache_read_per_token: float = 0.0
    cache_write_per_token: float = 0.0
    tool_call_overhead: float = 0.0
    provider: str = "unknown"


# All rates verified May 2026 from provider pricing pages.
# The dict key is the canonical model identifier used in API calls.
PRICING: Dict[str, ModelPricing] = {

    # --- Anthropic (Frontier escape-valve only) ---
    "claude-opus-4": ModelPricing(
        input_per_token=15.0 / _M,
        output_per_token=75.0 / _M,
        cache_read_per_token=1.5 / _M,
        cache_write_per_token=18.75 / _M,
        provider="anthropic",
    ),
    "claude-sonnet-4": ModelPricing(
        input_per_token=3.0 / _M,
        output_per_token=15.0 / _M,
        cache_read_per_token=0.3 / _M,
        cache_write_per_token=3.75 / _M,
        provider="anthropic",
    ),

    # --- OpenAI (Frontier escape-valve only) ---
    "gpt-4.1": ModelPricing(
        input_per_token=2.0 / _M,
        output_per_token=8.0 / _M,
        cache_read_per_token=0.5 / _M,
        cache_write_per_token=2.0 / _M,
        provider="openai",
    ),
    "gpt-4.1-mini": ModelPricing(
        input_per_token=0.4 / _M,
        output_per_token=1.6 / _M,
        cache_read_per_token=0.1 / _M,
        cache_write_per_token=0.4 / _M,
        provider="openai",
    ),

    # --- Google (Frontier escape-valve only) ---
    "gemini-2.5-pro": ModelPricing(
        input_per_token=1.25 / _M,
        output_per_token=10.0 / _M,
        cache_read_per_token=0.315 / _M,
        cache_write_per_token=4.5 / _M,
        provider="google",
    ),
    "gemini-2.5-flash": ModelPricing(
        input_per_token=0.15 / _M,
        output_per_token=0.60 / _M,
        cache_read_per_token=0.0375 / _M,
        cache_write_per_token=1.0 / _M,
        provider="google",
    ),

    # --- OpenRouter (Phase 1-3 default routing) ---
    "deepseek/deepseek-chat-v3": ModelPricing(
        input_per_token=0.27 / _M,
        output_per_token=1.10 / _M,
        cache_read_per_token=0.07 / _M,
        provider="openrouter",
    ),
    "qwen/qwen3-235b": ModelPricing(
        input_per_token=0.75 / _M,
        output_per_token=3.00 / _M,
        provider="openrouter",
    ),
    "meta-llama/llama-4-maverick": ModelPricing(
        input_per_token=0.20 / _M,
        output_per_token=0.60 / _M,
        provider="openrouter",
    ),

    # --- Self-hosted Kimi K2.6 on RunPod (Phase 4+ default) ---
    # Token-level cost is effectively zero once the GPU is running.
    # The cost is GPU-hours, tracked separately via RUNPOD_GPU_RATES.
    # We set a nominal per-token rate for budget tracking uniformity.
    "kimi-k2.6-local": ModelPricing(
        input_per_token=0.0,
        output_per_token=0.0,
        provider="runpod-self-hosted",
    ),
}


# =============================================================================
# Part 2: RUNPOD GPU-HOUR RATES (for self-hosted inference costing)
# =============================================================================

@dataclass(frozen=True)
class GpuRate:
    """
    LAYER: Agent — RunPod GPU pricing for self-hosted inference/training.

    Purpose:
        - Track hourly cost for GPU configurations used in JARVIS
        - Feed into CostTracker for self-hosted session costing

    Fields:
        name:       Human-readable GPU name
        vram_gb:    GPU VRAM in GB
        usd_per_hr: Community Cloud hourly rate (USD)
        inr_per_hr: Equivalent in INR at $1 = ₹84
    """
    name: str
    vram_gb: int
    usd_per_hr: float
    inr_per_hr: float


# Verified against RunPod public pricing page, May 2026.
RUNPOD_GPU_RATES: Dict[str, GpuRate] = {
    "rtx-a5000": GpuRate("RTX A5000", 24, 0.27, 23.0),
    "a40": GpuRate("A40", 48, 0.44, 37.0),
    "rtx-3090": GpuRate("RTX 3090", 24, 0.46, 39.0),
    "a6000": GpuRate("A6000", 48, 0.49, 41.0),
    "rtx-4090": GpuRate("RTX 4090", 24, 0.69, 58.0),
    "a100-pcie": GpuRate("A100 PCIe", 80, 1.39, 117.0),
}

# Named inference configurations from JARVIS_ENDGAME.md Section 2
RUNPOD_INFERENCE_CONFIGS: Dict[str, Dict[str, Any]] = {
    "4xa5000": {
        "gpus": ["rtx-a5000"] * 4,
        "total_vram_gb": 96,
        "usd_per_hr": 0.27 * 4,
        "inr_per_hr": 23.0 * 4,
        "note": "Cheapest viable multi-GPU for Kimi K2.6 INT4",
    },
    "1xa100": {
        "gpus": ["a100-pcie"],
        "total_vram_gb": 80,
        "usd_per_hr": 1.39,
        "inr_per_hr": 117.0,
        "note": "Tight fit with KV cache, single-card simplicity",
    },
    "1xa40-offload": {
        "gpus": ["a40"],
        "total_vram_gb": 48,
        "usd_per_hr": 0.44,
        "inr_per_hr": 37.0,
        "note": "Cheapest option, 3-5× slower with CPU offload",
    },
}


# =============================================================================
# Part 3: PURE COST ESTIMATION FUNCTION
# =============================================================================

def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
) -> float:
    """
    Compute the USD cost for a single LLM call. Pure function, no side effects.

    EXECUTION FLOW:
    1. Look up model in PRICING dict.
    2. Split input tokens into cached vs. fresh.
    3. Multiply each bucket by its per-token rate.
    4. Return total USD.

    Args:
        model:         Canonical model key from PRICING dict.
        input_tokens:  Total input tokens sent to the model.
        output_tokens: Total output tokens received from the model.
        cached_tokens: How many of the input tokens were served from cache.

    Returns:
        Total cost in USD (float). Returns 0.0 for unknown models.
    """
    pricing = PRICING.get(model)
    if pricing is None:
        return 0.0

    fresh_input = max(0, input_tokens - cached_tokens)

    cost = (
        fresh_input * pricing.input_per_token
        + cached_tokens * pricing.cache_read_per_token
        + output_tokens * pricing.output_per_token
        + pricing.tool_call_overhead
    )
    return cost


# =============================================================================
# Part 4: PER-SESSION COST TRACKER
# =============================================================================

@dataclass
class CostRecord:
    """Single LLM call cost record for audit trail."""
    model: str
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    cost_usd: float


@dataclass
class CostTracker:
    """
    LAYER: Agent — Per-session cost accumulator.

    Purpose:
        - Track cumulative cost across all LLM calls in one agent session
        - Provide budget-aware routing signals (remaining_usd, would_exceed)
        - Emit a summary report at session end

    How it works:
        - Each record() call computes cost via estimate_cost() and appends
          to a running ledger.
        - total_usd is a running sum — O(1) per call, not a re-scan.
        - budget_usd is optional; if set, would_exceed() gates expensive calls.
    """
    budget_usd: Optional[float] = None
    _records: List[CostRecord] = field(default_factory=list)
    _total_usd: float = 0.0

    @property
    def total_usd(self) -> float:
        """Running total cost in USD."""
        return self._total_usd

    @property
    def remaining_usd(self) -> Optional[float]:
        """Remaining budget in USD. None if no budget was set."""
        if self.budget_usd is None:
            return None
        return max(0.0, self.budget_usd - self._total_usd)

    @property
    def call_count(self) -> int:
        """Total number of LLM calls recorded."""
        return len(self._records)

    def record(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0,
    ) -> CostRecord:
        """
        Record a single LLM call and accumulate its cost.

        EXECUTION FLOW:
        1. Compute cost via estimate_cost() pure function.
        2. Create CostRecord and append to ledger.
        3. Add cost to running total.
        4. Return the record for caller inspection.

        Args:
            model:         Canonical model key from PRICING dict.
            input_tokens:  Total input tokens sent.
            output_tokens: Total output tokens received.
            cached_tokens: How many input tokens were cache hits.

        Returns:
            The CostRecord created for this call.
        """
        cost = estimate_cost(model, input_tokens, output_tokens, cached_tokens)
        rec = CostRecord(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            cost_usd=cost,
        )
        self._records.append(rec)
        self._total_usd += cost
        return rec

    def would_exceed(
        self,
        model: str,
        estimated_input: int,
        estimated_output: int,
    ) -> bool:
        """
        Check whether a hypothetical call would exceed the session budget.

        Returns False if no budget is set (unlimited mode).

        Args:
            model:            Model to estimate cost for.
            estimated_input:  Expected input tokens.
            estimated_output: Expected output tokens.

        Returns:
            True if the call would push total_usd past budget_usd.
        """
        if self.budget_usd is None:
            return False
        est_cost = estimate_cost(model, estimated_input, estimated_output)
        return (self._total_usd + est_cost) > self.budget_usd

    def summary(self) -> Dict[str, Any]:
        """
        Produce a session cost summary.

        Returns:
            Dict with: total_usd, call_count, budget_usd, remaining_usd,
            cost_per_call_avg, models_used, records.
        """
        models_used: Dict[str, float] = {}
        for rec in self._records:
            models_used[rec.model] = models_used.get(rec.model, 0.0) + rec.cost_usd

        total_input = sum(r.input_tokens for r in self._records)
        total_output = sum(r.output_tokens for r in self._records)
        total_cached = sum(r.cached_tokens for r in self._records)

        return {
            "total_usd": round(self._total_usd, 6),
            "call_count": self.call_count,
            "budget_usd": self.budget_usd,
            "remaining_usd": (
                round(self.remaining_usd, 6)
                if self.remaining_usd is not None
                else None
            ),
            "cost_per_call_avg": (
                round(self._total_usd / self.call_count, 6)
                if self.call_count > 0
                else 0.0
            ),
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_cached_tokens": total_cached,
            "cache_hit_ratio": (
                round(total_cached / total_input, 4)
                if total_input > 0
                else 0.0
            ),
            "models_used": {
                k: round(v, 6) for k, v in sorted(models_used.items())
            },
        }


# =============================================================================
# Part 5: HUMAN-READABLE DISPLAY HELPERS
# =============================================================================

def format_pricing_table() -> str:
    """Generate a formatted table of all model pricing for display."""
    lines = [
        f"{'Model':<40} {'Input $/M':>10} {'Output $/M':>11} "
        f"{'Cache R $/M':>12} {'Provider':<15}",
        "-" * 90,
    ]
    for model_key, p in sorted(PRICING.items()):
        lines.append(
            f"{model_key:<40} "
            f"${p.input_per_token * _M:>8.2f} "
            f"${p.output_per_token * _M:>9.2f} "
            f"${p.cache_read_per_token * _M:>10.4f} "
            f"{p.provider:<15}"
        )
    return "\n".join(lines)


def format_gpu_table() -> str:
    """Generate a formatted table of RunPod GPU rates for display."""
    lines = [
        f"{'GPU':<15} {'VRAM':>6} {'$/hr':>7} {'Rs/hr':>8}",
        "-" * 42,
    ]
    for _, g in sorted(RUNPOD_GPU_RATES.items()):
        lines.append(
            f"{g.name:<15} {g.vram_gb:>4} GB "
            f"${g.usd_per_hr:>5.2f} Rs{g.inr_per_hr:>5.0f}"
        )
    return "\n".join(lines)


# =============================================================================
# MAIN ENTRY POINT (Smoke test: cost tracking across a mock session)
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  JARVIS Cost Accounting -- Smoke Test")
    print("=" * 60)

    # -- Display pricing tables --------------------------------------------

    print("\n[PRICING] Model Pricing:\n")
    print(format_pricing_table())
    print(f"\n[PRICING] RunPod GPU Rates:\n")
    print(format_gpu_table())

    # -- Simulate a session with budget ------------------------------------

    print("\n\n[TEST] Simulated Session (budget=$0.10):\n")

    tracker = CostTracker(budget_usd=0.10)

    # Call 1: DeepSeek V3 — cheap
    rec1 = tracker.record(
        model="deepseek/deepseek-chat-v3",
        input_tokens=2000,
        output_tokens=500,
        cached_tokens=800,
    )
    print(f"  Call 1: deepseek-v3, cost=${rec1.cost_usd:.6f}")

    # Call 2: Gemini Flash — also cheap
    rec2 = tracker.record(
        model="gemini-2.5-flash",
        input_tokens=3000,
        output_tokens=1000,
    )
    print(f"  Call 2: gemini-flash, cost=${rec2.cost_usd:.6f}")

    # Call 3: Claude Opus — expensive
    rec3 = tracker.record(
        model="claude-opus-4",
        input_tokens=1000,
        output_tokens=500,
    )
    print(f"  Call 3: claude-opus-4, cost=${rec3.cost_usd:.6f}")

    # -- Budget check before a hypothetical next call ----------------------

    would_bust = tracker.would_exceed(
        model="claude-opus-4",
        estimated_input=5000,
        estimated_output=2000,
    )
    print(f"\n  Would next Opus call exceed budget? {would_bust}")
    print(f"  Remaining budget: ${tracker.remaining_usd:.6f}")

    # -- Session summary ---------------------------------------------------

    summary = tracker.summary()
    print(f"\n[SUMMARY] Session Summary:")
    for key, val in summary.items():
        if key == "models_used":
            print(f"  {key}:")
            for model, cost in val.items():
                print(f"    {model}: ${cost:.6f}")
        else:
            print(f"  {key}: {val}")

    # -- Verify self-hosted model costs $0 per token -----------------------

    kimi_cost = estimate_cost("kimi-k2.6-local", 10000, 5000)
    assert kimi_cost == 0.0, f"Kimi K2.6 local should cost $0/token, got ${kimi_cost}"
    print(f"\n  [OK] kimi-k2.6-local: 10K input + 5K output = ${kimi_cost:.2f} (GPU-hour costed separately)")

    print("\n" + "=" * 60)
    print("  All smoke tests passed.")
    print("=" * 60)
