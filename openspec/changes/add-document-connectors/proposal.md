## Why

The only ways to get a document into the RAG knowledge base today are hand-driven: a multipart upload to `POST /api/v1/ingestion/upload` (`AscendAgent/src/main/java/com/lukk/ascend/ai/agent/controller/IngestionController.java`), or dropping files into the MinIO knowledge-base bucket out-of-band and calling `POST /api/v1/ingestion/run`, which scans the bucket with ETag dedupe (`service/ingestion/ManualIngestionService.java`). A Spring Integration S3 poller exists but is off by default (`config/IngestionPipelineConfig.java`, `app.ingestion.auto.enabled=false` in `application.yaml`). For a company, that model does not survive contact with reality: corporate policies, handbooks, and procedures live in SharePoint and OneDrive, they change weekly, and nobody is going to re-upload them by hand. Without automated sync the knowledge base silently goes stale, the worst failure mode for a RAG product, because answers keep coming but stop being true.

Those documents are not uniformly readable by the company that owns them. SharePoint enforces an access list on every file open, and the moment the bytes are chunked and embedded that enforcement is gone unless something rebuilds it. `docs/architecture/permission-aware-retrieval.md` and ADR-M004 through ADR-M009 settle how it is rebuilt: every chunk carries the list of group principals permitted to read it, and the search filters on that list. Two sibling changes own the reading side. This change owns the capture side, and it owns it from the first sync a connector ever performs, because attaching an access list to documents that are already chunked and embedded means reprocessing the whole corpus. There is no version of this that is cheaper to retrofit than to build correctly now, while nothing exists yet.

This change adds a **connector framework** for automated document sync from corporate sources into the existing ingestion pipeline, with per-document access-list capture as part of the landing contract, plus the first concrete connector: **SharePoint/OneDrive via Microsoft Graph**, which is where EU corporate documents actually live.

## What Changes

- **Connector framework (provider-agnostic):**
  - Connector configurations persisted per tenant via Liquibase: connector type, display name, credentials reference, source scope (site/drive/folder), sync schedule, permission confirmation interval, access-list maximum age, enabled flag.
  - Scheduled incremental sync jobs per enabled connector, plus on-demand trigger in either a full mode or a permissions-only mode.
  - Sync-run history: one record per run with status, timing, and per-file outcomes (added / updated / permissions-updated / deleted / skipped / failed with reason).
  - Connector CRUD REST API under `/api/v1/connectors` (ADMIN role): create, list, get, update, disable, delete, trigger-sync-now, and get sync history.
  - Explicit design principle: **a connector's only job is to land bytes plus a per-item access list, and trigger the existing ingestion pipeline**. All parsing stays in the existing `DocumentRouter` path (markdown parser, Docling, PaddleOCR, Unstructured). No parallel parse path.
- **Per-document access-list capture:**
  - Every in-scope item's effective permitted principals are read from the source and carried through to the `acl`, `acl_source`, `acl_version`, and `acl_synced_at` chunk metadata keys that `add-tenant-isolation` defines.
  - Permissions are read from the source rather than inferred from the content change feed, because sources are inconsistent about reporting permission edits at all and about reporting a change made higher in a folder tree.
  - Capture is container-first: folder permissions are read once and applied to inheriting items, with a per-item read only where an item carries permissions of its own or its confirmation is due, so a first full enumeration does not cost one throttled call per document.
  - An access list longer than the 64-principal cap is a capture failure that leaves the document unindexed, never a truncation, because a truncated allow list silently denies people and is indistinguishable from a retrieval bug.
  - A capture failure fails the item. Bytes are never landed and indexed without a list, since under the deny-by-default rule that produces storage cost and no retrievability.
- **Permission-only change detection:**
  - The ingestion deduplication key becomes the pair of content version and access-list version, so a sharing change on an unchanged file is no longer deduplicated away.
  - A four-way sync branch on those two versions, whose permission-only path performs a payload-only update on the existing points rather than a re-parse and re-embed, so a revocation takes seconds rather than an hour.
  - A `PERMISSIONS_UPDATED` per-file outcome, and a permission confirmation timestamp on the sync cursor that advances independently of the content cursor.
  - A carve-out to the framework's no-direct-vector-store-writes rule, scoped to setting exactly the four access-list keys on points that already exist.
- **Staleness controls:**
  - A scheduled sweep that empties access lists older than a configured maximum age, so a silent capture outage becomes visible degradation rather than a corpus that keeps answering from permissions that stopped being true.
  - An administrator-triggered immediate resync in permissions-only mode, so a deliberate revocation does not have to wait for a schedule.
- **SharePoint/OneDrive connector (Microsoft Graph):**
  - Per-tenant app-registration (client-credentials) authentication against Microsoft Entra ID.
  - Incremental change detection via Graph **delta queries**: new, modified, and deleted files per sync, with delta-token persistence between runs.
  - Item and folder permission reads mapped to `entra:group:<directory object id>` principals, with an unmappable entry failing capture for that item.
  - Application permissions wide enough to read sharing: a site/file content grant covers the `driveItem` permissions collection, and a directory group read grant is additionally required to resolve a permission entry's group identity.
  - Scoping to selected sites, drives, and folders.
  - File-type filter aligned with the existing upload allowlist (`app.ingestion.upload.allowed-mime-types`: pdf, docx, pptx, markdown, plain text, images) and a per-file size limit.
  - Throttling compliance per Graph API guidance: honour `Retry-After` on 429/503, exponential backoff, bounded retries, with separate content and permission budgets per run.
