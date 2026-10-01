from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from src.config.config import settings
from src.model.ocr_models import OcrJsonResponse, OcrPageResult, OcrTextLine
from src.service.result_store import (
    MARKDOWN_CONTENT_TYPE,
    UPLOAD_MAX_ATTEMPTS,
    ResultStore,
    ResultStoreUnavailableError,
    render_markdown,
)

JOB_ID = "abcdefghijklmnopqrstuv"


def _line(text: str) -> OcrTextLine:
    return OcrTextLine(text=text, confidence=0.9, bounding_box=[[0.0, 0.0]])


def _response(*pages: list[str]) -> OcrJsonResponse:
    return OcrJsonResponse(
        filename="scan.pdf",
        language="en",
        pages=[
            OcrPageResult(page_number=number, lines=[_line(text) for text in texts])
            for number, texts in enumerate(pages, start=1)
        ],
        processing_time_seconds=1.0,
    )


def _client_error(code: str, operation: str = "HeadBucket") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, operation)


@pytest.fixture
def store() -> ResultStore:
    return ResultStore()


@pytest.fixture
def fake_client(store: ResultStore) -> MagicMock:
    client = MagicMock()
    store._client = client
    store._public_client = client

    return client


class TestRenderMarkdown:
    def test_each_page_is_a_heading_followed_by_its_lines_in_order(self):
        # When
        markdown = render_markdown(_response(["first line", "second line"], ["third line"]))

        # Then
        assert markdown == "## Page 1\nfirst line\nsecond line\n\n## Page 2\nthird line\n"

    def test_a_page_with_no_recognised_lines_keeps_its_heading(self):
        # When
        markdown = render_markdown(_response(["only page one"], []))

        # Then
        assert markdown.endswith("## Page 2\n")

    def test_markdown_control_characters_in_the_text_are_carried_verbatim(self):
        # Given — the document's own text, not something to escape: the agent indexes
        # whatever this returns, so altering the characters alters the document

        # When
        markdown = render_markdown(_response(["# not a heading", "- not a list", "**bold** | pipe"]))

        # Then
        assert "# not a heading" in markdown
        assert "- not a list" in markdown
        assert "**bold** | pipe" in markdown

    def test_the_rendering_carries_no_front_matter(self):
        # When
        markdown = render_markdown(_response(["text"]))

        # Then
        assert not markdown.startswith("---")
        assert "schema_version" not in markdown
        assert "filename" not in markdown
        assert markdown.splitlines()[0] == "## Page 1"


