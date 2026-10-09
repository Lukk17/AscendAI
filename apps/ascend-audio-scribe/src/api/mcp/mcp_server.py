"""MCP surface. URI-only contract (no multipart uploads); every fetch goes
through `download_to_temp_async` which enforces the SSRF guard, file:// jail,
and streaming size cap."""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from typing import Any, NoReturn

from ascend_python_common.errors import INTERNAL, INTERNAL_FIXED_DETAIL, resolve_detail
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from src.adapters.download_service import download_to_temp_async
from src.adapters.file_service import cleanup_temp_file
from src.api.exception_handlers import error_registry
from src.config.config import settings
from src.scribe import (
    hf_speech_transcription,
    local_speech_transcription,
    openai_speech_transcription,
)
from src.transcription.audacity_parser import extract_tracks_from_aup
from src.transcription.conversation_merger import transcribe_and_merge_tracks

logger = logging.getLogger(__name__)

URI_NOT_PROVIDED = "URI not provided"

mcp = FastMCP("ascend-audio-scribe")


def _resolve_language(language: str | None) -> str:
    """Narrow `str | None` to `str` for downstream calls. Explicit `if`
    branches let both pyright and PyCharm tighten the type."""

    if language is None or language == "":
        return settings.TRANSCRIPTION_LANGUAGE
    return language


def _success_envelope(payload: dict[str, Any]) -> dict[str, Any]:
    return {"status": "success", **payload}


def _raise_mapped_error(operation: str, exc: Exception) -> NoReturn:
    """Re-raise a failure as a tool error whose text starts with the registry code.

    The code and detail come from the service error registry, the same mapping
    the REST handlers apply to registered exceptions.
    """

    entry = error_registry.lookup(exc)
    if entry is not None:
        raise ToolError(f"{entry.code.code}: {resolve_detail(entry, exc)}") from exc

    logger.exception(f"MCP {operation} failed")
    raise ToolError(f"{INTERNAL.code}: {INTERNAL_FIXED_DETAIL}") from exc


async def _collect_local_segments(temp_file_path: str, model: str, lang: str) -> list[dict[str, Any]]:
    """Materialise the local async-iterator into a concrete `list[dict]`.
    Returning a list (not the iterator) gives downstream comprehensions a
    plainly-typed iterable so static analysers don't second-guess the
    `async for` expression."""

    return [
        segment
        async for segment in local_speech_transcription(
            audio_file_path=temp_file_path, model_path=model, language=lang
        )
    ]


def _format_local_transcription(
    segments: list[dict[str, Any]], with_timestamps: bool
) -> list[dict[str, Any]] | str:
    if with_timestamps:
        return [{"text": s["text"], "timestamp": (s["start"], s["end"])} for s in segments]
    return " ".join(s["text"] for s in segments)


@mcp.tool(
    name="transcribe_local",
    description=(
        "Transcribes audio from a URI using a local faster-whisper model. "
        "URI must be file:// (jailed to MCP_FILE_URI_ROOT) or http(s):// "
        "(SSRF-guarded). Returns segments with timestamps by default."
    ),
)
async def transcribe_local(
    audio_uri: str,
    model: str = "Systran/faster-whisper-large-v3",
    language: str | None = None,
    with_timestamps: bool = True,
) -> dict[str, Any]:
    if not audio_uri or not audio_uri.strip():
        _raise_mapped_error("transcribe_local", ValueError(URI_NOT_PROVIDED))

    # Empty-string sentinel rather than None so the variable's type stays
    # `str` for downstream call sites (no narrowing dance required).
    temp_file_path = ""
    try:
        temp_file_path = await download_to_temp_async(audio_uri)
        lang = _resolve_language(language)

        segments = await _collect_local_segments(temp_file_path, model, lang)
        transcription = _format_local_transcription(segments, with_timestamps)

        payload = {"source": "local", "model": model, "language": lang, "transcription": transcription}
        return _success_envelope(payload)
    except ToolError:
        raise
    except Exception as exc:
        _raise_mapped_error("transcribe_local", exc)
    finally:
        cleanup_temp_file(temp_file_path)


