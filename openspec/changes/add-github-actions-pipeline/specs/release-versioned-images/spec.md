## ADDED Requirements

### Requirement: Release is manual, with a stack version and per-app selection

`release.yaml` SHALL be triggered exclusively via `workflow_dispatch`. It SHALL NOT trigger on Git tag pushes, on schedule, on push to any branch, or on pull-request events. The dispatch inputs SHALL be a required `stack_version` string (e.g. `1.1.1`, naming the monorepo release `ascend-ai_1.1.1`) and one boolean per app selecting whether that app is released. The workflow file SHALL use the `.yaml` extension.

#### Scenario: Manual dispatch releases only the selected apps

- **WHEN** the operator dispatches with `stack_version=1.1.1`, `release_ascend_agent=true`, `release_ascend_audio_scribe=true`, and the other four app booleans `false`
- **THEN** only `ascend-ai-agent` and `ascend-audio-scribe` images are built and pushed
- **AND** `ascend-weather-mcp`, `ascend-web-hunter`, `ascend-memory`, and `ascend-ocr` are not built and their images are untouched

#### Scenario: Tag push does not trigger the release

- **WHEN** a Git tag `ascend-ai_1.1.1` is pushed directly without using the dispatch UI
- **THEN** the `Release` workflow does NOT trigger and no images are pushed

### Requirement: Image version is read from each app's committed manifest

For each selected app the workflow SHALL read the version already committed in that app's manifest — `version` in `build.gradle.kts` for Java services (`ascend-ai-agent`, `ascend-weather-mcp`), `[project].version` in `pyproject.toml` for Python services (`ascend-audio-scribe`, `ascend-web-hunter`, `AscendMemory`, `ascend-ocr`) — and SHALL use that value as the Docker image tag. The workflow SHALL NOT accept a per-app version input, SHALL NOT override the version via a build property or build-arg, and SHALL NOT edit the manifest.

#### Scenario: Tag equals the manifest version

- **WHEN** `apps/ascend-ai-agent/build.gradle.kts` declares `version = "1.3.0"` and `ascend-ai-agent` is selected for release
- **THEN** the pushed image is tagged `lukk17/ascend-ai-agent:1.3.0`
- **AND** `apps/ascend-ai-agent/build.gradle.kts` on disk is unchanged after the run

#### Scenario: Python manifest version

- **WHEN** `apps/ascend-audio-scribe/pyproject.toml` declares `[project] version = "0.2.1"` and `ascend-audio-scribe` is selected
- **THEN** the pushed image is tagged `lukk17/ascend-audio-scribe:0.2.1`
- **AND** `apps/ascend-audio-scribe/pyproject.toml` on disk is unchanged after the run

### Requirement: Release makes no commits

The release workflow SHALL NOT create, amend, or push any commit. It SHALL only create a Git tag and a GitHub Release. No manifest, changelog, or version file SHALL be written back to the repository by the workflow.

#### Scenario: No commit after release

- **WHEN** a release of any set of apps completes successfully
- **THEN** the default branch has no new commit authored by the workflow
- **AND** the only refs created are the tag `ascend-ai_<stack_version>` and its GitHub Release

### Requirement: Bump guard against the previous stack release

For each selected app, the workflow SHALL compare the app's current manifest version against that app's version at the previous `ascend-ai_*` Git tag. If a selected app's version is unchanged from the previous stack release, the workflow SHALL fail before any image is pushed, with a message naming the offending app. When no previous `ascend-ai_*` tag exists (first release), this guard SHALL be skipped.

#### Scenario: Selected app not bumped fails the run

- **WHEN** the previous release `ascend-ai_1.1.0` recorded `ascend-weather-mcp` at `1.0.0`, the current `apps/ascend-weather-mcp/build.gradle.kts` still says `1.0.0`, and `ascend-weather-mcp` is selected for release
- **THEN** the workflow fails in the prepare stage with a message identifying `ascend-weather-mcp` as not bumped
- **AND** no `docker login` or image push occurs for any app

#### Scenario: Selected app correctly bumped proceeds

- **WHEN** `ascend-weather-mcp` was `1.0.0` at the previous stack tag and its manifest now says `1.1.0`, and it is selected
- **THEN** the guard passes and `lukk17/ascend-weather-mcp:1.1.0` is built and pushed

#### Scenario: First release skips the guard

- **WHEN** no `ascend-ai_*` tag exists yet and apps are selected for release
- **THEN** the guard is skipped and each selected app ships at its current manifest version

### Requirement: Released images are tagged version + latest

Each selected app's image SHALL be pushed to Docker Hub at `lukk17/<service>:<manifest-version>` and also `lukk17/<service>:latest`. Unselected apps SHALL NOT have their `:latest` tag modified.

#### Scenario: Released app updates latest

- **WHEN** `ascend-ai-agent` is released at manifest version `1.3.0`
- **THEN** both `lukk17/ascend-ai-agent:1.3.0` and `lukk17/ascend-ai-agent:latest` point at the new image

#### Scenario: Unselected app latest untouched

- **WHEN** `ascend-ocr` is not selected in a release
- **THEN** `lukk17/ascend-ocr:latest` is unchanged by the run

### Requirement: Docker Hub authentication via repository secrets

The workflow SHALL log in to Docker Hub using `docker/login-action@v3` with `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` repository secrets before any push. Credentials SHALL NOT appear in plaintext in logs.

#### Scenario: Missing token fails before push

- **WHEN** `DOCKERHUB_TOKEN` is not configured and a release is dispatched
- **THEN** `docker/login-action@v3` fails and no `docker buildx build --push` step runs

### Requirement: Aggregated monorepo release record listing every app version

After all selected apps push successfully, the workflow SHALL create the Git tag `ascend-ai_<stack_version>` and a GitHub Release (via `softprops/action-gh-release@v2`) whose body lists the current manifest version of **all six** apps — marking which were released in this run — together with `generate_release_notes: true` PR notes. The workflow SHALL reject a `stack_version` whose `ascend-ai_<stack_version>` tag already exists.

#### Scenario: Release notes list all app versions

- **WHEN** a release of `ascend-ai-agent` (1.3.0) and `ascend-audio-scribe` (0.2.1) is dispatched as `stack_version=1.1.1`, with the other apps currently at ascend-weather-mcp 1.0.0, ascend-web-hunter 1.2.0, ascend-memory 0.4.0, ascend-ocr 0.1.0
- **THEN** a GitHub Release tagged `ascend-ai_1.1.1` is created
- **AND** its body lists all six apps with their current versions, marking `ascend-ai-agent` and `ascend-audio-scribe` as released this run
- **AND** the release is not a draft

#### Scenario: Reusing a stack version is rejected

- **WHEN** a release `ascend-ai_1.1.1` already exists and the operator dispatches `stack_version=1.1.1` again
- **THEN** the workflow fails because the tag already exists, before pushing any image

### Requirement: Multi-arch builds use QEMU + Buildx with per-service GHA cache

Each selected app SHALL build with `docker/setup-qemu-action@v3`, `docker/setup-buildx-action@v3`, and `docker/build-push-action@v6` configured `platforms: linux/amd64,linux/arm64` with GHA build cache scoped per service (`cache-from`/`cache-to: type=gha,scope=<service>,mode=max`), and `strategy.fail-fast: false`.

#### Scenario: One app failing does not abort the others

- **WHEN** two apps are selected and one app's build fails
- **THEN** the other selected app still attempts its build (fail-fast disabled)
- **AND** the overall run concludes `failure` and the `release` job (tag + GitHub Release) does NOT run
