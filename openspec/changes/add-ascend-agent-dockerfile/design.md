## Context

AscendAgent is a Spring Boot 3.5.4 / Java 21 / Gradle service that listens on port 9917 and acts as the central gateway for the AscendAI platform. It connects to four host-managed prerequisites (PostgreSQL :5432, Redis :6379, Qdrant :6333, MinIO :9070), one optional host process (LM Studio :1234), three Python MCP servers running in containers (`ascend-memory` :7020, `audio-scribe` :7017, `ascend-web-search` :7021 via the included `ascend-scrapper.docker-compose.yaml`), one Java MCP server (`weather-mcp` :9998), and two document-processing services (`docling-serve` :5001, `unstructured-api` :9080).

Every other module in the monorepo is containerized and listed in `docker-compose.yaml`. Only AscendAgent is missing. That gap forces a two-step "compose up + gradlew bootRun" workflow, blocks any future "single-command full-stack" CI job, and means there is no canonical immutable image for the gateway.

The reference Dockerfile pattern in the repo is `WeatherMCP/Dockerfile` — same stack (Java 21, Spring Boot, Gradle), same base images (`eclipse-temurin:21-jdk-alpine` build, `eclipse-temurin:21-jre-alpine` runtime). We copy that pattern and extend it with the layer-cache optimization, healthcheck, and non-root user that production-grade Spring Boot images need.

## Goals / Non-Goals

**Goals:**
- One-command full-stack startup: `docker compose --profile fullstack up --build` brings up every AscendAI service.
- Reproducible image: same input → same image; no host-specific paths, no host-specific secrets.
- Zero hardcoded configuration in `docker-compose.yaml`. Everything is `KEY=${KEY}` only.
- Preserve the existing developer workflow (`./gradlew bootRun` on the host) unchanged.
- Match the existing `WeatherMCP/Dockerfile` style so the two Java services are consistent and easy to maintain.

**Non-Goals:**
- Production deployment manifests (Kubernetes, Helm, ECS task defs). Out of scope; future ADR.
- Pushing the image to a registry. The compose file builds locally only.
- Refactoring `application.yaml` to read more env vars. Container parity is delivered via the existing `application-docker.yaml` Spring profile activated by `SPRING_PROFILES_ACTIVE=docker`. The base `application.yaml` stays unchanged.
- Containerizing PostgreSQL / Redis / Qdrant / MinIO. They remain external prerequisites per the monorepo policy in `AGENTS.md`.

## Decisions

### D1 — Multi-stage Dockerfile, JRE-only runtime, non-root user

Two stages:

1. `builder` on `eclipse-temurin:21-jdk-alpine`. Working dir `/build`.
2. runtime on `eclipse-temurin:21-jre-alpine`. Working dir `/app`. Runs as a non-root user (e.g., `app:app`, uid/gid 1001).

JRE-only runtime cuts the image roughly in half versus carrying the JDK. Alpine is consistent with `WeatherMCP/Dockerfile` and keeps the image small. The non-root user is dropped via `RUN addgroup -S app && adduser -S app -G app`, then `USER app`.

**Alternative considered**: `eclipse-temurin:21-jre-jammy` (Ubuntu-based, glibc, no musl quirks). Rejected to stay consistent with `WeatherMCP/Dockerfile`. If a native dependency later needs glibc, we revisit per-module.

### D2 — Layer-cache friendly build order

The Gradle build is the slowest stage. We separate dependency resolution from compilation so a code-only change reuses the dependency layer:

```dockerfile
# stage: builder
COPY gradlew gradlew.bat ./
COPY gradle/ gradle/
COPY build.gradle.kts settings.gradle.kts ./
RUN chmod +x gradlew && ./gradlew --no-daemon dependencies
COPY src/ src/
RUN ./gradlew --no-daemon bootJar -x test
```

`-x test` skips tests inside the image build (tests run separately in CI). `--no-daemon` avoids leaving a daemon orphaned in the layer.

**Alternative considered**: Spring Boot's layered-jar feature (`bootBuildImage` + `BP_LAYERS_INDEX`). It produces tighter layer reuse but adds Buildpacks complexity, and the simple "deps first, src second" pattern already gives 80 % of the benefit.

### D3 — Healthcheck

```dockerfile
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD wget --quiet --tries=1 --spider http://localhost:9917/actuator/health || exit 1
```

If Spring Boot Actuator is not currently enabled in `application.yaml`, we either add `spring-boot-starter-actuator` to `build.gradle.kts` (cheap, ~1 MB) and expose `/actuator/health` only, OR fall back to a known existing endpoint (e.g., `/api/v1/...`) that returns 200 quickly. Verification step in `tasks.md` checks which is true at implementation time and picks one.

