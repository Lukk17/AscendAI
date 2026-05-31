from unittest.mock import MagicMock, patch

import pytest

from src.config.config import settings
from src.model.ocr_models import OcrJsonResponse
from src.service.ocr_service import OcrService, _convert_polygon, _safe_suffix


def _create_mock_predict_result() -> list[dict[str, object]]:
    return [
        {
            "rec_texts": ["Invoice Number: 12345", "Total: $500.00"],
            "rec_scores": [0.98, 0.95],
            "dt_polys": [
                [(10.0, 5.0), (200.0, 5.0), (200.0, 25.0), (10.0, 25.0)],
                [(10.0, 30.0), (200.0, 30.0), (200.0, 50.0), (10.0, 50.0)],
            ],
        }
    ]


def _create_multi_page_predict_result() -> list[dict[str, object]]:
    return [
        {
            "rec_texts": ["Page one"],
            "rec_scores": [0.9],
            "dt_polys": [[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]],
        },
        {
            "rec_texts": ["Page two"],
            "rec_scores": [0.91],
            "dt_polys": [[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]],
        },
    ]


class TestOcrServiceEngineCache:
    @patch("src.service.ocr_service.PaddleOCR")
    def test_engine_cached_per_language(self, mock_paddle_class):
        # Given
        service = OcrService()
        mock_paddle_class.return_value = MagicMock()

        # When
        service._get_engine("en")
        service._get_engine("en")

        # Then
        assert mock_paddle_class.call_count == 1

    @patch("src.service.ocr_service.PaddleOCR")
    def test_different_languages_create_separate_engines(self, mock_paddle_class):
        # Given
        service = OcrService()
        mock_paddle_class.return_value = MagicMock()

        # When
        service._get_engine("en")
        service._get_engine("pl")

        # Then
        assert mock_paddle_class.call_count == 2

    @patch("src.service.ocr_service.PaddleOCR")
    def test_unsupported_language_raises(self, mock_paddle_class):
        # Given
        service = OcrService()

        # Then
        with pytest.raises(ValueError, match="Unsupported language"):
            service._get_engine("xx-fake")

    @patch("src.service.ocr_service.PaddleOCR")
    def test_lru_eviction(self, mock_paddle_class, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "ENGINE_CACHE_MAX_SIZE", 2)
        mock_paddle_class.return_value = MagicMock()
        service = OcrService()

        # When — load three different langs, oldest should be evicted
        service._get_engine("en")
        service._get_engine("pl")
        service._get_engine("de")

        # Then
        assert "en" not in service._engines
        assert "pl" in service._engines
        assert "de" in service._engines


class TestOcrServiceBuildPages:
    def test_build_pages_assigns_page_numbers_in_order(self):
        # Given
        service = OcrService()

        # When
        pages = service._build_pages(_create_multi_page_predict_result())

        # Then
        assert [p.page_number for p in pages] == [1, 2]
        assert pages[0].lines[0].text == "Page one"
        assert pages[1].lines[0].text == "Page two"

    def test_build_pages_returns_empty_for_none(self):
        # Then
        assert OcrService()._build_pages(None) == []

    def test_build_pages_skips_non_dict_entries(self):
        # Given
        service = OcrService()
        garbage_then_real = ["not-a-dict", _create_mock_predict_result()[0]]

        # When
        pages = service._build_pages(garbage_then_real)

        # Then
        assert len(pages) == 1


