# Harden Cloud Deployment

## Why

The compose stack is a setup for one developer's workstation. On a cloud VM with a public IP it is a security incident. Line numbers below were checked against the files on 2026-10-01.

Services in `compose.yaml` publish their ports on every host interface: Docling with its UI enabled (`compose.yaml:14-15`, UI flag at `:25`), Unstructured (`:37-38`), ascend-ocr (`:58-59`), ascend-agent (`:121-122`), ascend-memory (`:180-181`), ascend-weather-mcp (`:239-240`), ascend-audio-scribe (`:266-267`), Prometheus (`:347-348`) and Grafana with anonymous Editor access (`:368-369`, anonymous flags at `:371-372`). In `compose.ascend-web-hunter.yaml`, ascend-web-hunter publishes `7021` on every interface (`:178-179`). SearXNG and FlareSolverr are already bound to `127.0.0.1` (`compose.ascend-web-hunter.yaml:26` and `:63`). The observability services loki, otel-collector, tempo and container-metrics-exporter publish no host port today, and that must stay true.

Further problems:

- `ascend-audio-scribe` bind-mounts the owner's Desktop and a personal model cache (`compose.yaml:282-283`) and sets `MCP_FILE_URI_ROOT=/audio` (`:277`), so any caller can read Desktop files through the transcription tool.
- `ascend-web-hunter` runs with `cap_add: SYS_ADMIN` (`compose.ascend-web-hunter.yaml:208-209`) while it renders untrusted web pages.
- The SSRF allowlists of ascend-ocr and ascend-audio-scribe list loopback (`MCP_ALLOWED_HOSTS=host.docker.internal,localhost,127.0.0.1` at `compose.yaml:81` and `:275`).
- Credentials are committed defaults: object store `admin`/`password` in `apps/ascend-agent/src/main/resources/application.yaml:107-108` and in the ascend-ocr result store variables (`compose.yaml:77-78`), Postgres `postgres`/`local` (`application.yaml:370-371`), the built-in login `admin`/`admin` (`application.yaml:73-74`), Redis without a password, Qdrant without an API key.
- The object store addresses are fixed: the agent uses `http://host.docker.internal:9070` with a presign address of `http://localhost:9070` (`application-docker.yaml`, `app.s3`), and ascend-ocr uses `OCR_RESULT_S3_ENDPOINT` and `OCR_RESULT_S3_PUBLIC_ENDPOINT` with the same two fixed values (`compose.yaml:74-75`).
- Prometheus runs with `--web.enable-lifecycle` (`compose.yaml:352`), an unauthenticated reload endpoint.
- `compose.yaml` has no log rotation. The `x-logging` anchor exists only in `compose.ascend-web-hunter.yaml:6-10`, and YAML anchors do not cross an `include:`.
- Everything speaks plain HTTP.

## Build order

Build order (owner build order of 2026-10-04, which supersedes the earlier orders, changed by owner answer 72.1 of 2026-10-06): build group 3 (base), position 4. This change was never started (its only ticked tasks are the section 0 checks of facts that were already true), so it left build group 1 and lands directly after `add-keycloak-login`, because the Keycloak login must land before hardening. It needs `add-observability` (build group 1, position 1), whose internal management port `9918` the gateway never routes to, `fix-linux-docker-host-access` (build group 1, position 4), which adds the `extra_hosts` line and the named volume form of the `ascend-audio-scribe` service (owner answer 83 of 2026-10-08), `add-ascend-python-common` (build group 2, position 1), which renamed `MCP_ALLOWED_HOSTS` to `ALLOWED_PRIVATE_HOSTS`, `upgrade-spring-boot-4` (build group 3, position 2) for the Spring Boot 4 failure analyzer of its startup check, and `add-keycloak-login` (build group 3, position 3), whose `keycloak` service, `SERVICE_AUTH_TOKEN` and production login guard (its D21) exist when this change starts. So the agent has no `app.security.*` and no HTTP Basic user any more, and this change adds no login check of its own: the D21 guard of `add-keycloak-login` is the production login guard. The build group 2 changes edit both compose files before this change, among them `remove-flaresolverr-tier`, which removes the `flaresolverr` service, and `add-file-download`, which adds the `clamav` service under its own profile, so every compose line number below is re-checked when this change starts.

