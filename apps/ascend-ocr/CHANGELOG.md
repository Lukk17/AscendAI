# Changelog: ascend-ocr

All notable changes to this project are documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to
[Semantic Versioning](https://semver.org/). Newest entry on top; the topmost `## [x.y.z]`
version is the current one. The release workflow reads it for the image tag and to guard
against re-publishing an already-released version, so keep it at the top and bump it
before every release. The `version` in `pyproject.toml` is a cosmetic label the release
workflow does not read; if the two ever disagree, this file wins for release purposes.

## [0.3.0] - 2026-10-01

### Changed
- Breaking for REST callers: every request is a job. POST /v1/ocr/jobs takes the file plus the optional
  lang, quality and straighten fields and answers 202 with a job identifier, never with the text.
  GET /v1/ocr/jobs/{job_id} reads the state, GET /v1/ocr/jobs lists the work that is waiting or running,
  and DELETE /v1/ocr/jobs/{job_id} cancels work or removes a finished result. See ADR-008.
- Breaking for REST callers: POST /v1/ocr is removed and now answers 404 like any unknown path. Submit to
  POST /v1/ocr/jobs instead. ADR-003 has an amendment that says why the job operations stay under /v1
  instead of moving to a /v2.
- Breaking for MCP callers: the ocr_process tool is removed, with no stub left behind. ocr_submit takes
  {file_uri, lang, quality, straighten}, and ocr_job_status, ocr_list_jobs and ocr_cancel_job complete the
  set.
- Breaking for operators: a finished result is one Markdown file in object storage, in a bucket of its own
  (OCR_RESULT_S3_BUCKET, default ocr-results, never the agent's knowledge-base). The status answer names the
  bucket and the key and carries a presigned link. The service needs OCR_RESULT_S3_ENDPOINT,
  OCR_RESULT_S3_ACCESS_KEY and OCR_RESULT_S3_SECRET_KEY to finish any job, and
  OCR_RESULT_S3_PUBLIC_ENDPOINT when callers reach the store at a different address. See ADR-009.
- Breaking for monitoring: /ready reports jobs_queued and jobs_running in place of queue_depth. The metrics
  ascendocr_ocr_queue_depth and ascendocr_ocr_queue_wait_seconds are gone. In their place are
  ascendocr_job_queue_documents, ascendocr_job_queue_pages and ascendocr_job_queue_wait_seconds, plus the
  new ascendocr_jobs_total, ascendocr_job_duration_seconds, ascendocr_jobs_retained,
  ascendocr_result_upload_attempts_total and ascendocr_result_upload_failures_total.
- Breaking for operators: OCR_REQUEST_TIMEOUT, the derived OCR_MAX_PAGES, OCR_PAGE_TIMEOUT_SECONDS,
  OCR_MAX_INFERENCE_PIXELS, OCR_DETECTOR_MAX_SIDE and OCR_SCRATCH_DIR are deleted, and a value left in the
  environment is ignored. The page ceiling per document is OCR_JOB_MAX_PAGES (default 100), and every time
  limit is derived from OCR_PAGE_ALLOWANCE_HEADROOM (default 4.5) times the worst measured page.
- Breaking for callers of two languages: ru and korean are switched off, and a request for either is
  refused with 400 UNSUPPORTED_LANGUAGE. The PP-OCRv5_server_det detector they loaded peaked at 9297 MiB
  on an A4 page and 12754 MiB on a 4200 x 4200 page. SUPPORTED_LANGUAGES now defaults to en, pl, de, fr,
  es, it, pt, nl, ch and japan.
- Every supported language now reads with one named model pair, PP-OCRv6_small_det and
  PP-OCRv6_small_rec, set by OCR_TEXT_DETECTION_MODEL and OCR_TEXT_RECOGNITION_MODEL, instead of the model
  PaddleOCR picked from the language. PaddleOCR goes from 3.6.0 to 3.7.0, and the image build downloads
  every model a supported language can reach, so no model is downloaded at request time. See ADR-007.
- Page orientation and text line orientation now run on every request. Text line orientation classifies
  one line per call, because the library's batch of 6 turned upright lines upside down on a mixed page.
  Unwarping is off unless the request asks for straighten. See ADR-011.
- One queue in strict submission order feeds one worker. The queue is bounded at OCR_JOB_QUEUE_MAX_PAGES
  (200) and OCR_JOB_QUEUE_MAX_DOCUMENTS (8), and a submission past either bound is refused with 503
  QUEUE_FULL and a Retry-After header. A page is allowed 4.5 times the worst measured page, 112.95 seconds,
  and the worker checks the budget between pages.
- Every log line goes through the root handler under LOG_LEVEL, uvicorn's and FastMCP's lines included.
  FASTMCP_LOG_LEVEL and uvicorn's --log-level and --no-access-log have no effect any more. An expected
  refusal is logged as one WARNING line naming its code, with no traceback. See ADR-002.
- The compose service drops its memory limit from 12G to 4G. The startup banner prices the worst
  straightened call at the defaults at 3118 MiB and logs a WARNING, never a refusal, when that meets the
  container's own limit.
- New runtime dependencies boto3 1.42.6 and numpy 2.3.5, and new development dependencies
  boto3-stubs[s3] 1.42.6 and pact-python-ffi 0.5.4.1, all pinned.
- OpenTelemetry goes from 1.42.1 to 1.44.0 and its FastAPI and aiohttp instrumentation from 0.63b1 to
  0.65b0, and the new development dependency httpx2 2.13.1 serves the test client, matching
  ascend-audio-scribe and AscendMemory.
- Every warning now fails the test run (pytest filterwarnings is error). The one warning ignored, in the
  contract test only, is the listening socket pact-python's state callback server never closes.
- mcp is now a direct dependency at 1.30.0 or newer, because older releases leak a stream on every request.

### Added
- quality picks one of two locked render and detector pairs: normal is 150 dpi with a 1024 detector bound,
  and high, the default, is 300 dpi with 1536. OCR_QUALITY_NORMAL and OCR_QUALITY_HIGH change them, and a
  pair beyond a 3.3 times downscale is refused at startup. The service renders every PDF page with pypdfium2
  and decodes every image with Pillow itself, so PaddleOCR's fixed 144 dpi rasterizer is no longer used.
  See ADR-010.
- straighten (default false) turns on page unwarping for that request only. It is meant for phone photos
  of bent, curled or crumpled paper, works best with quality=high, and hurts clean scans and PDFs.
- UNSUPPORTED_LANGUAGE (400): a lang outside SUPPORTED_LANGUAGES is refused at submission on both
  surfaces, before anything is fetched, stored or queued, and the detail lists the supported languages.
- Every log line carries correlation_id, the x-request-id of the request being served. Every MCP request is
  logged under the id of the HTTP request that carried it, and carries mcp_session_id, the first 16 hex
  characters of the SHA-256 digest of the session id. The raw session id is replaced by that digest in the
  MCP library's own log lines and in exported trace span attributes.
- The Pact provider verification (tests/contract/test_ascend_agent_pact.py, marker contract) replays
  contracts/pacts/ascend-agent-ascend-ocr.json, which the ascend-agent consumer test writes. It replaces
  the skipped stub test_ascend_ai_agent_pact_stub.py.
- Job records live in OCR_JOBS_DIR. A job the previous process left waiting or running is marked failed
  with SERVICE_RESTARTED and retryable true, and is never resumed. Finished records are kept for
  OCR_JOB_RETENTION_SECONDS (3600), up to OCR_JOB_MAX_RETAINED (1000).
- A multi-frame TIFF counts as one page per frame.
- End-to-end specs 13 to 20 cover a 25-page document, the job list, cancelling a running job, a full
  queue, a rotated photo, a straightened and a default crumpled photo, and an unsupported language over MCP,
  with their fixtures and templates.

### Fixed
- An x-request-id header holding a byte outside ASCII made every endpoint answer 500. The header is now
  read as Latin-1 and kept only when it is 1 to 128 characters of letters, digits, ".", "_", ":" and "-".
  Any other value is replaced by a fresh id, which is logged and echoed.
- The PaddlePaddle engine ran its own 10 compute threads under a 4 CPU quota, because
  PADDLE_PDX_CPU_NUM_THREADS never reached the inference graph. Each engine now gets cpu_threads equal to
  the container's CPU limit.
- OCR_MAX_INFERENCE_PIXELS refused ordinary scans. An oversized page is now shrunk to the mode's largest
  page and read. The only pixel refusal left is OCR_MAX_SOURCE_PIXELS, at Pillow's decompression-bomb
  threshold.
- The OpenAPI document reported FastAPI's default version. It now reports the package version, the same
  value /health reports.
- The Windows wheel of pact-python-ffi 0.5.4.0 failed to load its native library. The dependency is
  pinned to 0.5.4.1.
- mypy now checks the tests as well as the source, and continuous integration runs mypy src tests.
- The documented memory cost of one A4 page, about 440 MB, came from a probe that sampled between peaks.
  The documents now carry the measured container peaks, 1016 MiB for an A4 page in high mode.
- Dashes in comments, log and banner text and documentation are plain hyphens or commas now.
- Uvicorn's access line for an MCP request carrying an mcp-session-id header logged mcp_session_id as null,
  because the digest was bound only in the MCP SDK's session task. It now carries the session digest, and so
  does the access line of the initialize request that opens a session.
- A REST request carrying an mcp-session-id header logged a digest of that caller-chosen value on every line, and an unhandled exception logged its ERROR lines and its 500 access line with correlation_id "-" and answered without x-request-id. The digest is now bound only on the MCP endpoint, and the correlation middleware is the outermost layer.
- ascendocr_ocr_errors_total counted an error on /health, /ready or /metrics as surface="mcp", because every path outside /v1 was taken for MCP. Only a request to the MCP endpoint path is counted as mcp now, and every other path as rest.
- The log filters raised TypeError on a record whose exc_info was not an exception tuple, such as the OpenTelemetry exporter's error logged with exc_info=False, so the line was lost and the exception reached the exporter. Both filters now read exc_info only when it holds an exception, the session redaction also covers a traceback already in exc_text, and a filter that fails keeps the line and reports a LogFilterFailureWarning instead of raising.

## [0.2.1]

### Changed
- The compose service sets OCR_PAGE_TIMEOUT_SECONDS to 150 beside the existing OCR_REQUEST_TIMEOUT
  of 300. Without it a one-page document kept the 120 second default budget and timed out on runs
  measured at up to 139 seconds.

### Fixed
- End-to-end spec 10 piped through jq without listing it as a prerequisite. It is listed now, with
  a version check.
- The MCP specs and templates described the session id as a UUID. The value is a 32 character
  hexadecimal id without hyphens, and the wording now says so.
- The Bruno ready request accepted an empty version string, and the Polish OCR request accepted
  any language. They now assert a non-empty version and a language equal to pl.
- The PowerShell form of the MCP specs' JSON-body curl.exe blocks failed on pwsh 7.6.5 with a
  nested brace error and HTTP 400. Those blocks pass the body single-quoted now.
- The deployment view claimed compose leaves MCP_ALLOWED_HOSTS unset. It names the three hosts
  compose sets.
- The version in pyproject.toml, AGENTS.md, the service banner and the constraints document
  lagged this changelog at 0.1.0. All four say 0.2.1, and the service banner now reads its
  version from the installed package metadata at import time instead of a hardcoded literal,
  so pyproject.toml is the only place the version lives.
- The engine-bound end-to-end specs 2, 3, 4 and 6 were allowed to interleave with other runners.
  The engine is single-threaded and a loaded host took the same fixture from 59.2 to 160.9
  seconds on 2026-09-10, past the raised per-page budget, so each of the four now runs alone with
  no runner of any suite active. The README table and each spec's Concurrency section say so.
- End-to-end spec 2 described its fixture as a single 120 point line while the response carries
  about 30 wrapped body lines. The description now matches the page-1 screenshot the fixture is.
- The unsupported-MIME Bruno request sent the text fixture with its real content type, so it
  never exercised the header lie spec 12 describes. The file part now declares image/png.

## [0.2.0]

### Fixed
- The upload endpoint declared its language parameter without a form marker, so the web framework
  treated it as a query parameter and silently discarded the multipart field every documented
  client sends. Every request ran the English model whatever language it asked for. The parameter
  now reads the form body, which is what this module's contract always specified. The MCP tool
  surface takes its arguments from the request body and was never affected.

### Changed
- ENGINE_CACHE_MAX_SIZE now defaults to 2 rather than 8, matching the two language models the
  image actually ships. That takes roughly a gigabyte off the worst-case memory estimate for
  capacity nothing could use. A workload alternating a third language now pays an engine load on
  each switch instead of keeping that engine resident.

## [0.1.0]

### Added
- Changelog introduced for this module. No prior per-version history was tracked before
  this file, so consult git history for changes before this entry. This module wraps the
  PaddleOCR library behind a FastAPI REST API and a FastMCP server for multi-language
  text extraction from images and PDFs.
