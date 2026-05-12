## 1. Dockerfile and build context

- [ ] 1.1 Create `AscendAgent/Dockerfile` with two stages: `builder` on `eclipse-temurin:21-jdk-alpine`, runtime on `eclipse-temurin:21-jre-alpine`
- [ ] 1.2 In the `builder` stage, copy `gradlew`, `gradlew.bat`, `gradle/`, `build.gradle.kts`, `settings.gradle.kts` first; run `chmod +x gradlew && ./gradlew --no-daemon dependencies` to pre-cache deps; THEN copy `src/`; run `./gradlew --no-daemon bootJar -x test`
- [ ] 1.3 In the runtime stage, create a non-root user (`addgroup -S app && adduser -S app -G app`), `WORKDIR /app`, `COPY --from=builder --chown=app:app /build/build/libs/*.jar /app/app.jar`, `USER app`, `EXPOSE 9917`, `ENTRYPOINT ["java","-jar","/app/app.jar"]` (exec form)
- [ ] 1.4 Add `HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD wget --quiet --tries=1 --spider http://localhost:9917/actuator/health || exit 1`
- [ ] 1.5 Verify whether `spring-boot-starter-actuator` is on the classpath (`grep -r "spring-boot-starter-actuator" AscendAgent/build.gradle.kts`). If absent, add it and configure `management.endpoints.web.exposure.include=health` in `application.yaml`. If actuator is undesirable, swap the healthcheck to a known existing endpoint.
- [ ] 1.6 Create `AscendAgent/.dockerignore` excluding `build/`, `.gradle/`, `.idea/`, `.vscode/`, `bin/`, `out/`, `*.log`, `*.iml`, `.env*`, `**/.DS_Store`, `docs/`, `README.md`, `AGENTS.md`
- [ ] 1.7 Sanity-build locally: `docker build -t ascend-agent:dev ./AscendAgent` succeeds and produces an image under ~300 MB
- [ ] 1.8 Sanity-run locally: `docker run --rm -p 9917:9917 --add-host host.docker.internal:host-gateway -e EMBEDDING_PROVIDER=lmstudio -e LMSTUDIO_BASE_URL=http://host.docker.internal:1234/v1 ascend-agent:dev` boots Spring without crashing; `curl localhost:9917/actuator/health` returns 200

## 2. `.env` convention

- [ ] 2.1 Create `.env.example` at the monorepo root next to `docker-compose.yaml` with one line per variable, empty values for secrets, sane public defaults for non-secret URLs
- [ ] 2.2 Confirm `.gitignore` excludes `.env` (root, monorepo). If missing, add `.env` and `.env.local`
- [ ] 2.3 Cross-check: every `${VAR:...}` placeholder used in `AscendAgent/src/main/resources/application.yaml` (and any docker profile file) appears in `.env.example`. Add any that are missing
- [ ] 2.4 Cross-check: every variable already referenced as `${VAR}` in the existing `docker-compose.yaml` (e.g., `OPENAI_API_KEY`, `GEMINI_API_KEY`, `HF_TOKEN`) is present in `.env.example`
- [ ] 2.5 Document the bootstrap step in the root `README.md`: `cp .env.example .env`, fill in keys, then run compose

## 3. `docker-compose.yaml` integration

- [ ] 3.1 Add a new `ascend-agent` service entry under `services:` in `docker-compose.yaml`
- [ ] 3.2 Set `build: { context: ./AscendAgent, dockerfile: Dockerfile }`, `container_name: ascend-agent`, `restart: unless-stopped`
- [ ] 3.3 Add `profiles: ["fullstack"]` so the default `docker compose up` keeps today's behavior and only `--profile fullstack` brings up AscendAgent
- [ ] 3.4 Map port `9917:9917`
- [ ] 3.5 Add `extra_hosts: ["host.docker.internal:host-gateway"]` for host-loopback access on Linux
- [ ] 3.6 Add `depends_on: [ascend-memory, docling-serve, unstructured-api]` (no `condition: service_healthy` — see design D10)
- [ ] 3.7 Add the network alias under `networks.default.aliases: [ascend-agent]`
- [ ] 3.8 Add a healthcheck identical to the Dockerfile's
- [ ] 3.9 Pass every required environment variable as `KEY=${KEY}` only — NO hardcoded values, NO `KEY=${KEY:-default}` defaults in the compose file. Categories: provider API keys, provider base URLs, embedding provider, Postgres/Redis/Qdrant/MinIO host overrides, AscendMemory/Docling/Unstructured/MCP service URLs, feature toggles, `SPRING_PROFILES_ACTIVE`. See design D5 for the canonical list
- [ ] 3.10 Document the opt-in dev hot-mount in a commented-out `volumes:` block (`./AscendAgent/build/libs:/app/libs:ro`) with a note that it is opt-in and requires editing the entrypoint or jar path

## 4. Verification (manual)

- [ ] 4.1 `cp .env.example .env` and fill in real API keys for at least one provider (e.g., LM Studio + OpenAI)
- [ ] 4.2 `docker compose up --build` (no profile) — confirm AscendAgent does NOT start (the existing services come up; `docker compose ps` shows no `ascend-agent`)
- [ ] 4.3 In a separate shell, `cd AscendAgent && ./gradlew bootRun` — confirm the host-mode workflow still works (port 9917 responds)
- [ ] 4.4 Stop the host process. `docker compose --profile fullstack up --build` — confirm `ascend-agent` builds, starts, and reaches RUNNING/HEALTHY
- [ ] 4.5 `curl http://localhost:9917/actuator/health` returns 200 from within the container
- [ ] 4.6 Send a smoke prompt: `curl -X POST http://localhost:9917/api/v1/ai/prompt -F 'message=hi' -F 'userId=frosty' -F 'provider=lmstudio'` and confirm a non-error reply (LM Studio reachable on host via `host.docker.internal:1234`)
- [ ] 4.7 Confirm AscendAgent in the container can read AscendMemory: trigger a memory-bearing prompt and verify logs show `Received N semantic memory items` (no 500 / no DNS failure)
- [ ] 4.8 Confirm Postgres / Redis / Qdrant / MinIO connectivity from the container by reading the AscendAgent boot logs (no `ConnectException` / `UnknownHostException`)
- [ ] 4.9 `docker image inspect ascend-agent:latest` confirms (a) base is `eclipse-temurin:21-jre-alpine`, (b) user is non-root, (c) image size is reasonable (target < 300 MB)
- [ ] 4.10 Grep the built image's env: `docker run --rm ascend-agent:latest env` does NOT contain any of the API keys or DB passwords (proves secrets are runtime-only and not baked in)

## 5. Documentation

- [ ] 5.1 Update root `README.md`: add a "Run the full stack with Docker Compose" section showing `cp .env.example .env`, then `docker compose --profile fullstack up --build`
- [ ] 5.2 In the same README section, document the host-mode default and explain when to use which mode
- [ ] 5.3 Document the LM Studio host-loopback hop (`LMSTUDIO_BASE_URL=http://host.docker.internal:1234/v1`) so users running LM Studio on the host while AscendAgent is in a container know to override
- [ ] 5.4 Add a brief "Container security" note: secrets are runtime-only, the image runs as a non-root user, build context is pruned via `.dockerignore`
- [ ] 5.5 Cross-link the new section from `AscendAgent/README.md` so module-local readers find it
