# Tasks - Harden Cloud Deployment

Build order: after group A, group B and group D, before group C. Load the skills in the proposal's Relevant Skills section first. Every compose command runs against the main `compose.yaml` with no `-f` flag.

## 0. Already true in the code (checked 2026-10-01, no work)

- [x] 0.1 `SEARXNG_SECRET` is required by compose (`compose.ascend-web-hunter.yaml:28`) and `infra/searxng/settings.yml` has no `secret_key`
- [x] 0.2 SearXNG and FlareSolverr are bound to `127.0.0.1` (`compose.ascend-web-hunter.yaml:26`, `:63`)
- [x] 0.3 `compose.ascend-web-hunter.yaml` defines `x-logging: &default-logging` (`:6-10`) and every service in it uses it
- [x] 0.4 The ngrok image is pinned by digest (`compose.ascend-web-hunter.yaml:147`) and every other pulled image carries a version and a digest
- [x] 0.5 SearXNG and FlareSolverr have healthchecks, and ascend-web-hunter waits on both with `condition: service_healthy` (`compose.ascend-web-hunter.yaml:211-215`)

## 1. Port bindings and compose mechanics

- [ ] 1.1 In `compose.yaml`, change every `ports:` entry to `"${EXPOSE_BIND:-127.0.0.1}:<host>:<container>"`: docling-serve `5001:5001`, unstructured-api `9080:8000`, ascend-ocr `7022:7022`, ascend-agent `9917:9917`, ascend-memory `7020:7020`, ascend-weather-mcp `9998:9998`, ascend-audio-scribe `7017:7017`, prometheus `7077:9090`, grafana `7078:3000`. Acceptance: `docker compose config` shows `host_ip: 127.0.0.1` for each of them.
- [ ] 1.2 In `compose.ascend-web-hunter.yaml`, change searxng `127.0.0.1:9020:8080`, flaresolverr `127.0.0.1:8191:8191` and ascend-web-hunter `7021:7021` to the same form. Acceptance: `docker compose config` shows `host_ip: 127.0.0.1` for all three.
- [ ] 1.3 Confirm loki, vector, otel-collector, tempo, container-metrics-exporter and the bundled redis publish no port. Acceptance: `docker compose config` shows no `ports` key on those six services.
- [ ] 1.4 Add a top-level `x-logging: &default-logging` anchor to `compose.yaml` with the same values as `compose.ascend-web-hunter.yaml:6-10`, and add `logging: *default-logging` to every service in `compose.yaml`. Acceptance: `docker inspect --format '{{.HostConfig.LogConfig}}' ascend-agent loki grafana` shows `json-file` with `max-size:10m max-file:3` for each.
- [ ] 1.5 Add `profiles: ["captcha-intervention"]` to `ngrok-ascend-web-hunter`, and confirm ascend-web-hunter starts and serves `/health` when the ngrok service is absent (`PUBLIC_VNC_URL` points at a missing host). Fix the web-hunter code path with a test if it does not. Acceptance: `docker compose up -d` creates no `ngrok-ascend-web-hunter` container and `curl -f http://localhost:7021/health` returns 200.
- [ ] 1.6 Verify: `docker compose config --quiet` exits 0, `docker compose up -d` brings the stack up as one project, and from another machine `http://<host-LAN-IP>:7020/health` fails while `http://localhost:7020/health` on the host returns 200.

## 2. Edge gateway

