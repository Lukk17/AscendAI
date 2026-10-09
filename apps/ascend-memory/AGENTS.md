# AGENTS.md - AscendMemory

## Project Overview

AscendMemory is a semantic memory service that provides REST API and MCP server interfaces for storing, searching, and managing user-scoped memories. It uses mem0ai for memory operations backed by Qdrant vector database.

## Tech Stack

- **Language**: Python 3.11
- **Framework**: FastAPI + Uvicorn, FastMCP
- **Version**: 0.1.4
- **Docker Base**: `python:3.11-slim`

## Build & Run Commands

Every command below runs through this module's own virtual environment at `.venv/` (created via
`python -m venv .venv`, see README.md) - never the system Python or pip. Windows interpreter:
`.venv/Scripts/python.exe`; Linux/macOS: `.venv/bin/python`.

Windows:

```bash
# Install the shared library first, then the service
.venv/Scripts/python.exe -m pip install -e ../../libs/ascend-python-common[dev]
.venv/Scripts/python.exe -m pip install -e .[dev]

# Run the server (port 7020)
.venv/Scripts/python.exe -m uvicorn src.main:app --host 0.0.0.0 --port 7020 --reload

# Run tests with the configured 100% branch-coverage gate
.venv/Scripts/python.exe -m pytest --cov=src --cov-branch --cov-report=term-missing --cov-fail-under=100
```

Linux/macOS (the extra is quoted because zsh treats an unquoted `[dev]` as a glob):

```bash
# Install the shared library first, then the service
.venv/bin/python -m pip install -e "../../libs/ascend-python-common[dev]"
.venv/bin/python -m pip install -e ".[dev]"

# Run the server (port 7020)
.venv/bin/python -m uvicorn src.main:app --host 0.0.0.0 --port 7020 --reload

# Run tests with the configured 100% branch-coverage gate
.venv/bin/python -m pytest --cov=src --cov-branch --cov-report=term-missing --cov-fail-under=100
```

Docker, identical on every platform:

```bash
docker build -t ascend-memory:latest .
```

## Architecture

**Dual API surface**:
- REST API: CRUD endpoints for memory operations under `/api/v1/memory/`
- MCP Server: FastMCP tools exposed via Streamable HTTP at `/mcp`. The FastMCP server name is `ascend-memory`.

**Platform behavior** (via `ascend-python-common`, wired in `src/main.py` with `create_service_app`):
- REST errors are RFC 7807 problem bodies (`application/problem+json`) with `code` and `traceId`. Request
  validation failures answer `400` with code `validation` and an `errors` list sorted by `field`. Unexpected
  failures answer `500` with code `internal` and a fixed detail. MCP refusals are tool errors whose text starts
  with `<code>: ` (`validation: `, `internal: `).
- `/health` answers `200 {"status": "ok", "service": "ascend-memory", "version": ...}` without touching a
  dependency. `/ready` aggregates the `qdrant`, `embedding_api`, and `mem0_client` probes and answers `200
  {"status": "ready", ...}` or `503 {"status": "not-ready", ...}`. `/health/legacy` keeps the pre-split contract.
- Logging comes from the library (`LOG_LEVEL` honoured, `LOG_FORMAT` selects `json` or `color`, lines start with
  `[ascend-memory]`). There is no service `logging_config.py` and no `log_config` argument on `uvicorn.run`.

**Key Endpoints**:
- `POST /api/v1/memory/insert` - Store a new memory
- `GET /api/v1/memory/search` - Semantic search across memories
- `DELETE /api/v1/memory` - Delete specific memory
- `POST /api/v1/memory/wipe` - Wipe all memories for a user

**Core Dependencies**:
- mem0ai (2.0.4) - Memory management library
- Qdrant (port 6333) - Vector database backend
- OpenAI-compatible API for embeddings (LM Studio, OpenAI, or Gemini)

**Embedding providers and collections**: `PROVIDER_CONFIGS` in `src/config/config.py` (lines 25-50) hardcodes three
providers, each pinned to its own embedding model, dimension count, and Qdrant collection. The collection name, the
embedding model, and the dimension count are not configurable by environment variable. Only the endpoint and API key
per provider are.

| Provider | Embedding model | Dims | Qdrant collection | Endpoint / key vars |
|---|---|---|---|---|
| `lmstudio` | `text-embedding-nomic-embed-text-v2-moe` | 768 | `ascend_memory_768` | `LMSTUDIO_BASE_URL`, `LMSTUDIO_API_KEY` |
| `openai` | `text-embedding-3-small` | 1536 | `ascend_memory_1536` | `OPENAI_BASE_URL`, `OPENAI_API_KEY` |
| `gemini` | `gemini-embedding-001` | 768 | `ascend_memory_768` | `GEMINI_BASE_URL`, `GEMINI_API_KEY` |

`lmstudio` and `gemini` share `ascend_memory_768` because both embed at 768 dimensions. `openai` gets its own
`ascend_memory_1536` collection. A caller supplies `provider` per REST call or MCP tool call. ascend-ai-agent always
sends one explicitly, resolved from the chat provider's own embedding default. When a caller omits `provider`
entirely, `resolve_provider()` (`src/service/memory_client.py:25`) falls back to `MEM0_DEFAULT_PROVIDER` (default
`lmstudio`).

