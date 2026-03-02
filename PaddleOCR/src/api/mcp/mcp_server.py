import os
from fastmcp import FastMCP
from src.config.logging_config import get_logger
from src.service.ocr_service import ocr_service
from typing import Any

logger = get_logger(__name__)

mcp = FastMCP("PaddleOCR")


@mcp.tool()
async def ocr_process(file_path: str, lang: str = "en") -> dict[str, Any]:
    """
    Process a file through OCR.
    Args:
        file_path: Absolute path to the file to process.
        lang: Language code for OCR (e.g., 'en', 'pl').
    """
    _validate_file_exists(file_path)
    file_bytes: bytes = _read_file(file_path)
    filename: str = os.path.basename(file_path)
    result = ocr_service.process_file(file_bytes, filename, lang)
    return result.model_dump()


def _validate_file_exists(file_path: str) -> None:
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")


def _read_file(file_path: str) -> bytes:
    with open(file_path, "rb") as file_handle:
        return file_handle.read()
