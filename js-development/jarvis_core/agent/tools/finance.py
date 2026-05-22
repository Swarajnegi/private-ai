"""
finance.py

JARVIS Agent Layer: Finance callable tools (Category A — Callable).

Import-time registration:
    @Tool.register("portfolio_state")
    @Tool.register("trigger_monitor")
    @Tool.register("incentive_planner")

LAYER: Agent (Tools)

=============================================================================
THE BIG PICTURE
=============================================================================

Stage 3.2 contract: these three tools READ from `jarvis_data/Finance/strategy.md`
(the canonical capital-allocation document) and return structured slices of it.

Stage 5+ extension: each tool will be EXTENDED with live broker integration
(Groww + INDmoney + bank-balance APIs). The current contract is forward-compatible
— the agent invokes the SAME tool name; the dispatcher swaps in the live-data
backend without changing tool signatures.

WHY strategy.md as the source of truth (rather than encoded rules in code):
    1. The user maintains strategy.md by hand (v2.0 -> v2.5 -> v2.7 versions
       captured in KB Decisions L250 / L278 / L279 / etc.). Changes happen
       weekly; encoding rules in Python would require constant code churn.
    2. The markdown format is human-readable. The agent can SHOW the user
       the relevant section verbatim — no risk of state drift between what
       the tool reports and what the doc says.
    3. KB tag `finance-strategy` already exists for cross-referencing decisions
       against the doc.

WHY no live broker wiring at Stage 3.2:
    - Live wiring needs auth flows (OAuth for Groww, API keys for INDmoney)
      which are Stage 6 work.
    - The trigger_monitor + incentive_planner logic is the same regardless
      of live data — they just need market_state + amount as input.
    - portfolio_state returns the PLAN (structural state); the live balances
      come later. The plan rarely lies; balances do (rounding, settlements).

=============================================================================
THE FLOW
=============================================================================

portfolio_state:
    STEP 1: Read strategy.md (cache on first call).
    STEP 2: Extract version (regex on "v\\d+\\.\\d+").
    STEP 3: Extract "Current Allocation" / "Allocation" section text.
    STEP 4: Return {version, allocation_text, full_strategy_preview}.

trigger_monitor (callable form):
    STEP 1: Read strategy.md.
    STEP 2: Extract "Triggers" section.
    STEP 3: Parse line-items into structured rules where possible
            (heuristic: bullet points + colons).
    STEP 4: If caller provides market_state dict, evaluate which rules fire
            via simple key-comparison.
    STEP 5: Return {triggers_found, fired, market_state_received}.

incentive_planner:
    STEP 1: Read strategy.md.
    STEP 2: Extract "Incentive Foundation" / "Incentive" section.
    STEP 3: Caller provides {amount, date_iso}; tool surfaces the section
            text + caller-input context for the agent to reason over.
    STEP 4: Return {amount_inr, date, plan_text, parsed_allocations}.

=============================================================================
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import Field

from jarvis_core.agent.tool import Tool, ToolInput, ToolResult
from jarvis_core.config import JARVIS_ROOT


DEFAULT_STRATEGY_PATH: Path = JARVIS_ROOT / "jarvis_data" / "Finance" / "strategy.md"

# Section header regexes — case-insensitive, accept ##/###, partial matches.
_SECTION_RE_ALLOCATION = re.compile(
    r"(?im)^#{1,4}\s+.*(?:allocation|portfolio|holdings).*$"
)
_SECTION_RE_TRIGGERS = re.compile(
    r"(?im)^#{1,4}\s+.*(?:trigger|exit\s+rule).*$"
)
_SECTION_RE_INCENTIVE = re.compile(
    r"(?im)^#{1,4}\s+.*(?:incentive|inflow|deployment|foundation).*$"
)
_VERSION_RE = re.compile(r"v(\d+\.\d+)")


def _extract_section(content: str, header_re: re.Pattern[str]) -> str:
    """Find first header matching `header_re`, return text up to next header.
    Returns empty string if no header matched.
    """
    match = header_re.search(content)
    if not match:
        return ""
    start = match.end()
    # Find next header line at the same or shallower level
    next_match = re.search(r"^#{1,4}\s+", content[start:], re.MULTILINE)
    end = start + next_match.start() if next_match else len(content)
    return content[start:end].strip()


# =============================================================================
# Part 1: SHARED BASE (strategy.md DI + cache)
# =============================================================================

class FinanceToolBase(Tool):
    """Shared base: strategy.md path DI + per-instance content cache."""

    def __init__(self, strategy_path: Optional[Path] = None) -> None:
        self._strategy_path: Path = strategy_path or DEFAULT_STRATEGY_PATH
        self._strategy_cache: Optional[str] = None

    def _read_strategy(self) -> str:
        if self._strategy_cache is None:
            try:
                self._strategy_cache = self._strategy_path.read_text(encoding="utf-8")
            except FileNotFoundError as e:
                raise RuntimeError(
                    f"Finance/strategy.md not found at {self._strategy_path}. "
                    f"This is the canonical capital-allocation doc — re-create or fix path."
                ) from e
        return self._strategy_cache

    def _strategy_version(self, content: str) -> str:
        m = _VERSION_RE.search(content)
        return m.group(1) if m else "unknown"


# =============================================================================
# Part 2: TOOL 1 — portfolio_state
# =============================================================================

class PortfolioStateInput(ToolInput):
    preview_chars: int = Field(
        default=2000, ge=200, le=10000,
        description="Max chars of strategy.md to include in the preview.",
    )


@Tool.register("portfolio_state")
class PortfolioStateTool(FinanceToolBase):
    """Return structured allocation plan from Finance/strategy.md (Stage 3.2 stub; Stage 5+ extends to live broker APIs)."""

    name = "portfolio_state"
    description = (
        "Return the structured allocation plan from Finance/strategy.md: "
        "version + allocation section + preview of full strategy. Stage 3.2 "
        "is a strategy-only stub; Stage 5+ extension wires live broker APIs "
        "(Groww + INDmoney + bank balances) to return actual position values. "
        "The strategy-vs-live split is intentional — the plan rarely lies; "
        "live balances drift on settlements/rounding."
    )
    input_schema = PortfolioStateInput

    @property
    def is_concurrency_safe(self) -> bool:
        return True

    async def invoke(self, tool_input: PortfolioStateInput) -> ToolResult:
        try:
            content = self._read_strategy()
        except RuntimeError as e:
            return ToolResult(error=str(e))

        version = self._strategy_version(content)
        allocation_text = _extract_section(content, _SECTION_RE_ALLOCATION)

        return ToolResult(output={
            "version": version,
            "strategy_path": str(self._strategy_path),
            "allocation_text": allocation_text,
            "preview": content[: tool_input.preview_chars],
            "total_strategy_chars": len(content),
            "stage_note": (
                "Stage 3.2: returns strategy.md slices (the PLAN). "
                "Stage 5+ extension will add live_balances dict via broker APIs."
            ),
        })


# =============================================================================
# Part 3: TOOL 2 — trigger_monitor
# =============================================================================

class TriggerMonitorInput(ToolInput):
    market_state: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Optional dict of current market state values to compare against "
            "strategy.md triggers. Keys/values are caller-defined — typical "
            "examples: {'NPI_trailing_1yr_pct': 8.5, 'RIL_listing_pop_x': 1.6, "
            "'AVGO_pct_drawdown_from_entry': -22}."
        ),
    )


@Tool.register("trigger_monitor")
class TriggerMonitorTool(FinanceToolBase):
    """Parse Finance/strategy.md trigger section + optionally evaluate against current market_state."""

    name = "trigger_monitor"
    description = (
        "Surface the trigger conditions from Finance/strategy.md (RIL exit, "
        "NPI sunset, AVGO drawdown alerts, etc.) and optionally evaluate them "
        "against a current market_state dict. Returns the raw trigger text "
        "plus a structured list of bullet-form triggers parsed heuristically. "
        "Stage 5+ extension will use structured trigger schemas + live market "
        "feeds instead of dict input."
    )
    input_schema = TriggerMonitorInput

    @property
    def is_concurrency_safe(self) -> bool:
        return True

    async def invoke(self, tool_input: TriggerMonitorInput) -> ToolResult:
        try:
            content = self._read_strategy()
        except RuntimeError as e:
            return ToolResult(error=str(e))

        trigger_text = _extract_section(content, _SECTION_RE_TRIGGERS)
        bullet_triggers = _parse_bullet_rules(trigger_text)

        return ToolResult(output={
            "trigger_text": trigger_text,
            "bullet_triggers": bullet_triggers,
            "n_triggers_parsed": len(bullet_triggers),
            "market_state_received": tool_input.market_state,
            "fired": [],  # Stage 3.2 stub — Stage 5+ wires structured evaluation
            "stage_note": (
                "Stage 3.2: surfaces trigger text + heuristic parse. "
                "Stage 5+ extension adds structured trigger schemas + live "
                "market-feed evaluation (currently the 'fired' field is empty)."
            ),
        })


def _parse_bullet_rules(text: str) -> List[Dict[str, str]]:
    """Extract bullet-list trigger rules from strategy section text.
    Heuristic: lines starting with `-`, `*`, or `\\d+\\.` followed by content.
    """
    if not text:
        return []
    bullets: List[Dict[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        m = re.match(r"^(?:[-*]|\d+\.)\s+(.+)$", stripped)
        if not m:
            continue
        body = m.group(1).strip()
        # If body looks like "X: Y", split into rule_name + condition
        colon_split = body.split(":", 1)
        if len(colon_split) == 2:
            bullets.append({
                "rule": colon_split[0].strip(),
                "condition": colon_split[1].strip(),
            })
        else:
            bullets.append({"rule": body, "condition": ""})
    return bullets


# =============================================================================
# Part 4: TOOL 3 — incentive_planner
# =============================================================================

class IncentivePlannerInput(ToolInput):
    amount: float = Field(gt=0, description="Inflow amount in INR.")
    date_iso: str = Field(
        description="Inflow date in ISO format (YYYY-MM-DD).",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    )


@Tool.register("incentive_planner")
class IncentivePlannerTool(FinanceToolBase):
    """Surface strategy.md incentive deployment rules for a known upcoming inflow."""

    name = "incentive_planner"
    description = (
        "Given a known upcoming inflow (e.g., Sept incentive Rs 87.5K, March "
        "2027 incentive), surface the relevant deployment rules from "
        "Finance/strategy.md. Returns the incentive section text + a structured "
        "list of allocation bullets parsed heuristically. Removes the "
        "decision-when-stressed moment by pre-loading the plan before cash "
        "actually hits. Stage 5+ extension returns exact ₹-by-₹ allocations."
    )
    input_schema = IncentivePlannerInput

    @property
    def is_concurrency_safe(self) -> bool:
        return True

    async def invoke(self, tool_input: IncentivePlannerInput) -> ToolResult:
        try:
            content = self._read_strategy()
        except RuntimeError as e:
            return ToolResult(error=str(e))

        plan_text = _extract_section(content, _SECTION_RE_INCENTIVE)
        bullet_allocations = _parse_bullet_rules(plan_text)

        return ToolResult(output={
            "amount_inr": tool_input.amount,
            "date": tool_input.date_iso,
            "plan_text": plan_text,
            "bullet_allocations": bullet_allocations,
            "plan_section_found": bool(plan_text),
            "stage_note": (
                "Stage 3.2: surfaces strategy.md incentive section + heuristic "
                "bullet parse. Stage 5+ extension returns exact instrument-by-"
                "instrument allocations computed from the inflow amount and "
                "structured rules in strategy.md."
            ),
        })


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS  (synthetic strategy.md, no live data)
# =============================================================================

if __name__ == "__main__":
    import asyncio
    import tempfile
    from jarvis_core.agent.tool import safe_invoke

    print("=" * 70)
    print("  finance tools — smoke tests (synthetic strategy.md)")
    print("=" * 70)

    FAKE_STRATEGY = """# Finance Strategy v2.7

