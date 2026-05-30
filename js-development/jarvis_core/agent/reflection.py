"""
reflection.py

JARVIS Agent Layer (Reflection): MIRROR-Lite single-pass self-critique
template for Stage 3.4.5.

Import with:
    from jarvis_core.agent.reflection import (
        MIRROR_LITE_MARKER,
        MIRROR_LITE_PROMPT_TEMPLATE,
        MirrorReflection,
        inject_mirror_lite,
        extract_mirror_reflection,
    )

LAYER: Agent (Reflection)

=============================================================================
THE BIG PICTURE
=============================================================================

Without MIRROR-Lite:
    -> The agent emits its answer directly from the ReAct loop without ever
       checking whether it actually answered the goal, whether the reasoning
       chain is internally consistent, or whether the retrieved memory was
       relevant. Errors compound silently. The only feedback signal is
       "did the user complain?"
    -> Multi-pass reflection (a separate inference call after the answer)
       doubles latency and cost. For most queries this is overkill.

With MIRROR-Lite (this module):
    -> A small structured-reflection block is appended to the system prompt.
       The LLM emits a <mirror>...</mirror> JSON block in the SAME generation
       pass, right before the user-facing answer. Zero extra inference cost.
    -> The reflection is extractable by extract_mirror_reflection() into a
       MirrorReflection dataclass so downstream code (trace, KB, hooks) can
       inspect: did goals align, was reasoning sound, was memory relevant?
    -> The injector is idempotent (re-injection is a no-op) so it composes
       safely with other prompt layers.

=============================================================================
THE FLOW (Step by Step Execution Order)
=============================================================================

STEP 1: Caller assembles a base system prompt for the agent.
        |
        v
STEP 2: inject_mirror_lite(base_prompt) appends MIRROR_LITE_PROMPT_TEMPLATE
        (or prepends with force_at_top=True). If the marker is already
        present, the prompt is returned unchanged -- idempotent.
        |
        v
STEP 3: The LLM generates output. Because the template is in the system
        prompt, the LLM emits a <mirror>{...}</mirror> block FIRST, then
        the user-facing answer.
        |
        v
STEP 4: extract_mirror_reflection(llm_output) regex-scans for the <mirror>
        block, strips optional code fences, json.loads the content, and
        returns a MirrorReflection. Returns None on any failure (missing
        block, malformed JSON, missing required keys) so callers can fall
        through silently.
        |
        v
STEP 5: Downstream (3.4 trace/EventBus, KB Cognitive_Pattern logger) reads
        MirrorReflection.to_dict() for persistence + analysis.

=============================================================================
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional


# =============================================================================
# Part 1: TEMPLATE CONSTANTS
# =============================================================================

MIRROR_LITE_MARKER: str = "## MIRROR-Lite Reflection"


MIRROR_LITE_PROMPT_TEMPLATE: str = f"""{MIRROR_LITE_MARKER}

Before your user-facing answer, emit a single structured self-critique block.
This reflection does NOT count toward the user-facing answer and is stripped
from the final response. Cover three axes briefly (one sentence each):

  - Goals: does the planned response actually satisfy the user's goal?
  - Reasoning: is the chain of reasoning internally consistent, or are there
    gaps, contradictions, or unsupported leaps?
  - Memory: was the retrieved context relevant, or did irrelevant chunks
    leak in and bias the answer?

Output format (exact tags, valid JSON inside):
<mirror>{{"goals_alignment": "...", "reasoning_critique": "...", "memory_relevance": "..."}}</mirror>

