import os
import shutil
import tempfile

from fastapi import FastAPI,UploadFile, File, HTTPException


from src.scribe import openai_speech_transcription, local_speech_transcription

app = FastAPI()

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

@app.get("/")
async def root():
    return {"message": "Welcome to the Transcription API"}


@app.post("/transcribe/local")
async def transcribe_local_endpoint(file: UploadFile = File(...)):
    """
    Accepts an audio file upload and transcribes it using the local Whisper model.
    """
    temp_file_path = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as temp_file:
            shutil.copyfileobj(file.file, temp_file)
            temp_file_path = temp_file.name

        transcription, duration = local_speech_transcription(audio_file_path=temp_file_path)

        return {
            "source": "local",
            "duration": duration,
            "transcription": transcription
        }
    finally:
        if temp_file_path in locals() and os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        await file.close()


@app.post("/transcribe/openai")
async def transcribe_openai_endpoint(file: UploadFile = File(...)):
    """
    Accepts an audio file upload and transcribes it using the OpenAI Whisper API.
    """
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not configured on the server.")

    temp_file_path = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as temp_file:
            shutil.copyfileobj(file.file, temp_file)
            temp_file_path = temp_file.name

        response_text = openai_speech_transcription(audio_file_path=temp_file_path)

        return {
            "source": "openai",
            "transcription": response_text
        }
    finally:
        if temp_file_path in locals() and os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        await file.close()