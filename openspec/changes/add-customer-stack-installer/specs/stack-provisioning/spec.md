## ADDED Requirements

### Requirement: The owner decides the providers before any infrastructure code

The installer SHALL NOT contain infrastructure code for a cloud provider, DNS provider or object store product until the owner has chosen them and the choice is recorded in the change's design. Every provider-specific part SHALL live in a module named after the recorded provider.

#### Scenario: No provider code without a recorded decision

- **WHEN** a reviewer opens `deploy/terraform/`
- **THEN** every provider module there matches a provider named in the recorded decisions

### Requirement: Terraform provisions a gateway-only VM

The installer SHALL provide a Terraform configuration that provisions a VM with an NVIDIA GPU, a data disk, DNS records for `ASCEND_DOMAIN` and the Keycloak host name, and a firewall that opens 80 and 443 to everyone and 22 only to an operator address list.

#### Scenario: Only the gateway ports are open

- **WHEN** the configuration is applied and an outside host scans the VM
- **THEN** only 80 and 443 accept connections, plus 22 from an allowed address
- **AND** both DNS names resolve to the VM

### Requirement: Data stores come from a separate prerequisite stack

The installer SHALL provide Postgres, Redis, Qdrant and, when chosen, the S3-compatible object store through `deploy/datastores/compose.yaml` (project `ascend-datastores`) or through managed services named in the recorded decisions. Every data-store port SHALL bind only `127.0.0.1`, and Redis and Qdrant SHALL require credentials. The application stack SHALL keep the main `compose.yaml` free of data stores.

#### Scenario: Data stores are private and reachable by the stack

- **WHEN** the data-store stack and the application stack run on the VM
- **THEN** the agent health endpoint reports Postgres, Redis and Qdrant up
- **AND** no data-store port is reachable from outside the VM

### Requirement: The VM runs released images

The six app `image:` lines in the compose files SHALL be `${ASCEND_IMAGE_REGISTRY:-}ascend-ai-<service>:${<SERVICE>_IMAGE_TAG:-latest}`, so local builds keep today's names. The installer SHALL set the registry to the location `release.yaml` publishes to and pin each tag to a released `v<version>`, and SHALL start those services without building them.

#### Scenario: Local names are unchanged

- **WHEN** a developer runs `docker compose config --images` with the image variables unset
- **THEN** the names equal the local build names used before this change

#### Scenario: The VM pulls a pinned release

- **WHEN** the installer runs with `ASCEND_AGENT_IMAGE_TAG=v<version>`
- **THEN** the running `ascend-agent` container uses `ghcr.io/lukk17/ascend-ai-ascend-agent:v<version>`

### Requirement: Bootstrap generates secrets, takes customer inputs and refuses development defaults

The installer SHALL provide `deploy/bootstrap.sh` and `deploy/bootstrap.ps1` that sort every `.env.example` variable into generated secrets, customer inputs and fixed production values, generate each secret from the system random source, require at least one LLM provider key, and write `.env` with mode 600. The bootstrap SHALL abort without writing when a required value is blank or equals a development default, and SHALL NOT overwrite an existing `.env` unless asked to rotate.

#### Scenario: Complete .env with no development default

- **WHEN** the bootstrap runs with one LLM provider key supplied
- **THEN** every required variable in `.env` is set
- **AND** no value equals `admin`, `password` or `local`

#### Scenario: Missing provider key aborts

- **WHEN** the bootstrap runs with no LLM provider key
- **THEN** it aborts, names the missing input and writes no `.env`

#### Scenario: Every variable is classified

- **WHEN** a new variable is added to `.env.example` without being added to a bootstrap list
- **THEN** the bootstrap test suite fails naming that variable

### Requirement: The model cache is filled before first use

The installer SHALL check that the NVIDIA container runtime exists and SHALL fill the `hf-cache` volume with the configured Whisper model before starting the stack.

#### Scenario: Missing GPU runtime stops the install

- **WHEN** the host has no NVIDIA container runtime
- **THEN** the installer stops before starting the stack and names the missing runtime

### Requirement: First tenant provisioning leaves a usable admin

After the stack is healthy, the installer SHALL confirm the imported Keycloak realm exists and SHALL create the customer's first tenant and its first `ADMIN` user through the tenant-administration API as `PLATFORM_ADMIN`. The initial password SHALL be shown once to the operator and never written to a log file.

#### Scenario: Fresh stack has a usable admin

- **WHEN** the installer completes provisioning
- **THEN** the first tenant exists and its `ADMIN` user can get a token from Keycloak

### Requirement: The smoke test is a hard install gate

The installer SHALL run a smoke test that checks the gateway certificate, the agent health through the gateway, the Keycloak discovery document on its own host name, a token for the seeded admin, one authenticated prompt request and an external port scan. The installer SHALL exit non-zero and name the first failed check when any check fails.

#### Scenario: Broken stack fails the install

- **WHEN** the smoke test runs while ascend-agent is stopped
- **THEN** the installer exits non-zero naming the health check
- **AND** does not report the install as successful

### Requirement: The installer drives the single main compose file

The installer SHALL start the application stack only with `docker compose` against the main `compose.yaml` and no `-f` flag. The only other compose project on the VM SHALL be `ascend-datastores`.

#### Scenario: No second application project

- **WHEN** the install has finished
- **THEN** `docker compose ls` lists only `ascend-ai` and `ascend-datastores`
