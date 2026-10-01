import asyncio
import contextlib
import itertools
import logging
import time
from collections.abc import Iterator
from concurrent.futures.process import BrokenProcessPool
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from src.api.exception_handlers import FileSizeExceededError, OcrProcessingError, UnsupportedFileTypeError
from src.config.config import LANGUAGE_MODEL_OVERRIDES, ModelPair, QualityProfile, settings
from src.model.ocr_models import OcrJsonResponse
from src.observability.metrics import ENGINE_CACHE_EVICTIONS_TOTAL, POOL_REBUILDS_TOTAL
from src.service import ocr_service as ocr_service_module
from src.service.job_store import new_job_id, read_progress
from src.service.ocr_service import (
    OcrDeadlineExceededError,
    OcrService,
    _convert_polygon,
    _noop_task,
    _resolve_model_pair,
    _terminate_pool_processes,
    _warm_worker_engine,
    build_engine,
    dispatch_ocr_request,
    get_pool_generation,
    get_process_pool,
    is_accepting_work,
    is_job_overrunning,
    is_pool_usable,
    is_rebuild_in_progress,
    preload_models,
    replace_worker_for_cancel,
    request_worker_replacement_for_cancel,
    run_ocr_in_worker,
    start_worker_pool,
    stop_worker_pool,
    wait_for_worker_replacements,
)
from tests.conftest import OFF_FAMILY_PAIR, _make_pdf, _make_png


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


PAGE_IMAGE = np.zeros((4, 4, 3), dtype=np.uint8)
PROFILE = QualityProfile(render_dpi=200, detector_max_side=1280)


def _engine_reading(*page_results: object) -> MagicMock:
    """An engine that answers one predict call per page, the way the service calls it."""
    engine = MagicMock()
    engine.predict_iter.side_effect = [iter([result]) for result in page_results]

    return engine


def _pages(count: int) -> Iterator[np.ndarray]:
    return iter([PAGE_IMAGE] * count)


def _default_pair() -> ModelPair:
    return ModelPair(settings.OCR_TEXT_DETECTION_MODEL, settings.OCR_TEXT_RECOGNITION_MODEL)


