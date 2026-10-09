## ADDED Requirements

### Requirement: Per-user data export starts an asynchronous job

ascend-ai-agent SHALL expose `POST /api/v1/users/{userId}/data/export` which creates a persisted export job and returns HTTP 202 with the job id. The endpoint SHALL be callable by the authenticated user for their own `userId` or by a tenant ADMIN for any user of the ADMIN's own tenant. Any other caller, including an ADMIN of another tenant, receives HTTP 403. Job state SHALL be persisted as a row of kind `EXPORT` in the one job table `data_job` of the erasure capability, so the request survives restarts and remains reportable after completion, and SHALL run as one execution of the shared scheduler on exactly one agent instance, mirroring the erasure job lifecycle. The archive SHALL be written to the shared object store, in its own bucket `data-exports` (the setting `app.audit.export.bucket`), under the key `tenant/{tenantId}/exports/{jobId}.tar.gz`, so every agent instance can serve the download.

#### Scenario: Self-service export accepted

- **WHEN** the authenticated user `frosty` calls `POST /api/v1/users/frosty/data/export`
- **THEN** the response is HTTP 202 with a body containing a job id
- **AND** a `data_job` row of kind `EXPORT` exists with subject `frosty` and status `PENDING` or `RUNNING`

#### Scenario: The download works on another instance

- **WHEN** two agent instances run and an export started through the first instance completes
- **THEN** a download request for the job served by the second instance returns the archive

#### Scenario: Cross-user export by non-admin refused

- **WHEN** authenticated user `frosty` (no ADMIN role) calls `POST /api/v1/users/otheruser/data/export`
- **THEN** the response is HTTP 403 and no export job is created

### Requirement: Export assembles subject data into a downloadable archive

An export job SHALL assemble, into a single archive with a machine-readable manifest, the subject's: chat history and `conversations`, the user facts file `USER.md` of `add-agent-soul` at its newest commit, the store steps a later change registers in the shared store inventory (the `usage_ledger` rows of `add-usage-metering-and-quotas`), ingested documents fetched from the Floci `knowledge-base` bucket, the results of the subject's OCR jobs from the `ocr-results` bucket, AscendMemory memories across configured embedding providers under the tenant-qualified id `{tenantId}:{userId}`, and the subject's Keycloak user record (profile fields, realm roles and groups). It SHALL also include, through the export step this change writes on the layout each owning change defines (every owning change lands before this capability): the subject's `subagent_run` rows (`add-agent-subagents`), the subject's `sandbox_workspace` rows and their output archives found through each row's `output_key` (`add-agent-sandbox`), notifications (`add-shared-scheduler`), approval requests (`add-action-approvals`), chat platform links and conversation bindings (`add-openclaw-plugin-host`), `coding_project` and `coding_run` rows with their `coding-output` objects and one gzip tar archive of each project folder the subject created, fetched through the archive call of the sandbox runner (`GET /v1/coding-area/projects/{id}/archive` of `add-agent-sandbox`) and taken after any running coding run of that project ends (`add-coding-agent-delegation`), scheduled jobs and firings (`add-scheduled-tasks`), the subject's `self_review` and `self_change` rows as JSON (`add-self-improvement`), and the integrations whose `created_by` is the subject with manifests and version states and never a secret value (`add-self-built-integrations`). A per user export SHALL hold no crawl data of `enhance-web-search-crawl-at-scale`, because crawl jobs belong to the tenant and hold no user id. The job SHALL reuse the same store-walker inventory the erasure capability uses, so the set of stores exported equals the set of stores erased: every store an erasure job erases, for a user or for a tenant, SHALL have an export entry. The archive SHALL be retrievable via a status/download endpoint and SHALL be retained for a bounded window, the setting `app.audit.export.retention`, before automatic cleanup. The archive SHALL be one gzip tar that holds one top folder per step of the store-walker inventory, named by the step, and `manifest.json` at its root with the job id, the subject, the export time and `store_outcomes`.

#### Scenario: Export contains every subject store

- **WHEN** an export job for `frosty` completes
- **THEN** the archive manifest lists chat history / conversations, the user facts file `USER.md`, ingested documents, and AscendMemory memories for `frosty`
- **AND** the archive contains the ingested document bytes retrieved from the Floci `knowledge-base` bucket
- **AND** the manifest lists the Keycloak user record of `frosty`

#### Scenario: The archive has one folder per store step and a manifest at the root

- **WHEN** an export job for `frosty` of tenant `acme` completes
- **THEN** its archive is the object `tenant/acme/exports/<jobId>.tar.gz` in the bucket `data-exports`
- **AND** listing the archive shows one top folder for each step of the store-walker inventory and `manifest.json` at the root
- **AND** `manifest.json` holds the job id, the subject `frosty`, the export time and `store_outcomes` with one entry per step

#### Scenario: Export and erasure cover the same stores

- **WHEN** the export store-walker and the erasure store-walker are enumerated
- **THEN** they cover the identical set of subject stores, so neither can silently omit a store the other includes

### Requirement: Export job status and download endpoint

ascend-ai-agent SHALL expose a status/download endpoint returning the job's status (`PENDING`, `RUNNING`, `COMPLETED`, `FAILED`), and, when complete, a means to download the assembled archive. Authorization matches the export start endpoint (self or ADMIN). Export start and completion SHALL be recorded through the audit-logging capability.

#### Scenario: Completed export is downloadable and audited

