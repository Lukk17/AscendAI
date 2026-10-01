# AGENTS.md - ascend-ocr

## Project Overview

ascend-ocr is an OCR (Optical Character Recognition) service that wraps the PaddleOCR library behind a FastAPI REST API and FastMCP server. It supports multi-language text extraction from images and PDFs.

## Tech Stack

- **Language**: Python 3.11
- **Framework**: FastAPI + Uvicorn, FastMCP 3.3.1
- **Version**: 0.3.0
- **Key Libraries**: PaddlePaddle 3.3.1, PaddleOCR 3.7.0, Pillow 12.2.0, aiohttp 3.13.5
- **Docker Base**: `python:3.11-slim` (multi-stage build with pre-cached models)

## Build & Run Commands

Every command below runs through this module's own virtual environment at `.venv/` (created via
`python -m venv .venv`, see README.md) and always as `python -m <tool>`, never the system Python or pip and never a
console-script shim such as `ruff.exe`, which exits 1 silently in this environment. The commands differ between
platforms only in the interpreter path.

Windows (PowerShell or Git Bash):

```bash
.venv/Scripts/python.exe -m pip install -e .[dev]
```

```bash
.venv/Scripts/python.exe -m uvicorn src.main:app --host 0.0.0.0 --port 7022 --ws none --reload
```

```bash
.venv/Scripts/python.exe -m pytest
```

Every warning fails the run on both platforms (`filterwarnings = ["error"]` in `pyproject.toml`), so fix a new warning at its cause and never add an ignore entry unless it comes from a third-party library with no fix.

The default run includes the contract test, which needs the committed pact file `contracts/pacts/ascend-agent-ascend-ocr.json`. For a run without it:

```bash
.venv/Scripts/python.exe -m pytest -m "not contract"
```

```bash
.venv/Scripts/python.exe -m pytest --cov=src --cov-report=term-missing
```

Only the Pact provider verification, which needs `contracts/pacts/ascend-agent-ascend-ocr.json` at the repo root, written by the ascend-agent consumer tests:

```bash
.venv/Scripts/python.exe -m pytest -m contract --no-cov
```

```bash
.venv/Scripts/python.exe -m ruff check .
```

```bash
.venv/Scripts/python.exe -m ruff format --check .
```

```bash
.venv/Scripts/python.exe -m mypy src tests
```

Linux or macOS:

```bash
.venv/bin/python -m pip install -e .[dev]
```

```bash
.venv/bin/python -m uvicorn src.main:app --host 0.0.0.0 --port 7022 --ws none --reload
```

```bash
.venv/bin/python -m pytest
```

The default run includes the contract test, which needs the committed pact file. For a run without it:

```bash
.venv/bin/python -m pytest -m "not contract"
```

```bash
.venv/bin/python -m pytest --cov=src --cov-report=term-missing
```

Only the Pact provider verification:

```bash
.venv/bin/python -m pytest -m contract --no-cov
```

```bash
.venv/bin/python -m ruff check .
```

```bash
.venv/bin/python -m ruff format --check .
```

```bash
.venv/bin/python -m mypy src tests
```

The container image, identical on every platform:

```bash
docker build -t ascend-ocr:latest .
```

## Architecture

**Dual API surface** (port 7022). Every request is a job: a submission is answered with an identifier, never with
the document's text, and the recognised text is written to object storage as one Markdown file whose address the
state carries. See [ADR-008](docs/architecture/decisions/ADR-008-every-request-is-a-job.md) and
[ADR-009](docs/architecture/decisions/ADR-009-results-in-object-storage.md).

- **REST**: `POST /v1/ocr/jobs` (multipart, `file` + optional `lang`, `quality` and `straighten`, answers 202), `GET /v1/ocr/jobs/{job_id}`,
  `GET /v1/ocr/jobs`, `DELETE /v1/ocr/jobs/{job_id}`, `GET /health` (liveness), `GET /ready` (readiness).
  `POST /v1/ocr` is removed and answers 404 like any unknown path.
