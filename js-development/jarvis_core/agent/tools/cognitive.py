"""
cognitive.py

JARVIS Agent Layer: Cognitive / identity tools (Category A — Callable).

Import-time registration:
    @Tool.register("cognitive_mirror")
    @Tool.register("prior_self_consult")
    @Tool.register("bear_case_devil")
    @Tool.register("writing_voice_check")

LAYER: Agent (Tools)

=============================================================================
THE BIG PICTURE
=============================================================================

These four tools are NOT generic agentic primitives. Each one exists to give
the agent access to JARVIS-private substrate that no off-the-shelf system has:

    cognitive_mirror       -> surfaces user's own DIRECTIVE-tagged
                              Cognitive_Pattern entries against current input.
                              Forces every response to load YOUR behavioral
                              rules before reasoning, not generic LLM defaults.

    prior_self_consult     -> "What would past-you say about this?" Searches
                              KB within a time window for relevant decisions
                              and episodics. Counters drift from prior reasoning.

    bear_case_devil        -> Generates a structured contrarian argument
                              against a stated thesis. Forces falsification
                              before high-conviction action (position re-buy,
                              feature ship, architectural commitment).

    writing_voice_check    -> Heuristic style check against user's voice
                              patterns (KB L265 aesthetic_compression +
                              L267-L270 ambition/visceral imagery). Flags
                              sycophantic phrases, hedge words, verbose
                              sentences, low numeral density.

All four are concurrency-safe (read-only KB / pure heuristics / LLM read-only).
None require permission gating.

=============================================================================
THE FLOW (per-tool)
=============================================================================

cognitive_mirror:
    STEP 1: Load KB JSONL (path injected via __init__ DI).
    STEP 2: Filter to type=Cognitive_Pattern AND "DIRECTIVE" in tags.
    STEP 3: Score each candidate by token-overlap ratio with `context`.
    STEP 4: Return top-k by overlap score.

prior_self_consult (semantic since Wave 1.2, 2026-06-12 — token-overlap alone
missed vocabulary mismatches live: "deploying" vs "deployment", "zero-rupee"
vs "budget"; the superseding Decision surfaced in only ~1/3 runs):
    STEP 1: Compute cutoff datetime = now - days_back.
    STEP 2: Embed-index the whole KB once per (path, embedder) — cached by
            file mtime+size; ~350 entries ≈ seconds on CPU, MiniLM truncates
            each entry to its first ~1,000 chars (256-token model limit).
    STEP 3: Score each in-window entry: 0.6·cosine(query, entry) +
            0.4·token-overlap; meta-entries (session-distill / trap-probe
            tags) ×0.3 — records ABOUT probes carry the probed question's
            vocabulary and must rank below the entries holding the ANSWER.
    STEP 4: Sort by (score rounded to 0.01, timestamp) DESC — near-ties
            break NEWEST-first (an autobiography that breaks ties oldest-
            first recites its past as its present). Return top-N with
            content heads (450 chars — full contents overflowed the ReAct
            observation cap).

bear_case_devil:
    STEP 1: Require llm_call DI (else clean error — fail loud).
    STEP 2: Compose structured contrarian prompt with JSON output spec.
    STEP 3: Call llm_call(prompt); extract JSON from response.
    STEP 4: Return parsed bear_case + kill_switches + worst_case_pnl.

writing_voice_check:
    STEP 1: Tokenize text -> words + sentences.
    STEP 2: Compute metrics: avg_sentence_len, sycophant_count, hedge_count,
            numeral_density.
    STEP 3: Apply penalty rules per KB voice patterns (L265, L267-L270).
    STEP 4: Return voice_match_score in [0, 1] + explicit deviations.

=============================================================================
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from pydantic import Field

from jarvis_core.agent.tool import Tool, ToolInput, ToolResult
from jarvis_core.agent.domain_classifier import EmbedFn, _build_default_embed_fn, _dot
from jarvis_core.config import KB_PATH


# =============================================================================
# Part 1: SHARED BASE (KB path DI + optional llm_call DI)
# =============================================================================

class CognitiveToolBase(Tool):
    """Shared base for cognitive tools. DI of KB path + optional llm_call.

    NOT registered itself (no `name` set on this class).
    """

    def __init__(
        self,
        kb_path: Optional[Path] = None,
        llm_call: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._kb_path: Path = kb_path or KB_PATH
        self._llm_call: Optional[Callable[[str], str]] = llm_call


def _tokenize(text: str) -> List[str]:
    """Lowercase word-tokenize for overlap scoring. Empty list on empty input."""
    if not text:
        return []
    return re.findall(r"\w+", text.lower())


def _overlap_ratio(a_tokens: List[str], b_tokens: List[str]) -> float:
    """Token-overlap ratio: |a ∩ b| / |a|. Zero on empty `a`."""
    if not a_tokens:
        return 0.0
    a_set = set(a_tokens)
    b_set = set(b_tokens)
    return len(a_set & b_set) / len(a_set)


def _iter_kb(kb_path: Path):
    """Yield parsed entries from a JSONL KB file. Skips blank + malformed lines."""
    with kb_path.open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                yield json.loads(stripped)
            except json.JSONDecodeError:
                continue


# =============================================================================
# Part 2: TOOL 1 — cognitive_mirror
# =============================================================================

class CognitiveMirrorInput(ToolInput):
    context: str = Field(
        description="Current user input or topic — used to retrieve relevant DIRECTIVE patterns.",
    )
    k: int = Field(
        default=3, ge=1, le=10,
        description="Number of top patterns to return.",
    )


@Tool.register("cognitive_mirror")
class CognitiveMirrorTool(CognitiveToolBase):
    """Surface user's own DIRECTIVE-tagged Cognitive_Pattern entries relevant to current context."""

    name = "cognitive_mirror"
    description = (
        "Search the KB for Cognitive_Pattern entries tagged DIRECTIVE that are "
        "relevant to the given context. Use BEFORE responding to a user request "
        "to load user-specific behavioral rules (compression style, no fluff, "
        "ambition framing, visceral imagery, etc.) into the prompt frame."
    )
    input_schema = CognitiveMirrorInput

    @property
    def is_concurrency_safe(self) -> bool:
        return True

    async def invoke(self, tool_input: CognitiveMirrorInput) -> ToolResult:
        ctx_tokens = _tokenize(tool_input.context)
        if not ctx_tokens:
            return ToolResult(output={"patterns": [], "count": 0})

        try:
            candidates: List[tuple[float, Dict[str, Any]]] = []
            for entry in _iter_kb(self._kb_path):
                if entry.get("type") != "Cognitive_Pattern":
                    continue
                tags = entry.get("tags", []) or []
                if "DIRECTIVE" not in tags:
                    continue
                content_tokens = _tokenize(entry.get("content", ""))
                score = _overlap_ratio(ctx_tokens, content_tokens)
                if score > 0:
                    candidates.append((score, entry))
        except FileNotFoundError:
            return ToolResult(error=f"KB not found at {self._kb_path}")
        except OSError as e:
            return ToolResult(error=f"KB read failed: {e}")

        candidates.sort(key=lambda pair: pair[0], reverse=True)
        top = candidates[: tool_input.k]
        return ToolResult(output={
            "patterns": [
                {
                    "timestamp": e.get("timestamp"),
                    "tags": e.get("tags", []),
                    "content": e.get("content", ""),
                    "match_score": round(score, 3),
                }
                for score, e in top
            ],
            "count": len(top),
        })