- [ ] 2.1 Create `gateway/Caddyfile`: site address `{$ASCEND_DOMAIN:localhost}`, `reverse_proxy ascend-agent:9917`, no other upstream. Acceptance: `docker run --rm -v ./gateway/Caddyfile:/etc/caddy/Caddyfile caddy:<pinned> caddy validate --config /etc/caddy/Caddyfile` exits 0.
- [ ] 2.2 Add the `gateway` service to `compose.yaml`: Caddy 2 image pinned by version and digest, ports `"80:80"` and `"443:443"` (the one exception to task 1.1), Caddyfile mounted read-only, named volumes `caddy-data` and `caddy-config`, `ASCEND_DOMAIN=${ASCEND_DOMAIN:-localhost}`, healthcheck, `restart: unless-stopped`, `logging: *default-logging`, `depends_on` ascend-agent with `condition: service_healthy`. Acceptance: `docker compose ps gateway` shows `healthy`.
- [ ] 2.3 Do not add any Keycloak, Grafana or object store route. Keycloak gets its own host address and port in `add-auth-and-identity`, which may later add a separate Keycloak site block, never a path under the agent's site. Acceptance: `grep -nE 'keycloak|grafana|9070' gateway/Caddyfile` finds nothing.
- [ ] 2.4 Verify locally with `ASCEND_DOMAIN` unset: `curl -k https://localhost/actuator/health` returns 200 from the agent through Caddy's internal CA.
- [ ] 2.5 Configure the `POST /api/v1/ai/prompt/stream` route (added by `add-chat-streaming-and-conversations`, group D, built before this change) with `flush_interval -1` and no response timeout. Acceptance: `curl -k -N -X POST https://localhost/api/v1/ai/prompt/stream -F prompt=...` prints `delta` events one by one as they are produced and ends with the `done` event.

## 3. Secrets and credentials

