"""
retriever.py

JARVIS Memory Layer: Unified Retrieval Pipeline (Chroma + BM25 + Cross-Encoder)

Run with:
    python -m jarvis_core.memory.retriever

This script demonstrates:
    1. Component — UnifiedRetriever: The facade that connects all 3 retrieval stages.

=============================================================================
THE BIG PICTURE
=============================================================================

Without a Unified Pipeline:
    → The Brain Layer has to manually orchestrate ChromaDB, BM25, and Cross-Encoders.
    → High risk of state leaks and mismatched parameters between the 3 systems.

With a Unified Pipeline:
    → The Brain Layer makes a single `.retrieve(query)` call.
    → The pipeline handles the wide-net fetch (Chroma+BM25), the RRF fusion, 
      and the precision re-scoring (Cross-Encoder) automatically.

=============================================================================
THE FLOW (Step by Step Execution Order)
=============================================================================

STEP 1: UnifiedRetriever.retrieve() receives a query.
        ↓
STEP 2: Stage 1 - Wide Net (hybrid_search fetches top N from Chroma and BM25).
        ↓
STEP 3: Stage 2 - Fusion (Reciprocal Rank Fusion merges both lists).
        ↓
STEP 4: Stage 3 - Precision (Cross-Encoder reranks the fused list).
        ↓
STEP 5: Returns final top-K precision hits to the Brain Layer.
=============================================================================
"""

from typing import List
import logging

from jarvis_core.memory.store import JarvisMemoryStore
from jarvis_core.memory.bm25 import BM25Index
from jarvis_core.memory.hybrid import hybrid_search
from jarvis_core.memory.rerank import CrossEncoderReranker, RerankHit

logger = logging.getLogger(__name__)

# =============================================================================
# Part 1: PIPELINE IMPLEMENTATION
# =============================================================================

class UnifiedRetriever:
    """
    LAYER: Memory — The Orchestrator for the retrieval pipeline.
    
    Purpose:
        - Provide a single, clean API for the Brain Layer to fetch context.
        - Chain Semantic, Lexical, and Cross-Encoder systems safely.
        
    How it works:
        - Maintains references to the underlying Chroma store, BM25 index, and Reranker model.
        - Executes the 3-stage retrieval protocol sequentially.
    """
    
    def __init__(
        self,
        store: JarvisMemoryStore,
        bm25_index: BM25Index,
        reranker: CrossEncoderReranker,
        collection_name: str = "jarvis_primary"
    ):
        """
        Initialize the unified retrieval pipeline.
        
        Args:
            store: The ChromaDB semantic store.
            bm25_index: The lexical BM25 index.
            reranker: The initialized Cross-Encoder model.
            collection_name: Default ChromaDB collection to target.
        """
        self.store = store
        self.bm25_index = bm25_index
        self.reranker = reranker
        self.collection_name = collection_name
        
        logger.info(f"UnifiedRetriever initialized targeting collection: {collection_name}")

    def retrieve(
        self, 
        query: str, 
        final_k: int = 5, 
        hybrid_fetch_k: int = 20
    ) -> List[RerankHit]:
        """
        Execute the full 3-stage retrieval pipeline.
        
        EXECUTION FLOW:
        1. hybrid_search (Semantic + Lexical + RRF) fetches top N candidates.
        2. reranker.rerank_hybrid_hits re-scores the N candidates using joint attention.
        3. Returns the absolute top-K results.
        
        Args:
            query: The user's search query.
            final_k: The number of highly precise chunks to return to the LLM.
            hybrid_fetch_k: The number of raw candidates to fetch from the first stage.
            
        Returns:
            List of RerankHit objects containing the final document chunks and metadata.
        """
        logger.info(f"Executing retrieval pipeline for query: '{query}'")
        
        # Stage 1 & 2: Wide Net Retrieval & RRF Fusion
        # We fetch a larger pool (hybrid_fetch_k) to give the reranker enough candidates.
        hybrid_candidates = hybrid_search(
            store=self.store,
            collection_name=self.collection_name,
            bm25_index=self.bm25_index,
            query=query,
            k=hybrid_fetch_k, 
            fetch_k=hybrid_fetch_k
        )
        
        if not hybrid_candidates:
            logger.warning("Hybrid search returned 0 candidates.")
            return []
            
        logger.info(f"Hybrid search returned {len(hybrid_candidates)} candidates. Passing to Cross-Encoder...")
        
        # Stage 3: Precision Reranking
        # The cross-encoder is heavily penalized by large inputs, so we only feed it the hybrid candidates.
        final_hits = self.reranker.rerank_hybrid_hits(
            query=query,
            hits=hybrid_candidates,
            k=final_k
        )
        
        logger.info(f"Retrieval complete. Yielding top {len(final_hits)} precision hits.")
        return final_hits

# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("=" * 70)
    print("  jarvis_core.memory.retriever — Pipeline Definition")
    print("=" * 70)
    print("Note: Run via integration tests. Requires populated ChromaDB and BM25 index.")
