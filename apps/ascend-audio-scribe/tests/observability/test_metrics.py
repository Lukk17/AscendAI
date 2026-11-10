from prometheus_client import Histogram, generate_latest

from src.observability import metrics


def test_counters_registered() -> None:
    # given
    metrics.TRANSCRIPTION_REQUESTS_TOTAL.labels(provider="local", outcome="ok").inc()
    metrics.TRANSCRIPTION_BYTES_PROCESSED_TOTAL.labels(provider="openai").inc(1024)
    metrics.AUDACITY_TRACKS_EXTRACTED_TOTAL.inc()
    metrics.FFMPEG_INVOCATIONS_TOTAL.labels(binary="ffmpeg", outcome="success").inc()

    # when
    payload = generate_latest().decode()

    # then
    for name in (
        "ascendaudioscribe_transcription_requests_total",
        "ascendaudioscribe_transcription_bytes_processed_total",
        "ascendaudioscribe_audacity_tracks_extracted_total",
        "ascendaudioscribe_ffmpeg_invocations_total",
    ):
        assert name in payload


def test_histograms_registered() -> None:
    # given
    metrics.TRANSCRIPTION_DURATION_SECONDS.labels(provider="local", outcome="ok").observe(1.5)
    metrics.TRANSCRIPTION_AUDIO_DURATION_SECONDS.labels(provider="local").observe(42.0)
    metrics.DOWNLOAD_DURATION_SECONDS.observe(0.5)

    # when
    payload = generate_latest().decode()

    # then
    assert "transcription_duration_seconds" in payload
    assert "transcription_audio_duration_seconds" in payload
    assert "ascendaudioscribe_download_duration_seconds" in payload
    assert "ascendaudioscribe_transcription_duration_seconds" not in payload
    assert isinstance(metrics.TRANSCRIPTION_DURATION_SECONDS, Histogram)
    assert isinstance(metrics.TRANSCRIPTION_AUDIO_DURATION_SECONDS, Histogram)


def _histogram_count(payload: str, name: str, label_filter: str) -> float:
    import re

    match = re.search(rf"^{name}_count\{{{label_filter}\}} (\S+)$", payload, re.MULTILINE)
    if match is None:
        return 0.0
    return float(match.group(1))


def test_record_transcription_observes_both_histograms() -> None:
    # given
    labels = 'outcome="ok",provider="local"'
    before_duration = _histogram_count(generate_latest().decode(), "transcription_duration_seconds", labels)
    before_audio = _histogram_count(
        generate_latest().decode(), "transcription_audio_duration_seconds", 'provider="local"'
    )

    # when
    metrics.record_transcription("local", "ok", 1.5, 42.0)

    # then
    payload = generate_latest().decode()
    assert _histogram_count(payload, "transcription_duration_seconds", labels) - before_duration == 1.0
    assert (
        _histogram_count(payload, "transcription_audio_duration_seconds", 'provider="local"') - before_audio
        == 1.0
    )


def test_record_transcription_without_audio_skips_audio_histogram() -> None:
    # given
    labels = 'outcome="error",provider="local"'
    before_duration = _histogram_count(generate_latest().decode(), "transcription_duration_seconds", labels)
    before_audio = _histogram_count(
        generate_latest().decode(), "transcription_audio_duration_seconds", 'provider="local"'
    )

    # when
    metrics.record_transcription("local", "error", 0.5)

    # then
    payload = generate_latest().decode()
    assert _histogram_count(payload, "transcription_duration_seconds", labels) - before_duration == 1.0
    assert (
        _histogram_count(payload, "transcription_audio_duration_seconds", 'provider="local"') - before_audio
        == 0.0
    )
