# AGENTS.md — ascend-ocr

## Project Overview

ascend-ocr is an OCR (Optical Character Recognition) service that wraps the PaddleOCR library behind a FastAPI REST API and FastMCP server. It supports multi-language text extraction from images and PDFs.

## Tech Stack

- **Language**: Python 3.11
- **Framework**: FastAPI + Uvicorn, FastMCP 3.3.1
- **Version**: 0.2.1
- **Key Libraries**: PaddlePaddle 3.3.1, PaddleOCR 3.6.0, Pillow 12.2.0, aiohttp 3.13.5
- **Docker Base**: `python:3.11-slim` (multi-stage build with pre-cached models)

## Build & Run Commands

Every command below runs through this module's own virtual environment at `.venv/` (created via
`python -m venv .venv`, see README.md) — never the system Python or pip. Windows interpreter:
`.venv/Scripts/python.exe`; Linux/macOS: `.venv/bin/python`.

```bash
.venv/Scripts/pip.exe install -e .[dev]
```

```bash
.venv/Scripts/uvicorn.exe src.main:app --host 0.0.0.0 --port 7022 --reload
```

```bash
.venv/Scripts/pytest.exe
```

```bash
.venv/Scripts/pytest.exe --cov=src --cov-report=term-missing
```

```bash
.venv/Scripts/ruff.exe check .
```

```bash
.venv/Scripts/mypy.exe src
```

```bash
docker build -t ascend-ocr:latest .
```

## Architecture

**Dual API surface** (port 7022):

- **REST** — `POST /v1/ocr` (multipart, `file` + optional `lang`), `GET /health` (liveness), `GET /ready` (readiness).
- **MCP** — `tools/call name="ocr_process"` with `{file_uri, lang}`. URI-only; supports `http://`, `https://`, and `file://` (jailed). See ADR-001.

**File transport contract** (MCP):

- `http(s)://` is the primary path. ascend-ocr fetches via aiohttp, subject to an SSRF guard (block private/loopback IPs unless the hostname is on `MCP_ALLOWED_HOSTS`).
- `file://` is disabled unless `MCP_FILE_URI_ROOT` is set. When set, the URI is jailed to that directory via `realpath`; traversal outside is rejected. No upload endpoint — operator drops bytes into the root out-of-band.
- All other schemes (bare paths, `ftp://`, `data:`, Windows `C:\...`) are rejected with `UNSAFE_URI`.

**Error model** (REST + MCP, see ADR-002):

