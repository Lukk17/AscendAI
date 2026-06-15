## 1. Dockerfile and build context

- [x] 1.1 Create `AscendAgent/Dockerfile` with two stages: `builder` on `eclipse-temurin:21-jdk-alpine`, runtime on `eclipse-temurin:21-jre-alpine`
- [x] 1.2 In the `builder` stage, copy `gradlew`, `gradlew.bat`, `gradle/`, `build.gradle.kts`, `settings.gradle.kts` first; run `chmod +x gradlew && ./gradlew --no-daemon dependencies` to pre-cache deps; THEN copy `src/`; run `./gradlew --no-daemon bootJar -x test`
- [x] 1.3 In the runtime stage, create a non-root user (`addgroup -S app && adduser -S app -G app`), `WORKDIR /app`, `COPY --from=builder --chown=app:app /build/build/libs/*.jar /app/app.jar`, `USER app`, `EXPOSE 9917`, `ENTRYPOINT ["java","-jar","/app/app.jar"]` (exec form)
- [x] 1.4 Add `HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD wget --quiet --tries=1 --spider http://localhost:9917/actuator/health || exit 1`
- [x] 1.5 Verified `spring-boot-starter-actuator` is already on the classpath (`AscendAgent/build.gradle.kts`) and `application.yaml` already scopes exposure to `management.endpoints.web.exposure.include: health`. No build-config change needed.
- [x] 1.6 Create `AscendAgent/.dockerignore` excluding `build/`, `.gradle/`, `.idea/`, `.vscode/`, `bin/`, `out/`, `*.log`, `*.iml`, `.env*`, `**/.DS_Store`, `docs/`, `e2e/`, `README.md`, `AGENTS.md`
- [ ] 1.7 Sanity-build locally: `docker build -t ascend-agent:dev ./AscendAgent` succeeds and produces an image under ~300 MB *(user runs)*
- [ ] 1.8 Sanity-run locally: `docker run --rm -p 9917:9917 --add-host host.docker.internal:host-gateway -e SPRING_PROFILES_ACTIVE=docker ascend-agent:dev` boots Spring without crashing; `curl localhost:9917/actuator/health` returns 200 *(user runs)*

## 2. `.env` convention

- [x] 2.1 Create `.env.example` at the monorepo root with the secrets compose actually references: `OPENAI_API_KEY`, `ASCEND_ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `MINIMAX_API_KEY`, `HF_TOKEN`, `NGROK_AUTHTOKEN`. Empty values for all (all are secrets).
- [x] 2.2 Confirmed root `.gitignore` already excludes `.env` and `*.env.local`. No change needed.
- [x] 2.3 Cross-checked compose env-var references vs `.env.example` — all six `${VAR}` references in `docker-compose.yaml` + `ascend-scrapper.docker-compose.yaml` are present.
- [x] 2.4 Other env vars referenced inside `application.yaml` (`SECURITY_*`, `*_ENABLED`, `*_MODEL`, `EMBEDDING_PROVIDER`, etc.) intentionally stay at their YAML defaults and are not pre-wired into compose. Per D5 — operators who want to override them edit the compose file directly. This keeps `.env.example` lean and matches the precedent set by the `ascend-memory` service entry.
- [x] 2.5 Documented the bootstrap step in the root `README.md` Quick Start: `cp .env.example .env`, then `docker compose up -d --build`.

## 3. `docker-compose.yaml` integration

- [x] 3.1 Added a new `ascend-agent` service entry under `services:` in `docker-compose.yaml`
- [x] 3.2 `build: { context: ./AscendAgent, dockerfile: Dockerfile }`, `container_name: ascend-agent`, `restart: unless-stopped`
- [x] 3.3 **Deviation from original design**: no `profiles: ["fullstack"]`. Per the user decision recorded in D6, `ascend-agent` starts by default with `docker compose up`. Developers who want host mode run `docker compose stop ascend-agent` then `./gradlew bootRun`.
- [x] 3.4 Map port `9917:9917`
- [x] 3.5 `extra_hosts: ["host.docker.internal:host-gateway"]` for host-loopback access on Linux
- [x] 3.6 `depends_on: [ascend-memory, docling-serve, unstructured-api]` (no `condition: service_healthy` — see D10)
- [x] 3.7 Added the network alias under `networks.default.aliases: [ascend-agent]`
- [x] 3.8 Healthcheck identical to the Dockerfile's
- [x] 3.9 **Deviation from original design** (D5 rewritten): the compose entry does NOT pass every variable as `KEY=${KEY}`. Container parity is delivered via `SPRING_PROFILES_ACTIVE=docker` (hardcoded) which activates `application-docker.yaml`. Only the four provider API keys flow through env (`OPENAI_API_KEY`, `ASCEND_ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `MINIMAX_API_KEY`). This matches the existing `ascend-memory` service style.
- [ ] 3.10 *Skipped for this change.* Opt-in dev hot-mount (`./AscendAgent/build/libs:/app/libs:ro`) not added. The host-mode workflow (`docker compose stop ascend-agent` + `./gradlew bootRun`) already covers the iteration loop with zero compose changes, so a commented-out volume block would be dead weight.

