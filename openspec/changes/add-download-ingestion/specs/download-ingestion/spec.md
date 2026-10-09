## Purpose

Lets the owner make one downloaded file searchable in the tenant's knowledge base on request, without the download service depending on the agent and without indexing every download.

## ADDED Requirements

### Requirement: Opt-in ingestion of one download

ascend-ai-agent SHALL offer the agent native tool `knowledge_add_download` with a `download_id`, and the REST endpoint `POST /api/v1/documents/from-download` with a `download_id` and an optional `embedding_provider`, open to the roles that may upload a document: the endpoint SHALL require `USER` or `ADMIN`, the rule of `POST /api/v1/ingestion/upload` in the authorization matrix of `add-keycloak-login`, as this change's own row in that matrix, and a caller without either role SHALL receive HTTP 403. A download SHALL be added to the knowledge base only through this tool or endpoint. The id SHALL be looked up first as a temporary download and, when that is gone, as a kept file of the tenant. The tool and the endpoint SHALL exist only while the module `web-download` is in `ASCEND_MODULES`. The knowledge base they write to belongs to `rag`, which is always on and is never a switchable module (owner decision of 2026-10-03). The tenant SHALL be the caller's tenant from `TenantContext.currentTenantId()`, which is `default` in a personal deployment. On success the agent SHALL copy the file into the tenant's knowledge base, register it as a document with source type `web-download` and the download's `source_url` as its origin, start its indexing, and answer HTTP 202 with the `document_id` and the `run_id`.

#### Scenario: A downloaded datasheet becomes searchable

- **WHEN** the owner asks to add a stored PDF download to the knowledge base
- **THEN** the answer is 202 with a `document_id` and a `run_id`
- **AND** after the run finishes, a prompt about the datasheet's content retrieves passages from it

#### Scenario: A kept file is ingested after its download was deleted

- **WHEN** a file was kept, its temporary download was deleted 24 hours after its last download, and the owner asks to add it to the knowledge base
- **THEN** the answer is 202 with a `document_id` and a `run_id`, copied from the kept file

#### Scenario: Downloads are not indexed by default

- **WHEN** a file is downloaded and nobody calls the ingestion tool or endpoint for it
- **THEN** no document is registered for it and no chunk of it is in the vector store

### Requirement: Ingestion stays inside the caller's tenant

The agent SHALL read the download record for the caller's tenant only, SHALL refuse a record whose storage key does not start with `tenant/<caller tenant>/`, and SHALL store the copy in the `documents` folder under the tenant prefix of the agent's ingestion path (no tenant segment before `add-tenant-isolation`, `tenant/<caller tenant>/` after it). An unknown download id, an id of another tenant, or a record whose storage key does not start with `tenant/<caller tenant>/` SHALL be answered with HTTP 404 and code `download_not_found`. A missing or unreadable request body SHALL be answered with HTTP 400 and the existing code `bad_request`. When ascend-web-hunter cannot be reached, times out or answers with a server error, the agent SHALL answer HTTP 503 with the shared code `unavailable` and SHALL copy nothing.

#### Scenario: Web-hunter is down

- **WHEN** the owner asks to ingest a download while ascend-web-hunter does not answer
- **THEN** the answer is 503 `unavailable` and nothing is copied or registered

#### Scenario: Refusals are problem details

- **WHEN** a caller asks to ingest an unknown download id or sends an empty body
- **THEN** the answer is an `application/problem+json` body with `code` `download_not_found` (HTTP 404) or `bad_request` (HTTP 400) and a `traceId`
- **AND** no document row is written

#### Scenario: Another tenant's download

- **WHEN** a caller of tenant `globex` asks to ingest a download held only by tenant `acme`
- **THEN** the answer is 404 `download_not_found` and nothing is copied

### Requirement: Only ingestible families

Downloads of family `pdf`, `office`, `text` or `image` SHALL be accepted. A download of family `archive` SHALL be refused with HTTP 422 and code `download_not_ingestible`.

#### Scenario: Archive refused

- **WHEN** the owner asks to ingest a zip archive download
- **THEN** the answer is 422 `download_not_ingestible`

### Requirement: Repeated ingestion is idempotent

When the same download was already added for the tenant, the agent SHALL answer HTTP 200 with the existing `document_id` and SHALL NOT copy or register it again.

#### Scenario: Added twice

- **WHEN** the owner asks to ingest the same download twice
- **THEN** the second answer is 200 with the first answer's `document_id`

### Requirement: The download tools follow the module switch on the agent side

The agent's server entry `app.mcp.servers.ascend-web-hunter` SHALL mark each `web_download_*` tool with the module `web-download` through the per tool module override `tools.overrides.<tool>.module` of `add-mcp-tool-servers`, so a tenant without the module grant is never offered them. `knowledge_add_download`, `POST /api/v1/documents/from-download` and the agent's download client SHALL carry `@ConditionalOnModule("web-download")` alone.

#### Scenario: Tenant without the module grant

- **WHEN** a chat request runs for a tenant that does not hold the module `web-download` while ascend-web-hunter lists the `web_download_*` tools
- **THEN** no `web_download_*` tool and no `knowledge_add_download` is in the tool list given to the model
