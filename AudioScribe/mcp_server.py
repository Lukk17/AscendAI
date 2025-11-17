import asyncio
import json
import os

from src.config.settings import settings
from src.scribe import openai_speech_transcription, local_speech_transcription, hf_speech_transcription

try:
    from mcp.server import Server
    from mcp.types import TextContent
    from mcp.server.http import http_server
except Exception as e:
    raise RuntimeError(
        "The 'mcp' package is required to run the MCP server. Install it via `pip install mcp`."
    ) from e

server = Server("audio-scribe")

def create_error_response(message: str):
    """Creates a standardized MCP error response."""
    return {"content": [TextContent(type="text", text=message)], "is_error": True}

@server.tool(
    name="transcribe_local",
    description="Transcribes a file with a local model. This is a STREAMING tool.",
    is_streaming=True
)
async def transcribe_local(file_path: str, model: str = "Systran/faster-whisper-large-v3"):
    if not file_path or not os.path.exists(file_path):
        yield create_error_response(f"File not found: {file_path}")
        return

    try:
        # The core function is now an async generator. We can iterate over it directly.
        async for segment in local_speech_transcription(
            audio_file_path=file_path,
            model_path=model
        ):
            chunk = {
                "text": segment.text.strip(),
                "timestamp": (segment.start, segment.end)
            }
            yield {"content": [TextContent(type="text", text=json.dumps(chunk))]}

    except (ValueError, IOError) as e:
        yield create_error_response(str(e))
    except Exception as e:
        yield create_error_response(f"An unexpected error occurred: {e}")

@server.tool(
    name="transcribe_openai",
    description="Transcribes a file with the OpenAI API. Args: file_path (str), model (str, optional, e.g., 'whisper-1')."
)
async def transcribe_openai(file_path: str, model: str = "whisper-1"):
    if not settings.OPENAI_API_KEY:
        return create_error_response("OPENAI_API_KEY is not configured on the server.")
    if not file_path or not os.path.exists(file_path):
        return create_error_response(f"File not found: {file_path}")

    try:
        response_text = await asyncio.to_thread(
            openai_speech_transcription,
            audio_file_path=file_path,
            model=model
        )
        payload = {"source": "openai", "model": model, "transcription": response_text}
        return {"content": [TextContent(type="text", text=json.dumps(payload))]}
    except (ValueError, IOError) as e:
        return create_error_response(str(e))
    except Exception as e:
        return create_error_response(f"An unexpected error occurred: {e}")

@server.tool(
    name="transcribe_hf",
    description="Transcribes a file with a Hugging Face provider. Args: file_path (str), model (str, optional)."
)
async def transcribe_hf(file_path: str, model: str = "openai/whisper-large-v3"):
    if not settings.HF_TOKEN:
        return create_error_response("HF_TOKEN is not configured on the server.")
    if not file_path or not os.path.exists(file_path):
        return create_error_response(f"File not found: {file_path}")

    try:
        response_text = await asyncio.to_thread(
            hf_speech_transcription,
            audio_file_path=file_path,
            model=model
        )
        payload = {"source": "huggingface", "model": model, "transcription": response_text}
        return {"content": [TextContent(type="text", text=json.dumps(payload))]}
    except (ValueError, IOError) as e:
        return create_error_response(str(e))
    except Exception as e:
        return create_error_response(f"An unexpected error occurred: {e}")

@server.tool(name="health", description="Simple health check tool.")
async def health():
    return {"content": [TextContent(type="text", text="ok")]}

async def main() -> None:
    print(f"Starting MCP HTTP server on {settings.MCP_HOST}:{settings.MCP_PORT}")
    async with http_server(host=settings.MCP_HOST, port=settings.MCP_PORT) as (read_stream, write_stream):
        await server.run(read_stream, write_stream)

if __name__ == "__main__":
    asyncio.run(main())
