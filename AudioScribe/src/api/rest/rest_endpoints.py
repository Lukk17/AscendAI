import asyncio
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, UploadFile, File, HTTPException, Form
from fastapi.responses import JSONResponse

from src.adapters.file_service import save_upload_to_temp_async, cleanup_temp_file
from src.config.config import settings
from src.scribe import openai_speech_transcription, local_speech_transcription, hf_speech_transcription
from src.transcription.audacity_parser import extract_tracks_from_aup
from src.transcription.conversation_merger import transcribe_and_merge_tracks
import tempfile
import shutil
import os

rest_router = APIRouter()


def _build_timestamp_response(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Builds a list of segments with timestamps."""
    return [{"text": s['text'], "timestamp": (s['start'], s['end'])} for s in segments]


def _build_text_only_response(segments: List[Dict[str, Any]]) -> str:
    """Builds a single text block from segments."""
    return " ".join([s['text'] for s in segments])


@rest_router.post("/api/v1/transcribe/local", summary="Transcription with a local model")
async def transcribe_local_endpoint(
        file: UploadFile = File(...),
        model: str = Form("Systran/faster-whisper-large-v3"),
        language: Optional[str] = Form(None),
        with_timestamps: bool = Form(False)
):
    """
    Transcribes an audio file using a faster-whisper compatible model.
    - **with_timestamps**: If true, returns a JSON array of segments with timestamps.
      If false, returns a single JSON object with the full transcribed text.
    """
    lang = language if language else settings.TRANSCRIPTION_LANGUAGE
    temp_file_path = None
    try:
        temp_file_path = await save_upload_to_temp_async(file)

        all_segments = [segment async for segment in local_speech_transcription(
            audio_file_path=temp_file_path,
            model_path=model,
            language=lang
        )]

        if with_timestamps:
            transcription_data = _build_timestamp_response(all_segments)
        else:
            transcription_data = _build_text_only_response(all_segments)

        return JSONResponse(content={
            "source": "local",
            "model": model,
            "language": lang,
            "transcription": transcription_data
        })

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {e}")
    finally:
        if temp_file_path:
            cleanup_temp_file(temp_file_path)


@rest_router.post("/api/v1/transcribe/openai", summary="Transcription with OpenAI API")
async def transcribe_openai_endpoint(
        file: UploadFile = File(...),
        model: str = Form("whisper-1"),
        language: Optional[str] = Form(None)
):
    """
    Transcribes an audio file using the OpenAI Whisper API.
    - **language**: Language of the audio (e.g., 'en', 'pl'). If omitted, the server default is used.
    """
    if not settings.OPENAI_API_KEY:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not configured on the server.")

    lang = language if language else settings.TRANSCRIPTION_LANGUAGE
    temp_file_path = None
    try:
        temp_file_path = await save_upload_to_temp_async(file)
        response_text = await asyncio.to_thread(
            openai_speech_transcription,
            audio_file_path=temp_file_path,
            model=model,
            language=lang
        )
        return {"source": "openai", "model": model, "language": lang, "transcription": response_text}
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


@rest_router.post("/api/v1/transcribe/hf", summary="Transcription with Hugging Face provider")
async def transcribe_hf_endpoint(
        file: UploadFile = File(...),
        model: str = Form("openai/whisper-large-v3"),
        hf_provider: str = Form("hf-inference")
):
    """
    Transcribes an audio file using a Hugging Face Inference provider.
    - **hf_provider**: The provider to use (e.g., 'hf-inference', 'sambanova').
    """
    if not settings.HF_TOKEN:
        raise HTTPException(status_code=500, detail="HF_TOKEN is not configured on the server.")

    temp_file_path = None
    try:
        temp_file_path = await save_upload_to_temp_async(file)
        response_text = await asyncio.to_thread(
            hf_speech_transcription,
            audio_file_path=temp_file_path,
            model=model,
            provider=hf_provider
        )
        return {"source": "huggingface", "model": model, "provider": hf_provider, "transcription": response_text}
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


@rest_router.post("/api/v1/transcribe/audacity", summary="Transcription of Audacity project (.zip)")
async def transcribe_audacity_endpoint(
        file: UploadFile = File(...),
        provider: str = Form("local"),
        model: str = Form("Systran/faster-whisper-large-v3"),
        language: Optional[str] = Form(None),
        hf_provider: str = Form("hf-inference")
):
    """
    Transcribes a zipped Audacity project (.aup + _data folder) and merges the audio chronologically.
    - **provider**: 'local', 'openai', or 'huggingface'
    """
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="File must be a .zip containing an Audacity project.")

    lang = language if language else settings.TRANSCRIPTION_LANGUAGE
    temp_zip_path = None
    extraction_dir = tempfile.mkdtemp(prefix="audacity_")
    
    try:
        temp_zip_path = await save_upload_to_temp_async(file)
        
        tracks = await asyncio.to_thread(extract_tracks_from_aup, temp_zip_path, extraction_dir)
        
        if not tracks:
            raise HTTPException(status_code=400, detail="No usable audio tracks found in the uploaded Audacity project.")

        transcription_text = await transcribe_and_merge_tracks(
            tracks=tracks,
            provider=provider,
            model=model,
            language=lang,
            hf_provider=hf_provider
        )

        return JSONResponse(content={
            "source": provider,
            "model": model,
            "language": lang,
            "transcription": transcription_text
        })

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
