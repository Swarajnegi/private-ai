import sys
sys.path.append("js-development")
import time
from unittest.mock import MagicMock
from jarvis_core.memory.expansion import expand_then_query
import chromadb

def benchmark_expansion():
    # Setup mock LLM and mock store
    mock_llm = MagicMock()
    # Let's say we have 5 paraphrasings
    paraphrasings = "q1\nq2\nq3\nq4\nq5"
    mock_llm.return_value = paraphrasings

    # Mock store to just return dummy data but simulate some latency
    class MockStore:
        def __init__(self):
            # simulate 50ms latency per query
            self.latency = 0.1

        def query_collection(self, collection_name, query_text, n_results=5, where=None):
            time.sleep(self.latency)
            return {
                "ids": [["id1", "id2", "id3", "id4", "id5"]],
                "documents": [["doc1", "doc2", "doc3", "doc4", "doc5"]],
                "metadatas": [[{}, {}, {}, {}, {}]],
                "distances": [[0.1, 0.2, 0.3, 0.4, 0.5]],
                "embeddings": [[[0.0]*384]*5]
            }

        def batch_query_collection(self, collection_name, query_texts, n_results=5, where=None):
            time.sleep(self.latency) # one latency hit for the whole batch
            results = {
                "ids": [],
                "documents": [],
                "metadatas": [],
                "distances": [],
                "embeddings": []
            }
            for _ in query_texts:
                results["ids"].append(["id1", "id2", "id3", "id4", "id5"])
                results["documents"].append(["doc1", "doc2", "doc3", "doc4", "doc5"])
                results["metadatas"].append([{}, {}, {}, {}, {}])
                results["distances"].append([0.1, 0.2, 0.3, 0.4, 0.5])
                results["embeddings"].append([[0.0]*384]*5)
            return results

    store = MockStore()

    start_time = time.time()
    # Run the expansion with multi_query strategy
    result = expand_then_query(
        store=store,
        collection="test_collection",
        query="original query",
        llm_call=mock_llm,
        k=5,
        strategy="multi_query",
        force=True
    )
    end_time = time.time()

    print(f"Time taken: {end_time - start_time:.4f} seconds")

if __name__ == "__main__":
    benchmark_expansion()
