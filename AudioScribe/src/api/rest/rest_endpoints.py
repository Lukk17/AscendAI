import asyncio
import json
import os
import shutil
import tempfile
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, UploadFile, File, HTTPException, Form
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse

from src.adapters.download_file_manager import store_transcript, get_transcript_path, remove_transcript, cleanup_expired
from src.adapters.file_service import save_upload_to_temp_async, cleanup_temp_file
from src.config.config import settings
from src.scribe import openai_speech_transcription, local_speech_transcription, hf_speech_transcription
from src.transcription.audacity_parser import extract_tracks_from_aup
from src.transcription.conversation_merger import transcribe_and_merge_tracks

rest_router = APIRouter()


def _sse_event(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _build_timestamp_response(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{"text": s['text'], "timestamp": (s['start'], s['end'])} for s in segments]


def _build_text_only_response(segments: List[Dict[str, Any]]) -> str:
    return " ".join([s['text'] for s in segments])


def _build_transcript_text(segments: List[Dict[str, Any]], with_timestamps: bool) -> str:
    if with_timestamps:
        lines = []
        for s in segments:
            lines.append(f"[{s['start']:.2f} - {s['end']:.2f}] {s['text']}")
        return "\n".join(lines)
    return " ".join([s['text'] for s in segments])


@rest_router.get("/api/v1/transcribe/download/{file_id}", summary="Download transcript file")
async def download_transcript(file_id: str):
    cleanup_expired()
    file_path = get_transcript_path(file_id)
    if not file_path:
        raise HTTPException(status_code=404, detail="Transcript not found or expired.")

    filename = os.path.basename(file_path)
    return FileResponse(
        path=file_path,
        media_type="text/markdown",
        filename=filename,
        headers={"Content-Disposition": f"attachment; filename=\"{filename}\""}
    )


@rest_router.post("/api/v1/transcribe/local", summary="Transcription with a local model")
async def transcribe_local_endpoint(
        file: UploadFile = File(...),
        model: str = Form("Systran/faster-whisper-large-v3"),
        language: Optional[str] = Form(None),
        with_timestamps: bool = Form(False),
        stream: bool = Form(False)
):
    lang = language if language else settings.TRANSCRIPTION_LANGUAGE

    if stream:
        return StreamingResponse(_stream_local(file, model, lang, with_timestamps), media_type="text/event-stream")

    temp_file_path = None
    try:
        temp_file_path = await save_upload_to_temp_async(file)

        all_segments = [segment async for segment in local_speech_transcription(
            audio_file_path=temp_file_path, model_path=model, language=lang
        )]

        transcript_text = _build_transcript_text(all_segments, with_timestamps)
        file_id = store_transcript(transcript_text, "transcript_local.md")
        download_url = f"/api/v1/transcribe/download/{file_id}"

        return FileResponse(
            path=get_transcript_path(file_id),
            media_type="text/markdown",
            filename="transcript_local.md",
            headers={"Content-Disposition": "attachment; filename=\"transcript_local.md\""}
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {e}")
    finally:
        if temp_file_path:
            cleanup_temp_file(temp_file_path)


async def _stream_local(file: UploadFile, model: str, lang: str, with_timestamps: bool):
    temp_file_path = None
    try:
        temp_file_path = await save_upload_to_temp_async(file)
        yield _sse_event({"type": "progress", "message": "File uploaded, starting local transcription"})

        all_segments = []
        segment_count = 0
        async for segment in local_speech_transcription(audio_file_path=temp_file_path, model_path=model, language=lang):
            all_segments.append(segment)
            segment_count += 1
            if segment_count % 10 == 0:
                yield _sse_event({"type": "progress", "message": f"Transcribed {segment_count} segments",
                                  "data": {"segments": segment_count}})

        transcript_text = _build_transcript_text(all_segments, with_timestamps)
        file_id = store_transcript(transcript_text, "transcript_local.md")

        yield _sse_event({"type": "complete", "download_url": f"/api/v1/transcribe/download/{file_id}",
                          "source": "local", "model": model, "language": lang})
    except Exception as e:
        yield _sse_event({"type": "error", "message": str(e)})
    finally:
        if temp_file_path:
            cleanup_temp_file(temp_file_path)


@rest_router.post("/api/v1/transcribe/openai", summary="Transcription with OpenAI API")
async def transcribe_openai_endpoint(
        file: UploadFile = File(...),
        model: str = Form("whisper-1"),
        language: Optional[str] = Form(None),
        stream: bool = Form(False)
):
    if not settings.OPENAI_API_KEY:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not configured on the server.")

    lang = language if language else settings.TRANSCRIPTION_LANGUAGE

    if stream:
        return StreamingResponse(_stream_openai(file, model, lang), media_type="text/event-stream")

    temp_file_path = None
    try:
        temp_file_path = await save_upload_to_temp_async(file)
        response_text = await asyncio.to_thread(
            openai_speech_transcription, audio_file_path=temp_file_path, model=model, language=lang
        )

        transcript_text = response_text if isinstance(response_text, str) else json.dumps(response_text, ensure_ascii=False)
        file_id = store_transcript(transcript_text, "transcript_openai.md")

        return FileResponse(
            path=get_transcript_path(file_id),
            media_type="text/markdown",
            filename="transcript_openai.md",
            headers={"Content-Disposition": "attachment; filename=\"transcript_openai.md\""}
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except IOError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {e}")
    finally:
        if temp_file_path:
            cleanup_temp_file(temp_file_path)
        await file.close()


async def _stream_openai(file: UploadFile, model: str, lang: str):
    temp_file_path = None
    try:
        temp_file_path = await save_upload_to_temp_async(file)
        yield _sse_event({"type": "progress", "message": "File uploaded, starting OpenAI transcription"})

        progress_queue: asyncio.Queue = asyncio.Queue()

        task = asyncio.create_task(asyncio.to_thread(
            openai_speech_transcription, audio_file_path=temp_file_path, model=model, language=lang,
            progress_callback=progress_queue.put_nowait
        ))

        while not task.done():
            try:
                event = await asyncio.wait_for(progress_queue.get(), timeout=0.5)
                yield _sse_event(event)
            except asyncio.TimeoutError:
                continue

        while not progress_queue.empty():
            yield _sse_event(progress_queue.get_nowait())

        response_text = task.result()
        transcript_text = response_text if isinstance(response_text, str) else json.dumps(response_text, ensure_ascii=False)
        file_id = store_transcript(transcript_text, "transcript_openai.md")

        yield _sse_event({"type": "complete", "download_url": f"/api/v1/transcribe/download/{file_id}",
                          "source": "openai", "model": model, "language": lang})
    except Exception as e:
        yield _sse_event({"type": "error", "message": str(e)})
    finally:
        if temp_file_path:
            cleanup_temp_file(temp_file_path)
        await file.close()


@rest_router.post("/api/v1/transcribe/hf", summary="Transcription with Hugging Face provider")
async def transcribe_hf_endpoint(
        file: UploadFile = File(...),
        model: str = Form("openai/whisper-large-v3"),
        hf_provider: str = Form("hf-inference"),
        stream: bool = Form(False)
):
    if not settings.HF_TOKEN:
        raise HTTPException(status_code=500, detail="HF_TOKEN is not configured on the server.")

    if stream:
        return StreamingResponse(_stream_hf(file, model, hf_provider), media_type="text/event-stream")

    temp_file_path = None
    try:
        temp_file_path = await save_upload_to_temp_async(file)
        response_text = await asyncio.to_thread(
            hf_speech_transcription, audio_file_path=temp_file_path, model=model, provider=hf_provider
        )

        transcript_text = response_text if isinstance(response_text, str) else json.dumps(response_text, ensure_ascii=False)
        file_id = store_transcript(transcript_text, "transcript_hf.md")

        return FileResponse(
            path=get_transcript_path(file_id),
            media_type="text/markdown",
            filename="transcript_hf.md",
            headers={"Content-Disposition": "attachment; filename=\"transcript_hf.md\""}
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except IOError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {e}")
    finally:
        if temp_file_path:
            cleanup_temp_file(temp_file_path)
        await file.close()


async def _stream_hf(file: UploadFile, model: str, hf_provider: str):
    temp_file_path = None
    try:
        temp_file_path = await save_upload_to_temp_async(file)
        yield _sse_event({"type": "progress", "message": "File uploaded, starting Hugging Face transcription"})

        progress_queue: asyncio.Queue = asyncio.Queue()

        task = asyncio.create_task(asyncio.to_thread(
            hf_speech_transcription, audio_file_path=temp_file_path, model=model, provider=hf_provider,
            progress_callback=progress_queue.put_nowait
        ))

        while not task.done():
            try:
                event = await asyncio.wait_for(progress_queue.get(), timeout=0.5)
                yield _sse_event(event)
            except asyncio.TimeoutError:
                continue

        while not progress_queue.empty():
            yield _sse_event(progress_queue.get_nowait())

        response_text = task.result()
        transcript_text = response_text if isinstance(response_text, str) else json.dumps(response_text, ensure_ascii=False)
        file_id = store_transcript(transcript_text, "transcript_hf.md")

        yield _sse_event({"type": "complete", "download_url": f"/api/v1/transcribe/download/{file_id}",
                          "source": "huggingface", "model": model, "language": "auto"})
    except Exception as e:
        yield _sse_event({"type": "error", "message": str(e)})
    finally:
        if temp_file_path:
            cleanup_temp_file(temp_file_path)
        await file.close()


@rest_router.post("/api/v1/transcribe/audacity", summary="Transcription of Audacity project (.zip)")
async def transcribe_audacity_endpoint(
        file: UploadFile = File(...),
        provider: str = Form("local"),
        model: str = Form("Systran/faster-whisper-large-v3"),
        language: Optional[str] = Form(None),
        hf_provider: str = Form("hf-inference"),
        stream: bool = Form(False)
):
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="File must be a .zip containing an Audacity project.")

    lang = language if language else settings.TRANSCRIPTION_LANGUAGE

    if stream:
        return StreamingResponse(_stream_audacity(file, provider, model, lang, hf_provider), media_type="text/event-stream")

    temp_zip_path = None
    extraction_dir = tempfile.mkdtemp(prefix="audacity_")

    try:
        temp_zip_path = await save_upload_to_temp_async(file)
        tracks = await asyncio.to_thread(extract_tracks_from_aup, temp_zip_path, extraction_dir)

        if not tracks:
            raise HTTPException(status_code=400, detail="No usable audio tracks found in the uploaded Audacity project.")

        transcription_text = await transcribe_and_merge_tracks(
            tracks=tracks, provider=provider, model=model, language=lang, hf_provider=hf_provider
        )

        file_id = store_transcript(transcription_text, "transcript_audacity.md")

        return FileResponse(
            path=get_transcript_path(file_id),
            media_type="text/markdown",
            filename="transcript_audacity.md",
            headers={"Content-Disposition": "attachment; filename=\"transcript_audacity.md\""}
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {e}")
    finally:
        if temp_zip_path:
            cleanup_temp_file(temp_zip_path)
        if os.path.exists(extraction_dir):
            shutil.rmtree(extraction_dir, ignore_errors=True)
        await file.close()


async def _stream_audacity(file: UploadFile, provider: str, model: str, lang: str, hf_provider: str):
    temp_zip_path = None
    extraction_dir = tempfile.mkdtemp(prefix="audacity_")

    try:
        temp_zip_path = await save_upload_to_temp_async(file)
        yield _sse_event({"type": "progress", "message": "ZIP uploaded, extracting Audacity project"})

        tracks = await asyncio.to_thread(extract_tracks_from_aup, temp_zip_path, extraction_dir)

        if not tracks:
            yield _sse_event({"type": "error", "message": "No usable audio tracks found in the uploaded Audacity project."})
            return

        yield _sse_event({"type": "progress", "message": f"Extracted {len(tracks)} tracks, starting transcription",
                          "data": {"tracks": list(tracks.keys())}})

        progress_queue: asyncio.Queue = asyncio.Queue()

        task = asyncio.create_task(
            transcribe_and_merge_tracks(
                tracks=tracks, provider=provider, model=model, language=lang,
                hf_provider=hf_provider, progress_callback=progress_queue.put_nowait
            )
        )

        while not task.done():
            try:
                event = await asyncio.wait_for(progress_queue.get(), timeout=0.5)
                yield _sse_event(event)
            except asyncio.TimeoutError:
                continue

        while not progress_queue.empty():
            yield _sse_event(progress_queue.get_nowait())

        transcription_text = task.result()
        file_id = store_transcript(transcription_text, "transcript_audacity.md")

        yield _sse_event({"type": "complete", "download_url": f"/api/v1/transcribe/download/{file_id}",
                          "source": provider, "model": model, "language": lang})
    except Exception as e:
        yield _sse_event({"type": "error", "message": str(e)})
    finally:
        if temp_zip_path:
            cleanup_temp_file(temp_zip_path)
        if os.path.exists(extraction_dir):
            shutil.rmtree(extraction_dir, ignore_errors=True)
        await file.close()
