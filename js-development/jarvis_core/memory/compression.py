"""
compression.py

JARVIS Memory Layer: Contextual Compression (Embeddings Filter + LLM Filter
+ Adaptive Gate).

Import with:
    from jarvis_core.memory.compression import (
        should_compress,
        embeddings_filter,
        llm_filter,
        compress_results,
        CompressedHit,
        LLMCall,
    )

=============================================================================
THE BIG PICTURE
=============================================================================

Top-k retrieval (with or without query expansion) returns K candidate chunks.
Each chunk might be 300-800 tokens. With K=5, that's 1500-4000 tokens of
context — most of which is noise (sentences-near-the-relevant-info, not the
relevant info itself). Stuffing all of it into the final-LLM prompt:
    -> wastes tokens (cost)
    -> dilutes signal (precision drops; LLM gets confused by neighboring noise)
    -> hits context window limits faster

Contextual compression strips noise from candidate chunks BEFORE they hit
the final LLM. Two strategies are shipped here; a third (LLM Extractor —
lossy rewriter) is deliberately deferred until 2.5.6 RAGAS measurements
demonstrate the lossless filters aren't precise enough.

=============================================================================
THE TWO STRATEGIES
=============================================================================

EMBEDDINGS FILTER (default, cheap)
    Re-embed each retrieved chunk and the query, drop chunks below a cosine-
    similarity threshold. No LLM call. ~10-50 ms total on CPU for K chunks.
    Same blindspot as the original semantic search (it's cosine similarity
    again), so it reduces VOLUME but not QUALITY of relevance.

LLM FILTER (escalation, cheap-but-smarter, lossless)
    Pass each chunk to a small LLM with "Does this chunk directly answer
    the query? Respond yes or no." Drop the no's. Surviving chunks return
    VERBATIM (lossless). K small LLM calls (~80 input + 1 output tokens
    each = ~$0.0001 per chunk with DeepSeek-V4 / Llama 3 8B). Qualitatively
    different from embeddings filter — the LLM understands "reflective"
    beyond surface tokens, "circular reasoning" matches "self-referential",
    etc.

LLM EXTRACTOR (DEFERRED — not implemented here)
    Would pass each chunk to an LLM with "Extract sentences answering the
    query. Return verbatim quotes only." Lossy (LLM might rewrite or
    hallucinate). Most aggressive compression but riskiest. Implement in
    a separate commit ONLY if 2.5.6 RAGAS measurements show LLM Filter
    isn't precise enough. The "verbatim quotes only" instruction can be
    enforced via post-process substring validation, but that's extra work
    we shouldn't do until justified.

=============================================================================
ADAPTIVE GATE
=============================================================================

should_compress(query, k, total_words) — fail-closed predicate. Returns
False (skip compression, return baseline chunks unchanged) when:
    - K <= 3        : not enough volume to justify cost
    - total_words < 1000 : already tight; compression overhead exceeds gain
    - query has identifier chars (paths, function calls) : code-like
      queries shouldn't be re-filtered by semantics
    - query has acronyms (specific lookups) : expansion gate's logic applies

This mirrors expansion.should_expand and follows the fail-closed adaptive-
gate DIRECTIVE in knowledge_base.jsonl: any unexpected condition returns
the unexpanded baseline behavior, never raises.

=============================================================================
LAYER BOUNDARY NOTE
=============================================================================

Same DI pattern as expansion.py. Memory layer never instantiates an LLM
client — caller passes `llm_call: Callable[[str], str]`. The Memory layer
DOES own its embedding encoder (sentence-transformers), so the Embeddings
Filter strategy is fully self-contained; only LLM Filter requires the
caller to wire an LLM.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

# Reuse the same LLMCall type alias contract used by expansion.py
# (kept as a separate definition to avoid cross-module import coupling;
# both modules use the same Callable[[str], str] shape).
LLMCall = Callable[[str], str]


# =============================================================================
# Part 1: CONSTANTS
# =============================================================================

# Same identifier / acronym heuristics as the expansion gate — kept in sync
# so a query that bypasses expansion also bypasses compression by default.
_IDENTIFIER_CHARS: str = "()[]{}/_.<>"
_ACRONYM_PATTERN: re.Pattern[str] = re.compile(r"\b[A-Z]{2,}[a-z]?\b")

# Adaptive gate thresholds.
_MIN_K_FOR_COMPRESSION: int = 4          # K=1..3 → too few chunks to justify cost
_MIN_WORDS_FOR_COMPRESSION: int = 1000   # < 1000 words total → already tight

# Embeddings filter default. Lower = more permissive (more chunks survive).
# 0.30 calibrated against MiniLM-L6-v2 outputs on the research_papers
# collection: empirically, chunks above 0.30 cosine sim to query are
# usually on-topic, below 0.30 are tangential.
DEFAULT_EMBEDDINGS_THRESHOLD: float = 0.30

# Auto-strategy thresholds (total words across all retrieved chunks).
_AUTO_LLM_FILTER_WORD_FLOOR: int = 1500   # Above this, LLM filter earns its cost
# (Below: embeddings filter is enough; the chunks are tight already.)


# =============================================================================
# Part 2: ADAPTIVE GATE
# =============================================================================

def should_compress(query: str, k: int, total_words: int) -> bool:
    """
    Predicate: is this retrieval result worth compressing?

    Returns False (skip) when ANY of:
        - k <= 3                              : too few chunks
        - total_words < 1000                  : already tight
        - query contains identifier chars     : code-like, exact-match intent
        - query contains acronym              : specific lookup, not concept

    Returns True for medium-to-large retrieval results from conceptual
    queries — exactly where compression earns its keep.
    """
    if k < _MIN_K_FOR_COMPRESSION:
        return False
    if total_words < _MIN_WORDS_FOR_COMPRESSION:
        return False
    if any(c in query for c in _IDENTIFIER_CHARS):
        return False
    if _ACRONYM_PATTERN.search(query):
        return False
    return True


# =============================================================================
# Part 3: STRATEGY 1 — EMBEDDINGS FILTER (default, cheap, lossless)
# =============================================================================

def _cosine(a: List[float], b: List[float]) -> float:
    """Cosine similarity between two vectors, both assumed L2-normalized."""
    # When both vectors are normalized, cosine sim == dot product.
    return float(sum(x * y for x, y in zip(a, b)))


def embeddings_filter(
    chunks: List[str],
    metadatas: List[Dict[str, Any]],
    ids: List[str],
    query: str,
    encoder: Any,
    threshold: float = DEFAULT_EMBEDDINGS_THRESHOLD,
) -> Tuple[List[str], List[Dict[str, Any]], List[str], List[float]]:
    """
    Re-embed each chunk and the query; drop chunks below `threshold`.

    Why "re-embed"? The original retrieval used the chunk-level embedding
    against the query embedding (or HyDE-expanded embedding). Here we are
    not changing what we score against — we are filtering the same scores
    against an explicit threshold, returning chunks anchored to the
    ORIGINAL query (not any expanded form).

    EXECUTION FLOW:
        1. encoder.encode([query] + chunks)  -> normalized vectors
        2. cosine_sim(query, chunk_i) for each i
        3. keep where sim >= threshold
        4. preserve original order (high-rank = high-relevance survives)

    Returns:
        (kept_chunks, kept_metadatas, kept_ids, kept_similarities)
        — parallel lists; empty if all chunks fall below threshold.
    """
    if not chunks:
        return [], [], [], []

    vectors = encoder.encode(
        [query] + chunks,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    query_vec = vectors[0].tolist()
    chunk_vecs = [v.tolist() for v in vectors[1:]]

    kept_chunks: List[str] = []
    kept_metas: List[Dict[str, Any]] = []
    kept_ids: List[str] = []
    kept_sims: List[float] = []
    for chunk, meta, doc_id, vec in zip(chunks, metadatas, ids, chunk_vecs):
        sim = _cosine(query_vec, vec)
        if sim >= threshold:
            kept_chunks.append(chunk)
            kept_metas.append(meta)
            kept_ids.append(doc_id)
            kept_sims.append(sim)

    return kept_chunks, kept_metas, kept_ids, kept_sims


# =============================================================================
# Part 4: STRATEGY 2 — LLM FILTER (escalation, lossless)
# =============================================================================

LLM_FILTER_PROMPT_TEMPLATE: str = (
    'Does the following text passage directly answer or substantively '
    'address this query?\n\n'
    'Query: "{query}"\n\n'
    "Passage:\n{chunk}\n\n"
    'Respond with exactly one word: "yes" or "no". No explanation.'
)


def _parse_yes_no(raw: str) -> bool:
    """Robustly parse a yes/no LLM response.
    Falls open (returns True / keep) on ambiguous output — fail-closed
    means the compression layer never drops chunks it isn't sure about.
    """
    if not raw:
        return True  # ambiguous → keep
    first_word = raw.strip().split()[0].lower().strip(".,!?;:'\"")
    return first_word != "no"  # explicit "no" drops; everything else keeps


def llm_filter(
    chunks: List[str],
    metadatas: List[Dict[str, Any]],
    ids: List[str],
    query: str,
    llm_call: LLMCall,
) -> Tuple[List[str], List[Dict[str, Any]], List[str]]:
    """
    For each chunk, ask the LLM if it directly addresses the query;
    drop the no's. Surviving chunks return VERBATIM (lossless).

    EXECUTION FLOW:
        For each chunk:
            1. Format LLM_FILTER_PROMPT_TEMPLATE with query + chunk.
            2. llm_call(prompt) -> "yes" or "no" (or ambiguous).
            3. Parse via _parse_yes_no — explicit "no" drops, anything
               else keeps (fail-open on ambiguity).

    Returns:
        (kept_chunks, kept_metadatas, kept_ids) — verbatim, in original
        rank order. Empty if all chunks rejected.

    Note: this fires K LLM calls. Caller is responsible for rate limiting,
    retries on transient errors, and deciding which model to wire. Use a
    small/fast model (Llama 3 8B, DeepSeek-V4-Flash) — quality matters
    less than throughput here.
    """
    if not chunks:
        return [], [], []

    kept_chunks: List[str] = []
    kept_metas: List[Dict[str, Any]] = []
    kept_ids: List[str] = []
    for chunk, meta, doc_id in zip(chunks, metadatas, ids):
        prompt = LLM_FILTER_PROMPT_TEMPLATE.format(query=query, chunk=chunk)
        try:
            verdict = llm_call(prompt)
        except Exception:
            # Fail-closed at the chunk level: on LLM error, keep the chunk.
            verdict = ""
        if _parse_yes_no(verdict):
            kept_chunks.append(chunk)
            kept_metas.append(meta)
            kept_ids.append(doc_id)

    return kept_chunks, kept_metas, kept_ids


# =============================================================================
# Part 5: ORCHESTRATOR — gate + strategy dispatch
# =============================================================================

VALID_STRATEGIES: Tuple[str, ...] = ("embeddings", "llm_filter", "auto")


@dataclass(frozen=True)
class CompressedHit:
    """LAYER: Memory — one chunk that survived compression.

    Frozen so callers can pass these into a Stage 3+ Brain aggregator
    without risk of mutation. Includes the surviving relevance signal
    (cosine sim for embeddings filter, None for LLM filter — chunks are
    binary kept/dropped, no per-chunk score).
    """
    chunk_id: str
    document: str
    metadata: Dict[str, Any]
    sim: Optional[float]  # cosine sim from embeddings filter; None for LLM filter
    survived: str         # "embeddings" | "llm_filter" | "baseline"


def compress_results(
    retrieval_result: Dict[str, Any],
    query: str,
    encoder: Any,
    llm_call: Optional[LLMCall] = None,
    strategy: str = "auto",
    threshold: float = DEFAULT_EMBEDDINGS_THRESHOLD,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Main entry point. Apply the adaptive gate; dispatch to the chosen
    strategy; return a standardized result dict.

    EXECUTION FLOW:
        1. Validate strategy.
        2. Extract chunks/metas/ids from retrieval_result (ChromaDB-format).
        3. Compute total_words; check should_compress(query, k, total_words).
           If gate says skip and force=False -> return baseline unchanged.
        4. If strategy == "auto": pick "llm_filter" if total_words >=
           _AUTO_LLM_FILTER_WORD_FLOOR AND llm_call provided; else
           "embeddings".
        5. Dispatch to embeddings_filter or llm_filter.
        6. Repackage result as a ChromaDB-format dict (callers consume it
           the same way they consume query_collection output).

    Args:
        retrieval_result : dict from store.query_collection or
                           expand_then_query. Must have "ids", "documents",
                           "metadatas" keys; "distances" optional.
        query            : User query (or agent sub-query).
        encoder          : sentence-transformers SentenceTransformer
                           instance. Required for embeddings strategy.
        llm_call         : Caller-injected LLM. Required for llm_filter.
        strategy         : "embeddings" | "llm_filter" | "auto".
        threshold        : Embeddings filter threshold.
        force            : If True, bypass should_compress gate.

    Returns:
        Dict with keys:
            "compressed"     : bool — was compression applied?
            "strategy"       : "embeddings" | "llm_filter" | "baseline"
            "result"         : ChromaDB-format dict (always present)
            "fused_hits"     : List[CompressedHit] (only when compressed)
            "tokens_kept_ratio": float — kept_words / original_words
                               (only when compressed; 1.0 means no reduction)

    Raises:
        ValueError on invalid strategy or missing llm_call when llm_filter
        is selected.
    """
    if strategy not in VALID_STRATEGIES:
        raise ValueError(
            f"strategy must be one of {VALID_STRATEGIES}, got {strategy!r}"
        )

    # Extract input
    chunks: List[str] = retrieval_result["documents"][0]
    metadatas: List[Dict[str, Any]] = retrieval_result["metadatas"][0]
    ids: List[str] = retrieval_result["ids"][0]
    k = len(chunks)
    total_words = sum(len(c.split()) for c in chunks)

    # Gate check
    if not force and not should_compress(query, k, total_words):
        return {
            "compressed": False,
            "strategy": "baseline",
            "result": retrieval_result,
        }

    # Auto-strategy selection
    if strategy == "auto":
        if total_words >= _AUTO_LLM_FILTER_WORD_FLOOR and llm_call is not None:
            strategy = "llm_filter"
        else:
            strategy = "embeddings"

    # Validate llm_call presence for llm_filter
    if strategy == "llm_filter" and llm_call is None:
        raise ValueError(
            "strategy='llm_filter' requires llm_call to be provided"
        )

    # Dispatch
    if strategy == "embeddings":
        kept_chunks, kept_metas, kept_ids, kept_sims = embeddings_filter(
            chunks, metadatas, ids, query, encoder, threshold,
        )
        hits = [
            CompressedHit(
                chunk_id=i, document=d, metadata=m,
                sim=s, survived="embeddings",
            )
            for i, d, m, s in zip(kept_ids, kept_chunks, kept_metas, kept_sims)
        ]
    else:
        # llm_filter
        kept_chunks, kept_metas, kept_ids = llm_filter(
            chunks, metadatas, ids, query, llm_call,
        )
        hits = [
            CompressedHit(
                chunk_id=i, document=d, metadata=m,
                sim=None, survived="llm_filter",
            )
            for i, d, m in zip(kept_ids, kept_chunks, kept_metas)
        ]

    # Repackage as ChromaDB-format result for caller compatibility
    if hits:
        result = {
            "ids": [[h.chunk_id for h in hits]],
            "documents": [[h.document for h in hits]],
            "metadatas": [[h.metadata for h in hits]],
            "distances": [[
                (1.0 - h.sim) if h.sim is not None else 0.0
                for h in hits
            ]],
        }
    else:
        # Edge case: all chunks dropped. Return empty ChromaDB shape.
        result = {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

    kept_words = sum(len(d.split()) for d in (h.document for h in hits))
    ratio = (kept_words / total_words) if total_words > 0 else 1.0

    return {
        "compressed": True,
        "strategy": strategy,
        "result": result,
        "fused_hits": hits,
        "tokens_kept_ratio": ratio,
    }


# =============================================================================
# MAIN ENTRY POINT (smoke test — no live ChromaDB or LLM required)
# =============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("  jarvis_core.memory.compression — smoke test (stubs only)")
    print("=" * 70)

    # ------------------------------------------------------------------
    # 1. should_compress decisions
    # ------------------------------------------------------------------
    print("\n[1] should_compress() decisions")
    cases = [
        # (query, k, total_words, expected)
        ("what is dropout regularization", 5, 1500, True),    # all conditions met
        ("what is dropout regularization", 2, 1500, False),   # k too low
        ("what is dropout regularization", 5, 500, False),    # words too few
        ("ChromaDB.query_collection error", 5, 1500, False),  # identifier
        ("explain MMR algorithm", 5, 1500, False),            # acronym
    ]
    for query, k, words, expected in cases:
        actual = should_compress(query, k, words)
        ok = "ok  " if actual == expected else "FAIL"
        print(f"  [{ok}] should_compress({query!r:35s}, k={k}, words={words}) = {actual} (expected {expected})")

    # ------------------------------------------------------------------
    # 2. Stub encoder + stub LLM for compress_results dispatch testing
    # ------------------------------------------------------------------
    print("\n[2] compress_results() flow")

    class _StubEncoder:
        """Returns deterministic dummy vectors. First chunk gets high sim
        to query; later chunks get progressively lower sim. Tests the
        threshold-drop behavior."""
        def encode(self, texts, normalize_embeddings=True, show_progress_bar=False):
            import numpy as np
            n = len(texts)
            # query_vec = [1, 0, 0]; chunk_i_vec = scaled toward [1,0,0]
            # sim drops as i increases.
            vecs = [[1.0, 0.0, 0.0]]  # query
            for i in range(n - 1):
                # chunk_0: sim 0.95; chunk_1: 0.70; chunk_2: 0.45; chunk_3: 0.20
                similarity_to_query = 0.95 - (i * 0.25)
                # Build a unit vector with that cosine to [1,0,0]
                a = similarity_to_query
                b = (1 - a * a) ** 0.5
                vecs.append([a, b, 0.0])
            return np.array(vecs)

    def stub_llm(prompt: str) -> str:
        # Drop chunks containing "irrelevant"; keep all others.
        if "irrelevant" in prompt.lower():
            return "no"
        return "yes"

    # Build a fake retrieval_result with 4 chunks of varying lengths.
    fake_retrieval = {
        "ids":       [["c0", "c1", "c2", "c3"]],
        "documents": [[
            "highly relevant chunk about dropout " * 60,            # ~360 words
            "moderately relevant chunk about regularization " * 60, # ~360 words
            "tangential chunk about training " * 60,                # ~360 words
            "irrelevant chunk about something else entirely " * 60, # ~360 words
        ]],
        "metadatas": [[
            {"page": 1, "source": "stub.pdf"},
            {"page": 2, "source": "stub.pdf"},
            {"page": 3, "source": "stub.pdf"},
            {"page": 4, "source": "stub.pdf"},
        ]],
        "distances": [[0.30, 0.45, 0.60, 0.80]],
    }

    encoder = _StubEncoder()

    # 2a. embeddings strategy — threshold 0.30 should keep top 3
    out = compress_results(
        fake_retrieval, "dropout regularization",
        encoder=encoder, strategy="embeddings", threshold=0.30,
    )
    print(f"  embeddings strategy : compressed={out['compressed']} strategy={out['strategy']}")
    print(f"                       kept {len(out['fused_hits'])} of 4 chunks")
    print(f"                       sims: {[f'{h.sim:.3f}' for h in out['fused_hits']]}")
    print(f"                       tokens_kept_ratio={out['tokens_kept_ratio']:.2f}")

    # 2b. llm_filter strategy — drops "irrelevant" chunk only
    out = compress_results(
        fake_retrieval, "dropout regularization",
        encoder=encoder, llm_call=stub_llm, strategy="llm_filter",
    )
    print(f"\n  llm_filter strategy : compressed={out['compressed']} strategy={out['strategy']}")
    print(f"                       kept {len(out['fused_hits'])} of 4 chunks")
    print(f"                       (LLM dropped chunks containing 'irrelevant')")

    # 2c. auto strategy — total_words=1440 < 1500 floor → embeddings
    out = compress_results(
        fake_retrieval, "dropout regularization",
        encoder=encoder, llm_call=stub_llm, strategy="auto", threshold=0.30,
    )
    print(f"\n  auto strategy       : compressed={out['compressed']} strategy={out['strategy']}")
    assert out["strategy"] == "embeddings", "auto should pick embeddings under word floor"

    # 2d. Gate skips on short prompt with identifier
    out = compress_results(
        fake_retrieval, "ChromaDB.query_collection error",
        encoder=encoder, llm_call=stub_llm, strategy="auto",
    )
    print(f"\n  identifier query    : compressed={out['compressed']} strategy={out['strategy']}")
    assert out["compressed"] is False

    # ------------------------------------------------------------------
    # 3. Input validation
    # ------------------------------------------------------------------
    print("\n[3] Input validation")
    try:
        compress_results(fake_retrieval, "x", encoder=encoder, strategy="bogus")
        print("  FAIL: expected ValueError on bogus strategy")
    except ValueError as e:
        print(f"  ok   ValueError on bogus strategy: {e}")

    try:
        compress_results(
            fake_retrieval, "what is dropout regularization",
            encoder=encoder, strategy="llm_filter", force=True,
        )
        print("  FAIL: expected ValueError when llm_call missing for llm_filter")
    except ValueError as e:
        print(f"  ok   ValueError when llm_call missing: {e}")

    print("\n" + "=" * 70)
    print("  All smoke checks passed.")
    print("=" * 70)
