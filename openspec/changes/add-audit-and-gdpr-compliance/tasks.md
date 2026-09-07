## 1. Log redaction (ships first — no dependencies)

- [ ] 1.1 In `apps/ascend-ai-agent/src/main/java/com/lukk/ascend/ai/agent/controller/PromptController.java` (lines 90-97), replace the `Prompt: {}` argument with `PromptLength: {}` and `PromptSha256: {}` (SHA-256 hex of the prompt body); extract the digest helper to `util/`
- [ ] 1.2 In `apps/ascend-ai-agent/src/main/resources/application.yaml` `logging.level`, replace the stale `com.lukk.ai.agent: DEBUG` entry with `com.lukk.ascend.ai.agent: DEBUG` (dev posture keeps DEBUG)
- [ ] 1.3 Add a `logging.level` block to `apps/ascend-ai-agent/src/main/resources/application-docker.yaml` pinning `org.springframework.ai: INFO` and `com.lukk.ascend.ai.agent: INFO`
- [ ] 1.4 Sweep ascend-ai-agent service classes (`AscendChatService`, RAG, ingestion, memory packages) for log statements that pass prompt/document/memory content as arguments; convert offenders to length/count/hash form
- [ ] 1.5 Sweep the four Python services (ascend-audio-scribe, ascend-web-hunter, AscendMemory, ascend-ocr) for log statements emitting transcript, scraped-page, memory-text, or OCR content; fix any leakage found and note the clean files in the PR description
- [ ] 1.6 Test (`PromptControllerLogRedactionTest`): capture logs via a ListAppender while calling the endpoint with a marker prompt; assert the marker string is absent and length + digest are present
- [ ] 1.7 Test: with the `docker` profile active, assert the effective level for `org.springframework.ai` is INFO (LoggerContext inspection)

## 2. Audit schema and recorder

- [ ] 2.1 Add Liquibase changelog `02-audit-and-erasure.xml` under `apps/ascend-ai-agent/src/main/resources/db/changelog/` creating `audit_log` per design D3 (columns, indexes on `occurred_at`, `(actor, occurred_at)`, `(action, occurred_at)`) with rollback block; register it in `db.changelog-master.yaml`
- [ ] 2.2 In the same changelog, create the append-only trigger rejecting UPDATE/DELETE on `audit_log`, with the session-config escape hatch for the retention path and the pseudonymization rewrite (design D2/D5)
- [ ] 2.3 Create `model/AuditEntry.java`, `repository/AuditLogRepository.java` (insert + filtered page query), and the closed `AuditAction` enum with the eleven actions from the spec
- [ ] 2.4 Create `service/audit/AuditRecorder.java` publishing a Spring application event, and `service/audit/AuditEventListener.java` (`@Async`) persisting it; on persistence failure log ERROR and increment Micrometer counter `audit.write.failed`; add a synchronous `recordNow(...)` path for erasure-lifecycle events
- [ ] 2.5 Test (`AuditLogAppendOnlyIT`, Testcontainers Postgres): plain UPDATE and DELETE fail with the trigger error; retention-path delete of an old row succeeds
- [ ] 2.6 Test (`AuditRecorderTest`): listener failure does not propagate to the publisher and `audit_write_failed_total` increments

## 3. Audit instrumentation of actions

- [ ] 3.1 Emit `CHAT_PROMPT` from the prompt flow with `details` = prompt length + SHA-256 (reuse the 1.1 digest helper), actor from the authenticated principal (`add-auth-and-identity`), source IP from the request
- [ ] 3.2 Emit `DOCUMENT_UPLOADED` and `INGESTION_RUN` from `controller/IngestionController.java` (both success and rejection outcomes — 415/413 rejections audit with `outcome = DENIED`)
- [ ] 3.3 Emit `DOCUMENT_PRESIGN_ISSUED` from `service/rag/S3PresignedUrlService.java` with object keys in `details`
- [ ] 3.4 Emit `MEMORY_WIPED` where `SemanticMemoryClient.wipeUserMemory` is invoked outside an erasure job
- [ ] 3.5 Emit `AUTH_TOKEN_REJECTED` from the resource-server rejection hook once `add-auth-and-identity` lands (wire an `AuthenticationFailureEvent` / `BearerTokenAuthenticationEntryPoint` listener); until then leave the listener registered but inert behind the dev profile
- [ ] 3.6 Expose the `AuditRecorder` contract for `QUOTA_REJECTED` and coordinate with `add-usage-metering-and-quotas` so its enforcement path emits through it (task reference in that change, no quota logic here)
- [ ] 3.7 Test (`AuditInstrumentationIT`): one chat request, one upload, one presign, one memory wipe → exactly one audit row each with correct action, actor, and outcome; the chat row's `details` lack the prompt body

