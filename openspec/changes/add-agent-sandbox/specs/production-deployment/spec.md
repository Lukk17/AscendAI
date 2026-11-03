## MODIFIED Requirements

### Requirement: Internal service ports bind to loopback by default

Every host-port publication in `compose.yaml` and `compose.ascend-web-hunter.yaml` except the gateway's SHALL use the form `"${EXPOSE_BIND:-127.0.0.1}:${<SERVICE>_HOST_PORT:-<host-port>}:<container-port>"`, where `<SERVICE>_HOST_PORT` is the host port setting of that service with today's port as its default (owner answer 100.6 of 2026-10-09). The services loki, otel-collector, tempo, container-metrics-exporter, the bundled redis and `ascend-sandbox-runner` SHALL publish no host port. `compose.yaml` SHALL stay the single compose entry point.

#### Scenario: Fresh clone binds services to loopback

- **WHEN** a developer prepares `.env` from `.env.example` and runs `docker compose up -d --build`
- **THEN** `docker inspect` shows every published port except the gateway's bound to `127.0.0.1`
- **AND** `http://localhost:7020/health` and the other documented `localhost` addresses still respond

#### Scenario: Loopback binding blocks LAN access

- **WHEN** another machine on the same network requests `http://<host-LAN-IP>:7020/health`
- **THEN** the connection fails
- **AND** the same request from the host through `localhost` succeeds

### Requirement: Credentials flow from the environment with a production startup guard

Every credential the stack consumes SHALL come from environment variables backed by `.env`: Postgres user and password, Redis password, Qdrant API key, object store access and secret key, ascend-ocr result store keys, Grafana admin user and password, the SearXNG secret, the service token `SERVICE_AUTH_TOKEN` of `add-keycloak-login`, and the sandbox runner token `SANDBOX_RUNNER_TOKEN`. `GRAFANA_ADMIN_PASSWORD`, `SEARXNG_SECRET` and `SANDBOX_RUNNER_TOKEN` SHALL use compose's `${VAR:?message}` form, and every deployment SHALL set them, because Grafana and the sandbox runner are always-on services and compose checks the SearXNG guard in every deployment. Other credentials MAY keep development defaults outside the `production` Spring profile. Under the `production` Spring profile ascend-agent SHALL refuse to start while any object store, Postgres, Redis or Qdrant credential is unset, blank or equal to a known weak value, among them every development default, and the refusal SHALL name the property without printing its value. `application-production.yaml` SHALL set each of these credentials from its environment variable with no default, so an unset variable stops start-up with Spring's own error naming it, and the one production startup guard `ProductionStartupGuard` of `add-keycloak-login` SHALL refuse a blank or weak value.

#### Scenario: Missing required secret fails compose

- **WHEN** an operator runs `docker compose up` with `GRAFANA_ADMIN_PASSWORD` unset
- **THEN** compose exits with an error naming the variable before any container starts

#### Scenario: The Grafana guard holds with no compose profile set

- **WHEN** an operator runs `docker compose config` with `COMPOSE_PROFILES` empty and `GRAFANA_ADMIN_PASSWORD` unset
- **THEN** compose exits with an error naming `GRAFANA_ADMIN_PASSWORD`

#### Scenario: The sandbox runner token guard holds in every deployment

- **WHEN** an operator runs `docker compose config` with `COMPOSE_PROFILES` empty and `SANDBOX_RUNNER_TOKEN` unset
- **THEN** compose exits with an error naming `SANDBOX_RUNNER_TOKEN`

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

### Requirement: Only named services mount the Docker socket

ascend-agent SHALL NOT mount the Docker socket. The only services that mount it SHALL be the observability services otel-collector and container-metrics-exporter, read-only, and `ascend-sandbox-runner`, which is the one service allowed to mount it for sandbox work. `ascend-sandbox-runner` SHALL follow the other rules of this capability: `no-new-privileges:true`, no published port, its secret from `.env`, and the logging anchor. A read-only socket mount SHALL NOT be treated as a restriction, because the Docker API behind it still accepts every call.

#### Scenario: The agent has no socket

- **WHEN** `docker compose config` is read
- **THEN** no service other than otel-collector, container-metrics-exporter and `ascend-sandbox-runner` mounts `/var/run/docker.sock`
- **AND** the output lists `ascend-sandbox-runner`
- **AND** ascend-agent mounts it in no form

### Requirement: The deployment guide covers one cloud VM per customer

`docs/DEPLOYMENT.md` SHALL describe: DNS for `ASCEND_DOMAIN`, TLS through the gateway and the local internal CA, `.env` preparation, which stack provides the four data stores, the production checklist (`production` Spring profile, no development credentials, public endpoint variables set to the private object store address, external port scan), and backup and restore steps for Postgres, Redis, Qdrant and the object store for container and managed-service topologies. The production checklist SHALL require the Keycloak issuer variable to be set and `SERVICE_AUTH_TOKEN` to hold a non-default value, and SHALL NOT name the removed `SECURITY_ENABLED`, `SECURITY_USERNAME` and `SECURITY_PASSWORD` variables. The guide SHALL also describe, as steps of every VM setup, the gVisor (`runsc`) install from its apt repository, `sudo runsc install`, the `docker info` check, a `hello-world` run under `runsc` and the measured `DOCKER_SOCKET_GID`, with the rule that `runsc` is never the engine's default runtime.

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

#### Scenario: The sandbox host steps keep runc the default runtime

- **WHEN** an operator follows the gVisor steps of the guide on a Linux host
- **THEN** `docker info` lists `runsc` as a runtime
- **AND** the default runtime is still `runc`
