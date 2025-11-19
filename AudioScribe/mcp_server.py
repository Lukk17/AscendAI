import asyncio
import json
import os
from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent
from typing import Optional

from src.config.logging_config import setup_logging
from src.config.settings import settings
from src.scribe import openai_speech_transcription, local_speech_transcription, hf_speech_transcription
from starlette.applications import Starlette
from starlette.routing import Mount
from contextlib import asynccontextmanager
from starlette.types import ASGIApp, Scope, Receive, Send, Message

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
    
    # Wrap the final app in the middleware
    wrapped_app = ForceJSONUTF8Middleware(app)

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
    
    return wrapped_app

app = create_app()
