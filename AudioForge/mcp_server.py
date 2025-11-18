import asyncio
import json
import os
from typing import Optional

from src.forge import (
    convert_audio as forge_convert_audio,
    remove_silence as forge_remove_silence,
    process_full as forge_process_full,
)
from src.error.forge_error import ForgeError
from src.io.file_service import get_media_type_from_path, build_filename
from src.config.constants import (
    DEFAULT_FORMAT,
    DEFAULT_SAMPLE_RATE,
    DEFAULT_SILENCE_DURATION,
    DEFAULT_SILENCE_THRESHOLD,
    CONVERTED,
    TRIMMED,
    PROCESSED,
    DEFAULT_AUDIO_NAME,
)

try:
    # MCP Python SDK (Anthropic Model Context Protocol)
    from mcp.server import Server
    from mcp.types import TextContent
    from mcp.server.stdio import stdio_server
except Exception as e:  # pragma: no cover
    raise RuntimeError(
        "The 'mcp' package is required to run the MCP server. Install it via `pip install mcp`."
    ) from e


server = Server("audio-forge")


@server.tool(
    name="health",
    description="Simple health check tool returning 'ok' if the server is responsive.",
)
async def health():
    return {"content": [TextContent(type="text", text="ok")]}


@server.tool(
    name="convert_audio",
    description=(
        "Convert audio format and/or sample rate using FFmpeg. "
        "Inputs: file_path (str), output_format (str, e.g., 'wav', 'mp3'), sample_rate (int, e.g., 16000). "
        "Returns JSON with keys: source='forge', operation='converted', output_path, media_type, filename."
    ),
)
async def convert_audio(
    file_path: str,
    output_format: Optional[str] = None,
    sample_rate: Optional[int] = None,
):
    if not file_path or not os.path.exists(file_path):
        return {
            "content": [TextContent(type="text", text=f"File not found: {file_path}")],
            "is_error": True,
        }
    try:
        out_format = output_format or DEFAULT_FORMAT
        out_sr = sample_rate or DEFAULT_SAMPLE_RATE
        output_path = forge_convert_audio(file_path, output_format=out_format, sample_rate=out_sr)
        media_type = get_media_type_from_path(output_path)
        filename = build_filename(CONVERTED, os.path.basename(file_path) or DEFAULT_AUDIO_NAME, output_path)
        payload = {
            "source": "forge",
            "operation": CONVERTED,
            "output_path": output_path,
            "media_type": media_type,
            "filename": filename,
        }
        return {"content": [TextContent(type="text", text=json.dumps(payload))]}
    except ForgeError as error:
        return {"content": [TextContent(type="text", text=str(error))], "is_error": True}


@server.tool(
    name="remove_silence",
    description=(
        "Remove silence using SoX with configurable settings. "
        "Inputs: file_path (str), silence_duration (str, default 0.5), silence_threshold (str, default 0.05). "
        "Returns JSON with keys: source='forge', operation='trimmed', output_path, media_type, filename."
    ),
)
async def remove_silence(
    file_path: str,
    silence_duration: Optional[str] = None,
    silence_threshold: Optional[str] = None,
):
    if not file_path or not os.path.exists(file_path):
        return {
            "content": [TextContent(type="text", text=f"File not found: {file_path}")],
            "is_error": True,
        }
    try:
        dur = silence_duration or DEFAULT_SILENCE_DURATION
        thr = silence_threshold or DEFAULT_SILENCE_THRESHOLD
        output_path = forge_remove_silence(file_path, silence_duration=dur, silence_threshold=thr)
        media_type = get_media_type_from_path(output_path)
        filename = build_filename(TRIMMED, os.path.basename(file_path) or DEFAULT_AUDIO_NAME, output_path)
        payload = {
            "source": "forge",
            "operation": TRIMMED,
            "output_path": output_path,
            "media_type": media_type,
            "filename": filename,
        }
        return {"content": [TextContent(type="text", text=json.dumps(payload))]}
    except ForgeError as error:
        return {"content": [TextContent(type="text", text=str(error))], "is_error": True}


@server.tool(
    name="process_full",
    description=(
        "Full pipeline: convert to target sample rate/format then remove silence. "
        "Inputs: file_path (str), output_format (str), sample_rate (int), silence_duration (str), silence_threshold (str). "
        "Returns JSON with keys: source='forge', operation='processed', output_path, media_type, filename."
    ),
)
async def process_full(
    file_path: str,
    output_format: Optional[str] = None,
    sample_rate: Optional[int] = None,
    silence_duration: Optional[str] = None,
    silence_threshold: Optional[str] = None,
):
    if not file_path or not os.path.exists(file_path):
        return {
            "content": [TextContent(type="text", text=f"File not found: {file_path}")],
            "is_error": True,
        }
    try:
        out_format = output_format or DEFAULT_FORMAT
        out_sr = sample_rate or DEFAULT_SAMPLE_RATE
        dur = silence_duration or DEFAULT_SILENCE_DURATION
        thr = silence_threshold or DEFAULT_SILENCE_THRESHOLD
        output_path = forge_process_full(
            file_path,
            sample_rate=out_sr,
            output_format=out_format,
            silence_duration=dur,
            silence_threshold=thr,
        )
        media_type = get_media_type_from_path(output_path)
        filename = build_filename(PROCESSED, os.path.basename(file_path) or DEFAULT_AUDIO_NAME, output_path)
        payload = {
            "source": "forge",
            "operation": PROCESSED,
            "output_path": output_path,
            "media_type": media_type,
            "filename": filename,
        }
        return {"content": [TextContent(type="text", text=json.dumps(payload))]}
    except ForgeError as error:
        return {"content": [TextContent(type="text", text=str(error))], "is_error": True}


async def main() -> None:
    # Run the MCP server over stdio (recommended for editor integration)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream)


if __name__ == "__main__":
    asyncio.run(main())
