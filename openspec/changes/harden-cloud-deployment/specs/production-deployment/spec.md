# production-deployment Delta Specification

## ADDED Requirements

### Requirement: The edge gateway is the only publicly bound service

compose.yaml SHALL define gateway Caddy 2 pinned version digest as only all-interface publisher: 80 on GATEWAY_HTTP_HOST_PORT 80 and 443 on GATEWAY_HTTPS_HOST_PORT 443. SHALL end TLS via ACME for real ASCEND_DOMAIN else internal CA, proxy ascend-agent:9917, no profile. SHALL NOT route Grafana, object store, 9918, nor agent paths elsewhere. Keycloak SHALL be only own site own host proxying keycloak:8080 with per-address login/token limits, no agent path to Keycloak.

#### Scenario: External port scan shows only 80 and 443

- **WHEN** the stack runs on a cloud VM and an external host scans the VM's public IP
- **THEN** only ports 80 and 443 accept connections
- **AND** connections from outside the VM to 9917, 7020, 7017, 7021, 7022, 9998, 5001, 9080, 9020, 8180, 7077 and 7078 fail

#### Scenario: The agent is reachable through the gateway over TLS

- **WHEN** a client sends a prompt request to `https://<ASCEND_DOMAIN>/api/v1/ai/prompt`
- **THEN** the gateway terminates TLS, proxies to `ascend-agent:9917`, and the agent answers

#### Scenario: Actuator is not reachable through the gateway

- **WHEN** a client sends `GET https://<ASCEND_DOMAIN>/actuator/health` or `GET https://<ASCEND_DOMAIN>/actuator/prometheus`
- **THEN** the response is HTTP 404, because the agent serves actuator only on its internal management port `9918`

#### Scenario: Local TLS works without a domain

- **WHEN** a developer runs `docker compose up -d` with `ASCEND_DOMAIN` unset
- **THEN** the gateway serves `https://localhost` with a certificate from Caddy's internal CA
- **AND** no ACME request leaves the machine

#### Scenario: Keycloak has its own site

- **WHEN** a reviewer reads `gateway/Caddyfile`
- **THEN** Keycloak is reached only through a site block with its own host name that proxies to `keycloak:8080`
- **AND** no path of the agent's site proxies to Keycloak

### Requirement: Internal service ports bind to loopback by default

Every host publication except the gateway SHALL use `"${EXPOSE_BIND:-127.0.0.1}:${<SERVICE>_HOST_PORT:-<host-port>}:<container-port>"`, with today port as default. loki, otel-collector, tempo, container-metrics-exporter and bundled redis SHALL publish no host port. `compose.yaml` SHALL stay the single entry point.

#### Scenario: Fresh clone binds services to loopback

- **WHEN** a developer prepares `.env` from `.env.example` and runs `docker compose up -d --build`
- **THEN** `docker inspect` shows every published port except the gateway's bound to `127.0.0.1`
- **AND** `http://localhost:7020/health` and the other documented `localhost` addresses still respond

#### Scenario: Loopback binding blocks LAN access

- **WHEN** another machine on the same network requests `http://<host-LAN-IP>:7020/health`
- **THEN** the connection fails
- **AND** the same request from the host through `localhost` succeeds

### Requirement: Credentials flow from the environment with a production startup guard

All credentials including SERVICE_AUTH_TOKEN SHALL come from env via .env. GRAFANA_ADMIN_PASSWORD and SEARXNG_SECRET SHALL use ${VAR:?message} always. Others MAY keep dev defaults outside production. Under production ascend-agent SHALL refuse start while any object store, Postgres, Redis or Qdrant credential unset, blank or weak, naming property not value. application-production.yaml SHALL set each from env no default, ProductionStartupGuard SHALL refuse blank or weak.

#### Scenario: Missing required secret fails compose

- **WHEN** an operator runs `docker compose up` with `GRAFANA_ADMIN_PASSWORD` unset
- **THEN** compose exits with an error naming the variable before any container starts

#### Scenario: The Grafana guard holds with no compose profile set

- **WHEN** an operator runs `docker compose config` with `COMPOSE_PROFILES` empty and `GRAFANA_ADMIN_PASSWORD` unset
- **THEN** compose exits with an error naming `GRAFANA_ADMIN_PASSWORD`

#### Scenario: Production profile rejects an unset credential

- **WHEN** ascend-agent starts with the `production` profile active and `S3_SECRET_KEY` unset
- **THEN** startup fails with an error naming `S3_SECRET_KEY`
- **AND** with real values for every guarded credential the application starts

#### Scenario: Production profile rejects a development default

