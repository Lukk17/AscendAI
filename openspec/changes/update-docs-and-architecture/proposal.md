# Update Docs and Architecture

## Why

The platform is being reshaped by a long list of changes. Each one updates the documents it touches, but no change owns the whole picture: the system-level architecture, the request-path diagrams, the decision record index, the README front door and the documentation map. Without one owner the documents end up correct in pieces and wrong as a whole.

Build order (owner build order of 2026-10-04, which supersedes the earlier orders): build group 5 (company), position 10, the last change of all, directly after `plan-scaled-deployment` (position 9, order decision of 2026-10-09 for owner answer 99.1), which it documents too. It needs every other change, and it documents the system that exists after them: build group 1 (finish started work), build group 2 (web-hunter), build group 3 (base), build group 4 (personal) and the company changes of build group 5 before it, `add-customer-stack-installer` last among them. The order of 2026-10-01 (groups A, B and D, `harden-cloud-deployment`, group C, `add-document-connectors`, `add-customer-stack-installer`, then this change) is superseded by the owner build order of 2026-10-04.

The numbered order of the planned agent changes of 2026-10-02 (with number 2 inserted by owner answer 56 and number 3 by owner answer 60.6 of 2026-10-03) is superseded by the owner build order of 2026-10-04. The planned changes are listed below by their build group.

## Changes it consolidates

Active changes under `openspec/changes/`:

- `fix-linux-docker-host-access`: everything that breaks on Linux Docker Engine fixed, the rule for reaching the host from a container, and the configuration reference `docs/CONFIGURATION.md` (build group 1)
- `harden-cloud-deployment`: gateway, loopback ports, secrets, object store privacy
- `add-keycloak-login`: Keycloak on its own host address, password sign-in, the resource server, the roles and the service token (personal)
- `add-auth-and-identity`: the tenant claim, group principals, brokering, Keycloak Organizations and SAML (company)
- `add-tenant-isolation`
- `add-tenant-policy`
- `add-tenant-administration`
- `add-audit-and-gdpr-compliance`
- `add-usage-metering-and-quotas`
- `add-document-management-api`: documents and the content download endpoint
- `add-connector-framework`: the connector framework (personal)
- `add-document-connectors`: the SharePoint connector (company)
- `add-download-ingestion`: adding one download to the knowledge base (personal)
- `add-chat-streaming-and-conversations`: `POST /api/v1/ai/prompt/stream` and conversations
- `add-passage-level-citations`
- `add-observability`: loki, otel-collector (which also collects the container logs into Loki, Vector removed by owner answer 89.12 of 2026-10-08), tempo, container-metrics-exporter, prometheus, grafana
- `add-github-actions-pipeline`: CI and the release workflow
- `add-flutter-chat-app`: including on-device voice input on Android and iOS, which sends text and never audio
- `add-customer-stack-installer`: `deploy/`, with the module question
- web search: `enhance-web-search-extraction-and-tiers`, `enhance-web-search-crawl-at-scale`, `detect-challenge-walls-in-any-language`, `open-several-novnc-windows-at-once`, `add-web-search-scraping-e2e`
- `plan-scaled-deployment`: the Kubernetes Helm chart `deploy/helm/ascend-ai/` with a Horizontal Pod Autoscaler for `ascend-agent`, `ascend-web-hunter`, `ascend-ocr`, `ascend-audio-scribe` and `ascend-memory`, the NoVNC router, the sandbox runner per node and the prerequisites as external services or optional subcharts, for scaled company deployments (company, build group 5, position 9, owner answer 99.1)

The planned changes, by build group of the owner build order of 2026-10-04:

Build group 2 (web-hunter):

- `add-ascend-python-common`: the shared Python library `libs/ascend-python-common` that all four Python services import
- `add-python-runtime-upgrades`: FastAPI, uvicorn, FastMCP 4 and the MCP Python SDK 2 for all four Python services, set once in the shared library
- `enhance-web-search-tier-ladder`: two new patched-browser tiers in the extraction ladder of ascend-web-hunter
- `remove-flaresolverr-tier`: the FlareSolverr tier and its container removed
- `add-web-session-import`: importing a browser login session into ascend-web-hunter
- `add-file-download`: web file downloads, their 24-hour retention inside ascend-web-hunter and the `clamav` companion (web-hunter only since 2026-10-04, its agent part is `add-download-ingestion`)
- `scale-web-hunter-across-containers`: ascend-web-hunter as several containers of one compose service behind the edge proxy `ascend-web-hunter-edge`, which publishes port 7021 and routes each NoVNC window to its container, in the development stack and in the standalone bundle

Build group 3 (base):

- `close-agent-test-gaps`: the missing agent tests and the shared end-to-end harness with the scripted model and the fake MCP server
- `upgrade-spring-boot-4`: Spring Boot 4.1.1, Spring AI 2.0.1, Flyway in place of Liquibase, RFC 7807 problem details for every error body
- `scale-ocr-and-audio-across-containers`: ascend-ocr job records and queue in Redis, submitted files in object storage, ascend-audio-scribe transcript downloads in the bucket `audio-transcripts`, and every job visible from any container
- `add-deployment-modules`: the always-on core (chat, document search, memory, the sandbox, monitoring and the prerequisites), the catalog of switchable modules, `COMPOSE_PROFILES` as the one switch, presets, `GET /api/v1/modules`, `docs/MODULES.md`, and the company extension ports `AuditEventPort`, `UsageEventPort`, `QuotaGate` and `ModelAccessPolicy`
- `add-shared-scheduler`: the shared scheduler engine and owner notifications

