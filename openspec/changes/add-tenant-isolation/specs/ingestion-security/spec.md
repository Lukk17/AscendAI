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

Every ingestion producer (Markdown, Docling, PaddleOCR, Unstructured) SHALL stamp a `tenant_id` metadata key (declared in `IngestionMetadataKeys`) on every `Document` it writes to the vector store, set to the tenant resolved from the ingestion request's tenant context. Ingestion without a resolved tenant context SHALL fail; no chunk SHALL ever be written without `tenant_id`.

#### Scenario: Uploaded document's chunks carry tenant metadata

- **WHEN** a user of tenant `acme` uploads and ingests `notes.md`
- **THEN** every Qdrant point created for that document has `metadata.tenant_id == "acme"`

#### Scenario: Ingestion without tenant context is rejected

- **WHEN** an ingestion path is invoked while no tenant is resolved
- **THEN** the operation fails with an error
- **AND** no points are written to Qdrant

### Requirement: Manual ingestion scan scoped to the caller's tenant prefix

`POST /api/v1/ingestion/run` SHALL interpret the optional `prefix` parameter relative to the caller's tenant prefix, so the effective S3 scan prefix is always `tenant/{tenantId}/` plus the supplied value. A caller SHALL NOT be able to scan or ingest objects outside its own tenant prefix, regardless of the `prefix` value supplied.

#### Scenario: Scan without prefix stays inside the tenant

- **WHEN** a user of tenant `acme` calls `POST /api/v1/ingestion/run` with no `prefix`
- **THEN** the scan covers keys under `tenant/acme/` only

#### Scenario: Prefix cannot escape the tenant

- **WHEN** a user of tenant `acme` calls the endpoint with `prefix=tenant/globex/` (or `../`-style values)
- **THEN** no object outside `tenant/acme/` is scanned or ingested
