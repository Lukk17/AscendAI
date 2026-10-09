## ADDED Requirements

### Requirement: Ingestion runs execute asynchronously as tracked jobs

`POST /api/v1/ingestion/run` SHALL NOT block for the duration of the bucket scan. It SHALL persist a run record with state `QUEUED`, submit the job for execution, and immediately return HTTP 202 with a body containing the run id and a `Location` header pointing at `/api/v1/ingestion/runs/{id}`. Runs SHALL execute one at a time in the whole deployment, also when several agent instances run, in submission order, and transition `QUEUED` → `RUNNING` → `COMPLETED` (or `FAILED`). A `QUEUED` run SHALL be run by any live instance, also after the instance that accepted it stopped. A `RUNNING` run whose instance stopped renewing its lease SHALL be marked `FAILED` with an explicit interrupted-by-restart reason, at the next application start and by a periodic sweep while the instances stay up, and a run with a live lease of another instance SHALL never be marked so. While a run executes, its instance SHALL renew its lease at a configured interval (default 10 seconds), a lease SHALL expire a configured time after its last renewal (default 60 seconds), and an idle instance SHALL check the queue at a configured interval (default 30 seconds) even when no queue notification reached it. The existing `prefix` and `embeddingProvider` parameters SHALL be preserved and recorded on the run.

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

#### Scenario: Two instances share the queue

- **WHEN** two agent instances run against one database and two runs are requested, one on each instance
- **THEN** the two runs execute one after the other in submission order
- **AND** the startup of a third instance leaves the run that is `RUNNING` with a live lease untouched

#### Scenario: A long run keeps its lease

- **WHEN** a run executes for longer than the configured lease length and its instance stays up
- **THEN** its lease is renewed while it runs, and neither the startup sweep of another instance nor the periodic sweep marks it `FAILED`

### Requirement: Run status reports counts and per-file failures

`GET /api/v1/ingestion/runs/{id}` SHALL return the run's state, scope (prefix or single-document reference), embedding provider, requested / started / finished timestamps, aggregate `indexed`, `skipped`, and `failed` counts, and a per-file failure list of `{objectKey, reason}` entries. The failure detail list MAY be capped (at a configured number of entries, default 100) but the `failed` count SHALL remain exact. Unknown run ids SHALL return HTTP 404 with an RFC 7807 problem detail whose `code` is `not_found`.

#### Scenario: Completed run exposes counts and failures

- **WHEN** a run completes having indexed 2 objects, skipped 1 unchanged object, and failed on 1 object
- **THEN** `GET /api/v1/ingestion/runs/{id}` returns state `COMPLETED` with `indexed` reflecting the ingested chunks, `skipped` = 1, `failed` = 1
- **AND** the failure list contains one entry with the failing object key and a non-empty reason

#### Scenario: Unknown run id

- **WHEN** `GET /api/v1/ingestion/runs/{id}` is invoked with an id that does not exist
- **THEN** the response status is 404

### Requirement: Run history is queryable

The agent SHALL expose `GET /api/v1/ingestion/runs` returning recent runs newest-first, including reindex runs. The endpoint SHALL accept a `limit` query parameter (a configured default, default 20, and a configured maximum, default 100) and an optional `state` filter (`QUEUED`, `RUNNING`, `COMPLETED`, `FAILED`). The agent SHALL delete finished runs whose `finished_at` is older than the retention window `app.ingestion.run-retention` (default 30 days) and SHALL never delete a run that is still `QUEUED` or `RUNNING`. The deletion SHALL be a retention entry of the one shared retention task of `add-shared-scheduler`, run by exactly one agent instance per run of that task.

#### Scenario: History lists recent runs newest-first

- **WHEN** three runs have executed and `GET /api/v1/ingestion/runs?limit=2` is invoked
- **THEN** the response contains the 2 most recent runs ordered newest-first
- **AND** each entry carries the run id, state, and counts

#### Scenario: History filtered by state

- **WHEN** `GET /api/v1/ingestion/runs?state=FAILED` is invoked
- **THEN** every returned run has state `FAILED`

#### Scenario: Old finished runs are pruned

- **WHEN** the shared retention task runs and one `COMPLETED` run finished 31 days ago while one `RUNNING` run started 40 days ago
- **THEN** the completed run is deleted
- **AND** the running run is kept

### Requirement: Bucket-scan ingestion routes every object through DocumentRouter

Every object an ingestion run ingests SHALL be parsed via `DocumentRouter.routeAndProcess` (extension-based routing to the Markdown parser, Docling, ascend-ocr, Unstructured, or per-page PDF dispatch), identical to the upload and single-document reindex paths. The bucket-scan path SHALL NOT fall back to a default or plain-text parser that bypasses `DocumentRouter`, so a connector-dropped or manually-dropped PDF, Office, image, or e-mail file receives the same parse quality as an uploaded one. This closes the pre-existing gap where `ManualIngestionService`'s scan path ingested objects without routing.

#### Scenario: Scanned PDF is routed, not plain-parsed

- **WHEN** an ingestion run scans a scanned-image PDF dropped into the bucket out-of-band
- **THEN** the object is dispatched through `DocumentRouter` (per-page text-vs-scan split to Docling / ascend-ocr)
- **AND** it is not ingested as raw bytes or plain text

#### Scenario: Office document dropped into the bucket

- **WHEN** an ingestion run scans a `.docx` object with no prior registry row
- **THEN** the object is parsed via Docling through `DocumentRouter`, the same path an upload of that file would take

### Requirement: Bucket-scan deduplication uses the document registry ETag

Ingestion runs SHALL skip an object only when the S3 ETag of the object equals the ETag recorded in the document registry's index state for the target collection. A failed ingestion SHALL NOT update the recorded ETag, so the next run retries the object instead of skipping it. The run path SHALL NOT write `manual-ingestion:*` markers to `INT_METADATA_STORE`, and the Spring Integration streaming pipeline SHALL use the same registry ETag, so one store remembers what was ingested.

#### Scenario: Unchanged object skipped

- **WHEN** an object was indexed by a previous run and its ETag is unchanged
- **THEN** the next run counts it as skipped and does not re-embed it

#### Scenario: Failure does not poison deduplication

- **WHEN** ingestion of an object fails during a run
- **THEN** the registry ETag for that object and collection is not updated
- **AND** a subsequent run attempts the object again rather than skipping it

### Requirement: The streaming pipeline picks up new objects through the registry

When the streaming S3 pipeline is switched on, an object that lands in the knowledge-base bucket SHALL be picked up by its poller within about one poll interval (default 1 second), SHALL get or keep its registry row (`bucket-scan` when the row is new), and SHALL be indexed by a single-document ingestion run of the run model, through the same document routing as every other path. An object whose registry ETag for the target collection equals its S3 ETag SHALL NOT be picked up again. When several agent instances find the same object, exactly one run SHALL be queued for it, and while that run is `QUEUED` or `RUNNING` no second run SHALL be queued for the same document.

#### Scenario: New object indexed at once

- **WHEN** the pipeline is on and a Markdown object is put into the bucket
- **THEN** within a few seconds a single-document run for it appears in `GET /api/v1/ingestion/runs`, and after it completes the document reads `INDEXED` with source type `bucket-scan`

#### Scenario: Unchanged object not picked up again

- **WHEN** the pipeline is on and an object that was indexed stays unchanged
- **THEN** no further run is queued for it

#### Scenario: Two instances, one run

- **WHEN** two agent instances with the pipeline on find the same new object
- **THEN** exactly one run is queued for that document
