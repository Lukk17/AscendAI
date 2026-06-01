## ADDED Requirements

### Requirement: AscendAgent ships a multi-stage Dockerfile

`AscendAgent/Dockerfile` SHALL define a two-stage build. The `builder` stage SHALL use `eclipse-temurin:21-jdk-alpine` and produce a Spring Boot fat jar via `./gradlew --no-daemon bootJar -x test`. The runtime stage SHALL use `eclipse-temurin:21-jre-alpine`, copy the bootJar from the builder, run as a non-root user, expose port `9917`, and use `ENTRYPOINT ["java","-jar","/app/app.jar"]` in exec form so Linux signals propagate to the JVM.

#### Scenario: Image builds successfully

- **WHEN** a developer runs `docker build -t ascend-agent:dev ./AscendAgent` against a clean checkout
- **THEN** the build completes without errors
- **AND** the resulting image base layer is `eclipse-temurin:21-jre-alpine` (verified via `docker image inspect`)
- **AND** the image total size is under 300 MB

#### Scenario: Container runs as non-root

- **WHEN** the image is started with `docker run --rm ascend-agent:dev id`
- **THEN** the reported uid is not `0` (the process runs as the application user, not root)

#### Scenario: Dependency layer is reused on code-only changes

- **WHEN** a developer edits a Java source file under `AscendAgent/src/main/java/` and rebuilds the image
- **AND** `build.gradle.kts` and `settings.gradle.kts` are unchanged
- **THEN** the `RUN ./gradlew --no-daemon dependencies` layer is served from the Docker build cache
- **AND** only the `COPY src/` layer and the `bootJar` layer are rebuilt

### Requirement: Container exposes a healthcheck

The Dockerfile SHALL declare a `HEALTHCHECK` that probes `http://localhost:9917/actuator/health` so that Docker can mark the container `healthy` once the application is ready to serve requests. The matching `docker-compose.yaml` `ascend-agent` service SHALL declare an equivalent healthcheck with the same URL and a 30-second interval. Spring Boot Actuator is already on the AscendAgent classpath and exposure is already scoped to `management.endpoints.web.exposure.include: health` in `application.yaml`; no other actuator endpoints SHALL be exposed by this change.

#### Scenario: Container reaches healthy state

- **WHEN** the container is started with all required environment variables
- **AND** the application has finished Spring context initialization
- **THEN** within 90 seconds `docker inspect --format '{{.State.Health.Status}}' ascend-agent` returns `healthy`

#### Scenario: Container is marked unhealthy on JVM crash

- **WHEN** the JVM process exits or stops responding to HTTP
- **THEN** Docker reports the container as `unhealthy` after 3 failed probes (≤ 90 seconds)

#### Scenario: Only the health endpoint is exposed

- **WHEN** a reviewer requests `GET http://localhost:9917/actuator/info` against the running container
- **THEN** the response is HTTP 404
- **AND** `GET http://localhost:9917/actuator/health` returns HTTP 200

### Requirement: AscendAgent runs as a Compose service by default

`docker-compose.yaml` SHALL define an `ascend-agent` service that builds from `./AscendAgent/Dockerfile`, maps host port `9917` to container port `9917`, sets `extra_hosts: ["host.docker.internal:host-gateway"]`, declares `depends_on: [ascend-memory, docling-serve, unstructured-api]`, and has NO `profiles:` gating so that `docker compose up` starts it together with every other service. A developer SHALL also be able to fall back to the host-mode workflow (`docker compose stop ascend-agent` followed by `./gradlew bootRun` on the host) without a port conflict and without modifying the compose file.

#### Scenario: Default compose up starts AscendAgent

- **WHEN** a developer runs `docker compose up -d --build`
- **THEN** `ascend-agent` is built and started alongside every other compose service
- **AND** port `9917` on the host responds to `GET /actuator/health` with HTTP 200 once the container reports `healthy`

#### Scenario: Host-mode workflow remains available

- **WHEN** the developer runs `docker compose stop ascend-agent` and then `cd AscendAgent && ./gradlew bootRun` on the host
- **THEN** the host process binds port `9917` and serves prompts identically to the container
- **AND** there is no port conflict because the `ascend-agent` container has been stopped

### Requirement: Container-mode parity is delivered via the `docker` Spring profile

The `ascend-agent` compose entry SHALL set `SPRING_PROFILES_ACTIVE=docker` to activate `AscendAgent/src/main/resources/application-docker.yaml`. That profile SHALL override every URL and host that defaults to `localhost` in `application.yaml` so AscendAgent works correctly from inside the container without any further env-var configuration by the operator. The profile SHALL cover at minimum:

- `app.unstructured.base-url` → the in-network `unstructured-api` service URL.
- `app.docling.base-url` → the in-network `docling-serve` service URL.
- `app.paddleocr.base-url` → the in-network `ascend-paddle-ocr` service URL.
- `app.memory.semantic.base-url` → the in-network `ascend-memory` service URL.
- `app.s3.endpoint`, `spring.datasource.url`, `spring.data.redis.host`, `spring.ai.vectorstore.qdrant.host` → `host.docker.internal` (since MinIO / Postgres / Redis / Qdrant are external host prerequisites).
- `spring.ai.openai.base-url`, `app.ai.providers.lmstudio.base-url`, `app.embedding.providers.lmstudio.base-url` → `http://host.docker.internal:1234` for LM Studio reachability.
- `spring.ai.mcp.client.streamable-http.connections.{audioscribe,weather,ascend-web-search}.url` → the in-network MCP service URLs.

