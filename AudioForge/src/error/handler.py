from fastapi import HTTPException

from src.error.forge_error import ForgeError
from src.io.file_service import cleanup_paths


def handle_forge_error(e: ForgeError, uploaded_path: str) -> None:
    """
    Cleanup uploaded temp and raise HTTPException mapped from ForgeError.
    """
    cleanup_paths([uploaded_path])
    raise HTTPException(status_code=500, detail=str(e))