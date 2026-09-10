## ADDED Requirements

### Requirement: Architecture docs and diagrams reflect the shipped topology

The monorepo architecture docs (`docs/architecture/`) and the ascend-ai-agent internal architecture docs SHALL depict the end-state topology: the edge gateway as the only public surface, Keycloak as the identity provider, the tenant boundary across every data plane, and the connector/crawl paths into RAG. The C4 diagrams SHALL be text-based (Mermaid) and SHALL match the shipped compose topology and endpoint set.

#### Scenario: Container diagram shows the gateway and identity provider

- **WHEN** the C4 container diagram is reviewed against the shipped `compose.yaml`
- **THEN** it shows the gateway as the only public entry point and Keycloak as the identity provider
- **AND** no service other than the gateway is shown as publicly reachable

#### Scenario: Tenant boundary is depicted

- **WHEN** the architecture docs are reviewed
- **THEN** they show the tenant boundary applied to RAG, storage, chat history, and memory

### Requirement: ADRs record the load-bearing decisions

The architecture decision records SHALL include entries for the initiative's load-bearing decisions: the gateway-only public surface, the presign resolution to an authenticated agent content endpoint, the tenant model, tenant administration, per-tenant policy, and the scraper tier-ladder restructure.

#### Scenario: Presign-resolution decision is recorded

- **WHEN** the ADR index is reviewed
- **THEN** an ADR records the decision to serve RAG source downloads through the authenticated agent content endpoint with presigning demoted to in-network use

### Requirement: Request-path diagrams match the new flows

The documentation SHALL include current "path of one request" diagrams for the flows whose shape changed: an authenticated streamed chat turn with RAG source attachments served via the content endpoint, and a document flowing through ingestion/connector into tenant RAG.

#### Scenario: Streamed-chat request path is current

- **WHEN** the streamed-chat request-path diagram is reviewed
- **THEN** it shows the authenticated request through the gateway, streaming SSE, and source attachments referencing the content endpoint (not a presigned object-store URL)

### Requirement: READMEs follow the standard and the documentation map is complete

The root `README.md` SHALL follow the documentation standard (quick-start including auth, honest alternatives comparison, configuration/ports reflecting the gateway and loopback bindings, changing counts in badges) and SHALL carry a documentation map linking every shipped doc, with every link resolving. Each module `README.md` SHALL reflect its end-state surface.

#### Scenario: Documentation map links resolve

- **WHEN** the root README documentation map is checked
- **THEN** every listed document exists at the linked path
- **AND** `SECURITY.md`, `COMPLIANCE.md`, `CONNECTORS.md`, `USAGE_AND_QUOTAS.md`, `DEPLOYMENT.md`, `MCP_SETUP.md`, and the deploy run-book are all linked

#### Scenario: Counts live in badges

- **WHEN** the README is reviewed for changing numbers (service, endpoint, capability counts)
- **THEN** those counts appear in badges, not hard-coded in prose

### Requirement: AGENTS.md and the API collection match the shipped surface

The root and per-module `AGENTS.md` SHALL match the shipped endpoints, roles, ports, compose services, and capability matrix. The OpenAPI specification and the Bruno collection SHALL cover the full end-state endpoint set (auth token flow, conversations, documents + content download, ingestion runs, usage, audit, erasure/export, admin tenant/user/policy, connectors, crawl).

#### Scenario: AGENTS.md matches reality

- **WHEN** the compose service table and port list in `AGENTS.md` are compared to the shipped compose files
- **THEN** they match, including the gateway and the loopback-bound service ports

#### Scenario: Bruno collection covers every shipped endpoint

- **WHEN** the Bruno collection is compared to the shipped endpoint set
- **THEN** there is a request for every shipped endpoint group, including admin tenant/user/policy and the content-download endpoint

### Requirement: Documentation describes reality and flags the pending

Where a dependency in the initiative has not yet shipped, the documentation SHALL describe what exists and mark the rest pending; it SHALL NOT describe unshipped behavior as shipped.

#### Scenario: Unshipped dependency is flagged, not asserted

- **WHEN** a documented feature depends on a change that is not yet implemented
- **THEN** the docs mark that feature pending rather than describing it as available