The compose `environment:` block SHALL NOT duplicate these URLs as `${KEY}` overrides — the profile is the single source of truth for in-container topology.

#### Scenario: Container resolves in-network services via the docker profile

- **WHEN** `ascend-agent` starts with `SPRING_PROFILES_ACTIVE=docker`
- **THEN** boot logs show no `ConnectException` / `UnknownHostException` when contacting `ascend-memory`, `docling-serve`, `unstructured-api`, `audio-scribe`, `weather-mcp`, or `ascend-web-search`
- **AND** an MCP tool call routed via streamable-http succeeds without the operator setting any URL env vars

#### Scenario: Container reaches host PostgreSQL and Redis via the docker profile

- **WHEN** the host runs PostgreSQL on port 5432 with database `ascend_ai` and Redis on port 6379
- **AND** the container starts with `SPRING_PROFILES_ACTIVE=docker` and no `SPRING_DATASOURCE_URL` / `SPRING_DATA_REDIS_HOST` override
- **THEN** Liquibase migrations run successfully against the host database
- **AND** Redis-backed chat history is readable / writable

### Requirement: Provider API keys flow as runtime env from `.env`, never baked into the image

Provider API keys are runtime-only. The `ascend-agent` compose entry SHALL pass `OPENAI_API_KEY`, `ASCEND_ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, and `MINIMAX_API_KEY` through `environment:` in the form `KEY=${KEY}`, sourced from a developer-local `.env` file at the repository root. No API key SHALL appear as an `ARG` or `ENV` in the Dockerfile, and no API key SHALL appear as a hardcoded value in `docker-compose.yaml`.

#### Scenario: Compose reads provider keys from `.env`

- **WHEN** the developer copies `.env.example` to `.env`, fills in `OPENAI_API_KEY`, and runs `docker compose up`
- **THEN** `docker exec ascend-agent env | grep OPENAI_API_KEY` shows the runtime value the developer set in `.env`

#### Scenario: Built image carries no secrets

- **WHEN** a reviewer runs `docker history ascend-agent:latest` and `docker run --rm ascend-agent:latest env`
- **THEN** no API key appears in any image layer or default env entry
- **AND** secrets are present only in the running container's process environment, supplied at `docker compose up` time

### Requirement: A `.env.example` documents the secrets compose consumes

The repository SHALL ship a committed `.env.example` file at the monorepo root, next to `docker-compose.yaml`. The file SHALL list every `${KEY}` variable referenced by `docker-compose.yaml` and `ascend-scrapper.docker-compose.yaml` with empty values (all are secrets), and SHALL include a one-line comment above each variable explaining its purpose and which service consumes it. The actual `.env` file SHALL be excluded by `.gitignore` so it is never committed.

#### Scenario: `.env.example` is committed and complete

- **WHEN** a reviewer opens `.env.example`
- **THEN** every `${KEY}` reference present in `docker-compose.yaml` or `ascend-scrapper.docker-compose.yaml` appears in `.env.example` on its own line
- **AND** every variable has an empty value (no leaked secret)
- **AND** a one-line comment above each variable identifies the consuming service

#### Scenario: `.env` is gitignored

- **WHEN** a developer creates a local `.env` and runs `git status`
- **THEN** `.env` does NOT appear in the list of tracked or untracked files (it is ignored by `.gitignore`)

### Requirement: Container reaches host-only services via `host.docker.internal`

The `ascend-agent` Compose service SHALL declare `extra_hosts: ["host.docker.internal:host-gateway"]` so the container can resolve and reach services running on the Docker host (PostgreSQL :5432, Redis :6379, Qdrant :6333, MinIO :9070, optionally LM Studio :1234). The `docker` Spring profile already points these dependencies at `host.docker.internal`, so no further env-var configuration is required for the default flow.

#### Scenario: Container reaches host PostgreSQL

- **WHEN** the host runs PostgreSQL on port 5432 with database `ascend_ai`
- **AND** AscendAgent starts via `docker compose up` with `SPRING_PROFILES_ACTIVE=docker`
- **THEN** boot logs show no `ConnectException` against PostgreSQL
- **AND** Liquibase migrations run successfully against the host database

#### Scenario: Container reaches host LM Studio

- **WHEN** the host runs LM Studio on port 1234
- **AND** the developer sends a prompt with `provider=lmstudio`
- **THEN** AscendAgent forwards the request to the host LM Studio successfully and returns a 200 response

### Requirement: Build context is pruned via `.dockerignore`

`AscendAgent/.dockerignore` SHALL exclude build artifacts (`build/`, `.gradle/`), IDE files (`.idea/`, `.vscode/`, `*.iml`), logs, OS metadata, documentation (`docs/`, `e2e/`, `README.md`, `AGENTS.md`), and any local secret files (`.env`, `.env.local`, `.env.*.local`) from the Docker build context, so the image is small, builds are fast, and host-only artifacts cannot leak into image layers.

#### Scenario: Build context excludes host artifacts

- **WHEN** the Docker daemon prepares the build context for `docker build ./AscendAgent`
- **THEN** the context tarball does NOT contain `AscendAgent/build/`, `AscendAgent/.gradle/`, any `.iml` file, any `.idea/` directory, or any `.env*` file
- **AND** the build context size is under 50 MB on a clean checkout
