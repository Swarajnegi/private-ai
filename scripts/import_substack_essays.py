"""
import_substack_essays.py

Import the owner's published Substack essays into JARVIS's personalization
source corpus.

Run with:
    .venv\Scripts\python.exe scripts\import_substack_essays.py

=============================================================================
THE BIG PICTURE
=============================================================================

The personalization adapter must learn from the owner's authored prose, not
from an assistant describing the owner. The public essays are high-signal,
already-written voice material, but a URL mentioned in a roadmap is not a
reproducible corpus source.

This importer makes those sources explicit, reviewable Markdown files. It
extracts only the page's `body markup` article region and writes it in the
heading structure consumed by `personalization_corpus.extract_literature`.

=============================================================================
THE FLOW
=============================================================================

STEP 1: Fetch one explicit, public post URL.
        ↓
STEP 2: Parse only the `div.body.markup` article container.
        ↓
STEP 3: Render stable Markdown sections, splitting an unheaded essay into
        bounded passages when necessary.
        ↓
STEP 4: Atomically replace that essay's local source file.
=============================================================================
"""

from __future__ import annotations

import argparse
import html
import re
import sys
import tempfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "js-development"))

from jarvis_core.config import JARVIS_ROOT


_OUTPUT_DIR = JARVIS_ROOT / "knowledge" / "literature"
_USER_AGENT = "JARVIS-personalization-import/1.0 (owner-authored corpus)"
_MAX_SECTION_CHARS = 3_400
_BLOCK_TAGS = {"p", "h2", "h3", "li", "blockquote"}
_ESSAYS = (
    ("the_detective_of_unseen_graves", "The Detective of Unseen Graves",
     "https://swarajnegi.substack.com/p/the-detective-of-unseen-graves"),
    ("chasing_death_to_truly_live", "Chasing Death to Truly Live: The Philosophy of Mortality",
     "https://swarajnegi.substack.com/p/chasing-death-to-truly-live-the-philosophy"),
    ("a_study_of_conquest_napoleon", "A Study of Conquest: Napoleon's Reign",
     "https://swarajnegi.substack.com/p/a-study-of-conquest-napoleons-reign"),
)


@dataclass(frozen=True)
class Essay:
    """One explicit source, kept allowlisted rather than discovered at runtime."""

    filename: str
    title: str
    url: str


class ArticleBodyParser(HTMLParser):
    """Extract visible blocks from Substack's article-only body container."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._article_depth = 0
        self._active_tag: str | None = None
        self._fragments: list[str] = []
        self.blocks: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = dict(attrs).get("class", "") or ""
        if self._article_depth == 0 and tag == "div" and {"body", "markup"}.issubset(classes.split()):
            self._article_depth = 1
            return
        if self._article_depth == 0:
            return
        if tag == "div":
            self._article_depth += 1
        if tag in _BLOCK_TAGS and self._active_tag is None:
            self._active_tag = tag
            self._fragments = []
        elif tag == "br" and self._active_tag is not None:
            self._fragments.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self._article_depth == 0:
            return
        if tag == self._active_tag:
            text = _normalise("".join(self._fragments))
            if text:
                self.blocks.append((tag, text))
            self._active_tag = None
            self._fragments = []
        if tag == "div":
            self._article_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._article_depth and self._active_tag is not None:
            self._fragments.append(data)


def _normalise(value: str) -> str:
    return re.sub(r"[ \t\r\f\v]+", " ", html.unescape(value)).replace(" \n", "\n").strip()


def fetch(url: str) -> str:
    """Fetch one public source with a clear, bounded request."""
    request = Request(url, headers={"User-Agent": _USER_AGENT})
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def _passages(blocks: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    """Return heading/body sections, creating bounded headings only when absent."""
    sections: list[tuple[str, list[str]]] = []
    current_title = ""
    current: list[str] = []
    for tag, text in blocks:
        if tag in {"h2", "h3"}:
            if current:
                sections.append((current_title, current))
            current_title, current = text, []
        elif tag == "li":
            current.append(f"- {text}")
        elif tag == "blockquote":
            current.append(f"> {text}")
        else:
            current.append(text)
    if current:
        sections.append((current_title, current))

    rendered: list[tuple[str, str]] = []
    for title, body_blocks in sections:
        body = "\n\n".join(body_blocks).strip()
        if not body:
            continue
        if title:
            rendered.append((title, body))
            continue
        chunks: list[str] = []
        chunk: list[str] = []
        size = 0
        for block in body_blocks:
            if chunk and size + len(block) > _MAX_SECTION_CHARS:
                chunks.append("\n\n".join(chunk))
                chunk, size = [], 0
            chunk.append(block)
            size += len(block)
        if chunk:
            chunks.append("\n\n".join(chunk))
        rendered.extend((f"Passage {index}", value) for index, value in enumerate(chunks, start=1))
    return rendered


def render(essay: Essay, blocks: list[tuple[str, str]]) -> str:
    """Render the exact authored text in the Markdown contract the corpus reads."""
    sections = _passages(blocks)
    if not sections:
        raise ValueError(f"No article body found at {essay.url}")
    lines = [f"# {essay.title}", "", f"Source: {essay.url}", ""]
    for title, body in sections:
        lines.extend((f"## {title}", "", body, ""))
    return "\n".join(lines).rstrip() + "\n"


def write_atomic(path: Path, content: str) -> None:
    """Replace a corpus source only after a complete successful fetch and parse."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    temporary.replace(path)


def import_essay(essay: Essay, dry_run: bool) -> tuple[Path, int]:
    """Fetch, validate, and optionally persist one allowlisted essay."""
    parser = ArticleBodyParser()
    parser.feed(fetch(essay.url))
    content = render(essay, parser.blocks)
    path = _OUTPUT_DIR / f"{essay.filename}.md"
    if not dry_run:
        write_atomic(path, content)
    return path, len(content)


def main() -> int:
    parser = argparse.ArgumentParser(description="Import the owner's public Substack essays.")
    parser.add_argument("--dry-run", action="store_true", help="fetch and validate without writing")
    args = parser.parse_args()
    for raw in _ESSAYS:
        path, chars = import_essay(Essay(*raw), args.dry_run)
        action = "validated" if args.dry_run else "wrote"
        print(f"{action}: {path.relative_to(JARVIS_ROOT)} ({chars:,} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