# =============================================================================
# Part 3: TOOL 2 — prior_self_consult
# =============================================================================

class PriorSelfConsultInput(ToolInput):
    query: str = Field(description="What you'd ask past-self about this topic.")
    days_back: int = Field(
        default=90, ge=1, le=720,
        description="Time window in days (look back N days from now).",
    )
    types: Optional[List[str]] = Field(
        default=None,
        description="Optional KB type filter (e.g., ['Decision', 'Episodic']). None = all types.",
    )
    top_n: int = Field(default=8, ge=1, le=20, description="Max results to return.")


_EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_EMBED_HEAD_CHARS = 1000   # MiniLM truncates at 256 tokens — make the cut explicit
_SEMANTIC_WEIGHT = 0.6     # cosine recall (vocabulary-mismatch-proof)
_LEXICAL_WEIGHT = 0.4      # token-overlap precision (exact terms, ids, codes)
# Recency prior — the trap-probe lesson (2026-06-12) made systematic. Pure
# relevance ranks a SUPERSEDED decision above the one that superseded it,
# because the old entry is densely on-topic while the superseding entry spreads
# across many concerns. A memory recalling "what did we decide about X" weights
# its NEWEST memory of X. Multiplicative + bounded: an irrelevant-but-recent
# entry (base ~0) stays ~0; a relevant entry gets up to +RECENCY_BOOST, decaying
# by half every HALFLIFE days. Tie-break newest-first remains as a backstop.
_RECENCY_BOOST = 0.35
_RECENCY_HALFLIFE_DAYS = 25.0

