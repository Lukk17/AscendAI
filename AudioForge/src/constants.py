"""Application constants."""

# File processing prefixes
PROCESSED = "processed"
TRIMMED = "trimmed"
CONVERTED = "converted"

# Default values
DEFAULT_AUDIO_NAME = "audio"
WAVE_FORMAT = "wav"
DEFAULT_FORMAT = WAVE_FORMAT
DEFAULT_SAMPLE_RATE = 16000

PRESERVE_SAMPLE_RATE = 0

# SoX silence removal settings (optimized for Whisper transcription)
DEFAULT_SILENCE_DURATION = "0.5"  # seconds
DEFAULT_SILENCE_THRESHOLD = "0.05"  # 5% amplitude threshold
