"""
02_sentence_transformers_deep_dive.py

Stage 2, Sub-Phase 2.1: Embeddings & Similarity
Lesson 2.1.2: Sentence Transformers & all-MiniLM-L6-v2

Run with:
    python 02_sentence_transformers_deep_dive.py

=============================================================================
USE CASE (The "Life of a Request")
=============================================================================

sentence-transformers is called TWICE in every RAG request:
  1. INGESTION (offline): Embed every document chunk at storage time
  2. QUERY (real-time):   Embed the user's question at search time

The SAME model must be used for both. Different models produce
different vector spaces — similarity scores break across spaces.

=============================================================================
WHAT THIS SCRIPT TEACHES
=============================================================================

1. What sentence-transformers actually does (tokenize → transform → pool)
2. The architecture of all-MiniLM-L6-v2 (6 layers, 384-dim)
3. The difference between raw BERT output and sentence embeddings
4. Silent truncation at 256 tokens — the #1 RAG mistake
5. Model comparison: when to upgrade from MiniLM
6. Normalization: why it makes dot product = cosine

=============================================================================
ARCHITECTURE
=============================================================================

LAYER: Memory (Embedding Engine)

    sentence-transformers pipeline:

    Text → [Tokenizer] → [6 Transformer Layers] → [Mean Pooling] → [Normalize]
                                                         ↓
                                                   384-dim vector
                                                   one per sentence

    vs. raw BERT/HuggingFace:

    Text → [Tokenizer] → [12 Transformer Layers] → N token vectors (one per token)
                                                         ↓
                                                   (N, 768) matrix
                                                   no sentence vector
=============================================================================
"""

import time
from contextlib import contextmanager
from typing import Generator

import numpy as np
from sentence_transformers import SentenceTransformer


# =============================================================================
# UTILITIES
# =============================================================================

@contextmanager
def timer(label: str) -> Generator[None, None, None]:
    """Context manager to time a block of code."""
    start = time.perf_counter()
    yield
    elapsed_ms = (time.perf_counter() - start) * 1000
    print(f"  ⏱  {label}: {elapsed_ms:.1f}ms")


# =============================================================================
# PART 1: MODEL INTERNALS
# =============================================================================
#
# What happens when you call SentenceTransformer("all-MiniLM-L6-v2")?
#
# 1. Downloads (or loads from cache) three things:
#    - Tokenizer vocabulary (30,522 WordPiece tokens)
#    - Transformer weights (6 layers × attention heads = ~22M params)
#    - Pooling config (mean pooling, no CLS)
#
# 2. Chains them into a pipeline:
#    Tokenizer → Transformer → Pooling → (optional Normalize)
#
# The "sentence-transformers" magic is that this model was
# TRAINED on 1 billion sentence pairs specifically to produce
# sentence-level embeddings that cluster by meaning.
#
# =============================================================================

def inspect_model_internals(model: SentenceTransformer) -> None:
    """
    Show what's inside the sentence-transformers pipeline.

    LAYER: Memory (Model Inspection)
    """
    print("=" * 70)
    print("  PART 1: Model Internals")
    print("=" * 70)

    print(f"\n  Model name:     all-MiniLM-L6-v2")
    print(f"  Embedding dim:  {model.get_sentence_embedding_dimension()}")
    print(f"  Max seq length: {model.max_seq_length}")
    print(f"  Device:         {model.device}")

    # Count parameters
    total_params = sum(p.numel() for p in model.parameters())
    print(f"  Parameters:     {total_params:,} ({total_params / 1e6:.1f}M)")

    # Show the pipeline modules
    print(f"\n  Pipeline modules:")
    for idx, module in enumerate(model.modules()):
        module_name = type(module).__name__
        if module_name in (
            "Transformer", "Pooling", "Dense", "Normalize",
            "SentenceTransformer",
        ):
            print(f"    [{idx}] {module_name}")

    # Tokenizer info
    tokenizer = model.tokenizer
    print(f"\n  Tokenizer:")
    print(f"    Vocab size:   {tokenizer.vocab_size:,}")
    print(f"    Type:         {type(tokenizer).__name__}")
    print(f"    Max length:   {tokenizer.model_max_length}")

    # Show how tokenizer works
    sample = "How does the ReAct pattern work?"
    tokens = tokenizer.tokenize(sample)
    ids = tokenizer.encode(sample)
    print(f"\n  Tokenization demo:")
    print(f"    Input:    \"{sample}\"")
    print(f"    Tokens:   {tokens}")
    print(f"    IDs:      {ids}")
    print(f"    Count:    {len(tokens)} tokens (+ 2 special = {len(ids)} IDs)")
    print()


