## Purpose

Lets one AscendAI stack be deployed with only the switchable modules a deployment needs, from the owner's personal stack with every module on to a company stack with the core alone, through one catalog of stable module names and one setting that the containers and the agent both read, while the core is always on.

## ADDED Requirements

### Requirement: The core is always on

The core SHALL run in every deployment and SHALL NOT be switchable. It SHALL hold core chat (chat, conversations, streaming, login, approvals, the personality file and user facts, background runs, the shared scheduler engine, notifications, and the skill and tool search index), monitoring (Prometheus, Grafana, Loki, Tempo, the OpenTelemetry collector, Vector and the container metrics exporter), document search (knowledge search, Docling, Unstructured and the connectors), memory (ascend-memory), the sandbox (the sandbox runner and the shell and file tools), and the prerequisites (PostgreSQL, Redis, Qdrant, object storage and Keycloak, which the personal assistant logs in to as well). No compose service of the core SHALL carry `profiles:`, so `docker compose up` starts every core service whatever `COMPOSE_PROFILES` holds. Every service SHALL keep exporting its telemetry to the collector in every deployment. Tenant policy, metering, audit and every other company part SHALL NOT be part of the core this capability defines: each company change adds its own parts to the deployment when it lands.

#### Scenario: The core runs with no switchable module

- **WHEN** `COMPOSE_PROFILES` is empty and `docker compose up -d` is run
- **THEN** `ascend-agent`, `docling-serve`, `unstructured-api`, `ascend-memory`, `prometheus`, `grafana`, `loki`, `tempo`, `otel-collector` and `container-metrics-exporter` run
- **AND** after one chat turn a trace of it reaches Tempo

#### Scenario: No core service is gated

- **WHEN** the compose consistency test reads `compose.yaml` and the files it includes
- **THEN** no service of the core carries a `profiles:` entry

### Requirement: One catalog lists every switchable module

The repository SHALL hold exactly one module catalog. Each switchable module entry SHALL have a stable name of lowercase letters, digits and single dashes, a title, a one-sentence description, the modules it requires, the modules it uses when they are present, its companion compose profiles, and the names of the agent environment variables that hold its secrets. The catalog SHALL also hold the presets and the list of former module names that are now part of the core (`rag`, `memory`, `sandbox`, `observability`). The catalog SHALL contain no cycle in `requires`, no entry that requires or uses an unknown name or a core name, and no companion that belongs to two modules. A module name, once released, SHALL NOT be renamed. The entry `core-chat` SHALL be in the catalog, SHALL stand for the whole core, SHALL be always on, and SHALL have no compose profile. Once every planned change has landed, the switchable modules SHALL be exactly `ocr`, `audio`, `web-search`, `web-download`, `weather`, `obsidian`, `channels`, `openclaw-apps`, `coding`, `self-built-integrations`, `subagents`, `skills`, `self-improvement` and `scheduler`. The catalog SHALL be a JSON file at one fixed path in the repository that ships inside the agent image, so scripts such as the installer read the same file the agent reads.

#### Scenario: A script reads the catalog

- **WHEN** a PowerShell script runs `Get-Content` on the catalog path and pipes it to `ConvertFrom-Json`
- **THEN** it gets every module name, title, description, `requires` list and preset without any other tool

#### Scenario: The catalog is valid

- **WHEN** the catalog unit test loads the shipped catalog
- **THEN** every name matches the name pattern, every `requires` and `uses` entry names a switchable module of the catalog, no `requires` cycle exists, and every companion belongs to exactly one module
- **AND** no entry is named `rag`, `memory`, `sandbox` or `observability`

#### Scenario: A catalog with a cycle is refused

- **WHEN** a catalog in which `a` requires `b` and `b` requires `a` is loaded
- **THEN** loading fails with a message naming both modules

### Requirement: COMPOSE_PROFILES is the one switch and the agent reads it as ASCEND_MODULES

The switchable modules of a deployment SHALL be on exactly when their names are in `COMPOSE_PROFILES` in the root `.env`. Every compose service that belongs to a switchable module SHALL carry that module's name in its `profiles:`. The agent, and every later service that reads the module list, SHALL receive it as the environment variable `ASCEND_MODULES`, set in compose to `${COMPOSE_PROFILES:-}`. No other variable or property SHALL switch a whole module on or off. A setting MAY switch a part inside a module that is on or inside the core. Modules SHALL NOT be switched with the `docker compose --profile` flag, because that flag does not reach `ASCEND_MODULES`, and the documentation SHALL say so.

#### Scenario: One entry starts the containers and the agent code

- **WHEN** `COMPOSE_PROFILES=ocr,weather` and `docker compose up -d` is run
- **THEN** the `ascend-ocr` and `ascend-weather-mcp` containers run beside the core
- **AND** the agent container's environment holds `ASCEND_MODULES=ocr,weather`

#### Scenario: Empty list starts the core alone

- **WHEN** `COMPOSE_PROFILES` is empty and `docker compose up -d` is run
- **THEN** only the services of the core run and no container of `ocr`, `audio`, `web-search` or `weather` is created

