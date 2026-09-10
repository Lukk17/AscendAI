## ADDED Requirements

### Requirement: Client-credentials authentication per tenant

The SharePoint connector SHALL authenticate to Microsoft Graph using the OAuth2 client-credentials flow with a per-tenant Entra ID app registration (directory/tenant id, client id, and a client secret resolved from the encrypted credential store at sync time). Access tokens SHALL be cached in memory until expiry and SHALL never be persisted or logged. An authentication failure SHALL fail the sync run with status `FAILED` and an error summary that identifies the failure class (e.g., invalid client, consent missing) without reproducing the secret or the raw token response.

#### Scenario: Token acquired and used

- **WHEN** a sync run starts for a connector with valid app-registration credentials
- **THEN** the connector obtains an access token via the client-credentials grant and calls Graph with it
- **AND** no token or secret value is written to logs or the database

#### Scenario: Invalid credentials fail the run cleanly

- **WHEN** the client secret has been revoked in Entra ID
- **THEN** the sync run ends with status `FAILED` and an error summary naming an authentication failure
- **AND** the content cursor and the connector's last successful sync timestamp are both unchanged

### Requirement: Application permissions cover content and nothing wider

The connector's Entra ID app registration SHALL hold admin-consented application permissions sufficient to enumerate the configured sites and drives and to read item content: `Sites.Read.All`, or `Sites.Selected` granted per configured site. The connector SHALL NOT require, request, or use a directory group read grant such as `GroupMember.Read.All`, because nothing in this version resolves a directory group identity. A connector scoped to a site the registration cannot read SHALL fail that site's sync with a reason naming the site, rather than silently syncing nothing.

#### Scenario: Content grant alone is sufficient

- **WHEN** a connector's app registration holds `Sites.Read.All` with admin consent and no directory permission of any kind
- **THEN** in-scope items are enumerated, downloaded, and landed in MinIO
- **AND** the run completes without any permission-related failure

#### Scenario: Site outside a Sites.Selected grant fails loudly

- **WHEN** a connector using `Sites.Selected` is scoped to a site the app registration was not granted access to
- **THEN** that site's items fail with a reason naming the ungranted site
- **AND** no item from that site is landed in MinIO
- **AND** the run does not report success for that site

#### Scenario: No directory permission is requested

- **WHEN** the setup guide's app-registration walkthrough and the connector's Graph calls are reviewed
- **THEN** no directory, group, or group-member application permission is asked of the customer
- **AND** the connector issues no request against a directory group endpoint

### Requirement: Incremental change detection via Graph delta queries

The SharePoint connector SHALL detect content changes using Microsoft Graph drive delta queries. The first sync of a drive SHALL enumerate it fully via a delta request without a token; every subsequent sync SHALL pass the persisted delta token and process only items created, modified, or deleted since the previous run (deletions identified by the item's `deleted` facet). One delta token SHALL be persisted per drive. When Graph signals that a token is no longer valid (HTTP 410 / resync required), the connector SHALL discard the token and re-enumerate the drive in full.

A full re-enumeration SHALL NOT re-parse, re-chunk, or re-embed a file whose content version matches the stored value.

#### Scenario: Only changes since last run are processed

- **WHEN** a drive with 500 files has one file modified and one added since the last sync
- **THEN** the next sync run touches exactly those two files for content
- **AND** the run's counters show added=1, updated=1

#### Scenario: Deleted item detected

- **WHEN** the delta response contains an item carrying the `deleted` facet for a previously synced file
- **THEN** the connector reports it as a deletion to the framework's deletion-propagation path

#### Scenario: Expired delta token triggers full resync without re-embedding unchanged content

- **WHEN** Graph responds 410 with a resync instruction for the stored delta token
- **THEN** the connector discards the token and re-enumerates the drive from scratch
- **AND** a file whose bytes are unchanged is not re-embedded and keeps its existing chunk point identifiers
- **AND** the run's counters show updated=0 for those files

### Requirement: Sync scope limited to configured sites, drives, and folders

The SharePoint connector SHALL sync only the sites, drives, and folders named in the connector's source scope. Configured sites SHALL be resolved to their drives via Graph; folder scoping SHALL be applied to delta results by path so items outside the configured folders are ignored entirely (no download, no MinIO write, no outcome record).

#### Scenario: Out-of-scope file ignored

- **WHEN** the delta response includes a new file located outside every configured folder
- **THEN** the file is not downloaded and it is not landed in MinIO
- **AND** no per-file outcome is recorded for it

#### Scenario: Folder scope honoured within a drive

- **WHEN** a connector is scoped to `/Policies` within a drive and files change in both `/Policies` and `/Marketing`
- **THEN** only the `/Policies` changes are synced

### Requirement: File-type and size filtering aligned with the upload allowlist

The SharePoint connector SHALL download only files whose type is in the existing upload allowlist (`app.ingestion.upload.allowed-mime-types`: PDF, DOCX, PPTX, markdown, plain text, and the allowed image types) and whose size does not exceed the connector's configured per-file limit. Files failing either check SHALL be recorded as `SKIPPED` with the reason, without being downloaded in full.

#### Scenario: Oversized file skipped

- **WHEN** the delta response reports a 2 GB video file in scope
- **THEN** the file is not downloaded
- **AND** its outcome record shows `SKIPPED` with a size-limit reason

#### Scenario: Allowed document synced

- **WHEN** the delta response reports a new 3 MB DOCX in scope
- **THEN** the file is downloaded, passes the sniffed-MIME check, and lands in MinIO

### Requirement: Graph throttling compliance

The SharePoint connector SHALL treat HTTP 429 and throttling 503 responses from Graph per Microsoft's guidance: when a `Retry-After` header is present, wait at least that long before retrying; otherwise apply exponential backoff with jitter. Retries SHALL be bounded per request, and each sync run SHALL have one bounded throttling budget that when exhausted ends the run with status `PARTIAL`, persisting the content cursor only up to the last fully processed page, so the next run resumes without loss.

#### Scenario: Retry-After honoured

- **WHEN** Graph returns 429 with `Retry-After: 7` during a sync
- **THEN** the connector waits at least 7 seconds before retrying the same request
- **AND** the request eventually succeeds and the run continues

#### Scenario: Throttle budget exhausted ends run as PARTIAL

- **WHEN** repeated 429 responses exhaust the run's throttling budget mid-sync
- **THEN** the run ends with status `PARTIAL`
- **AND** the persisted content cursor reflects only fully processed pages, so the next run resumes the remainder
