"""
01_what_are_embeddings.py

Stage 2, Sub-Phase 2.1: Embeddings & Similarity
Lesson 2.1.1: What Are Embeddings?

Run with:
    python 01_what_are_embeddings.py

=============================================================================
USE CASE (The "Life of a Request")
=============================================================================

You ask JARVIS: "How does the ReAct pattern work?"

Without embeddings:
    JARVIS searches for the exact string "ReAct pattern" in its memory.
    It finds nothing — the stored entry says "ReAct: Synergizing Reasoning 
    and Acting." No keyword match. JARVIS says "I don't know."

With embeddings:
    JARVIS converts your question into a 384-dimensional float array.
    It compares this array against ALL stored document arrays using 
    cosine similarity. The ReAct paper scores 0.92 (high). The PPO 
    paper scores 0.28 (low). JARVIS retrieves the right paper and 
    feeds it to the LLM as context. This is RAG.

=============================================================================
WHAT THIS SCRIPT TEACHES
=============================================================================

1. What embeddings are (float arrays representing meaning)
2. How to generate them (SentenceTransformer model)
3. How to compare them (cosine similarity, dot product)
4. Why cosine > dot product (magnitude bias)
5. Real-world demo with your actual research papers' text
6. Failure modes (cross-domain confusion, long-text collapse)

=============================================================================
ARCHITECTURE
=============================================================================

LAYER: Memory (Embedding Engine)

    Text Input       Tokenizer       Transformer       Pooling        Output
    ──────────  →  ─────────────  →  ───────────  →  ─────────  →  ───────────
    "How does       [101, 2129,       12 layers          Mean         [0.12,
     ReAct           2515, ...]       of attention       Pool         -0.45,
     work?"                           heads                           0.78,
                                                                      ...,
                                                                      0.33]
                                                                      
                                                                   384 floats

=============================================================================
"""

import time
from dataclasses import dataclass
from typing import Optional

import numpy as np
import torch
from sentence_transformers import SentenceTransformer


# =============================================================================
# PART 1: LOADING THE MODEL
# =============================================================================
#
# all-MiniLM-L6-v2:
#   - 384 dimensions (each text → array of 384 floats)
#   - 80MB model size
#   - Runs on CPU (no GPU required)
#   - Free, open-source, runs locally
#   - This is the "default starter" for most RAG systems
#
# The model downloads on first run (~80MB) and caches locally.
#
# =============================================================================

def load_model() -> SentenceTransformer:
    """
    Load the embedding model.

    LAYER: Memory (Model Loading)

    First call downloads the model (~80MB).
    Subsequent calls load from cache instantly.
    """
    print("=" * 70)
    print("  PART 1: Loading Embedding Model")
    print("=" * 70)

    start = time.perf_counter()
    model = SentenceTransformer("all-MiniLM-L6-v2")
    load_ms = (time.perf_counter() - start) * 1000

    print(f"  Model:      all-MiniLM-L6-v2")
    print(f"  Dimensions: {model.get_sentence_embedding_dimension()}")
    print(f"  Load time:  {load_ms:.0f}ms")
    print(f"  Device:     {model.device}")
    print()

    return model


# =============================================================================
# PART 2: GENERATING EMBEDDINGS
# =============================================================================
#
# An embedding is a FIXED-LENGTH float array that captures the MEANING
# of text. Two texts with similar meaning produce arrays that point in
# similar directions in 384-dimensional space.
#
# Key insight: "fix my Python error" and "debug my Python code" produce
# nearly identical embeddings, even though they share few exact words.
#
# =============================================================================

