from __future__ import annotations

from fastapi import FastAPI, UploadFile, File, Query
from fastapi.responses import FileResponse

from src.constants import DEFAULT_FORMAT, DEFAULT_SAMPLE_RATE, CONVERTED, DEFAULT_AUDIO_NAME, TRIMMED, PROCESSED, \
    DEFAULT_SILENCE_DURATION, DEFAULT_SILENCE_THRESHOLD
from src.error.forge_error import ForgeError
from src.error.handler import handle_forge_error
from src.forge import (
    convert_audio as forge_convert_audio,
    remove_silence as forge_remove_silence,
    process_full as forge_process_full,
)
from src.io.file_service import (
    save_upload_to_temp,
    get_media_type_from_path,
    build_filename,
)
from src.io.logging_config import setup_logging

app = FastAPI()
setup_logging()


@app.post("/convert")
async def convert_audio(
        file: UploadFile = File(...),
        output_format: str = Query(DEFAULT_FORMAT, description="Output format, e.g., mp3, wav, ogg"),
        sample_rate: int = Query(DEFAULT_SAMPLE_RATE, description="Audio sample rate, e.g., 16000, 44100"),
):
    temp_in_path = save_upload_to_temp(file)
    output_path = None

    try:
        output_path = forge_convert_audio(temp_in_path, output_format=output_format, sample_rate=sample_rate)
    except ForgeError as e:
        handle_forge_error(e, temp_in_path)

    media_type = get_media_type_from_path(output_path)
    filename = build_filename(CONVERTED, file.filename or DEFAULT_AUDIO_NAME, output_path)

    return FileResponse(
        path=output_path,
        media_type=media_type,
        filename=filename
    )


@app.post("/remove-silence")
async def remove_silence(
        file: UploadFile = File(...),
        silence_duration: str = Query(DEFAULT_SILENCE_DURATION, description="Minimum silence duration to remove (seconds)"),
        silence_threshold: str = Query(DEFAULT_SILENCE_THRESHOLD, description="Silence detection threshold (0.01-1.0)"),
):
    temp_in_path = save_upload_to_temp(file)
    output_path = None

    try:
        output_path = forge_remove_silence(
            temp_in_path,
            silence_duration=silence_duration,
            silence_threshold=silence_threshold
        )
    except ForgeError as e:
        handle_forge_error(e, temp_in_path)

    media_type = get_media_type_from_path(output_path)
    filename = build_filename(TRIMMED, file.filename or DEFAULT_AUDIO_NAME, output_path)

    return FileResponse(
        path=output_path,
        media_type=media_type,
        filename=filename
    )


@app.post("/process-full")
async def process_full(
        file: UploadFile = File(...),
        sample_rate: int = Query(DEFAULT_SAMPLE_RATE, description="Audio sample rate, e.g., 16000, 44100"),
        output_format: str = Query(DEFAULT_FORMAT, description="Final output format, e.g., mp3, wav"),
        silence_duration: str = Query(DEFAULT_SILENCE_DURATION, description="Minimum silence duration to remove (seconds)"),
        silence_threshold: str = Query(DEFAULT_SILENCE_THRESHOLD, description="Silence detection threshold (0.01-1.0)"),
):
    temp_in_path = save_upload_to_temp(file)
    output_path = None

    try:
        output_path = forge_process_full(
            temp_in_path,
            sample_rate=sample_rate,
            output_format=output_format,
            silence_duration=silence_duration,
            silence_threshold=silence_threshold
        )
    except ForgeError as e:
        handle_forge_error(e, temp_in_path)

    media_type = get_media_type_from_path(output_path)
    filename = build_filename(PROCESSED, file.filename or DEFAULT_AUDIO_NAME, output_path)

    return FileResponse(
        path=output_path,
        media_type=media_type,
        filename=filename
    )
