## Context

Documents enter the RAG knowledge base through exactly two hand-driven paths today:

1. `POST /api/v1/ingestion/upload` (`controller/IngestionController.java`) — multipart upload; filename sanitization (`util/IngestionSecurity`), Tika MIME sniffing against `app.ingestion.upload.allowed-mime-types`, then a `StorageService` write into MinIO under `markdown/` or `documents/`.
2. Out-of-band drops into the MinIO bucket followed by `POST /api/v1/ingestion/run` — `service/ingestion/ManualIngestionService.java` scans the bucket, dedupes on ETag via a `ConcurrentMetadataStore` (`manual-ingestion:<key>:<etag>` markers), and pushes content through `IngestionService` / `DocumentRouter` into Qdrant.

A Spring Integration S3 poller exists (`config/IngestionPipelineConfig.java`) but is disabled by default (`app.ingestion.auto.enabled=false`). Downstream parsing is already rich: `DocumentRouter` routes to the markdown parser, Docling, PaddleOCR, or Unstructured, with per-page PDF classification. There is no connector or sync concept anywhere in the codebase.

This change layers automated source sync on top, without touching the parse path.

**Dependencies on sibling changes** (their scope is not re-specified here):

- `add-auth-and-identity` — provides the ADMIN role that guards the connector API and the authenticated principal recorded on connector mutations.
- `add-tenant-isolation` — provides the tenant prefix under which connector-fetched objects land in MinIO and the tenant metadata carried into Qdrant chunks. Connector configuration rows are tenant-scoped using the same tenant key.
- `add-document-management-api` — owns the document metadata/status model and the single-document deletion machinery (MinIO object + Qdrant chunks + metadata row). Deletion propagation in this change calls that path; it does not build its own.
- `add-usage-metering-and-quotas` — owns the encryption-at-rest mechanism (BYOK key handling). Connector client secrets are stored with the same mechanism family; this change consumes it, it does not re-specify encryption.

## Goals / Non-Goals

**Goals:**

- A provider-agnostic connector framework: per-tenant persisted configuration, scheduled + on-demand incremental sync, sync-run history with per-file outcomes, deletion propagation, ADMIN CRUD API.
- First concrete connector: SharePoint/OneDrive via Microsoft Graph with client-credentials auth, delta-query incremental sync, site/drive/folder scoping, allowlist-aligned file filtering, and Graph-compliant throttling behaviour.
- Connectors land bytes in MinIO and trigger the existing pipeline — nothing else.

**Non-Goals:**

- **Google Drive, Confluence, and network-share connectors.** Named follow-ons, explicitly out of scope. The framework interfaces (`DocumentConnector`, per-connector `ConnectorType`, credential-reference indirection, per-connector cursor storage) are designed so each of these is an additive implementation plus a Liquibase enum value — no framework rework.
- Any new parsing capability. `DocumentRouter` and its parsers are untouched.
- Real-time (webhook/subscription-based) change notification. First iteration is polling via scheduled delta sync; Graph change notifications are a later optimisation.
- Per-document ACL mirroring from SharePoint into RAG retrieval. Everything a connector syncs is visible to the whole tenant. ACL-aware retrieval is a separate future change.
- User-delegated (on-behalf-of) Graph auth. Client credentials only.
- Encryption mechanism design — consumed from `add-usage-metering-and-quotas`.
- Single-document delete mechanics — consumed from `add-document-management-api`.

## Decisions

### D1 — Connector → MinIO → existing pipeline; no parallel parse path

A connector's contract ends when the source file's bytes are written to MinIO under the tenant prefix (markdown to the markdown folder, everything else to the documents folder, same routing rule as `IngestionController.determineFolder`) and the existing ingestion scan is triggered for the affected prefix. Parsing, chunking, embedding, and dedup are the existing pipeline's job — `ManualIngestionService`'s ETag-keyed scan already makes re-landing an unchanged object a no-op and re-landing a changed object a replace (`documentService.removeOldDocuments`).

