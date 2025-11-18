import asyncio
import json
import os
from typing import Optional

from src.config.settings import settings
from src.scribe import openai_speech_transcription, local_speech_transcription, hf_speech_transcription

try:
    from mcp.server import Server
    from mcp.types import TextContent
    # noinspection PyUnresolvedReferences
    from mcp.server.http import http_server
except Exception as e:
    raise RuntimeError(
        "The 'mcp' package is required to run the MCP server. Install it via `pip install mcp`."
    ) from e

server = Server("audio-scribe")

def create_error_response(message: str):
    """Creates a standardized MCP error response."""
    return {"content": [TextContent(type="text", text=message)], "is_error": True}

# noinspection PyUnresolvedReferences
@server.tool(
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
        all_segments = [segment async for segment in local_speech_transcription(
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
        return {"content": [TextContent(type="text", text=json.dumps(payload))]}

    except (ValueError, IOError) as error:
        return create_error_response(str(error))
    except Exception as error:
        return create_error_response(f"An unexpected error occurred: {error}")

# noinspection PyUnresolvedReferences
@server.tool(
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
        return {"content": [TextContent(type="text", text=json.dumps(payload))]}
    except (ValueError, IOError) as error:
        return create_error_response(str(error))
    except Exception as error:
        return create_error_response(f"An unexpected error occurred: {error}")

# noinspection PyUnresolvedReferences
@server.tool(
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
        return {"content": [TextContent(type="text", text=json.dumps(payload))]}
    except (ValueError, IOError) as error:
        return create_error_response(str(error))
    except Exception as error:
        return create_error_response(f"An unexpected error occurred: {error}")

# noinspection PyUnresolvedReferences
@server.tool(name="health", description="Simple health check tool.")
async def health():
    return {"content": [TextContent(type="text", text="ok")]}

async def main() -> None:
    print(f"Starting MCP HTTP server on {settings.MCP_HOST}:{settings.MCP_PORT}")
    async with http_server(host=settings.MCP_HOST, port=settings.MCP_PORT) as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            initialization_options=None
        )

if __name__ == "__main__":
    asyncio.run(main())