def demonstrate_embeddings(model: SentenceTransformer) -> None:
    """
    Show what embeddings look like and how similar texts cluster.

    LAYER: Memory (Embedding Generation)
    """
    print("=" * 70)
    print("  PART 2: What Do Embeddings Look Like?")
    print("=" * 70)

    texts = [
        "How do I fix a Python error?",
        "Debug my Python code",
        "Best pizza recipe in Naples",
    ]

    for text in texts:
        start = time.perf_counter()
        embedding = model.encode(text)
        encode_ms = (time.perf_counter() - start) * 1000

        print(f"\n  Text:       \"{text}\"")
        print(f"  Type:       {type(embedding).__name__}")
        print(f"  Shape:      {embedding.shape}")
        print(f"  First 8:    [{', '.join(f'{v:.4f}' for v in embedding[:8])}]")
        print(f"  Min/Max:    {embedding.min():.4f} / {embedding.max():.4f}")
        print(f"  Norm (L2):  {np.linalg.norm(embedding):.4f}")
        print(f"  Encode:     {encode_ms:.0f}ms")

    print()


# =============================================================================
# PART 3: COSINE SIMILARITY vs DOT PRODUCT
# =============================================================================
#
# COSINE SIMILARITY:
#   Measures the ANGLE between two vectors.
#   cos(0°)  = 1.0   → identical meaning (same direction)
#   cos(90°) = 0.0   → unrelated (perpendicular)
#   cos(180°) = -1.0 → opposite meaning
#
#   Formula: cos(A, B) = (A · B) / (||A|| * ||B||)
#
# DOT PRODUCT:
#   Measures BOTH direction AND magnitude.
#   Affected by vector length → biased toward longer texts.
#
# WHY COSINE WINS:
#   A 50-page document has a larger embedding magnitude than a 1-line query.
#   Dot product would always rank long documents higher, regardless of meaning.
#   Cosine normalizes this — it only cares about DIRECTION.
#
# =============================================================================

def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """
    Compute cosine similarity between two vectors.

    LAYER: Memory (Similarity Metric)

    Returns float in [-1.0, 1.0]:
      1.0  = identical meaning
      0.0  = unrelated
     -1.0  = opposite meaning
    """
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def dot_product(a: np.ndarray, b: np.ndarray) -> float:
    """
    Compute raw dot product between two vectors.

    LAYER: Memory (Similarity Metric)

    No normalization. Affected by vector magnitude.
    """
    return float(np.dot(a, b))


def demonstrate_similarity(model: SentenceTransformer) -> None:
    """
    Compare cosine similarity vs dot product on real examples.

    LAYER: Memory (Similarity Comparison)
    """
    print("=" * 70)
    print("  PART 3: Cosine Similarity vs Dot Product")
    print("=" * 70)

    pairs = [
        ("How do I fix a Python error?", "Debug my Python code"),
        ("How do I fix a Python error?", "Best pizza recipe in Naples"),
        ("Asynchronous generators in Python", "async def with yield statement"),
        ("Asynchronous generators in Python", "The weather is sunny today"),
        ("Machine learning model training", "Fine-tuning neural networks"),
        ("Machine learning model training", "Italian cooking techniques"),
    ]

    print(f"\n  {'Text A':<42} {'Text B':<42} {'Cosine':>7} {'Dot':>8}")
    print("  " + "-" * 103)

    for text_a, text_b in pairs:
        emb_a = model.encode(text_a)
        emb_b = model.encode(text_b)

        cos = cosine_similarity(emb_a, emb_b)
        dot = dot_product(emb_a, emb_b)

        # Truncate for display
        short_a = text_a[:40] + ".." if len(text_a) > 40 else text_a
        short_b = text_b[:40] + ".." if len(text_b) > 40 else text_b

        print(f"  {short_a:<42} {short_b:<42} {cos:>7.3f} {dot:>8.2f}")

    print()
    print("  OBSERVATION: Cosine clusters related texts near 1.0 and")
    print("  unrelated texts near 0.0. Dot product values are harder")
    print("  to interpret because they depend on vector magnitude.")
    print()


# =============================================================================
# PART 4: REAL-WORLD DEMO — SEARCH YOUR RESEARCH PAPERS
# =============================================================================
#
# This simulates JARVIS's retrieval step.
# We embed snippets from your actual research papers and search them.
#
# Flow:
#   1. Embed all paper abstracts
#   2. Embed your query
#   3. Compute cosine similarity against all papers
#   4. Return top-k ranked results
#
# This is EXACTLY what ChromaDB does under the hood (Stage 2.2).
#
# =============================================================================

