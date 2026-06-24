## Why

AscendAgent is the only AscendAI service that does not ship a Dockerfile and is not wired into the root `docker-compose.yaml`. Every other module — AscendMemory, AscendWebSearch, AudioScribe, PaddleOCR, WeatherMCP — already builds a container and is started by `docker compose up --build`. Today a developer who clones the monorepo and runs `docker compose up --build` gets 9 of 10 services; the gateway (port 9917) is missing and must be started separately on the host with `./gradlew bootRun`. That makes "spin up the full stack" a two-step operation, complicates onboarding, and means there is no canonical container image of the gateway for CI, local end-to-end tests, or eventual deployment.

This change adds an `AscendAgent/Dockerfile` (multi-stage Java 21 / Gradle / Spring Boot, matching the `WeatherMCP/Dockerfile` pattern already used in the repo) and wires a new `ascend-agent` service into `docker-compose.yaml`, so a single `docker compose up --build` brings up the whole monorepo. AscendAgent still connects to PostgreSQL / Redis / Qdrant / MinIO running on the host (via `host.docker.internal`) — those remain external prerequisites and are not in scope.

Container parity is delivered via the existing `application-docker.yaml` Spring profile, activated by `SPRING_PROFILES_ACTIVE=docker` (hardcoded in the compose entry — there is one correct value for in-container runtime). That profile is the single source of truth for every URL the agent needs to swap between host mode and container mode. The compose `environment:` block therefore stays small: it carries only the four provider API keys (`OPENAI_API_KEY`, `ASCEND_ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `MINIMAX_API_KEY`), each sourced from a developer-local `.env` file. This matches the style already established by the existing `ascend-memory` service entry (mix of hardcoded stable values and `${KEY}` for secrets), keeps secrets out of the repo and out of the image, and avoids forcing operators to override two dozen environment variables just to run the default container.

## What Changes

- **Add `AscendAgent/Dockerfile`** — multi-stage build. Stage 1 (`builder`) on `eclipse-temurin:21-jdk-alpine`: copy the Gradle wrapper, `build.gradle.kts`, `settings.gradle.kts`, and `gradle/` first; run `./gradlew --no-daemon dependencies` to pre-cache; THEN copy `src/`; run `./gradlew --no-daemon bootJar -x test`. Stage 2 (runtime) on `eclipse-temurin:21-jre-alpine`: copy the bootJar from the builder, expose `9917`, run as a non-root user (`app:app`), `ENTRYPOINT ["java","-jar","/app/app.jar"]` (exec form so signals propagate). Add a `HEALTHCHECK` that probes `http://localhost:9917/actuator/health` — actuator is already on the classpath and exposure is already scoped to `health` only in `application.yaml`, so no build-config change is needed.
- **Add `AscendAgent/.dockerignore`** — exclude `build/`, `.gradle/`, `.idea/`, `.vscode/`, `*.log`, `bin/`, `out/`, `*.iml`, `**/.DS_Store`, `docs/`, `e2e/`, `README.md`, `AGENTS.md`, and any local secret files (`.env`, `.env.local`) so the build context stays small and never carries credentials.
- **Add `ascend-agent` service to `docker-compose.yaml`** — `build: { context: ./AscendAgent, dockerfile: Dockerfile }`, port mapping `9917:9917`, `extra_hosts: ["host.docker.internal:host-gateway"]` so the container can reach the host-only services (Postgres :5432, Redis :6379, Qdrant :6333, MinIO :9070, optionally LM Studio :1234), `depends_on` on `ascend-memory`, `docling-serve`, and `unstructured-api`, healthcheck wired to the same `/actuator/health` URL. The service starts by default — no `profiles:` gating — so `docker compose up` brings up the entire monorepo in one command.
- **Pass only secrets and the Spring profile through `environment:`** — `SPRING_PROFILES_ACTIVE=docker` (hardcoded; one correct value at runtime), and `OPENAI_API_KEY=${OPENAI_API_KEY}`, `ASCEND_ANTHROPIC_API_KEY=${ASCEND_ANTHROPIC_API_KEY}`, `GEMINI_API_KEY=${GEMINI_API_KEY}`, `MINIMAX_API_KEY=${MINIMAX_API_KEY}` for provider credentials. Everything else (URLs, hosts, ports, feature toggles) lives in `application.yaml` / `application-docker.yaml`, not duplicated into the compose entry.
- **Fix `AscendAgent/src/main/resources/application-docker.yaml`** — the file already existed but had two latent bugs that would make container mode fail at runtime, plus missing overrides:
  - `app.unstructured.base-url`: `http://ascend-unstructured:9080` → `http://unstructured-api:8000` (correct compose service name, correct internal port).
  - `spring.datasource.url`: `jdbc:postgresql://postgres:5432/...` → `jdbc:postgresql://host.docker.internal:5432/ascend_ai` (Postgres is an external host prerequisite; there is no `postgres` service in compose).
  - Add overrides for the three MCP streamable-http connections (`audioscribe`, `weather`, `ascend-web-search`) so MCP clients dial container DNS instead of host loopback.
  - Add `app.ai.providers.lmstudio.base-url`, `app.embedding.providers.lmstudio.base-url`, and `spring.ai.openai.base-url` → `http://host.docker.internal:1234` so the LM Studio fallbacks work from inside the container.
- **Add `.env.example`** at the monorepo root listing the six secrets the compose stack actually references (`OPENAI_API_KEY`, `ASCEND_ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `MINIMAX_API_KEY`, `HF_TOKEN`, `NGROK_AUTHTOKEN`), all empty. `.gitignore` already excludes `.env` and `*.env.local` — no change needed.
- **Update `README.md`** at the monorepo root: Quick Start now begins with `cp .env.example .env`, then `docker compose up -d --build` brings up the agent too. The host-mode workflow (`docker compose stop ascend-agent` + `./gradlew bootRun`) is documented as the alternative for active development with hot reload or an attached debugger.
- **Update `AscendAgent/README.md`** — cross-link the "Run the AscendAgent" section to the root Quick Start; document the `docker compose stop ascend-agent` step for the host-mode escape hatch.

## Capabilities

### New Capabilities

- `ascend-agent-containerization`: AscendAgent SHALL build into a reproducible OCI container image (multi-stage, Java 21 JRE-only runtime, non-root user) and SHALL run as a service in the monorepo `docker-compose.yaml` so that a single `docker compose up --build` brings up the whole AscendAI stack including the gateway. Container-mode parity SHALL be delivered via the `application-docker.yaml` Spring profile (activated by `SPRING_PROFILES_ACTIVE=docker`), not by duplicating every URL into the compose `environment:` block. Provider API key secrets SHALL flow through `${KEY}` env passthrough sourced from a developer-local `.env` file, and SHALL never be baked into the image. The container SHALL be able to reach host-only prerequisites (PostgreSQL, Redis, Qdrant, MinIO, optionally LM Studio) via `host.docker.internal`.

### Modified Capabilities

(none — this change does not alter existing service behavior; it only adds a new packaging path)

## Impact

- **New files**:
  - `AscendAgent/Dockerfile`
  - `AscendAgent/.dockerignore`
  - `.env.example` (monorepo root, next to `docker-compose.yaml`)
- **Modified files**:
  - `docker-compose.yaml` — add `ascend-agent` service. Starts by default; no `profiles:` gating.
  - `AscendAgent/src/main/resources/application-docker.yaml` — fix unstructured host:port, fix Postgres host, add MCP and LM Studio overrides.
  - `README.md` — add `.env` bootstrap + container-by-default invocation, document host-mode escape hatch.
  - `AscendAgent/README.md` — cross-link to the root Quick Start; document the host-mode switch.
- **APIs**: no contract change. AscendAgent's public REST API is identical whether the process runs on the host or in the container.
- **Dependencies**: no new runtime dependencies. The image relies only on `eclipse-temurin:21` base images already used by `WeatherMCP`.
- **DB migrations**: none.
- **Tests**: no automated tests added; verification is manual via the compose-up smoke check listed in `tasks.md`.
- **Backward compatibility**: the existing `./gradlew bootRun` host workflow is preserved. To switch from container mode to host mode the developer runs `docker compose stop ascend-agent` then `./gradlew bootRun` — port 9917 is the same either way, so REST clients don't change.
- **Security**: API keys never enter the image (runtime env only); the runtime container runs as a non-root user; the build context is pruned via `.dockerignore` so no host-only files leak into the image.
