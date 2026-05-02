"""
hybrid.py

JARVIS Memory Layer: Hybrid Search Engine (Semantic + BM25 Lexical).

Run with:
    python -m jarvis_core.memory.hybrid

This script demonstrates:
    1. Component — HybridHit: Immutable dataclass representing a fused search result.
    2. Component — hybrid_search: Executes RRF (Reciprocal Rank Fusion) across 
                   ChromaDB semantic search and BM25 lexical search.

=============================================================================
THE BIG PICTURE
=============================================================================

Without Hybrid Search:
    → Semantic search misses exact keywords, acronyms, and identifiers because
      dense embeddings map sub-word fragments into a fuzzy conceptual space.
    → Lexical search (BM25) misses synonyms and conceptual overlaps because
      it relies on literal string matching.

With Hybrid Search:
    → Both modalities retrieve candidates independently.
    → Reciprocal Rank Fusion (RRF) assigns a score to each candidate based on
      its rank in both lists: 1 / (60 + rank).
    → A document ranking high in both semantic and lexical lists rises to
      the absolute top.
    → The system gets the best of both worlds: conceptual recall + precise pinpointing.

=============================================================================
THE FLOW (Step by Step Execution Order)
=============================================================================

STEP 1: hybrid_search() invoked with query, store, and bm25_index.
        ↓
STEP 2: Semantic retrieval (store.query_collection) executes.
        ↓
STEP 3: Lexical retrieval (bm25_query) executes.
        ↓
STEP 4: RRF scores accumulated for all unique document IDs.
        ↓
STEP 5: Results sorted by descending RRF score.
        ↓
STEP 6: Return top-k HybridHits.
=============================================================================
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from jarvis_core.memory.store import JarvisMemoryStore
from jarvis_core.memory.bm25 import BM25Index, bm25_query

# =============================================================================
# Part 1: CONSTANTS & TYPES
# =============================================================================

# Reciprocal Rank Fusion constant (Cormack et al., 2009).
# 60 is a robust default that matches Stanford / Pyserini implementations.
RRF_K_CONSTANT: int = 60

@dataclass(frozen=True)
class HybridHit:
    """
    LAYER: Memory — one result from Hybrid (Semantic + BM25) retrieval.
    
    Purpose:
        - Immutable envelope for fused search results.
    
    How it works:
        - Combines ranks and raw documents from multiple retrieval streams
          into a single comparable object.
    """
    chunk_id: str
    document: str
    metadata: Dict[str, Any]
    rrf_score: float
    semantic_rank: Optional[int]
    bm25_rank: Optional[int]

# =============================================================================
# Part 2: CORE FUSION LOGIC
# =============================================================================

def hybrid_search(
    store: JarvisMemoryStore,
    collection_name: str,
    bm25_index: BM25Index,
    query: str,
    k: int = 5,
    fetch_k: int = 20,
) -> List[HybridHit]:
    """
    Execute hybrid retrieval using Reciprocal Rank Fusion (RRF).
    
    EXECUTION FLOW:
    1. Fetch top-fetch_k candidates from semantic search (ChromaDB).
    2. Fetch top-fetch_k candidates from lexical search (BM25).
    3. Accumulate RRF scores for every unique chunk_id encountered.
    4. Sort chunk_ids by descending RRF score.
    5. Return the absolute top-k as HybridHit objects.
    
    Returns:
        List of length at most `k` containing the fused and re-ranked hits.
    """
    # 1. Semantic Search
    semantic_res = store.query_collection(
        collection_name=collection_name,
        query_text=query,
        n_results=fetch_k
    )
    
    # 2. Lexical Search
    bm25_res = bm25_query(
        index=bm25_index,
        query=query,
        n_results=fetch_k
    )
    
    # 3. Fusion Dictionary
    # chunk_id -> dict of data
    fusion_map: Dict[str, Dict[str, Any]] = {}
    
    # Process Semantic Hits
    if semantic_res and semantic_res.get("ids") and len(semantic_res["ids"]) > 0:
        ids = semantic_res["ids"][0]
        docs = semantic_res["documents"][0]
        metas = semantic_res["metadatas"][0]
        
        for rank, chunk_id in enumerate(ids):
            fusion_map[chunk_id] = {
                "document": docs[rank],
                "metadata": metas[rank],
                "semantic_rank": rank,
                "bm25_rank": None,
                "rrf_score": 1.0 / (RRF_K_CONSTANT + rank)
            }
            
    # Process BM25 Hits
    for rank, hit in enumerate(bm25_res):
        chunk_id = hit.id
        if chunk_id in fusion_map:
            # Accumulate score
            fusion_map[chunk_id]["bm25_rank"] = rank
            fusion_map[chunk_id]["rrf_score"] += 1.0 / (RRF_K_CONSTANT + rank)
        else:
            # New hit
            fusion_map[chunk_id] = {
                "document": hit.document,
                "metadata": hit.metadata,
                "semantic_rank": None,
                "bm25_rank": rank,
                "rrf_score": 1.0 / (RRF_K_CONSTANT + rank)
            }
            
    # 4. Sort by RRF score descending
    sorted_ids = sorted(fusion_map.keys(), key=lambda i: fusion_map[i]["rrf_score"], reverse=True)
    
    # 5. Build Final Output
    top_k_ids = sorted_ids[:k]
    final_hits = []
    
    for chunk_id in top_k_ids:
        data = fusion_map[chunk_id]
        final_hits.append(HybridHit(
            chunk_id=chunk_id,
            document=data["document"],
            metadata=data["metadata"],
            rrf_score=data["rrf_score"],
            semantic_rank=data["semantic_rank"],
            bm25_rank=data["bm25_rank"]
        ))
        
    return final_hits

# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("  jarvis_core.memory.hybrid — smoke test")
    print("=" * 70)
    print("Run `pytest` to fully test hybrid capabilities with actual BM25 indexes.")
