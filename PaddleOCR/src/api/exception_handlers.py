import logging
from typing import Final

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.observability.metrics import OCR_ERRORS_TOTAL

logger = logging.getLogger(__name__)


class OcrProcessingError(Exception):
    pass


class FileSizeExceededError(Exception):
    pass


class UnsupportedFileTypeError(Exception):
    pass


class UnsafeUriError(Exception):
    pass


class DownloadFailedError(Exception):
    pass


ERROR_CODE_OCR_FAILED: Final[str] = "OCR_FAILED"
ERROR_CODE_FILE_TOO_LARGE: Final[str] = "FILE_TOO_LARGE"
ERROR_CODE_UNSUPPORTED_FILE_TYPE: Final[str] = "UNSUPPORTED_FILE_TYPE"
ERROR_CODE_UNSAFE_URI: Final[str] = "UNSAFE_URI"
ERROR_CODE_DOWNLOAD_FAILED: Final[str] = "DOWNLOAD_FAILED"
ERROR_CODE_INTERNAL: Final[str] = "INTERNAL_ERROR"


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(OcrProcessingError, _ocr_processing_handler)
    app.add_exception_handler(FileSizeExceededError, _file_size_exceeded_handler)
    app.add_exception_handler(UnsupportedFileTypeError, _unsupported_file_type_handler)
    app.add_exception_handler(UnsafeUriError, _unsafe_uri_handler)
    app.add_exception_handler(DownloadFailedError, _download_failed_handler)
    app.add_exception_handler(Exception, _global_exception_handler)


def _ocr_processing_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("OCR processing failed: %s", exc)
    _increment(ERROR_CODE_OCR_FAILED, request)

    return JSONResponse(
        status_code=422,
        content={"code": ERROR_CODE_OCR_FAILED, "detail": "OCR processing failed"},
    )


def _file_size_exceeded_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.warning("File size exceeded: %s", exc)
    _increment(ERROR_CODE_FILE_TOO_LARGE, request)

    return JSONResponse(
        status_code=400,
        content={"code": ERROR_CODE_FILE_TOO_LARGE, "detail": "File too large"},
    )


def _unsupported_file_type_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.warning("Unsupported file type: %s", exc)
    _increment(ERROR_CODE_UNSUPPORTED_FILE_TYPE, request)

    return JSONResponse(
        status_code=400,
        content={"code": ERROR_CODE_UNSUPPORTED_FILE_TYPE, "detail": "Unsupported file type"},
    )


def _unsafe_uri_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.warning("Unsafe URI rejected: %s", exc)
    _increment(ERROR_CODE_UNSAFE_URI, request)

    return JSONResponse(
        status_code=400,
        content={"code": ERROR_CODE_UNSAFE_URI, "detail": "URI is not permitted"},
    )


def _download_failed_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.warning("Download failed: %s", exc)
    _increment(ERROR_CODE_DOWNLOAD_FAILED, request)

    return JSONResponse(
        status_code=502,
        content={"code": ERROR_CODE_DOWNLOAD_FAILED, "detail": "Failed to fetch source"},
    )


def _global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception: %s", exc)
    _increment(ERROR_CODE_INTERNAL, request)

    return JSONResponse(
        status_code=500,
        content={"code": ERROR_CODE_INTERNAL, "detail": "Internal server error"},
    )


def _increment(code: str, request: Request) -> None:
    surface = "rest" if request.url.path.startswith("/v1") else "mcp"
    OCR_ERRORS_TOTAL.labels(error_code=code, surface=surface).inc()
