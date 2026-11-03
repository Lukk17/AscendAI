## Purpose

Keeps downloaded files in object storage per tenant, found again by their content hash, and hands the owner time-limited links to them, with operations to get, list and delete what was stored.

## ADDED Requirements

### Requirement: Objects under the tenant prefix

Every downloaded file SHALL be stored in the bucket `DOWNLOAD_S3_BUCKET`, never in the `knowledge-base` bucket, under `tenant/<tenantId>/downloads/<sha256>/`, with the content and a metadata record holding the source URL without query string, fragment or user info, the source host, the first and last fetch times, the size, the SHA-256, the family, the content type, the fetch path and the scan result. The metadata record SHALL be written only after the content is stored. The bucket SHALL be created at startup when it is missing.

#### Scenario: Keys carry the tenant

- **WHEN** a caller of tenant `acme` stores a file whose SHA-256 is `h`
- **THEN** the content and its metadata record are stored under `tenant/acme/downloads/h/`

### Requirement: Tenant from the trusted caller only

The tenant of an operation SHALL come from the MCP request metadata key `ascend.ai/tenant_id` or the REST header `X-Ascend-Tenant`, and SHALL be the fixed tenant `default` when neither names one. No setting SHALL change that default. No tool argument SHALL name a tenant. A tenant outside `[a-z0-9-]{1,64}` SHALL be refused with code `invalid_tenant` (HTTP 400).

#### Scenario: Invalid tenant refused

- **WHEN** a REST call sends `X-Ascend-Tenant: ../acme`
- **THEN** the answer is `invalid_tenant` and nothing is read or written

#### Scenario: No tenant named

- **WHEN** a call names no tenant
- **THEN** the operation acts on tenant `default`

### Requirement: Deduplication inside one tenant

Before storing a file the service SHALL look for a record with the same SHA-256 under the caller's tenant. When one exists, the content SHALL NOT be stored again, the record's last fetch time and fetch count and its place in the newest first list SHALL be updated, and the answer SHALL be that record with `deduplicated` true. A hash SHALL never be looked up under another tenant.

#### Scenario: Same file in two tenants

- **WHEN** tenant `acme` and tenant `globex` each download the same file
- **THEN** each tenant gets its own stored copy and neither answer is marked `deduplicated`

### Requirement: Time-limited download links

Every answer that returns a record SHALL carry a fresh presigned `GET` link to the content, valid for `DOWNLOAD_LINK_TTL_SECONDS`, signed for the public object store address, and asking the browser to save the file as an attachment under the record's `file_name` with the record's content type. A link lifetime above 86400 seconds SHALL be refused at startup, so a link lasts at most 24 hours.

#### Scenario: Link saves under the right name

- **WHEN** the owner opens the `download_url` of a record named `LM317-datasheet.pdf`
- **THEN** the browser receives the file with `Content-Disposition` `attachment` and that file name

#### Scenario: Link expires

- **WHEN** `DOWNLOAD_LINK_TTL_SECONDS` has passed since the link was signed
- **THEN** the object store refuses the link

### Requirement: Get, list and delete downloads

ascend-web-hunter SHALL expose `web_download_get`, `web_download_list` and `web_download_delete` on MCP, and `GET /api/v2/web/downloads/{download_id}`, `GET /api/v2/web/downloads` and `DELETE /api/v2/web/downloads/{download_id}` on REST, each acting only on the caller's tenant. Get SHALL return the record with a fresh link, or code `download_not_found` (HTTP 404) for an unknown id, an id of another tenant, or an id that is not 64 lower-case hexadecimal characters. List SHALL return records newest first by last fetch time, at most `limit` per page, from 1 to `DOWNLOAD_LIST_MAX_LIMIT` (default 100), `DOWNLOAD_LIST_DEFAULT_LIMIT` (default 20) when the call names none, both settings read from the environment, with an opaque cursor for the next page. Delete SHALL remove the content, the metadata record and the list entry, and SHALL succeed (HTTP 204) whether or not the download existed.

#### Scenario: Another tenant's id is not found

- **WHEN** a caller of tenant `globex` gets a `download_id` stored only under tenant `acme`
- **THEN** the answer is `download_not_found`

#### Scenario: Newest first

- **WHEN** a tenant has three downloads fetched at different times
- **THEN** the list returns them with the most recently fetched first

#### Scenario: Delete makes the link stop working

- **WHEN** a caller deletes a download and then opens a link signed before the delete
- **THEN** the object store answers that the object does not exist
- **AND** a get of that id answers `download_not_found`

#### Scenario: Delete is idempotent

- **WHEN** a caller deletes a download id the tenant does not hold, twice
- **THEN** both answers are HTTP 204

### Requirement: Storage failures fail closed

