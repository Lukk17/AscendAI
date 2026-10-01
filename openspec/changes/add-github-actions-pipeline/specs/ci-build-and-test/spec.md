## ADDED Requirements

### Requirement: CI runs on master pushes, PRs, and manual dispatch only

`ci.yaml` SHALL trigger on `pull_request` (any branch), `push: branches: [master]`, and `workflow_dispatch`. It SHALL NOT trigger on pushes to feature branches. Feature work runs CI only through the PR opened against master. The workflow file SHALL use the `.yaml` extension to match the repo's YAML convention.

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

### Requirement: Path-filtered dynamic matrix per service

`ci.yaml` SHALL run a build-and-test matrix entry for a service only when files under that service's directory have changed in the triggering push or pull request, OR when `.github/workflows/**` has changed. The `changes` job SHALL use `dorny/paths-filter@v3` with one filter per service (`ascend-agent` for `apps/ascend-agent/**`, `ascend-weather-mcp` for `apps/ascend-weather-mcp/**`, `ascend-audio-scribe` for `apps/ascend-audio-scribe/**`, `ascend-web-hunter` for `apps/ascend-web-hunter/**`, `ascend-memory` for `apps/ascend-memory/**`, `ascend-ocr` for `apps/ascend-ocr/**`), plus a `workflows` filter, and SHALL emit a JSON matrix holding only the selected services. The `build` job SHALL be skipped when that matrix is empty.

#### Scenario: Docs-only PR runs zero matrix entries

- **WHEN** a pull request changes only `README.md` and no service directory
- **THEN** the `changes` job emits an empty matrix
- **AND** the `build` job is skipped
- **AND** `verify-changelog`, `integration-test` and both contract jobs are skipped

#### Scenario: Single-service PR runs only that service

- **WHEN** a pull request changes a file under `apps/ascend-agent/src/main/java/...`
- **THEN** the matrix holds only the `ascend-agent` entry
- **AND** that entry runs `./gradlew --no-daemon build test` from `apps/ascend-agent/`

#### Scenario: Workflow-file change forces full matrix

- **WHEN** a pull request changes `.github/workflows/ci.yaml`
- **THEN** the matrix holds all six services regardless of whether their directories changed

### Requirement: Java services build with Gradle and Temurin 21, with the agent's coverage floor

For each Java service in the matrix, the workflow SHALL set up Eclipse Temurin JDK 21 via `actions/setup-java@v4`, configure Gradle caching via `gradle/actions/setup-gradle@v3`, and run `./gradlew --no-daemon build test` from the service's subdirectory. For `ascend-agent` only, it SHALL then run `./gradlew --no-daemon jacocoTestCoverageVerification`, which fails below 80 percent instruction coverage. The entry SHALL fail if any Gradle command exits non-zero.

#### Scenario: Failing unit test fails the entry

- **WHEN** an `ascend-agent` unit test asserts incorrectly and `./gradlew build test` exits non-zero
- **THEN** the `ascend-agent` matrix entry fails
- **AND** the test reports are uploaded as artifact `test-results-ascend-agent` via `actions/upload-artifact@v4` even though the entry failed
- **AND** because `strategy.fail-fast: false` is set, the other matrix entries still run

#### Scenario: Agent coverage below the floor fails the entry

- **WHEN** `ascend-agent` tests pass but instruction coverage is below 80 percent
- **THEN** the `jacocoTestCoverageVerification` step fails the `ascend-agent` entry

#### Scenario: Weather MCP has no coverage step

- **WHEN** the `ascend-weather-mcp` entry runs
- **THEN** no `jacocoTestCoverageVerification` step runs for it

### Requirement: Python services lint, type check and test with a 100 percent branch coverage floor

For each Python service in the matrix, the workflow SHALL set up the per-service Python interpreter via `actions/setup-python@v5` with `cache: pip` and a `cache-dependency-path` of that service's own `pyproject.toml` and any `*requirements*.txt` beside it, install the service with `pip install -e .[dev]`, then run `ruff check .`, `mypy src`, and the tests, all from the service's subdirectory. `ascend-audio-scribe` and `ascend-ocr` SHALL run plain `pytest`, whose configured options enforce `--cov-fail-under=100` with branch coverage. `ascend-web-hunter` and `ascend-memory` SHALL run `pytest --cov=src --cov-branch --cov-report=term-missing --cov-fail-under=100`. Per-service Python versions: `ascend-audio-scribe`, `ascend-memory` and `ascend-ocr` use `3.11`, and `ascend-web-hunter` uses `3.12`.

#### Scenario: A Python entry runs every gate

- **WHEN** the `ascend-memory` matrix entry executes
- **THEN** `actions/setup-python@v5` installs Python 3.11 with a pip cache keyed on `apps/ascend-memory/pyproject.toml`
- **AND** `pip install -e .[dev]`, `ruff check .`, `mypy src` and the coverage-gated `pytest` run in that order from `apps/ascend-memory/`

#### Scenario: ascend-web-hunter uses Python 3.12

- **WHEN** the `ascend-web-hunter` matrix entry executes
- **THEN** the setup-python step is configured with `python-version: '3.12'`

#### Scenario: Coverage below 100 percent fails the entry

- **WHEN** a Python service's tests pass but branch coverage is below 100 percent
- **THEN** its `pytest` step fails the entry

### Requirement: Every changed app carries a changelog version bump on pull requests

