## 1. Repository scaffolding

- [x] 1.1 Create `.github/workflows/` directory at the repo root
- [x] 1.2 Add `.github/workflows/README.md` with operator notes: required secrets table, the changelog-version and app-selection release model, how the bump guard works, how to cut a release, image naming and GHCR visibility, GHA cache budget, and follow-up ideas

## 2. `ci.yaml`: build, gates and tests (never pushes images)

- [x] 2.1 Add `name: CI`, triggers: `pull_request`, `push: branches: [master]`, `workflow_dispatch`
- [x] 2.2 Declare top-level `permissions: { contents: read }`, with no secrets referenced anywhere in this workflow
- [x] 2.3 Declare `concurrency: { group: ci-${{ github.ref }}, cancel-in-progress: true }`
- [x] 2.4 First job `changes`: `dorny/paths-filter@v3` with one filter per service (`ascend-agent`, `ascend-weather-mcp`, `ascend-audio-scribe`, `ascend-web-hunter`, `ascend-memory`, `ascend-ocr`) plus a `workflows` filter (`.github/workflows/**`), a step that emits a dynamic JSON matrix of the changed services (all six when `workflows` changed), and per-service `*_changed` outputs
- [x] 2.5 Job `verify-changelog` on `pull_request` and `workflow_dispatch` only: for each changed app, compare the top `## [x.y.z]` of `apps/<app>/CHANGELOG.md` at HEAD against the base ref (or `master`), and fail when missing, not strictly greater by `sort -V`, or empty. A file absent at the base ref counts as a new module
- [x] 2.6 Job `build` over the dynamic matrix `{ service, language, path, python_version }`, needing `changes` and `verify-changelog`, with `if: !cancelled() && needs.verify-changelog.result != 'failure'` and a non-empty matrix, and `strategy.fail-fast: false`
- [x] 2.7 Java step set: `actions/checkout@v4`, `actions/setup-java@v4` (Temurin 21), `gradle/actions/setup-gradle@v3`, then `./gradlew --no-daemon build test` in `${{ matrix.path }}`
- [x] 2.8 Java coverage gate: `./gradlew --no-daemon jacocoTestCoverageVerification` for `ascend-agent` only (80 percent instruction coverage)
- [x] 2.9 Python step set: `actions/setup-python@v5` with the right version per service, `cache: pip` and a `cache-dependency-path` of the service's own `pyproject.toml` and `*requirements*.txt`, then `pip install -e .[dev]`, `ruff check .`, `mypy src`
- [x] 2.10 Python tests with the 100 percent branch coverage floor: plain `pytest` for `ascend-audio-scribe` and `ascend-ocr`, `pytest --cov=src --cov-branch --cov-report=term-missing --cov-fail-under=100` for `ascend-web-hunter` and `ascend-memory`
- [x] 2.11 Upload test reports as artifact `test-results-${{ matrix.service }}` on `always()`
- [x] 2.12 Job `integration-test` (needs `changes` and `verify-changelog`, runs when `ascend-agent` or the workflows changed): Temurin 21, Gradle, `./gradlew --no-daemon integrationTest` in `apps/ascend-agent`, JUnit XML uploaded as `integration-test-results-ascend-agent` on `always()`

## 3. `release.yaml`: manual, app-selective, version-from-changelog

- [x] 3.1 Add `name: Release`, single trigger `workflow_dispatch` with inputs: `create_github_release` (required boolean, default `true`), `stack_version` (optional string), and six required booleans `release_<app>` (default `false`), one per service. No tag, push, PR or cron trigger
- [x] 3.2 Declare top-level `permissions: { contents: write }` (Git tag and GitHub Release), narrowed on `build-and-push` to `contents: read` and `packages: write`
- [x] 3.3 Declare `concurrency: { group: release-${{ inputs.stack_version || github.run_id }}, cancel-in-progress: false }`
- [x] 3.4 Job `prepare`: collect the selected apps from the booleans, and fail early if zero apps are selected
- [x] 3.5 `prepare`: when `create_github_release` is ticked, require `stack_version` and reject the run if the tag `ascend-ai_<stack_version>` already exists
- [x] 3.6 `prepare`: read each selected app's version from the top `## [x.y.z]` entry of its `CHANGELOG.md` with one pinned `grep -oP` extractor, failing when it cannot be read, and document the extractor in the workflow README
- [x] 3.7 `prepare`: emit a JSON matrix of `{ service, path, version, image_name }` for the selected apps (job output)
- [x] 3.8 Job `build-and-push` (matrix from `prepare`, `strategy.fail-fast: false`): `actions/checkout@v4`, `docker/setup-qemu-action@v3`, `docker/setup-buildx-action@v3`, `docker/login-action@v3` for Docker Hub (secrets) and for GHCR (`GITHUB_TOKEN`)
- [x] 3.9 `build-and-push`: per-registry bump guard with `docker manifest inspect` on `v<version>`: fail when found on both, proceed when found on neither, warn and complete when found on one, fail closed on a lookup error
- [x] 3.10 `build-and-push`: `docker/build-push-action@v6` with `context: ${{ matrix.path }}`, `platforms: linux/amd64,linux/arm64`, `cache-from` and `cache-to: type=gha,scope=${{ matrix.service }},mode=max`, and tags `v<version>` and `latest` on `lukk17/ascend-ai-<service>` and `ghcr.io/lukk17/ascend-ai-<service>`. No version build-arg or `-Pversion` override
- [x] 3.11 Job `release` (needs `build-and-push`, runs only when `create_github_release` is ticked and the pushes succeeded): read the current changelog version of all six apps and compose a body table listing every app and version, marking the released ones
- [x] 3.12 `release`: `softprops/action-gh-release@v2` with `tag_name: ascend-ai_${{ inputs.stack_version }}`, the composed body, `generate_release_notes: true`, not a draft or prerelease. No commit is made anywhere in the workflow

