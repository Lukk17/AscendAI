## Context

See proposal.md for why. The current state that shapes the design:

- `compose.yaml` (project `ascend-ai`) starts every service on `docker compose up`. It `include:`s `compose.ascend-web-hunter.yaml`, whose only profile today is `redis` for an optional bundled Redis. `harden-cloud-deployment` adds a second profile, `captcha-intervention`, for the ngrok tunnel.
- The agent's `depends_on` is the short list `[ascend-memory, docling-serve, unstructured-api]`. `SEARXNG_SECRET` is guarded with `${SEARXNG_SECRET:?...}`.
- The agent has two controllers (`PromptController` on `/api/v1/ai`, `IngestionController` on `/api/v1/ingestion`) and three MCP connections in `application.yaml` (`ascend-audio-scribe`, `ascend-weather-mcp`, `ascend-web-hunter`). `ChatContextAssembler` imports `RagRetrievalService` and `SemanticMemoryClient` directly. `DocumentRouter` sends images and scanned PDF pages to ascend-ocr through `AscendOcrClient`.
- Every service exports its traces to the OpenTelemetry collector, and the observability containers carry no profile (`add-observability`).
- Active changes disagree on the switch: `add-mcp-tool-servers` D10 sets `APP_MCP_MODULES: ${COMPOSE_PROFILES:-}` and binds `app.mcp.modules`, `add-openclaw-plugin-host` (named `add-openclaw-channel-host` until 2026-10-02) D15 passes `COMPOSE_PROFILES` as `ASCEND_MODULES` and binds `app.channels.enabled`, and `add-agent-sandbox`, `add-coding-agent-delegation`, `add-self-built-integrations`, `add-self-improvement`, `add-agent-skills` and `add-agent-soul` each add an `app.<feature>.enabled` flag.

Measured on this machine with Docker Compose v5.1.0 against a scratch compose file, before writing this design:

- A long form `depends_on` with `required: false` on a service whose profile is off passes `docker compose config`. The short form fails with `service "agent" depends on undefined service "ocr": invalid compose project`.
- A `${VAR:?message}` guard fails `docker compose config` even when the only service using it is under a profile that is off.
- `ASCEND_MODULES: ${COMPOSE_PROFILES:-}` receives the value from the shell environment and from `.env`. With `docker compose --profile web-search config` it receives an empty string, so the `--profile` flag does not reach the agent.
- An unknown name in `COMPOSE_PROFILES` is accepted by compose without a message, so compose alone does not catch a typo.

## Goals / Non-Goals

Goals:

- One list of module names, one switch, and one meaning of "off" everywhere: compose, agent, tenants and installer.
- A personal deployment that keeps today's full stack, and company deployments that run only the switchable modules they bought, with no service, bean, tool, route, connection or metric of the rest.
- A core that is always on and can never be switched off by mistake.
- An inconsistent selection fails at startup with a message that says how to fix it.

Non-Goals:

- Licensing, billing or any check of whether a customer paid for a module.
- Turning modules on or off while the agent runs. A change of `COMPOSE_PROFILES` takes effect with `docker compose up -d`, which recreates the agent because its environment changed.
- A modular database schema. Every Flyway migration runs in every deployment (D15).
- Per user or per employee group module grants inside a tenant (owner answer 41.4). The tenant grant of D9 is the seam a later change can extend.
- Switching off any part of the core (owner answer 52 of 2026-10-03). Moving the data stores into modules.

## Decisions

### D0: The core is always on and only services the system works without are modules

Owner decision of 2026-10-03 (answers 51 and 52). A module is switchable only when the system keeps working without it. Everything else is the core, which has no compose profile, no `@ConditionalOnModule` marking and no tenant module grant, and runs in every deployment:

| Part of the core | Compose services (no profile) | What it holds in the agent |
|---|---|---|
| core chat | `ascend-agent`, `gateway` (from `harden-cloud-deployment`, listed in the always-on part of the catalog description and of `docs/MODULES.md`), `mcp-egress-proxy` (from `add-mcp-tool-servers`, always on from that change onward because our own tool servers are always on, owner answer 76.5 of 2026-10-08) | chat, conversations, streaming, login and `TenantContext` (`add-keycloak-login`), approvals, the personality file and user facts (`add-agent-soul`), background runs (the run classes of `add-agent-subagents`), the shared scheduler engine with its system tasks (`add-shared-scheduler`), notifications, and the skill and tool search index (`add-agent-skills`) |
| monitoring | `prometheus`, `grafana`, `loki`, `tempo`, `otel-collector`, `container-metrics-exporter`, and the exporters `postgres-exporter` and `redis-exporter` of `add-observability` | trace export and the metrics endpoints of every service |
| document search (`rag`) | `docling-serve`, `unstructured-api` | knowledge search, ingestion, retrieval, the vector store, the connector framework (`add-connector-framework`), the document management API and the citations |
| memory | `ascend-memory` | semantic memory reading and extraction |
| the sandbox | `ascend-sandbox-runner` (from `add-agent-sandbox`) | the sandbox client, the shell and file tools `shell`, `file_read` and `file_write`, and the sandbox output routes |
| prerequisites | PostgreSQL, Redis, Qdrant, object storage and Keycloak, external or in compose, always without a profile. Keycloak is a core prerequisite of every deployment, the personal one included, because the personal assistant itself logs in to Keycloak (owner answer 70.2 of 2026-10-04, `add-keycloak-login`) | none |

Tenant policy, metering, audit and every other company part are not core (owner build order of 2026-10-04 and owner rule of the same day: nothing personal or base depends on company work). The core list names only what build groups 1 to 4 build. Each company change of build group 5 adds its own parts to the deployment when it lands, as always-on parts or as modules of its own, and registers its implementations of the ports of D9 and D21. Keycloak stays a core prerequisite, because the personal assistant itself logs in to it through `add-keycloak-login` (build group 3).

Why these are core: a chat without memory, document search or monitoring is not the product the owner sells, and the sandbox is the one safe place where the shell and file tools run for every kind of run. The names `rag`, `memory`, `sandbox` and `observability` were modules in the draft of 2026-10-02. They are not module names any more, and the startup check refuses them with a message that they are always on (D4), so an old `.env` fails loudly instead of being ignored.

The catalog keeps one always-on entry, `core-chat`, which stands for the whole core in the catalog, in `GET /api/v1/modules` and in the banner. The name stays `core-chat` because it is already used by every other change and a released name is never renamed. The list of core classes in `ModuleMarkingCoverageTest` is called the `core-chat` list for the same reason, and it holds the classes of every part of the core, not only the chat ones.

### D1: The module catalog is one JSON file inside the agent

The catalog lives at `apps/ascend-agent/src/main/resources/modules/catalog.json` and is loaded from the classpath. Shape:

```json
{
  "modules": {
    "core-chat": { "title": "Core", "description": "Chat, document search, memory, the sandbox and monitoring. Always on.", "always-on": true },
    "ocr": { "title": "Text from images", "description": "Reads scanned pages and photos with ascend-ocr.", "requires": [], "uses": [], "companions": [], "agent-secrets": [] },
    "web-search": { "title": "Web search", "description": "Searches and reads the web.", "companions": ["redis", "captcha-intervention"] }
  },
  "core-names": ["rag", "memory", "sandbox", "observability"],
  "presets": {
    "personal": ["audio", "ocr", "weather", "web-download", "web-search"],
    "company-docs": ["ocr"],
    "core": []
  }
}
```

Missing list fields mean empty. The example is shortened: the shipped file holds `core-chat` and the five switchable modules of D3 that exist when this change lands. `core-names` lists the former module names of the core, so the startup check can refuse them with their own message (D4).

Why inside the agent: the catalog names the beans of the agent, so it must change in the same commit and ship in the same image as the code it describes. A file at the repository root mounted into the container (the price table pattern of `add-agent-subagents` D12) would let an image run against a catalog of another version. Why JSON: the agent reads it with Jackson, the PowerShell installer reads it with `ConvertFrom-Json` with nothing to install, and the Bash installer reads it with `jq`, which the installer can check for and install. YAML would need an extra module in PowerShell. A Java enum was rejected because no script could read it.