## Environment Variables

- `MEM0_DEFAULT_PROVIDER` - Embedding provider used when a caller omits `provider` (default: `lmstudio`)
- `LMSTUDIO_BASE_URL` / `LMSTUDIO_API_KEY` - Endpoint and key for the `lmstudio` provider (default base URL: `http://localhost:1234/v1`)
- `OPENAI_API_KEY` - API key for the `openai` provider (required when `provider=openai` is used)
- `OPENAI_BASE_URL` - Endpoint for the `openai` provider (default: `https://api.openai.com/v1`)
- `GEMINI_BASE_URL` / `GEMINI_API_KEY` - Endpoint and key for the `gemini` provider
- `MEM0_LLM_MODEL` - Model mem0 uses for its own extraction LLM (default: `meta-llama-3.1-8b-instruct`). Unlike the
  embedding model, dims, and collection above, this one really is environment-configurable, but it's one value
  shared across all three providers' `llm` block (`src/service/memory_client.py:130-137`), not a per-provider entry.
  Only exercised when `MEM0_INFER_MEMORY=true`.
- `MEM0_INFER_MEMORY` - Enable memory inference (default: false)
- `API_PORT` - Service port (default: 7020)
- `API_HOST` - Bind address (default: `0.0.0.0`)
- `LOG_LEVEL` - Logging level (default: `INFO`)
- `LOG_FORMAT` - Log format, `json` or `color` (default: `json`)
- `OTEL_EXPORTER_OTLP_ENDPOINT` - OTLP trace export endpoint, export whenever it is set, unset by default
- `OTEL_SDK_DISABLED` - OpenTelemetry's standard switch, `true` turns the SDK off
- `RATE_LIMIT_DEFAULT` - Flood-protection rate limit for REST routes and MCP tools (default: `6000/minute`)
- `READINESS_PROBE_TIMEOUT_SECONDS` - Budget of each readiness probe (default: `3`)
- `STARTUP_PROBE_TIMEOUT_SECONDS` - Time each startup banner check may take (default: `2`)
- `SECURITY_HSTS_MAX_AGE_SECONDS` - `max-age` of the `strict-transport-security` response header (default: `63072000`)
- `REDIS_URL` - Shared storage for the rate limit windows, one budget per caller under the key prefix `ascend-memory` (default: `redis://127.0.0.1:6379/0`)

`API_HOST`, `API_PORT`, `LOG_LEVEL`, `LOG_FORMAT`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SDK_DISABLED`, and `RATE_LIMIT_DEFAULT` are defined in the
`ascend-python-common` `ServiceSettings` base class and subclassed in `src/config/config.py`. The service reads
no `MCP_ALLOWED_HOSTS` (it fetches no caller URI) and has no `MCP_PORT`.
- `QDRANT_HOST` / `QDRANT_PORT` - Qdrant connection
- `DEFAULT_USER_ID` - Fallback `user_id` when a REST or MCP caller omits it (default: `default_user`)
- `MAX_USER_ID_LENGTH` - Input cap on `user_id` length (default: `128`)
- `MAX_QUERY_LENGTH` - Input cap on search query length (default: `2048`)
- `MAX_MEMORY_TEXT_LENGTH` - Input cap on stored memory text length (default: `32768`)
- `MAX_SEARCH_LIMIT` - Upper bound on the `limit` search parameter (default: `100`)

`compose.yaml`'s `ascend-memory` service sets `API_HOST=0.0.0.0` and `LOG_LEVEL=INFO` explicitly, matching the code
defaults, so neither is a real override. The other six vars added above (`MEM0_LLM_MODEL`, `DEFAULT_USER_ID`,
`MAX_USER_ID_LENGTH`, `MAX_QUERY_LENGTH`, `MAX_MEMORY_TEXT_LENGTH`, `MAX_SEARCH_LIMIT`) aren't set in `compose.yaml`
at all, so the running container uses their code defaults as-is.

`MEM0_EMBEDDING_MODEL`, `MEM0_COLLECTION_NAME`, and `MEM0_EMBEDDING_DIMS` are not read anywhere in this service
(verified: zero matches under `src/`). The embedding model, collection name, and dimension count come from the
provider table above, not from the environment. Qdrant on this host still holds a bare `ascend_memory` collection
alongside `ascend_memory_768` and `ascend_memory_1536`: a leftover from before the dimension-suffix scheme, not
something this service reads or writes to.

## Code Conventions

- Absolute imports from `src`
- Type hints (PEP 484) on all function signatures
- Pydantic models for request/response validation
- Async/await for I/O-bound operations
- User-scoped memory operations (all operations require a user_id)
- When instrumenting new code (metrics, logs, or spans), follow [../../docs/OBSERVABILITY.md](../../docs/OBSERVABILITY.md)

## Relevant Skills

- `/python-patterns`
- `/api-design`, `/docker-patterns`
