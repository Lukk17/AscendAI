from typing import Any

from pydantic import BaseModel, Field


class SSEProgressEvent(BaseModel):
    type: str = Field(default="progress")
    message: str
    data: dict[str, Any] | None = None


class SSECompleteEvent(BaseModel):
    type: str = Field(default="complete")
    download_url: str
    source: str
    model: str
    language: str


class SSEErrorEvent(BaseModel):
    type: str = Field(default="error")
    message: str
