## MODIFIED Requirements

### Requirement: Personal-machine artifacts are opt-in

The compose files SHALL contain no personal absolute paths. ascend-audio-scribe volumes SHALL be `${HF_CACHE_ROOT:-hf-cache}:/hf-cache` and `${ASCEND_AUDIO_SCRIBE_MEDIA_ROOT:-ascend-audio-scribe-media}:/audio`, and `MCP_FILE_URI_ROOT` SHALL be `${ASCEND_AUDIO_SCRIBE_FILE_URI_ROOT:-}`, where empty disables `file://`. `ngrok-ascend-web-hunter` SHALL sit behind the `captcha-intervention` compose profile, which the module catalog lists as a companion of the module `web-search`.

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

### Requirement: Compose declares production runtime posture

`compose.yaml` SHALL define its own `x-logging` anchor (json-file, `max-size` from `DOCKER_LOG_MAX_SIZE` with the default `10m`, `max-file` from `DOCKER_LOG_MAX_FILE` with the default `3`, owner rule 98 of 2026-10-08) and apply it to every service it defines, because anchors do not cross `include:`. It SHALL define healthchecks for every service it defines, SHALL make ascend-agent wait on ascend-memory, docling-serve, unstructured-api and keycloak with `condition: service_healthy`, SHALL set `no-new-privileges:true` on every service, SHALL use `required: false` on every `depends_on` entry for a service under a module profile, and SHALL pin every pulled image by version and digest.

#### Scenario: Agent waits for healthy dependencies

- **WHEN** `docker compose up -d` starts the stack from cold
- **THEN** ascend-agent starts only after ascend-memory, docling-serve, unstructured-api and keycloak report healthy

#### Scenario: Log output is bounded

- **WHEN** any container of the stack is inspected while `DOCKER_LOG_MAX_SIZE` and `DOCKER_LOG_MAX_FILE` are unset
- **THEN** its logging uses the json-file driver with `max-size: 10m` and `max-file: 3`

#### Scenario: No floating image

- **WHEN** a reviewer lists every pulled `image:` line in both compose files
- **THEN** each one carries a version tag and a digest

#### Scenario: A module service the agent does not need is skipped

- **WHEN** `docker compose config` is run with `COMPOSE_PROFILES` empty
- **THEN** it succeeds although services under module profiles are off
