# AGENTS.md — PaddleOCR

## Project Overview

PaddleOCR is an OCR (Optical Character Recognition) service that wraps the PaddleOCR library behind a FastAPI REST API and FastMCP server. It supports multi-language text extraction from images and PDFs.

## Tech Stack

- **Language**: Python 3.11
- **Framework**: FastAPI + Uvicorn, FastMCP 3.3.1
- **Version**: 0.1.0
- **Key Libraries**: PaddlePaddle 3.3.1, PaddleOCR 3.6.0, Pillow 12.2.0, aiohttp 3.13.5
- **Docker Base**: `python:3.11-slim` (multi-stage build with pre-cached models)

## Build & Run Commands

```bash
pip install -e .[dev]
```

```bash
uvicorn src.main:app --host 0.0.0.0 --port 7022 --reload
```

```bash
pytest
```

```bash
pytest --cov=src --cov-report=term-missing
```

```bash
ruff check .
```

```bash
mypy src
```

```bash
docker build -t ascend-paddle-ocr:latest .
```

## Architecture

**Dual API surface** (port 7022):

- **REST** — `POST /v1/ocr` (multipart, `file` + optional `lang`), `GET /health` (liveness), `GET /ready` (readiness).
- **MCP** — `tools/call name="ocr_process"` with `{file_uri, lang}`. URI-only; supports `http://`, `https://`, and `file://` (jailed). See ADR-001.

**File transport contract** (MCP):

- `http(s)://` is the primary path. PaddleOCR fetches via aiohttp, subject to an SSRF guard (block private/loopback IPs unless the hostname is on `MCP_ALLOWED_HOSTS`).
- `file://` is disabled unless `MCP_FILE_URI_ROOT` is set. When set, the URI is jailed to that directory via `realpath`; traversal outside is rejected. No upload endpoint — operator drops bytes into the root out-of-band.
- All other schemes (bare paths, `ftp://`, `data:`, Windows `C:\...`) are rejected with `UNSAFE_URI`.

**Error model** (REST + MCP, see ADR-002):

| Code                    | REST status | When raised                                                       |
| ----------------------- | ----------- | ----------------------------------------------------------------- |
| `OCR_FAILED`            | 422         | OCR engine raised on valid input                                  |
| `FILE_TOO_LARGE`        | 400         | Source exceeds `MAX_FILE_SIZE_MB`                                 |
| `UNSUPPORTED_FILE_TYPE` | 400         | Content type not image/* or application/pdf                       |
| `UNSAFE_URI`            | 400         | SSRF guard, file:// jail, or scheme check rejected the URI        |
| `DOWNLOAD_FAILED`       | 502         | Upstream URI fetch failed                                         |
| `INTERNAL_ERROR`        | 500         | Unhandled exception                                               |

Architecture decisions live under [`docs/architecture/decisions/`](docs/architecture/decisions/README.md).

## Environment Variables

- `API_PORT` — service port (default `7022`).
- `API_HOST` — bind address (default `0.0.0.0`).
- `LOG_LEVEL` — `DEBUG | INFO | WARNING | ERROR | CRITICAL` (default `INFO`).
- `DEFAULT_LANGUAGE` — default OCR language; must match `^[a-z]{2,5}$` (default `en`).
- `MAX_FILE_SIZE_MB` — max source size, enforced on both REST upload and MCP download (default `50`).
- `OCR_REQUEST_TIMEOUT` — per-request engine timeout in seconds, enforced via `asyncio.wait_for` (default `120`).
- `ENGINE_CACHE_MAX_SIZE` — max number of language engines kept resident; LRU eviction beyond this (default `8`).
- `MCP_FILE_URI_ROOT` — when set, enables `file://` URI scheme jailed to this absolute path. Unset by default ⇒ `file://` rejected.
- `MCP_ALLOWED_HOSTS` — comma-separated hostnames that bypass the SSRF private-IP check. Required for the docker-internal MinIO pattern (set to `minio`). Default empty ⇒ strict block.
- `MCP_DOWNLOAD_TIMEOUT_SECONDS` — total timeout for MCP HTTP fetch (default `30`).

## Code Conventions

- Absolute imports from `src`.
- Type hints (PEP 484) on all function signatures; `dict[str, object]` preferred over `dict[str, Any]`.
- Pydantic models for data validation; `Field(...)` constraints on every user-influenced field.
- Constructor injection in `OcrService`; module-level singletons for `ocr_service` and the FastMCP HTTP session.
- Linting: ruff (E/F/W/I/B/UP/SIM/RUF/S/PL); type-checking: mypy with `paddleocr.*` / `paddlepaddle.*` / `fastmcp.*` ignored.

## Relevant Skills

- `/python-patterns`, `/python-testing`
- `/api-design`, `/docker-patterns`
- `/security-review` (URL handling, SSRF, jail)
