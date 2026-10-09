# ascend-agent-containerization Delta Specification

## MODIFIED Requirements

### Requirement: ascend-agent runs as a Compose service by default

`compose.yaml` SHALL define an `ascend-agent` service that builds from `./apps/ascend-agent/Dockerfile`, publishes host port `9917` bound to the environment-driven bind address (`"${EXPOSE_BIND:-127.0.0.1}:${AGENT_HOST_PORT:-9917}:9917"`, loopback by default, the host port the setting `AGENT_HOST_PORT`), sets `extra_hosts: ["host.docker.internal:host-gateway"]`, declares `depends_on` in the long form on `ascend-memory`, `docling-serve`, `unstructured-api` and `keycloak` (added by `add-keycloak-login`, which lands earlier) with `condition: service_healthy`, and has NO `profiles:` gating, so that `docker compose up` starts it together with the rest of the stack. Public reachability SHALL go through the edge gateway (see the `production-deployment` capability), never through an all-interfaces binding of port 9917. A developer SHALL be able to fall back to the host-mode workflow (`docker compose stop ascend-agent` followed by `./gradlew bootRun` on the host) without a port conflict and without changing the compose file.

#### Scenario: Default compose up starts ascend-agent

- **WHEN** a developer runs `docker compose up -d --build`
- **THEN** `ascend-agent` is built and started alongside the other services
- **AND** the container's healthcheck on `http://localhost:9918/actuator/health`, the internal management port that `compose.yaml` does not publish, passes and the container reports `healthy`

#### Scenario: The agent waits for its dependencies

- **WHEN** a developer runs `docker compose up -d` from cold
- **THEN** `ascend-memory`, `docling-serve`, `unstructured-api` and `keycloak` start
- **AND** `ascend-agent` starts after they report healthy

#### Scenario: Port 9917 is not reachable from outside the host

- **WHEN** the stack runs with `EXPOSE_BIND` unset and another machine opens a TCP connection to `<host-IP>:9917`
- **THEN** the connection fails
- **AND** the same request through the gateway (`https://<ASCEND_DOMAIN>/...`) succeeds

#### Scenario: Host-mode workflow remains available

- **WHEN** the developer runs `docker compose stop ascend-agent` and then `./gradlew bootRun` in `apps/ascend-agent`
- **THEN** the host process binds port `9917` and serves prompts like the container
- **AND** there is no port conflict because the `ascend-agent` container is stopped

### Requirement: A `.env.example` documents the secrets compose consumes

The repository SHALL ship a committed `.env.example` at the monorepo root, next to `compose.yaml`. It SHALL list every secret that `compose.yaml` and `compose.ascend-web-hunter.yaml` reference and every other variable they reference that has no default, among them `GRAFANA_ADMIN_PASSWORD`, `SEARXNG_SECRET`, the service token `SERVICE_AUTH_TOKEN`, `KEYCLOAK_DIRECTORY_CLIENT_SECRET` and `E2E_USER_PASSWORD` of `add-keycloak-login`, and the Postgres, Redis, object store, Qdrant and ascend-ocr result store credential variables. A variable that has a default (for example `EXPOSE_BIND`, `ASCEND_DOMAIN`, `GRAFANA_ADMIN_USER`, `HF_CACHE_ROOT`, `ASCEND_AUDIO_SCRIBE_MEDIA_ROOT`, `ASCEND_AUDIO_SCRIBE_FILE_URI_ROOT`, the issuer variable `KEYCLOAK_ISSUER_URI` and the object store address variables `S3_ENDPOINT`, `S3_PUBLIC_ENDPOINT`, `OCR_RESULT_S3_ENDPOINT` and `OCR_RESULT_S3_PUBLIC_ENDPOINT`) SHALL get no new line in `.env.example` and SHALL have its row in the configuration reference instead (`docs/CONFIGURATION.md` or the service's own reference, owner rule 98 of 2026-10-08), except a new variable of the scrapper stack, which also follows that stack's sync rule. Lines that `.env.example` already holds stay, among them `ALLOWED_PRIVATE_HOSTS` (renamed from `MCP_ALLOWED_HOSTS` by `add-ascend-python-common`, owner answer 68.2 of 2026-10-04). Secret-valued variables SHALL have empty values. Non-secret deployment variables MAY show their safe default. Every variable SHALL carry a one-line comment above it naming its purpose and consuming service and, where production requires it, saying so. The real `.env` SHALL be excluded by `.gitignore`. The old name `MCP_ALLOWED_HOSTS` SHALL NOT appear in `.env.example` or in either compose file (owner answer 72.3 of 2026-10-06). No compose file and no line of `.env.example` SHALL name the removed login variables `SECURITY_ENABLED`, `SECURITY_USERNAME` and `SECURITY_PASSWORD`.

#### Scenario: `.env.example` is committed and complete

- **WHEN** a reviewer opens `.env.example`
- **THEN** every `${KEY}` reference in `compose.yaml` or `compose.ascend-web-hunter.yaml` appears in `.env.example` on its own line or has its row in the configuration reference
- **AND** every secret appears in `.env.example` with an empty value
- **AND** a one-line comment above each variable names the consuming service and its purpose

#### Scenario: Production-required variables are flagged

- **WHEN** a reviewer reads the entries for `GRAFANA_ADMIN_PASSWORD`, `SEARXNG_SECRET`, `SERVICE_AUTH_TOKEN` and the datastore credential variables in `.env.example`, and the rows of the public endpoint variables and `KEYCLOAK_ISSUER_URI` in the configuration reference
- **THEN** each says production deployments must set it to a non-default value
- **AND** the entries for `GRAFANA_ADMIN_PASSWORD` and `SEARXNG_SECRET` say that every deployment must set them, whatever `COMPOSE_PROFILES` holds

#### Scenario: `.env` is gitignored

- **WHEN** a developer creates a local `.env` and runs `git status`
- **THEN** `.env` does not appear as tracked or untracked

#### Scenario: The old allow list name is gone

- **WHEN** a reviewer searches `.env.example`, `compose.yaml` and `compose.ascend-web-hunter.yaml` for `MCP_ALLOWED_HOSTS`
- **THEN** none of them is found
- **AND** the `ascend-ocr` and `ascend-audio-scribe` services set `ALLOWED_PRIVATE_HOSTS` instead

#### Scenario: The removed login variables are gone

- **WHEN** a reviewer searches `.env.example` and `compose.yaml` for `SECURITY_ENABLED`, `SECURITY_USERNAME` and `SECURITY_PASSWORD`
- **THEN** none of them is found