| Code                    | REST status | When raised                                                                      |
| ----------------------- | ----------- | --------------------------------------------------------------------------------- |
| `OCR_FAILED`            | 422         | OCR engine raised on valid input, or a request's own budget expired mid-document  |
| `FILE_TOO_LARGE`        | 400         | Source exceeds `MAX_FILE_SIZE_MB`, `OCR_MAX_INFERENCE_PIXELS`, or `OCR_MAX_PAGES`  |
| `UNSUPPORTED_FILE_TYPE` | 400         | Content type not image/* or application/pdf                                       |
| `UNSAFE_URI`            | 400         | SSRF guard, file:// jail, or scheme check rejected the URI                        |
| `DOWNLOAD_FAILED`       | 502         | Upstream URI fetch failed                                                         |
| `INTERNAL_ERROR`        | 500         | Unhandled exception                                                               |

Architecture decisions live under [`docs/architecture/decisions/`](docs/architecture/decisions/README.md).

**Request budgets and the single worker** (see [ADR-006](docs/architecture/decisions/ADR-006-detector-input-bound.md)
and `openspec/changes/stop-ocr-getting-stuck-on-large-jobs/design.md`):

- A request's time budget is `min(pages * OCR_PAGE_TIMEOUT_SECONDS, OCR_REQUEST_TIMEOUT)`. The worker checks that
  budget between pages (`predict_iter()`, not `predict()`), so it stops itself instead of being abandoned. A worker
  that does not return within `OCR_RECLAMATION_GRACE_SECONDS` past its own budget is replaced; a broken pool is
  rebuilt the same way. Both trigger `/ready` reporting `not-ready` for the duration, never `/health`.
- Requests queue on an admission gate with `OCR_WORKER_COUNT` permits, holding their own deadline while waiting. A
  request whose budget expires while queued fails without ever reaching the worker.
- `OCR_WORKER_COUNT` is a memory constraint, not only a throughput one: one call's peak is already most of the
  container's memory ceiling (see the memory model below), so `service_peak_MiB ~= per_call_peak_MiB *
  OCR_WORKER_COUNT`. Raising it multiplies that peak.

**Memory model** — measured, not estimated (see `openspec/changes/stop-ocr-getting-stuck-on-large-jobs/design.md`,
"The measured memory model"): `peak_MiB ~= 635 + 5302 * megapixels_of_the_largest_page + 11.5 * pages`, with text
detection responsible for 94 percent of the transient. `OCR_DETECTOR_MAX_SIDE` caps what detection sees regardless of
the page's own resolution, which is what makes an A4 page (144 dpi, fixed by the library, see
[ADR-005](docs/architecture/decisions/ADR-005-fixed-pdf-render-resolution.md)) affordable rather than merely bounded.
`OCR_MAX_INFERENCE_PIXELS` refuses, at the request boundary before any decode, whatever that bound does not make
affordable. The startup banner also reads this container's own cgroup memory limit
(`src/config/memory_limits.py`) and logs a `WARNING` — never a refusal — when `OCR_WORKER_COUNT x` one call's peak
meets or exceeds it; see "Warn, don't refuse" in
[07-deployment-view.md](docs/architecture/arc42/07-deployment-view.md).

## Environment Variables

- `API_PORT` — service port (default `7022`).
- `API_HOST` — bind address (default `0.0.0.0`).
- `LOG_LEVEL` — `DEBUG | INFO | WARNING | ERROR | CRITICAL` (default `INFO`).
- `DEFAULT_LANGUAGE` — default OCR language; must match `^[a-z]{2,5}$` (default `en`).
- `MAX_FILE_SIZE_MB` — max source size, enforced on both REST upload and MCP download (default `50`).
- `OCR_REQUEST_TIMEOUT` — absolute ceiling on one request in seconds, the larger of the two deadline inputs (default `120`).
- `ENGINE_CACHE_MAX_SIZE` — max number of language engines kept resident; LRU eviction beyond this (default `2`, matching the two languages — `en`, `pl` — the Dockerfile pre-caches; a workload that alternates a third language reloads an engine on every switch instead of keeping it resident).
- `MCP_FILE_URI_ROOT` — when set, enables `file://` URI scheme jailed to this absolute path. Unset by default ⇒ `file://` rejected.
- `MCP_ALLOWED_HOSTS` — comma-separated hostnames that bypass the SSRF private-IP check. `host.docker.internal` reaches the object store on host ports 9070/9071 from inside the container. Default empty ⇒ strict block.
- `MCP_DOWNLOAD_TIMEOUT_SECONDS` — total timeout for MCP HTTP fetch (default `30`).
- `OCR_WORKER_COUNT` — number of inference worker processes and admission-gate permits, both read from this one setting so they cannot disagree. A memory constraint, not a throughput knob (default `1`).
- `OCR_PAGE_TIMEOUT_SECONDS` — per-page time allowance the worker checks between pages via `predict_iter()` (default `120`).
- `OCR_DISPATCH_MARGIN_SECONDS` — headroom the worker's own budget subtracts so it gives up slightly before the parent does (default `5`).
- `OCR_MAX_INFERENCE_PIXELS` — pixel ceiling on what one inference may receive, checked from the file header before decode; refused with `FILE_TOO_LARGE` (default `2500000`, the provisional value design.md's own guidance settles on pending task 1.6's confirmation at higher ceilings).
- `OCR_DETECTOR_MAX_SIDE` — bounds the longest side text detection sees via `text_det_limit_type="max"`, independent of the page's own resolution; set to empty to restore the library's own unbounded behaviour (default `1536`, the owner's measured choice — see [ADR-006](docs/architecture/decisions/ADR-006-detector-input-bound.md)).
- `OCR_POOL_REBUILD_MAX_CONSECUTIVE` — consecutive failed pool rebuilds before the service stops trying and stays not-ready; resets on the first request that completes (default `3`).
- `OCR_SCRATCH_DIR` — directory for the worker's temporary upload copy; swept of anything older than `OCR_REQUEST_TIMEOUT + OCR_DISPATCH_MARGIN_SECONDS` by every fresh worker and at startup, so a killed worker's leaked file cannot accumulate (default an `ascend-ocr-scratch` directory under the system temp path).

Two further values are derived properties on `Settings`, not settings themselves, so they cannot drift out of
agreement with their inputs: `OCR_MAX_PAGES = floor(OCR_REQUEST_TIMEOUT / OCR_PAGE_TIMEOUT_SECONDS)` and
`OCR_RECLAMATION_GRACE_SECONDS = OCR_PAGE_TIMEOUT_SECONDS + OCR_DISPATCH_MARGIN_SECONDS`. Tune them by tuning their
inputs.

## Code Conventions

- Absolute imports from `src`.
- Type hints (PEP 484) on all function signatures; `dict[str, object]` preferred over `dict[str, Any]`.
- Pydantic models for data validation; `Field(...)` constraints on every user-influenced field.
- Constructor injection in `OcrService`; module-level singletons for `ocr_service` and the FastMCP HTTP session.
- Linting: ruff (E/F/W/I/B/UP/SIM/RUF/S/PL); type-checking: mypy with `paddleocr.*` / `fastmcp.*` / `slowapi.*` / `prometheus_fastapi_instrumentator.*` / `pypdfium2.*` ignored.

## Relevant Skills

- `/python-patterns`
- `/api-design`, `/docker-patterns`
- `/security-review` (URL handling, SSRF, jail)
