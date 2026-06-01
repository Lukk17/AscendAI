from src.api.rest.sse_models import SSECompleteEvent, SSEErrorEvent, SSEProgressEvent


def test_progress_event_defaults() -> None:
    event = SSEProgressEvent(message="hello")
    assert event.type == "progress"
    assert event.data is None


def test_progress_event_with_data() -> None:
    event = SSEProgressEvent(message="x", data={"n": 1})
    assert event.data == {"n": 1}


def test_complete_event_shape() -> None:
    event = SSECompleteEvent(
        download_url="/api/v1/transcribe/download/abc",
        source="local",
        model="m",
        language="en",
    )
    assert event.type == "complete"


def test_error_event_shape() -> None:
    event = SSEErrorEvent(message="bad")
    assert event.type == "error"
