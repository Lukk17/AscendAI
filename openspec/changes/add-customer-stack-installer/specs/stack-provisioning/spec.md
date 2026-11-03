## ADDED Requirements

### Requirement: The installer targets any Linux server with Docker

The installer SHALL contain no code and no guide for a cloud provider, DNS provider or managed object store, because the deployment target is not chosen (owner decision 65.5 of 2026-10-04). It SHALL run on any Linux server with Docker Engine and Docker Compose 2.20 or later, and SHALL check before the module question that the system is Linux, Docker answers, Compose is 2.20 or later and `sudo` works. Before the stack starts it SHALL check that `ASCEND_DOMAIN` and the Keycloak host name resolve to an address of the server and that ports 80 and 443 are free. A failed check SHALL stop the install and name the check. The installer SHALL NOT change DNS or the firewall.

#### Scenario: No provider code

- **WHEN** a reviewer opens `deploy/`
- **THEN** there is no Terraform and no file that names a cloud provider

#### Scenario: A wrong DNS record stops the install

- **WHEN** the Keycloak host name resolves to an address that is not one of the server's
- **THEN** the installer stops before starting anything and names the DNS check

### Requirement: The installer asks for the modules before any secret

Before it asks for or generates any secret, the installer SHALL check that `docker compose version` reports 2.20 or later, SHALL read the module catalog of `add-deployment-modules` from the checkout, and SHALL ask for one of the presets `personal`, `company-docs` and `core`, or for `custom`, where it shows each switchable module with its title and description and asks yes or no. The core (chat, document search, memory, the sandbox, monitoring and the prerequisites) SHALL always be installed and SHALL NOT be offered as a choice. It SHALL add every missing `requires` module and print which ones it added and why, and SHALL write the chosen list to `COMPOSE_PROFILES`. It SHALL ask for a companion profile only when its module is chosen, with no as the default answer, so no install turns on the virus scanner `clamav` unless the operator asks for it.

#### Scenario: A requires module is added with a reason

- **WHEN** the catalog holds `self-improvement` requiring `subagents` and `subagents` requiring `skills`, and the operator chooses `custom` and answers yes only to `self-improvement`
- **THEN** the installer adds `subagents` and `skills`, prints why each was added, and writes all three to `COMPOSE_PROFILES`

#### Scenario: The core is never a choice

- **WHEN** the operator chooses `custom`
- **THEN** none of `rag`, `memory`, `sandbox`, `observability` or a companion is offered as a module
- **AND** the core is installed whatever the answers are

#### Scenario: The question comes first

- **WHEN** the installer starts on a fresh checkout
- **THEN** the module question is asked before any secret is asked or generated

#### Scenario: An old Compose version stops the install

- **WHEN** `docker compose version` reports a version older than 2.20
- **THEN** the installer stops before the module question and names the required version

### Requirement: Only the secrets of the chosen modules are asked or generated

Every variable in the bootstrap lists SHALL carry the module it belongs to, `core-chat` for the variables of the core. A variable of a switchable module that was not chosen SHALL be neither generated nor asked. The secrets of the core SHALL be generated in every install, among them the datastore credentials that document search and memory use, `GRAFANA_ADMIN_PASSWORD` and `SANDBOX_RUNNER_TOKEN`. `VNC_PASSWORD` SHALL belong to `web-search`. `SEARXNG_SECRET` SHALL belong to `web-search` and SHALL still be generated in every install, because its compose `:?` guard needs it in every deployment. Secrets of outside MCP servers and connector credentials SHALL be customer inputs and SHALL never be generated. When `coding` is chosen, the installer SHALL set `app.coding.providers.opencode-go.allow-deployment-key` to false.

#### Scenario: A core install generates every always-needed secret

- **WHEN** the operator chooses the `core` preset
- **THEN** `.env` holds generated values of `SEARXNG_SECRET`, `GRAFANA_ADMIN_PASSWORD` and `SANDBOX_RUNNER_TOKEN`
- **AND** the installer neither asks for nor generates `VNC_PASSWORD`

#### Scenario: Every variable names its module

- **WHEN** a variable is added to a bootstrap list without a module
- **THEN** the bootstrap test suite fails naming that variable

