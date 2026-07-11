## ADDED Requirements

### Requirement: Ingestion runs execute asynchronously as tracked jobs

`POST /api/v1/ingestion/run` SHALL NOT block for the duration of the bucket scan. It SHALL persist a run record with state `QUEUED`, submit the job for execution, and immediately return HTTP 202 with a body containing the run id and a `Location` header pointing at `/api/v1/ingestion/runs/{id}`. Runs SHALL execute serially in submission order and transition `QUEUED` → `RUNNING` → `COMPLETED` (or `FAILED`). Runs left in `QUEUED` or `RUNNING` state when the application starts SHALL be marked `FAILED` with an explicit interrupted-by-restart reason. The existing `prefix` and `embeddingProvider` parameters SHALL be preserved and recorded on the run.

#### Scenario: Run request returns immediately with a run id

- **WHEN** `POST /api/v1/ingestion/run?prefix=markdown/` is invoked
- **THEN** the response status is 202 and the body contains a run id
- **AND** the `Location` header is `/api/v1/ingestion/runs/{id}`
- **AND** the response arrives without waiting for the scan to finish

#### Scenario: Run status transitions to completed

- **WHEN** a run is created and its scan finishes successfully
- **THEN** `GET /api/v1/ingestion/runs/{id}` observed over time shows state `QUEUED` or `RUNNING` first and `COMPLETED` after the scan ends
- **AND** the completed record carries `started_at` and `finished_at` timestamps

#### Scenario: Interrupted run marked failed on restart

- **WHEN** the application restarts while a run record is in state `RUNNING`
- **THEN** after startup `GET /api/v1/ingestion/runs/{id}` shows state `FAILED` with a reason indicating the run was interrupted by a restart

### Requirement: Run status reports counts and per-file failures

`GET /api/v1/ingestion/runs/{id}` SHALL return the run's state, scope (prefix or single-document reference), embedding provider, requested / started / finished timestamps, aggregate `indexed`, `skipped`, and `failed` counts, and a per-file failure list of `{objectKey, reason}` entries. The failure detail list MAY be capped (at 100 entries) but the `failed` count SHALL remain exact. Unknown run ids SHALL return HTTP 404.

#### Scenario: Completed run exposes counts and failures

- **WHEN** a run completes having indexed 2 objects, skipped 1 unchanged object, and failed on 1 object
- **THEN** `GET /api/v1/ingestion/runs/{id}` returns state `COMPLETED` with `indexed` reflecting the ingested chunks, `skipped` = 1, `failed` = 1
- **AND** the failure list contains one entry with the failing object key and a non-empty reason

#### Scenario: Unknown run id

- **WHEN** `GET /api/v1/ingestion/runs/{id}` is invoked with an id that does not exist
- **THEN** the response status is 404

### Requirement: Run history is queryable

The agent SHALL expose `GET /api/v1/ingestion/runs` returning recent runs newest-first, including reindex runs. The endpoint SHALL accept a `limit` query parameter (default 20, maximum 100).

#### Scenario: History lists recent runs newest-first

- **WHEN** three runs have executed and `GET /api/v1/ingestion/runs?limit=2` is invoked
- **THEN** the response contains the 2 most recent runs ordered newest-first
- **AND** each entry carries the run id, state, and counts

### Requirement: Bucket-scan ingestion routes every object through DocumentRouter

Every object an ingestion run ingests SHALL be parsed via `DocumentRouter.routeAndProcess` (extension-based routing to the Markdown parser, Docling, PaddleOCR, Unstructured, or per-page PDF dispatch), identical to the upload and single-document reindex paths. The bucket-scan path SHALL NOT fall back to a default or plain-text parser that bypasses `DocumentRouter`, so a connector-dropped or manually-dropped PDF, Office, image, or e-mail file receives the same parse quality as an uploaded one. This closes the pre-existing gap where `ManualIngestionService`'s scan path ingested objects without routing.

#### Scenario: Scanned PDF is routed, not plain-parsed

- **WHEN** an ingestion run scans a scanned-image PDF dropped into the bucket out-of-band
- **THEN** the object is dispatched through `DocumentRouter` (per-page text-vs-scan split to Docling / PaddleOCR)
- **AND** it is not ingested as raw bytes or plain text

#### Scenario: Office document dropped into the bucket

- **WHEN** an ingestion run scans a `.docx` object with no prior registry row
- **THEN** the object is parsed via Docling through `DocumentRouter`, the same path an upload of that file would take

### Requirement: Bucket-scan deduplication uses the document registry ETag

Ingestion runs SHALL skip an object only when the S3 ETag of the object equals the ETag recorded in the document registry's index state for the target collection. A failed ingestion SHALL NOT update the recorded ETag, so the next run retries the object instead of skipping it. The run path SHALL NOT write `manual-ingestion:*` markers to `INT_METADATA_STORE`; the Spring Integration streaming pipeline's metadata-store filter is unaffected.

#### Scenario: Unchanged object skipped

- **WHEN** an object was indexed by a previous run and its ETag is unchanged
- **THEN** the next run counts it as skipped and does not re-embed it

#### Scenario: Failure does not poison deduplication

- **WHEN** ingestion of an object fails during a run
- **THEN** the registry ETag for that object and collection is not updated
- **AND** a subsequent run attempts the object again rather than skipping it
