## Build order

Build order (owner build order of 2026-10-04, which supersedes the earlier orders): build group 4 (personal), position 7. This change was split out of `add-document-connectors` on 2026-10-04 to follow that rule: the personal assistant comes first, nothing personal may depend on company work, and company work comes last and only plugs in through extension points with safe defaults. The framework is personal, because the personal assistant's Obsidian vault (`add-obsidian-vault`) is its first connector type. The SharePoint connector and its access list rules stay in `add-document-connectors`, which is company work of build group 5 and plugs into this framework.

It needs `upgrade-spring-boot-4` (Flyway and the RFC 7807 problem detail), `add-keycloak-login` (the `ADMIN` role, the authorization matrix this change adds its row to, the problem code `forbidden` with the 403 writer, and `TenantContext` with `currentTenantId()` and `runAs`), `add-deployment-modules` (`ASCEND_MODULES`, `@ConditionalOnModule` and `module_denied` for a connector type of a switchable module), `add-shared-scheduler` (the shared scheduler, its system tasks and `CronRule`), `add-document-management-api` (the document registry, `IngestionRunService` and the single-document deletion path) and `add-agent-skills` (build group 4, position 1: the shared problem code `unavailable`), which all land earlier. Later changes plug into it: `add-obsidian-vault` (build group 4, position 9) adds the `OBSIDIAN` connector type, `add-web-crawl-rag-connector` (build group 4, position 16) adds the `WEB_CRAWL` type, and `add-document-connectors` (company, build group 5) adds the `SHAREPOINT` type later. It depends on no company change.

## Why

The only ways to get a document into the RAG knowledge base today are hand-driven: a multipart upload to `POST /api/v1/ingestion/upload` (`apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/controller/IngestionController.java`), or dropping files into the object storage knowledge-base bucket out-of-band and calling `POST /api/v1/ingestion/run`, which scans the bucket with ETag dedupe (`service/ingestion/ManualIngestionService.java`). A Spring Integration S3 poller exists but is off by default (`config/IngestionPipelineConfig.java`, `app.ingestion.auto.enabled=false` in `application.yaml`). The owner's notes live in an Obsidian vault and change every day, and nobody is going to re-upload them by hand. Without automated sync the knowledge base silently goes stale, the worst failure mode for a RAG product, because answers keep coming but stop being true.

This change adds a connector framework for automated document sync from a source into the existing ingestion pipeline. It ships no connector type of its own. `add-obsidian-vault` adds the first one, `OBSIDIAN`, and `add-web-crawl-rag-connector` and `add-document-connectors` (SharePoint, company) add theirs.

## What Changes

- Connector configurations persisted per tenant through a Flyway migration: connector type, display name, credentials reference, source scope, sync schedule (a five-field cron and a time zone), maximum sync age, enabled flag. The type column admits `OBSIDIAN` in this migration (the required edit of `add-obsidian-vault`), and each later type admits its value in its own migration.
- A connector type declares whether it needs a credential (`OBSIDIAN` needs none) and whether its schedule comes from the connector's own cron or from a system task of `add-shared-scheduler` (`OBSIDIAN` takes it from `obsidian-vault-rescan`, so it has no cron).
- Scheduled incremental sync per enabled connector on the shared scheduler of `add-shared-scheduler`: one execution `connector-sync/<connectorId>` per connector, created, rescheduled and removed in the same transaction as the connector row. Plus an on-demand trigger, and an `EVENT` trigger for a change a connector notices itself: an `EVENT` or scheduled start during a run queues exactly one follow-up run instead of answering 409.
- A connector may choose the object key segment of a landed file inside the tenant prefix and folder the framework picks, and the framework registers every landed file in the document registry of `add-document-management-api` with the `source_type` (`connector:<name>`), `origin_uri` and connector id the connector supplies. This change adds the column `documents.connector_id` with its index, puts `connector_id` on every chunk through a `ChunkPayloadContributor` of `add-document-management-api`, and creates its Qdrant payload index (owner answer 93 of 2026-10-08, moved here from `add-document-management-api`).
- Sync-run history: one record per run with status, timing, and per-file outcomes (added, updated, deleted, skipped, failed with reason).
- Connector CRUD REST API under `/api/v1/connectors` (`ADMIN` role): create, list, get, update, disable, delete, trigger-sync-now, and get sync history. Every error is an RFC 7807 problem detail with a `code` from `ApiErrorCode` of `upgrade-spring-boot-4`, and this change adds the one code `connector_run_in_progress` (409).
- The `ADMIN` rule is this change's row `/api/v1/connectors/**` in the authorization matrix of `add-keycloak-login` (its D4), which every later change extends with its own rows.
- The tenant of a connector comes from `TenantContext.currentTenantId()` of `add-keycloak-login`, which answers `default` in the personal deployment, and is stored on the row. Every run binds the row's tenant with `TenantContext.runAs(tenantId, action)`, also a run that starts without a request. The tenant prefix of a landed object comes from a `TenantPrefixResolver` port whose default keeps today's key layout, and `add-tenant-isolation` (company, build group 5) registers its `tenant/{tenantId}/` implementation later.
- Connector credentials sit behind a `ConnectorCredentialStore` port with an encrypted store of this change's own as its default (AES-256-GCM, key from `CONNECTOR_CREDENTIALS_KEY`), referenced from connector rows by an opaque handle. It is the agent's one encrypted secret store: `add-usage-metering-and-quotas` (company, build group 5) later stores its BYOK provider keys through the same port and key. This change does not wait for it. Secrets are write-only and never logged.
- The framework is part of the core document search (`rag`), which is always on and is not a module (owner decision of 2026-10-03): its controller, services and scheduled tasks carry no `@ConditionalOnModule` and no tenant module grant guards them. A connector type that needs a switchable module carries that module's `@ConditionalOnModule`, and a sync of such a type for a tenant without that module's grant is skipped with `module_denied`.
- Explicit design principle: a connector's only job is to land bytes and trigger the existing ingestion pipeline. All parsing stays in the `DocumentRouter` path (markdown parser, Docling, ascend-ocr, Unstructured). The bucket scan reaches `DocumentRouter` only because `add-document-management-api` moves `ManualIngestionService` onto it (that change's tasks 3.2a and 3.2b). No parallel parse path, and no write to the vector store from a connector by any route.
- Sync freshness: the system task `connector-freshness-check` of `add-shared-scheduler` marks a connector stale when it has not completed a successful sync within its configured maximum sync age, surfaced on the connector read and list endpoints and as a per-connector gauge. It writes no document and does not call the source. The framework rejects a configuration whose maximum sync age is not greater than the interval its cron schedule fires on.
- Deletion propagation: a file removed at the source is removed from object storage and its chunks removed from Qdrant on the next sync, reusing the single-document deletion machinery of `add-document-management-api`.
- A new `docs/CONNECTORS.md` with one section per connector type, which each type change fills in.

