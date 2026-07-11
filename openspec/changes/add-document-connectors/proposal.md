## Why

The only ways to get a document into the RAG knowledge base today are hand-driven: a multipart upload to `POST /api/v1/ingestion/upload` (`AscendAgent/src/main/java/com/lukk/ascend/ai/agent/controller/IngestionController.java`), or dropping files into the MinIO knowledge-base bucket out-of-band and calling `POST /api/v1/ingestion/run`, which scans the bucket with ETag dedupe (`service/ingestion/ManualIngestionService.java`). A Spring Integration S3 poller exists but is off by default (`config/IngestionPipelineConfig.java`, `app.ingestion.auto.enabled=false` in `application.yaml`). For a company, that model does not survive contact with reality: corporate policies, handbooks, and procedures live in SharePoint and OneDrive, they change weekly, and nobody is going to re-upload them by hand. Without automated sync the knowledge base silently goes stale — the worst failure mode for a RAG product, because answers keep coming but stop being true.

This change adds a **connector framework** for automated document sync from corporate sources into the existing ingestion pipeline, plus the first concrete connector: **SharePoint/OneDrive via Microsoft Graph** — which is where EU corporate documents actually live.

## What Changes

- **Connector framework (provider-agnostic):**
  - Connector configurations persisted per tenant via Liquibase: connector type, display name, credentials reference, source scope (site/drive/folder), sync schedule, enabled flag.
  - Scheduled incremental sync jobs per enabled connector, plus on-demand trigger.
  - Sync-run history: one record per run with status, timing, and per-file outcomes (added / updated / deleted / skipped / failed with reason).
  - Connector CRUD REST API under `/api/v1/connectors` (ADMIN role): create, list, get, update, disable, delete, trigger-sync-now, get sync history.
  - Explicit design principle: **a connector's only job is to land bytes in MinIO under the tenant prefix and trigger the existing ingestion pipeline**. All parsing stays in the existing `DocumentRouter` path (markdown parser, Docling, PaddleOCR, Unstructured). No parallel parse path.
- **SharePoint/OneDrive connector (Microsoft Graph):**
  - Per-tenant app-registration (client-credentials) authentication against Microsoft Entra ID.
  - Incremental change detection via Graph **delta queries** — new, modified, and deleted files per sync, with delta-token persistence between runs.
  - Scoping to selected sites, drives, and folders.
  - File-type filter aligned with the existing upload allowlist (`app.ingestion.upload.allowed-mime-types`: pdf, docx, pptx, markdown, plain text, images) and a per-file size limit.
  - Throttling compliance per Graph API guidance: honour `Retry-After` on 429/503, exponential backoff, bounded retries.
- **Deletion propagation:** a file removed at the source is removed from MinIO and its chunks removed from Qdrant on the next sync, reusing the single-document deletion machinery owned by the sibling `add-document-management-api` change.
- **Credentials encrypted at rest:** connector credentials (client secrets) are stored using the same encryption mechanism family as BYOK keys in the sibling `add-usage-metering-and-quotas` change — coordinated there, not re-specified here.

Follow-on connectors (Google Drive, Confluence, network share) are explicit **non-goals**; the framework interfaces make them additive.

## Capabilities

### New Capabilities

- `document-connectors`: provider-agnostic connector framework — persisted per-tenant connector configuration, scheduled and on-demand incremental sync, sync-run history with per-file outcomes, deletion propagation into MinIO and Qdrant, ADMIN-only CRUD API, encrypted credential storage, and the connector → MinIO → existing-pipeline landing contract.
- `sharepoint-connector`: SharePoint/OneDrive sync via Microsoft Graph — client-credentials auth per tenant, delta-query incremental change detection with persisted delta tokens, site/drive/folder scoping, file-type and size filtering aligned with the upload allowlist, and 429/503 throttling compliance.

### Modified Capabilities

(none — reviewed `ingestion-correctness`, `ingestion-security`, and `document-ingestion-docling`; this change is additive. Connector-fetched files reuse the existing sanitization, MIME-allowlist, and ETag-dedup behavior those specs already require; the requirements that connectors honour them live in the new capabilities, and the existing upload-path requirements are unchanged.)

## Impact

- **AscendAgent (new code):** `service/connector/` package (framework interfaces, sync orchestrator, scheduler), `service/connector/sharepoint/` (Graph client, delta sync), `controller/ConnectorController.java`, JPA entities + repositories for connector config, sync runs, per-file outcomes, and delta tokens; new Liquibase changelog under `src/main/resources/db/changelog/`; `@ConfigurationProperties` for connector defaults in `application.yaml`.
- **Reused unchanged:** MinIO landing via `StorageService`, ETag-dedup bucket scan (`ManualIngestionService`), the `DocumentRouter` parse path, and the MIME allowlist / filename sanitization from `ingestion-security`.
- **Dependencies (sibling changes):** `add-auth-and-identity` (ADMIN role guards the API), `add-tenant-isolation` (documents land under the tenant prefix and carry tenant metadata), `add-document-management-api` (document metadata/status model and the single-document deletion path), `add-usage-metering-and-quotas` (encryption-at-rest mechanism for stored credentials).
- **External:** outbound HTTPS to Microsoft Graph (`graph.microsoft.com`); customer-side Azure app registration (documented in a new `docs/CONNECTORS.md`).
- **Docs:** new `docs/CONNECTORS.md` setup guide including the Azure app-registration steps a customer admin must perform; root `AGENTS.md` and `AscendAgent/AGENTS.md` touch-ups.
- **Tests:** unit + integration tests with mocked Graph responses covering add/modify/delete propagation, throttling backoff, and credential-logging hygiene.

## Relevant Skills

- `/springboot-patterns`
- `/java-coding-standards`
- `/jpa-patterns`
- `/database-migrations`
- `/api-design`
- `/springboot-security`
- `/springboot-tdd`
