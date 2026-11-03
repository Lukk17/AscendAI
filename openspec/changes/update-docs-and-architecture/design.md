# Design - Update Docs and Architecture

## Context

Documentation lives in `docs/architecture/` (five arc42 files, two diagrams `diagrams/system-overview.md` and `diagrams/prompt-flow.md`, monorepo decision records `ADR-M001` to `ADR-M010`), `apps/ascend-agent/docs/architecture/` (twelve arc42 files, four C4 diagrams `context-diagram.md`, `container-diagram.md`, `component-diagram.md`, `deployment-diagram.md`, decision records `ADR-001` to `ADR-010`), topic documents in `docs/`, the root and module `README.md` and `AGENTS.md` files, and the Bruno collection in `docs/api/request/AscendAI/`. No OpenAPI file is committed today, although the agent already applies the springdoc Gradle plugin (`apps/ascend-agent/build.gradle.kts:6`) and the springdoc web starter (`:84`).

## Goals / Non-Goals

Goals:

- One consistent end-state picture across every diagram, overview and cross-reference.
- Decision records for the load-bearing decisions of the consolidated changes.
- A documentation map where every link resolves.
- `AGENTS.md`, OpenAPI and Bruno matching the shipped surface.

Non-Goals:

- Application behavior changes.
- Redoing documents a sibling change already made correct.
- Marketing content.

## Decisions

### D1 - Run last, document reality, mark the pending

This change is build group 5, position 10 of the owner build order of 2026-10-04 (position 9 until the order decision of 2026-10-09 put `plan-scaled-deployment` before it), after every other change (proposal). The implementer starts with `openspec list` and the archive folder. Where a change has not shipped, the documents describe what exists and mark the rest with the word "Pending" and the change name. Nothing unshipped is described as shipped.

### D2 - Diagrams as Mermaid text in git

The monorepo has two diagrams. `system-overview.md` becomes the container view of the end state: the gateway as the only public entry, Keycloak on its own host address, the agent, the MCP services, ascend-ocr with its result store, the observability services, the services of the planned changes (`ascend-sandbox-runner`, `ascend-openclaw-host`, `obsidian-sync`, `mcp-egress-proxy`, `clamav`, the web-hunter edge proxy `ascend-web-hunter-edge` of `scale-web-hunter-across-containers`), and the four external data stores. Since `add-deployment-modules` the services of the always-on core carry no profile and every other service sits under the profile of its switchable module, so the view names the module of each service, or "core" (D6), and it is checked against compose with `COMPOSE_PROFILES` set to the `personal` preset, which holds every switchable module, plus the companions `redis`, `captcha-intervention` and `clamav`, so every service appears. `prompt-flow.md` becomes the path of one authenticated streamed chat turn with sources served by the content endpoint. A new `document-ingestion-flow.md` shows a document from upload or connector through ingestion (Docling, Unstructured, the OCR job API) into tenant RAG. The agent's four C4 files are updated in place.

### D3 - Counts in badges, not prose

Service, endpoint and capability counts live in README badges only.

### D4 - The documentation map is the completeness check

The root README map links every shipped document. A link check makes completeness testable.

### D5 - OpenAPI generated at build time and exported

The springdoc Gradle plugin starts the application, reads `/v3/api-docs` and writes the file. An `openApi { }` block in `apps/ascend-agent/build.gradle.kts` sets `apiDocsUrl` to `http://localhost:9917/v3/api-docs`, `outputDir` to the repository's `docs/api` folder and `outputFileName` to `openapi.json`, and passes a Spring profile that starts without external services when one exists (otherwise the task runs with the local prerequisite stack up, and the task says so). `./gradlew generateOpenApiDocs` regenerates the file. The committed file is the reviewed snapshot, and a change to the API shows up as a diff of it.

### D6 - The module of each service is documented

`add-deployment-modules` writes `docs/MODULES.md`, the one guide to the core and the switchable modules (owner answers 51 and 52 of 2026-10-03). This change does not repeat its content. It links it from the root README documentation map and from `docs/architecture/README.md`, and it names the module of each service everywhere services are listed: the compose tables of the root `AGENTS.md`, the configuration and ports section of the root README, and the container view of D2. Each row names the switchable module whose profile the service carries (`ocr`, `audio`, `web-search`, `web-download`, `weather`, `obsidian`, `channels`, `openclaw-apps`), the companion profile with its parent module (`redis`, `captcha-intervention`, `clamav`), or "core" for an always-on service with no profile (the agent, the gateway, Docling, Unstructured, ascend-memory, the sandbox runner and the observability services). Modules with no compose service of their own (`coding`, `self-built-integrations`, `subagents`, `skills`, `self-improvement`, `scheduler`) appear only in `docs/MODULES.md`. Tenant policy, metering, audit, tenant administration and the SharePoint connector are not core and not switchable modules: each company change adds its own parts to the deployment when it lands, so the documents name them as company parts, and the test mail server of `add-tenant-administration` as a development service.

### D7 - One mechanism per job, as the owner decided on 2026-10-08

