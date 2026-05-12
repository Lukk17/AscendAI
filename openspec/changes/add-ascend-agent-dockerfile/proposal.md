## Why

AscendAgent is the only AscendAI service that does not ship a Dockerfile and is not wired into the root `docker-compose.yaml`. Every other module — AscendMemory, AscendWebSearch, AudioScribe, PaddleOCR, WeatherMCP — already builds a container and is started by `docker compose up --build`. Today a developer who clones the monorepo and runs `docker compose up --build` gets 9 of 10 services; the gateway (port 9917) is missing and must be started separately on the host with `./gradlew bootRun`. That makes "spin up the full stack" a two-step operation, complicates onboarding, and means there is no canonical container image of the gateway for CI, local end-to-end tests, or eventual deployment.

This change adds an `AscendAgent/Dockerfile` (multi-stage Java 21 / Gradle / Spring Boot, matching the `WeatherMCP/Dockerfile` pattern already used in the repo) and wires a new `ascend-agent` service into `docker-compose.yaml`, so a single `docker compose up --build` brings up the whole monorepo. AscendAgent still connects to PostgreSQL / Redis / Qdrant / MinIO running on the host (via `host.docker.internal`) — those remain external prerequisites and are not in scope.

A central design constraint is **no hardcoded configuration in `docker-compose.yaml`**. Every environment variable the gateway needs (API keys, embedding-provider toggles, base URLs, host overrides, feature flags) is passed by name only — `KEY=${KEY}` — and resolved from the developer's shell environment or a `.env` file sitting next to `docker-compose.yaml`. A `.env.example` is added with the full variable list and empty values; `.env` is gitignored. This keeps secrets out of the repo and out of the image, makes the same compose file work for every developer with their own keys, and matches the pattern already established for `OPENAI_API_KEY`, `HF_TOKEN`, and `GEMINI_API_KEY` in the existing services.

## What Changes

- **Add `AscendAgent/Dockerfile`** — multi-stage build. Stage 1 (`builder`) on `eclipse-temurin:21-jdk-alpine`: copy the Gradle wrapper, `build.gradle.kts`, `settings.gradle.kts`, and `gradle/` first; run `./gradlew dependencies` to pre-cache; THEN copy `src/`; run `./gradlew bootJar -x test`. Stage 2 (runtime) on `eclipse-temurin:21-jre-alpine`: copy the bootJar from the builder, expose `9917`, run as a non-root user, `ENTRYPOINT ["java","-jar","app.jar"]` (exec form so signals propagate). Add a `HEALTHCHECK` that probes `http://localhost:9917/actuator/health` (or a known endpoint if actuator is not enabled).
- **Add `AscendAgent/.dockerignore`** — exclude `build/`, `.gradle/`, `.idea/`, `.vscode/`, `*.log`, `bin/`, host-specific files, and any local secret files so the build context stays small and never carries credentials.
- **Add `ascend-agent` service to `docker-compose.yaml`** — `build: { context: ./AscendAgent, dockerfile: Dockerfile }`, port mapping `9917:9917`, `extra_hosts: ["host.docker.internal:host-gateway"]` so the container can reach the host-only services (Postgres :5432, Redis :6379, Qdrant :6333, MinIO :9070, LM Studio :1234), `depends_on` on `ascend-memory`, `docling-serve`, and `unstructured-api`, healthcheck wired to the same `/actuator/health` URL.
- **Pass every config knob through `${...}` only** — no defaults baked into the compose file. Variables include: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `MINIMAX_API_KEY`, `EMBEDDING_PROVIDER`, `LMSTUDIO_BASE_URL`, `OPENAI_BASE_URL`, `GEMINI_BASE_URL`, `ANTHROPIC_BASE_URL`, `MINIMAX_BASE_URL`, all `app.*.enabled` toggles, and DB / Redis / Qdrant / MinIO host overrides so the container can flip those to `host.docker.internal` without rebuilding the image.
- **Add `.env.example`** at the monorepo root listing every variable AscendAgent reads, with empty values and one-line comments. `.env` is added to `.gitignore` (or confirmed already present) and explicitly never committed.
- **Add a `profiles:` toggle** so `ascend-agent` is only started when the developer wants the containerized gateway. Two operational modes are supported:
  - **host mode** (default for local dev): `docker compose up` starts everything *except* `ascend-agent`; the developer runs `./gradlew bootRun` on the host while the rest runs in containers.
  - **fully containerized mode**: `docker compose --profile fullstack up --build` starts AscendAgent in the container too.
- **Document the LM Studio reachability hop** — when the gateway runs in the container and the user wants to keep LM Studio on the host, `LMSTUDIO_BASE_URL=http://host.docker.internal:1234/v1` is the canonical override. Document this in `.env.example` and the README.
- **Document an opt-in dev volume mount** for fast iteration — mount `./AscendAgent/build/libs:/app/libs` (commented out by default) so a host-side `./gradlew bootJar` updates the container on restart without a full image rebuild. Listed as opt-in only.
- **Update `README.md`** at the monorepo root with the new "fullstack" profile invocation, the `.env` file convention, and the host-vs-container decision matrix.

## Capabilities

### New Capabilities

- `ascend-agent-containerization`: AscendAgent SHALL build into a reproducible OCI container image (multi-stage, Java 21 JRE-only runtime, non-root user) and SHALL run as a service in the monorepo `docker-compose.yaml` so that a single `docker compose --profile fullstack up --build` brings up the whole AscendAI stack. The container SHALL receive all configuration via environment variables only, sourced from the developer's shell or a `.env` file next to `docker-compose.yaml`, with no hardcoded values in the compose file and no secrets baked into the image. The container SHALL be able to reach host-only prerequisites (PostgreSQL, Redis, Qdrant, MinIO, optionally LM Studio) via `host.docker.internal`.

### Modified Capabilities

(none — this change does not alter existing service behavior; it only adds a new packaging path)

## Impact

- **New files**:
  - `AscendAgent/Dockerfile`
  - `AscendAgent/.dockerignore`
  - `.env.example` (monorepo root, next to `docker-compose.yaml`)
- **Modified files**:
  - `docker-compose.yaml` — add `ascend-agent` service under a `fullstack` profile.
  - `.gitignore` — confirm `.env` is excluded (add if missing).
  - `README.md` — add full-stack invocation, `.env` convention, host-vs-container modes.
- **APIs**: no contract change. AscendAgent's public REST API is identical whether the process runs on the host or in the container.
- **Dependencies**: no new runtime dependencies. The image relies only on `eclipse-temurin:21` base images already used by `WeatherMCP`.
- **DB migrations**: none.
- **Tests**: no automated tests added; verification is manual via the compose-up smoke check listed in `tasks.md`.
- **Backward compatibility**: the existing `./gradlew bootRun` host workflow is preserved unchanged. The new `ascend-agent` service is gated behind the `fullstack` profile so a plain `docker compose up` keeps the same behavior it has today.
- **Security**: API keys never enter the image (runtime env only); the runtime container runs as a non-root user; the build context is pruned via `.dockerignore` so no host-only files leak into the image.
