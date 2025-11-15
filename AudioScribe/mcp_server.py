import asyncio
import json
import os
from typing import Optional

from src.scribe import openai_speech_transcription, local_speech_transcription

try:
    # MCP Python SDK (Anthropic Model Context Protocol)
    from mcp.server import Server
    from mcp.types import TextContent
    from mcp.server.stdio import stdio_server
except Exception as e:  # pragma: no cover
    raise RuntimeError(
        "The 'mcp' package is required to run the MCP server. Install it via `pip install mcp`."
    ) from e


server = Server("audio-scribe")


@server.tool(
    name="transcribe_local",
    description=(
        "Transcribe an audio file using the local Whisper model. "
        "Input: file_path (str) pointing to an accessible audio file within the container or host. "
        "Returns JSON with keys: transcription (list of segments with start,end,text) and duration (seconds)."
    ),
)
async def transcribe_local(file_path: str):
    if not file_path or not os.path.exists(file_path):
        return {
            "content": [TextContent(type="text", text=f"File not found: {file_path}")],
            "is_error": True,
        }

    transcription, duration = local_speech_transcription(audio_file_path=file_path)
    payload = {"source": "local", "duration": duration, "transcription": transcription}
    return {"content": [TextContent(type="text", text=json.dumps(payload))]}


@server.tool(
    name="transcribe_openai",
    description=(
        "Transcribe an audio file using the OpenAI Whisper API. Requires OPENAI_API_KEY in the environment. "
        "Input: file_path (str). Returns JSON with keys: source, transcription."
    ),
)
async def transcribe_openai(file_path: str):
    if not os.environ.get("OPENAI_API_KEY"):
        return {
            "content": [TextContent(type="text", text="OPENAI_API_KEY is not configured on the server.")],
            "is_error": True,
        }
    if not file_path or not os.path.exists(file_path):
        return {
            "content": [TextContent(type="text", text=f"File not found: {file_path}")],
            "is_error": True,
        }

    response_text = openai_speech_transcription(audio_file_path=file_path)
    payload = {"source": "openai", "transcription": response_text}
    return {"content": [TextContent(type="text", text=json.dumps(payload))]}


@server.tool(
    name="health",
    description="Simple health check tool returning 'ok' if the server is responsive.",
)
async def health():
    return {"content": [TextContent(type="text", text="ok")]} 


async def main() -> None:
    # Run the MCP server over stdio (recommended for editor integration)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream)


if __name__ == "__main__":
    asyncio.run(main())
