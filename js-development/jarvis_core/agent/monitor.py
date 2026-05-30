"""
monitor.py

JARVIS Agent Layer (Monitor): Stage 3.4.6 CoT loop detector.

Import with:
    from jarvis_core.agent.monitor import MetaR1Monitor, InstabilityReport

LAYER: Agent (Monitor)

=============================================================================
THE BIG PICTURE
=============================================================================

Without a CoT instability monitor:
    -> Long chain-of-thought traces from reasoning models (DeepSeek R1, Kimi
       K2.6 thinking, Qwen3-Thinking) can spiral into self-corrective loops:
       "wait, actually... no, let me reconsider... wait but...". The model
       burns tokens without converging. Downstream tool-call extraction
       degrades because the final answer is buried under back-and-forth.
    -> The ReAct loop driver has no signal to abort or replan; it watches
       the trace grow and ships whatever junk comes out the other end.

With MetaR1Monitor (this module):
    -> Cheap regex pass counts transition tokens ("wait", "actually",
       "re-evaluate", ...) inside <think>...</think> blocks. If any token
       class crosses INSTABILITY_THRESHOLD, the trace is flagged unstable.
    -> The ReAct driver (3.4 wiring) consults from_cot_trace() before
       extracting the final answer. Unstable -> trigger replanning, escape
       to a stronger model, or surface uncertainty to the user.
    -> Per metacognitive review Section 4 part C: this is the cheapest
       possible loop detector. Heavier semantic loop detection (embedding
       drift, n-gram cycles) lands later if regex proves insufficient.

=============================================================================
THE FLOW (Step by Step Execution Order)
=============================================================================

STEP 1: A reasoning model emits a CoT trace with <think>...</think> markup.
        Example:
            "<think>The user asked X. wait, let me reconsider. Actually
            the answer is Y. wait, but what if Z?</think>The answer is Y."
        |
        v
STEP 2: ReAct driver hands the raw trace to MetaR1Monitor.from_cot_trace().
        |
        v
STEP 3: Monitor extracts every <think> block via re.DOTALL findall.
        If no blocks exist, the whole trace is analyzed as a single block
        (handles models that emit raw CoT without tags).
        |
        v
STEP 4: Each pre-compiled token regex (ClassVar dict, case-insensitive,
        word-boundary aware) runs across the joined block content.
        Counts aggregate into token_counts.
        |
        v
STEP 5: is_unstable = any(count > threshold for count in token_counts).
        flagged_tokens lists every token class that breached the threshold.
        |
        v
STEP 6: InstabilityReport returned; ReAct driver decides next action
        (continue, replan, escape, or surface uncertainty).

=============================================================================
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, ClassVar, Dict, List, Pattern


# =============================================================================
# Part 1: TRANSITION TOKEN VOCABULARY + THRESHOLD CONSTANTS
# =============================================================================

TRANSITION_TOKENS: List[str] = [
    "wait",
    "alternatively",
    "re-evaluate",
    "actually",
    "no,",
    "let me reconsider",
    "on second thought",
    "wait but",
]

INSTABILITY_THRESHOLD: int = 2


# =============================================================================
# Part 2: INSTABILITY REPORT (frozen value object)
# =============================================================================

@dataclass(frozen=True)
class InstabilityReport:
    """Result of a single CoT instability analysis.

    Fields:
        is_unstable:           True if any transition token exceeded threshold.
        token_counts:          Map of token -> occurrence count across blocks.
        total_transitions:     Sum of all token counts.
        flagged_tokens:        Tokens whose count exceeded the threshold.
        think_blocks_analyzed: Number of <think> blocks found (0 -> raw mode).
        notes:                 Free-text diagnostic, e.g. "no <think> tags".
    """
    is_unstable: bool
    token_counts: Dict[str, int]
    total_transitions: int
    flagged_tokens: List[str]
    think_blocks_analyzed: int
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Stable JSON-serializable representation for trace/EventBus."""
        return {
            "is_unstable": self.is_unstable,
            "token_counts": dict(self.token_counts),
            "total_transitions": self.total_transitions,
            "flagged_tokens": list(self.flagged_tokens),
            "think_blocks_analyzed": self.think_blocks_analyzed,
            "notes": self.notes,
        }


