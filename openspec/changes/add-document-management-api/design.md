## Context

**Current state.** Documents live in the MinIO bucket `knowledge-base` (`app.s3.bucket` in `apps/ascend-agent/src/main/resources/application.yaml`) under `markdown/` and `documents/` prefixes. Chunks live in Qdrant collections `ascendai-768` and `ascendai-1536` with `source` / `type` / `title` metadata (`service/ingestion/IngestionMetadataKeys.java`); `source` is the sanitized object key, and `DocumentService.removeOldDocuments` deletes by `source ==` filter before re-adding. Ingestion state is a Spring Integration `JdbcMetadataStore` (`config/AppConfig.java`) writing `manual-ingestion:<key>:<etag> -> timestamp` rows into `INT_METADATA_STORE`, a table created by `spring.integration.jdbc.initialize-schema: always` outside Liquibase. `ManualIngestionService.run` scans the bucket synchronously, dedupes via `putIfAbsent` on that marker, and returns aggregate `{indexed, skipped, failed}` counts; stale-marker cleanup on failure is hand-rolled (`processObject`). `ManualIngestionService` routes only by markdown-vs-unstructured; the richer extension-based `DocumentRouter` (Markdown / Docling / ascend-ocr / Unstructured / per-page PDF) is used by the prompt-attachment path.

**Sibling dependencies (consumed, not re-specified).**

- `add-auth-and-identity`: all endpoints here assume its authenticated identity; `DELETE /api/v1/documents/{id}`, `POST /api/v1/documents/{id}/reindex`, and `POST /api/v1/ingestion/run` require the ADMIN role per that change's role model. This change writes no security rules of its own.
- `add-tenant-isolation`: the `documents` table is the natural home for its document-ownership column. This change creates the table; the tenant change adds and enforces the column. No tenancy behavior is specified here.
- `add-document-connectors`: synced sources (Google Drive, Notion, ...) will register documents through the same registry. The schema therefore carries `source_type` (open string: `upload`, `bucket-scan`, later `connector:<name>`) and a nullable `origin_uri`, so connectors need no schema change.

## Goals / Non-Goals

**Goals:**

- A queryable, Liquibase-managed registry of every knowledge-base document with status, chunk counts, and failure reasons.
- List / detail / delete / reindex endpoints over that registry.
- Asynchronous ingestion runs with observable per-file outcomes and a bounded history.
- Delete that is retryable after partial failure and safe to execute mid-chat.

**Non-Goals:**

- Authentication, authorization, tenancy (siblings own these).
- Connector sync logic (only the schema hooks land here).
- Changing the Spring Integration S3 streaming pipeline (`IngestionPipelineConfig`) or its metadata-store filter.
- Distributed job queues; ascend-ai-agent is a single instance today (`harden-cloud-deployment` may revisit).
- UI.

## Decisions

### D1. Registry tables: `documents` + `document_index_state` + `ingestion_runs`

- `documents`: `id UUID PK`, `object_key VARCHAR UNIQUE`, `display_name`, `size_bytes`, `mime_type`, `source_type`, `origin_uri NULL`, `status` (`UPLOADED` | `INDEXING` | `INDEXED` | `FAILED` | `DELETING`), `failure_reason NULL`, `created_at`, `updated_at`.
- `document_index_state`: `(document_id FK, collection_name)` unique pair, `chunk_count`, `etag`, `last_indexed_at`. A document can be indexed into `ascendai-768` and `ascendai-1536` independently (the embedding provider chosen per run decides the collection via `VectorStoreResolver`), so per-collection state is a child table rather than duplicated columns. Listing aggregates chunk counts and takes the max `last_indexed_at`.
- `ingestion_runs`: `id UUID PK`, `state` (`QUEUED` | `RUNNING` | `COMPLETED` | `FAILED`), `scope_prefix NULL`, `document_id NULL` (set for reindex runs), `embedding_provider`, `indexed_count`, `skipped_count`, `failed_count`, `failures JSONB` (array of `{objectKey, reason}`, capped at 100 entries), `requested_at`, `started_at NULL`, `finished_at NULL`.

Alternative considered: extend `INT_METADATA_STORE` usage. Rejected — it is a schema-less key-value table owned by Spring Integration, cannot hold typed columns, and is not Liquibase-managed, which violates the module's migration convention.

