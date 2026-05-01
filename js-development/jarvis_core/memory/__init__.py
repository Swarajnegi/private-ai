"""
memory/__init__.py

JARVIS Memory Layer.

This package owns all persistent storage, semantic retrieval, and
document ingestion for the JARVIS system.

Available modules:
    jarvis_core.memory.chunking    — RecursiveWordChunker: text -> bounded chunks
    jarvis_core.memory.store       — JarvisMemoryStore: ChromaDB + backup layer
    jarvis_core.memory.expansion   — HyDE + Multi-Query + RRF + adaptive gate (2.4.3)
    jarvis_core.memory.compression — embeddings/LLM filters + adaptive gate (2.4.4)
    jarvis_core.memory.bm25        — BM25 lexical retrieval (2.5.1)
"""
