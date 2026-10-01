import pytest

from src.model.ocr_models import (
    RETRYABLE_FAILURE_REASONS,
    TERMINAL_JOB_STATES,
    HealthResponse,
    JobListEntry,
    JobRecord,
    JobResultLocation,
    JobResultReference,
    JobStatusResponse,
    JobSubmitResponse,
    OcrJsonResponse,
    OcrPageResult,
    OcrTextLine,
    ReadinessResponse,
)
from src.service.job_store import new_job_id


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
        # When / Then
        with pytest.raises(ValueError):
            _create_text_line(confidence=1.5)

    def test_confidence_below_zero_rejected(self):
        # When / Then
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
        # When / Then
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
        # When / Then
        with pytest.raises(ValueError):
            OcrJsonResponse(
                filename="x.png",
                language="not-a-lang",
                pages=[],
                processing_time_seconds=1.0,
            )

    def test_six_letter_korean_language_accepted(self):
        # When. "korean" is PaddleOCR's own code and the longest one, switched off but still a valid shape.
        response = OcrJsonResponse(
            filename="x.png",
            language="korean",
            pages=[],
            processing_time_seconds=1.0,
        )

        # Then
        assert response.language == "korean"


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
        ready = ReadinessResponse(
            status="ready",
            version="0.1.0",
            engine_warm=True,
            accepting_work=True,
            jobs_queued=0,
            jobs_running=0,
        )

        # Then
        assert ready.status == "ready"
        assert ready.engine_warm is True
        assert ready.accepting_work is True

    def test_not_ready(self):
        # When
        not_ready = ReadinessResponse(
            status="not-ready",
            version="0.1.0",
            engine_warm=False,
            accepting_work=False,
            jobs_queued=3,
            jobs_running=1,
        )

        # Then
        assert not_ready.status == "not-ready"
        assert not_ready.engine_warm is False
        assert not_ready.accepting_work is False
        assert not_ready.jobs_queued == 3
        assert not_ready.jobs_running == 1

    @pytest.mark.parametrize("field", ["jobs_queued", "jobs_running"])
    def test_negative_job_counts_rejected(self, field):
        # Given
        fields = {
            "status": "ready",
            "version": "0.1.0",
            "engine_warm": True,
            "accepting_work": True,
            "jobs_queued": 0,
            "jobs_running": 0,
        }
        fields[field] = -1

        # When / Then
        with pytest.raises(ValueError):
            ReadinessResponse.model_validate(fields)


def _job_record(**overrides: object) -> JobRecord:
    fields: dict[str, object] = {
        "job_id": new_job_id(),
        "state": "waiting",
        "surface": "rest",
        "filename": "scan.pdf",
        "language": "en",
        "page_count": 2,
        "submitted_at": 1_700_000_000.0,
    }
    fields.update(overrides)

    return JobRecord.model_validate(fields)


class TestJobRecord:
    def test_a_fresh_record_has_read_nothing_and_failed_at_nothing(self):
        # When
        record = _job_record()

        # Then
        assert record.pages_done == 0
        assert record.error_code is None
        assert record.error_reason is None
        assert record.retryable is False
        assert record.result is None
        assert record.is_terminal is False

    @pytest.mark.parametrize("state", ["succeeded", "failed", "cancelled"])
    def test_the_three_finished_states_are_terminal(self, state):
        # When / Then
        assert _job_record(state=state).is_terminal is True
        assert state in TERMINAL_JOB_STATES

    @pytest.mark.parametrize("state", ["waiting", "running"])
    def test_work_still_in_flight_is_not_terminal(self, state):
        # When / Then
        assert _job_record(state=state).is_terminal is False

    def test_a_state_the_service_never_issues_is_rejected(self):
        # When / Then
        with pytest.raises(ValueError):
            _job_record(state="paused")

    def test_an_identifier_that_is_not_shaped_like_one_is_rejected(self):
        # When / Then
        with pytest.raises(ValueError):
            _job_record(job_id="../../etc/passwd")

    def test_a_document_with_no_pages_is_rejected(self):
        # When / Then
        with pytest.raises(ValueError):
            _job_record(page_count=0)

    def test_a_record_round_trips_through_its_serialised_form(self):
        # Given
        record = _job_record(
            state="succeeded",
            finished_at=1_700_000_100.0,
            result=JobResultLocation(bucket="ocr-results", key="x.md"),
        )

        # When
        restored = JobRecord.model_validate_json(record.model_dump_json())

        # Then
        assert restored == record

    def test_a_record_written_before_quality_modes_existed_reads_as_high(self):
        # Given
        stored = _job_record().model_dump(exclude={"quality"})

        # When
        restored = JobRecord.model_validate(stored)

        # Then
        assert restored.quality == "high"

    def test_a_quality_mode_the_service_never_offers_is_rejected(self):
        # When / Then
        with pytest.raises(ValueError):
            _job_record(quality="ultra")

    def test_a_straightened_record_round_trips_through_its_serialised_form(self):
        # Given
        record = _job_record(straighten=True)

        # When
        restored = JobRecord.model_validate_json(record.model_dump_json())

        # Then
        assert restored.straighten is True

    def test_a_record_written_before_straightening_existed_reads_as_not_straightened(self):
        # Given
        stored = _job_record().model_dump(exclude={"straighten"})

        # When
        restored = JobRecord.model_validate(stored)

        # Then
        assert restored.straighten is False

    def test_a_straighten_value_that_is_not_a_boolean_is_rejected(self):
        # When / Then
        with pytest.raises(ValueError):
            _job_record(straighten="sometimes")

    def test_only_the_reasons_that_learned_nothing_about_the_document_are_retryable(self):
        # When / Then
        assert sorted(RETRYABLE_FAILURE_REASONS) == ["RESULT_STORE_UNAVAILABLE", "SERVICE_RESTARTED"]


