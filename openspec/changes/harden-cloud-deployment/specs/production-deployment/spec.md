# production-deployment Delta Specification

## ADDED Requirements

### Requirement: The edge gateway is the only publicly bound service

`compose.yaml` SHALL define a `gateway` service (Caddy 2, version-pinned image) that is the only compose service publishing ports on all host interfaces: `0.0.0.0:80` and `0.0.0.0:443`. The gateway SHALL terminate TLS — via ACME when `ASCEND_DOMAIN` is a real domain, via Caddy's internal CA when `ASCEND_DOMAIN` is `localhost` or unset — and SHALL reverse-proxy application traffic to `ascend-ai-agent:9917` over the compose network. The gateway config SHALL live in a checked-in file (`gateway/Caddyfile`) and SHALL reserve a commented route for the Keycloak service introduced by the `add-auth-and-identity` change. The gateway SHALL set `X-Forwarded-For` and `X-Forwarded-Proto` on proxied requests.

#### Scenario: External port scan shows only 80 and 443

- **WHEN** the stack runs on a cloud VM and an external host port-scans the VM's public IP
- **THEN** only ports 80 and 443 accept connections
- **AND** direct connection attempts to 9917, 7020, 7017, 7021, 7022, 9998, 5001, 9080, 9020, 8191, 7077, and 7078 from outside the VM fail

#### Scenario: ascend-ai-agent is reachable through the gateway over TLS

- **WHEN** a client sends `POST https://<ASCEND_DOMAIN>/api/v1/ai/prompt` with a valid request body
- **THEN** the gateway terminates TLS and proxies the request to `ascend-ai-agent:9917`
- **AND** the response is the same as a direct in-network call to ascend-ai-agent

#### Scenario: Local dev gets a working TLS endpoint without a domain

- **WHEN** a developer runs `docker compose up` with `ASCEND_DOMAIN` unset
- **THEN** the gateway serves `https://localhost` with a certificate from Caddy's internal CA
- **AND** no ACME requests leave the machine

### Requirement: Internal service ports bind to loopback by default

Every host-port publication in `compose.yaml` and `compose.ascend-web-hunter.yaml` except the gateway's SHALL use the form `"${EXPOSE_BIND:-127.0.0.1}:<host-port>:<container-port>"`. With `EXPOSE_BIND` unset the port binds to `127.0.0.1` only. The main `compose.yaml` SHALL remain the single compose entry point (no `-f` flag, no second compose project), and `docker compose up` from the repo root SHALL continue to bring up the full stack.

#### Scenario: Fresh clone binds services to loopback

- **WHEN** a developer clones the repo, prepares `.env` from `.env.example`, and runs `docker compose up -d --build`
- **THEN** `docker inspect` shows every published port except the gateway's bound to `127.0.0.1`
- **AND** `http://localhost:7020/health` (and the other localhost port URLs documented in the README) still respond as before

#### Scenario: Loopback binding blocks LAN access

- **WHEN** another machine on the same network attempts `http://<host-LAN-IP>:7020/health`
- **THEN** the connection is refused or times out
- **AND** the same request from the host itself via `localhost` succeeds

### Requirement: Credentials flow from environment with production fail-fast

All credentials consumed by the stack SHALL be sourced from environment variables backed by `.env`: Postgres user/password, Redis password, S3 access/secret keys, Qdrant API key, Grafana admin user/password, and the SearXNG secret. `GRAFANA_ADMIN_PASSWORD` and `SEARXNG_SECRET` SHALL use compose's `${VAR:?message}` required form so `docker compose up` fails immediately when they are unset. Datastore credentials MAY carry dev defaults in `application.yaml` (`${VAR:devdefault}`), but ascend-ai-agent SHALL refuse to start under the `production` Spring profile while any datastore credential still equals its known dev default. The SearXNG `secret_key` SHALL be removed from `infra/searxng/settings.yml` and injected via the `SEARXNG_SECRET` env var; the previously committed value SHALL be treated as compromised and rotated.

#### Scenario: Missing required secret fails compose up

- **WHEN** an operator runs `docker compose up` with `GRAFANA_ADMIN_PASSWORD` unset
- **THEN** compose exits with an error naming the missing variable before any container starts

#### Scenario: Production profile rejects dev-default credentials

- **WHEN** ascend-ai-agent starts with the `production` Spring profile active and `S3_SECRET_KEY` still resolving to the dev default `password`
- **THEN** the application fails startup with an error naming the offending credential
- **AND** with real values set for every datastore credential the application starts normally

#### Scenario: No working secret remains in the tree

