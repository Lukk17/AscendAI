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

The Dockerfile SHALL declare a `HEALTHCHECK` that probes a Spring Boot health endpoint on `http://localhost:9917` so that Docker can mark the container `healthy` once the application is ready to serve requests. The matching `docker-compose.yaml` `ascend-agent` service SHALL declare an equivalent healthcheck with the same URL and a 30-second interval.

#### Scenario: Container reaches healthy state

- **WHEN** the container is started with all required environment variables
- **AND** the application has finished Spring context initialization
- **THEN** within 90 seconds `docker inspect --format '{{.State.Health.Status}}' ascend-agent` returns `healthy`

#### Scenario: Container is marked unhealthy on JVM crash

- **WHEN** the JVM process exits or stops responding to HTTP
- **THEN** Docker reports the container as `unhealthy` after 3 failed probes (≤ 90 seconds)

### Requirement: AscendAgent runs as a Compose service under the `fullstack` profile

`docker-compose.yaml` SHALL define an `ascend-agent` service that builds from `./AscendAgent/Dockerfile`, maps host port `9917` to container port `9917`, sets `extra_hosts: ["host.docker.internal:host-gateway"]`, and is gated behind `profiles: ["fullstack"]` so that the default `docker compose up` does not start it. A developer SHALL be able to bring up the entire stack — including AscendAgent — with `docker compose --profile fullstack up --build` and the host-mode workflow (`./gradlew bootRun` on the host while everything else is in containers) SHALL continue to work unchanged when the profile is omitted.

#### Scenario: Default compose up does not start AscendAgent

- **WHEN** a developer runs `docker compose up -d` without the `fullstack` profile
- **THEN** services `ascend-memory`, `docling-serve`, `unstructured-api`, `weather-mcp`, `audio-scribe`, and `ascend-paddle-ocr` start
- **AND** `docker compose ps` does NOT list a running `ascend-agent` container

#### Scenario: Fullstack profile starts AscendAgent

- **WHEN** a developer runs `docker compose --profile fullstack up --build`
- **THEN** `ascend-agent` is built and started alongside every other compose service
- **AND** port `9917` on the host responds to `GET /actuator/health` with HTTP 200

#### Scenario: Host-mode workflow still works

- **WHEN** the developer runs `docker compose up -d` (no profile) and then `cd AscendAgent && ./gradlew bootRun` on the host
- **THEN** the host process binds port `9917` and serves prompts identically to today
- **AND** there is no port conflict because the `ascend-agent` container is not running

### Requirement: All AscendAgent configuration is passed by environment variable, never hardcoded

The `ascend-agent` service entry in `docker-compose.yaml` SHALL declare every environment variable in the form `KEY=${KEY}` only. The compose file SHALL NOT contain any hardcoded provider API key, hardcoded base URL, hardcoded host name, hardcoded password, or any `KEY=${KEY:-fallback}` default value for `ascend-agent`. Variable values SHALL come from the developer's shell environment or a `.env` file located next to `docker-compose.yaml`. Required variables SHALL include at minimum: provider API keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `MINIMAX_API_KEY`), provider base URLs (`LMSTUDIO_BASE_URL`, `OPENAI_BASE_URL`, `GEMINI_BASE_URL`, `ANTHROPIC_BASE_URL`, `MINIMAX_BASE_URL`), `EMBEDDING_PROVIDER`, host overrides for the host-managed prerequisites (Postgres / Redis / Qdrant / MinIO), URLs for the in-cluster services AscendAgent talks to (AscendMemory, Docling, Unstructured, MCP servers), and any `app.*.enabled` feature toggles.

#### Scenario: Compose file contains no hardcoded secrets

- **WHEN** a reviewer greps `docker-compose.yaml` for the `ascend-agent` service block
- **THEN** every line in `environment:` matches the pattern `- KEY=${KEY}` exactly
- **AND** no line contains a literal API key, password, or `KEY=${KEY:-default}` form

