## ADDED Requirements

### Requirement: Per-user data export starts an asynchronous job

AscendAgent SHALL expose `POST /api/v1/users/{userId}/data/export` which creates a persisted export job and returns HTTP 202 with the job id. The endpoint SHALL be callable by the authenticated user for their own `userId` or by an ADMIN for any user; any other caller receives HTTP 403. Job state SHALL be persisted so the request survives restarts and remains reportable after completion, mirroring the erasure job lifecycle.

#### Scenario: Self-service export accepted

- **WHEN** the authenticated user `frosty` calls `POST /api/v1/users/frosty/data/export`
- **THEN** the response is HTTP 202 with a body containing a job id
- **AND** an export-job row exists with subject `frosty` and status `PENDING` or `RUNNING`

#### Scenario: Cross-user export by non-admin refused

- **WHEN** authenticated user `frosty` (no ADMIN role) calls `POST /api/v1/users/otheruser/data/export`
- **THEN** the response is HTTP 403 and no export job is created

### Requirement: Export assembles subject data into a downloadable archive

An export job SHALL assemble, into a single archive with a machine-readable manifest, the subject's: chat history and `conversations`, `user_instructions`, ingested documents fetched from MinIO, and AscendMemory memories across configured embedding providers. The job SHALL reuse the same store-walker inventory the erasure capability uses, so the set of stores exported equals the set of stores erased. The archive SHALL be retrievable via a status/download endpoint and SHALL be retained for a bounded, configurable window before automatic cleanup.

#### Scenario: Export contains every subject store

- **WHEN** an export job for `frosty` completes
- **THEN** the archive manifest lists chat history / conversations, user instructions, ingested documents, and AscendMemory memories for `frosty`
- **AND** the archive contains the ingested document bytes retrieved from MinIO

#### Scenario: Export and erasure cover the same stores

- **WHEN** the export store-walker and the erasure store-walker are enumerated
- **THEN** they cover the identical set of subject stores, so neither can silently omit a store the other includes

### Requirement: Export job status and download endpoint

AscendAgent SHALL expose a status/download endpoint returning the job's status (`PENDING`, `RUNNING`, `COMPLETED`, `FAILED`), and, when complete, a means to download the assembled archive. Authorization matches the export start endpoint (self or ADMIN). Export start and completion SHALL be recorded through the audit-logging capability.

#### Scenario: Completed export is downloadable and audited

- **WHEN** the requester polls the status endpoint after the job finishes
- **THEN** the response reports status `COMPLETED` and provides the archive download
- **AND** an `EXPORT_REQUESTED` and an `EXPORT_COMPLETED` audit row exist for the subject

### Requirement: Per-tenant export for offboarding

An ADMIN SHALL be able to start an export job covering an entire tenant via `POST /api/v1/tenants/{tenantId}/data/export`, using the same job machinery, store coverage, status/download endpoint, and audit semantics as per-user export, with tenant attribution supplied by `add-tenant-isolation`.

#### Scenario: Tenant export then erase

- **WHEN** an ADMIN exports tenant `acme`, downloads the archive, and then runs tenant erasure
- **THEN** the export archive contains tenant `acme`'s data and the subsequent erasure leaves zero residue for `acme`
