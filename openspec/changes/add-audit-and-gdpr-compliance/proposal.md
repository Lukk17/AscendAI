## Why

AscendAI cannot be sold to EU companies in its current shape. Three compliance gaps, all verified in code:

1. **No audit trail.** There is no record of who did what, anywhere in the codebase — no audit table, no audit service, nothing an auditor or an incident responder could query. A GDPR Article 30 processing record and any SOC-2-adjacent sales conversation both start with "show me the audit log", and today the answer is `docker logs`.
2. **Customer content leaks into logs.** `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/controller/PromptController.java` lines 90-97 log the **full prompt body** plus userId at INFO on every request. `application.yaml` lines 397-404 set `org.springframework.ai` to DEBUG, so Spring AI's request/response logging (prompt, document context, model output) also hits stdout — and the observability stack ships all stdout to Loki via Vector, giving prompt content a 168h searchable afterlife in a log store. (Side finding: the `com.lukk.ai.agent: DEBUG` entry names a logger that doesn't match the actual package `com.lukk.ascend.ai.agent` — it is a stale no-op.)
3. **The right to erasure (GDPR Article 17) is unimplementable.** AscendMemory has a per-user wipe (`POST /api/v1/memory/wipe`) and `SemanticMemoryClient` exposes it, but nothing deletes a user's chat history (Redis `chat:{userId}` keys + Postgres `chat_history`), `user_instructions` rows, ingested documents (MinIO `knowledge-base` bucket), or their Qdrant vectors (`ascendai-768` / `ascendai-1536`). A data-subject request today means five manual store-by-store operations with no proof of completion. Retention is equally absent: Postgres rows live forever (the `chat-history-persistence` spec explicitly defers "a separate retention policy" that was never built).

## What Changes

- **Audit log (new).** An append-only Postgres `audit_log` table (Liquibase changelog) recording actor, tenant, action, resource, outcome, source IP, and timestamp for security-relevant events: token rejections at the resource server, chat requests (prompt **length and SHA-256 hash**, never the body), document upload / delete / presigned-URL issuance, ingestion runs, memory wipes, erasure jobs, admin operations, and quota rejections (event emitted here, quota logic owned by `add-usage-metering-and-quotas`). Events are written through a service-layer `AuditRecorder` (Spring application events, async listener), never via log lines. Queryable through ADMIN-only `GET /api/v1/audit` with filters and pagination.
- **User and tenant erasure (new).** `DELETE /api/v1/users/{userId}/data` (self or ADMIN) starts an asynchronous erasure job spanning all five stores: Postgres (`chat_history`, `user_instructions`, the `conversations` rows owned by `add-chat-streaming-and-conversations`, and usage rows owned by `add-usage-metering-and-quotas`), Redis `chat:{userId}` keys, MinIO objects, Qdrant vectors in both collections, and AscendMemory memories across configured embedding providers. The per-tenant variant additionally covers tenant-shared tables that are not attributed to a single user — the `documents` / `document_index_state` / `ingestion_runs` registry from `add-document-management-api` and the connector configuration / sync-run tables from `add-document-connectors`. Job status is queryable; completion emits an audit event with per-store deletion counts. Audit rows survive erasure with the actor pseudonymized (design decides the mechanism).
- **Data export / portability (new).** A per-user `POST /api/v1/users/{userId}/data/export` (self or ADMIN) and per-tenant `POST /api/v1/tenants/{tenantId}/data/export` (ADMIN) start an asynchronous export job that assembles the subject's data — chat history and conversations, user instructions, ingested documents from MinIO, and AscendMemory memories — into a single downloadable archive with a manifest, satisfying GDPR Article 20 portability and clean customer offboarding ("give us our data, then erase it"). Reuses the erasure job machinery and store-walker inventory so export and erasure never drift on which stores hold subject data.
- **Log redaction (new).** Prompt bodies never appear in logs at any level under the docker/production posture: `PromptController` switches to length + hash, `application-docker.yaml` pins `org.springframework.ai` (and the corrected application logger) to INFO, and a written redaction convention covers all six services — the Python services' `[ServiceName]`-prefixed logging gets audited for content leakage as part of this change (AscendMemory's REST layer was spot-checked clean; the sweep makes it a guarantee).
- **Retention policy (new).** Configurable, scheduled retention for Postgres `chat_history` / `user_instructions` (default 180 days) and `audit_log` rows (default 730 days), with documented defaults. The scheduled retention job SHALL be replica-safe — guarded by a single-owner lock (advisory lock or ShedLock) so it fires once per window even when the agent runs with more than one instance. Redis already expires via the `chat-history-persistence` TTL; Loki is already bounded at 168h; Prometheus at 72h — this change closes the Postgres gap and documents the whole retention matrix in one place.
- **Compliance walkthrough doc** (`docs/COMPLIANCE.md`): what is audited, how to serve an erasure request, retention defaults, and what survives erasure.