*Why:* one parse path means one set of parser bugs, one dedup semantics, one metrics surface. The alternative — connectors calling `IngestionService` directly with in-memory streams — would bypass the ETag dedup and the MinIO source-of-truth, and would make the `add-document-management-api` metadata model inconsistent (documents in Qdrant with no MinIO object).

*Consequence:* connector-fetched files pass the **same** hygiene as uploads — filename sanitization from `util/IngestionSecurity` and MIME sniffing against `app.ingestion.upload.allowed-mime-types` — applied by the framework before the MinIO write, so a compromised or misconfigured source cannot smuggle disallowed content types past the controller-level checks.

### D2 — Framework shape: `DocumentConnector` interface + sync orchestrator

- `DocumentConnector` (interface, `service/connector/`): `ConnectorType type()`, `ChangeSet fetchChanges(ConnectorConfig, SyncCursor)` returning added/modified/deleted entries plus the next cursor. Implementations are stateless; all state lives in the database.
- `ConnectorSyncOrchestrator` (framework): loads due connectors, resolves credentials, calls `fetchChanges`, applies hygiene + MinIO writes + deletion propagation, records the sync run and per-file outcomes, persists the new cursor **only after** the run completes; a failed run keeps the previous cursor so the next run retries the same window.
- Scheduling via Spring's `@Scheduled` tick (every minute) that scans for connectors whose `next_run_at` has passed, guarded by `ShedLock`-style DB row locking (`SELECT ... FOR UPDATE SKIP LOCKED` on the connector row) so multiple agent instances never double-sync one connector. Per-connector schedule stored as a cron expression.

*Why not Quartz:* a full scheduler dependency for "run N connectors on a cron" is overkill (KISS); the DB-row claim gives multi-instance safety without extra infrastructure. *Why not Spring Integration poller reuse:* `IngestionPipelineConfig` polls one bucket with one filter; connectors need per-source cursors, credentials, and run history — a different problem.

### D3 — Data model (Liquibase, new changelog in `db/changelog/`)

Four tables, all tenant-scoped:

- `connector` — id (UUID), tenant id, type (enum string, first value `SHAREPOINT`), display name, credentials reference (FK/opaque handle into the encrypted credential store from `add-usage-metering-and-quotas`), source scope (JSONB: site/drive/folder identifiers — provider-specific shape validated by the connector implementation), cron schedule, enabled flag, created/updated audit columns, `next_run_at`.
- `connector_sync_run` — id, connector FK, trigger (`SCHEDULED` | `MANUAL`), status (`RUNNING` | `SUCCEEDED` | `PARTIAL` | `FAILED`), started/finished timestamps, counters (added/updated/deleted/skipped/failed), error summary.
- `connector_sync_file_outcome` — id, sync-run FK, source item id, source path, action (`ADDED` | `UPDATED` | `DELETED` | `SKIPPED` | `FAILED`), MinIO key, failure reason (nullable).
- `connector_sync_cursor` — connector FK (+ per-drive discriminator for SharePoint, since Graph issues one delta token per drive), opaque cursor value, updated timestamp.

*Why JSONB scope instead of typed columns:* each provider scopes differently (SharePoint: site/drive/folder; Google Drive: shared-drive/folder; Confluence: space). A typed-per-provider table set would multiply migrations per connector; a JSONB blob validated by the owning connector keeps additions additive (OCP).

### D4 — SharePoint sync via Graph delta queries

