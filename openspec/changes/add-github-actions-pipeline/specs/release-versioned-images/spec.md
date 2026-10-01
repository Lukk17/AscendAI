## ADDED Requirements

### Requirement: Release is manual, with per-app selection and an optional stack release

`release.yaml` SHALL be triggered exclusively via `workflow_dispatch`. It SHALL NOT trigger on Git tag pushes, on schedule, on push to any branch, or on pull-request events. The dispatch inputs SHALL be a required boolean `create_github_release` (default `true`), an optional `stack_version` string (e.g. `1.1.1`, naming the monorepo release `ascend-ai_1.1.1`), and one required boolean per app (`release_ascend_agent`, `release_ascend_weather_mcp`, `release_ascend_audio_scribe`, `release_ascend_web_hunter`, `release_ascend_memory`, `release_ascend_ocr`, each default `false`). The run SHALL fail before any build when no app is selected, and, when `create_github_release` is ticked, when `stack_version` is empty. The workflow file SHALL use the `.yaml` extension.

#### Scenario: Manual dispatch releases only the selected apps

- **WHEN** the operator dispatches with `stack_version=1.1.1`, `release_ascend_agent=true`, `release_ascend_audio_scribe=true`, and the other four app booleans `false`
- **THEN** only the `ascend-agent` and `ascend-audio-scribe` images are built and pushed
- **AND** `ascend-weather-mcp`, `ascend-web-hunter`, `ascend-memory`, and `ascend-ocr` are not built and their images are untouched

#### Scenario: No app selected fails early

- **WHEN** the operator dispatches with every app boolean `false`
- **THEN** the `prepare` job fails and nothing is built or pushed

#### Scenario: Image-only run consumes no stack version

- **WHEN** the operator dispatches with `create_github_release=false`, an empty `stack_version`, and one app selected
- **THEN** that app's images are built and pushed
- **AND** the `release` job is skipped, so no Git tag and no GitHub Release are created

#### Scenario: Tag push does not trigger the release

- **WHEN** a Git tag `ascend-ai_1.1.1` is pushed directly without using the dispatch UI
- **THEN** the `Release` workflow does NOT trigger and no images are pushed

### Requirement: Image version is read from each app's committed CHANGELOG.md

For each selected app the workflow SHALL read the version from the topmost `## [x.y.z]` entry of `apps/<app>/CHANGELOG.md`, using one extractor for all six apps, and SHALL use `v<version>` as the Docker image tag. The run SHALL fail when an entry cannot be read. The workflow SHALL NOT read the `version` in `build.gradle.kts` or `pyproject.toml`, SHALL NOT accept a per-app version input, SHALL NOT override the version via a build property or build-arg, and SHALL NOT edit any file.

#### Scenario: Tag equals the changelog version

- **WHEN** the top entry of `apps/ascend-agent/CHANGELOG.md` is `## [1.3.0]` and `ascend-agent` is selected for release
- **THEN** the pushed images are tagged `lukk17/ascend-ai-ascend-agent:v1.3.0` and `ghcr.io/lukk17/ascend-ai-ascend-agent:v1.3.0`
- **AND** `apps/ascend-agent/CHANGELOG.md` on disk is unchanged after the run

#### Scenario: Manifest version is ignored

- **WHEN** `apps/ascend-audio-scribe/pyproject.toml` says `version = "0.2.0"`, the top entry of `apps/ascend-audio-scribe/CHANGELOG.md` is `## [0.2.1]`, and `ascend-audio-scribe` is selected
- **THEN** the pushed images are tagged `v0.2.1`
- **AND** the mismatch causes no failure

### Requirement: Release makes no commits

The release workflow SHALL NOT create, amend, or push any commit. It SHALL only create a Git tag and a GitHub Release, and only when `create_github_release` is ticked. No manifest, changelog, or version file SHALL be written back to the repository by the workflow.

#### Scenario: No commit after release

- **WHEN** a release of any set of apps completes successfully
- **THEN** the default branch has no new commit authored by the workflow
- **AND** the only refs created are the tag `ascend-ai_<stack_version>` and its GitHub Release, or none for an image-only run

### Requirement: Bump guard against the registries

For each selected app, after logging in and before building, the workflow SHALL check whether `<image>:v<version>` exists on Docker Hub (`lukk17/ascend-ai-<service>`) and on GHCR (`ghcr.io/lukk17/ascend-ai-<service>`). Found on both registries SHALL fail that app's job with a message asking for a new `CHANGELOG.md` entry. Found on neither SHALL proceed. Found on exactly one SHALL log a warning and proceed, completing the missing registry. A lookup that fails for any reason other than a missing manifest SHALL fail that app's job without pushing. The guard SHALL NOT depend on git history.

#### Scenario: Already published version fails the app

- **WHEN** `ascend-weather-mcp` v1.0.0 exists on both Docker Hub and GHCR and the changelog still says `## [1.0.0]` and `ascend-weather-mcp` is selected
- **THEN** its `build-and-push` job fails naming `ascend-weather-mcp` and asking for a new changelog entry
- **AND** no image is pushed for it