class TestModelPairResolution:
    def test_language_inside_the_default_family_resolves_to_the_configured_pair(self):
        # When / Then
        assert _resolve_model_pair("pl") == _default_pair()

    def test_language_outside_the_default_family_resolves_to_its_own_pair(self, off_family_language):
        # When / Then
        assert _resolve_model_pair(off_family_language) == OFF_FAMILY_PAIR

    def test_configured_pair_is_the_source_for_every_non_override_language(self, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OCR_TEXT_DETECTION_MODEL", "PP-OCRv6_medium_det")
        monkeypatch.setattr(settings, "OCR_TEXT_RECOGNITION_MODEL", "PP-OCRv6_medium_rec")

        # When / Then
        assert _resolve_model_pair("en") == ModelPair("PP-OCRv6_medium_det", "PP-OCRv6_medium_rec")

    def test_configured_pair_does_not_override_a_language_with_its_own_pair(self, monkeypatch, off_family_language):
        # Given
        monkeypatch.setattr(settings, "OCR_TEXT_DETECTION_MODEL", "PP-OCRv6_medium_det")
        monkeypatch.setattr(settings, "OCR_TEXT_RECOGNITION_MODEL", "PP-OCRv6_medium_rec")

        # When / Then
        assert _resolve_model_pair(off_family_language) == OFF_FAMILY_PAIR

    def test_every_override_language_is_a_supported_language(self):
        # When / Then - an override for a language the allowlist rejects would be unreachable
        assert set(LANGUAGE_MODEL_OVERRIDES) <= set(settings.SUPPORTED_LANGUAGES)

    def test_model_pair_renders_as_detection_over_recognition(self):
        # When / Then - this string is the eviction metric's label and the eviction log line
        assert str(ModelPair("det-model", "rec-model")) == "det-model/rec-model"


class TestOcrServiceEngineCache:
    @patch("src.service.ocr_service.PaddleOCR")
    def test_repeated_language_constructs_one_engine(self, mock_paddle_class):
        # Given
        service = OcrService()
        mock_paddle_class.return_value = MagicMock()

        # When
        service._get_engine("en")
        service._get_engine("en")

        # Then
        assert mock_paddle_class.call_count == 1

    @patch("src.service.ocr_service.PaddleOCR")
    def test_languages_sharing_a_model_pair_share_one_engine(self, mock_paddle_class):
        # Given - "en" and "pl" both resolve to the configured default pair
        service = OcrService()
        mock_paddle_class.return_value = MagicMock()

        # When
        service._get_engine("en")
        service._get_engine("pl")

        # Then
        assert mock_paddle_class.call_count == 1
        assert list(service._engines) == [_default_pair()]

    @patch("src.service.ocr_service.PaddleOCR")
    def test_languages_with_different_model_pairs_get_their_own_engine(self, mock_paddle_class, off_family_language):
        # Given
        service = OcrService()
        mock_paddle_class.return_value = MagicMock()

        # When
        service._get_engine("en")
        service._get_engine(off_family_language)

        # Then
        assert mock_paddle_class.call_count == 2
        assert list(service._engines) == [_default_pair(), OFF_FAMILY_PAIR]

    @patch("src.service.ocr_service.PaddleOCR")
    def test_configured_models_are_named_on_the_constructor(self, mock_paddle_class):
        # Given
        service = OcrService()
        mock_paddle_class.return_value = MagicMock()

        # When
        service._get_engine("en")

        # Then - named explicitly, and no `lang`, which the library would warn about and ignore
        _, kwargs = mock_paddle_class.call_args
        assert kwargs["text_detection_model_name"] == settings.OCR_TEXT_DETECTION_MODEL
        assert kwargs["text_recognition_model_name"] == settings.OCR_TEXT_RECOGNITION_MODEL
        assert "lang" not in kwargs

    @patch("src.service.ocr_service.PaddleOCR")
    def test_operator_configured_pair_reaches_the_constructor(self, mock_paddle_class, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OCR_TEXT_DETECTION_MODEL", "PP-OCRv6_medium_det")
        monkeypatch.setattr(settings, "OCR_TEXT_RECOGNITION_MODEL", "PP-OCRv6_medium_rec")
        mock_paddle_class.return_value = MagicMock()
        service = OcrService()

        # When
        service._get_engine("en")

        # Then
        _, kwargs = mock_paddle_class.call_args
        assert kwargs["text_detection_model_name"] == "PP-OCRv6_medium_det"
        assert kwargs["text_recognition_model_name"] == "PP-OCRv6_medium_rec"

    @patch("src.service.ocr_service.PaddleOCR")
    def test_override_language_is_constructed_from_its_own_pair(self, mock_paddle_class, off_family_language):
        # Given
        service = OcrService()
        mock_paddle_class.return_value = MagicMock()

        # When
        service._get_engine(off_family_language)

        # Then
        _, kwargs = mock_paddle_class.call_args
        assert kwargs["text_detection_model_name"] == OFF_FAMILY_PAIR.detection
        assert kwargs["text_recognition_model_name"] == OFF_FAMILY_PAIR.recognition

    @pytest.mark.parametrize("language", ["ru", "korean"])
    @patch("src.service.ocr_service.PaddleOCR")
    def test_russian_and_korean_are_refused_before_any_engine_is_built(self, mock_paddle_class, language):
        # Given: the shipped allowlist, with both switched off
        service = OcrService()

        # When
        with pytest.raises(ValueError, match="Unsupported language"):
            service._get_engine(language)

        # Then
        mock_paddle_class.assert_not_called()

    @patch("src.service.ocr_service.PaddleOCR")
    def test_unsupported_language_raises(self, mock_paddle_class):
        # Given
        service = OcrService()

        # When / Then
        with pytest.raises(ValueError, match="Unsupported language"):
            service._get_engine("xx-fake")

    @patch("src.service.ocr_service.PaddleOCR")
    def test_unsupported_language_is_refused_before_any_engine_is_built(self, mock_paddle_class):
        # Given
        service = OcrService()

        # When
        with pytest.raises(ValueError, match="Unsupported language"):
            service._get_engine("xx-fake")

        # Then
        mock_paddle_class.assert_not_called()
        assert not service._engines

    @patch("src.service.ocr_service.PaddleOCR")
    def test_lru_eviction(self, mock_paddle_class, monkeypatch, off_family_language):
        # Given: a second language opted back in with a third pair
        third_pair = ModelPair("PP-OCRv5_server_det", "korean_PP-OCRv5_mobile_rec")
        monkeypatch.setitem(LANGUAGE_MODEL_OVERRIDES, "korean", third_pair)
        monkeypatch.setattr(settings, "SUPPORTED_LANGUAGES", (*settings.SUPPORTED_LANGUAGES, "korean"))
        monkeypatch.setattr(settings, "ENGINE_CACHE_MAX_SIZE", 2)
        mock_paddle_class.return_value = MagicMock()
        service = OcrService()

        # When: three distinct model pairs, oldest should be evicted
        service._get_engine("en")
        service._get_engine(off_family_language)
        service._get_engine("korean")

        # Then
        assert _default_pair() not in service._engines
        assert OFF_FAMILY_PAIR in service._engines
        assert third_pair in service._engines

    @patch("src.service.ocr_service.PaddleOCR")
    def test_eviction_is_counted_against_the_evicted_model_pair(
        self, mock_paddle_class, monkeypatch, off_family_language
    ):
        # Given
        monkeypatch.setattr(settings, "ENGINE_CACHE_MAX_SIZE", 1)
        mock_paddle_class.return_value = MagicMock()
        service = OcrService()
        label = str(_default_pair())
        before = ENGINE_CACHE_EVICTIONS_TOTAL.labels(engine=label)._value.get()

        # When
        service._get_engine("en")
        service._get_engine(off_family_language)

        # Then
        assert ENGINE_CACHE_EVICTIONS_TOTAL.labels(engine=label)._value.get() == before + 1

    @patch("src.service.ocr_service.PaddleOCR")
    def test_the_engine_is_constructed_without_a_detector_bound(self, mock_paddle_class):
        # Given: the bound belongs to the request's quality mode, not to the engine
        mock_paddle_class.return_value = MagicMock()
        service = OcrService()

        # When
        service._get_engine("en")

        # Then
        _, kwargs = mock_paddle_class.call_args
        assert "text_det_limit_type" not in kwargs
        assert "text_det_limit_side_len" not in kwargs

    @patch("src.service.ocr_service.PaddleOCR")
    def test_the_engine_names_every_preprocessing_model_rather_than_inheriting_library_defaults(
        self, mock_paddle_class
    ):
        # Given: unwarping is loaded once and switched per call, so straightening needs no second engine
        mock_paddle_class.return_value = MagicMock()
        service = OcrService()

        # When
        service._get_engine("en")

        # Then
        _, kwargs = mock_paddle_class.call_args
        assert kwargs["use_doc_orientation_classify"] is True
        assert kwargs["use_doc_unwarping"] is True
        assert kwargs["use_textline_orientation"] is True
        assert kwargs["enable_mkldnn"] is False

    @patch("src.service.ocr_service.PaddleOCR")
    def test_the_line_orientation_classifier_decides_each_line_on_its_own(self, mock_paddle_class):
        # Given: the library's batch of 6 turns upright lines upside down in blocks of 6 on a mixed page
        mock_paddle_class.return_value = MagicMock()
        service = OcrService()

        # When
        service._get_engine("en")

        # Then
        _, kwargs = mock_paddle_class.call_args
        assert kwargs["textline_orientation_batch_size"] == 1

    @patch("src.service.ocr_service.PaddleOCR")
    def test_the_recogniser_reads_each_line_unpadded(self, mock_paddle_class):
        # Given: the library's batch of 6 pads every line to the widest in its batch, slower and dropping spaces
        mock_paddle_class.return_value = MagicMock()
        service = OcrService()

        # When
        service._get_engine("en")

        # Then
        _, kwargs = mock_paddle_class.call_args
        assert kwargs["text_recognition_batch_size"] == 1

    @patch("src.service.ocr_service.render_pages", side_effect=lambda _data, _profile: _pages(1))
    @patch("src.service.ocr_service.PaddleOCR")
    def test_straightened_and_plain_requests_share_one_engine(self, mock_paddle_class, _mock_render):
        # Given
        mock_paddle_class.return_value = _engine_reading({}, {})
        service = OcrService()

        # When
        service.process_file(b"x", "a.jpg", "en", "high", straighten=True)
        service.process_file(b"x", "b.jpg", "en", "high", straighten=False)

        # Then
        assert mock_paddle_class.call_count == 1
        assert list(service._engines) == [_default_pair()]

    @patch("src.service.ocr_service.render_pages", side_effect=lambda _data, _profile: _pages(1))
    @patch("src.service.ocr_service.PaddleOCR")
    def test_both_quality_modes_share_one_engine(self, mock_paddle_class, _mock_render):
        # Given
        mock_paddle_class.return_value = _engine_reading({}, {})
        service = OcrService()

        # When
        service.process_file(b"x", "a.png", "en", "normal")
        service.process_file(b"x", "b.png", "en", "high")

        # Then
        assert mock_paddle_class.call_count == 1
        assert list(service._engines) == [_default_pair()]


class TestOcrServicePredictPages:
    def test_predict_pages_assigns_page_numbers_in_order(self):
        # Given
        service = OcrService()
        engine = _engine_reading(*_create_multi_page_predict_result())

        # When
        pages = service._predict_pages(engine, _pages(2), PROFILE, deadline=None)

        # Then
        assert [p.page_number for p in pages] == [1, 2]
        assert pages[0].lines[0].text == "Page one"
        assert pages[1].lines[0].text == "Page two"

    def test_each_page_is_read_as_its_own_image_with_the_modes_detector_bound(self):
        # Given
        service = OcrService()
        first, second = np.zeros((2, 2, 3), dtype=np.uint8), np.ones((3, 3, 3), dtype=np.uint8)
        engine = _engine_reading({}, {})

        # When
        service._predict_pages(engine, iter([first, second]), PROFILE, deadline=None)

        # Then
        calls = engine.predict_iter.call_args_list
        assert [call.args[0] is image for call, image in zip(calls, [first, second], strict=True)] == [True, True]
        assert all(
            call.kwargs
            == {
                "text_det_limit_type": "max",
                "text_det_limit_side_len": 1280,
                "use_doc_orientation_classify": True,
                "use_doc_unwarping": False,
                "use_textline_orientation": True,
            }
            for call in calls
        )

    def test_a_straightened_page_is_unwarped_and_still_orientation_corrected(self):
        # Given
        service = OcrService()
        engine = _engine_reading({})

        # When
        service._predict_pages(engine, _pages(1), PROFILE, deadline=None, straighten=True)

        # Then
        kwargs = engine.predict_iter.call_args.kwargs
        assert kwargs["use_doc_unwarping"] is True
        assert kwargs["use_doc_orientation_classify"] is True
        assert kwargs["use_textline_orientation"] is True

    def test_predict_pages_empty_document_returns_empty(self):
        # Given
        service = OcrService()
        engine = _engine_reading()

        # When
        pages = service._predict_pages(engine, _pages(0), PROFILE, deadline=None)

        # Then
        assert pages == []
        engine.predict_iter.assert_not_called()

    def test_predict_pages_skips_non_dict_entries(self):
        # Given
        service = OcrService()
        engine = _engine_reading("not-a-dict", _create_mock_predict_result()[0])

        # When
        pages = service._predict_pages(engine, _pages(2), PROFILE, deadline=None)

        # Then
        assert len(pages) == 1

    def test_a_page_the_engine_returns_nothing_for_is_skipped(self):
        # Given
        service = OcrService()
        engine = MagicMock()
        engine.predict_iter.return_value = iter([])

        # When
        pages = service._predict_pages(engine, _pages(1), PROFILE, deadline=None)

        # Then
        assert pages == []

    def test_deadline_stops_before_first_page_when_already_expired(self):
        # Given: deadline in the past: no page should ever be rendered or read
        service = OcrService()
        engine = _engine_reading(*_create_multi_page_predict_result())
        rendered = MagicMock(wraps=_pages(2))

        # When / Then
        with pytest.raises(OcrDeadlineExceededError, match="after 0"):
            service._predict_pages(engine, rendered, PROFILE, deadline=time.monotonic() - 1)

        rendered.__next__.assert_not_called()
        engine.predict_iter.assert_not_called()

    def test_deadline_stops_mid_document_before_next_page_is_rendered(self):
        # Given: the deadline expires after the first page, so the second page must be
        # neither rendered nor read.
        service = OcrService()
        engine = _engine_reading(*_create_multi_page_predict_result())
        rendered = MagicMock(wraps=_pages(2))
        deadline = 100.0
        # Calls, in order: check before page 1 (before deadline), page-timer start,
        # page-timer end, check before page 2 (past deadline).
        monotonic_values = iter([50.0, 50.0, 50.1, 200.0])

        # When
        with (
            patch("src.service.ocr_service.time.monotonic", side_effect=lambda: next(monotonic_values)),
            pytest.raises(OcrDeadlineExceededError, match="after 1"),
        ):
            service._predict_pages(engine, rendered, PROFILE, deadline=deadline)

        # Then
        assert rendered.__next__.call_count == 1
        assert engine.predict_iter.call_count == 1

    def test_no_deadline_consumes_every_page(self):
        # Given
        service = OcrService()
        engine = _engine_reading(*_create_multi_page_predict_result())

        # When
        pages = service._predict_pages(engine, _pages(2), PROFILE, deadline=None)

        # Then
        assert len(pages) == 2

    def test_one_span_per_page_carrying_index_and_remaining_budget(self):
        # Given
        service = OcrService()
        engine = _engine_reading(*_create_multi_page_predict_result())
        deadline = time.monotonic() + 60.0

        # When
        with patch("src.service.ocr_service.tracer") as mock_tracer:
            service._predict_pages(engine, _pages(2), PROFILE, deadline=deadline)

        # Then: one span per page, each nested under whatever span is current when
        # _predict_pages runs, since start_as_current_span attaches to the ambient context
        page_span_calls = [
            call for call in mock_tracer.start_as_current_span.call_args_list if call.args[0].endswith(".page")
        ]
        assert len(page_span_calls) == 2
        assert page_span_calls[0].kwargs["attributes"]["page_index"] == 1
        assert page_span_calls[1].kwargs["attributes"]["page_index"] == 2
        assert page_span_calls[0].kwargs["attributes"]["remaining_budget_seconds"] > 0

    def test_span_remaining_budget_is_negative_one_when_no_deadline(self):
        # Given
        service = OcrService()
        engine = _engine_reading(*_create_mock_predict_result())

        # When
        with patch("src.service.ocr_service.tracer") as mock_tracer:
            service._predict_pages(engine, _pages(1), PROFILE, deadline=None)

        # Then
        _, kwargs = mock_tracer.start_as_current_span.call_args
        assert kwargs["attributes"]["remaining_budget_seconds"] == -1.0


class TestOcrServiceProcessFile:
    @pytest.fixture(autouse=True)
    def _render_one_page_per_result(self):
        self.page_count = 1
        with patch("src.service.ocr_service.render_pages") as mock_render:
            mock_render.side_effect = lambda _data, _profile: _pages(self.page_count)
            self.mock_render = mock_render
            yield

    @patch("src.service.ocr_service.PaddleOCR")
    def test_process_file_json_output(self, mock_paddle_class):
        # Given
        mock_paddle_class.return_value = _engine_reading(*_create_mock_predict_result())
        service = OcrService()

        # When
        result = service.process_file(b"fake_bytes", "test.png", "en", "high")

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
        self.page_count = 2
        mock_paddle_class.return_value = _engine_reading(*_create_multi_page_predict_result())
        service = OcrService()

        # When
        result = service.process_file(b"x", "test.pdf", "en", "high")

        # Then
        assert len(result.pages) == 2
        assert result.pages[0].page_number == 1
        assert result.pages[1].page_number == 2

    @patch("src.service.ocr_service.PaddleOCR")
    def test_process_file_empty_result(self, mock_paddle_class):
        # Given
        mock_paddle_class.return_value = _engine_reading({})
        service = OcrService()

        # When
        result = service.process_file(b"x", "empty.png", "en", "high")

        # Then
        assert len(result.pages) == 1
        assert result.pages[0].lines == []

    @pytest.mark.parametrize("quality", ["normal", "high"])
    @patch("src.service.ocr_service.PaddleOCR")
    def test_the_submitted_bytes_are_rendered_with_the_requested_modes_pair(self, mock_paddle_class, quality):
        # Given
        mock_paddle_class.return_value = _engine_reading({})
        service = OcrService()

        # When
        service.process_file(b"document-bytes", "doc.pdf", "en", quality)

        # Then
        self.mock_render.assert_called_once_with(b"document-bytes", settings.quality_profile(quality))
        _, kwargs = mock_paddle_class.return_value.predict_iter.call_args
        assert kwargs["text_det_limit_side_len"] == settings.quality_profile(quality).detector_max_side

    @pytest.mark.parametrize("straighten", [True, False])
    @patch("src.service.ocr_service.PaddleOCR")
    def test_the_requests_straighten_choice_reaches_the_engine_on_that_call(self, mock_paddle_class, straighten):
        # Given
        mock_paddle_class.return_value = _engine_reading({})
        service = OcrService()

        # When
        service.process_file(b"x", "photo.jpg", "en", "high", straighten=straighten)

        # Then
        kwargs = mock_paddle_class.return_value.predict_iter.call_args.kwargs
        assert kwargs["use_doc_unwarping"] is straighten

    @patch("src.service.ocr_service.PaddleOCR")
    def test_an_omitted_straighten_choice_leaves_the_page_unwarped(self, mock_paddle_class):
        # Given
        mock_paddle_class.return_value = _engine_reading({})
        service = OcrService()

        # When
        service.process_file(b"x", "scan.png", "en", "high")

        # Then
        assert mock_paddle_class.return_value.predict_iter.call_args.kwargs["use_doc_unwarping"] is False

    @patch("src.service.ocr_service.PaddleOCR")
    def test_nothing_is_written_to_disk(self, mock_paddle_class, tmp_path, monkeypatch):
        # Given: the engine reads rendered arrays, so no scratch copy of the upload exists
        monkeypatch.chdir(tmp_path)
        mock_paddle_class.return_value = _engine_reading({})
        service = OcrService()

        # When
        with patch("tempfile.NamedTemporaryFile") as mock_temp:
            service.process_file(b"x", "test.png", "en", "high")

        # Then
        mock_temp.assert_not_called()
        assert list(tmp_path.iterdir()) == []

    @patch("src.service.ocr_service.PaddleOCR")
    def test_process_file_raises_when_budget_exhausted_before_first_page(self, mock_paddle_class):
        # Given
        mock_paddle_class.return_value = _engine_reading(*_create_mock_predict_result())
        service = OcrService()

        # When / Then: a zero/negative budget must stop the request without inferring
        with pytest.raises(OcrDeadlineExceededError):
            service.process_file(b"x", "test.png", "en", "high", budget_seconds=-1.0)

    @patch("src.service.ocr_service.PaddleOCR")
    def test_process_file_deadline_computed_from_duration_not_absolute_time(self, mock_paddle_class):
        # Given - no absolute timestamp may cross the process boundary: the worker
        # must derive its deadline from its own time.monotonic() plus the duration.
        mock_paddle_class.return_value = _engine_reading(*_create_mock_predict_result())
        service = OcrService()

        # When
        with patch("src.service.ocr_service.time.monotonic", return_value=1_000_000.0) as mock_monotonic:
            service.process_file(b"x", "test.png", "en", "high", budget_seconds=30.0)

        # Then - every deadline check is relative to this process's own clock
        mock_monotonic.assert_called()

    @patch("src.service.ocr_service.PaddleOCR")
    def test_process_file_no_budget_means_no_deadline(self, mock_paddle_class):
        # Given
        mock_paddle_class.return_value = _engine_reading(*_create_mock_predict_result())
        service = OcrService()

        # When / Then: budget_seconds omitted entirely, must not raise
        result = service.process_file(b"x", "test.png", "en", "high")
        assert isinstance(result, OcrJsonResponse)


class TestOcrServiceReadsRealDocuments:
    @patch("src.service.ocr_service.PaddleOCR")
    def test_a_pdf_page_reaches_the_engine_rendered_at_the_modes_resolution(self, mock_paddle_class, monkeypatch):
        # Given: a 100 x 50 pt page, and a 144 dpi mode, which is a scale of exactly 2
        monkeypatch.setattr(settings, "OCR_QUALITY_NORMAL", QualityProfile(render_dpi=144, detector_max_side=1024))
        engine = _engine_reading({})
        mock_paddle_class.return_value = engine
        service = OcrService()

        # When
        service.process_file(_make_pdf((100, 50)), "doc.pdf", "en", "normal")

        # Then
        page_image = engine.predict_iter.call_args.args[0]
        assert page_image.shape == (100, 200, 3)

    @patch("src.service.ocr_service.PaddleOCR")
    def test_an_image_reaches_the_engine_as_its_own_pixels(self, mock_paddle_class):
        # Given
        engine = _engine_reading({})
        mock_paddle_class.return_value = engine
        service = OcrService()

        # When
        service.process_file(_make_png(width=30, height=20), "scan.png", "en", "high")

        # Then
        page_image = engine.predict_iter.call_args.args[0]
        assert page_image.shape == (20, 30, 3)


class TestOcrServiceProcessFileTraceContext:
    @pytest.fixture(autouse=True)
    def _render_one_page(self):
        with patch("src.service.ocr_service.render_pages", side_effect=lambda _data, _profile: _pages(1)):
            yield

    @patch("src.service.ocr_service.PaddleOCR")
    def test_no_trace_carrier_starts_span_with_no_parent(self, mock_paddle_class):
        # Given
        mock_paddle_class.return_value = _engine_reading(*_create_mock_predict_result())
        service = OcrService()

        # When
        with patch.object(ocr_service_module, "tracer") as mock_tracer:
            service.process_file(b"x", "test.png", "en", "high")

        # Then. [0] is the outer ascend-ocr.engine.predict span (the one that carries
        # the parent context); later calls are the per-page child spans.
        _, kwargs = mock_tracer.start_as_current_span.call_args_list[0]
        assert kwargs["context"] is None

    @patch("src.service.ocr_service.extract_trace_context")
    @patch("src.service.ocr_service.PaddleOCR")
    def test_trace_carrier_is_extracted_into_parent_context(self, mock_paddle_class, mock_extract):
        # Given - trace_carrier simulates a context injected by the process that
        # submitted this call, since process_file runs inside a separate OCR worker
        mock_paddle_class.return_value = _engine_reading(*_create_mock_predict_result())
        sentinel_context = object()
        mock_extract.return_value = sentinel_context
        service = OcrService()
        carrier = {"traceparent": "00-fake-01"}

        # When
        with patch.object(ocr_service_module, "tracer") as mock_tracer:
            service.process_file(b"x", "test.png", "en", "high", carrier)

        # Then
        mock_extract.assert_called_once_with(carrier)
        _, kwargs = mock_tracer.start_as_current_span.call_args_list[0]
        assert kwargs["context"] is sentinel_context

    @patch("src.service.ocr_service.PaddleOCR")
    def test_the_predict_span_names_the_quality_mode(self, mock_paddle_class):
        # Given
        mock_paddle_class.return_value = _engine_reading({})
        service = OcrService()

        # When
        with patch.object(ocr_service_module, "tracer") as mock_tracer:
            service.process_file(b"x", "test.png", "en", "normal")

        # Then
        _, kwargs = mock_tracer.start_as_current_span.call_args_list[0]
        assert kwargs["attributes"] == {"language": "en", "quality": "normal", "straighten": False}


class TestOcrServiceWarmUp:
    @patch("src.service.ocr_service.PaddleOCR")
    def test_warm_up_creates_engine(self, mock_paddle_class):
        # Given
        mock_paddle_class.return_value = MagicMock()
        service = OcrService()

        # When
        service.warm_up_engine("en")

        # Then
        assert _default_pair() in service._engines

    @patch("src.service.ocr_service.PaddleOCR")
    def test_warm_up_reads_one_generated_page_so_the_first_job_pays_no_first_inference(self, mock_paddle_class):
        # Given
        engine = _engine_reading({})
        mock_paddle_class.return_value = engine
        service = OcrService()

        # When
        service.warm_up_engine("en")

        # Then
        engine.predict_iter.assert_called_once()
        page_image = engine.predict_iter.call_args.args[0]
        assert page_image.ndim == 3
        assert page_image.shape[2] == 3
        assert page_image.min() < page_image.max()
        assert engine.predict_iter.call_args.kwargs["use_doc_unwarping"] is False

    @patch("src.service.ocr_service.PaddleOCR")
    def test_a_failed_warm_up_read_fails_the_warm_up(self, mock_paddle_class):
        # Given: the build already fails the pool's initializer, so the first read must not be quieter
        engine = MagicMock()
        engine.predict_iter.side_effect = RuntimeError("inference failed")
        mock_paddle_class.return_value = engine
        service = OcrService()

        # When / Then
        with pytest.raises(RuntimeError, match="inference failed"):
            service.warm_up_engine("en")


class TestEngineConstruction:
    @patch("src.service.ocr_service.PaddleOCR")
    def test_every_engine_a_supported_language_can_load_is_built_once(self, mock_paddle_class):
        # When
        preload_models()

        # Then
        built = [
            ModelPair(call.kwargs["text_detection_model_name"], call.kwargs["text_recognition_model_name"])
            for call in mock_paddle_class.call_args_list
        ]
        assert sorted(built, key=str) == sorted(settings.reachable_model_pairs(), key=str)

    @patch("src.service.ocr_service.PaddleOCR")
    def test_the_shipped_languages_preload_only_the_small_pair(self, mock_paddle_class):
        # When
        preload_models()

        # Then: no PP-OCRv5 server detector or korean or eslav recogniser reaches the image
        built = [
            ModelPair(call.kwargs["text_detection_model_name"], call.kwargs["text_recognition_model_name"])
            for call in mock_paddle_class.call_args_list
        ]
        assert built == [ModelPair("PP-OCRv6_small_det", "PP-OCRv6_small_rec")]

    @patch("src.service.ocr_service.PaddleOCR")
    def test_the_preload_builds_engines_exactly_as_the_service_does(self, mock_paddle_class):
        # Given
        OcrService()._get_engine("en")
        service_kwargs = mock_paddle_class.call_args.kwargs
        mock_paddle_class.reset_mock()

        # When
        preload_models()

        # Then
        default_call = next(
            call
            for call in mock_paddle_class.call_args_list
            if call.kwargs["text_detection_model_name"] == settings.OCR_TEXT_DETECTION_MODEL
        )
        assert default_call.kwargs == service_kwargs

    @patch("src.service.ocr_service.detect_cpu_limit", return_value=3)
    @patch("src.service.ocr_service.PaddleOCR")
    def test_an_engine_runs_as_many_cpu_threads_as_the_container_may_use(self, mock_paddle_class, _limit):
        # When
        build_engine(_default_pair())

        # Then: passed explicitly, because PaddleOCR otherwise passes its own 10 and the env var never applies
        assert mock_paddle_class.call_args.kwargs["cpu_threads"] == 3


class TestConvertPolygon:
    def test_valid_polygon(self):
        # Given
        polygon = [(1, 2), (3, 4)]

        # When
        converted = _convert_polygon(polygon)

        # Then
        assert converted == [[1.0, 2.0], [3.0, 4.0]]

    def test_none_returns_empty(self):
        # When / Then
        assert _convert_polygon(None) == []

    def test_empty_returns_empty(self):
        # When / Then
        assert _convert_polygon([]) == []

    def test_index_error_returns_empty(self):
        # When / Then - point with no elements triggers IndexError
        assert _convert_polygon([[]]) == []

    def test_value_error_returns_empty(self):
        # When / Then - non-numeric coordinates trigger ValueError on float()
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
                raise ValueError("The truth value of an array with more than one element is ambiguous")

            def __len__(self) -> int:
                return len(self._points)

            def __iter__(self):
                return iter(self._points)

        polygon = _FakeArray([(1.0, 2.0), (3.0, 4.0), (5.0, 6.0), (7.0, 8.0)])

        # When
        result = _convert_polygon(polygon)

        # Then
        assert result == [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0], [7.0, 8.0]]


class TestWorkerPoolLifecycle:
    @patch("src.service.ocr_service.multiprocessing")
    @patch("src.service.ocr_service.ProcessPoolExecutor")
    def test_start_worker_pool_creates_and_warms_pool(self, mock_executor_class, mock_multiprocessing):
        # Given
        mock_pool = MagicMock()
        mock_executor_class.return_value = mock_pool
        mock_context = MagicMock()
        mock_multiprocessing.get_context.return_value = mock_context

        # When
        with patch.object(ocr_service_module, "_process_pool", None):
            warmed = start_worker_pool()

            # Then
            assert warmed is True
            mock_multiprocessing.get_context.assert_called_once_with("spawn")
            mock_executor_class.assert_called_once_with(
                max_workers=settings.OCR_WORKER_COUNT,
                mp_context=mock_context,
                initializer=_warm_worker_engine,
                initargs=(settings.DEFAULT_LANGUAGE,),
            )
            mock_pool.submit.assert_called_once_with(_noop_task)
            mock_pool.submit.return_value.result.assert_called_once()
            assert ocr_service_module._process_pool is mock_pool

    @patch("src.service.ocr_service.multiprocessing")
    @patch("src.service.ocr_service.ProcessPoolExecutor")
    def test_start_worker_pool_increments_generation(self, mock_executor_class, mock_multiprocessing):
        # Given
        mock_executor_class.return_value = MagicMock()
        mock_multiprocessing.get_context.return_value = MagicMock()

        # When
        with patch.object(ocr_service_module, "_pool_generation", 5):
            start_worker_pool()

            # Then
            assert get_pool_generation() == 6

    @patch("src.service.ocr_service.multiprocessing")
    @patch("src.service.ocr_service.ProcessPoolExecutor")
    def test_start_worker_pool_resets_gate(self, mock_executor_class, mock_multiprocessing):
        # Given
        mock_executor_class.return_value = MagicMock()
        mock_multiprocessing.get_context.return_value = MagicMock()

        # When
        with patch.object(settings, "OCR_WORKER_COUNT", 2):
            start_worker_pool()

            # Then - gate permits and pool size come from the same setting
            assert ocr_service_module._admission_semaphore._value == 2

    @patch("src.service.ocr_service.multiprocessing")
    @patch("src.service.ocr_service.ProcessPoolExecutor")
    def test_start_worker_pool_survives_broken_initializer(self, mock_executor_class, mock_multiprocessing):
        # Given. A warm-up failure inside _warm_worker_engine (the pool initializer)
        # surfaces here as BrokenProcessPool when the blocking .result() call is
        # awaited, not as the original exception.
        mock_pool = MagicMock()
        mock_pool.submit.return_value.result.side_effect = BrokenProcessPool("initializer failed")
        mock_executor_class.return_value = mock_pool
        mock_multiprocessing.get_context.return_value = MagicMock()

        # When / Then - must not propagate: a startup exception here would kill the
        # FastAPI lifespan and crash the container instead of leaving /ready to report
        # not-ready.
        with patch.object(ocr_service_module, "_process_pool", None):
            warmed = start_worker_pool()

            assert warmed is False
            assert ocr_service_module._process_pool is mock_pool

    @patch("src.service.ocr_service.multiprocessing")
    @patch("src.service.ocr_service.ProcessPoolExecutor")
    def test_start_worker_pool_warms_every_configured_worker(self, mock_executor_class, mock_multiprocessing):
        # Given - ProcessPoolExecutor only spawns one worker per submit() call when no
        # worker is idle yet, so warming all OCR_WORKER_COUNT workers at startup
        # requires one submission per worker, not one submission total.
        mock_pool = MagicMock()
        mock_executor_class.return_value = mock_pool
        mock_multiprocessing.get_context.return_value = MagicMock()

        # When
        with (
            patch.object(ocr_service_module, "_process_pool", None),
            patch.object(settings, "OCR_WORKER_COUNT", 3),
        ):
            warmed = start_worker_pool()

        # Then
        assert warmed is True
        assert mock_pool.submit.call_count == 3
        mock_pool.submit.assert_called_with(_noop_task)
        assert mock_pool.submit.return_value.result.call_count == 3

    @patch("src.service.ocr_service.multiprocessing")
    @patch("src.service.ocr_service.ProcessPoolExecutor")
    def test_start_worker_pool_one_broken_worker_among_several_fails_the_whole_pool(
        self, mock_executor_class, mock_multiprocessing
    ):
        # Given - three workers requested, the second one's own warm-up is broken.
        # ProcessPoolExecutor has no per-worker recovery: any worker's initializer
        # failure marks the whole pool broken, so start_worker_pool must report False
        # rather than silently accepting two of the three.
        healthy_future = MagicMock()
        broken_future = MagicMock()
        broken_future.result.side_effect = BrokenProcessPool("initializer failed")
        mock_pool = MagicMock()
        mock_pool.submit.side_effect = [healthy_future, broken_future, healthy_future]
        mock_executor_class.return_value = mock_pool
        mock_multiprocessing.get_context.return_value = MagicMock()

        # When
        with (
            patch.object(ocr_service_module, "_process_pool", None),
            patch.object(settings, "OCR_WORKER_COUNT", 3),
        ):
            warmed = start_worker_pool()

        # Then
        assert warmed is False
        assert mock_pool.submit.call_count == 3

    def test_stop_worker_pool_shuts_down_existing_pool(self):
        # Given
        mock_pool = MagicMock()

        # When
        with patch.object(ocr_service_module, "_process_pool", mock_pool):
            stop_worker_pool()

            # Then
            mock_pool.shutdown.assert_called_once_with(wait=True)
            assert ocr_service_module._process_pool is None

    def test_stop_worker_pool_no_op_when_not_started(self):
        # When / Then - no raise, nothing to shut down
        with patch.object(ocr_service_module, "_process_pool", None):
            stop_worker_pool()
            assert ocr_service_module._process_pool is None

    def test_get_process_pool_raises_when_not_started(self):
        # When / Then
        with (
            patch.object(ocr_service_module, "_process_pool", None),
            pytest.raises(RuntimeError, match="not initialised"),
        ):
            get_process_pool()

    def test_get_process_pool_returns_started_pool(self):
        # Given
        mock_pool = MagicMock()

        # When / Then
        with patch.object(ocr_service_module, "_process_pool", mock_pool):
            assert get_process_pool() is mock_pool

    @patch("src.service.ocr_service.ocr_service")
    def test_run_ocr_in_worker_delegates_to_singleton(self, mock_service):
        # Given
        mock_service.process_file.return_value = "sentinel-response"
        carrier = {"traceparent": "00-fake-01"}

        # When
        result = run_ocr_in_worker(b"bytes", "scan.png", "en", "normal", carrier, 30.0)

        # Then
        mock_service.process_file.assert_called_once_with(
            b"bytes", "scan.png", "en", "normal", carrier, 30.0, None, False
        )
        assert result == "sentinel-response"

    @patch("src.service.ocr_service.ocr_service")
    def test_run_ocr_in_worker_carries_the_straighten_choice(self, mock_service):
        # When
        run_ocr_in_worker(b"bytes", "photo.jpg", "en", "high", None, 30.0, "job", True)

        # Then
        assert mock_service.process_file.call_args.args[-1] is True

    @patch("src.service.ocr_service.ocr_service")
    def test_run_ocr_in_worker_defaults_to_none(self, mock_service):
        # Given
        mock_service.process_file.return_value = "sentinel-response"

        # When
        run_ocr_in_worker(b"bytes", "scan.png", "en", "high")

        # Then
        mock_service.process_file.assert_called_once_with(b"bytes", "scan.png", "en", "high", None, None, None, False)

    @patch("src.service.ocr_service.configure_worker_tracing")
    @patch("src.service.ocr_service.ocr_service")
    def test_warm_worker_engine_configures_tracing_before_warmup(self, mock_service, mock_configure_tracing):
        # When
        _warm_worker_engine("en")

        # Then - tracing must be wired up before the warmup span is created
        mock_configure_tracing.assert_called_once()
        mock_service.warm_up_engine.assert_called_once_with("en")

    def test_noop_task_completes_without_raising(self):
        # When / Then
        _noop_task()


class TestPoolHealthSignals:
    def test_is_pool_usable_true_under_cap(self, monkeypatch):
        # Given
        monkeypatch.setattr(ocr_service_module, "_consecutive_rebuild_failures", 0)

        # When / Then
        assert is_pool_usable() is True

    def test_is_pool_usable_false_at_cap(self, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OCR_POOL_REBUILD_MAX_CONSECUTIVE", 3)
        monkeypatch.setattr(ocr_service_module, "_consecutive_rebuild_failures", 3)

        # When / Then
        assert is_pool_usable() is False

    def test_is_rebuild_in_progress_false_by_default(self):
        # When / Then
        assert is_rebuild_in_progress() is False

    async def test_is_rebuild_in_progress_true_while_locked(self):
        # Given
        async with ocr_service_module._rebuild_lock:
            # When / Then
            assert is_rebuild_in_progress() is True

        assert is_rebuild_in_progress() is False

    def test_is_job_overrunning_false_when_idle(self, monkeypatch):
        # Given
        monkeypatch.setattr(ocr_service_module, "_active_deadlines", {})

        # When / Then
        assert is_job_overrunning() is False

    def test_is_job_overrunning_false_within_budget(self, monkeypatch):
        # Given
        monkeypatch.setattr(ocr_service_module, "_active_deadlines", {object(): time.monotonic() + 100})

        # When / Then
        assert is_job_overrunning() is False

    def test_is_job_overrunning_true_past_budget(self, monkeypatch):
        # Given
        monkeypatch.setattr(ocr_service_module, "_active_deadlines", {object(): time.monotonic() - 1})

        # When / Then
        assert is_job_overrunning() is True

    def test_is_job_overrunning_true_when_one_of_several_jobs_is_past_budget(self, monkeypatch):
        # Given - two workers, one healthy and well within budget, one genuinely stuck.
        # A single shared deadline variable could only ever record the more recent of
        # the two, so this is the regression case for that bug.
        monkeypatch.setattr(
            ocr_service_module,
            "_active_deadlines",
            {object(): time.monotonic() + 100, object(): time.monotonic() - 1},
        )

        # When / Then
        assert is_job_overrunning() is True

    def test_is_accepting_work_true_when_healthy_and_idle(self, monkeypatch):
        # Given
        monkeypatch.setattr(ocr_service_module, "_consecutive_rebuild_failures", 0)
        monkeypatch.setattr(ocr_service_module, "_active_deadlines", {})

        # When / Then
        assert is_accepting_work() is True

    def test_is_accepting_work_false_when_pool_exhausted(self, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OCR_POOL_REBUILD_MAX_CONSECUTIVE", 1)
        monkeypatch.setattr(ocr_service_module, "_consecutive_rebuild_failures", 1)

        # When / Then
        assert is_accepting_work() is False

    def test_is_accepting_work_false_while_job_overrunning(self, monkeypatch):
        # Given
        monkeypatch.setattr(ocr_service_module, "_consecutive_rebuild_failures", 0)
        monkeypatch.setattr(ocr_service_module, "_active_deadlines", {object(): time.monotonic() - 1})

        # When / Then
        assert is_accepting_work() is False

    async def test_is_accepting_work_false_while_rebuilding(self, monkeypatch):
        # Given
        monkeypatch.setattr(ocr_service_module, "_consecutive_rebuild_failures", 0)
        monkeypatch.setattr(ocr_service_module, "_active_deadlines", {})

        # When / Then
        async with ocr_service_module._rebuild_lock:
            assert is_accepting_work() is False


class TestRebuildPool:
    async def test_generation_mismatch_skips_rebuild(self, monkeypatch):
        # Given - another caller already rebuilt past the generation this caller saw
        monkeypatch.setattr(ocr_service_module, "_pool_generation", 5)
        stop_mock = MagicMock()
        monkeypatch.setattr(ocr_service_module, "stop_worker_pool", stop_mock)

        # When
        await ocr_service_module._rebuild_pool(observed_generation=4, reason="reclaim")

        # Then
        stop_mock.assert_not_called()

    async def test_cap_already_reached_skips_rebuild(self, monkeypatch):
        # Given
        monkeypatch.setattr(ocr_service_module, "_pool_generation", 1)
        monkeypatch.setattr(settings, "OCR_POOL_REBUILD_MAX_CONSECUTIVE", 1)
        monkeypatch.setattr(ocr_service_module, "_consecutive_rebuild_failures", 1)
        stop_mock = MagicMock()
        monkeypatch.setattr(ocr_service_module, "stop_worker_pool", stop_mock)

        # When
        await ocr_service_module._rebuild_pool(observed_generation=1, reason="broken")

        # Then
        stop_mock.assert_not_called()

    async def test_successful_rebuild_increments_ok_metric(self, monkeypatch):
        # Given
        monkeypatch.setattr(ocr_service_module, "_pool_generation", 1)
        monkeypatch.setattr(ocr_service_module, "_consecutive_rebuild_failures", 0)
        monkeypatch.setattr(ocr_service_module, "stop_worker_pool", MagicMock())
        monkeypatch.setattr(ocr_service_module, "start_worker_pool", MagicMock(return_value=True))

        # When
        await ocr_service_module._rebuild_pool(observed_generation=1, reason="reclaim")

        # Then
        assert ocr_service_module._consecutive_rebuild_failures == 0

    async def test_failed_rebuild_increments_failure_counter(self, monkeypatch):
        # Given
        monkeypatch.setattr(ocr_service_module, "_pool_generation", 1)
        monkeypatch.setattr(ocr_service_module, "_consecutive_rebuild_failures", 0)
        monkeypatch.setattr(ocr_service_module, "stop_worker_pool", MagicMock())
        monkeypatch.setattr(ocr_service_module, "start_worker_pool", MagicMock(return_value=False))

        # When
        await ocr_service_module._rebuild_pool(observed_generation=1, reason="broken")

        # Then
        assert ocr_service_module._consecutive_rebuild_failures == 1

    async def test_stop_worker_pool_does_not_block_the_event_loop(self, monkeypatch):
        # Given - stop_worker_pool blocks its own thread for a while, mirroring
        # ProcessPoolExecutor.shutdown(wait=True) waiting on another worker's own
        # legitimate, unrelated in-flight job to finish (proven against the real
        # stdlib: a two-worker pool with one fast and one 8s-sleeping job took 7.94s
        # to shut down, not the fast job's own time). A version of _rebuild_pool that
        # called stop_worker_pool directly, without offloading it, would freeze this
        # coroutine's own event loop thread for that whole span.
        monkeypatch.setattr(ocr_service_module, "_pool_generation", 1)
        monkeypatch.setattr(ocr_service_module, "_consecutive_rebuild_failures", 0)

        def blocking_stop(terminate: bool = False) -> None:
            _ = terminate
            time.sleep(0.3)

        monkeypatch.setattr(ocr_service_module, "stop_worker_pool", blocking_stop)
        monkeypatch.setattr(ocr_service_module, "start_worker_pool", MagicMock(return_value=True))

        ticks: list[float] = []

        async def heartbeat() -> None:
            for _ in range(6):
                ticks.append(time.monotonic())
                await asyncio.sleep(0.05)

        # When - the rebuild and an unrelated coroutine run concurrently
        await asyncio.gather(
            ocr_service_module._rebuild_pool(observed_generation=1, reason="reclaim"),
            heartbeat(),
        )

        # Then - the heartbeat kept ticking roughly every 0.05s throughout, rather than
        # being frozen for the ~0.3s stop_worker_pool spent blocking its own thread.
        gaps = [b - a for a, b in itertools.pairwise(ticks)]
        assert max(gaps) < 0.2

    async def test_concurrent_triggers_produce_one_rebuild(self, monkeypatch):
        # Given
        monkeypatch.setattr(ocr_service_module, "_pool_generation", 1)
        monkeypatch.setattr(ocr_service_module, "_consecutive_rebuild_failures", 0)

        def fake_start() -> bool:
            # Mirrors the real start_worker_pool(), which bumps the generation on every
            # (re)build - the second concurrent caller must see this bump and bail out.
            ocr_service_module._pool_generation += 1

            return True

        start_mock = MagicMock(side_effect=fake_start)

        async def fake_run_in_executor(_executor, func):
            return func()

        monkeypatch.setattr(ocr_service_module, "stop_worker_pool", MagicMock())
        monkeypatch.setattr(ocr_service_module, "start_worker_pool", start_mock)

        # When - two concurrent callers both observed the same broken generation
        await asyncio.gather(
            ocr_service_module._rebuild_pool(observed_generation=1, reason="reclaim"),
            ocr_service_module._rebuild_pool(observed_generation=1, reason="reclaim"),
        )

        # Then - only the first actually rebuilds; the second sees the bumped generation
        assert start_mock.call_count == 1

    async def test_successful_request_resets_failure_counter(self, monkeypatch):
        # Given
        monkeypatch.setattr(ocr_service_module, "_consecutive_rebuild_failures", 2)

        # When
        ocr_service_module._reset_rebuild_failures()

        # Then
        assert ocr_service_module._consecutive_rebuild_failures == 0


class TestDispatchOcrRequest:
    @pytest.fixture(autouse=True)
    def _reset_state(self, monkeypatch):
        monkeypatch.setattr(ocr_service_module, "_active_deadlines", {})
        monkeypatch.setattr(ocr_service_module, "_consecutive_rebuild_failures", 0)
        monkeypatch.setattr(ocr_service_module, "_admission_semaphore", asyncio.Semaphore(1))
        monkeypatch.setattr(ocr_service_module, "_pool_generation", 1)
        yield

    async def test_pool_unusable_refuses_immediately(self, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OCR_POOL_REBUILD_MAX_CONSECUTIVE", 1)
        monkeypatch.setattr(ocr_service_module, "_consecutive_rebuild_failures", 1)

        # When / Then
        with pytest.raises(OcrProcessingError, match="unavailable"):
            await dispatch_ocr_request(b"x", "f.png", "en", "high", 30.0, "rest")

    async def test_successful_dispatch_returns_result(self, monkeypatch):
        # Given
        sentinel = OcrJsonResponse(filename="f.png", language="en", pages=[], processing_time_seconds=0.1)
        mock_pool = MagicMock()
        monkeypatch.setattr(ocr_service_module, "get_process_pool", MagicMock(return_value=mock_pool))

        async def fake_run_in_executor(_executor, _func, *_args):
            return sentinel

        with patch("asyncio.get_running_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_loop.run_in_executor = fake_run_in_executor
            mock_get_loop.return_value = mock_loop

            # When
            result = await dispatch_ocr_request(b"x", "f.png", "en", "high", 30.0, "rest")

        # Then
        assert result is sentinel
        # Then - permit released back to its starting value
        assert ocr_service_module._admission_semaphore._value == 1

    @patch("src.service.ocr_service.multiprocessing")
    @patch("src.service.ocr_service.ProcessPoolExecutor")
    async def test_a_dispatch_across_a_pool_rebuild_releases_the_gate_it_acquired(
        self, mock_executor_class, mock_multiprocessing, monkeypatch
    ):
        # Given: the pool is rebuilt while this document is being read, which replaces the gate
        mock_executor_class.return_value = MagicMock()
        mock_multiprocessing.get_context.return_value = MagicMock()
        monkeypatch.setattr(ocr_service_module, "_process_pool", None)
        monkeypatch.setattr(ocr_service_module, "get_process_pool", MagicMock(return_value=MagicMock()))
        acquired_gate = ocr_service_module._admission_semaphore
        sentinel = OcrJsonResponse(filename="f.png", language="en", pages=[], processing_time_seconds=0.1)

        async def rebuilding_run_in_executor(_executor, _func, *_args):
            start_worker_pool()

            return sentinel

        with patch("asyncio.get_running_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_loop.run_in_executor = rebuilding_run_in_executor
            mock_get_loop.return_value = mock_loop

            # When
            await dispatch_ocr_request(b"x", "f.png", "en", "high", 30.0, "rest")

        # Then: the permit went back to the gate it came from, and the new gate holds exactly its own permits
        rebuilt_gate = ocr_service_module._admission_semaphore
        assert rebuilt_gate is not acquired_gate
        assert acquired_gate._value == 1
        assert rebuilt_gate._value == settings.OCR_WORKER_COUNT

    @pytest.mark.parametrize("straighten", [True, False])
    async def test_the_straighten_choice_reaches_the_worker(self, monkeypatch, straighten):
        # Given
        sentinel = OcrJsonResponse(filename="f.jpg", language="en", pages=[], processing_time_seconds=0.1)
        monkeypatch.setattr(ocr_service_module, "get_process_pool", MagicMock(return_value=MagicMock()))
        worker_args: list[tuple[object, ...]] = []

        async def fake_run_in_executor(_executor, _func, *args):
            worker_args.append(args)

            return sentinel

        with patch("asyncio.get_running_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_loop.run_in_executor = fake_run_in_executor
            mock_get_loop.return_value = mock_loop

            # When
            await dispatch_ocr_request(b"x", "f.jpg", "en", "high", 30.0, "rest", straighten=straighten)

        # Then
        assert worker_args[0][-1] is straighten

    async def test_budget_expired_while_waiting_never_dispatches(self, monkeypatch):
        # Given - permit already held by someone else, and the budget is effectively zero
        held_semaphore = asyncio.Semaphore(0)
        monkeypatch.setattr(ocr_service_module, "_admission_semaphore", held_semaphore)
        pool_mock = MagicMock()
        monkeypatch.setattr(ocr_service_module, "get_process_pool", MagicMock(return_value=pool_mock))

        # When / Then
        with pytest.raises(OcrProcessingError, match="waiting for a worker"):
            await dispatch_ocr_request(b"x", "f.png", "en", "high", 0.01, "rest")

        pool_mock.submit.assert_not_called()

    async def test_budget_expired_between_acquire_and_dispatch_never_dispatches(self, monkeypatch):
        # Given - the gate grants the permit right away, but by the time dispatch
        # re-checks the budget afterward, the clock has moved past it. wait_for is
        # replaced with a direct await so only dispatch_ocr_request's own three explicit
        # time.monotonic() calls are in play, none of asyncio's own timer bookkeeping.
        pool_mock = MagicMock()
        monkeypatch.setattr(ocr_service_module, "get_process_pool", MagicMock(return_value=pool_mock))
        monotonic_values = iter([0.0, 0.0, 1.0])

        async def fake_wait_for(coro, **_kwargs):
            return await coro

        # When / Then
        with (
            patch("src.service.ocr_service.time.monotonic", side_effect=lambda: next(monotonic_values)),
            patch("src.service.ocr_service.asyncio.wait_for", fake_wait_for),
            pytest.raises(OcrProcessingError, match="before dispatch"),
        ):
            await dispatch_ocr_request(b"x", "f.png", "en", "high", 0.5, "rest")

        pool_mock.submit.assert_not_called()

    async def test_worker_timeout_triggers_rebuild_and_fails_request(self, monkeypatch):
        # Given. The reclamation grace is derived (the reading engine's page allowance
        # plus the dispatch margin), so it is driven through its real settings.
        monkeypatch.setattr(ocr_service_module, "_rebuild_pool", lambda *a, **k: _async_none())
        monkeypatch.setattr(ocr_service_module, "get_process_pool", MagicMock(return_value=MagicMock()))

        async def fake_run_in_executor(_executor, _func, *_args):
            await asyncio.sleep(10)

        with patch("asyncio.get_running_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_loop.run_in_executor = fake_run_in_executor
            mock_get_loop.return_value = mock_loop

            # When / Then
            with (
                patch.object(ocr_service_module.settings, "OCR_DISPATCH_MARGIN_SECONDS", 0.0),
                patch.object(ocr_service_module.settings, "OCR_PAGE_ALLOWANCE_HEADROOM", 0.0001),
                pytest.raises(OcrProcessingError, match="reclamation grace"),
            ):
                await dispatch_ocr_request(b"x", "f.png", "en", "high", 0.05, "rest")

    @pytest.mark.usefixtures("off_family_language")
    @pytest.mark.parametrize("language", ["en", "ru"])
    async def test_the_reclamation_grace_is_the_reading_engine_s_own(self, monkeypatch, language):
        # Given: the server detector an opted-in ru loads is allowed far longer per page than the small one
        monkeypatch.setattr(ocr_service_module, "get_process_pool", MagicMock(return_value=MagicMock()))
        sentinel = OcrJsonResponse(filename="f.png", language=language, pages=[], processing_time_seconds=0.1)
        timeouts: list[float] = []
        real_wait_for = asyncio.wait_for

        async def recording_wait_for(awaitable, **kwargs):
            timeouts.append(kwargs["timeout"])

            return await real_wait_for(awaitable, **kwargs)

        async def fake_run_in_executor(_executor, _func, *_args):
            return sentinel

        # When
        with patch("asyncio.get_running_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_loop.run_in_executor = fake_run_in_executor
            mock_get_loop.return_value = mock_loop

            with patch.object(ocr_service_module.asyncio, "wait_for", recording_wait_for):
                await dispatch_ocr_request(b"x", "f.png", language, "high", 30.0, "rest")

        # Then
        grace = settings.reclamation_grace_seconds(settings.model_pair(language))
        assert timeouts[-1] == pytest.approx(30.0 + grace, abs=0.5)

    async def test_broken_pool_triggers_rebuild_and_fails_request(self, monkeypatch):
        # Given
        monkeypatch.setattr(ocr_service_module, "_rebuild_pool", lambda *a, **k: _async_none())
        monkeypatch.setattr(ocr_service_module, "get_process_pool", MagicMock(return_value=MagicMock()))

        async def fake_run_in_executor(_executor, _func, *_args):
            raise BrokenProcessPool("dead worker")

        with patch("asyncio.get_running_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_loop.run_in_executor = fake_run_in_executor
            mock_get_loop.return_value = mock_loop

            # When / Then
            with pytest.raises(OcrProcessingError, match="worker process failed"):
                await dispatch_ocr_request(b"x", "f.png", "en", "high", 30.0, "rest")

    async def test_pool_already_broken_at_submission_triggers_rebuild_and_fails_request(self, monkeypatch):
        # Given - a worker killed between requests (e.g. by the OS, out-of-band) leaves
        # the pool broken before this request ever calls run_in_executor. concurrent.
        # futures' own executor.submit() raises BrokenProcessPool synchronously in that
        # case, inside run_in_executor's own body, before it ever returns a future -
        # not through the awaited future the way a mid-request kill does. A version of
        # this code that only wrapped `await future` in the except clause let this case
        # escape as an unhandled 500 instead of the rebuild-and-retry path (found live,
        # against the module's own venv, verifying task 8.8).
        monkeypatch.setattr(ocr_service_module, "_rebuild_pool", lambda *a, **k: _async_none())
        monkeypatch.setattr(ocr_service_module, "get_process_pool", MagicMock(return_value=MagicMock()))

        def synchronously_broken_run_in_executor(_executor, _func, *_args):
            raise BrokenProcessPool("pool already broken")

        with patch("asyncio.get_running_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_loop.run_in_executor = synchronously_broken_run_in_executor
            mock_get_loop.return_value = mock_loop

            # When / Then
            with pytest.raises(OcrProcessingError, match="worker process failed"):
                await dispatch_ocr_request(b"x", "f.png", "en", "high", 30.0, "rest")

    async def test_pool_torn_down_mid_rebuild_fails_cleanly(self, monkeypatch):
        # Given - a request that clears admission while a concurrent background
        # rebuild (now offloaded off the event loop, see TestRebuildPool) has already
        # torn the old pool down but not yet stood the replacement up.
        # get_process_pool() raises exactly this RuntimeError in that window.
        monkeypatch.setattr(
            ocr_service_module,
            "get_process_pool",
            MagicMock(side_effect=RuntimeError("OCR worker pool is not initialised")),
        )

        # When / Then - a clean, handled OcrProcessingError, not a raw RuntimeError escaping
        # the dispatch stack.
        with pytest.raises(OcrProcessingError):
            await dispatch_ocr_request(b"x", "f.png", "en", "high", 30.0, "rest")

        # And the permit is still released for the next request.
        assert ocr_service_module._admission_semaphore._value == 1

    async def test_concurrent_jobs_track_independent_overrun_deadlines(self, monkeypatch):
        # Given - two permits, two concurrent jobs with different budgets. The first
        # to finish must not erase the still-running second job's own deadline
        # tracking (the regression case for the single shared _active_deadline bug).
        monkeypatch.setattr(ocr_service_module, "_admission_semaphore", asyncio.Semaphore(2))
        monkeypatch.setattr(ocr_service_module, "get_process_pool", MagicMock(return_value=MagicMock()))
        release_slow = asyncio.Event()

        async def fake_run_in_executor(_executor, _func, *args):
            # run_ocr_in_worker's positional args carry the budget third from last, with
            # the job identifier and the straighten choice after it. Use the budget to
            # tell the fast call from the slow one.
            budget = args[-3]
            if budget < 1:
                return OcrJsonResponse(filename="fast", language="en", pages=[], processing_time_seconds=0.01)

            await release_slow.wait()

            return OcrJsonResponse(filename="slow", language="en", pages=[], processing_time_seconds=0.01)

        with patch("asyncio.get_running_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_loop.run_in_executor = fake_run_in_executor
            mock_get_loop.return_value = mock_loop

            fast_task = asyncio.create_task(dispatch_ocr_request(b"x", "fast.png", "en", "high", 0.5, "rest"))
            slow_task = asyncio.create_task(dispatch_ocr_request(b"x", "slow.png", "en", "high", 60.0, "rest"))
            await asyncio.sleep(0.05)

            # When - the fast job finishes and its own finally clears its own entry
            fast_result = await fast_task
            # Then - the still-running slow job's own deadline entry must survive
            assert len(ocr_service_module._active_deadlines) == 1

            release_slow.set()
            slow_result = await slow_task

        assert fast_result.filename == "fast"
        assert slow_result.filename == "slow"
        assert ocr_service_module._active_deadlines == {}

    async def test_worker_own_deadline_stop_fails_cleanly_without_rebuild(self, monkeypatch):
        # Given - the worker observed its own deadline between pages and returned on
        # its own (Decision 3's expected path), which must not trigger a replacement.
        rebuild_mock = AsyncMock()
        monkeypatch.setattr(ocr_service_module, "_rebuild_pool", rebuild_mock)
        monkeypatch.setattr(ocr_service_module, "get_process_pool", MagicMock(return_value=MagicMock()))

        async def fake_run_in_executor(_executor, _func, *_args):
            raise OcrDeadlineExceededError("Budget exhausted after 1 of the document's pages")

        with patch("asyncio.get_running_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_loop.run_in_executor = fake_run_in_executor
            mock_get_loop.return_value = mock_loop

            # When
            with pytest.raises(OcrProcessingError, match="budget exhausted during inference"):
                await dispatch_ocr_request(b"x", "f.png", "en", "high", 30.0, "rest")

        # Then
        rebuild_mock.assert_not_called()

    async def test_size_and_type_errors_pass_through_unwrapped(self, monkeypatch):
        # Given - the worker can in principle still raise these directly; they must
        # not be masked as a generic OCR failure.
        monkeypatch.setattr(ocr_service_module, "get_process_pool", MagicMock(return_value=MagicMock()))

        async def fake_run_in_executor(_executor, _func, *_args):
            raise FileSizeExceededError("too big")

        with patch("asyncio.get_running_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_loop.run_in_executor = fake_run_in_executor
            mock_get_loop.return_value = mock_loop

            # When / Then
            with pytest.raises(FileSizeExceededError):
                await dispatch_ocr_request(b"x", "f.png", "en", "high", 30.0, "rest")

    async def test_unsupported_type_error_passes_through_unwrapped(self, monkeypatch):
        # Given
        monkeypatch.setattr(ocr_service_module, "get_process_pool", MagicMock(return_value=MagicMock()))

        async def fake_run_in_executor(_executor, _func, *_args):
            raise UnsupportedFileTypeError("bad type")

        with patch("asyncio.get_running_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_loop.run_in_executor = fake_run_in_executor
            mock_get_loop.return_value = mock_loop

            # When / Then
            with pytest.raises(UnsupportedFileTypeError):
                await dispatch_ocr_request(b"x", "f.png", "en", "high", 30.0, "rest")

    async def test_generic_engine_failure_wrapped_as_ocr_processing_error(self, monkeypatch):
        # Given
        monkeypatch.setattr(ocr_service_module, "get_process_pool", MagicMock(return_value=MagicMock()))

        async def fake_run_in_executor(_executor, _func, *_args):
            raise RuntimeError("engine internal trace")

        with patch("asyncio.get_running_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_loop.run_in_executor = fake_run_in_executor
            mock_get_loop.return_value = mock_loop

            # When
            with pytest.raises(OcrProcessingError) as exc_info:
                await dispatch_ocr_request(b"x", "f.png", "en", "high", 30.0, "rest")

        # Then
        assert "engine internal trace" not in str(exc_info.value)

    async def test_successful_dispatch_resets_rebuild_failure_counter(self, monkeypatch):
        # Given
        monkeypatch.setattr(ocr_service_module, "_consecutive_rebuild_failures", 2)
        sentinel = OcrJsonResponse(filename="f.png", language="en", pages=[], processing_time_seconds=0.1)
        monkeypatch.setattr(ocr_service_module, "get_process_pool", MagicMock(return_value=MagicMock()))

        async def fake_run_in_executor(_executor, _func, *_args):
            return sentinel

        with patch("asyncio.get_running_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_loop.run_in_executor = fake_run_in_executor
            mock_get_loop.return_value = mock_loop

            # When
            await dispatch_ocr_request(b"x", "f.png", "en", "high", 30.0, "rest")

        # Then
        assert ocr_service_module._consecutive_rebuild_failures == 0

    async def test_permit_released_on_worker_failure(self, monkeypatch):
        # Given
        monkeypatch.setattr(ocr_service_module, "get_process_pool", MagicMock(return_value=MagicMock()))

        async def fake_run_in_executor(_executor, _func, *_args):
            raise RuntimeError("boom")

        with patch("asyncio.get_running_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_loop.run_in_executor = fake_run_in_executor
            mock_get_loop.return_value = mock_loop

            # When
            with pytest.raises(OcrProcessingError):
                await dispatch_ocr_request(b"x", "f.png", "en", "high", 30.0, "rest")

        # Then
        assert ocr_service_module._admission_semaphore._value == 1

    async def test_pool_never_receives_more_concurrent_work_than_worker_count(self, monkeypatch):
        # Given - the pool's own queue can only ever be empty if the admission gate
        # never lets more than OCR_WORKER_COUNT dispatches reach it at once.
        monkeypatch.setattr(ocr_service_module, "_admission_semaphore", asyncio.Semaphore(2))
        monkeypatch.setattr(ocr_service_module, "get_process_pool", MagicMock(return_value=MagicMock()))
        active = 0
        max_active = 0
        lock = asyncio.Lock()

        async def fake_run_in_executor(_executor, _func, *_args):
            nonlocal active, max_active
            async with lock:
                active += 1
                max_active = max(max_active, active)
            await asyncio.sleep(0.05)
            async with lock:
                active -= 1

            return OcrJsonResponse(filename="f.png", language="en", pages=[], processing_time_seconds=0.1)

        with patch("asyncio.get_running_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_loop.run_in_executor = fake_run_in_executor
            mock_get_loop.return_value = mock_loop

            # When - five requests arrive at once against a pool of two workers
            await asyncio.gather(*[dispatch_ocr_request(b"x", "f.png", "en", "high", 5.0, "rest") for _ in range(5)])

        # Then
        assert max_active <= 2


async def _async_none() -> None:
    return None


class TestWorkerProgress:
    def test_the_worker_records_each_page_as_it_finishes_it(self, jobs_dir, monkeypatch):
        # Given - a three page document being read for a known job
        _ = jobs_dir
        service = OcrService()
        engine = _engine_reading({}, {}, {})
        job_id = new_job_id()
        seen: list[int] = []
        monkeypatch.setattr(
            "src.service.ocr_service.write_progress",
            lambda recorded_id, pages: seen.append(pages) if recorded_id == job_id else None,
        )

        # When
        pages = service._predict_pages(engine, _pages(3), PROFILE, deadline=None, job_id=job_id)

        # Then - page by page, and never past the document's own page count
        assert seen == [1, 2, 3]
        assert len(pages) == 3

    def test_progress_is_readable_between_pages(self, jobs_dir):
        # Given
        _ = jobs_dir
        service = OcrService()
        engine = _engine_reading({}, {})
        job_id = new_job_id()

        # When
        service._predict_pages(engine, _pages(2), PROFILE, deadline=None, job_id=job_id)

        # Then
        assert read_progress(job_id) == 2

    def test_a_call_with_no_job_records_no_progress(self, jobs_dir, monkeypatch):
        # Given - the warm-up path and any direct call, which belong to no job
        _ = jobs_dir
        service = OcrService()
        engine = _engine_reading({})
        written: list[tuple[str, int]] = []
        monkeypatch.setattr(
            "src.service.ocr_service.write_progress",
            lambda job_id, pages: written.append((job_id, pages)),
        )

        # When
        service._predict_pages(engine, _pages(1), PROFILE, deadline=None, job_id=None)

        # Then
        assert written == []


class TestCancellationReplacesTheWorker:
    async def test_a_requested_replacement_is_reported_as_in_progress_before_it_first_runs(self, monkeypatch):
        # Given
        replacement_may_finish = asyncio.Event()

        async def slow_replacement() -> None:
            await replacement_may_finish.wait()

        monkeypatch.setattr(ocr_service_module, "replace_worker_for_cancel", slow_replacement)

        # When
        request_worker_replacement_for_cancel()

        # Then
        assert is_rebuild_in_progress() is True
        assert is_accepting_work() is False
        replacement_may_finish.set()
        await wait_for_worker_replacements()
        assert is_rebuild_in_progress() is False

    async def test_requesting_a_replacement_does_not_wait_for_it(self, monkeypatch):
        # Given
        started: list[bool] = []

        async def recording_replacement() -> None:
            started.append(True)

        monkeypatch.setattr(ocr_service_module, "replace_worker_for_cancel", recording_replacement)

        # When
        request_worker_replacement_for_cancel()

        # Then: returned before the replacement ran, and the replacement still runs
        assert started == []
        await wait_for_worker_replacements()
        assert started == [True]

    async def test_a_replacement_that_fails_is_logged_and_no_longer_in_progress(self, monkeypatch, emitted_logs):
        # Given
        async def failing_replacement() -> None:
            raise RuntimeError("pool would not start")

        monkeypatch.setattr(ocr_service_module, "replace_worker_for_cancel", failing_replacement)

        # When
        request_worker_replacement_for_cancel()
        await wait_for_worker_replacements()

        # Then
        failures = [record for record in emitted_logs if record.levelno == logging.ERROR]
        assert [record.exc_info is not None for record in failures] == [True]
        assert is_rebuild_in_progress() is False

    async def test_a_replacement_cancelled_by_shutdown_is_forgotten_without_an_error(self, monkeypatch, emitted_logs):
        # Given
        async def endless_replacement() -> None:
            await asyncio.Event().wait()

        monkeypatch.setattr(ocr_service_module, "replace_worker_for_cancel", endless_replacement)
        request_worker_replacement_for_cancel()

        # When
        for task in list(ocr_service_module._pending_replacements):
            task.cancel()
        await wait_for_worker_replacements()

        # Then
        assert is_rebuild_in_progress() is False
        assert [record for record in emitted_logs if record.levelno >= logging.ERROR] == []

    async def test_a_waiter_that_is_cancelled_leaves_the_replacement_running(self, monkeypatch):
        # Given: the job runner waits on a replacement, and shutdown cancels the runner mid-wait
        replacement_may_finish = asyncio.Event()

        async def slow_replacement() -> None:
            await replacement_may_finish.wait()

        monkeypatch.setattr(ocr_service_module, "replace_worker_for_cancel", slow_replacement)
        request_worker_replacement_for_cancel()
        (replacement,) = ocr_service_module._pending_replacements
        waiter = asyncio.create_task(wait_for_worker_replacements())
        await asyncio.sleep(0)

        # When
        waiter.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await waiter

        # Then
        assert replacement.cancelled() is False
        replacement_may_finish.set()
        await wait_for_worker_replacements()
        assert replacement.done() is True
        assert replacement.cancelled() is False

    async def test_waiting_for_replacements_with_none_in_flight_returns_at_once(self):
        # When
        await asyncio.wait_for(wait_for_worker_replacements(), timeout=1.0)

        # Then
        assert is_rebuild_in_progress() is False

    async def test_a_cancel_kills_the_worker_rather_than_draining_it(self, monkeypatch):
        # Given - a pool whose worker is mid-document, which shutdown(wait=True) alone
        # would wait for
        monkeypatch.setattr(ocr_service_module, "_pool_generation", 7)
        monkeypatch.setattr(ocr_service_module, "_consecutive_rebuild_failures", 0)
        stopped: list[bool] = []
        monkeypatch.setattr(ocr_service_module, "stop_worker_pool", lambda terminate=False: stopped.append(terminate))
        monkeypatch.setattr(ocr_service_module, "start_worker_pool", MagicMock(return_value=True))
        before = POOL_REBUILDS_TOTAL.labels(reason="cancel", outcome="ok")._value.get()

        # When
        await replace_worker_for_cancel()

        # Then
        assert stopped == [True]
        assert POOL_REBUILDS_TOTAL.labels(reason="cancel", outcome="ok")._value.get() == before + 1

    async def test_a_cancel_does_not_count_towards_the_consecutive_failure_cap(self, monkeypatch):
        # Given
        monkeypatch.setattr(ocr_service_module, "_pool_generation", 7)
        monkeypatch.setattr(ocr_service_module, "_consecutive_rebuild_failures", 0)
        monkeypatch.setattr(ocr_service_module, "stop_worker_pool", MagicMock())
        monkeypatch.setattr(ocr_service_module, "start_worker_pool", MagicMock(return_value=True))

        # When
        await replace_worker_for_cancel()

        # Then
        assert ocr_service_module._consecutive_rebuild_failures == 0
        assert is_pool_usable() is True

    def test_terminating_the_pool_kills_every_worker_process(self):
        # Given
        first = MagicMock()
        second = MagicMock()
        pool = MagicMock()
        pool._processes = {1: first, 2: second}

        # When
        _terminate_pool_processes(pool)

        # Then
        first.kill.assert_called_once()
        second.kill.assert_called_once()

    def test_stopping_without_terminating_leaves_the_workers_to_finish(self, monkeypatch):
        # Given
        pool = MagicMock()
        pool._processes = {1: MagicMock()}
        monkeypatch.setattr(ocr_service_module, "_process_pool", pool)

        # When
        stop_worker_pool()

        # Then
        pool._processes[1].kill.assert_not_called()
        pool.shutdown.assert_called_once_with(wait=True)

    def test_stopping_with_terminate_kills_first_and_then_shuts_down(self, monkeypatch):
        # Given
        process = MagicMock()
        pool = MagicMock()
        pool._processes = {1: process}
        monkeypatch.setattr(ocr_service_module, "_process_pool", pool)

        # When
        stop_worker_pool(terminate=True)

        # Then
        process.kill.assert_called_once()
        pool.shutdown.assert_called_once_with(wait=True)
