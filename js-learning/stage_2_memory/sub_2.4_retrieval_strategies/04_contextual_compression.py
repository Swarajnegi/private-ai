"""
04_contextual_compression.py — Stage 2.4.4

Lesson: Contextual Compression (Embeddings Filter + LLM Filter + Adaptive Gate)

This lesson consumes the production module at
`jarvis_core.memory.compression`. The retrieval primitives (embeddings
filter, LLM filter, the should_compress gate, RRF-free orchestrator)
all live in production code; the lesson contributes the LLM client
wrapper that production deliberately does not own.

=============================================================================
THE BIG PICTURE
=============================================================================

After top-k retrieval (with or without query expansion), you have K
chunks ready to feed the answering LLM. Each chunk is whole — 200-600
words of paper text where maybe 50 words are directly relevant. Stuffed
into the LLM prompt as-is, this:
    - Wastes tokens (5x cost)
    - Dilutes signal (LLM hallucinates from neighboring noise)
    - Fills the context window prematurely

Contextual compression strips the noise BEFORE the chunks hit the LLM.

Two strategies shipped in production:
    - Embeddings Filter: re-embed each chunk against the query, drop
      below threshold. ~10-50ms total. No LLM call. Lossless.
    - LLM Filter:        ask LLM yes/no per chunk; drop the no's.
                         K small LLM calls. Lossless.

A third (LLM Extractor — lossy rewriter) is deferred until 2.5.6 RAGAS
measurements warrant.

=============================================================================
THE FLOW (this demo)
=============================================================================

STEP 1 : Query "what is reflective feedback in agentic systems"
         |
STEP 2 : Top-k=5 retrieval against research_papers collection
         |
STEP 3 : Apply embeddings_filter -> measure tokens kept
         |
STEP 4 : Apply llm_filter -> measure tokens kept
         |
STEP 5 : Run compress_results(strategy="auto") -> show which it picks
         |
STEP 6 : Demonstrate should_compress() decisions on sample queries

Run:
    OPENROUTER_API_KEY=sk-... python3 04_contextual_compression.py
or without the key — falls back to a deterministic LLM stub.

JARVIS connection:
    Stage 3+ ReAct agents will compose retrieval + compression as:
        result = expand_then_query(...)             # 2.4.3
        result = compress_results(result, ...)      # 2.4.4
        # then feed compressed `result` into the answering LLM
    The two adaptive gates (should_expand, should_compress) ensure
    cost is paid only when each step earns its keep.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "js-development"))

from sentence_transformers import SentenceTransformer

from jarvis_core.config import DEFAULT_EMBEDDING_MODEL
from jarvis_core.memory.store import JarvisMemoryStore
from jarvis_core.memory.compression import (
    compress_results,
    embeddings_filter,
    llm_filter,
    should_compress,
)


# =============================================================================
# Part 1: LLM CLIENT (the lesson's contribution — production deliberately
# doesn't own one; caller injects it)
# =============================================================================

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "deepseek/deepseek-chat"


def call_llm(prompt: str, max_tokens: int = 50, model: str = DEFAULT_MODEL) -> str:
    """Single LLM call via OpenRouter. Falls back to a yes/no template
    when no API key is set so the lesson runs without credentials."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return _template_fallback(prompt)
    import httpx
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
            "temperature": 0.0,  # deterministic yes/no
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _template_fallback(prompt: str) -> str:
    """Heuristic: keep chunks containing query keywords, drop those that
    don't. NOT for production — real LLM filter quality requires a real model.
    Demonstrates the wiring; substitute with a real LLM in production."""
    # Extract the query and chunk from the prompt template
    if 'Query: "' in prompt and "Passage:\n" in prompt:
        try:
            query = prompt.split('Query: "')[1].split('"')[0]
            chunk = prompt.split("Passage:\n")[1].split("\n\nRespond")[0]
            # Crude: keep if any query keyword appears in chunk
            kws = [w.lower() for w in query.split() if len(w) > 3]
            kept = any(kw in chunk.lower() for kw in kws)
            return "yes" if kept else "no"
        except (IndexError, ValueError):
            return "yes"  # fail-open
    return "yes"


# =============================================================================
# Part 2: DEMO HELPERS
# =============================================================================

def _sum_words(chunks):
    return sum(len(c.split()) for c in chunks)


def _print_compressed(label: str, out):
    docs = out["result"]["documents"][0]
    if out["compressed"]:
        ratio = out.get("tokens_kept_ratio", 1.0)
        print(f"\n[{label}] strategy={out['strategy']}  kept {len(docs)} chunks  "
              f"({ratio*100:.0f}% of original word count)")
    else:
        print(f"\n[{label}] strategy={out['strategy']} (gate skipped — baseline returned)")
    for i, d in enumerate(docs[:3], 1):  # show first 3 to keep output tight
        print(f"  {i}. {d[:160]}...")
    if len(docs) > 3:
        print(f"  ... and {len(docs)-3} more")


# =============================================================================
# Part 3: DEMO
# =============================================================================

