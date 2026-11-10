# Add Customer Stack Installer

## Why

The product is sold as one dedicated stack per customer. `harden-cloud-deployment` delivers a manual guide in `docs/DEPLOYMENT.md`: DNS, TLS, `.env` secrets, data stores, smoke checks, all by hand. That works for the first customer and becomes slow and error-prone after that. A mistyped secret or a skipped step becomes a support incident. For the self-hosted license tier the installer is the thing the customer runs.

This change turns the manual guide into a repeatable installer for any Linux server with Docker (owner decision 65.5 of 2026-10-04, no provider guide and no deployment target chosen now): checks of the server the operator brings, a bootstrap that generates every secret and assembles `.env`, a separate data-store stack, image pulls from the published registry, first-tenant provisioning and a smoke test that fails the install on a broken stack.

## Build order and dependencies

Build order (owner build order of 2026-10-04, which supersedes the earlier orders): build group 5 (company), position 8. It lands after every web-hunter, base and personal change and after the other company changes `add-auth-and-identity`, `add-tenant-isolation`, `add-tenant-policy`, `add-tenant-administration`, `add-audit-and-gdpr-compliance`, `add-usage-metering-and-quotas` and `add-document-connectors`. Only `update-docs-and-architecture` comes after it. The order of 2026-10-01 (groups A, B and D, `harden-cloud-deployment`, group C) is superseded by the owner build order of 2026-10-04. Its rehearsal server (task 8.3) is not a dependency of `harden-cloud-deployment`: that change (build group 3, position 4) runs its own drill on any throwaway server and never waits for this change.

This change depends on:

- `harden-cloud-deployment`: the gateway, the loopback port model, the `.env.example` variable set, the production credential guard, the private object store rule and the backup steps.
- `add-keycloak-login`: the `keycloak` service on its own host address (host port 8180), the realm export `keycloak/realm-ascend-ai.json` imported at Keycloak start with `--import-realm`, the service token `SERVICE_AUTH_TOKEN`, and the Keycloak site in `gateway/Caddyfile` with its own host name (added by `harden-cloud-deployment`, which lands directly after `add-keycloak-login` and creates the gateway with that site, owner answer 72.1 of 2026-10-06). `add-auth-and-identity` adds the company content of that realm export (the `tenant` mapper, groups, the brokering template).
- `add-tenant-administration`: `POST /api/v1/admin/tenants` and the user endpoints, called as `PLATFORM_ADMIN`.
- `add-connector-framework` and `add-document-connectors`: their variables in `.env.example`. The framework's `CONNECTOR_CREDENTIALS_KEY` is a stack key and is generated. Connector credentials are customer inputs and are never generated.
- `add-github-actions-pipeline` (already built): `.github/workflows/release.yaml` publishes `lukk17/ascend-ai-<service>` and `ghcr.io/lukk17/ascend-ai-<service>` with tags `v<version>` and `latest`.

It also depends on these earlier changes (the order of 2026-10-02, with number 2 inserted by owner answer 56 and number 3 by owner answer 60.6 of 2026-10-03, is superseded by the owner build order of 2026-10-04, under which all of them land before this change):

- `add-deployment-modules`: the module catalog `apps/ascend-agent/src/main/resources/modules/catalog.json` with its `requires`, companions and agent secrets per module, the presets `personal`, `company-docs` and `core`, `COMPOSE_PROFILES` as the one switch, `GET /api/v1/modules`, the always-on core (chat, document search, memory, the sandbox, monitoring and the prerequisites, owner answer 52 of 2026-10-03), the three compose `:?` guards every deployment must satisfy (`SEARXNG_SECRET` by its owner answer 41.2, `GRAFANA_ADMIN_PASSWORD` and `SANDBOX_RUNNER_TOKEN`), and Docker Compose 2.20 or later for `required: false`. Its D18 is the design of the module question this change adds.
- `add-agent-sandbox`: the sandbox is core, so every install sets up gVisor (`runsc`) and `DOCKER_SOCKET_GID` on the host and always generates `SANDBOX_RUNNER_TOKEN`.
- `add-observability`: monitoring is core, so every install starts it and always generates `GRAFANA_ADMIN_PASSWORD`.
- Every earlier change that adds a module, its variables or its secrets (`add-connector-framework`, `add-download-ingestion`, `add-shared-scheduler`, `add-agent-skills`, `add-agent-subagents`, `add-obsidian-vault`, `add-openclaw-plugin-host`, `add-file-download`, `add-coding-agent-delegation`, `add-scheduled-tasks`, `add-self-improvement`, `add-self-built-integrations`): the module question reads their catalog entries, and the bootstrap classifies every variable they add to `.env.example`.
- `add-mcp-tool-servers`: secrets of outside MCP servers are customer inputs and are never generated, the same rule as connector credentials.
- `add-obsidian-vault`: the image `ascend-ai-obsidian-sync:local` is built locally only. The installer never builds, pulls or ships it, and a customer who chooses `obsidian` builds it on their own machine with their own Obsidian account.
- `add-coding-agent-delegation`: the installer sets `app.coding.providers.opencode-go.allow-deployment-key` to false, because an OpenCode Go subscription is personal use and only the owner's personal deployment may use the deployment key.

## What Changes

