## ADDED Requirements

### Requirement: Every container that reaches the Docker host declares the host gateway mapping

Host access is host.docker.internal with the mapping (20.10+). Compose naming it SHALL declare extra_hosts, list/map. Documented docker run SHALL carry --add-host=host.docker.internal:host-gateway. Naming IDE configs SHALL carry it. Container calls SHALL use service names. Host calls SHALL use 127.0.0.1 and a port. localhost SHALL mean only that container. Handed addresses SHALL never be localhost for the host. CI jobs SHALL start host services. IDE secrets SHALL use --env-file from .env only.

#### Scenario: ascend-audio-scribe declares the mapping

- **WHEN** a reviewer runs `docker compose config` from the repository root
- **THEN** the `ascend-audio-scribe` service shows `host.docker.internal:host-gateway` under `extra_hosts`

#### Scenario: Documented docker run lines carry the option

- **WHEN** a reviewer lists the lines of the developer documents that hold both `docker run` and `host.docker.internal`
- **THEN** each of them also holds `--add-host=host.docker.internal:host-gateway`

#### Scenario: IDE run configurations carry the option

- **WHEN** a reviewer lists the `*.run.xml` files that name `host.docker.internal`
- **THEN** the `commandLineOptions` value of each holds `--add-host=host.docker.internal:host-gateway`

#### Scenario: A host service reached through a loopback-only port is not documented as reachable

- **WHEN** a document or an IDE run configuration tells a container to call a host port that is published on `127.0.0.1` only
- **THEN** it instead joins the container to the stack network and calls the service by its name

#### Scenario: The ascend-audio-scribe Bruno folder hands the container a reachable address

- **WHEN** a reviewer reads `docs/api/request/AscendAI/mcp/audio-scribe/folder.yml`
- **THEN** `audio_uri_docker` is `http://host.docker.internal:9070/e2e-fixtures/meeting-clip.wav`
- **AND** the folder holds no variable `audio_uri`

#### Scenario: The ascend-ocr e2e job starts the object store its specs read

- **WHEN** a reviewer reads the `ascend-ocr` job of `.github/workflows/e2e.yaml`
- **THEN** the job starts an object store published on port 9070 of the runner and seeds the spec 6 fixture before ascend-ocr starts
- **AND** the object store image is pinned by tag and digest

#### Scenario: The ascend-ocr IDE run configuration reads its keys from .env

- **WHEN** a reviewer reads `apps/ascend-ocr/.run/ascend-ocr Run.run.xml`
- **THEN** it sets `OCR_RESULT_S3_ENDPOINT` to `http://host.docker.internal:9070` and `OCR_RESULT_S3_PUBLIC_ENDPOINT` to `http://localhost:9070`
- **AND** its `commandLineOptions` hold `--env-file` with the repository `.env`
- **AND** it holds no value for `OCR_RESULT_S3_ACCESS_KEY` or `OCR_RESULT_S3_SECRET_KEY`

### Requirement: The development stack starts on Docker Engine for Linux

Compose files SHALL name no Windows path. Volumes of ascend-audio-scribe SHALL be ${HF_CACHE_ROOT:-hf-cache}:/hf-cache and ${ASCEND_AUDIO_SCRIBE_MEDIA_ROOT:-ascend-audio-scribe-media}:/audio (unset is named volume). Socket readers SHALL use group_add ${DOCKER_SOCKET_GID:-0}. .env.example SHALL NOT list the three. Each SHALL have its default row in docs/CONFIGURATION.md. docs/DEPLOYMENT.md and AGENTS.md SHALL state host rules and Linux needs: 20.10+, bridge/all-address, firewall, NVIDIA, GID.

#### Scenario: No Windows path is left

- **WHEN** a reviewer reads the `volumes` of every service in `compose.yaml`, `compose.ascend-web-hunter.yaml` and `apps/ascend-web-hunter/deploy-standalone/compose.yaml`
- **THEN** no source starts with a drive letter such as `C:` or `D:`
- **AND** `grep -nE 'Desktop|D:/Development' compose.yaml` prints nothing

#### Scenario: Unset media variables give named volumes

- **WHEN** `HF_CACHE_ROOT` and `ASCEND_AUDIO_SCRIBE_MEDIA_ROOT` are unset and a reviewer runs `docker compose config`
- **THEN** the `ascend-audio-scribe` service mounts the named volumes `hf-cache` and `ascend-audio-scribe-media`

#### Scenario: The socket group defaults to Docker Desktop's group

- **WHEN** `DOCKER_SOCKET_GID` is unset and a reviewer runs `docker compose config`
- **THEN** `container-metrics-exporter` shows group `0` under `group_add`

#### Scenario: The Linux prerequisites are documented

- **WHEN** a developer reads the part "Reaching the host from a container" of `docs/DEPLOYMENT.md`
- **THEN** it names Docker Engine 20.10 or newer, the listening address of each host prerequisite, the NVIDIA Container Toolkit and how to read `DOCKER_SOCKET_GID` with `stat -c %g /var/run/docker.sock`

#### Scenario: The three settings have rows and no .env.example line

- **WHEN** a reviewer reads `.env.example` and `docs/CONFIGURATION.md`
- **THEN** `.env.example` names none of `HF_CACHE_ROOT`, `ASCEND_AUDIO_SCRIBE_MEDIA_ROOT` and `DOCKER_SOCKET_GID`
- **AND** `docs/CONFIGURATION.md` holds one row for each, with the default of its compose line and `fix-linux-docker-host-access` in Added by

### Requirement: Every setting of every service has one row in one configuration reference

docs/CONFIGURATION.md SHALL list every setting of both compose files plus Compose variables in tables. Each of the four services SHALL have one linked section with no repeated rows, each own file SHALL list every variable it reads or sets. Each setting SHALL have one row in one file. Old SHALL show existing, new their change. Defaults SHALL come from source, secrets SHALL show none. The file SHALL require same-commit updates and SHALL link from docs/DEPLOYMENT.md and root README.md.

#### Scenario: A service without its own reference has its rows in the root file

- **WHEN** a reviewer compares the variables that `docker compose config` shows for `ascend-audio-scribe` with `docs/CONFIGURATION.md`
- **THEN** each variable has exactly one row in the `ascend-audio-scribe` section, with five cells

#### Scenario: A service with its own reference is linked, not repeated

- **WHEN** a reviewer reads the ascend-ocr section of `docs/CONFIGURATION.md`
- **THEN** it holds a link to `apps/ascend-ocr/docs/CONFIGURATION.md` and no table
- **AND** every variable that ascend-ocr reads or its compose service sets has a row in `apps/ascend-ocr/docs/CONFIGURATION.md`

#### Scenario: The reference is reachable from the documentation map

- **WHEN** a developer reads the "Documentation" table of the root `README.md` or the "See also" section of `docs/DEPLOYMENT.md`
- **THEN** each links `docs/CONFIGURATION.md`
