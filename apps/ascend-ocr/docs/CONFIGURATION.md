# ascend-ocr Configuration

*Every runtime setting binds from the environment (or a local `.env` file) into the typed `Settings` class at
[../src/config/config.py](../src/config/config.py). Defaults are safe for a single-instance local run.*

---

### Service

| Variable                          | Default                                       | Purpose                                                                                  |
| :-------------------------------- | :-------------------------------------------- | :--------------------------------------------------------------------------------------- |
| API_HOST                          | `0.0.0.0`                                     | Uvicorn bind address.                                                                    |
| API_PORT                          | `7022`                                        | Uvicorn port.                                                                            |
| LOG_LEVEL                         | `INFO`                                        | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`.                                         |
| LOG_FORMAT                        | `json`                                        | `json` for production log sinks, `color` for local terminal output.                      |

---

### Request budgets, memory bounds, and worker recovery

See [ADR-010](architecture/decisions/ADR-010-quality-modes-and-service-side-rendering.md) for the quality modes,
the source pixel ceiling and the per-engine page allowance, and
[ADR-006](architecture/decisions/ADR-006-detector-input-bound.md) for how the detector bounds were chosen.
Preprocessing has no environment variable: page orientation and text line orientation always run, unwarping runs only
for a request that sends `straighten=true`, and all of it is fixed in code as
[ADR-011](architecture/decisions/ADR-011-explicit-preprocessing-and-straighten.md) records.

| Variable                          | Default                                       | Purpose                                                                                  |
| :-------------------------------- | :-------------------------------------------- | :--------------------------------------------------------------------------------------- |
| OCR_WORKER_COUNT                  | `1`                                           | Inference worker processes, and admission-gate permits - both read from this one setting. One document is read at a time, and every promise the queue makes about how long a submission waits is computed against that, so raising it changes the promise as well as the throughput. It also multiplies the service's memory peak: `service_peak_MiB ~= api_process_MiB + per_call_peak_MiB * OCR_WORKER_COUNT`. |
| OCR_PAGE_ALLOWANCE_HEADROOM       | `4.5`                                         | The service's **only configured time input**. A page is allowed this multiple of the worst page measured on the detection model that reads it, and every duration below derives from that allowance. The measured worst page on `PP-OCRv6_small_det`, the detector every supported language reads with, is 25.1 s, a dense Polish A4 prose page (48 lines, 4000 characters) in `high` mode, measured in a Linux container with 4 CPUs with the engine's threads capped to those CPUs, so the allowance is 112.95 s. The earlier 50.4 s and 226.8 s were measured while PaddleOCR ran its own 10 threads throttled under the 4-CPU quota. `PP-OCRv5_server_det`, which no supported language loads, was measured at 96.0 s on a 4200 x 4200 page before that thread cap, and a detection model nobody measured gets that slowest figure. |
| OCR_DISPATCH_MARGIN_SECONDS       | `5.0`                                         | Headroom the worker's own budget subtracts, so it gives up slightly before the parent.   |
| OCR_QUALITY_NORMAL                | `150:1024`                                    | The `normal` quality mode, as one pair `<dpi>:<detector bound>`: pages rendered at 150 dpi, detection bounded to a long side of 1024, and nothing read larger than 2100 px on its long side (US Legal at 150 dpi). |
| OCR_QUALITY_HIGH                  | `300:1536`                                    | The `high` quality mode, the default a caller gets: 300 dpi, a detector bound of 1536, and nothing larger than 4200 px. Either mode's setting is refused at startup if it is malformed or if its largest page would be downscaled more than 3.3x for detection, the largest ratio measured to read every line. |
| OCR_MAX_SOURCE_PIXELS             | `89478485`                                    | The one pixel refusal left. A raster image frame declaring more pixels than this is refused with `FILE_TOO_LARGE` from its header, before decode, naming the count and the ceiling. Pillow's process-wide `Image.MAX_IMAGE_PIXELS` is set from it and from nothing else. The default is Pillow's own decompression-bomb threshold. A PDF page is never refused on pixels, and an oversized page or image is shrunk to its mode's largest size and read. |
| OCR_POOL_REBUILD_MAX_CONSECUTIVE  | `3`                                           | Consecutive failed pool rebuilds before the service stops trying and stays not-ready. Resets on the first request that completes. |

A worker reading on an engine may run that engine's page allowance plus `OCR_DISPATCH_MARGIN_SECONDS` past its own
expired budget before it is replaced. That grace is derived (`Settings.reclamation_grace_seconds`), not a setting.

`OCR_REQUEST_TIMEOUT` and the derived `OCR_MAX_PAGES` are **gone**. Both bounded a held connection, and no connection
is held: every request is a job (see [ADR-008](architecture/decisions/ADR-008-every-request-is-a-job.md)). The page
ceiling is now `OCR_JOB_MAX_PAGES` below, the reading ceiling is derived from it, and a leftover `OCR_REQUEST_TIMEOUT`
in the environment is ignored rather than refused.

`OCR_PAGE_TIMEOUT_SECONDS`, `OCR_MAX_INFERENCE_PIXELS`, `OCR_DETECTOR_MAX_SIDE` and `OCR_SCRATCH_DIR` are **gone** as
well (see ADR-010). A deployment that tuned the allowance sets `OCR_PAGE_ALLOWANCE_HEADROOM`, one that tuned the
detector bound sets it inside `OCR_QUALITY_HIGH`, and nothing writes a scratch file any more. A leftover value of any
of them is ignored rather than refused.

---

### The job queue and its bounds

Every document is submitted, queued and collected. See
[ADR-008](architecture/decisions/ADR-008-every-request-is-a-job.md) for why, and the job lifecycle section of
[../README.md](../README.md) for the path a caller takes.

| Variable                          | Default                                       | Purpose                                                                                  |
| :-------------------------------- | :-------------------------------------------- | :--------------------------------------------------------------------------------------- |
| OCR_JOB_MAX_PAGES                 | `100`                                         | Page ceiling per document, refused with `FILE_TOO_LARGE` before any page is read. What sets it is how long one document may hold the single worker and everything queued behind it: 100 pages is about 42 min at the worst measured page. Memory is the cross-check rather than the derivation, about 1.2 GB of retained result at the ceiling using a per-page term carried forward from the previous detector. Raising it is a decision about the queue, not a throughput setting. |
| OCR_JOB_QUEUE_MAX_PAGES           | `200`                                         | Total pages that may be waiting. This is what turns "come back later" into a promise with a number attached: the longest a newly accepted submission waits is each page ahead of it multiplied by the allowance of the engine that reads it. Cannot be configured below `OCR_JOB_MAX_PAGES`, or a single maximal document could never be queued, and the service refuses to start naming both settings. |
| OCR_JOB_QUEUE_MAX_DOCUMENTS       | `8`                                           | Documents that may be waiting. It bounds disk rather than time, because every waiting submission's bytes sit in the jobs directory until it runs: a chosen 400 MB budget divided by `MAX_FILE_SIZE_MB`. It also bounds the list operation, which can never return more than this many waiting entries plus the one running document. |
| OCR_JOBS_DIR                      | `<system temp>/ascend-ocr-jobs`               | One JSON record per job, the submitted bytes until the job reaches a terminal state, and a small progress file while it runs. Mount a volume here if job records must survive a container recreate. |
| OCR_JOB_RETENTION_SECONDS         | `3600.0`                                      | How long a finished record and its stored result live, measured from the moment the work finished, so a caller whose polling died has a working session to restart it and collect. It is also how long a document's own extracted text sits in the result bucket. |
| OCR_JOB_MAX_RETAINED              | `1000`                                        | Finished records retained before the oldest is evicted. A backstop against a defect rather than an eviction policy a caller meets: the single worker cannot produce this many results inside one retention window at the measured per-page cost. |

Three more derived properties, none settable from the environment:

- `OCR_WORST_PAGE_ALLOWANCE_SECONDS` is the allowance of the slowest engine any supported language can load, 112.95 s
  at the defaults, the small detector's, since every supported language reads with it.
- `OCR_JOB_READING_CEILING_SECONDS = OCR_JOB_MAX_PAGES x OCR_WORST_PAGE_ALLOWANCE_SECONDS` (11,295 s at the defaults)
  is the longest one document may be read for.
- `OCR_JOB_MAX_LIFETIME_SECONDS = (OCR_JOB_QUEUE_MAX_PAGES + OCR_JOB_MAX_PAGES) x OCR_WORST_PAGE_ALLOWANCE_SECONDS`
  (33,885 s at the defaults) is the longest any document could legitimately
  wait and then be read for. A record still
  waiting or running past it is wedged by a defect, and is failed with the `LIFETIME_EXCEEDED` reason rather than
  polled forever.

---

### The result store

A finished document's text is written to S3-compatible object storage as one Markdown file, `{job_id}.md`, and the
status answer carries its address rather than its content. See
[ADR-009](architecture/decisions/ADR-009-results-in-object-storage.md). Each setting mirrors the property the
ascend-ai-agent already uses for the same store.

| Variable                          | Default                                       | Purpose                                                                                  |
| :-------------------------------- | :-------------------------------------------- | :--------------------------------------------------------------------------------------- |
| OCR_RESULT_S3_ENDPOINT            | `http://localhost:9070`                       | The address this service writes to. Must be an absolute `http` or `https` URL. The docker-compose service sets `http://host.docker.internal:9070`, which is the address its SSRF allowlist already names. |
| OCR_RESULT_S3_PUBLIC_ENDPOINT     | the endpoint above                            | The address baked into a presigned URL, which is not always the one this service reaches. The docker-compose service sets `http://localhost:9070`. |
| OCR_RESULT_S3_BUCKET              | `ocr-results`                                 | Its own bucket, never the agent's `knowledge-base`, whose contents the agent's manual ingestion lists and indexes as source documents. Headed at startup and created when missing. Must allow neither anonymous listing nor anonymous reads, because the job identifier is the only credential. |
| OCR_RESULT_S3_ACCESS_KEY          | empty                                         | Static credentials, the way the agent supplies them. Empty by default so a deployment that has not configured a result store finds out at startup, in the banner, rather than silently writing nowhere. |
| OCR_RESULT_S3_SECRET_KEY          | empty                                         | As above. Never printed in the startup banner or in any log line.                        |