# One lazily-built default embedder + one KB embedding index per (path, embedder),
# invalidated on file mtime/size change — ~350 entries embed in seconds on CPU
# and then every consult in the process is a dot-product scan.
_DEFAULT_EMBED: List[Optional[EmbedFn]] = [None]
_KB_EMBED_CACHE: Dict[Any, Any] = {}


def _default_embed_fn() -> EmbedFn:
    if _DEFAULT_EMBED[0] is None:
        _DEFAULT_EMBED[0] = _build_default_embed_fn(_EMBED_MODEL)
    return _DEFAULT_EMBED[0]


def _kb_embed_index(kb_path: Path, embed_fn: EmbedFn) -> List[tuple]:
    """[(ts, entry, unit_vec)] for the whole KB — cached by (path, embedder, mtime, size)."""
    st = kb_path.stat()
    key = (str(kb_path), id(embed_fn))
    cached = _KB_EMBED_CACHE.get(key)
    if cached and cached[0] == (st.st_mtime_ns, st.st_size):
        return cached[1]
    entries = list(_iter_kb(kb_path))
    vecs = embed_fn([e.get("content", "")[:_EMBED_HEAD_CHARS] for e in entries]) if entries else []
    index = [(_parse_iso_utc(e.get("timestamp", "")), e, v) for e, v in zip(entries, vecs)]
    _KB_EMBED_CACHE[key] = ((st.st_mtime_ns, st.st_size), index)
    return index


