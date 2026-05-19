## ADDED Requirements

### Requirement: CI runs on master pushes, PRs, and manual dispatch only

`ci.yaml` SHALL trigger on `pull_request` (any branch), `push: branches: [master]`, and `workflow_dispatch`. It SHALL NOT trigger on pushes to feature branches — feature work runs CI only via the PR opened against master. The workflow file SHALL use the `.yaml` extension to match the repo's YAML convention.

#### Scenario: Push to feature branch does not trigger CI

- **WHEN** a contributor pushes a commit to a feature branch (no PR open)
- **THEN** the CI workflow does NOT run for that push
- **AND** the maintainer can still trigger it manually via `workflow_dispatch` if desired

#### Scenario: Opening a PR triggers CI

- **WHEN** a contributor opens or updates a pull request against `master`
- **THEN** the CI workflow runs for the PR's head commit

#### Scenario: Push to master triggers CI

- **WHEN** a maintainer merges a PR into `master` (a push event on `master`)
- **THEN** the CI workflow runs for the merge commit

### Requirement: Path-filtered matrix per service

`ci.yaml` SHALL run a build-and-test matrix entry for a service only when files under that service's directory have changed in the triggering push or pull request, OR when the workflow file itself has changed. Path filtering SHALL use `dorny/paths-filter@v3` with one filter per service: `ascend-agent` → `AscendAgent/**`, `weather-mcp` → `WeatherMCP/**`, `audio-scribe` → `AudioScribe/**`, `ascend-web-search` → `AscendWebSearch/**`, `ascend-memory` → `AscendMemory/**`, `paddle-ocr` → `PaddleOCR/**`.

#### Scenario: Docs-only PR runs zero matrix entries

- **WHEN** a pull request changes only `README.md` and no service directory
- **THEN** the `changes` job emits all six service outputs as `false`
- **AND** the `build` matrix job is skipped for every service
- **AND** the workflow finishes green in under one minute

#### Scenario: Single-service PR runs only that service

- **WHEN** a pull request changes a file under `AscendAgent/src/main/java/...`
- **THEN** the `changes` job emits `ascend-agent: true` and all other services as `false`
- **AND** only the `ascend-agent` matrix entry executes
- **AND** the entry runs `./gradlew --no-daemon build test` from `AscendAgent/`

#### Scenario: Workflow-file change forces full matrix

- **WHEN** a pull request changes `.github/workflows/ci.yaml`
- **THEN** every service matrix entry runs regardless of whether that service's directory changed
- **AND** this is achieved via a `workflows` filter in `dorny/paths-filter` that the matrix `if:` clause OR-combines with the per-service filter

### Requirement: Java services build with Gradle and Temurin 21

For each Java service in the matrix, the workflow SHALL set up Eclipse Temurin JDK 21 via `actions/setup-java@v4`, configure Gradle caching via `gradle/actions/setup-gradle@v3`, and run `./gradlew --no-daemon build test` from the service's subdirectory. The build SHALL fail if any unit test fails or if the Gradle build exits non-zero.

#### Scenario: AscendAgent build runs with cached Gradle dependencies

- **WHEN** the `ascend-agent` matrix entry executes on a push following a prior successful run on the same branch
- **THEN** `gradle/actions/setup-gradle@v3` restores the dependency cache from the prior run
- **AND** `./gradlew --no-daemon build test` runs from `AscendAgent/`
- **AND** the build succeeds with the cache hit visible in the Gradle build scan output

#### Scenario: Failing unit test fails the workflow

- **WHEN** an `AscendAgent` unit test asserts incorrectly and `./gradlew test` exits non-zero
- **THEN** the `ascend-agent` matrix entry fails
- **AND** the test reports are uploaded as artifact `test-results-ascend-agent` via `actions/upload-artifact@v4` even though the entry failed
- **AND** because `strategy.fail-fast: false` is set, the other service matrix entries still run

### Requirement: Python services install editable with dev extras and run pytest

For each Python service in the matrix, the workflow SHALL set up the per-service Python interpreter via `actions/setup-python@v5` with `cache: pip`, install the service in editable mode with dev extras (`pip install -e .[dev]`), and run `pytest` from the service's subdirectory. The build SHALL fail if any test fails or if pytest exits non-zero. Per-service Python versions: `AudioScribe`, `AscendMemory`, `PaddleOCR` use `3.11`; `AscendWebSearch` uses `3.12`.

#### Scenario: AudioScribe matrix entry installs and tests

- **WHEN** the `audio-scribe` matrix entry executes
- **THEN** `actions/setup-python@v5` installs Python 3.11 with pip caching keyed on `AudioScribe/pyproject.toml`
- **AND** `pip install -e .[dev]` succeeds from `AudioScribe/`
- **AND** `pytest` runs from `AudioScribe/` and exits zero

#### Scenario: AscendWebSearch uses Python 3.12

- **WHEN** the `ascend-web-search` matrix entry executes
- **THEN** the setup-python step is configured with `python-version: '3.12'`
- **AND** the resulting interpreter reports `Python 3.12.x` in the build log

### Requirement: Concurrency cancels superseded PR builds

`ci.yaml` SHALL declare `concurrency: { group: ci-${{ github.ref }}, cancel-in-progress: true }` so that a force-push or new commit to the same pull request cancels the in-flight CI run for that ref.

#### Scenario: Force-push cancels prior run

- **WHEN** CI is mid-execution on commit `abc123` of PR `#42` and the contributor force-pushes a new commit `def456`
- **THEN** the workflow run for `abc123` transitions to `cancelled`
- **AND** a new workflow run starts for `def456` immediately

### Requirement: Read-only permissions and no secret exposure on PR

`ci.yaml` SHALL declare top-level `permissions: { contents: read }` and SHALL NOT consume any repository secret. PRs from forks SHALL therefore execute the workflow safely with no privileged access.

#### Scenario: Fork PR has no secret access

- **WHEN** a contributor opens a pull request from a fork of the repository
- **THEN** the CI workflow runs against the PR's commit
- **AND** any reference to `${{ secrets.* }}` resolves to empty (default GitHub Actions behavior for fork PRs)
- **AND** because the workflow does not depend on any secret, the build still succeeds for valid changes
