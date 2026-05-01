"""
bm25.py

JARVIS Memory Layer: BM25 lexical retrieval (Stage 2.5.1).

Import with:
    from jarvis_core.memory.bm25 import (
        build_bm25_index,
        bm25_query,
        default_tokenize,
        BM25Hit,
        BM25Index,
    )

=============================================================================
THE BIG PICTURE
=============================================================================

Without lexical retrieval:
    -> Identifier queries ("store.query_collection", "$contains", "AWQ")
       degrade to noise. Sub-word tokenization in MiniLM splits identifiers
       into fragments that lose semantic identity. Recall on exact-match
       queries collapses to "wherever the embedding noise happens to land".
    -> Acronyms with strong corpus statistics (AWQ, FP16, RAG) get blurred
       into the conceptual neighborhood instead of pinpointed at chunks
       that mention them by name.

With BM25:
    -> A bag-of-words probabilistic ranker scores documents by saturated
       TF (term frequency) weighted by IDF (inverse document frequency),
       normalized by document length. The literal token
       "ChromaDB.query_collection" or "$contains" jumps to the top of
       the result list when it appears even once in a chunk.
    -> Two knobs control the curve: k1 (TF saturation, default 1.5) and
       b (length penalty, default 0.75). Together they implement the
       Robertson-Sparck-Jones probabilistic relevance model that has
       been the lexical-retrieval backbone since TREC-3 (1994).
    -> Sets up Stage 2.5.2 hybrid search: BM25 + semantic, fused via RRF.
       Each retriever's blindspot is the other's strength.

=============================================================================
THE FLOW (Step-by-Step Execution Order)
=============================================================================

STEP 1: caller builds an index over a corpus ONCE per session:
            index = build_bm25_index(documents, metadatas, ids, tokenizer)
        |
STEP 2: tokenizer runs over each document; corpus statistics computed:
            df(t) per term, N total docs, avgdl average length
            IDF(t) = ln(1 + (N - df + 0.5) / (df + 0.5))
        |
STEP 3: BM25Okapi internal state ready: posting lists + per-doc lengths.
        |
STEP 4: caller invokes bm25_query(index, query, n_results=10).
        |
STEP 5: query tokenized with the SAME tokenizer the index was built with
        (consistency invariant). Score every doc:
            sum_t IDF(t) * TF(t,d) * (k1+1)
                 / (TF(t,d) + k1 * (1 - b + b * |d|/avgdl))
        |
STEP 6: argpartition top-k by score in O(N); return BM25Hit list, score-desc.

=============================================================================
LAYER BOUNDARY NOTE
=============================================================================

BM25 is pure Memory layer — no LLM dependency, no Brain layer touch.
Tokenization is the only injected concern (caller can swap default regex
tokenizer for nltk/spaCy/HF stems if their corpus needs it).

=============================================================================
WHY NO ADAPTIVE GATE (vs. should_expand / should_compress)
=============================================================================

BM25 is never counterproductive on its own — it just becomes irrelevant
when the query has no terms in common with the corpus. The "when to skip
BM25" decision only makes sense in the *hybrid* context (Stage 2.5.2),
where the question is "does adding BM25 help or hurt the fused ranking?"
That gate lives in the hybrid module, not here.

=============================================================================
FAILURE MODES (audited; each item is either resolved here or out of scope)
=============================================================================

Resolved structurally:
  * Tokenizer drift between index and query
        -> BM25Index.tokenize travels with the index; bm25_query uses it
           always. Caller cannot pass a different tokenizer at query time.
  * Repeated query terms inflating score
        -> Query tokens deduplicated (first-occurrence order preserved).
           Standard BM25 sums over UNIQUE query terms; rank_bm25 does not
           dedupe automatically.
  * Unicode silently dropped
        -> Default regex is Unicode-aware (\\b\\w[\\w.]*\\b after str.lower()).
           Catches "Müller", "café", multi-script names in research papers.
  * Tie-ordering nondeterminism within the top-k slice
        -> Stable sort on the partitioned slice. (Tie boundaries CROSSING
           the top-k cutoff remain implementation-defined because
           argpartition is not stable; documented gotcha.)
  * Invalid k1 / b
        -> ValueError on k1 <= 0 or b not in [0, 1].
  * Empty corpus / length mismatch / empty query / empty per-doc tokens
        -> ValueError, []-return, or sentinel as appropriate.

Library-specific (rank_bm25 0.2.2 implementation detail, not a bug):
  * IDF formula differs from Lucene's smoothed form
        -> rank_bm25 uses the raw Robertson-Sparck-Jones IDF:
              IDF(t) = ln((N - df + 0.5) / (df + 0.5))
           which goes NEGATIVE when df > N/2 (term in majority of docs).
           Negatives are clamped to `epsilon * average_idf` (epsilon=0.25
           default). Lucene/Pyserini use the smoothed `ln(1 + ...)` form
           that never goes negative. The Stage 2.5.1 lesson hand-computation
           used the Lucene form for pedagogical clarity. Absolute scores
           from rank_bm25 will differ from lesson values, but relative
           ordering (which is what matters for ranking) is preserved on
           practical corpora.

Out of scope here (solved elsewhere or by caller):
  * Synonyms invisible: BM25 is bag-of-words and exact. Use the hybrid
    retriever in Stage 2.5.2 (which fuses BM25 + semantic via RRF) when
    you need synonym tolerance.
  * Stopwords / stemming: the default tokenizer does NEITHER. This is
    deliberate (correct for code/identifier corpora; lossy for prose).
    Caller composes::

        STOP = {"the", "a", "is", "of"}
        def my_tokenize(t):
            return [w for w in default_tokenize(t) if w not in STOP]
        index = build_bm25_index(docs, metas, ids, tokenizer=my_tokenize)

  * k1 / b corpus-specific tuning: defaults are TREC-3 (1.5, 0.75).
    Calibrate per-corpus once Stage 2.5.5 produces a labeled test set.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, List, Mapping, Sequence, Tuple

import numpy as np
from rank_bm25 import BM25Okapi


# =============================================================================
# Part 1: TYPE ALIASES
# =============================================================================

# Caller-provided tokenizer. Input text -> list of normalized tokens.
# Same function MUST be used at index build and query (enforced by
# BM25Index.tokenize binding; bm25_query never accepts a different one).
Tokenizer = Callable[[str], List[str]]


# =============================================================================
# Part 2: CONSTANTS
# =============================================================================

# Robertson-Sparck-Jones defaults from the original Okapi paper (TREC-3, 1994).
DEFAULT_K1: float = 1.5     # TF saturation; higher => slower saturation
DEFAULT_B: float = 0.75     # Length-norm strength; 0 disables, 1 maximally penalizes

# Default tokenizer regex. Lowercase + word-boundary tokens that PRESERVE
# identifier characters (dot). \w in Python 3 includes Unicode letters/digits/
# underscore by default, so "müller" / "café" / "tf_idf" / "store.query_collection"
# all tokenize as expected.
# Caveat: '$' is NOT in \w, so MongoDB-style ChromaDB operators like
# $contains tokenize as just "contains". Acceptable for our current corpora
# (research papers); revisit if/when we ingest code-docs that reference
# operators with $-prefixes.
_DEFAULT_TOKEN_PATTERN: re.Pattern[str] = re.compile(r"\b\w[\w.]*\b")


# =============================================================================
# Part 3: PUBLIC TYPES
# =============================================================================

@dataclass(frozen=True)
class BM25Hit:
    """One result from bm25_query, sorted top-k by score descending."""
    document: str
    metadata: Mapping[str, Any]
    id: str
    score: float
    rank: int


@dataclass(frozen=True)
class BM25Index:
    """
    LAYER: Memory. Frozen index over a fixed corpus snapshot.

    Purpose:
        - Hold the BM25Okapi engine plus aligned (documents, metadatas, ids)
          arrays in matching order, so query-time materialization is O(1)
          per result by row index.
        - Travel with its tokenizer so query and index stay in sync.

    How it works:
        - bm25.get_scores(tokens) returns a numpy array of length N.
        - argpartition picks the top-k indices in O(N), then we sort just
          those k stably and slice the parallel arrays to materialize hits.
    """
    bm25: BM25Okapi
    documents: Tuple[str, ...]
    metadatas: Tuple[Mapping[str, Any], ...]
    ids: Tuple[str, ...]
    tokenize: Tokenizer
    k1: float
    b: float


# =============================================================================
# Part 4: TOKENIZATION
# =============================================================================

def default_tokenize(text: str) -> List[str]:
    """
    Lowercase + identifier-preserving Unicode-aware regex tokenizer.

    EXECUTION FLOW:
    1. Lowercase the entire text (case-insensitive matching, Unicode-correct).
    2. Find tokens matching \\b\\w[\\w.]*\\b — keeps "store.query_collection"
       and "tf_idf" and "müller" as single tokens.
    3. Return list of strings (no stemming, no stopword removal).

    Returns:
        Tokens. Empty list for empty input.
    """
    if not text:
        return []
    return _DEFAULT_TOKEN_PATTERN.findall(text.lower())


# =============================================================================
# Part 5: INDEX CONSTRUCTION
# =============================================================================

def build_bm25_index(
    documents: Sequence[str],
    metadatas: Sequence[Mapping[str, Any]],
    ids: Sequence[str],
    tokenizer: Tokenizer = default_tokenize,
    k1: float = DEFAULT_K1,
    b: float = DEFAULT_B,
) -> BM25Index:
    """
    Tokenize a corpus and return an in-memory BM25 index.

    EXECUTION FLOW:
    1. Validate parallel arrays (documents/metadatas/ids same length, non-empty)
       and parameter ranges (k1 > 0, b in [0, 1]).
    2. Tokenize every document once.
    3. Replace any empty token list with sentinel ["__empty__"] so BM25Okapi
       does not crash; such docs score 0 on real queries (correct outcome).
    4. Pass tokenized corpus to BM25Okapi (computes df, idf, avgdl internally).
    5. Snapshot inputs into immutable tuples for the frozen BM25Index.

    Raises:
        ValueError on empty corpus, length mismatch, or invalid k1/b.
    """
    n = len(documents)
    if n == 0:
        raise ValueError("Cannot build BM25 index from empty corpus.")
    if not (n == len(metadatas) == len(ids)):
        raise ValueError(
            f"Length mismatch: documents={n}, metadatas={len(metadatas)}, "
            f"ids={len(ids)}. All three must align."
        )
    if k1 <= 0:
        raise ValueError(
            f"k1 must be > 0 (got {k1}). k1=0 collapses TF entirely; "
            f"k1<0 inverts the saturation curve."
        )
    if not 0.0 <= b <= 1.0:
        raise ValueError(
            f"b must be in [0, 1] (got {b}). b=0 disables length-norm; "
            f"b=1 is maximal penalty; outside this range is undefined."
        )

    tokenized_corpus: List[List[str]] = [tokenizer(doc) for doc in documents]
    tokenized_corpus = [toks if toks else ["__empty__"] for toks in tokenized_corpus]

    bm25 = BM25Okapi(tokenized_corpus, k1=k1, b=b)

    return BM25Index(
        bm25=bm25,
        documents=tuple(documents),
        metadatas=tuple(metadatas),
        ids=tuple(ids),
        tokenize=tokenizer,
        k1=k1,
        b=b,
    )


# =============================================================================
# Part 6: QUERY
# =============================================================================

def bm25_query(
    index: BM25Index,
    query: str,
    n_results: int = 10,
) -> List[BM25Hit]:
    """
    Score every doc against `query`; return top-k by score desc.

    EXECUTION FLOW:
    1. Empty/whitespace query -> [].
    2. Tokenize query with the index's bound tokenizer (consistency invariant).
    3. Dedupe query tokens preserving first-occurrence order. Reason:
       rank_bm25 sums score per occurrence in the query token list,
       so "cat cat cat" against a doc containing "cat" gives 3x the
       score it should. Standard BM25 sums over UNIQUE query terms.
    4. BM25Okapi.get_scores -> numpy array of length N.
    5. argpartition top-k indices in O(N); stable-sort just those k
       (kind="stable" so within-slice tie order is deterministic).
    6. Materialize BM25Hit dataclasses with rank/score/aligned fields.

    Returns:
        Length min(n_results, corpus). Score-desc. Score-0 docs ARE included
        if they fall in the top-k slot - caller filters if desired.
    """
    if not query.strip():
        return []

    raw_tokens = index.tokenize(query)
    if not raw_tokens:
        return []

    # Dedupe preserving first-occurrence order.
    seen: set = set()
    query_tokens: List[str] = []
    for tok in raw_tokens:
        if tok not in seen:
            seen.add(tok)
            query_tokens.append(tok)

    scores = index.bm25.get_scores(query_tokens)
    n = len(scores)
    k = min(n_results, n)

    if k < n:
        top_k_unsorted = np.argpartition(-scores, k - 1)[:k]
    else:
        top_k_unsorted = np.arange(n)
    # kind='stable' so ordering within the partitioned slice is deterministic.
    # Tie boundaries CROSSING the top-k cutoff remain implementation-defined
    # because argpartition itself is not stable (documented in module header).
    top_k_sorted = top_k_unsorted[np.argsort(-scores[top_k_unsorted], kind="stable")]

    return [
        BM25Hit(
            document=index.documents[i],
            metadata=index.metadatas[i],
            id=index.ids[i],
            score=float(scores[i]),
            rank=rank,
        )
        for rank, i in enumerate(top_k_sorted)
    ]


# =============================================================================
# Part 7: SMOKE TESTS (cover every resolved-here gotcha)
# =============================================================================

if __name__ == "__main__":
    # ---- Smoke 1: ranking-order invariant ----------------------------------
    # Use ORDER assertions, not absolute scores. rank_bm25 0.2.2 uses the
    # un-smoothed Robertson-Sparck-Jones IDF with negative-IDF clamping;
    # absolute values differ from the Lucene-style lesson math, but the
    # ranking order (which is what retrieval cares about) holds.
    corpus = [
        "agentic RAG uses reflective feedback loops",
        "deep learning convolutional neural network model",
        "agentic systems plan execute reflect agents",
        "agentic AI tools automation pipeline orchestration",
        "RAG retrieval augmented generation embeddings model",
    ]
    metas = [{"source": f"doc{i}"} for i in range(len(corpus))]
    ids = [f"d{i}" for i in range(len(corpus))]
    index = build_bm25_index(corpus, metas, ids)

    print("=" * 72)
    print("Smoke 1: 'agentic RAG' on 5-doc lesson corpus (order-invariant)")
    print("=" * 72)
    hits = bm25_query(index, "agentic RAG", n_results=5)
    for h in hits:
        print(f"  rank={h.rank}  score={h.score:.4f}  id={h.id}  '{h.document[:50]}'")
    score_by_id = {h.id: h.score for h in hits}
    assert score_by_id["d0"] > score_by_id["d4"] > score_by_id["d2"] > score_by_id["d1"], \
        "Ranking order broken: expected d0 > d4 > d2 > d1"
    assert abs(score_by_id["d2"] - score_by_id["d3"]) < 1e-9, \
        "d2 and d3 should tie (both have only 'agentic' once)"
    assert score_by_id["d1"] == 0.0, "d1 has no query terms; must score exactly 0"
    print("  PASS  (d0 > d4 > d2=d3 > d1=0; rank_bm25 absolute scores differ from")
    print("         lesson math by design - see FAILURE MODES note in module header)")

    # ---- Smoke 2: gotcha - repeated query tokens dedupe --------------------
    print("\n" + "=" * 72)
    print("Smoke 2: gotcha - 'rag rag rag' must score same as 'rag'")
    print("=" * 72)
    h_single = bm25_query(index, "rag", 1)[0].score
    h_triple = bm25_query(index, "rag rag rag", 1)[0].score
    print(f"  single='rag'           -> {h_single:.4f}")
    print(f"  tripled='rag rag rag'  -> {h_triple:.4f}")
    assert abs(h_single - h_triple) < 1e-9, "Query-token dedup is broken"
    print("  PASS  (dedup working)")

    # ---- Smoke 3: gotcha - Unicode tokenization (decoupled from IDF math) --
    print("\n" + "=" * 72)
    print("Smoke 3: gotcha - Unicode chars survive tokenization")
    print("=" * 72)
    # Test the tokenizer directly (avoiding rank_bm25's IDF=0 corner case
    # for terms appearing in df=1 of N=2 corpus).
    toks = default_tokenize("Müller proposed agentic café résumé naïve")
    expected = {"müller", "proposed", "agentic", "café", "résumé", "naïve"}
    print(f"  default_tokenize(...) -> {toks}")
    missing = expected - set(toks)
    assert not missing, f"Unicode tokenization dropped: {missing}"
    print(f"  PASS  (all 6 Unicode tokens preserved: {sorted(expected)})")

    # ---- Smoke 4: gotcha - parameter validation rejects invalid k1/b -------
    print("\n" + "=" * 72)
    print("Smoke 4: gotcha - parameter validation rejects invalid k1/b")
    print("=" * 72)
    rejected = 0
    for bad_k1 in (-1.0, 0.0):
        try:
            build_bm25_index(corpus, metas, ids, k1=bad_k1)
            print(f"  FAIL: k1={bad_k1} should have raised")
        except ValueError as e:
            rejected += 1
            print(f"  k1={bad_k1}: ValueError ({str(e)[:50]}...)  PASS")
    for bad_b in (-0.1, 1.5):
        try:
            build_bm25_index(corpus, metas, ids, b=bad_b)
            print(f"  FAIL: b={bad_b} should have raised")
        except ValueError as e:
            rejected += 1
            print(f"  b={bad_b}: ValueError ({str(e)[:50]}...)  PASS")
    assert rejected == 4, f"Expected 4 rejections, got {rejected}"

    # ---- Smoke 5: gotcha - empty/whitespace queries ------------------------
    print("\n" + "=" * 72)
    print("Smoke 5: gotcha - empty / whitespace / punctuation queries -> []")
    print("=" * 72)
    assert bm25_query(index, "") == [], "Empty query"
    assert bm25_query(index, "   ") == [], "Whitespace query"
    assert bm25_query(index, "!!!") == [], "All-punctuation query"
    print("  empty / whitespace / punctuation queries -> []  PASS")

    print("\n" + "=" * 72)
    print("All smoke tests PASSED")
    print("=" * 72)