@Tool.register("prior_self_consult")
class PriorSelfConsultTool(CognitiveToolBase):
    """Time-windowed KB query — surface past decisions/episodics relevant to current query."""

    name = "prior_self_consult"
    description = (
        "Query the KB within a time window (default last 90 days) for entries "
        "relevant to the query string (semantic + keyword relevance). Use to "
        "consult past decisions / episodic events before making a similar "
        "choice now. Defends against drift from prior reasoning. Results are "
        "newest-first within equal relevance — a newer Decision supersedes an "
        "older one on the same topic."
    )
    input_schema = PriorSelfConsultInput

    # META-ENTRIES — records ABOUT sessions/probes — contain the asked
    # question's exact vocabulary, so they outrank the entries holding the
    # actual ANSWER. Observed live twice on 2026-06-12: (1) session distills
    # echo the question verbatim (a re-asked question retrieves its own echo;
    # stale answers self-reinforce); (2) the Failure entry DOCUMENTING the trap
    # probe became the top hit for the trap phrasing, and its truncated head
    # ends on the wrong-answer quote — the model read a failure description as
    # policy. Self-observation contaminating the observed. Down-weight, never
    # exclude ("what did I ask you last time?" must still find distills).
    # 0.3, not 0.5: a meta-entry scores ~1.0 raw while real entries cannot
    # match the question's chat words, so the weight must push meta hits below
    # any entry covering >=~30% of the query.
    _META_TAGS = frozenset({"session-distill", "trap-probe"})
    _DEFAULT_META_WEIGHT = 0.3
    # Head-truncate each hit: 5 FULL contents (~2,000 chars each for battle-plan
    # class entries) silently overflowed the ReAct 4,000-char observation cap —
    # ranks 4-5 were never actually seen by the model. 8 bounded hits fit.
    _CONTENT_HEAD_CHARS = 450

    def __init__(self, *args: Any, meta_weight: float = _DEFAULT_META_WEIGHT,
                 embed_fn: Optional[EmbedFn] = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._meta_weight = meta_weight
        self._embed_fn = embed_fn

    @property
    def is_concurrency_safe(self) -> bool:
        return True

    def _embedder(self) -> EmbedFn:
        return self._embed_fn or _default_embed_fn()

    async def invoke(self, tool_input: PriorSelfConsultInput) -> ToolResult:
        query_tokens = _tokenize(tool_input.query)
        if not query_tokens:
            return ToolResult(output={"results": [], "count": 0})

        cutoff = datetime.now(timezone.utc) - timedelta(days=tool_input.days_back)
        type_filter = set(tool_input.types) if tool_input.types else None

        try:
            embed = self._embedder()
            index = _kb_embed_index(self._kb_path, embed)
            query_vec = embed([tool_input.query])[0]
        except FileNotFoundError:
            return ToolResult(error=f"KB not found at {self._kb_path}")
        except OSError as e:
            return ToolResult(error=f"KB read failed: {e}")

        now = datetime.now(timezone.utc)
        hits: List[tuple[float, datetime, Dict[str, Any]]] = []
        for ts, entry, vec in index:
            if type_filter and entry.get("type") not in type_filter:
                continue
            if ts is None or ts < cutoff:
                continue
            semantic = max(0.0, _dot(query_vec, vec))
            lexical = _overlap_ratio(query_tokens, _tokenize(entry.get("content", "")))
            score = _SEMANTIC_WEIGHT * semantic + _LEXICAL_WEIGHT * lexical
            age_days = max(0.0, (now - ts).total_seconds() / 86400.0)
            score *= 1.0 + _RECENCY_BOOST * math.exp(-age_days / _RECENCY_HALFLIFE_DAYS)
            if self._META_TAGS & set(entry.get("tags") or []):
                score *= self._meta_weight
            if score > 0:
                hits.append((score, ts, entry))

        # Newest-first within near-equal relevance (0.01 score bands): an
        # autobiography that breaks ties oldest-first recites its past as its
        # present (trap probe 2026-06-12 — a superseded Decision was asserted
        # as "standing").
        hits.sort(key=lambda t: (round(t[0], 2), t[1]), reverse=True)
        top = hits[: tool_input.top_n]
        def _content_head(text: str) -> str:
            return (text[: self._CONTENT_HEAD_CHARS] + "…"
                    if len(text) > self._CONTENT_HEAD_CHARS else text)

        return ToolResult(output={
            "results": [
                {
                    "timestamp": e.get("timestamp"),
                    "type": e.get("type"),
                    "tags": e.get("tags", []),
                    "content": _content_head(e.get("content", "")),
                    "match_score": round(score, 3),
                }
                for score, _, e in top
            ],
            "count": len(top),
            "window_days": tool_input.days_back,
        })


def _parse_iso_utc(ts: str) -> Optional[datetime]:
    """Parse ISO 8601 timestamp; coerce naive to UTC. Returns None on parse failure."""
    if not ts:
        return None
    try:
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


# =============================================================================
# Part 4: TOOL 3 — bear_case_devil
# =============================================================================

class BearCaseDevilInput(ToolInput):
    position_thesis: str = Field(
        description="The bullish thesis to attack (position, decision, project plan)."
    )
    domain: str = Field(
        default="finance",
        description="Domain context: finance | project | decision | architecture.",
    )


_BEAR_CASE_PROMPT = """You are a contrarian devil's advocate. Generate the strongest structured \
bear case against the following thesis in the {domain} domain.

THESIS: {thesis}

Return ONLY a JSON object with exactly these keys (no prose outside the JSON):
  bear_case: a 3-paragraph contrarian argument (concrete, with numbers if applicable)
  kill_switches: a list of 3 specific conditions that would prove the bear case correct
  worst_case_pnl: estimated drawdown / cost if bear case fully realizes (string with units)
"""


@Tool.register("bear_case_devil")
class BearCaseDevilTool(CognitiveToolBase):
    """Generate structured contrarian bear case against a thesis. Requires llm_call DI."""

    name = "bear_case_devil"
    description = (
        "Force structured falsification of a bullish thesis. Returns bear_case "
        "(3-paragraph contrarian argument), kill_switches (3 conditions that "
        "would prove the bear case), and worst_case_pnl (estimated drawdown). "
        "Use BEFORE any high-conviction action: position re-buy, feature ship, "
        "architectural commitment."
    )
    input_schema = BearCaseDevilInput

    @property
    def is_concurrency_safe(self) -> bool:
        return True

    async def invoke(self, tool_input: BearCaseDevilInput) -> ToolResult:
        if self._llm_call is None:
            return ToolResult(error=(
                "bear_case_devil requires llm_call DI; pass it via constructor: "
                "BearCaseDevilTool(llm_call=fn). fn signature: (prompt: str) -> str."
            ))
        prompt = _BEAR_CASE_PROMPT.format(
            domain=tool_input.domain,
            thesis=tool_input.position_thesis,
        )
        try:
            raw = self._llm_call(prompt)
        except Exception as e:
            return ToolResult(error=f"llm_call raised: {type(e).__name__}: {e}")

        # Robust JSON extraction (matches parser.py pattern: fence then brace fallback)
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", raw, re.DOTALL)
        json_str = json_match.group(1) if json_match else None
        if not json_str:
            brace_match = re.search(r"\{.*\}", raw, re.DOTALL)
            json_str = brace_match.group(0) if brace_match else None
        if not json_str:
            return ToolResult(error=f"LLM did not return JSON. Raw[:200]: {raw[:200]}")

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            return ToolResult(error=f"JSON parse failed: {e}. Raw[:200]: {raw[:200]}")

        # Schema check: require all 3 keys
        missing = {"bear_case", "kill_switches", "worst_case_pnl"} - set(data.keys())
        if missing:
            return ToolResult(error=f"LLM response missing keys: {sorted(missing)}")
        if not isinstance(data["kill_switches"], list):
            return ToolResult(error=f"kill_switches must be a list; got {type(data['kill_switches']).__name__}")

        return ToolResult(output=data)


# =============================================================================
# Part 5: TOOL 4 — writing_voice_check
# =============================================================================

class WritingVoiceCheckInput(ToolInput):
    text: str = Field(description="Text to analyze for voice consistency with user's writing style.")


# Voice criteria from KB L265 (aesthetic_compression_cross_domain) +
# L267-L270 (insufficiency_as_sin / visceral_imagination_test / ambition_over_passion).
_SYCOPHANTIC_PHRASES: tuple[str, ...] = (
    "great question", "let me help", "i'd be happy to", "i hope this helps",
    "feel free to ask", "no problem", "absolutely", "certainly happy to",
    "of course!", "happy to assist", "i'm glad",
)
_HEDGE_PHRASES: tuple[str, ...] = (
    "kind of", "sort of", "i think maybe", "perhaps", "might be",
    "could potentially", "in some sense", "more or less",
)


@Tool.register("writing_voice_check")
class WritingVoiceCheckTool(CognitiveToolBase):
    """Heuristic voice-style check against user's compressed-minimalist patterns."""

    name = "writing_voice_check"
    description = (
        "Heuristic style audit against user's known writing voice: rejects "
        "sycophantic openers, excessive hedging, verbose sentences, low "
        "numerical density. Returns a voice_match_score in [0, 1] plus explicit "
        "deviation list. Use BEFORE emitting user-facing text."
    )
    input_schema = WritingVoiceCheckInput

    @property
    def is_concurrency_safe(self) -> bool:
        return True

    async def invoke(self, tool_input: WritingVoiceCheckInput) -> ToolResult:
        text = tool_input.text
        if not text.strip():
            return ToolResult(output={
                "voice_match_score": 0.0,
                "deviations": ["empty_text"],
                "metrics": {},
            })

        lower = text.lower()
        words = re.findall(r"\w+", text)
        sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]

        n_words = len(words)
        n_sentences = max(1, len(sentences))
        avg_sentence_len = n_words / n_sentences

        sycophant_count = sum(1 for p in _SYCOPHANTIC_PHRASES if p in lower)
        hedge_count = sum(1 for p in _HEDGE_PHRASES if p in lower)
        n_numerals = len(re.findall(r"\b\d+(?:\.\d+)?\b", text))
        numeral_density = n_numerals / max(1, n_words)

        deviations: List[str] = []
        score = 1.0

        if sycophant_count > 0:
            deviations.append(
                f"sycophantic_phrases: {sycophant_count} match(es). Violates L265 aesthetic_compression."
            )
            score -= 0.25 * sycophant_count
        if hedge_count > 2:
            deviations.append(
                f"hedge_phrases: {hedge_count}. Voice prefers directness "
                f"(L268 insufficiency_as_sin)."
            )
            score -= 0.10 * (hedge_count - 2)
        if avg_sentence_len > 28 and n_words > 30:
            deviations.append(
                f"avg_sentence_len={avg_sentence_len:.0f}. Voice favors compressed "
                f"sentences (~12-20 words)."
            )
            score -= 0.15
        if numeral_density < 0.005 and n_words > 50:
            deviations.append(
                "low_numeral_density. Voice favors concrete numbers + visceral "
                "imagery over abstract claims (L269 visceral_imagination_test)."
            )
            score -= 0.10

        score = max(0.0, min(1.0, score))
        return ToolResult(output={
            "voice_match_score": round(score, 2),
            "deviations": deviations,
            "metrics": {
                "n_words": n_words,
                "n_sentences": n_sentences,
                "avg_sentence_len": round(avg_sentence_len, 1),
                "sycophant_phrases": sycophant_count,
                "hedge_phrases": hedge_count,
                "numeral_density": round(numeral_density, 4),
            },
        })


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS  (synthetic KB + mock llm_call)
# =============================================================================

