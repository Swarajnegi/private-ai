import pytest
from pathlib import Path
from jarvis_core.memory.code_parser import parse_python_file, CodeChunk

def test_parse_python_file_success(tmp_path):
    """Test successful parsing of a python file with various node types and sizes."""
    py_file = tmp_path / "test_sample.py"
    py_file.write_text(
        "class MyClass:\n"
        "    def __init__(self):\n"
        "        self.val = 1\n"
        "\n"
        "def my_func():\n"
        "    a = 1\n"
        "    b = 2\n"
        "    return a + b\n"
        "\n"
        "def short_func():\n"
        "    pass\n",
        encoding="utf-8"
    )

    chunks = parse_python_file(str(py_file))

    # _MIN_LINES is 3.
    # MyClass: 3 lines
    # my_func: 4 lines
    # short_func: 2 lines
    assert len(chunks) == 2

    # Check the class chunk
    class_chunk = next(c for c in chunks if c.node_type == "class_definition")
    assert class_chunk.name == "MyClass"
    assert class_chunk.start_line == 1
    assert class_chunk.end_line == 3
    assert "class MyClass" in class_chunk.text

    # Check the function chunk
    func_chunk = next(c for c in chunks if c.node_type == "function_definition")
    assert func_chunk.name == "my_func"
    assert func_chunk.start_line == 5
    assert func_chunk.end_line == 8
    assert "def my_func" in func_chunk.text

def test_parse_python_file_not_found(tmp_path):
    """Test parsing a non-existent file raises FileNotFoundError."""
    missing_file = tmp_path / "does_not_exist.py"
    with pytest.raises(FileNotFoundError, match="File not found"):
        parse_python_file(str(missing_file))

def test_parse_python_file_invalid_extension(tmp_path):
    """Test parsing a non-.py file raises ValueError."""
    txt_file = tmp_path / "test.txt"
    txt_file.write_text("Hello World")
    with pytest.raises(ValueError, match="Only .py files supported"):
        parse_python_file(str(txt_file))

def test_parse_python_file_empty(tmp_path):
    """Test parsing an empty file returns an empty list."""
    empty_file = tmp_path / "empty.py"
    empty_file.write_text("")
    chunks = parse_python_file(str(empty_file))
    assert chunks == []
