import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class OcrProcessingError(Exception):
    pass


class FileSizeExceededError(Exception):
    pass


class UnsupportedFileTypeError(Exception):
    pass


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(OcrProcessingError, _ocr_processing_exception_handler)
    app.add_exception_handler(FileSizeExceededError, _file_size_exceeded_handler)
    app.add_exception_handler(UnsupportedFileTypeError, _unsupported_file_type_handler)
    app.add_exception_handler(Exception, _global_exception_handler)


async def _ocr_processing_exception_handler(request: Request, exc: OcrProcessingError) -> JSONResponse:
    logger.error(f"OCR processing failed: {exc}")
    return JSONResponse(status_code=422, content={"detail": str(exc)})


async def _file_size_exceeded_handler(request: Request, exc: FileSizeExceededError) -> JSONResponse:
    logger.warning(f"File size exceeded: {exc}")
    return JSONResponse(status_code=400, content={"detail": str(exc)})


async def _unsupported_file_type_handler(request: Request, exc: UnsupportedFileTypeError) -> JSONResponse:
    logger.warning(f"Unsupported file type: {exc}")
    return JSONResponse(status_code=400, content={"detail": str(exc)})


async def _global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(f"Unhandled exception: {exc}")
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
