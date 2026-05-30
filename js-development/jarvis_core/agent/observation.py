"""
observation.py

JARVIS Agent Layer (Observation): Step -> LLM-readable observation strings.

Import with:
    from jarvis_core.agent.observation import (
        format_observation,
        format_plan_summary,
        format_hits_compact,
        truncate,
    )

LAYER: Agent (Observation)

=============================================================================
THE BIG PICTURE
=============================================================================

Without an Observation formatter:
    -> The ReAct loop hands raw ToolResult objects (or dicts) back to the LLM
       as the next-turn user message. Memory-retrieval payloads carry hundreds
       of KB of chunk text. The 200K-token context window saturates within
       3-4 tool calls and the agent silently degrades to truncation soup.
    -> Failures surface as opaque tracebacks. The LLM can't tell whether
       the step failed permanently, was retried, or got skipped because an
       upstream step blew up. Replanning loops on the same error.

With format_observation (this module):
    -> Every Step is rendered into a deterministic, bounded string. Hits get
       compact "[N] score=X id=Y: <truncated>" lines. Dicts get json.dumps
       with default=str. Failures get "[step X ERROR after N attempts] ..."
       so the LLM can decide between retry, replan, or escape-valve.
    -> A global truncate() cap (4000 chars default) guarantees no single
       observation blows the context budget. The omitted byte-count is
       included in the marker so the LLM knows information was elided.
    -> format_plan_summary gives the ReAct system prompt a one-liner of
       plan-level progress without re-serializing the whole DAG.

=============================================================================
THE FLOW (Step by Step Execution Order)
=============================================================================

STEP 1: PlanExecutor finishes a Step (success, failure, or skip).
        ↓
STEP 2: ReAct loop iterates plan.steps and calls format_observation(step)
        for each terminal step it wants to surface to the LLM.
        ↓
STEP 3: format_observation branches on step.status:
            - SUCCEEDED + dict-with-hits -> format_hits_compact()
            - SUCCEEDED + dict           -> json.dumps(indent=2)
            - SUCCEEDED + other          -> str(output)
            - FAILED                     -> [ERROR after N attempts] msg
            - SKIPPED                    -> [SKIPPED] upstream-failure msg
            - PENDING/RUNNING            -> [in flight] status
        ↓
STEP 4: Result string runs through truncate() with the caller's max_chars.
        ↓
STEP 5: format_plan_summary(plan) prepended to the LLM turn gives a
        DAG-level rollup: X/Y succeeded, F failed, S skipped.

=============================================================================
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from jarvis_core.agent.plan import Plan, Step, StepStatus


# =============================================================================
# Part 1: CONSTANTS
# =============================================================================

DEFAULT_MAX_OBSERVATION_CHARS: int = 4000
TRUNCATION_MARKER_TEMPLATE: str = "\n... [TRUNCATED, omitted {n} chars] ..."


# =============================================================================
# Part 2: TRUNCATION
# =============================================================================

def truncate(text: str, max_chars: int = DEFAULT_MAX_OBSERVATION_CHARS) -> str:
    """Cap `text` at `max_chars` with a marker disclosing omitted byte count."""
    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    return text[:max_chars] + TRUNCATION_MARKER_TEMPLATE.format(n=omitted)


# =============================================================================
# Part 3: HIT FORMATTING (retrieval-shape payloads)
# =============================================================================

def format_hits_compact(hits: List[Dict[str, Any]], max_per_hit: int = 200) -> str:
    """Render a list of retrieval hits as bounded one-line entries.

    Each hit is expected to expose `id`, `content`, optional `metadata`,
    `score`. Missing fields render as empty / 0.0 without raising.

    Defensive against real-world hit payloads:
      - `score` may be None or a string -> coerced via float(); fallback to 0.0
      - `content` may contain embedded newlines (very common in chunked KB
        entries) -> newlines collapsed to spaces so the one-line-per-hit
        contract holds
    """
    if not hits:
        return "  (no hits)"
    lines: List[str] = []
    for i, h in enumerate(hits, start=1):
        raw_score = h.get("score")
        if raw_score is None:
            score = 0.0
        else:
            try:
                score = float(raw_score)
            except (TypeError, ValueError):
                score = 0.0
        hid = h.get("id", "")
        content = str(h.get("content", ""))
        # Sanitize control chars that would break the one-line-per-hit
        # contract (newlines, carriage returns, tabs).
        content = content.replace("\r", " ").replace("\n", " ").replace("\t", " ")
        if len(content) > max_per_hit:
            content = content[:max_per_hit]
        lines.append(f"  [{i}] score={score:.2f} id={hid}: {content}")
    return "\n".join(lines)


# =============================================================================
# Part 4: STEP-LEVEL OBSERVATION
# =============================================================================

def format_observation(step: Step, max_chars: int = DEFAULT_MAX_OBSERVATION_CHARS) -> str:
    """Render a Step as an LLM-readable observation string, capped at max_chars."""
    if step.status == StepStatus.SUCCEEDED:
        output = step.result.output if step.result is not None else None
        if isinstance(output, dict) and "hits" in output:
            hits = output.get("hits") or []
            body = format_hits_compact(hits)
            result = f"[step {step.step_id} OK] Retrieved {len(hits)} hits:\n{body}"
        elif isinstance(output, dict):
            result = f"[step {step.step_id} OK]\n{json.dumps(output, indent=2, default=str)}"
        else:
            result = f"[step {step.step_id} OK] {output}"
    elif step.status == StepStatus.FAILED:
        err = step.result.error if step.result is not None else "(no error message)"
        result = f"[step {step.step_id} ERROR after {step.attempts} attempts] {err}"
    elif step.status == StepStatus.SKIPPED:
        msg = step.result.error if step.result is not None else "upstream failure"
        result = f"[step {step.step_id} SKIPPED] {msg}"
    else:
        result = f"[step {step.step_id} still in flight: {step.status.value}]"

    return truncate(result, max_chars)


# =============================================================================
# Part 5: PLAN-LEVEL SUMMARY
# =============================================================================

def format_plan_summary(plan: Plan) -> str:
    """One-line rollup of plan progress: succeeded / failed / skipped counts."""
    total = len(plan.steps)
    succeeded = sum(1 for s in plan.steps.values() if s.status == StepStatus.SUCCEEDED)
    failed = sum(1 for s in plan.steps.values() if s.status == StepStatus.FAILED)
    skipped = sum(1 for s in plan.steps.values() if s.status == StepStatus.SKIPPED)
    return (
        f"[plan {plan.plan_id} goal={plan.goal}: "
        f"{succeeded}/{total} succeeded, {failed} failed, {skipped} skipped]"
    )


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS
# =============================================================================

if __name__ == "__main__":

    from jarvis_core.agent.tool import ToolResult

    print("=" * 70)
    print("  observation.py — Smoke Tests (Stage 3.4.3)")
    print("=" * 70)

    passed = 0
    failed: List[str] = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        global passed
        if cond:
            passed += 1
        else:
            failed.append(f"FAIL: {name}" + (f" ({hint})" if hint else ""))

    # ---- T1: truncate short passthrough ----------------------------------
    short = "hello world"
    check("T1 truncate short passthrough", truncate(short, max_chars=50) == short)

    # ---- T2: truncate long adds marker with correct count ----------------
    long_text = "x" * 5000
    truncated = truncate(long_text, max_chars=100)
    expected_marker = TRUNCATION_MARKER_TEMPLATE.format(n=4900)
    check(
        "T2 truncate long marker correct char count",
        truncated == "x" * 100 + expected_marker,
        hint=f"got len={len(truncated)}",
    )

    # ---- T3: SUCCEEDED with str output -----------------------------------
    s3 = Step(step_id="s3", tool_name="echo", status=StepStatus.SUCCEEDED,
              result=ToolResult(output="hello"))
    obs3 = format_observation(s3)
    check("T3 SUCCEEDED str output", obs3 == "[step s3 OK] hello", hint=obs3)

    # ---- T4: SUCCEEDED with dict (no hits) -> JSON dump ------------------
    s4 = Step(step_id="s4", tool_name="calc", status=StepStatus.SUCCEEDED,
              result=ToolResult(output={"answer": 42, "unit": "tokens"}))
    obs4 = format_observation(s4)
    check("T4a SUCCEEDED dict header", obs4.startswith("[step s4 OK]\n"), hint=obs4)
    check("T4b SUCCEEDED dict json body", '"answer": 42' in obs4 and '"unit": "tokens"' in obs4)

    # ---- T5: SUCCEEDED with hits dict -> compact format ------------------
    hits = [
        {"id": "doc_a", "content": "Alpha content body", "score": 0.91},
        {"id": "doc_b", "content": "Beta content body",  "score": 0.77},
    ]
    s5 = Step(step_id="s5", tool_name="memory_hybrid_search", status=StepStatus.SUCCEEDED,
              result=ToolResult(output={"hits": hits}))
    obs5 = format_observation(s5)
    check("T5a hits header with count", obs5.startswith("[step s5 OK] Retrieved 2 hits:\n"), hint=obs5)
    check("T5b hit line 1 present", "[1] score=0.91 id=doc_a: Alpha content body" in obs5)
    check("T5c hit line 2 present", "[2] score=0.77 id=doc_b: Beta content body" in obs5)

    # ---- T6: FAILED -> [ERROR] format with attempt count -----------------
    s6 = Step(step_id="s6", tool_name="calc", status=StepStatus.FAILED, attempts=3,
              result=ToolResult(error="division by zero"))
    obs6 = format_observation(s6)
    check(
        "T6 FAILED format with attempts",
        obs6 == "[step s6 ERROR after 3 attempts] division by zero",
        hint=obs6,
    )

    # ---- T7: SKIPPED -> [SKIPPED] format ---------------------------------
    s7 = Step(step_id="s7", tool_name="calc", status=StepStatus.SKIPPED,
              result=ToolResult(error="upstream s6 failed"))
    obs7 = format_observation(s7)
    check(
        "T7 SKIPPED format",
        obs7 == "[step s7 SKIPPED] upstream s6 failed",
        hint=obs7,
    )

    # ---- T8: PENDING -> [in flight] format -------------------------------
    s8 = Step(step_id="s8", tool_name="calc", status=StepStatus.PENDING)
    obs8 = format_observation(s8)
    check(
        "T8 PENDING in-flight format",
        obs8 == "[step s8 still in flight: pending]",
        hint=obs8,
    )

    # ---- T9: format_hits_compact 3 hits truncated to max_per_hit ----------
    long_content = "y" * 500
    hits9 = [
        {"id": "h1", "content": long_content, "score": 0.5},
        {"id": "h2", "content": long_content, "score": 0.4},
        {"id": "h3", "content": long_content, "score": 0.3},
    ]
    out9 = format_hits_compact(hits9, max_per_hit=50)
    check("T9a 3 lines produced", len(out9.split("\n")) == 3, hint=out9)
    check("T9b each hit truncated to 50 chars", all(("y" * 50) in line and ("y" * 51) not in line for line in out9.split("\n")))

    # ---- T10: format_hits_compact empty list -----------------------------
    check("T10 empty hits returns (no hits)", format_hits_compact([]) == "  (no hits)")

    # ---- T11a: hit with score=None coerced to 0.0 (no crash) -------------
    hits_none = [{"id": "x", "content": "ok", "score": None}]
    out11a = format_hits_compact(hits_none)
    check("T11a None score coerced to 0.0",
          "score=0.00" in out11a, hint=out11a)

    # ---- T11b: hit with non-numeric score safely defaults ----------------
    hits_bad = [{"id": "x", "content": "ok", "score": "not-a-number"}]
    out11b = format_hits_compact(hits_bad)
    check("T11b non-numeric score coerced to 0.0",
          "score=0.00" in out11b, hint=out11b)

    # ---- T11c: hit content with newlines sanitized to spaces -------------
    hits_nl = [{"id": "x", "content": "line1\nline2\rline3\twith tab",
                "score": 0.5}]
    out11c = format_hits_compact(hits_nl)
    check("T11c content newlines collapsed to spaces",
          "\n" not in out11c.split("score=0.50 id=x: ", 1)[1],
          hint=out11c)
    check("T11d one line per hit preserved",
          out11c.count("\n") == 0,
          hint=out11c)

    # ---- T11: format_plan_summary mixed counts ---------------------------
    p = Plan(goal="mix")
    p.add_step(Step(step_id="a", tool_name="t"))
    p.add_step(Step(step_id="b", tool_name="t"))
    p.add_step(Step(step_id="c", tool_name="t"))
    p.add_step(Step(step_id="d", tool_name="t"))
    p.steps["a"].status = StepStatus.SUCCEEDED
    p.steps["b"].status = StepStatus.SUCCEEDED
    p.steps["c"].status = StepStatus.FAILED
    p.steps["d"].status = StepStatus.SKIPPED
    summary = format_plan_summary(p)
    check(
        "T11 plan summary mixed counts",
        summary == f"[plan {p.plan_id} goal=mix: 2/4 succeeded, 1 failed, 1 skipped]",
        hint=summary,
    )

    # ---- Report ----------------------------------------------------------
    total = passed + len(failed)
    print(f"\n  Passed: {passed}/{total}")
    if failed:
        for f_ in failed:
            print(f"  {f_}")
        print("=" * 70)
        raise SystemExit(1)
    print(f"  All {total} observation smoke tests passed.")
    print("=" * 70)
