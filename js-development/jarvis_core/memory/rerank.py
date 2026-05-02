"""
rerank.py

JARVIS Memory Layer: Cross-Encoder Reranking

Run with:
    python -m jarvis_core.memory.rerank

This script demonstrates:
    1. Component — CrossEncoderReranker: Uses sentence-transformers to jointly embed 
                   and score query-document pairs.
    2. Component — RerankHit: A dataclass wrapping the final reranked result.

=============================================================================
THE BIG PICTURE
=============================================================================

Without Cross-Encoder Reranking:
    → Bi-Encoders (Chroma) provide fast retrieval but miss nuanced token interactions
      because the query and document never "see" each other during embedding.
    → The LLM is fed noisy, semi-relevant context.

With Cross-Encoder Reranking:
    → The retrieved candidates from Chroma/BM25 are paired with the query.
    → A Cross-Encoder computes Self-Attention jointly across both texts.
    → Only mathematically verified, highly-correlated chunks survive to enter the LLM prompt.

=============================================================================
THE FLOW (Step by Step Execution Order)
=============================================================================

STEP 1: Instantiate CrossEncoderReranker with a model name.
        ↓
STEP 2: Reranker downloads/loads the model into memory.
        ↓
STEP 3: call rerank(query, documents, k)
        ↓
STEP 4: Reranker builds pairs: [[query, doc1], [query, doc2], ...]
        ↓
STEP 5: Model predicts logits for all pairs in one batch.
        ↓
STEP 6: Results are zipped, sorted descending by score, and top-k returned.
=============================================================================
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import logging

try:
    from sentence_transformers import CrossEncoder
except ImportError:
    CrossEncoder = None

logger = logging.getLogger(__name__)

# =============================================================================
# Part 1: CONSTANTS & TYPES
# =============================================================================

@dataclass(frozen=True)
class RerankHit:
    """
    LAYER: Memory — Output of the Reranking pipeline.
    
    Purpose:
        - Encapsulate the final document and its mathematically precise relevance score.
    """
    chunk_id: str
    document: str
    metadata: Dict[str, Any]
    score: float
    original_rank: int


# =============================================================================
# Part 2: RERANKER IMPLEMENTATION
# =============================================================================

class CrossEncoderReranker:
    """
    LAYER: Memory — Precision filtering component.
    
    Purpose:
        - Re-score candidates retrieved from fast first-pass search (Chroma/BM25).
        - Provide highly accurate top-K results for LLM context injection.
        
    How it works:
        - Loads a huggingface cross-encoder model.
        - Formats input as [CLS] Query [SEP] Document [SEP].
        - Predicts a logit score representing relevance.
    """
    
    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        """
        Initialize the reranker.
        
        Args:
            model_name: HuggingFace hub name of the cross-encoder model.
        """
        if CrossEncoder is None:
            raise ImportError("sentence-transformers is not installed. Run `pip install sentence-transformers`")
            
        logger.info(f"Initializing CrossEncoderReranker with model: {model_name}")
        self.model_name = model_name
        self.model = CrossEncoder(self.model_name)
        
    def rerank_hybrid_hits(self, query: str, hits: List[Any], k: int = 5, batch_size: int = 32) -> List[RerankHit]:
        """
        Re-score a list of HybridHit objects from the previous pipeline stage.
        Preserves the chunk_id and metadata.
        
        Systems Safety:
        Uses a `batch_size` sliding window. Feeds matrices to the Cross-Encoder in 
        small blocks to prevent VRAM OOM on large pools, while still preserving 
        the parallel processing speed of PyTorch/TensorFlow.
        """
        if not hits:
            return []
            
        logger.info(f"Reranking {len(hits)} HybridHits for query: '{query}' in batches of {batch_size}")
        
        reranked = []
        # Process in chunks to prevent PyTorch OOM
        for i in range(0, len(hits), batch_size):
            batch = hits[i:i + batch_size]
            pairs = [[query, hit.document] for hit in batch]
            
            # 1. Predict Scores (Vectorized Math)
            scores = self.model.predict(pairs)
            
            # 2. Assemble
            for j, (score, hit) in enumerate(zip(scores, batch)):
                reranked.append(RerankHit(
                    chunk_id=hit.chunk_id,
                    document=hit.document,
                    metadata=hit.metadata,
                    score=float(score),
                    original_rank=i + j
                ))
            
        # 3. Sort the final accumulated list
        reranked.sort(key=lambda x: x.score, reverse=True)
        return reranked[:k]
        
    def rerank(self, query: str, documents: List[str], chunk_ids: Optional[List[str]] = None, metadatas: Optional[List[Dict[str, Any]]] = None, k: int = 5) -> List[RerankHit]:
        """
        Re-score and filter a list of raw documents based on relevance to the query.
        """
        if not documents:
            return []
            
        if metadatas is None:
            metadatas = [{} for _ in documents]
            
        if chunk_ids is None:
            chunk_ids = [f"chunk_{i}" for i in range(len(documents))]
            
        if len(documents) != len(metadatas) or len(documents) != len(chunk_ids):
            raise ValueError("documents, chunk_ids, and metadatas lists must have the same length.")
            
        logger.info(f"Reranking {len(documents)} documents for query: '{query}'")
        
        # 1. Build Pairs
        pairs = [[query, doc] for doc in documents]
        
        # 2. Predict Scores (batch inference)
        scores = self.model.predict(pairs)
        
        # 3. Assemble and Sort
        hits = []
        for i, (score, doc, meta, cid) in enumerate(zip(scores, documents, metadatas, chunk_ids)):
            hits.append(RerankHit(
                chunk_id=cid,
                document=doc,
                metadata=meta,
                score=float(score),
                original_rank=i
            ))
            
        hits.sort(key=lambda hit: hit.score, reverse=True)
        
        # 4. Truncate to top-k
        top_k_hits = hits[:k]
        logger.info(f"Returning top {len(top_k_hits)} reranked hits.")
        
        return top_k_hits

# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    
    print("=" * 70)
    print("  jarvis_core.memory.rerank — Smoke Test")
    print("=" * 70)
    
    try:
        reranker = CrossEncoderReranker()
        
        test_query = "How do I fix Docker connection errors?"
        test_docs = [
            "Kubernetes orchestrates containers.",
            "Docker Desktop must be running to execute docker commands without a daemon connection error.",
            "Python is a great programming language.",
            "To fix docker: error during connect, ensure the docker daemon is active."
        ]
        
        print(f"\nQuery: {test_query}")
        print("-" * 30)
        
        results = reranker.rerank(query=test_query, documents=test_docs, k=2)
        
        for i, hit in enumerate(results):
            print(f"Rank {i+1} | Score: {hit.score:.2f} | ID: {hit.chunk_id}")
            print(f"Text: {hit.document}\n")
            
    except ImportError as e:
        print(f"Test aborted: {e}")
