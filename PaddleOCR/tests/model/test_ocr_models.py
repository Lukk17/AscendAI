import pytest

from src.model.ocr_models import (
    HealthResponse,
    OcrJsonResponse,
    OcrPageResult,
    OcrTextLine,
    ReadinessResponse,
)


def _create_text_line(
    text: str = "sample text",
    confidence: float = 0.95,
    bounding_box: list[list[float]] | None = None,
) -> OcrTextLine:
    if bounding_box is None:
        bounding_box = [[0.0, 0.0], [100.0, 0.0], [100.0, 20.0], [0.0, 20.0]]

    return OcrTextLine(text=text, confidence=confidence, bounding_box=bounding_box)


class TestOcrTextLine:
    def test_creation(self):
        # When
        line = _create_text_line()

        # Then
        assert line.text == "sample text"
        assert line.confidence == pytest.approx(0.95)
        assert len(line.bounding_box) == 4

    def test_empty_text(self):
        # When
        line = _create_text_line(text="")

        # Then
        assert line.text == ""

    def test_zero_confidence(self):
        # When
        line = _create_text_line(confidence=0.0)

        # Then
        assert line.confidence == pytest.approx(0.0)

    def test_confidence_above_one_rejected(self):
        # Then
        with pytest.raises(ValueError):
            _create_text_line(confidence=1.5)

    def test_confidence_below_zero_rejected(self):
        # Then
        with pytest.raises(ValueError):
            _create_text_line(confidence=-0.1)

    def test_serialization(self):
        # Given
        line = _create_text_line()

        # When
        data = line.model_dump()

        # Then
        assert data["text"] == "sample text"
        assert data["confidence"] == pytest.approx(0.95)


class TestOcrPageResult:
    def test_creation_with_lines(self):
        # Given
        lines = [_create_text_line(), _create_text_line(text="second")]

        # When
        page = OcrPageResult(page_number=1, lines=lines)

        # Then
        assert page.page_number == 1
        assert len(page.lines) == 2

    def test_empty_lines(self):
        # When
        page = OcrPageResult(page_number=1, lines=[])

        # Then
        assert len(page.lines) == 0

    def test_page_number_must_be_positive(self):
        # Then
        with pytest.raises(ValueError):
            OcrPageResult(page_number=0, lines=[])


class TestOcrJsonResponse:
    def test_creation_carries_schema_version(self):
        # Given
        page = OcrPageResult(page_number=1, lines=[_create_text_line()])

        # When
        response = OcrJsonResponse(
            filename="test.png",
            language="en",
            pages=[page],
            processing_time_seconds=1.5,
        )

        # Then
        assert response.schema_version == "1"
        assert response.filename == "test.png"
        assert response.language == "en"
        assert response.processing_time_seconds == pytest.approx(1.5)

    def test_invalid_language_rejected(self):
        # Then
        with pytest.raises(ValueError):
            OcrJsonResponse(
                filename="x.png",
                language="not-a-lang",
                pages=[],
                processing_time_seconds=1.0,
            )


class TestHealthResponse:
    def test_creation(self):
        # When
        health = HealthResponse(status="ok", version="0.1.0")

        # Then
        assert health.status == "ok"
        assert health.version == "0.1.0"


class TestReadinessResponse:
    def test_ready(self):
        # When
        ready = ReadinessResponse(status="ready", version="0.1.0", engine_warm=True)

        # Then
        assert ready.status == "ready"
        assert ready.engine_warm is True

    def test_not_ready(self):
        # When
        not_ready = ReadinessResponse(status="not-ready", version="0.1.0", engine_warm=False)

        # Then
        assert not_ready.status == "not-ready"
        assert not_ready.engine_warm is False
