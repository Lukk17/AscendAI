## Why

The only ways to get a document into the RAG knowledge base today are hand-driven: a multipart upload to `POST /api/v1/ingestion/upload` (`apps/ascend-ai-agent/src/main/java/com/lukk/ascend/ai/agent/controller/IngestionController.java`), or dropping files into the MinIO knowledge-base bucket out-of-band and calling `POST /api/v1/ingestion/run`, which scans the bucket with ETag dedupe (`service/ingestion/ManualIngestionService.java`). A Spring Integration S3 poller exists but is off by default (`config/IngestionPipelineConfig.java`, `app.ingestion.auto.enabled=false` in `application.yaml`). For a company, that model does not survive contact with reality: corporate policies, handbooks, and procedures live in SharePoint and OneDrive, they change weekly, and nobody is going to re-upload them by hand. Without automated sync the knowledge base silently goes stale, the worst failure mode for a RAG product, because answers keep coming but stop being true.

Those documents are not uniformly readable by the company that owns them, and this version does not fix that. `docs/architecture/permission-aware-retrieval.md` and ADR-M004 through ADR-M009 settle how it is fixed: every chunk carries the list of group principals permitted to read it, and the search filters on that list. Two sibling changes own the reading side. Capturing that list from the source was this change's half, and it is deferred, because `add-auth-and-identity` mints principals only from Keycloak realm groups and a SharePoint permission entry names an Entra ID directory object id that no principal in this version can equal. A captured list would match nobody, for everybody, and under deny-by-default every synced document would be invisible to the whole company.

So a document a connector syncs is readable by everyone in the company that owns it, carrying the `tenant:everyone:{tenantId}` grant the ingestion producer already stamps. That is a product fact stated to the customer rather than a caveat, and it is the same statement `add-auth-and-identity` makes as a named limitation on its side. The capture design is preserved whole in this change's design document and in its decision records, because retrofitting it later still means reprocessing an already-embedded corpus and the analysis is the expensive part.

This change adds a connector framework for automated document sync from corporate sources into the existing ingestion pipeline, plus the first concrete connector: SharePoint/OneDrive via Microsoft Graph, which is where EU corporate documents actually live.

## What Changes

- Connector framework (provider-agnostic):
  - Connector configurations persisted per tenant via Liquibase: connector type, display name, credentials reference, source scope (site/drive/folder), sync schedule, maximum sync age, enabled flag.
  - Scheduled incremental sync jobs per enabled connector, plus an on-demand trigger.
  - Sync-run history: one record per run with status, timing, and per-file outcomes (added / updated / deleted / skipped / failed with reason).
  - Connector CRUD REST API under `/api/v1/connectors` (ADMIN role): create, list, get, update, disable, delete, trigger-sync-now, and get sync history.
  - Explicit design principle: a connector's only job is to land bytes and trigger the existing ingestion pipeline. All parsing stays in the existing `DocumentRouter` path (markdown parser, Docling, ascend-ocr, Unstructured). No parallel parse path, and no write to the vector store from a connector by any route.
- Company-wide visibility for synced documents:
  - Every chunk of a connector-landed document carries `acl` of `["tenant:everyone:{tenantId}"]` with `acl_source` of `tenant-default`, stamped by the ingestion producer default that `add-tenant-isolation` owns. The connector composes no access list itself, so there is exactly one producer of that principal in the system.
  - Per-document permissions captured from the source are deferred whole, with their design, their decision records, and their failure analysis preserved.
- Administrator authorization on the connector endpoints:
  - A filter-chain rule requiring `ADMIN` on `/api/v1/connectors/**`. `add-auth-and-identity` leaves every path its matrix does not name at merely authenticated, and the administrative-prefix rule it used to carry was removed along with the identity-link endpoints, so this change carries its own.
- Sync freshness:
  - A scheduled check that marks a connector stale when it has not completed a successful sync within its configured maximum sync age, surfaced on the connector read and list endpoints and as a per-connector gauge. It writes no document and does not call the source, so a connector that has quietly stopped is visible without a corpus going dark.
  - The framework rejects a configuration whose maximum sync age is not greater than the interval its cron schedule fires on, because a healthy connector must never mark itself stale.
