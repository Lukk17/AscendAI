## Build order

Build order (owner build order of 2026-10-04, which supersedes the earlier orders): build group 5 (company), position 7. On 2026-10-04 the connector framework moved out of this change into the personal change `add-connector-framework` (build group 4), because the owner rule of that day says the personal assistant comes first, nothing personal may depend on company work, and company work comes last and only plugs in through extension points with safe defaults. This change keeps SharePoint, its access list rules and the deferred permission capture design, and plugs into the framework as one more connector type.

It needs `upgrade-spring-boot-4` (Flyway, build group 3), `add-document-management-api` (the document registry and the single-document deletion path the framework calls, build group 3), `add-connector-framework` (the framework, the landing contract, scheduling, run history, the freshness check, the API with its `ADMIN` row and `ConnectorCredentialStore`, build group 4), `add-auth-and-identity` (the test tenants) and `add-tenant-isolation` (the tenant prefix and the access-list stamp), all earlier. `add-customer-stack-installer` and `update-docs-and-architecture` come after it. The company order of 2026-10-01 is superseded by the owner build order of 2026-10-04.

## Why

For a company, hand-driven ingestion does not survive contact with reality: corporate policies, handbooks, and procedures live in SharePoint and OneDrive, they change weekly, and nobody is going to re-upload them by hand. Without automated sync the knowledge base silently goes stale, the worst failure mode for a RAG product, because answers keep coming but stop being true. `add-connector-framework` gives the agent automated sync. This change gives it the source a company actually uses.

Those documents are not uniformly readable by the company that owns them, and this version does not fix that. `docs/architecture/permission-aware-retrieval.md` and ADR-M004 through ADR-M009 settle how it is fixed: every chunk carries the list of group principals permitted to read it, and the search filters on that list. Two sibling changes own the reading side. Capturing that list from the source was this change's half, and it is deferred, because `add-auth-and-identity` mints principals only from Keycloak realm groups and a SharePoint permission entry names an Entra ID directory object id that no principal in this version can equal. A captured list would match nobody, for everybody, and under deny-by-default every synced document would be invisible to the whole company.

So a document a connector syncs is readable by everyone in the company that owns it, carrying the `tenant:everyone:{tenantId}` grant the ingestion producer already stamps. That is a product fact stated to the customer rather than a caveat, and it is the same statement `add-auth-and-identity` makes as a named limitation on its side. The capture design is preserved whole in this change's design document and in its decision records, because retrofitting it later still means reprocessing an already-embedded corpus and the analysis is the expensive part.

## What Changes

- A new connector type `SHAREPOINT` on the framework of `add-connector-framework`, admitted by this change's own Flyway migration that extends the framework's type check constraint. It needs a credential and takes its schedule from the connector's own cron.
- SharePoint and OneDrive connector (Microsoft Graph):
  - Per-tenant app-registration (client-credentials) authentication against Microsoft Entra ID, with the tenant id, client id and client secret stored through the framework's `ConnectorCredentialStore`.
  - Incremental change detection via Graph delta queries: new, modified, and deleted files per sync, with delta-token persistence between runs (one cursor per drive).
  - Application permissions covering content only: a site and file read grant (`Sites.Read.All`, or `Sites.Selected` per site). No directory group read grant is requested, because nothing in this version resolves a group identity, and asking a customer to consent to directory enumeration we cannot use would be an unearned permission.
  - Scoping to selected sites, drives, and folders.
  - File-type filter aligned with the existing upload allowlist (`app.ingestion.upload.allowed-mime-types`: pdf, docx, pptx, markdown, plain text, images) and a per-file size limit.
  - Throttling compliance per Graph API guidance: honour `Retry-After` on 429 and 503, exponential backoff, bounded retries, with one throttle budget per run.
  - The Graph and Entra ID token base addresses are settings that default to the public Microsoft hosts, so the e2e stack points them at a stub.
- Company-wide visibility for connector-synced documents:
  - Every chunk of a connector-landed document carries `acl` of `["tenant:everyone:{tenantId}"]` with `acl_source` of `tenant-default`, stamped by the ingestion producer default that `add-tenant-isolation` owns. No connector composes an access list itself, so there is exactly one producer of that principal in the system. The rule holds for every connector type of the framework once `add-tenant-isolation` lands.
  - Per-document permissions captured from the source are deferred whole, with their design, their decision records, and their failure analysis preserved.
- The SharePoint section of `docs/CONNECTORS.md`: the Azure app-registration steps a customer admin performs and the company-wide visibility statement a customer is told.
- Its own parts of the deployment: `add-deployment-modules` keeps company parts out of the always-on core, so this change adds its own parts when it lands: the `SHAREPOINT` type migration and the `app.connector.sharepoint.*` settings. A deployment without this change has no `SHAREPOINT` type.

Follow-on connectors (Google Drive, Confluence, network share) are explicit non-goals, and the framework interfaces make them additive.

## Capabilities

### New Capabilities

- `sharepoint-connector`: SharePoint and OneDrive sync via Microsoft Graph: client-credentials auth per tenant, delta-query incremental change detection with persisted delta tokens, the content application permission grants a sync actually requires, site, drive and folder scoping, file-type and size filtering aligned with the upload allowlist, 429 and 503 throttling compliance with a bounded per-run budget, and the end-to-end specs against a Graph stub.

One capability is shared with `add-connector-framework`, which adds its first requirements and lands first. This change adds one further requirement to it, with a name of its own:

- `document-connectors`: the company-wide visibility rule for connector-landed documents.

### Modified Capabilities

(none. No capability under `openspec/specs/` changes. Reviewed `ingestion-correctness`, `ingestion-security`, and `document-ingestion-docling`: connector-fetched files reuse the existing sanitization, MIME-allowlist, and ETag-dedup behavior through the framework, and the access list on their chunks is the tenant-everyone default that `add-tenant-isolation` already stamps for a document with no source-captured list.)

## Impact

- ascend-ai-agent (new code): `service/connector/sharepoint/` (Graph auth client, Graph API client, delta sync, the `SHAREPOINT` connector type), a Flyway versioned SQL migration `V<n>__connector_type_sharepoint.sql` (`<n>` taken at implementation time), and `app.connector.sharepoint.*` settings in `application.yaml`.
- Reused unchanged: everything of `add-connector-framework`, and the access-list stamp from `add-tenant-isolation`.
- External: outbound HTTPS to Microsoft Graph (`graph.microsoft.com`), and a customer-side Azure app registration with content application permissions only (documented in the SharePoint section of `docs/CONNECTORS.md`).
- Docs: the SharePoint section of `docs/CONNECTORS.md`. Decision records for what this change decides beyond ADR-M004 through ADR-M009 live under `decisions/` in this change folder, several of them deferred under the current scope with their analysis intact.
- Tests: unit and integration tests with mocked Graph responses covering add, modify and delete propagation, the company-wide access list on landed chunks, throttling backoff, delta-token invalidation and credential-logging hygiene. End-to-end specs in `apps/ascend-agent/e2e/testing/` run the SharePoint connector through the framework's API, sync now, sync history, retrieval scope and freshness against a Microsoft Graph stub.

## Relevant Skills

- `/springboot-patterns`
- `/java-coding-standards`
- `/api-design`
- `/database-migrations`
- `/security-review`
- `/backend-patterns`
- `/architecture-decision-records`
- `/tdd-workflow`
- `/e2e-runbooks`
