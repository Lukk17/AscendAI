# Tasks — Harden Cloud Deployment

## 1. Port bindings and compose mechanics

- [ ] 1.1 Rewrite every `ports:` entry in `compose.yaml` (docling-serve, unstructured-api, ascend-ocr, ascend-ai-agent, ascend-memory, ascend-weather-mcp, ascend-audio-scribe, prometheus, grafana) to the `"${EXPOSE_BIND:-127.0.0.1}:<host>:<container>"` form
- [ ] 1.2 Rewrite every `ports:` entry in `compose.ascend-web-hunter.yaml` (searxng, flaresolverr, ascend-web-hunter) to the same form
- [ ] 1.3 Add a top-level `x-logging: &default-logging` anchor (json-file, `max-size: 10m`, `max-file: 3`) and apply `logging: *default-logging` to every service in both files
- [ ] 1.4 Pin `ngrok/ngrok:3` to an exact version tag and confirm every other `image:` line in both files is already exact-pinned
- [ ] 1.5 Verify: `docker compose config` renders cleanly; `docker compose up -d` from the repo root brings up the full stack as one project with no `-f` flag; `docker inspect` shows every published port bound to `127.0.0.1`; a request to `http://<host-LAN-IP>:7020/health` from another machine fails while `http://localhost:7020/health` succeeds

## 2. Edge gateway

- [ ] 2.1 Create `gateway/Caddyfile`: site block on `{$ASCEND_DOMAIN:localhost}`, reverse_proxy to `ascend-agent:9917`, forwarded headers on, commented reserved routes for Keycloak (`/auth/*` path form and `auth.` subdomain form, per design D2)
- [ ] 2.2 Add the `gateway` service to `compose.yaml`: pinned `caddy:2.x` image, ports `"80:80"` and `"443:443"` (all interfaces — the one exception to task 1.1), Caddyfile + cert-storage volume mounts, `ASCEND_DOMAIN` env, healthcheck, restart policy, logging anchor
- [ ] 2.3 Add a commented, operator-gated Caddy route for Grafana (disabled by default per design D8)
- [ ] 2.4 Verify locally: `docker compose up -d gateway` with `ASCEND_DOMAIN` unset serves `https://localhost` from Caddy's internal CA; `curl -k https://localhost/actuator/health` proxies through to ascend-ai-agent and returns 200
- [ ] 2.5 Coordinate with `add-auth-and-identity`: note in that change's tasks that uncommenting the Keycloak route in `gateway/Caddyfile` is part of its Keycloak wiring
- [ ] 2.6 Add edge-layer request/connection ceilings on the gateway for the unauthenticated surfaces it fronts (Keycloak login and token endpoints, plus a coarse global cap): per-client connection limit and request-rate limit tuned to bound brute-force / abuse without tripping normal use; document the thresholds as env-overridable
- [ ] 2.7 Configure SSE-friendly proxying for the `POST /api/v1/ai/prompt/stream` route (`add-chat-streaming-and-conversations`): disable response buffering, set a long/unbounded read timeout on that route so token streams are not cut, and confirm `flush_interval` (or equivalent) streams events immediately; verify a streamed response passes through the gateway without buffering

## 3. Secrets and credentials

- [ ] 3.1 Remove `secret_key` from `infra/searxng/settings.yml`; wire `SEARXNG_SECRET=${SEARXNG_SECRET:?SEARXNG_SECRET must be set}` into the `searxng` service environment; document that the old committed value is compromised and every deployment generates a fresh one
- [ ] 3.2 Grafana: set `GF_AUTH_ANONYMOUS_ENABLED=false`, drop `GF_AUTH_ANONYMOUS_ORG_ROLE`, add `GF_SECURITY_ADMIN_USER=${GRAFANA_ADMIN_USER:-admin}` and `GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD:?GRAFANA_ADMIN_PASSWORD must be set}`
- [ ] 3.3 Parameterize `apps/ascend-agent/src/main/resources/application.yaml`: `app.s3.access-key`/`secret-key` → `${S3_ACCESS_KEY:admin}`/`${S3_SECRET_KEY:password}`, `spring.datasource.username`/`password` → `${POSTGRES_USER:postgres}`/`${POSTGRES_PASSWORD:local}`, `spring.data.redis.password` → `${REDIS_PASSWORD:}`, Qdrant API key → `${QDRANT_API_KEY:}`; mirror any docker-profile overrides in `application-docker.yaml`; pass the variables through the `ascend-ai-agent` compose environment
- [ ] 3.4 Wire `QDRANT_API_KEY` into the `ascend-memory` compose environment and `REDIS_PASSWORD` into the `ascend-web-hunter` `REDIS_URL`, both defaulting to today's unauthenticated local behavior
- [ ] 3.5 Implement the ascend-ai-agent production-profile startup guard (design D3): a `@Configuration` validator active only under the `production` Spring profile that fails startup when any datastore credential equals its dev default, and logs a prominent warning when `SECURITY_ENABLED` is false; add a unit test asserting the guard's default-value constants match `application.yaml` and a test for the fail path
- [ ] 3.6 Verify: `docker compose up` without `GRAFANA_ADMIN_PASSWORD` or `SEARXNG_SECRET` fails fast naming the variable; with them set the stack starts; `./gradlew test` passes; starting ascend-ai-agent with `SPRING_PROFILES_ACTIVE=production` and dev-default S3 credentials aborts startup

## 4. Personal-machine artifacts

