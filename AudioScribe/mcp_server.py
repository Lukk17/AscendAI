import asyncio
import json
import os
from contextlib import asynccontextmanager
from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.types import ASGIApp, Scope, Receive, Send, Message
from typing import Optional

from src.io.download_service import download_to_temp_async
from src.io.file_service import cleanup_temp_file
from src.config.logging_config import setup_logging
from src.config.settings import settings
from src.scribe import openai_speech_transcription, local_speech_transcription, hf_speech_transcription


class ForceJSONUTF8Middleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message):
            if message["type"] == "http.response.start":
                # Normalize/ensure UTF-8 charset for JSON and SSE responses.
                # ASGI headers are a list of (key: bytes, value: bytes) tuples.
                raw_headers = list(message.get("headers", []))

                ct_index = None
                current_value = None
                for i, (k, v) in enumerate(raw_headers):
                    # Compare header name case-insensitively in bytes
                    if k.lower() == b"content-type":
                        ct_index = i
                        current_value = v
                        break

                def main_type_and_params(val: bytes) -> tuple[bytes, bytes]:
                    """Split content-type into main type and raw params (bytes)."""
                    if not val:
                        return b"", b""
                    parts = val.split(b";", 1)
                    if len(parts) == 1:
                        return parts[0].strip().lower(), b""
                    return parts[0].strip().lower(), parts[1].strip()

                def has_charset(params: bytes) -> bool:
                    return b"charset=" in params.lower()

                # Default behavior when the header is entirely missing: set JSON with UTF-8
                if ct_index is None:
                    raw_headers.append((b"content-type", b"application/json; charset=utf-8"))
                else:
                    main, params = main_type_and_params(current_value or b"")
                    # For application/json, enforce the exact value with charset to avoid client mis-decoding
                    if main == b"application/json":
                        raw_headers[ct_index] = (b"content-type", b"application/json; charset=utf-8")
                    # For SSE, ensure charset is present while preserving other parameters
                    elif main == b"text/event-stream" and not has_charset(params):
                        # Preserve any existing params order, just append charset at the end
                        new_val = b"text/event-stream; " + (params + b"; " if params else b"") + b"charset=utf-8"
                        raw_headers[ct_index] = (b"content-type", new_val)

                message["headers"] = raw_headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


def create_app() -> Starlette:
    setup_logging()

    scribe_mcp_server = FastMCP("audio-scribe")

    _streamable_http_subapp = scribe_mcp_server.streamable_http_app()
    _sse_subapp = scribe_mcp_server.sse_app()

    @asynccontextmanager
    async def _parent_lifespan(_app: Starlette):
        session_manager = getattr(scribe_mcp_server, "_session_manager", None)
        if session_manager is None:
            _ = scribe_mcp_server.streamable_http_app()
            session_manager = getattr(scribe_mcp_server, "_session_manager", None)

        if session_manager is None:
            yield
            return

        async with session_manager.run():
            yield

    app = Starlette(
        routes=[
            Mount("/sse-root", app=_sse_subapp),
            Mount("/", app=_streamable_http_subapp),
        ],
        lifespan=_parent_lifespan,
    )

    wrapped_app = ForceJSONUTF8Middleware(app)

    def create_error_response(message: str):
        return {"content": [TextContent(type="text", text=message)], "is_error": True}

    @scribe_mcp_server.tool(
        name="transcribe_local",
        description="Transcribes audio from a URI using a local faster-whisper model. "
                    "Parameters: "
                    "- audio_uri: The URI of the audio file (e.g., 'file:///path/to/file.wav' or 'http://...'). "
                    "- model: The model path (default: 'Systran/faster-whisper-large-v3'). "
                    "- language: ISO 639-1 language code (e.g., 'en', 'pl', 'fr'). Do NOT use full language names like 'Polish'. "
                    "- with_timestamps: Whether to return timestamps (default: True)."
    )
    async def transcribe_local(
            audio_uri: str,  # Changed: Now audio_uri instead of file_path
            model: str = "Systran/faster-whisper-large-v3",
            language: Optional[str] = None,
            with_timestamps: bool = True
    ):
        if not audio_uri:
            return create_error_response("URI not provided")

        temp_file_path = None
        try:
            temp_file_path = await download_to_temp_async(audio_uri)  # New: Download to temp
            if not os.path.exists(temp_file_path):
                return create_error_response(f"File not accessible after download: {temp_file_path}")

            lang = language if language else settings.TRANSCRIPTION_LANGUAGE
            all_segments = [segment async for segment in local_speech_transcription(
                audio_file_path=temp_file_path,  # Use temp path
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
                cleanup_temp_file(temp_file_path)  # Cleanup like in main.py

    @scribe_mcp_server.tool(
        name="transcribe_openai",
        description="Transcribes audio from a URI with the OpenAI API. Args: audio_uri (str), model (str, optional), language (str, optional)."
    )
    async def transcribe_openai(
            audio_uri: str,
            model: str = "whisper-1",
            language: Optional[str] = None
    ):
        if not settings.OPENAI_API_KEY:
            return create_error_response("OPENAI_API_KEY is not configured on the server.")
        if not audio_uri:
            return create_error_response("URI not provided")

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

    @scribe_mcp_server.tool(
        name="transcribe_hf",
        description="Transcribes audio from a URI with a Hugging Face provider. Args: audio_uri (str), model (str, optional), hf_provider (str, optional)."
    )
    async def transcribe_hf(
            audio_uri: str,
            model: str = "openai/whisper-large-v3",
            hf_provider: str = "hf-inference"
    ):
        if not settings.HF_TOKEN:
            return create_error_response("HF_TOKEN is not configured on the server.")
        if not audio_uri:
            return create_error_response("URI not provided")

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

    @scribe_mcp_server.tool(name="health", description="Simple health check tool.")
    async def health():
        return {"content": [TextContent(type="text", text="ok")]}

    return wrapped_app


app = create_app()