### Requirement: Data stores come from a separate prerequisite stack

The installer SHALL provide Postgres, Redis, Qdrant and, when chosen, the S3-compatible object store through `deploy/datastores/compose.yaml` (project `ascend-datastores`), where the object store is a container unless the operator gives the address and keys of an S3-compatible store he already runs. Every data-store port SHALL bind only `127.0.0.1`, and Redis and Qdrant SHALL require credentials. The data store containers SHALL be named `ascend-postgres`, `ascend-redis`, `ascend-qdrant` and `ascend-object-storage` and SHALL sit on the Docker network `ascend-data`, which the data-store stack creates. The application stack SHALL reach the data stores by these container names on `ascend-data` and SHALL NOT reach them through `host.docker.internal`, because on Linux that name resolves to the host's address on the default bridge network, where a port published on `127.0.0.1` only does not answer. The installer SHALL join the application services that use a data store to `ascend-data` through a `compose.override.yaml` file it writes next to `compose.yaml` on the server, which the repository ignores, so local development keeps reaching its data stores through `host.docker.internal`. The application stack SHALL keep the main `compose.yaml` free of data stores.

#### Scenario: Data stores are private and reachable by the stack

- **WHEN** the data-store stack and the application stack run on the server
- **THEN** the agent health endpoint reports Postgres, Redis and Qdrant up
- **AND** no data-store port is reachable from outside the server

#### Scenario: The override file joins the stack to the data network on the server only

- **WHEN** the installer has finished on the server
- **THEN** `docker compose config`, run with no `-f` flag, shows the network `ascend-data` on every application service that uses a data store
- **AND** a development checkout, which has no `compose.override.yaml`, shows no `ascend-data` network

### Requirement: The server runs released images

The six app `image:` lines in the compose files SHALL be `${ASCEND_IMAGE_REGISTRY:-}ascend-ai-<service>:${<SERVICE>_IMAGE_TAG:-latest}`, so local builds keep today's names. The installer SHALL set the registry to the location `release.yaml` publishes to and pin each tag to a released `v<version>`, and SHALL start the released services of the chosen modules without building them. It SHALL NOT name on the command line a service whose module was not chosen, and SHALL NOT build, pull or ship the image `ascend-ai-obsidian-sync:local`.

#### Scenario: Local names are unchanged

- **WHEN** a developer runs `docker compose config --images` with the image variables unset
- **THEN** the names equal the local build names used before this change

#### Scenario: The server pulls a pinned release

- **WHEN** the installer runs with `ASCEND_AGENT_IMAGE_TAG=v<version>`
- **THEN** the running `ascend-agent` container uses `ghcr.io/lukk17/ascend-ai-ascend-agent:v<version>`

### Requirement: Bootstrap generates secrets, takes customer inputs and refuses development defaults

The installer SHALL provide `deploy/bootstrap.sh` and `deploy/bootstrap.ps1` that sort every `.env.example` variable into generated secrets, customer inputs and fixed production values, generate each secret from the system random source, require at least one LLM provider key, read every customer input from a hidden prompt or from an inputs file in `.env` format and never from the shell environment, and write `.env` with mode 600. The bootstrap SHALL abort without writing when a required value is blank or equals a development default, and SHALL NOT overwrite an existing `.env` unless asked to rotate.

#### Scenario: Complete .env with no development default

- **WHEN** the bootstrap runs with one LLM provider key supplied
- **THEN** every required variable in `.env` is set
- **AND** no value equals `admin`, `password` or `local`

#### Scenario: Customer inputs come from a file, not the shell

- **WHEN** the bootstrap runs with `--inputs` naming a file that holds one LLM provider key, and the same variable is also set in the shell environment with another value
- **THEN** `.env` holds the value of the file and no prompt waited

#### Scenario: Missing provider key aborts

- **WHEN** the bootstrap runs with no LLM provider key
- **THEN** it aborts, names the missing input and writes no `.env`

#### Scenario: Every variable is classified

- **WHEN** a new variable is added to `.env.example` without being added to a bootstrap list
- **THEN** the bootstrap test suite fails naming that variable

### Requirement: The audio backend follows the server's GPU