### D2. Registry ETag comparison replaces the manual-ingestion dedupe markers

`ManualIngestionService` stops calling `metadataStore.putIfAbsent` and instead compares the S3 object's ETag against `document_index_state.etag` for the target collection; unchanged means skip, changed or absent means ingest and update the row on success. This removes the hand-rolled stale-marker cleanup in `processObject` (failure simply leaves the old ETag in place, so the next run retries naturally). Existing `manual-ingestion:*` rows in `INT_METADATA_STORE` become inert and are left in place; the streaming pipeline's filter still owns that table.

Alternative considered: dual-write both stores during a transition. Rejected — two sources of truth for the same fact (DRY), and nothing reads the old markers after the switch.

### D3. Async runs: in-process single-worker executor, state persisted in Postgres

`POST /api/v1/ingestion/run` inserts a `QUEUED` row and submits the job to a dedicated single-threaded executor; it returns `202 Accepted` with `{runId}` and a `Location: /api/v1/ingestion/runs/{id}` header. Runs execute serially in submission order (a concurrent full-bucket scan against the same collection would race `removeOldDocuments`). Status reads come from Postgres, so any instance/thread can answer. On application startup, rows still `QUEUED` or `RUNNING` are marked `FAILED` with reason `interrupted by restart` — the job itself is safe to re-request because ETag dedupe makes re-runs cheap. Reindex jobs share the same run model with `document_id` set.

Alternative considered: keep `/run` synchronous and add polling only for reindex. Rejected — the blocking full-bucket scan is the worst offender (minutes-long HTTP requests through Docling/OCR) and the run-history requirement needs persisted runs anyway. Alternative considered: DB-polling job queue or message broker. Rejected as YAGNI for a single-instance service; the Postgres row is already the durable record, only execution is in-process.

### D4. Delete ordering: vectors, then object, then row — resumable via `DELETING` status

`DELETE /api/v1/documents/{id}` executes: (1) set `status = DELETING`; (2) delete Qdrant points with `source == object_key` from every collection listed in `document_index_state` (delete-by-filter is idempotent); (3) delete the MinIO object (idempotent); (4) delete the `document_index_state` rows and the `documents` row. A failure at any step leaves the row in `DELETING`; repeating the DELETE re-executes the remaining steps. Order rationale: orphaned vectors are the harmful failure mode (retrieval would cite a document whose file is gone), so vectors go first; an orphaned MinIO object is inert. Returns `204 No Content` on completion, `404` for an unknown id, `409 Conflict` if the document is currently `INDEXING` (deleting under an active ingest would race chunk re-insertion).

Mid-chat behavior: presigned source URLs already handed out (TTL `app.rag.source-attachments.presign-ttl`, default PT15M) are not tracked or revoked — they stop resolving once the MinIO object is gone and expire on their own anyway. In-flight chat turns that already retrieved chunks complete normally; subsequent retrievals no longer see the document.

### D5. Reindex goes through `DocumentRouter`

`POST /api/v1/documents/{id}/reindex` fetches the object bytes from MinIO and processes them via `DocumentRouter.routeAndProcess` (full extension-based routing, including per-page PDF Docling/OCR dispatch), then splits and ingests with the existing `removeOldDocuments`-then-add replacement path into the collection resolved from the requested embedding provider. Reindex ignores ETag dedupe by design (the point is to force a refresh, e.g. after a router or chunking improvement). It runs as an async run (D3) because OCR of a large PDF is minutes-long; response is `202` + run id, and the document shows `INDEXING` until the run finishes.

Note: the bucket-scan path (`ManualIngestionService.ingestObject`) still routes only markdown-vs-unstructured. Aligning it onto `DocumentRouter` is a behavior change to bulk ingestion quality and cost (OCR fan-out) and is deliberately left out of scope; reindex gives operators the precise tool for individual documents meanwhile.

### D6. Registry population and backfill

Upload registers or updates the row immediately (`status = UPLOADED`). Bucket-scan runs upsert rows for every object they visit, so the first run after deploy backfills the registry for pre-existing MinIO content; no data migration script attempts to reconstruct state Liquibase cannot see. Documents present in MinIO but never scanned simply do not appear in listings until a run executes — acceptable and self-healing.

