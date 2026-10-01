import io
from collections.abc import Generator
from typing import Final

import numpy as np
import pypdfium2 as pdfium
from numpy.typing import NDArray
from PIL import Image, ImageOps

from src.api.mime_sniffer import sniff_mime
from src.config.config import QualityProfile, settings

PageImage = NDArray[np.uint8]

# The formats whose every frame is a page, matching what PaddleOCR's own reader did.
# Every other format is read at its first frame, as cv2.imread did.
MULTI_PAGE_IMAGE_FORMATS: Final[frozenset[str]] = frozenset({"TIFF"})


def apply_decompression_bomb_guard() -> None:
    """Make Pillow's process-wide bomb guard the source pixel ceiling, and nothing else."""
    Image.MAX_IMAGE_PIXELS = settings.OCR_MAX_SOURCE_PIXELS


apply_decompression_bomb_guard()


def image_page_count(image: Image.Image) -> int:
    if image.format in MULTI_PAGE_IMAGE_FORMATS:
        return int(getattr(image, "n_frames", 1))

    return 1


def render_pages(data: bytes, profile: QualityProfile) -> Generator[PageImage, None, None]:
    """Yield each page of a submission as the BGR array the OCR engine reads, one at a time.

    A page is never larger than the profile's largest supported long side and never scaled up.
    """
    if sniff_mime(data) == "application/pdf":
        return _render_pdf_pages(data, profile)

    return _render_image_pages(data, profile)


def _render_pdf_pages(data: bytes, profile: QualityProfile) -> Generator[PageImage, None, None]:
    document = pdfium.PdfDocument(data)
    try:
        document.init_forms()
        for index in range(len(document)):
            page = document[index]
            try:
                yield page.render(scale=_pdf_render_scale(page.get_size(), profile)).to_numpy()
            finally:
                page.close()
    finally:
        document.close()


def _pdf_render_scale(page_size_points: tuple[float, float], profile: QualityProfile) -> float:
    fitting_scale = profile.max_long_side_pixels / max(page_size_points)

    return min(profile.render_scale, fitting_scale)


def _render_image_pages(data: bytes, profile: QualityProfile) -> Generator[PageImage, None, None]:
    with Image.open(io.BytesIO(data)) as image:
        page_count = image_page_count(image)

    for index in range(page_count):
        yield _read_image_frame(data, index, profile.max_long_side_pixels)


def _read_image_frame(data: bytes, index: int, max_long_side: int) -> PageImage:
    bounding_box = (max_long_side, max_long_side)

    with Image.open(io.BytesIO(data)) as image:
        image.seek(index)
        image.draft("RGB", bounding_box)
        ImageOps.exif_transpose(image, in_place=True)
        frame = image if image.mode == "RGB" else image.convert("RGB")
        frame.thumbnail(bounding_box, Image.Resampling.LANCZOS)

        return np.ascontiguousarray(np.asarray(frame, dtype=np.uint8)[:, :, ::-1])
