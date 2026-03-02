from fastapi import APIRouter, UploadFile

from src.api.exception_handlers import (
    OcrProcessingError,
    FileSizeExceededError,
    UnsupportedFileTypeError,
)
from src.config.config import settings
from src.config.logging_config import get_logger
from src.model.ocr_models import OcrJsonResponse
from src.service.ocr_service import ocr_service

logger = get_logger(__name__)

rest_router = APIRouter(prefix="/v1")

BYTES_PER_MB: int = 1024 * 1024
ALLOWED_MIME_PREFIXES: tuple[str, ...] = ("image/", "application/pdf")


@rest_router.post("/ocr", response_model=None)
async def process_ocr(
        files: UploadFile,
        lang: str | None = None,
) -> OcrJsonResponse:
    language: str = lang or settings.DEFAULT_LANGUAGE
    _validate_file_type(files.content_type)
    file_bytes: bytes = await files.read()
    _validate_file_size(len(file_bytes))
    return _execute_ocr(file_bytes, files.filename, language)


def _validate_file_type(content_type: str | None) -> None:
    if not content_type:
        raise UnsupportedFileTypeError("File content type is missing")
    is_allowed: bool = any(content_type.startswith(prefix) for prefix in ALLOWED_MIME_PREFIXES)
    if not is_allowed:
        raise UnsupportedFileTypeError(f"Unsupported file type: {content_type}")


def _validate_file_size(size_bytes: int) -> None:
    max_size_bytes: int = settings.MAX_FILE_SIZE_MB * BYTES_PER_MB
    if size_bytes > max_size_bytes:
        raise FileSizeExceededError(
            f"File size {size_bytes} bytes exceeds maximum {settings.MAX_FILE_SIZE_MB} MB"
        )


def _execute_ocr(
        file_bytes: bytes,
        filename: str,
        language: str,
) -> OcrJsonResponse:
    try:
        return ocr_service.process_file(file_bytes, filename, language)
    except Exception as exc:
        raise OcrProcessingError(f"OCR processing failed for {filename}: {exc}") from exc