- [ ] 4.1 Replace the `ascend-audio-scribe` bind mounts with `"${HF_CACHE_ROOT:-hf-cache}:/hf-cache"` and `"${ASCEND_AUDIO_SCRIBE_MEDIA_ROOT:-ascend-audio-scribe-media}:/audio"`; declare the `hf-cache` and `ascend-audio-scribe-media` named volumes
- [ ] 4.2 Change `MCP_FILE_URI_ROOT` to `${ASCEND_AUDIO_SCRIBE_FILE_URI_ROOT:-}` and confirm ascend-audio-scribe treats empty as `file://` disabled (add a test if that path is untested)
- [ ] 4.3 Add `profiles: ["captcha-intervention"]` to `ngrok-ascend-web-hunter`; make `PUBLIC_VNC_URL` handling in `ascend-web-hunter` tolerate the ngrok service being absent
- [ ] 4.4 Verify: default `docker compose up` creates no ngrok container, `/audio` is an empty named volume, and a `file:///audio/x.mp3` MCP request is rejected; with the owner's `.env` lines set, Desktop-file transcription works again

## 5. Container hardening — ascend-web-hunter

- [ ] 5.1 Add `security/chromium-seccomp.json` (Chromium seccomp profile permitting user-namespace clone/unshare/setns per design D5) to the repo
- [ ] 5.2 In `compose.ascend-web-hunter.yaml`, remove `cap_add: SYS_ADMIN` from `ascend-web-hunter`; add `security_opt: ["seccomp=./security/chromium-seccomp.json"]` and `init: true`
- [ ] 5.3 Verify: `docker inspect ascend-web-hunter` shows no added capabilities and the seccomp profile applied; the Playwright extraction tier renders a JavaScript-heavy page end-to-end inside the rebuilt container

## 6. SSRF and SearXNG posture

- [ ] 6.1 Change `MCP_ALLOWED_HOSTS` on `ascend-ocr` and `ascend-audio-scribe` to `${MCP_ALLOWED_HOSTS:-object-store}`; remove the committed loopback entries
- [ ] 6.2 Set `SEARXNG_LIMITER=true` and delete the `SEARXNG_X_FORWARDED_FOR` / `SEARXNG_X_REAL_IP` spoofed constants from `ascend-web-hunter`; forward the received client `X-Forwarded-For` on SearXNG requests instead
- [ ] 6.3 Verify: with `MCP_ALLOWED_HOSTS` unset, an ascend-ocr MCP fetch of `http://127.0.0.1:9070/x` returns `UNSAFE_URI` while an `http://object-store:...` fetch is permitted; SearXNG reports the limiter enabled and search still works through ascend-web-hunter

## 7. Healthchecks and startup ordering

- [ ] 7.1 Add healthchecks to `docling-serve`, `unstructured-api`, `ascend-weather-mcp`, `searxng`, `flaresolverr`, `prometheus`, and `grafana`
- [ ] 7.2 Upgrade `depends_on` to long form with `condition: service_healthy`: `ascend-ai-agent` → {ascend-memory, docling-serve, unstructured-api}; `ascend-web-hunter` → {searxng, flaresolverr}
- [ ] 7.3 Drop `--web.enable-lifecycle` from the Prometheus command
- [ ] 7.4 Verify: cold `docker compose up -d` starts `ascend-ai-agent` only after its dependencies are healthy; `POST http://localhost:7077/-/reload` is rejected; all services reach `healthy`

## 8. .env.example and documentation

- [ ] 8.1 Extend `.env.example` with every new variable (`EXPOSE_BIND`, `ASCEND_DOMAIN`, `GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD`, `SEARXNG_SECRET`, `SECURITY_ENABLED`, `MCP_ALLOWED_HOSTS`, `HF_CACHE_ROOT`, `ASCEND_AUDIO_SCRIBE_MEDIA_ROOT`, `ASCEND_AUDIO_SCRIBE_FILE_URI_ROOT`, `COMPOSE_PROFILES`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `QDRANT_API_KEY`): one-line comment per variable naming purpose and consuming service, empty values for secrets, safe defaults shown for non-secrets, production-required variables flagged
- [ ] 8.2 Add the cloud VM deployment section to `docs/DEPLOYMENT.md`: DNS for `ASCEND_DOMAIN`, ACME TLS via the gateway plus local internal-CA fallback, `.env` preparation, the production checklist (`SECURITY_ENABLED=true`, no dev-default credentials, external port scan), and the loopback-ports-on-VM caveat from design Risks
- [ ] 8.3 Add backup/restore procedures for Postgres, Redis, Qdrant, and the S3-compatible object store to the same section, covering both co-located-container and managed-service topologies
- [ ] 8.4 Update the root `README.md` ports/configuration prose and the `AGENTS.md` compose tables where exposure semantics changed (gateway on 80/443, loopback-bound service ports, ngrok profile)

## 9. End-to-end verification

- [ ] 9.1 Fresh-clone rehearsal: clean checkout, copy `.env.example` → `.env`, fill the two required secrets, `docker compose up -d --build` — full stack healthy, all documented `localhost:<port>` endpoints respond, Bruno smoke request to ascend-ai-agent succeeds
- [ ] 9.2 From a second machine (or the VM's public interface), port-scan the host: only 80/443 open; direct connections to every internal service port fail; `https://<domain-or-localhost>` reaches ascend-ai-agent through the gateway
- [ ] 9.3 Grafana requires login; Prometheus lifecycle endpoint rejected; repository grep confirms no committed working credential remains (old SearXNG key, `admin`/`password`, `postgres`/`local` as literals)
- [ ] 9.4 Run the e2e suite (`apps/ascend-agent/e2e/`) against the hardened local stack to confirm no capability regressed
- [ ] 9.5 Keep `openspec/changes/harden-cloud-deployment/tasks.md` checkboxes current as work proceeds
