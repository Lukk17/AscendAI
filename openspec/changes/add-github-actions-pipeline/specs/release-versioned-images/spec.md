## ADDED Requirements

### Requirement: Tag-triggered multi-arch image build for every service

`release.yml` SHALL trigger on Git tags matching `v*.*.*` and SHALL build a multi-arch (`linux/amd64` and `linux/arm64`) Docker image for every service in the monorepo (`AscendAgent`, `WeatherMCP`, `AudioScribe`, `AscendWebSearch`, `AscendMemory`, `PaddleOCR`). Each image SHALL be pushed to Docker Hub at `lukk17/<service-name>:<version>` where `<version>` is the tag with the leading `v` stripped.

#### Scenario: Tag push produces six images

- **WHEN** a maintainer pushes the tag `v1.2.3`
- **THEN** the workflow extracts `version=1.2.3`
- **AND** six images are built and pushed: `lukk17/ascend-agent:1.2.3`, `lukk17/weather-mcp:1.2.3`, `lukk17/audio-scribe:1.2.3`, `lukk17/ascend-web-search:1.2.3`, `lukk17/ascend-memory:1.2.3`, `lukk17/paddle-ocr:1.2.3`
- **AND** each image is multi-arch with manifests for both `linux/amd64` and `linux/arm64`

#### Scenario: One service build failing does not abort the rest

- **WHEN** the matrix entry for `ascend-memory` fails (e.g., `pip install` times out) during a tag-triggered run
- **THEN** because `strategy.fail-fast: false` is set, the other five services still build and push
- **AND** the workflow's overall conclusion is `failure`
- **AND** re-running the workflow on the same tag re-pushes the missing image without disturbing the five already-published images

### Requirement: Version sync via build-time override, not by committing

The workflow SHALL pass the version into each service's build as a build-time property and SHALL NOT commit any change back to the repository's `build.gradle.kts` or `pyproject.toml`. Java services SHALL receive the version via `-Pversion=<version>` (Gradle property override). Python services SHALL receive it via `--build-arg BUILD_VERSION=<version>` consumed by the `Dockerfile` (e.g., as a `LABEL org.opencontainers.image.version` and optionally written to a `VERSION` file inside the image).

#### Scenario: Java service version override

- **WHEN** `release.yml` runs against tag `v1.2.3` and builds the `ascend-agent` image
- **THEN** the build invokes Gradle with `-Pversion=1.2.3` (either directly or via a `GRADLE_ARGS` build-arg threaded into the Dockerfile)
- **AND** the resulting JAR's `Implementation-Version` manifest entry equals `1.2.3`
- **AND** `AscendAgent/build.gradle.kts` on disk in the repo is unchanged after the workflow finishes

#### Scenario: Python service version label

- **WHEN** `release.yml` runs against tag `v1.2.3` and builds the `audio-scribe` image
- **THEN** `docker buildx build --build-arg BUILD_VERSION=1.2.3 ...` is invoked
- **AND** the resulting image carries `LABEL org.opencontainers.image.version=1.2.3`
- **AND** `AudioScribe/pyproject.toml` on disk in the repo is unchanged after the workflow finishes

### Requirement: `:latest` tag only for stable semver

The workflow SHALL tag an image as `lukk17/<service>:latest` if and only if the Git tag matches the strict stable semver pattern `^v[0-9]+\.[0-9]+\.[0-9]+$`. Pre-release tags (`v1.2.3-rc.1`, `v1.2.3-beta`, `v1.2.3-alpha.2`) SHALL NOT update the `:latest` tag.

#### Scenario: Stable tag updates :latest

- **WHEN** the maintainer pushes `v1.2.3`
- **THEN** the regex `^[0-9]+\.[0-9]+\.[0-9]+$` matches `1.2.3` and the `is_stable` output is `true`
- **AND** every pushed image carries both `lukk17/<service>:1.2.3` and `lukk17/<service>:latest`

#### Scenario: Release-candidate tag does not touch :latest

- **WHEN** the maintainer pushes `v1.2.3-rc.1`
- **THEN** `is_stable` is `false`
- **AND** every pushed image carries only `lukk17/<service>:1.2.3-rc.1`
- **AND** the existing `lukk17/<service>:latest` on Docker Hub is unchanged

### Requirement: Docker Hub authentication via repository secrets

The workflow SHALL log in to Docker Hub using `docker/login-action@v3` with credentials sourced from repository secrets `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`. The token SHALL be a Docker Hub access token (not a password) with read+write scope on the `lukk17/*` namespace.

#### Scenario: Login succeeds

- **WHEN** the workflow runs against any tag and the secrets are configured
- **THEN** `docker/login-action@v3` succeeds before any `docker buildx build --push` step runs
- **AND** the credentials never appear in plain text in the workflow log

#### Scenario: Missing token fails fast with a clear message

- **WHEN** the maintainer pushes a tag but `DOCKERHUB_TOKEN` is not configured
- **THEN** `docker/login-action@v3` fails with the action's standard "no token provided" error
- **AND** no `docker buildx build --push` step runs
- **AND** the workflow conclusion is `failure` with the failed step pointing to the login action

### Requirement: GitHub Release with auto-generated notes

After all matrix images push successfully, the workflow SHALL create a GitHub Release at the same tag using `softprops/action-gh-release@v2` with `generate_release_notes: true` so that the release body is populated from PR titles and contributors since the previous tag.

#### Scenario: Release notes summarize PRs since previous tag

- **WHEN** the previous release tag was `v1.2.2` and three PRs (`#101`, `#102`, `#103`) merged between then and `v1.2.3`
- **THEN** pushing `v1.2.3` and completing all six matrix builds creates a GitHub Release at `v1.2.3`
- **AND** the release body lists the three PR titles with their authors as auto-generated by GitHub
- **AND** the release is NOT marked as a draft

### Requirement: Multi-arch builds use QEMU + Buildx with per-service GHA cache

Each matrix entry SHALL set up `docker/setup-qemu-action@v3` and `docker/setup-buildx-action@v3`, then build with `docker/build-push-action@v6` configured with `platforms: linux/amd64,linux/arm64` and GHA build cache scoped per service (`cache-from: type=gha,scope=<service>` and `cache-to: type=gha,scope=<service>,mode=max`).

#### Scenario: Cache scope isolates services

- **WHEN** the `ascend-agent` and `paddle-ocr` matrix entries run in parallel
- **THEN** the buildx step for each entry reads and writes its own cache scope
- **AND** a cache eviction in the `paddle-ocr` scope does not affect the `ascend-agent` scope's hit rate
