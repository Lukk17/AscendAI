## Why

The thirteen changes ahead of this one reshape the platform: authentication and identity, tenant isolation and administration, per-tenant policy, streaming and conversations, document management and connectors, usage metering and quotas, audit and GDPR compliance, cloud hardening, a rebuilt scraper, and an automated installer. Each change updates the docs it touches, but no change owns the whole picture — the system-level architecture, the cross-cutting request paths, the diagrams, the ADR index, the README front door, and the documentation map. Left alone, the docs end up accurate in fragments and wrong as a whole: a C4 diagram with no gateway or Keycloak, a README quick-start that predates auth, an architecture overview with no tenant boundary.

This change is the capstone. It runs last, after the others are implemented and archived, so it documents the system that actually exists rather than a moving target. Its job is coherence: every diagram, overview, and cross-reference reflects the same end state, and a new reader (customer, auditor, or engineer) can understand the platform from the docs without reading the code.

## What Changes

- **Monorepo architecture docs (`docs/architecture/`)**: refresh the arc42 sections and the C4 diagrams to show the end-state topology — the edge gateway as the only public surface, Keycloak as the identity provider, the tenant boundary across every data plane, the connector and crawl paths into RAG, and the metering/audit cross-cuts. Add or update ADRs for the decisions these changes made (gateway-only surface, presign resolution to an agent content endpoint, tenant model, per-tenant policy, tier-ladder restructure).
- **ascend-ai-agent internal architecture (`apps/ascend-ai-agent/docs/architecture/`)**: update the component diagrams and internal arc42 for the new packages (auth, tenant, admin, policy, usage, audit, erasure, export, streaming, document management) and the module-level ADRs.
- **Cross-cutting request paths**: add/refresh the "path of one request" diagrams for the flows that changed shape — an authenticated streamed chat turn with RAG source attachments via the content endpoint, and an ingestion/connector document flowing into tenant RAG.
- **READMEs (root + per module)**: bring the root `README.md` and each module README into line with the ordering/voice/section standard — quick-start that includes auth, honest alternatives comparison, configuration/ports reflecting the gateway and loopback bindings, and a complete documentation map linking every doc the platform ships (`SECURITY.md`, `COMPLIANCE.md`, `CONNECTORS.md`, `USAGE_AND_QUOTAS.md`, `DEPLOYMENT.md`, `MCP_SETUP.md`, the `deploy/` run-book).
- **AGENTS.md files**: reconcile the root and per-module `AGENTS.md` with the shipped endpoints, roles, ports, compose services, and capability matrix so the machine-facing instructions match reality.
- **API surface docs**: ensure the OpenAPI specification and the Bruno collection cover the full end-state endpoint set (auth token flow, conversations, documents + content download, ingestion runs, usage, audit, erasure/export, admin tenant/user/policy, connectors, crawl), with the numbers-in-badges rule so counts do not go stale in prose.

## Capabilities

### New Capabilities

- `platform-documentation`: the end-state documentation and architecture set is coherent and accurate — architecture docs and C4 diagrams reflect the shipped topology, ADRs record the load-bearing decisions, the request-path diagrams match the new flows, the READMEs follow the documentation standard with a complete documentation map, the AGENTS.md files match the shipped surface, and the OpenAPI/Bruno collection covers the full endpoint set.

### Modified Capabilities

(none as spec deltas — `rag-documentation` is the only archived documentation capability and it concerns RAG source-attachment docs specifically, unchanged here. This change's requirements are about platform-wide documentation coherence and are expressed as a new capability.)

## Impact

- **Depends on**: every other change in this initiative — it documents their combined end state and must run after they are implemented and archived. If a dependency slips, this change documents what exists and flags what is pending, rather than describing unshipped behavior as shipped.
- **Docs touched**: `docs/architecture/` (arc42, C4, ADRs), `apps/ascend-ai-agent/docs/architecture/`, root `README.md`, every module `README.md`, root and per-module `AGENTS.md`, and the documentation map; the OpenAPI spec and the Bruno collection under `docs/api/request/AscendAI/`.
- **No application code changes** — documentation, diagrams, and API-collection artifacts only.
- **Verification**: a documentation review that every diagram matches the shipped topology, every documentation-map link resolves, the README quick-start actually works against a freshly installed stack, and the Bruno collection exercises every shipped endpoint.

## Relevant Skills

- `/markdown-writer`
- `/architecture-decision-records`
- `/api-design`
- `/deployment-patterns`