- **WHEN** a reviewer greps the repository for the old SearXNG `secret_key` value and for `access-key: admin` / `secret-key: password` as literal committed values
- **THEN** no committed file contains a credential that a production deployment would accept
- **AND** `infra/searxng/settings.yml` contains no `secret_key` entry

### Requirement: Personal-machine artifacts are opt-in

The compose files SHALL contain no personal absolute paths. The `ascend-audio-scribe` volumes SHALL use env-interpolated sources with named-volume defaults (`${HF_CACHE_ROOT:-hf-cache}:/hf-cache`, `${ASCEND_AUDIO_SCRIBE_MEDIA_ROOT:-ascend-audio-scribe-media}:/audio`), and `MCP_FILE_URI_ROOT` SHALL default to empty (`${ASCEND_AUDIO_SCRIBE_FILE_URI_ROOT:-}`), which disables `file://` URIs. The `ngrok-ascend-web-hunter` service SHALL be gated behind a compose profile so it does not start by default.

#### Scenario: Default deployment cannot read host files via transcription

- **WHEN** the stack starts with `ASCEND_AUDIO_SCRIBE_FILE_URI_ROOT` and `ASCEND_AUDIO_SCRIBE_MEDIA_ROOT` unset
- **AND** a caller sends the ascend-audio-scribe MCP tool a `file:///audio/anything.mp3` URI
- **THEN** the request is rejected because `file://` support is disabled
- **AND** `/audio` inside the container is an empty named volume, not a host directory

#### Scenario: Owner restores the Desktop workflow via .env

- **WHEN** the repo owner sets `ASCEND_AUDIO_SCRIBE_MEDIA_ROOT` to a host path and `ASCEND_AUDIO_SCRIBE_FILE_URI_ROOT=/audio` in `.env` and restarts the service
- **THEN** `file://` transcription of files in that directory works as it did before this change

#### Scenario: Ngrok does not start by default

- **WHEN** a developer runs `docker compose up -d`
- **THEN** `ngrok-ascend-web-hunter` is not created
- **AND** activating its profile (via `COMPOSE_PROFILES` in `.env`) starts it

### Requirement: ascend-web-hunter runs without SYS_ADMIN

The `ascend-web-hunter` service SHALL NOT declare `cap_add: SYS_ADMIN`. Chromium sandboxing SHALL instead be enabled by a checked-in seccomp profile (`security/chromium-seccomp.json`) referenced via `security_opt`, together with `init: true` for child-process reaping. The existing `shm_size: 2gb` SHALL be retained.

#### Scenario: Capability removed while extraction still works

- **WHEN** the `ascend-web-hunter` container is inspected after `docker compose up`
- **THEN** `docker inspect` shows no added capabilities and the custom seccomp profile applied
- **AND** the Playwright extraction tier successfully renders a JavaScript-heavy page end-to-end

### Requirement: SSRF allowlists exclude loopback by default

`MCP_ALLOWED_HOSTS` on `ascend-ocr` and `ascend-audio-scribe` SHALL be env-driven with the default `object-store` (`${MCP_ALLOWED_HOSTS:-object-store}`). The committed compose files SHALL NOT list `localhost`, `127.0.0.1`, or `host.docker.internal` as allowlist defaults. Local-dev topologies where the S3-compatible object store runs on the Docker host SHALL opt in per machine by setting `MCP_ALLOWED_HOSTS` in `.env`, and this opt-in SHALL be documented in `.env.example` and the deployment guide.

#### Scenario: Loopback fetch is blocked by default

- **WHEN** the stack runs with `MCP_ALLOWED_HOSTS` unset and a caller asks ascend-ocr's MCP tool to fetch `http://127.0.0.1:9070/some-object`
- **THEN** the request is rejected with `UNSAFE_URI`

#### Scenario: In-network object-store fetch succeeds

- **WHEN** the S3-compatible object store is reachable at hostname `object-store` on the compose network and a caller supplies an `http://object-store:...` presigned URL
- **THEN** the fetch is permitted by the default allowlist and OCR/transcription proceeds

### Requirement: SearXNG runs with its limiter enabled and real client context

