# AGENTS.md

This file provides guidance to AI coding agents when working with code in this repository.

## Project Overview

ascend-audio-scribe is a speech-to-text microservice that dynamically selects transcription providers per-request: local (faster-whisper with GPU), OpenAI API, or Hugging Face Inference. It also supports multi-track Audacity project transcription with speaker-tagged chronological merging.

## Build & Run Commands

Every command below runs through this module's own virtual environment at `.venv/` (created via
`python -m venv .venv`, see README.md) - never the system Python or pip. Windows interpreter:
`.venv/Scripts/python.exe`; Linux/macOS: `.venv/bin/python`.

Platform support: `pytorch-requirements.txt` pins CUDA 12.6 builds of PyTorch, which exist only for Windows and Linux
on x86_64 and cannot be installed on macOS. The local (faster-whisper) backend therefore needs Windows or Linux with
an NVIDIA GPU. The OpenAI and Hugging Face backends need no PyTorch and work on any platform, including macOS. The
local backend imports `torch` only when it loads a model, and the test suite replaces `torch` with a stub, so on macOS
skip the PyTorch step and install the project alone. Everything else, the test suite included, then works.

Windows:

```bash
# Install dependencies (pytorch first, then the shared library, then the project)
.venv/Scripts/python.exe -m pip install -r pytorch-requirements.txt
.venv/Scripts/python.exe -m pip install -e ../../libs/ascend-python-common[fetch]
.venv/Scripts/python.exe -m pip install -e .[dev]

# Run the server (port 7017)
.venv/Scripts/python.exe -m uvicorn src.main:app --host 0.0.0.0 --port 7017 --reload

# Run all tests
.venv/Scripts/python.exe -m pytest

# Run a single test file
.venv/Scripts/python.exe -m pytest tests/transcription/test_openai_api_speach_to_text.py

# Run a single test
.venv/Scripts/python.exe -m pytest tests/transcription/test_openai_api_speach_to_text.py::test_name -v
```

Linux/macOS (the extra is quoted because zsh treats an unquoted `[dev]` as a glob):

```bash
# Install PyTorch first (Linux with an NVIDIA GPU only, skip this line on macOS)
.venv/bin/python -m pip install -r pytorch-requirements.txt

# Install the shared library first, then the project
.venv/bin/python -m pip install -e "../../libs/ascend-python-common[fetch]"
.venv/bin/python -m pip install -e ".[dev]"

# Run the server (port 7017)
.venv/bin/python -m uvicorn src.main:app --host 0.0.0.0 --port 7017 --reload

# Run all tests
.venv/bin/python -m pytest

# Run a single test file
.venv/bin/python -m pytest tests/transcription/test_openai_api_speach_to_text.py

# Run a single test
.venv/bin/python -m pytest tests/transcription/test_openai_api_speach_to_text.py::test_name -v
```

Docker, identical on every platform:

```bash
docker build -t ascend-audio-scribe:latest .
```

## Architecture

**Entry point**: `src/main.py` builds the FastAPI app with `create_service_app` from `ascend-python-common`, passing a `ServiceDefinition` with the service name, settings, MCP server, REST router, error registry, the `ffmpeg` and `tempdir` readiness probes, the transcript-cleanup lifespan, `ForceJSONUTF8Middleware`, per-tool transcribe rate limits, and the banner content. REST routes and the MCP server share the same port (7017).

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

**Configuration**: `src/config/config.py` subclasses `ServiceSettings` with `McpFetchSettings` (`Settings` class), reads from env vars and `.env` file. `API_PORT` (default 7017) is the only port setting.