class TestClientConstruction:
    def test_the_client_is_built_from_the_settings_not_the_ambient_environment(
        self, store: ResultStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Given
        monkeypatch.setattr(settings, "OCR_RESULT_S3_ENDPOINT", "http://store.example:9070")
        monkeypatch.setattr(settings, "OCR_RESULT_S3_ACCESS_KEY", "configured-key")
        monkeypatch.setattr(settings, "OCR_RESULT_S3_SECRET_KEY", "configured-secret")
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "ambient-key")
        monkeypatch.setenv("AWS_ENDPOINT_URL", "http://ambient.example")

        # When
        with patch("src.service.result_store.boto3.client") as mock_client:
            store.client()

        # Then
        kwargs = mock_client.call_args.kwargs
        assert mock_client.call_args.args == ("s3",)
        assert kwargs["endpoint_url"] == "http://store.example:9070"
        assert kwargs["aws_access_key_id"] == "configured-key"
        assert kwargs["aws_secret_access_key"] == "configured-secret"
        assert kwargs["config"].s3 == {"addressing_style": "path"}

    def test_the_client_is_built_once_and_reused(self, store: ResultStore) -> None:
        # When
        with patch("src.service.result_store.boto3.client") as mock_client:
            first = store.client()
            second = store.client()

        # Then
        assert first is second
        assert mock_client.call_count == 1

    def test_the_presigning_client_is_built_against_the_public_endpoint(
        self, store: ResultStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Given
        monkeypatch.setattr(settings, "OCR_RESULT_S3_ENDPOINT", "http://internal.example:9070")
        monkeypatch.setattr(settings, "OCR_RESULT_S3_PUBLIC_ENDPOINT", "http://public.example:9070")

        # When
        with patch("src.service.result_store.boto3.client") as mock_client:
            store.public_client()
            store.public_client()

        # Then
        assert mock_client.call_args.kwargs["endpoint_url"] == "http://public.example:9070"
        assert mock_client.call_count == 1


class TestEnsureBucket:
    def test_an_existing_bucket_is_left_alone(self, store: ResultStore, fake_client: MagicMock) -> None:
        # When
        reachable = store.ensure_bucket()

        # Then
        fake_client.head_bucket.assert_called_once_with(Bucket=settings.OCR_RESULT_S3_BUCKET)
        fake_client.create_bucket.assert_not_called()
        assert reachable is True
        assert store.bucket_reachable is True

    def test_a_missing_bucket_is_created(self, store: ResultStore, fake_client: MagicMock) -> None:
        # Given
        fake_client.head_bucket.side_effect = _client_error("404")

        # When
        reachable = store.ensure_bucket()

        # Then
        fake_client.create_bucket.assert_called_once_with(Bucket=settings.OCR_RESULT_S3_BUCKET)
        assert reachable is True

    def test_a_store_that_does_not_answer_warns_and_lets_the_service_boot(
        self, store: ResultStore, fake_client: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Given
        fake_client.head_bucket.side_effect = OSError("connection refused")
        caplog.set_level("WARNING")

        # When
        reachable = store.ensure_bucket()

        # Then
        assert reachable is False
        assert store.bucket_reachable is False
        assert any(record.levelname == "WARNING" for record in caplog.records)

    def test_a_refused_head_is_not_mistaken_for_a_missing_bucket(
        self, store: ResultStore, fake_client: MagicMock
    ) -> None:
        # Given
        fake_client.head_bucket.side_effect = _client_error("403")

        # When
        reachable = store.ensure_bucket()

        # Then
        fake_client.create_bucket.assert_not_called()
        assert reachable is False


class TestUpload:
    async def test_the_markdown_is_written_under_the_job_identifier(
        self, store: ResultStore, fake_client: MagicMock
    ) -> None:
        # When
        location = await store.upload(JOB_ID, "## Page 1\ntext\n")

        # Then
        assert location.bucket == settings.OCR_RESULT_S3_BUCKET
        assert location.key == f"{JOB_ID}.md"
        fake_client.put_object.assert_called_once_with(
            Bucket=settings.OCR_RESULT_S3_BUCKET,
            Key=f"{JOB_ID}.md",
            Body=b"## Page 1\ntext\n",
            ContentType=MARKDOWN_CONTENT_TYPE,
        )

    async def test_a_transient_failure_is_retried(
        self, store: ResultStore, fake_client: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Given
        monkeypatch.setattr("src.service.result_store.UPLOAD_RETRY_BASE_SECONDS", 0.0)
        fake_client.put_object.side_effect = [OSError("reset by peer"), None]

        # When
        location = await store.upload(JOB_ID, "text")

        # Then
        assert location.key == f"{JOB_ID}.md"
        assert fake_client.put_object.call_count == 2

    async def test_exhausting_the_attempts_raises_the_result_store_failure(
        self, store: ResultStore, fake_client: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Given
        monkeypatch.setattr("src.service.result_store.UPLOAD_RETRY_BASE_SECONDS", 0.0)
        fake_client.put_object.side_effect = OSError("connection refused")

        # When / Then
        with pytest.raises(ResultStoreUnavailableError, match="after 3 attempts"):
            await store.upload(JOB_ID, "text")

        assert fake_client.put_object.call_count == UPLOAD_MAX_ATTEMPTS


class TestPresignedUrl:
    def test_the_url_is_signed_against_the_public_endpoint(
        self, store: ResultStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Given
        monkeypatch.setattr(settings, "OCR_RESULT_S3_ENDPOINT", "http://internal.example:9070")
        monkeypatch.setattr(settings, "OCR_RESULT_S3_PUBLIC_ENDPOINT", "http://public.example:9070")
        internal = MagicMock()
        public = MagicMock()
        public.generate_presigned_url.return_value = "http://public.example:9070/signed"
        store._client = internal
        store._public_client = public

        # When
        url = store.presigned_url(f"{JOB_ID}.md", 600.0)

        # Then
        assert url == "http://public.example:9070/signed"
        internal.generate_presigned_url.assert_not_called()
        assert public.generate_presigned_url.call_args.kwargs["ExpiresIn"] == 600

    def test_the_expiry_never_exceeds_the_remaining_retention(self, store: ResultStore, fake_client: MagicMock) -> None:
        # When
        store.presigned_url(f"{JOB_ID}.md", 42.7)

        # Then — floored, never rounded up past what the object has left
        assert fake_client.generate_presigned_url.call_args.kwargs["ExpiresIn"] == 42

    def test_a_result_a_moment_from_expiry_still_signs(self, store: ResultStore, fake_client: MagicMock) -> None:
        # When
        store.presigned_url(f"{JOB_ID}.md", 0.2)

        # Then — one second rather than an error, because zero is not a valid expiry
        assert fake_client.generate_presigned_url.call_args.kwargs["ExpiresIn"] == 1


class TestDelete:
    def test_deleting_removes_the_object(self, store: ResultStore, fake_client: MagicMock) -> None:
        # When
        store.delete_result(f"{JOB_ID}.md")

        # Then
        fake_client.delete_object.assert_called_once_with(Bucket=settings.OCR_RESULT_S3_BUCKET, Key=f"{JOB_ID}.md")

    def test_deleting_twice_is_not_an_error(self, store: ResultStore, fake_client: MagicMock) -> None:
        # When
        store.delete_result(f"{JOB_ID}.md")
        store.delete_result(f"{JOB_ID}.md")

        # Then
        assert fake_client.delete_object.call_count == 2