- [ ] 3.1 Grafana in `compose.yaml`: set `GF_AUTH_ANONYMOUS_ENABLED=false`, remove `GF_AUTH_ANONYMOUS_ORG_ROLE=Editor`, add `GF_SECURITY_ADMIN_USER=${GRAFANA_ADMIN_USER:-admin}` and `GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD:?GRAFANA_ADMIN_PASSWORD must be set in .env}`. Acceptance: `docker compose config` without the variable fails naming `GRAFANA_ADMIN_PASSWORD`.
- [ ] 3.2 In `apps/ascend-agent/src/main/resources/application.yaml`: `app.s3.access-key` to `${S3_ACCESS_KEY:admin}`, `app.s3.secret-key` to `${S3_SECRET_KEY:password}`, `app.s3.endpoint` to `${S3_ENDPOINT:http://localhost:9070}`, `app.s3.public-endpoint` to `${S3_PUBLIC_ENDPOINT:${app.s3.endpoint}}`, `spring.datasource.username` to `${POSTGRES_USER:postgres}`, `spring.datasource.password` to `${POSTGRES_PASSWORD:local}`, add `spring.data.redis.password: ${REDIS_PASSWORD:}` and `spring.ai.vectorstore.qdrant.api-key: ${QDRANT_API_KEY:}`. In `application-docker.yaml` make `app.s3.endpoint` `${S3_ENDPOINT:http://host.docker.internal:9070}` and `app.s3.public-endpoint` `${S3_PUBLIC_ENDPOINT:http://localhost:9070}`. Acceptance: `./gradlew test` passes with no variable set.
- [ ] 3.3 Pass through to the `ascend-agent` compose environment: `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_ENDPOINT`, `S3_PUBLIC_ENDPOINT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `QDRANT_API_KEY`, `SECURITY_USERNAME` and `SECURITY_PASSWORD` (both already read at `application.yaml:73-74` with default `admin`/`admin`), each as `${VAR:-}` so the `application.yaml` default applies when unset. Acceptance: `docker compose exec ascend-agent printenv SECURITY_USERNAME` prints the `.env` value when set, and the agent still starts with none of them set.
- [ ] 3.4 Wire `QDRANT_API_KEY` into the `ascend-memory` environment (and confirm ascend-memory passes it to its Qdrant client, adding the setting and a test in `apps/ascend-memory/` if it does not), and document a password-bearing `REDIS_URL` form for ascend-web-hunter in `.env.example`. Acceptance: with both unset, ascend-memory and ascend-web-hunter reach `healthy` as today.
- [ ] 3.5 ascend-ocr result store: `OCR_RESULT_S3_ENDPOINT=${OCR_RESULT_S3_ENDPOINT:-http://host.docker.internal:9070}` and `OCR_RESULT_S3_PUBLIC_ENDPOINT=${OCR_RESULT_S3_PUBLIC_ENDPOINT:-http://localhost:9070}` in `compose.yaml:74-75`. The keys at `:77-78` are already from the environment. Acceptance: `docker compose config` shows the defaults, and an OCR job through ascend-ocr still stores its result.
- [ ] 3.6 Add `ProductionCredentialGuard` in `apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/config/` (design D3), active only under `@Profile("production")`, failing startup when any listed credential equals its development default, naming the property and never its value. Write the tests first in `apps/ascend-agent/src/test/java/com/lukk/ascend/ai/agent/config/`: one per credential for the fail path, one for the pass path, one asserting the guard's default constants equal the defaults in `application.yaml`. Acceptance: `./gradlew test --tests "com.lukk.ascend.ai.agent.config.ProductionCredentialGuard*"` passes and `./gradlew build` passes.

## 4. Personal-machine artifacts

- [ ] 4.1 Replace `compose.yaml:282-283` with `"${HF_CACHE_ROOT:-hf-cache}:/hf-cache"` and `"${ASCEND_AUDIO_SCRIBE_MEDIA_ROOT:-ascend-audio-scribe-media}:/audio"`, and declare `hf-cache` and `ascend-audio-scribe-media` under top-level `volumes:`. Acceptance: `grep -nE 'Desktop|D:/Development' compose.yaml` finds nothing.
- [ ] 4.2 Change `compose.yaml:277` to `MCP_FILE_URI_ROOT=${ASCEND_AUDIO_SCRIBE_FILE_URI_ROOT:-}` and update the comment above it. Confirm ascend-audio-scribe treats an empty value as `file://` disabled, adding a test in `apps/ascend-audio-scribe/tests/` if that path has none. Acceptance: `.venv/Scripts/python.exe -m pytest` in `apps/ascend-audio-scribe` passes.
- [ ] 4.3 Verify: with the variables unset, `/audio` is an empty named volume and an MCP call with `file:///audio/x.mp3` is rejected. With the owner's `.env` lines set, a Desktop file is transcribed.

## 5. Container hardening

- [ ] 5.1 Add `security/chromium-seccomp.json`: the Docker default seccomp profile plus `clone`, `unshare` and `setns` with namespace flags (design D5). Acceptance: the file is valid JSON (`python -m json.tool security/chromium-seccomp.json`).
- [ ] 5.2 In `compose.ascend-web-hunter.yaml`, remove `cap_add: SYS_ADMIN` (`:208-209`) from ascend-web-hunter and add `init: true` and `security_opt: ["seccomp=./security/chromium-seccomp.json", "no-new-privileges:true"]`. Acceptance: `docker inspect --format '{{.HostConfig.CapAdd}} {{.HostConfig.SecurityOpt}}' ascend-web-hunter` shows no added capability and both options.
- [ ] 5.3 Verify the Playwright tier still renders a JavaScript-heavy page inside the rebuilt container through a `POST` to the ascend-web-hunter page-reading endpoint. Acceptance: the response carries extracted text and the container log shows no sandbox error.
- [ ] 5.4 Add `security_opt: ["no-new-privileges:true"]` to every service in `compose.yaml` that lacks it, including loki, vector, otel-collector, tempo, container-metrics-exporter, prometheus, grafana and gateway. Acceptance: `docker inspect` shows the option on every running container.

## 6. SSRF allowlists and object store privacy

- [ ] 6.1 Change `MCP_ALLOWED_HOSTS` at `compose.yaml:81` (ascend-ocr) and `:275` (ascend-audio-scribe) to `${MCP_ALLOWED_HOSTS:-}`. Acceptance: `grep -n 'MCP_ALLOWED_HOSTS=' compose.yaml` shows no `localhost`, `127.0.0.1` or `host.docker.internal`.
- [ ] 6.2 Verify: with `MCP_ALLOWED_HOSTS` unset, an ascend-ocr `ocr_submit` with `http://host.docker.internal:9070/x` fails with `UNSAFE_URI`. With `MCP_ALLOWED_HOSTS=host.docker.internal` the same kind of fetch of a real object succeeds.
- [ ] 6.3 SearXNG limiter: no change (design D6). Leave `infra/searxng/settings.yml`, `apps/ascend-web-hunter/deploy-standalone/searxng/settings.yml` and `compose.ascend-web-hunter.yaml:190-191` as they are. Acceptance: `git diff --stat` lists none of these three files.

## 7. Healthchecks and startup ordering

- [ ] 7.1 Add healthchecks to docling-serve, unstructured-api, ascend-weather-mcp, prometheus, grafana, loki, vector, otel-collector and tempo, each with a tool present in its image (design D9). Acceptance: after `docker compose up -d`, `docker compose ps` shows every service `healthy`.
- [ ] 7.2 Change ascend-agent `depends_on` (`compose.yaml:125-128`) to long form with `condition: service_healthy` on ascend-memory, docling-serve and unstructured-api. Acceptance: on a cold `docker compose up -d`, `docker events` shows ascend-agent starting only after the three report healthy.
- [ ] 7.3 Remove `--web.enable-lifecycle` from the Prometheus command (`compose.yaml:352`). Acceptance: `curl -X POST http://localhost:7077/-/reload` does not return 200.

## 8. `.env.example` and documentation

- [ ] 8.1 Extend `.env.example` with `EXPOSE_BIND`, `ASCEND_DOMAIN`, `GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD`, `MCP_ALLOWED_HOSTS` (with the `host.docker.internal` line for local work), `HF_CACHE_ROOT`, `ASCEND_AUDIO_SCRIBE_MEDIA_ROOT`, `ASCEND_AUDIO_SCRIBE_FILE_URI_ROOT`, `COMPOSE_PROFILES` (naming `redis` and `captcha-intervention`), `POSTGRES_USER`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_ENDPOINT`, `S3_PUBLIC_ENDPOINT`, `QDRANT_API_KEY`, `OCR_RESULT_S3_ENDPOINT`, `OCR_RESULT_S3_PUBLIC_ENDPOINT`, `OCR_RESULT_S3_ACCESS_KEY`, `OCR_RESULT_S3_SECRET_KEY`, `SECURITY_USERNAME`, `SECURITY_PASSWORD`. One comment line per variable naming its purpose and consuming service, empty values for secrets, production-required variables flagged. Do not add `SECURITY_ENABLED` (owned by `add-auth-and-identity`). Acceptance: every `${VAR` in both compose files appears in `.env.example`, checked with `grep -ohE '\$\{[A-Z_]+' compose.yaml compose.ascend-web-hunter.yaml | sort -u`.
- [ ] 8.2 Add the cloud VM section to `docs/DEPLOYMENT.md`: DNS for `ASCEND_DOMAIN`, ACME and the local internal CA, `.env` preparation, which stack provides the four data stores, the production checklist (`SPRING_PROFILES_ACTIVE=docker,production`, no development default credentials, both public endpoint variables set to the private object store address, external port scan), and the loopback-ports caveat. Acceptance: every checklist item has a command next to it.
- [ ] 8.3 Add backup and restore steps for Postgres, Redis, Qdrant and the object store to the same section, for both container and managed-service topologies. Acceptance: each store has one backup command and one restore command.
- [ ] 8.4 Update the root `README.md` ports section and the compose tables in the root `AGENTS.md` (gateway on 80 and 443, loopback-bound ports, ngrok profile). Acceptance: `grep -n '0.0.0.0' README.md AGENTS.md` finds no claim that a service other than the gateway listens on all interfaces.

## 9. End-to-end verification

- [ ] 9.1 Fresh clone: copy `.env.example` to `.env`, fill the required values, `docker compose up -d --build`. Acceptance: every service `healthy`, every documented `localhost:<port>` address answers, a Bruno prompt request to the agent succeeds.
- [ ] 9.2 From a second machine scan the host. Acceptance: only 80 and 443 open, `https://<domain-or-localhost>/actuator/health` returns 200 through the gateway.
- [ ] 9.3 Acceptance: Grafana redirects an anonymous request to its login page, and `git grep -nE 'access-key: admin|secret-key: password|password: local'` finds no committed literal.
- [ ] 9.4 Ask the owner which run scenario from `docs/E2E_RUN_SCENARIOS.md` to use, then run it against the hardened stack. Acceptance: no spec regresses compared with the last run on master.
- [ ] 9.5 Keep the checkboxes in this file current as work proceeds.