The owner answers 87 to 93 of 2026-10-08 left one mechanism for each job and made every mechanism safe with several instances of the same service. The end-state documents describe exactly that, and the crosscutting concepts files (`docs/architecture/arc42/` and the agent's `08-crosscutting-concepts.md`) name each one once, with a link to the change that owns it. A removed mechanism is never described, not even as an alternative, so a reader cannot rebuild it. The list, by owner answer:

| Answer | The one mechanism the documents name | Owner change | What the documents no longer describe |
| :--- | :--- | :--- | :--- |
| 87 (rule R1) | Several containers of the same service run at once. Timed work that must run once uses the shared scheduler of the agent (a Redis lock with an expiry in a Python service), local timed work uses Spring's `TaskScheduler` with `@Scheduled`, cross-instance state lives in Postgres rows in the agent and in Redis in a Python service, cancel is written to the shared row, a stream to a client is fed from the shared store, a cache has a bounded TTL plus shared invalidation where a stale read is a defect | every change, CANON 26.1 | an in-process-only lock, map, queue, flag or private thread pool where a second instance would act on the same work |
| 89.1 | One chat executor, `StreamingChatExecutor`, whose stream `POST /api/v1/ai/prompt` collects into one answer | `add-chat-streaming-and-conversations` | a second, blocking executor |
| 89.2 | One ingestion path through `IngestionRunService` and the documents registry | `add-document-management-api` (the `connector_id` column and payload index added by `add-connector-framework`) | a second ingestion store |
| 89.3 | One local timer mechanism (`@Scheduled`) next to db-scheduler for persistent and cluster-wide work | `add-shared-scheduler`, `add-deployment-modules` | a private timer or thread pool |
| 89.4 | One approval record, `approval_request`, with a handler per kind | `add-action-approvals` | separate proposal, credential approval, approved host and reviewed tool records |
| 89.5, 89.17 | One catalog for skills and subagent definitions, with one switch per tool | `add-agent-skills`, `add-agent-subagents` | two loaders, two watchers, two controllers, two switches for one tool |
| 89.6 | One notification path through `OwnerNotificationService`, one retry layer, one action endpoint, `read_at` as the only seen marker | `add-shared-scheduler` | a second retry table, a second action endpoint, a second seen marker |
| 89.7 | One run slot pool with a limit per run kind, and one retention task with registered entries | `add-agent-subagents`, `add-shared-scheduler` | a slot pool or a retention task per change |
| 89.8 | One `TenantPolicy` service with one policy store and one deny list, plugged into the earlier plug-in points | `add-tenant-policy` | three deny-list settings |
| 89.9 | One path into the usage ledger (`UsageEventPort`), quota sums from Postgres, BYOK keys in the one encrypted secret store (`ConnectorCredentialStore`, `CONNECTOR_CREDENTIALS_KEY`) | `add-usage-metering-and-quotas`, `add-connector-framework` | Redis quota counters, `SETNX` markers, a second envelope store, `USAGE_KEK` |
| 89.10 | One production startup guard: `application-production.yaml` with required placeholders and one guard class | `harden-cloud-deployment`, `add-keycloak-login` | a second guard |
| 89.11 | One schema owner: Flyway, the Spring Integration Postgres DDL as a Flyway migration | `upgrade-spring-boot-4` | `initialize-schema` |
| 89.12 | Logs through the OpenTelemetry collector to Loki, with every label | `add-observability` | Vector |
| 89.13 | One price source, `infra/pricing/pricing.yaml`, read by the dashboard | `add-observability`, `add-agent-subagents` | a hard-coded copy of the prices |
| 89.14 | Tracing exports whenever `OTEL_EXPORTER_OTLP_ENDPOINT` is set, `OTEL_SDK_DISABLED` switches it off | `add-ascend-python-common` | a custom `OTEL_ENABLED` |
| 89.15 | The real Keycloak Testcontainer for integration tests of the Keycloak Admin API, the JDK `HttpServer` for pure unit tests | `add-tenant-administration`, `add-audit-and-gdpr-compliance` | a separate Mockoon environment for Keycloak |
| 89.16 | Suspend is one mechanism and resume keeps the users an admin disabled one by one | `add-tenant-administration` | a second suspend mechanism |
| 90 | No test code or test-only setting in real logic or service configuration, test overlays and fakes instead | the changes CANON 26.6 names | the removed test-only settings and endpoints |
| 91.1, 91.2, 98.1, 98.2 | The deterministic test phase copies the test overlay into the running agent as `/app/config/application.yaml`, restarts only the agent and recreates it from its image at the end, fakes AscendMemory in the one Mockoon container under `/ascend-memory/`, runs exactly two test containers, and runs the fake MCP server, one test class of the agent's test sources packaged as `ascend-e2e-fake-mcp:local` | `close-agent-test-gaps` | a test line or an `e2e` profile in `compose.yaml`, an overlay mount, an AscendMemory restart, a dummy key, memory wipes in deterministic specs, a third fake program |
| 91.3 | One deterministic API spec per capability where it proves something no lower test proves, and every spec with real AI answers | every change | the end-to-end specs that only repeated a lower test |
| 88.1 (CANON 26.3) | Tenant isolation starts from empty stores | `add-tenant-isolation` | the one-time tenant backfill, `tenant_backfill_step` and its readiness hold |
| 93 (CANON 26.8) | One tenant header, `X-Ascend-Tenant` | every change that names one | a second tenant header name |
| 98 (owner rule 98) | Every value with a default is a setting, read from the environment with the same default in code and passed by compose as `${VAR:-default}`, and every setting has exactly one row, in `docs/CONFIGURATION.md` or in its service's own reference | every change, `fix-linux-docker-host-access` (the reference) | a hidden operational constant, a setting described with its default in two places |
| 98.6, 99.1 | Local development runs one container of each service, a caller inside Docker reaches every copy of a service by its compose service name, and a scaled company deployment is the Helm chart with a Horizontal Pod Autoscaler of `plan-scaled-deployment` | `scale-ocr-and-audio-across-containers`, `scale-web-hunter-across-containers`, `plan-scaled-deployment` | host port ranges for several copies of a service |

The implementer checks each row against the archived change before writing, because a later decision may have refined it, and writes what the archive says.

## Risks / Trade-offs

- Documents drift again later. Per-change documents stay each change's job, and the map and `AGENTS.md` pass make drift visible.
- The OpenAPI task needs the application to start. D5 names the fallback.

## Owner decisions of 2026-10-07

Answer 75.1: the review of 2026-10-07 is fixed here. Item 75: the proposal lists the five changes it had left out (`close-agent-test-gaps`, `enhance-web-search-tier-ladder`, `remove-flaresolverr-tier`, `add-web-session-import` and `add-web-crawl-rag-connector`) and all four company extension ports of `add-deployment-modules` D21 (`AuditEventPort`, `UsageEventPort`, `QuotaGate` and `ModelAccessPolicy`).

## Open Questions

None.

## Owner decisions of 2026-10-08

Answer 89 (89.1 to 89.17), answer 90 and answer 91 (91.1 to 91.3): the documents describe one mechanism per job, as the table of D7 lists, and name no removed mechanism. Task 1.5 checks it.

Answer 87 (rule R1): the crosscutting concepts files describe the one multi-instance mechanism of CANON 26.1 (D7, first row, task 1.5), and the container view and the arc42 deployment view say that several containers of the agent and of ascend-web-hunter run at once.

Answer 88 (rule R2) and answer 88.1 (CANON 26.3): every company plug-in point stays in the documents, and tenant isolation is described as starting from empty stores, with no tenant backfill and no readiness hold (D7).

Answer 89.12: the proposal no longer names Vector among the observability services, and the container view shows the OpenTelemetry collector collecting the container logs (D2, D7).

Answer 91.1: `docs/E2E_RUN_SCENARIOS.md` and the suite READMEs describe the deterministic phase that restarts only the agent and runs exactly the two test containers `e2e-scripted-model` and `e2e-fake-mcp`, with AscendMemory faked under `/ascend-memory/` (task 7.1).

Answer 91.3: the scenario document and the suite READMEs list only the specs that exist after the removals of the other changes, with counts recomputed from the files on disk (tasks 7.1 and 7.2 already count from disk).

Answer 85.1: the documents never tell the owner to export a secret in a shell. Every key and secret is read from the repository `.env` (task 1.5).

Answer 93: the documents use the one tenant header name `X-Ascend-Tenant` (D7).

Answer 98 (the configuration rule, CANON 31.11 to 31.13): the documents name the one configuration reference, `docs/CONFIGURATION.md` with the four per-service references it links, and the end-state check of task 4.2 compares it with the settings that exist. This change adds no setting of its own. The `apiDocsUrl` and the output folder of the `openApi { }` block (D5) are values of a build task, not of a running service, so they stay in `build.gradle.kts`. No test or measurement of this change uses LM Studio: task 5.4 and the quick start spec of task 7.5 ask the owner for the scenario and need no AI model (checked in round 98).

Answer 98.1 and answer 98.2: the deterministic phase copies the test overlay into the running agent and restarts only the agent, and the fake MCP server is one test class packaged as `ascend-e2e-fake-mcp:local` (D7, row 91.1, task 7.1).

Answer 98.6 and answer 99.1: local development runs one container of each service, and the scaled company deployment is the group 5 change `plan-scaled-deployment` (a Kubernetes Helm chart with a Horizontal Pod Autoscaler), which the proposal lists and the deployment view names (D7).

Stale text fixed in round 98 (CANON 31.14): the proposal lists `fix-linux-docker-host-access`, `scale-ocr-and-audio-across-containers` and `scale-web-hunter-across-containers`, the container view of D2 names the web-hunter edge proxy, and row 91.1 of D7 no longer says that the fake MCP server is built from the in-test fake of `McpStartupToleranceIT`, which holds none (CANON 26.15).

## Owner decisions of 2026-10-09

Answer 99.1: the change `plan-scaled-deployment` now exists, at build group 5, position 9, and this change moves to position 10 (order decision of 2026-10-09), so it still documents the Kubernetes deployment. The proposal entry names what that change plans, and new task 1.6 documents it in `docs/architecture/arc42/04-deployment.md`, the container view and the documentation map.
