# ADR-003: Whisper model singleton + GPU semaphore

**Date**: 2026-06-01
**Status**: Accepted

---

## Context

The previous local transcription path spawned a new `multiprocessing.spawn` worker per request. Each spawn paid the
full cost of: Python interpreter import, torch + CUDA init, faster-whisper model weights load (3-10 s on
`large-v3`), cuDNN warm-up. For a 30-second clip the cold-start cost easily exceeded the actual inference cost. Two
concurrent requests would each load the model independently, OOMing any consumer GPU on `large-v3`.

The streaming SSE path was also misleading: `local_speech_transcription_stream` blocked on
`result_queue.get()` until ALL segments were done, then yielded them in a batch. SSE consumers saw zero progress for
the entire job, even though the per-segment data was available inside the worker.

---

## Decision

Replace the per-request worker process with a module-level lazy `WhisperModel` singleton guarded by an
`asyncio.Semaphore(1)` so the GPU is serialised. The singleton is constructed on the first call (cold start cost
paid once) and re-loads only when `model_path` changes (rare in practice).

Streaming becomes per-chunk: the audio is sliced on disk via the shared `chunked_audio` ffmpeg-segment helper, each
chunk is transcribed via `asyncio.to_thread(_transcribe_chunk_sync, ...)`, and each resulting segment is yielded
immediately. The first SSE progress event arrives within seconds of the first chunk completing.

(`src/transcription/local_speech_to_text.py`, `src/transcription/audio_chunker.py`)

---

## Alternatives Considered

### Alternative 1: Keep per-request spawned worker for isolation

- **Pros**: A crashing inference can't take down the parent process.
- **Cons**: 3-10 s per-request cold start dominates; concurrent requests OOM the GPU.
- **Why not**: The crash isolation never paid off in practice; warmup cost did.

### Alternative 2: Pool of workers

- **Pros**: Parallel inference across GPUs.
- **Cons**: Significant added complexity. Most deployments have one GPU.
- **Why not**: Wait for measured demand. The semaphore is easy to swap for a worker-pool later.

---

## Consequences

### Positive

- p50 latency on warm requests drops 70-90% (entire cold-start budget eliminated).
- Concurrent requests serialise via the semaphore; no GPU OOM.
- Streaming actually streams; SSE consumers see real per-segment progress.

### Negative

- A crash in `WhisperModel.transcribe` now takes the process down (no worker isolation).
- Memory footprint of the parent process grows by the model size (~3 GB for `large-v3`); previously this was charged
  to the worker process only.

### Risks

- **GPU semaphore starvation**: under heavy load, an `asyncio.Semaphore(1)` queues every request. Long jobs block
  short ones. Mitigation: future deployments with multiple GPUs can bump the semaphore size.
