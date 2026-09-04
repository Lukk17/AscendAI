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
- **AND** the content cursor and the permission confirmation timestamp are both unchanged

### Requirement: Application permissions sufficient to read sharing and to resolve group identities

The connector's Entra ID app registration SHALL hold admin-consented application permissions covering both site and item content and the directory reads that principal mapping requires: a site/file read grant sufficient for the `driveItem` permissions collection (`Sites.Read.All`, or `Sites.Selected` granted per configured site), and a directory group read grant sufficient to resolve a permission entry's group identity (`GroupMember.Read.All` or a higher-privileged equivalent). A connector whose registration lacks the directory grant SHALL fail access-list capture rather than syncing documents without access lists.

#### Scenario: Missing directory grant fails capture rather than landing unprotected documents

- **WHEN** a connector's app registration holds only the site and file content grants and a sync runs
- **THEN** capture fails for every in-scope item with a reason naming the missing directory grant
- **AND** no chunk is written for any of those items

#### Scenario: Site outside a Sites.Selected grant fails capture

- **WHEN** a connector using `Sites.Selected` is scoped to a site the app registration was not granted access to
- **THEN** that site's items fail capture with a reason naming the ungranted site
- **AND** no item from that site is landed in MinIO

#### Scenario: Both grants present, capture succeeds

- **WHEN** a connector's app registration holds `Sites.Read.All` and `GroupMember.Read.All` with admin consent
- **THEN** in-scope items are landed and every chunk carries a non-empty or deliberately empty access list captured from Graph

### Requirement: Item and container permissions read from Graph

The SharePoint connector SHALL obtain access lists by reading the effective sharing permissions of drive items and folders from Microsoft Graph, container-first: the permissions of the drive root and each in-scope folder are read and applied to the items that inherit them, and a per-item read is issued only for an item whose permission collection carries an entry the source does not mark as inherited, or whose permission confirmation is due. The connector SHALL NOT infer permissions from the delta response, and SHALL NOT treat an item's absence from a delta page as evidence that its permissions are unchanged.

Permission reads SHALL draw on a per-run throttling budget separate from the content budget, so that permission reads cannot starve document landing and document landing cannot starve permission reads. Exhausting either budget SHALL end the run as `PARTIAL` with the corresponding cursor state advanced only through what was fully processed.

#### Scenario: Folder read covers inheriting items

- **WHEN** a first sync enumerates an in-scope folder containing documents that all inherit the folder's permissions
- **THEN** the connector issues one permission read for the folder and none for the inheriting documents
- **AND** every one of those documents' chunks carries the folder's captured access list

#### Scenario: Item with a non-inherited entry is read individually

- **WHEN** an item's permission collection contains an entry that Graph does not mark as inherited from an ancestor
- **THEN** the connector issues a permission read for that item
- **AND** the item's chunks carry the item's own access list rather than its folder's

#### Scenario: Sharing change with unchanged bytes is detected

- **WHEN** a group's access to an in-scope file is revoked in SharePoint and the file's bytes are not edited
- **THEN** the next run in which that file's confirmation is due reads its permissions from Graph
- **AND** the file's outcome is `PERMISSIONS_UPDATED` with a new access-list version
- **AND** the file's chunk point identifiers are unchanged

#### Scenario: Permission throttling does not starve content landing

- **WHEN** repeated 429 responses exhaust the run's permission throttling budget while the content budget remains
- **THEN** the run ends with status `PARTIAL`
- **AND** items landed in that run carry captured access lists
- **AND** the permission confirmation timestamp advances only through the items actually confirmed

### Requirement: Graph permission entries mapped to group principals

The connector SHALL map each Graph permission entry to a principal in the `entra:group:<directory object id>` form, using the directory object id rather than any display name, login name, or pairwise subject identifier. A permission entry granted to an individual user SHALL NOT be expanded into the access list. An entry the connector cannot map to a group principal in a known namespace (including a sharing-link entry, an application grant, and a site-local group the connector cannot resolve to a directory group) SHALL fail capture for that item with a reason naming the entry class.

A permission collection that is empty, or that returns fewer entries than the connector can attribute, on an item whose content the connector can otherwise read SHALL be treated as a capture failure rather than as an empty access list.

#### Scenario: Group entry becomes a directory-object-id principal

- **WHEN** an item is shared with an Entra ID security group
- **THEN** the item's access list contains `entra:group:` followed by that group's directory object id
- **AND** the group's display name appears in no chunk metadata

#### Scenario: User-only sharing does not produce a user principal

- **WHEN** an item is shared with individual people and with no group
- **THEN** no principal naming an individual person is written to the access list
- **AND** the item's outcome records the personal-grant capture reason

#### Scenario: Sharing-link entry fails capture