# =============================================================================
# PART 2: TOKENIZER → TRANSFORMER → POOLING (Step by Step)
# =============================================================================
#
# sentence-transformers hides three steps inside .encode().
# Here we run each step manually so you see what happens.
#
# =============================================================================

def manual_pipeline(model: SentenceTransformer) -> None:
    """
    Run the embedding pipeline step by step.

    LAYER: Memory (Pipeline Decomposition)
    """
    print("=" * 70)
    print("  PART 2: Manual Pipeline (What .encode() Does)")
    print("=" * 70)

    text = "Asynchronous generators power JARVIS memory ingestion"
    print(f"\n  Input: \"{text}\"")

    # ----- Step 1: Tokenize -----
    tokenizer = model.tokenizer
    encoded = tokenizer(
        text,
        padding=True,
        truncation=True,
        max_length=model.max_seq_length,
        return_tensors="pt",
    )
    print(f"\n  STEP 1 — Tokenize:")
    print(f"    input_ids shape:      {encoded['input_ids'].shape}")
    print(f"    attention_mask shape:  {encoded['attention_mask'].shape}")
    print(f"    Tokens: {tokenizer.convert_ids_to_tokens(encoded['input_ids'][0])}")

    # ----- Step 2: Transformer forward pass -----
    import torch
    with torch.no_grad():
        # Get the transformer module (first module in the pipeline)
        transformer_module = model[0]  # The Transformer wrapper
        outputs = transformer_module(encoded)

    # The output is a dict with 'token_embeddings' and other keys
    token_embeddings = outputs["token_embeddings"]
    print(f"\n  STEP 2 — Transformer (6 layers of attention):")
    print(f"    token_embeddings shape: {token_embeddings.shape}")
    print(f"    → One {token_embeddings.shape[-1]}-dim vector PER token")
    print(f"    → {token_embeddings.shape[1]} tokens total")

    # ----- Step 3: Mean Pooling -----
    # This is what collapses N token vectors into 1 sentence vector
    attention_mask = encoded["attention_mask"]
    mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
    sum_embeddings = torch.sum(token_embeddings * mask_expanded, dim=1)
    sum_mask = torch.clamp(mask_expanded.sum(dim=1), min=1e-9)
    mean_pooled = (sum_embeddings / sum_mask).numpy()[0]

    print(f"\n  STEP 3 — Mean Pooling:")
    print(f"    Sentence embedding shape: {mean_pooled.shape}")
    print(f"    First 8 values: [{', '.join(f'{v:.4f}' for v in mean_pooled[:8])}]")

    # ----- Compare with .encode() -----
    auto_embedding = model.encode(text)
    # Note: .encode() may normalize, so compare direction not values
    cos_sim = np.dot(mean_pooled, auto_embedding) / (
        np.linalg.norm(mean_pooled) * np.linalg.norm(auto_embedding)
    )
    print(f"\n  VERIFICATION:")
    print(f"    Manual vs .encode() cosine: {cos_sim:.6f}")
    print(f"    (1.000000 = identical direction, minor float diff is normal)")
    print()


