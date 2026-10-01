import io
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from src.api.exception_handlers import FileSizeExceededError, UnsupportedFileTypeError
from src.api.limits import InputShape, enforce_page_limit, inspect_input
from src.config.config import settings
from tests.conftest import VALID_MULTI_PAGE_PDF_BYTES, VALID_PDF_BYTES, VALID_PNG_BYTES, _make_pdf, _make_png


def _make_tiff(*frame_sizes: tuple[int, int]) -> bytes:
    """A real multi-frame TIFF, one frame per (width, height) pair."""
    buffer = io.BytesIO()
    frames = [Image.new("RGB", size, color="white") for size in frame_sizes]
    frames[0].save(buffer, format="TIFF", save_all=True, append_images=frames[1:])

    return buffer.getvalue()


class TestInspectInputDispatch:
    def test_pdf_mime_routes_to_pdf_inspection(self):
        # When
        shape = inspect_input(VALID_PDF_BYTES, "application/pdf")

        # Then
        assert shape.page_count == 1

    def test_image_mime_routes_to_image_inspection(self):
        # When
        shape = inspect_input(VALID_PNG_BYTES, "image/png")

        # Then
        assert shape.page_count == 1


class TestInspectImage:
    def test_an_image_at_the_source_pixel_ceiling_is_accepted(self, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OCR_MAX_SOURCE_PIXELS", 200)

        # When
        shape = inspect_input(_make_png(width=20, height=10), "image/png")

        # Then
        assert shape.page_count == 1

    def test_an_image_above_the_source_pixel_ceiling_is_refused_naming_both_numbers(self, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OCR_MAX_SOURCE_PIXELS", 199)

        # When / Then
        with pytest.raises(FileSizeExceededError, match="200 pixels, exceeding the source pixel ceiling of 199"):
            inspect_input(_make_png(width=20, height=10), "image/png")

    def test_a_300_dpi_a4_scan_is_accepted_rather_than_refused(self):
        # Given: the input the old 2.5 megapixel inference ceiling refused
        scan = _make_png(width=2480, height=3508)

        # When
        shape = inspect_input(scan, "image/png")

        # Then
        assert shape.page_count == 1

    def test_a_tiff_reports_one_page_per_frame(self):
        # When
        shape = inspect_input(_make_tiff((10, 10), (20, 5), (5, 5)), "image/tiff")

        # Then
        assert shape.page_count == 3

    def test_a_tiff_is_refused_when_a_later_frame_is_above_the_ceiling(self, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OCR_MAX_SOURCE_PIXELS", 150)

        # When / Then
        with pytest.raises(FileSizeExceededError, match="400 pixels"):
            inspect_input(_make_tiff((10, 10), (20, 20)), "image/tiff")

    def test_corrupt_header_raises_unsupported_file_type(self):
        # When / Then
        with pytest.raises(UnsupportedFileTypeError, match="Cannot read image header"):
            inspect_input(b"not a real image", "image/png")

    def test_pillows_own_guard_above_twice_its_limit_is_the_same_refusal(self, monkeypatch):
        # Given: Pillow raises by itself inside Image.open above twice MAX_IMAGE_PIXELS
        monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10)

        # When / Then
        with pytest.raises(FileSizeExceededError, match="source pixel ceiling"):
            inspect_input(_make_png(width=10, height=10), "image/png")

    def test_reads_only_the_header_not_the_full_pixel_buffer(self):
        # Given: Image.open() only parses the header, and neither .size nor seek() on a
        # TIFF forces Image.load(), which is what decodes and allocates the pixels
        data = _make_tiff((50, 50), (60, 60))

        # When / Then
        with patch("src.api.limits.Image.Image.load") as mock_load:
            inspect_input(data, "image/tiff")

        mock_load.assert_not_called()


class TestInspectPdf:
    def test_reports_page_count(self):
        # When
        shape = inspect_input(VALID_MULTI_PAGE_PDF_BYTES, "application/pdf")

        # Then
        assert shape.page_count == 2

    def test_a_physically_enormous_page_is_never_refused_for_its_pixels(self, monkeypatch):
        # Given: the service decides how many pixels a page is rendered at
        monkeypatch.setattr(settings, "OCR_MAX_SOURCE_PIXELS", 1)

        # When
        shape = inspect_input(_make_pdf((2000, 2000)), "application/pdf")

        # Then
        assert shape.page_count == 1

    def test_corrupt_header_raises_unsupported_file_type(self):
        # When / Then
        with pytest.raises(UnsupportedFileTypeError, match="Cannot read PDF header"):
            inspect_input(b"not a real pdf", "application/pdf")

    def test_zero_page_document_raises_unsupported_file_type(self):
        # Given
        empty_pdf = MagicMock()
        empty_pdf.__len__.return_value = 0

        # When / Then
        with (
            patch("src.api.limits.pdfium.PdfDocument", return_value=empty_pdf),
            pytest.raises(UnsupportedFileTypeError, match="no pages"),
        ):
            inspect_input(b"irrelevant", "application/pdf")

        empty_pdf.close.assert_called_once()

    def test_document_is_closed_even_when_counting_pages_fails(self):
        # Given
        broken_pdf = MagicMock()
        broken_pdf.__len__.side_effect = RuntimeError("corrupt page tree")

        # When / Then
        with (
            patch("src.api.limits.pdfium.PdfDocument", return_value=broken_pdf),
            pytest.raises(RuntimeError, match="corrupt page tree"),
        ):
            inspect_input(b"irrelevant", "application/pdf")

        broken_pdf.close.assert_called_once()


class TestEnforcePageLimit:
    def test_below_the_ceiling_is_accepted(self, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OCR_JOB_MAX_PAGES", 2)

        # When / Then: no raise
        enforce_page_limit(InputShape(page_count=1))

    def test_at_the_ceiling_is_accepted(self, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OCR_JOB_MAX_PAGES", 2)

        # When / Then: no raise
        enforce_page_limit(InputShape(page_count=2))

    def test_above_the_ceiling_is_refused_naming_both_numbers(self, monkeypatch):
        # Given: the only page ceiling left is the configured one
        monkeypatch.setattr(settings, "OCR_JOB_MAX_PAGES", 2)

        # When / Then
        with pytest.raises(FileSizeExceededError, match="Document has 3 pages, exceeding the limit of 2"):
            enforce_page_limit(InputShape(page_count=3))


class TestTheDecompressionBombGuardIsSetForTheApiProcess:
    def test_importing_the_limits_module_sets_the_image_library_limit_from_the_setting(self):
        # Then
        assert Image.MAX_IMAGE_PIXELS == settings.OCR_MAX_SOURCE_PIXELS