if __name__ == "__main__":
    import asyncio
    import tempfile
    from jarvis_core.agent.tool import safe_invoke

    print("=" * 70)
    print("  cognitive tools — smoke tests (synthetic KB, mock llm_call)")
    print("=" * 70)

    # Build a synthetic KB JSONL with realistic entries. Timestamps are RELATIVE
    # to now — absolute dates time-bombed this suite once (the "recent" Decision
    # silently aged out of its 30-day window on 2026-06-12).
    _IST_TZ = timezone(timedelta(hours=5, minutes=30))
    _NOW = datetime.now(_IST_TZ)

    def _days_ago(n: int) -> str:
        return (_NOW - timedelta(days=n)).isoformat(timespec="seconds")

    test_entries = [
        # DIRECTIVE Cognitive_Patterns
        {"timestamp": _days_ago(5), "type": "Cognitive_Pattern",
         "tags": ["identity", "ambition", "DIRECTIVE"],
         "content": "Insufficiency as sin. Greatest sin is to be a fraction of what you could be.",
         "expiry": "Permanent"},
        {"timestamp": _days_ago(5), "type": "Cognitive_Pattern",
         "tags": ["compression", "minimalism", "DIRECTIVE"],
         "content": "Aesthetic compression. Same minimalism discipline in poetry and code. No wasted words.",
         "expiry": "Permanent"},
        # Cognitive_Pattern without DIRECTIVE (should be excluded)
        {"timestamp": _days_ago(5), "type": "Cognitive_Pattern",
         "tags": ["compression", "background"],
         "content": "Background observation about compression patterns.",
         "expiry": "Permanent"},
        # Recent Decision (safely inside the 30-day window)
        {"timestamp": _days_ago(9), "type": "Decision",
         "tags": ["openclaude", "reversal", "stage-3"],
         "content": "Build agent from scratch in jarvis_core/agent/ instead of OpenClaude delegation.",
         "expiry": "Permanent"},
        # Old Decision (outside the 30-day window)
        {"timestamp": _days_ago(180), "type": "Decision",
         "tags": ["legacy"],
         "content": "Some old reversal decision about openclaude scratch agent.",
         "expiry": "Permanent"},
        # Recent Episodic
        {"timestamp": _days_ago(7), "type": "Episodic",
         "tags": ["test"],
         "content": "Ran test on openclaude bridge integration. Result was negative.",
         "expiry": "Permanent"},
        # Supersession pair: SAME query-token overlap, 40 days apart (PSC4)
        {"timestamp": _days_ago(41), "type": "Decision",
         "tags": ["brain", "kimchi-deploy"],
         "content": "Decision: deploy the kimchi brain on cloudpods as the default route.",
         "expiry": "Permanent"},
        {"timestamp": _days_ago(1), "type": "Decision",
         "tags": ["brain", "kimchi-deploy", "supersedes"],
         "content": "Decision: deploy of the kimchi brain on cloudpods is DEFERRED; zero-cost route stands.",
         "expiry": "Permanent"},
        # Session-distill echoing a likely query verbatim (PSC5/PSC6)
        {"timestamp": _days_ago(0), "type": "Episodic",
         "tags": ["session-distill", "terminal", "general"],
         "content": "Terminal session distill (brain-x): Q: what did we decide about kimchi cloudpods deploy? | A: deferred | tools: none",
         "expiry": "Permanent"},
        # Probe-documentation Failure sharing the probed question's vocabulary (PSC8)
        {"timestamp": _days_ago(0), "type": "Failure",
         "tags": ["trap-probe", "retrieval"],
         "content": "Failure: trap probe about the kimchi cloudpods deploy budget decision; system wrongly recited the old deploy as standing.",
         "expiry": "Permanent"},
    ]
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as kbf:
        for e in test_entries:
            kbf.write(json.dumps(e) + "\n")
        kb_test_path = Path(kbf.name)

    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as kbf2:
        kbf2.write(json.dumps({
            "timestamp": _days_ago(1), "type": "Decision", "tags": ["longform"],
            "content": "longform marker entry " + "x" * 3000, "expiry": "Permanent",
        }) + "\n")
        kb_long_path = Path(kbf2.name)

    # Deterministic offline embedder for PSC tests: bag-of-keywords unit vector
    # over a fixed vocab — cosine then behaves like lexical similarity, so the
    # ranking logic (blend, ties, weights, filters) is tested without downloads.
    _FAKE_VOCAB = ["openclaude", "reversal", "scratch", "agent", "kimchi",
                   "cloudpods", "deploy", "decision", "budget", "terminal",
                   "distill", "longform", "marker", "entry", "brain", "bridge"]

    def fake_embed(texts: List[str]) -> List[List[float]]:
        out: List[List[float]] = []
        for t in texts:
            tl = t.lower()
            vec = [1.0 if w in tl else 0.0 for w in _FAKE_VOCAB]
            norm = sum(x * x for x in vec) ** 0.5
            out.append([x / norm for x in vec] if norm else vec)
        return out

    def mock_llm_good(prompt: str) -> str:
        return ('{"bear_case": "Para1: structural mismatch. Para2: timing risk. Para3: '
                'capital constraints.", "kill_switches": ["price <50", "earnings miss '
                '>10%", "ASIC supply glut"], "worst_case_pnl": "-40%"}')

    def mock_llm_bad(prompt: str) -> str:
        return "I cannot fulfill this request."

    def mock_llm_partial(prompt: str) -> str:
        return '{"bear_case": "x", "kill_switches": ["a"]}'  # missing worst_case_pnl

    async def run() -> None:
        passed = 0
        failed: List[str] = []

        def check(name: str, cond: bool, hint: str = "") -> None:
            nonlocal passed
            if cond:
                passed += 1
            else:
                failed.append(f"FAIL: {name}" + (f" ({hint})" if hint else ""))

        # -- cognitive_mirror ---------------------------------------------
        cm = CognitiveMirrorTool(kb_path=kb_test_path)
        r1 = await safe_invoke(cm, {"context": "minimalism compression discipline", "k": 3})
        check("CM1 success", r1.is_success)
        check("CM1 returns patterns",
              r1.is_success and r1.output["count"] >= 1)
        check("CM1 finds aesthetic_compression match",
              r1.is_success and any("compression" in p["content"].lower()
                                    for p in r1.output["patterns"]))
        check("CM1 excludes non-DIRECTIVE Cognitive_Pattern",
              r1.is_success and all("DIRECTIVE" in p["tags"]
                                    for p in r1.output["patterns"]))
        check("CM1 excludes non-Cognitive_Pattern types",
              r1.is_success and not any("OpenClaude" in p["content"]
                                        for p in r1.output["patterns"]))

        r2 = await safe_invoke(cm, {"context": "", "k": 3})
        check("CM2 empty context returns empty",
              r2.is_success and r2.output["count"] == 0)

        # -- prior_self_consult -------------------------------------------
        psc = PriorSelfConsultTool(kb_path=kb_test_path, embed_fn=fake_embed)
        r3 = await safe_invoke(psc, {"query": "openclaude reversal scratch agent", "days_back": 30})
        check("PSC1 success", r3.is_success)
        check("PSC1 finds recent decision",
              r3.is_success and any("Decision" == r["type"]
                                    for r in r3.output["results"]))
        check("PSC1 excludes old (outside 30-day window) decision",
              r3.is_success and not any("legacy" in r.get("tags", [])
                                        for r in r3.output["results"]))

        r4 = await safe_invoke(psc, {
            "query": "openclaude reversal", "days_back": 30, "types": ["Episodic"],
        })
        check("PSC2 type filter narrows to Episodic only",
              r4.is_success and all(r["type"] == "Episodic"
                                    for r in r4.output["results"]))

        r5 = await safe_invoke(psc, {"query": "totally_unrelated_xyzzy"})
        check("PSC3 unrelated query returns empty",
              r5.is_success and r5.output["count"] == 0)

        # PSC4: newest-first ties — equal-overlap supersession pair must rank
        # the NEWER Decision first (trap probe 2026-06-12: oldest-first ties
        # made a superseded decision read as "standing")
        r5b = await safe_invoke(psc, {"query": "kimchi cloudpods deploy decision",
                                      "days_back": 90, "types": ["Decision"]})
        deploy_hits = [r["content"] for r in r5b.output["results"]]
        check("PSC4 newest-first within equal relevance",
              r5b.is_success and len(deploy_hits) >= 2
              and "DEFERRED" in deploy_hits[0],
              str(deploy_hits[:2]))

        # PSC5: a session-distill echoing the query verbatim must NOT outrank
        # real Decisions (echo down-weight)
        r5c = await safe_invoke(psc, {"query": "what did we decide about kimchi cloudpods deploy",
                                      "days_back": 90})
        check("PSC5 distill echo ranks below real Decisions",
              r5c.is_success and r5c.output["results"][0]["type"] == "Decision"
              and "session-distill" not in r5c.output["results"][0]["tags"],
              str([(r["type"], r["tags"]) for r in r5c.output["results"][:2]]))

        # PSC6: down-weight is not exclusion — the distill is still retrievable
        # when it is the only match
        r5d = await safe_invoke(psc, {"query": "terminal session distill brain-x",
                                      "days_back": 90})
        check("PSC6 distill still retrievable when only match",
              r5d.is_success and any("session-distill" in r["tags"]
                                     for r in r5d.output["results"]),
              str(r5d.output["results"][:1]))

        # PSC8: a Failure entry DOCUMENTING a probe (sharing its vocabulary)
        # must rank below the real Decision — self-observation must not
        # contaminate the observed (live regression, trap run 3, 2026-06-12)
        r5f = await safe_invoke(psc, {"query": "kimchi cloudpods deploy budget decision",
                                      "days_back": 90})
        check("PSC8 probe-documentation ranks below the real Decision",
              r5f.is_success and r5f.output["results"][0]["type"] == "Decision"
              and "trap-probe" not in r5f.output["results"][0]["tags"]
              and "DEFERRED" in r5f.output["results"][0]["content"],
              str([(r["type"], r["tags"]) for r in r5f.output["results"][:2]]))

        # PSC7: hit contents are head-truncated so top_n results fit the ReAct
        # observation cap (full contents silently overflowed it — trap probe)
        psc_long = PriorSelfConsultTool(kb_path=kb_long_path, embed_fn=fake_embed)
        r5e = await safe_invoke(psc_long, {"query": "longform marker entry"})
        check("PSC7 hit content head-truncated",
              r5e.is_success and r5e.output["count"] == 1
              and len(r5e.output["results"][0]["content"]) <= 460
              and r5e.output["results"][0]["content"].endswith("…"),
              str(len(r5e.output["results"][0]["content"]) if r5e.output["results"] else 0))

        # -- bear_case_devil ----------------------------------------------
        bcd = BearCaseDevilTool(llm_call=mock_llm_good)
        r6 = await safe_invoke(bcd, {
            "position_thesis": "AVGO will outperform NVDA over next 5 years",
            "domain": "finance",
        })
        check("BCD1 success with valid llm",
              r6.is_success, hint=str(r6.error if r6.is_error else ""))
        check("BCD1 returns bear_case + kill_switches + worst_case_pnl",
              r6.is_success and set(r6.output.keys()) >= {"bear_case", "kill_switches", "worst_case_pnl"})
        check("BCD1 kill_switches is a list",
              r6.is_success and isinstance(r6.output["kill_switches"], list)
              and len(r6.output["kill_switches"]) == 3)

        bcd_no_llm = BearCaseDevilTool(llm_call=None)
        r7 = await safe_invoke(bcd_no_llm, {"position_thesis": "x", "domain": "finance"})
        check("BCD2 missing llm_call -> clean error",
              r7.is_error and "llm_call" in r7.error.lower())

        bcd_bad = BearCaseDevilTool(llm_call=mock_llm_bad)
        r8 = await safe_invoke(bcd_bad, {"position_thesis": "x", "domain": "finance"})
        check("BCD3 non-JSON llm response -> clean error",
              r8.is_error and "json" in r8.error.lower())

        bcd_partial = BearCaseDevilTool(llm_call=mock_llm_partial)
        r9 = await safe_invoke(bcd_partial, {"position_thesis": "x", "domain": "finance"})
        check("BCD4 incomplete-schema llm response -> clean error",
              r9.is_error and "missing keys" in r9.error.lower())

        # -- writing_voice_check ------------------------------------------
        wvc = WritingVoiceCheckTool()

        r10 = await safe_invoke(wvc, {
            "text": "Of course! Let me help you with this great question. I'd be "
                    "happy to assist. I hope this helps!"
        })
        check("WVC1 sycophantic text scores low",
              r10.is_success and r10.output["voice_match_score"] < 0.5,
              hint=str(r10.output.get("voice_match_score")))
        check("WVC1 flags sycophantic",
              r10.is_success and any("sycophant" in d for d in r10.output["deviations"]))

        r11 = await safe_invoke(wvc, {
            "text": "Built 11 tools. 9 concurrency-safe, 2 unsafe. KB at 294 entries. "
                    "Stage 3.2 at 11/19. Phase C ships 7 tools today."
        })
        check("WVC2 compressed-numeric text scores high",
              r11.is_success and r11.output["voice_match_score"] >= 0.8,
              hint=str(r11.output.get("voice_match_score")))
        check("WVC2 no deviations on clean text",
              r11.is_success and len(r11.output["deviations"]) == 0)

        r12 = await safe_invoke(wvc, {
            "text": "I think maybe perhaps this could potentially work, kind of, "
                    "in some sense, sort of, more or less I think maybe.",
        })
        check("WVC3 hedge-heavy text flagged",
              r12.is_success and any("hedge" in d for d in r12.output["deviations"]))

        r13 = await safe_invoke(wvc, {"text": ""})
        check("WVC4 empty text -> empty_text deviation",
              r13.is_success and "empty_text" in r13.output["deviations"])

        # -- Registry + flags ---------------------------------------------
        expected = {"cognitive_mirror", "prior_self_consult", "bear_case_devil", "writing_voice_check"}
        registered = set(Tool.list_registered())
        check("REG all 4 cognitive tools registered",
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
        print("  All cognitive smoke tests passed.")
        print("=" * 70)

    try:
        asyncio.run(run())
    finally:
        kb_test_path.unlink(missing_ok=True)
        kb_long_path.unlink(missing_ok=True)
