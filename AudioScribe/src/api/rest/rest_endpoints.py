"""REST surface.

Single source of truth for `/api/v1/transcribe/*` endpoints. Errors raise
typed exceptions (ValueError, FileSizeExceededError) which the global
RFC 7807 handlers in `src.api.exception_handlers` translate to
problem-document responses. SSE streams use the typed events in
`src.api.rest.sse_models`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
import time
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from src.adapters.download_file_manager import (
    cleanup_expired,
    get_transcript_path,
    remove_transcript,
    store_transcript,
)
from src.adapters.file_service import cleanup_temp_file, save_upload_to_temp_async
from src.config.config import settings
from src.observability.metrics import (
    TRANSCRIPTION_DURATION_SECONDS,
    TRANSCRIPTION_REQUESTS_TOTAL,
)
from src.scribe import (
    hf_speech_transcription,
    local_speech_transcription,
    openai_speech_transcription,
)
from src.transcription.audacity_parser import extract_tracks_from_aup
from src.transcription.conversation_merger import transcribe_and_merge_tracks

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

logger = logging.getLogger(__name__)

rest_router = APIRouter(prefix="/api/v1/transcribe", tags=["transcribe"])

# --- Constants for duplicated literals ------------------------------------

SSE_MEDIA_TYPE = "text/event-stream"
MARKDOWN_MEDIA_TYPE = "text/markdown"

TRANSCRIPT_LOCAL_FILENAME = "transcript_local.md"
TRANSCRIPT_OPENAI_FILENAME = "transcript_openai.md"
TRANSCRIPT_HF_FILENAME = "transcript_hf.md"
TRANSCRIPT_AUDACITY_FILENAME = "transcript_audacity.md"

PROVIDER_LOCAL = "local"
PROVIDER_OPENAI = "openai"
PROVIDER_HF = "huggingface"

SSE_PROGRESS = "progress"
SSE_COMPLETE = "complete"
SSE_ERROR = "error"

DOWNLOAD_URL_PREFIX = "/api/v1/transcribe/download"
INTERNAL_ERROR_MESSAGE = "Internal transcription error"

SSE_POLL_TIMEOUT_SECONDS = 0.5
SSE_QUEUE_MAXSIZE = 200
AUDACITY_SSE_QUEUE_MAXSIZE = 400

# --- Annotated query/form aliases -----------------------------------------
# Defaults belong on the `= ...` part per FastAPI rule.

LanguageForm = Annotated[
    str | None,
    Form(
        max_length=16,
        pattern=settings.LANGUAGE_PATTERN,
        description="ISO 639-1/2 language code; falls back to TRANSCRIPTION_LANGUAGE",
    ),
]
ModelForm = Annotated[str, Form(max_length=128, pattern=settings.MODEL_PATTERN)]
StreamForm = Annotated[bool, Form(description="True returns an SSE stream; False returns the file")]
HfProviderForm = Annotated[str, Form(max_length=32, pattern=settings.PROVIDER_PATTERN)]
ProviderForm = Annotated[
    str, Form(max_length=16, pattern=r"^(local|openai|huggingface)$")
]
WithTimestampsForm = Annotated[bool, Form(description="Include per-segment timestamps in output")]


# --- Pure helpers ---------------------------------------------------------


def _sse_event(data: dict[str, Any]) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _build_transcript_text(segments: list[dict[str, Any]], with_timestamps: bool) -> str:
    if with_timestamps:
        return "\n".join(f"[{s['start']:.2f} - {s['end']:.2f}] {s['text']}" for s in segments)
    return " ".join(s["text"] for s in segments)


def _resolve_language(language: str | None) -> str:
    """Narrow `str | None` to `str` for downstream call sites — explicit
    `if` so static analysers tighten the type."""

    if language is None or language == "":
        return settings.TRANSCRIPTION_LANGUAGE
    return language


def _file_response(file_path: str, filename: str) -> FileResponse:
    return FileResponse(
        path=file_path,
        media_type=MARKDOWN_MEDIA_TYPE,
        filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _record(provider: str, outcome: str, duration_s: float) -> None:
    TRANSCRIPTION_REQUESTS_TOTAL.labels(provider=provider, outcome=outcome).inc()
    if outcome == "success":
        TRANSCRIPTION_DURATION_SECONDS.labels(provider=provider).observe(duration_s)


def _coerce_response_text(response_text: Any) -> str:
    """Backend functions return either `str` (text mode) or `list[dict]`
    (with-timestamps mode). For the file-response path we always store a
    string — JSON-serialise the list when needed."""

    if isinstance(response_text, str):
        return response_text
    return json.dumps(response_text, ensure_ascii=False)


def _complete_event(file_id: str, source: str, model: str, language: str) -> dict[str, Any]:
    return {
        "type": SSE_COMPLETE,
        "download_url": f"{DOWNLOAD_URL_PREFIX}/{file_id}",
        "source": source,
        "model": model,
        "language": language,
    }


def _error_event(exc: Exception) -> dict[str, Any]:
    message = str(exc) if isinstance(exc, ValueError) else INTERNAL_ERROR_MESSAGE
    return {"type": SSE_ERROR, "message": message}


async def _drain_progress_queue(
    progress_queue: asyncio.Queue[dict[str, Any]],
    task: asyncio.Task[Any],
) -> AsyncIterator[str]:
    """Shared SSE polling loop used by every threaded backend (openai, hf,
    audacity). Poll the progress queue while the background task runs, then
    drain any tail events. CancelledError propagates to the caller after
    cancelling the task — client mid-stream disconnect path."""

    try:
        while not task.done():
            try:
                event = await asyncio.wait_for(
                    progress_queue.get(), timeout=SSE_POLL_TIMEOUT_SECONDS
                )
                yield _sse_event(event)
            except TimeoutError:
                continue
        while not progress_queue.empty():
            yield _sse_event(progress_queue.get_nowait())
    except asyncio.CancelledError:
        task.cancel()
        raise


# --- /download/{file_id} -------------------------------------------------


@rest_router.get("/download/{file_id}", summary="Download transcript file")
def download_transcript(file_id: str) -> FileResponse:
    """Sync `def` — every call inside is sync (registry lookup, FileResponse
    construction); no awaitable work exists."""

    cleanup_expired()
    file_path = get_transcript_path(file_id)
    if not file_path:
        raise HTTPException(status_code=404, detail="Transcript not found or expired.")
    return _file_response(file_path, os.path.basename(file_path))


# --- /local --------------------------------------------------------------


@rest_router.post("/local", summary="Transcription with a local model", response_model=None)
async def transcribe_local_endpoint(
    file: Annotated[UploadFile, File(...)],
    model: ModelForm = "Systran/faster-whisper-large-v3",
    language: LanguageForm = None,
    with_timestamps: WithTimestampsForm = False,
    stream: StreamForm = False,
) -> FileResponse | StreamingResponse:
    lang = _resolve_language(language)

    if stream:
        return StreamingResponse(
            _stream_local(file, model, lang, with_timestamps),
            media_type=SSE_MEDIA_TYPE,
        )

    started = time.monotonic()
    temp_file_path = ""
    try:
        temp_file_path = await save_upload_to_temp_async(file)
        all_segments: list[dict[str, Any]] = []
        async for segment in local_speech_transcription(
            audio_file_path=temp_file_path, model_path=model, language=lang
        ):
            all_segments.append(segment)
        transcript_text = _build_transcript_text(all_segments, with_timestamps)
        _, file_path = store_transcript(transcript_text, TRANSCRIPT_LOCAL_FILENAME)
        _record(PROVIDER_LOCAL, "success", time.monotonic() - started)
        return _file_response(file_path, TRANSCRIPT_LOCAL_FILENAME)
    except Exception:
        _record(PROVIDER_LOCAL, "error", time.monotonic() - started)
        raise
    finally:
        # cleanup_temp_file is a no-op on empty/None; no outer guard needed.
        cleanup_temp_file(temp_file_path)


async def _stream_local(
    file: UploadFile, model: str, lang: str, with_timestamps: bool
) -> AsyncIterator[str]:
    temp_file_path = ""
    started = time.monotonic()
    try:
        temp_file_path = await save_upload_to_temp_async(file)
        yield _sse_event({"type": SSE_PROGRESS, "message": "File uploaded, starting local transcription"})

        all_segments: list[dict[str, Any]] = []
        segment_count = 0
        async for segment in local_speech_transcription(
            audio_file_path=temp_file_path, model_path=model, language=lang
        ):
            all_segments.append(segment)
            segment_count += 1
            yield _sse_event({
                "type": SSE_PROGRESS,
                "message": f"Segment {segment_count}: {segment.get('text', '')[:60]}",
                "data": {"segments": segment_count, "start": segment["start"], "end": segment["end"]},
            })

        transcript_text = _build_transcript_text(all_segments, with_timestamps)
        file_id, _ = store_transcript(transcript_text, TRANSCRIPT_LOCAL_FILENAME)
        _record(PROVIDER_LOCAL, "success", time.monotonic() - started)
        yield _sse_event(_complete_event(file_id, PROVIDER_LOCAL, model, lang))
    except Exception as exc:
        _record(PROVIDER_LOCAL, "error", time.monotonic() - started)
        logger.exception("SSE local transcription failed")
        yield _sse_event(_error_event(exc))
    finally:
        # cleanup_temp_file is a no-op on empty/None; no outer guard needed.
        cleanup_temp_file(temp_file_path)


# --- /openai -------------------------------------------------------------


@rest_router.post("/openai", summary="Transcription with OpenAI API", response_model=None)
async def transcribe_openai_endpoint(
    file: Annotated[UploadFile, File(...)],
    model: ModelForm = "whisper-1",
    language: LanguageForm = None,
    stream: StreamForm = False,
) -> FileResponse | StreamingResponse:
    if not settings.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is not configured on the server.")

    lang = _resolve_language(language)
    if stream:
        return StreamingResponse(
            _stream_openai(file, model, lang),
            media_type=SSE_MEDIA_TYPE,
        )

    started = time.monotonic()
    temp_file_path = ""
    try:
        temp_file_path = await save_upload_to_temp_async(file)
        response_text = await asyncio.to_thread(
            openai_speech_transcription,
            audio_file_path=temp_file_path,
            model=model,
            language=lang,
        )
        transcript_text = _coerce_response_text(response_text)
        _, file_path = store_transcript(transcript_text, TRANSCRIPT_OPENAI_FILENAME)
        _record(PROVIDER_OPENAI, "success", time.monotonic() - started)
        return _file_response(file_path, TRANSCRIPT_OPENAI_FILENAME)
    except Exception:
        _record(PROVIDER_OPENAI, "error", time.monotonic() - started)
        raise
    finally:
        # cleanup_temp_file is a no-op on empty/None; no outer guard needed.
        cleanup_temp_file(temp_file_path)
        await file.close()


def _make_progress_queue(maxsize: int = SSE_QUEUE_MAXSIZE) -> asyncio.Queue[dict[str, Any]]:
    return asyncio.Queue(maxsize=maxsize)


def _spawn_threaded_transcription(
    fn: Callable[..., Any],
    progress_queue: asyncio.Queue[dict[str, Any]],
    **kwargs: Any,
) -> asyncio.Task[Any]:
    return asyncio.create_task(
        asyncio.to_thread(fn, progress_callback=progress_queue.put_nowait, **kwargs)
    )


async def _stream_openai(file: UploadFile, model: str, lang: str) -> AsyncIterator[str]:
    temp_file_path = ""
    started = time.monotonic()
    try:
        temp_file_path = await save_upload_to_temp_async(file)
        yield _sse_event({"type": SSE_PROGRESS, "message": "File uploaded, starting OpenAI transcription"})

        progress_queue = _make_progress_queue()
        task = _spawn_threaded_transcription(
            openai_speech_transcription,
            progress_queue,
            audio_file_path=temp_file_path,
            model=model,
            language=lang,
        )
        async for event in _drain_progress_queue(progress_queue, task):
            yield event

        response_text = await task
        transcript_text = _coerce_response_text(response_text)
        file_id, _ = store_transcript(transcript_text, TRANSCRIPT_OPENAI_FILENAME)
        _record(PROVIDER_OPENAI, "success", time.monotonic() - started)
        yield _sse_event(_complete_event(file_id, PROVIDER_OPENAI, model, lang))
    except Exception as exc:
        _record(PROVIDER_OPENAI, "error", time.monotonic() - started)
        logger.exception("SSE OpenAI transcription failed")
        yield _sse_event(_error_event(exc))
    finally:
        # cleanup_temp_file is a no-op on empty/None; no outer guard needed.
        cleanup_temp_file(temp_file_path)
        await file.close()


# --- /hf -----------------------------------------------------------------


@rest_router.post("/hf", summary="Transcription with Hugging Face provider", response_model=None)
async def transcribe_hf_endpoint(
    file: Annotated[UploadFile, File(...)],
    model: ModelForm = "openai/whisper-large-v3",
    hf_provider: HfProviderForm = "hf-inference",
    stream: StreamForm = False,
) -> FileResponse | StreamingResponse:
    if not settings.HF_TOKEN:
        raise ValueError("HF_TOKEN is not configured on the server.")

    if stream:
        return StreamingResponse(
            _stream_hf(file, model, hf_provider),
            media_type=SSE_MEDIA_TYPE,
        )

    started = time.monotonic()
    temp_file_path = ""
    try:
        temp_file_path = await save_upload_to_temp_async(file)
        response_text = await asyncio.to_thread(
            hf_speech_transcription,
            audio_file_path=temp_file_path,
            model=model,
            provider=hf_provider,
        )
        transcript_text = _coerce_response_text(response_text)
        _, file_path = store_transcript(transcript_text, TRANSCRIPT_HF_FILENAME)
        _record(PROVIDER_HF, "success", time.monotonic() - started)
        return _file_response(file_path, TRANSCRIPT_HF_FILENAME)
    except Exception:
        _record(PROVIDER_HF, "error", time.monotonic() - started)
        raise
    finally:
        # cleanup_temp_file is a no-op on empty/None; no outer guard needed.
        cleanup_temp_file(temp_file_path)
        await file.close()


async def _stream_hf(file: UploadFile, model: str, hf_provider: str) -> AsyncIterator[str]:
    temp_file_path = ""
    started = time.monotonic()
    try:
        temp_file_path = await save_upload_to_temp_async(file)
        yield _sse_event({
            "type": SSE_PROGRESS,
            "message": "File uploaded, starting Hugging Face transcription",
        })

        progress_queue = _make_progress_queue()
        task = _spawn_threaded_transcription(
            hf_speech_transcription,
            progress_queue,
            audio_file_path=temp_file_path,
            model=model,
            provider=hf_provider,
        )
        async for event in _drain_progress_queue(progress_queue, task):
            yield event

        response_text = await task
        transcript_text = _coerce_response_text(response_text)
        file_id, _ = store_transcript(transcript_text, TRANSCRIPT_HF_FILENAME)
        _record(PROVIDER_HF, "success", time.monotonic() - started)
        yield _sse_event(_complete_event(file_id, PROVIDER_HF, model, "auto"))
    except Exception as exc:
        _record(PROVIDER_HF, "error", time.monotonic() - started)
        logger.exception("SSE HF transcription failed")
        yield _sse_event(_error_event(exc))
    finally:
        # cleanup_temp_file is a no-op on empty/None; no outer guard needed.
        cleanup_temp_file(temp_file_path)
        await file.close()


# --- /audacity -----------------------------------------------------------


@rest_router.post("/audacity", summary="Transcription of Audacity project (.zip)", response_model=None)
async def transcribe_audacity_endpoint(
    file: Annotated[UploadFile, File(...)],
    provider: ProviderForm = "local",
    model: ModelForm = "Systran/faster-whisper-large-v3",
    language: LanguageForm = None,
    hf_provider: HfProviderForm = "hf-inference",
    stream: StreamForm = False,
) -> FileResponse | StreamingResponse:
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise ValueError("File must be a .zip containing an Audacity project.")

    lang = _resolve_language(language)
    if stream:
        return StreamingResponse(
            _stream_audacity(file, provider, model, lang, hf_provider),
            media_type=SSE_MEDIA_TYPE,
        )

    started = time.monotonic()
    temp_zip_path = ""
    extraction_dir = tempfile.mkdtemp(prefix="audacity_")
    try:
        temp_zip_path = await save_upload_to_temp_async(file)
        tracks = await asyncio.to_thread(
            extract_tracks_from_aup, temp_zip_path, extraction_dir
        )
        if not tracks:
            raise ValueError("No usable audio tracks found in the uploaded Audacity project.")

        transcription_text = await transcribe_and_merge_tracks(
            tracks=tracks, provider=provider, model=model, language=lang, hf_provider=hf_provider
        )
        _, file_path = store_transcript(transcription_text, TRANSCRIPT_AUDACITY_FILENAME)
        _record(provider, "success", time.monotonic() - started)
        return _file_response(file_path, TRANSCRIPT_AUDACITY_FILENAME)
    except Exception:
        _record(provider, "error", time.monotonic() - started)
        raise
    finally:
        cleanup_temp_file(temp_zip_path)
        shutil.rmtree(extraction_dir, ignore_errors=True)
        await file.close()


async def _stream_audacity(
    file: UploadFile, provider: str, model: str, lang: str, hf_provider: str
) -> AsyncIterator[str]:
    temp_zip_path = ""
    extraction_dir = tempfile.mkdtemp(prefix="audacity_")
    started = time.monotonic()
    try:
        temp_zip_path = await save_upload_to_temp_async(file)
        yield _sse_event({"type": SSE_PROGRESS, "message": "ZIP uploaded, extracting Audacity project"})

        tracks: dict[str, str] = await asyncio.to_thread(
            extract_tracks_from_aup, temp_zip_path, extraction_dir
        )
        if not tracks:
            yield _sse_event({
                "type": SSE_ERROR,
                "message": "No usable audio tracks found in the uploaded Audacity project.",
            })
            return

        yield _sse_event({
            "type": SSE_PROGRESS,
            "message": f"Extracted {len(tracks)} tracks, starting transcription",
            "data": {"tracks": list(tracks.keys())},
        })

        progress_queue = _make_progress_queue(AUDACITY_SSE_QUEUE_MAXSIZE)
        task = asyncio.create_task(
            transcribe_and_merge_tracks(
                tracks=tracks,
                provider=provider,
                model=model,
                language=lang,
                hf_provider=hf_provider,
                progress_callback=progress_queue.put_nowait,
            )
        )
        async for event in _drain_progress_queue(progress_queue, task):
            yield event

        transcription_text = await task
        file_id, _ = store_transcript(transcription_text, TRANSCRIPT_AUDACITY_FILENAME)
        _record(provider, "success", time.monotonic() - started)
        yield _sse_event(_complete_event(file_id, provider, model, lang))
    except Exception as exc:
        _record(provider, "error", time.monotonic() - started)
        logger.exception("SSE Audacity transcription failed")
        yield _sse_event(_error_event(exc))
    finally:
        cleanup_temp_file(temp_zip_path)
        shutil.rmtree(extraction_dir, ignore_errors=True)
        await file.close()


# Re-export to keep import side-effects from old tests working.
__all__ = [
    "remove_transcript",
    "rest_router",
]