- **WHEN** ascend-agent starts with the `production` profile active and `S3_SECRET_KEY=password`
- **THEN** startup fails with one ERROR line naming `app.s3.secret-key` and not printing `password`

#### Scenario: Development profile keeps working without variables

- **WHEN** ascend-agent starts without the `production` profile and with none of the credential variables set
- **THEN** it starts with the development defaults

### Requirement: The object store is never public

The gateway SHALL have no object store route, and no committed file SHALL publish it publicly. Agent (`S3_ENDPOINT`, `S3_PUBLIC_ENDPOINT`) and ascend-ocr (`OCR_RESULT_S3_ENDPOINT`, `OCR_RESULT_S3_PUBLIC_ENDPOINT`) addresses SHALL come from env with today local defaults. The guide SHALL require both public endpoints equal the private address in production, since only private-network containers follow presigned links.

#### Scenario: Presigned links point at the private address in production

- **WHEN** a production deployment sets `S3_PUBLIC_ENDPOINT` and `OCR_RESULT_S3_PUBLIC_ENDPOINT` to the private object store address
- **THEN** the agent still reads ascend-ocr results through the presigned link
- **AND** the presigned link does not resolve from outside the VM

### Requirement: Personal-machine artifacts are opt-in

The compose files SHALL contain no personal absolute paths. ascend-audio-scribe volumes SHALL be `${HF_CACHE_ROOT:-hf-cache}:/hf-cache` and `${ASCEND_AUDIO_SCRIBE_MEDIA_ROOT:-ascend-audio-scribe-media}:/audio`, and `MCP_FILE_URI_ROOT` SHALL be `${ASCEND_AUDIO_SCRIBE_FILE_URI_ROOT:-}`, where empty disables `file://`.

#### Scenario: Default deployment cannot read host files

- **WHEN** the stack starts with the three variables unset and a caller sends ascend-audio-scribe a `file:///audio/anything.mp3` URI
- **THEN** the request is rejected because `file://` is disabled
- **AND** `/audio` is an empty named volume

#### Scenario: Owner restores the Desktop workflow

- **WHEN** the owner sets `ASCEND_AUDIO_SCRIBE_MEDIA_ROOT` to a host path and `ASCEND_AUDIO_SCRIBE_FILE_URI_ROOT=/audio` and recreates the service
- **THEN** `file://` transcription of files in that directory works

### Requirement: ascend-web-hunter runs without SYS_ADMIN

`ascend-web-hunter` SHALL NOT declare `cap_add: SYS_ADMIN`. It SHALL use the checked-in seccomp profile `security/chromium-seccomp.json` through `security_opt`, `no-new-privileges:true` and `init: true`, and SHALL keep `shm_size: 2gb`.

#### Scenario: Capability removed while extraction still works

- **WHEN** the rebuilt container is inspected
- **THEN** it has no added capability and the custom seccomp profile applied
- **AND** the Playwright tier renders a JavaScript-heavy page

### Requirement: SSRF allowlists have no loopback default

`ALLOWED_PRIVATE_HOSTS` on ascend-ocr and ascend-audio-scribe SHALL be `${ALLOWED_PRIVATE_HOSTS:-}`. Committed files SHALL NOT default `localhost`, `127.0.0.1` or `host.docker.internal`. Local dev opts in with `ALLOWED_PRIVATE_HOSTS=host.docker.internal` in `.env`, cloud lists only the private object host. Both services SHALL declare `extra_hosts: ["host.docker.internal:host-gateway"]` for Linux. `MCP_ALLOWED_HOSTS` SHALL appear in no committed file or `.env.example`.

#### Scenario: Host fetch is blocked by default

- **WHEN** `ALLOWED_PRIVATE_HOSTS` is unset and a caller submits `http://host.docker.internal:9070/x` to ascend-ocr's `ocr_submit`
- **THEN** the call fails with `UNSAFE_URI`

#### Scenario: Opt-in allows the local object store

- **WHEN** `.env` sets `ALLOWED_PRIVATE_HOSTS=host.docker.internal` and a caller submits a presigned URL on that host
- **THEN** the fetch is allowed and the job proceeds

#### Scenario: The host name resolves in both services on Linux

- **WHEN** the stack runs on Linux Docker Engine
- **THEN** `getent hosts host.docker.internal` inside `ascend-ocr` and inside `ascend-audio-scribe` prints an address

### Requirement: SearXNG stays private with its limiter off

