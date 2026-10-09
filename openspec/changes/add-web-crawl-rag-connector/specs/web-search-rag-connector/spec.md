## ADDED Requirements

### Requirement: Web connector crawls a site into tenant RAG through the existing framework

A `WEB_CRAWL` connector type SHALL be available in the `add-connector-framework` framework, configured with seed URLs / patterns and the framework's sync schedule (a five-field cron and a time zone, run on the shared scheduler of `add-shared-scheduler`). It SHALL need no credential, SHALL depend only on the switchable module `web-search`, and SHALL exist only while `web-search` is in `ASCEND_MODULES`. On each scheduled run it SHALL trigger an ascend-web-hunter crawl, land the crawl output in object storage (Floci locally) under the prefix that the framework's `TenantPrefixResolver` answers for the connector's tenant (taken from `TenantContext` of `add-keycloak-login`), supply for each landed page the `source_type` `connector:web-crawl` and the page URL as `origin_uri` for the document registry, and trigger the existing ingestion pipeline - the framework's land-bytes-then-ingest contract. The connector SHALL NOT parse, chunk, or embed content itself and SHALL NOT write to Qdrant directly. A refused configuration SHALL answer HTTP 400 with an RFC 7807 problem detail whose `code` is `validation`.

#### Scenario: Scheduled crawl lands in tenant RAG

- **WHEN** a `WEB_CRAWL` connector of tenant `default` runs on schedule against a documentation site
- **THEN** the crawl output is written to object storage (Floci locally) under the prefix the `TenantPrefixResolver` answers for tenant `default`
- **AND** the existing ingestion pipeline indexes it into the RAG collections through the standard parse path
- **AND** each landed page has a registry row with `source_type` `connector:web-crawl`, its URL as `origin_uri` and the connector id

#### Scenario: Type absent without the web-search module

- **WHEN** the agent runs without `web-search` in `ASCEND_MODULES` and an ADMIN creates a `WEB_CRAWL` connector
- **THEN** the response status is 400 with `code` `validation`

#### Scenario: No parallel parse path

- **WHEN** the web connector processes a crawled PDF page
- **THEN** the PDF is parsed by the existing `DocumentRouter` path, not a crawler-local parser

### Requirement: Web connector propagates source deletions and lands under the framework's tenant prefix

When a previously crawled source page is gone on a later run, the web connector SHALL remove the corresponding object storage (Floci locally) object and its Qdrant chunks using the single-document deletion path owned by `add-document-management-api`, recorded as a `DELETED` per-file outcome. All landing SHALL occur under the prefix that the `TenantPrefixResolver` of `add-connector-framework` answers for the connector's tenant, so a later implementation of that port changes the layout with no edit of this connector.

#### Scenario: Removed source page propagates

- **WHEN** a page that a web connector previously landed is no longer reachable on the next run
- **THEN** its object storage (Floci locally) object and Qdrant chunks are removed
- **AND** the run history shows a `DELETED` outcome for it

#### Scenario: Output stays within the tenant prefix

- **WHEN** a `TenantPrefixResolver` bean answers `tenant/acme/` for tenant `acme` and a `WEB_CRAWL` connector of tenant `acme` lands crawl output
- **THEN** every landed object key is under `tenant/acme/` and under no other prefix

#### Scenario: A refused configuration names the field

- **WHEN** an ADMIN creates a `WEB_CRAWL` connector whose seed is `ftp://example.com/`
- **THEN** the response status is 400 with an RFC 7807 problem detail, `code` `validation` and an `errors` field naming the seed
- **AND** no connector is created

#### Scenario: A manual run lands the crawl in the registry and the vector store

- **WHEN** an ADMIN starts a manual run of a `WEB_CRAWL` connector and it finishes
- **THEN** each landed page has a registry row with `source_type` `connector:web-crawl`, its URL as `origin_uri` and the connector id
- **AND** the vector store holds chunks of each landed page carrying `source_type` and `connector_id`