@dataclass
class Document:
    """A document with its text and embedding."""
    title: str
    text: str
    embedding: Optional[np.ndarray] = None


def build_document_set() -> list[Document]:
    """
    Create a set of documents from real research paper snippets.

    LAYER: Memory (Document Store)

    These are real abstracts/descriptions from papers in your
    Research Papers folder.
    """
    return [
        Document(
            title="Attention Is All You Need (1706.03762)",
            text=(
                "The dominant sequence transduction models are based on complex "
                "recurrent or convolutional neural networks. We propose a new "
                "simple network architecture, the Transformer, based solely on "
                "attention mechanisms, dispensing with recurrence and convolutions "
                "entirely."
            ),
        ),
        Document(
            title="RAG: Retrieval-Augmented Generation (2005.11401)",
            text=(
                "Large pre-trained language models have been shown to store "
                "factual knowledge in their parameters. We explore a general "
                "fine-tuning recipe for retrieval-augmented generation — models "
                "which combine pre-trained parametric and non-parametric memory "
                "for language generation."
            ),
        ),
        Document(
            title="Chain-of-Thought Prompting (2201.11903)",
            text=(
                "We explore how generating a chain of thought — a series of "
                "intermediate reasoning steps — significantly improves the "
                "ability of large language models to perform complex reasoning. "
                "Chain-of-thought prompting enables step-by-step problem solving."
            ),
        ),
        Document(
            title="ReAct: Reasoning and Acting (2210.03629)",
            text=(
                "While large language models have demonstrated impressive "
                "capabilities, their use is often confined to token generation. "
                "We propose ReAct, a paradigm that synergizes reasoning and "
                "acting in language models for general task solving."
            ),
        ),
        Document(
            title="MemGPT: LLMs as Operating Systems (2310.08560)",
            text=(
                "Large language models are limited by fixed context windows. "
                "We propose MemGPT, a system that intelligently manages "
                "different memory tiers to provide extended context within "
                "fixed-context models, inspired by virtual memory in "
                "traditional operating systems."
            ),
        ),
        Document(
            title="Sentence-BERT (1908.10084)",
            text=(
                "BERT and RoBERTa produce poor sentence embeddings. We present "
                "Sentence-BERT, a modification of BERT using siamese and triplet "
                "networks to derive semantically meaningful sentence embeddings "
                "that can be compared using cosine similarity."
            ),
        ),
        Document(
            title="Toolformer (2302.04761)",
            text=(
                "Language models can learn to use external tools via simple APIs "
                "in a self-supervised way, without human annotation. We introduce "
                "Toolformer, a model trained to decide which APIs to call, when, "
                "and what arguments to pass."
            ),
        ),
        Document(
            title="Proximal Policy Optimization (1707.06347)",
            text=(
                "We propose a new family of policy gradient methods for "
                "reinforcement learning, which alternate between sampling data "
                "through interaction with the environment and optimizing a "
                "'surrogate' objective function using stochastic gradient ascent."
            ),
        ),
    ]


def semantic_search(
    query: str,
    documents: list[Document],
    model: SentenceTransformer,
    top_k: int = 5,
) -> list[tuple[Document, float]]:
    """
    Search documents by semantic similarity to query.

    LAYER: Memory (Retrieval Engine)

    This is what happens inside ChromaDB.query().
    We're implementing it from scratch to understand the mechanics.

    Steps:
        1. Embed the query
        2. Compute cosine similarity against all document embeddings
        3. Sort by score descending
        4. Return top-k
    """
    # Embed query
    query_embedding = model.encode(query)

    # Score all documents
    results: list[tuple[Document, float]] = []
    for doc in documents:
        if doc.embedding is not None:
            score = cosine_similarity(query_embedding, doc.embedding)
            results.append((doc, score))

    # Sort by similarity (highest first)
    results.sort(key=lambda x: x[1], reverse=True)

    return results[:top_k]


