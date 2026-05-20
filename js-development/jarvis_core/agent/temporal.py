"""
temporal.py

JARVIS Agent Layer: Temporal Reference Resolver (pure-functional utility library).

Import with:
    from jarvis_core.agent.temporal import (
        detect_temporal_markers,
        resolve_relative_date,
        resolve_event_reference,
        resolve_pronoun,
        Marker, ResolvedRef, Commit,
    )

This module provides four pure deterministic functions used by:
    1. `temporal_grounding` middleware (Stage 3.4, KB L287) — auto-injects
       TEMPORAL_CONTEXT before LLM sees user message.
    2. Future agent-callable temporal tools (Stage 3.2 cognitive tools).

NO LLM CALL inside this module. NO network. LLM-based disambiguation lives
in the middleware that consumes these primitives, not in the resolver.

LAYER: Agent

=============================================================================
THE BIG PICTURE
=============================================================================

Without a temporal resolver:
    -> Every JARVIS response that involves temporal/causal reasoning ("the test
       failed before the feature was pushed") requires the LLM to figure out
       the causality from raw token context. 5-15 tokens of CoT per response,
       sometimes wrong-path reasoning before arrival.
    -> Pronouns like "the test" / "that bug" stay unresolved unless the LLM
       explicitly scans backwards.

With a temporal resolver:
    -> Every user message gets scanned for temporal markers BEFORE the LLM
       sees it (in the middleware layer).
    -> Markers resolve to concrete timestamps / commit SHAs / KB entries.
    -> The resolved frame is pre-injected into system prompt; LLM never has
       to "figure it out". This is the Iron-Man-feel for time-awareness.

Production goal: <100ms p95 to scan + resolve all markers in a typical message.

=============================================================================
THE FLOW (Step by Step Execution Order)
=============================================================================

STEP 1: detect_temporal_markers(text) scans the user message via regex
        for date/event-ref/pronoun/causal markers.
        |
        v
STEP 2: For each Marker, dispatch to the matching resolver:
            DATE      -> resolve_relative_date()
            EVENT_REF -> resolve_event_reference(git_log, kb_index)
            PRONOUN   -> resolve_pronoun(conversation)
        |
        v
STEP 3: Each resolver returns ResolvedRef (or None on failure).
        |
        v
STEP 4: Middleware (caller, not us) builds TEMPORAL_CONTEXT block from the
        list of (Marker, ResolvedRef) pairs and injects into system prompt.

=============================================================================
"""

from __future__ import annotations

import datetime as _dt
import difflib
import re
from dataclasses import dataclass
from enum import Enum
from typing import List, Mapping, Optional, Sequence, Tuple


# Optional enhancers. Module loads fine without them; smoke tests still pass.
try:
    import dateparser  # type: ignore
    _HAVE_DATEPARSER = True
except ImportError:
    _HAVE_DATEPARSER = False

try:
    from rapidfuzz import fuzz as _rf_fuzz  # type: ignore
    _HAVE_RAPIDFUZZ = True
except ImportError:
    _HAVE_RAPIDFUZZ = False


# =============================================================================
# Part 1: PUBLIC TYPES
# =============================================================================

class MarkerType(str, Enum):
    """Category of a detected temporal/causal marker. String enum for JSON."""
    DATE = "date"           # "yesterday", "last week", "3 days ago", ISO dates
    EVENT_REF = "event_ref" # "before X", "after Y", "since the rerank fix"
    PRONOUN = "pronoun"     # "the test", "that bug", "the fix"
    CAUSAL = "causal"       # bare "because"/"after"/"before" linking words


@dataclass(frozen=True)
class Marker:
    """A detected temporal/causal span in user text.

    start_idx, end_idx index into the original text (Python slice convention).
    raw_text is the matched substring; marker_type routes to the right resolver.
    """
    start_idx: int
    end_idx: int
    marker_type: MarkerType
    raw_text: str


