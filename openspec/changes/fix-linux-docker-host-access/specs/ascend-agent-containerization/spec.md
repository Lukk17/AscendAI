## ADDED Requirements

### Requirement: Every container that reaches the Docker host declares the host gateway mapping

A container reaches a service on the Docker host only through the name `host.docker.internal`, and only together with the mapping `host.docker.internal:host-gateway`, which Docker Engine 20.10 or newer supports. Every service of every compose file in the repository whose definition names `host.docker.internal` (in its environment, command, configuration values or allow lists) SHALL declare `extra_hosts` with `host.docker.internal:host-gateway`, in the list form or the map form. Every `docker run` command in the developer documents that names `host.docker.internal` SHALL carry `--add-host=host.docker.internal:host-gateway`. Every IDE Docker run configuration that names `host.docker.internal` SHALL carry the same option. Container to container calls SHALL use the container or service name on the shared network, and host to container calls SHALL use `127.0.0.1` and a published port. Inside a container, `localhost` and `127.0.0.1` SHALL mean only that container itself, so an address handed to a container (a Bruno variable, an IDE run configuration value, a CI job) SHALL never be `localhost` when it means the host. A CI job whose specs make a container call a host service SHALL start that service. A key or secret that an IDE Docker run configuration needs SHALL come from the repository `.env` through Docker's `--env-file` option, never as a value in the run configuration and never from a variable exported in a shell (owner answer 85.1 of 2026-10-08).

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

The compose files SHALL name no host path that exists only on Windows. The `ascend-audio-scribe` volumes SHALL be `${HF_CACHE_ROOT:-hf-cache}:/hf-cache` and `${ASCEND_AUDIO_SCRIBE_MEDIA_ROOT:-ascend-audio-scribe-media}:/audio`, so an unset variable gives a named volume and a set variable gives a bind mount of that host path. A non-root container that reads the Docker socket SHALL join the socket's group through `group_add` with `${DOCKER_SOCKET_GID:-0}`, because Docker Engine for Linux gives the socket to the group `docker` and Docker Desktop gives it to `root`. `.env.example` SHALL NOT list `HF_CACHE_ROOT`, `ASCEND_AUDIO_SCRIBE_MEDIA_ROOT` or `DOCKER_SOCKET_GID`, because each has a default (owner rule 98 of 2026-10-08). Each of the three SHALL have its row in `docs/CONFIGURATION.md` with its default. `docs/DEPLOYMENT.md` and the root `AGENTS.md` SHALL state the host access rules and the Linux host prerequisites: Docker Engine 20.10 or newer, host services reached through `host.docker.internal` listen on the Docker bridge address or on all addresses and are not blocked by a host firewall, the NVIDIA Container Toolkit for the GPU reservation of ascend-audio-scribe, and how to read `DOCKER_SOCKET_GID` on the host.

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

The file `docs/CONFIGURATION.md` at the repository root SHALL list every setting of every service and container of `compose.yaml` and `compose.ascend-web-hunter.yaml`, and the variables Compose itself reads, in tables with the columns Service, Variable, Default, What it does and Added by (owner rule 98 of 2026-10-08). A service that has its own reference (`apps/ascend-agent/docs/CONFIGURATION.md`, `apps/ascend-memory/docs/CONFIGURATION.md`, `apps/ascend-ocr/docs/CONFIGURATION.md`, `apps/ascend-web-hunter/docs/configuration.md`) SHALL get one section in `docs/CONFIGURATION.md` that links that reference and repeats none of its rows, and its own reference SHALL list every variable the service reads or its compose service sets. Every setting SHALL have exactly one row in exactly one of these files. A setting that existed before owner rule 98 SHALL show `existing` in Added by, and a later one the name of the change that added it (in a per-service reference, the description ends with "Added by `<change>`."). A default SHALL be the value the source holds (the code default, the `:-` part of the compose line or the fixed compose value), and a secret SHALL show no default. `docs/CONFIGURATION.md` SHALL state the rule that every later change adds or changes the row of a setting in the same commit as the setting, and SHALL be linked from `docs/DEPLOYMENT.md` and from the documentation map of the root `README.md`.

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