### Requirement: The agent refuses an inconsistent module selection

The agent SHALL check `ASCEND_MODULES` against the catalog before it creates any bean, and SHALL refuse to start with one message naming each problem and its fix when the list names a part of the core, names an unknown module or companion, lists a module without every module it requires, or lists a companion profile without its parent module. Listing `core-chat` SHALL be accepted and change nothing. Names SHALL be compared after trimming spaces, and an empty entry SHALL be ignored. Under the Spring profile `production`, the agent SHALL also refuse to start when an agent secret of an active module is empty. Outside `production` it SHALL log one WARN line per missing secret instead.

#### Scenario: A part of the core is listed

- **WHEN** the agent starts with `ASCEND_MODULES=rag,ocr`
- **THEN** the start fails with a message that `rag` is part of the core and always on, and that it must be removed from `COMPOSE_PROFILES`

#### Scenario: Unknown module name

- **WHEN** the agent starts with `ASCEND_MODULES=ocrr`
- **THEN** the start fails with a message that names `ocrr` as unknown and proposes `ocr`

#### Scenario: Missing required module

- **WHEN** the catalog holds `subagents` requiring `skills` and the agent starts with `ASCEND_MODULES=subagents`
- **THEN** the start fails with a message that `subagents` requires `skills` and that `skills` must be added to `COMPOSE_PROFILES`

#### Scenario: Companion without its module

- **WHEN** the agent starts with `ASCEND_MODULES=captcha-intervention`
- **THEN** the start fails with a message that `captcha-intervention` belongs to `web-search`

#### Scenario: A refused selection never becomes healthy

- **WHEN** compose starts the agent container with `COMPOSE_PROFILES=rag`
- **THEN** within 120 seconds the container is `exited` or `restarting` with a non-zero last exit code
- **AND** the container never reports `healthy`

### Requirement: Presets are named module lists

The catalog SHALL hold the presets `personal` (every switchable module of the catalog), `core` (no switchable module) and `company-docs` (`ocr`). No preset SHALL hold a companion, so no preset turns on the virus scanner `clamav`. Every preset SHALL pass the startup check. A preset SHALL NOT be a value of `COMPOSE_PROFILES`: an operator or the installer writes the preset's module list. `.env.example` SHALL set `COMPOSE_PROFILES` to the `personal` list and show the other presets as comments, and a test SHALL fail when that line differs from the catalog.

#### Scenario: Personal preset matches the catalog

- **WHEN** a switchable module is added to the catalog
- **THEN** the preset test fails until `personal` and the `.env.example` line both name it

#### Scenario: No preset turns the download scanner on

- **WHEN** `COMPOSE_PROFILES` in `.env` equals any preset, the `personal` preset included
- **THEN** `clamav` is not in the list, `docker compose up -d` starts no `clamav` container, and every new download of `add-file-download` records `scan.status` `skipped`

#### Scenario: No preset turns on the virus scanner

- **WHEN** the preset test reads every preset
- **THEN** none of them holds `clamav` or any other companion

#### Scenario: A preset is recognized in the banner

- **WHEN** the agent starts with exactly the modules of `company-docs`
- **THEN** the startup banner names the preset `company-docs` next to the module list

### Requirement: Compose files stay consistent with the catalog

Every `profiles:` value in `compose.yaml` and the files it includes SHALL be a switchable module or a companion of the catalog, and never `core-chat` or a core name. A core service SHALL have no `profiles:`. Every `depends_on` entry that names a service under a module profile SHALL use the long form with `required: false`. Compose checks a `${VAR:?}` guard even when the profile of its service is off, so a service under a module profile SHALL use such a guard only for a variable that every deployment must set, and `SEARXNG_SECRET` SHALL be the only such variable. A guard on an always-on service is allowed: `GRAFANA_ADMIN_PASSWORD` on `grafana` and `SANDBOX_RUNNER_TOKEN` on the sandbox runner and the agent are such guards. Every deployment SHALL set `SEARXNG_SECRET`, `GRAFANA_ADMIN_PASSWORD` and `SANDBOX_RUNNER_TOKEN`, also one without `web-search`. A test SHALL check these rules by reading the compose files, without starting Docker.

#### Scenario: The core starts without any module

- **WHEN** `COMPOSE_PROFILES` is empty, the three always-needed variables are set, and `docker compose config` is run
- **THEN** the command succeeds and lists no service of a switchable module

#### Scenario: SEARXNG_SECRET is needed without web search

- **WHEN** `COMPOSE_PROFILES=ocr`, `SEARXNG_SECRET` is not set, and `docker compose config` is run
- **THEN** the command fails and names `SEARXNG_SECRET`

#### Scenario: A new guard under a module profile is caught

- **WHEN** a service under a module profile uses a `${VAR:?}` guard for a variable other than `SEARXNG_SECRET`
- **THEN** the compose consistency test fails naming the service and the variable

#### Scenario: A stray profile is caught

- **WHEN** a compose service carries `profiles: [rag]` or `profiles: [ocr-v2]`
- **THEN** the compose consistency test fails naming the service and the profile
