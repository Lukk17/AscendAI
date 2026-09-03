# ascend-agent-containerization Delta Specification

## MODIFIED Requirements

### Requirement: Container-mode parity is delivered via the `docker` Spring profile

The `ascend-agent` compose entry SHALL set `SPRING_PROFILES_ACTIVE=docker` to activate `AscendAgent/src/main/resources/application-docker.yaml`. That profile SHALL override every URL and host that defaults to `localhost` in `application.yaml` so AscendAgent works correctly from inside the container without any further env-var configuration by the operator. The profile SHALL cover at minimum:

- `app.unstructured.base-url` → the in-network `unstructured-api` service URL.
- `app.docling.base-url` → the in-network `docling-serve` service URL.
- `app.paddleocr.base-url` → the in-network `ascend-paddle-ocr` service URL.
- `app.memory.semantic.base-url` → the in-network `ascend-memory` service URL.
- `app.s3.endpoint`, `spring.datasource.url`, `spring.data.redis.host`, `spring.ai.vectorstore.qdrant.host` → `host.docker.internal` (since the S3-compatible object store, Postgres, Redis, and Qdrant are external host prerequisites).
- `spring.ai.openai.base-url`, `app.ai.providers.lmstudio.base-url`, `app.embedding.providers.lmstudio.base-url` → `http://host.docker.internal:1234` for LM Studio reachability.
- `spring.ai.mcp.client.streamable-http.connections.{audioscribe,weather,ascend-web-search}.url` → the in-network MCP service URLs.

The object store is Floci (`floci/floci:2.0.1`), reached on host port `9070`, which maps to the emulator's internal AWS edge port `4566`. It runs in a compose project owned by a different repository and SHALL NOT be defined as a service in any compose file in this repository. The agent therefore reaches it through `host.docker.internal:9070` from inside the container and `localhost:9070` from the host, and there is no in-network service name for it.

The compose `environment:` block SHALL NOT duplicate these URLs as `${KEY}` overrides. The profile is the single source of truth for in-container topology.

#### Scenario: Container resolves in-network services via the docker profile

- **WHEN** `ascend-agent` starts with `SPRING_PROFILES_ACTIVE=docker`
- **THEN** boot logs show no `ConnectException` / `UnknownHostException` when contacting `ascend-memory`, `docling-serve`, `unstructured-api`, `audio-scribe`, `weather-mcp`, or `ascend-web-search`
- **AND** an MCP tool call routed via streamable-http succeeds without the operator setting any URL env vars

#### Scenario: Container reaches host PostgreSQL and Redis via the docker profile

- **WHEN** the host runs PostgreSQL on port 5432 with database `ascend_ai` and Redis on port 6379
- **AND** the container starts with `SPRING_PROFILES_ACTIVE=docker` and no `SPRING_DATASOURCE_URL` / `SPRING_DATA_REDIS_HOST` override
- **THEN** Liquibase migrations run successfully against the host database

#### Scenario: No compose file defines the object store

- **WHEN** a reviewer greps `docker-compose.yaml` and `ascend-scrapper.docker-compose.yaml` for a service definition of the object store
- **THEN** neither file defines a `minio` service nor a `floci` service
- **AND** `AGENTS.md` lists the object store under external prerequisites on ports `9070` / `9071`

#### Scenario: `.env` is gitignored

- **WHEN** a developer creates a local `.env` and runs `git status`
- **THEN** `.env` does NOT appear in the list of tracked or untracked files (it is ignored by `.gitignore`)

### Requirement: Container reaches host-only services via `host.docker.internal`

The `ascend-agent` Compose service SHALL declare `extra_hosts: ["host.docker.internal:host-gateway"]` so the container can resolve and reach services running on the Docker host (PostgreSQL :5432, Redis :6379, Qdrant :6333, the Floci object store :9070, optionally LM Studio :1234). The `docker` Spring profile already points these dependencies at `host.docker.internal`, so no further env-var configuration is required for the default flow.

#### Scenario: Container reaches host PostgreSQL

- **WHEN** the host runs PostgreSQL on port 5432 with database `ascend_ai`
- **AND** AscendAgent starts via `docker compose up` with `SPRING_PROFILES_ACTIVE=docker`
- **THEN** boot logs show no `ConnectException` against PostgreSQL
- **AND** Liquibase migrations run successfully against the host database

#### Scenario: Container reaches the host object store

- **WHEN** the host runs Floci with its AWS edge published on port 9070
- **AND** AscendAgent starts via `docker compose up` with `SPRING_PROFILES_ACTIVE=docker`
- **THEN** the startup banner reports the S3 check as reachable
- **AND** the `knowledge-base` bucket exists after startup

#### Scenario: Container reaches host LM Studio

- **WHEN** the host runs LM Studio on port 1234
- **AND** the developer sends a prompt with `provider=lmstudio`
- **THEN** AscendAgent forwards the request to the host LM Studio successfully and returns a 200 response
