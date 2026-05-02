import pytest
from unittest.mock import MagicMock
from jarvis_core.memory.expansion import (
    should_expand,
    hyde_query,
    multi_query_search,
    expand_then_query,
)

@pytest.mark.parametrize("query, expected", [
    ("what is dropout regularization", True),
    ("how does cross-attention work", True),
    ("ChromaDB.query_collection error", False),  # identifier .
    ("path/to/file", False),                      # identifier /
    ("my_function()", False),                     # identifier ( ) _
    ("AWQ quantization", False),                  # acronym
    ("explain MMR algorithm", False),             # acronym
    ("BERT is a model", False),                   # acronym
    ("NLP is great", False),                      # acronym (heuristic limitation)
    ("", True),                                   # empty string
    (" ".join(["word"] * 30), True),              # exactly 30 words
    (" ".join(["word"] * 31), False),             # 31 words
    ("a" * 100, True),                            # one very long word (still 1 word)
    ("special character !", True),                # non-identifier special character
    ("bracket [ test", False),                    # identifier [
    ("bracket ] test", False),                    # identifier ]
    ("brace { test", False),                      # identifier {
    ("brace } test", False),                      # identifier }
    ("chevron < test", False),                    # identifier <
    ("chevron > test", False),                    # identifier >
])
def test_should_expand(query, expected):
    assert should_expand(query) == expected

def test_hyde_query():
    store = MagicMock()
    llm_call = MagicMock(return_value="Hypothetical answer.")
    collection = "test_collection"
    query = "test query"

    hypothetical, result = hyde_query(store, collection, query, llm_call, k=3)

    assert hypothetical == "Hypothetical answer."
    llm_call.assert_called_once()
    store.query_collection.assert_called_once_with(
        collection_name=collection,
        query_text="Hypothetical answer.",
        n_results=3
    )

def test_multi_query_search():
    store = MagicMock()
    llm_call = MagicMock(return_value="q1\nq2\nq3")
    store.query_collection.return_value = {
        "ids": [["id1", "id2"]],
        "documents": [["doc1", "doc2"]],
        "metadatas": [[{"m": 1}, {"m": 2}]],
        "distances": [[0.1, 0.2]]
    }

    queries, fused = multi_query_search(store, "coll", "orig", llm_call, k=2, n_paraphrasings=2)

    assert queries == ["orig", "q1", "q2"]
    assert len(fused) == 2
    assert llm_call.called
    assert store.query_collection.call_count == 3

def test_expand_then_query_baseline():
    store = MagicMock()
    llm_call = MagicMock()
    query = " ".join(["word"] * 40)  # Should not expand

    res = expand_then_query(store, "coll", query, llm_call)

    assert res["expanded"] is False
    assert res["strategy"] == "baseline"
    store.query_collection.assert_called_once()
    llm_call.assert_not_called()

def test_expand_then_query_force_hyde():
    store = MagicMock()
    llm_call = MagicMock(return_value="Hypo")
    query = " ".join(["word"] * 40)

    res = expand_then_query(store, "coll", query, llm_call, strategy="hyde", force=True)

    assert res["expanded"] is True
    assert res["strategy"] == "hyde"
    assert res["hypothetical"] == "Hypo"

def test_expand_then_query_auto_hyde():
    store = MagicMock()
    llm_call = MagicMock(return_value="Hypo")
    query = "short query" # 2 words <= 6

    res = expand_then_query(store, "coll", query, llm_call, strategy="auto")

    assert res["expanded"] is True
    assert res["strategy"] == "hyde"

def test_expand_then_query_auto_multi_query():
    store = MagicMock()
    llm_call = MagicMock(return_value="q1\nq2\nq3")
    store.query_collection.return_value = {
        "ids": [["id1"]],
        "documents": [["doc1"]],
        "metadatas": [[{}]],
        "distances": [[0.1]]
    }
    query = "this is a slightly longer medium length query" # 8 words > 6

    res = expand_then_query(store, "coll", query, llm_call, strategy="auto")

    assert res["expanded"] is True
    assert res["strategy"] == "multi_query"

def test_expand_then_query_invalid_strategy():
    with pytest.raises(ValueError, match="strategy must be one of"):
        expand_then_query(None, "coll", "query", None, strategy="invalid")
