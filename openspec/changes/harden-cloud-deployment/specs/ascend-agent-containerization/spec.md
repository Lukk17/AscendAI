# ascend-agent-containerization Delta Specification

## MODIFIED Requirements

### Requirement: AscendAgent runs as a Compose service by default

`docker-compose.yaml` SHALL define an `ascend-agent` service that builds from `./AscendAgent/Dockerfile`, publishes host port `9917` bound to the env-driven bind address (`"${EXPOSE_BIND:-127.0.0.1}:9917:9917"`, loopback by default), sets `extra_hosts: ["host.docker.internal:host-gateway"]`, declares `depends_on` on `ascend-memory`, `docling-serve`, and `unstructured-api` with `condition: service_healthy`, and has NO `profiles:` gating so that `docker compose up` starts it together with every other service. Public reachability SHALL go through the edge gateway (see the `production-deployment` capability), never through a direct all-interfaces binding of port 9917. A developer SHALL also be able to fall back to the host-mode workflow (`docker compose stop ascend-agent` followed by `./gradlew bootRun` on the host) without a port conflict and without modifying the compose file.

#### Scenario: Default compose up starts AscendAgent

- **WHEN** a developer runs `docker compose up -d --build`
- **THEN** `ascend-agent` is built and started alongside every other compose service
- **AND** `http://localhost:9917/actuator/health` responds with HTTP 200 once the container reports `healthy`

#### Scenario: Port 9917 is not reachable from outside the host

- **WHEN** the stack runs with `EXPOSE_BIND` unset and another machine attempts a TCP connection to `<host-IP>:9917`
- **THEN** the connection fails
- **AND** the same request routed through the gateway (`https://<ASCEND_DOMAIN>/...`) succeeds

#### Scenario: Host-mode workflow remains available

- **WHEN** the developer runs `docker compose stop ascend-agent` and then `cd AscendAgent && ./gradlew bootRun` on the host
- **THEN** the host process binds port `9917` and serves prompts identically to the container
- **AND** there is no port conflict because the `ascend-agent` container has been stopped

### Requirement: A `.env.example` documents the secrets compose consumes

The repository SHALL ship a committed `.env.example` file at the monorepo root, next to `docker-compose.yaml`. The file SHALL list every `${KEY}` variable referenced by `docker-compose.yaml` and `ascend-scrapper.docker-compose.yaml` — including the deployment variables introduced by the `production-deployment` capability (`EXPOSE_BIND`, `ASCEND_DOMAIN`, `GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD`, `SEARXNG_SECRET`, `SECURITY_ENABLED`, `MCP_ALLOWED_HOSTS`, `HF_CACHE_ROOT`, `AUDIO_SCRIBE_MEDIA_ROOT`, `AUDIO_SCRIBE_FILE_URI_ROOT`, `COMPOSE_PROFILES`, and the Postgres / Redis / object-store / Qdrant credential variables). Secret-valued variables SHALL have empty values (no leaked secret); non-secret deployment variables MAY show their safe default. Every variable SHALL carry a one-line comment above it explaining its purpose, which service consumes it, and — for variables the production posture requires — that production deployments must set it. The actual `.env` file SHALL be excluded by `.gitignore` so it is never committed.

#### Scenario: `.env.example` is committed and complete

- **WHEN** a reviewer opens `.env.example`
- **THEN** every `${KEY}` reference present in `docker-compose.yaml` or `ascend-scrapper.docker-compose.yaml` appears in `.env.example` on its own line
- **AND** every secret-valued variable has an empty value (no leaked secret)
- **AND** a one-line comment above each variable identifies the consuming service and its purpose

#### Scenario: Production-required variables are flagged

- **WHEN** a reviewer scans `.env.example` for `GRAFANA_ADMIN_PASSWORD`, `SEARXNG_SECRET`, `SECURITY_ENABLED`, and the datastore credential variables
- **THEN** each carries a comment stating it is required (or must be non-default) for production deployments

#### Scenario: `.env` is gitignored

- **WHEN** a developer creates a local `.env` and runs `git status`
- **THEN** `.env` does NOT appear in the list of tracked or untracked files (it is ignored by `.gitignore`)
