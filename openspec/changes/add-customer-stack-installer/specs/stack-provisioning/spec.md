## ADDED Requirements

### Requirement: Terraform provisions a gateway-only VM with a provider variable

The installer SHALL provide a Terraform configuration that provisions a cloud VM, its DNS record for `ASCEND_DOMAIN`, a firewall opening only ports 80 and 443, and the data-store volumes/backup. The target cloud provider SHALL be a variable/module boundary so a different provider is additive, not a rewrite.

#### Scenario: Only the gateway ports are open

- **WHEN** the Terraform configuration is applied for the first target provider
- **THEN** the provisioned VM accepts inbound traffic on 80 and 443 only
- **AND** direct connections to any internal service port from outside fail

### Requirement: Bootstrap generates every secret and refuses dev-defaults

The installer SHALL provide a cross-platform bootstrap (Bash and PowerShell) that reads the `.env.example` variable set, generates strong values for every secret, and assembles a complete `.env`. The bootstrap SHALL abort with a clear message if any required secret is unset, and SHALL never write a dev-default credential into a production `.env`.

#### Scenario: Complete .env with no dev-defaults

- **WHEN** the bootstrap runs against a fresh target
- **THEN** it writes a `.env` in which every required variable is set to a generated value
- **AND** no dev-default credential (e.g. `admin`/`password`, `postgres`/`local`) appears

#### Scenario: Missing required secret aborts

- **WHEN** a required secret cannot be generated or is left blank
- **THEN** the bootstrap aborts and names the missing variable, writing no partial production `.env`

### Requirement: Realm import and first tenant provisioning leave a usable admin

After the stack is up, the installer SHALL import the Keycloak realm export and create the customer's first tenant and its initial `ADMIN` user through the tenant-administration API, so the delivered stack has a working admin account rather than an empty realm.

#### Scenario: Fresh stack has a usable admin

- **WHEN** the installer completes provisioning
- **THEN** the customer's first tenant exists and its initial `ADMIN` user can acquire a token and sign in

### Requirement: Readiness smoke test is a hard install gate

The installer SHALL run a smoke test verifying gateway TLS, ascend-ai-agent health behind the gateway, token acquisition for the seeded admin, and one authenticated round-trip. The installer SHALL fail the install (non-zero exit, naming the failed check) if any check does not pass, so a broken stack is never handed over as complete.

#### Scenario: Broken stack fails the install

- **WHEN** the smoke test runs while ascend-ai-agent is unhealthy behind the gateway
- **THEN** the installer exits non-zero and names the failed health check
- **AND** does not report the install as successful

### Requirement: Installer drives the single main compose file

The installer SHALL bring the stack up by running `docker compose` against the main `docker-compose.yaml` with no `-f` flags, so an installed stack is identical to a hand-brought-up one.

#### Scenario: No secondary compose project

- **WHEN** the installer brings the stack up
- **THEN** it uses the main `docker-compose.yaml` as the only compose entry point and no `-f` override
