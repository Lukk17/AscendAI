## MODIFIED Requirements

### Requirement: Credentials flow from the environment with a production startup guard

Every credential the stack consumes SHALL come from environment variables backed by `.env`: Postgres user and password, Redis password, Qdrant API key, object store access and secret key, ascend-ocr result store keys, Grafana admin user and password, the SearXNG secret, the service token `SERVICE_AUTH_TOKEN` of `add-keycloak-login`, the sandbox runner token `SANDBOX_RUNNER_TOKEN`, and, while the module `coding` is active, `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY` (the PEM, base64 encoded) and `OPENCODE_API_KEY` (the personal deployment only). `GRAFANA_ADMIN_PASSWORD`, `SEARXNG_SECRET` and `SANDBOX_RUNNER_TOKEN` SHALL use compose's `${VAR:?message}` form, and every deployment SHALL set them, because Grafana and the sandbox runner are always-on services and compose checks the SearXNG guard in every deployment. Other credentials MAY keep development defaults outside the `production` Spring profile. Under the `production` Spring profile ascend-agent SHALL refuse to start while any object store, Postgres, Redis or Qdrant credential is unset, blank or equal to a known weak value, among them every development default, and the refusal SHALL name the property without printing its value. `application-production.yaml` SHALL set each of these credentials from its environment variable with no default, so an unset variable stops start-up with Spring's own error naming it, and the one production startup guard `ProductionStartupGuard` of `add-keycloak-login` SHALL refuse a blank or weak value. The check that the GitHub App key is not empty SHALL be the module secret check of `add-deployment-modules`, not a rule of the production startup guard.

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

#### Scenario: Coding module without the GitHub App key

- **WHEN** ascend-agent starts with the module `coding` active and `GITHUB_APP_PRIVATE_KEY` empty
- **THEN** the module secret check of `add-deployment-modules` refuses startup and names `GITHUB_APP_PRIVATE_KEY` without a value

### Requirement: The deployment guide covers one cloud VM per customer

`docs/DEPLOYMENT.md` SHALL describe: DNS for `ASCEND_DOMAIN`, TLS through the gateway and the local internal CA, `.env` preparation, which stack provides the four data stores, the production checklist (`production` Spring profile, no development credentials, public endpoint variables set to the private object store address, external port scan), and backup and restore steps for Postgres, Redis, Qdrant and the object store for container and managed-service topologies. The production checklist SHALL require the Keycloak issuer variable to be set and `SERVICE_AUTH_TOKEN` to hold a non-default value, and SHALL NOT name the removed `SECURITY_ENABLED`, `SECURITY_USERNAME` and `SECURITY_PASSWORD` variables. The guide SHALL also describe, as steps of every VM setup, the gVisor (`runsc`) install from its apt repository, `sudo runsc install`, the `docker info` check, a `hello-world` run under `runsc` and the measured `DOCKER_SOCKET_GID`, with the rule that `runsc` is never the engine's default runtime. For the module `coding`, the guide SHALL also describe the coding project area on a separate partition mounted at `/srv/ascend/coding` with `setup-coding-area.sh` and `CODING_AREA_HOST_PATH`, the GitHub App setup and `OPENCODE_API_KEY` for the personal deployment only.

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

#### Scenario: The coding host step is documented

- **WHEN** a reader follows the coding section of the guide on a fresh Linux VM
- **THEN** the coding project area is mounted at `/srv/ascend/coding`, `setup-coding-area.sh` ran, and `.env` names `CODING_AREA_HOST_PATH`, `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY` and `OPENCODE_API_KEY`
