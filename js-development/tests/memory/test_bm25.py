import pytest
from jarvis_core.memory.bm25 import default_tokenize

def test_default_tokenize_empty():
    assert default_tokenize("") == []

def test_default_tokenize_basic():
    assert default_tokenize("hello world") == ["hello", "world"]

def test_default_tokenize_lowercase():
    assert default_tokenize("Hello World") == ["hello", "world"]

def test_default_tokenize_identifiers():
    assert default_tokenize("store.query_collection") == ["store.query_collection"]
    assert default_tokenize("tf_idf") == ["tf_idf"]
    assert default_tokenize("müller") == ["müller"]
    assert default_tokenize("version 1.0.0") == ["version", "1.0.0"]

def test_default_tokenize_punctuation():
    assert default_tokenize("hello, world!") == ["hello", "world"]

def test_default_tokenize_dollars():
    assert default_tokenize("$contains") == ["contains"]