## 4. Audit query API

- [ ] 4.1 Create `controller/AuditController.java`: `GET /api/v1/audit` with `actor`, `action`, `outcome`, `from`, `to`, `page`, `size` (cap 200), sorted `occurred_at DESC`, page envelope consistent with existing DTO conventions
- [ ] 4.2 Restrict the endpoint to ADMIN in the security configuration from `add-auth-and-identity`
- [ ] 4.3 Test (`AuditControllerIT`): filter combinations return matching rows; size above cap is clamped; non-admin gets 403
- [ ] 4.4 Add Bruno requests for the audit query under `docs/api/request/AscendAI/`

## 5. Erasure job machinery

- [ ] 5.1 Extend changelog `02-audit-and-erasure.xml` with `erasure_job` per design D4 (UUID id, subject type/id, requested_by, overall + per-store status and counts, timestamps, failure detail) with rollback
- [ ] 5.2 Create `model/ErasureJob.java`, `repository/ErasureJobRepository.java`, and `service/erasure/ErasureOrchestrator.java` walking the fixed store order with idempotent delete-if-exists steps and per-store outcome recording; failures mark the job `PARTIAL`, jobs are re-runnable
- [ ] 5.3 Implement the store steps: Postgres per-user (`chat_history`, `user_instructions`, the subject's `conversations` rows per `add-chat-streaming-and-conversations`, usage-ledger rows per `add-usage-metering-and-quotas` schema), Redis `chat:` keys for the subject's conversations, MinIO `knowledge-base` objects by ownership metadata (`add-tenant-isolation`), Qdrant points in `ascendai-768` + `ascendai-1536` by ownership filter, AscendMemory `wipeUserMemory` looped over every configured embedding provider. For per-tenant erasure add the tenant-shared tables: `documents` / `document_index_state` / `ingestion_runs` (`add-document-management-api`) and connector config / sync-run / delta-token rows (`add-document-connectors`). A store step whose sibling change is not yet implemented is a no-op guard
- [ ] 5.3a Centralize the covered-store inventory in one `StoreWalker` component so erasure and the export job (data-portability) enumerate the identical store set
- [ ] 5.4 Implement audit pseudonymization (design D5): rewrite `actor` / matching `resource_id` in the subject's audit rows to `pseudo:` + truncated HMAC-SHA256 keyed by `app.audit.pseudonym-pepper` (env-injected secret), through the trigger's sanctioned path
- [ ] 5.5 Record `ERASURE_REQUESTED` / `ERASURE_COMPLETED` synchronously with per-store counts in `details`

## 6. Erasure API

- [ ] 6.1 Create `controller/UserDataController.java`: `DELETE /api/v1/users/{userId}/data` → 202 + job id; `GET /api/v1/users/{userId}/data/erasure/{jobId}` → status with per-store outcomes and counts; authorization self-or-ADMIN
- [ ] 6.2 Add `DELETE /api/v1/tenants/{tenantId}/data` (ADMIN only) on the same machinery, including tenant-shared data, once `add-tenant-isolation` fixes tenant attribution
- [ ] 6.3 Test (`ErasureAuthorizationIT`): self allowed, ADMIN allowed, other user 403 with no job row created
- [ ] 6.4 Add Bruno requests for erasure start + status polling

## 7. Erasure integration test — zero residue

- [ ] 7.1 Build `ErasureZeroResidueIT` (Testcontainers: Postgres, Redis, Qdrant, MinIO; WireMock for AscendMemory): seed a user with chat history, instructions, usage rows, Redis keys, MinIO objects, and Qdrant points in both collections; run the job; assert every store empty for the subject per the `data-erasure` spec scenario
- [ ] 7.2 Extend it with a schema-drift guard: enumerate user-keyed tables via `information_schema` and fail if a table with a user-id column is not covered by an erasure step; additionally assert the tenant-keyed tables (`documents`, `document_index_state`, `ingestion_runs`, connector tables) are covered by the per-tenant erasure path, since those carry no user-id column and the user-column heuristic alone would miss them (design risk: registry / connector coordination)
- [ ] 7.3 Test the `PARTIAL` path: force the MinIO step to fail, assert per-store statuses, then re-run and assert `COMPLETED` with idempotent steps
- [ ] 7.4 Test pseudonymization: pre-seed audit rows for the subject, run erasure, assert rows survive with `pseudo:` actors and the raw user id absent from `audit_log`

## 8. Retention job

- [ ] 8.1 Add `config/properties/RetentionProperties.java` binding `app.retention.chat-history` (default `180d`) and `app.retention.audit-log` (default `730d`); wire defaults into `application.yaml`
- [ ] 8.2 Implement the daily `@Scheduled` retention job with batched deletes for `chat_history`, `user_instructions`, and (via the sanctioned trigger path) `audit_log`; per-run summary log and Micrometer deleted-rows counter
- [ ] 8.2a Make the retention job replica-safe: guard the scheduled tick with a single-owner lock (Postgres advisory lock or ShedLock) so it executes once per window across multiple agent instances; test that two concurrent invocations perform the delete only once
- [ ] 8.3 Update the `app.memory.chat-history` comment in `application.yaml` to point at `app.retention.chat-history` (MODIFIED `chat-history-persistence` requirement)
- [ ] 8.4 Test (`RetentionJobIT`): seed rows straddling both windows; assert only expired rows deleted per table and the audit/chat windows act independently

## 8b. Data export / portability

- [ ] 8b.1 Extend the erasure changelog with an `export_job` table (UUID id, subject type/id, requested_by, status, archive location/handle, timestamps) with rollback
- [ ] 8b.2 Create `service/export/ExportOrchestrator.java` walking the shared `StoreWalker` inventory (task 5.3a) read-side: dump `chat_history` + `conversations` + `user_instructions` + usage rows, fetch MinIO objects, pull AscendMemory memories per provider, assemble a single archive plus a JSON manifest
- [ ] 8b.3 Create export endpoints on `UserDataController`: `POST /api/v1/users/{userId}/data/export` (self or ADMIN) and `POST /api/v1/tenants/{tenantId}/data/export` (ADMIN) → 202 + job id; status/download endpoint; bounded retention + cleanup of produced archives
- [ ] 8b.4 Record `EXPORT_REQUESTED` / `EXPORT_COMPLETED` audit events
- [ ] 8b.5 Test (`DataExportIT`, Testcontainers): seed a subject across all stores, run export, assert the archive manifest lists every store and contains the MinIO document bytes; assert the export and erasure store-walkers enumerate the identical store set
- [ ] 8b.6 Add Bruno requests for export start + status/download

## 9. Documentation and verification

- [ ] 9.1 Author `docs/COMPLIANCE.md`: audited action catalogue, how to serve an Article 17 erasure request and an Article 20 export request end-to-end (API calls + expected evidence), what survives erasure and why (pseudonymized audit rows), the log-redaction convention with allowed/forbidden examples for all six services, and the full retention matrix (Postgres chat 180d, audit 730d, Redis TTL, Loki 168h, Prometheus 72h, Tempo 168h, export-archive window, erasure-bounded stores)
- [ ] 9.2 Link `docs/COMPLIANCE.md` from the root `README.md` documentation map and note the audit/erasure endpoints in `apps/ascend-ai-agent/AGENTS.md`
- [ ] 9.3 Run `./gradlew test integrationTest` for ascend-ai-agent and `pytest` for each swept Python service; all green
- [ ] 9.4 Manual verification against the live stack: one chat request → audit row queryable via `GET /api/v1/audit`; prompt body absent from `docker logs` and Loki; erasure of a seeded test user leaves zero residue (spot-check MinIO console, Qdrant collections, Redis keys, Postgres)
- [ ] 9.5 Update `openspec/changes/add-audit-and-gdpr-compliance/tasks.md` checkboxes as work proceeds
