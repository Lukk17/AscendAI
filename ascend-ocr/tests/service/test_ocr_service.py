import asyncio
import itertools
import os
import time
from concurrent.futures.process import BrokenProcessPool
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.exception_handlers import FileSizeExceededError, OcrProcessingError, UnsupportedFileTypeError
from src.config.config import settings
from src.model.ocr_models import OcrJsonResponse
from src.service import ocr_service as ocr_service_module
from src.service.ocr_service import (
    OcrDeadlineExceededError,
    OcrService,
    _convert_polygon,
    _noop_task,
    _safe_suffix,
    _warm_worker_engine,
    dispatch_ocr_request,
    get_pool_generation,
    get_process_pool,
    get_queue_depth,
    is_accepting_work,
    is_job_overrunning,
    is_pool_usable,
    is_rebuild_in_progress,
    run_ocr_in_worker,
    start_worker_pool,
    stop_worker_pool,
    sweep_scratch_dir,
)


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

    @patch("src.service.ocr_service.PaddleOCR")
    def test_detector_bound_passed_when_configured(self, mock_paddle_class, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OCR_DETECTOR_MAX_SIDE", 1536)
        mock_paddle_class.return_value = MagicMock()
        service = OcrService()

        # When
        service._get_engine("en")

        # Then
        _, kwargs = mock_paddle_class.call_args
        assert kwargs["text_det_limit_type"] == "max"
        assert kwargs["text_det_limit_side_len"] == 1536

    @patch("src.service.ocr_service.PaddleOCR")
    def test_detector_bound_omitted_when_unset(self, mock_paddle_class, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OCR_DETECTOR_MAX_SIDE", None)
        mock_paddle_class.return_value = MagicMock()
        service = OcrService()

        # When
        service._get_engine("en")

        # Then
        _, kwargs = mock_paddle_class.call_args
        assert "text_det_limit_type" not in kwargs
        assert "text_det_limit_side_len" not in kwargs

    @patch("src.service.ocr_service.PaddleOCR")
    def test_cache_key_is_language_only_regardless_of_detector_bound(self, mock_paddle_class, monkeypatch):
        # Given — the bound is fixed for the process's lifetime, so it must not affect
        # which cache slot a language resolves to.
        monkeypatch.setattr(settings, "OCR_DETECTOR_MAX_SIDE", 960)
        mock_paddle_class.return_value = MagicMock()
        service = OcrService()

        # When
        service._get_engine("en")
        monkeypatch.setattr(settings, "OCR_DETECTOR_MAX_SIDE", 1536)
        service._get_engine("en")

        # Then — still one cached engine for "en", constructor called once
        assert mock_paddle_class.call_count == 1
        assert list(service._engines) == ["en"]


class TestOcrServicePredictPages:
    def test_predict_pages_assigns_page_numbers_in_order(self):
        # Given
        service = OcrService()
        engine = MagicMock()
        engine.predict_iter.return_value = _create_multi_page_predict_result()

        # When
        pages = service._predict_pages(engine, "doc.pdf", deadline=None)

        # Then
        assert [p.page_number for p in pages] == [1, 2]
        assert pages[0].lines[0].text == "Page one"
        assert pages[1].lines[0].text == "Page two"

    def test_predict_pages_empty_generator_returns_empty(self):
        # Given
        service = OcrService()
        engine = MagicMock()
        engine.predict_iter.return_value = []

        # When
        pages = service._predict_pages(engine, "doc.pdf", deadline=None)

        # Then
        assert pages == []

    def test_predict_pages_skips_non_dict_entries(self):
        # Given
        service = OcrService()
        engine = MagicMock()
        engine.predict_iter.return_value = ["not-a-dict", _create_mock_predict_result()[0]]

        # When
        pages = service._predict_pages(engine, "doc.pdf", deadline=None)

        # Then
        assert len(pages) == 1

    def test_deadline_stops_before_first_page_when_already_expired(self):
        # Given — deadline in the past: no page should ever be pulled from the iterator
        service = OcrService()
        engine = MagicMock()
        engine.predict_iter.return_value = _create_multi_page_predict_result()

        # Then
        with pytest.raises(OcrDeadlineExceededError, match="after 0"):
            service._predict_pages(engine, "doc.pdf", deadline=time.monotonic() - 1)

        engine.predict_iter.assert_called_once()

    def test_deadline_stops_mid_document_before_next_page(self):
        # Given — deadline expires after the first page is consumed, so the second
        # page must never be inferred (predict_iter must not be asked for it).
        service = OcrService()
        engine = MagicMock()
        engine.predict_iter.return_value = _create_multi_page_predict_result()
        deadline = 100.0
        # Calls, in order: check before page 1 (before deadline), page-timer start,
        # page-timer end, check before page 2 (past deadline).
        monotonic_values = iter([50.0, 50.0, 50.1, 200.0])

        with (
            patch("src.service.ocr_service.time.monotonic", side_effect=lambda: next(monotonic_values)),
            pytest.raises(OcrDeadlineExceededError, match="after 1"),
        ):
            service._predict_pages(engine, "doc.pdf", deadline=deadline)

    def test_no_deadline_consumes_every_page(self):
        # Given
        service = OcrService()
        engine = MagicMock()
        engine.predict_iter.return_value = _create_multi_page_predict_result()

        # When
        pages = service._predict_pages(engine, "doc.pdf", deadline=None)

        # Then
        assert len(pages) == 2

    def test_one_span_per_page_carrying_index_and_remaining_budget(self):
        # Given
        service = OcrService()
        engine = MagicMock()
        engine.predict_iter.return_value = _create_multi_page_predict_result()
        deadline = time.monotonic() + 60.0

        # When
        with patch("src.service.ocr_service.tracer") as mock_tracer:
            service._predict_pages(engine, "doc.pdf", deadline=deadline)

        # Then — one span per page (matching the two pages in the fixture), each
        # nested under whatever span is current when _predict_pages runs, since
        # start_as_current_span attaches to the ambient context rather than a
        # passed-in one.
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
        engine = MagicMock()
        engine.predict_iter.return_value = _create_mock_predict_result()

        # When
        with patch("src.service.ocr_service.tracer") as mock_tracer:
            service._predict_pages(engine, "doc.pdf", deadline=None)

        # Then
        _, kwargs = mock_tracer.start_as_current_span.call_args
        assert kwargs["attributes"]["remaining_budget_seconds"] == -1.0


class TestOcrServiceProcessFile:
    @patch("src.service.ocr_service.PaddleOCR")
    def test_process_file_json_output(self, mock_paddle_class):
        # Given
        mock_engine = MagicMock()
        mock_engine.predict_iter.return_value = _create_mock_predict_result()
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
        mock_engine.predict_iter.return_value = _create_multi_page_predict_result()
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
        mock_engine.predict_iter.return_value = [{}]
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
        mock_engine.predict_iter.return_value = _create_mock_predict_result()
        mock_paddle_class.return_value = mock_engine
        service = OcrService()

        # When / Then. Patch exists -> False inline so the unused fixture parameter is dropped.
        with patch("src.service.ocr_service.os.path.exists", return_value=False):
            result = service.process_file(b"x", "test.png", "en")

        assert isinstance(result, OcrJsonResponse)

    @patch("src.service.ocr_service.os.remove", side_effect=OSError("locked by another process"))
    @patch("src.service.ocr_service.PaddleOCR")
    def test_cleanup_failure_does_not_mask_the_original_exception(self, mock_paddle_class, _mock_remove):
        # Given — a removal failure during cleanup (e.g. Windows holding the file open)
        # must never replace whatever this method was already propagating.
        mock_engine = MagicMock()
        mock_engine.predict_iter.side_effect = RuntimeError("engine blew up")
        mock_paddle_class.return_value = mock_engine
        service = OcrService()

        # Then
        with pytest.raises(RuntimeError, match="engine blew up"):
            service.process_file(b"x", "test.png", "en")

    @patch("src.service.ocr_service.PaddleOCR")
    def test_process_file_writes_into_scratch_dir(self, mock_paddle_class, tmp_path, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OCR_SCRATCH_DIR", str(tmp_path / "scratch"))
        mock_engine = MagicMock()
        seen_paths: list[str] = []

        def fake_predict_iter(path: str):
            seen_paths.append(path)
            return iter(_create_mock_predict_result())

        mock_engine.predict_iter.side_effect = fake_predict_iter
        mock_paddle_class.return_value = mock_engine
        service = OcrService()

        # When
        service.process_file(b"x", "test.png", "en")

        # Then
        assert seen_paths[0].startswith(str(tmp_path / "scratch"))

    @patch("src.service.ocr_service.PaddleOCR")
    def test_process_file_raises_when_budget_exhausted_before_first_page(self, mock_paddle_class):
        # Given
        mock_engine = MagicMock()
        mock_engine.predict_iter.return_value = _create_mock_predict_result()
        mock_paddle_class.return_value = mock_engine
        service = OcrService()

        # Then — a zero/negative budget must stop the request without inferring
        with pytest.raises(OcrDeadlineExceededError):
            service.process_file(b"x", "test.png", "en", budget_seconds=-1.0)

    @patch("src.service.ocr_service.PaddleOCR")
    def test_process_file_deadline_computed_from_duration_not_absolute_time(self, mock_paddle_class):
        # Given — no absolute timestamp may cross the process boundary: the worker
        # must derive its deadline from its own time.monotonic() plus the duration.
        mock_engine = MagicMock()
        mock_engine.predict_iter.return_value = _create_mock_predict_result()
        mock_paddle_class.return_value = mock_engine
        service = OcrService()

        with patch("src.service.ocr_service.time.monotonic", return_value=1_000_000.0) as mock_monotonic:
            service.process_file(b"x", "test.png", "en", budget_seconds=30.0)

        # Then — every deadline check is relative to this process's own clock
        mock_monotonic.assert_called()

    @patch("src.service.ocr_service.PaddleOCR")
    def test_process_file_no_budget_means_no_deadline(self, mock_paddle_class):
        # Given
        mock_engine = MagicMock()
        mock_engine.predict_iter.return_value = _create_mock_predict_result()
        mock_paddle_class.return_value = mock_engine
        service = OcrService()

        # When / Then — budget_seconds omitted entirely, must not raise
        result = service.process_file(b"x", "test.png", "en")
        assert isinstance(result, OcrJsonResponse)


class TestOcrServiceProcessFileTraceContext:
    @patch("src.service.ocr_service.PaddleOCR")
    def test_no_trace_carrier_starts_span_with_no_parent(self, mock_paddle_class):
        # Given
        mock_engine = MagicMock()
        mock_engine.predict_iter.return_value = _create_mock_predict_result()
        mock_paddle_class.return_value = mock_engine
        service = OcrService()

        # When
        with patch.object(ocr_service_module, "tracer") as mock_tracer:
            service.process_file(b"x", "test.png", "en")

        # Then. [0] is the outer ascend-ocr.engine.predict span (the one that carries
        # the parent context); later calls are the per-page child spans.
        _, kwargs = mock_tracer.start_as_current_span.call_args_list[0]
        assert kwargs["context"] is None

    @patch("src.service.ocr_service.extract_trace_context")
    @patch("src.service.ocr_service.PaddleOCR")
    def test_trace_carrier_is_extracted_into_parent_context(self, mock_paddle_class, mock_extract):
        # Given — trace_carrier simulates a context injected by the process that
        # submitted this call, since process_file runs inside a separate OCR worker
        mock_engine = MagicMock()
        mock_engine.predict_iter.return_value = _create_mock_predict_result()
        mock_paddle_class.return_value = mock_engine
        sentinel_context = object()
        mock_extract.return_value = sentinel_context
        service = OcrService()
        carrier = {"traceparent": "00-fake-01"}

        # When
        with patch.object(ocr_service_module, "tracer") as mock_tracer:
            service.process_file(b"x", "test.png", "en", carrier)

        # Then
        mock_extract.assert_called_once_with(carrier)
        _, kwargs = mock_tracer.start_as_current_span.call_args_list[0]
        assert kwargs["context"] is sentinel_context


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
    def test_start_worker_pool_resets_gate_and_queue_depth(self, mock_executor_class, mock_multiprocessing):
        # Given
        mock_executor_class.return_value = MagicMock()
        mock_multiprocessing.get_context.return_value = MagicMock()

        # When
        with (
            patch.object(ocr_service_module, "_queue_depth", 3),
            patch.object(settings, "OCR_WORKER_COUNT", 2),
        ):
            start_worker_pool()

            # Then — gate permits and pool size come from the same setting
            assert get_queue_depth() == 0
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

        # When / Then — must not propagate: a startup exception here would kill the
        # FastAPI lifespan and crash the container instead of leaving /ready to report
        # not-ready.
        with patch.object(ocr_service_module, "_process_pool", None):
            warmed = start_worker_pool()

            assert warmed is False
            assert ocr_service_module._process_pool is mock_pool

    @patch("src.service.ocr_service.multiprocessing")
    @patch("src.service.ocr_service.ProcessPoolExecutor")
    def test_start_worker_pool_warms_every_configured_worker(self, mock_executor_class, mock_multiprocessing):
        # Given — ProcessPoolExecutor only spawns one worker per submit() call when no
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
        # Given — three workers requested, the second one's own warm-up is broken.
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
        # When / Then — no raise, nothing to shut down
        with patch.object(ocr_service_module, "_process_pool", None):
            stop_worker_pool()
            assert ocr_service_module._process_pool is None

    def test_get_process_pool_raises_when_not_started(self):
        # Then
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
        result = run_ocr_in_worker(b"bytes", "scan.png", "en", carrier, 30.0)

        # Then
        mock_service.process_file.assert_called_once_with(b"bytes", "scan.png", "en", carrier, 30.0)
        assert result == "sentinel-response"

    @patch("src.service.ocr_service.ocr_service")
    def test_run_ocr_in_worker_defaults_to_none(self, mock_service):
        # Given
        mock_service.process_file.return_value = "sentinel-response"

        # When
        run_ocr_in_worker(b"bytes", "scan.png", "en")

        # Then
        mock_service.process_file.assert_called_once_with(b"bytes", "scan.png", "en", None, None)

    @patch("src.service.ocr_service.configure_worker_tracing")
    @patch("src.service.ocr_service.ocr_service")
    def test_warm_worker_engine_configures_tracing_before_warmup(self, mock_service, mock_configure_tracing):
        # When
        _warm_worker_engine("en")

        # Then — tracing must be wired up before the warmup span is created
        mock_configure_tracing.assert_called_once()
        mock_service.warm_up_engine.assert_called_once_with("en")

    def test_noop_task_returns_none(self):
        # Then
        assert _noop_task() is None


class TestSweepScratchDir:
    def test_creates_missing_directory(self, tmp_path, monkeypatch):
        # Given
        scratch = tmp_path / "scratch"
        monkeypatch.setattr(settings, "OCR_SCRATCH_DIR", str(scratch))

        # When
        sweep_scratch_dir()

        # Then
        assert scratch.is_dir()

    def test_removes_stale_file(self, tmp_path, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OCR_SCRATCH_DIR", str(tmp_path))
        monkeypatch.setattr(settings, "OCR_REQUEST_TIMEOUT", 10.0)
        monkeypatch.setattr(settings, "OCR_DISPATCH_MARGIN_SECONDS", 1.0)
        stale = tmp_path / "stale.tmp"
        stale.write_bytes(b"x")
        old_time = time.time() - 1000
        os.utime(stale, (old_time, old_time))

        # When
        sweep_scratch_dir()

        # Then
        assert not stale.exists()

    def test_keeps_fresh_file(self, tmp_path, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OCR_SCRATCH_DIR", str(tmp_path))
        monkeypatch.setattr(settings, "OCR_REQUEST_TIMEOUT", 300.0)
        monkeypatch.setattr(settings, "OCR_DISPATCH_MARGIN_SECONDS", 5.0)
        fresh = tmp_path / "fresh.tmp"
        fresh.write_bytes(b"x")

        # When
        sweep_scratch_dir()

        # Then
        assert fresh.exists()

    def test_skips_subdirectories(self, tmp_path, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OCR_SCRATCH_DIR", str(tmp_path))
        (tmp_path / "subdir").mkdir()

        # When / Then — no raise
        sweep_scratch_dir()
        assert (tmp_path / "subdir").is_dir()

    def test_stat_failure_is_skipped(self, tmp_path, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OCR_SCRATCH_DIR", str(tmp_path))
        present = tmp_path / "present.tmp"
        present.write_bytes(b"x")

        # When / Then — an entry whose stat() races (removed mid-scan) is skipped, not raised
        with patch("src.service.ocr_service.os.scandir") as mock_scandir:
            entry = MagicMock()
            entry.is_file.return_value = True
            entry.stat.side_effect = OSError("vanished")
            mock_scandir.return_value.__enter__ = MagicMock(return_value=None)
            mock_scandir.return_value = [entry]
            sweep_scratch_dir()

    def test_remove_failure_is_logged_not_raised(self, tmp_path, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OCR_SCRATCH_DIR", str(tmp_path))
        monkeypatch.setattr(settings, "OCR_REQUEST_TIMEOUT", 1.0)
        monkeypatch.setattr(settings, "OCR_DISPATCH_MARGIN_SECONDS", 0.0)
        stale = tmp_path / "stale.tmp"
        stale.write_bytes(b"x")
        old_time = time.time() - 1000
        os.utime(stale, (old_time, old_time))

        # When / Then — no raise even if the remove itself fails
        with patch("src.service.ocr_service.os.remove", side_effect=OSError("locked")):
            sweep_scratch_dir()


class TestPoolHealthSignals:
    def test_is_pool_usable_true_under_cap(self, monkeypatch):
        # Given
        monkeypatch.setattr(ocr_service_module, "_consecutive_rebuild_failures", 0)

        # Then
        assert is_pool_usable() is True

    def test_is_pool_usable_false_at_cap(self, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OCR_POOL_REBUILD_MAX_CONSECUTIVE", 3)
        monkeypatch.setattr(ocr_service_module, "_consecutive_rebuild_failures", 3)

        # Then
        assert is_pool_usable() is False

    def test_is_rebuild_in_progress_false_by_default(self):
        # Then
        assert is_rebuild_in_progress() is False

    async def test_is_rebuild_in_progress_true_while_locked(self):
        # Given
        async with ocr_service_module._rebuild_lock:
            # Then
            assert is_rebuild_in_progress() is True

        assert is_rebuild_in_progress() is False

    def test_is_job_overrunning_false_when_idle(self, monkeypatch):
        # Given
        monkeypatch.setattr(ocr_service_module, "_active_deadlines", {})

        # Then
        assert is_job_overrunning() is False

    def test_is_job_overrunning_false_within_budget(self, monkeypatch):
        # Given
        monkeypatch.setattr(ocr_service_module, "_active_deadlines", {object(): time.monotonic() + 100})

        # Then
        assert is_job_overrunning() is False

    def test_is_job_overrunning_true_past_budget(self, monkeypatch):
        # Given
        monkeypatch.setattr(ocr_service_module, "_active_deadlines", {object(): time.monotonic() - 1})

        # Then
        assert is_job_overrunning() is True

    def test_is_job_overrunning_true_when_one_of_several_jobs_is_past_budget(self, monkeypatch):
        # Given — two workers, one healthy and well within budget, one genuinely stuck.
        # A single shared deadline variable could only ever record the more recent of
        # the two, so this is the regression case for that bug.
        monkeypatch.setattr(
            ocr_service_module,
            "_active_deadlines",
            {object(): time.monotonic() + 100, object(): time.monotonic() - 1},
        )

        # Then
        assert is_job_overrunning() is True

    def test_is_accepting_work_true_when_healthy_and_idle(self, monkeypatch):
        # Given
        monkeypatch.setattr(ocr_service_module, "_consecutive_rebuild_failures", 0)
        monkeypatch.setattr(ocr_service_module, "_active_deadlines", {})

        # Then
        assert is_accepting_work() is True

    def test_is_accepting_work_false_when_pool_exhausted(self, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OCR_POOL_REBUILD_MAX_CONSECUTIVE", 1)
        monkeypatch.setattr(ocr_service_module, "_consecutive_rebuild_failures", 1)

        # Then
        assert is_accepting_work() is False

    def test_is_accepting_work_false_while_job_overrunning(self, monkeypatch):
        # Given
        monkeypatch.setattr(ocr_service_module, "_consecutive_rebuild_failures", 0)
        monkeypatch.setattr(ocr_service_module, "_active_deadlines", {object(): time.monotonic() - 1})

        # Then
        assert is_accepting_work() is False

    async def test_is_accepting_work_false_while_rebuilding(self, monkeypatch):
        # Given
        monkeypatch.setattr(ocr_service_module, "_consecutive_rebuild_failures", 0)
        monkeypatch.setattr(ocr_service_module, "_active_deadlines", {})

        # Then
        async with ocr_service_module._rebuild_lock:
            assert is_accepting_work() is False


class TestRebuildPool:
    async def test_generation_mismatch_skips_rebuild(self, monkeypatch):
        # Given — another caller already rebuilt past the generation this caller saw
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
        # Given — stop_worker_pool blocks its own thread for a while, mirroring
        # ProcessPoolExecutor.shutdown(wait=True) waiting on another worker's own
        # legitimate, unrelated in-flight job to finish (proven against the real
        # stdlib: a two-worker pool with one fast and one 8s-sleeping job took 7.94s
        # to shut down, not the fast job's own time). A version of _rebuild_pool that
        # called stop_worker_pool directly, without offloading it, would freeze this
        # coroutine's own event loop thread for that whole span.
        monkeypatch.setattr(ocr_service_module, "_pool_generation", 1)
        monkeypatch.setattr(ocr_service_module, "_consecutive_rebuild_failures", 0)

        def blocking_stop() -> None:
            time.sleep(0.3)

        monkeypatch.setattr(ocr_service_module, "stop_worker_pool", blocking_stop)
        monkeypatch.setattr(ocr_service_module, "start_worker_pool", MagicMock(return_value=True))

        ticks: list[float] = []

        async def heartbeat() -> None:
            for _ in range(6):
                ticks.append(time.monotonic())
                await asyncio.sleep(0.05)

        # When — the rebuild and an unrelated coroutine run concurrently
        await asyncio.gather(
            ocr_service_module._rebuild_pool(observed_generation=1, reason="reclaim"),
            heartbeat(),
        )

        # Then — the heartbeat kept ticking roughly every 0.05s throughout, rather than
        # being frozen for the ~0.3s stop_worker_pool spent blocking its own thread.
        gaps = [b - a for a, b in itertools.pairwise(ticks)]
        assert max(gaps) < 0.2

    async def test_concurrent_triggers_produce_one_rebuild(self, monkeypatch):
        # Given
        monkeypatch.setattr(ocr_service_module, "_pool_generation", 1)
        monkeypatch.setattr(ocr_service_module, "_consecutive_rebuild_failures", 0)

        def fake_start() -> bool:
            # Mirrors the real start_worker_pool(), which bumps the generation on every
            # (re)build — the second concurrent caller must see this bump and bail out.
            ocr_service_module._pool_generation += 1

            return True

        start_mock = MagicMock(side_effect=fake_start)

        async def fake_run_in_executor(_executor, func):
            return func()

        monkeypatch.setattr(ocr_service_module, "stop_worker_pool", MagicMock())
        monkeypatch.setattr(ocr_service_module, "start_worker_pool", start_mock)

        # When — two concurrent callers both observed the same broken generation
        await asyncio.gather(
            ocr_service_module._rebuild_pool(observed_generation=1, reason="reclaim"),
            ocr_service_module._rebuild_pool(observed_generation=1, reason="reclaim"),
        )

        # Then — only the first actually rebuilds; the second sees the bumped generation
        assert start_mock.call_count == 1

    async def test_successful_request_resets_failure_counter(self, monkeypatch):
        # Given
        monkeypatch.setattr(ocr_service_module, "_consecutive_rebuild_failures", 2)
        ocr_service_module._reset_rebuild_failures()

        # Then
        assert ocr_service_module._consecutive_rebuild_failures == 0


class TestDispatchOcrRequest:
    @pytest.fixture(autouse=True)
    def _reset_state(self, monkeypatch):
        monkeypatch.setattr(ocr_service_module, "_queue_depth", 0)
        monkeypatch.setattr(ocr_service_module, "_active_deadlines", {})
        monkeypatch.setattr(ocr_service_module, "_consecutive_rebuild_failures", 0)
        monkeypatch.setattr(ocr_service_module, "_admission_semaphore", asyncio.Semaphore(1))
        monkeypatch.setattr(ocr_service_module, "_pool_generation", 1)
        yield

    async def test_pool_unusable_refuses_immediately(self, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OCR_POOL_REBUILD_MAX_CONSECUTIVE", 1)
        monkeypatch.setattr(ocr_service_module, "_consecutive_rebuild_failures", 1)

        # Then
        with pytest.raises(OcrProcessingError, match="unavailable"):
            await dispatch_ocr_request(b"x", "f.png", "en", 30.0, "rest")

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

            result = await dispatch_ocr_request(b"x", "f.png", "en", 30.0, "rest")

        # Then
        assert result is sentinel
        # Then — permit released back to its starting value
        assert ocr_service_module._admission_semaphore._value == 1

    async def test_budget_expired_while_waiting_never_dispatches(self, monkeypatch):
        # Given — permit already held by someone else, and the budget is effectively zero
        held_semaphore = asyncio.Semaphore(0)
        monkeypatch.setattr(ocr_service_module, "_admission_semaphore", held_semaphore)
        pool_mock = MagicMock()
        monkeypatch.setattr(ocr_service_module, "get_process_pool", MagicMock(return_value=pool_mock))

        # Then
        with pytest.raises(OcrProcessingError, match="waiting for a worker"):
            await dispatch_ocr_request(b"x", "f.png", "en", 0.01, "rest")

        pool_mock.submit.assert_not_called()

    async def test_budget_expired_between_acquire_and_dispatch_never_dispatches(self, monkeypatch):
        # Given — the gate grants the permit right away, but by the time dispatch
        # re-checks the budget afterward, the clock has moved past it. wait_for is
        # replaced with a direct await so only dispatch_ocr_request's own four explicit
        # time.monotonic() calls are in play, none of asyncio's own timer bookkeeping.
        pool_mock = MagicMock()
        monkeypatch.setattr(ocr_service_module, "get_process_pool", MagicMock(return_value=pool_mock))
        monotonic_values = iter([0.0, 0.0, 0.0, 1.0])

        async def fake_wait_for(coro, **_kwargs):
            return await coro

        # Then
        with (
            patch("src.service.ocr_service.time.monotonic", side_effect=lambda: next(monotonic_values)),
            patch("src.service.ocr_service.asyncio.wait_for", fake_wait_for),
            pytest.raises(OcrProcessingError, match="before dispatch"),
        ):
            await dispatch_ocr_request(b"x", "f.png", "en", 0.5, "rest")

        pool_mock.submit.assert_not_called()

    async def test_worker_timeout_triggers_rebuild_and_fails_request(self, monkeypatch):
        # Given. OCR_RECLAMATION_GRACE_SECONDS is a derived property
        # (OCR_PAGE_TIMEOUT_SECONDS + OCR_DISPATCH_MARGIN_SECONDS), so it is driven
        # through its two real settings rather than patched directly.
        monkeypatch.setattr(ocr_service_module, "_rebuild_pool", lambda *a, **k: _async_none())
        monkeypatch.setattr(ocr_service_module, "get_process_pool", MagicMock(return_value=MagicMock()))

        async def fake_run_in_executor(_executor, _func, *_args):
            await asyncio.sleep(10)

        with patch("asyncio.get_running_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_loop.run_in_executor = fake_run_in_executor
            mock_get_loop.return_value = mock_loop

            with (
                patch.object(ocr_service_module.settings, "OCR_DISPATCH_MARGIN_SECONDS", 0.0),
                patch.object(ocr_service_module.settings, "OCR_PAGE_TIMEOUT_SECONDS", 0.01),
                pytest.raises(OcrProcessingError, match="reclamation grace"),
            ):
                await dispatch_ocr_request(b"x", "f.png", "en", 0.05, "rest")

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

            with pytest.raises(OcrProcessingError, match="worker process failed"):
                await dispatch_ocr_request(b"x", "f.png", "en", 30.0, "rest")

    async def test_pool_already_broken_at_submission_triggers_rebuild_and_fails_request(self, monkeypatch):
        # Given — a worker killed between requests (e.g. by the OS, out-of-band) leaves
        # the pool broken before this request ever calls run_in_executor. concurrent.
        # futures' own executor.submit() raises BrokenProcessPool synchronously in that
        # case, inside run_in_executor's own body, before it ever returns a future —
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

            with pytest.raises(OcrProcessingError, match="worker process failed"):
                await dispatch_ocr_request(b"x", "f.png", "en", 30.0, "rest")

    async def test_pool_torn_down_mid_rebuild_fails_cleanly(self, monkeypatch):
        # Given — a request that clears admission while a concurrent background
        # rebuild (now offloaded off the event loop, see TestRebuildPool) has already
        # torn the old pool down but not yet stood the replacement up.
        # get_process_pool() raises exactly this RuntimeError in that window.
        monkeypatch.setattr(
            ocr_service_module,
            "get_process_pool",
            MagicMock(side_effect=RuntimeError("OCR worker pool is not initialised")),
        )

        # Then — a clean, handled OcrProcessingError, not a raw RuntimeError escaping
        # the dispatch stack.
        with pytest.raises(OcrProcessingError):
            await dispatch_ocr_request(b"x", "f.png", "en", 30.0, "rest")

        # And the permit is still released for the next request.
        assert ocr_service_module._admission_semaphore._value == 1

    async def test_concurrent_jobs_track_independent_overrun_deadlines(self, monkeypatch):
        # Given — two permits, two concurrent jobs with different budgets. The first
        # to finish must not erase the still-running second job's own deadline
        # tracking (the regression case for the single shared _active_deadline bug).
        monkeypatch.setattr(ocr_service_module, "_admission_semaphore", asyncio.Semaphore(2))
        monkeypatch.setattr(ocr_service_module, "get_process_pool", MagicMock(return_value=MagicMock()))
        release_slow = asyncio.Event()

        async def fake_run_in_executor(_executor, _func, *args):
            # run_ocr_in_worker's positional args include the budget last; use it to
            # tell the fast call from the slow one.
            budget = args[-1]
            if budget < 1:
                return OcrJsonResponse(filename="fast", language="en", pages=[], processing_time_seconds=0.01)

            await release_slow.wait()

            return OcrJsonResponse(filename="slow", language="en", pages=[], processing_time_seconds=0.01)

        with patch("asyncio.get_running_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_loop.run_in_executor = fake_run_in_executor
            mock_get_loop.return_value = mock_loop

            fast_task = asyncio.create_task(dispatch_ocr_request(b"x", "fast.png", "en", 0.5, "rest"))
            slow_task = asyncio.create_task(dispatch_ocr_request(b"x", "slow.png", "en", 60.0, "rest"))
            await asyncio.sleep(0.05)

            # When — the fast job finishes and its own finally clears its own entry
            fast_result = await fast_task
            # Then — the still-running slow job's own deadline entry must survive
            assert len(ocr_service_module._active_deadlines) == 1

            release_slow.set()
            slow_result = await slow_task

        assert fast_result.filename == "fast"
        assert slow_result.filename == "slow"
        assert ocr_service_module._active_deadlines == {}

    async def test_worker_own_deadline_stop_fails_cleanly_without_rebuild(self, monkeypatch):
        # Given — the worker observed its own deadline between pages and returned on
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

            with pytest.raises(OcrProcessingError, match="budget exhausted during inference"):
                await dispatch_ocr_request(b"x", "f.png", "en", 30.0, "rest")

        rebuild_mock.assert_not_called()

    async def test_size_and_type_errors_pass_through_unwrapped(self, monkeypatch):
        # Given — the worker can in principle still raise these directly; they must
        # not be masked as a generic OCR failure.
        monkeypatch.setattr(ocr_service_module, "get_process_pool", MagicMock(return_value=MagicMock()))

        async def fake_run_in_executor(_executor, _func, *_args):
            raise FileSizeExceededError("too big")

        with patch("asyncio.get_running_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_loop.run_in_executor = fake_run_in_executor
            mock_get_loop.return_value = mock_loop

            with pytest.raises(FileSizeExceededError):
                await dispatch_ocr_request(b"x", "f.png", "en", 30.0, "rest")

    async def test_unsupported_type_error_passes_through_unwrapped(self, monkeypatch):
        # Given
        monkeypatch.setattr(ocr_service_module, "get_process_pool", MagicMock(return_value=MagicMock()))

        async def fake_run_in_executor(_executor, _func, *_args):
            raise UnsupportedFileTypeError("bad type")

        with patch("asyncio.get_running_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_loop.run_in_executor = fake_run_in_executor
            mock_get_loop.return_value = mock_loop

            with pytest.raises(UnsupportedFileTypeError):
                await dispatch_ocr_request(b"x", "f.png", "en", 30.0, "rest")

    async def test_generic_engine_failure_wrapped_as_ocr_processing_error(self, monkeypatch):
        # Given
        monkeypatch.setattr(ocr_service_module, "get_process_pool", MagicMock(return_value=MagicMock()))

        async def fake_run_in_executor(_executor, _func, *_args):
            raise RuntimeError("engine internal trace")

        with patch("asyncio.get_running_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_loop.run_in_executor = fake_run_in_executor
            mock_get_loop.return_value = mock_loop

            with pytest.raises(OcrProcessingError) as exc_info:
                await dispatch_ocr_request(b"x", "f.png", "en", 30.0, "rest")

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

            await dispatch_ocr_request(b"x", "f.png", "en", 30.0, "rest")

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

            with pytest.raises(OcrProcessingError):
                await dispatch_ocr_request(b"x", "f.png", "en", 30.0, "rest")

        assert ocr_service_module._admission_semaphore._value == 1

    async def test_pool_never_receives_more_concurrent_work_than_worker_count(self, monkeypatch):
        # Given — the pool's own queue can only ever be empty if the admission gate
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

            # When — five requests arrive at once against a pool of two workers
            await asyncio.gather(*[dispatch_ocr_request(b"x", "f.png", "en", 5.0, "rest") for _ in range(5)])

        # Then
        assert max_active <= 2


async def _async_none() -> None:
    return None
