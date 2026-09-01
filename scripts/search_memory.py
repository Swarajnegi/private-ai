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

# Resolve KB_PATH from jarvis_core.config so this script works on any machine
# without per-OS path edits. config.JARVIS_ROOT honors the JARVIS_ROOT env var
# and falls back to the repo root via Path(__file__).resolve().
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "js-development"))
from jarvis_core.config import KB_PATH

# ============================================================================
# PART 1: Configuration
# ============================================================================

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"  # 384-dim, fast
SIMILARITY_THRESHOLD = 0.3  # Lower = more results

# CHUNK BEFORE EMBEDDING — this is not an optimization, it is a correctness fix.
#
# all-MiniLM-L6-v2 has max_seq_length = 256 tokens and sentence-transformers
# TRUNCATES PAST IT SILENTLY: no exception, no warning, just a vector computed
# from the first 256 tokens as though the rest of the text did not exist.
#
# Measured 2026-08-26, before this fix: 152 of 505 KB entries (30%) exceeded the
# ceiling, and 15 of the 15 entries written since id 490 did — 100%. KB 504
# (3,220 chars) had only its first ~35% embedded, so every distinctive term in it
# ("phone app", "ambient", "camera", "Tier 0") sat in the discarded tail and the
# entry was unreachable by any query naming them.
#
# Proof it was truncation rather than a ranking quirk: two strings sharing a long
# head but with completely unrelated tails embedded to cosine 1.000000.
#
# 900 chars is DEFAULT_CHUNK_CHAR_LIMIT from jarvis_core.config — it exists in
# this repo precisely to fit MiniLM's 256-token ceiling, and memory/store.py
# already chunks before embedding for the ChromaDB path. This script was the
# outlier that bypassed machinery already written for exactly this problem.
_CHUNK_CHAR_LIMIT = 900
_CHUNK_OVERLAP = 180

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
        """Parse JSONL line into entry. `expiry` defaults to 'Permanent'
        per /memory.md when missing (some older entries omit the field)."""
        data = json.loads(line)
        return cls(
            timestamp=data['timestamp'],
            type=data['type'],
            tags=data.get('tags', []),
            content=data['content'],
            expiry=data.get('expiry', 'Permanent'),
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

        # Chunk first — see _CHUNK_CHAR_LIMIT for why this is mandatory.
        # chunk_owner maps every embedding row back to the entry it came from,
        # so search() can reduce chunk scores to one score per entry.
        chunks: List[str] = []
        self.chunk_owner = []
        for i, entry in enumerate(self.entries):
            for chunk in self._chunk(entry.content):
                chunks.append(chunk)
                self.chunk_owner.append(i)
        self.chunk_owner = np.array(self.chunk_owner)

        print(f"Computing embeddings over {len(chunks)} chunks...")
        self.embeddings = self.model.encode(
            chunks,
            batch_size=32,
            show_progress_bar=True,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )

        oversized = sum(1 for e in self.entries if len(e.content) > _CHUNK_CHAR_LIMIT)
        print(f"Index ready. Embedding dim: {self.embeddings.shape[1]} | "
              f"{oversized} entr{'y' if oversized == 1 else 'ies'} needed splitting "
              f"(would have been silently truncated before)")

    @staticmethod
    def _chunk(text: str) -> List[str]:
        """Split on word boundaries at _CHUNK_CHAR_LIMIT with overlap.

        Overlap matters: a claim spanning a boundary would otherwise be split
        across two chunks and match neither well.
        """
        text = text.strip()
        if len(text) <= _CHUNK_CHAR_LIMIT:
            return [text] if text else [""]
        out, start = [], 0
        while start < len(text):
            end = start + _CHUNK_CHAR_LIMIT
            if end < len(text):
                space = text.rfind(" ", start, end)
                if space > start:
                    end = space
            out.append(text[start:end].strip())
            if end >= len(text):
                break
            start = max(end - _CHUNK_OVERLAP, start + 1)
        return [c for c in out if c]
    
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

        # Score every CHUNK, then reduce to one score per ENTRY by taking the
        # MAX across that entry's chunks. Max, not mean: a long entry usually has
        # one passage that answers the query and several that don't, and
        # averaging would penalize exactly the detailed entries most worth
        # finding. An entry is relevant if ANY part of it is.
        chunk_sims = np.dot(self.embeddings, query_emb)
        similarities = np.full(len(self.entries), -np.inf, dtype=chunk_sims.dtype)
        np.maximum.at(similarities, self.chunk_owner, chunk_sims)

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