class TestJobResponses:
    def test_a_submission_answer_names_where_the_state_can_be_read(self):
        # When
        submitted = JobSubmitResponse(
            job_id=new_job_id(),
            state="waiting",
            page_count=1,
            queue_position=0,
            pages_ahead=0,
            status_url="/v1/ocr/jobs/x",
            poll_after_seconds=1.0,
        )

        # Then
        assert submitted.state == "waiting"
        assert submitted.status_url.startswith("/v1/ocr/jobs/")

    def test_a_hint_of_zero_seconds_is_rejected(self):
        # When / Then - a hint must ask the caller to wait, never to ask again immediately
        with pytest.raises(ValueError):
            JobSubmitResponse(
                job_id=new_job_id(),
                state="waiting",
                page_count=1,
                queue_position=0,
                pages_ahead=0,
                status_url="/v1/ocr/jobs/x",
                poll_after_seconds=0.0,
            )

    def test_a_status_answer_carries_no_hint_and_no_result_by_default(self):
        # When
        status = JobStatusResponse(
            job_id=new_job_id(),
            state="failed",
            page_count=1,
            pages_done=0,
            submitted_at=1_700_000_000.0,
        )

        # Then
        assert status.poll_after_seconds is None
        assert status.result is None
        assert status.retryable is False

    def test_a_status_answer_without_a_hint_serialises_with_no_hint_key(self):
        # Given
        status = JobStatusResponse(
            job_id=new_job_id(),
            state="succeeded",
            page_count=1,
            pages_done=1,
            submitted_at=1_700_000_000.0,
        )

        # When
        dumped = status.model_dump()
        dumped_json = status.model_dump_json()

        # Then, absence rather than null is the signal that there is nothing left to ask
        assert "poll_after_seconds" not in dumped
        assert "poll_after_seconds" not in dumped_json

    def test_a_status_answer_with_a_hint_serialises_it(self):
        # Given
        status = JobStatusResponse(
            job_id=new_job_id(),
            state="running",
            page_count=1,
            pages_done=0,
            submitted_at=1_700_000_000.0,
            poll_after_seconds=2.5,
        )

        # When
        dumped = status.model_dump()

        # Then
        assert dumped["poll_after_seconds"] == pytest.approx(2.5)

    def test_a_result_reference_carries_the_address_and_the_bounded_description(self):
        # When
        reference = JobResultReference(
            bucket="ocr-results",
            key="x.md",
            url="http://localhost:9070/ocr-results/x.md",
            filename="scan.pdf",
            language="en",
            quality="normal",
            straighten=True,
            page_count=25,
            processing_time_seconds=250.0,
        )

        # Then
        assert reference.schema_version == "1"
        assert reference.page_count == 25
        assert reference.quality == "normal"
        assert reference.straighten is True

    def test_a_listing_entry_only_describes_work_in_flight(self):
        # When
        entry = JobListEntry(
            job_id=new_job_id(),
            state="running",
            page_count=4,
            pages_done=2,
            elapsed_seconds=12.5,
            queue_position=0,
        )

        # Then
        assert entry.state == "running"

    @pytest.mark.parametrize("state", ["succeeded", "failed", "cancelled"])
    def test_a_finished_state_cannot_appear_in_the_listing(self, state):
        # When / Then
        with pytest.raises(ValueError):
            JobListEntry(
                job_id=new_job_id(),
                state=state,
                page_count=1,
                pages_done=1,
                elapsed_seconds=1.0,
                queue_position=0,
            )