---

### OCR engine

| Variable                          | Default                                       | Purpose                                                                                  |
| :-------------------------------- | :-------------------------------------------- | :--------------------------------------------------------------------------------------- |
| DEFAULT_LANGUAGE                  | `en`                                          | Engine warmed during lifespan. Pattern `[a-z]{2,6}`.                                     |
| SUPPORTED_LANGUAGES               | `en,pl,de,fr,es,it,pt,nl,ch,japan`            | Allowlist enforced at submission on both surfaces, where anything else is refused with 400 `UNSUPPORTED_LANGUAGE` and no job, and again by `OcrService._get_engine`. `ru` and `korean` are switched off until the small detector is measured with their recognisers, see [ADR-011](architecture/decisions/ADR-011-explicit-preprocessing-and-straighten.md). |
| OCR_TEXT_DETECTION_MODEL          | `PP-OCRv6_small_det`                          | Detection model for every language the default pair covers. Named rather than resolved from the language - see [ADR-007](architecture/decisions/ADR-007-explicit-ocr-model-selection.md). |
| OCR_TEXT_RECOGNITION_MODEL        | `PP-OCRv6_small_rec`                          | Recognition model for the same languages. With the row above, switching to `PP-OCRv6_medium_det` / `PP-OCRv6_medium_rec` is a configuration change and a rebuild, not a code change. A language outside the family would name its own pair in `LANGUAGE_MODEL_OVERRIDES` in `src/config/config.py`, which is empty while `ru` and `korean` are switched off. |
| ENGINE_CACHE_MAX_SIZE             | `2`                                           | LRU eviction kicks in past this engine count. It counts engines, not languages: the cache is keyed by the model pair, so every supported language shares one entry. The second slot stays empty until a language is opted back in with a pair of its own, and then keeps it from evicting the default pair. The startup banner prices only the engines a supported language can reach, about 209 MiB for each idle one (see 07-deployment-view.md). |
| MAX_FILE_SIZE_MB                  | `50`                                          | Caps REST upload and MCP download.                                                       |