@mcp.tool(
    name="transcribe_openai",
    description="Transcribes audio from a URI via the OpenAI Whisper API.",
)
async def transcribe_openai(
    audio_uri: str,
    model: str = "whisper-1",
    language: str | None = None,
) -> dict[str, Any]:
    if not settings.OPENAI_API_KEY:
        _raise_mapped_error(
            "transcribe_openai", ValueError("OPENAI_API_KEY is not configured on the server.")
        )
    if not audio_uri or not audio_uri.strip():
        _raise_mapped_error("transcribe_openai", ValueError(URI_NOT_PROVIDED))

    temp_file_path = ""
    try:
        temp_file_path = await download_to_temp_async(audio_uri)
        lang = _resolve_language(language)
        response_text = await asyncio.to_thread(
            openai_speech_transcription,
            audio_file_path=temp_file_path,
            model=model,
            language=lang,
        )
        payload = {"source": "openai", "model": model, "language": lang, "transcription": response_text}
        return _success_envelope(payload)
    except ToolError:
        raise
    except Exception as exc:
        _raise_mapped_error("transcribe_openai", exc)
    finally:
        cleanup_temp_file(temp_file_path)


@mcp.tool(
    name="transcribe_hf",
    description="Transcribes audio from a URI via a Hugging Face provider.",
)
async def transcribe_hf(
    audio_uri: str,
    model: str = "openai/whisper-large-v3",
    hf_provider: str = "hf-inference",
) -> dict[str, Any]:
    if not settings.HF_TOKEN:
        _raise_mapped_error("transcribe_hf", ValueError("HF_TOKEN is not configured on the server."))
    if not audio_uri or not audio_uri.strip():
        _raise_mapped_error("transcribe_hf", ValueError(URI_NOT_PROVIDED))

    temp_file_path = ""
    try:
        temp_file_path = await download_to_temp_async(audio_uri)
        response_text = await asyncio.to_thread(
            hf_speech_transcription,
            audio_file_path=temp_file_path,
            model=model,
            provider=hf_provider,
        )
        payload = {
            "source": "huggingface",
            "model": model,
            "provider": hf_provider,
            "transcription": response_text,
        }
        return _success_envelope(payload)
    except ToolError:
        raise
    except Exception as exc:
        _raise_mapped_error("transcribe_hf", exc)
    finally:
        cleanup_temp_file(temp_file_path)


@mcp.tool(
    name="transcribe_audacity",
    description=(
        "Transcribes a multi-track Audacity project (.zip containing .aup + _data) from a URI. "
        "Supports provider=local|openai|huggingface."
    ),
)
async def transcribe_audacity(
    audio_uri: str,
    provider: str = "local",
    model: str = "Systran/faster-whisper-large-v3",
    language: str | None = None,
    hf_provider: str = "hf-inference",
) -> dict[str, Any]:
    if not audio_uri or not audio_uri.strip():
        _raise_mapped_error("transcribe_audacity", ValueError(URI_NOT_PROVIDED))

    temp_zip_path = ""
    extraction_dir = tempfile.mkdtemp(prefix="mcp_audacity_")
    try:
        temp_zip_path = await download_to_temp_async(audio_uri)
        lang = _resolve_language(language)
        tracks = await asyncio.to_thread(extract_tracks_from_aup, temp_zip_path, extraction_dir)
        if not tracks:
            _raise_mapped_error(
                "transcribe_audacity",
                ValueError("No usable audio tracks found in the uploaded Audacity project."),
            )

        transcription_text = await transcribe_and_merge_tracks(
            tracks=tracks, provider=provider, model=model, language=lang, hf_provider=hf_provider
        )
        payload = {
            "source": provider,
            "model": model,
            "language": lang,
            "transcription": transcription_text,
        }
        return _success_envelope(payload)
    except ToolError:
        raise
    except Exception as exc:
        _raise_mapped_error("transcribe_audacity", exc)
    finally:
        cleanup_temp_file(temp_zip_path)
        shutil.rmtree(extraction_dir, ignore_errors=True)


@mcp.tool(name="health", description="Liveness check tool.")
def health() -> dict[str, Any]:
    return {"status": "ok"}