Earlier changes whose work this change builds on (owner answer 72.1 of 2026-10-06): `add-ascend-python-common` (build group 2) already renamed `MCP_ALLOWED_HOSTS` to `ALLOWED_PRIVATE_HOSTS`, so this change writes only the new name. `add-keycloak-login` (build group 3, position 3) already deleted `app.security.*` and the HTTP Basic user, added the `keycloak` service with its production start mode, the production guard of its D21, and `SERVICE_AUTH_TOKEN` and the issuer variable in the agent environment and `.env.example`. This change adds the Keycloak site block with its own host name to `gateway/Caddyfile` and the login and token rate limits on that site (former tasks 1.6 gateway part and 1.7 of `add-keycloak-login`). Keycloak is never routed under a path of the agent's site.

Later changes that plug into the files this change creates, each adding its own part when it lands (dependency fix of 2026-10-05):

- `add-deployment-modules` (build group 3): puts `ngrok-ascend-web-hunter` behind the profile `captcha-intervention`, a companion of the module `web-search`, uses `required: false` on every `depends_on` entry for a service under a module profile, passes `ASCEND_MODULES` to the agent, and describes `COMPOSE_PROFILES` as the module list in `.env.example`.
- `add-document-management-api` (build group 3): gives public clients `GET /api/v1/documents/{id}/content`, so the object store never needs to be public.
- `add-chat-streaming-and-conversations` (build group 3): adds the gateway route for `POST /api/v1/ai/prompt/stream` with no buffering, and its end-to-end check through the gateway.
- `add-agent-sandbox` (build group 4): adds `ascend-sandbox-runner` as the one service allowed to mount the Docker socket for sandbox work, its `SANDBOX_RUNNER_TOKEN` compose guard and `.env.example` line, and the gVisor (`runsc`) and `DOCKER_SOCKET_GID` steps to the VM guide.
- `add-mcp-tool-servers` (build group 4): its egress proxy follows the rules of this change (no published port, `no-new-privileges`, secrets in `.env`).
- `add-openclaw-plugin-host` (build group 4): adds the gateway routes `/hooks/<platform>/*` to its `channels` container, the 404 for `/api/v1/channel-host/*` at the gateway, and the loopback-only port of `ascend-openclaw-host-channels`.
- `add-coding-agent-delegation` (build group 4): adds the coding project area partition at `/srv/ascend/coding`, the GitHub App setup and its secrets `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY` and `OPENCODE_API_KEY` to the VM guide and `.env.example`.
- `add-self-built-integrations` (build group 4): adds the sizing of integration containers, the `integrations-ingress` network and the secrets file `integration-secrets.env` to the VM guide.

Earlier text of this change carried an interim production check that refused to start while `app.security.enabled` was false, and a login password `admin` check in `ProductionCredentialGuard`, to be replaced later by `add-keycloak-login` task 2.9. Owner answer 72.1 of 2026-10-06 removed both: `add-keycloak-login` lands first and its D21 guard is the guard.

## What Changes

- Edge gateway with TLS. A Caddy 2 service is the only service that publishes on every interface, ports 80 and 443. It gets ACME certificates for a real domain and an internal certificate for `localhost`. The agent's site routes to `ascend-agent:9917` and nowhere else. A second site with Keycloak's own host name routes to `keycloak:8080` and carries per-client-address rate limits on the Keycloak login and token endpoints. Later changes add their own routes to `gateway/Caddyfile` (see Build order).
- Bind address from the environment. Every other published port becomes `"${EXPOSE_BIND:-127.0.0.1}:<host>:<container>"`, the Keycloak port `8180` included. Local `docker compose up` keeps every `localhost:<port>` address. The SearXNG port, already bound to `127.0.0.1`, moves to the same form so one variable controls all of them.
- Secrets out of the tree. Postgres, Redis, Qdrant, object store, ascend-ocr result store and Grafana admin come from `.env`, next to `SERVICE_AUTH_TOKEN` and the issuer variable `KEYCLOAK_ISSUER_URI` that `add-keycloak-login` already passes. `GRAFANA_ADMIN_PASSWORD` and `SEARXNG_SECRET` are required in every deployment through their compose `:?` guards, because Grafana is an always-on service. Under the `production` Spring profile the agent refuses to start while a datastore credential still equals its development default (design D3). The login side of a public deployment is the D21 guard of `add-keycloak-login`, which this change does not repeat.
- Object store addresses from the environment, and the object store is never public. The presign address variables of the agent and of ascend-ocr are set to the private address in production, because only containers on the private network follow those links.
- Personal-machine artifacts become opt-in: `MCP_FILE_URI_ROOT`. The Desktop mount and the model cache path already became opt-in variables in `fix-linux-docker-host-access` (build group 1, position 4, owner answer 83 of 2026-10-08). The ngrok tunnel moves behind a compose profile later, in `add-deployment-modules`.
- Docker socket: the agent never gets it. Only the observability services that read it (otel-collector and container-metrics-exporter, read-only) mount it. A read-only socket mount is not a restriction, because the Docker API still accepts every call through it. `add-agent-sandbox` later adds `ascend-sandbox-runner` as the one service allowed to mount it for sandbox work.
- `SYS_ADMIN` removed from ascend-web-hunter. A checked-in seccomp profile and `init: true` replace it.
- SSRF allowlists with no loopback default, under the name `ALLOWED_PRIVATE_HOSTS`.
- Grafana requires a login, Prometheus loses the lifecycle endpoint.
- Production posture: own `x-logging` anchor in `compose.yaml`, healthchecks for the services that lack them, `condition: service_healthy` for the agent's dependencies on ascend-memory, docling-serve and unstructured-api, `no-new-privileges` on every service.
- SearXNG limiter stays off by an explicit decision (design D6), so `infra/searxng/settings.yml` and its copy are not changed.
- Deployment guide: `docs/DEPLOYMENT.md` gains a section for one cloud VM per customer. Later changes that need a host step add it to that section themselves (see Build order).

