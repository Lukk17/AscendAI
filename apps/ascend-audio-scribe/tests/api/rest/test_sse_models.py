from src.api.rest.sse_models import SSECompleteEvent, SSEErrorEvent, SSEProgressEvent


def test_progress_event_defaults() -> None:
    # when
    event = SSEProgressEvent(message="hello")

    # then
    assert event.type == "progress"
    assert event.data is None


def test_progress_event_with_data() -> None:
    # when
    event = SSEProgressEvent(message="x", data={"n": 1})

    # then
    assert event.data == {"n": 1}


def test_complete_event_shape() -> None:
    # when
    event = SSECompleteEvent(
        download_url="/api/v1/transcribe/download/abc",
        source="local",
        model="m",
        language="en",
    )

    # then
    assert event.type == "complete"


def test_error_event_shape() -> None:
    # when
    event = SSEErrorEvent(message="bad")

    # then
    assert event.type == "error"