Then continue with the user-facing answer on a new line.
"""


# =============================================================================
# Part 2: INJECTION HELPER (idempotent)
# =============================================================================

def inject_mirror_lite(system_prompt: str, force_at_top: bool = False) -> str:
    """Append (or prepend) the MIRROR-Lite reflection template to a system prompt.

    Idempotent: if MIRROR_LITE_MARKER is already present, returns unchanged.

    Args:
        system_prompt: The base agent system prompt.
        force_at_top: If True, prepend the template instead of appending.
                      Useful when the template must come BEFORE downstream
                      role-specific instructions.

    Returns:
        The system prompt with the reflection template attached, or the
        original prompt if already injected.
    """
    if MIRROR_LITE_MARKER in system_prompt:
        return system_prompt
    if force_at_top:
        return MIRROR_LITE_PROMPT_TEMPLATE + "\n\n" + system_prompt
    return system_prompt + "\n\n" + MIRROR_LITE_PROMPT_TEMPLATE


# =============================================================================
# Part 3: REFLECTION VALUE OBJECT
# =============================================================================

_REQUIRED_KEYS = ("goals_alignment", "reasoning_critique", "memory_relevance")


@dataclass(frozen=True)
class MirrorReflection:
    """Parsed MIRROR-Lite self-critique extracted from LLM output."""
    goals_alignment: str
    reasoning_critique: str
    memory_relevance: str
    raw_text: str = ""

    @classmethod
    def from_dict(cls, d: Dict[str, Any], raw_text: str = "") -> "MirrorReflection":
        """Build from a dict (typically the parsed JSON block)."""
        return cls(
            goals_alignment=str(d.get("goals_alignment", "")),
            reasoning_critique=str(d.get("reasoning_critique", "")),
            memory_relevance=str(d.get("memory_relevance", "")),
            raw_text=raw_text,
        )

    def to_dict(self) -> Dict[str, str]:
        """Stable serializable representation (excludes raw_text)."""
        return {
            "goals_alignment": self.goals_alignment,
            "reasoning_critique": self.reasoning_critique,
            "memory_relevance": self.memory_relevance,
        }


# =============================================================================
# Part 4: EXTRACTOR (robust to fences, whitespace, surrounding prose)
# =============================================================================

_MIRROR_BLOCK_RE = re.compile(r"<mirror>(.*?)</mirror>", re.DOTALL | re.IGNORECASE)
_CODE_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)


def extract_mirror_reflection(llm_output: str) -> Optional[MirrorReflection]:
    """Extract a MirrorReflection from LLM output text.

    Returns None on any failure (no block, malformed JSON, missing keys).
    The caller treats None as "no reflection emitted; proceed normally."
    """
    if not llm_output:
        return None

    match = _MIRROR_BLOCK_RE.search(llm_output)
    if not match:
        return None

    payload = match.group(1).strip()

    fence_match = _CODE_FENCE_RE.match(payload)
    if fence_match:
        payload = fence_match.group(1).strip()

    try:
        parsed = json.loads(payload)
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(parsed, dict):
        return None

    for key in _REQUIRED_KEYS:
        if key not in parsed:
            return None

    return MirrorReflection.from_dict(parsed, raw_text=match.group(0))


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS
# =============================================================================

if __name__ == "__main__":

    from typing import List

    print("=" * 70)
    print("  reflection.py -- Smoke Tests (Stage 3.4.5)")
    print("=" * 70)

    passed = 0
    failed: List[str] = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        global passed
        if cond:
            passed += 1
        else:
            failed.append(f"FAIL: {name}" + (f" ({hint})" if hint else ""))

    # ---- T1: Template non-empty + contains marker -----------------------
    check(
        "T1 template non-empty + contains marker",
        bool(MIRROR_LITE_PROMPT_TEMPLATE) and MIRROR_LITE_MARKER in MIRROR_LITE_PROMPT_TEMPLATE,
    )

    # ---- T2: Template contains the three axis keywords -----------------
    template_lower = MIRROR_LITE_PROMPT_TEMPLATE.lower()
    check(
        "T2 template covers Goals / Reasoning / Memory",
        "goals" in template_lower and "reasoning" in template_lower and "memory" in template_lower,
    )

    # ---- T3: inject_mirror_lite appends by default ---------------------
    base = "You are a helpful agent."
    injected = inject_mirror_lite(base)
    check(
        "T3 inject appends to base prompt",
        injected.startswith(base) and MIRROR_LITE_MARKER in injected,
        hint=injected[:80],
    )

    # ---- T4: force_at_top prepends -------------------------------------
    injected_top = inject_mirror_lite(base, force_at_top=True)
    check(
        "T4 inject force_at_top prepends",
        injected_top.endswith(base) and injected_top.startswith(MIRROR_LITE_PROMPT_TEMPLATE),
    )

    # ---- T5: Idempotent re-injection -----------------------------------
    double = inject_mirror_lite(injected)
    check("T5 idempotent re-injection", double == injected)
    # Also idempotent under force_at_top
    double_top = inject_mirror_lite(injected_top, force_at_top=True)
    check("T5b idempotent re-injection (force_at_top)", double_top == injected_top)

    # ---- T6: Extract plain JSON inside <mirror> -------------------------
    plain = (
        'Some preamble.\n'
        '<mirror>{"goals_alignment": "on target", "reasoning_critique": "sound", '
        '"memory_relevance": "all chunks relevant"}</mirror>\n'
        'Final answer to user goes here.'
    )
    r_plain = extract_mirror_reflection(plain)
    check(
        "T6 extract plain JSON",
        r_plain is not None
        and r_plain.goals_alignment == "on target"
        and r_plain.reasoning_critique == "sound"
        and r_plain.memory_relevance == "all chunks relevant",
    )

    # ---- T7: Extract code-fenced JSON -----------------------------------
    fenced = (
        'Reflecting now:\n'
        '<mirror>\n'
        '```json\n'
        '{"goals_alignment": "yes", "reasoning_critique": "ok", "memory_relevance": "tight"}\n'
        '```\n'
        '</mirror>\n'
        'Answer follows.'
    )
    r_fenced = extract_mirror_reflection(fenced)
    check(
        "T7 extract code-fenced JSON",
        r_fenced is not None
        and r_fenced.goals_alignment == "yes"
        and r_fenced.reasoning_critique == "ok"
        and r_fenced.memory_relevance == "tight",
        hint=str(r_fenced),
    )

    # ---- T8: Missing block returns None ---------------------------------
    no_block = "Just an answer with no reflection at all."
    check("T8 missing block -> None", extract_mirror_reflection(no_block) is None)

    # ---- T9: Malformed JSON returns None -------------------------------
    broken = '<mirror>{"goals_alignment": "a", "reasoning_critique": missing_quotes}</mirror>'
    check("T9 malformed JSON -> None", extract_mirror_reflection(broken) is None)

    # ---- T10: Missing required keys returns None -----------------------
    partial = '<mirror>{"goals_alignment": "only one key"}</mirror>'
    check("T10 missing required keys -> None", extract_mirror_reflection(partial) is None)

    # ---- T11: from_dict / to_dict roundtrip ----------------------------
    d_in = {
        "goals_alignment": "g",
        "reasoning_critique": "r",
        "memory_relevance": "m",
    }
    rt = MirrorReflection.from_dict(d_in)
    check("T11 from_dict/to_dict roundtrip", rt.to_dict() == d_in)

    # ---- Report --------------------------------------------------------
    total = passed + len(failed)
    print(f"\n  Passed: {passed}/{total}")
    if failed:
        for f_ in failed:
            print(f"  {f_}")
        print("=" * 70)
        raise SystemExit(1)
    print(f"  All {total} reflection smoke tests passed.")
    print("=" * 70)