Already true in the code and not repeated by this change: `SEARXNG_SECRET` is required by compose and `infra/searxng/settings.yml` has no `secret_key`, SearXNG and FlareSolverr are bound to `127.0.0.1`, `compose.ascend-web-hunter.yaml` has its own `x-logging` anchor on every service, the ngrok image is pinned by digest, SearXNG and FlareSolverr have healthchecks, and ascend-web-hunter waits on both with `condition: service_healthy`.

## Capabilities

### New Capabilities

- `production-deployment`: network exposure model, TLS at the gateway with the Keycloak site, secrets from the environment with a production startup guard for datastore credentials, object store privacy, personal-artifact gating, SSRF allowlist posture, container hardening with the Docker socket rule, observability exposure, production runtime posture and the cloud VM guide.

### Modified Capabilities

- `ascend-agent-containerization`: the agent port becomes loopback-bound by default with public access through the gateway, `depends_on` uses the long form with `condition: service_healthy` on ascend-memory, docling-serve, unstructured-api and keycloak, and `.env.example` covers the new deployment variables.
- `identity-provider` (created by `add-keycloak-login`, which lands first): a new requirement that the Keycloak login and token endpoints are rate limited at the gateway (moved here from `add-keycloak-login` by owner answer 72.1 of 2026-10-06).

`ingestion-security` was reviewed and stays unchanged. It covers upload checks inside the agent, not deployment posture.

## Impact

- `compose.yaml`: new `gateway` service, new `x-logging` anchor applied to every service, port prefixes, Grafana environment, Prometheus command, ascend-audio-scribe `MCP_FILE_URI_ROOT`, `ALLOWED_PRIVATE_HOSTS` and `OCR_RESULT_S3_*` from the environment, agent credentials and object store addresses passed through, new healthchecks, `depends_on` long form, `no-new-privileges`.
- `compose.ascend-web-hunter.yaml`: port prefixes, `SYS_ADMIN` removed, seccomp profile and `init: true`, `REDIS_URL` password support.
- New files: `gateway/Caddyfile` (agent site and Keycloak site with its rate limits), `security/chromium-seccomp.json`.
- `apps/ascend-agent/src/main/resources/application.yaml` and `application-docker.yaml`: credentials and object store addresses from the environment. The datastore credentials join the one production startup guard of `add-keycloak-login` (owner answer 89.10 of 2026-10-08): required placeholders in `application-production.yaml` and one check bean, `DatastoreCredentialCheck`, for blank and weak values, with no guard class of its own and its tests in `apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/config/` and `src/test/java/...`.
- `.env.example`, `docs/DEPLOYMENT.md`, root `README.md`, root `AGENTS.md`.
- `apps/ascend-web-hunter/deploy-standalone/` is not changed by this change. It keeps its own documented differences.

## Relevant Skills

- `/docker-patterns`
- `/deployment-patterns`
- `/security-review`
- `/springboot-patterns`
- `/java-coding-standards`
- `/tdd-workflow`
- `/markdown-writer`
- `/e2e-runbooks`
