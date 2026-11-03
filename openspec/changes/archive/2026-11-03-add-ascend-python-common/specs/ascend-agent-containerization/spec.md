## MODIFIED Requirements

### Requirement: A `.env.example` documents the secrets compose consumes

The repository SHALL ship a committed `.env.example` file at the monorepo root, next to `compose.yaml`. The file SHALL list every secret that `compose.yaml` and `compose.ascend-web-hunter.yaml` reference, with an empty value, and every other variable they reference that has no default. A variable that has a default SHALL get no new line in `.env.example` and SHALL have its row in the configuration reference instead (`docs/CONFIGURATION.md` or the service's own reference, owner rule 98 of 2026-10-08), except a new variable of the scrapper stack, which also follows that stack's sync rule. Lines that `.env.example` already holds stay. The file SHALL include a one-line comment above each variable explaining its purpose and which service consumes it. The actual `.env` file SHALL be excluded by `.gitignore` so it is never committed. The old name `MCP_ALLOWED_HOSTS` SHALL NOT appear in `.env.example` or in either compose file, because it was renamed to `ALLOWED_PRIVATE_HOSTS` (owner answer 68.2 of 2026-10-04) and every Python service refuses to start while it is set (owner answer 72.3 of 2026-10-06).

#### Scenario: `.env.example` is committed and complete

- **WHEN** a reviewer opens `.env.example`
- **THEN** every `${KEY}` reference present in `compose.yaml` or `compose.ascend-web-hunter.yaml` appears in `.env.example` on its own line or has its row in the configuration reference
- **AND** every secret appears in `.env.example` with an empty value (no leaked secret)
- **AND** a one-line comment above each variable identifies the consuming service

#### Scenario: `.env` is gitignored

- **WHEN** a developer creates a local `.env` and runs `git status`
- **THEN** `.env` does NOT appear in the list of tracked or untracked files (it is ignored by `.gitignore`)

#### Scenario: The old allow list name is gone

- **WHEN** a reviewer searches `.env.example`, `compose.yaml` and `compose.ascend-web-hunter.yaml` for `MCP_ALLOWED_HOSTS`
- **THEN** none of them is found
- **AND** the `ascend-ocr` and `ascend-audio-scribe` services set `ALLOWED_PRIVATE_HOSTS` instead