**Platform behavior** (via `ascend-python-common`, wired in `src/main.py` with `create_service_app`):
- REST errors are RFC 7807 problem bodies (`application/problem+json`) with `code` and `traceId`. Request validation failures answer `400` with code `validation` and an `errors` list sorted by `field`. `FileSizeExceededError` maps to `413` with code `file_too_large`, `UpstreamProviderError` to `502` with code `upstream_provider`, unexpected failures to `500` with code `internal` and a fixed detail. Unknown paths answer `404` with code `not_found`, wrong methods `405` with code `method_not_allowed` and an `Allow` header. Every body also carries `type`, `title`, `status`, and `instance`.
- MCP refusals are tool errors whose text starts with `<code>: ` (`validation: `, `internal: `). The MCP app is attached at the `/mcp` path only.
- `/health` answers `200 {"status": "ok", "service": "ascend-audio-scribe", "version": ...}` without touching a dependency. `/ready` aggregates the `ffmpeg` and `tempdir` probes and answers `200 {"status": "ready", ...}` or `503 {"status": "not-ready", ...}`. Probes run at once with a 3 s budget.
- Logging comes from the library (`LOG_LEVEL` honoured, `LOG_FORMAT` selects `json` or `color`, lines start with `[ascend-audio-scribe]`). There is no service `logging_config.py` and no `log_config` argument on `uvicorn.run`.
- `RATE_LIMIT_DEFAULT` defaults to `600/minute` and `RATE_LIMIT_TRANSCRIBE` to `60/minute` on the four transcription routes and tools; `/health`, `/ready`, `/metrics`, and `tools/list` are never limited.
- URI fetches go through the library guard (`check_fetch_uri` plus `guarded_get` with `PinnedResolver`): each redirect hop is re-checked, a public URL that redirects to a private address is refused with `validation`, and `file://` stays jailed to `MCP_FILE_URI_ROOT`.

## Code Conventions

- Always use absolute imports starting from `src` (e.g., `from src.config.config import settings`)
- Every package must have an `__init__.py`
- Use FastAPI for REST, FastMCP for MCP tools
- Type hints (PEP 484) on all function signatures
- Pydantic models for data validation and settings
- Logging format must start with `[ascend-audio-scribe]` (handled by `ascend-python-common` `configure_logging`, always true)
- Use async/await for I/O-bound operations
- Self-documenting code; avoid comments
- No magic numbers; extract to named constants or `Settings`
- Use guard clauses and early returns; avoid deep nesting
- Public methods should be concise; extract complex logic to private helpers
- Use global exception handlers over local try-catch
- When instrumenting new code (metrics, logs, or spans), follow [../../docs/OBSERVABILITY.md](../../docs/OBSERVABILITY.md)

## Key Configuration

- Environment variables: `OPENAI_API_KEY`, `HF_TOKEN`, `HF_HOME`
- `API_HOST` - Bind address (default: `0.0.0.0`)
- `API_PORT` - Service port (default: 7017)
- `LOG_LEVEL` - Logging level (default: `INFO`)
- `LOG_FORMAT` - Log format, `json` or `color` (default: `json`)
- `OTEL_EXPORTER_OTLP_ENDPOINT` - OTLP trace export endpoint, export whenever it is set, unset by default
- `OTEL_SDK_DISABLED` - OpenTelemetry's standard switch, `true` turns the SDK off
- `RATE_LIMIT_DEFAULT` - Flood-protection rate limit for REST routes and MCP tools (default: `600/minute`)
- `RATE_LIMIT_TRANSCRIBE` - Stricter limit on the four transcription routes and tools (default: `60/minute`)
- `REDIS_URL` - Shared storage for the rate limit windows, one budget per caller under the key prefix `ascend-audio-scribe` (default: `redis://127.0.0.1:6379/0`)
- `READINESS_PROBE_TIMEOUT_SECONDS` - Budget of each readiness probe (default: `3`)
- `STARTUP_PROBE_TIMEOUT_SECONDS` - Time each startup banner check may take (default: `2`)
- `SECURITY_HSTS_MAX_AGE_SECONDS` - `max-age` of the `strict-transport-security` response header (default: `63072000`)
- `FETCH_MAX_REDIRECT_HOPS` - Redirect hops the URI fetch guard follows (default: `10`)
- `ALLOWED_PRIVATE_HOSTS` - Hosts the URI fetch guard may reach even at a private address (default: empty)
- `MCP_FILE_URI_ROOT` - Jail root for `file://` audio URIs (default: unset, `file://` refused)

`API_HOST`, `API_PORT`, `LOG_LEVEL`, `LOG_FORMAT`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SDK_DISABLED`, and `RATE_LIMIT_DEFAULT` are defined in the `ascend-python-common` `ServiceSettings` base class and subclassed in `src/config/config.py`.
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
