from prometheus_client import generate_latest

from src.observability import metrics


def test_counters_registered() -> None:
    metrics.TRANSCRIPTION_REQUESTS_TOTAL.labels(provider="local", outcome="success").inc()
    metrics.TRANSCRIPTION_BYTES_PROCESSED_TOTAL.labels(provider="openai").inc(1024)
    metrics.AUDACITY_TRACKS_EXTRACTED_TOTAL.inc()
    metrics.FFMPEG_INVOCATIONS_TOTAL.labels(binary="ffmpeg", outcome="success").inc()

    payload = generate_latest().decode()
    for name in (
        "ascendaudioscribe_transcription_requests_total",
        "ascendaudioscribe_transcription_bytes_processed_total",
        "ascendaudioscribe_audacity_tracks_extracted_total",
        "ascendaudioscribe_ffmpeg_invocations_total",
    ):
        assert name in payload


def test_histograms_registered() -> None:
    metrics.TRANSCRIPTION_DURATION_SECONDS.labels(provider="local", outcome="success").observe(1.5)
    metrics.DOWNLOAD_DURATION_SECONDS.observe(0.5)

    payload = generate_latest().decode()
    assert "ascendaudioscribe_transcription_duration_seconds" in payload
    assert "ascendaudioscribe_download_duration_seconds" in payload