# =============================================================================
# Part 3: PATTERN COMPILATION HELPERS (run once at class-load time)
# =============================================================================

# Multi-word phrases and tokens that already contain non-word punctuation
# ("no,", "wait but", "let me reconsider", ...) cannot use simple \b\b
# wrapping because word boundaries don't sit cleanly against ",". We split:
#   - "alphanumeric-only" tokens get \b\b boundaries (avoid "waiter" matching "wait")
#   - everything else gets literal-escaped match with a non-letter lookbehind/ahead
#     to keep substring drift in check ("alternatively" shouldn't match "alt").

_WORD_ONLY = re.compile(r"^[A-Za-z]+$")


def _compile_token(token: str) -> Pattern[str]:
    escaped = re.escape(token)
    if _WORD_ONLY.match(token):
        return re.compile(rf"\b{escaped}\b", re.IGNORECASE)
    # For multi-word phrases / punctuated tokens: anchor with non-letter
    # boundaries on either side so "actually" inside another word can't match,
    # but punctuation-adjacent matches still fire.
    return re.compile(
        rf"(?<![A-Za-z]){escaped}(?![A-Za-z])",
        re.IGNORECASE,
    )


_THINK_BLOCK_RE: Pattern[str] = re.compile(
    r"<think>(.*?)</think>",
    re.DOTALL | re.IGNORECASE,
)


# =============================================================================
# Part 4: META R1 MONITOR (regex frequency analyzer)
# =============================================================================

class MetaR1Monitor:
    """CoT loop detector via regex frequency analysis.

    Patterns compile ONCE at class load (ClassVar dict). Per-call cost is
    O(num_tokens * len(trace)) with no backtracking risk -- every pattern is
    literal-escaped with bounded boundary lookarounds.

    Stage 3.4.6 hook: the ReAct driver invokes from_cot_trace() each turn
    before extracting tool calls. On is_unstable=True it may abort, replan,
    or escalate to a stronger model.
    """

    _COMPILED_PATTERNS: ClassVar[Dict[str, Pattern[str]]] = {
        token: _compile_token(token) for token in TRANSITION_TOKENS
    }

    @classmethod
    def from_cot_trace(
        cls,
        trace: str,
        threshold: int = INSTABILITY_THRESHOLD,
    ) -> InstabilityReport:
        """Analyze a CoT trace for transition-token instability.

        Args:
            trace:     Raw text emitted by the reasoning model. May contain
                       zero or more <think>...</think> blocks.
            threshold: Per-token-class count above which a token is flagged.
                       Defaults to module-level INSTABILITY_THRESHOLD (2).

        Returns:
            InstabilityReport describing counts, flags, and metadata.
        """
        if not trace:
            return InstabilityReport(
                is_unstable=False,
                token_counts={t: 0 for t in TRANSITION_TOKENS},
                total_transitions=0,
                flagged_tokens=[],
                think_blocks_analyzed=0,
                notes="empty trace",
            )

        blocks = _THINK_BLOCK_RE.findall(trace)
        if blocks:
            corpus = "\n".join(blocks)
            notes = f"analyzed {len(blocks)} <think> block(s)"
            block_count = len(blocks)
        else:
            corpus = trace
            notes = "no <think> tags; analyzed entire trace"
            block_count = 0

        # Mask longer phrases first so they don't get double-counted by the
        # shorter tokens they contain. Example: "wait but" must not also
        # contribute to "wait"'s count. Process tokens in descending length
        # order, replacing each match with a placeholder before counting
        # the next.
        counts: Dict[str, int] = {}
        flagged: List[str] = []
        working_corpus = corpus
        ordered_tokens = sorted(
            cls._COMPILED_PATTERNS.items(),
            key=lambda kv: len(kv[0]),
            reverse=True,
        )
        for token, pattern in ordered_tokens:
            matches = pattern.findall(working_corpus)
            n = len(matches)
            counts[token] = n
            if n > threshold:
                flagged.append(token)
            if n > 0:
                # Mask with a same-length sentinel that can't match other tokens.
                working_corpus = pattern.sub("\x00" * len(token), working_corpus)

        return InstabilityReport(
            is_unstable=bool(flagged),
            token_counts=counts,
            total_transitions=sum(counts.values()),
            flagged_tokens=flagged,
            think_blocks_analyzed=block_count,
            notes=notes,
        )


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS
# =============================================================================

