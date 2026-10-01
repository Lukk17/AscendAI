## ADDED Requirements

### Requirement: Architecture docs and diagrams reflect the shipped topology

The monorepo architecture documents (`docs/architecture/`) and the agent internal architecture documents (`apps/ascend-agent/docs/architecture/`) SHALL depict the end-state topology: the edge gateway as the only public surface, Keycloak as the identity provider on its own host address, the tenant boundary across every data plane, the connector and crawl paths into RAG, the OCR job API with its result store, and the observability services. Diagrams SHALL be Mermaid text and SHALL match the shipped compose services and endpoint set. The monorepo diagrams SHALL be `diagrams/system-overview.md`, `diagrams/prompt-flow.md` and `diagrams/document-ingestion-flow.md`.

#### Scenario: Container view shows the gateway and identity provider

- **WHEN** `docs/architecture/diagrams/system-overview.md` is compared with `docker compose config --services`
- **THEN** it shows the gateway as the only public entry point and Keycloak on its own host address
- **AND** no other service is shown as publicly reachable

#### Scenario: Tenant boundary is shown

- **WHEN** the architecture documents are reviewed
- **THEN** they show the tenant boundary applied to RAG, storage, chat history and memory

### Requirement: Decision records cover the load-bearing decisions

The monorepo decision records SHALL include entries for the gateway-only public surface, the private object store with downloads through the authenticated agent content endpoint, the tenant model, tenant administration, per-tenant policy and the web search tier ladder, and every decision index SHALL list every record file in its folder.

#### Scenario: Object store decision is recorded

- **WHEN** `docs/architecture/decisions/README.md` is reviewed
- **THEN** it lists a record stating that RAG source downloads go through the agent content endpoint and that presigned links are used only inside the private network

### Requirement: Request-path diagrams match the new flows

The documentation SHALL include a path-of-one-request diagram for an authenticated streamed chat turn with sources served through the content endpoint, and one for a document flowing from upload or connector through ingestion into tenant RAG.

#### Scenario: Streamed chat path is current

- **WHEN** `docs/architecture/diagrams/prompt-flow.md` is reviewed
- **THEN** it shows the request through the gateway with a Keycloak token, `POST /api/v1/ai/prompt/stream`, and sources pointing at the content endpoint, not at a presigned object store link

### Requirement: READMEs follow the standard and the documentation map is complete

The root `README.md` SHALL follow the documentation standard and SHALL carry a documentation map linking every shipped document, with every link resolving. Changing counts SHALL appear only in badges. Each module README SHALL match its end-state surface.

#### Scenario: Map links resolve

- **WHEN** a link checker runs over the root `README.md`
- **THEN** every link resolves
- **AND** every `docs/*.md` file and `deploy/README.md` appear in the map

#### Scenario: Counts live in badges

- **WHEN** the README prose is searched for service, endpoint or capability counts
- **THEN** none is found outside badges

### Requirement: The OpenAPI document is generated at build time and committed

The agent build SHALL export the OpenAPI document that springdoc generates to `docs/api/openapi.json` through the springdoc Gradle plugin's `generateOpenApiDocs` task, and the committed file SHALL cover every shipped endpoint group.

#### Scenario: The export task writes the file

- **WHEN** `./gradlew generateOpenApiDocs` runs in `apps/ascend-agent`
- **THEN** `docs/api/openapi.json` is written and is a valid OpenAPI 3 document

### Requirement: AGENTS.md and the Bruno collection match the shipped surface

The root and per-module `AGENTS.md` SHALL match the shipped endpoints, roles, ports, compose services and capability matrix. The Bruno collection SHALL hold a request for every path in `docs/api/openapi.json`.

#### Scenario: AGENTS.md matches compose

- **WHEN** the compose tables in the root `AGENTS.md` are compared with `docker compose config`
- **THEN** the services and port bindings match, including the gateway and the loopback-bound ports

#### Scenario: Bruno covers every path

- **WHEN** the paths in `docs/api/openapi.json` are compared with the Bruno request files
- **THEN** every path has a request

### Requirement: Documentation describes reality and marks the pending

Where a consolidated change has not shipped, the documentation SHALL describe what exists and mark the rest "Pending: <change name>". It SHALL NOT describe unshipped behavior as shipped.

#### Scenario: Unshipped change is marked

- **WHEN** a documented feature depends on a change that is not implemented
- **THEN** the documentation marks it pending with the change name
