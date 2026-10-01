# production-deployment Delta Specification

## ADDED Requirements

### Requirement: The edge gateway is the only publicly bound service

`compose.yaml` SHALL define a `gateway` service (Caddy 2, image pinned by version and digest) that is the only compose service publishing ports on all host interfaces: `80` and `443`. The gateway SHALL terminate TLS, through ACME when `ASCEND_DOMAIN` is a real domain and through Caddy's internal CA when `ASCEND_DOMAIN` is `localhost` or unset. Its configuration SHALL live in `gateway/Caddyfile` and SHALL proxy only to `ascend-agent:9917`. The gateway SHALL NOT route to Grafana or the object store, and SHALL NOT route any path of the agent's site to Keycloak. Keycloak is a separate service on its own host address and port, defined by `add-auth-and-identity`, which may add Keycloak to `gateway/Caddyfile` only as a separate site address with its own host name.

#### Scenario: External port scan shows only 80 and 443

- **WHEN** the stack runs on a cloud VM and an external host scans the VM's public IP
- **THEN** only ports 80 and 443 accept connections
- **AND** connections from outside the VM to 9917, 7020, 7017, 7021, 7022, 9998, 5001, 9080, 9020, 8191, 7077 and 7078 fail

#### Scenario: The agent is reachable through the gateway over TLS

- **WHEN** a client sends `GET https://<ASCEND_DOMAIN>/actuator/health`
- **THEN** the gateway terminates TLS, proxies to `ascend-agent:9917`, and returns HTTP 200

#### Scenario: Local TLS works without a domain

- **WHEN** a developer runs `docker compose up -d` with `ASCEND_DOMAIN` unset
- **THEN** the gateway serves `https://localhost` with a certificate from Caddy's internal CA
- **AND** no ACME request leaves the machine

### Requirement: The gateway streams Server-Sent Events without buffering

The gateway SHALL proxy `POST /api/v1/ai/prompt/stream` (added by `add-chat-streaming-and-conversations`) without buffering the response and without a proxy timeout that ends a normal stream early.

#### Scenario: A stream passes through the gateway unbuffered

- **WHEN** a client calls `POST /api/v1/ai/prompt/stream` through the gateway and the agent emits `delta` events over several seconds
- **THEN** the client receives each `delta` event as it is produced
- **AND** the connection stays open until the terminal `done` event

### Requirement: Internal service ports bind to loopback by default

Every host-port publication in `compose.yaml` and `compose.ascend-web-hunter.yaml` except the gateway's SHALL use the form `"${EXPOSE_BIND:-127.0.0.1}:<host-port>:<container-port>"`. The services loki, vector, otel-collector, tempo, container-metrics-exporter and the bundled redis SHALL publish no host port. `compose.yaml` SHALL stay the single compose entry point.

#### Scenario: Fresh clone binds services to loopback

- **WHEN** a developer prepares `.env` from `.env.example` and runs `docker compose up -d --build`
- **THEN** `docker inspect` shows every published port except the gateway's bound to `127.0.0.1`
- **AND** `http://localhost:7020/health` and the other documented `localhost` addresses still respond

#### Scenario: Loopback binding blocks LAN access

- **WHEN** another machine on the same network requests `http://<host-LAN-IP>:7020/health`
- **THEN** the connection fails
- **AND** the same request from the host through `localhost` succeeds

### Requirement: Credentials flow from the environment with a production startup guard

Every credential the stack consumes SHALL come from environment variables backed by `.env`: Postgres user and password, Redis password, Qdrant API key, object store access and secret key, ascend-ocr result store keys, Grafana admin user and password, the SearXNG secret, and the built-in login `SECURITY_USERNAME` and `SECURITY_PASSWORD`. `GRAFANA_ADMIN_PASSWORD` and `SEARXNG_SECRET` SHALL use compose's `${VAR:?message}` form. Other credentials MAY keep development defaults, but under the `production` Spring profile ascend-agent SHALL refuse to start while any object store, Postgres, Redis, Qdrant or built-in login credential equals its development default, and the error SHALL name the property without printing its value.