def main() -> None:
    QUERY = "what is reflective feedback in agentic systems"
    COLLECTION = "research_papers"
    K = 5

    using_real_llm = bool(os.environ.get("OPENROUTER_API_KEY"))

    print("=" * 78)
    print("  Stage 2.4.4 — Contextual Compression Demo")
    print(f"  Query        : {QUERY!r}")
    print(f"  Collection   : {COLLECTION}")
    print(f"  k            : {K}")
    print(f"  LLM source   : {'OpenRouter (' + DEFAULT_MODEL + ')' if using_real_llm else 'template fallback (no API key)'}")
    print("=" * 78)

    encoder = SentenceTransformer(DEFAULT_EMBEDDING_MODEL)

    with JarvisMemoryStore() as store:
        # ---- Retrieve baseline top-k ------------------------------------
        baseline = store.query_collection(
            collection_name=COLLECTION,
            query_text=QUERY,
            n_results=K,
        )
        chunks = baseline["documents"][0]
        original_words = _sum_words(chunks)

        print(f"\n[BASELINE] top-{K} retrieval: {len(chunks)} chunks, {original_words} total words")
        for i, d in enumerate(chunks[:3], 1):
            print(f"  {i}. {d[:160]}...")
        if len(chunks) > 3:
            print(f"  ... and {len(chunks)-3} more")

        # ---- Strategy 1: Embeddings Filter (production primitive) ---------
        print("\n" + "-" * 78)
        print("[1] EMBEDDINGS FILTER — re-embed against query, drop below threshold")
        print("    (cheap, lossless; same blindspot as the original retrieval)")
        kept_chunks, kept_metas, kept_ids, sims = embeddings_filter(
            chunks=chunks,
            metadatas=baseline["metadatas"][0],
            ids=baseline["ids"][0],
            query=QUERY,
            encoder=encoder,
            threshold=0.30,
        )
        kept_words = _sum_words(kept_chunks)
        print(f"  kept {len(kept_chunks)} of {len(chunks)} chunks  "
              f"({kept_words} of {original_words} words = {kept_words/max(1,original_words)*100:.0f}%)")
        print(f"  cosine sims of survivors: {[f'{s:.3f}' for s in sims]}")

        # ---- Strategy 2: LLM Filter (production primitive) ----------------
        print("\n" + "-" * 78)
        print("[2] LLM FILTER — yes/no per chunk; surviving chunks return verbatim")
        print(f"    (uses {'real LLM' if using_real_llm else 'template stub'}; "
              f"production: small fast model)")
        kept_chunks2, kept_metas2, kept_ids2 = llm_filter(
            chunks=chunks,
            metadatas=baseline["metadatas"][0],
            ids=baseline["ids"][0],
            query=QUERY,
            llm_call=call_llm,
        )
        kept_words2 = _sum_words(kept_chunks2)
        print(f"  kept {len(kept_chunks2)} of {len(chunks)} chunks  "
              f"({kept_words2} of {original_words} words = {kept_words2/max(1,original_words)*100:.0f}%)")

        # ---- Strategy: auto via the orchestrator -------------------------
        print("\n" + "-" * 78)
        print("[3] ORCHESTRATOR — compress_results(strategy='auto')")
        print("    Auto-picks embeddings (cheap) or llm_filter (smart) by total word count.")
        out = compress_results(
            retrieval_result=baseline,
            query=QUERY,
            encoder=encoder,
            llm_call=call_llm,
            strategy="auto",
        )
        _print_compressed("auto-strategy result", out)

        # ---- Force LLM filter via orchestrator ---------------------------
        print("\n" + "-" * 78)
        print("[4] ORCHESTRATOR — compress_results(strategy='llm_filter', force=True)")
        print("    Bypass the gate, force LLM-filter strategy to demonstrate it.")
        out = compress_results(
            retrieval_result=baseline,
            query=QUERY,
            encoder=encoder,
            llm_call=call_llm,
            strategy="llm_filter",
            force=True,
        )
        _print_compressed("forced llm_filter", out)

    # ---- 5. Adaptive gate decisions on sample queries -------------------
    print("\n" + "=" * 78)
    print("[ADAPTIVE GATE] should_compress() decisions (k=5, total_words=1500):")
    sample_queries = [
        ("what is reflective feedback in agentic systems", "expected COMPRESS — short conceptual"),
        ("how does retrieval-augmented generation handle context", "expected COMPRESS — long conceptual"),
        ("explain MMR algorithm", "expected skip — acronym"),
        ("ChromaDB.query_collection error", "expected skip — identifier"),
        ("AWQ quantization tradeoffs", "expected skip — acronym"),
    ]
    for q, why in sample_queries:
        decision = "COMPRESS" if should_compress(q, k=5, total_words=1500) else "skip    "
        print(f"  [{decision}]  {q!r}")
        print(f"            {why}")

    # Edge: small K skipped regardless of query
    print("\n  Edge case (k=2, regardless of query):")
    print(f"    [{('COMPRESS' if should_compress('what is dropout', 2, 5000) else 'skip    ')}]  "
          f"k=2 even with 5000 words → skip (overhead exceeds gain on so few chunks)")

    print("\n" + "=" * 78)
    print("  Takeaways:")
    print("    - Embeddings filter: ~10-50ms, $0, lossless. Default for low/medium")
    print("            chunk volumes. Same blindspot as original retrieval.")
    print("    - LLM filter: K small calls (~$0.0001 each), lossless. Qualitatively")
    print("            smarter — understands semantic intent beyond surface tokens.")
    print("    - Adaptive gate: skip on K<4, total_words<1000, identifiers, or")
    print("            acronyms. Fail-closed — never raises, always returns baseline.")
    print("    - LLM Extractor (rewriter) DEFERRED: build only if 2.5.6 RAGAS")
    print("            measurements show LLM Filter isn't precise enough.")
    print("    - Production: jarvis_core.memory.compression — caller injects llm_call")
    print("            (DI pattern, same as expansion.py). Layer-pure.")
    print("=" * 78)


if __name__ == "__main__":
    main()
