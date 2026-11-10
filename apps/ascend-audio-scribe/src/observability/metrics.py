from prometheus_client import Counter, Histogram

# Outcome label values: "success" | "error" | "validation_error"
TRANSCRIPTION_REQUESTS_TOTAL = Counter(
    "ascendaudioscribe_transcription_requests_total",
    "Transcription request outcomes",
    ["provider", "outcome"],
)

TRANSCRIPTION_BYTES_PROCESSED_TOTAL = Counter(
    "ascendaudioscribe_transcription_bytes_processed_total",
    "Bytes of source audio processed",
    ["provider"],
)

AUDACITY_TRACKS_EXTRACTED_TOTAL = Counter(
    "ascendaudioscribe_audacity_tracks_extracted_total",
    "Audacity tracks successfully extracted",
)

FFMPEG_INVOCATIONS_TOTAL = Counter(
    "ascendaudioscribe_ffmpeg_invocations_total",
    "ffmpeg/ffprobe invocations",
    ["binary", "outcome"],
)

# Realistic per-backend latency spread: openai (~3-60s), hf (~5-120s), local (~10-600s on CPU).
# outcome label values: "ok" | "error"
TRANSCRIPTION_DURATION_SECONDS = Histogram(
    "transcription_duration_seconds",
    "Wall-clock duration of transcription requests",
    ["provider", "outcome"],
    buckets=(1, 5, 10, 30, 60, 120, 300, 600, 1200),
)

# Input audio length spread: clips (~1-60s), episodes (~600-3600s).
TRANSCRIPTION_AUDIO_DURATION_SECONDS = Histogram(
    "transcription_audio_duration_seconds",
    "Input audio length in seconds",
    ["provider"],
    buckets=(1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600),
)

DOWNLOAD_DURATION_SECONDS = Histogram(
    "ascendaudioscribe_download_duration_seconds",
    "Wall-clock duration of MCP audio_uri fetches",
    buckets=(0.1, 0.5, 1, 5, 10, 30, 60, 120),
)


def record_transcription(
    provider: str, outcome: str, duration_s: float, audio_duration_s: float | None = None
) -> None:
    TRANSCRIPTION_REQUESTS_TOTAL.labels(provider=provider, outcome=outcome).inc()
    TRANSCRIPTION_DURATION_SECONDS.labels(provider=provider, outcome=outcome).observe(duration_s)
    if audio_duration_s is not None:
        TRANSCRIPTION_AUDIO_DURATION_SECONDS.labels(provider=provider).observe(audio_duration_s)