- **WHEN** an item's permission collection contains an anyone-with-the-link entry
- **THEN** the item's outcome is `FAILED` with a reason naming the link-share entry class
- **AND** no chunk for that item is written with a partial access list

#### Scenario: Unattributable permission collection is a failure, not an empty list

- **WHEN** Graph returns an empty permission collection for an item whose content the connector successfully downloaded
- **THEN** the item's outcome is `FAILED` with a capture reason
- **AND** no chunk for that item is written with an empty access list

### Requirement: Incremental change detection via Graph delta queries

The SharePoint connector SHALL detect content changes using Microsoft Graph drive delta queries. The first sync of a drive SHALL enumerate it fully via a delta request without a token; every subsequent sync SHALL pass the persisted delta token and process only items created, modified, or deleted since the previous run (deletions identified by the item's `deleted` facet). One delta token SHALL be persisted per drive. When Graph signals that a token is no longer valid (HTTP 410 / resync required), the connector SHALL discard the token and re-enumerate the drive in full.

A full re-enumeration SHALL NOT re-parse, re-chunk, or re-embed a file whose content version and access-list version both match the stored values, and SHALL apply a payload-only access-list update to any item whose access list changed while its bytes did not. A full re-enumeration is the point at which every item in scope has its permissions confirmed, so it SHALL advance the permission confirmation timestamp for the items it confirms.

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
- **AND** a file whose bytes and access list are both unchanged is not re-embedded and keeps its existing chunk point identifiers
- **AND** the run's counters show updated=0 for those files

#### Scenario: Full re-enumeration refreshes access lists that moved during the outage

- **WHEN** a group's access to an in-scope file was revoked while the delta token was invalid, and the file's bytes did not change
- **THEN** the full re-enumeration captures the new access list and applies a payload-only update to that file
- **AND** the file's outcome is `PERMISSIONS_UPDATED` with unchanged chunk point identifiers
- **AND** the permission confirmation timestamp advances for the re-enumerated items

### Requirement: Sync scope limited to configured sites, drives, and folders

The SharePoint connector SHALL sync only the sites, drives, and folders named in the connector's source scope. Configured sites SHALL be resolved to their drives via Graph; folder scoping SHALL be applied to delta results by path so items outside the configured folders are ignored entirely (no permission read, no MinIO write, no outcome record).

#### Scenario: Out-of-scope file ignored

- **WHEN** the delta response includes a new file located outside every configured folder
- **THEN** the file is not downloaded, its permissions are not read, and it is not landed in MinIO
- **AND** no per-file outcome is recorded for it

#### Scenario: Folder scope honoured within a drive

- **WHEN** a connector is scoped to `/Policies` within a drive and files change in both `/Policies` and `/Marketing`
- **THEN** only the `/Policies` changes are synced

### Requirement: File-type and size filtering aligned with the upload allowlist

The SharePoint connector SHALL download only files whose type is in the existing upload allowlist (`app.ingestion.upload.allowed-mime-types`: PDF, DOCX, PPTX, markdown, plain text, and the allowed image types) and whose size does not exceed the connector's configured per-file limit. Files failing either check SHALL be recorded as `SKIPPED` with the reason, without being downloaded in full and without a permission read being spent on them.

#### Scenario: Oversized file skipped

- **WHEN** the delta response reports a 2 GB video file in scope
- **THEN** the file is not downloaded and no permission read is issued for it
- **AND** its outcome record shows `SKIPPED` with a size-limit reason

#### Scenario: Allowed document synced

- **WHEN** the delta response reports a new 3 MB DOCX in scope
- **THEN** the file is downloaded, passes the sniffed-MIME check, has its access list captured, and lands in MinIO

### Requirement: Graph throttling compliance

The SharePoint connector SHALL treat HTTP 429 and throttling 503 responses from Graph per Microsoft's guidance: when a `Retry-After` header is present, wait at least that long before retrying; otherwise apply exponential backoff with jitter. Retries SHALL be bounded per request, and each sync run SHALL have bounded throttling budgets (one for content requests and one for permission requests) that when exhausted end the run with status `PARTIAL`, persisting the content cursor only up to the last fully processed page and the permission confirmation timestamp only through the items actually confirmed, so the next run resumes without loss.

#### Scenario: Retry-After honoured

- **WHEN** Graph returns 429 with `Retry-After: 7` during a sync
- **THEN** the connector waits at least 7 seconds before retrying the same request
- **AND** the request eventually succeeds and the run continues

#### Scenario: Throttle budget exhausted ends run as PARTIAL

- **WHEN** repeated 429 responses exhaust the run's content throttling budget mid-sync
- **THEN** the run ends with status `PARTIAL`
- **AND** the persisted content cursor reflects only fully processed pages, so the next run resumes the remainder