class TestOcrServiceProcessFile:
    @patch("src.service.ocr_service.PaddleOCR")
    def test_process_file_json_output(self, mock_paddle_class):
        # Given
        mock_engine = MagicMock()
        mock_engine.predict.return_value = _create_mock_predict_result()
        mock_paddle_class.return_value = mock_engine
        service = OcrService()

        # When
        result = service.process_file(b"fake_bytes", "test.png", "en")

        # Then
        assert isinstance(result, OcrJsonResponse)
        assert result.filename == "test.png"
        assert result.language == "en"
        assert len(result.pages) == 1
        assert len(result.pages[0].lines) == 2
        assert result.pages[0].lines[0].confidence == pytest.approx(0.98)
        assert result.pages[0].lines[0].bounding_box == [
            [10.0, 5.0],
            [200.0, 5.0],
            [200.0, 25.0],
            [10.0, 25.0],
        ]

    @patch("src.service.ocr_service.PaddleOCR")
    def test_process_file_multi_page(self, mock_paddle_class):
        # Given
        mock_engine = MagicMock()
        mock_engine.predict.return_value = _create_multi_page_predict_result()
        mock_paddle_class.return_value = mock_engine
        service = OcrService()

        # When
        result = service.process_file(b"x", "test.pdf", "en")

        # Then
        assert len(result.pages) == 2
        assert result.pages[0].page_number == 1
        assert result.pages[1].page_number == 2

    @patch("src.service.ocr_service.PaddleOCR")
    def test_process_file_empty_result(self, mock_paddle_class):
        # Given
        mock_engine = MagicMock()
        mock_engine.predict.return_value = [{}]
        mock_paddle_class.return_value = mock_engine
        service = OcrService()

        # When
        result = service.process_file(b"x", "empty.png", "en")

        # Then
        assert len(result.pages) == 1
        assert result.pages[0].lines == []

    @patch("src.service.ocr_service.PaddleOCR")
    def test_process_file_cleanup_skipped_when_file_already_gone(self, mock_paddle_class):
        # Given
        mock_engine = MagicMock()
        mock_engine.predict.return_value = _create_mock_predict_result()
        mock_paddle_class.return_value = mock_engine
        service = OcrService()

        # When / Then. Patch exists -> False inline so the unused fixture parameter is dropped.
        with patch("src.service.ocr_service.os.path.exists", return_value=False):
            result = service.process_file(b"x", "test.png", "en")

        assert isinstance(result, OcrJsonResponse)


class TestOcrServiceWarmUp:
    @patch("src.service.ocr_service.PaddleOCR")
    def test_warm_up_creates_engine(self, mock_paddle_class):
        # Given
        mock_paddle_class.return_value = MagicMock()
        service = OcrService()

        # When
        service.warm_up_engine("en")

        # Then
        assert "en" in service._engines


class TestSafeSuffix:
    def test_valid_suffix(self):
        # Then
        assert _safe_suffix("scan.png") == ".png"

    def test_no_extension_returns_empty(self):
        # Then
        assert _safe_suffix("noextension") == ""

    def test_dot_only_returns_empty(self):
        # Then
        assert _safe_suffix("trailing.") == ""

    def test_attacker_long_suffix_stripped(self):
        # Then
        assert _safe_suffix("foo." + "x" * 100) == ""

    def test_non_alnum_suffix_stripped(self):
        # Then
        assert _safe_suffix("foo.!evil!") == ""


class TestConvertPolygon:
    def test_valid_polygon(self):
        # Given
        polygon = [(1, 2), (3, 4)]

        # When
        converted = _convert_polygon(polygon)

        # Then
        assert converted == [[1.0, 2.0], [3.0, 4.0]]

    def test_none_returns_empty(self):
        # Then
        assert _convert_polygon(None) == []

    def test_empty_returns_empty(self):
        # Then
        assert _convert_polygon([]) == []

    def test_index_error_returns_empty(self):
        # Then — point with no elements triggers IndexError
        assert _convert_polygon([[]]) == []

    def test_value_error_returns_empty(self):
        # Then — non-numeric coordinates trigger ValueError on float()
        assert _convert_polygon([["x", "y"]]) == []

    def test_numpy_array_polygon_does_not_raise_on_truthiness(self):
        # Given. PaddleOCR returns dt_polys as numpy arrays in production. An older
        # `if not polygon` check raised `ValueError: The truth value of an array with
        # more than one element is ambiguous` and surfaced as OCR_FAILED on every
        # real engine call. Simulate the numpy semantics with a stub that mimics
        # __bool__ and __len__ without importing numpy in the test suite.
        class _FakeArray:
            def __init__(self, points: list[tuple[float, float]]) -> None:
                self._points = points

            def __bool__(self) -> bool:
                raise ValueError(
                    "The truth value of an array with more than one element is ambiguous"
                )

            def __len__(self) -> int:
                return len(self._points)

            def __iter__(self):
                return iter(self._points)

        polygon = _FakeArray([(1.0, 2.0), (3.0, 4.0), (5.0, 6.0), (7.0, 8.0)])

        # When
        result = _convert_polygon(polygon)

        # Then
        assert result == [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0], [7.0, 8.0]]