`wget` is already present in the Alpine base.

### D4 — Compose service shape and `host.docker.internal` wiring

```yaml
ascend-agent:
  build:
    context: ./AscendAgent
    dockerfile: Dockerfile
  container_name: ascend-agent
  restart: unless-stopped
  ports:
    - "9917:9917"
  extra_hosts:
    - "host.docker.internal:host-gateway"
  depends_on:
    - ascend-memory
    - docling-serve
    - unstructured-api
  environment:
    # ... see D5 ...
  networks:
    default:
      aliases:
        - ascend-agent
  healthcheck:
    test: ["CMD", "wget", "--quiet", "--tries=1", "--spider", "http://localhost:9917/actuator/health"]
    interval: 30s
    timeout: 5s
    retries: 3
```

`extra_hosts: ["host.docker.internal:host-gateway"]` makes the host loopback reachable from the container on Linux too — already used by `ascend-memory` so the convention is established.

### D5 — Container parity via the `docker` Spring profile, secrets via env

Container-mode parity is delivered via the existing `application-docker.yaml` Spring profile, activated by `SPRING_PROFILES_ACTIVE=docker` (hardcoded in the compose entry — there is one correct value for in-container runtime, so it is not parameterised). The profile overrides every URL that defaults to `localhost` in `application.yaml`:

- `app.unstructured.base-url` → `http://unstructured-api:8000`
- `app.docling.base-url` → `http://docling-serve:5001`
- `app.paddleocr.base-url` → `http://ascend-paddle-ocr:7022`
- `app.memory.semantic.base-url` → `http://ascend-memory:7020`
- `app.s3.endpoint` → `http://host.docker.internal:9070`
- `spring.datasource.url` → `jdbc:postgresql://host.docker.internal:5432/ascend_ai`
- `spring.data.redis.host` → `host.docker.internal`
- `spring.ai.vectorstore.qdrant.host` → `host.docker.internal`
- `spring.ai.openai.base-url` and `app.ai.providers.lmstudio.base-url` and `app.embedding.providers.lmstudio.base-url` → `http://host.docker.internal:1234`
- `spring.ai.mcp.client.streamable-http.connections.{audioscribe,weather,ascend-web-search}.url` → the corresponding compose service URLs

Only **secrets and per-deployment knobs** flow through `environment:` in the compose entry. These match the style already established by the `ascend-memory` service (mix of hardcoded values for stable configuration and `KEY=${KEY}` for secrets):

