## MODIFIED Requirements

### Requirement: Filename sanitization before storage

The ingestion controller SHALL sanitize the user-supplied filename before using it in any storage key (S3 object key, local path, Qdrant `source` metadata). Sanitization SHALL replace any character outside `[A-Za-z0-9._-]` with `_`, strip leading dots (no `.htaccess`-style hidden files), collapse repeated separators, and cap the length at 200 characters. The resulting storage key SHALL be prefixed with `tenant/{tenantId}/` where `{tenantId}` is the tenant resolved from the request's tenant context — never from user input — followed by the existing folder segment (`markdown/` or `documents/`) and the sanitized filename. Uploads without a resolved tenant context SHALL be rejected.

#### Scenario: Path-traversal attempt is neutralized

- **WHEN** a user of tenant `acme` uploads a file named `../../etc/passwd.txt`
- **THEN** the stored S3 key contains `_.._.._etc_passwd.txt` (or equivalent) — no `/` separators or leading dots survive in the filename segment
- **AND** the upload does NOT write outside `tenant/acme/`

#### Scenario: Unicode and control characters

- **WHEN** the filename contains spaces, emoji, or control characters
- **THEN** all such characters are replaced with `_` and the resulting key is ASCII-safe

#### Scenario: Upload key carries the tenant prefix

- **WHEN** a user of tenant `acme` uploads `notes.md`
- **THEN** the stored S3 key is `tenant/acme/markdown/notes.md`
- **AND** an upload of `report.pdf` by the same tenant lands at `tenant/acme/documents/report.pdf`

## ADDED Requirements

### Requirement: Tenant metadata stamped on every ingested chunk

Every ingestion producer (Markdown, Docling, ascend-ocr, Unstructured) SHALL stamp a `tenant_id` metadata key (declared in `IngestionMetadataKeys`) on every `Document` it writes to the vector store, set to the tenant resolved from the ingestion request's tenant context. Ingestion without a resolved tenant context SHALL fail; no chunk SHALL ever be written without `tenant_id`.

#### Scenario: Uploaded document's chunks carry tenant metadata

- **WHEN** a user of tenant `acme` uploads and ingests `notes.md`
- **THEN** every Qdrant point created for that document has `metadata.tenant_id == "acme"`

#### Scenario: Ingestion without tenant context is rejected

- **WHEN** an ingestion path is invoked while no tenant is resolved
- **THEN** the operation fails with an error
- **AND** no points are written to Qdrant

### Requirement: Access-list metadata stamped on every ingested chunk

Every ingestion producer SHALL stamp `acl`, `acl_source`, `acl_version`, and `acl_synced_at` (declared in `IngestionMetadataKeys`, contract in the `tenant-isolation` capability) on every `Document` it writes, in the same place it stamps `tenant_id`, so the two axes cannot diverge. The list SHALL be explicit: a producer SHALL NOT write a chunk with an absent or empty `acl` and rely on any later step to fill it in, because under deny-by-default that chunk is retrievable by nobody and costs storage while doing nothing.

For a direct upload, where no source system holds a permission list, the producer SHALL stamp `acl` as `["tenant:everyone:{tenantId}"]` with `acl_source` of `tenant-default`. That reproduces the pre-change behaviour of a single-company deployment deliberately, as a grant visible in the payload. Narrower lists on direct uploads come from the administrator assignment surface, whose ownership is an open question in `docs/architecture/permission-aware-retrieval.md` and which is out of scope here; connector-captured lists (`sharepoint`, `google-drive`) are owned by `add-document-connectors`. Ingestion without a resolved tenant context SHALL fail before any access list is composed.

#### Scenario: Uploaded document's chunks carry an explicit tenant-wide list

- **WHEN** a user of tenant `acme` uploads and ingests `notes.md`
- **THEN** every Qdrant point created for that document has `metadata.acl` equal to `["tenant:everyone:acme"]`
- **AND** `metadata.acl_source` is `tenant-default`
- **AND** `metadata.acl_version` is the hash of that sorted list and `metadata.acl_synced_at` is the ingest time

#### Scenario: No chunk is written without an access list

- **WHEN** any ingestion producer completes a run
- **THEN** no point written by that run has an absent or empty `acl`
- **AND** a producer that cannot compose a list fails the source rather than writing the chunk without one

#### Scenario: Ingested chunk is immediately retrievable by its own tenant

- **WHEN** a user of tenant `acme` uploads `notes.md` and then prompts with a query matching it
- **THEN** retrieval returns chunks from `notes.md`
- **AND** no migration or backfill step is required for a freshly ingested document to be retrievable

### Requirement: Manual ingestion scan scoped to the caller's tenant prefix

`POST /api/v1/ingestion/run` SHALL interpret the optional `prefix` parameter relative to the caller's tenant prefix, so the effective S3 scan prefix is always `tenant/{tenantId}/` plus the supplied value. A caller SHALL NOT be able to scan or ingest objects outside its own tenant prefix, regardless of the `prefix` value supplied.

#### Scenario: Scan without prefix stays inside the tenant

- **WHEN** a user of tenant `acme` calls `POST /api/v1/ingestion/run` with no `prefix`
- **THEN** the scan covers keys under `tenant/acme/` only

#### Scenario: Prefix cannot escape the tenant

- **WHEN** a user of tenant `acme` calls the endpoint with `prefix=tenant/globex/` (or `../`-style values)
- **THEN** no object outside `tenant/acme/` is scanned or ingested
