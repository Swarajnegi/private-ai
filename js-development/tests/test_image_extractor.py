import unittest
from unittest.mock import MagicMock, patch
import sys

# Mock fitz before importing our module
sys.modules['fitz'] = MagicMock()

from jarvis_core.memory.image_extractor import PdfImageExtractor, ExtractedImage

class TestPdfImageExtractor(unittest.TestCase):
    @patch('jarvis_core.memory.image_extractor.fitz')
    def test_deduplication(self, mock_fitz):
        # Setup mock doc
        mock_doc = MagicMock()
        mock_fitz.open.return_value = mock_doc
        mock_doc.__len__.return_value = 1

        # Setup mock page
        mock_page = MagicMock()
        mock_doc.__getitem__.return_value = mock_page

        # Image 1 and 2 have different xrefs but same content bytes
        # Image 3 has different xref and different content bytes
        mock_page.get_images.return_value = [
            (1, 0, 100, 100, 8, 'DeviceRGB', '', 'Im1', 'FlateDecode', 0),
            (2, 0, 100, 100, 8, 'DeviceRGB', '', 'Im2', 'FlateDecode', 0),
            (3, 0, 100, 100, 8, 'DeviceRGB', '', 'Im3', 'FlateDecode', 0),
        ]

        def mock_extract_image(xref):
            if xref == 1:
                return {"image": b"duplicate_content", "ext": "png"}
            elif xref == 2:
                return {"image": b"duplicate_content", "ext": "png"}
            elif xref == 3:
                return {"image": b"unique_content", "ext": "png"}
            return None

        mock_doc.extract_image.side_effect = mock_extract_image

        # Setup bounding boxes
        mock_page.get_image_rects.return_value = [MagicMock(x0=0, y0=0, x1=10, y1=10)]

        # Mock pathlib.Path.exists to avoid FileNotFoundError
        with patch('jarvis_core.memory.image_extractor.Path.exists', return_value=True):
            # Run extractor with low threshold to ensure our dummy bytes pass the size filter
            with PdfImageExtractor("dummy.pdf", min_image_bytes=1) as extractor:
                images = list(extractor.stream_images())

        # Should only get 2 images, xref 1 and 3. xref 2 is skipped due to duplicate content.
        self.assertEqual(len(images), 2)
        self.assertEqual(images[0].xref_id, 1)
        self.assertEqual(images[1].xref_id, 3)

if __name__ == '__main__':
    unittest.main()
