import asyncio
import json
import os
from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent
from typing import Optional

from src.config.settings import settings
from src.scribe import openai_speech_transcription, local_speech_transcription, hf_speech_transcription
from starlette.applications import Starlette
from starlette.routing import Mount
from contextlib import asynccontextmanager

scribe_mcp_server = FastMCP("audio-scribe", json_response=True)

# Expose a conventional ASGI app entrypoint for uvicorn/gunicorn.
# Here we COMPOSE both transports into a single parent Starlette app:
# - Streamable HTTP mounted at "/mcp" (provided by FastMCP)
# - SSE mounted under "/sse-root" → 
#     • GET /sse-root/sse
#     • POST /sse-root/messages/
_streamable_http_subapp = scribe_mcp_server.streamable_http_app()
_sse_subapp = scribe_mcp_server.sse_app()

@asynccontextmanager
async def _parent_lifespan(_app: Starlette):
    # Ensure the session manager has been created by the call above
    session_manager = getattr(scribe_mcp_server, "_session_manager", None)
    if session_manager is None:
        # As a fallback, call the factory to force initialization
        _ = scribe_mcp_server.streamable_http_app()
        session_manager = getattr(scribe_mcp_server, "_session_manager", None)

    if session_manager is None:
        # Should not happen, but keep the app running even if we can't start
        # the manager (SSE will still work)
        yield
        return

    async with session_manager.run():
        yield

# Important: order of mounts matters. Mount "/sse-root" first so it matches
# before the catch-all root mount below.
app = Starlette(
    routes=[
        Mount("/sse-root", app=_sse_subapp),
        # Mount the Streamable HTTP app at root so it exposes its default /mcp path.
        Mount("/", app=_streamable_http_subapp),
    ],
    lifespan=_parent_lifespan,
)


def create_error_response(message: str):
    return {"content": [TextContent(type="text", text=message)], "is_error": True}


@scribe_mcp_server.tool(
    name="transcribe_local",
    description="Transcribes a file with a local model. Args: file_path (str), model (str, optional), language (str, optional), with_timestamps (bool, optional)."
)
async def transcribe_local(
        file_path: str,
        model: str = "Systran/faster-whisper-large-v3",
        language: Optional[str] = None,
        with_timestamps: bool = True
):
    if not file_path or not os.path.exists(file_path):
        return create_error_response(f"File not found: {file_path}")

    lang = language if language else settings.TRANSCRIPTION_LANGUAGE
    try:
        all_segments = [segment async for segment in local_speech_transcription(  # type: ignore
            audio_file_path=file_path,
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
        # Return readable JSON without ASCII escaping so non‑ASCII characters are preserved
        return {"content": [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))]}

    except (ValueError, IOError) as error:
        return create_error_response(str(error))
    except Exception as error:
        return create_error_response(f"An unexpected error occurred: {error}")


@scribe_mcp_server.tool(
    name="transcribe_openai",
    description="Transcribes a file with the OpenAI API. Args: file_path (str), model (str, optional), language (str, optional)."
)
async def transcribe_openai(
        file_path: str,
        model: str = "whisper-1",
        language: Optional[str] = None
):
    if not settings.OPENAI_API_KEY:
        return create_error_response("OPENAI_API_KEY is not configured on the server.")
    if not file_path or not os.path.exists(file_path):
        return create_error_response(f"File not found: {file_path}")

    lang = language if language else settings.TRANSCRIPTION_LANGUAGE
    try:
        response_text = await asyncio.to_thread(
            openai_speech_transcription,
            audio_file_path=file_path,
            model=model,
            language=lang
        )
        payload = {"source": "openai", "model": model, "language": lang, "transcription": response_text}
        return {"content": [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))]}
    except (ValueError, IOError) as error:
        return create_error_response(str(error))
    except Exception as error:
        return create_error_response(f"An unexpected error occurred: {error}")


@scribe_mcp_server.tool(
    name="transcribe_hf",
    description="Transcribes a file with a Hugging Face provider. Args: file_path (str), model (str, optional), hf_provider (str, optional)."
)
async def transcribe_hf(
        file_path: str,
        model: str = "openai/whisper-large-v3",
        hf_provider: str = "hf-inference"
):
    if not settings.HF_TOKEN:
        return create_error_response("HF_TOKEN is not configured on the server.")
    if not file_path or not os.path.exists(file_path):
        return create_error_response(f"File not found: {file_path}")

    try:
        response_text = await asyncio.to_thread(
            hf_speech_transcription,
            audio_file_path=file_path,
            model=model,
            provider=hf_provider
        )
        payload = {"source": "huggingface", "model": model, "provider": hf_provider, "transcription": response_text}
        return {"content": [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))]}
    except (ValueError, IOError) as error:
        return create_error_response(str(error))
    except Exception as error:
        return create_error_response(f"An unexpected error occurred: {error}")


@scribe_mcp_server.tool(name="health", description="Simple health check tool.")
async def health():
    return {"content": [TextContent(type="text", text="ok")]}