---

### MCP transport

| Variable                          | Default                                       | Purpose                                                                                  |
| :-------------------------------- | :-------------------------------------------- | :--------------------------------------------------------------------------------------- |
| MCP_FILE_URI_ROOT                 | unset                                         | When set, `file://` is enabled and jailed to this directory via `realpath`. See [ADR-001](architecture/decisions/ADR-001-mcp-file-transport-uri-only.md). |
| MCP_ALLOWED_HOSTS                 | empty                                         | Hostnames that bypass the SSRF private-IP guard. The docker-compose default is `host.docker.internal,localhost,127.0.0.1`. |
| MCP_DOWNLOAD_TIMEOUT_SECONDS      | `30.0`                                        | Total aiohttp timeout for the URI fetch.                                                 |

---

### Rate limiting

| Variable                          | Default                                       | Purpose                                                                                  |
| :-------------------------------- | :-------------------------------------------- | :--------------------------------------------------------------------------------------- |
| RATE_LIMIT_DEFAULT                | `60/minute`                                   | slowapi default applied to every endpoint.                                               |
| RATE_LIMIT_OCR                    | `20/minute`                                   | Stricter cap on `POST /v1/ocr/jobs`. Reading a state, listing work in flight and deleting a job are throttled at the default limit instead, because they are file reads rather than inference. |

---

### OpenTelemetry

| Variable                          | Default                                       | Purpose                                                                                  |
| :-------------------------------- | :-------------------------------------------- | :--------------------------------------------------------------------------------------- |
| OTEL_ENABLED                      | `false`                                       | When `true`, FastAPI + aiohttp auto-instrumentation plus three manual spans are wired up. |
| OTEL_EXPORTER_OTLP_ENDPOINT       | `http://otel-collector:4317`                  | gRPC OTLP collector address.                                                             |

---

### Local override file

The `Settings` class reads a `.env` file in the project root if present. Example for a local run that enables
`file://` access and points at a non-default upload directory:

```dotenv
LOG_FORMAT=color
LOG_LEVEL=DEBUG
MCP_FILE_URI_ROOT=/tmp/ascend-ocr-uploads
MCP_ALLOWED_HOSTS=host.docker.internal,localhost,127.0.0.1
```

The repo's [.gitignore](../../../.gitignore) excludes `.env`. Commit a sanitised `.env.example` if a profile needs sharing.
