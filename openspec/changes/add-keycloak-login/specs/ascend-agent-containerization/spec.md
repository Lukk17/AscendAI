## MODIFIED Requirements

### Requirement: A `.env.example` documents the secrets compose consumes

The repository SHALL ship a committed `.env.example` file at the monorepo root, next to `compose.yaml`. The file SHALL list every secret that `compose.yaml` and `compose.ascend-web-hunter.yaml` reference, among them the service token `SERVICE_AUTH_TOKEN`, the directory client secret `KEYCLOAK_DIRECTORY_CLIENT_SECRET` and the e2e user password `E2E_USER_PASSWORD` of `add-keycloak-login`, and every other variable they reference that has no default. A variable that has a default, such as the issuer variable `KEYCLOAK_ISSUER_URI`, SHALL get no new line in `.env.example` and SHALL have its row in the configuration reference instead (`docs/CONFIGURATION.md` or the service's own reference, owner rule 98 of 2026-10-08). Lines that `.env.example` already holds stay. Secret-valued variables SHALL have empty values. Non-secret variables MAY show their safe default. Every variable SHALL carry a one-line comment above it naming its purpose and consuming service and, where production requires it, saying so. The actual `.env` file SHALL be excluded by `.gitignore` so it is never committed. The old name `MCP_ALLOWED_HOSTS` SHALL NOT appear in `.env.example` or in either compose file, because it was renamed to `ALLOWED_PRIVATE_HOSTS` (owner answer 68.2 of 2026-10-04) and every Python service refuses to start while it is set (owner answer 72.3 of 2026-10-06). No compose file and no line of `.env.example` SHALL name the removed login variables `SECURITY_ENABLED`, `SECURITY_USERNAME` and `SECURITY_PASSWORD`.

#### Scenario: `.env.example` is committed and complete

- **WHEN** a reviewer opens `.env.example`
- **THEN** every `${KEY}` reference present in `compose.yaml` or `compose.ascend-web-hunter.yaml` appears in `.env.example` on its own line or has its row in the configuration reference
- **AND** every secret appears in `.env.example` with an empty value
- **AND** a one-line comment above each variable identifies the consuming service

#### Scenario: The service token is flagged for production

- **WHEN** a reviewer reads the entry for `SERVICE_AUTH_TOKEN`
- **THEN** its comment says production deployments must set it to a non-default value

#### Scenario: `.env` is gitignored

- **WHEN** a developer creates a local `.env` and runs `git status`
- **THEN** `.env` does NOT appear in the list of tracked or untracked files (it is ignored by `.gitignore`)

#### Scenario: The old allow list name is gone

- **WHEN** a reviewer searches `.env.example`, `compose.yaml` and `compose.ascend-web-hunter.yaml` for `MCP_ALLOWED_HOSTS`
- **THEN** none of them is found
- **AND** the `ascend-ocr` and `ascend-audio-scribe` services set `ALLOWED_PRIVATE_HOSTS` instead

#### Scenario: The removed login variables are gone

- **WHEN** a reviewer searches `.env.example` and `compose.yaml` for `SECURITY_ENABLED`, `SECURITY_USERNAME` and `SECURITY_PASSWORD`
- **THEN** none of them is found