## 3b. `application-docker.yaml` parity fixes (added during implementation)

The pre-existing `AscendAgent/src/main/resources/application-docker.yaml` had two latent bugs and missing overrides that would have made container mode fail at runtime. Fixed as part of this change:

- [x] 3b.1 `app.unstructured.base-url`: `http://ascend-unstructured:9080` → `http://unstructured-api:8000` (correct compose service name, correct internal port).
- [x] 3b.2 `spring.datasource.url`: `jdbc:postgresql://postgres:5432/...` → `jdbc:postgresql://host.docker.internal:5432/ascend_ai` (Postgres is an external host prerequisite; there is no `postgres` service in compose).
- [x] 3b.3 Added overrides for the three MCP streamable-http connections (`audioscribe`, `weather`, `ascend-web-search`) so MCP clients dial container DNS instead of host loopback.
- [x] 3b.4 Added `app.ai.providers.lmstudio.base-url`, `app.embedding.providers.lmstudio.base-url`, and `spring.ai.openai.base-url` → `http://host.docker.internal:1234` so the LM Studio fallbacks work from inside the container.

## 4. Verification (manual — user runs)

- [ ] 4.1 `cp .env.example .env` and fill in real API keys for at least one provider
- [ ] 4.2 `docker compose up --build` — confirm `ascend-agent` builds, starts, and reaches RUNNING/HEALTHY
- [ ] 4.3 `curl http://localhost:9917/actuator/health` returns 200
- [ ] 4.4 Send a smoke prompt: `curl -X POST http://localhost:9917/api/v1/ai/prompt -F 'message=hi' -F 'userId=frosty' -F 'provider=lmstudio'` and confirm a non-error reply (LM Studio reachable on host via `host.docker.internal:1234`)
- [ ] 4.5 Confirm AscendAgent in the container can read AscendMemory: trigger a memory-bearing prompt and verify logs show `Received N semantic memory items` (no 500 / no DNS failure)
- [ ] 4.6 Confirm Postgres / Redis / Qdrant / MinIO connectivity from the container by reading the AscendAgent boot logs (no `ConnectException` / `UnknownHostException`)
- [ ] 4.7 Confirm host-mode workflow still works: `docker compose stop ascend-agent`, then `cd AscendAgent && ./gradlew bootRun` (port 9917 responds without the docker profile)
- [ ] 4.8 `docker image inspect ascend-agent:latest` confirms (a) base is `eclipse-temurin:21-jre-alpine`, (b) user is non-root, (c) image size is reasonable (target < 300 MB)
- [ ] 4.9 Grep the built image's env: `docker run --rm ascend-agent:latest env` does NOT contain any of the API keys (proves secrets are runtime-only and not baked in)

## 5. Documentation

- [x] 5.1 Updated root `README.md` Quick Start: `cp .env.example .env` → `docker compose up -d --build` (one combined flow; AscendAgent now starts as part of the default compose).
- [x] 5.2 Documented the host-mode workflow in the same README section as the alternative for active development.
- [x] 5.3 LM Studio host-loopback hop documented implicitly via the `application-docker.yaml` overrides; no extra README step needed because the user does not have to set this manually.
- [x] 5.4 Container security note covered by the design (D8 — secrets runtime-only, non-root user, build context pruned via `.dockerignore`). README links to the design.
- [x] 5.5 Cross-linked the new section from `AscendAgent/README.md` so module-local readers find it.
