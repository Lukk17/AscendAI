# AGENTS.md

This file provides guidance to AI coding agents when working with code in this repository.

## Project Overview

AudioScribe is a speech-to-text microservice that dynamically selects transcription providers per-request: local (faster-whisper with GPU), OpenAI API, or Hugging Face Inference. It also supports multi-track Audacity project transcription with speaker-tagged chronological merging.

## Build & Run Commands

```bash
# Install dependencies (pytorch first, then the project)
pip install -r pytorch-requirements.txt
pip install -e .[dev]

# Run the server (port 7017)
uvicorn src.main:app --host 0.0.0.0 --port 7017 --reload

# Run all tests
pytest

# Run a single test file
pytest tests/transcription/test_openai_api_speach_to_text.py

# Run a single test
pytest tests/transcription/test_openai_api_speach_to_text.py::test_name -v

# Docker
docker build -t audio-scribe:latest .
```

## Architecture

**Entry point**: `src/main.py` creates the FastAPI app, mounts REST routes and the MCP server on the same port (7017).

**Dual API surface**:
- REST API (`src/api/rest/rest_endpoints.py`): File upload endpoints at `/api/v1/transcribe/{local,openai,hf,audacity}`. Supports SSE streaming (`stream=true`) and direct `.md` FileResponse download (`stream=false`).
- MCP Server (`src/api/mcp/mcp_server.py`): FastMCP tools exposed at `/mcp` (Streamable HTTP), accepting `audio_uri` (file:// or http://)

**Orchestration layer**: `src/scribe.py` is a thin facade that delegates to the three transcription backends. REST and MCP endpoints both call through this layer. Supports optional `progress_callback` for SSE streaming.

**Transcription backends** (`src/transcription/`):
- `local_speech_to_text.py` - faster-whisper, async generator yielding segments with timestamps
- `openai_api_speach_to_text.py` - OpenAI Whisper API, handles chunking for files >25MB, supports `progress_callback`
- `huggingface_api_speach_to_text.py` - HF Inference API, supports `progress_callback`
- `audacity_parser.py` - Extracts tracks from zipped Audacity projects (.aup + _data) using ffmpeg subprocess calls, supports both standard wavetracks and Craig Bot imports
- `conversation_merger.py` - Merges multi-track transcriptions chronologically with `[HH:MM:SS] [Speaker]` format, supports `progress_callback`

**Adapters** (`src/adapters/`):
- `file_service.py` - Temp file management for uploads
- `download_service.py` - Downloads audio from URIs (file://, http/https) for MCP tools
- `download_file_manager.py` - Manages temporary transcript `.md` files for download with TTL-based cleanup

**Configuration**: `src/config/config.py` uses pydantic-settings (`Settings` class), reads from env vars and `.env` file.

## Code Conventions

- Always use absolute imports starting from `src` (e.g., `from src.config.config import settings`)
- Every package must have an `__init__.py`
- Use FastAPI for REST, FastMCP for MCP tools
- Type hints (PEP 484) on all function signatures
- Pydantic models for data validation and settings
- Logging format must start with `[AudioScribe]` (handled by `logging_config.py`)
- Use async/await for I/O-bound operations
- Self-documenting code; avoid comments
- No magic numbers; extract to named constants or `Settings`
- Use guard clauses and early returns; avoid deep nesting
- Public methods should be concise; extract complex logic to private helpers
- Use global exception handlers over local try-catch

## Key Configuration

- Environment variables: `OPENAI_API_KEY`, `HF_TOKEN`, `HF_HOME`
- Settings singleton: `from src.config.config import settings`
- Default port: 7017
- Requires NVIDIA CUDA 12.6 + cuDNN for local transcription
- Requires `ffmpeg` system dependency for audio processing and Audacity track extraction

## Testing

- pytest with `pytest-asyncio` (asyncio_mode = "auto")
- pythonpath configured as `[".", "src"]` in pyproject.toml
- Test files mirror source structure under `tests/`

## Dependencies

Two-file approach:
- `pytorch-requirements.txt` - PyTorch pinned to CUDA 12.6 builds (install first)
- `pyproject.toml` - All other deps with frozen versions
