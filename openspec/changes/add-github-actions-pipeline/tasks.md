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
- [x] 2.9 Python step set: `actions/setup-python@v5` with the right version per service, `cache: pip` and a `cache-dependency-path` of the service's own `pyproject.toml` and `*requirements*.txt`, then `pip install -e .[dev]`, `ruff check .`, and Mypy: `mypy src` for `ascend-audio-scribe`, `ascend-web-hunter` and `ascend-memory`, `mypy src tests` for `ascend-ocr`
- [x] 2.10 Python tests with the 100 percent branch coverage floor: plain `pytest` for `ascend-audio-scribe`, `pytest -m "not contract"` for `ascend-ocr` (the contract test runs in `contract-provider`), `pytest --cov=src --cov-branch --cov-report=term-missing --cov-fail-under=100` for `ascend-web-hunter` and `ascend-memory`
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

Every task in this section and 6.11 to 6.16 is proved only by a new GitHub Actions run started after this change was refreshed on 2026-10-01. A run from before that date does not count. A task is ticked only after its run URL is written on an indented line right below the task, as `Run: <url> (commit <sha>)`. Each pull request comes from a throwaway branch named `ci-verify/<task>` (for example `ci-verify/5-1`) and is closed without merging afterwards. Pushing a branch and opening a pull request starts CI, so each one needs the owner's go-ahead in the conversation first.

- [ ] 5.1 A docs-only change runs no build. Change: edit one line of the root `README.md` and nothing else. Trigger: open a pull request from `ci-verify/5-1` to `master`. Pass: in the `CI` run the `changes` job emits an empty matrix, and `build`, `integration-test`, `contract-consumer`, `contract-provider` and `verify-changelog` all show as skipped. Record the run URL here.
- [ ] 5.2 An agent change runs only the agent entry. Change: a harmless edit under `apps/ascend-agent/src/` plus a new top `## [0.1.3]` entry with one line of content in `apps/ascend-agent/CHANGELOG.md` (current is `0.1.2`). Trigger: pull request from `ci-verify/5-2`. Pass: `verify-changelog` succeeds, the `build` matrix holds only `ascend-agent`, the `jacocoTestCoverageVerification` step runs and passes, and `integration-test` runs and passes. Record the run URL here.
- [ ] 5.3 A Python change runs only that entry with every gate. Change: a harmless edit under `apps/ascend-memory/src/` plus a new top `## [0.1.4]` entry in `apps/ascend-memory/CHANGELOG.md` (current is `0.1.3`). Trigger: pull request from `ci-verify/5-3`. Pass: the `build` matrix holds only `ascend-memory`, and the job log shows `ruff check .`, `mypy src` and `pytest --cov=src --cov-branch --cov-report=term-missing --cov-fail-under=100` each running and passing. Record the run URL here.
- [ ] 5.4 A missing changelog bump blocks the build. Change: a harmless edit under `apps/ascend-weather-mcp/src/` with no change to `apps/ascend-weather-mcp/CHANGELOG.md` (stays at `0.0.4`). Trigger: pull request from `ci-verify/5-4`. Pass: `verify-changelog` fails with a message naming `ascend-weather-mcp`, and `build` does not run. Record the run URL here.

Tasks 5.5 to 5.8 dispatch the `Release` workflow, which pushes real images to Docker Hub and GHCR and can create a real Git tag and GitHub Release. Each one needs the owner's explicit approval for that single run, naming the app, its version and the stack version, before it is dispatched. Trigger for all four: GitHub, Actions, `Release`, `Run workflow` on `master`, or `gh workflow run release.yaml --ref master` with the `-f` inputs given in the task.