#### Scenario: Compose reads variables from .env

- **WHEN** the developer copies `.env.example` to `.env`, fills in `OPENAI_API_KEY`, and runs `docker compose --profile fullstack up`
- **THEN** the `ascend-agent` container's process environment contains the value the developer set in `.env`
- **AND** `docker exec ascend-agent env | grep OPENAI_API_KEY` shows the runtime value

#### Scenario: Built image carries no secrets

- **WHEN** a reviewer runs `docker history ascend-agent:latest` and `docker run --rm ascend-agent:latest env`
- **THEN** no API key, password, or other secret value appears in any image layer or default env entry
- **AND** secrets are present only in the running container's process environment, supplied at `docker run` / `docker compose up` time

### Requirement: A `.env.example` documents every variable AscendAgent reads

The repository SHALL ship a committed `.env.example` file at the monorepo root, next to `docker-compose.yaml`, listing every environment variable the `ascend-agent` service consumes, with empty values for secrets and sane public defaults only for non-secret URLs. The actual `.env` file SHALL be listed in `.gitignore` so it is never committed.

#### Scenario: .env.example is committed and complete

- **WHEN** a reviewer opens `.env.example`
- **THEN** every variable referenced in the `ascend-agent` `environment:` block of `docker-compose.yaml` appears in `.env.example` on its own line
- **AND** secret-bearing variables (API keys, passwords) have empty values
- **AND** a one-line comment above each variable explains its purpose

#### Scenario: .env is gitignored

- **WHEN** a developer creates a local `.env` and runs `git status`
- **THEN** `.env` does NOT appear in the list of tracked or untracked files (it is ignored by `.gitignore`)

### Requirement: Container reaches host-only services via `host.docker.internal`

The `ascend-agent` Compose service SHALL declare `extra_hosts: ["host.docker.internal:host-gateway"]` so the container can resolve and reach services running on the Docker host (PostgreSQL :5432, Redis :6379, Qdrant :6333, MinIO :9070, optionally LM Studio :1234). When the developer overrides `POSTGRES_HOST`, `REDIS_HOST`, `QDRANT_HOST`, `MINIO_ENDPOINT`, or `LMSTUDIO_BASE_URL` in `.env` to use `host.docker.internal`, the container SHALL connect successfully without requiring the prerequisites to be moved into Compose.

#### Scenario: Container reaches host PostgreSQL

- **WHEN** the host runs PostgreSQL on port 5432 with database `ascend_ai`
- **AND** `.env` contains `POSTGRES_HOST=host.docker.internal`
- **AND** AscendAgent starts via `docker compose --profile fullstack up`
- **THEN** boot logs show no `ConnectException` against PostgreSQL
- **AND** Liquibase migrations run successfully against the host database

#### Scenario: Container reaches host LM Studio

- **WHEN** the host runs LM Studio on port 1234
- **AND** `.env` contains `LMSTUDIO_BASE_URL=http://host.docker.internal:1234/v1`
- **AND** the developer sends a prompt with `provider=lmstudio`
- **THEN** AscendAgent forwards the request to the host LM Studio successfully and returns a 200 response

### Requirement: Build context is pruned via `.dockerignore`

`AscendAgent/.dockerignore` SHALL exclude build artifacts (`build/`, `.gradle/`), IDE files (`.idea/`, `.vscode/`, `*.iml`), logs, OS metadata, and any local secret files (`.env`, `.env.local`) from the Docker build context, so the image is small, builds are fast, and host-only artifacts cannot leak into image layers.

#### Scenario: Build context excludes host artifacts

- **WHEN** the Docker daemon prepares the build context for `docker build ./AscendAgent`
- **THEN** the context tarball does NOT contain `AscendAgent/build/`, `AscendAgent/.gradle/`, any `.iml` file, any `.idea/` directory, or any `.env*` file
- **AND** the build context size is under 50 MB on a clean checkout
