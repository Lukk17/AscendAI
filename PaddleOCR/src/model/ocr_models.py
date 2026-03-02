from enum import Enum

from pydantic import BaseModel


class OutputFormat(str, Enum):
    JSON = "json"


class OcrTextLine(BaseModel):
    text: str
    confidence: float
    bounding_box: list[list[float]]


class OcrPageResult(BaseModel):
    page_number: int
    lines: list[OcrTextLine]


class OcrJsonResponse(BaseModel):
    filename: str
    language: str
    pages: list[OcrPageResult]
    processing_time_seconds: float


class HealthResponse(BaseModel):
    status: str
    version: str
