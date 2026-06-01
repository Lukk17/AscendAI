from typing import Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION: Literal["1"] = "1"


class OcrTextLine(BaseModel):
    text: str = Field(max_length=10_000)
    confidence: float = Field(ge=0.0, le=1.0)
    bounding_box: list[list[float]] = Field(max_length=32)


class OcrPageResult(BaseModel):
    page_number: int = Field(ge=1)
    lines: list[OcrTextLine]


class OcrJsonResponse(BaseModel):
    schema_version: Literal["1"] = SCHEMA_VERSION
    filename: str = Field(max_length=512)
    language: str = Field(pattern=r"^[a-z]{2,5}$")
    pages: list[OcrPageResult]
    processing_time_seconds: float = Field(ge=0.0)


class HealthResponse(BaseModel):
    status: Literal["ok", "warming-up"] = "ok"
    version: str


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not-ready"]
    version: str
    engine_warm: bool
