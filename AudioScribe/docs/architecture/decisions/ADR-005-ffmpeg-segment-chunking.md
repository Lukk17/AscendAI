# ADR-005: ffmpeg-segment chunking (drop pydub full-decode)

**Date**: 2026-06-01
**Status**: Accepted

---

## Context

Both the OpenAI and Hugging Face transcription paths previously used `pydub.AudioSegment.from_file(audio_path)` to
load the entire source audio into a Python-side buffer, then iterated the in-memory buffer chunk-by-chunk, exporting
each chunk to disk via `chunk.export(...)`. For a 1-hour stereo 44.1 kHz file that's ~635 MB of Python memory held
for the entire transcription. The local backend had the same pattern.

---

## Decision

Introduce `src/transcription/audio_chunker.py:chunked_audio(audio_path, chunk_seconds)` — a context manager that
spawns a single `ffmpeg -f segment -segment_time T -ar 16000 -ac 1 -sample_fmt s16` invocation. ffmpeg streams the
input, normalises to 16 kHz mono 16-bit signed, and writes numbered WAV chunks to a temp directory. The context
manager yields the chunk paths; on exit it deletes them.

All three backends (`openai_api_speach_to_text`, `huggingface_api_speach_to_text`, `local_speech_to_text`) use this
helper. No Python-side audio buffer is ever held; ffmpeg does its own streaming I/O.

(`src/transcription/audio_chunker.py`, plus call-sites in each backend)

---

## Alternatives Considered

### Alternative 1: Stick with pydub

- **Pros**: Pure-Python; no subprocess.
- **Cons**: O(audio size) memory.

### Alternative 2: Use a chunked-decode library (e.g. soundfile streaming)

- **Pros**: Stays in-process.
- **Cons**: Adds another dependency; ffmpeg is already required for Audacity processing and is universally available.

---

## Consequences

### Positive

- Constant memory regardless of source size.
- Same normalised chunk shape across all backends; easier to reason about.

### Negative

- Subprocess overhead per request (one ffmpeg invocation per transcription).
- pydub dropped from the runtime hot path; the dependency stays (still used in unit tests historically) but is
  effectively unused in production. Future cleanup opportunity.

### Risks

- **ffmpeg PATH changes**: silently failing chunker = silently failing transcription. The `/ready` probe and
  `FFMPEG_INVOCATIONS_TOTAL` counter surface this fast.
