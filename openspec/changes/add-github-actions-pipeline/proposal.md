## Why

AscendAI is a six-service monorepo (ascend-agent, ascend-weather-mcp, ascend-audio-scribe, ascend-web-hunter, ascend-memory, ascend-ocr). Before this change there was **no automated build, test, or release pipeline at all**. Every change was built and image-pushed by hand from the maintainer's laptop. Two concrete consequences:

1. **No PR signal.** Pull requests merged with no proof that the affected service even compiled, let alone passed its unit tests. The first time a regression was noticed was when someone ran `docker compose up` locally and a container restarted in a loop.
2. **Release process was undocumented and unreproducible.** Docker Hub images were pushed manually. There was no record of which per-service version made up a given "state of the stack", and no way to reproduce a previously shipped set of images.

GitHub Actions is the obvious fit: the repo already lives on GitHub, a dynamic matrix maps cleanly onto a six-service monorepo, and `dorny/paths-filter` keeps PR builds fast by only building the services whose paths changed.

## What Changes

This change adds two GitHub Actions workflows under `.github/workflows/`. **All workflow files use the `.yaml` extension** (matching the repo's YAML convention). The two workflows have strictly separate responsibilities, and **neither builds or pushes images automatically**. Releases are manual and operator-driven.

- **`ci.yaml`: build, lint, type check, test and coverage gates. Never pushes images.** Triggers: `pull_request`, `push: branches: [master]`, and `workflow_dispatch`. A `changes` job builds a dynamic matrix holding only the services whose source changed, or every service when `.github/workflows/**` changed. A docs-only PR runs zero builds.
  - Java services run `./gradlew --no-daemon build test`. ascend-agent then runs `jacocoTestCoverageVerification`, which fails below 80 percent instruction coverage.
  - Python services run `pip install -e .[dev]`, `ruff check .`, `mypy src` and `pytest`, and fail below 100 percent branch coverage (set in each module's pytest options, and written out on the command line for ascend-web-hunter and ascend-memory).
  - A `verify-changelog` job runs on pull requests and manual dispatches for every changed app, and fails when the app's `CHANGELOG.md` top `## [x.y.z]` entry is missing, not higher than the base ref's, or empty. A failure there blocks the build jobs. A skipped check does not.
  - An `integration-test` job runs `./gradlew --no-daemon integrationTest` (Testcontainers) for ascend-agent in parallel with the unit-test matrix.
  - This workflow has no secrets and produces no artifacts beyond test reports and the pact file.

- **`ci.yaml`: Agent to OCR contract check.** Two ordered jobs verify the Pact contract between `ascend-agent` (consumer) and `ascend-ocr` (provider) whenever either service, `contracts/**` or the workflows change. `contract-consumer` regenerates `contracts/pacts/ascend-agent-ascend-ocr.json` from `AscendOcrClientPactTest` and fails when it differs from the committed file. `contract-provider` then verifies the committed pact against ascend-ocr with `pytest tests/contract --no-cov`. The pact is committed in the repo, there is no Pact Broker, and no secret is used (ADR-M010).

- **`release.yaml`: manual-only, app-selective, version-from-changelog image build and push.** Triggered **exclusively** via `workflow_dispatch`. Its model is the core of this change:

  - **Each app's `CHANGELOG.md` is the source of truth for its release version.** Developers add a new top `## [x.y.z]` entry in the PR, and `ci.yaml`'s `verify-changelog` enforces it. The release workflow **reads** the top entry and never writes it. The `version` in `build.gradle.kts` or `pyproject.toml` is a label the release workflow does not read.
  - **The dispatch form takes** (a) `create_github_release` (default ticked), (b) a `stack_version` (e.g. `1.1.1`, naming the monorepo release `ascend-ai_1.1.1`), required only when a release is being cut, and (c) a per-app boolean for **which apps to release**.
  - **The bump guard checks the registries, not git history.** For each selected app, after logging in, the workflow looks up `v<version>` on Docker Hub and on GHCR. Found on both fails the run for that app. Found on neither proceeds. Found on exactly one is completed with a warning. A failed lookup fails closed.
  - **Each selected app is built once for `linux/amd64,linux/arm64` and pushed** to `lukk17/ascend-ai-<service>` and `ghcr.io/lukk17/ascend-ai-<service>`, each tagged `v<version>` and `latest`. Apps that are **not** selected are not built and keep their existing images.
  - **After the selected apps push**, when `create_github_release` is ticked, the workflow creates the Git tag `ascend-ai_<stack_version>` and a **GitHub Release** whose body lists the **current changelog version of every app** (released this round or not), marking the released ones, alongside GitHub's auto-generated PR notes. Unticked, it publishes images only and consumes no stack version.
  - **No commits are made by the release workflow.** Versions already live in the committed changelogs, so there is no version-bump-and-commit-back step, no bot commit, and no `[skip ci]` loop.

The change also pins the GitHub repository configuration these workflows depend on:

- **Secrets** (added at `Settings → Secrets and variables → Actions`): `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN` (release only). GHCR uses the automatic `GITHUB_TOKEN`. `ci.yaml` consumes no secrets.
- **Least-privilege permissions**: `ci.yaml` declares `permissions: { contents: read }`. `release.yaml` declares `permissions: { contents: write }` at workflow level (Git tag and GitHub Release), and its `build-and-push` job narrows that to `contents: read` plus `packages: write` (GHCR push).
- **Concurrency keys**: `ci.yaml` cancels superseded runs per ref. `release.yaml` never cancels in progress (a manual release must complete).

## Capabilities

### New Capabilities

- `ci-build-and-test`: every push to master, every pull request, and every manual dispatch SHALL build, lint, type check and test the services whose source paths changed, enforce the coverage floors, require a changelog bump for every changed app on pull requests, run the agent's integration tests, and verify the agent to OCR contract. The workflow SHALL fail if any selected job fails and SHALL push no images.
- `release-versioned-images`: a manual `workflow_dispatch` SHALL build and push Docker images **only for the operator-selected apps**, tagging each at the version read from that app's committed `CHANGELOG.md`, to Docker Hub and GHCR. It SHALL refuse a version already published to both registries, SHALL make no commits, and, when asked to, SHALL cut an `ascend-ai_<stack_version>` Git tag and GitHub Release whose notes list every app's current version.

### Modified Capabilities

(none. This change is purely additive infrastructure)

## Impact

- **New files**:
  - `.github/workflows/ci.yaml`
  - `.github/workflows/release.yaml`
  - `.github/workflows/README.md` (operator notes: secrets, the changelog convention, the app-selection release model, how the bump guard works, image naming and GHCR visibility)
- **Contract tests**: `ci.yaml` gains the `contract-consumer` and `contract-provider` jobs and a `contract` paths filter. New files `contracts/README.md` and `docs/architecture/decisions/ADR-M010-consumer-driven-contract-in-repo.md`, a `.gitattributes` rule keeping `contracts/pacts/*.json` on LF, and a Contract tests section in `.github/workflows/README.md`. The pact file itself and the two contract tests are written in `apps/ascend-agent` and `apps/ascend-ocr`, outside this change.
- **Per-app changelogs**: each app carries `apps/<app>/CHANGELOG.md` with `## [x.y.z]` entries. The workflows read them and never edit them.
- **No source changes** to any of the six services from this change. Each `Dockerfile` is consumed as-is.
- **Developer-workflow convention (enforced on pull requests)**: adding a new top `## [x.y.z]` entry to an app's `CHANGELOG.md` in every PR that touches the app. `verify-changelog` fails the PR otherwise. The release operator then selects which apps to ship.
- **No changes** to `compose.yaml` or `compose.ascend-web-hunter.yaml`.
- **Not part of this change**: `.github/workflows/e2e.yaml`, which runs the free end-to-end specs, is documented in `.github/workflows/README.md` but is owned by no OpenSpec change.
- **Repository settings**: the two Docker Hub secrets, and making each GHCR package public once after its first push. No branch-protection or auto-delete-branches recommendations (maintainer's policy, out of scope).
- **Backwards compat**: fully additive. Existing manual `./gradlew build` and `docker push` flows still work.
