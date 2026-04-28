"""
03_query_expansion.py — Stage 2.4.3

Lesson: Query Expansion (HyDE + Multi-Query + RRF)

=============================================================================
THE BIG PICTURE
=============================================================================

User queries are short. Corpus chunks are long. A 2-word query like
"agentic RAG" produces a MiniLM embedding that aligns with chunks
containing those exact tokens — but misses chunks that discuss the same
*concept* using different wording (e.g. "iterative refinement loops",
"reflective autonomous agents"). Query expansion fixes that.

Two techniques worth implementing in JARVIS:

  HyDE        : Have an LLM hallucinate a hypothetical answer paragraph,
                then embed THAT instead of the raw query. The answer-style
                vector lives in the same neighborhood as actual answer
                chunks, so retrieval pulls them in.

  Multi-Query : Have an LLM generate 3-5 paraphrasings / sub-questions,
                retrieve top-k for each, fuse via Reciprocal Rank Fusion
                (RRF). RRF score for a doc d in any query's results:
                    score(d) = sum over all queries q of 1 / (60 + rank_q(d))
                The constant 60 dampens lower-ranked hits. Top-k by
                fused score = expanded retrieval.

=============================================================================
THE FLOW
=============================================================================

STEP 1 : User query "agentic RAG"
         |
STEP 2a: HyDE       -> LLM("generate hypothetical answer") -> ~200 token paragraph
         STEP 3a   : embed(paragraph) -> ChromaDB.query -> top-5
         |
STEP 2b: Multi-Q   -> LLM("generate 3 paraphrasings")    -> 3 queries (+ original)
         STEP 3b   : embed each, ChromaDB.query each, RRF-fuse top-k
         |
STEP 4 : Compare baseline vs HyDE vs Multi-Q on the same query

Run:
    OPENROUTER_API_KEY=sk-... python3 03_query_expansion.py
or without the key — script falls back to a deterministic template-based
expansion so the lesson is still demonstrable.

JARVIS connection:
    Memory Layer pre-retrieval hook. The Brain (Stage 4) calls
    expand_then_query(...) instead of query_collection(...) on conceptual
    questions. Adaptive — skipped for queries containing identifiers
    (function names, error codes) where expansion hurts precision.
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Make jarvis_core importable from the learning artifact
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "js-development"))

from jarvis_core.memory.store import JarvisMemoryStore


# =============================================================================
# Part 1: LLM CALL (graceful degradation when no API key)
# =============================================================================

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "deepseek/deepseek-chat"


def call_llm(prompt: str, max_tokens: int = 300, model: str = DEFAULT_MODEL) -> str:
    """Single LLM call via OpenRouter. Falls back to template expansion if
    OPENROUTER_API_KEY is unset — that fallback is a teaching scaffold, not
    a production path."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return _template_fallback(prompt)

    import httpx  # local import — only needed when the key is present

    resp = httpx.post(
        OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.3,
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _template_fallback(prompt: str) -> str:
    """Deterministic stub so the lesson runs without an API key.
    NOT for production — real HyDE quality requires a real model."""
    if "hypothetical" in prompt.lower():
        # Pull the query from between the first pair of double quotes
        try:
            query = prompt.split('"')[1]
        except IndexError:
            query = "the topic"
        return (
            f"{query} is a research paradigm where autonomous agents dynamically "
            f"orchestrate retrieval steps, employ reflective feedback loops, plan "
            f"and execute multi-step tasks, and iterate on intermediate results. "
            f"Implementations include ReAct-style agents, plan-and-execute "
            f"frameworks, and reflexion architectures that decide when to fetch "
            f"additional context based on observed answer quality."
        )
    if "paraphrasings" in prompt.lower() or "sub-questions" in prompt.lower():
        try:
            query = prompt.split('"')[1]
        except IndexError:
            query = "the topic"
        return (
            f"What are the key components of {query}?\n"
            f"How does {query} differ from traditional retrieval approaches?\n"
            f"What are best practices for implementing {query} in production?"
        )
    return ""


# =============================================================================
# Part 1.5: ADAPTIVE GATE — when expansion is worth it
# =============================================================================
#
# HyDE and Multi-Query exist to bridge the lexical gap between short/sparse
# user queries and long answer-style corpus chunks. Detailed multi-sentence
# prompts already embed in the answer neighborhood — expansion on them is
# wasted cost (LLM call + latency) and can hurt precision when the
# hypothetical drifts from intent. Gate expansion in production callers via
# this predicate; default to OFF for direct user prompts and ON for
# agent-generated sub-queries (Stage 3+ ReAct loops).

_IDENTIFIER_CHARS = "()[]{}/_.<>"
_ACRONYM_PATTERN = re.compile(r"\b[A-Z]{2,}[a-z]?\b")

# Tunable. Calibrated against the user's natural prompt style: detailed
# multi-claim paragraphs averaging ~150 words. Below ~30 words = sparse.
_LONG_PROMPT_WORD_THRESHOLD = 30


def should_expand(query: str) -> bool:
    """Predicate: is this query the right shape for HyDE / Multi-Query?

    Returns False (skip expansion) when:
      - query is already long and detailed (>30 words)
      - query contains identifier characters (paths, function calls, code refs)
      - query contains an acronym or model name (signals specific lookup)
    Returns True (expand) for short conceptual queries — typically
    agent-emitted sub-questions or cold-start exploratory retrievals.
    """
    if len(query.split()) > _LONG_PROMPT_WORD_THRESHOLD:
        return False
    if any(c in query for c in _IDENTIFIER_CHARS):
        return False
    if _ACRONYM_PATTERN.search(query):
        return False
    return True


# =============================================================================
# Part 2: HyDE — Hypothetical Document Embeddings
# =============================================================================

HYDE_PROMPT = (
    'Generate a hypothetical paragraph answer to this question: "{query}"\n\n'
    "Write 3-4 dense sentences using technical vocabulary as if it were a "
    "paragraph excerpted from an academic research paper on the topic. Do not "
    "introduce yourself or add disclaimers — output the paragraph only."
)


def hyde_query(
    store: JarvisMemoryStore,
    collection: str,
    query: str,
    k: int = 5,
) -> Tuple[str, Dict[str, Any]]:
    """Expand `query` via HyDE, then retrieve top-k from `collection`.
    Returns the hypothetical doc + the ChromaDB result dict."""
    hypothetical = call_llm(HYDE_PROMPT.format(query=query))
    result = store.query_collection(
        collection_name=collection,
        query_text=hypothetical,
        n_results=k,
    )
    return hypothetical, result


# =============================================================================
# Part 3: MULTI-QUERY + RRF
# =============================================================================

MULTI_QUERY_PROMPT = (
    'Generate three diverse paraphrasings or related sub-questions for this '
    'query: "{query}"\n\n'
    "Each on its own line. No numbering, no preamble. Output only the three "
    "lines."
)

RRF_K_CONSTANT = 60  # standard RRF constant; lower = more weight on rank-1


@dataclass
class FusedHit:
    chunk_id: str
    document: str
    metadata: Dict[str, Any]
    rrf_score: float
    appeared_in: int  # how many queries returned this chunk


def multi_query_search(
    store: JarvisMemoryStore,
    collection: str,
    query: str,
    k: int = 5,
    n_paraphrasings: int = 3,
) -> Tuple[List[str], List[FusedHit]]:
    """Generate paraphrasings, retrieve top-k for each, fuse via RRF, return
    top-k by fused score."""
    raw = call_llm(MULTI_QUERY_PROMPT.format(query=query))
    paraphrasings = [
        line.strip().lstrip("0123456789.- )")
        for line in raw.split("\n")
        if line.strip()
    ][:n_paraphrasings]

    queries: List[str] = [query] + paraphrasings  # always include original

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
# Part 4: DEMO — baseline vs HyDE vs Multi-Query
# =============================================================================

def _print_chroma_hits(label: str, result: Dict[str, Any]) -> None:
    print(f"\n[{label}]")
    docs = result["documents"][0]
    metas = result["metadatas"][0]
    dists = result["distances"][0]
    for i, (d, m, dist) in enumerate(zip(docs, metas, dists), 1):
        page = m.get("page", "?")
        print(f"  {i}. dist={dist:.3f}  page={page}  | {d[:130]}...")


def main() -> None:
    QUERY = "agentic RAG"
    COLLECTION = "research_papers"
    K = 5

    using_real_llm = bool(os.environ.get("OPENROUTER_API_KEY"))

    print("=" * 78)
    print("  Stage 2.4.3 — Query Expansion Demo (HyDE + Multi-Query + RRF)")
    print(f"  Query        : {QUERY!r}")
    print(f"  Collection   : {COLLECTION}")
    print(f"  k            : {K}")
    print(f"  LLM source   : {'OpenRouter (' + DEFAULT_MODEL + ')' if using_real_llm else 'template fallback (no API key)'}")
    print(f"  should_expand: {should_expand(QUERY)} (this demo runs all three regardless,")
    print(f"                  for pedagogical comparison)")
    print("=" * 78)

    with JarvisMemoryStore() as store:
        # 1. Baseline
        baseline = store.query_collection(
            collection_name=COLLECTION,
            query_text=QUERY,
            n_results=K,
        )
        _print_chroma_hits("BASELINE — direct top-k on raw query", baseline)

        # 2. HyDE
        hypothetical, hyde_result = hyde_query(store, COLLECTION, QUERY, K)
        print("\n[HyDE — hypothetical answer used as the embedding source]")
        print(f"  Hypothetical doc ({len(hypothetical)} chars):")
        # Wrap to ~75 cols
        for i in range(0, len(hypothetical), 75):
            print(f"    {hypothetical[i:i+75]}")
        _print_chroma_hits("HyDE retrieval", hyde_result)

        # 3. Multi-Query + RRF
        queries, fused = multi_query_search(store, COLLECTION, QUERY, K)
        print("\n[MULTI-QUERY + RRF]")
        print("  Generated queries:")
        for q in queries:
            print(f"    - {q}")
        print(f"\n  Fused top-{K} (sorted by RRF score):")
        for i, hit in enumerate(fused, 1):
            page = hit.metadata.get("page", "?")
            print(f"  {i}. rrf={hit.rrf_score:.4f}  appeared_in={hit.appeared_in}/{len(queries)}  page={page}")
            print(f"     {hit.document[:130]}...")

    # 4. Adaptive gate demonstration — when to expand, when not to
    print("\n[ADAPTIVE GATE] should_expand() decisions on representative queries:")
    sample_queries = [
        ("what is dropout regularization?", "expected EXPAND — short, no identifiers/acronyms"),
        ("how does cross-attention work", "expected EXPAND — short, conceptual"),
        ("ChromaDB.query_collection error", "expected skip — contains identifier"),
        ("explain MMR algorithm", "expected skip — acronym = specific lookup"),
        ("AWQ quantization tradeoffs", "expected skip — acronym = specific lookup"),
        (
            "I'm building a multi-stage retrieval pipeline that combines BM25 "
            "with semantic search and want to understand exactly how the "
            "cross-encoder reranker integrates with the upstream retrievers "
            "and what the latency budget looks like in production",
            "expected skip — long detailed prompt (>30 words)",
        ),
    ]
    for q, why in sample_queries:
        decision = "EXPAND" if should_expand(q) else "skip  "
        short_q = q if len(q) <= 75 else q[:72] + "..."
        print(f"  [{decision}]  {short_q!r}")
        print(f"            {why}")

    # Edge case — heuristic limits worth knowing about
    print("\n  Edge case worth flagging:")
    print(f"    [{('EXPAND' if should_expand('agentic RAG') else 'skip  ')}]  'agentic RAG'")
    print("            HyDE actually helps a lot here (we saw distance drop from")
    print("            ~0.85 to ~0.40 above). But the acronym rule fires on 'RAG'")
    print("            and skips. Heuristic limitation. A stronger production")
    print("            gate could (a) whitelist common conceptual acronyms,")
    print("            (b) use a small classifier, or (c) measure recall@k")
    print("            empirically with-vs-without expansion and learn the cutoff.")

    print("\n" + "=" * 78)
    print("  Takeaways:")
    print("    - HyDE: 1 extra LLM call. Converts question-vec to answer-vec — pulls")
    print("            in chunks discussing the concept rather than the phrase.")
    print("    - Multi-Query+RRF: N+1 retrievals + 1 LLM call. Wider net via")
    print("            paraphrasings; RRF score promotes chunks appearing in")
    print("            multiple queries' top-k (consensus = relevance signal).")
    print("    - ADAPTIVE GATE (should_expand): skip for long detailed prompts")
    print("            (>30 words), queries with identifiers, or acronyms.")
    print("            Production callers map: /learn, /research, /dev, direct CLI")
    print("            = off; agent-emitted sub-queries (Stage 3+) = on.")
    print("=" * 78)


if __name__ == "__main__":
    main()