- No provider (owner decision 65.5 of 2026-10-04): the installer targets any Linux server with Docker, and the deployment target is not chosen now. No Terraform, no provider guide. The operator brings the server, its DNS records and its firewall, and the installer checks them and stops naming the first failed check.
- Module question first in every install, before any secret is asked: a preset (`personal`, `company-docs`, `core`) or `custom` with a yes or no per switchable module from the catalog of `add-deployment-modules`, missing `requires` modules added with a printed reason, and the result written to `COMPOSE_PROFILES`. The core (chat, document search, memory, the sandbox and monitoring) is always installed and is never part of the question. No preset turns on the virus scanner `clamav` (owner answer 51.2).
- Server checks: Linux, Docker, Compose 2.20 or later, `sudo`, both DNS names resolving to the server, and ports 80 and 443 free.
- Data-store stack: Postgres, Redis, Qdrant and an S3-compatible object store are not in `compose.yaml` (they are external prerequisites). The installer provides them as a separate compose project `ascend-datastores` in `deploy/datastores/compose.yaml`, with no published port except loopback, or points at an S3-compatible store the operator already runs. The data store containers `ascend-postgres`, `ascend-redis`, `ascend-qdrant` and `ascend-object-storage` sit on the Docker network `ascend-data`, and a `compose.override.yaml` that the installer writes on the server joins the application services to it, while local development keeps `host.docker.internal` (owner answer 82.6 of 2026-10-08).
- Image distribution: `compose.yaml` image names become environment-driven so the server pulls released images instead of building. The installer pins each app to a released version.
- Bootstrap (`deploy/bootstrap.sh`, `deploy/bootstrap.ps1`): generates every secret of the core and of the chosen modules, takes the LLM provider keys and other customer inputs of the chosen modules as inputs, writes `.env`, refuses development defaults. A variable of a switchable module that is not chosen is neither generated nor asked. The secrets of the core (monitoring, document search, memory, the sandbox) are always generated, and so are `SEARXNG_SECRET`, `GRAFANA_ADMIN_PASSWORD` and `SANDBOX_RUNNER_TOKEN`, because their compose guards need them in every deployment.
- Sandbox host: every install sets up gVisor (`runsc`) and `DOCKER_SOCKET_GID`, because the sandbox runner runs in every deployment.
- Audio backend: only when `audio` is chosen. On a server with an NVIDIA GPU the `hf-cache` named volume is filled before the stack starts, so the first transcription does not download models. On a server without one the OpenAI backend is the default (owner decision 65.5): no GPU reservation (`AUDIO_GPU_COUNT=0`), the local tool not offered (`AUDIO_TOOLS_EXCLUDE`), and `OPENAI_API_KEY` required.
- First tenant and admin through the product's own admin API.
- Smoke test as a hard gate, including a check that `GET /api/v1/modules` lists `core-chat` and exactly the chosen modules.
- Company parts: `add-deployment-modules` keeps tenant policy, metering, audit and every other company part out of the always-on core, and each company change adds its own parts to the deployment when it lands (all of them land before this change). The installer installs them as they are, classifies their variables like every other one, and generates their stack secrets (`CONNECTOR_CREDENTIALS_KEY`, which also encrypts the BYOK provider keys of `add-usage-metering-and-quotas` since owner answer 89.9, the audit pseudonym pepper of `add-audit-and-gdpr-compliance`, the Keycloak admin client secret of `add-tenant-administration`).
- One entry point: the application stack is always the main `compose.yaml` with no `-f` flag.

## Capabilities

### New Capabilities

- `stack-provisioning`: the any-Linux-server target and its checks, the module question, the data-store stack, image distribution from the registry, the module-aware secret-generating bootstrap with customer-supplied provider keys, the audio backend chosen by the GPU when `audio` is chosen, first-tenant provisioning, the smoke test and the single compose entry point.

### Modified Capabilities

None as spec deltas. `production-deployment` and the auth and tenant-administration capabilities live in sibling changes that are not archived yet. This change consumes them.

## Impact

- New files: `deploy/README.md`, `deploy/datastores/compose.yaml`, `deploy/datastores/.env.example`, `deploy/bootstrap.sh`, `deploy/bootstrap.ps1`, `deploy/smoke-test.sh`, `deploy/smoke-test.ps1`, `deploy/tests/` (bats and Pester tests). The module question reads the catalog with `ConvertFrom-Json` in PowerShell and `jq` in Bash.
- `compose.yaml` and `compose.ascend-web-hunter.yaml`: the six app `image:` lines become `${ASCEND_IMAGE_REGISTRY:-}ascend-ai-<service>:${<SERVICE>_IMAGE_TAG:-latest}`. Local builds keep today's names.
- `docs/CONFIGURATION.md` and `apps/ascend-agent/docs/CONFIGURATION.md`: rows for the image variables, `AUDIO_GPU_COUNT`, `AUDIO_TOOLS_EXCLUDE` and the data-store host ports, with no `.env.example` line for any of them, because each has a default (owner answer 98). `deploy/README.md` lists the options of both scripts, among them the three waits, each with its default.
- `compose.yaml`: the GPU reservation count of ascend-audio-scribe reads `${AUDIO_GPU_COUNT:-1}`. The agent's `ascend-audio-scribe` entry of `add-mcp-tool-servers` reads its exclude list from `${AUDIO_TOOLS_EXCLUDE:health}`, and the `ascend-agent` service passes `- AUDIO_TOOLS_EXCLUDE=${AUDIO_TOOLS_EXCLUDE:-health}`.
- `docs/DEPLOYMENT.md`: an automated install section.
- No application code changes.

## Relevant Skills

- `/deployment-patterns`
- `/docker-patterns`
- `/bash`
- `/powershell`
- `/security-review`
- `/keycloak-administration`
- `/postgres-patterns`
- `/markdown-writer`
- `/e2e-runbooks`
