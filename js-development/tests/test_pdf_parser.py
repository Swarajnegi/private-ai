import pytest
from unittest.mock import patch, MagicMock

from jarvis_core.memory.pdf_parser import (
    parse_pdf,
    PageContent,
    TextBlock,
    StructuredDocument
)

def test_parse_pdf_happy_path():
    with patch("jarvis_core.memory.pdf_parser.PdfPageExtractor") as MockExtractor, \
         patch("jarvis_core.memory.pdf_parser.SpatialBlockMerger") as MockMerger:

        # Setup mock merger
        mock_merger_instance = MagicMock()
        MockMerger.return_value = mock_merger_instance

        # Setup mock extractor
        mock_extractor_instance = MagicMock()
        MockExtractor.return_value.__enter__.return_value = mock_extractor_instance
        mock_extractor_instance.page_count = 2

        page1 = PageContent(page_number=0, width=100, height=200)
        page2 = PageContent(page_number=1, width=100, height=200)
        mock_extractor_instance.stream_pages.return_value = [page1, page2]

        # Mock sorted blocks
        block1 = TextBlock(text="Block 1", bbox=(0,0,10,10), font_size=12, font_name="Arial", page_number=0)
        block2 = TextBlock(text="Block 2", bbox=(0,0,10,10), font_size=12, font_name="Arial", page_number=1)
        mock_merger_instance.sort_blocks.side_effect = [[block1], [block2]]

        # Call parse_pdf
        doc = parse_pdf("dummy.pdf", row_tolerance=10.0)

        # Asserts
        MockMerger.assert_called_once_with(row_tolerance=10.0)
        MockExtractor.assert_called_once_with("dummy.pdf")

        assert isinstance(doc, StructuredDocument)
        assert doc.source_path == "dummy.pdf"
        assert doc.total_pages == 2
        assert len(doc.pages) == 2
        assert doc.pages[0].blocks == [block1]
        assert doc.pages[1].blocks == [block2]

        assert mock_merger_instance.sort_blocks.call_count == 2
        assert mock_merger_instance.classify_roles.call_count == 2
        mock_merger_instance.classify_roles.assert_any_call([block1])
        mock_merger_instance.classify_roles.assert_any_call([block2])

def test_parse_pdf_empty_document():
    with patch("jarvis_core.memory.pdf_parser.PdfPageExtractor") as MockExtractor, \
         patch("jarvis_core.memory.pdf_parser.SpatialBlockMerger") as MockMerger:

        mock_extractor_instance = MagicMock()
        MockExtractor.return_value.__enter__.return_value = mock_extractor_instance
        mock_extractor_instance.page_count = 0
        mock_extractor_instance.stream_pages.return_value = []

        mock_merger_instance = MagicMock()
        MockMerger.return_value = mock_merger_instance

        doc = parse_pdf("empty.pdf")

        assert isinstance(doc, StructuredDocument)
        assert doc.source_path == "empty.pdf"
        assert doc.total_pages == 0
        assert len(doc.pages) == 0

        mock_merger_instance.sort_blocks.assert_not_called()
        mock_merger_instance.classify_roles.assert_not_called()

def test_parse_pdf_file_not_found():
    with patch("jarvis_core.memory.pdf_parser.PdfPageExtractor") as MockExtractor:
        MockExtractor.side_effect = FileNotFoundError("PDF not found: missing.pdf")

        with pytest.raises(FileNotFoundError, match="PDF not found: missing.pdf"):
            parse_pdf("missing.pdf")
