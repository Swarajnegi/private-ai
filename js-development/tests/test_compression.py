import pytest
from unittest.mock import Mock, call

from jarvis_core.memory.compression import llm_filter, LLM_FILTER_PROMPT_TEMPLATE

def test_llm_filter_empty():
    chunks, metas, ids = llm_filter([], [], [], "query", Mock())
    assert chunks == []
    assert metas == []
    assert ids == []

def test_llm_filter_keeps_yes():
    chunks = ["chunk1", "chunk2"]
    metas = [{"meta": 1}, {"meta": 2}]
    ids = ["id1", "id2"]
    query = "test query"

    mock_llm = Mock(side_effect=["yes", "Yes, absolutely"])

    kept_chunks, kept_metas, kept_ids = llm_filter(chunks, metas, ids, query, mock_llm)

    assert kept_chunks == chunks
    assert kept_metas == metas
    assert kept_ids == ids

    # Check LLM calls formatting
    expected_calls = [
        call(LLM_FILTER_PROMPT_TEMPLATE.format(query=query, chunk="chunk1")),
        call(LLM_FILTER_PROMPT_TEMPLATE.format(query=query, chunk="chunk2"))
    ]
    mock_llm.assert_has_calls(expected_calls)

def test_llm_filter_drops_no():
    chunks = ["chunk1", "chunk2"]
    metas = [{"meta": 1}, {"meta": 2}]
    ids = ["id1", "id2"]
    query = "test query"

    mock_llm = Mock(side_effect=["no", "NO."])

    kept_chunks, kept_metas, kept_ids = llm_filter(chunks, metas, ids, query, mock_llm)

    assert kept_chunks == []
    assert kept_metas == []
    assert kept_ids == []

def test_llm_filter_mixed_and_ambiguous():
    chunks = ["chunk1", "chunk2", "chunk3", "chunk4"]
    metas = [{"meta": 1}, {"meta": 2}, {"meta": 3}, {"meta": 4}]
    ids = ["id1", "id2", "id3", "id4"]
    query = "test query"

    # chunk1: "yes" -> keep
    # chunk2: "no" -> drop
    # chunk3: "ambiguous string" -> keep (fail-open)
    # chunk4: exception -> keep (fail-closed, which acts as fail-open here)
    def mock_llm_side_effect(prompt):
        if "chunk1" in prompt: return "yes"
        if "chunk2" in prompt: return "no"
        if "chunk3" in prompt: return "I am not sure"
        if "chunk4" in prompt: raise ValueError("LLM Error")
        return "yes"

    mock_llm = Mock(side_effect=mock_llm_side_effect)

    kept_chunks, kept_metas, kept_ids = llm_filter(chunks, metas, ids, query, mock_llm)

    assert kept_chunks == ["chunk1", "chunk3", "chunk4"]
    assert kept_metas == [{"meta": 1}, {"meta": 3}, {"meta": 4}]
    assert kept_ids == ["id1", "id3", "id4"]