When the object store or the list index cannot be reached, a download, get, list or delete SHALL be answered with code `storage_unavailable` (HTTP 503) and SHALL NOT report a file as stored. A lost list index SHALL be rebuilt from the bucket on the next list.

#### Scenario: Object store down during a download

- **WHEN** the object store refuses the upload of a downloaded file
- **THEN** the answer is `storage_unavailable` and no record is returned

### Requirement: Downloads are deleted 24 hours after the last download

A downloaded file SHALL be temporary. ascend-web-hunter itself SHALL run a retention sweep, with no agent system task, started only while the module `web-download` is in `ASCEND_MODULES`. Every `DOWNLOAD_RETENTION_SWEEP_SECONDS` (default 900) one process at a time, chosen by a Redis lock, SHALL sweep every tenant that has a prefix under `tenant/` in the download bucket, with `fetched_before` set to the round's time minus `DOWNLOAD_RETENTION_SECONDS` (default and maximum 86400). The sweep SHALL delete every download of that tenant whose last fetch time is at or before `fetched_before`, as a delete does, and SHALL NOT delete a kept file. No route or tool SHALL force the deletion. Several ascend-web-hunter instances MAY run the sweep timer, and the Redis lock SHALL let only one of them sweep in a round. A new download of the same file SHALL update its last fetch time and so start the 24 hours again. A failed sweep of a tenant SHALL be retried at the next round.

#### Scenario: Downloading again starts the 24 hours again

- **WHEN** a file was first downloaded 30 hours ago, downloaded again 2 hours ago, and the retention sweep runs
- **THEN** the file is still listed and its link still works

#### Scenario: Download older than 24 hours is deleted

- **WHEN** a file was last downloaded 25 hours ago and the retention sweep runs
- **THEN** its content, its metadata record and its list entry are gone
- **AND** a get of its id answers `download_not_found`

#### Scenario: Recent download stays

- **WHEN** a file was last downloaded 2 hours ago and the retention sweep runs
- **THEN** the file is still listed and its link still works

#### Scenario: Kept copy survives the deletion

- **WHEN** a file was kept and its download is deleted by the retention sweep
- **THEN** the kept file is still listed and readable

#### Scenario: A sweep round while another process sweeps

- **WHEN** two ascend-web-hunter processes reach a sweep round at the same time
- **THEN** exactly one of them sweeps and the other skips that round

### Requirement: A file can be kept in the persistent folder

ascend-web-hunter SHALL expose the MCP tool `web_download_keep` and the REST endpoint `POST /api/v2/web/downloads/{download_id}/keep`, taking the download id and an optional file name checked by the caller name rules. Keep SHALL copy the stored file server side to `tenant/<tenantId>/files/<sha256>/` in the same bucket, with a metadata record that adds the keep time, and SHALL answer the kept file record with a fresh link: HTTP 201 when it was kept now and HTTP 200 when it was already kept. A kept file SHALL stay until it is deleted. ascend-web-hunter SHALL expose `web_download_kept_get`, `web_download_kept_list` and `web_download_kept_delete` on MCP and `GET /api/v2/web/downloads/kept/{download_id}`, `GET /api/v2/web/downloads/kept` and `DELETE /api/v2/web/downloads/kept/{download_id}` on REST, with the same tenant, paging, link and idempotent delete rules as the download operations. Deleting a download SHALL NOT delete its kept copy, and deleting a kept file SHALL NOT delete the download. Links to kept files SHALL last at most 24 hours like every other link.

#### Scenario: The assistant keeps a datasheet

- **WHEN** the assistant calls `web_download_keep` for a stored download
- **THEN** the answer carries a fresh link and the file is stored under `tenant/<tenantId>/files/<sha256>/`
- **AND** `web_download_kept_list` returns it

#### Scenario: Keep an unknown download

- **WHEN** a caller keeps a `download_id` that the tenant does not hold
- **THEN** the answer is `download_not_found` and nothing is copied

### Requirement: Download operations follow the module switch

ascend-web-hunter SHALL register the download and kept file MCP tools and the `/api/v2/web/downloads` routes only when `ASCEND_MODULES` holds `web-download`. The development compose file SHALL pass `COMPOSE_PROFILES` from `.env` to ascend-web-hunter as `ASCEND_MODULES`, so the module `web-download` is switched on through `COMPOSE_PROFILES`. An unset or empty `ASCEND_MODULES` SHALL mean the feature is off. No setting of its own SHALL switch the feature. With the module off, the retention sweep SHALL NOT start.

#### Scenario: Module off

- **WHEN** ascend-web-hunter starts without `web-download` in `ASCEND_MODULES`
- **THEN** no `web_download_*` tool is listed and `GET /api/v2/web/downloads` answers 404