`ci.yaml` SHALL run a `verify-changelog` job on `pull_request` and `workflow_dispatch`, never on `push`, when at least one app directory changed. For each changed app it SHALL compare the top `## [x.y.z]` entry of `apps/<app>/CHANGELOG.md` at HEAD against the same file at the PR base ref, or `master` for a dispatch, and SHALL fail when the file or entry is missing at HEAD, when the entry is missing at the base ref while the file exists there, when the HEAD version is not strictly greater by `sort -V`, or when the top entry has no content. A file absent at the base ref SHALL be treated as a new module. The `build`, `integration-test` and `contract-consumer` jobs SHALL run only when `verify-changelog` did not fail, and SHALL still run when it was skipped.

#### Scenario: Unbumped app fails the PR

- **WHEN** a pull request changes `apps/ascend-ocr/src/...` and the top entry of `apps/ascend-ocr/CHANGELOG.md` equals the base ref's
- **THEN** `verify-changelog` fails naming `ascend-ocr`
- **AND** `build`, `integration-test` and `contract-consumer` do not run

#### Scenario: Push to master skips the check without blocking

- **WHEN** a PR is merged to `master`
- **THEN** `verify-changelog` is skipped
- **AND** the `build` job still runs for the changed services

### Requirement: The agent's integration tests run in their own job

`ci.yaml` SHALL run an `integration-test` job when `ascend-agent` or `.github/workflows/**` changed. It SHALL set up Temurin 21 and Gradle, run `./gradlew --no-daemon integrationTest` in `apps/ascend-agent` (Testcontainers on the runner's Docker daemon), and upload the JUnit XML as artifact `integration-test-results-ascend-agent` on every run.

#### Scenario: Integration tests run beside the unit-test matrix

- **WHEN** a pull request changes a file under `apps/ascend-agent/`
- **THEN** `integration-test` and the `build` matrix both start after `verify-changelog`, neither waiting for the other
- **AND** a failing integration test fails the workflow while the `build` results still report

### Requirement: Concurrency cancels superseded builds

`ci.yaml` SHALL declare `concurrency: { group: ci-${{ github.ref }}, cancel-in-progress: true }` so that a force-push or new commit to the same ref cancels the in-flight CI run for that ref.

#### Scenario: Force-push cancels prior run

- **WHEN** CI is mid-execution on commit `abc123` of PR `#42` and the contributor force-pushes a new commit `def456`
- **THEN** the workflow run for `abc123` transitions to `cancelled`
- **AND** a new workflow run starts for `def456` immediately

### Requirement: Read-only permissions and no secret exposure on PR

`ci.yaml` SHALL declare top-level `permissions: { contents: read }` and SHALL NOT consume any repository secret. PRs from forks SHALL therefore execute the workflow safely with no privileged access.

#### Scenario: Fork PR has no secret access

- **WHEN** a contributor opens a pull request from a fork of the repository
- **THEN** the CI workflow runs against the PR's commit
- **AND** because the workflow does not depend on any secret, the build still succeeds for valid changes

### Requirement: Agent to OCR contract verification runs when either side changes

`ci.yaml` SHALL verify the Pact contract between `ascend-agent` (consumer) and `ascend-ocr` (provider) in two ordered jobs whenever `apps/ascend-agent/**`, `apps/ascend-ocr/**`, `contracts/**` or `.github/workflows/**` changed. The `changes` job SHALL expose this as a `contract` output. The job `contract-consumer` SHALL run `./gradlew --no-daemon test --tests "com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrClientPactTest"` in `apps/ascend-agent`, SHALL fail when `git status --porcelain -- contracts/pacts` is not empty afterwards, and SHALL upload `contracts/pacts` as artifact `pact-ascend-agent-ascend-ocr` on every run. The job `contract-provider` SHALL run only after `contract-consumer` succeeded, and SHALL run `pytest tests/contract --no-cov` in `apps/ascend-ocr` after `pip install -e .[dev]` on Python 3.11. Neither job SHALL use a repository secret or a Pact Broker.

#### Scenario: Agent-only change runs both contract jobs

- **WHEN** a pull request changes only files under `apps/ascend-agent/`
- **THEN** the `changes` job emits `contract: true`
- **AND** `contract-consumer` runs and, when it passes, `contract-provider` runs after it

#### Scenario: OCR-only change runs both contract jobs

- **WHEN** a pull request changes only files under `apps/ascend-ocr/`
- **THEN** the `changes` job emits `contract: true`
- **AND** `contract-consumer` regenerates the pact from the agent side and `contract-provider` verifies the committed pact against the changed provider

#### Scenario: Docs-only change runs neither contract job

- **WHEN** a pull request changes only `README.md` or files under `docs/`
- **THEN** the `changes` job emits `contract: false`
- **AND** both `contract-consumer` and `contract-provider` are skipped

#### Scenario: A stale committed pact fails the consumer job and stops the provider job

- **WHEN** the consumer test produces a pact that differs from the committed `contracts/pacts/ascend-agent-ascend-ocr.json`
- **THEN** `contract-consumer` prints the diff, emits an `::error::` annotation saying the committed pact is out of date and must be regenerated and committed, and fails
- **AND** `contract-provider` does not run
- **AND** the pact artifact is still uploaded

#### Scenario: A provider failure fails the workflow

- **WHEN** `contract-consumer` passes and ascend-ocr no longer answers an interaction the way the committed pact records it
- **THEN** `contract-provider` fails
- **AND** the CI workflow run concludes as failed

#### Scenario: No secret is used by the contract jobs

- **WHEN** a pull request from a fork triggers the contract jobs
- **THEN** neither job references `${{ secrets.* }}` or a Pact Broker URL or token
- **AND** both jobs run with the workflow's `permissions: { contents: read }`
