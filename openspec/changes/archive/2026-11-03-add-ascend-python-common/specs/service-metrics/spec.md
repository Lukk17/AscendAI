## MODIFIED Requirements

### Requirement: Domain custom metrics - Python services

ascend-web-hunter, ascend-ocr, ascend-audio-scribe and ascend-memory SHALL emit at least the following custom metrics in addition to framework defaults. The metrics register on the default Prometheus registry that the `/metrics` endpoint of the `ascend-python-common` library serves. The rows of ascend-audio-scribe, ascend-memory and the ascend-web-hunter search results are added by `add-ascend-python-common` on top of its library (moved there from `add-observability` in the dependency fix of 2026-10-05).

| Service | Metric | Type | Required tags |
|---|---|---|---|
| ascend-web-hunter | `strategy_attempts_total` | counter | `strategy`, `outcome`, `domain`, as defined by the main spec `web-search-caching-observability` |
| ascend-web-hunter | `search.results_returned` | histogram | `engine`, `outcome` |
| ascend-ocr | `ascendocr_jobs_total` | counter | `outcome` (the job's terminal state) |
| ascend-ocr | `ascendocr_job_duration_seconds` | histogram | none |
| ascend-ocr | `ascendocr_job_queue_wait_seconds` | histogram | none |
| ascend-ocr | `ascendocr_job_queue_documents` | gauge | none |
| ascend-ocr | `ascendocr_job_queue_pages` | gauge | none |
| ascend-audio-scribe | `transcription.duration_seconds` | histogram | `provider`, `outcome` |
| ascend-audio-scribe | `transcription.audio_duration_seconds` | histogram | `provider` |
| ascend-memory | `memory.operations_total` | counter | `operation`, `outcome` |
| ascend-memory | `memory.search.duration_seconds` | histogram | `embedding_provider` |

Where a main spec under `openspec/specs/` already defines a metric of the same service, that spec is the source of truth and this table only points to it. The ascend-ocr rows follow the job model of `openspec/specs/ocr-job-admission/spec.md`. In the Prometheus exposition every `.` of a metric name is written as `_`.

#### Scenario: ascend-ocr job metric counts a finished job

- **WHEN** an OCR job submitted through `POST /v1/ocr/jobs` reaches a terminal state
- **AND** `GET http://localhost:7022/metrics` is then invoked
- **THEN** `ascendocr_jobs_total{outcome="<terminal state>"}` has increased by 1

#### Scenario: ascend-audio-scribe transcription metric records duration

- **WHEN** any `/api/v1/transcribe/*` request completes successfully
- **THEN** `transcription_duration_seconds_count{provider="<p>",outcome="ok"}` increments by 1

#### Scenario: ascend-memory counts its operations

- **WHEN** a memory insert answers 200
- **THEN** `memory_operations_total{operation="insert",outcome="ok"}` increments by 1
