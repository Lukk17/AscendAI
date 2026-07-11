# Tasks — update-docs-and-architecture

## 1. Monorepo architecture and ADRs

- [ ] 1.1 Update `docs/architecture/` arc42 sections for the end-state topology (gateway-only public surface, Keycloak, tenant boundary across every data plane, connector/crawl paths, metering/audit cross-cuts)
- [ ] 1.2 Refresh the C4 diagrams (context + container) as Mermaid to show the gateway, Keycloak, and the tenant boundary
- [ ] 1.3 Add/refresh ADRs for the load-bearing decisions: gateway-only surface, presign resolution to the agent content endpoint, tenant model, tenant administration, per-tenant policy, scraper tier-ladder restructure
- [ ] 1.4 Verify each diagram against the shipped compose topology and endpoint set

## 2. AscendAgent internal architecture

- [ ] 2.1 Update `AscendAgent/docs/architecture/` component diagrams and internal arc42 for the new packages (auth, tenant, admin, policy, usage, audit, erasure, export, streaming, document management, connector)
- [ ] 2.2 Update the module-level ADR index

## 3. Cross-cutting request-path diagrams

- [ ] 3.1 Add/refresh a Mermaid diagram for an authenticated streamed chat turn with RAG source attachments served via the content endpoint
- [ ] 3.2 Add/refresh a Mermaid diagram for a document flowing through ingestion/connector into tenant RAG

## 4. READMEs and documentation map

- [ ] 4.1 Bring the root `README.md` into line with the documentation standard: quick-start including auth, honest alternatives comparison, configuration/ports reflecting the gateway and loopback bindings, counts in badges
- [ ] 4.2 Update each module `README.md` for its end-state surface
- [ ] 4.3 Complete the documentation map linking every shipped doc (`SECURITY.md`, `COMPLIANCE.md`, `CONNECTORS.md`, `USAGE_AND_QUOTAS.md`, `DEPLOYMENT.md`, `MCP_SETUP.md`, `deploy/README.md`); verify every link resolves

## 5. AGENTS.md reconciliation

- [ ] 5.1 Reconcile root and per-module `AGENTS.md` with the shipped endpoints, roles, ports, compose services, and capability matrix

## 6. API surface docs

- [ ] 6.1 Ensure the OpenAPI specification covers the full end-state endpoint set (auth token flow, conversations, documents + content download, ingestion runs, usage, audit, erasure/export, admin tenant/user/policy, connectors, crawl)
- [ ] 6.2 Ensure the Bruno collection under `docs/api/request/AscendAI/` exercises every shipped endpoint
- [ ] 6.3 Verify: README quick-start works against a freshly installed stack; the Bruno collection runs green end-to-end

## 7. Pending-aware pass

- [ ] 7.1 For any dependency not yet shipped, document what exists and mark the rest pending — never describe unshipped behavior as shipped
