## ADDED Requirements

### Requirement: Tenant crawl data erase and export calls

ascend-web-hunter SHALL expose the internal REST calls `DELETE /api/v1/crawl/data` and `GET /api/v1/crawl/data/export`, each acting on the one tenant named by the header `X-Ascend-Tenant`. A call without that header, or with a value outside `[a-z0-9-]{1,64}`, SHALL be refused with HTTP 400 `invalid_tenant` and SHALL NOT fall back to the tenant `default`. Neither call SHALL be offered as an MCP tool. The erase call SHALL first cancel every `waiting` or `running` job of the tenant, which removes it from the shared set `crawl_runnable` and stops its workers on every ascend-web-hunter instance, SHALL wait until no worker of those jobs is writing, at most `CRAWL_ERASE_DRAIN_SECONDS`, and SHALL otherwise answer HTTP 503 `crawl_erase_busy` with `Retry-After` before deleting anything. It SHALL then delete every result object of the tenant, every Redis key that matches `crawl_*:{tenantId}:*` (the frontier, claims, next fetch and pages keys of its jobs), its recrawl state and, last, its job records, and SHALL answer HTTP 200 with the counts. A repeated erase call SHALL finish a half-done one and SHALL answer zero counts after a complete one. The export call SHALL stream one gzip tar archive holding every retained job record of the tenant, its result objects, the frontier of every job that still has one, its recrawl state and a manifest as the last entry, and SHALL NOT cancel a running job. When the object store or Redis cannot be reached before the answer starts, either call SHALL answer HTTP 503 `storage_unavailable`. When a read fails after the export answer has started, the stream SHALL stop without the closing tar blocks. Neither call SHALL list, read or delete the data of another tenant, and no call SHALL act on a single user, because a crawl job holds no user id.

#### Scenario: Erase removes one tenant's crawl data

- **WHEN** tenant `acme` has one running and one succeeded crawl job with recrawl state, tenant `globex` has one succeeded crawl job, and the agent calls `DELETE /api/v1/crawl/data` with `X-Ascend-Tenant: acme`
- **THEN** the answer is HTTP 200 with `jobs_cancelled` 1 and `jobs_deleted` 2
- **AND** no object under `tenant/acme/` remains in `CRAWL_RESULT_S3_BUCKET`, and no frontier key, recrawl state or job record of `acme` remains
- **AND** every object, key and job record of `globex` is unchanged

#### Scenario: A repeated erase finds nothing

- **WHEN** the erase call for tenant `acme` has completed and the agent calls it again
- **THEN** the answer is HTTP 200 with every count zero

#### Scenario: A worker still writing holds the erase back

- **WHEN** a worker of a cancelled job of `acme` is still writing a page after `CRAWL_ERASE_DRAIN_SECONDS`
- **THEN** the answer is HTTP 503 with `code` `crawl_erase_busy` and a `Retry-After` header
- **AND** no object of `acme` was deleted by that call

#### Scenario: A call without a tenant header is refused

- **WHEN** the agent calls `DELETE /api/v1/crawl/data` or `GET /api/v1/crawl/data/export` without `X-Ascend-Tenant`
- **THEN** the answer is HTTP 400 with `code` `invalid_tenant`
- **AND** no data of the tenant `default` is deleted or exported

#### Scenario: Export holds one tenant's crawl data

- **WHEN** tenant `acme` has one succeeded crawl job with recrawl state, tenant `globex` has one succeeded crawl job, and the agent calls `GET /api/v1/crawl/data/export` with `X-Ascend-Tenant: acme`
- **THEN** the archive holds `jobs/<job_id>/job.json`, `jobs/<job_id>/pages.ndjson`, the page files of that job and the recrawl state of `acme`, with `manifest.json` as the last entry
- **AND** the archive holds nothing of `globex`

#### Scenario: The calls are not MCP tools

- **WHEN** a client lists the MCP tools of ascend-web-hunter
- **THEN** no tool erases or exports crawl data