The `ascend-web-hunter` environment SHALL set `SEARXNG_LIMITER=true` and SHALL NOT set the spoofed `SEARXNG_X_FORWARDED_FOR` / `SEARXNG_X_REAL_IP` constants. ascend-web-hunter SHALL forward the client context it received (originating from the gateway's `X-Forwarded-For`) on its SearXNG requests.

#### Scenario: Limiter is active

- **WHEN** SearXNG starts via `docker compose up`
- **THEN** its effective configuration reports the limiter enabled
- **AND** search requests from ascend-web-hunter carry a real forwarded client address, not `0.0.0.0`

### Requirement: Observability UIs require authentication and are not publicly bound

Grafana SHALL run with `GF_AUTH_ANONYMOUS_ENABLED=false` and admin credentials from env (`GF_SECURITY_ADMIN_USER`, `GF_SECURITY_ADMIN_PASSWORD`). Prometheus SHALL NOT run with `--web.enable-lifecycle`. Both SHALL be loopback-bound per the port-binding requirement, reachable on a VM only via SSH tunnel or an explicitly enabled gateway route.

#### Scenario: Anonymous Grafana access is refused

- **WHEN** a client requests a Grafana dashboard URL without logging in
- **THEN** Grafana redirects to its login page instead of rendering the dashboard
- **AND** logging in with the credentials from `.env` succeeds

### Requirement: Gateway enforces edge limits and streams SSE without buffering

The edge gateway SHALL apply coarse abuse-limiting to the unauthenticated surfaces it fronts — a per-client connection cap and a request-rate limit covering the Keycloak login and token endpoints and a global fallback — with thresholds overridable via environment. The gateway SHALL proxy the `POST /api/v1/ai/prompt/stream` route without buffering the response and with a read timeout long enough that a normal token stream is never truncated by the proxy, so Server-Sent Events reach the client as they are produced.

#### Scenario: Token-endpoint abuse is rate-limited at the edge

- **WHEN** a single client sends a burst of requests to the Keycloak token endpoint exceeding the configured edge rate limit
- **THEN** the gateway rejects the excess with HTTP 429 before they reach the upstream

#### Scenario: SSE stream passes through the gateway unbuffered

- **WHEN** a client calls `POST /api/v1/ai/prompt/stream` through the gateway and the agent emits `delta` events over several seconds
- **THEN** the client receives `delta` events incrementally as they are produced
- **AND** the gateway does not close the connection before the terminal `done` event on a normal-length generation

#### Scenario: Prometheus config cannot be reloaded over HTTP

- **WHEN** a client sends `POST http://localhost:7077/-/reload`
- **THEN** the request is rejected because the lifecycle endpoint is disabled

### Requirement: Compose declares production runtime posture

`compose.yaml` SHALL apply a shared `x-logging` anchor (json-file driver, `max-size: 10m`, `max-file: 3`) to every service; SHALL upgrade `depends_on` entries to `condition: service_healthy` wherever the dependency defines a healthcheck; SHALL define healthchecks for `docling-serve`, `unstructured-api`, `ascend-weather-mcp`, `searxng`, `flaresolverr`, `prometheus`, and `grafana`; SHALL pin every image to a specific version (including `ngrok/ngrok`); and SHALL pass `SECURITY_ENABLED=${SECURITY_ENABLED:-false}` to ascend-ai-agent, with the production checklist in the deployment guide requiring `SECURITY_ENABLED=true`.

#### Scenario: Agent waits for healthy dependencies

- **WHEN** `docker compose up -d` starts the stack from cold
- **THEN** `ascend-ai-agent` is not started until `ascend-memory`, `docling-serve`, and `unstructured-api` report healthy

#### Scenario: Log output is rotation-bounded

- **WHEN** any service container is inspected
- **THEN** its logging config shows the json-file driver with `max-size: 10m` and `max-file: 3`

#### Scenario: No floating image tags

- **WHEN** a reviewer lists every `image:` line across both compose files
- **THEN** every pulled image carries an exact version tag (no `latest`, no bare major tag)

### Requirement: The deployment guide covers single-tenant cloud VM deployment

`docs/DEPLOYMENT.md` SHALL gain a cloud VM deployment section covering: DNS setup for `ASCEND_DOMAIN`, TLS issuance via the gateway (ACME) and the local internal-CA fallback, preparing `.env` from `.env.example` with every required secret, the production checklist (`SECURITY_ENABLED=true`, no dev-default credentials, external port scan), and backup/restore procedures for the four external data stores (Postgres, Redis, Qdrant, the S3-compatible object store) for both co-located-container and managed-service topologies.

#### Scenario: An operator can deploy from the guide alone

- **WHEN** an operator with a fresh VM, a domain, and the four data stores follows the guide top to bottom
- **THEN** the stack comes up serving `https://<domain>` with only 80/443 publicly open, and every checklist item is verifiable with a command given in the guide

#### Scenario: Backups are documented per store

- **WHEN** a reader opens the backup section
- **THEN** it contains a concrete backup and restore procedure for each of Postgres, Redis, Qdrant, and the S3-compatible object store
