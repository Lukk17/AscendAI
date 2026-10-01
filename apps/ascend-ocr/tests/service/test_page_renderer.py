import io
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PIL import Image

from src.config.config import QualityProfile, settings
from src.service.page_renderer import apply_decompression_bomb_guard, image_page_count, render_pages
from tests.conftest import _make_pdf

# 144 dpi is a scale of exactly 2.0 on PDF points, so every expected size is exact.
# Its largest supported long side is 14 in x 144 dpi = 2016 px.
PROFILE = QualityProfile(render_dpi=144, detector_max_side=1024)
LARGEST_LONG_SIDE = 2016
RED_IN_BGR = [0, 0, 255]


def _encode(image: Image.Image, image_format: str, **save_args: object) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format=image_format, **save_args)

    return buffer.getvalue()


def _red_pdf(width_pt: int, height_pt: int) -> bytes:
    return _encode(Image.new("RGB", (width_pt, height_pt), color="red"), "PDF")


def _two_frame_tiff() -> bytes:
    first = Image.new("RGB", (10, 10), color="red")

    return _encode(first, "TIFF", save_all=True, append_images=[Image.new("RGB", (20, 5), color="red")])


class TestPdfPages:
    def test_a_page_is_rendered_at_the_modes_resolution(self):
        # When
        pages = list(render_pages(_red_pdf(100, 50), PROFILE))

        # Then
        assert [page.shape for page in pages] == [(100, 200, 3)]

    def test_every_page_is_rendered_in_order(self):
        # When
        pages = list(render_pages(_make_pdf((100, 100), (50, 100)), PROFILE))

        # Then
        assert [page.shape for page in pages] == [(200, 200, 3), (200, 100, 3)]

    def test_a_page_larger_than_the_largest_supported_page_is_rendered_at_the_reduced_scale(self):
        # Given: 2000 pt at 144 dpi would be 4000 px on the long side
        document = _red_pdf(2000, 1000)

        # When
        pages = list(render_pages(document, PROFILE))

        # Then
        assert [page.shape for page in pages] == [(LARGEST_LONG_SIDE // 2, LARGEST_LONG_SIDE, 3)]

    def test_pixels_arrive_in_the_bgr_order_the_engine_reads(self):
        # When
        page = next(render_pages(_red_pdf(20, 20), PROFILE))

        # Then
        assert page.dtype == np.uint8
        assert page[5, 5].tolist() == pytest.approx(RED_IN_BGR, abs=2)

    def test_forms_are_initialised_and_the_document_is_closed_when_the_reader_stops_early(self):
        # Given
        page = MagicMock()
        page.get_size.return_value = (100.0, 100.0)
        page.render.return_value.to_numpy.return_value = np.zeros((1, 1, 3), dtype=np.uint8)
        document = MagicMock()
        document.__len__.return_value = 2
        document.__getitem__.return_value = page

        # When
        with patch("src.service.page_renderer.pdfium.PdfDocument", return_value=document):
            pages = render_pages(_red_pdf(10, 10), PROFILE)
            next(pages)
            pages.close()

        # Then
        document.init_forms.assert_called_once()
        page.render.assert_called_once_with(scale=pytest.approx(2.0))
        page.close.assert_called_once()
        document.close.assert_called_once()


class TestImagePages:
    def test_an_image_within_the_largest_supported_size_is_read_at_its_own_size(self):
        # When
        pages = list(render_pages(_encode(Image.new("RGB", (30, 20), color="red"), "PNG"), PROFILE))

        # Then
        assert [page.shape for page in pages] == [(20, 30, 3)]

    def test_pixels_arrive_in_the_bgr_order_the_engine_reads(self):
        # When
        page = next(render_pages(_encode(Image.new("RGB", (4, 4), color="red"), "PNG"), PROFILE))

        # Then
        assert page.dtype == np.uint8
        assert page.flags["C_CONTIGUOUS"]
        assert page[0, 0].tolist() == RED_IN_BGR

    def test_an_oversized_image_is_shrunk_to_the_largest_supported_long_side_keeping_its_aspect(self):
        # Given
        oversized = _encode(Image.new("RGB", (LARGEST_LONG_SIDE * 2, LARGEST_LONG_SIDE), color="red"), "PNG")

        # When
        pages = list(render_pages(oversized, PROFILE))

        # Then
        assert [page.shape for page in pages] == [(LARGEST_LONG_SIDE // 2, LARGEST_LONG_SIDE, 3)]

    def test_an_oversized_jpeg_is_shrunk_too(self):
        # Given
        oversized = _encode(Image.new("RGB", (LARGEST_LONG_SIDE * 4, 100), color="red"), "JPEG")

        # When
        page = next(render_pages(oversized, PROFILE))

        # Then
        assert page.shape[1] == LARGEST_LONG_SIDE

    def test_exif_orientation_is_applied(self):
        # Given: orientation 6 means the stored pixels must be turned a quarter to be upright
        exif = Image.Exif()
        exif[0x0112] = 6
        rotated = _encode(Image.new("RGB", (40, 20), color="red"), "JPEG", exif=exif.tobytes())

        # When
        page = next(render_pages(rotated, PROFILE))

        # Then
        assert page.shape == (40, 20, 3)

    def test_a_single_channel_image_is_read_as_three_channels(self):
        # When
        page = next(render_pages(_encode(Image.new("L", (8, 6), color=255), "PNG"), PROFILE))

        # Then
        assert page.shape == (6, 8, 3)

    def test_every_frame_of_a_tiff_is_a_page(self):
        # When
        pages = list(render_pages(_two_frame_tiff(), PROFILE))

        # Then
        assert [page.shape for page in pages] == [(10, 10, 3), (5, 20, 3)]


class TestImagePageCount:
    def test_a_tiff_has_as_many_pages_as_frames(self):
        # When
        with Image.open(io.BytesIO(_two_frame_tiff())) as image:
            count = image_page_count(image)

        # Then
        assert count == 2

    def test_any_other_format_is_read_at_its_first_frame_only(self):
        # Given
        frames = [Image.new("P", (4, 4), color=index) for index in range(3)]
        animation = _encode(frames[0], "GIF", save_all=True, append_images=frames[1:])

        # When
        with Image.open(io.BytesIO(animation)) as image:
            count = image_page_count(image)

        # Then
        assert count == 1


class TestDecompressionBombGuard:
    def test_the_image_library_limit_is_the_source_pixel_ceiling(self, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OCR_MAX_SOURCE_PIXELS", 123)
        monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", Image.MAX_IMAGE_PIXELS)

        # When
        apply_decompression_bomb_guard()

        # Then
        assert Image.MAX_IMAGE_PIXELS == 123

    def test_it_is_applied_when_the_renderer_is_imported(self):
        # Then: the worker process imports the renderer and nothing else sets it there
        assert Image.MAX_IMAGE_PIXELS == settings.OCR_MAX_SOURCE_PIXELS