- **Deletion propagation:** a file removed at the source is removed from MinIO and its chunks removed from Qdrant on the next sync, reusing the single-document deletion machinery owned by the sibling `add-document-management-api` change.
- **Credentials encrypted at rest:** connector credentials (client secrets) are stored using the same encryption mechanism family as BYOK keys in the sibling `add-usage-metering-and-quotas` change, coordinated there, not re-specified here.

Follow-on connectors (Google Drive, Confluence, network share) are explicit **non-goals**; the framework interfaces make them additive. Design decision D17 records why Google Drive would in fact be the cheaper connector to make permission-correct, and why SharePoint still goes first.

## Capabilities

### New Capabilities

- `document-connectors`: provider-agnostic connector framework: persisted per-tenant connector configuration, scheduled and on-demand incremental sync, per-item access-list capture with container-level inheritance, a deduplication key pairing content version with access-list version, the four-way sync branch and its payload-only permission update path, the `PERMISSIONS_UPDATED` outcome and permission confirmation cursor state, the access-list cap as a capture failure, the staleness sweep, sync-run history with per-file outcomes, deletion propagation into MinIO and Qdrant, ADMIN-only CRUD API, encrypted credential storage, and the connector → MinIO plus access list → existing-pipeline landing contract.
- `sharepoint-connector`: SharePoint/OneDrive sync via Microsoft Graph: client-credentials auth per tenant, delta-query incremental change detection with persisted delta tokens, container-first item and folder permission reads mapped to Entra group principals, the application permission grants that reading sharing actually requires, site/drive/folder scoping, file-type and size filtering aligned with the upload allowlist, and 429/503 throttling compliance with separate content and permission budgets.

### Modified Capabilities

(none. Reviewed `ingestion-correctness`, `ingestion-security`, and `document-ingestion-docling`; this change is additive. Connector-fetched files reuse the existing sanitization, MIME-allowlist, and ETag-dedup behavior those specs already require; the requirements that connectors honour them live in the new capabilities, and the existing upload-path requirements are unchanged. The deduplication key extension in this change applies to connector-landed objects and does not alter the marker format for objects landed by the manual upload paths.)

## Impact

- **AscendAgent (new code):** `service/connector/` package (framework interfaces, sync orchestrator, scheduler, staleness sweep), `service/connector/acl/` (access-list value type, version hashing, capture abstraction, payload-only update via the native Qdrant client), `service/connector/sharepoint/` (Graph client, delta sync, permission reads, principal mapping), `controller/ConnectorController.java`, JPA entities + repositories for connector config, sync runs, per-file outcomes, delta and permission cursors, and per-item access-list records; new Liquibase changelog under `src/main/resources/db/changelog/`; `@ConfigurationProperties` for connector defaults in `application.yaml`.
- **Reused unchanged:** MinIO landing via `StorageService`, the bucket scan (`ManualIngestionService`), the `DocumentRouter` parse path, and the MIME allowlist / filename sanitization from `ingestion-security`. The deduplication marker gains an access-list-version segment for connector-landed objects.
- **New dependency use, not a new dependency:** the native Qdrant client already declared as `libs.qdrant.client` in `AscendAgent/build.gradle.kts` is used for `setPayload`, which Spring AI's `VectorStore` abstraction cannot express.
- **Dependencies (sibling changes):** `add-auth-and-identity` (ADMIN role guards the API; the principal format, its typed factory, and the `oid` directory identifier that permission entries map onto), `add-tenant-isolation` (documents land under the tenant prefix and carry tenant metadata; the four access-list metadata keys, the keyword payload index on `acl`, the `tenant:everyone:{tenantId}` pseudo-group, and the search-side filter that reads them), `add-document-management-api` (document metadata/status model and the single-document deletion path), `add-usage-metering-and-quotas` (encryption-at-rest mechanism for stored credentials).
- **External:** outbound HTTPS to Microsoft Graph (`graph.microsoft.com`); customer-side Azure app registration with both content and directory application permissions (documented in a new `docs/CONNECTORS.md`).
- **Docs:** new `docs/CONNECTORS.md` setup guide including the Azure app-registration steps a customer admin must perform and the staleness numbers a customer is told; root `AGENTS.md` and `AscendAgent/AGENTS.md` touch-ups. Decision records for what this change decides beyond ADR-M004 through ADR-M009 live under `decisions/` in this change folder.
- **Tests:** unit + integration tests with mocked Graph responses covering add/modify/delete propagation, permission-only change detection, container inheritance fan-out, cap failure, the staleness sweep, throttling backoff, and credential-logging hygiene.

## Relevant Skills

- `/springboot-patterns`
- `/java-coding-standards`
- `/jpa-patterns`
- `/database-migrations`
- `/api-design`
- `/springboot-security`
- `/springboot-tdd`
- `/security-review`
