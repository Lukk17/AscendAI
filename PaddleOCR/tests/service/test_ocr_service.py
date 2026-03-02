import pytest
from src.model.ocr_models import OcrJsonResponse
from src.service.ocr_service import OcrService
from unittest.mock import patch, MagicMock


def _create_mock_predict_result() -> list:
    return [
        {
            "rec_texts": ["Invoice Number: 12345", "Total: $500.00"],
            "rec_scores": [0.98, 0.95],
            "dt_polys": [
                [[10.0, 5.0], [200.0, 5.0], [200.0, 25.0], [10.0, 25.0]],
                [[10.0, 30.0], [200.0, 30.0], [200.0, 50.0], [10.0, 50.0]],
            ],
        }
    ]


def _create_empty_predict_result() -> list:
    return [{}]


class TestOcrServiceEngineCache:
    @patch("src.service.ocr_service.PaddleOCR")
    def test_engine_cached_per_language(self, mock_paddle_class):
        # Arrange
        service = OcrService()
        mock_paddle_class.return_value = MagicMock()

        # Act
        service._get_engine("en")
        service._get_engine("en")

        # Assert
        assert mock_paddle_class.call_count == 1

    @patch("src.service.ocr_service.PaddleOCR")
    def test_different_languages_create_separate_engines(self, mock_paddle_class):
        # Arrange
        service = OcrService()
        mock_paddle_class.return_value = MagicMock()

        # Act
        service._get_engine("en")
        service._get_engine("pl")

        # Assert
        assert mock_paddle_class.call_count == 2


class TestOcrServiceExtractTextLines:
    def test_extract_from_valid_result(self):
        # Arrange
        service = OcrService()
        ocr_result = _create_mock_predict_result()

        # Act
        lines = service._extract_text_lines(ocr_result)

        # Assert
        assert len(lines) == 2
        assert lines[0].text == "Invoice Number: 12345"
        assert lines[0].confidence == 0.98
        assert lines[1].text == "Total: $500.00"

    def test_extract_from_empty_result(self):
        # Arrange
        service = OcrService()

        # Act
        lines = service._extract_text_lines(_create_empty_predict_result())

        # Assert
        assert len(lines) == 0

    def test_extract_from_none_result(self):
        # Arrange
        service = OcrService()

        # Act
        lines = service._extract_text_lines(None)

        # Assert
        assert len(lines) == 0

    def test_extract_skips_none_pages(self):
        # Arrange
        service = OcrService()
        result_with_none = [None, _create_mock_predict_result()[0]]

        # Act
        lines = service._extract_text_lines(result_with_none)

        # Assert
        assert len(lines) == 2


class TestOcrServiceProcessFile:
    @patch("src.service.ocr_service.PaddleOCR")
    def test_process_file_json_output(self, mock_paddle_class):
        # Arrange
        mock_engine = MagicMock()
        mock_engine.predict.return_value = _create_mock_predict_result()
        mock_paddle_class.return_value = mock_engine
        service = OcrService()

        # Act
        result = service.process_file(b"fake_bytes", "test.png", "en")

        # Assert
        assert isinstance(result, OcrJsonResponse)
        assert result.filename == "test.png"
        assert result.language == "en"
        assert len(result.pages) == 1
        assert len(result.pages[0].lines) == 2

    @patch("src.service.ocr_service.PaddleOCR")
    def test_process_file_empty_result(self, mock_paddle_class):
        # Arrange
        mock_engine = MagicMock()
        mock_engine.predict.return_value = _create_empty_predict_result()
        mock_paddle_class.return_value = mock_engine
        service = OcrService()

        # Act
        result = service.process_file(b"fake_bytes", "empty.png", "en")

        # Assert
        assert isinstance(result, OcrJsonResponse)
        assert len(result.pages[0].lines) == 0


class TestOcrServiceWarmUp:
    @patch("src.service.ocr_service.PaddleOCR")
    def test_warm_up_creates_engine(self, mock_paddle_class):
        # Arrange
        mock_paddle_class.return_value = MagicMock()
        service = OcrService()

        # Act
        service.warm_up_engine("en")

        # Assert
        assert "en" in service._engines
