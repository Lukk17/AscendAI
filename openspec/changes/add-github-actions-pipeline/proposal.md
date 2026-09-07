## Why

AscendAI is a six-service monorepo (ascend-ai-agent, ascend-weather-mcp, ascend-audio-scribe, ascend-web-hunter, AscendMemory, ascend-ocr) and today there is **no automated build, test, or release pipeline at all**. Every change is built and image-pushed by hand from the maintainer's laptop. Two concrete consequences:

1. **No PR signal.** Pull requests merge with no proof that the affected service even compiles, let alone passes its unit tests. The first time a regression is noticed is when someone runs `docker compose up` locally and a container restarts in a loop.
2. **Release process is undocumented and unreproducible.** Docker Hub images at `lukk17/<service>:<tag>` are pushed manually; there is no record of which per-service version made up a given "state of the stack", and no way to reproduce a previously-shipped set of images.

GitHub Actions is the obvious fit: the repo already lives on GitHub, the matrix strategy maps cleanly onto a six-service monorepo, and `dorny/paths-filter` keeps PR builds fast by only building the services whose paths changed.

## What Changes

This change adds two GitHub Actions workflows under `.github/workflows/`. **All workflow files use the `.yaml` extension** (matching the repo's YAML convention). The two workflows have strictly separate responsibilities, and **neither builds or pushes images automatically** — releases are manual and operator-driven.

- **`ci.yaml` — Build + test only. Never pushes images.** Triggers: `pull_request`, `push: branches: [master]`, and `workflow_dispatch`. A path-filtered matrix builds and unit-tests only the services whose source changed (a docs-only PR runs zero builds). Java services run `./gradlew build test`; Python services run `pip install -e .[dev]` + `pytest`. This workflow has no Docker Hub credentials and produces no artifacts beyond test reports.

- **`release.yaml` — Manual-only, app-selective, version-from-manifest image build + push.** Triggered **exclusively** via `workflow_dispatch`. Its model is the core of this change:

  - **Per-app versions are the source of truth and are bumped by developers in the PR**, in each app's own manifest (`build.gradle.kts` `version` for the two Java services, `pyproject.toml` `[project].version` for the four Python services). The release workflow **reads** these versions; it never sets, overrides, or commits them.
  - **The dispatch form takes** (a) a `stack_version` (e.g. `1.1.1`, naming the monorepo release `ascend-ai_1.1.1`), and (b) a per-app boolean for **which apps to release**.
  - **For each selected app the workflow first guards versioning**: it compares the app's current manifest version against that app's version at the **previous `ascend-ai_*` release tag**. If a selected app's version was **not** bumped since the last stack release, the workflow **fails before pushing anything**. (On the very first release there is no previous tag, so the guard is skipped.)
  - **Each selected app is then built and pushed** to Docker Hub as `lukk17/<service>:<that app's manifest version>` plus `lukk17/<service>:latest`. Apps that are **not** selected are not built and keep their existing images and versions.
  - **After the selected apps push**, the workflow creates the Git tag `ascend-ai_<stack_version>` and a **GitHub Release** whose body lists the **current version of every app** (released this round or not) — e.g. "ascend-ai_1.1.1 — ascend-ai-agent 1.3.0, ascend-weather-mcp 1.0.0, ascend-web-hunter 1.2.0, …" — alongside GitHub's auto-generated PR notes. This GitHub Release **is** the changelog: it records the full per-app version snapshot for the monorepo release.
  - **No commits are made by the release workflow.** Because versions already live in the manifests (committed by the developer in the PR), the release is complete the moment it runs — no version-bump-and-commit-back step, no bot commit, no `[skip ci]` loop.

The change also pins the GitHub repository configuration these workflows depend on:

- **Secrets** (added at `Settings → Secrets and variables → Actions`): `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN` (release only). `ci.yaml` consumes no secrets.
- **Least-privilege permissions**: `ci.yaml` declares `permissions: { contents: read }`; `release.yaml` declares `permissions: { contents: write }` (only to create the Git tag + GitHub Release).
- **Concurrency keys**: `ci.yaml` cancels superseded PR runs; `release.yaml` never cancels in progress (a manual release must complete).

## Capabilities

### New Capabilities

- `ci-build-and-test` — every push to master, every pull request, and every manual dispatch SHALL build + unit-test the services whose source paths changed; the workflow SHALL fail if any selected matrix entry fails and SHALL push no images.
- `release-versioned-images` — a manual `workflow_dispatch` SHALL build and push Docker images **only for the operator-selected apps**, tagging each at the version read from that app's committed manifest; SHALL fail if a selected app's manifest version was not bumped since the previous `ascend-ai_*` release; SHALL make no commits; and SHALL cut a `ascend-ai_<stack_version>` Git tag + GitHub Release whose notes list every app's current version.

### Modified Capabilities

(none — this change is purely additive infrastructure)

## Impact

- **New files**:
  - `.github/workflows/ci.yaml`
  - `.github/workflows/release.yaml`
  - `.github/workflows/README.md` (operator notes: secrets, the per-app-version + app-selection release model, how the bump guard works)
- **No source changes** to any of the six services. Each `Dockerfile`, `build.gradle.kts`, and `pyproject.toml` is consumed as-is; the image version is whatever the committed manifest already says. **The workflows never edit or commit a version.**
- **Developer-workflow convention (documented, not code-enforced)**: bumping an app's `version` in its manifest within a PR is what makes that app eligible for the next release. The release operator then selects which already-bumped apps to ship.
- **No changes** to `docker-compose.yaml` or `ascend-scrapper.docker-compose.yaml`.
- **Repository settings**: only the two Docker Hub secrets. No branch-protection or auto-delete-branches recommendations (maintainer's policy, out of scope).
- **Backwards compat**: fully additive. Existing manual `./gradlew build` / `docker push` flows still work; the workflows can be ignored entirely.