#### Scenario: Missing required secret fails compose

- **WHEN** an operator runs `docker compose up` with `GRAFANA_ADMIN_PASSWORD` unset
- **THEN** compose exits with an error naming the variable before any container starts

#### Scenario: Production profile rejects development defaults

- **WHEN** ascend-agent starts with the `production` profile active and `S3_SECRET_KEY` unset so the value is `password`
- **THEN** startup fails with an error naming `app.s3.secret-key`
- **AND** with real values for every guarded credential the application starts

#### Scenario: Development profile keeps working without variables

- **WHEN** ascend-agent starts without the `production` profile and with none of the credential variables set
- **THEN** it starts with the development defaults

### Requirement: The object store is never public

The gateway SHALL have no route to the object store, and the object store SHALL NOT be published on a public interface by any file of this repository. The object store addresses of the agent (`S3_ENDPOINT`, `S3_PUBLIC_ENDPOINT`) and of ascend-ocr (`OCR_RESULT_S3_ENDPOINT`, `OCR_RESULT_S3_PUBLIC_ENDPOINT`) SHALL come from the environment with today's local values as defaults. The deployment guide SHALL require both public endpoint variables to equal the private object store address in production, because only containers on the private network follow presigned links. Public clients SHALL download RAG sources through the agent's `GET /api/v1/documents/{id}/content`.

#### Scenario: Presigned links point at the private address in production

- **WHEN** a production deployment sets `S3_PUBLIC_ENDPOINT` and `OCR_RESULT_S3_PUBLIC_ENDPOINT` to the private object store address
- **THEN** the agent still reads ascend-ocr results through the presigned link
- **AND** the presigned link does not resolve from outside the VM

### Requirement: Personal-machine artifacts are opt-in

The compose files SHALL contain no personal absolute paths. ascend-audio-scribe volumes SHALL be `${HF_CACHE_ROOT:-hf-cache}:/hf-cache` and `${ASCEND_AUDIO_SCRIBE_MEDIA_ROOT:-ascend-audio-scribe-media}:/audio`, and `MCP_FILE_URI_ROOT` SHALL be `${ASCEND_AUDIO_SCRIBE_FILE_URI_ROOT:-}`, where empty disables `file://`. `ngrok-ascend-web-hunter` SHALL sit behind the `captcha-intervention` compose profile.

#### Scenario: Default deployment cannot read host files

- **WHEN** the stack starts with the three variables unset and a caller sends ascend-audio-scribe a `file:///audio/anything.mp3` URI
- **THEN** the request is rejected because `file://` is disabled
- **AND** `/audio` is an empty named volume

#### Scenario: Owner restores the Desktop workflow

- **WHEN** the owner sets `ASCEND_AUDIO_SCRIBE_MEDIA_ROOT` to a host path and `ASCEND_AUDIO_SCRIBE_FILE_URI_ROOT=/audio` and recreates the service
- **THEN** `file://` transcription of files in that directory works

#### Scenario: Ngrok does not start by default

- **WHEN** a developer runs `docker compose up -d` without `captcha-intervention` in `COMPOSE_PROFILES`
- **THEN** no `ngrok-ascend-web-hunter` container is created
- **AND** ascend-web-hunter still reports healthy

### Requirement: ascend-web-hunter runs without SYS_ADMIN

`ascend-web-hunter` SHALL NOT declare `cap_add: SYS_ADMIN`. It SHALL use the checked-in seccomp profile `security/chromium-seccomp.json` through `security_opt`, `no-new-privileges:true` and `init: true`, and SHALL keep `shm_size: 2gb`.

#### Scenario: Capability removed while extraction still works

- **WHEN** the rebuilt container is inspected
- **THEN** it has no added capability and the custom seccomp profile applied
- **AND** the Playwright tier renders a JavaScript-heavy page

### Requirement: SSRF allowlists have no loopback default

`MCP_ALLOWED_HOSTS` on ascend-ocr and ascend-audio-scribe SHALL be `${MCP_ALLOWED_HOSTS:-}`. The committed compose files SHALL NOT list `localhost`, `127.0.0.1` or `host.docker.internal` as a default. Local development opts in with `MCP_ALLOWED_HOSTS=host.docker.internal` in `.env`, and a cloud deployment lists only the private object store host.

