## ADDED Requirements

### Requirement: Web connector crawls a site into tenant RAG through the existing framework

A `web` connector type SHALL be available in the `add-document-connectors` framework, configured with seed URLs / patterns and a sync schedule. On each scheduled run it SHALL trigger an ascend-web-hunter crawl, land the crawl output in the tenant's MinIO prefix, and trigger the existing ingestion pipeline — the framework's land-bytes-then-ingest contract. The connector SHALL NOT parse, chunk, or embed content itself and SHALL NOT write to Qdrant directly.

#### Scenario: Scheduled crawl lands in tenant RAG

- **WHEN** a `web` connector for tenant `acme` runs on schedule against a documentation site
- **THEN** the crawl output is written to MinIO under tenant `acme`'s prefix
- **AND** the existing ingestion pipeline indexes it into tenant `acme`'s RAG collections through the standard parse path

#### Scenario: No parallel parse path

- **WHEN** the web connector processes a crawled PDF page
- **THEN** the PDF is parsed by the existing `DocumentRouter` path, not a crawler-local parser

### Requirement: Web connector propagates source deletions and inherits tenant isolation

When a previously crawled source page is gone on a later run, the web connector SHALL remove the corresponding MinIO object and its Qdrant chunks using the single-document deletion path owned by `add-document-management-api`, recorded as a `DELETED` per-file outcome. All landing SHALL occur under the caller tenant's prefix, inheriting tenant isolation from the connector framework.

#### Scenario: Removed source page propagates

- **WHEN** a page that a web connector previously landed is no longer reachable on the next run
- **THEN** its MinIO object and Qdrant chunks are removed
- **AND** the run history shows a `DELETED` outcome for it

#### Scenario: Output stays within the tenant prefix

- **WHEN** a web connector for tenant `acme` lands crawl output
- **THEN** every landed object key is under tenant `acme`'s prefix and no other tenant's prefix