### D7. Pagination and response shape

`GET /api/v1/documents` uses Spring Data `Pageable` (`page`, `size` with default 20 / max 100, `sort` defaulting to `updatedAt,desc`) and returns `{items, page, size, totalElements, totalPages}` following the module's DTO-at-the-boundary convention. Run history takes a `limit` query parameter (default 20, max 100), newest first.

### D8. The presigned link stays mandatory, `contentPath` is added beside it (owner decision, 2026-09-03)

The first draft of this change made `downloadUrl` and `expiresAt` optional on `SourceFile` and declared `contentPath` the canonical download path, on the reasoning that a public deployment should never have to expose the object store. That contradicted the `rag-source-attachments` baseline, which guarantees a non-blank `downloadUrl` and `expiresAt` on every source entry, and the contradiction had also broken archival: the delta modified a requirement titled `Caller sets `attachSources=true``, which is a scenario in the baseline rather than a requirement, so the merge aborted with a not-found error in every ordering while `openspec validate --strict` stayed silent (the validator skips a MODIFIED block whose target requirement is missing).

The owner's decision is that the link stays. Every source entry always carries a non-blank `downloadUrl` and `expiresAt`, exactly as the baseline guarantees today, and this change adds `documentId` and `contentPath` alongside them as further mandatory fields. The reason is that a caller must never have to implement two different ways of fetching the same source: if the presigned link were sometimes absent, every client would need both code paths plus the logic to choose between them.

What that costs is the deployment posture the first draft was reaching for. The object store still has to be reachable by clients wherever presigned links are handed out, so `harden-cloud-deployment` cannot treat the agent as the only public surface for source downloads. That is accepted deliberately, and it is the trade the decision makes.

Two mechanical consequences follow. The delta now modifies the requirement that genuinely exists, `Opt-in `attachSources` parameter on prompt endpoint`, and carries all three of its baseline scenarios so the merge engine does not abort on a dropped scenario name. The delta's `SourceFile` modification is written on top of the post-Floci wording from `replace-minio-with-floci`, which is the text on the ground, rather than the older MinIO-specific phrasing still sitting in `openspec/specs/`.

## Risks / Trade-offs

- [First run after deploy re-indexes everything] The registry starts empty, so ETag comparison misses and every object re-ingests once. → Mitigation: `removeOldDocuments` keeps this idempotent for Qdrant; call out the one-time embedding cost in the release note; operators can scope the first run with `prefix`.
- [In-process executor loses queued runs on restart] → Mitigation: startup sweep marks stale runs `FAILED` with an explicit reason; re-requesting is cheap due to ETag dedupe.
- [Delete leaves an orphaned MinIO object if the process dies between steps 3 and 4] → Mitigation: row stays `DELETING` and is surfaced as such in listings; retrying the DELETE finishes the job.
- [`failures` JSONB cap at 100 hides the tail of a catastrophic run] → Mitigation: `failed_count` stays exact; the cap only bounds detail rows, and the log retains every failure line.
- [Breaking `/run` response contract] Existing Bruno requests and the e2e specs assert on synchronous counts. → Mitigation: update the Bruno collection and `apps/ascend-agent/e2e/` specs in the same change; version stays `/api/v1` because the endpoint's consumers are all in-repo.
- [Race between reindex and delete on the same document] → Mitigation: `409` guard both directions — delete rejects `INDEXING`, reindex rejects `DELETING`.

## Migration Plan

1. Ship `02-document-management.xml` (pure additive tables) — deployable ahead of code.
2. Deploy the code: new endpoints live, `/run` now async, dedupe reads the registry.
3. Trigger one full ingestion run to backfill the registry.
4. Rollback: revert the deployment; the old code ignores the new tables entirely (its `INT_METADATA_STORE` markers were never deleted), so behavior returns to pre-change state without a down-migration. The tables can be dropped in a later cleanup changelog if the change is abandoned.

## Open Questions

- Should run history have retention (e.g. prune rows older than 30 days)? Proposed: yes, a scheduled prune, but confirm the window with the user during implementation.
- Should `GET /api/v1/documents` support a `status` filter in this change or defer to the connectors change that will need it? Proposed: include it now — it is one JPA specification and the listing is the operator's main triage tool.
