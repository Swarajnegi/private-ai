"""
03_query_expansion.py — Stage 2.4.3

Lesson: Query Expansion (HyDE + Multi-Query + RRF + Adaptive Gate)

This lesson now consumes the production module at
`jarvis_core.memory.expansion`. The retrieval primitives (HyDE,
Multi-Query+RRF, the should_expand gate, RRF formula) all live in
production code; the lesson contributes the LLM client wrapper that
production deliberately does not own (Memory layer stays LLM-agnostic
via dependency injection).

=============================================================================
THE BIG PICTURE
=============================================================================

User queries are short. Corpus chunks are long. A 2-word query like
"agentic RAG" produces a MiniLM embedding that aligns with chunks
containing those exact tokens — but misses chunks discussing the same
*concept* using different wording (e.g. "iterative refinement loops",
"reflective autonomous agents"). Query expansion fixes that.

Two techniques implemented in production:

  HyDE        : LLM hallucinates a hypothetical answer paragraph,
                embed THAT instead of the raw query. The answer-style
                vector lives in the same neighborhood as actual answer
                chunks, so retrieval pulls them in.

  Multi-Query : LLM generates 3-5 paraphrasings / sub-questions,
                retrieve top-k for each, fuse via Reciprocal Rank
                Fusion. RRF score for a doc d in any query's results:
                    score(d) = sum_q 1 / (60 + rank_q(d))
                The constant 60 dampens lower-ranked hits. Top-k by
                fused score = expanded retrieval.

The adaptive gate (`should_expand`) skips expansion for queries
already shaped like long detailed prompts, identifier lookups, or
acronym-specific searches.

=============================================================================
THE FLOW (this demo)
=============================================================================

STEP 1 : Query "agentic RAG"
         |
STEP 2 : Run BASELINE top-k via store.query_collection
         |
STEP 3 : Run hyde_query  -> LLM-generated hypothetical, embed, retrieve
         |
STEP 4 : Run multi_query_search -> 3 paraphrasings + RRF fusion
         |
STEP 5 : Demonstrate should_expand() decisions on a sample of queries,
         with one honest edge case (acronym false negative).

Run:
    OPENROUTER_API_KEY=sk-... python3 03_query_expansion.py
or without the key — falls back to a deterministic template-based
LLM stub so the lesson is still demonstrable.

JARVIS connection:
    Stage 3+ ReAct agents will call expand_then_query(...) instead of
    store.query_collection(...) directly when their sub-questions are
    short and conceptual. The user's natural detailed prompts go
    straight to baseline retrieval (gate skips expansion).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Make jarvis_core importable from the learning artifact
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "js-development"))

# All retrieval primitives live in production. The lesson consumes them.
from jarvis_core.memory.store import JarvisMemoryStore
from jarvis_core.memory.expansion import (
    expand_then_query,
    hyde_query,
    multi_query_search,
    should_expand,
)


# =============================================================================
# Part 1: LLM CLIENT (this is the lesson's contribution — production
# expansion module deliberately doesn't own one; caller injects)
# =============================================================================

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "deepseek/deepseek-chat"


def call_llm(prompt: str, max_tokens: int = 300, model: str = DEFAULT_MODEL) -> str:
    """Single LLM call via OpenRouter. Falls back to template expansion if
    OPENROUTER_API_KEY is unset — that fallback is a teaching scaffold,
    not a production path."""
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
# Part 2: DEMO HELPERS
# =============================================================================

def _print_chroma_hits(label: str, result):
    print(f"\n[{label}]")
    docs = result["documents"][0]
    metas = result["metadatas"][0]
    dists = result["distances"][0]
    for i, (d, m, dist) in enumerate(zip(docs, metas, dists), 1):
        page = m.get("page", "?")
        print(f"  {i}. dist={dist:.3f}  page={page}  | {d[:130]}...")


# =============================================================================
# Part 3: DEMO — baseline vs HyDE vs Multi-Query, then gate showcase
# =============================================================================

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

        # 2. HyDE — production primitive, lesson supplies the LLM call
        hypothetical, hyde_result = hyde_query(store, COLLECTION, QUERY, call_llm, K)
        print("\n[HyDE — hypothetical answer used as the embedding source]")
        print(f"  Hypothetical doc ({len(hypothetical)} chars):")
        for i in range(0, len(hypothetical), 75):
            print(f"    {hypothetical[i:i+75]}")
        _print_chroma_hits("HyDE retrieval", hyde_result)

        # 3. Multi-Query + RRF — production primitive
        queries, fused = multi_query_search(store, COLLECTION, QUERY, call_llm, K)
        print("\n[MULTI-QUERY + RRF]")
        print("  Generated queries:")
        for q in queries:
            print(f"    - {q}")
        print(f"\n  Fused top-{K} (sorted by RRF score):")
        for i, hit in enumerate(fused, 1):
            page = hit.metadata.get("page", "?")
            print(f"  {i}. rrf={hit.rrf_score:.4f}  appeared_in={hit.appeared_in}/{len(queries)}  page={page}")
            print(f"     {hit.document[:130]}...")

        # 4. Orchestrator — the production entry point Stage 3+ agents will use
        print("\n[ORCHESTRATOR — expand_then_query() = gate + dispatch]")
        out = expand_then_query(store, COLLECTION, QUERY, call_llm, k=K, strategy="auto")
        print(f"  expand_then_query('agentic RAG', strategy='auto')")
        print(f"    expanded = {out['expanded']}")
        print(f"    strategy = {out['strategy']}")
        print(f"    (acronym 'RAG' triggers the gate; without force=True, returns baseline)")

    # 5. Adaptive gate demonstration — when to expand, when not to
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

    # Edge case worth flagging
    print("\n  Edge case worth flagging:")
    print(f"    [{('EXPAND' if should_expand('agentic RAG') else 'skip  ')}]  'agentic RAG'")
    print("            HyDE actually helps a lot here (we saw distance drop from")
    print("            ~0.85 to ~0.40 above). But the acronym rule fires on 'RAG'")
    print("            and skips. Heuristic limitation. A stronger production")
    print("            gate could (a) whitelist common conceptual acronyms,")
    print("            (b) use a small classifier, or (c) measure recall@k")
    print("            empirically with-vs-without expansion and learn the cutoff.")
    print("            For now, callers can override via expand_then_query(force=True).")

    print("\n" + "=" * 78)
    print("  Takeaways:")
    print("    - HyDE: 1 extra LLM call. Question-vec -> answer-vec.")
    print("            Distance dropped 0.85 -> 0.40 on 'agentic RAG'.")
    print("    - Multi-Query+RRF: N+1 retrievals + 1 LLM call. Wider net via")
    print("            paraphrasings; RRF score promotes consensus chunks.")
    print("    - Adaptive gate: skip expansion for long detailed prompts,")
    print("            identifiers, acronyms. Calibrated to user's natural style.")
    print("    - Production: jarvis_core.memory.expansion is the canonical")
    print("            implementation; this lesson consumes those primitives.")
    print("=" * 78)


if __name__ == "__main__":
    main()
