import pytest
from jarvis_core.memory.compression import should_compress

def test_should_compress_happy_path():
    """Returns True for queries that meet all criteria."""
    assert should_compress("what is the concept of abstract syntax trees", 4, 1000) is True
    assert should_compress("explain quantum mechanics", 10, 5000) is True

def test_should_compress_low_k():
    """Returns False when k is less than 4."""
    # Boundary check (k=3)
    assert should_compress("what is the concept of abstract syntax trees", 3, 1000) is False
    # Extreme low (k=0)
    assert should_compress("what is the concept of abstract syntax trees", 0, 1000) is False

def test_should_compress_low_total_words():
    """Returns False when total_words is less than 1000."""
    # Boundary check (total_words=999)
    assert should_compress("what is the concept of abstract syntax trees", 4, 999) is False
    # Extreme low (total_words=0)
    assert should_compress("what is the concept of abstract syntax trees", 4, 0) is False

@pytest.mark.parametrize("char", ["(", ")", "[", "]", "{", "}", "/", "_", ".", "<", ">"])
def test_should_compress_identifier_chars(char):
    """Returns False when the query contains code-like identifier characters."""
    query = f"explain this {char} concept"
    assert should_compress(query, 5, 2000) is False

@pytest.mark.parametrize("acronym", ["CPU", "URLs", "NASA", "PDFs", "JSON"])
def test_should_compress_acronym(acronym):
    """Returns False when the query contains an acronym."""
    query = f"what does {acronym} mean"
    assert should_compress(query, 5, 2000) is False

def test_should_compress_acronym_edge_cases():
    """Ensures acronym pattern doesn't trigger on normal words or single letters."""
    # Single uppercase letter shouldn't trigger it (if not part of acronym)
    assert should_compress("A normal query", 5, 2000) is True
    # Capitalized word shouldn't trigger it
    assert should_compress("Normal Query Here", 5, 2000) is True
    # Numbers shouldn't trigger it
    assert should_compress("what is 42", 5, 2000) is True
