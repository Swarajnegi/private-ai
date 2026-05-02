import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from jarvis_core.memory.image_extractor import extract_images, ExtractedImage

@pytest.fixture
def mock_extracted_image_1():
    return ExtractedImage(
        page_number=1,
        image_bytes=b"fake_image_data_1",
        extension="png",
        xref_id=101,
        size_bytes=len(b"fake_image_data_1"),
        bbox=(0.0, 0.0, 100.0, 100.0)
    )

@pytest.fixture
def mock_extracted_image_2():
    return ExtractedImage(
        page_number=1,
        image_bytes=b"fake_image_data_2",
        extension="jpeg",
        xref_id=102,
        size_bytes=len(b"fake_image_data_2"),
        bbox=(100.0, 100.0, 200.0, 200.0)
    )

@pytest.fixture
def mock_extracted_image_3():
    return ExtractedImage(
        page_number=2,
        image_bytes=b"fake_image_data_3",
        extension="png",
        xref_id=103,
        size_bytes=len(b"fake_image_data_3"),
        bbox=(0.0, 0.0, 50.0, 50.0)
    )

@patch("jarvis_core.memory.image_extractor.PdfImageExtractor")
def test_extract_images_happy_path(mock_extractor_class, tmp_path, mock_extracted_image_1, mock_extracted_image_3):
    # Setup mock extractor
    mock_extractor_instance = MagicMock()
    mock_extractor_instance.stream_images.return_value = [mock_extracted_image_1, mock_extracted_image_3]
    mock_extractor_class.return_value.__enter__.return_value = mock_extractor_instance

    pdf_path = "mock_source_pdf.pdf"
    output_dir = tmp_path / "output_images"

    # Call function
    saved_paths = extract_images(pdf_path, str(output_dir))

    # Assertions
    assert len(saved_paths) == 2
    assert output_dir.exists()

    expected_path_1 = output_dir / "mock_source_pdf_page1_img1.png"
    expected_path_2 = output_dir / "mock_source_pdf_page2_img1.png"

    assert expected_path_1 in saved_paths
    assert expected_path_2 in saved_paths

    assert expected_path_1.exists()
    assert expected_path_2.exists()

    assert expected_path_1.read_bytes() == b"fake_image_data_1"
    assert expected_path_2.read_bytes() == b"fake_image_data_3"

@patch("jarvis_core.memory.image_extractor.PdfImageExtractor")
def test_extract_images_empty_case(mock_extractor_class, tmp_path):
    # Setup mock extractor
    mock_extractor_instance = MagicMock()
    mock_extractor_instance.stream_images.return_value = []
    mock_extractor_class.return_value.__enter__.return_value = mock_extractor_instance

    pdf_path = "mock_empty_pdf.pdf"
    output_dir = tmp_path / "output_images"

    # Call function
    saved_paths = extract_images(pdf_path, str(output_dir))

    # Assertions
    assert len(saved_paths) == 0
    assert output_dir.exists() # Should still create the directory
    assert len(list(output_dir.iterdir())) == 0 # But directory should be empty

@patch("jarvis_core.memory.image_extractor.PdfImageExtractor")
def test_extract_images_counters(mock_extractor_class, tmp_path, mock_extracted_image_1, mock_extracted_image_2):
    # Setup mock extractor
    mock_extractor_instance = MagicMock()
    # Return two images for the SAME page
    mock_extractor_instance.stream_images.return_value = [mock_extracted_image_1, mock_extracted_image_2]
    mock_extractor_class.return_value.__enter__.return_value = mock_extractor_instance

    pdf_path = "mock_counters_pdf.pdf"
    output_dir = tmp_path / "output_images"

    # Call function
    saved_paths = extract_images(pdf_path, str(output_dir))

    # Assertions
    assert len(saved_paths) == 2

    expected_path_1 = output_dir / "mock_counters_pdf_page1_img1.png"
    expected_path_2 = output_dir / "mock_counters_pdf_page1_img2.jpeg"

    assert expected_path_1 in saved_paths
    assert expected_path_2 in saved_paths

    assert expected_path_1.exists()
    assert expected_path_2.exists()