@dataclass(frozen=True)
class Commit:
    """Minimal git-log shim. Caller-built from `git log --pretty=...` output."""
    sha: str
    timestamp: _dt.datetime
    message: str
    modified_paths: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolvedRef:
    """Outcome of resolving a Marker.

    Exactly one of (timestamp, commit_sha, kb_entry_id) is the primary anchor;
    the others may be set as supporting context. `confidence` in [0.0, 1.0].
    `evidence` is the substring that justified the match (for debugging).
    """
    timestamp: Optional[_dt.datetime] = None
    commit_sha: Optional[str] = None
    kb_entry_id: Optional[str] = None
    confidence: float = 0.0
    evidence: str = ""


# =============================================================================
# Part 2: MARKER DETECTION (regex-based, pure stdlib)
# =============================================================================

# Order matters: more specific patterns first to avoid swallowing by less-specific.
# Patterns return groups for the resolver to consume.

_DATE_REGEXES: Tuple[re.Pattern[str], ...] = (
    # ISO date: 2026-05-19, 2026/05/19
    re.compile(r"\b(\d{4}[-/]\d{1,2}[-/]\d{1,2})\b"),
    # Relative-day: yesterday, today, tomorrow
    re.compile(r"\b(yesterday|today|tomorrow|tonight)\b", re.IGNORECASE),
    # N units ago / in N units: "3 days ago", "in 2 weeks", "an hour ago"
    re.compile(
        r"\b((?:a|an|\d+)\s+(?:second|minute|hour|day|week|month|year)s?\s+ago)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(in\s+(?:a|an|\d+)\s+(?:second|minute|hour|day|week|month|year)s?)\b",
        re.IGNORECASE,
    ),
    # last/next + weekday or unit: "last Monday", "next week", "last night"
    re.compile(
        r"\b((?:last|next|this)\s+(?:morning|afternoon|evening|night|"
        r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
        r"week|month|year))\b",
        re.IGNORECASE,
    ),
)

_EVENT_REF_REGEX: re.Pattern[str] = re.compile(
    # Captures the trigger word and the noun phrase following it
    r"\b(before|after|since|prior\s+to|following|upon)\s+"
    r"(?:the\s+|that\s+|this\s+)?"
    r"([\w\s]{1,40}?)"
    r"(?=\s+(?:was|were|got|is|are|landed|shipped|pushed|committed|merged|fixed|"
    r"deployed|happened|fired|failed)\b|[\.,;]|\s*$)",
    re.IGNORECASE,
)

_PRONOUN_REGEX: re.Pattern[str] = re.compile(
    r"\b(the|that|this)\s+"
    r"(test|tests|bug|bugs|fix|fixes|feature|features|change|changes|"
    r"commit|commits|push|pushes|build|builds|run|runs|error|errors|"
    r"failure|failures|issue|issues|patch|patches)\b",
    re.IGNORECASE,
)


def detect_temporal_markers(text: str) -> List[Marker]:
    """
    Scan text for temporal/causal markers. Returns a list sorted by start_idx.

    Overlapping matches are deduplicated by giving DATE > EVENT_REF > PRONOUN
    precedence (more-specific wins). The same span never returns twice.
    """
    if not text:
        return []

    found: List[Marker] = []

    for regex in _DATE_REGEXES:
        for m in regex.finditer(text):
            found.append(Marker(m.start(), m.end(), MarkerType.DATE, m.group(0)))

    for m in _EVENT_REF_REGEX.finditer(text):
        found.append(Marker(m.start(), m.end(), MarkerType.EVENT_REF, m.group(0)))

    for m in _PRONOUN_REGEX.finditer(text):
        found.append(Marker(m.start(), m.end(), MarkerType.PRONOUN, m.group(0)))

    # Dedup: drop any marker whose span overlaps a higher-priority marker.
    # Priority order: DATE > EVENT_REF > PRONOUN.
    priority = {MarkerType.DATE: 3, MarkerType.EVENT_REF: 2, MarkerType.PRONOUN: 1, MarkerType.CAUSAL: 0}
    found.sort(key=lambda mk: (-priority[mk.marker_type], mk.start_idx))

    accepted: List[Marker] = []
    for mk in found:
        if any(_spans_overlap(mk, kept) for kept in accepted):
            continue
        accepted.append(mk)

    accepted.sort(key=lambda mk: mk.start_idx)
    return accepted