Depends on `add-auth-and-identity` (trustworthy actor identity, ADMIN role, token-rejection events) and `add-tenant-isolation` (tenant claim and tenant-scoped resource attribution for erasure). Sibling changes own adjacent surfaces: single-conversation delete is `add-chat-streaming-and-conversations`, single-document delete is `add-document-management-api`, the usage ledger schema is `add-usage-metering-and-quotas` (our erasure deletes its rows; coordinated in design).

## Capabilities

### New Capabilities

- `audit-logging`: append-only audit trail of security-relevant events with actor/tenant/action/resource/outcome/IP/timestamp, service-layer recorder, ADMIN-only query API with filters and pagination.
- `data-erasure`: asynchronous per-user and per-tenant erasure jobs spanning Postgres, Redis, MinIO, Qdrant, and AscendMemory, with status endpoint, completion audit event, and pseudonymized audit-row survival.
- `log-redaction`: prompt and document content never logged in the production/docker posture; length-and-hash convention; per-service redaction rules for all six services.
- `data-retention`: configurable scheduled retention for chat history and audit rows with documented platform-wide retention matrix; the retention job is replica-safe (single-owner lock).
- `data-portability`: asynchronous per-user and per-tenant export jobs that assemble the subject's data across Postgres, MinIO, and AscendMemory into a downloadable archive with a manifest, sharing the erasure store-walker so export and erasure cover the same stores.

### Modified Capabilities

- `chat-history-persistence`: the "TTL configuration is documented" requirement currently mandates a comment saying Postgres pruning is deferred to "a separate retention policy" — that policy now exists, so the documented comment must point at the concrete `app.retention.*` configuration instead of a placeholder.

(`semantic-memory-client` reviewed and left unchanged — erasure consumes its existing `wipeUserMemory` contract as-is. `ingestion-security` reviewed and left unchanged — upload hygiene requirements don't change; the audit events emitted on upload live in `audit-logging` to keep one source of truth.)

## Impact

- **AscendAgent (bulk of the work)**:
  - New Liquibase changelog under `src/main/resources/db/changelog/` for `audit_log` and `erasure_job` tables.
  - New `service/audit/` package: `AuditRecorder`, event listener, repository; new `service/erasure/` package: job orchestrator + per-store erasure steps; new `service/export/` package: export job orchestrator reusing the erasure store-walker inventory to assemble the archive + manifest.
  - New `controller/AuditController.java` and `controller/UserDataController.java` (erasure + export start/status/download).
  - `controller/PromptController.java` — prompt-body log line replaced with length + hash; audit event emitted.
  - `controller/IngestionController.java`, `service/rag/S3PresignedUrlService.java` — audit events on upload / run / presign.
  - `src/main/resources/application.yaml` + `application-docker.yaml` — logging-level corrections, `app.retention.*` and `app.audit.*` properties.
  - New scheduled retention job.
- **Python services**: log-content audit of AudioScribe, AscendWebSearch, AscendMemory, PaddleOCR against the redaction convention; fixes where leakage is found.
- **Cross-change coordination**: actor identity and ADMIN gate from `add-auth-and-identity`; tenant attribution from `add-tenant-isolation`; usage-row erasure coordinated with `add-usage-metering-and-quotas`.
- **Tests**: erasure integration test asserting zero residue across all five stores (Testcontainers); audit-row-per-action tests; log-capture test asserting prompt bodies are absent; retention job tests.
- **Docs**: new `docs/COMPLIANCE.md`; README documentation-map link; `AGENTS.md` notes where conventions change.

## Relevant Skills

- `/springboot-patterns`
- `/java-coding-standards`
- `/jpa-patterns`
- `/database-migrations`
- `/security-review`
- `/python-patterns`
- `/springboot-tdd`
