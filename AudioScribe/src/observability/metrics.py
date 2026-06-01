from prometheus_client import Counter, Histogram

# Outcome label values: "success" | "error" | "validation_error"
TRANSCRIPTION_REQUESTS_TOTAL = Counter(
    "audioscribe_transcription_requests_total",
    "Transcription request outcomes",
    ["provider", "outcome"],
)

TRANSCRIPTION_BYTES_PROCESSED_TOTAL = Counter(
    "audioscribe_transcription_bytes_processed_total",
    "Bytes of source audio processed",
    ["provider"],
)

AUDACITY_TRACKS_EXTRACTED_TOTAL = Counter(
    "audioscribe_audacity_tracks_extracted_total",
    "Audacity tracks successfully extracted",
)

FFMPEG_INVOCATIONS_TOTAL = Counter(
    "audioscribe_ffmpeg_invocations_total",
    "ffmpeg/ffprobe invocations",
    ["binary", "outcome"],
)

# Realistic per-backend latency spread: openai (~3-60s), hf (~5-120s), local (~10-600s on CPU).
TRANSCRIPTION_DURATION_SECONDS = Histogram(
    "audioscribe_transcription_duration_seconds",
    "Wall-clock duration of transcription requests",
    ["provider"],
    buckets=(1, 5, 10, 30, 60, 120, 300, 600, 1200),
)

DOWNLOAD_DURATION_SECONDS = Histogram(
    "audioscribe_download_duration_seconds",
    "Wall-clock duration of MCP audio_uri fetches",
    buckets=(0.1, 0.5, 1, 5, 10, 30, 60, 120),
)