- `SPRING_PROFILES_ACTIVE=docker` (hardcoded)
- `OPENAI_API_KEY=${OPENAI_API_KEY}`
- `ASCEND_ANTHROPIC_API_KEY=${ASCEND_ANTHROPIC_API_KEY}` (the agent already uses the `ASCEND_`-prefixed name to avoid collisions with Claude Code's own auth on the host — see `application.yaml`)
- `GEMINI_API_KEY=${GEMINI_API_KEY}`
- `MINIMAX_API_KEY=${MINIMAX_API_KEY}`

Other knobs that `application.yaml` already reads from env (`SECURITY_ENABLED`, `*_ENABLED`, `*_MODEL`, `EMBEDDING_PROVIDER`, etc.) stay at their YAML defaults and are not pre-wired into the compose entry. Operators who want to override them edit the compose file directly. This avoids a noisy environment block that mostly carries values nobody changes.

**Alternative considered**: strict "every URL/host as `${KEY}` in compose" with matching `${VAR:default}` placeholders added to `application.yaml`. Rejected because it duplicates configuration (YAML profile + env vars), adds churn to a stable file, and diverges from the `ascend-memory` precedent in the same compose file.

### D6 — Host vs container modes, both supported, container is default

AscendAgent runs in two modes depending on the developer's workflow:

| Mode | Command | When |
|---|---|---|
| containerized (default) | `docker compose up -d --build` | Default. End-to-end smoke tests, demos, CI, "I want everything to work without thinking" |
| host | `docker compose stop ascend-agent` then `cd AscendAgent && ./gradlew bootRun` | Active development with hot reload, JVM debugging, IDE attached |

The `ascend-agent` service has no `profiles:` gating, so `docker compose up` brings up the full stack including the gateway. Switching to host mode is a one-command stop + `./gradlew bootRun`. Port 9917 is the same either way, so REST clients don't need to change.

**Alternative considered**: gate `ascend-agent` behind `profiles: ["fullstack"]` so default compose preserves the legacy "compose + host gradlew" workflow. Rejected — the user explicitly chose container-by-default so that a fresh clone + `docker compose up` brings up the entire monorepo. Developers who prefer host mode pay one extra `docker compose stop ascend-agent`, which is documented in both READMEs.

### D7 — `.env` file convention and gitignore

`docker compose` reads `./.env` automatically (next to `docker-compose.yaml`). We commit `.env.example` with the full variable list and ship `.gitignore` excluding `.env`. README documents the bootstrap step:

```
cp .env.example .env
# edit .env, fill in API keys
docker compose --profile fullstack up --build
```

This is the same pattern already used by `${OPENAI_API_KEY}`, `${HF_TOKEN}`, and `${GEMINI_API_KEY}` in the existing `ascend-memory` and `audio-scribe` service definitions. We just formalize and document it.

### D8 — Build args vs runtime env for secrets

Secrets (API keys, DB passwords) are **runtime-only**. They never appear as `ARG` or `ENV` in the Dockerfile and never get baked into a layer. The compose file passes them through `environment:` so they live only in the container's process env at runtime. This means a built image is safe to push to a registry; it carries no credentials.

Build args are reserved for non-secret build-time toggles (e.g., a future `JVM_OPTS` injected at boot via `ENTRYPOINT`). None are needed today.

### D9 — Optional dev hot-mount

Documented as opt-in in `.env.example` and the README, not enabled by default:

```yaml
# Uncomment for fast iteration: rebuild the bootJar on the host with
#   ./gradlew bootJar
# then `docker compose restart ascend-agent` picks up the new jar without
# rebuilding the image.
# volumes:
#   - ./AscendAgent/build/libs:/app/libs:ro
```

This requires the `ENTRYPOINT` to point at `/app/libs/<jar>` instead of `/app/app.jar`, OR a wrapper that picks the newest jar. Implementation chooses the simpler path: keep `ENTRYPOINT` on `/app/app.jar` for the default flow and document the volume mount as "for advanced users who edit the compose file." This avoids carrying a wrapper script just for opt-in dev convenience.

### D10 — `depends_on` semantics

`depends_on` in Compose v2 without `condition: service_healthy` only waits for the dependency container to *start*, not to be ready. AscendAgent's startup is resilient to AscendMemory / Docling / Unstructured being briefly unavailable (the existing `RestClient`s retry / fail per-request, not at boot). So plain `depends_on` is sufficient. We do *not* add `condition: service_healthy` because Docling and Unstructured do not currently expose healthchecks in `docker-compose.yaml`, and adding them is out of scope.

### D11 — `.dockerignore` content

To keep the build context small and avoid leaking host-only artifacts:

```
.gradle/
build/
.idea/
.vscode/
bin/
*.log
*.iml
out/
.env
.env.local
**/.DS_Store
docs/
README.md
AGENTS.md
```

This trims the typical `AscendAgent/` directory from ~hundreds of MB (with `build/`) to a handful of MB, makes builds faster, and ensures a stray `.env` in `AscendAgent/` never enters the image.

## Risks / Trade-offs

- **`host.docker.internal` is not free on Linux pre-20.10**. Mitigation: `extra_hosts: ["host.docker.internal:host-gateway"]` works on Docker 20.10+ which is the floor for `compose v2` anyway. Documented in README.
- **Image rebuild cost on dependency change**. Mitigation: layer-cache order in D2. A pure code change reuses the dependency layer; a `build.gradle.kts` change invalidates it (acceptable).
- **Actuator surface**. Adding `spring-boot-starter-actuator` only for healthcheck risks exposing endpoints. Mitigation: scope `management.endpoints.web.exposure.include=health` only; no others.
- **Drift between `application.yaml` defaults and `.env.example`**. Mitigation: tasks.md includes a verification step to grep `application.yaml` for every `${ENV:...}` placeholder and confirm each appears in `.env.example`.

## Migration Plan

This is purely additive. Existing developers who run `./gradlew bootRun` see no change. Developers who want the full container stack run the new `--profile fullstack` command after copying `.env.example` to `.env`. No rollback path needed; if the new files cause friction, removing them restores today's state exactly.

## Open Questions

- Does AscendAgent currently include `spring-boot-starter-actuator`? **Resolved at implementation time: yes.** `AscendAgent/build.gradle.kts` already pulls in `spring-boot-starter-actuator` and `application.yaml` already scopes exposure to `management.endpoints.web.exposure.include: health`. The healthcheck works as-is; no build-config change needed.
- Should the image be tagged and pushed to a registry as part of this change? Out of scope for this change; deferred to a future deployment-focused proposal.