#### Scenario: New version proceeds

- **WHEN** the changelog says `## [1.1.0]` and `v1.1.0` exists on neither registry
- **THEN** the guard passes and the images are built and pushed

#### Scenario: Incomplete earlier publish is completed

- **WHEN** `v1.1.0` exists on Docker Hub but not on GHCR
- **THEN** the job logs a warning and pushes to both registries

#### Scenario: Registry lookup error fails closed

- **WHEN** the lookup fails with an authentication or network error
- **THEN** the job fails without pushing

### Requirement: Released images are pushed to two registries, tagged version and latest

Each selected app's image SHALL be built once and pushed to `lukk17/ascend-ai-<service>:v<version>`, `lukk17/ascend-ai-<service>:latest`, `ghcr.io/lukk17/ascend-ai-<service>:v<version>` and `ghcr.io/lukk17/ascend-ai-<service>:latest`, where `<service>` is the service key (`ascend-agent`, `ascend-weather-mcp`, `ascend-audio-scribe`, `ascend-web-hunter`, `ascend-memory`, `ascend-ocr`). Unselected apps SHALL NOT have their `latest` tag modified.

#### Scenario: Released app updates latest on both registries

- **WHEN** `ascend-agent` is released at changelog version `1.3.0`
- **THEN** `lukk17/ascend-ai-ascend-agent:v1.3.0`, `lukk17/ascend-ai-ascend-agent:latest`, `ghcr.io/lukk17/ascend-ai-ascend-agent:v1.3.0` and `ghcr.io/lukk17/ascend-ai-ascend-agent:latest` all point at the new image

#### Scenario: Unselected app latest untouched

- **WHEN** `ascend-ocr` is not selected in a release
- **THEN** `lukk17/ascend-ai-ascend-ocr:latest` and `ghcr.io/lukk17/ascend-ai-ascend-ocr:latest` are unchanged by the run

### Requirement: Registry authentication and least privilege

The workflow SHALL log in to Docker Hub using `docker/login-action@v3` with the `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` repository secrets, and to GHCR using `docker/login-action@v3` with the automatic `GITHUB_TOKEN`, before any push. The workflow SHALL declare `permissions: { contents: write }` at workflow level, and the `build-and-push` job SHALL narrow it to `contents: read` and `packages: write`. Credentials SHALL NOT appear in plaintext in logs.

#### Scenario: Missing token fails before push

- **WHEN** `DOCKERHUB_TOKEN` is not configured and a release is dispatched
- **THEN** the Docker Hub login step fails and no build-and-push step runs for that app

### Requirement: Aggregated monorepo release record listing every app version

When `create_github_release` is ticked and every selected app pushed successfully, the workflow SHALL create the Git tag `ascend-ai_<stack_version>` and a GitHub Release (via `softprops/action-gh-release@v2`) whose body lists the current changelog version of **all six** apps, marking which were released in this run, together with `generate_release_notes: true` PR notes. The release SHALL NOT be a draft or a prerelease. The `prepare` job SHALL reject a `stack_version` whose `ascend-ai_<stack_version>` tag already exists, before any build.

#### Scenario: Release notes list all app versions

- **WHEN** a release of `ascend-agent` (1.3.0) and `ascend-audio-scribe` (0.2.1) is dispatched as `stack_version=1.1.1`, with the other apps currently at ascend-weather-mcp 1.0.0, ascend-web-hunter 1.2.0, ascend-memory 0.4.0, ascend-ocr 0.1.0
- **THEN** a GitHub Release tagged `ascend-ai_1.1.1` is created
- **AND** its body lists all six apps with their current versions, marking `ascend-agent` and `ascend-audio-scribe` as released
- **AND** the release is not a draft

#### Scenario: Reusing a stack version is rejected

- **WHEN** a release `ascend-ai_1.1.1` already exists and the operator dispatches `stack_version=1.1.1` again with `create_github_release` ticked
- **THEN** the `prepare` job fails because the tag already exists, before building or pushing any image

### Requirement: Multi-arch builds use QEMU and Buildx with per-service GHA cache

Each selected app SHALL build with `docker/setup-qemu-action@v3`, `docker/setup-buildx-action@v3`, and `docker/build-push-action@v6` configured `platforms: linux/amd64,linux/arm64` with GHA build cache scoped per service (`cache-from: type=gha,scope=<service>` and `cache-to: type=gha,scope=<service>,mode=max`), and `strategy.fail-fast: false`.

#### Scenario: One app failing does not abort the others

- **WHEN** two apps are selected and one app's build fails
- **THEN** the other selected app still attempts its build (fail-fast disabled)
- **AND** the overall run concludes `failure` and the `release` job (tag and GitHub Release) does NOT run

### Requirement: A manual release is never cancelled by another

The workflow SHALL declare `concurrency` with group `release-${{ inputs.stack_version || github.run_id }}` and `cancel-in-progress: false`.

#### Scenario: Image-only runs do not share a group

- **WHEN** two image-only runs with an empty `stack_version` are dispatched one after the other
- **THEN** each run uses its own run identifier as the group and neither cancels the other
