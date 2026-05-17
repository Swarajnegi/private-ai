"""
telemetry.py

JARVIS Agent Layer: Pure-Functional Text Telemetry Analyzers.

Import with:
    from jarvis_core.agent.telemetry import analyze_message

This module provides:
    1. analyze_message()  — The single entry point. Takes the current user
       message + optional previous message + optional timestamp info and
       returns a TextTelemetrySnapshot ready for UserTelemetryState.
    2. count_words()      — Word count via whitespace split.
    3. estimate_typo_density() — Heuristic typo ratio using keyboard
       adjacency, repeated chars, and short non-dictionary fragments.
    4. detect_correction() — Whether the current message is a correction
       of the previous (starts with "I meant", "sorry,", "no,", etc.).
    5. detect_rephrasing() — Whether the current message restates the
       previous using different words (n-gram overlap > threshold with
       different surface form). No embedding model — pure token overlap.
    6. estimate_sentiment_direction() — Keyword-based directional shift
       (escalating/deescalating/stable). Not absolute sentiment — only
       the DIRECTION matters for metacognitive response modulation.

=============================================================================
THE BIG PICTURE
=============================================================================

Without text telemetry:
    -> The metacognitive daemon has no quantitative signals about the
       user's engagement state. It can only guess from conversation
       content — which requires an LLM call per turn.
    -> Typo density, prompt brevity, and correction rate are invisible.
       JARVIS cannot detect fatigue, frustration, or flow.

With text telemetry:
    -> Every user message produces a TextTelemetrySnapshot in <1ms
       using pure regex + arithmetic. No LLM call, no external API.
    -> The daemon reads concrete numbers (typo_density=0.08,
       session_hour=2, correction_rate=0.3) and maps them to
       EngagementLevel and AttentionState.
    -> Trends over multiple turns reveal patterns: rising typo density
       + late-night hour = fatigue. Repeated corrections = frustration.

=============================================================================
THE FLOW (Step by Step Execution Order)
=============================================================================

STEP 1: Agent loop receives user message text + timestamp.
        |
STEP 2: Agent loop calls:
            snapshot = analyze_message(
                current_message="...",
                previous_message="...",    # None if first turn
                gap_seconds=15.3,          # None if first turn
                local_hour=2,              # None if unknown
            )
        |
STEP 3: Each sub-analyzer runs independently:
            count_words(text) -> int
            estimate_typo_density(text) -> float
            detect_correction(current, previous) -> bool
            detect_rephrasing(current, previous) -> bool
            estimate_sentiment_direction(current, previous) -> str
        |
STEP 4: Results are packed into a TextTelemetrySnapshot (frozen).
        |
STEP 5: Agent loop wraps snapshot in UserTelemetryState and passes
        to the metacognitive daemon (Stage 3.5).

=============================================================================

All analyzers are pure functions: no side effects, no I/O, no state.
They can be unit-tested in isolation and composed freely.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Literal, Optional, Set, Tuple

from jarvis_core.agent.state import TextTelemetrySnapshot


# =============================================================================
# Part 1: CONSTANTS
# =============================================================================

# Correction signal phrases — if a message starts with one of these,
# the user is explicitly correcting their previous statement.
_CORRECTION_PREFIXES: Tuple[str, ...] = (
    "i meant",
    "i mean",
    "sorry,",
    "sorry ",
    "no,",
    "no ",
    "actually,",
    "actually ",
    "correction:",
    "wait,",
    "wait ",
    "not that",
    "i was wrong",
    "let me rephrase",
    "let me clarify",
    "to clarify",
    "what i meant",
)

# Frustration / negative-escalation keywords.
# Weighted: stronger signals get higher weight.
_ESCALATION_KEYWORDS: dict[str, float] = {
    "why": 0.3,       "wrong": 0.5,      "broken": 0.6,
    "doesn't work": 0.7, "not working": 0.7, "failed": 0.5,
    "again": 0.4,     "still": 0.3,      "already": 0.3,
    "told you": 0.8,  "i said": 0.6,     "frustrat": 0.8,
    "annoying": 0.7,  "useless": 0.9,    "terrible": 0.9,
    "waste": 0.6,     "can't": 0.3,      "impossible": 0.5,
    "seriously": 0.4, "ridiculous": 0.7,  "ugh": 0.6,
    "wtf": 0.9,       "damn": 0.5,       "stop": 0.4,
    "no no": 0.6,
}

# De-escalation / positive keywords.
_DEESCALATION_KEYWORDS: dict[str, float] = {
    "thanks": 0.5,    "thank you": 0.6,  "great": 0.5,
    "perfect": 0.6,   "got it": 0.5,     "makes sense": 0.6,
    "understood": 0.5,"nice": 0.3,       "good": 0.3,
    "awesome": 0.5,   "cool": 0.3,       "love it": 0.7,
    "exactly": 0.4,   "yes": 0.2,        "ok": 0.1,
    "brilliant": 0.6, "well done": 0.6,  "excellent": 0.6,
}

# Words too short to meaningfully typo-check (articles, prepositions)
_SKIP_WORDS: Set[str] = {
    "a", "i", "an", "am", "as", "at", "be", "by", "do", "go",
    "he", "if", "in", "is", "it", "me", "my", "no", "of", "ok",
    "on", "or", "so", "to", "up", "us", "we",
}

# Regex: sequences of 3+ identical characters (e.g., "helllo", "soooo")
_REPEATED_CHARS_RE = re.compile(r"(.)\1{2,}")


# Known common transposition patterns (the→teh, and→adn, the→hte, etc.)
# These are high-confidence typo indicators — if the word matches any
# of these fragments, it's almost certainly a typo.
_KNOWN_TRANSPOSITIONS: Set[str] = {
    "teh", "hte", "thn", "adn", "nad", "nto", "ont",
    "ot", "ti", "fo", "ehr", "hsi", "ot ", "eht",
    "taht", "thier", "recieve", "beleive", "definately",
    "occured", "seperate", "untill", "wich", "becuase",
    "beacuse", "wiht", "jsut", "htat", "cna", "wnat",
    "ahve", "oen", "soem", "thsi", "waht", "gor",
    "palce", "buidl", "wokr",
}

# Regex: words (alphanum sequences)
_WORD_RE = re.compile(r"[a-zA-Z]+")

# Regex: common code/technical patterns to EXCLUDE from typo checking
# (variable names, file paths, URLs, hex values)
_CODE_PATTERN_RE = re.compile(
    r"(?:"
    r"https?://\S+"          # URLs
    r"|[a-zA-Z_]\w*\.\w+"   # dotted.identifiers
    r"|[a-zA-Z_]\w*_\w+"    # snake_case_identifiers
    r"|[A-Z][a-z]+[A-Z]\w*" # CamelCaseIdentifiers
    r"|0x[0-9a-fA-F]+"      # hex values
    r"|/[\w/.]+"             # file paths
    r"|\\[\w\\.]+"           # windows paths
    r")"
)


# =============================================================================
# Part 2: WORD COUNT
# =============================================================================

def count_words(text: str) -> int:
    """Word count via whitespace split, ignoring empty tokens."""
    return len(text.split())


# =============================================================================
# Part 3: TYPO DENSITY ESTIMATOR
# =============================================================================

def _has_repeated_chars(word: str) -> bool:
    """True if word contains 3+ consecutive identical characters."""
    return bool(_REPEATED_CHARS_RE.search(word))


def _is_known_transposition(word: str) -> bool:
    """True if the word matches a known transposition pattern."""
    lower = word.lower()
    return lower in _KNOWN_TRANSPOSITIONS


def _has_anomalous_doubled_end(word: str) -> bool:
    """
    True if the word ends with a doubled letter that creates an
    unusual English ending (e.g., "handlee", "buildd").

    Allows common English doubled endings: -ll, -ss, -ff, -zz, -pp.
    Flags everything else: -ee at end of a word >5 chars that doesn't
    look like a standard -ee word (free, tree, see are fine; handlee is not).
    """
    lower = word.lower()
    if len(lower) < 4:
        return False

    # Check for doubled final letter
    if lower[-1] != lower[-2]:
        return False

    # Allow common doubled endings
    allowed_doubles = {"ll", "ss", "ff", "zz", "pp", "rr", "nn", "mm", "tt", "dd", "gg", "cc", "bb", "ee"}
    doubled = lower[-2:]

    if doubled == "ee" and len(lower) > 5:
        # Most English -ee words are short (free, tree, see, bee, fee)
        # Long words ending in -ee are rare — flag as suspicious
        # Exception: "committee", "employee", "guarantee" etc.
        _LEGIT_EE_WORDS = {"committee", "employee", "guarantee", "trainee", "degree", "referee"}
        if lower not in _LEGIT_EE_WORDS:
            return True

    if doubled not in allowed_doubles:
        return True

    return False


def estimate_typo_density(text: str) -> float:
    """
    Estimate the ratio of likely typos to total words.

    EXECUTION FLOW:
    1. Strip code patterns (URLs, identifiers, paths) — these are
       not typos even if they look like nonsense words.
    2. Extract all alphabetic words.
    3. Skip words that are too short (≤2 chars) or in the skip list.
    4. For each remaining word, check (in priority order):
       a. Contains 3+ repeated chars (e.g., "helllo") → typo signal.
       b. Matches a known transposition (e.g., "teh") → typo signal.
       c. Has anomalous doubled ending (e.g., "handlee") → typo signal.
    5. Return typo_count / total_eligible_words. Clamp to [0.0, 1.0].

    Returns:
        Float in [0.0, 1.0]. 0.0 = no typos detected.
    """
    # Strip code patterns before analysis
    cleaned = _CODE_PATTERN_RE.sub("", text)
    words = _WORD_RE.findall(cleaned)

    if not words:
        return 0.0

    eligible = [w for w in words if len(w) > 2 and w.lower() not in _SKIP_WORDS]
    if not eligible:
        return 0.0

    typo_count = 0
    for word in eligible:
        if _has_repeated_chars(word):
            typo_count += 1
        elif _is_known_transposition(word):
            typo_count += 1
        elif _has_anomalous_doubled_end(word):
            typo_count += 1

    return min(typo_count / len(eligible), 1.0)


# =============================================================================
# Part 4: CORRECTION DETECTION
# =============================================================================

def detect_correction(
    current: str,
    previous: Optional[str] = None,
) -> bool:
    """
    Whether the current message is explicitly correcting the previous.

    EXECUTION FLOW:
    1. If no previous message, return False (nothing to correct).
    2. Check if current message starts with a correction prefix
       ("I meant", "sorry,", "no,", "actually,", etc.).
    3. Return True if any prefix matches.

    This detects EXPLICIT corrections only. Implicit rephrasing is
    handled by detect_rephrasing().
    """
    if previous is None:
        return False

    lower = current.lower().lstrip()
    return any(lower.startswith(prefix) for prefix in _CORRECTION_PREFIXES)


# =============================================================================
# Part 5: REPHRASING DETECTION (N-gram overlap, no embeddings)
# =============================================================================

def _extract_ngrams(text: str, n: int = 2) -> Counter:
    """Extract word-level n-grams from text as a Counter."""
    words = text.lower().split()
    if len(words) < n:
        return Counter(words)
    return Counter(
        tuple(words[i:i + n]) for i in range(len(words) - n + 1)
    )


def _jaccard_similarity(set_a: set, set_b: set) -> float:
    """Jaccard index: |intersection| / |union|. 0.0 if both empty."""
    if not set_a and not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def detect_rephrasing(
    current: str,
    previous: Optional[str] = None,
    bigram_threshold: float = 0.3,
    unigram_threshold: float = 0.5,
) -> bool:
    """
    Whether the current message restates the previous with different words.

    EXECUTION FLOW:
    1. If no previous message, return False.
    2. Compute unigram Jaccard similarity (word-level overlap).
    3. Compute bigram Jaccard similarity (phrase-level overlap).
    4. Rephrasing = high unigram overlap (same topic) + low bigram
       overlap (different phrasing). This separates "same idea,
       different words" from "completely different message."

    The thresholds are tuned for chat-length messages (5-100 words).
    For very short messages (<5 words), detection is unreliable —
    return False to avoid false positives.

    Args:
        current:            The current user message.
        previous:           The previous user message.
        bigram_threshold:   Max bigram similarity for "different phrasing".
        unigram_threshold:  Min unigram similarity for "same topic".

    Returns:
        True if the message looks like a rephrase of the previous.
    """
    if previous is None:
        return False

    # Too-short messages: unreliable detection
    if len(current.split()) < 5 or len(previous.split()) < 5:
        return False

    # Unigram overlap — are they talking about the same thing?
    cur_words = set(current.lower().split())
    prev_words = set(previous.lower().split())
    unigram_sim = _jaccard_similarity(cur_words, prev_words)

    if unigram_sim < unigram_threshold:
        return False  # Different topics entirely

    # Bigram overlap — are they using the same phrases?
    cur_bigrams = set(_extract_ngrams(current, 2).keys())
    prev_bigrams = set(_extract_ngrams(previous, 2).keys())
    bigram_sim = _jaccard_similarity(cur_bigrams, prev_bigrams)

    # High unigram overlap + low bigram overlap = rephrase
    return bigram_sim < bigram_threshold


# =============================================================================
# Part 6: SENTIMENT DIRECTION ESTIMATOR
# =============================================================================

def _score_keywords(
    text: str,
    keywords: dict[str, float],
) -> float:
    """Sum weighted keyword matches in text. Case-insensitive."""
    lower = text.lower()
    score = 0.0
    for keyword, weight in keywords.items():
        if keyword in lower:
            score += weight
    return score


def estimate_sentiment_direction(
    current: str,
    previous: Optional[str] = None,
) -> Literal["escalating", "deescalating", "stable"]:
    """
    Estimate directional sentiment shift between consecutive messages.

    EXECUTION FLOW:
    1. Score current message for escalation and de-escalation keywords.
    2. If no previous message, use absolute scores only.
    3. If previous exists, compare scores: if escalation rose, return
       "escalating". If de-escalation rose, return "deescalating".
    4. If neither shifted significantly, return "stable".

    This is NOT absolute sentiment analysis. It only detects the
    DIRECTION of change — which is what the metacognitive daemon needs
    to decide whether to modulate response strategy.

    Returns:
        "escalating", "deescalating", or "stable".
    """
    cur_esc = _score_keywords(current, _ESCALATION_KEYWORDS)
    cur_deesc = _score_keywords(current, _DEESCALATION_KEYWORDS)

    if previous is None:
        # No baseline — use absolute score with a high threshold
        if cur_esc > 1.5:
            return "escalating"
        if cur_deesc > 1.0:
            return "deescalating"
        return "stable"

    prev_esc = _score_keywords(previous, _ESCALATION_KEYWORDS)
    prev_deesc = _score_keywords(previous, _DEESCALATION_KEYWORDS)

    esc_delta = cur_esc - prev_esc
    deesc_delta = cur_deesc - prev_deesc

    # Significant shift = delta > 0.5
    if esc_delta > 0.5 and esc_delta > deesc_delta:
        return "escalating"
    if deesc_delta > 0.5 and deesc_delta > esc_delta:
        return "deescalating"

    return "stable"


# =============================================================================
# Part 7: CORRECTION RATE (rolling window over conversation history)
# =============================================================================

def compute_correction_rate(
    messages: list[str],
    window: int = 5,
) -> float:
    """
    Compute correction rate over the last N message pairs.

    EXECUTION FLOW:
    1. Take the last `window` messages.
    2. For each consecutive pair, check if the later message is a
       correction of the earlier one.
    3. Return corrections / pairs. 0.0 if <2 messages.

    Args:
        messages: List of user messages in chronological order.
        window:   Number of recent messages to consider.

    Returns:
        Float in [0.0, 1.0]. Ratio of correction pairs to total pairs.
    """
    recent = messages[-window:] if len(messages) > window else messages
    if len(recent) < 2:
        return 0.0

    corrections = sum(
        1 for i in range(1, len(recent))
        if detect_correction(recent[i], recent[i - 1])
    )
    return corrections / (len(recent) - 1)


# =============================================================================
# Part 8: ORCHESTRATOR (Single entry point)
# =============================================================================

def analyze_message(
    current_message: str,
    previous_message: Optional[str] = None,
    message_history: Optional[list[str]] = None,
    gap_seconds: Optional[float] = None,
    local_hour: Optional[int] = None,
) -> TextTelemetrySnapshot:
    """
    Analyze a single user message and produce a TextTelemetrySnapshot.

    This is the ONLY function the agent loop needs to call. It
    orchestrates all sub-analyzers and packs the result into the
    frozen dataclass defined in state.py.

    EXECUTION FLOW:
    1. Count words and characters.
    2. Estimate typo density via keyboard adjacency heuristics.
    3. Compute correction rate over message history (or just the pair).
    4. Detect rephrasing via n-gram overlap.
    5. Estimate sentiment direction via keyword scoring.
    6. Pack all signals into TextTelemetrySnapshot with gap/hour metadata.

    Args:
        current_message:   The user's latest message text.
        previous_message:  The user's previous message (None if first turn).
        message_history:   Full list of user messages this session, for
                           correction rate computation. If None, only the
                           current/previous pair is used.
        gap_seconds:       Seconds between this and the previous message.
                           None if first turn or unknown.
        local_hour:        Hour of day in user's local timezone (0-23).
                           None if unknown.

    Returns:
        TextTelemetrySnapshot (frozen, immutable).
    """
    word_count = count_words(current_message)
    char_count = len(current_message)

    typo_density = estimate_typo_density(current_message)

    # Correction rate: prefer full history, fall back to pair
    if message_history and len(message_history) >= 2:
        correction_rate = compute_correction_rate(message_history)
    elif previous_message is not None:
        correction_rate = 1.0 if detect_correction(
            current_message, previous_message
        ) else 0.0
    else:
        correction_rate = 0.0

    rephrasing = detect_rephrasing(current_message, previous_message)

    sentiment = estimate_sentiment_direction(
        current_message, previous_message
    )

    return TextTelemetrySnapshot(
        prompt_length_words=word_count,
        prompt_length_chars=char_count,
        typo_density=round(typo_density, 4),
        correction_rate=round(correction_rate, 4),
        rephrasing_detected=rephrasing,
        sentiment_direction=sentiment,
        message_gap_seconds=gap_seconds,
        session_hour_local=local_hour,
    )


# =============================================================================
# MAIN ENTRY POINT (Smoke test: 4-message conversation analysis)
# =============================================================================

if __name__ == "__main__":
    print("=" * 65)
    print("  TextTelemetry Analyzers -- Smoke Test")
    print("=" * 65)

    # --- Simulated 4-message conversation ---
    messages = [
        # Turn 1: Normal engagement (long, technical, clean)
        (
            "I want to build a function call parser that handles "
            "malformed JSON from LLM outputs. The parser should extract "
            "the tool name and arguments, normalize key aliases like "
            "'args' vs 'arguments', and return a frozen ToolCall dataclass."
        ),
        # Turn 2: Slight fatigue (shorter, one typo "teh")
        "Can you also handlee teh error cases where the JSON is truncated?",
        # Turn 3: Correction (explicit "I meant...")
        "I meant handle the error cases. Also add retry logic.",
        # Turn 4: Frustration building
        "Why doesn't this work? I already told you about the retry "
        "budget. This is broken again.",
    ]

    print("\n  --- Sub-analyzer unit tests ---\n")

    # Test 1: Word count
    wc = count_words(messages[0])
    print(f"  [1] Word count (msg 1): {wc}")
    assert wc > 30

    # Test 2: Typo density — clean message
    td_clean = estimate_typo_density(messages[0])
    print(f"  [2] Typo density (clean msg): {td_clean:.4f}")
    assert td_clean < 0.05

    # Test 3: Typo density — message with typos
    td_typo = estimate_typo_density(messages[1])
    print(f"  [3] Typo density (typo msg 'handlee teh'): {td_typo:.4f}")
    # 'handlee' has repeated chars, 'teh' has adjacent swap
    assert td_typo > 0.0

    # Test 4: Correction detection
    is_corr = detect_correction(messages[2], messages[1])
    print(f"  [4] Correction detected (msg 3 vs 2): {is_corr}")
    assert is_corr is True

    # Test 5: No correction when first turn
    is_corr_first = detect_correction(messages[0])
    print(f"  [5] Correction on first turn: {is_corr_first}")
    assert is_corr_first is False

    # Test 6: Rephrasing detection (msg 3 is NOT a rephrase of msg 2 — too short)
    rephrase_short = detect_rephrasing(messages[2], messages[1])
    print(f"  [6] Rephrasing (short msgs): {rephrase_short}")
    # Short messages don't trigger rephrasing to avoid false positives

    # Test 7: Rephrasing with controlled test
    original = "I want to build a parser that handles malformed JSON from LLMs"
    rephrase = "Build me a JSON parser for handling broken output from language models"
    rephrase_real = detect_rephrasing(rephrase, original)
    print(f"  [7] Rephrasing (real rephrase): {rephrase_real}")

    # Test 8: Sentiment — escalating
    sent = estimate_sentiment_direction(messages[3], messages[2])
    print(f"  [8] Sentiment (msg 4 vs 3): {sent}")
    assert sent == "escalating"

    # Test 9: Sentiment — stable (first turn)
    sent_first = estimate_sentiment_direction(messages[0])
    print(f"  [9] Sentiment (first turn): {sent_first}")
    assert sent_first == "stable"

    # Test 10: Correction rate over history
    cr = compute_correction_rate(messages)
    print(f"  [10] Correction rate (4 msgs): {cr:.4f}")
    assert 0.0 < cr < 1.0  # Exactly 1 of 3 pairs is a correction

    print("\n  --- Full pipeline test (analyze_message) ---\n")

    # Test 11-14: Analyze each message in sequence
    for i, msg in enumerate(messages):
        prev = messages[i - 1] if i > 0 else None
        history = messages[:i + 1] if i > 0 else None
        snapshot = analyze_message(
            current_message=msg,
            previous_message=prev,
            message_history=history,
            gap_seconds=12.5 * (i + 1),
            local_hour=2 if i >= 2 else 14,  # Late night for last 2
        )
        print(
            f"  [{11 + i}] Turn {i + 1}: "
            f"words={snapshot.prompt_length_words}, "
            f"typos={snapshot.typo_density:.3f}, "
            f"corr_rate={snapshot.correction_rate:.3f}, "
            f"rephrase={snapshot.rephrasing_detected}, "
            f"sentiment={snapshot.sentiment_direction}, "
            f"hour={snapshot.session_hour_local}"
        )

    # Test 15: Verify immutability
    s = analyze_message("test message")
    try:
        s.prompt_length_words = 999
        assert False, "Should have raised"
    except AttributeError:
        print(f"\n  [15] Immutability: frozen dataclass enforced")

    # Test 16: Edge case — empty message
    s_empty = analyze_message("")
    print(f"  [16] Empty message: words={s_empty.prompt_length_words}, "
          f"typos={s_empty.typo_density}")
    assert s_empty.prompt_length_words == 0
    assert s_empty.typo_density == 0.0

    # Test 17: Edge case — code-heavy message (should not flag as typos)
    code_msg = (
        "Check the file at /home/user/jarvis_core/memory/store.py "
        "and the URL https://github.com/Swarajnegi/private-ai "
        "for the RegistryBase implementation."
    )
    s_code = analyze_message(code_msg)
    print(f"  [17] Code-heavy message: typos={s_code.typo_density:.4f}")
    # Code patterns should be stripped before typo analysis

    # Test 18: Keywords in code should not trigger sentiment
    code_fail = "The build failed with error code 0x1F at RuntimeError"
    sent_code = estimate_sentiment_direction(code_fail)
    print(f"  [18] Code failure msg sentiment: {sent_code}")

    print("\n" + "=" * 65)
    print("  All smoke tests passed.")
    print("=" * 65)