- [ ] 5.5 An already published version is refused. Setup: pick an app whose current changelog version is on both registries, for example `ascend-memory` at `0.1.3`. Check first that both `docker manifest inspect lukk17/ascend-ai-ascend-memory:v0.1.3` and `docker manifest inspect ghcr.io/lukk17/ascend-ai-ascend-memory:v0.1.3` succeed. Trigger: `-f create_github_release=true -f stack_version=<unused stack version> -f release_ascend_memory=true`. Pass: the `build-and-push` job for `ascend-memory` fails in the bump guard step before the build step, the digest of `v0.1.3` on both registries is unchanged, the `release` job is skipped, and `git ls-remote --tags origin ascend-ai_<stack version>` prints nothing. Record the run URL here.
- [ ] 5.6 A full release of one bumped app. Setup: a merged changelog bump on `master` for one app, whose new version is on neither registry. Trigger: `-f create_github_release=true -f stack_version=<next unused stack version> -f release_<app>=true`. Pass: `v<version>` and `latest` exist on `lukk17/ascend-ai-<app>` and on `ghcr.io/lukk17/ascend-ai-<app>` with the same digest, the tag `ascend-ai_<stack version>` and a non-draft GitHub Release exist, the release body lists all six apps with the versions in their `CHANGELOG.md` files and marks only `<app>` as released, and `git log origin/master -1` after the run shows no commit made by the workflow. Record the run URL and the release URL here.
- [ ] 5.7 An image-only release. Setup: an app with a version on neither registry. Trigger: `-f create_github_release=false -f release_<app>=true` with `stack_version` left empty. Pass: both registries hold the new `v<version>` and `latest`, the `release` job is skipped, and `gh release list` and `git ls-remote --tags origin "ascend-ai_*"` show no new entry. Record the run URL here.
- [ ] 5.8 A reused stack version is refused. Setup: the stack version created in 5.6. Trigger: `-f create_github_release=true -f stack_version=<the 5.6 stack version> -f release_<any app>=true`. Pass: the `prepare` job fails with a message that the tag already exists, and `build-and-push` never starts, so no image is pushed. Record the run URL here.
- [ ] 5.9 A superseded run is cancelled. Change: on an open `ci-verify/*` pull request with an app change and a changelog bump, push one commit, wait until its `CI` run is in progress, then push a second commit. Pass: the first run ends as `cancelled` and the second run completes. Record both run URLs here.
- [ ] 5.10 A fork pull request sees no secret. Change: open a pull request to `master` from a fork of the repository with a harmless app change and a changelog bump. Pass: `grep -n "secrets\." .github/workflows/ci.yaml` prints nothing, the `CI` run log shows no repository secret in the `Set up job` section of any job, and no `Release` run was started. Record the run URL here.

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
- [ ] 6.11 An agent-only change runs both contract jobs. Reuse the 5.2 pull request, or open `ci-verify/6-11` with an `apps/ascend-agent/` change and a changelog bump. Pass: `contract-consumer` passes with an empty drift check, then `contract-provider` runs and passes. Record the run URL here.
- [ ] 6.12 An OCR-only change runs both contract jobs. Open `ci-verify/6-12` with a harmless change under `apps/ascend-ocr/src/` and a new top `## [0.3.1]` entry in `apps/ascend-ocr/CHANGELOG.md` (current is `0.3.0`). Pass: both contract jobs run and pass. Record the run URL here.
- [ ] 6.13 A docs-only change skips the contract jobs. Reuse the 5.1 run. Pass: `contract-consumer` and `contract-provider` both show as skipped in that run. Record the run URL here.
- [ ] 6.14 Pact drift fails the consumer. Open `ci-verify/6-14` that changes one expected response field in `apps/ascend-agent/src/test/java/com/lukk/ascend/ai/agent/service/ingestion/client/AscendOcrClientPactTest.java` without regenerating `contracts/pacts/ascend-agent-ascend-ocr.json`, plus an agent changelog bump. Pass: `contract-consumer` fails with an `::error::` line saying the pact is out of date and prints the diff, and `contract-provider` is skipped. Record the run URL here.
- [ ] 6.15 A provider break fails the run. Open `ci-verify/6-15` that renames one field of the job status response under `apps/ascend-ocr/src/`, plus an OCR changelog bump. Pass: `contract-consumer` passes, `contract-provider` fails in `pytest tests/contract --no-cov`, and the whole `CI` run is red. Record the run URL here.
- [ ] 6.16 No secret reaches the contract jobs. In the run from 6.11, open the `Set up job` section of both contract jobs. Pass: neither lists a secret, `grep -n "secrets\." .github/workflows/ci.yaml` prints nothing, and the listed token permissions are `Contents: read` only. Record the run URL here.