def demonstrate_search(model: SentenceTransformer) -> None:
    """
    Run semantic search against research paper snippets.

    LAYER: Memory (Retrieval Demo)
    """
    print("=" * 70)
    print("  PART 4: Semantic Search (What ChromaDB Does Under the Hood)")
    print("=" * 70)

    # Build and embed documents
    documents = build_document_set()

    print(f"\n  Embedding {len(documents)} documents...")
    start = time.perf_counter()
    texts = [doc.text for doc in documents]
    embeddings = model.encode(texts)
    for doc, emb in zip(documents, embeddings):
        doc.embedding = emb
    embed_ms = (time.perf_counter() - start) * 1000
    print(f"  Done in {embed_ms:.0f}ms\n")

    # Run queries
    queries = [
        "How does the ReAct pattern work?",
        "What is retrieval augmented generation?",
        "How can LLMs use external tools?",
        "Explain virtual memory for language models",
        "How to generate sentence embeddings?",
        "reinforcement learning policy gradient",
    ]

    for query in queries:
        results = semantic_search(query, documents, model, top_k=3)

        print(f"  QUERY: \"{query}\"")
        print(f"  {'Rank':<6} {'Score':>6}  {'Paper'}")
        print(f"  {'─' * 6} {'─' * 6}  {'─' * 50}")
        for rank, (doc, score) in enumerate(results, 1):
            marker = " ◄── BEST MATCH" if rank == 1 else ""
            print(f"  #{rank:<5} {score:>6.3f}  {doc.title}{marker}")
        print()


# =============================================================================
# PART 5: FAILURE MODES — WHEN EMBEDDINGS LIE
# =============================================================================
#
# Embeddings are NOT perfect. They fail in specific ways that you
# need to understand before building JARVIS's memory.
#
# Failure 1: Cross-Domain Confusion
#   "Python is a powerful language" (programming)
#   "The python is a powerful snake" (biology)
#   → Embeddings score these as similar because of shared words.
#   → Fix: Metadata filtering (filter by domain BEFORE similarity search)
#
# Failure 2: Long-Text Collapse
#   A 500-word abstract → meaningful embedding.
#   A 50-page PDF → bland, averaged-out embedding that captures nothing.
#   → Fix: Chunk documents into ~500 word segments (Stage 2.3)
#
# Failure 3: Negation Blindness
#   "Python is good for async" and "Python is NOT good for async"
#   → Surprisingly similar embeddings. Models struggle with negation.
#   → Fix: Cross-encoder reranking (Stage 2.5)
#
# =============================================================================

def demonstrate_failure_modes(model: SentenceTransformer) -> None:
    """
    Show where embeddings fail so you know what to watch for.

    LAYER: Memory (Failure Analysis)
    """
    print("=" * 70)
    print("  PART 5: Failure Modes — When Embeddings Lie")
    print("=" * 70)

    failures = [
        {
            "name": "Cross-Domain Confusion",
            "text_a": "Python is a powerful programming language",
            "text_b": "The python is a powerful snake",
            "expected": "LOW (different domains)",
            "fix": "Metadata filtering (Stage 2.2.3)",
        },
        {
            "name": "Long-Text Collapse",
            "text_a": "Transformers use self-attention mechanisms",
            "text_b": (
                "Neural networks have evolved significantly. "
                "Early models used perceptrons. Then came CNNs for images. "
                "RNNs handled sequences. LSTMs improved long-range deps. "
                "Finally transformers revolutionized NLP with attention. "
                "They also changed computer vision and speech processing."
            ),
            "expected": "The long text dilutes the specific transformer mention",
            "fix": "Chunking into ~500 word segments (Stage 2.3)",
        },
        {
            "name": "Negation Blindness",
            "text_a": "Python is great for async programming",
            "text_b": "Python is not great for async programming",
            "expected": "LOW (opposite meaning)",
            "fix": "Cross-encoder reranking (Stage 2.5.3)",
        },
    ]

    for failure in failures:
        emb_a = model.encode(failure["text_a"])
        emb_b = model.encode(failure["text_b"])
        score = cosine_similarity(emb_a, emb_b)

        print(f"\n  FAILURE: {failure['name']}")
        print(f"  Text A:    \"{failure['text_a']}\"")
        print(f"  Text B:    \"{failure['text_b'][:70]}...\"")
        print(f"  Cosine:    {score:.3f}")
        print(f"  Expected:  {failure['expected']}")
        print(f"  Fix:       {failure['fix']}")

        if score > 0.5:
            print(f"  ⚠️  HIGH SIMILARITY — embedding was FOOLED!")
        else:
            print(f"  ✅  Embedding correctly detected low similarity")

    print()


