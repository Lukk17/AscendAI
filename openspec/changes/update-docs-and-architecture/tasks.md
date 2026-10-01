# Tasks - Update Docs and Architecture

Build order: last, after `add-customer-stack-installer`. Load the skills in the proposal's Relevant Skills section first. Follow the documentation standard in the owner's global rules: plain words, no em or en dashes, one command per code block.

## 0. Scope

- [ ] 0.1 Run `openspec list` and list `openspec/changes/archive/`, and update the "Changes it consolidates" list in `openspec/changes/update-docs-and-architecture/proposal.md` to what exists. Acceptance: every change named there exists either as an active folder or in the archive, and each active one is marked shipped or pending.

## 1. Monorepo architecture and decision records

- [ ] 1.1 Update the five files in `docs/architecture/arc42/` for the end state: gateway as the only public surface, Keycloak on its own host address, tenant boundary on RAG, storage, chat history and memory, connector and crawl paths, OCR job API with its result store, observability services, metering and audit. Acceptance: each file names only services that appear in `docker compose config --services` or in the data-store prerequisites.
- [ ] 1.2 Update `docs/architecture/diagrams/system-overview.md` (container view, design D2) and `docs/architecture/diagrams/prompt-flow.md` (authenticated streamed chat turn), and add `docs/architecture/diagrams/document-ingestion-flow.md`. All three in Mermaid. Acceptance: each diagram renders in the Mermaid live editor without error, and every service box matches a compose service name or a named external prerequisite.
- [ ] 1.3 Add monorepo decision records from `ADR-M011` onward in `docs/architecture/decisions/` for: gateway-only public surface, private object store with downloads through the agent content endpoint, tenant model, tenant administration, per-tenant policy, web search tier ladder, and every other load-bearing decision a consolidated change recorded only in its own design. Use `/architecture-decision-records`. Acceptance: `docs/architecture/decisions/README.md` lists every file in the folder.
- [ ] 1.4 Update `docs/architecture/README.md` to link every arc42 file, diagram and decision record. Acceptance: a link check over the file finds no broken link.

## 2. Agent internal architecture

- [ ] 2.1 Update the twelve files in `apps/ascend-agent/docs/architecture/arc42/` and the four diagrams in `apps/ascend-agent/docs/architecture/diagrams/` for the new packages (auth, tenant, admin, policy, usage, audit, erasure, export, streaming, document management, connectors, citations). Acceptance: every package named in `component-diagram.md` exists under `apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/`.
- [ ] 2.2 Update `apps/ascend-agent/docs/architecture/decisions/README.md` (or the index in `09-architecture-decisions.md`) to list every agent decision record. Acceptance: every `ADR-*.md` file in that folder is listed.

## 3. READMEs and documentation map

- [ ] 3.1 Bring the root `README.md` in line with the documentation standard: title and badges, quick start that includes signing in, architecture diagram, request-path diagram, features, honest comparison, configuration and ports (gateway on 80 and 443, loopback-bound service ports, Keycloak host port), documentation map, license. Acceptance: no service, endpoint or capability count appears in prose (`grep -nE '[0-9]+ (services|endpoints|capabilities)' README.md` finds nothing).
- [ ] 3.2 Update each module README (`apps/*/README.md`, `apps/ascend-web-hunter/deploy-standalone/README.md`, and the Flutter app README) for its end-state surface. Acceptance: every port and endpoint in each README matches that module's `AGENTS.md`.
- [ ] 3.3 Complete the documentation map in the root README: every `.md` file in `docs/` and `docs/architecture/`, every module README and `AGENTS.md`, `deploy/README.md`, and the topic documents the consolidated changes added. Acceptance: every link resolves, checked with a link checker run over `README.md`, and every `docs/*.md` file appears in the map.

## 4. `AGENTS.md` reconciliation

- [ ] 4.1 Reconcile the root `AGENTS.md` and each `apps/*/AGENTS.md` with the shipped endpoints, roles, ports, compose services and capability matrix. Acceptance: the compose service tables list exactly the services of `docker compose config --services`, and the port table matches `docker compose config` port bindings.

## 5. API surface

- [ ] 5.1 Add an `openApi { }` block to `apps/ascend-agent/build.gradle.kts` for the already applied springdoc Gradle plugin (design D5), writing `openapi.json` to the repository's `docs/api/` folder, and generate it. Acceptance: `./gradlew generateOpenApiDocs` in `apps/ascend-agent` writes `docs/api/openapi.json`, and the file is valid OpenAPI 3 (it parses as JSON and its `openapi` field starts with `3.`).
- [ ] 5.2 Confirm `docs/api/openapi.json` contains every shipped endpoint group: token-protected prompt and stream, conversations, documents and content download, ingestion runs, usage, audit, erasure and export, admin tenants, users and policy, connectors, crawl. Acceptance: a `jq '.paths | keys'` listing contains a path for each group, or the group is marked pending per task 6.1.
- [ ] 5.3 Make the Bruno collection under `docs/api/request/AscendAI/` contain a request for every path in `docs/api/openapi.json`. Acceptance: a comparison of the path list with the `.yml` request files finds no path without a request.
- [ ] 5.4 Verify the README quick start against a freshly installed stack and run the Bruno collection. Ask the owner which run scenario from `docs/E2E_RUN_SCENARIOS.md` to use before running any e2e spec. Acceptance: the quick start works step by step and the chosen run is green.

## 6. Pending-aware pass

- [ ] 6.1 For every consolidated change not yet shipped, mark the documented feature "Pending: <change name>" and describe only what exists. Acceptance: `grep -rn 'Pending:' docs README.md apps/*/README.md` lists exactly the pending changes from task 0.1.
