## Why

AscendAI is a six-service monorepo (AscendAgent, WeatherMCP, AudioScribe, AscendWebSearch, AscendMemory, PaddleOCR) and today there is **no automated build, test, or release pipeline at all**. Every change is built and image-pushed by hand from the maintainer's laptop. Three concrete consequences:

1. **No PR signal.** Pull requests merge with no proof that the affected service even compiles, let alone passes its unit tests. The first time a regression is noticed is when someone runs `docker compose up` locally and a container restarts in a loop.
2. **Release process is undocumented and unreproducible.** Docker Hub images at `lukk17/<service>:<tag>` are pushed manually; the version inside `build.gradle.kts` / `pyproject.toml` and the image tag drift, and there is no way to reproduce a previously-shipped version from a Git SHA.
3. **No end-to-end smoke run.** The Bruno collection at `docs/api/request/AscendAI/ascend-agent/testing` is the de-facto integration test, but it is only run by hand on the maintainer's box. There is no nightly proof that the full stack still works against the latest images.

GitHub Actions is the obvious fit: the repo already lives on GitHub, the runners are free for public repos and cheap for private ones, the matrix strategy maps cleanly onto a six-service monorepo, and `dorny/paths-filter` lets us keep PR builds fast by only running the matrix entries whose paths actually changed.

## What Changes

This change adds three GitHub Actions workflows under `.github/workflows/`, plus the secrets, permissions, and concurrency-key conventions needed to run them safely.

- **`ci.yml` — Build + test on every push and PR.** Matrix per service. Java services (`AscendAgent`, `WeatherMCP`) run `./gradlew build test` with `gradle/actions/setup-gradle@v3` for cache reuse. Python services (`AudioScribe`, `AscendWebSearch`, `AscendMemory`, `PaddleOCR`) run `pip install -e .[dev]` + `pytest` with `actions/setup-python@v5` and pip caching. `dorny/paths-filter@v3` selects only the matrix entries whose paths changed so a one-line README edit does not run six full builds. Workflow fails if any selected matrix entry fails. Concurrency key cancels superseded PR builds.
- **`release.yml` — Versioned multi-arch image build + Docker Hub push, triggered on Git tag `v*.*.*`.** The version is derived from the tag (strip leading `v` → `1.2.3`). Each service builds a multi-arch image (`linux/amd64`, `linux/arm64`) via `docker/setup-qemu-action` + `docker/setup-buildx-action`, with GHA cache reuse. The version is **passed as a build property override, never committed back to the repo** — Java services build with `-Pversion=1.2.3`, Python services build with a `BUILD_VERSION` env var consumed by the Dockerfile. Images are tagged `lukk17/<service>:<version>`; the `:latest` tag is added only when the tag is a stable semver release (no `-rc`, `-beta`, `-alpha` suffix). Login uses `${{ secrets.DOCKERHUB_USERNAME }}` / `${{ secrets.DOCKERHUB_TOKEN }}`. After all six images push, a GitHub Release is created at the same tag with auto-generated notes from PR titles since the previous tag.
- **`e2e.yml` — End-to-end smoke run, triggered after `ci.yml` passes on `master` and nightly via cron.** Spins up the data-layer prerequisites (Postgres, Redis, Qdrant, MinIO) as GitHub Actions service containers, then runs `docker compose up -d --build` to bring up the application stack. Installs the Bruno CLI (`npm install -g @usebruno/cli`) and runs `bru run docs/api/request/AscendAI/ascend-agent/testing --env ascend-local`. Bruno output is uploaded as a workflow artifact regardless of pass/fail. Workflow fails if any Bruno test fails.

The change also pins the GitHub repository configuration these workflows depend on:

- **Secrets** the maintainer must add at `Settings → Secrets and variables → Actions`: `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN` (release only); `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `MINIMAX_API_KEY`, `HF_TOKEN`, `NGROK_AUTHTOKEN` (e2e only — the providers/services the Bruno collection actually exercises at runtime).
- **Permissions blocks** are least-privilege per workflow: `ci.yml` and `e2e.yml` declare `permissions: { contents: read }`; `release.yml` declares `permissions: { contents: write, packages: write }` because it cuts a GitHub Release.
- **Concurrency keys** — `ci.yml` and `e2e.yml` use `${{ github.workflow }}-${{ github.ref }}` with `cancel-in-progress: true` so a force-push to a PR cancels the prior run. `release.yml` does NOT cancel in progress (a tag push is final and must complete).

## Capabilities

### New Capabilities

- `ci-build-and-test` — every push and pull request that touches a service's source paths SHALL run that service's build + unit tests on a matrix runner; the workflow SHALL fail if any selected matrix entry fails.
- `release-versioned-images` — a Git tag matching `v*.*.*` SHALL produce a multi-arch Docker image at `lukk17/<service>:<version>` for every service in the monorepo, with `:latest` added only for stable semver tags, and a GitHub Release SHALL be cut at the tag with auto-generated notes.
- `e2e-pipeline` — the application stack SHALL be brought up end-to-end and exercised by the Bruno collection on every successful master CI run and on a nightly cron schedule, with results uploaded as a workflow artifact.

### Modified Capabilities

(none — this change is purely additive infrastructure)

## Impact

- **New files**:
  - `.github/workflows/ci.yml`
  - `.github/workflows/release.yml`
  - `.github/workflows/e2e.yml`
  - `.github/workflows/README.md` (operator notes: required secrets, how to cut a release, how to debug a failed e2e run)
- **No code changes** to any of the six services. Each service's existing `Dockerfile` and `build.gradle.kts` / `pyproject.toml` is consumed as-is. Version override is a build-time property; nothing is committed back to the repo.
- **No changes** to `docker-compose.yaml` or `ascend-scrapper.docker-compose.yaml`. The e2e workflow consumes them as-is.
- **Repository settings** the maintainer must configure manually (documented in `.github/workflows/README.md`):
  - Secrets listed above.
  - Branch protection on `master` recommending "CI" status check be required before merge.
  - Optional: enable "Automatically delete head branches" for cleanliness.
- **Runtime cost**: GitHub-hosted runners. Public repo → free. Private repo → ~2,000 minutes/month included on the Free plan, sufficient for the matrix sizes here.
- **Backwards compat**: fully additive. Existing manual `./gradlew build` and `docker push` flows still work. The maintainer can ignore the workflows entirely if they want.