Alternatives considered: one `enabled` flag per feature (today's drift, rejected), a catalog per service (several lists, rejected).

### D2: COMPOSE_PROFILES is the switch, ASCEND_MODULES is what the agent reads

The operator writes the module list once, in `COMPOSE_PROFILES` in the root `.env`. Compose starts the services of those profiles. The agent gets `ASCEND_MODULES: ${COMPOSE_PROFILES:-}` and binds `app.modules.active: ${ASCEND_MODULES:}` as a list. A later service that needs the list gets the same line from the change that adds the need (the `ascend-openclaw-host` containers from `add-openclaw-plugin-host`). ascend-web-hunter already reads `ASCEND_MODULES` for its download tools, from `add-file-download`, which lands earlier (build group 2) and gets the value from `COMPOSE_PROFILES` the same way. No service reads it to switch its telemetry, because monitoring is core.

Recommendation on the disputed name, followed here: `ASCEND_MODULES`. Reasons:

1. The services read a product setting, not a compose setting. When the agent runs with `./gradlew bootRun` on the host there is no compose, and `ASCEND_MODULES` in the run configuration says what it is.
2. `APP_MCP_MODULES` (from `add-mcp-tool-servers`) names one consumer. Channels and every later module need the same list.
3. Reading `COMPOSE_PROFILES` itself inside containers would tie every service to a compose detail and would break the day a deployment uses another orchestrator.

`app.mcp.modules`, `APP_MCP_MODULES`, `app.channels.enabled`, `app.coding.enabled`, `app.integrations.enabled`, `app.self-improvement.enabled` and `app.skills.enabled` are replaced by the module list (required edits). `app.sandbox.enabled` is removed without a replacement, because the sandbox is core. Settings that switch a part inside an active module or inside the core stay, such as `app.skills.search.enabled`, `app.ingestion.auto.enabled` and the `app.soul.*` part flags.

The `--profile` flag must not be used for modules, as measured in Context. `docs/MODULES.md` says so, and the commands in the docs always edit `COMPOSE_PROFILES`. `docker compose --profile <name> down` to remove the containers of a module after taking it out of the list is still fine, because it changes nothing the agent reads.

Unset `ASCEND_MODULES` means only `core-chat`, the same as an empty `COMPOSE_PROFILES` in compose, so the container and a host run agree.

### D3: The module list

Switchable modules that exist when this change lands, all in this change. `web-download` belongs to ascend-web-hunter services that `add-file-download` (build group 2) added earlier, so this change adds its catalog entry and its companion `clamav`:

| Module | Compose services (profile) | Agent parts | Routes | Tools | Settings | Requires | Uses | Agent secrets |
|---|---|---|---|---|---|---|---|---|
| `ocr` | `ascend-ocr` | `AscendOcrClient` (the `OcrReader` of D6), `AscendOcrProperties` | none | none | `app.ascend-ocr.*` | none | none | none |
| `audio` | `ascend-audio-scribe` | MCP connection `ascend-audio-scribe` | none | `transcribe_*` | none | none | none | none |
| `web-search` | `searxng`, `ascend-web-hunter`, companions `redis` and `captcha-intervention` (`ngrok-ascend-web-hunter`) | MCP connection `ascend-web-hunter` | none | `web_*` | none | none | none | none |
| `weather` | `ascend-weather-mcp` | MCP connection `ascend-weather-mcp` | none | `weather_*` | none | none | none | none |
| `web-download` | none of its own (tools and routes of `ascend-web-hunter`, which registers them only when `ASCEND_MODULES` holds `web-download`, `add-file-download` D16), companion `clamav` | none until `add-download-ingestion` adds its tool and route | none | `web_download_*` on the `ascend-web-hunter` connection | none | `web-search` | none | none |

`core-chat` is the always-on entry of D0. Its agent parts include `PromptController`, `IngestionController`, `ModuleController`, `DoclingClient`, `SemanticMemoryClient`, `DocumentRouter`, `RagRetrievalService` and every other class of chat, document search and memory, and its routes include `/api/v1/ai/**`, `/api/v1/ingestion/**`, `/api/v1/modules` and actuator.

Switchable modules that later changes add, each through its required edit, with the names reserved here:

| Module | Change | Compose services | Requires | Uses | Agent secrets |
|---|---|---|---|---|---|
| `skills` | `add-agent-skills` | none | none | none | none |
| `subagents` | `add-agent-subagents` | none | `skills` | none | none |
| `coding` | `add-coding-agent-delegation` | none of its own (runner images of the core sandbox) | none | none | `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY` |
| `self-built-integrations` | `add-self-built-integrations` | none of its own (network `integrations-ingress`) | `coding` | `self-improvement` | none |
| `self-improvement` | `add-self-improvement` | none | `subagents` | none | none |
| `scheduler` | `add-shared-scheduler` adds the entry, `add-scheduled-tasks` adds its job tools | none | `subagents` (added by `add-scheduled-tasks`) | none | none |
| `channels` | `add-openclaw-plugin-host` | the `ascend-openclaw-host` containers that hold chat platform connections | none | `audio` | none |
| `openclaw-apps` | `add-openclaw-plugin-host` | the `ascend-openclaw-host` containers that run app plugins | none | none | `OPENCLAW_APPS_MCP_TOKEN` |
| `obsidian` | `add-obsidian-vault` | `obsidian-sync` | none | none | none |

Once every change of the build order has landed, the catalog holds exactly these fourteen switchable modules: `ocr`, `audio`, `web-search`, `web-download`, `weather`, `obsidian`, `channels`, `openclaw-apps`, `coding`, `self-built-integrations`, `subagents`, `skills`, `self-improvement` and `scheduler`.

`requires` lists direct needs only. The check of D4 applies it to every listed module, so needs further down the chain are checked too: `self-improvement` without `skills` fails on `subagents`. No switchable module requires a part of the core, because the core is always there: `ocr` and `obsidian` no longer require `rag`, `web-download` no longer uses it, and `coding` no longer requires `sandbox` (owner answer 52).

`uses` lists optional references only (D6). `self-built-integrations` uses `self-improvement`, because it reports its integration events to `add-self-improvement` as change records only while that module is active. `channels` uses `audio` only: its run status messages read the run view and `SubagentRunChangedEvent`, which are core, so it uses no class of `subagents`. `scheduler` has no `uses` entry, because its notifications go through the core notification delivery and its code refers to no class of `channels`.

The `WEB_CRAWL` connector type of `add-web-crawl-rag-connector` needs `web-search` (its connector framework is core). `knowledge_add_download` and `POST /api/v1/documents/from-download` of `add-download-ingestion` (the agent part split out of `add-file-download` on 2026-10-04) need `web-download`.

`core-chat` holds `TenantContext` of `add-keycloak-login`, the one tenant seam, and the capability index, `ChatToolset`, `AgentNativeTool`, `VersionedFolder` and `app.agent-home` of `add-agent-skills`, because `add-mcp-tool-servers` finds tools through the same index and must work without `skills`, and `add-agent-soul` uses `VersionedFolder` and the agent home root with `skills` off. The `skills` module is the skill registry, the skill tools, `skill_search` and `/api/v1/skills`. `subagents` requires `skills` because `add-agent-subagents` D6a finds subagents through `skill_search`.

`core-chat` also holds the shared scheduler engine of `add-shared-scheduler`, because connector syncs, retention and sweeps run on it. The notification store, notification delivery and `/api/v1/notifications` of `add-shared-scheduler` are core too (owner decision of 2026-10-02), so a notification reaches the owner in every deployment, and `channels` delivers notifications through the core delivery port without using `scheduler`. `add-shared-scheduler` adds the catalog entry `scheduler` with empty `requires` and no `uses` entry, because `subagents` is not in the catalog yet at build step 5 and D4 refuses an unknown name. The `scheduler` module is the assistant's own jobs: `add-scheduled-tasks` adds the job tools, `/api/v1/scheduled-jobs` and `owner_notify` to it, together with `requires: [subagents]` and no `uses` entry.

Of `add-agent-subagents`, these are core and carry no marking (owner decision of 2026-10-02): the run table, `SubagentRunService` with the port `ScheduledRunStarter`, `RunController` with `/api/v1/runs`, the run loop `RunLoop`, `RunSlots`, `RunBudget`, `PriceTable`, `SubagentModelResolver`, `ToolPermission`, `SubagentProperties`, the finished runs block and the system task `run-orphan-sweep` and the retention entry `subagent-run` of the shared retention task of `add-shared-scheduler` (owner answer 89.7 of 2026-10-08), because runs of every kind use them. The `subagents` module is only the `Task` tool, the `TaskOutput` tool, the subagent definitions as the catalog type `SubagentCatalogType` of the one catalog of `add-agent-skills` (its validator, its store and the routes `/api/v1/subagents/definitions/**`, owner answer 89.5 of 2026-10-08), `subagent_definition_write` and `AscendSubagentExecutor`. The one catalog itself (`CatalogLoader`, `CatalogHolder`, `CatalogWatcher`, `CatalogWriteService`, `CatalogChangeNotifier`, `CatalogController` and the interface `CatalogType`, `add-agent-skills` D24) belongs to the module `skills`, and a route of a catalog type whose bean is absent answers 404, so `/api/v1/subagents/definitions` still answers 404 with `subagents` off.

Of `add-agent-sandbox`, everything is core (owner answer 52): the classes of `service/sandbox/`, `SandboxOutputController`, `SandboxProperties`, the tools `shell`, `file_read` and `file_write`, and its system tasks. The tenant tool policy of `add-tenant-policy` stays the per tenant switch of the three tools.

`channels` and `openclaw-apps` map to the one service `ascend-openclaw-host` of `add-openclaw-plugin-host`: one program and one image that runs every OpenClaw plugin, as several containers. Each container is told which plugins it runs. The containers that hold chat platform connections carry the profile `channels`, and the containers that run app plugins carry the profile `openclaw-apps`. A chat platform connection runs in exactly one container. App plugins can be spread over many containers. A container that holds chat platform tokens never runs third-party app plugins. `mcp-egress-proxy` of `add-mcp-tool-servers` is not a catalog companion and carries no profile: it is always on from `add-mcp-tool-servers` onward (owner answer 76.5 of 2026-10-08), and the app plugin containers of `openclaw-apps` use it.

### D4: The selection check runs before any bean exists

`ModuleSelectionEnvironmentPostProcessor`, registered in `META-INF/spring.factories`, loads the catalog, splits `app.modules.active` (trim, drop empty entries, accept `core-chat`), and checks it in this order. Each failure throws `InvalidModuleSelectionException` with every problem found, not only the first. A connection with no module is not a refusal: it belongs to no switchable module and is always on (owner answer 90 of 2026-10-08, D7). A connection that names a module outside the catalog is refused as an unknown name. `ModuleSelectionFailureAnalyzer` turns it into Spring Boot's failure report with a description and an action. These are all the refusals, and `docs/MODULES.md` explains each one under "Troubleshooting":

| Refusal | Example description | Action line |
|---|---|---|
| A name of the core | `'rag' is part of the core and is always on. It is not a module.` | `Remove 'rag' from COMPOSE_PROFILES in .env and run docker compose up -d.` |
| An unknown name | `'ocrr' is not a module or companion in the catalog.` | `Did you mean 'ocr'? Fix COMPOSE_PROFILES in .env and run docker compose up -d.` (the closest known name by edit distance) |
| A companion without its module | `'captcha-intervention' is a companion of 'web-search', which is not in ASCEND_MODULES (from COMPOSE_PROFILES).` | `Add 'web-search' to COMPOSE_PROFILES in .env, or remove 'captcha-intervention', and run docker compose up -d.` |
| A missing requirement | `Module 'subagents' requires 'skills', which is not in ASCEND_MODULES (from COMPOSE_PROFILES).` | `Add 'skills' to COMPOSE_PROFILES in .env and run docker compose up -d.` |
| A missing agent secret under `production` (after the context starts, below) | `Module 'coding' is active but GITHUB_APP_ID is empty.` | `Set GITHUB_APP_ID in .env, or remove 'coding' from COMPOSE_PROFILES, and run docker compose up -d.` |

Agent secrets: after the context starts, `ModuleSecretCheck` reads the `agent-secrets` of every active module from the environment. Under the Spring profile `production` it runs as one `ProductionStartupCheck` of the one production startup guard `ProductionStartupGuard` of `add-keycloak-login` (owner answer 89.10 of 2026-10-08), so an empty secret fails the start with that guard's one ERROR line naming the secret and never its value. Otherwise it logs one WARN line per missing name. No module that exists in this change has an agent secret. The ones that later changes add are `GITHUB_APP_ID` and `GITHUB_APP_PRIVATE_KEY` of `coding` and `OPENCLAW_APPS_MCP_TOKEN` of `openclaw-apps` (D3). Secrets of the core are not module secrets: `SANDBOX_RUNNER_TOKEN` and `GRAFANA_ADMIN_PASSWORD` are compose `:?` guards on always-on services (D11), and the always-needed credentials are required placeholders of `application-production.yaml` and checks of `ProductionStartupGuard` (`add-keycloak-login` and `harden-cloud-deployment`, owner answer 89.10 of 2026-10-08).

Alternative considered: resolving missing requirements automatically. Rejected: a company that bought `self-improvement` alone would silently run `subagents` and `skills` too, and the owner asked for a refusal.

### D5: One conditional annotation and a coverage test

`@ConditionalOnModule(String... value)` is backed by `OnModuleCondition extends SpringBootCondition`, which binds `app.modules.active` through `Binder` and matches only when every named module is active. A name in a marking must be a switchable module of the catalog: `core-chat` or a core name in a marking fails the context, because the core is never marked. It goes on `@Configuration` classes, `@Component` classes and `@Bean` methods. `ModuleState`, an immutable core bean, exposes the active set and the catalog to code that must ask at run time (the interceptor of D8, the tool filter of D10, the modules endpoint of D16).

`ModuleMarkingCoverageTest` scans `com.lukk.ascend.ai.agent` with `ClassPathScanningCandidateComponentProvider` for `@RestController`, `AgentNativeTool` implementations, scheduled task beans and outbound clients (`*Client` components). Each class must carry `@ConditionalOnModule` with switchable catalog names, or be in the test's explicit `core-chat` list. The `core-chat` list lives in the test, so adding to it is a visible decision in review. It holds the classes of every part of the core (D0). It starts with the core classes that exist today: `PromptController`, `IngestionController`, `ModuleController`, `DoclingClient` and `SemanticMemoryClient`. Later changes add their own core classes to it through their required edits: `ChatToolset`, `CapabilityIndexSync` and `VersionedFolder` of `add-agent-skills`, the run classes of `add-agent-subagents` listed in D3, the classes of `service/sandbox/`, `SandboxOutputController` and `SandboxProperties` of `add-agent-sandbox`, the connector framework of `add-connector-framework`, the controllers and services of `add-document-management-api`, and the scheduler engine and notification classes of `add-shared-scheduler`. `Task`, `TaskOutput`, `subagent_definition_write`, `AscendSubagentExecutor` and the definition classes of `add-agent-subagents` are never on that list, because they carry `@ConditionalOnModule("subagents")`. No new dependency is needed.

Spring Boot reads conditions before it creates the bean, so a module that is off costs nothing at run time, and its meters, routes and OpenAPI entries never exist.

### D6: The core depends on ports, not on modules

The rule: a class may refer to a class of a switchable module only when its own module lists that module in `requires` (required reference) or `uses` (optional reference). A core class refers to no class of a switchable module. When the core needs something a switchable module provides, it declares a port, and the module implements it. `ModuleMarkingCoverageTest` gains a check of imports from core packages into marked classes so the rule is tested.

- `OcrReader` (core interface in `service/ingestion/`): reads the text of an image or of the PDF pages without a text layer. `AscendOcrClient` in `ocr` implements it. `DocumentRouter` (core, document search) takes it through `ObjectProvider<OcrReader>`, so with `ocr` off there is no implementation and the router refuses the file (D14). The router never imports `AscendOcrClient`.
- `ChatContextContributor` (core interface): `contribute(ChatContextRequest)` returns zero or more blocks, each marked for the system message or for the user message, with a stable order key and the sources it cites. `ChatContextAssembler` takes `List<ChatContextContributor>`. Today semantic memory goes into the system message and retrieved documents into the user message, and that placement is kept: `RagRetrievalService` and the semantic memory reader each provide one contributor bean. Both are core, so the port is not needed for gating. It stays because it keeps `ChatContextAssembler` closed for modification when a further context source is added, and because `add-passage-level-citations` threads its labeled passages and citations through the RAG contributor. `BuiltUserMessage` and `SourceRef` move into the chat package with it.

The draft of 2026-10-02 also planned `PromptAttachmentReader` and `ChatTurnCompletedEvent`, because `rag` and `memory` were modules then. Both are dropped: document search and memory are core, so `AscendChatService` keeps its direct use of `SemanticMemoryExtractor` and a prompt attachment keeps its direct path to document reading. No other change refers to either name.

### D7: Each MCP connection names its module

Until `add-mcp-tool-servers` lands, `application.yaml` gains:

```yaml
app:
  modules:
    active: ${ASCEND_MODULES:}
    connections:
      ascend-audio-scribe: audio
      ascend-weather-mcp: weather
      ascend-web-hunter: web-search
```

The module of a connection is optional (owner answer 90 of 2026-10-08, which replaces the `e2e` profile branch of answer 72.5): a configured `spring.ai.mcp.client.streamable-http.connections` entry that names no module belongs to no switchable module and is always on, in every profile, and the selection check of D4 refuses only a module name that is not a switchable module of the catalog. No branch of the real check knows a test profile. The connection `e2e-fake` of the deterministic test harness of `close-agent-test-gaps` names no module, so it is always connected while it is configured, and it is configured only in the overlay file `application-e2e.yaml` of that harness, which the deterministic phase copies into the running agent and removes again by recreating the agent (`close-agent-test-gaps` D7, owner answer 98.1 of 2026-10-08). No `e2e` profile exists. Only a connection of an active module, or one with no module, gets a connection. `McpClientStartupInitializer` skips a connection of an inactive module: it never calls `initialize()` on it and records no entry for it in `McpClientStatusRegistry`, so the background retry of D19 never sees it. Spring AI's auto-configuration still builds the client object from the properties, which opens nothing, because `spring.ai.mcp.client.initialized=false`. `FilteredToolCallbackProvider` already offers only `CONNECTED` clients, so its tools never appear. The banner lists only connections of active modules and counts only them in the aggregate, and its `Modules:` block (D16) shows which modules are off, so no `[Off]` state exists (the `mcp-startup-resilience` delta). When `add-mcp-tool-servers` lands, the `module` field of each server entry replaces `app.modules.connections`, and only connections of active modules, and of entries with no module, are derived at all (required edit), which keeps the same banner and retry rules.

Alternative considered: removing the connection properties of inactive modules in an environment post processor. Rejected: rewriting another component's property sources is fragile, and the derived list of `add-mcp-tool-servers` does it properly later.

### D8: Routes of inactive modules do not exist, routes a tenant lacks answer 403

An inactive module's controller is not a bean, so Spring has no handler and the request gets the normal 404 problem detail. No route list is kept anywhere.

For tenant narrowing, `ModuleAccessInterceptor` (a core `HandlerInterceptor`) reads `@ConditionalOnModule` from the handler's bean class, asks `ModuleAccess` (D9) for the caller's grants, and throws `ModuleDeniedException` when one is missing. A core handler carries no marking, so the interceptor never denies it. `GlobalExceptionHandler` maps it to 403 with the code `module_denied` (`https://ascend.ai/errors/module-denied`), a value this change adds to the `ApiErrorCode` enum of `upgrade-spring-boot-4` D19, next to `module_required` of D14. The detail names the module. The interceptor runs after authentication, so it sees the tenant.

### D9: Tenant narrowing goes through one port

`ModuleAccess` (core interface): `Set<String> grantedModules(TenantId)`. Every caller passes the tenant that `TenantContext.currentTenantId()` of `add-keycloak-login` answers, the one tenant seam of the agent: a request reads the tenant of its resolved identity, and a background run or firing reads the tenant its worker bound with `TenantContext.runAs`. No caller reads a tenant from anywhere else. The default bean, `AllActiveModuleAccess`, registered with `@ConditionalOnMissingBean`, returns every active module. `add-tenant-policy` (company, build group 5) registers its tenant-aware bean later. This change does not wait for it. Effective modules are always `active ∩ granted ∩ deployment default`, computed in `ModuleState.effectiveFor(tenant)`, so no implementation can widen. A grant set must be closed under `requires`, and `add-tenant-policy` refuses a policy update that breaks it (required edit). A grant names switchable modules only: `core-chat` is always effective for every tenant and is never part of a grant, and a core name in a grant is refused like an unknown name. The tenant tool policy remains the way to switch single core tools, such as the sandbox tools, per tenant.

The order of narrowing, from widest to narrowest: catalog, active modules (`COMPOSE_PROFILES`), deployment default policy (`app.policy.default.modules`, default all active), tenant policy, then the existing tool allow-list and deny list per tenant. A tool survives only when its module is effective for the tenant (a core tool always is) and the tool policy allows it.

### D10: Tools of a module the tenant lacks are filtered with the other tool rules

The module of each tool is known: an agent native tool has the marking of its bean class (no marking means core), and an MCP tool has the module of its connection (D7), or a per tool override where one server serves two modules (`web_download_*` on `ascend-web-hunter` belongs to `web-download`, required edit to `add-download-ingestion`, the agent part of `add-file-download` since 2026-10-04). `FilteredToolCallbackProvider` today, and `ChatToolset` once `add-agent-skills` lands, drop tools whose module is not effective for the caller's tenant, in the same pass as the tenant tool policy. Background runs use the tenant of the run. Work that starts without a request, such as a scheduled firing or a connector sync of a connector type that belongs to a switchable module, checks the tenant's grants at its own start and is skipped with the reason `module_denied` (required edits to `add-scheduled-tasks` and `add-connector-framework`).

### D11: Compose layout

`compose.yaml`:

| Service | `profiles:` |
|---|---|
| `ascend-agent`, `docling-serve`, `unstructured-api`, `ascend-memory`, `container-metrics-exporter`, `prometheus`, `grafana`, `loki`, `otel-collector`, `tempo` (core) | none |
| `ascend-ocr` | `[ocr]` |
| `ascend-audio-scribe` | `[audio]` |
| `ascend-weather-mcp` | `[weather]` |

`compose.ascend-web-hunter.yaml`:

| Service | `profiles:` |
|---|---|
| `searxng`, `ascend-web-hunter` | `[web-search]` |
| `redis` | `[redis]` (unchanged, companion of `web-search`) |
| `ngrok-ascend-web-hunter` | `[captcha-intervention]` (from `harden-cloud-deployment`, companion of `web-search`) |
| `clamav` | `[clamav]` (from `add-file-download`, unchanged, companion of `web-download`) |

Services that later changes add follow the same rule: a service of a core part has no profile (`gateway`, `ascend-sandbox-runner`, `postgres-exporter`, `redis-exporter`, and `mcp-egress-proxy` of `add-mcp-tool-servers`, owner answer 76.5 of 2026-10-08), and a service of a switchable module carries its module's profile.

- Every `depends_on` entry that names a service under a module profile uses the long form with `required: false`, as measured in Context. The agent's own `depends_on` today names only core services (`ascend-memory`, `docling-serve`, `unstructured-api`), so it needs no `required: false`, and `harden-cloud-deployment` gives those entries `condition: service_healthy`.
- `ascend-agent` gets `ASCEND_MODULES=${COMPOSE_PROFILES:-}`. No other service gets it from this change (D2).
- Compose `:?` guards. Compose checks a guard even when the profile of its service is off (measured in Context), so a variable guarded on any service must be set in every deployment. The rules:
  1. Under a module profile, `SEARXNG_SECRET` (on `searxng`) is the one guard allowed (owner answer 41.2). Every deployment must set `SEARXNG_SECRET`, also one without web search. That is the accepted minus: a company that runs no web search still sets one secret it does not use. In return a missing secret fails `docker compose up` at once with a message that names it. Any other guard under a module profile fails `ComposeModuleConsistencyTest`, and `clamav` of `add-file-download` uses none.
  2. On always-on services, a guard is allowed, because the service runs in every deployment anyway. `GRAFANA_ADMIN_PASSWORD` on `grafana` (from `harden-cloud-deployment`) and `SANDBOX_RUNNER_TOKEN` on `ascend-sandbox-runner` and `ascend-agent` (from `add-agent-sandbox`) are such guards. Monitoring and the sandbox are core, so neither conflicts with a switched-off module.
  3. The installer always generates all three (required edit to `add-customer-stack-installer`), and `.env.example` marks each as required in every deployment.
- Running the scrapper file alone (`docker compose -f compose.ascend-web-hunter.yaml up -d`, project `ascend-scrapper`) now also needs `web-search` in `COMPOSE_PROFILES`, which the root `.env` already holds in the `personal` preset. The root and module `AGENTS.md` files say so.
- `apps/ascend-web-hunter/deploy-standalone/compose.yaml` keeps no profiles, because that bundle is web search and nothing else. For the same reason it sets no `ASCEND_MODULES`, so its `ascend-web-hunter` registers no tool of another module, and it carries no companion of another module: `clamav`, the companion of `web-download` that `add-file-download` adds, is left out of it (review finding 12). The missing `profiles:` lines and the missing `ASCEND_MODULES` are added to the list of intended differences in `deploy-standalone/README.md` by this change, and `add-file-download` adds `clamav` to that list when it adds the service (required edit). Its `SEARXNG_SECRET` guard stays `:?`, the same as in the development stack.
- Docker Compose 2.20 or later is required for `required: false`. `docs/MODULES.md` and `docs/DEPLOYMENT.md` state it.

### D12: Monitoring stays on in every deployment

Monitoring is core (D0). This change adds no profile to the observability containers and no export switch to any service: every service keeps exporting its traces to the collector exactly as `add-observability` configures it, whatever `COMPOSE_PROFILES` holds. The draft of 2026-10-02 made observability a module with a per service export switch. That draft is withdrawn by owner answer 52, and its tasks are gone from this change.

### D13: Presets

`personal` lists every switchable module of the catalog and grows with each change that adds a module. Once every change of the build order has landed it is the fourteen modules of D3: `audio`, `channels`, `coding`, `obsidian`, `ocr`, `openclaw-apps`, `scheduler`, `self-built-integrations`, `self-improvement`, `skills`, `subagents`, `weather`, `web-download` and `web-search`. Companions are never part of a preset: `redis`, `captcha-intervention` and `clamav` are added by hand. No preset holds the virus scanner `clamav` (owner answer 51.2), so `personal` runs `web-download` with `DOWNLOAD_SCAN_MODE=off`, the default of `add-file-download`. No `mcp-*` module exists, because `add-mcp-tool-servers` ships no specific outside server.

`core` is empty: the core alone, with chat, document search, memory, the sandbox and monitoring. It is used by tests and by a company that wants chat and document search with nothing switchable.

`company-docs` is `ocr` alone. It replaces the `company-rag` preset of the draft (`rag` and `ocr`), which no longer makes sense because `rag` is core. It is kept (owner answer 53 of 2026-10-03). Reasons: the owner's first company example is a deployment for document search only, and most company document stores hold scanned paper or phone photos. Without `ocr` those files are refused with `module_required` (D14), so `core` alone would refuse part of such a company's documents. `company-docs` names that common company case, so the installer can offer it by name and `PresetCompanyDocsIT` pins its exact routes and tools. A company that stores only born-digital documents takes `core`. Decided by owner answer 53 of 2026-10-03: `company-docs` stays, as `core` plus `ocr`.

A preset is never a compose profile, because a service under `personal` would duplicate every module's list. `PresetCatalogTest` checks that every preset passes D4, that `personal` holds every switchable module, that no preset holds a companion, and that the `COMPOSE_PROFILES=` line in `.env.example` equals `personal` in name order.

### D14: No OCR reading without the ocr module

With `ocr` off there is no OCR reading at all (owner answer 41.3). `DocumentRouter` takes an optional `OcrReader` (D6). When it is absent, an image file, or a PDF with at least one page without a text layer, is refused as a whole before any part of it is sent anywhere: `DocumentRouter` throws `ModuleRequiredException` with the module `ocr`, the file name and, for a PDF, the page numbers without a text layer. `GlobalExceptionHandler` maps it to 422 with the code `module_required` (`https://ascend.ai/errors/module-required`), a value this change adds to the `ApiErrorCode` enum of `upgrade-spring-boot-4` D19, the same status the agent already uses for `document_routing_failed`. The detail says that reading text from images needs the module `ocr`, which this deployment does not run. Nothing of the document is stored. The S3 inbound pipeline, which has no HTTP caller, handles the same exception the way it handles any routing failure today and writes one WARN line naming the file and the module. A PDF whose every page has a text layer is ingested as today.

No image and no page without a text layer is ever sent to Docling, to Docling's OCR engine or to ascend-ocr while `ocr` is off. A whole PDF is refused rather than ingested without its scanned pages, so a search never silently misses part of a document.

Alternative considered: sending images and scanned pages to Docling's own OCR engine. Rejected by the owner on 2026-10-02 (answer 41.3): a deployment without `ocr` does no OCR reading.

### D15: The database schema is the same in every deployment

Flyway runs every migration in every deployment, including tables of inactive modules. Reason: a module switched on later finds its tables without a migration order problem, and Flyway's ordered history stays one line. Empty tables cost nothing. The project is under development, so there is no data migration. Owner answer 73.1 of 2026-10-06 confirms that the data in today's development stores is disposable.

### D16: Modules endpoint and banner block

`ModuleController` (core) answers `GET /api/v1/modules` with:

```json
{
  "preset": "company-docs",
  "modules": [
    { "name": "core-chat", "title": "Core", "description": "..." },
    { "name": "ocr", "title": "Text from images", "description": "..." }
  ]
}
```

`preset` is `null` when the active list equals no preset. The list is the caller's effective modules (D9), always with `core-chat` first. `StartupLogConfig` adds a `Modules:` block. A Bruno request goes under `docs/api/request/AscendAI/ascend-agent/modules/`. The endpoint and the banner block are the two places that show the active modules. The gauge `module.active` of the plan before 2026-10-08 is dropped, because it repeated what the endpoint and the banner show (owner answer 93 of 2026-10-08, review item S3-9), so `ModuleMetrics` does not exist.

### D17: Tests

- `ModuleCatalogTest`: shape, name pattern, unknown references, cycles, companions owned once, `core-chat` present and always on, no `core-names` entry used as a module or companion name.
- `ModuleSelectionEnvironmentPostProcessorTest` and `ModuleSelectionFailureAnalyzerTest`: every refusal of D4 and its message, trimming, `core-chat` accepted, a core name refused. The missing requirement and the cycle cases use a test catalog, because no module of this change requires another.
- `OnModuleConditionTest`: one name, several names, inactive, `core-chat` or a core name in a marking fails the context.
- `ModuleMarkingCoverageTest`: D5 and the import rule of D6.
- `ComposeModuleConsistencyTest`: parses `../../compose.yaml` and `../../compose.ascend-web-hunter.yaml` with SnakeYAML and checks the rules of the `deployment-modules` spec: every profile is a switchable module or a companion, no profile is `core-chat` or a core name, every core service has no profile, every `depends_on` on a service under a module profile has `required: false`, the agent's `ASCEND_MODULES` line, every catalog module with services has at least one service under its profile, and the only `:?` guard under a module profile is the one for `SEARXNG_SECRET`.
- `PresetCatalogTest`: D13, and every catalog module name appears in the module table of `docs/MODULES.md`.
- `ModuleAccessInterceptorTest`, `FilteredToolCallbackProviderTest` additions, and `McpClientStartupInitializerTest` and `StartupLogConfigTest` additions for a connection of an inactive module (no entry, no initialise, no banner line, not counted).
- `McpReconnectSchedulerTest` for D19, and one case in `McpStartupToleranceIT` where a fake server that is down at start comes up and is `CONNECTED` within one lowered interval. The fake is the one fake MCP server class of the agent's test sources that `close-agent-test-gaps` task 4.2 writes and packages as its e2e image, started in-process (owner answer 91.2 of 2026-10-08).
- `DocumentRouterTest` additions for D14: an image and a PDF with one page without a text layer, each refused with `ModuleRequiredException` and no call on the Docling or Unstructured client, and a PDF with a text layer on every page ingested as today.
- Integration tests, one per preset, in the existing `integrationTest` task with Testcontainers: `PresetCoreIT`, `PresetCompanyDocsIT` and `PresetPersonalIT`. Each boots the agent with `ASCEND_MODULES` set to the preset and checks, against a list written by hand in the test, the exact request mappings from `RequestMappingHandlerMapping`, the agent tool names, the state of each MCP connection, the body of `GET /api/v1/modules`, and that `/actuator/prometheus` holds no meter of an inactive module while it holds the document search and memory meters in every preset. The lists are hand written so a bean that ignores its marking fails the test. The three own servers are stood in for by the one fake MCP server class of the agent's test sources that `close-agent-test-gaps` task 4.2 writes and packages as the test image `ascend-e2e-fake-mcp:local`, started in-process three times, once with the tools of each server (owner answer 91.2 of 2026-10-08). No change writes a fake MCP server program of its own.

### D18: How the installer asks for modules

This is the design the required edit to `add-customer-stack-installer` adds there:

1. Read the catalog from the checkout (`ConvertFrom-Json` in PowerShell, `jq` in Bash).
2. Say what the core holds and that it is always installed. Ask: `personal`, `company-docs`, `core` or `custom`. For `custom`, show each switchable module with its title and description and ask yes or no. Never offer a core part or a companion as a module.
3. Add every missing `requires` module and print which ones were added and why.
4. Write `COMPOSE_PROFILES`. Always generate the secrets of the core and the guarded secrets of D11 (`SEARXNG_SECRET`, `GRAFANA_ADMIN_PASSWORD`, `SANDBOX_RUNNER_TOKEN`), and ask only for the secrets of the chosen switchable modules. Ask for companions only when their module is chosen, and never turn on `clamav` by default (owner answer 51.2).
5. Always set up the sandbox host: gVisor (`runsc`) and `DOCKER_SOCKET_GID`, because the sandbox runner runs in every deployment.
6. Only when `audio` is chosen, check for a GPU: fill the model cache when the server has one, and make the OpenAI backend the default when it has none (installer D5, owner decision 65.5 of 2026-10-04).
7. The smoke test compares `GET /api/v1/modules` with the chosen list.

### D19: A failed MCP server is retried in the background

Once only active modules get a connection (D7), the banner and the retry rules of `mcp-startup-resilience` change together, so this change owns the delta of that capability that covers connections, the banner and the retry (review finding 4), and `add-mcp-tool-servers` builds on it (required edit). `upgrade-spring-boot-4` also carries a delta of `mcp-startup-resilience`, which lands first: it removes "Configuration uses Spring AI's built-in deferral flag" and adds it back as "Configuration uses Spring AI's built-in MCP deferral flag". This change modifies "Tool callback provider filters by initialised-client state", "A session that goes stale after startup is reconnected once, then demoted" and "Readiness banner renders per-server MCP status", and adds "A failed client is retried in the background". The two deltas touch different requirements, so they do not conflict at archive, and this change's text does not refer to the deferral flag requirement under either name.

This change owns `McpReconnectScheduler` (task 4.4). `add-mcp-tool-servers` reuses it and `app.mcp.reconnect.interval` for every server entry it derives, and adds no retry and no scheduler of its own (required edit 4 to that change). Today a client recorded `FAILED` at startup, or demoted to `FAILED` after a stale session, is never tried again until the agent restarts.

`McpReconnectScheduler` in `config/mcp/` is a `@Scheduled` method that runs every `app.mcp.reconnect.interval` (default 60 seconds, environment variable `APP_MCP_RECONNECT_INTERVAL`, bound by the record `McpReconnectProperties` with the same default, owner rule 98 of 2026-10-08) on Spring Boot's auto-configured `TaskScheduler`, the one local timer of the agent (owner answer 89.3 of 2026-10-08). This change switches on `@EnableScheduling` once, on a core configuration class, because it is the first change that needs it. Reconnecting is local work: every agent instance reconnects its own clients, so it does not use the shared scheduler engine of `add-shared-scheduler`, which comes later in the build order and is for persistent and cluster-wide work. The method skips a run while the previous one of the same instance still runs, so slow attempts never pile up. For each client of an active module recorded `FAILED` it calls `initialize()` under the same per-client gate that `FilteredToolCallbackProvider` uses for a stale session, bounded by `app.mcp.startup.init-timeout`. Success records `CONNECTED`, which changes the connected set and so invalidates the cached tool listing (ADR-010), and writes one INFO line naming the client, so the next request is offered its tools. Failure leaves it `FAILED` and writes at most one DEBUG line, so a server that stays down adds no WARN or ERROR line per retry, and the logging of the first failure at startup is unchanged. Every attempt sits in its own try and catch, so a retry never fails the application, and no chat request waits for it. A connection of an inactive module has no registry entry (D7), so it is never retried.

Alternative considered: retrying on the next chat request. Rejected: the request would wait up to the init timeout for a server that is down.

### D20: The modules documentation

The owner asked for good documentation of the modules. `docs/MODULES.md` follows the naming of the existing guides in `docs/` (`DEPLOYMENT.md`, `OBSERVABILITY.md`, `INGESTION.md`: upper case, one topic per file) and replaces the `docs/DEPLOYMENT_MODULES.md` of the draft. It holds, in this order:

1. What a module is, and what the core is: every part of D0 with its services, and why it is always on (the system does not work as the product without it).
2. A text diagram of the core and the switchable modules around it, with the `requires` and `uses` arrows of D3, kept in the file so it stays in version control.
3. One section per switchable module: its compose services and companions, its agent tools, its routes, its settings, the modules it requires and uses, its agent secrets, and its memory cost. The memory cost is the `deploy.resources.limits.memory` and `deploy.resources.reservations.memory` of each of its compose services, read from the compose files when the section is written, with a link to `docs/architecture/memory-budget.md` for measured peaks. A module with no service of its own says that it adds no container.
4. The presets with their module lists and when to choose each, with the reason for `company-docs` from D13, and that no preset holds `clamav`.
5. How to switch: edit `COMPOSE_PROFILES` in `.env`, then `docker compose up -d`. One command per code block. A command that is the same in PowerShell and Bash gets one block, and a PowerShell and a Bash block are shown only where they differ (for example setting a variable in the current shell). The rule that `--profile` is never used to switch a module, the three variables every deployment must set (`SEARXNG_SECRET`, `GRAFANA_ADMIN_PASSWORD`, `SANDBOX_RUNNER_TOKEN`), and Docker Compose 2.20 or later.
6. How tenant policy narrows further: the narrowing order of D9, that the core is never narrowed by a module grant, the 403 `module_denied` answer, and that single core tools are switched per tenant by the tool policy.
7. Troubleshooting: every refusal of D4 with its exact message and its fix, the 422 `module_required` answer for images and scanned pages without `ocr`, the 404 for a route of an inactive module, a missing `:?` variable, and a module whose tools are missing because `--profile` was used.
8. How a later change adds a module: the catalog entry, the marking, the profile, the preset, the `.env.example` line and the row in this file.

The root `README.md` gets a short "Modules" section that names the core and the presets and links `docs/MODULES.md`, and its documentation map links it. The root `AGENTS.md` gets the profile column in its compose tables and a "Deployment modules" paragraph that links `docs/MODULES.md`. `update-docs-and-architecture` links it from its documentation map and lists the module of each service (required edit).

### D21: Company extension ports

Owner rule of 2026-10-04: no personal or base change may depend on a company change, and company work plugs in only through extension points with safe defaults. Four concerns are needed by many personal changes and are filled in by company changes: recording an audit event, recording a unit of usage, asking whether a metered action is still within quota, and asking whether a tenant may use a provider and model. If each personal change declared its own port for them, a company change would have to implement one port per personal change. So this change owns all four ports once (dependency fix of 2026-10-05 and phase B ruling 13.1 of the same day). The change-local ports `RunQuotaGate` of `add-agent-subagents` and `CodingQuotaGate` of `add-coding-agent-delegation` become `QuotaGate`, and the provider and model check `CodingProviderPolicy` of `add-coding-agent-delegation` becomes `ModelAccessPolicy` unless it checks something coding-specific, which that change decides and states. `ProviderKeyResolver` of `add-coding-agent-delegation` stays its own port.

All four ports, their request and answer records and their defaults live in the package `com.lukk.ascend.ai.agent.extension`. Every record is immutable. The fields below were settled from what the callers of build groups 3 and 4 record or ask (read on 2026-10-05 in their designs and tasks), so no caller needs a field the record lacks:

- `AuditEventPort` with one method, `record(AuditEvent)`. `AuditEvent` holds `action` (a stable upper snake case event name such as `SKILL_WRITTEN` or `APPROVAL_DECIDED`), `tenantId`, `actor` (an `AuditActor` with `kind`, one of `USER`, `SYSTEM` and `SERVICE`, and `id`: the user id, the system task name or the client id), `target` (an `AuditTarget` with `kind`, for example `skill` or `approval`, and `id`), `outcome` (`SUCCESS`, `DENIED` or `FAILED`), `occurredAt` (from the injected `Clock`), `requestId` (the trace id of the request when there is one, otherwise empty) and `details`, a map of extra non-secret text values a caller records, for example a commit id, an origin, a category, a version or the note path of `add-obsidian-vault` (owner answer 72.7 of 2026-10-06). No field ever holds a secret, a token or the content of a document, a prompt, an answer or a file. The default `LogAuditEventPort` writes exactly one structured INFO log line per event with the action, the tenant, the actor, the target and the outcome, and nothing else: it never prints `details`, so a personal value such as a note path stays out of every log line and only a registered company audit store saves it. `add-audit-and-gdpr-compliance` (company, build group 5) registers its `AuditRecorder` backed implementation later, which stores every field.
- `UsageEventPort` with one method, `record(UsageEvent)`. `UsageEvent` holds `requestType` (the kind of use, for example `chat`, `subagent`, `scheduled`, `self-review`, `self-check`, `mcp-tool`, `coding-agent`, `sandbox` or `transcription`, as each caller names it), `tenantId`, `userId` (empty for work without a user), `provider` and `model` (empty when no model was called), `inputTokens` and `outputTokens` (0 when no model was called), `quantities` (a map from a quantity name to a number, for example `sandbox_seconds` or `audio_seconds`), `runId` and `parentRunId` (empty when the use belongs to no run), `attributes` (a map of extra non-secret text values, for example the MCP server id and the prefixed tool name) and `occurredAt`. The default `NoOpUsageEventPort` does nothing. `add-usage-metering-and-quotas` (company, build group 5) registers its `UsageLedgerRecorder` backed implementation later.
- `QuotaGate` with one method, `QuotaDecision check(QuotaRequest)`, asked before a metered action: before each model call of a run (`add-agent-subagents`) and before and during a coding run (`add-coding-agent-delegation`). `QuotaRequest` holds `tenantId`, `userId`, `requestType` (the same names as `UsageEvent`), `provider` and `model` (empty when not known yet) and `runId` (empty outside a run). `QuotaDecision` holds `allowed`, and when not allowed the `reason` code `quota_exceeded` and `retryAfter` (the time until the quota window rolls over, empty when unknown). A caller that gets a refusal stops the action: a run ends with `QUOTA_EXCEEDED`, a REST caller answers 429 with the problem detail code `quota_exceeded` and `Retry-After`. The default `AllowAllQuotaGate` allows every call. `add-usage-metering-and-quotas` registers the real one later.
- `ModelAccessPolicy` with one method, `ModelAccessDecision check(String tenantId, String provider, String model)`, asked whether a tenant may use a provider and model before any client is built and any token is spent. `ModelAccessDecision` holds `allowed`, and when not allowed the `reason` code `provider_denied` or `model_denied` and a detail that names the provider or the model. The default `ConfiguredModelAccessPolicy` allows every provider the deployment has enabled, with any model of it: every provider under `app.ai.providers` whose `enabled` is not `false`, and, while the module `coding` is active, every provider under `app.coding.providers`, so the default never refuses a coding run. `app.coding.providers` is empty until `add-coding-agent-delegation` (build group 4) fills it with `opencode-go` and `opencode-zen`, and the module `coding` enters the catalog with that change. The test of this rule (task 11.5) therefore uses a test catalog that holds a module `coding` and a test property source with a test provider under `app.coding.providers`, so it needs no class or configuration of `add-coding-agent-delegation` (owner answer 75.1 of 2026-10-07, item 15). It refuses with `provider_denied` a provider that `app.ai.providers` disables, a coding provider while `coding` is off, and a provider name neither list holds. This change calls it in `ChatModelResolver.resolve` with the tenant of `TenantContext.currentTenantId()` of `add-keycloak-login`, and a refusal answers 403 with the problem detail code `provider_denied` or `model_denied`, two values this change adds to `ApiErrorCode`. `add-tenant-policy` (company, build group 5) registers the tenant allow-lists as its implementation later, instead of editing `ChatModelResolver`.
- Every default is registered with `@ConditionalOnMissingBean`, so a deployment without company work runs the default and a company change replaces it by registering a bean of the port type, with no edit of this change or of any caller. A caller takes the port by constructor injection and never checks which implementation it got.
- The tenant of every event, request and check is the one `TenantContext.currentTenantId()` of `add-keycloak-login` answers when it is made, or the one a background worker bound with `TenantContext.runAs`.
- A change-local policy check that `add-tenant-policy` would govern and that none of the four ports expresses stays a port of the change that owns the feature, with a default that reads that change's own configuration (for example `ToolModeResolver` of `add-action-approvals` and `ModuleAccess` of D9).

None of the ports is a module and none carries `@ConditionalOnModule`: all belong to the core, so a call never fails because a module is off. `ModuleMarkingCoverageTest` needs no entry for them, because they are neither controllers, tools, scheduled tasks nor clients.

Alternative considered: one generic event bus that company changes listen to. Rejected: a listener cannot refuse or enrich, and an untyped event hides which fields an audit row needs. Four small typed ports keep each interface focused.

## Risks / Trade-offs

- [A deployment uses `docker compose --profile x up` and the agent never sees `x`] → the docs forbid it, every documented command edits `COMPOSE_PROFILES`, and the module's tools and banner line are visibly missing, so the mismatch shows at once.
- [Every deployment must set `SEARXNG_SECRET`, also one without web search] → accepted minus of keeping the guard (owner answer 41.2, D11). The installer always generates it, `.env.example` says it is needed in every deployment, and a missing value fails at once with a message that names it.
- [A company that runs without `ocr` cannot ingest images or scanned PDFs] → accepted (owner answer 41.3, D14). The refusal is a problem detail that names the module `ocr`, so the operator knows to add it, and `company-docs` holds `ocr`.
- [The core always costs its memory, also for a company that would not use the sandbox or monitoring] → accepted by owner answer 52. `docs/MODULES.md` states the memory of the core so a customer machine is sized for it.
- [An old `.env` still lists `rag`, `memory`, `sandbox` or `observability`] → the startup check refuses it with a message that the part is always on and the fix (D4).
- [The background retry of D19 contacts a server that stays down every interval] → one thread, each attempt bounded by the init timeout, at most a DEBUG line per attempt, and only for servers of active modules.
- [Compose older than 2.20 rejects `required: false`] → documented minimum version, and the installer checks `docker compose version`.
- [The coverage test misses a new kind of module bean, such as a message listener] → the test's list of checked kinds is extended in the same review that adds the new kind, and the per preset integration tests catch what reaches routes, tools and meters.
- [A tenant grant without a module's requirements] → `add-tenant-policy` refuses it, and `ModuleState.effectiveFor` drops a granted module whose requirements are not granted.
- [The `personal` preset grows with modules that need secrets the owner has not set] → outside `production` a missing agent secret is one WARN line, not a refusal, and the module's own server stays down until the secret is set.
- [Every migration runs everywhere] → empty tables of inactive modules. Accepted for one schema history (D15).

## Migration Plan

1. Land as build group 3, position 6 of the owner build order of 2026-10-04 (owner answer 94.5 of 2026-10-08), after `close-agent-test-gaps`, `upgrade-spring-boot-4` and `add-keycloak-login`, and before `add-shared-scheduler` and every other change that adds a module.
2. Before pulling this change, the owner adds the `personal` line from the new `.env.example` to his `.env`. Without it the next `docker compose up -d` starts the core alone, which still serves chat, document search and memory.
3. `docker compose up -d` recreates the agent and the services whose definitions changed.
4. Each later change adds its catalog entry, its marking and its profile as listed below.
5. Rollback: deploy the previous image and restore the previous compose files. No data moves.

## Required edits to other changes

This change does not edit any other change. Each edit is made in the named change, and the tasks here that depend on one are marked blocked. Every status below was checked on 2026-10-03, after the owner answers 51 and 52. Under the owner build order of 2026-10-04, `harden-cloud-deployment` (build group 3, position 4) and `add-file-download` (build group 2) land before this change, so the parts of their edits that need this change's catalog are made here (see their sections). The company changes named below (`add-customer-stack-installer`, `add-tenant-policy`, `update-docs-and-architecture`) land last, in build group 5, and plug in later. No task of this change waits for them.

### `add-mcp-tool-servers`

1. Design D1: `app.mcp.modules` and `APP_MCP_MODULES` are removed. An entry is enabled when its `module` is active in `app.modules.active`. Our three own servers name their modules, `ascend-weather-mcp` (`weather`), `ascend-web-hunter` (`web-search`) and `ascend-audio-scribe` (`audio`). Since owner answer 90 of 2026-10-08 the `module` field is optional in every profile, and an entry with no `module` is always on, with no `e2e` profile branch (sent to that change through the round 93 inbox). Only entries of active modules, and entries with no module, are derived into Spring AI connections. `app.modules.connections` of this change is removed.
2. Design D10: `ascend-agent` gets `ASCEND_MODULES: ${COMPOSE_PROFILES:-}` instead of `APP_MCP_MODULES`.
3. Design D11: `mcp-egress-proxy` carries no profile and is always on from `add-mcp-tool-servers` onward, because our own tool servers are always on (owner answer 76.5 of 2026-10-08). `ComposeModuleConsistencyTest` treats it as a core service, which has no profile. `add-openclaw-plugin-host` adds its own use of it when it lands (its task 8.4) and adds no profile to it. It is not a catalog companion. `add-mcp-tool-servers` ships no specific outside server (owner decision of 2026-10-02), so the five names `mcp-google`, `mcp-github`, `mcp-home-assistant`, `mcp-browser` and `mcp-files` are not in the catalog and not in `personal`, and their agent secrets `GITHUB_MCP_TOKEN` and `HOME_ASSISTANT_TOKEN` are not in any catalog entry.
4. Design D9, its context line 21, the banner bullet of its D13 that shows `[Off]`, and the requirement "A failed server is retried in the background" of `specs/mcp-tool-servers/spec.md`: this change owns `McpReconnectScheduler` (D19, task 4.4) and its `mcp-startup-resilience` delta owns the retry and banner rules. `add-mcp-tool-servers` reuses that scheduler and `app.mcp.reconnect.interval` and adds no scheduler of its own. It removes its own retry requirement, the `OFF` state and the `[Off]` banner line: a server of an inactive module has no connection and no banner line.
5. `specs/mcp-tool-server-deployment/spec.md`: "the agent SHALL receive the same list as `app.mcp.modules`" becomes "the agent SHALL receive the same list as `ASCEND_MODULES`".

Edits 1 to 5 are made in that change (its section for this change, checked 2026-10-03).

### `add-openclaw-plugin-host`

This change was named `add-openclaw-channel-host` until 2026-10-02. Its service is `ascend-openclaw-host`.

1. Design D15 and task 3.1: `app.channels.enabled` is removed. Channel beans carry `@ConditionalOnModule("channels")` and the agent side of the app plugins carries `@ConditionalOnModule("openclaw-apps")`. With a module off its routes answer 404 because they do not exist, as its spec already requires.
2. Design D15: "the same value `add-mcp-tool-servers` passes for its modules" is now true by construction, both read `ASCEND_MODULES`.
3. Voice notes check `ModuleState` for `audio` and answer the sender that voice notes are not available when it is off. Notifications reach a chat platform through the core notification delivery of `add-shared-scheduler`, so `channels` does not use `scheduler`. The `uses` of `channels` is `audio` only.
4. Catalog entries `channels` and `openclaw-apps`, both added to `personal`. `openclaw-apps` requires nothing, uses nothing, and has the agent secret `OPENCLAW_APPS_MCP_TOKEN`. Its MCP server entry of `add-mcp-tool-servers` names the module `openclaw-apps`.
5. Compose: the containers that hold chat platform connections carry the profile `channels`, and the containers that run app plugins carry the profile `openclaw-apps`. The app plugin containers use `mcp-egress-proxy`, which is always on and carries no profile (edit 3 to `add-mcp-tool-servers`, owner answer 76.5 of 2026-10-08).

Edits 1 to 5 are made in that change (checked 2026-10-03, its D3).

### `add-obsidian-vault`

1. The `obsidian-sync` service keeps the profile `obsidian`. A catalog entry `obsidian` with empty `requires` (document search is core, owner answer 52) and the agent secret list empty (the token lives in the sync container), added to `personal`.
2. The five `obsidian_*` tools, the watcher and the `OBSIDIAN` connector type carry `@ConditionalOnModule("obsidian")`. The connector framework they plug into is core.
3. Design line 379: "Without the `obsidian` compose profile and without an `OBSIDIAN` connector, nothing runs" becomes "without the `obsidian` module".

Edits 1 to 3 are made in that change (checked 2026-10-03, its design section for this change and its proposal: the entry `obsidian` has no `requires` entry).

### `add-file-download`

1. A catalog entry `web-download` that requires `web-search`, uses nothing (document search is core, owner answer 52), and owns the companion `clamav`, added to `personal`. No preset holds `clamav` (owner answer 51.2), so `DOWNLOAD_SCAN_MODE` stays `off` by default. `add-file-download` lands earlier (build group 2), when no catalog exists, so this change adds the entry itself (D3, task 1.1).
2. ascend-web-hunter reads `ASCEND_MODULES` and registers the `web_download_*` MCP tools and the `/api/v2/web/downloads` routes only when `web-download` is in it.
3. The agent's connection entry for `ascend-web-hunter` marks the `web_download_*` tools with the module `web-download`. `knowledge_add_download` and `POST /api/v1/documents/from-download` carry `@ConditionalOnModule("web-download")`. Since 2026-10-04 this edit lives in `add-download-ingestion` (its D11 and D16), which took the agent parts of `add-file-download` under the owner rule of that day, and `add-file-download` keeps edits 1, 2, 4 and 5.
4. The `clamav` service must not use a `${VAR:?}` guard (D11).
5. `clamav` is not added to `apps/ascend-web-hunter/deploy-standalone/compose.yaml`, which is web search only (D11). `add-file-download` adds it to the list of intended differences in `deploy-standalone/README.md`.

Edits 2, 4 and 5 are made in that change (checked 2026-10-03, its section for this change: no `uses` entry, `@ConditionalOnModule("web-download")` alone, and no preset holds `clamav`). They need nothing of this change, because ascend-web-hunter reads `ASCEND_MODULES` from `COMPOSE_PROFILES` directly. Edit 1 is made by this change since the dependency fix of 2026-10-05. Edit 3 moved to `add-download-ingestion` on 2026-10-04 with the agent parts.

### `add-observability`

1. Monitoring is core and always on (owner answer 52 of 2026-10-03). No observability container carries a profile, every service always exports, there is no opt-out profile, and the `GRAFANA_ADMIN_PASSWORD` guard of `harden-cloud-deployment` stays. The earlier edit of 2026-10-02 that made observability a module is withdrawn.

Made in that change (checked 2026-10-03, its D7 and its `observability-stack` spec).

### `add-customer-stack-installer`

1. A new decision after D4: the module question of D18, before any secret is asked, with the core always installed.
2. D4: each variable of a switchable module carries the module it belongs to, and a variable of an inactive module is neither generated nor asked. The core secrets (monitoring, document search, memory and the sandbox) are always generated, and so are `SEARXNG_SECRET`, `GRAFANA_ADMIN_PASSWORD` and `SANDBOX_RUNNER_TOKEN` (D11). `VNC_PASSWORD` belongs to `web-search`.
3. D5: the GPU check and the model cache only when `audio` is chosen, with the OpenAI backend as the default on a server without a GPU (owner decision 65.5 of 2026-10-04, which also removed the installer's provider step and Terraform). gVisor and the sandbox runner always.
4. D7: the smoke test checks `GET /api/v1/modules`.
5. `specs/stack-provisioning/spec.md`: requirements for the module question and the module-aware secret list.

Edits 1 to 5 are made in that change (checked 2026-10-03).

### `add-tenant-policy`

1. Design D3 and D4: the policy gains `modules`, a list of switchable module names, and the deployment default `app.policy.default.modules` (default: every active module). A tenant may only narrow. An update naming an inactive or unknown module, a core name, or a set not closed under `requires`, is refused with 400. The core is never part of a grant.
2. `TenantPolicyService` provides the `ModuleAccess` bean of this change's D9, replacing `AllActiveModuleAccess`.
3. Design D2: the tool filter drops tools of modules not effective for the tenant before it applies the allow-list.
4. A new requirement in `specs/tool-policy/spec.md` (or a new `module-policy` spec) with the 403 `module_denied` scenario.

Edits 1 to 4 are made in that change (checked 2026-10-03, its D6 and its `tool-policy` spec: grants cover only the switchable modules, the core is never granted or denied, and the 403 `module_denied` scenario).

### `add-agent-skills`

1. `app.skills.enabled` is removed. The `skills` catalog entry covers the registry, the skill tools, `skill_search` and `/api/v1/skills`.
2. The capability index, `CapabilitySource`, `CapabilityIndexSync`, `ChatToolset`, `AgentNativeTool`, `VersionedFolder` and `app.agent-home` are core and carry no marking (D3). It reads the tenant through `TenantContext` of `add-keycloak-login` and adds no tenant seam of its own (dependency fix of 2026-10-05).
3. `ChatToolset` drops tools of modules not effective for the tenant (D10).

Edits 1 to 3 are made in that change (checked 2026-10-03).

### `add-agent-subagents`

1. A catalog entry `subagents` that requires `skills`, and markings on the `Task` tool, the `TaskOutput` tool, the catalog type `SubagentCatalogType` of the one catalog of `add-agent-skills` (owner answer 89.5 of 2026-10-08), `subagent_definition_write` and `AscendSubagentExecutor`.
2. The run table, `SubagentRunService` with `ScheduledRunStarter`, `RunController` with `/api/v1/runs`, `RunLoop`, `RunSlots`, `RunBudget`, `PriceTable`, `SubagentModelResolver`, `ToolPermission`, `SubagentProperties`, the finished runs block and the system task `run-orphan-sweep` and the retention entry `subagent-run` of the shared retention task of `add-shared-scheduler` (owner answer 89.7 of 2026-10-08) are core and carry no marking (D3).

Edits 1 and 2 are made in that change (checked 2026-10-03).

### `add-agent-sandbox`

1. The sandbox is core (owner answer 52): no catalog entry `sandbox`, no tenant module grant, no `profiles:` on `ascend-sandbox-runner`, and `app.sandbox.enabled` removed without a replacement.
2. The classes of `service/sandbox/`, `SandboxOutputController` and `SandboxProperties` go on the `core-chat` list of `ModuleMarkingCoverageTest` with no `@ConditionalOnModule`.
3. `SANDBOX_RUNNER_TOKEN` is not a module secret. It is guarded with `${SANDBOX_RUNNER_TOKEN:?...}` on the always-on runner and the agent, and every deployment sets it.

Edits 1 to 3 are made in that change (checked 2026-10-03, its D11 and its section for this change).

### `add-coding-agent-delegation`

1. `app.coding.enabled` is removed. A catalog entry `coding` with empty `requires` (the sandbox is core, owner answer 52), with `GITHUB_APP_ID` and `GITHUB_APP_PRIVATE_KEY` as agent secrets, which the module secret check covers (under `production` a `ProductionStartupCheck` of `ProductionStartupGuard`, owner answer 89.10 of 2026-10-08).
2. The error code `coding_disabled` is removed: the routes do not exist when the module is off (404) and answer `module_denied` when the tenant lacks it.

Edits 1 and 2 are made in that change (checked 2026-10-03, its design line 6 and its section for this change: `coding` requires no module).

### `add-self-built-integrations`

1. `app.integrations.enabled` is removed. A catalog entry `self-built-integrations` that requires `coding` and uses `self-improvement` (D3). The `integrations_disabled` code is removed like `coding_disabled`.
2. Every registered integration's MCP entry belongs to `self-built-integrations`, so switching it off removes every integration tool.

Edits 1 and 2 are made in that change (checked 2026-10-03), the `uses` entry in its D26.

### `add-self-improvement`

1. `app.self-improvement.enabled` is removed. A catalog entry `self-improvement` that requires `subagents`. The per tenant flag `self_improvement` becomes the tenant module grant of D9.

Made in that change (checked 2026-10-03).

### `add-shared-scheduler`

1. It adds the module `scheduler` to the catalog, with its title and description, empty `requires` and `uses` (D3), and adds it to `personal`. The module has no compose service and no agent secret.
2. The shared scheduler engine and its system tasks are core and carry no marking. A system task that belongs to a switchable module is registered only when its module is active.
3. `/api/v1/notifications`, the notification store and notification delivery are core and carry no marking (D3).

Edits 1 to 3 are made in that change (checked 2026-10-03).

### `add-scheduled-tasks`

1. The job tools, `owner_notify` and `/api/v1/scheduled-jobs` join the `scheduler` entry and carry `@ConditionalOnModule("scheduler")`. The entry gains `requires: [subagents]` and no `uses` entry.
2. A firing for a tenant that lacks `scheduler` is skipped with the reason `module_denied`. A system task that belongs to a switchable module (an `OBSIDIAN` rescan) is registered only when its module is active.
3. Design line 436: "The `channels` compose profile switches the channel on" becomes "the `channels` module".

Edits 1 to 3 are made in that change (checked 2026-10-03).

### `add-connector-framework`, `add-document-management-api`, `add-passage-level-citations`, `add-web-crawl-rag-connector`

1. Document search is core (owner answer 52): their controllers, connector framework, services and citation classes carry no `@ConditionalOnModule` and no tenant module grant guards them. The `WEB_CRAWL` connector type carries `@ConditionalOnModule("web-search")`.
2. `add-connector-framework`: a sync run of a connector type that belongs to a switchable module, for a tenant without that module, is skipped with `module_denied`.
3. `add-passage-level-citations`: its labeled passages and citations go through the RAG `ChatContextContributor` of D6, which this change keeps.

Edits 1 to 3 are made in those changes (checked 2026-10-03, `add-document-connectors` D20, which moved with the framework to `add-connector-framework` D20 on 2026-10-04, `add-document-management-api` D13, `add-passage-level-citations` D10, `add-web-crawl-rag-connector` design line 17).

### `harden-cloud-deployment`

1. Design D1: `captcha-intervention` is a companion of `web-search` in the catalog. `.env.example` describes `COMPOSE_PROFILES` as the module list of `docs/MODULES.md`, with `redis` and `captcha-intervention` as companions. `harden-cloud-deployment` lands earlier (build group 3, position 4), when no catalog exists, so this change makes the catalog entry and the `.env.example` text itself (tasks 1.1 and 4.2).
2. `specs/ascend-agent-containerization/spec.md`, requirement "ascend-agent runs as a Compose service by default": `required: false` only on `depends_on` entries for services under a module profile, the agent's dependencies on the core services `ascend-memory`, `docling-serve` and `unstructured-api` without it, and the agent receives `ASCEND_MODULES`.
3. `gateway` and the observability services stay without a profile, as core. The `GRAFANA_ADMIN_PASSWORD` guard stays.
4. The cloud VM guide always holds the gVisor (`runsc`) and `DOCKER_SOCKET_GID` steps, because the sandbox runner runs in every deployment. The sandbox runner comes with `add-agent-sandbox` (build group 4), so that change adds these steps to the guide when it lands.

Edits 2 and 3 are made in that change (checked 2026-10-03). Edit 1 is made here, and edit 4 by `add-agent-sandbox`, since the dependency fix of 2026-10-05. Edit 2 is carried by this change itself, because `harden-cloud-deployment` lands first: this change's deltas of `production-deployment` ("Personal-machine artifacts are opt-in" and "Compose declares production runtime posture") and of `ascend-agent-containerization` ("ascend-agent runs as a Compose service by default" and the `.env.example` requirement) add the companion profile of `ngrok-ascend-web-hunter`, `required: false`, `ASCEND_MODULES` and `COMPOSE_PROFILES` as the module list (tasks 4.7 to 4.9, phase B ruling 13.6 of 2026-10-05).

### `update-docs-and-architecture`

1. Its documentation map links `docs/MODULES.md`, and its service table lists the module of each service, or "core" for an always-on service.

Made in that change (checked 2026-10-03).

### Checked, no edit needed

- `add-keycloak-login`: Keycloak is core and a prerequisite of every deployment (owner answer 70.2 of 2026-10-04: the personal assistant itself needs real Keycloak login). The service token rule is unchanged. It lands before this change, so `GET /api/v1/modules` adds its own row to the authorization matrix of that change (task 6.1), and `ModuleAccess` reads the tenant through its `TenantContext` (D9).
- `close-agent-test-gaps`: it lands before this change, and its e2e overlay holds the hand-written MCP connection `e2e-fake`. The fake MCP server belongs to no module (owner answer 72.5 of 2026-10-06), so its connection names no module and is always on, in every profile (owner answer 90 of 2026-10-08, D7, task 4.6), and the overlay gets no module entry.
- `add-auth-and-identity`: company parts (tenant claim, groups, brokering) only. It adds its parts to the deployment when it lands. No edit.
- `add-action-approvals`: approvals are core. Approval kinds of a module simply never occur when it is off.
- `add-agent-soul`: core. Its `app.soul.*` flags switch parts, which D2 allows.
- `add-usage-metering-and-quotas`: request types of inactive modules never occur. Quotas already limit token use per tenant. It registers its implementation of `UsageEventPort` (D21) later and adds its own parts to the deployment when it lands.
- `add-audit-and-gdpr-compliance`: it registers its implementation of `AuditEventPort` (D21) later and adds its own parts to the deployment when it lands.
- `add-tenant-isolation`, `add-tenant-administration`: company parts, added to the deployment by each when it lands.
- `add-chat-streaming-and-conversations`: core.
- `add-flutter-chat-app`: no compose service. It can read `GET /api/v1/modules` to hide screens, which is its own later choice.

## Decision record numbering

The monorepo record "Deployment modules: an always-on core, one catalog, COMPOSE_PROFILES as the switch" takes the next free number in `docs/architecture/decisions/` at implementation time (today `ADR-M010` is the highest).

## Owner answers

Answers of 2026-10-02 (answer 41):

1. 41.1: `observability` stays out of the company preset. Superseded by answer 52: monitoring is core and runs in every deployment.
2. 41.2: the compose `:?` guard for `SEARXNG_SECRET` stays, always. Every deployment must set `SEARXNG_SECRET`, also one without web search, and that is the accepted minus (D11).
3. 41.3: with `ocr` off there is no OCR reading at all. Images and scanned PDF pages are refused with a clear problem detail and are never sent to Docling OCR (D14).
4. 41.4: module access per employee group is a non-goal for now (Non-Goals). The tenant grant of D9 is the seam a later change can extend.

Answers of 2026-10-03 (answers 51 and 52):

1. 52: switchable modules are only services the system works without: `ocr`, `audio`, `web-search`, `web-download`, `weather`, `obsidian`, `channels`, `openclaw-apps`, `coding`, `self-built-integrations`, `subagents`, `skills`, `self-improvement` and `scheduler`. Core chat, monitoring, document search, memory, the sandbox and the prerequisites are always on (D0). Monitoring is not a module (D12).
2. 51.2: no virus scanner by default in any preset (D13).
3. 51.3: every error problem body carries `traceId` from the current trace. `add-observability` owns that decision, and `upgrade-spring-boot-4` adds the field to its D19. It also covers the `module_denied` and `module_required` bodies of this change, with nothing to add here.
4. 53: the `company-docs` preset (the core plus `ocr`) is kept as the company preset (D13). This closes open question 2.

Answers of 2026-10-06 (answer 72):

1. 72.5: the fake MCP server of the test harness belongs to no module. It starts only with the deterministic test profile `e2e` and its phase of `docs/E2E_RUN_SCENARIOS.md`, and the selection check accepts its module-less connection only under that profile (D7, task 4.6). This closes the module question of task 4.6. (The profile branch is superseded by owner answer 90 of 2026-10-08: a connection with no module is always on in every profile. Since owner answer 98.1 of 2026-10-08 no `e2e` profile exists at all, and the fake server's connection reaches the agent through the overlay that the deterministic phase copies in, `close-agent-test-gaps` D7.)
2. 72.4 (recorded in `add-file-download`): until this change lands, `clamav` starts only when `COMPOSE_PROFILES` names it. This change keeps it as the companion of `web-download` that no preset holds (D13).
3. 72.1: `harden-cloud-deployment` moved to build group 3, position 4, so this change moves to position 5 (position 6 since owner answer 94.5 of 2026-10-08). `harden-cloud-deployment` still lands before it, so every edit this change makes to the files of that change stays as written.

## Owner decisions of 2026-10-06

Answer 73.1: the data that exists today in the development database, Redis, Qdrant, object storage and AscendMemory is disposable. No change converts it, backfills it or depends on it, and any change may start from empty stores. This change needs none of today's data. Its tables start empty.

## Owner decisions of 2026-10-07

Answer 75.1: the owner approved the fixes of the review of 2026-10-07. In this change they fix item 12 (the proposal no longer gives the overlay connection `e2e-fake` a module, as D7, task 4.6 and owner answer 72.5 say), item 13 (the sentence that said this change carries no delta of the `ascend-agent-containerization` requirement is deleted, because it does), item 14 (`flaresolverr`, which `remove-flaresolverr-tier` removed in build group 2, leaves the `web-search` rows), item 15 (the test of the coding rule of `ConfiguredModelAccessPolicy` uses a test catalog, D21 and task 11.5) and item 55 (task 1.1 credits `clamav` to `add-file-download` only). Follow-up of item 5: edit 3 to `add-mcp-tool-servers` and the compose edit 5 to `add-openclaw-plugin-host` now say that `add-openclaw-plugin-host` adds the profile `openclaw-apps` to `mcp-egress-proxy` (its task 8.4).

## Owner decisions of 2026-10-08

Answer 76.5: `mcp-egress-proxy` of `add-mcp-tool-servers` is always on from that change onward, because our own tool servers are always on. It carries no compose profile and is listed with the core chat services of D0 and with the services of later changes that have no profile (D11). `ComposeModuleConsistencyTest` therefore treats it as a core service. The `openclaw-apps` row of D3 no longer names it, and `add-openclaw-plugin-host` still adds its own use of it (its task 8.4) without a profile. This replaces the follow-up of item 5 of 2026-10-07 recorded above.

Answer 81.3, addition (mandatory): every host and port of this change follows the rules of `close-agent-test-gaps` D8, so the plan works on Linux Docker Engine, where `host.docker.internal` does not resolve by itself. Checked on 2026-10-08: the `ascend-agent-containerization` requirement of this change keeps `extra_hosts: ["host.docker.internal:host-gateway"]` on `ascend-agent` (rule 3) and publishes `9917` through `${EXPOSE_BIND:-127.0.0.1}` (rule 2). The module-less connection `e2e-fake` reaches the fake MCP server by container name at `http://e2e-fake-mcp:7032` (owner answer 81.1 of 2026-10-08, rule 1). No change is needed here.

Answer 87 (rule R1): several agent instances run at once. Every mechanism of this change is safe with several instances, because none holds shared state in one process: the catalog, the active modules and `ModuleState` are read from the same configuration on every instance, each instance connects, records and reconnects only its own MCP clients (`McpClientStatusRegistry` describes the clients of that instance), and the company ports keep no state of their own.

Answer 88 (rule R2): every company plug-in point of this change stays: the module access port with its tenant narrowing (D8, D9, D10) and the four company extension ports of D21. Review items S1-1 and S1-2 are therefore not applied.

Answer 89.3: `McpReconnectScheduler` is a `@Scheduled` method on Spring Boot's auto-configured `TaskScheduler`, the one local timer of the agent, and this change switches on `@EnableScheduling`, because it lands before `add-shared-scheduler`. No private `ThreadPoolTaskScheduler` (D19, task 4.4).

Answer 90: the module of an MCP connection is optional, a connection with no module is always on, and the selection check has no `e2e` profile branch. This replaces answer 72.5 for the check (D4, D7, task 4.6, the `module-gating` spec). The same text goes to `add-mcp-tool-servers` for its server entries (its D1 and its `mcp-tool-servers` spec).

Answer 91.2: the fake MCP server `e2e-fake-mcp` is the one fake MCP server class of the agent's test sources, packaged as the test image `ascend-e2e-fake-mcp:local` by `close-agent-test-gaps` task 4.2 and started in-process by the agent's integration tests, so no change writes a fake MCP server program of its own. This change's reconnect case in `McpStartupToleranceIT` and its per preset integration tests start that class in-process, and no third fake is written (D17, tasks 4.4 and 7.1). Checked by `close-agent-test-gaps` on 2026-10-08: `McpStartupToleranceIT` holds no fake MCP server today, so the class of task 4.2 is the first one.

Answer 91.3: the stack changing preset specs of tasks 10.5, 10.6 and 10.7 (the core, `company-docs` and `personal` presets and the refused module selections) are removed, because `PresetCoreIT`, `PresetCompanyDocsIT`, `PresetPersonalIT`, `ComposeModuleConsistencyTest`, `DocumentRouterTest`, `ModuleSelectionEnvironmentPostProcessorTest` and the live preset run of task 8.3 already prove what they proved. The fixtures of task 10.2 and the Bruno requests of task 10.3 that only they used go with them. The live active modules spec (task 10.4) and the two AI-run specs (task 10.8) stay.

Answer 93: the gauge `module.active` is dropped, because the endpoint and the banner block stay and show the same (review item S3-9, D16, task 6.2, task 10.4). Review items S1-1 (the tenant narrowing seam), S1-2 (the four company extension ports), S2-7 (`ChatContextContributor`) and S2-11 (module features no module of this change uses yet) are not applied: S1-1 and S1-2 are company plug-in points (rule R2), and S2-7 and S2-11 would move work into later changes against the owner's plug-in rule and drop checks he asked for (rule R3).

Answer 89.5 (received from `add-agent-subagents` and `add-agent-skills`): the subagent definitions are the catalog type `SubagentCatalogType` of the one catalog of `add-agent-skills` in the module `subagents`, and the one catalog belongs to the module `skills` (D3 and the required edits to `add-agent-subagents`).

Answer 89.7 (received from `add-agent-subagents`): run retention is the entry `subagent-run` of the shared retention task of `add-shared-scheduler`, core like the run sweep (D3 and the required edits to `add-agent-subagents`).

Answer 89.10 (received from `harden-cloud-deployment` and `add-keycloak-login`): one production startup guard. Under the `production` profile `ModuleSecretCheck` runs as a `ProductionStartupCheck` of `ProductionStartupGuard` of `add-keycloak-login`, and the always-needed credentials are required placeholders of `application-production.yaml` (D4 and task 1.3). The base requirement of the `production-deployment` spec that this change modifies carries the new text.

Answer 89.12 (received from `add-observability`): Vector is removed and logs go through the OpenTelemetry collector, so the core monitoring services are eight: `prometheus`, `grafana`, `loki`, `otel-collector`, `tempo`, `postgres-exporter`, `redis-exporter` and `container-metrics-exporter` (D0, D11, the `deployment-modules` and `observability-stack` specs, task 8.5).

Answer 89.14 (received from `add-observability`): no custom `OTEL_ENABLED`. A service exports its traces whenever its OTLP endpoint is set. This change still adds no switch that reads `ASCEND_MODULES` for export (D12, the `observability-stack` spec).

Answer 91.1: the deterministic phase restarts only the agent, and AscendMemory is faked in the Mockoon container under `/ascend-memory/` (`close-agent-test-gaps` D7). No spec of this change runs in that phase, so nothing else changes here.

Answer 94.5: the new change `scale-ocr-and-audio-across-containers` takes build group 3, position 5, directly after `harden-cloud-deployment`, so this change moves from position 5 to position 6 (`openspec/BUILD_ORDER.md`), and the positions of the other moved changes it names were moved by one too. Its dependencies and its tasks do not change.

Answer 98 (owner rule 98, every value with a default is a setting): made external: `app.mcp.reconnect.interval` (`APP_MCP_RECONNECT_INTERVAL`, default 60 seconds) as `${APP_MCP_RECONNECT_INTERVAL:60s}` in `application.yaml`, the same default in the new record `McpReconnectProperties`, and `- APP_MCP_RECONNECT_INTERVAL=${APP_MCP_RECONNECT_INTERVAL:-60s}` on the `ascend-agent` service of `compose.yaml` (D19, task 4.4). Already external and kept: `app.modules.active` from `ASCEND_MODULES` (default empty, which means `core-chat` only), passed by compose as `ASCEND_MODULES=${COMPOSE_PROFILES:-}` (task 4.8), and the compose-level `COMPOSE_PROFILES` (default empty, the core alone, `.env.example` ships the `personal` preset). Kept as constants, because they are not operational: the catalog file `modules/catalog.json` with its module names, presets and companions (the product's list of names, changed only by a change that adds a module), the fixed module of each MCP connection in `app.modules.connections`, the problem codes `module_denied`, `module_required`, `provider_denied` and `model_denied` with their types, the route `GET /api/v1/modules`, and the class and package names of D21. `QuotaGate`, `ModelAccessPolicy`, `AuditEventPort` and `UsageEventPort` and their defaults carry no value with a default. The 120 seconds of the `deployment-modules` scenario for a refused start is a test wait, not a setting (answer 90). The agent port `9917` and `EXPOSE_BIND` are existing settings this change does not change. Rows: `apps/ascend-agent/docs/CONFIGURATION.md` for `app.mcp.reconnect.interval` and `app.modules.active`, each ending "Added by `add-deployment-modules`.", and `docs/CONFIGURATION.md` for the compose-level `COMPOSE_PROFILES`, in the same commit as the setting (tasks 4.4 and 4.10). No test or measurement of this change uses LM Studio: the two AI-run specs of task 10.8 name no provider in this plan. The `.env.example` requirement of the `ascend-agent-containerization` delta and the logging requirement of the `production-deployment` delta follow the rule too (aligned in the final pass of round 98): a variable with a default gets no new `.env.example` line, only its row in the configuration reference, and the `x-logging` values come from `DOCKER_LOG_MAX_SIZE` and `DOCKER_LOG_MAX_FILE` of `harden-cloud-deployment` (its tasks 1.4 and 1.7).

Answer 98.1: no `e2e` profile exists any more. The test settings of `close-agent-test-gaps` reach the running agent by a copy of `apps/ascend-agent/e2e/overlay/application-e2e.yaml` into `/app/config/application.yaml` and a restart, and the phase ends with a recreate of the agent (`close-agent-test-gaps` D7). The module-less connection `e2e-fake` of that overlay is always on, like every connection with no module (answer 90), so the selection check has no profile branch. Fixed in this round: proposal.md line 3 and the e2e Impact line, D7, the record of answer 72.5 under "Owner answers", task 4.1, task 4.6 (tests and Verify no longer name `SPRING_PROFILES_ACTIVE=docker,e2e`) and the scenario "A connection with no module is always on" of the `module-gating` spec. The earlier rule of answer 72.5 (the module-less connection accepted only under the `e2e` profile) is superseded by answers 90 and 98.1.

## Owner decisions of 2026-10-09

Answer 100.6: every published host port is a setting `${<SERVICE>_HOST_PORT:-<today's port>}:<container port>`. The copied `ascend-agent-containerization` requirement names the agent's port as `"${EXPOSE_BIND:-127.0.0.1}:${AGENT_HOST_PORT:-9917}:9917"`, the setting `AGENT_HOST_PORT` of `add-observability` task 9.14 with the bind address of `harden-cloud-deployment`. This change publishes no new host port.

## Open Questions

These do not change the specs or the tasks, and the design follows each recommendation.

1. Should the personality and user facts of `add-agent-soul` become a module of their own? Answered by owner answer 52: no, they are core.
2. Is the `company-docs` preset (`ocr` alone) worth keeping as the one company preset? Answered by owner answer 53 of 2026-10-03: yes, it is kept, the core plus `ocr`, for the reasons in D13.