Build group 4 (personal):

- `add-agent-skills`: skills and the capability index
- `add-agent-subagents`: subagent definitions, runs and the price table at `infra/pricing/pricing.yaml`
- `add-agent-sandbox`: `ascend-sandbox-runner` with gVisor workspaces
- `add-agent-soul`: the agent's personality and user facts
- `add-action-approvals`: owner approval of actions
- `add-mcp-tool-servers`: MCP server entries and `mcp-egress-proxy`
- `add-obsidian-vault`: `obsidian-sync` and the Obsidian connector
- `add-openclaw-plugin-host`: `ascend-openclaw-host` for chat platforms and app plugins, and the gateway webhook routes
- `add-coding-agent-delegation`: coding runs with OpenCode and the coding project area
- `add-scheduled-tasks`: the assistant's own scheduled jobs
- `add-self-improvement`: self-improvement reviews and change records
- `add-self-built-integrations`: integrations the agent builds, the `integrations-ingress` network
- `add-web-crawl-rag-connector`: a connector that crawls a website into the knowledge base

Already archived and also reflected in the end state:

- the OCR job API and its result store (`archive/2026-10-01-read-long-documents`, `archive/2026-10-01-stop-ocr-getting-stuck-on-large-jobs`, `archive/2026-10-01-fix-ocr-page-resolution`, `archive/2026-10-01-upgrade-ocr-to-ppocrv6`)
- the web search scraping work (`archive/2026-09-18-enhance-web-search-scraping`, `archive/2026-09-18-close-web-search-scraping-follow-ups`, `archive/2026-09-19-follow-relative-redirects`)
- `archive/2026-09-04-replace-minio-with-floci`, `archive/2026-09-19-add-mcp-startup-tolerance`

The implementer runs `openspec list` at start, because changes may have been archived or added since this list was written, and documents the set that exists then.

## What Changes

- One mechanism per job (owner answers 87 to 93 of 2026-10-08, design D7): every document names the one mechanism each job now has, and no document describes a removed second mechanism: logs through the OpenTelemetry collector (no Vector), one chat executor, one ingestion path, one local timer mechanism next to the shared scheduler, one approval record, one catalog for skills and subagent definitions, one notification path, one slot pool, one retention task, one tenant policy service, one usage path with one encrypted secret store, one production startup guard, one schema owner, one price source, one tracing switch, one Keycloak Admin API fake, the multi-instance rule, the deterministic test phase that copies the test overlay into the running agent, restarts only the agent and fakes AscendMemory in the one Mockoon container, and tenant isolation starting from empty stores with no tenant backfill.
- Configuration reference (owner rule 98 of 2026-10-08, design D7): every setting of every service has exactly one row, in `docs/CONFIGURATION.md` of `fix-linux-docker-host-access` or in the service's own reference that it links, and every document that names a setting links that row instead of repeating its default.
- Monorepo architecture (`docs/architecture/`): the five arc42 files, the two diagrams that exist (`diagrams/system-overview.md`, `diagrams/prompt-flow.md`) and a new `diagrams/document-ingestion-flow.md`, plus monorepo decision records (`ADR-M011` onward) for the decisions these changes made.
- Agent internal architecture (`apps/ascend-agent/docs/architecture/`): the twelve arc42 files, the four C4 diagrams in `diagrams/`, and the decision record index.
- READMEs: root and every module README follow the documentation standard with a complete documentation map.
- `AGENTS.md` files: root and per module match the shipped endpoints, roles, ports and compose services.
- API surface: the OpenAPI document generated by springdoc at build time is exported to `docs/api/openapi.json`, and the Bruno collection under `docs/api/request/AscendAI/` covers every shipped endpoint group.
- Modules: the root README documentation map links `docs/MODULES.md` of `add-deployment-modules`, and every service table and the container view name the module of each service, or "core" for an always-on service (design D6). Tenant policy, metering, audit and the other company parts are neither core nor modules: each company change adds its own parts to the deployment, and the documents name them as company parts.
- End-to-end documentation: `docs/E2E_RUN_SCENARIOS.md`, every app suite README under `apps/*/e2e/` and the platform suite README `e2e/platform/README.md` list every numbered spec the earlier changes added, with counts that match the files on disk, every Bruno request a spec names exists, the app suite READMEs say that "immutable" means a spec is not edited during or between the runs of one sweep while a changed feature updates its spec in place (owner answer 67.2 of 2026-10-04), and the README quick start becomes a repeatable spec of the platform suite.

## Capabilities

### New Capabilities

- `platform-documentation`: architecture documents and diagrams match the shipped topology, decision records cover the load-bearing decisions, request-path diagrams match the new flows, READMEs follow the standard with a complete map, `AGENTS.md` files match the shipped surface, the OpenAPI document is generated and exported, and pending work is marked pending.

### Modified Capabilities

None. `rag-documentation` covers RAG source attachment documents only and stays unchanged.

## Impact

- Documents only, plus one build change: an `openApi { }` block in `apps/ascend-agent/build.gradle.kts` for the springdoc Gradle plugin that is already applied (`org.springdoc.openapi-gradle-plugin` 1.9.0).
- Files: `docs/architecture/**`, `apps/ascend-agent/docs/architecture/**`, every `README.md`, every `AGENTS.md`, `docs/api/openapi.json`, `docs/api/request/AscendAI/**`.
- No application behavior changes.

## Relevant Skills

- `/markdown-writer`
- `/e2e-runbooks`
- `/architecture-decision-records`
- `/api-design`
- `/springboot-patterns`
- `/java-coding-standards`
