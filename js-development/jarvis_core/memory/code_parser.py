"""
code_parser.py

JARVIS Memory Layer: Tree-Sitter Python Code Parser.

Import with:
    from jarvis_core.memory.code_parser import CodeParser, parse_python_file

Run (smoke test):
    python -m jarvis_core.memory.code_parser

=============================================================================
THE BIG PICTURE: Parse source code into semantic chunks for JARVIS memory
=============================================================================

Without this parser:
    -> All code is treated as flat text (same as PDF plain text)
    -> Chunker splits mid-function, breaking semantic meaning
    -> ChromaDB gets "def foo(self,\n    x: int)\n -> None:" split across 3 chunks
    -> Retrieval for "how does foo work" returns fragments, not the full function
    -> No function names in metadata -- can't filter by "class", "function", etc.

With this parser:
    -> tree-sitter parses the Python AST (Abstract Syntax Tree) precisely
    -> Each chunk = one complete function OR one complete class
    -> Metadata carries: function name, node type, start/end line
    -> Retrieval for "how does ingest_pdf work" returns the FULL method body
    -> Brain can ask: "give me all functions that mention ChromaDB"

=============================================================================
THE FLOW (Step by Step Execution Order)
=============================================================================

STEP 1: CodeParser.__init__ -- load tree-sitter Python grammar
        |
STEP 2: parse_file(path) called
        |
STEP 3: tree-sitter parses the .py file into an AST in memory
        |
STEP 4: Walk AST nodes, collect: function_definition, class_definition
        For each node: extract source text, name, start line, end line
        |
STEP 5: Yield CodeChunk objects (name, text, node_type, start_line, end_line)
        |
STEP 6: Caller passes chunks to JarvisMemoryStore.ingest_documents()
        Collection: "source_code"

=============================================================================
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generator, List

import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser


# =============================================================================
# Part 1: DATA CONTRACT
# =============================================================================

@dataclass
class CodeChunk:
    """
    MEMORY LAYER: One semantic unit of parsed source code.

    Purpose:
        - Carries everything needed to store a function/class in ChromaDB
        - Structured so the Brain can query by name, type, or line range

    How it works:
        - One CodeChunk per function definition or class definition in the file
        - The 'text' field is what gets embedded (the full source of the node)
        - All other fields go into ChromaDB metadata
    """

    name:       str          # e.g. "ingest_pdf", "JarvisMemoryStore"
    text:       str          # Full source text of the node (what gets embedded)
    node_type:  str          # "function_definition" or "class_definition"
    source:     str          # Filename (e.g. "store.py") -- the Foreign Key to disk
    start_line: int          # 1-indexed line where the function/class starts
    end_line:   int          # 1-indexed line where it ends
    language:   str = "python"
    category:   str = "code"
    specialist: str = "The Engineer"

    def chunk_id(self) -> str:
        """
        Deterministic chunk ID: md5(source + name + start_line).

        Why include start_line?
            A file can have two functions with the same name at different stages
            of refactoring (e.g., overloads in test files). Line number breaks ties.

        Returns:
            16-char hex string, same as IngestionPipeline._make_chunk_ids().
        """
        raw = f"{self.source}::{self.name}::L{self.start_line}".encode("utf-8")
        return hashlib.md5(raw).hexdigest()[:16]

    def to_metadata(self) -> dict:
        """Return a flat dict safe for ChromaDB metadata (no nested objects)."""
        return {
            "source":     self.source,
            "name":       self.name,
            "node_type":  self.node_type,
            "start_line": self.start_line,
            "end_line":   self.end_line,
            "language":   self.language,
            "category":   self.category,
            "specialist": self.specialist,
        }


# =============================================================================
# Part 2: THE PARSER
# =============================================================================

# Node types that represent a complete, self-contained semantic unit.
# We do NOT parse 'decorated_definition' separately because tree-sitter
# wraps the inner function/class inside it -- we collect the inner node.
_TARGET_TYPES: frozenset[str] = frozenset({
    "function_definition",
    "class_definition",
})

# Minimum number of lines a node must have to be worth storing.
# A 1-line function (e.g. `def foo(): pass`) adds noise, not signal.
_MIN_LINES: int = 3


class CodeParser:
    """
    MEMORY LAYER: Parses Python source files into semantic CodeChunks using tree-sitter.

    Purpose:
        - Replaces flat text splitting for source code
        - Produces one chunk per function or class definition
        - Each chunk has precise line-number metadata for navigation

    How it works:
        - Loads the tree-sitter Python grammar (pre-compiled, no build step)
        - Parses the file bytes into a CST (Concrete Syntax Tree)
        - Walks the tree, collecting function and class nodes
        - Yields CodeChunk objects ready for ChromaDB ingestion
    """

    def __init__(self) -> None:
        """
        Initialize the parser with the Python grammar.

        tree-sitter 0.25+ uses Language(capsule) directly.
        No compilation or .so file needed -- grammar is pre-built in the wheel.
        """
        py_language = Language(tspython.language())
        self._parser = Parser(py_language)

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def parse_file(self, file_path: str) -> Generator[CodeChunk, None, None]:
        """
        Parse a .py file and yield one CodeChunk per function or class.

        EXECUTION FLOW:
        1. Read raw bytes (tree-sitter works on bytes, not str).
        2. Parse into a CST via tree-sitter.
        3. Walk all nodes with a depth-first traversal.
        4. Collect nodes whose type is in _TARGET_TYPES.
        5. Skip nodes shorter than _MIN_LINES (trivial stubs).
        6. Extract name, text, line numbers.
        7. Yield CodeChunk.

        Args:
            file_path: Absolute path to the .py file.

        Yields:
            CodeChunk for each discovered function or class definition.

        Raises:
            FileNotFoundError: If file_path does not exist.
            ValueError:        If the file is not a .py file.
        """
        path = Path(file_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"[CodeParser] File not found: {path}")
        if path.suffix != ".py":
            raise ValueError(f"[CodeParser] Only .py files supported. Got: {path.suffix}")

        source_bytes: bytes = path.read_bytes()
        source_lines: List[str] = path.read_text(encoding="utf-8", errors="replace").splitlines()

        tree = self._parser.parse(source_bytes)

        for node in self._walk(tree.root_node):
            if node.type not in _TARGET_TYPES:
                continue

            start_line = node.start_point[0] + 1  # tree-sitter is 0-indexed
            end_line   = node.end_point[0] + 1

            if (end_line - start_line + 1) < _MIN_LINES:
                continue

            name = self._extract_name(node, source_bytes)
            text = self._extract_text(node, source_bytes)

            yield CodeChunk(
                name=name,
                text=text,
                node_type=node.type,
                source=path.name,
                start_line=start_line,
                end_line=end_line,
            )

    # ─────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _walk(self, node: Node) -> Generator[Node, None, None]:
        """
        Depth-first traversal of the CST.

        Why not use tree-sitter's built-in cursor?
            The cursor API requires manual navigation and state tracking.
            A simple recursive generator is cleaner for our read-only use case
            and the files we parse are small enough (< 1000 lines) to not
            need the cursor's performance advantage.

        Yields:
            Every node in the tree, depth-first.
        """
        yield node
        for child in node.children:
            yield from self._walk(child)

    @staticmethod
    def _extract_name(node: Node, source_bytes: bytes) -> str:
        """
        Extract the identifier name of a function or class node.

        The name child is always the second child of function_definition
        and class_definition in Python's grammar:
            (function_definition "def" name: (identifier) ...)
            (class_definition "class" name: (identifier) ...)

        Returns:
            The function or class name as a plain string.
            Falls back to "<anonymous>" if the grammar is unexpected.
        """
        for child in node.children:
            if child.type == "identifier":
                return source_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="replace")
        return "<anonymous>"

    @staticmethod
    def _extract_text(node: Node, source_bytes: bytes) -> str:
        """
        Extract the full source text of the node.

        Returns:
            Complete, verbatim source of the function or class,
            decoded as UTF-8. Used as the document text in ChromaDB.
        """
        return source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


# =============================================================================
# Part 3: CONVENIENCE FUNCTION (for IngestionPipeline integration)
# =============================================================================

def parse_python_file(file_path: str) -> List[CodeChunk]:
    """
    Parse a .py file into a list of CodeChunks.

    This is the recommended entry point for the IngestionPipeline.
    For large codebases, use CodeParser.parse_file() directly (generator).

    Args:
        file_path: Absolute path to the .py file.

    Returns:
        List of CodeChunk objects, one per function/class definition.
    """
    parser = CodeParser()
    return list(parser.parse_file(file_path))


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

    # Parse a file from our own codebase as the smoke test
    # (eating our own cooking: JARVIS parses its own source code)
    target = Path(__file__).resolve().parents[0] / "store.py"

    print("=" * 60)
    print("  JARVIS CodeParser — Smoke Test")
    print("=" * 60)
    print(f"  Target: {target.name}")
    print()

    parser = CodeParser()
    chunks = list(parser.parse_file(str(target)))

    print(f"  Found {len(chunks)} semantic chunks:\n")
    for chunk in chunks:
        print(
            f"  [{chunk.node_type[:5]}] {chunk.name:<40} "
            f"L{chunk.start_line}-{chunk.end_line}  "
            f"id={chunk.chunk_id()}"
        )

    print()
    print(f"  Sample chunk text (first function):")
    print("  " + "-" * 56)
    if chunks:
        sample = next(c for c in chunks if c.node_type == "function_definition")
        for line in sample.text.splitlines()[:8]:
            print(f"  {line}")
        if len(sample.text.splitlines()) > 8:
            print(f"  ... ({len(sample.text.splitlines()) - 8} more lines)")

    print()
    print(f"  Sample metadata:")
    if chunks:
        print(f"  {sample.to_metadata()}")

    print()
    print("  " + "=" * 56)
    print(f"  Chunk IDs are deterministic: re-run = same IDs")
    print(f"  Next step: pipe these into store.ingest_documents('source_code', ...)")
    print("  " + "=" * 56)
