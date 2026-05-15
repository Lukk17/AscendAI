## Why

AscendAI is a six-service monorepo (AscendAgent, WeatherMCP, AudioScribe, AscendWebSearch, AscendMemory, PaddleOCR) and today there is **no automated build, test, or release pipeline at all**. Every change is built and image-pushed by hand from the maintainer's laptop. Two concrete consequences:

1. **No PR signal.** Pull requests merge with no proof that the affected service even compiles, let alone passes its unit tests. The first time a regression is noticed is when someone runs `docker compose up` locally and a container restarts in a loop.
2. **Release process is undocumented and unreproducible.** Docker Hub images at `lukk17/<service>:<tag>` are pushed manually; the version inside `build.gradle.kts` / `pyproject.toml` and the image tag drift, and there is no way to reproduce a previously-shipped version from a Git SHA.

GitHub Actions is the obvious fit: the repo already lives on GitHub, the runners are free for public repos and cheap for private ones, the matrix strategy maps cleanly onto a six-service monorepo, and `dorny/paths-filter` lets us keep PR builds fast by only running the matrix entries whose paths actually changed.

## What Changes

This change adds two GitHub Actions workflows under `.github/workflows/`, plus the secrets and concurrency-key conventions needed to run them safely. **All workflow files use the `.yaml` extension** (matching the rest of the repo's YAML convention).

- **`ci.yaml` — Build + test on master pushes, PRs, and manual dispatch.** Triggers: `push: branches: [master]`, `pull_request`, `workflow_dispatch`. Does NOT run on every push to feature branches — feature work runs CI only via PR. Matrix per service. Java services (`AscendAgent`, `WeatherMCP`) run `./gradlew build test` with `gradle/actions/setup-gradle@v3` for cache reuse. Python services (`AudioScribe`, `AscendWebSearch`, `AscendMemory`, `PaddleOCR`) run `pip install -e .[dev]` + `pytest` with `actions/setup-python@v5` and pip caching. `dorny/paths-filter@v3` selects only the matrix entries whose paths changed so a one-line README edit does not run six full builds. Workflow fails if any selected matrix entry fails. Concurrency key cancels superseded PR builds.
- **`release.yaml` — Manual-only versioned multi-arch image build + Docker Hub push.** Triggered exclusively via `workflow_dispatch` with a required `version` input (e.g. `1.2.3` or `1.2.3-rc.1`). No tag trigger — the maintainer chooses when to ship. Each service builds a multi-arch image (`linux/amd64`, `linux/arm64`) via `docker/setup-qemu-action` + `docker/setup-buildx-action`, with GHA cache reuse. The version is **passed as a build property override, never committed back to the repo** — Java services build with `-Pversion=<version>`, Python services build with a `BUILD_VERSION` env var consumed by the Dockerfile. Images are tagged `lukk17/<service>:<version>`; the `:latest` tag is added only when the version is a stable semver (no `-rc`, `-beta`, `-alpha` suffix). Login uses `${{ secrets.DOCKERHUB_USERNAME }}` / `${{ secrets.DOCKERHUB_TOKEN }}`. After all six images push, a GitHub Release is created at the chosen version with auto-generated notes from PR titles since the previous release.

The change also pins the GitHub repository configuration these workflows depend on:

- **Secrets** the maintainer must add at `Settings → Secrets and variables → Actions`: `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN` (release only). No CI-time secrets required (`ci.yaml` consumes none).
- **Permissions blocks** are least-privilege per workflow: `ci.yaml` declares `permissions: { contents: read }`; `release.yaml` declares `permissions: { contents: write, packages: write }` because it cuts a GitHub Release.
- **Concurrency keys** — `ci.yaml` uses `${{ github.workflow }}-${{ github.ref }}` with `cancel-in-progress: true` so a force-push to a PR cancels the prior run. `release.yaml` does NOT cancel in progress (a manual release is final and must complete).

## Capabilities

### New Capabilities

- `ci-build-and-test` — every push to master, every pull request, and every manual dispatch SHALL run the matrix build + unit tests for the services whose source paths changed; the workflow SHALL fail if any selected matrix entry fails.
- `release-versioned-images` — a manual `workflow_dispatch` invocation with a `version` input SHALL produce a multi-arch Docker image at `lukk17/<service>:<version>` for every service in the monorepo, with `:latest` added only for stable semver versions, and a GitHub Release SHALL be cut at the same version with auto-generated notes.

### Modified Capabilities

(none — this change is purely additive infrastructure)

## Impact

- **New files**:
  - `.github/workflows/ci.yaml`
  - `.github/workflows/release.yaml`
  - `.github/workflows/README.md` (operator notes: required Docker Hub secrets, how to cut a release manually)
- **No code changes** to any of the six services. Each service's existing `Dockerfile` and `build.gradle.kts` / `pyproject.toml` is consumed as-is. Version override is a build-time property; nothing is committed back to the repo.
- **No changes** to `docker-compose.yaml` or `ascend-scrapper.docker-compose.yaml`.
- **Repository settings**: only the two Docker Hub secrets above. **No branch-protection or auto-delete-branches recommendations** — those are the maintainer's preference, not part of CI/CD scope.
- **Runtime cost**: GitHub-hosted runners. Public repo → free. Private repo → ~2,000 minutes/month included on the Free plan, sufficient for the matrix sizes here.
- **Backwards compat**: fully additive. Existing manual `./gradlew build` and `docker push` flows still work. The maintainer can ignore the workflows entirely if they want.