# =============================================================================
# PART 3: SILENT TRUNCATION — THE #1 RAG MISTAKE
# =============================================================================
#
# all-MiniLM-L6-v2 has max_seq_length = 256 tokens (~200 words).
# If your text is longer, it SILENTLY truncates. No error. No warning.
#
# The embedding represents ONLY the first ~200 words.
# Everything after that is IGNORED.
#
# This is WHY chunking matters (Stage 2.3).
#
# =============================================================================

def demonstrate_truncation(model: SentenceTransformer) -> None:
    """
    Prove that long texts are silently truncated.

    LAYER: Memory (Failure Mode)
    """
    print("=" * 70)
    print("  PART 3: Silent Truncation (The #1 RAG Mistake)")
    print("=" * 70)

    # Build a text that's clearly longer than 256 tokens
    short_text = "Async generators use yield to stream data non-blockingly."
    
    # Put the important content at the END of a long text
    filler = " ".join([
        f"This is filler sentence number {i} about generic topics."
        for i in range(60)
    ])
    long_text_important_at_end = (
        filler + " " + short_text
    )

    # Check token counts
    tokenizer = model.tokenizer
    short_tokens = tokenizer.tokenize(short_text)
    long_tokens = tokenizer.tokenize(long_text_important_at_end)

    print(f"\n  Short text tokens: {len(short_tokens)}")
    print(f"  Long text tokens:  {len(long_tokens)}")
    print(f"  Max model tokens:  {model.max_seq_length}")
    print(f"  Tokens LOST:       {max(0, len(long_tokens) - model.max_seq_length)}")

    # Embed both
    emb_short = model.encode(short_text)
    emb_long = model.encode(long_text_important_at_end)

    # Also embed just the filler
    emb_filler = model.encode(filler[:500])  # Just filler, no important content

    # Compare
    cos_short_vs_long = np.dot(emb_short, emb_long) / (
        np.linalg.norm(emb_short) * np.linalg.norm(emb_long)
    )
    cos_filler_vs_long = np.dot(emb_filler, emb_long) / (
        np.linalg.norm(emb_filler) * np.linalg.norm(emb_long)
    )

    print(f"\n  Cosine(short_text, long_text):   {cos_short_vs_long:.3f}")
    print(f"  Cosine(filler_only, long_text):  {cos_filler_vs_long:.3f}")
    print()

    if cos_filler_vs_long > cos_short_vs_long:
        print("  ⚠️  CONFIRMED: The long text's embedding matches FILLER,")
        print("     not the important content at the end!")
        print("     The model only saw the first ~200 words.")
    else:
        print("  ✅  The short text was partially captured.")

    print()
    print("  LESSON: Never embed text longer than ~200 words.")
    print("  Always CHUNK first (Stage 2.3).")
    print("  The model will silently eat your content with no warning.")
    print()


# =============================================================================
# PART 4: NORMALIZATION — WHY IT MATTERS
# =============================================================================
#
# After mean pooling, you can optionally L2-normalize the vector.
# When normalized, ||v|| = 1.0 for all vectors.
#
# This means: dot product = cosine similarity
# (because the denominator ||a|| * ||b|| = 1.0 * 1.0 = 1.0)
#
# ChromaDB stores normalized vectors, so it uses dot product
# internally (faster) and gets cosine similarity results.
#
# =============================================================================

