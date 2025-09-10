import os
from fastapi import FastAPI, UploadFile, File, HTTPException

from src.config.logging_config import setup_logging
from src.io.file_service import save_upload_to_temp_async, cleanup_temp_file_async
from src.scribe import openai_speech_transcription, local_speech_transcription

setup_logging()
app = FastAPI(
    title="AudioScribe",
    description="Speech-to-text transcription service with local and OpenAI processing options",
    version="0.0.1",
    contact={
        "name": "Lukk",
        "url": "https://lukksarna.com",
        "email": "luksarna@gmail.com",
    },
)

@app.get("/")
async def root():
    return {"message": "Welcome to the transcription API"}


@app.post("/api/v1/transcribe/local", summary="Transcription audio files")
async def transcribe_local_endpoint(file: UploadFile = File(...)):
    """
    Accepts an audio file upload and transcribes it using the local Whisper model.
    """
    temp_file_path = None

    try:
        temp_file_path = await save_upload_to_temp_async(file)

        transcription, duration = local_speech_transcription(audio_file_path=temp_file_path)

        return {
            "source": "local",
            "duration": duration,
            "transcription": transcription
        }
    finally:
        if temp_file_path:
            cleanup_temp_file_async(temp_file_path)
        await file.close()


@app.post("/api/v1/transcribe/openai")
async def transcribe_openai_endpoint(file: UploadFile = File(...)):
    """
    Accepts an audio file upload and transcribes it using the OpenAI Whisper API.
    """
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not configured on the server.")

    temp_file_path = None

    try:
        temp_file_path = await save_upload_to_temp_async(file)

        response_text = openai_speech_transcription(audio_file_path=temp_file_path)

        return {
            "source": "openai",
            "transcription": response_text
        }
    finally:
        if temp_file_path:
            cleanup_temp_file_async(temp_file_path)
        await file.close()