- SharePoint/OneDrive connector (Microsoft Graph):
  - Per-tenant app-registration (client-credentials) authentication against Microsoft Entra ID.
  - Incremental change detection via Graph delta queries: new, modified, and deleted files per sync, with delta-token persistence between runs.
  - Application permissions covering content only: a site/file read grant (`Sites.Read.All`, or `Sites.Selected` per site). No directory group read grant is requested, because nothing in this version resolves a group identity, and asking a customer to consent to directory enumeration we cannot use would be an unearned permission.
  - Scoping to selected sites, drives, and folders.
  - File-type filter aligned with the existing upload allowlist (`app.ingestion.upload.allowed-mime-types`: pdf, docx, pptx, markdown, plain text, images) and a per-file size limit.
  - Throttling compliance per Graph API guidance: honour `Retry-After` on 429/503, exponential backoff, bounded retries, with one throttle budget per run.
- Deletion propagation: a file removed at the source is removed from MinIO and its chunks removed from Qdrant on the next sync, reusing the single-document deletion machinery owned by the sibling `add-document-management-api` change.
- Credentials encrypted at rest: connector credentials (client secrets) are stored using the same encryption mechanism family as BYOK keys in the sibling `add-usage-metering-and-quotas` change, coordinated there, not re-specified here.

Follow-on connectors (Google Drive, Confluence, network share) are explicit non-goals; the framework interfaces make them additive.

## Capabilities

### New Capabilities

- `document-connectors`: provider-agnostic connector framework: persisted per-tenant connector configuration, scheduled and on-demand incremental sync, the company-wide visibility rule for connector-landed documents, sync-run history with per-file outcomes, the sync freshness check and its configuration invariant, deletion propagation into MinIO and Qdrant, an ADMIN-only CRUD API with its filter-chain authorization rule, encrypted credential storage, and the connector to MinIO to existing-pipeline landing contract.
- `sharepoint-connector`: SharePoint/OneDrive sync via Microsoft Graph: client-credentials auth per tenant, delta-query incremental change detection with persisted delta tokens, the content application permission grants a sync actually requires, site/drive/folder scoping, file-type and size filtering aligned with the upload allowlist, and 429/503 throttling compliance with a bounded per-run budget.

### Modified Capabilities

(none. Reviewed `ingestion-correctness`, `ingestion-security`, and `document-ingestion-docling`; this change is additive. Connector-fetched files reuse the existing sanitization, MIME-allowlist, and ETag-dedup behavior those specs already require, and the access list on their chunks is the tenant-everyone default that `add-tenant-isolation` already stamps for a document with no source-captured list. The requirements that connectors honour all of that live in the new capabilities, and the existing upload-path requirements are unchanged.)

## Impact

- ascend-ai-agent (new code): `service/connector/` package (framework interfaces, sync orchestrator, scheduler, freshness check), `service/connector/sharepoint/` (Graph client, delta sync), `controller/ConnectorController.java`, JPA entities + repositories for connector config, sync runs, per-file outcomes, and delta cursors; new Liquibase changelog under `src/main/resources/db/changelog/`; `@ConfigurationProperties` for connector defaults in `application.yaml`; one filter-chain rule added to `SecurityConfig`.
- Reused unchanged: MinIO landing via `StorageService`, the bucket scan (`ManualIngestionService`) and its ETag deduplication marker format, the `DocumentRouter` parse path, the MIME allowlist and filename sanitization from `ingestion-security`, and the access-list stamp from `add-tenant-isolation`.
- Dependencies (sibling changes): `add-auth-and-identity` (the ADMIN role that guards the API and the authenticated principal recorded on mutations), `add-tenant-isolation` (documents land under the tenant prefix and carry tenant metadata; the four access-list metadata keys, the `tenant:everyone:{tenantId}` pseudo-group and the producer default that stamps it), `add-document-management-api` (document metadata/status model and the single-document deletion path), `add-usage-metering-and-quotas` (encryption-at-rest mechanism for stored credentials).
- External: outbound HTTPS to Microsoft Graph (`graph.microsoft.com`); customer-side Azure app registration with content application permissions only (documented in a new `docs/CONNECTORS.md`).
- Docs: new `docs/CONNECTORS.md` setup guide including the Azure app-registration steps a customer admin must perform and the company-wide visibility statement a customer is told; root `AGENTS.md` and `apps/ascend-ai-agent/AGENTS.md` touch-ups. Decision records for what this change decides beyond ADR-M004 through ADR-M009 live under `decisions/` in this change folder, several of them deferred under the current scope with their analysis intact.
- Tests: unit + integration tests with mocked Graph responses covering add/modify/delete propagation, the company-wide access list on landed chunks, throttling backoff, delta-token invalidation, the freshness check and its configuration invariant, the ADMIN filter-chain rule, and credential-logging hygiene.

## Relevant Skills

- `/springboot-patterns`
- `/java-coding-standards`
- `/jpa-patterns`
- `/database-migrations`
- `/api-design`
- `/springboot-security`
- `/springboot-tdd`
- `/security-review`