def demonstrate_normalization(model: SentenceTransformer) -> None:
    """
    Show the effect of L2 normalization on similarity computation.

    LAYER: Memory (Vector Math)
    """
    print("=" * 70)
    print("  PART 4: Normalization — dot product = cosine shortcut")
    print("=" * 70)

    texts = [
        "async generators in Python",
        "yielding data non-blockingly",
    ]

    # Get unnormalized embeddings
    raw_embeddings = model.encode(texts, normalize_embeddings=False)
    
    # Get normalized embeddings
    norm_embeddings = model.encode(texts, normalize_embeddings=True)

    for i, text in enumerate(texts):
        raw_norm = np.linalg.norm(raw_embeddings[i])
        normalized_norm = np.linalg.norm(norm_embeddings[i])
        print(f"\n  Text: \"{text}\"")
        print(f"  Raw L2 norm:        {raw_norm:.4f}")
        print(f"  Normalized L2 norm: {normalized_norm:.4f}  (always 1.0)")

    # Compute similarity both ways
    # Cosine similarity (works on both raw and normalized)
    dot_raw = np.dot(raw_embeddings[0], raw_embeddings[1])
    cos_raw = dot_raw / (
        np.linalg.norm(raw_embeddings[0]) * np.linalg.norm(raw_embeddings[1])
    )
    
    # Dot product of normalized (should equal cosine)
    dot_norm = np.dot(norm_embeddings[0], norm_embeddings[1])

    print(f"\n  Cosine similarity (raw):           {cos_raw:.6f}")
    print(f"  Dot product of normalized:         {dot_norm:.6f}")
    print(f"  Difference:                        {abs(cos_raw - dot_norm):.9f}")
    print()
    print("  TAKEAWAY: When vectors are normalized, dot product = cosine.")
    print("  ChromaDB normalizes internally → uses fast dot product,")
    print("  but you get cosine similarity results.")
    print()


# =============================================================================
# PART 5: MODEL COMPARISON — WHEN TO UPGRADE
# =============================================================================
#
# You'll eventually wonder: "Should I use a bigger model?"
# Here we benchmark MiniLM against what you'd gain from upgrading.
#
# =============================================================================

def demonstrate_model_tradeoffs(model: SentenceTransformer) -> None:
    """
    Benchmark embedding speed and show the upgrade decision.

    LAYER: Memory (Model Selection)
    """
    print("=" * 70)
    print("  PART 5: Model Comparison — When to Upgrade")
    print("=" * 70)

    # Benchmark current model
    sample_texts = [
        f"Document {i}: Topic about {'async' if i % 2 else 'memory'} "
        f"{'pipelines' if i % 3 else 'generators'} in JARVIS."
        for i in range(200)
    ]

    with timer("MiniLM-L6: 200 texts (batch=32)"):
        embeddings = model.encode(sample_texts, batch_size=32)

    print(f"\n  Embedding shape: {embeddings.shape}")
    print(f"  Memory per embedding: {embeddings[0].nbytes} bytes")
    print(f"  Memory for 10K docs: {embeddings[0].nbytes * 10_000 / 1e6:.1f} MB")

    # Show the comparison table
    print(f"""
  ┌───────────────────────────┬──────┬────────┬──────────┬────────────────┐
  │ Model                     │ Dims │  Size  │ 10K Docs │ JARVIS Verdict │
  ├───────────────────────────┼──────┼────────┼──────────┼────────────────┤
  │ all-MiniLM-L6-v2      ◄  │  384 │  80MB  │   3.8 MB │ START HERE     │
  │ all-mpnet-base-v2        │  768 │ 420MB  │   7.7 MB │ If 384 fails   │
  │ bge-large-en-v1.5        │ 1024 │ 1.3GB  │  10.2 MB │ Overkill       │
  │ nomic-embed-text-v1.5    │  768 │ 560MB  │   7.7 MB │ Alt (Matryosh) │
  │ e5-mistral-7b-instruct   │ 4096 │  14GB  │  41.0 MB │ GPU only       │
  └───────────────────────────┴──────┴────────┴──────────┴────────────────┘

  RULE: Only upgrade when you have EVIDENCE that retrieval quality
  is the bottleneck. 90% of the time, chunking and reranking fix
  bad retrieval, not a bigger embedding model.

  The 384→768 jump gives ~1.5% quality improvement but DOUBLES
  your index size and search latency.
    """)


# =============================================================================
# PART 6: PRODUCTION PATTERNS
# =============================================================================
#
# How you'll use sentence-transformers in JARVIS.
#
# =============================================================================

