from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, UploadFile, File, Query
from fastapi.responses import FileResponse

from src.audio.analyzer import get_supported_audio_formats
from src.config.process_mode import ProcessMode
from src.config.constants import DEFAULT_FORMAT, DEFAULT_SAMPLE_RATE, CONVERTED, DEFAULT_AUDIO_NAME, TRIMMED, PROCESSED, \
    DEFAULT_SILENCE_DURATION, DEFAULT_SILENCE_THRESHOLD
from src.error.forge_error import ForgeError
from src.error.handler import handle_forge_error
from src.forge import (
    convert_audio as forge_convert_audio,
    remove_silence as forge_remove_silence,
    process_full as forge_process_full,
)
from src.io.file_service import (
    save_upload_to_temp_async,
    get_media_type_from_path,
    build_filename,
)
from src.config.logging_config import setup_logging

app = FastAPI(
    title="AudioForge",
    description="Process audio files with conversion, trimming",
    version="0.0.1",
    contact={
        "name": "Lukk",
        "url": "https://lukksarna.com",
        "email": "luksarna@gmail.com",
    },
)
setup_logging()

SUPPORTED_FORMATS = get_supported_audio_formats()


@app.get("/")
async def root():
    return {"message": "Welcome to the audio processing API"}


@app.post("/api/v1/audio/process", summary="Process audio files")
async def process_audio(
        file: UploadFile = File(...),

        mode: Annotated[
            ProcessMode,
            Query(description="Processing mode to use")
        ] = ProcessMode.FULL,

        output_format: Annotated[
            str,
            Query(description="Output format <br> Modes: `convert` `full`",
                  enum=SUPPORTED_FORMATS)
        ] = DEFAULT_FORMAT,

        sample_rate: Annotated[
            int,
            Query(description="Audio sample rate, e.g., `16000`, `44100` <br> Modes: `convert` `full`")
        ] = DEFAULT_SAMPLE_RATE,

        silence_duration: Annotated[
            str, Query(description="Minimum silence duration in seconds to remove <br> Modes: `trim` `full`")
        ] = DEFAULT_SILENCE_DURATION,

        silence_threshold: Annotated[
            str, Query(description="Silence detection threshold from range: `0.01` - `1.0` <br> Modes: `trim` `full`")
        ] = DEFAULT_SILENCE_THRESHOLD,
):
    temp_in_path = await save_upload_to_temp_async(file)
    output_path = None
    operation_type = None

    try:
        if mode == ProcessMode.CONVERT:
            output_path = forge_convert_audio(temp_in_path, output_format=output_format, sample_rate=sample_rate)
            operation_type = CONVERTED

        elif mode == ProcessMode.TRIM:
            output_path = forge_remove_silence(
                temp_in_path,
                silence_duration=silence_duration,
                silence_threshold=silence_threshold
            )
            operation_type = TRIMMED

        elif mode == ProcessMode.FULL:
            output_path = forge_process_full(
                temp_in_path,
                sample_rate=sample_rate,
                output_format=output_format,
                silence_duration=silence_duration,
                silence_threshold=silence_threshold
            )
            operation_type = PROCESSED

    except ForgeError as e:
        handle_forge_error(e, temp_in_path)

    media_type = get_media_type_from_path(output_path)
    filename = build_filename(operation_type, file.filename or DEFAULT_AUDIO_NAME, output_path)

    return FileResponse(
        path=output_path,
        media_type=media_type,
        filename=filename
    )
