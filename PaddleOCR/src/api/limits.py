import io
import warnings
from dataclasses import dataclass

import pypdfium2 as pdfium
from PIL import Image

from src.api.exception_handlers import FileSizeExceededError, UnsupportedFileTypeError
from src.config.config import settings

# Matches PADDLE_PDX_PDF_RENDER_SCALE's own default in paddlex/utils/flags.py: the
# library rasterizes every PDF page at this fixed zoom on PDF points, which is 144 dpi.
# Not configurable here by design (see ADR for the fixed rendering resolution) — this
# constant only lets the service predict what the library will do, it does not control it.
PDF_RENDER_SCALE: float = 2.0

Image.MAX_IMAGE_PIXELS = settings.OCR_MAX_INFERENCE_PIXELS


@dataclass(frozen=True)
class InputShape:
    page_count: int
    max_page_pixels: int


def inspect_input(data: bytes, mime: str) -> InputShape:
    """Determine the page count and the pixels one inference will receive, from the header only.

    Raises:
        UnsupportedFileTypeError: when the header cannot be parsed.
    """
    if mime == "application/pdf":
        return _inspect_pdf(data)

    return _inspect_image(data)


def _inspect_image(data: bytes) -> InputShape:
    # Pillow's own decompression-bomb guard (Image.MAX_IMAGE_PIXELS, set from
    # OCR_MAX_INFERENCE_PIXELS at import time above) only warns below twice that
    # value and raises above it, so both branches are handled explicitly here: the
    # warning is suppressed because enforce_pixel_ceiling below is the real guard for
    # that range, and the raise is remapped to the service's own oversized-input code.
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                width, height = image.size
    except Image.DecompressionBombError as exc:
        raise FileSizeExceededError(
            f"Image exceeds the pixel ceiling of {settings.OCR_MAX_INFERENCE_PIXELS}: {exc}"
        ) from exc
    except Exception as exc:
        raise UnsupportedFileTypeError(f"Cannot read image header: {exc}") from exc

    return InputShape(page_count=1, max_page_pixels=width * height)


def _inspect_pdf(data: bytes) -> InputShape:
    try:
        pdf = pdfium.PdfDocument(data)
    except Exception as exc:
        raise UnsupportedFileTypeError(f"Cannot read PDF header: {exc}") from exc

    try:
        page_count = len(pdf)
        if page_count == 0:
            raise UnsupportedFileTypeError("PDF declares no pages")

        max_pixels = 0
        for index in range(page_count):
            width_pt, height_pt = pdf[index].get_size()
            pixels = int(width_pt * PDF_RENDER_SCALE * height_pt * PDF_RENDER_SCALE)
            max_pixels = max(max_pixels, pixels)
    finally:
        pdf.close()

    return InputShape(page_count=page_count, max_page_pixels=max_pixels)


def enforce_pixel_ceiling(shape: InputShape) -> None:
    if shape.max_page_pixels > settings.OCR_MAX_INFERENCE_PIXELS:
        raise FileSizeExceededError(
            f"One inference would receive {shape.max_page_pixels} pixels, "
            f"exceeding the ceiling of {settings.OCR_MAX_INFERENCE_PIXELS}"
        )


def enforce_page_limit(shape: InputShape) -> None:
    if shape.page_count > settings.OCR_MAX_PAGES:
        raise FileSizeExceededError(
            f"Document has {shape.page_count} pages, exceeding the limit of {settings.OCR_MAX_PAGES}"
        )