def demonstrate_production_patterns(model: SentenceTransformer) -> None:
    """
    Show patterns you'll use when building JARVIS memory.

    LAYER: Memory (Production Code)
    """
    print("=" * 70)
    print("  PART 6: Production Patterns for JARVIS")
    print("=" * 70)

    # Pattern 1: Singleton model loading
    print("""
  PATTERN 1: Load model ONCE at startup
  ──────────────────────────────────────
  
  # WRONG (reloads model every query — 500ms+ overhead):
  def search(query: str):
      model = SentenceTransformer("all-MiniLM-L6-v2")  # BAD
      embedding = model.encode(query)
  
  # RIGHT (load once, reuse):
  class EmbeddingEngine:
      def __init__(self):
          self.model = SentenceTransformer("all-MiniLM-L6-v2")
      
      def embed(self, texts: list[str]) -> np.ndarray:
          return self.model.encode(texts, batch_size=32)
    """)

    # Pattern 2: Same model for ingest and query
    print("""
  PATTERN 2: Same model for BOTH ingestion and query
  ──────────────────────────────────────────────────
  
  # WRONG (different models produce different vector spaces):
  ingest_model = SentenceTransformer("all-MiniLM-L6-v2")
  query_model  = SentenceTransformer("all-mpnet-base-v2")  # BAD
  
  # RIGHT (same model, same vector space):
  model = SentenceTransformer("all-MiniLM-L6-v2")
  doc_embedding   = model.encode("Document text")
  query_embedding = model.encode("User query")
  # These live in the SAME 384-dim space → cosine is meaningful
    """)

    # Pattern 3: Chunk before embed
    print("""
  PATTERN 3: Always chunk BEFORE embedding
  ─────────────────────────────────────────
  
  # WRONG (silent truncation at 256 tokens):
  embedding = model.encode(entire_pdf_text)  # BAD — loses 90% of content
  
  # RIGHT (chunk into ~200 word segments):
  chunks = chunk_text(pdf_text, max_words=200)
  embeddings = model.encode(chunks, batch_size=32)
  # Each chunk gets its own embedding → nothing is lost
    """)

    # Pattern 4: Normalize for ChromaDB
    print("""
  PATTERN 4: Normalize when using ChromaDB
  ─────────────────────────────────────────
  
  # ChromaDB can handle normalization, but being explicit is safer:
  embeddings = model.encode(texts, normalize_embeddings=True)
  # Now dot product = cosine similarity (faster search)
    """)


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    """
    Run all sentence-transformers demonstrations.

    LAYER: Brain (Orchestrator)
    """
    print()
    print("#" * 70)
    print("  JARVIS Stage 2.1: Sentence Transformers Deep Dive")
    print("  Model: all-MiniLM-L6-v2 (384-dim, 6-layer, ~22M params)")
    print("#" * 70)
    print()

    with timer("Model loading"):
        model = SentenceTransformer("all-MiniLM-L6-v2")
    print()

    inspect_model_internals(model)
    manual_pipeline(model)
    demonstrate_truncation(model)
    demonstrate_normalization(model)
    demonstrate_model_tradeoffs(model)
    demonstrate_production_patterns(model)

    print("#" * 70)
    print("  SUMMARY")
    print("#" * 70)
    print("""
  1. sentence-transformers = Tokenizer → Transformer → Mean Pool → Normalize
  2. all-MiniLM-L6-v2: 6 layers, 384-dim, 22M params, ~80MB
  3. Max 256 tokens (~200 words) — SILENTLY truncates longer text
  4. Same model MUST be used for ingestion AND query
  5. When normalized, dot product = cosine similarity (faster)
  6. Only upgrade models when you prove retrieval is the bottleneck

  NEXT: Lesson 2.1.3 — Cosine Similarity math deep dive
  Run: @[/learn] Explain cosine similarity and dot product for search.
    """)
    print("#" * 70)


if __name__ == "__main__":
    main()
