import io
import warnings
from dataclasses import dataclass

import pypdfium2 as pdfium
from PIL import Image

from src.api.exception_handlers import FileSizeExceededError, UnsupportedFileTypeError
from src.config.config import settings
from src.service.page_renderer import image_page_count


@dataclass(frozen=True)
class InputShape:
    page_count: int


def inspect_input(data: bytes, mime: str) -> InputShape:
    """Count the pages a submission holds, from the header only.

    Raises:
        UnsupportedFileTypeError: when the header cannot be parsed.
        FileSizeExceededError: when an image frame declares more pixels than the source pixel ceiling.
    """
    if mime == "application/pdf":
        return _inspect_pdf(data)

    return _inspect_image(data)


def _inspect_image(data: bytes) -> InputShape:
    # Pillow's own guard (Image.MAX_IMAGE_PIXELS, set from OCR_MAX_SOURCE_PIXELS) only
    # warns between one and two times its value and raises above that, so the warning is
    # silenced because enforce_source_pixel_ceiling below refuses that range itself, and
    # the raise is mapped to the same refusal.
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                frame_sizes = [_frame_size(image, index) for index in range(image_page_count(image))]
    except Image.DecompressionBombError as exc:
        raise FileSizeExceededError(
            f"Image exceeds the source pixel ceiling of {settings.OCR_MAX_SOURCE_PIXELS}: {exc}"
        ) from exc
    except Exception as exc:
        raise UnsupportedFileTypeError(f"Cannot read image header: {exc}") from exc

    for width, height in frame_sizes:
        enforce_source_pixel_ceiling(width * height)

    return InputShape(page_count=len(frame_sizes))


def _frame_size(image: Image.Image, index: int) -> tuple[int, int]:
    image.seek(index)

    return image.size


def _inspect_pdf(data: bytes) -> InputShape:
    try:
        pdf = pdfium.PdfDocument(data)
    except Exception as exc:
        raise UnsupportedFileTypeError(f"Cannot read PDF header: {exc}") from exc

    try:
        page_count = len(pdf)
    finally:
        pdf.close()

    if page_count == 0:
        raise UnsupportedFileTypeError("PDF declares no pages")

    return InputShape(page_count=page_count)


def enforce_source_pixel_ceiling(pixels: int) -> None:
    """Refuse an image frame at decompression-bomb scale.

    Raises:
        FileSizeExceededError: when the frame declares more pixels than OCR_MAX_SOURCE_PIXELS.
    """
    if pixels > settings.OCR_MAX_SOURCE_PIXELS:
        raise FileSizeExceededError(
            f"Image frame has {pixels} pixels, exceeding the source pixel ceiling of {settings.OCR_MAX_SOURCE_PIXELS}"
        )


def enforce_page_limit(shape: InputShape) -> None:
    if shape.page_count > settings.OCR_JOB_MAX_PAGES:
        raise FileSizeExceededError(
            f"Document has {shape.page_count} pages, exceeding the limit of {settings.OCR_JOB_MAX_PAGES}"
        )
