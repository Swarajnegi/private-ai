import pytest
from unittest.mock import MagicMock, patch
from jarvis_core.memory.expansion import expand_then_query, VALID_STRATEGIES, FusedHit

class MockStore:
    def query_collection(self, collection_name, query_text, n_results):
        return {
            "ids": [["id1"]],
            "documents": [["doc1"]],
            "metadatas": [[{"source": "test"}]],
            "distances": [[0.1]]
        }

def mock_llm_call(prompt: str) -> str:
    return "mock response"

@pytest.fixture
def store():
    return MockStore()

def test_expand_then_query_invalid_strategy(store):
    with pytest.raises(ValueError, match="strategy must be one of"):
        expand_then_query(store, "test_collection", "test query", mock_llm_call, strategy="invalid")


@patch("jarvis_core.memory.expansion.should_expand")
def test_expand_then_query_skip_expansion(mock_should_expand, store):
    mock_should_expand.return_value = False

    result = expand_then_query(store, "test_col", "test query", mock_llm_call, k=1)

    assert result["expanded"] is False
    assert result["strategy"] == "baseline"
    assert "result" in result
    assert result["result"]["distances"][0][0] == 0.1

@patch("jarvis_core.memory.expansion.should_expand")
@patch("jarvis_core.memory.expansion.hyde_query")
def test_expand_then_query_hyde(mock_hyde_query, mock_should_expand, store):
    mock_should_expand.return_value = True

    mock_hyde_query.return_value = ("hypothetical answer", {"ids": [["id2"]], "documents": [["doc2"]]})

    result = expand_then_query(store, "test_col", "test query", mock_llm_call, k=1, strategy="hyde")

    assert result["expanded"] is True
    assert result["strategy"] == "hyde"
    assert result["hypothetical"] == "hypothetical answer"
    assert result["result"]["ids"][0][0] == "id2"
    mock_hyde_query.assert_called_once()

@patch("jarvis_core.memory.expansion.should_expand")
@patch("jarvis_core.memory.expansion.multi_query_search")
def test_expand_then_query_multi_query(mock_multi_query, mock_should_expand, store):
    mock_should_expand.return_value = True

    fused_hit = FusedHit(chunk_id="id3", document="doc3", metadata={"key": "val"}, appeared_in=1, rrf_score=0.8)
    mock_multi_query.return_value = (["query1", "query2"], [fused_hit])

    result = expand_then_query(store, "test_col", "test query", mock_llm_call, k=1, strategy="multi_query")

    assert result["expanded"] is True
    assert result["strategy"] == "multi_query"
    assert result["queries_used"] == ["query1", "query2"]
    assert len(result["fused_hits"]) == 1
    assert result["result"]["ids"][0][0] == "id3"
    assert result["result"]["distances"][0][0] == pytest.approx(0.2) # 1.0 - 0.8

@patch("jarvis_core.memory.expansion.should_expand")
@patch("jarvis_core.memory.expansion.hyde_query")
@patch("jarvis_core.memory.expansion.multi_query_search")
def test_expand_then_query_auto_hyde(mock_multi_query, mock_hyde_query, mock_should_expand, store):
    mock_should_expand.return_value = True
    mock_hyde_query.return_value = ("hypo", {"ids": []})

    # "test query" has 2 words (<= 6), so should use hyde
    result = expand_then_query(store, "test_col", "test query", mock_llm_call, k=1, strategy="auto")

    assert result["strategy"] == "hyde"
    mock_hyde_query.assert_called_once()
    mock_multi_query.assert_not_called()

@patch("jarvis_core.memory.expansion.should_expand")
@patch("jarvis_core.memory.expansion.hyde_query")
@patch("jarvis_core.memory.expansion.multi_query_search")
def test_expand_then_query_auto_multi_query(mock_multi_query, mock_hyde_query, mock_should_expand, store):
    mock_should_expand.return_value = True
    mock_multi_query.return_value = ([], [])

    # 7 words query (> 6), so should use multi_query
    long_query = "this is a long query to trigger multi query"
    result = expand_then_query(store, "test_col", long_query, mock_llm_call, k=1, strategy="auto")

    assert result["strategy"] == "multi_query"
    mock_multi_query.assert_called_once()
    mock_hyde_query.assert_not_called()

@patch("jarvis_core.memory.expansion.should_expand")
def test_expand_then_query_force(mock_should_expand, store):
    # even if should_expand is False, force=True should bypass it
    mock_should_expand.return_value = False

    with patch("jarvis_core.memory.expansion.hyde_query") as mock_hyde:
        mock_hyde.return_value = ("hypo", {"ids": []})
        result = expand_then_query(store, "test_col", "test query", mock_llm_call, k=1, strategy="hyde", force=True)

        assert result["expanded"] is True
        mock_hyde.assert_called_once()
