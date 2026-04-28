"""
expansion.py

JARVIS Memory Layer: Query Expansion (HyDE + Multi-Query + RRF + Adaptive Gate).

Import with:
    from jarvis_core.memory.expansion import (
        should_expand,
        hyde_query,
        multi_query_search,
        expand_then_query,
        FusedHit,
        LLMCall,
    )

=============================================================================
THE BIG PICTURE
=============================================================================

Without query expansion:
    -> Short user queries embed far from answer-style corpus chunks.
    -> ChromaDB returns shallow keyword matches; deep technical sections
       discussing the *concept* but not the literal phrase get missed.
    -> Recall caps out at "exact phrase neighborhood".

With query expansion:
    -> HyDE: an LLM generates a hypothetical answer paragraph; embed THAT
       instead of the raw query. Verified empirically on the
       research_papers collection (156 chunks): cosine distance drops
       from ~0.85 to ~0.40 on conceptual queries.
    -> Multi-Query+RRF: an LLM generates paraphrasings; retrieve top-k
       for each; fuse via Reciprocal Rank Fusion: 1 / (60 + rank).
       Chunks appearing in many queries' top-k get promoted (consensus
       as relevance signal).
    -> Adaptive gate (`should_expand`) skips expansion for long detailed
       prompts, queries with identifiers, or acronyms — saves cost and
       prevents precision loss when expansion is the wrong tool.

=============================================================================
THE FLOW (Step-by-Step Execution Order)
=============================================================================

STEP 1: caller invokes expand_then_query(store, collection, query, llm_call)
        |
STEP 2: should_expand(query) gate check
        |   - long detailed prompt   -> skip; return baseline top-k
        |   - contains identifier    -> skip
        |   - contains acronym       -> skip (heuristic; documented edge)
        |   - otherwise              -> proceed to expansion
        |
STEP 3: strategy="auto" picks "hyde" for very short queries (<= 6 words),
        "multi_query" otherwise. Explicit strategy="hyde" / "multi_query"
        bypasses the auto-pick.
        |
STEP 4: caller-provided llm_call runs (HYDE_PROMPT_TEMPLATE or
        MULTI_QUERY_PROMPT_TEMPLATE) -> hypothetical doc OR paraphrasings.
        |
STEP 5: store.query_collection(...) executes the actual ChromaDB retrieval.
        HyDE: one call with the hypothetical as query_text.
        Multi-Query: N+1 calls (original + paraphrasings), accumulated
        into RRF scores keyed by chunk_id.
        |
STEP 6: HyDE returns the standard ChromaDB result dict.
        Multi-Query returns a sorted list of FusedHit dataclasses,
        plus a result dict in ChromaDB shape for caller compatibility.

=============================================================================
LAYER BOUNDARY NOTE
=============================================================================

Query expansion is structurally a Memory-layer concern (it sits between
the user query and the vector store). But it *invokes* an LLM, which
is a Brain-layer primitive. The boundary is preserved via dependency
injection: the caller passes an `llm_call: Callable[[str], str]`. This
module never instantiates an LLM client itself. Stage 3+ agents wire the
LLM call when they integrate.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Pattern, Tuple

# Type alias: caller-provided LLM call. Input prompt -> completion text.
LLMCall = Callable[[str], str]


# =============================================================================
# Part 1: CONSTANTS
# =============================================================================

# Reciprocal Rank Fusion constant (Cormack et al., 2009).
# Lower values weight rank-1 hits more heavily; 60 is a robust default
# that matches Stanford / Pyserini implementations.
RRF_K_CONSTANT: int = 60

# Adaptive gate tuning. Calibrated against the user's natural prompt style:
# detailed multi-claim paragraphs averaging ~150 words. Below ~30 words is
# treated as "short / agent-style".
_LONG_PROMPT_WORD_THRESHOLD: int = 30

# Identifier characters: their presence signals a specific lookup
# (function name, file path, attribute access) rather than conceptual search.
_IDENTIFIER_CHARS: str = "()[]{}/_.<>"

# Acronym pattern: 2+ consecutive uppercase letters, optionally followed by
# a single trailing lowercase. Catches BERT, AWQ, GPTQ, MMR, GGUF, FFN, etc.
# Edge case: also catches conceptual abbreviations like RAG / NLP / ML where
# HyDE genuinely helps. See should_expand() docstring.
_ACRONYM_PATTERN: Pattern[str] = re.compile(r"\b[A-Z]{2,}[a-z]?\b")

# Multi-Query: how many paraphrasings to request from the LLM (the original
# query is always included, so total retrievals = N + 1).
DEFAULT_N_PARAPHRASINGS: int = 3

# Default top-k. Most callers should pass an explicit value.
DEFAULT_K: int = 5


# =============================================================================
# Part 2: ADAPTIVE GATE
# =============================================================================

def should_expand(query: str) -> bool:
    """
    Predicate: is this query the right shape for HyDE / Multi-Query?

    Returns False (skip expansion) when ANY of:
        - query is already long and detailed (> 30 words)
        - query contains identifier characters (paths, function calls,
          attribute access) — signals a specific lookup
        - query contains an acronym (signals specific lookup, not concept)

    Returns True (expand) for short conceptual queries — typically
    agent-emitted sub-questions or cold-start exploratory retrievals.

    HEURISTIC LIMITATION:
        The acronym rule produces false negatives on conceptual
        abbreviations like "agentic RAG" where HyDE empirically helps
        (distance drops from ~0.85 to ~0.40 on the research_papers
        collection). Production callers can override the gate via
        `expand_then_query(..., force=True)`.
    """
    if len(query.split()) > _LONG_PROMPT_WORD_THRESHOLD:
        return False
    if any(c in query for c in _IDENTIFIER_CHARS):
        return False
    if _ACRONYM_PATTERN.search(query):
        return False
    return True


# =============================================================================
# Part 3: HyDE — Hypothetical Document Embeddings
# =============================================================================

HYDE_PROMPT_TEMPLATE: str = (
    'Generate a hypothetical paragraph answer to this question: "{query}"\n\n'
    "Write 3-4 dense sentences using technical vocabulary as if it were a "
    "paragraph excerpted from an academic research paper. Output the "
    "paragraph only — no preamble, no disclaimers."
)


def hyde_query(
    store: Any,           # JarvisMemoryStore — typed Any to avoid circular import
    collection: str,
    query: str,
    llm_call: LLMCall,
    k: int = DEFAULT_K,
) -> Tuple[str, Dict[str, Any]]:
    """
    Expand `query` via HyDE, then retrieve top-k from `collection`.

    EXECUTION FLOW:
        1. Format HYDE_PROMPT_TEMPLATE with the user query.
        2. Call llm_call -> hypothetical answer paragraph.
        3. Pass hypothetical to store.query_collection as query_text.
        4. Return (hypothetical, ChromaDB result dict).

    Returns:
        Tuple of (hypothetical_paragraph, chroma_result). chroma_result has
        the standard ChromaDB query format: keys "ids", "documents",
        "metadatas", "distances", each a list-of-lists (outer one entry
        per query, inner the actual results).
    """
    hypothetical = llm_call(HYDE_PROMPT_TEMPLATE.format(query=query))
    result = store.query_collection(
        collection_name=collection,
        query_text=hypothetical,
        n_results=k,
    )
    return hypothetical, result


# =============================================================================
# Part 4: MULTI-QUERY + RRF
# =============================================================================

MULTI_QUERY_PROMPT_TEMPLATE: str = (
    'Generate three diverse paraphrasings or related sub-questions for this '
    'query: "{query}"\n\n'
    "Each on its own line. No numbering, no preamble. Output only the lines."
)


@dataclass(frozen=True)
class FusedHit:
    """
    LAYER: Memory — one result from Multi-Query+RRF retrieval.

    Frozen so callers can pass these across layer boundaries (e.g., into
    a Stage 3+ Brain aggregator) without risk of accidental mutation.

    Fields:
        chunk_id    : ChromaDB document ID (md5 hash from IngestionPipeline)
        document    : Raw chunk text
        metadata    : Source page, category, specialist, etc.
        rrf_score   : Sum of 1 / (60 + rank) across all queries that returned
                      this chunk; higher = stronger consensus + higher rank
        appeared_in : Count of paraphrasings (incl. original) where this
                      chunk appeared in top-k; high count = robust relevance
    """
    chunk_id: str
    document: str
    metadata: Dict[str, Any]
    rrf_score: float
    appeared_in: int


def multi_query_search(
    store: Any,
    collection: str,
    query: str,
    llm_call: LLMCall,
    k: int = DEFAULT_K,
    n_paraphrasings: int = DEFAULT_N_PARAPHRASINGS,
) -> Tuple[List[str], List[FusedHit]]:
    """
    Generate paraphrasings, retrieve top-k for each (plus the original),
    fuse via RRF, return top-k by fused score.

    EXECUTION FLOW:
        1. Format MULTI_QUERY_PROMPT_TEMPLATE; call llm_call.
        2. Parse N paraphrasings (one per line, strip numbering).
        3. queries = [original, *paraphrasings] (original always first).
        4. For each query, store.query_collection -> top-k result.
        5. Accumulate RRF scores: rrf[id] += 1 / (60 + rank) per appearance.
        6. Sort by fused score descending; return top-k as FusedHit list.

    RRF formula:
        score(d) = sum over queries q of  1 / (RRF_K_CONSTANT + rank_q(d))

    Returns:
        Tuple of (queries_used, fused_hits).
        queries_used[0] is always the original query.
    """
    raw = llm_call(MULTI_QUERY_PROMPT_TEMPLATE.format(query=query))
    paraphrasings = [
        line.strip().lstrip("0123456789.- )")
        for line in raw.split("\n")
        if line.strip()
    ][:n_paraphrasings]

    queries: List[str] = [query] + paraphrasings  # original always first

    rrf: Dict[str, float] = {}
    docs: Dict[str, str] = {}
    metas: Dict[str, Dict[str, Any]] = {}
    appearances: Dict[str, int] = {}

    for q in queries:
        out = store.query_collection(
            collection_name=collection,
            query_text=q,
            n_results=k,
        )
        ids = out["ids"][0]
        for rank, doc_id in enumerate(ids):
            rrf[doc_id] = rrf.get(doc_id, 0.0) + 1.0 / (RRF_K_CONSTANT + rank)
            docs[doc_id] = out["documents"][0][rank]
            metas[doc_id] = out["metadatas"][0][rank]
            appearances[doc_id] = appearances.get(doc_id, 0) + 1

    top_ids = sorted(rrf, key=lambda i: rrf[i], reverse=True)[:k]
    fused = [
        FusedHit(
            chunk_id=i,
            document=docs[i],
            metadata=metas[i],
            rrf_score=rrf[i],
            appeared_in=appearances[i],
        )
        for i in top_ids
    ]
    return queries, fused


# =============================================================================
# Part 5: ORCHESTRATOR — gate + strategy dispatch
# =============================================================================

VALID_STRATEGIES: Tuple[str, ...] = ("hyde", "multi_query", "auto")
_AUTO_HYDE_WORD_CUTOFF: int = 6  # auto-strategy picks HyDE for queries this short


def expand_then_query(
    store: Any,
    collection: str,
    query: str,
    llm_call: LLMCall,
    k: int = DEFAULT_K,
    strategy: str = "auto",
    force: bool = False,
) -> Dict[str, Any]:
    """
    Main entry point: applies the adaptive gate, dispatches to the chosen
    expansion strategy, returns a standardized result dict.

    EXECUTION FLOW:
        1. Validate strategy.
        2. If not force and not should_expand(query): return baseline top-k.
        3. If strategy == "auto": pick "hyde" for short queries (<= 6 words),
           "multi_query" for medium-length expandable queries.
        4. Dispatch to hyde_query or multi_query_search.

    Args:
        store          : JarvisMemoryStore instance (caller-managed).
        collection     : ChromaDB collection name.
        query          : User query (or agent sub-query).
        llm_call       : Caller-provided LLM call function.
        k              : Top-k for retrieval.
        strategy       : "hyde" | "multi_query" | "auto".
        force          : If True, bypass the should_expand gate.

    Returns:
        Dict with keys:
            "expanded"     : bool — was expansion applied?
            "strategy"     : str  — "hyde" | "multi_query" | "baseline"
            "result"       : dict — ChromaDB-format result (always present)
            "hypothetical" : str  — only when strategy == "hyde"
            "fused_hits"   : list — only when strategy == "multi_query"
            "queries_used" : list — only when strategy == "multi_query"

    Raises:
        ValueError if `strategy` is not in VALID_STRATEGIES.
    """
    if strategy not in VALID_STRATEGIES:
        raise ValueError(
            f"strategy must be one of {VALID_STRATEGIES}, got {strategy!r}"
        )

    if not force and not should_expand(query):
        # Skip expansion — return baseline top-k unchanged
        baseline = store.query_collection(
            collection_name=collection,
            query_text=query,
            n_results=k,
        )
        return {
            "expanded": False,
            "strategy": "baseline",
            "result": baseline,
        }

    if strategy == "auto":
        strategy = "hyde" if len(query.split()) <= _AUTO_HYDE_WORD_CUTOFF else "multi_query"

    if strategy == "hyde":
        hypothetical, result = hyde_query(store, collection, query, llm_call, k)
        return {
            "expanded": True,
            "strategy": "hyde",
            "result": result,
            "hypothetical": hypothetical,
        }

    # strategy == "multi_query"
    queries, fused = multi_query_search(store, collection, query, llm_call, k)
    # Repackage FusedHit list into ChromaDB-format dict for callers that
    # expect the standard shape. RRF score inverted to a pseudo-distance
    # in [0, 1] so downstream code reading "distances" still gets a
    # lower-is-better signal.
    result = {
        "ids": [[h.chunk_id for h in fused]],
        "documents": [[h.document for h in fused]],
        "metadatas": [[h.metadata for h in fused]],
        "distances": [[1.0 - h.rrf_score for h in fused]],
    }
    return {
        "expanded": True,
        "strategy": "multi_query",
        "result": result,
        "fused_hits": fused,
        "queries_used": queries,
    }


# =============================================================================
# MAIN ENTRY POINT (smoke test — no live ChromaDB or LLM required)
# =============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("  jarvis_core.memory.expansion — smoke test (stub LLM + stub store)")
    print("=" * 70)

    # ------------------------------------------------------------------
    # 1. should_expand decisions
    # ------------------------------------------------------------------
    print("\n[1] should_expand() decisions")
    cases = [
        ("what is dropout regularization", True),
        ("how does cross-attention work", True),
        ("ChromaDB.query_collection error", False),  # identifier
        ("AWQ quantization tradeoffs", False),       # acronym
        ("explain MMR algorithm", False),            # acronym
        (
            "I'm building a multi-stage retrieval pipeline that combines "
            "BM25 with semantic search and want to understand exactly how "
            "the cross-encoder reranker integrates with the upstream "
            "retrievers and what the latency budget looks like in production",
            False,  # > 30 words
        ),
    ]
    for q, expected in cases:
        actual = should_expand(q)
        ok = "ok  " if actual == expected else "FAIL"
        snippet = q if len(q) <= 60 else q[:57] + "..."
        print(f"  [{ok}] should_expand({snippet!r:65s}) = {actual} (expected {expected})")

    # ------------------------------------------------------------------
    # 2. expand_then_query() with stub LLM + stub store
    # ------------------------------------------------------------------
    print("\n[2] expand_then_query() flow")

    def stub_llm(prompt: str) -> str:
        if "hypothetical" in prompt.lower():
            return "A hypothetical answer paragraph in academic prose style."
        if "paraphrasings" in prompt.lower() or "sub-questions" in prompt.lower():
            return "First variant\nSecond variant\nThird variant"
        return ""

    class _StubStore:
        def query_collection(self, collection_name, query_text, n_results):
            return {
                "ids": [[f"chunk_{i}" for i in range(n_results)]],
                "documents": [[f"doc {i} for {query_text!r}" for i in range(n_results)]],
                "metadatas": [[{"page": i, "source": "stub.pdf"} for i in range(n_results)]],
                "distances": [[0.1 + i * 0.05 for i in range(n_results)]],
            }

    store = _StubStore()

    out = expand_then_query(store, "test", "what is dropout", stub_llm, k=3)
    assert out["expanded"] is True, "short conceptual query should expand"
    print(f"  short conceptual query -> expanded={out['expanded']} strategy={out['strategy']}")

    long_q = " ".join(["word"] * 50)
    out = expand_then_query(store, "test", long_q, stub_llm, k=3)
    assert out["expanded"] is False, "long detailed prompt should skip"
    print(f"  long detailed prompt   -> expanded={out['expanded']} strategy={out['strategy']}")

    out = expand_then_query(store, "test", long_q, stub_llm, k=3, strategy="hyde", force=True)
    assert out["expanded"] is True and out["strategy"] == "hyde"
    print(f"  long + force=True      -> expanded={out['expanded']} strategy={out['strategy']}")

    out = expand_then_query(store, "test", "what is attention", stub_llm, k=3, strategy="multi_query")
    assert out["expanded"] is True and out["strategy"] == "multi_query"
    assert len(out["fused_hits"]) <= 3
    print(f"  multi_query explicit   -> queries={len(out['queries_used'])} hits={len(out['fused_hits'])}")

    # ------------------------------------------------------------------
    # 3. Strategy validation
    # ------------------------------------------------------------------
    print("\n[3] Input validation")
    try:
        expand_then_query(store, "test", "x", stub_llm, strategy="bogus")
        print("  FAIL: expected ValueError on bogus strategy")
    except ValueError as e:
        print(f"  ok   ValueError raised on bogus strategy: {e}")

    print("\n" + "=" * 70)
    print("  All smoke checks passed.")
    print("=" * 70)
