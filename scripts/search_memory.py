"""
JARVIS Knowledge Base Semantic Search
=====================================
LAYER: Tools
PURPOSE: Fast retrieval from knowledge_base.jsonl via embedding similarity

Usage:
    python scripts/search_memory.py "agent loops"
    python scripts/search_memory.py "why does RAG fail" --type Failure
    python scripts/search_memory.py "python async" --tags asyncio --top_k 10
"""

import json
import sys
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass
from sentence_transformers import SentenceTransformer
import numpy as np

# ============================================================================
# PART 1: Configuration
# ============================================================================

KB_PATH = Path("E:/J.A.R.V.I.S/jarvis_data/knowledge_base.jsonl")
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"  # 384-dim, fast
SIMILARITY_THRESHOLD = 0.3  # Lower = more results

# ============================================================================
# PART 2: Data Models
# ============================================================================

@dataclass
class KnowledgeEntry:
    """Single knowledge base entry with embedding"""
    timestamp: str
    type: str
    tags: List[str]
    content: str
    expiry: str
    embedding: Optional[np.ndarray] = None
    
    @classmethod
    def from_jsonl_line(cls, line: str) -> 'KnowledgeEntry':
        """Parse JSONL line into entry"""
        data = json.loads(line)
        return cls(
            timestamp=data['timestamp'],
            type=data['type'],
            tags=data['tags'],
            content=data['content'],
            expiry=data['expiry'],
        )

@dataclass
class SearchResult:
    """Search result with similarity score"""
    entry: KnowledgeEntry
    similarity: float
    
    def __str__(self) -> str:
        return (
            f"[{self.entry.type}] {self.similarity:.3f}\n"
            f"Tags: {', '.join(self.entry.tags)}\n"
            f"{self.entry.content[:200]}...\n"
            f"{'-'*80}\n"
        )

# ============================================================================
# PART 3: Knowledge Base Index
# ============================================================================

class KnowledgeBaseIndex:
    """In-memory index of knowledge base with embeddings"""
    
    def __init__(self, kb_path: Path, model_name: str):
        self.kb_path = kb_path
        self.model = SentenceTransformer(model_name)
        self.entries: List[KnowledgeEntry] = []
        self.embeddings: Optional[np.ndarray] = None
        
    def load(self) -> None:
        """Load JSONL and compute embeddings"""
        print(f"Loading knowledge base from {self.kb_path}...")
        
        # Parse JSONL
        with open(self.kb_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    self.entries.append(KnowledgeEntry.from_jsonl_line(line))
        
        print(f"Loaded {len(self.entries)} entries")
        
        # Compute embeddings (batch for speed)
        print("Computing embeddings...")
        contents = [entry.content for entry in self.entries]
        self.embeddings = self.model.encode(
            contents,
            batch_size=32,
            show_progress_bar=True,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        
        # Store embeddings in entries
        for entry, emb in zip(self.entries, self.embeddings):
            entry.embedding = emb
            
        print(f"Index ready. Embedding dim: {self.embeddings.shape[1]}")
    
    def search(
        self,
        query: str,
        top_k: int = 5,
        type_filter: Optional[str] = None,
        tag_filter: Optional[List[str]] = None,
        min_similarity: float = SIMILARITY_THRESHOLD,
    ) -> List[SearchResult]:
        """
        Semantic search through knowledge base
        
        Args:
            query: Natural language search query
            top_k: Number of results to return
            type_filter: Only return this type (e.g., "Failure")
            tag_filter: Only return entries with these tags
            min_similarity: Minimum cosine similarity threshold
            
        Returns:
            List of SearchResult sorted by similarity (high to low)
        """
        # Embed query
        query_emb = self.model.encode([query], convert_to_numpy=True, normalize_embeddings=True)[0]
        
        # Compute similarities
        similarities = np.dot(self.embeddings, query_emb)
        
        # Filter by type
        if type_filter:
            mask = np.array([e.type == type_filter for e in self.entries])
            similarities = np.where(mask, similarities, -999)
        
        # Filter by tags
        if tag_filter:
            mask = np.array([
                any(tag in e.tags for tag in tag_filter)
                for e in self.entries
            ])
            similarities = np.where(mask, similarities, -999)
        
        # Filter by threshold
        similarities = np.where(similarities >= min_similarity, similarities, -999)
        
        # Get top-k
        top_indices = np.argsort(similarities)[-top_k:][::-1]
        
        results = []
        for idx in top_indices:
            sim = similarities[idx]
            if sim > -999:  # Valid result
                results.append(SearchResult(
                    entry=self.entries[idx],
                    similarity=sim,
                ))
        
        return results

# ============================================================================
# PART 4: CLI Interface
# ============================================================================

def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Search JARVIS knowledge base semantically"
    )
    parser.add_argument(
        "query",
        type=str,
        help="Search query (natural language)"
    )
    parser.add_argument(
        "--type",
        type=str,
        default=None,
        help="Filter by type (Procedural, Semantic, Idea, etc.)"
    )
    parser.add_argument(
        "--tags",
        type=str,
        nargs="+",
        default=None,
        help="Filter by tags (space-separated)"
    )
    parser.add_argument(
        "--top_k",
        type=int,
        default=5,
        help="Number of results (default: 5)"
    )
    
    args = parser.parse_args()
    
    # Build index
    index = KnowledgeBaseIndex(KB_PATH, EMBEDDING_MODEL)
    index.load()
    
    # Search
    print(f"\nSearching for: '{args.query}'")
    if args.type:
        print(f"Type filter: {args.type}")
    if args.tags:
        print(f"Tag filter: {args.tags}")
    print("="*80)
    
    results = index.search(
        query=args.query,
        top_k=args.top_k,
        type_filter=args.type,
        tag_filter=args.tags,
    )
    
    if not results:
        print("No results found.")
        return
    
    print(f"\nFound {len(results)} results:\n")
    for i, result in enumerate(results, 1):
        print(f"Result {i}:")
        print(result)

# ============================================================================
# PART 5: Demo
# ============================================================================

if __name__ == "__main__":
    main()