SearXNG SHALL be reachable only on the compose network and on host loopback. Its limiter SHALL stay off, as `infra/searxng/settings.yml` documents, because every caller reaches it from the ascend-web-hunter container address. `infra/searxng/settings.yml` and its byte-identical copy `apps/ascend-web-hunter/deploy-standalone/searxng/settings.yml` SHALL stay identical.

#### Scenario: SearXNG is not reachable from outside

- **WHEN** an external host connects to port 9020 on the VM
- **THEN** the connection fails
- **AND** a search through ascend-web-hunter still returns results

### Requirement: Observability services require login or stay unpublished

Grafana SHALL run with `GF_AUTH_ANONYMOUS_ENABLED=false` and admin credentials from the environment. Prometheus SHALL NOT run with `--web.enable-lifecycle`. Grafana and Prometheus SHALL be loopback-bound. loki, otel-collector, tempo and container-metrics-exporter SHALL publish no port and SHALL run with `no-new-privileges:true`.

#### Scenario: Anonymous Grafana access is refused

- **WHEN** a client requests a Grafana dashboard without logging in
- **THEN** Grafana redirects to its login page
- **AND** the credentials from `.env` log in

#### Scenario: Prometheus cannot be reloaded over HTTP

- **WHEN** a client sends `POST http://localhost:7077/-/reload`
- **THEN** the request is rejected

### Requirement: Compose declares production runtime posture

`compose.yaml` SHALL define its own `x-logging` anchor (json-file, `max-size` from `DOCKER_LOG_MAX_SIZE` default `10m`, `max-file` from `DOCKER_LOG_MAX_FILE` default `3`) and apply it to every service it defines. It SHALL define healthchecks for every service, make ascend-agent wait on ascend-memory, docling-serve, unstructured-api and keycloak with `condition: service_healthy`, set `no-new-privileges:true` on every service, and pin every pulled image by version and digest.

#### Scenario: Agent waits for healthy dependencies

- **WHEN** `docker compose up -d` starts the stack from cold
- **THEN** ascend-agent starts only after ascend-memory, docling-serve, unstructured-api and keycloak report healthy

#### Scenario: Log output is bounded

- **WHEN** any container of the stack is inspected while `DOCKER_LOG_MAX_SIZE` and `DOCKER_LOG_MAX_FILE` are unset
- **THEN** its logging uses the json-file driver with `max-size: 10m` and `max-file: 3`

#### Scenario: No floating image

- **WHEN** a reviewer lists every pulled `image:` line in both compose files
- **THEN** each one carries a version tag and a digest

### Requirement: Only named services mount the Docker socket

ascend-agent SHALL NOT mount the Docker socket. The only services that mount it SHALL be the observability services otel-collector and container-metrics-exporter, read-only. A read-only socket mount SHALL NOT be treated as a restriction, because the Docker API behind it still accepts every call.

#### Scenario: The agent has no socket

- **WHEN** `docker compose config` is read
- **THEN** no service other than otel-collector and container-metrics-exporter mounts `/var/run/docker.sock`
- **AND** ascend-agent mounts it in no form

### Requirement: The deployment guide covers one cloud VM per customer

docs/DEPLOYMENT.md SHALL describe DNS for ASCEND_DOMAIN, TLS via gateway and local CA, .env prep, which stack has the four stores, production checklist, backup plus restore for Postgres, Redis, Qdrant, object store for container and managed. Checklist SHALL require Keycloak issuer and non-default SERVICE_AUTH_TOKEN, and SHALL NOT name removed SECURITY_ENABLED, SECURITY_USERNAME, SECURITY_PASSWORD.

#### Scenario: An operator deploys from the guide alone

- **WHEN** an operator with a fresh VM, a domain and the four data stores follows the guide
- **THEN** the stack serves `https://<domain>` with only 80 and 443 open
- **AND** every checklist item has a command that verifies it

#### Scenario: Backups are documented per store

- **WHEN** a reader opens the backup section
- **THEN** it gives a backup and a restore procedure for each of Postgres, Redis, Qdrant and the object store

#### Scenario: A restore drill brings back a canary record

- **WHEN** on a throwaway server one canary is written to each of Postgres, Redis, Qdrant and the object store, each store is backed up with the guide's command, the canaries are deleted and each store is restored with the guide's command
- **THEN** each canary reads back with its value
- **AND** the agent answers requests afterwards

#### Scenario: The production checklist names the token-based login

- **WHEN** a reader opens the production checklist of `docs/DEPLOYMENT.md`
- **THEN** it requires the Keycloak issuer variable and a non-default `SERVICE_AUTH_TOKEN`, each with a command that verifies it
- **AND** it names none of `SECURITY_ENABLED`, `SECURITY_USERNAME` and `SECURITY_PASSWORD`