# =============================================================================
# PART 6: BATCH EMBEDDING PERFORMANCE
# =============================================================================
#
# In production, JARVIS will embed hundreds or thousands of documents.
# Batched encoding is MUCH faster than encoding one at a time because
# the model can process multiple texts in a single GPU/CPU pass.
#
# =============================================================================

def demonstrate_batch_performance(model: SentenceTransformer) -> None:
    """
    Compare one-at-a-time vs batch embedding speed.

    LAYER: Memory (Performance)
    """
    print("=" * 70)
    print("  PART 6: Batch Embedding Performance")
    print("=" * 70)

    # Generate 100 sample texts
    sample_texts = [
        f"Document number {i}: This is a sample text about topic {i % 10} "
        f"covering concepts like {'async' if i % 3 == 0 else 'generators'} "
        f"and {'memory' if i % 2 == 0 else 'pipelines'} in Python."
        for i in range(100)
    ]

    # One at a time
    start = time.perf_counter()
    for text in sample_texts:
        _ = model.encode(text)
    sequential_ms = (time.perf_counter() - start) * 1000

    # Batched
    start = time.perf_counter()
    _ = model.encode(sample_texts, batch_size=32)
    batch_ms = (time.perf_counter() - start) * 1000

    speedup = sequential_ms / batch_ms if batch_ms > 0 else 0

    print(f"\n  Texts:        {len(sample_texts)}")
    print(f"  Sequential:   {sequential_ms:.0f}ms ({sequential_ms/len(sample_texts):.1f}ms/doc)")
    print(f"  Batched (32): {batch_ms:.0f}ms ({batch_ms/len(sample_texts):.1f}ms/doc)")
    print(f"  Speedup:      {speedup:.1f}x")
    print()
    print("  TAKEAWAY: Always use batch encoding in production.")
    print("  model.encode(list_of_texts, batch_size=32)")
    print()


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def main() -> None:
    """
    Run all embedding demonstrations.

    LAYER: Brain (Orchestrator)
    """
    print()
    print("#" * 70)
    print("  JARVIS Stage 2.1: What Are Embeddings?")
    print("  Using: all-MiniLM-L6-v2 (384-dim, ~80MB)")
    print("#" * 70)
    print()

    model = load_model()
    demonstrate_embeddings(model)
    demonstrate_similarity(model)
    demonstrate_search(model)
    demonstrate_failure_modes(model)
    demonstrate_batch_performance(model)

    print("#" * 70)
    print("  SUMMARY")
    print("#" * 70)
    print("""
  1. Embeddings convert text to fixed-length float arrays (384-dim)
  2. Similar meaning → similar direction → high cosine similarity
  3. Use cosine (not dot product) to avoid magnitude bias
  4. all-MiniLM-L6-v2: 80MB, runs on CPU, free, private
  5. Batch encoding is 2-4x faster than sequential
  6. Failure modes: cross-domain confusion, long-text collapse, negation blindness
  7. Fixes: metadata filtering, chunking, cross-encoder reranking

  NEXT: Lesson 2.1.2 — Sentence Transformers deep dive
  Run: @[/learn] Explain sentence-transformers and all-MiniLM-L6-v2.
    """)
    print("#" * 70)


if __name__ == "__main__":
    main()
