from typing import Any, Optional

from pydantic import BaseModel


class SSEProgressEvent(BaseModel):
    type: str = "progress"
    message: str
    data: Optional[dict[str, Any]] = None


class SSECompleteEvent(BaseModel):
    type: str = "complete"
    download_url: str
    source: str
    model: str
    language: str
