1. **Add `batch_query_collection` to `JarvisMemoryStore`:**
   - I will define a new method `batch_query_collection` in `js-development/jarvis_core/memory/store.py` that takes a list of query strings (`query_texts`).
   - This method will compute embeddings for all `query_texts` in a single batch.
   - It will call `collection.query` with the batched embeddings, which will natively return a batch of results.
2. **Update `multi_query_search` in `expansion.py`:**
   - I will modify `multi_query_search` in `js-development/jarvis_core/memory/expansion.py` to use `store.batch_query_collection` instead of iterating over `queries` and calling `store.query_collection` sequentially.
   - I will process the batched results by zipping the queries with the returned arrays of `ids`, `documents`, and `metadatas`.
3. **Verify Functionality and Measure Performance:**
   - I will run `benchmark_expansion.py` using my modified files to ensure the time taken goes down and establish the performance baseline + improvement.
   - I will format and lint the code.
   - I will execute any existing tests in the project (if any).
4. **Pre-commit Instructions:**
   - Ensure proper testing, verifications, reviews, and reflections are done before submit.
5. **Submit PR:**
   - Create a PR explaining the optimizations.
