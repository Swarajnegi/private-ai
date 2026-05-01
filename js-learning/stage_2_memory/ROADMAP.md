# PHASE 2: Memory Layer Roadmap

> **Master Plan Position:** Phase 2 of 6 → [JARVIS_MASTER_ROADMAP.md](../JARVIS_MASTER_ROADMAP.md)  
> **Goal:** Build JARVIS's long-term memory: embeddings, vector stores, retrieval, and knowledge persistence.  
> **Prerequisites:** Phase 1 (Systems Python) — Generators, Async, Context Managers

---

## Overview

| Sub-Phase | Name | Core Concept | Definition of Done |
|-----------|------|--------------|-------------------|
| **2.1** | Embeddings & Similarity | Turn text into vectors, measure relevance | You can explain cosine similarity and embed 1000 documents |
| **2.2** | Vector Databases | Store and query high-dimensional vectors | ChromaDB running locally with working CRUD operations |
| **2.3** | Document Ingestion | Parse PDFs, split into chunks, embed | Ingestion pipeline handles 100+ documents without OOM |
| **2.4** | Retrieval Strategies | Top-k, MMR, filtered search | Can retrieve the most relevant chunks for any query |
| **2.5** | Hybrid Search & Reranking | Combine semantic + keyword, rerank results | Hybrid search outperforms pure semantic on benchmarks |

---

## Sub-Phase 2.1: Embeddings & Similarity ✅

**Goal:** Understand how text becomes vectors and how to measure similarity.

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 2.1.1 | What Are Embeddings? | Convert user queries to searchable vectors | `@[/learn] Explain embeddings and why they matter for RAG.` |
| 2.1.2 | Sentence Transformers | Local embedding models | `@[/learn] Explain sentence-transformers and all-MiniLM-L6-v2.` |
| 2.1.3 | Cosine Similarity | Measure relevance between vectors | `@[/learn] Explain cosine similarity and dot product for search.` |
| 2.1.4 | Embedding Dimensions | Trade-offs between size and quality | `@[/learn] Explain embedding dimensions and their impact.` |

**Practical Exercise:** Embed 100 text chunks and find the top-5 most similar to a query.

---

## Sub-Phase 2.2: Vector Databases ✅
**Goal:** Store embeddings persistently and query them efficiently.

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 2.2.1 | ChromaDB Basics | Local-first vector store | **COMPLETE** |
| 2.2.2 | Collections & Documents | Organizing knowledge | **COMPLETE** |
| 2.2.3 | Metadata Filtering | Filter by source, date, type | **COMPLETE** |
| 2.2.4 | Persistence & Backup | Don't lose JARVIS's memory | **COMPLETE** |

**Practical Exercise:** Built a hardened CLI wrapper (JarvisMemoryLayer) with Novelty Gates and Truncation Guards.

---

## Sub-Phase 2.3: Document Ingestion ✅ COMPLETE
**Goal:** Parse real documents (PDFs, code, notes) into embeddable chunks.

**Goal:** Parse real documents (PDFs, code, notes) into embeddable chunks.

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 2.3.1 | Chunking Strategies | Split documents intelligently | **COMPLETE** |
| 2.3.2 | PDF Parsing | Extract text from research papers | **COMPLETE** |
| 2.3.3 | Code Parsing | Ingest your own codebase | **COMPLETE** — `jarvis_core/memory/code_parser.py` (tree-sitter, function-level chunks) |
| 2.3.4 | Deduplication | Don't store the same content twice | **COMPLETE** — md5 NoveltyGate + upsert in `store.py` |

**Practical Exercise:** Ingest your `js-learning/py-learning/` folder into ChromaDB.

---

## Sub-Phase 2.4: Retrieval Strategies ✅ COMPLETE

**Goal:** Get the right context for any query.

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 2.4.1 | Top-k Retrieval | Basic semantic search | **COMPLETE** — `store.query_collection` |
| 2.4.2 | MMR (Maximal Marginal Relevance) | Diverse results, not just similar | **COMPLETE** — `store.mmr_query_collection` + `compute_mmr_reranking` |
| 2.4.3 | Query Expansion | Improve recall with rephrasing | **COMPLETE** — `jarvis_core/memory/expansion.py` (HyDE + Multi-Query + RRF + `should_expand` gate) |
| 2.4.4 | Contextual Compression | Reduce noise in retrieved chunks | **COMPLETE** — `jarvis_core/memory/compression.py` (embeddings_filter + llm_filter + `should_compress` gate; LLM Extractor deferred until 2.5.6 RAGAS) |

**Practical Exercise:** Compare top-k vs MMR on a real query against your knowledge base.

---

## Sub-Phase 2.5: Hybrid Search, Reranking & Evaluation ⬅️ YOU ARE HERE

**Goal:** Combine multiple retrieval methods, measure quality, iterate.

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 2.5.1 | BM25 (Keyword Search) | When exact matches matter | **COMPLETE** — `jarvis_core/memory/bm25.py` (Unicode-aware tokenizer, query-token dedup, k1/b validation, stable top-k; rank_bm25 0.2.2 backend) |
| 2.5.2 | Hybrid Search | Combine semantic + keyword | `/dev Implement hybrid search for JARVIS memory.` |
| 2.5.3 | Reranking Models | Score results with a cross-encoder | `@[/learn] Explain cross-encoder reranking.` |
| 2.5.4 | ColBERT / Late Interaction | Token-level precision retrieval | `@[/learn] Explain ColBERT late interaction and ragatouille.` |
| 2.5.5 | Evaluation Metrics | recall@k, MRR, NDCG | `@[/learn] Explain recall@k, MRR, and NDCG.` |
| 2.5.6 | RAGAS Framework | Automated RAG quality scoring | `@[/learn] Explain RAGAS: faithfulness, relevance, context recall, correctness.` |
| 2.5.7 | LLM-as-Judge & Tracing | Grade outputs + debug with Langfuse | `@[/learn] Explain LLM-as-Judge evaluation and observability tracing.` |

**Practical Exercise:** Build a hybrid retriever, measure with RAGAS, prove it outperforms pure semantic.

---

## Final Boss: The Memory Layer

Build a complete memory system that:
1. [ ] Ingests documents from a folder (PDFs, code, markdown)
2. [ ] Chunks and embeds with sentence-transformers
3. [ ] Stores in ChromaDB with metadata
4. [ ] Retrieves with hybrid search (semantic + BM25)
5. [ ] Reranks results before returning

**When this works, you have JARVIS's Soul (v1).**

> **Architecture Note:** ChromaDB is intentionally "v1" memory.
> In Stage 4 (Orchestration), flat vector search will be augmented with
> **GraphRAG** for multi-hop reasoning across research papers.
> In Stage 6 (Integration), **context caching** via cloud APIs may supplement
> local retrieval for coding tasks. Build the foundation here first.

---

## Progress Tracker

| Sub-Phase | Status | Lessons Complete |
|-----------|--------|------------------|
| 2.1 Embeddings & Similarity | ✅ Complete | 4/4 |
| 2.2 Vector Databases | ✅ Complete | 4/4 |
| 2.3 Document Ingestion | ✅ Complete | 4/4 |
| 2.4 Retrieval Strategies | ✅ Complete | 4/4 |
| 2.5 Hybrid Search, Reranking & Evaluation | 🔄 In Progress | 1/7 |

---

## After This Phase

→ Proceed to **Phase 3: Agent Framework** → [PHASE_03_ROADMAP.md](../agent-learning/PHASE_03_ROADMAP.md)