- Auth: MSAL-style client-credentials flow per tenant (Entra ID app registration; tenant id + client id + encrypted client secret in the credential store). Token cached in memory until expiry; never persisted, never logged.
- Change detection: `GET /drives/{drive-id}/root/delta` (scoped to configured folders by filtering returned paths). First run is a full enumeration (delta with no token); subsequent runs pass the stored `deltaLink` token and receive only created/modified/deleted items. Deleted items arrive as entries with a `deleted` facet.
- Scoping: configured sites are resolved to drives via `GET /sites/{site-id}/drives`; folder scoping filters delta results by path prefix. Items outside scope are ignored (not recorded as skipped — they are not part of the connector's universe).
- Filtering: file MIME (from Graph item metadata, re-verified by Tika sniff before the MinIO write per D1) must be in `app.ingestion.upload.allowed-mime-types`; file size must not exceed the connector's size limit (default aligned with the multipart limits from `ingestion-security`). Filtered files are recorded as `SKIPPED` with reason.
- Throttling: on HTTP 429 or 503 with `Retry-After`, sleep the advised interval; without the header, exponential backoff with jitter, bounded retries per request and a bounded total-throttle budget per run — exceeding the budget ends the run as `PARTIAL` with the cursor unadvanced past the completed window. This follows Microsoft's published throttling guidance for Graph.

*Why delta queries over full listing + diff:* delta is the Graph-native incremental mechanism — server-side change tracking, one round trip per page of changes, deletions included. Full listing per sync would hammer both Graph (throttling) and our comparison logic, and cannot see deletions without keeping a full remote-inventory shadow ourselves.

### D5 — Deletion propagation reuses `add-document-management-api`

When a delta entry carries the deleted facet, the orchestrator maps source item → MinIO key (recorded in the file-outcome history and in the document metadata model owned by `add-document-management-api`) and invokes that change's single-document deletion path, which removes the MinIO object, the Qdrant chunks for that source, and the metadata row. This change adds only the mapping and the trigger; if `add-document-management-api` has not shipped, this change is blocked on it (declared dependency, not an inline re-implementation).

### D6 — Credentials: reference, not value

The `connector` row stores an opaque credentials reference; the secret material lives in the encrypted credential store from `add-usage-metering-and-quotas` (same mechanism family as BYOK provider keys). API responses never echo secrets (write-only field); logs and sync-run records carry the reference only. Rotating a secret is an update through the credential store with no connector-table change.

## Risks / Trade-offs

- [Graph throttling on large tenants — initial full sync of a big site can hit 429 storms] → delta paging with `Retry-After` compliance, bounded per-run throttle budget, `PARTIAL` status with resumable cursor; document in `docs/CONNECTORS.md` that the first sync of a large site can take multiple runs.
- [Delta token invalidation (Graph returns `410 Gone` / `resyncRequired`)] → orchestrator resets the cursor and performs a full re-enumeration; ETag dedup in `ManualIngestionService` makes re-landing unchanged files a no-op, so a forced resync is slow but not corrupting.
- [Deletion propagation ordering — file deleted and re-added between syncs] → process delta entries in Graph-returned order per item id; Graph collapses per-item history in a delta page, so the last state wins.
- [Filename collisions — two source files sanitize to the same MinIO key] → connector keys include a source-scoped path segment (sanitized relative path, not just the leaf name) under the tenant prefix; collisions within one connector then require identical relative paths, which the source itself forbids.
- [Scheduler drift with multiple agent instances] → DB-row claim (`FOR UPDATE SKIP LOCKED`) makes each due connector run exactly once per due tick.
- [Secret leakage via logs or API echoes] → write-only credential fields, reference-only persistence, explicit test asserting no credential material appears in logs at any level during a sync (including failure paths).
- [Sibling-change coupling — this change cannot ship before its four dependencies] → declared up front; the framework compiles against interfaces those changes define, and tasks order the integration points last.

## Migration Plan

1. Liquibase changelog adds the four tables; purely additive, no existing-table changes, rollback = drop tables.
2. Framework + SharePoint connector ship dark: no connector rows exist until an ADMIN creates one, so default behaviour is byte-identical to today.
3. Disabling a connector stops scheduling immediately; deleting a connector removes its configuration, cursors, and run history but leaves already-ingested documents in place (removal is an explicit document-management operation, not a side effect of connector deletion).
4. Rollback: disable connectors (or feature-flag the scheduler off via a property), then revert code; tables can stay (inert) or be dropped with the changelog rollback.

## Open Questions

1. Should sync-run history have a retention policy (row count or age cap per connector), or is unbounded history acceptable for the first iteration? Default proposal: cap at the last 50 runs per connector, prune on write.
2. Does `add-tenant-isolation` expose the tenant MinIO prefix as an injectable component this change can call, or is the prefix convention-only? To confirm when that change's design lands; the orchestrator assumes an injectable prefix resolver.
