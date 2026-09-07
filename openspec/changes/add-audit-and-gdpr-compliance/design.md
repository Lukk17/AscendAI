## Context

AscendAgent is the only service with a Postgres connection and the only place all five data stores (Postgres, Redis, MinIO, Qdrant, AscendMemory) are already wired as clients — so both the audit trail and the erasure orchestrator live there. Current state, verified:

- No audit table, recorder, or query API exists anywhere.
- `PromptController.java:90-97` logs the full prompt at INFO. `application.yaml:397-404` sets `org.springframework.ai: DEBUG` (real content leak via Spring AI's advisor/model logging) and `com.lukk.ai.agent: DEBUG` (stale logger name — actual package is `com.lukk.ascend.ai.agent`, so this line is a no-op and the app effectively logs at root INFO). `application-docker.yaml` has **no** `logging:` block, so the DEBUG leak carries into the container posture. Vector ships all container stdout to Loki (168h retention).
- Per-user data lives in: Postgres `chat_history` + `user_instructions` (`01-initial-schema.xml`), Redis `chat:{conversationId}` keys (`PersistentChatMemory.java:69`), MinIO bucket `knowledge-base` (`application.yaml:92`), Qdrant collections `ascendai-768` / `ascendai-1536`, and AscendMemory (mem0/Qdrant, wiped via the existing `SemanticMemoryClient.wipeUserMemory(userId, embeddingProvider)`).
- Retention today: Redis TTL (chat-history-persistence spec), Loki 168h, Prometheus 72h, Tempo 168h. Postgres: nothing, ever.

This change **depends on** `add-auth-and-identity` (validated JWT identity, `USER`/`ADMIN` roles, token-rejection events at the resource server) and `add-tenant-isolation` (the `tenant` claim and per-tenant attribution of documents/vectors). Neither is re-specified here; where erasure needs "all MinIO objects belonging to user X", the ownership metadata comes from tenant isolation's scoping work. The `add-usage-metering-and-quotas` sibling owns the usage-ledger schema; erasure here deletes its per-user rows and its quota-rejection path emits an audit event through our recorder — coordinated via task references, not duplicated specs.

## Goals / Non-Goals

**Goals:**

- One append-only audit trail for security-relevant events, queryable by admins.
- One-call, provable, asynchronous erasure of everything a user (or tenant) owns across all five stores.
- Zero prompt/document content in logs under the docker/production posture, with a convention all six services follow.
- Bounded retention for the two unbounded Postgres surfaces (chat history, audit log).

**Non-Goals:**

- Authentication, roles, token validation (`add-auth-and-identity`).
- Tenant claim propagation and per-tenant data scoping (`add-tenant-isolation`).
- Single-conversation delete (`add-chat-streaming-and-conversations`) and single-document delete (`add-document-management-api`) — erasure here is the everything-for-a-user path only.
- Usage-ledger schema and quota logic (`add-usage-metering-and-quotas`).
- Consent management, data-processing agreements, cookie banners — legal-document territory, out of scope.
- Cryptographic erasure / envelope encryption of stores (a future hardening; physical deletion suffices for the stores we run).

## Decisions

### D1 — Audit events via Spring application events, not inline writes

`AuditRecorder.record(AuditEvent)` publishes a Spring `ApplicationEvent`; an `@Async` listener persists the row. Rationale: the business operation must never block on or fail because of audit persistence (a chat request that 500s because the audit insert timed out is worse than a missed audit row). A failed audit write logs at ERROR and increments a Micrometer counter (`audit.write.failed`) so the observability stack alerts on systemic loss. Alternative considered: synchronous same-transaction insert (strongest guarantee, but couples chat latency to a second Postgres write and fails closed); rejected for the request path, but erasure-job lifecycle events use synchronous writes since they are already async background work where the stronger guarantee is free.

### D2 — Append-only enforced in the database, not just the code

Liquibase creates `audit_log` and a Postgres trigger that raises an exception on `UPDATE` or `DELETE` — except deletes issued by the retention job's dedicated path (implemented as the trigger allowing deletes where `occurred_at` is older than a session-set retention boundary, via `set_config`). Rationale: "append-only because the repository has no update method" is not a compliance argument; a DB-level guard is. Alternative: separate Postgres role with only INSERT/SELECT grants — cleaner in principle, but the app runs as a single DB user today and introducing role separation is a `harden-cloud-deployment` concern; the trigger works with the current single-user setup and survives role changes later.

### D3 — Audit schema

`audit_log(id BIGSERIAL PK, occurred_at TIMESTAMPTZ NOT NULL, actor VARCHAR NOT NULL, tenant VARCHAR NULL, action VARCHAR NOT NULL, resource_type VARCHAR NULL, resource_id VARCHAR NULL, outcome VARCHAR NOT NULL, source_ip VARCHAR NULL, details JSONB NULL)` with indexes on `(occurred_at)`, `(actor, occurred_at)`, `(action, occurred_at)`. `action` is a closed enum-backed set: `AUTH_TOKEN_REJECTED`, `CHAT_PROMPT`, `DOCUMENT_UPLOADED`, `DOCUMENT_DELETED`, `DOCUMENT_PRESIGN_ISSUED`, `INGESTION_RUN`, `MEMORY_WIPED`, `ERASURE_REQUESTED`, `ERASURE_COMPLETED`, `ADMIN_OPERATION`, `QUOTA_REJECTED`. `details` carries action-specific payload — for `CHAT_PROMPT` that is `{"prompt_length": N, "prompt_sha256": "..."}`, never the body. Rationale for JSONB details over wide columns: actions have heterogeneous payloads and the query API filters on the indexed columns, not inside details.

### D4 — Erasure is a persisted state machine, not a fire-and-forget task

`erasure_job(id UUID PK, subject_type USER|TENANT, subject_id, requested_by, status PENDING|RUNNING|COMPLETED|FAILED|PARTIAL, per-store status + deleted-count columns, requested_at, completed_at, failure_detail)`. The orchestrator walks the stores in a fixed order — Postgres rows, Redis keys, MinIO objects, Qdrant points (both collections), AscendMemory wipe (every configured embedding provider) — recording per-store outcome. A store failure marks the job `PARTIAL` (not rolled back: erasure of four stores is strictly better than zero) and the job is re-runnable idempotently; every step is a delete-if-exists. Rationale for Postgres-persisted jobs over an in-memory `@Async` future: an erasure request is a legal act — it must survive a restart and be reportable ("job X completed at T with counts") months later. `DELETE /api/v1/users/{userId}/data` returns `202 Accepted` with the job id; `GET /api/v1/users/{userId}/data/erasure/{jobId}` returns status. Authorization: the authenticated principal must equal `userId` or hold ADMIN (self-service Article 17 without a support ticket).

### D5 — Audit rows survive erasure, pseudonymized

GDPR Article 17(3)(b) permits retaining data needed for legal obligations; an audit trail that evaporates on erasure is useless. Decision: erasure rewrites `actor` (and `resource_id` where it is the userId) in the subject's audit rows to `HMAC-SHA256(userId, server-side pepper)` truncated to 16 hex chars, prefixed `pseudo:`. The pepper lives in configuration (env var), never in the database — without it the pseudonym is irreversible; with it, a lawful re-identification (e.g. a court order) remains possible. This rewrite is the **one sanctioned mutation** of audit rows and goes through the same trigger-gated path as retention deletes. Alternative considered: deleting the subject's audit rows outright — rejected, it destroys the evidence that the erasure itself happened.

### D6 — Prompt redaction at the source, levels fixed in the docker profile

Three layers: a) `PromptController` logs `promptLength` + `promptSha256` instead of the body (the hash lets support correlate a user-reported prompt with logs without storing content); b) `application-docker.yaml` gains a `logging.level` block pinning `org.springframework.ai: INFO` and `com.lukk.ascend.ai.agent: INFO` (also fixing the stale `com.lukk.ai.agent` logger name in base `application.yaml`); c) a redaction convention in `docs/COMPLIANCE.md`: user-supplied content (prompts, documents, transcripts, memory text, scraped pages, OCR output) is never a log argument — log lengths, counts, hashes, ids. The Python services are swept against this convention (AscendMemory's REST layer spot-checked clean already; ascend-audio-scribe/ascend-web-hunter/PaddleOCR to verify). DEBUG for AI packages remains available in the local dev profile — redaction is a posture of the shipped profiles, not a removal of debuggability.

### D7 — Retention as an in-app scheduled job, not a cron container

Spring `@Scheduled` job (daily, off-peak, `SHEDLOCK`-free: single-instance deployment today, lock noted as a scale-out follow-up) deletes `chat_history` and `user_instructions` rows older than `app.retention.chat-history` (default `180d`) and audit rows older than `app.retention.audit-log` (default `730d`), batched deletes to bound lock time. Rationale: the agent already owns the schema and Liquibase; a separate cron container would duplicate datasource config for one query. Retention values are `@ConfigurationProperties`-bound and documented in the retention matrix in `docs/COMPLIANCE.md` alongside the already-bounded Redis/Loki/Prometheus/Tempo windows.

### D8 — Audit query API shape

`GET /api/v1/audit?actor=&action=&outcome=&from=&to=&page=&size=` — ADMIN only (role from `add-auth-and-identity`), default sort `occurred_at DESC`, page size capped at 200, returns a standard page envelope. Filters map 1:1 to the indexed columns; no free-text search over `details` (that is what Grafana/Loki is for operationally; the API is the compliance surface).

## Risks / Trade-offs

- [Async audit writes can drop events on crash] → acceptable for request-path events (metric + alert on `audit.write.failed`); erasure lifecycle events write synchronously, so the legally significant records are not exposed to this window.
- [Erasure completeness depends on tenant-isolation's ownership metadata] → until `add-tenant-isolation` lands, MinIO objects and Qdrant points are not user-attributed; the erasure spec requires per-user deletion of *attributed* data and the tenant-wide job covers shared/legacy data. Sequencing: this change's erasure implementation tasks land after tenant isolation's attribution tasks.
- [Prompt SHA-256 of low-entropy prompts is guessable] → the hash is a correlation id, not a secrecy mechanism; a short prompt's hash confirms a guess an attacker already has. Documented as such; no salting (salting would break the correlate-user-report-to-log use case).
- [Retention delete vs. append-only trigger conflict] → the trigger's retention escape hatch (session-scoped config) is a sharp edge; covered by a dedicated integration test proving ad-hoc DELETEs fail and the retention path succeeds.
- [Usage-ledger coordination] → if `add-usage-metering-and-quotas` renames its tables, our erasure step must follow; mitigated by referencing its spec capability in the erasure task and an integration test that fails if a known per-user table is missed (test enumerates user-keyed tables via `information_schema`).
- [Pepper loss makes pseudonyms permanently irreversible] → acceptable (privacy-safe failure mode); pepper handling documented with the platform's existing secret conventions.

## Migration Plan

1. Liquibase changelog adds `audit_log` + trigger + `erasure_job` — additive, no existing-table changes, safe to roll forward on boot.
2. Redaction (controller line + logging levels) ships first and independently — it is the highest-severity leak and has no dependencies.
3. Audit recorder + instrumented events ship next (auth-rejection event wiring activates once `add-auth-and-identity` merges; the recorder API is stable before then).
4. Erasure endpoints + orchestrator ship last, after tenant-isolation attribution is available.
5. Rollback: all additive — dropping the scheduled job and endpoints reverts behavior; Liquibase rollback blocks provided for both tables.

## Open Questions

- Does the tenant-wide erasure trigger (customer offboarding) need an API endpoint at all, or is an admin-invoked job enough for v1? Current lean: ADMIN-only `DELETE /api/v1/tenants/{tenantId}/data`, same job machinery — confirm when `add-tenant-isolation` fixes the tenant model.
- Should `CHAT_PROMPT` audit events be sampled under sustained load? Current lean: no — one row per request is small (~200 bytes) and 730d retention bounds it; revisit if volume proves otherwise.