## Identity
Capital allocation plan for Swaraj. Phased architecture.

## Current Allocation
- NVIDIA SIP: Rs 5K/mo via INDmoney
- AVGO single-stock: Rs 5K/mo via INDmoney
- 4 Indian SIPs: Rs 19.5K/mo (Nippon Power & Infra, Parag Parikh, etc.)
- Liquid Fund: Rs 3K/mo

## Triggers
- RIL exit: listing-day pop >= 1.5x OR 3mo post-listing
- NPI sunset: 24mo OR trailing-1yr < 12%
- AVGO drawdown alert: -25% from entry
- General rebalance: annual in March

## Incentive Foundation
- Sept Rs 87.5K incentive:
  * Rs 50K to liquid fund (emergency buffer)
  * Rs 8K to individual health insurance
  * Rs 500 to PPF
  * Rs 29K STP into VOO/QQQM (US equity ramp)
- March 2027 Rs 49.5K incentive:
  * Rs 49.5K lump sum into XLK (US tech ETF)
"""

    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(FAKE_STRATEGY)
        strategy_path = Path(f.name)

    async def run() -> None:
        passed = 0
        failed: List[str] = []

        def check(name: str, cond: bool, hint: str = "") -> None:
            nonlocal passed
            if cond:
                passed += 1
            else:
                failed.append(f"FAIL: {name}" + (f" ({hint})" if hint else ""))

        # -- portfolio_state --------------------------------------------
        ps = PortfolioStateTool(strategy_path=strategy_path)
        r1 = await safe_invoke(ps, {})
        check("PS1 success", r1.is_success, hint=str(r1.error))
        check("PS1 version extracted", r1.is_success and r1.output["version"] == "2.7")
        check("PS1 allocation text found",
              r1.is_success and "NVIDIA" in r1.output["allocation_text"])
        check("PS1 preview length capped",
              r1.is_success and len(r1.output["preview"]) <= 2000)
        check("PS1 stage_note present",
              r1.is_success and "Stage 3.2" in r1.output["stage_note"])

        # Missing strategy file
        ps_missing = PortfolioStateTool(strategy_path=Path("/no/such/file.md"))
        r2 = await safe_invoke(ps_missing, {})
        check("PS2 missing strategy -> clean error",
              r2.is_error and "not found" in r2.error.lower())

        # -- trigger_monitor --------------------------------------------
        tm = TriggerMonitorTool(strategy_path=strategy_path)
        r3 = await safe_invoke(tm, {"market_state": {"NPI_trailing_1yr_pct": 8.5}})
        check("TM1 success", r3.is_success)
        check("TM1 trigger text contains RIL",
              r3.is_success and "RIL" in r3.output["trigger_text"])
        check("TM1 parses 4 bullet rules",
              r3.is_success and r3.output["n_triggers_parsed"] == 4,
              hint=f"got {r3.output.get('n_triggers_parsed')}")
        check("TM1 each rule has 'rule' key",
              r3.is_success and all("rule" in t for t in r3.output["bullet_triggers"]))
        check("TM1 market_state passed through",
              r3.is_success and r3.output["market_state_received"]["NPI_trailing_1yr_pct"] == 8.5)

        r4 = await safe_invoke(tm, {})  # no market_state
        check("TM2 no market_state default empty dict",
              r4.is_success and r4.output["market_state_received"] == {})

        # -- incentive_planner ------------------------------------------
        ip = IncentivePlannerTool(strategy_path=strategy_path)
        r5 = await safe_invoke(ip, {"amount": 87500.0, "date_iso": "2026-09-15"})
        check("IP1 success", r5.is_success, hint=str(r5.error))
        check("IP1 plan_text contains liquid fund",
              r5.is_success and "liquid fund" in r5.output["plan_text"].lower())
        check("IP1 bullet_allocations parsed",
              r5.is_success and len(r5.output["bullet_allocations"]) >= 1)
        check("IP1 amount + date echoed",
              r5.is_success and r5.output["amount_inr"] == 87500.0
              and r5.output["date"] == "2026-09-15")

        # Validation: bad date format
        r6 = await safe_invoke(ip, {"amount": 50000.0, "date_iso": "September 2026"})
        check("IP2 bad date format rejected by Pydantic",
              r6.is_error and "validation" in r6.error.lower())

        # Validation: negative amount
        r7 = await safe_invoke(ip, {"amount": -1000.0, "date_iso": "2026-09-15"})
        check("IP3 negative amount rejected by Pydantic", r7.is_error)

        # -- Registry + flags -------------------------------------------
        expected = {"portfolio_state", "trigger_monitor", "incentive_planner"}
        registered = set(Tool.list_registered())
        check("REG all 3 finance tools registered",
              expected.issubset(registered),
              hint=f"missing: {expected - registered}")

        for tn in expected:
            cls = Tool.get_or_raise(tn)
            check(f"FLAG {tn} concurrency_safe=True",
                  cls().is_concurrency_safe is True)
            check(f"FLAG {tn} requires_permission=False",
                  cls.requires_permission is False)

        # -- Final --------------------------------------------------------
        total = passed + len(failed)
        print("-" * 70)
        print(f"  Passed: {passed}/{total}")
        if failed:
            for f_ in failed:
                print(f"  {f_}")
            print("=" * 70)
            raise SystemExit(1)
        print("  All finance smoke tests passed.")
        print("=" * 70)

    try:
        asyncio.run(run())
    finally:
        strategy_path.unlink(missing_ok=True)
