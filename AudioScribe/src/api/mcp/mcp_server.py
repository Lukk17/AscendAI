import asyncio
import json
import os
from typing import Optional

from fastmcp import FastMCP
from mcp.types import TextContent

from src.adapters.download_service import download_to_temp_async
from src.adapters.file_service import cleanup_temp_file
from src.config.config import settings
from src.scribe import openai_speech_transcription, local_speech_transcription, hf_speech_transcription

URI_NOT_PROVIDED = "URI not provided"

mcp = FastMCP("AudioScribe")


def create_error_response(message: str):
    return {"content": [TextContent(type="text", text=message)], "is_error": True}


@mcp.tool(
    name="transcribe_local",
    description="Transcribes audio from a URI using a local faster-whisper model. "
                "Supports mp3, wav, aac, flac, ogg, m4a, wma. Converted to 16kHz WAV internally. "
                "Parameters: "
                "- audio_uri: The URI of the audio file (e.g., 'file:///path/to/file.wav' or 'http://...'). "
                "- model: The model path (default: 'Systran/faster-whisper-large-v3'). "
                "- language: ISO 639-1 language code (e.g., 'en', 'pl', 'fr'). Do NOT use full language names like 'Polish'. "
                "- with_timestamps: Whether to return timestamps (default: True)."
)
async def transcribe_local(
        audio_uri: str,
        model: str = "Systran/faster-whisper-large-v3",
        language: Optional[str] = None,
        with_timestamps: bool = True
):
    if not audio_uri:
        return create_error_response(URI_NOT_PROVIDED)

    temp_file_path = None
    try:
        temp_file_path = await download_to_temp_async(audio_uri)
        if not os.path.exists(temp_file_path):
            return create_error_response(f"File not accessible after download: {temp_file_path}")

        lang = language if language else settings.TRANSCRIPTION_LANGUAGE
        all_segments = [segment async for segment in local_speech_transcription(
            audio_file_path=temp_file_path,
            model_path=model,
            language=lang
        )]

        if with_timestamps:
            transcription_data = [
                {"text": s['text'], "timestamp": (s['start'], s['end'])} for s in all_segments
            ]
        else:
            transcription_data = " ".join([s['text'] for s in all_segments])

        payload = {"source": "local", "model": model, "language": lang, "transcription": transcription_data}
        return {"content": [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))]}

    except (ValueError, IOError) as error:
        return create_error_response(str(error))
    except Exception as error:
        return create_error_response(f"An unexpected error occurred: {error}")
    finally:
        if temp_file_path:
            cleanup_temp_file(temp_file_path)


@mcp.tool(
    name="transcribe_openai",
    description="Transcribes audio from a URI with the OpenAI API. Supports mp3, mp4, mpeg, mpga, m4a, wav, and webm. Args: audio_uri (str), model (str, optional), language (str, optional)."
)
async def transcribe_openai(
        audio_uri: str,
        model: str = "whisper-1",
        language: Optional[str] = None
):
    if not settings.OPENAI_API_KEY:
        return create_error_response("OPENAI_API_KEY is not configured on the server.")
    if not audio_uri:
        return create_error_response(URI_NOT_PROVIDED)

    temp_file_path = None
    try:
        temp_file_path = await download_to_temp_async(audio_uri)
        if not os.path.exists(temp_file_path):
            return create_error_response(f"File not accessible after download: {temp_file_path}")

        lang = language if language else settings.TRANSCRIPTION_LANGUAGE
        response_text = await asyncio.to_thread(
            openai_speech_transcription,
            audio_file_path=temp_file_path,
            model=model,
            language=lang
        )
        payload = {"source": "openai", "model": model, "language": lang, "transcription": response_text}
        return {"content": [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))]}
    except (ValueError, IOError) as error:
        return create_error_response(str(error))
    except Exception as error:
        return create_error_response(f"An unexpected error occurred: {error}")
    finally:
        if temp_file_path:
            cleanup_temp_file(temp_file_path)


@mcp.tool(
    name="transcribe_hf",
    description="Transcribes audio from a URI with a Hugging Face provider. "
                "Supports mp3, wav, aac, flac, ogg, m4a, wma. Converted to 16kHz WAV internally. "
                "Args: audio_uri (str), model (str, optional), hf_provider (str, optional)."
)
async def transcribe_hf(
        audio_uri: str,
        model: str = "openai/whisper-large-v3",
        hf_provider: str = "hf-inference"
):
    if not settings.HF_TOKEN:
        return create_error_response("HF_TOKEN is not configured on the server.")
    if not audio_uri:
        return create_error_response(URI_NOT_PROVIDED)

    temp_file_path = None
    try:
        temp_file_path = await download_to_temp_async(audio_uri)
        if not os.path.exists(temp_file_path):
            return create_error_response(f"File not accessible after download: {temp_file_path}")

        response_text = await asyncio.to_thread(
            hf_speech_transcription,
            audio_file_path=temp_file_path,
            model=model,
            provider=hf_provider
        )
        payload = {"source": "huggingface", "model": model, "provider": hf_provider, "transcription": response_text}
        return {"content": [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))]}
    except (ValueError, IOError) as error:
        return create_error_response(str(error))
    except Exception as error:
        return create_error_response(f"An unexpected error occurred: {error}")
    finally:
        if temp_file_path:
            cleanup_temp_file(temp_file_path)


@mcp.tool(name="health", description="Simple health check tool.")
async def health():
    return {"content": [TextContent(type="text", text="ok")]}
