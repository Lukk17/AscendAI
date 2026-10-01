# ascend-agent-containerization Delta Specification

## MODIFIED Requirements

### Requirement: ascend-agent runs as a Compose service by default

`compose.yaml` SHALL define an `ascend-agent` service that builds from `./apps/ascend-agent/Dockerfile`, publishes host port `9917` bound to the environment-driven bind address (`"${EXPOSE_BIND:-127.0.0.1}:9917:9917"`, loopback by default), sets `extra_hosts: ["host.docker.internal:host-gateway"]`, declares `depends_on` on `ascend-memory`, `docling-serve` and `unstructured-api` with `condition: service_healthy`, and has NO `profiles:` gating so that `docker compose up` starts it together with every other service. Public reachability SHALL go through the edge gateway (see the `production-deployment` capability), never through an all-interfaces binding of port 9917. A developer SHALL be able to fall back to the host-mode workflow (`docker compose stop ascend-agent` followed by `./gradlew bootRun` on the host) without a port conflict and without changing the compose file.

#### Scenario: Default compose up starts ascend-agent

- **WHEN** a developer runs `docker compose up -d --build`
- **THEN** `ascend-agent` is built and started alongside every other compose service
- **AND** `http://localhost:9917/actuator/health` responds with HTTP 200 once the container reports `healthy`

#### Scenario: Port 9917 is not reachable from outside the host

- **WHEN** the stack runs with `EXPOSE_BIND` unset and another machine opens a TCP connection to `<host-IP>:9917`
- **THEN** the connection fails
- **AND** the same request through the gateway (`https://<ASCEND_DOMAIN>/...`) succeeds

#### Scenario: Host-mode workflow remains available

- **WHEN** the developer runs `docker compose stop ascend-agent` and then `./gradlew bootRun` in `apps/ascend-agent`
- **THEN** the host process binds port `9917` and serves prompts like the container
- **AND** there is no port conflict because the `ascend-agent` container is stopped

### Requirement: A `.env.example` documents the secrets compose consumes

The repository SHALL ship a committed `.env.example` at the monorepo root, next to `compose.yaml`. It SHALL list every `${KEY}` variable referenced by `compose.yaml` and `compose.ascend-web-hunter.yaml`, including the deployment variables of the `production-deployment` capability: `EXPOSE_BIND`, `ASCEND_DOMAIN`, `GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD`, `SEARXNG_SECRET`, `MCP_ALLOWED_HOSTS`, `HF_CACHE_ROOT`, `ASCEND_AUDIO_SCRIBE_MEDIA_ROOT`, `ASCEND_AUDIO_SCRIBE_FILE_URI_ROOT`, `COMPOSE_PROFILES`, `SECURITY_USERNAME`, `SECURITY_PASSWORD`, the object store address variables (`S3_ENDPOINT`, `S3_PUBLIC_ENDPOINT`, `OCR_RESULT_S3_ENDPOINT`, `OCR_RESULT_S3_PUBLIC_ENDPOINT`), and the Postgres, Redis, object store and Qdrant credential variables. Secret-valued variables SHALL have empty values. Non-secret deployment variables MAY show their safe default. Every variable SHALL carry a one-line comment above it naming its purpose and consuming service and, where production requires it, saying so. The real `.env` SHALL be excluded by `.gitignore`.

#### Scenario: `.env.example` is committed and complete

- **WHEN** a reviewer opens `.env.example`
- **THEN** every `${KEY}` reference in `compose.yaml` or `compose.ascend-web-hunter.yaml` appears in `.env.example` on its own line
- **AND** every secret-valued variable has an empty value
- **AND** a one-line comment above each variable names the consuming service and its purpose

#### Scenario: Production-required variables are flagged

- **WHEN** a reviewer reads the entries for `GRAFANA_ADMIN_PASSWORD`, `SEARXNG_SECRET`, `SECURITY_PASSWORD`, the public endpoint variables and the datastore credential variables
- **THEN** each carries a comment saying production deployments must set it to a non-default value

#### Scenario: `.env` is gitignored

- **WHEN** a developer creates a local `.env` and runs `git status`
- **THEN** `.env` does not appear as tracked or untracked