## Capabilities

### New Capabilities

- `document-connectors`: provider-agnostic connector framework: persisted per-tenant connector configuration, scheduled and on-demand incremental sync, the `EVENT` trigger and its one follow-up run, sync-run history with per-file outcomes, the sync freshness check and its configuration invariant, deletion propagation into object storage and Qdrant, an `ADMIN`-only CRUD API with its matrix row, the credential store port with its own encrypted store, and the connector to object storage to existing-pipeline landing contract.

### Modified Capabilities

(none. Reviewed `ingestion-correctness`, `ingestion-security`, and `document-ingestion-docling`. This change is additive. Connector-fetched files reuse the existing sanitization, MIME-allowlist, and ETag-dedup behavior those specs already require.)

## Impact

- ascend-ai-agent (new code): `service/connector/` package (framework interfaces, sync orchestrator, the `connector-sync` task and the `connector-freshness-check` system task on the shared scheduler, `ConnectorCredentialStore` and its encrypted store, `TenantPrefixResolver` with its default), `controller/ConnectorController.java`, Spring Data JDBC entities (`@Table`, `@Id`, never JPA) and `CrudRepository` repositories for connector config, sync runs, per-file outcomes, delta cursors and stored credentials, a new Flyway versioned SQL migration `V<n>__connectors.sql` under `src/main/resources/db/migration/` (`<n>` taken at implementation time), `@ConfigurationProperties` for connector defaults in `application.yaml`, one matrix row added to `SecurityConfig`, and the new environment variable `CONNECTOR_CREDENTIALS_KEY` in `.env.example`.
- Reused unchanged: object storage landing through `StorageService`, the bucket scan started through `IngestionRunService` of `add-document-management-api` and its document registry ETag deduplication, the `DocumentRouter` parse path, and the MIME allowlist and filename sanitization from `ingestion-security`.
- Docs: new `docs/CONNECTORS.md`, root `AGENTS.md` and `apps/ascend-agent/AGENTS.md` touch-ups. The decision record for the freshness check lives under `decisions/` in this change folder.
- Tests: unit and integration tests with a fake connector type covering landing, deletion propagation, scheduling, the follow-up run, the freshness check and its configuration invariant, the `ADMIN` rule, the credential store and credential-logging hygiene. This change carries no end-to-end spec of its own (owner answer 91.3 of 2026-10-08): with no connector type installed the API can only refuse, and every refusal is proven by the MockMvc and security slice tests. The sync, history and freshness specs need a connector type and are written by the type changes (`add-obsidian-vault`, `add-document-connectors`).

## Relevant Skills

- `/springboot-patterns`
- `/java-coding-standards`
- `/api-design`
- `/postgres-patterns`
- `/database-migrations`
- `/security-review`
- `/backend-patterns`
- `/architecture-decision-records`
- `/tdd-workflow`
- `/e2e-runbooks`