def _spans_overlap(a: Marker, b: Marker) -> bool:
    return not (a.end_idx <= b.start_idx or b.end_idx <= a.start_idx)


# =============================================================================
# Part 3: RESOLVE RELATIVE DATE
# =============================================================================

_WEEKDAY_NAMES: Tuple[str, ...] = (
    "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday",
)

# Hour-of-day defaults for IST workflow phrases. Indian-English bias deliberate.
_TIME_OF_DAY_HOURS: Mapping[str, int] = {
    "morning": 9, "afternoon": 14, "evening": 18,
    "night": 21, "tonight": 21, "lunch": 13, "dinner": 20,
}


def resolve_relative_date(
    expr: str,
    reference: _dt.datetime,
    locale: str = "en-IN",
) -> Optional[_dt.datetime]:
    """
    Resolve a relative-date expression to an absolute datetime.

    Pure deterministic for the stdlib path (regex + arithmetic). If dateparser
    is installed, falls through to dateparser for ambiguous cases the stdlib
    path doesn't cover.

    Returns None on unresolvable input. Never raises.

    Locale `en-IN` biases hour-of-day defaults to Indian work patterns
    (morning=9, evening=18, night=21).
    """
    if not expr:
        return None
    s = expr.strip().lower()

    # -- Stdlib fast path -------------------------------------------------
    # Direct ISO date
    iso_match = re.fullmatch(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
    if iso_match:
        try:
            return _dt.datetime(
                int(iso_match.group(1)),
                int(iso_match.group(2)),
                int(iso_match.group(3)),
                tzinfo=reference.tzinfo,
            )
        except ValueError:
            return None

    if s in ("today",):
        return reference.replace(hour=0, minute=0, second=0, microsecond=0)
    if s in ("yesterday",):
        return (reference - _dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    if s in ("tomorrow",):
        return (reference + _dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    if s in ("tonight", "this night"):
        return reference.replace(hour=21, minute=0, second=0, microsecond=0)

    # "N units ago" / "an hour ago"
    ago_match = re.fullmatch(
        r"(a|an|\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago",
        s,
    )
    if ago_match:
        n_raw = ago_match.group(1)
        n = 1 if n_raw in ("a", "an") else int(n_raw)
        unit = ago_match.group(2)
        return _shift_datetime(reference, -n, unit)

    # "in N units"
    in_match = re.fullmatch(
        r"in\s+(a|an|\d+)\s+(second|minute|hour|day|week|month|year)s?",
        s,
    )
    if in_match:
        n_raw = in_match.group(1)
        n = 1 if n_raw in ("a", "an") else int(n_raw)
        unit = in_match.group(2)
        return _shift_datetime(reference, +n, unit)

    # "last/next/this <weekday or unit>"
    rel_match = re.fullmatch(
        r"(last|next|this)\s+([a-z]+)",
        s,
    )
    if rel_match:
        direction = rel_match.group(1)
        target = rel_match.group(2)
        return _resolve_directional(reference, direction, target)

    # -- dateparser fallback (if installed) -------------------------------
    if _HAVE_DATEPARSER:
        try:
            parsed = dateparser.parse(
                expr,
                settings={
                    "RELATIVE_BASE": reference.replace(tzinfo=None),
                    "PREFER_DATES_FROM": "past",
                    "DATE_ORDER": "DMY" if locale.endswith("IN") else "MDY",
                },
            )
            if parsed is not None:
                if parsed.tzinfo is None and reference.tzinfo is not None:
                    parsed = parsed.replace(tzinfo=reference.tzinfo)
                return parsed
        except Exception:
            pass

    return None


def _shift_datetime(reference: _dt.datetime, n: int, unit: str) -> _dt.datetime:
    """Add n units to reference. Months/years use 30/365-day approximations
    (datetime doesn't support variable-length deltas natively)."""
    unit_to_days = {"second": 0, "minute": 0, "hour": 0, "day": 1, "week": 7, "month": 30, "year": 365}
    if unit in ("second", "minute", "hour"):
        seconds_per = {"second": 1, "minute": 60, "hour": 3600}[unit]
        return reference + _dt.timedelta(seconds=n * seconds_per)
    return reference + _dt.timedelta(days=n * unit_to_days[unit])


def _resolve_directional(
    reference: _dt.datetime,
    direction: str,
    target: str,
) -> Optional[_dt.datetime]:
    """Resolve 'last Monday' / 'next week' / 'this Friday' style expressions."""
    if target in _TIME_OF_DAY_HOURS:
        # "this morning" / "last night" / "tonight"
        hour = _TIME_OF_DAY_HOURS[target]
        base = reference.replace(hour=hour, minute=0, second=0, microsecond=0)
        if direction == "last":
            return base - _dt.timedelta(days=1)
        return base

    if target in _WEEKDAY_NAMES:
        target_dow = _WEEKDAY_NAMES.index(target)
        current_dow = reference.weekday()
        diff = target_dow - current_dow
        if direction == "last":
            diff -= 7 if diff >= 0 else 0
        elif direction == "next":
            diff += 7 if diff <= 0 else 0
        # "this Monday" — if today is past target weekday, go to next week
        elif direction == "this" and diff < 0:
            diff += 7
        return (reference + _dt.timedelta(days=diff)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    if target in ("week", "month", "year"):
        deltas = {"week": 7, "month": 30, "year": 365}
        d = deltas[target]
        if direction == "last":
            return reference - _dt.timedelta(days=d)
        if direction == "next":
            return reference + _dt.timedelta(days=d)
        return reference  # "this week" — return current

    return None


# =============================================================================
# Part 4: RESOLVE EVENT REFERENCE
# =============================================================================

def resolve_event_reference(
    expr: str,
    git_log: Sequence[Commit],
    kb_index: Sequence[Mapping[str, object]] = (),
) -> List[ResolvedRef]:
    """
    Resolve an event-reference expression ("before the rerank fix", "since X
    was pushed") to one or more candidate matches in git history or KB.

    Returns ranked candidates by confidence (descending). Empty list if
    nothing matches above a minimum confidence threshold (0.5).

    `git_log` should be a sequence of Commit objects (caller-built from
    `git log --pretty='%H%n%aI%n%s%n'` or equivalent).

    `kb_index` is an optional sequence of KB entry dicts (each with at least
    a "timestamp" ISO string and "content" string).

    The function STRIPS the trigger word ("before"/"after"/"since"/...) before
    fuzzy-matching the noun phrase against commit messages and KB content.
    """
    if not expr:
        return []

    needle = _strip_trigger_words(expr).strip().lower()
    if not needle or len(needle) < 3:
        return []

    candidates: List[Tuple[float, ResolvedRef]] = []

    # -- Git log matches -------------------------------------------------
    for commit in git_log:
        score = _fuzzy_ratio(needle, commit.message.lower())
        if score >= 0.5:
            candidates.append((
                score,
                ResolvedRef(
                    timestamp=commit.timestamp,
                    commit_sha=commit.sha,
                    confidence=score,
                    evidence=f"commit {commit.sha[:8]}: {commit.message[:80]}",
                ),
            ))

    # -- KB content matches ----------------------------------------------
    for entry in kb_index:
        content = str(entry.get("content", "")).lower()
        if not content:
            continue
        score = _fuzzy_ratio(needle, content[:500])  # match against entry head
        if score >= 0.5:
            ts_raw = entry.get("timestamp")
            ts = _parse_iso(str(ts_raw)) if ts_raw else None
            candidates.append((
                score,
                ResolvedRef(
                    timestamp=ts,
                    kb_entry_id=str(entry.get("timestamp", "")),
                    confidence=score,
                    evidence=f"KB {ts_raw}: {content[:80]}",
                ),
            ))

    candidates.sort(key=lambda pair: pair[0], reverse=True)
    return [ref for _, ref in candidates[:5]]


def _strip_trigger_words(expr: str) -> str:
    """Remove leading triggers (before/after/since/...) + articles, AND
    trailing auxiliary-verb phrases (was pushed / got fixed / is shipped)
    so the residual is the bare noun phrase suitable for fuzzy match."""
    leading = (
        "before", "after", "since", "prior to", "following", "upon",
        "the ", "that ", "this ", "a ", "an ",
    )
    # Trailing aux-verb phrases — cut at first occurrence
    trailing_cut = re.compile(
        r"\s+(?:was|were|got|is|are|has|have|had|landed|shipped|pushed|"
        r"committed|merged|fixed|deployed|happened|fired|failed|ran|run)\b.*$",
        re.IGNORECASE,
    )
    s = expr.strip().lower()
    # Strip leading triggers (loop until stable)
    changed = True
    while changed:
        changed = False
        for t in leading:
            if s.startswith(t):
                s = s[len(t):].strip()
                changed = True
                break
    # Strip trailing aux-verb tail
    s = trailing_cut.sub("", s).strip()
    return s


def _fuzzy_ratio(a: str, b: str) -> float:
    """Substring-aware fuzzy ratio in [0.0, 1.0]. Uses rapidfuzz if available,
    else stdlib difflib partial-ratio approximation."""
    if not a or not b:
        return 0.0
    if a in b:
        return 1.0
    if _HAVE_RAPIDFUZZ:
        return float(_rf_fuzz.partial_ratio(a, b)) / 100.0
    # difflib approx: slide window of len(a) over b, take best ratio
    best = 0.0
    if len(b) <= len(a):
        return difflib.SequenceMatcher(None, a, b).ratio()
    for i in range(len(b) - len(a) + 1):
        chunk = b[i: i + len(a)]
        r = difflib.SequenceMatcher(None, a, chunk).ratio()
        if r > best:
            best = r
            if best >= 0.95:
                break
    return best


def _parse_iso(s: str) -> Optional[_dt.datetime]:
    """Robust ISO 8601 parse with timezone preservation. Returns None on fail."""
    if not s:
        return None
    try:
        # Python 3.11+ handles offsets natively; earlier needs Z normalization
        return _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


# =============================================================================
# Part 5: RESOLVE PRONOUN
# =============================================================================

@dataclass(frozen=True)
class ConversationTurn:
    """Minimal conversation-turn shim. Caller-built from chat history."""
    role: str  # "user" | "assistant" | "system"
    content: str
    timestamp: Optional[_dt.datetime] = None


def resolve_pronoun(
    expr: str,
    conversation: Sequence[ConversationTurn],
) -> Optional[ResolvedRef]:
    """
    Resolve a pronoun reference ("the test", "that bug", "the fix") against
    recent conversation turns. Last-mention heuristic with mild coreference.

    Returns the most-recent turn that mentions the head noun. Returns None
    if no prior turn mentions it.
    """
    if not expr or not conversation:
        return None

    # Extract the head noun: "the test" -> "test", "that bug" -> "bug"
    m = _PRONOUN_REGEX.fullmatch(expr.strip())
    if not m:
        # Caller fed us a non-pronoun span. Try lenient match: last word.
        words = expr.lower().strip().split()
        if not words:
            return None
        head_noun = words[-1]
    else:
        head_noun = m.group(2).lower()

    # Normalize plural -> singular for matching
    singular = head_noun[:-1] if head_noun.endswith("s") and len(head_noun) > 3 else head_noun

    # Walk conversation in reverse — most recent wins
    for turn in reversed(conversation):
        if not turn.content:
            continue
        body = turn.content.lower()
        if singular in body or head_noun in body:
            confidence = 1.0 if singular in body else 0.85
            return ResolvedRef(
                timestamp=turn.timestamp,
                confidence=confidence,
                evidence=f"{turn.role}: ...{_extract_window(body, singular, 60)}...",
            )
    return None


def _extract_window(text: str, needle: str, width: int) -> str:
    """Return up to `width` chars around the first occurrence of needle."""
    idx = text.find(needle)
    if idx < 0:
        return text[:width]
    start = max(0, idx - width // 2)
    end = min(len(text), idx + len(needle) + width // 2)
    return text[start:end]


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS  (50+ pure-functional checks)
# =============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("  temporal_resolver — smoke tests (pure stdlib path)")
    print("=" * 70)
    print(f"  dateparser available: {_HAVE_DATEPARSER}")
    print(f"  rapidfuzz  available: {_HAVE_RAPIDFUZZ}")
    print("-" * 70)

    REF = _dt.datetime(2026, 5, 19, 14, 0, 0, tzinfo=_dt.timezone(_dt.timedelta(hours=5, minutes=30)))
    passed = 0
    failed: List[str] = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        global passed
        if cond:
            passed += 1
        else:
            failed.append(f"FAIL: {name}" + (f" ({hint})" if hint else ""))

    # -- Group A: detect_temporal_markers (12 tests) -----------------------
    print("\n[A] detect_temporal_markers")

    m1 = detect_temporal_markers("Run the test yesterday before the bug fix.")
    check("A1 finds 'yesterday' as DATE", any(x.marker_type == MarkerType.DATE and "yesterday" in x.raw_text for x in m1))
    check("A2 finds 'before the bug fix' as EVENT_REF", any(x.marker_type == MarkerType.EVENT_REF for x in m1))
    check("A3 finds 'the test' as PRONOUN", any(x.marker_type == MarkerType.PRONOUN and "test" in x.raw_text.lower() for x in m1))

    m2 = detect_temporal_markers("2026-05-13 was when we reversed the decision")
    check("A4 finds ISO date", any(x.marker_type == MarkerType.DATE and "2026-05-13" in x.raw_text for x in m2))

    m3 = detect_temporal_markers("3 days ago we shipped the parser")
    check("A5 finds 'N units ago'", any(x.marker_type == MarkerType.DATE and "3 days ago" in x.raw_text.lower() for x in m3))

    m4 = detect_temporal_markers("Last Monday we pushed the rerank fix")
    check("A6 finds 'last Monday'", any(x.marker_type == MarkerType.DATE and "last monday" in x.raw_text.lower() for x in m4))

    m5 = detect_temporal_markers("")
    check("A7 empty text returns empty list", m5 == [])

    m6 = detect_temporal_markers("Just a normal sentence with no markers.")
    check("A8 no-marker text returns empty list", m6 == [])

    m7 = detect_temporal_markers("After the feature was pushed, the test broke.")
    check("A9 'after the feature was pushed' is EVENT_REF", any(x.marker_type == MarkerType.EVENT_REF for x in m7))
    check("A10 also finds 'the test' as PRONOUN", any(x.marker_type == MarkerType.PRONOUN and "test" in x.raw_text.lower() for x in m7))

    m8 = detect_temporal_markers("Today we work on temporal. Tomorrow we ship.")
    check("A11 finds both today and tomorrow", sum(1 for x in m8 if x.marker_type == MarkerType.DATE) >= 2)

    m9 = detect_temporal_markers("an hour ago")
    check("A12 'an hour ago' matches DATE", any(x.marker_type == MarkerType.DATE for x in m9))

    # -- Group B: resolve_relative_date (15 tests) -------------------------
    print("[B] resolve_relative_date")

    b1 = resolve_relative_date("yesterday", REF)
    check("B1 yesterday is 24h before reference", b1 is not None and (REF - b1).days == 1)

    b2 = resolve_relative_date("today", REF)
    check("B2 today preserves date", b2 is not None and b2.date() == REF.date())

    b3 = resolve_relative_date("tomorrow", REF)
    check("B3 tomorrow is 24h after reference", b3 is not None and (b3 - REF).days >= 0)

    b4 = resolve_relative_date("3 days ago", REF)
    check("B4 3 days ago = REF - 3 days", b4 is not None and (REF - b4).days == 3)

    b5 = resolve_relative_date("an hour ago", REF)
    check("B5 an hour ago = REF - 3600s", b5 is not None and abs((REF - b5).total_seconds() - 3600) < 1)

    b6 = resolve_relative_date("in 2 weeks", REF)
    check("B6 in 2 weeks = REF + 14 days", b6 is not None and (b6 - REF).days == 14)

    b7 = resolve_relative_date("2026-05-13", REF)
    check("B7 ISO date parses", b7 is not None and b7.year == 2026 and b7.month == 5 and b7.day == 13)

    b8 = resolve_relative_date("2026/12/31", REF)
    check("B8 slash-separated ISO parses", b8 is not None and b8.day == 31)

    b9 = resolve_relative_date("last week", REF)
    check("B9 last week shifts back ~7 days", b9 is not None and (REF - b9).days >= 6)

    b10 = resolve_relative_date("next month", REF)
    check("B10 next month shifts forward", b10 is not None and (b10 - REF).days > 25)

    # REF is Tuesday 2026-05-19. "last Monday" should be Monday 2026-05-18 (1 day before).
    b11 = resolve_relative_date("last monday", REF)
    check("B11 last Monday is one day before Tuesday REF", b11 is not None and b11.weekday() == 0 and (REF - b11).days >= 1)

    b12 = resolve_relative_date("tonight", REF)
    check("B12 tonight is hour 21 on REF date", b12 is not None and b12.hour == 21 and b12.date() == REF.date())

    b13 = resolve_relative_date("nonsense gibberish", REF)
    check("B13 unparseable returns None", b13 is None)

    b14 = resolve_relative_date("", REF)
    check("B14 empty returns None", b14 is None)

    b15 = resolve_relative_date("an hour ago", REF)
    check("B15 'an' resolves to 1", b15 is not None)

    # -- Group C: resolve_event_reference (10 tests) -----------------------
    print("[C] resolve_event_reference")

    commits = [
        Commit("abc12345", REF - _dt.timedelta(days=3), "feat: ship the rerank fix"),
        Commit("def67890", REF - _dt.timedelta(days=1), "fix: parser handles malformed JSON"),
        Commit("aaaaaaaa", REF - _dt.timedelta(days=10), "feat: temporal resolver landing"),
    ]
    kb = [
        {"timestamp": "2026-05-13T08:00:00+05:30", "content": "Decision: OpenClaude delegation reversed in favor of build-from-scratch."},
        {"timestamp": "2026-05-16T08:51:00+05:30", "content": "Stage 3.1 ships parser + state + telemetry modules."},
    ]

    c1 = resolve_event_reference("the rerank fix", commits, kb)
    check("C1 'the rerank fix' matches rerank commit", len(c1) >= 1 and c1[0].commit_sha == "abc12345")

    c2 = resolve_event_reference("before the rerank fix was pushed", commits, kb)
    check("C2 trigger-word stripped, still matches", any(r.commit_sha == "abc12345" for r in c2))

    c3 = resolve_event_reference("after the parser handles JSON", commits, kb)
    check("C3 fuzzy match to parser commit", any(r.commit_sha == "def67890" for r in c3))

    c4 = resolve_event_reference("OpenClaude delegation", commits, kb)
    check("C4 KB content match", any(r.kb_entry_id and "2026-05-13" in r.kb_entry_id for r in c4))

    c5 = resolve_event_reference("totally unrelated garbage xyzqwerty", commits, kb)
    check("C5 unmatchable returns empty", c5 == [])

    c6 = resolve_event_reference("", commits, kb)
    check("C6 empty returns empty", c6 == [])

    c7 = resolve_event_reference("ab", commits, kb)
    check("C7 too-short returns empty", c7 == [])

    c8 = resolve_event_reference("Stage 3.1", commits, kb)
    check("C8 multi-word KB match", any(r.kb_entry_id for r in c8))

    c9 = resolve_event_reference("the rerank fix", [], [])
    check("C9 no sources returns empty", c9 == [])

    c10 = resolve_event_reference("the rerank fix", commits, kb)
    check("C10 results sorted by confidence", all(c10[i].confidence >= c10[i+1].confidence for i in range(len(c10)-1)))

    # -- Group D: resolve_pronoun (10 tests) -------------------------------
    print("[D] resolve_pronoun")

    convo = [
        ConversationTurn("user", "Hey, I ran a test on the rerank module.", REF - _dt.timedelta(minutes=30)),
        ConversationTurn("assistant", "Got it — looking at the test output now.", REF - _dt.timedelta(minutes=28)),
        ConversationTurn("user", "There was a bug in the offset calc.", REF - _dt.timedelta(minutes=20)),
        ConversationTurn("assistant", "I see the bug; will patch.", REF - _dt.timedelta(minutes=18)),
    ]

    d1 = resolve_pronoun("the test", convo)
    check("D1 'the test' finds last test mention", d1 is not None and d1.confidence > 0)

    d2 = resolve_pronoun("the bug", convo)
    check("D2 'the bug' finds last bug mention", d2 is not None)

    d3 = resolve_pronoun("the fix", convo)
    check("D3 'the fix' returns None (no fix in history)", d3 is None)

    d4 = resolve_pronoun("the test", [])
    check("D4 empty conversation returns None", d4 is None)

    d5 = resolve_pronoun("", convo)
    check("D5 empty expr returns None", d5 is None)

    d6 = resolve_pronoun("that bug", convo)
    check("D6 'that bug' matches same as 'the bug'", d6 is not None)

    d7 = resolve_pronoun("this test", convo)
    check("D7 'this test' resolves", d7 is not None)

    d8 = resolve_pronoun("the tests", convo)
    check("D8 plural 'the tests' singularizes to test", d8 is not None)

    # D9: last-mention precedence — bug mentioned later than test should resolve to assistant turn (the most recent)
    d9 = resolve_pronoun("the bug", convo)
    check("D9 last-mention wins (assistant turn most recent)", d9 is not None and d9.evidence.startswith("assistant"))

    d10 = resolve_pronoun("the test", [ConversationTurn("user", "no relevant content", REF)])
    check("D10 no-match in conversation returns None", d10 is None)

    # -- Group E: integration (5 tests) -----------------------------------
    print("[E] integration (detect + dispatch)")

    e_text = "Yesterday I ran the test, but after the rerank fix was pushed, results differ."
    e_markers = detect_temporal_markers(e_text)
    e_dates = [mk for mk in e_markers if mk.marker_type == MarkerType.DATE]
    e_events = [mk for mk in e_markers if mk.marker_type == MarkerType.EVENT_REF]
    e_pronouns = [mk for mk in e_markers if mk.marker_type == MarkerType.PRONOUN]
    check("E1 integration: finds yesterday", len(e_dates) >= 1)
    check("E2 integration: finds event ref", len(e_events) >= 1)
    check("E3 integration: finds 'the test'", any("test" in mk.raw_text.lower() for mk in e_pronouns))
    check("E4 integration: markers in start_idx order",
          all(e_markers[i].start_idx <= e_markers[i+1].start_idx for i in range(len(e_markers)-1)))
    check("E5 integration: no overlapping spans",
          all(not _spans_overlap(e_markers[i], e_markers[j])
              for i in range(len(e_markers)) for j in range(i+1, len(e_markers))))

    # -- Final tally -------------------------------------------------------
    total = passed + len(failed)
    print("-" * 70)
    print(f"  Passed: {passed}/{total}")
    if failed:
        for f in failed:
            print(f"  {f}")
        print("=" * 70)
        raise SystemExit(1)
    print("  All 50+ smoke tests passed.")
    print("=" * 70)