- **MCP**: `ocr_submit` with `{file_uri, lang, quality, straighten}`, plus `ocr_job_status`, `ocr_list_jobs` and `ocr_cancel_job`. The
  removed `ocr_process` tool is not advertised at all. URI-only; supports `http://`, `https://`, and `file://`
  (jailed). See ADR-001.

**Quality modes and page rendering** (see
[ADR-010](docs/architecture/decisions/ADR-010-quality-modes-and-service-side-rendering.md)). The service renders
every PDF page itself with pypdfium2 and decodes every image with Pillow, one page at a time, and hands PaddleOCR an
array, so the library's fixed 144 dpi rasterizer is off the path. `quality` picks one of two locked pairs of render
resolution and detector bound, and a caller never supplies either number:

| Mode | Setting | Render resolution | Detector bound | Largest page long side |
|---|---|---|---|---|
| `normal` | `OCR_QUALITY_NORMAL` | 150 dpi | 1024 | 2100 px |
| `high` (default) | `OCR_QUALITY_HIGH` | 300 dpi | 1536 | 4200 px |

The largest page a mode supports is US Legal, 14 inches, at its resolution. A larger PDF page is rendered at the lower
scale that fits it, and a larger image is downscaled to it with its aspect ratio kept. Nothing is scaled up and
nothing is refused for being large. A pair whose rendered long side exceeds 3.3 times its detector bound is refused at
startup, because 3.3x is the largest downscale measured to read every line and 6.85x read every line as garbage. A
multi-frame TIFF is as many pages as it has frames.

Preprocessing and `straighten` (see
[ADR-011](docs/architecture/decisions/ADR-011-explicit-preprocessing-and-straighten.md)). Every preprocessing flag is
named on the engine constructor and on every call, never left to a PaddleOCR default. Every request gets page
orientation (`PP-LCNet_x1_0_doc_ori`, fixes pages turned 90 or 180 degrees) and text line orientation
(`PP-LCNet_x1_0_textline_ori`, one line per classifier call, because the library's batch of 6 turned upright lines
upside down on a mixed page). Unwarping (`UVDoc`) is off, because it reads a clean flat page as garbage. `straighten`
(boolean, default `false`) turns UVDoc on for that request only. It is meant for phone photos of bent, curled or
crumpled paper, is recommended with `quality=high`, and is harmful on clean scans and PDFs. It is stored in the job
record and echoed in the status result beside `quality`. Every engine loads all three models once and the request
switches UVDoc per call, so the engine cache stays keyed by the model pair and a straightened request needs no second
engine. The image's download step (`preload_models()` in `src/service/ocr_service.py`) builds every pair in
`Settings.reachable_model_pairs()` the same way, so no model is downloaded at request time.

**File transport contract** (MCP):

- `http(s)://` is the primary path. ascend-ocr fetches via aiohttp, subject to an SSRF guard (block private/loopback IPs unless the hostname is on `MCP_ALLOWED_HOSTS`).
- `file://` is disabled unless `MCP_FILE_URI_ROOT` is set. When set, the URI is jailed to that directory via `realpath`; traversal outside is rejected. No upload endpoint - operator drops bytes into the root out-of-band.
- All other schemes (bare paths, `ftp://`, `data:`, Windows `C:\...`) are rejected with `UNSAFE_URI`.

**Error model** (REST + MCP, see ADR-002):