When the `audio` module is chosen, the installer SHALL check for the NVIDIA container runtime. With it, the installer SHALL fill the `hf-cache` volume with the configured Whisper model before starting the stack. Without it, the OpenAI backend SHALL be the default (owner decision 65.5 of 2026-10-04): the installer SHALL write `AUDIO_GPU_COUNT=0` and `AUDIO_TOOLS_EXCLUDE=health,transcribe_local`, SHALL require `OPENAI_API_KEY` and SHALL download no Whisper model. When `audio` is not chosen, the installer SHALL skip the check and the cache.

#### Scenario: GPU server gets the local backend and the cache

- **WHEN** `audio` is chosen and the server has the NVIDIA container runtime
- **THEN** the `hf-cache` volume holds the configured Whisper model before the stack starts

#### Scenario: Server without a GPU uses OpenAI

- **WHEN** `audio` is chosen and the server has no NVIDIA container runtime
- **THEN** ascend-audio-scribe starts with no GPU reservation, the agent offers no `transcribe_local` tool, and a transcription request is served by `transcribe_openai`

#### Scenario: Missing OpenAI key on a server without a GPU stops the install

- **WHEN** `audio` is chosen, the server has no NVIDIA container runtime and no `OPENAI_API_KEY` is given
- **THEN** the bootstrap aborts naming `OPENAI_API_KEY` and writes no `.env`

#### Scenario: No audio, no check

- **WHEN** `audio` is not chosen
- **THEN** the installer checks no NVIDIA runtime and downloads no Whisper model

### Requirement: Every install sets up the sandbox host

The sandbox runner is part of the always-on core, so every install SHALL prepare its host before the stack starts, whatever the module question chose: install gVisor (`runsc`), register it with Docker, confirm that `runsc` is listed and that the default runtime is still `runc`, run one container under `runsc`, and write `DOCKER_SOCKET_GID` to `.env`. The installer SHALL NOT set `runsc` as the engine's default runtime, and SHALL stop the install naming the step that failed.

#### Scenario: A core install prepares the sandbox host

- **WHEN** the operator chooses the `core` preset on a fresh Linux server
- **THEN** `docker info` lists `runsc` as a runtime and `runc` as the default runtime
- **AND** `.env` holds `DOCKER_SOCKET_GID` and a generated `SANDBOX_RUNNER_TOKEN`

#### Scenario: A failed gVisor step stops the install

- **WHEN** `docker run --rm --runtime=runsc hello-world` fails during the install
- **THEN** the installer stops before starting the stack and names the failed step

### Requirement: First tenant provisioning leaves a usable admin

After the stack is healthy, the installer SHALL confirm the imported Keycloak realm exists and SHALL create the customer's first tenant and its first `ADMIN` user through the tenant-administration API as `PLATFORM_ADMIN`. The initial password SHALL be shown once to the operator and never written to a log file.

#### Scenario: Fresh stack has a usable admin

- **WHEN** the installer completes provisioning
- **THEN** the first tenant exists and its `ADMIN` user can get a token from Keycloak

### Requirement: The smoke test is a hard install gate

The installer SHALL run a smoke test that checks the gateway certificate, the agent's container health (its healthcheck on the internal management port `9918`) and that `/actuator/*` answers 404 through the gateway, the Keycloak discovery document on its own host name, a token for the seeded admin, one authenticated prompt request, that `GET /api/v1/modules` lists `core-chat` and exactly the chosen modules, and an external port scan. The installer SHALL exit non-zero and name the first failed check when any check fails.

#### Scenario: Broken stack fails the install

- **WHEN** the smoke test runs while ascend-agent is stopped
- **THEN** the installer exits non-zero naming the health check
- **AND** does not report the install as successful

#### Scenario: A module mismatch fails the install

- **WHEN** `GET /api/v1/modules` lists a module set that differs from `core-chat` plus the chosen modules
- **THEN** the installer exits non-zero naming the modules check

### Requirement: The installer drives the single main compose file

The installer SHALL start the application stack only with `docker compose` against the main `compose.yaml` and no `-f` flag. The only other compose project on the server SHALL be `ascend-datastores`.

#### Scenario: No second application project

- **WHEN** the install has finished
- **THEN** `docker compose ls` lists only `ascend-ai` and `ascend-datastores`
