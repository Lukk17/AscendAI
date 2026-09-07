from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from src.api.exception_handlers import FileSizeExceededError, UnsupportedFileTypeError
from src.api.limits import InputShape, enforce_page_limit, enforce_pixel_ceiling, inspect_input
from src.config.config import settings
from tests.conftest import VALID_MULTI_PAGE_PDF_BYTES, VALID_PDF_BYTES, VALID_PNG_BYTES, _make_png


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
    def test_reports_decoded_pixel_dimensions(self):
        # Given
        data = _make_png(width=20, height=10)

        # When
        shape = inspect_input(data, "image/png")

        # Then
        assert shape.page_count == 1
        assert shape.max_page_pixels == 200

    def test_corrupt_header_raises_unsupported_file_type(self):
        # When / Then
        with pytest.raises(UnsupportedFileTypeError, match="Cannot read image header"):
            inspect_input(b"not a real image", "image/png")

    def test_declared_pixels_far_above_ceiling_raise_file_too_large(self, monkeypatch):
        # Given — Pillow's own bomb guard only raises above twice MAX_IMAGE_PIXELS, so a
        # real image whose pixel count crosses that line must be remapped to the
        # service's own oversized-input error rather than left as Pillow's own type.
        monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10)
        data = _make_png(width=10, height=10)

        # When / Then
        with pytest.raises(FileSizeExceededError, match="pixel ceiling"):
            inspect_input(data, "image/png")

    def test_reads_only_the_header_not_the_full_pixel_buffer(self):
        # Given — a real, valid image. Image.open() only parses the header; accessing
        # .size (as _inspect_image does) must not force Image.load(), which is the
        # method that actually decodes and allocates the full pixel buffer.
        data = _make_png(width=50, height=50)

        # When / Then
        with patch("src.api.limits.Image.Image.load") as mock_load:
            inspect_input(data, "image/png")

        mock_load.assert_not_called()


class TestInspectPdf:
    def test_reports_page_count_and_largest_rendered_page(self):
        # When
        shape = inspect_input(VALID_MULTI_PAGE_PDF_BYTES, "application/pdf")

        # Then
        assert shape.page_count == 2
        assert shape.max_page_pixels == int(100 * 2.0 * 100 * 2.0)

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

    def test_document_is_closed_even_when_page_inspection_fails(self):
        # Given
        broken_pdf = MagicMock()
        broken_pdf.__len__.return_value = 1
        broken_pdf.__getitem__.side_effect = RuntimeError("corrupt page")

        # When / Then
        with (
            patch("src.api.limits.pdfium.PdfDocument", return_value=broken_pdf),
            pytest.raises(RuntimeError, match="corrupt page"),
        ):
            inspect_input(b"irrelevant", "application/pdf")

        broken_pdf.close.assert_called_once()


class TestEnforcePixelCeiling:
    def test_at_ceiling_is_accepted(self, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OCR_MAX_INFERENCE_PIXELS", 100)

        # When / Then — no raise
        enforce_pixel_ceiling(InputShape(page_count=1, max_page_pixels=100))

    def test_above_ceiling_is_refused(self, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OCR_MAX_INFERENCE_PIXELS", 100)

        # When / Then
        with pytest.raises(FileSizeExceededError, match="exceeding the ceiling of 100"):
            enforce_pixel_ceiling(InputShape(page_count=1, max_page_pixels=101))


class TestEnforcePageLimit:
    def test_at_limit_is_accepted(self, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OCR_REQUEST_TIMEOUT", 10.0)
        monkeypatch.setattr(settings, "OCR_PAGE_TIMEOUT_SECONDS", 5.0)

        # When / Then — no raise, floor(10/5) == 2
        enforce_page_limit(InputShape(page_count=2, max_page_pixels=1))

    def test_above_limit_is_refused(self, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OCR_REQUEST_TIMEOUT", 10.0)
        monkeypatch.setattr(settings, "OCR_PAGE_TIMEOUT_SECONDS", 5.0)

        # When / Then
        with pytest.raises(FileSizeExceededError, match="exceeding the limit of 2"):
            enforce_page_limit(InputShape(page_count=3, max_page_pixels=1))