## 4. Documentation

- [x] 4.1 Document the secrets table (`DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`, release only, GHCR via `GITHUB_TOKEN`, CI uses none)
- [x] 4.2 Document the developer convention: add a new top `## [x.y.z]` entry to the app's `CHANGELOG.md` in the PR, enforced by `verify-changelog`, and that the manifest `version` is not read
- [x] 4.3 Document the release procedure: Actions → `Release` → `Run workflow`, enter `stack_version` and tick the apps to ship, the image-only mode, the bump-guard outcomes and how to fix a failure, and that no commits are produced
- [x] 4.4 Document the trigger matrix (no tag trigger, no cron), image naming on both registries, GHCR package visibility, and the per-service cache scoping and GHA cache budget
- [x] 4.5 Cross-link from the root `README.md` to `.github/workflows/README.md`

## 5. Verification

- [ ] 5.1 PR touching only `README.md` → zero matrix entries run and `verify-changelog` is skipped
- [ ] 5.2 PR touching `apps/ascend-agent/` with a changelog bump → only the `ascend-agent` build entry and `integration-test` run and pass, including the Jacoco gate
- [ ] 5.3 PR touching a Python service with a changelog bump → only that entry runs, and Ruff, Mypy and the coverage-gated `pytest` execute
- [ ] 5.4 PR touching an app without a changelog bump → `verify-changelog` fails naming the app and the build jobs do not run
- [ ] 5.5 Dispatch `Release` selecting an app whose `v<version>` is already on both registries → that app's `build-and-push` fails before pushing and the `release` job does not run
- [ ] 5.6 Dispatch `Release` with `stack_version` and one bumped app selected → only that image pushes to both registries at `v<version>` and `latest`, an `ascend-ai_<stack_version>` tag and GitHub Release are created listing all six app versions, and the default branch gains no workflow commit
- [ ] 5.7 Dispatch `Release` with `create_github_release` unticked → images push and no tag or GitHub Release is created
- [ ] 5.8 Dispatch `Release` reusing an existing `stack_version` → run fails in `prepare` before any push
- [ ] 5.9 Force-push to a PR while CI runs → prior CI run is cancelled
- [ ] 5.10 Confirm a fork PR run exposes no secrets (CI holds none, release never runs on PRs)

## 6. Contract tests (ascend-agent consumer, ascend-ocr provider)

- [x] 6.1 `changes` job: add a `contract` paths-filter entry for `contracts/**` and a `contract` output that is true when `ascend-agent`, `ascend-ocr`, `contract` or `workflows` changed
- [x] 6.2 Add job `contract-consumer` (needs `changes` and `verify-changelog`, runs when not cancelled, `verify-changelog` did not fail and `contract` is true): checkout, Temurin 21 and `setup-gradle` as in `build`, `./gradlew --no-daemon test --tests "com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrClientPactTest"` in `apps/ascend-agent`
- [x] 6.3 `contract-consumer`: drift step that fails with `::error::` and the diff when `git status --porcelain -- contracts/pacts` is not empty
- [x] 6.4 `contract-consumer`: upload `contracts/pacts` as artifact `pact-ascend-agent-ascend-ocr` on `always()`
- [x] 6.5 Add job `contract-provider` (needs `changes` and `contract-consumer`, runs when not cancelled and `contract-consumer` succeeded): checkout, `setup-python` 3.11 with `cache: pip`, `pip install -e .[dev]`, `pytest tests/contract --no-cov` in `apps/ascend-ocr`
- [x] 6.6 No secret and no Pact Broker referenced by either job, and workflow permissions stay `contents: read`
- [x] 6.7 `.gitattributes`: `contracts/pacts/*.json text eol=lf`
- [x] 6.8 Add `contracts/README.md`: who writes and who reads the pact, how to regenerate it, the drift check command, no broker and no `can-i-deploy`
- [x] 6.9 Add a Contract tests section to `.github/workflows/README.md`: jobs, order, triggers, how to fix a drift failure
- [x] 6.10 Add ADR-M010 and its index entry in `docs/architecture/decisions/README.md`, and list `contracts/README.md` in the root `README.md` documentation map
- [ ] 6.11 PR touching only `apps/ascend-agent/` → `contract-consumer` and then `contract-provider` run and pass
- [ ] 6.12 PR touching only `apps/ascend-ocr/` → both contract jobs run and pass
- [ ] 6.13 PR touching only `README.md` → both contract jobs are skipped
- [ ] 6.14 PR with a consumer test change but the old committed pact → `contract-consumer` fails with the out-of-date error and the diff, `contract-provider` does not run
- [ ] 6.15 PR that breaks an interaction on the ascend-ocr side → `contract-provider` fails and the workflow run fails
- [ ] 6.16 Confirm from the run log that neither contract job receives a secret
