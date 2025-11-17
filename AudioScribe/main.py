import asyncio
import json
from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.responses import StreamingResponse
from typing import AsyncGenerator

from src.config.logging_config import setup_logging
from src.config.settings import settings
from src.io.file_service import save_upload_to_temp_async, cleanup_temp_file
from src.scribe import openai_speech_transcription, local_speech_transcription, hf_speech_transcription

setup_logging()

app = FastAPI(
    title="AudioScribe",
    description="A dynamic speech-to-text service supporting local, OpenAI, and Hugging Face models.",
    version="0.4.0",
)

@app.get("/")
async def root():
    return {"message": "Welcome to the AudioScribe API"}

async def local_transcription_generator(temp_file_path: str, model: str) -> AsyncGenerator[str, None]:
    """
    A generator that yields JSON chunks for a streaming response.
    This avoids building a giant JSON string in memory.
    """
    yield '{"source": "local", "model": "'
    yield model
    yield '", "transcription": ['

    is_first_segment = True
    try:
        async for segment in local_speech_transcription(
            audio_file_path=temp_file_path,
            model_path=model
        ):
            if not is_first_segment:
                yield ","
            
            chunk = {
                "text": segment.text.strip(),
                "timestamp": (segment.start, segment.end)
            }
            yield json.dumps(chunk)
            is_first_segment = False
            
    finally:
        yield "]}"
        cleanup_temp_file(temp_file_path)


@app.post("/api/v1/transcribe/local", summary="Transcription with a local model (Streaming)")
async def transcribe_local_endpoint(
    file: UploadFile = File(...),
    model: str = Form("Systran/faster-whisper-large-v3")
):
    """
    Transcribes an audio file using a faster-whisper compatible model.
    This endpoint **streams** the response, making it suitable for very long audio files.
    """
    temp_file_path = await save_upload_to_temp_async(file)
    return StreamingResponse(
        local_transcription_generator(temp_file_path, model),
        media_type="application/json"
    )


@app.post("/api/v1/transcribe/openai", summary="Transcription with OpenAI API")
async def transcribe_openai_endpoint(
    file: UploadFile = File(...),
    model: str = Form("whisper-1")
):
    """
    Transcribes an audio file using the OpenAI Whisper API.
    """
    if not settings.OPENAI_API_KEY:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not configured on the server.")
    
    temp_file_path = None
    try:
        temp_file_path = await save_upload_to_temp_async(file)
        response_text = await asyncio.to_thread(
            openai_speech_transcription,
            audio_file_path=temp_file_path,
            model=model
        )
        return {"source": "openai", "model": model, "transcription": response_text}
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


@app.post("/api/v1/transcribe/hf", summary="Transcription with Hugging Face provider")
async def transcribe_hf_endpoint(
    file: UploadFile = File(...),
    model: str = Form("openai/whisper-large-v3")
):
    """
    Transcribes an audio file using a Hugging Face Inference provider.
    """
    if not settings.HF_TOKEN:
        raise HTTPException(status_code=500, detail="HF_TOKEN is not configured on the server.")

    temp_file_path = None
    try:
        temp_file_path = await save_upload_to_temp_async(file)
        response_text = await asyncio.to_thread(
            hf_speech_transcription,
            audio_file_path=temp_file_path,
            model=model
        )
        return {"source": "huggingface", "model": model, "transcription": response_text}
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