if __name__ == "__main__":

    print("=" * 70)
    print("  monitor.py -- Smoke Tests (Stage 3.4.6 CoT Loop Detector)")
    print("=" * 70)

    passed = 0
    failed: List[str] = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        global passed
        if cond:
            passed += 1
        else:
            failed.append(f"FAIL: {name}" + (f" ({hint})" if hint else ""))

    # ---- T1: Empty trace -------------------------------------------------
    r1 = MetaR1Monitor.from_cot_trace("")
    check("T1 empty trace not unstable", not r1.is_unstable)
    check("T1 empty trace zero transitions", r1.total_transitions == 0)

    # ---- T2: Stable trace -------------------------------------------------
    r2 = MetaR1Monitor.from_cot_trace("The answer is 42.")
    check("T2 stable trace not unstable", not r2.is_unstable, hint=str(r2.token_counts))
    check("T2 stable trace zero transitions", r2.total_transitions == 0)

    # ---- T3: Single "wait" below threshold --------------------------------
    r3 = MetaR1Monitor.from_cot_trace("wait, let me think about this.")
    check("T3 single wait counted", r3.token_counts["wait"] == 1)
    check("T3 single wait not unstable", not r3.is_unstable)

    # ---- T4: Three "wait" exceeds threshold -------------------------------
    r4 = MetaR1Monitor.from_cot_trace("wait. wait! wait?")
    check("T4 three wait counted", r4.token_counts["wait"] == 3, hint=str(r4.token_counts))
    check("T4 three wait unstable", r4.is_unstable)
    check("T4 wait flagged", "wait" in r4.flagged_tokens)

    # ---- T5: Both "actually" and "wait" flagged ---------------------------
    trace5 = (
        "wait, hold on. actually, no. wait again. actually maybe. "
        "wait one more time. actually yes."
    )
    r5 = MetaR1Monitor.from_cot_trace(trace5)
    check("T5 wait flagged", "wait" in r5.flagged_tokens, hint=str(r5.token_counts))
    check("T5 actually flagged", "actually" in r5.flagged_tokens, hint=str(r5.token_counts))
    check("T5 unstable", r5.is_unstable)

    # ---- T6: Case-insensitive matching ------------------------------------
    r6 = MetaR1Monitor.from_cot_trace("WAIT here. wait there.")
    check("T6 case insensitive wait==2", r6.token_counts["wait"] == 2,
          hint=str(r6.token_counts))

    # ---- T7: Wrapped in <think>...</think> --------------------------------
    r7 = MetaR1Monitor.from_cot_trace(
        "<think>wait. wait. wait.</think>Final answer: 7."
    )
    check("T7 think block wait counted", r7.token_counts["wait"] == 3,
          hint=str(r7.token_counts))
    check("T7 think_blocks_analyzed=1", r7.think_blocks_analyzed == 1)
    check("T7 unstable", r7.is_unstable)

    # ---- T8: Multiple <think> blocks aggregate ----------------------------
    r8 = MetaR1Monitor.from_cot_trace(
        "<think>wait first.</think>"
        "intermediate text wait NOT counted because not in think? "
        "<think>wait second. wait third.</think>"
    )
    check("T8 two blocks analyzed", r8.think_blocks_analyzed == 2,
          hint=str(r8.think_blocks_analyzed))
    check("T8 wait aggregated across blocks", r8.token_counts["wait"] == 3,
          hint=str(r8.token_counts))

    # ---- T9: No <think> tag, raw text still counted -----------------------
    r9 = MetaR1Monitor.from_cot_trace(
        "wait. wait. wait. wait. Final answer."
    )
    check("T9 raw mode think_blocks_analyzed=0", r9.think_blocks_analyzed == 0)
    check("T9 raw mode wait counted", r9.token_counts["wait"] == 4)
    check("T9 raw mode unstable", r9.is_unstable)

    # ---- T10: "no," with comma matches ------------------------------------
    r10 = MetaR1Monitor.from_cot_trace(
        "Maybe. no, that's wrong. no, also wrong. no, definitely off."
    )
    check("T10 'no,' counted three times", r10.token_counts["no,"] == 3,
          hint=str(r10.token_counts))
    check("T10 'no,' flagged", "no," in r10.flagged_tokens)

    # ---- T11: InstabilityReport.to_dict keys ------------------------------
    d = r5.to_dict()
    expected_keys = {
        "is_unstable",
        "token_counts",
        "total_transitions",
        "flagged_tokens",
        "think_blocks_analyzed",
        "notes",
    }
    check("T11 to_dict has expected keys", set(d.keys()) == expected_keys,
          hint=str(set(d.keys())))
    check("T11 to_dict types stable",
          isinstance(d["token_counts"], dict)
          and isinstance(d["flagged_tokens"], list)
          and isinstance(d["is_unstable"], bool))

    # ---- T12: Word-boundary protection ("waiter" must not match "wait") ---
    r12 = MetaR1Monitor.from_cot_trace("The waiter brought tea. A waitress too.")
    check("T12 'waiter' does not match 'wait'", r12.token_counts["wait"] == 0,
          hint=str(r12.token_counts))

    # ---- T13: Multi-word phrase "let me reconsider" -----------------------
    r13 = MetaR1Monitor.from_cot_trace(
        "OK let me reconsider. Hmm let me reconsider again. let me reconsider once more."
    )
    check("T13 'let me reconsider' counted 3x",
          r13.token_counts["let me reconsider"] == 3,
          hint=str(r13.token_counts))
    check("T13 phrase flagged", "let me reconsider" in r13.flagged_tokens)

    # ---- T14: Patterns compiled once at class load ------------------------
    check("T14 patterns precompiled",
          len(MetaR1Monitor._COMPILED_PATTERNS) == len(TRANSITION_TOKENS))
    check("T14 all patterns are re.Pattern",
          all(isinstance(p, re.Pattern)
              for p in MetaR1Monitor._COMPILED_PATTERNS.values()))

    # ---- T15: "wait but" must not double-count as both "wait" and "wait but"
    # Previously: "wait but x. wait but y. wait but z." counted as
    #             wait=3 AND wait_but=3. Now: wait_but=3, wait=0.
    r15 = MetaR1Monitor.from_cot_trace(
        "wait but actually no. wait but I think. wait but maybe."
    )
    check("T15a 'wait but' counted 3x",
          r15.token_counts["wait but"] == 3, hint=str(r15.token_counts))
    check("T15b 'wait' NOT also counted inside 'wait but'",
          r15.token_counts["wait"] == 0, hint=str(r15.token_counts))

    # ---- T16: Bare "wait" without "but" still counted independently -------
    r16 = MetaR1Monitor.from_cot_trace(
        "wait. wait but no. wait. wait."
    )
    # Expected: wait but=1, wait=3 (the 3 bare ones).
    check("T16a 'wait but' counted 1x",
          r16.token_counts["wait but"] == 1, hint=str(r16.token_counts))
    check("T16b bare 'wait' counted 3x",
          r16.token_counts["wait"] == 3, hint=str(r16.token_counts))

    # ---- Report ----------------------------------------------------------
    total = passed + len(failed)
    print(f"\n  Passed: {passed}/{total}")
    if failed:
        for f_ in failed:
            print(f"  {f_}")
        print("=" * 70)
        raise SystemExit(1)
    print(f"  All {total} smoke tests passed.")
    print("=" * 70)
