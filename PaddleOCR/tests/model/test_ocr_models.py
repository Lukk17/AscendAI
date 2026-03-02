import pytest
from pydantic import ValidationError

from src.model.ocr_models import (
    OutputFormat,
    OcrTextLine,
    OcrPageResult,
    OcrJsonResponse,
    HealthResponse,
)


def _create_text_line(
        text: str = "sample text",
        confidence: float = 0.95,
        bounding_box: list[list[float]] | None = None,
) -> OcrTextLine:
    if bounding_box is None:
        bounding_box = [[0.0, 0.0], [100.0, 0.0], [100.0, 20.0], [0.0, 20.0]]
    return OcrTextLine(text=text, confidence=confidence, bounding_box=bounding_box)


class TestOutputFormat:
    def test_json_value(self):
        assert OutputFormat.JSON == "json"

    def test_from_string(self):
        assert OutputFormat("json") == OutputFormat.JSON

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError):
            OutputFormat("xml")


class TestOcrTextLine:
    def test_creation(self):
        # Arrange / Act
        line = _create_text_line()

        # Assert
        assert line.text == "sample text"
        assert line.confidence == 0.95
        assert len(line.bounding_box) == 4

    def test_empty_text(self):
        # Arrange / Act
        line = _create_text_line(text="")

        # Assert
        assert line.text == ""

    def test_zero_confidence(self):
        # Arrange / Act
        line = _create_text_line(confidence=0.0)

        # Assert
        assert line.confidence == 0.0

    def test_serialization(self):
        # Arrange
        line = _create_text_line()

        # Act
        data = line.model_dump()

        # Assert
        assert data["text"] == "sample text"
        assert data["confidence"] == 0.95


class TestOcrPageResult:
    def test_creation_with_lines(self):
        # Arrange
        lines = [_create_text_line(), _create_text_line(text="second")]

        # Act
        page = OcrPageResult(page_number=1, lines=lines)

        # Assert
        assert page.page_number == 1
        assert len(page.lines) == 2

    def test_empty_lines(self):
        # Arrange / Act
        page = OcrPageResult(page_number=1, lines=[])

        # Assert
        assert len(page.lines) == 0


class TestOcrJsonResponse:
    def test_creation(self):
        # Arrange
        page = OcrPageResult(page_number=1, lines=[_create_text_line()])

        # Act
        response = OcrJsonResponse(
            filename="test.png",
            language="en",
            pages=[page],
            processing_time_seconds=1.5,
        )

        # Assert
        assert response.filename == "test.png"
        assert response.language == "en"
        assert len(response.pages) == 1
        assert response.processing_time_seconds == 1.5


class TestHealthResponse:
    def test_creation(self):
        # Arrange / Act
        health = HealthResponse(status="ok", version="0.1.0")

        # Assert
        assert health.status == "ok"
        assert health.version == "0.1.0"