| Code                    | REST status | When raised                                                                      |
| ----------------------- | ----------- | --------------------------------------------------------------------------------- |
| `OCR_FAILED`            | 422         | OCR engine raised on valid input, or a document's own reading budget expired      |
| `FILE_TOO_LARGE`        | 400         | Source exceeds `MAX_FILE_SIZE_MB`, an image frame exceeds `OCR_MAX_SOURCE_PIXELS`, or the document exceeds `OCR_JOB_MAX_PAGES`. An oversized page is shrunk and read, never refused |
| `UNSUPPORTED_FILE_TYPE` | 400         | Content type not image/* or application/pdf                                       |
| `UNSUPPORTED_LANGUAGE`  | 400         | `lang` is outside `SUPPORTED_LANGUAGES`, refused at submission before anything is fetched, stored or queued. The detail lists the supported languages |
| `UNSAFE_URI`            | 400         | SSRF guard, file:// jail, or scheme check rejected the URI                        |
| `DOWNLOAD_FAILED`       | 502         | Upstream URI fetch failed                                                         |
| `QUEUE_FULL`            | 503         | The queue is at `OCR_JOB_QUEUE_MAX_PAGES` or `OCR_JOB_QUEUE_MAX_DOCUMENTS`, with `Retry-After` |
| `JOB_NOT_FOUND`         | 404         | Identifier unknown, expired, or not shaped like one                               |
| `INTERNAL_ERROR`        | 500         | Unhandled exception                                                               |

Three further reasons live inside a job record and are never HTTP statuses, because reading a record that says it
failed is a successful read: `SERVICE_RESTARTED`, `RESULT_STORE_UNAVAILABLE` and `LIFETIME_EXCEEDED`. The first two
carry `retryable: true`, because nothing was learned about the document.

An expected refusal (`UNSAFE_URI`, `UNSUPPORTED_FILE_TYPE`, `FILE_TOO_LARGE`, `UNSUPPORTED_LANGUAGE`, `QUEUE_FULL`,
`JOB_NOT_FOUND`, and the upstream `DOWNLOAD_FAILED`) is logged as one WARNING line naming its code, with no traceback
and never a URI's userinfo, on both surfaces. On MCP it is raised as FastMCP's `ToolError` reading `CODE: detail`, so
FastMCP adds no ERROR line of its own. An unexpected exception is still logged at ERROR with its traceback. See the
third 2026-09-25 amendment to ADR-002.

Every log line carries `correlation_id`, the `x-request-id` of the HTTP request being served. An inbound
`x-request-id` is kept only when it is 1 to 128 characters of letters, digits, `.`, `_`, `:` and `-`
(`ACCEPTED_CORRELATION_ID_PATTERN` in `src/api/middleware/correlation_id.py`). Any other value, including one with a
byte outside ASCII or a control character, is replaced by a fresh id, which is then logged and echoed. Every MCP
request (tool calls, `tools/list`, resources, prompts) is logged under the id of the HTTP request that carried it,
never the one that opened the session, and each line written while that request is bound also carries
`mcp_session_id`, the first 16 hex characters of the SHA-256 digest of the session's `mcp-session-id`, so one
session's requests can be grouped without writing the live session handle into the log. Two places bind it, both
through `digest_of_mcp_session_id`. `McpRequestLogContextMiddleware` in `src/api/mcp/request_log_context.py` binds it
inside the MCP SDK's session task, where the MCP request runs. `CorrelationIdMiddleware` binds it in the HTTP
request's own task, for the whole request, only for a request to the MCP endpoint (path exactly `MCP_ENDPOINT_PATH`,
`/mcp`, in `src/config/config.py`, the one constant `src/main.py` passes to both `mcp.http_app` and the middleware)
that carries an `mcp-session-id` header the SDK accepts (visible ASCII, the SDK's `SESSION_ID_PATTERN`), so uvicorn's
access line and every other line written in that task carry it too. It is the digest of the value the caller sent,
not proof that a session exists: on the 404 the SDK answers for an unknown or expired session it names no live
session. A request to any other path never carries it, whatever headers it sends. An `initialize` request carries no
such header, because its response creates the session, so `CorrelationIdMiddleware` binds the digest of the
response's `mcp-session-id` header only while the response start is sent, which is when uvicorn writes the access
line. That access line is the one line that ties the opening request's `correlation_id` to the session in the field
itself. The caller chooses `correlation_id` whenever it sends an acceptable `x-request-id`, so the id is a debugging
aid and must never be used to decide who did something.

`CorrelationIdMiddleware` is the outermost layer of the app: `build_middleware_stack` of the FastAPI subclass in
`src/main.py` wraps Starlette's whole stack in it, `ServerErrorMiddleware` included, and nothing else registers it.
When an unhandled exception ends a request, the `INTERNAL_ERROR` line `_global_exception_handler` writes and the
500's access line are therefore written while the request's ids are bound, and the 500 carries `x-request-id` like
every other response. Uvicorn writes its own `Exception in ASGI application` line after the app has raised, outside
every ASGI layer, so the middleware attaches the request's ids to the exception on its way out, and
`CorrelationIdLogFilter` uses them for a record whose exception carries them when no request is bound. That line
carries the same `correlation_id`, and the session digest for a request to the MCP endpoint.

In the JSON format every line names both fields: `correlation_id` is `-` outside any request (a job state transition
the job runner writes while it reads a document), and `mcp_session_id` is `null` on every line of a request to any
path other than the MCP endpoint (every REST line, `/health`, `/ready` and `/metrics` included, even when the request
sends an `mcp-session-id` header), on a line of an MCP endpoint request that carries no acceptable `mcp-session-id`
header (every line of an `initialize` request except its access line), on lines outside any request, and on the MCP
SDK's transport lines written outside a request that carries the header: `Created new transport` during
`initialize`, and the idle timeout, crash and clean-up lines the session's own task writes. `Terminating session` on
DELETE is written in the DELETE request's own task and carries the digest. The color format prints `[<correlation_id> <mcp_session_id>]`, with `-`
for either one when it is missing. The one line that cannot carry the id of its own request is the MCP SDK's INFO line
`Processing request of type ...`, written before any FastMCP middleware runs, which carries the id of the
`initialize` request that opened the session and no `mcp_session_id`.

The raw session id never leaves the process. The MCP SDK writes it into its own transport lines (new session, idle
timeout, crash with traceback, clean-up, `Terminating session` on DELETE), and `McpSessionIdRedactionFilter`
replaces every 32-hex-character token in those lines and their traceback text with its digest. It runs as a logger
filter on `mcp.server.streamable_http_manager` and `mcp.server.streamable_http`, before any handler, so a handler added
later cannot bypass it, and again as a handler filter on the root handler in both formats. It rewrites every 32-hex run
in those two loggers' lines, not only session ids. `setup_logging` removes the handlers of `fastmcp`, `uvicorn`,
`uvicorn.error` and `uvicorn.access`, sets them to `NOTSET` and turns propagation on. It runs when `src.main` is
imported, after uvicorn has applied its own logging config (the commands above pass no `--log-config`), so FastMCP's
lines, uvicorn's access lines and the startup banner all go through the root handler's format and filters under
`LOG_LEVEL` (`FASTMCP_LOG_LEVEL`, uvicorn's `--log-level` and `--no-access-log` have no effect). With tracing on,
`McpSessionDigestSpanExporter` in `src/observability/tracing.py` replaces the raw id with the digest in the span
attributes `mcp.session.id`, `http.request.header.mcp_session_id` and `http.response.header.mcp_session_id` before any
span is exported, and keeps the span's events, links, status, resource, scope and dropped counts. All three use `digest_of_mcp_session_id` in
`src/api/middleware/correlation_id.py`. See the fourth 2026-09-25 amendment to ADR-002.

Architecture decisions live under [`docs/architecture/decisions/`](docs/architecture/decisions/README.md).

**The queue, the reading budget and the single worker** (see
[ADR-008](docs/architecture/decisions/ADR-008-every-request-is-a-job.md) and
[ADR-006](docs/architecture/decisions/ADR-006-detector-input-bound.md)):

- One queue, strict submission order, no priority classes, and no path to the worker except through it. The job
  runner is the single consumer and the only caller of `dispatch_ocr_request`, which is what makes every statement
  about what runs at once true by construction.
- A page's allowance is `OCR_PAGE_ALLOWANCE_HEADROOM` times the worst measured page of the engine that reads it:
  4.5 x 25.1 s = 112.95 s on `PP-OCRv6_small_det`, the engine every supported language reads with, where 25.1 s is a
  dense Polish A4 prose page (48 lines, 4000 characters) in `high` mode, measured with the engine's threads capped to
  the container's CPUs. A document's reading budget is `pages` times its own engine's allowance, counted from the
  moment the runner picks it up.
  Time spent waiting is not charged against it, because no caller is holding a connection and the wait is bounded
  separately by `OCR_JOB_QUEUE_MAX_PAGES`. The worker checks the budget between pages (`predict_iter()`, not
  `predict()`), so it stops itself instead of being abandoned. A worker that does not return within
  one page allowance plus `OCR_DISPATCH_MARGIN_SECONDS` past its own budget is replaced; a broken pool is rebuilt the same way; a cancel
  is the third trigger of the same path and kills the worker rather than draining it. All three trigger `/ready`
  reporting `not-ready` for the duration, never `/health`. A cancel answers without waiting for its replacement: the
  record reads `cancelled` at once, the replacement runs as a background task, and shutdown waits for it before the
  pool is stopped (see the 2026-09-25 amendment to ADR-004). The runner takes no next document while a replacement is
  pending, so a cancelled document that finishes before the kill lands never hands the next one to the dying worker.
  A dispatch releases the admission permit to the gate it took it from, so a rebuild during a read never adds a
  permit to the new gate. A cancel that lands before dispatch is kept: `JobStore.start` moves a record to `running`
  only while it still reads `waiting`, and the runner skips a document it refuses without replacing any worker. The
  queue is measured by `ascendocr_job_queue_documents` and `ascendocr_job_queue_pages`, and the wait by
  `ascendocr_job_queue_wait_seconds`.
- Every engine runs as many compute threads as the container's CPU quota allows. `build_engine` passes
  `cpu_threads=detect_cpu_limit()` (`src/config/cpu_limits.py`), because PaddleOCR otherwise passes its own 10 and
  `PADDLE_PDX_CPU_NUM_THREADS` never reaches paddlex. OpenCV is capped to the same number at import.
- The queue is bounded twice, in pages and in documents, and a submission beyond either bound is refused with
  `QUEUE_FULL` and a 503 rather than accepted into an unbounded wait.
- `OCR_WORKER_COUNT` governs both the pool size and the admission gate's permits. One document is read at a time,
  and every promise the queue makes about how long a submission waits is computed against that, so raising it is a
  change to the promise as well as to throughput. It also multiplies the memory peak:
  `service_peak_MiB ~= api_process_MiB + per_call_peak_MiB * OCR_WORKER_COUNT`.

**Memory model**, measured in a Linux container with 4 CPUs as the cgroup's `memory.peak`, worst of three runs, image
`7b2cb25e7360`, PaddleOCR 3.7.0, on the `PP-OCRv6_small` pair every supported language reads with:

| Page | Mode | Peak | Time |
|---|---|---|---|
| A4 at 300 dpi, 2480 x 3508 px, 50 lines | `high` | 1016 MiB | 20.5 s |
| 4200 x 4200 px, 50 lines, the largest `high` page | `high` | 1236 MiB | 24.6 s |
| 3162 x 4200 px photo, straightened, the worst of six | `high` | 2771 MiB | 28.4 s |
| 2100 x 2100 px, 50 lines, the largest `normal` page | `normal` | 858 MiB | 18.3 s |

The times in that table, and the 50.4 s dense-page figure that set the allowance until 2026-09-25, were measured
while PaddleOCR ran its own 10 compute threads throttled under the 4-CPU quota. With the engine's threads capped to
the container's CPUs (ADR-011, third amendment), measured the same way on image `9c100951f59b` with the recognition
batch of 1 on a host 54 to 92 percent busy, the dense Polish page sets the page allowance:

| Page | Mode | Peak | Time |
|---|---|---|---|
| Dense English A4 prose at 300 dpi, 50 lines, 4162 characters | `high` | 1132 MiB | 22.1 s |
| The same page, straightened | `high` | 1958 MiB | 24.9 s |
| Dense Polish A4 prose at 300 dpi, 48 lines, 4000 characters | `high` | 1070 MiB | 25.1 s |
| The dense English page | `normal` | 827 MiB | 22.7 s |
| 4200 x 4200 px, 50 lines | `high` | 1213 MiB | 15.8 s |
| 3162 x 4200 px flat phone photo, straightened | `high` | 2636 MiB | 19.5 s |

On the same image the 778 x 932 px scan fixture `argent-saga-chronicles-page1.png` took 15.6 s at 807 MiB. No page
peaked above a figure the banner already prices.

Times are the fastest of the three runs. A loaded engine holds about 333 MiB, of which about 124 MiB is the Python and
Paddle runtime, so a further engine idling in the cache costs about 209 MiB. The API process at rest holds 259 MiB.
A direct run of the whole service on the 4200 x 4200 English page peaked at 1367 MiB for the container. Each page of
a document adds about 11.5 MiB of retained result on top, once, and that one term is carried forward from the older
fit rather than re-measured.

The earlier statement that one A4 page costs about 440 MB was wrong. The probe that produced it sampled memory at
intervals and missed the peak, so every figure it gave for the small pair (394, 441 and 501 MiB) is superseded by the
table above. `ru` and `korean` are switched off: the `PP-OCRv5_server_det` they loaded peaked at 9297 MiB on an A4 page
and 12754 MiB on a 4200 x 4200 page in `high` mode, and 5958 MiB in `normal` mode, the worst of them above the 12 GiB
limit the container then had. See
[ADR-011](docs/architecture/decisions/ADR-011-explicit-preprocessing-and-straighten.md).

The earlier fitted model, `peak_MiB ~= 635 + 5302 * megapixels + 11.5 * pages`, fitted on `PP-OCRv5_server_det`
under PaddleOCR 3.6.0, runs 22 to 41 percent above the container measurement of that detector and eleven to fifteen
times above the small pair, so it prices only a pair or an input nobody measured, as an upper bound. The startup banner prices every engine a
supported language can load in both modes from these measurements, using a measurement of a mode's exact worst page
when one exists, and prices a straightened call as that plus the largest straighten overhead measured on one photo,
2771 - 1148 = 1623 MiB. It compares the API process plus `OCR_WORKER_COUNT` straightened calls on the worst engine,
plus the idle engines `ENGINE_CACHE_MAX_SIZE` lets sit beside it, against the cgroup limit. At the shipped defaults
that is 259 + 1236 + 1623 = 3118 MiB, under the 4 GiB container limit. See "Memory model and the single worker" in
[07-deployment-view.md](docs/architecture/arc42/07-deployment-view.md). The banner also reads this container's own cgroup memory limit (`src/config/memory_limits.py`) and
logs a `WARNING`, never a refusal, when that service peak meets or exceeds it. See
"Warn, don't refuse" in [07-deployment-view.md](docs/architecture/arc42/07-deployment-view.md).

## Environment Variables

- `API_PORT` - service port (default `7022`).
- `API_HOST` - bind address (default `0.0.0.0`).
- `LOG_LEVEL` - `DEBUG | INFO | WARNING | ERROR | CRITICAL` (default `INFO`).
- `LOG_FORMAT` - `json` for production log sinks, `color` for a local terminal (default `json`).
- `SUPPORTED_LANGUAGES` - the allowlist both surfaces enforce at submission with `UNSUPPORTED_LANGUAGE`, and `OcrService._get_engine` again before any model name is resolved (default `en,pl,de,fr,es,it,pt,nl,ch,japan`). `ru` and `korean` are switched off until the small detector is measured with their recognisers.
- `RATE_LIMIT_DEFAULT` - slowapi's default limit, applied to every operation but submission (default `60/minute`).
- `RATE_LIMIT_OCR` - the stricter limit on `POST /v1/ocr/jobs` and `ocr_submit` (default `20/minute`).
- `OTEL_ENABLED` - when true, FastAPI and aiohttp auto-instrumentation plus the manual spans are wired up (default `false`).
- `OTEL_EXPORTER_OTLP_ENDPOINT` - gRPC OTLP collector address (default `http://otel-collector:4317`).
- `DEFAULT_LANGUAGE`: default OCR language, which must match `^[a-z]{2,6}$` (default `en`).
- `MAX_FILE_SIZE_MB` - max source size, enforced on both REST upload and MCP download (default `50`).
- `ENGINE_CACHE_MAX_SIZE` - max number of engines kept resident; LRU eviction beyond this (default `2`). It counts engines, not languages: the cache is keyed by the model pair a language resolves to, so every supported language shares one entry. The second slot stays empty until a language is opted back in with a pair of its own, and then keeps it from evicting the pair almost every request uses. An empty slot costs nothing, and the banner prices only engines a supported language can reach. See [ADR-007](docs/architecture/decisions/ADR-007-explicit-ocr-model-selection.md).
- `OCR_TEXT_DETECTION_MODEL` - detection model for every language the default pair covers (default `PP-OCRv6_small_det`).
- `OCR_TEXT_RECOGNITION_MODEL` - recognition model for the same languages (default `PP-OCRv6_small_rec`). Together with the line above this is the whole model choice, named rather than resolved from the language, and switching family member (`PP-OCRv6_medium_det` / `PP-OCRv6_medium_rec`) is these two variables and a rebuild. A language outside the family would name its own pair in `LANGUAGE_MODEL_OVERRIDES` in `src/config/config.py`, which is empty while `ru` and `korean` are switched off. See [ADR-007](docs/architecture/decisions/ADR-007-explicit-ocr-model-selection.md).
- `MCP_FILE_URI_ROOT` - when set, enables `file://` URI scheme jailed to this absolute path. Unset by default ⇒ `file://` rejected.
- `MCP_ALLOWED_HOSTS` - comma-separated hostnames that bypass the SSRF private-IP check. `host.docker.internal` reaches the object store on host ports 9070/9071 from inside the container. Default empty ⇒ strict block.
- `MCP_DOWNLOAD_TIMEOUT_SECONDS` - total timeout for MCP HTTP fetch (default `30`).
- `OCR_WORKER_COUNT` - number of inference worker processes and admission-gate permits, both read from this one setting so they cannot disagree. A memory constraint, not a throughput knob (default `1`).
- `OCR_PAGE_ALLOWANCE_HEADROOM`: the service's only configured time input. A page is allowed this multiple of the worst page measured on the engine that reads it (`MEASURED_WORST_PAGE_SECONDS` in `src/config/config.py`), the worker checks the resulting budget between pages, and every other duration the service enforces derives from it (default `4.5`, the headroom the allowance was first derived with).
- `OCR_DISPATCH_MARGIN_SECONDS` - headroom the worker's own budget subtracts so it gives up slightly before the parent does (default `5`).
- `OCR_QUALITY_NORMAL`: the `normal` mode's pair, written `<dpi>:<detector bound>` (default `150:1024`). Refused at startup if malformed or beyond the 3.3x ratio.
- `OCR_QUALITY_HIGH`: the `high` mode's pair, same format and guard (default `300:1536`).
- `OCR_MAX_SOURCE_PIXELS`: the one pixel refusal left: a raster image frame declaring more pixels than this is refused with `FILE_TOO_LARGE` from its header, before decode. Pillow's process-wide `Image.MAX_IMAGE_PIXELS` is set from it and from nothing else, and PDFs are never refused on pixels (default `89478485`, Pillow's own decompression-bomb threshold).
- `OCR_POOL_REBUILD_MAX_CONSECUTIVE` - consecutive failed pool rebuilds before the service stops trying and stays not-ready; resets on the first request that completes (default `3`).
- `OCR_JOB_MAX_PAGES` - page ceiling per document, and the only page ceiling left. Set by how long one document may hold the single worker and everything behind it, with memory as a cross-check rather than the derivation (default `100`, about 42 min at the worst measured page).
- `OCR_JOBS_DIR` - one JSON record per job, the submitted bytes until it reaches a terminal state, and a small progress file while it runs. Mount a volume here if records must survive a container recreate (default an `ascend-ocr-jobs` directory under the system temp path).
- `OCR_JOB_RETENTION_SECONDS` - how long a finished record and its stored result live, from the moment the work finished (default `3600`).
- `OCR_JOB_MAX_RETAINED` - finished records retained before the oldest is evicted. A backstop against a defect rather than an eviction policy a caller meets (default `1000`).
- `OCR_JOB_QUEUE_MAX_PAGES` - total pages that may be waiting, which is what turns the wait into a number: each page ahead multiplied by its own engine's allowance. Cannot be below `OCR_JOB_MAX_PAGES` (default `200`).
- `OCR_JOB_QUEUE_MAX_DOCUMENTS` - documents that may be waiting, which bounds the disk their bytes hold and the length of the list operation (default `8`).
- `OCR_RESULT_S3_ENDPOINT` - the S3-compatible address results are written to; must be an absolute http or https URL (default `http://localhost:9070`, the same Floci instance the agent uses).
- `OCR_RESULT_S3_PUBLIC_ENDPOINT` - the address baked into a presigned URL, which is not always the one this service reaches (defaults to the endpoint above).
- `OCR_RESULT_S3_BUCKET` - its own bucket, never the agent's `knowledge-base` (default `ocr-results`).
- `OCR_RESULT_S3_ACCESS_KEY` / `OCR_RESULT_S3_SECRET_KEY` - static credentials, the way the agent supplies them (default empty, so an unconfigured store is visible in the startup banner).

`OCR_REQUEST_TIMEOUT` and the derived `OCR_MAX_PAGES` are **deleted**. Both bounded a held connection, and no
connection is held. `OCR_PAGE_TIMEOUT_SECONDS`, `OCR_MAX_INFERENCE_PIXELS`, `OCR_DETECTOR_MAX_SIDE` and
`OCR_SCRATCH_DIR` are **deleted** by ADR-010: one allowance could not cover engines 8.5 times apart, the inference
ceiling refused ordinary scans, the detector bound moved into the quality pairs, and nothing writes a scratch file any
more. A leftover value of any of them in the environment is ignored rather than refused.

Every duration is derived on `Settings`, never set, so none can drift out of agreement with its inputs:

- `page_allowance_seconds(pair) = OCR_PAGE_ALLOWANCE_HEADROOM x` the pair's detector's worst measured page. A detector
  nobody measured gets the slowest measured figure.
- `reclamation_grace_seconds(pair) = page_allowance_seconds(pair) + OCR_DISPATCH_MARGIN_SECONDS`.
- `OCR_WORST_PAGE_ALLOWANCE_SECONDS`, the allowance of the slowest engine any supported language can load: 112.95 s at
  the defaults, the small detector's, since every supported language reads with it.
- `OCR_JOB_READING_CEILING_SECONDS = OCR_JOB_MAX_PAGES x OCR_WORST_PAGE_ALLOWANCE_SECONDS` (11,295 s at the defaults).
- `OCR_JOB_MAX_LIFETIME_SECONDS = (OCR_JOB_QUEUE_MAX_PAGES + OCR_JOB_MAX_PAGES) x OCR_WORST_PAGE_ALLOWANCE_SECONDS`
  (33,885 s at the defaults).
- The poll hint is a tenth of the allowed time still ahead of a document, each page at its own engine's allowance,
  held between 1 and 30 seconds, and `Retry-After` on `QUEUE_FULL` is the same rule applied to everything in flight.

Tune them by tuning their inputs.

**Where the job path lives**: `src/service/job_service.py` is the one service layer both surfaces call,
`src/service/job_runner.py` is the queue and its single consumer, `src/service/job_store.py` is the record on disk,
and `src/service/result_store.py` is the bucket. The composition root that wires the four singletons together is at
the bottom of `job_service.py`.

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
