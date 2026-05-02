import pytest
from typing import Any, Dict

from jarvis_core.memory.expansion import hyde_query, HYDE_PROMPT_TEMPLATE, DEFAULT_K


class MockStore:
    def __init__(self):
        self.calls = []

    def query_collection(
        self, collection_name: str, query_text: str, n_results: int
    ) -> Dict[str, Any]:
        self.calls.append({
            "collection_name": collection_name,
            "query_text": query_text,
            "n_results": n_results,
        })
        return {
            "ids": [["id1", "id2"]],
            "documents": [["doc1", "doc2"]],
            "metadatas": [[{"meta": "data"}, {"meta": "data2"}]],
            "distances": [[0.1, 0.2]],
        }


def test_hyde_query_explicit_k():
    """Test hyde_query with an explicit k value."""
    store = MockStore()
    query = "What is a vector database?"
    collection = "tech_docs"
    k = 10

    expected_prompt = HYDE_PROMPT_TEMPLATE.format(query=query)
    mock_hypothetical = "A vector database stores high-dimensional embeddings."

    def mock_llm_call(prompt: str) -> str:
        assert prompt == expected_prompt
        return mock_hypothetical

    hypothetical, result = hyde_query(
        store=store,
        collection=collection,
        query=query,
        llm_call=mock_llm_call,
        k=k
    )

    # Verify the hypothetical string matches what the mock LLM returned
    assert hypothetical == mock_hypothetical

    # Verify that the store was called correctly
    assert len(store.calls) == 1
    call_args = store.calls[0]
    assert call_args["collection_name"] == collection
    assert call_args["query_text"] == mock_hypothetical
    assert call_args["n_results"] == k

    # Verify the result structure matches our mock store
    assert "ids" in result
    assert "documents" in result
    assert "distances" in result


def test_hyde_query_default_k():
    """Test hyde_query using the default k value."""
    store = MockStore()
    query = "Explain transformer architecture."
    collection = "research_papers"

    expected_prompt = HYDE_PROMPT_TEMPLATE.format(query=query)
    mock_hypothetical = "Transformers use self-attention mechanisms."

    def mock_llm_call(prompt: str) -> str:
        assert prompt == expected_prompt
        return mock_hypothetical

    hypothetical, result = hyde_query(
        store=store,
        collection=collection,
        query=query,
        llm_call=mock_llm_call
    )

    assert hypothetical == mock_hypothetical

    assert len(store.calls) == 1
    call_args = store.calls[0]
    assert call_args["collection_name"] == collection
    assert call_args["query_text"] == mock_hypothetical
    assert call_args["n_results"] == DEFAULT_K