#### Scenario: Host fetch is blocked by default

- **WHEN** `MCP_ALLOWED_HOSTS` is unset and a caller submits `http://host.docker.internal:9070/x` to ascend-ocr's `ocr_submit`
- **THEN** the call fails with `UNSAFE_URI`

#### Scenario: Opt-in allows the local object store

- **WHEN** `.env` sets `MCP_ALLOWED_HOSTS=host.docker.internal` and a caller submits a presigned URL on that host
- **THEN** the fetch is allowed and the job proceeds

### Requirement: SearXNG stays private with its limiter off

SearXNG SHALL be reachable only on the compose network and on host loopback. Its limiter SHALL stay off, as `infra/searxng/settings.yml` documents, because every caller reaches it from the ascend-web-hunter container address. `infra/searxng/settings.yml` and its byte-identical copy `apps/ascend-web-hunter/deploy-standalone/searxng/settings.yml` SHALL stay identical.

#### Scenario: SearXNG is not reachable from outside

- **WHEN** an external host connects to port 9020 on the VM
- **THEN** the connection fails
- **AND** a search through ascend-web-hunter still returns results

### Requirement: Observability services require login or stay unpublished

Grafana SHALL run with `GF_AUTH_ANONYMOUS_ENABLED=false` and admin credentials from the environment. Prometheus SHALL NOT run with `--web.enable-lifecycle`. Grafana and Prometheus SHALL be loopback-bound. loki, vector, otel-collector, tempo and container-metrics-exporter SHALL publish no port and SHALL run with `no-new-privileges:true`.

#### Scenario: Anonymous Grafana access is refused

- **WHEN** a client requests a Grafana dashboard without logging in
- **THEN** Grafana redirects to its login page
- **AND** the credentials from `.env` log in

#### Scenario: Prometheus cannot be reloaded over HTTP

- **WHEN** a client sends `POST http://localhost:7077/-/reload`
- **THEN** the request is rejected

### Requirement: Compose declares production runtime posture

`compose.yaml` SHALL define its own `x-logging` anchor (json-file, `max-size: 10m`, `max-file: 3`) and apply it to every service it defines, because anchors do not cross `include:`. It SHALL define healthchecks for every service it defines, SHALL make ascend-agent wait on ascend-memory, docling-serve and unstructured-api with `condition: service_healthy`, SHALL set `no-new-privileges:true` on every service, and SHALL pin every pulled image by version and digest.

#### Scenario: Agent waits for healthy dependencies

- **WHEN** `docker compose up -d` starts the stack from cold
- **THEN** ascend-agent starts only after ascend-memory, docling-serve and unstructured-api report healthy

#### Scenario: Log output is bounded

- **WHEN** any container of the stack is inspected
- **THEN** its logging uses the json-file driver with `max-size: 10m` and `max-file: 3`

#### Scenario: No floating image

- **WHEN** a reviewer lists every pulled `image:` line in both compose files
- **THEN** each one carries a version tag and a digest

### Requirement: The deployment guide covers one cloud VM per customer

`docs/DEPLOYMENT.md` SHALL describe: DNS for `ASCEND_DOMAIN`, TLS through the gateway and the local internal CA, `.env` preparation, which stack provides the four data stores, the production checklist (`production` Spring profile, no development credentials, public endpoint variables set to the private object store address, external port scan), and backup and restore steps for Postgres, Redis, Qdrant and the object store for container and managed-service topologies.

#### Scenario: An operator deploys from the guide alone

- **WHEN** an operator with a fresh VM, a domain and the four data stores follows the guide
- **THEN** the stack serves `https://<domain>` with only 80 and 443 open
- **AND** every checklist item has a command that verifies it

#### Scenario: Backups are documented per store

- **WHEN** a reader opens the backup section
- **THEN** it gives a backup and a restore procedure for each of Postgres, Redis, Qdrant and the object store