- **WHEN** the requester polls the status endpoint after the job finishes
- **THEN** the response reports status `COMPLETED` and provides the archive download
- **AND** an `EXPORT_REQUESTED` and an `EXPORT_COMPLETED` audit row exist for the subject

### Requirement: Per-tenant export for offboarding

A tenant ADMIN SHALL be able to start an export job covering their own entire tenant via `POST /api/v1/admin/tenants/{tenantId}/data/export`, and an ADMIN whose tenant differs from `{tenantId}` SHALL receive HTTP 403, using the same job machinery, store coverage, status/download endpoint, and audit semantics as per-user export, with tenant attribution supplied by `add-tenant-isolation`. A tenant export SHALL hold the per-user export of every user of the tenant, and SHALL also include the tenant's skill folders at their newest commit plus a `git bundle` of the tenant skill repository (`SkillTenantStore.exportTenant`, `add-agent-skills`), the subagent definitions at their newest commit with a `git bundle` and every `subagent_run` row of the tenant (`add-agent-subagents`), the personality file with a `git bundle` (`add-agent-soul`), every `sandbox_workspace` row and every object under `tenant/<tenantId>/sandbox-output/` in the `sandbox-output` bucket (`add-agent-sandbox`), the rows of both approval tables (`add-action-approvals`), the `obsidian_vault_file` rows as JSON without copying any file of the vault folder (`add-obsidian-vault`), every temporary download and every kept file of the tenant with its record, listed through `GET /api/v2/web/downloads` and `GET /api/v2/web/downloads/kept` (`add-file-download`), the crawl data of the tenant, read through the export endpoint `GET /api/v1/crawl/data/export` that this change adds to ascend-web-hunter with the header `X-Ascend-Tenant` and never with the agent's own storage client: every crawl job of the tenant still retained with its record, every object under `tenant/<tenantId>/` in the crawl results bucket `web-hunter-crawls`, the crawl progress of jobs still running and the recrawl state (`enhance-web-search-crawl-at-scale`), every `coding_project` and `coding_run` row, every object under `tenant/<tenantId>/coding/` in the `coding-output` bucket and one gzip tar archive of every project folder of the tenant, fetched through the archive call of the sandbox runner (`add-coding-agent-delegation`), every `self_review`, `self_change`, `self_check_case` and `self_capability_use` row as JSON (`add-self-improvement`), and everything integration erasure removes for the tenant (`add-self-built-integrations`): every integration row with its versions, destinations, credentials (never a secret value) and tool reviews (the tenant's `approval_rule` rows of kind `integration_tool_review`), the tenant's integration repository folder as its files at the newest commit plus a `git bundle`, and every build report under `tenant/<tenantId>/integration-builds/`. Capability index entries, integration images and runner objects are derived data and SHALL NOT be exported.

#### Scenario: Tenant export then erase

- **WHEN** an ADMIN exports tenant `acme`, downloads the archive, and then runs tenant erasure
- **THEN** the export archive contains tenant `acme`'s data and the subsequent erasure leaves zero residue for `acme`

#### Scenario: Tenant export holds the stores only the tenant erasure removes

- **WHEN** an ADMIN exports tenant `acme`, which has one sandbox output archive, one kept file, one temporary download, one `obsidian_vault_file` row and one integration whose `created_by` is null
- **THEN** the archive manifest lists the sandbox output archive, the kept file and the temporary download with their records, the `obsidian_vault_file` row and the integration
- **AND** no file of the vault folder is in the archive

#### Scenario: Tenant export holds the crawl results of the tenant

- **WHEN** an ADMIN exports tenant `acme`, which has one succeeded crawl job, and tenant `globex` has one succeeded crawl job
- **THEN** the archive manifest lists the crawl job of `acme` with its record, and the archive holds its `pages.ndjson` and page files from `tenant/acme/` in `web-hunter-crawls` and the recrawl state of `acme`, all read through `GET /api/v1/crawl/data/export` with `X-Ascend-Tenant: acme`
- **AND** no object under `tenant/globex/` is in the archive

#### Scenario: Export holds coding project folders and integration sources

- **WHEN** an ADMIN exports tenant `acme`, which has one coding project folder created by `frosty`, one integration with one version and one build report
- **THEN** the archive holds one gzip tar archive of that project folder, fetched through the archive call of the sandbox runner
- **AND** the per-user export of `frosty` inside it holds the same project folder archive
- **AND** the archive holds the integration rows, the files and a `git bundle` of the tenant's integration repository and the build report, and no secret value

### Requirement: Coding project folders join erasure and export

Export SHALL cover everything erasure covers for the stores of `add-coding-agent-delegation`. User erasure SHALL stop the user's running coding runs and then delete the user's `coding_project` and `coding_run` rows, their stored results and the project folders the user created, and tenant erasure SHALL do the same for every project of the tenant and its folder `tenants/<tenantId>/`. User export SHALL hold the user's project and run rows, their stored results and one gzip tar archive of each project folder the user created, and tenant export SHALL hold the same for every project of the tenant. An archive SHALL never be taken while a workspace mounts the project, and SHALL never hold a file from outside the project folder.

#### Scenario: User export holds the project folders

- **WHEN** a user who created two coding projects is exported
- **THEN** the export holds both project rows, their runs and their stored results
- **AND** it holds one archive per project whose files match the project folder

#### Scenario: Tenant export holds only the tenant's folders

- **WHEN** tenant `acme` is exported while tenant `globex` also has coding projects
- **THEN** the export holds an archive of every project folder of `acme` and none of `globex`
