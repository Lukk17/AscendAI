## Context

AscendAI is a six-service monorepo with two Java/Gradle services (`AscendAgent`, `WeatherMCP`) and four Python/pyproject services (`AudioScribe`, `AscendWebSearch`, `AscendMemory`, `PaddleOCR`). Each has its own `Dockerfile`. The compose files at the repo root (`docker-compose.yaml`, `ascend-scrapper.docker-compose.yaml`) wire them together with the data-layer prerequisites (PostgreSQL, Redis, Qdrant, MinIO) which are intentionally external in production.

There is no CI today. The maintainer builds and pushes Docker Hub images by hand (`lukk17/<service>:<tag>`). PRs merge with no automated proof of build or test correctness. This change adds two GitHub Actions workflows to close those gaps.

## Goals / Non-Goals

**Goals:**

- Every push to master, every PR, and every manual dispatch runs the affected service's build + unit tests in parallel with caches.
- A manual `workflow_dispatch` with a version input produces a complete, reproducible multi-arch image set on Docker Hub plus a GitHub Release — with no further manual steps.
- Secrets stay in GitHub's encrypted store; nothing is checked into the repo.
- Workflows are least-privilege: `contents: read` on CI; `contents: write` only on the release flow (for the GitHub Release).
- PR builds are fast: a docs-only PR runs zero matrix entries; a single-service PR runs one.

**Non-Goals:**

- No changes to any service's source code. The pipeline consumes existing `Dockerfile`s and build files as-is.
- No changes to `docker-compose.yaml`. The pipeline does not bring up the application stack.
- No replacement for the local dev loop. `./gradlew bootRun` and `uvicorn ... --reload` keep working unchanged.
- No e2e/Bruno-in-CI run. End-to-end validation happens locally (see `AscendAgent/e2e/`) and via the manual smoke checklist after each release. The earlier draft included an `e2e.yaml` workflow; user dropped it as out of scope.
- No deployment. This change builds and tags images; rolling them out to a target environment is a separate concern.
- No code coverage gating, no SAST, no DAST, no Dependabot setup, no sticky-PR-comment on release. Those are follow-up changes.
- No branch-protection / auto-delete-branches recommendations from this change. Those are GitHub repo policy decisions for the maintainer, not CI/CD scope.

## Decisions

### D1 — Two workflows, one responsibility each

`ci.yaml` and `release.yaml`. Each does exactly one job. This keeps each workflow file readable end-to-end, makes triggers obvious, and isolates failure surfaces (a Docker Hub outage cannot block a PR).

The `.yaml` extension is used everywhere — matching the rest of the repo's YAML convention (`docker-compose.yaml`, `application.yaml`, etc.). `.yml` works too but mixed extensions are noise.

**Alternative considered:** one mega-workflow with conditional jobs. Rejected — harder to reason about, harder to grant least-privilege permissions per job.

### D2 — Path-filtered matrix per service

`ci.yaml` uses `dorny/paths-filter@v3` to compute six boolean outputs (`ascend-agent`, `weather-mcp`, `audio-scribe`, `ascend-web-search`, `ascend-memory`, `paddle-ocr`), one per service. Each output is true if files under that service's directory changed. The matrix job's `if:` consumes the filter output to skip the entry if untouched.

```yaml
filters: |
  ascend-agent:
    - 'AscendAgent/**'
  audio-scribe:
    - 'AudioScribe/**'
  # ...etc
```

A docs-only PR runs zero builds. A change touching `AscendAgent/` runs only the AscendAgent build. A change to a shared CI file (`.github/workflows/ci.yaml` itself) re-runs everything via a wildcard fallback filter (`workflows`).

### D3 — Java vs Python jobs are separate matrix entries with separate setup

Each matrix entry declares `language: java | python`, `service: <name>`, `path: <subdir>`. The job conditionally sets up the right toolchain:

- **Java**: `actions/setup-java@v4` with `temurin@21`, then `gradle/actions/setup-gradle@v3` (handles Gradle's wrapper validation, dep cache, build cache). Run `./gradlew --no-daemon build test` from `${{ matrix.path }}`.
- **Python**: `actions/setup-python@v5` with the per-service version (`3.11` for AudioScribe/AscendMemory/PaddleOCR, `3.12` for AscendWebSearch) and `cache: pip`. Run `pip install -e .[dev]` then `pytest` from `${{ matrix.path }}`.

**Alternative considered:** Detect language from `Dockerfile` or presence of `build.gradle.kts` vs `pyproject.toml`. Rejected — explicit matrix is cheaper to read and harder to break by accident.

### D4 — Release trigger is manual `workflow_dispatch` only

`release.yaml` is triggered exclusively via the Actions UI, with a required `version` input (string, e.g., `1.2.3` or `1.2.3-rc.1`). No tag trigger. The maintainer chooses when to ship and types the version directly.

**Why not tag-triggered?** The maintainer prefers manual control over release timing — pushing a Git tag locally and watching it auto-release felt opaque. Manual dispatch keeps the "I'm shipping right now" gesture explicit and reviewable in the Actions tab. There's still a Git tag — `release.yaml` creates `v<version>` after a successful run via `softprops/action-gh-release` so history stays clean.

**Alternative considered:** Both tag-triggered and manual. Rejected for simplicity — one trigger source means one mental model.

### D5 — Version sync for releases: build-time override, never committed

When `release.yaml` runs with input `version=1.2.3`, the repo's `build.gradle.kts` may still say `version = "1.0.0"` and `pyproject.toml` may still say `version = "0.1.0"` — that is fine and intentional.

- **Java**: `./gradlew -Pversion=1.2.3 bootJar` — Gradle's standard convention; `version` in `build.gradle.kts` becomes the **default** that the `-P` overrides.
- **Python**: pass `--build-arg BUILD_VERSION=1.2.3` to `docker build`. The Dockerfile sets a `LABEL org.opencontainers.image.version=$BUILD_VERSION` and (where the Python service exposes a version, e.g., via `/version`) writes it to a `VERSION` file at image build time. The `pyproject.toml` `version` field is left alone; the source of truth for shipped images is the workflow input.

This keeps Git history clean — releases produce no automated source-edit commits, no diff churn, no `[skip ci]` loops. The maintainer bumps `pyproject.toml` / `build.gradle.kts` manually only when they want the local dev version to advance.

**Alternative considered:** Have `release.yaml` rewrite the version files in-place, commit, push, then build. Rejected — pollutes Git history with bot commits and adds a permission requirement.

### D6 — Multi-arch builds with QEMU + Buildx + GHA cache

```yaml
- uses: docker/setup-qemu-action@v3
- uses: docker/setup-buildx-action@v3
- uses: docker/build-push-action@v6
  with:
    context: ./AscendAgent
    platforms: linux/amd64,linux/arm64
    push: true
    tags: |
      lukk17/ascend-agent:1.2.3
      lukk17/ascend-agent:latest
    cache-from: type=gha,scope=ascend-agent
    cache-to: type=gha,scope=ascend-agent,mode=max
    build-args: |
      BUILD_VERSION=1.2.3
```

Each service uses its own `scope` so caches do not collide. `mode=max` caches all layers (not just the final stage), which is what makes the Python services' multi-stage CUDA / Paddle builds tolerable on every run.

### D7 — `:latest` only on stable semver

```yaml
- id: tag
  run: |
    raw="${{ inputs.version }}"
    echo "version=$raw" >> $GITHUB_OUTPUT
    if [[ "$raw" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
      echo "is_stable=true" >> $GITHUB_OUTPUT
    else
      echo "is_stable=false" >> $GITHUB_OUTPUT
    fi
```

The Buildx step's `tags:` block conditionally includes `lukk17/<service>:latest` only when `steps.tag.outputs.is_stable == 'true'`. So `1.2.3-rc.1` ships `lukk17/<service>:1.2.3-rc.1` but does NOT touch `:latest`.

### D8 — Concurrency keys

- `ci.yaml`: `concurrency: { group: ci-${{ github.ref }}, cancel-in-progress: true }`. Force-pushing to a PR cancels the prior CI run.
- `release.yaml`: `concurrency: { group: release-${{ github.event.inputs.version }}, cancel-in-progress: false }`. A manual release run is final; never cancel a half-pushed image set.

### D9 — Permissions blocks (least privilege)

Each workflow declares an explicit `permissions:` block at the top, overriding the repo default:

- `ci.yaml`: `permissions: { contents: read }`
- `release.yaml`: `permissions: { contents: write, packages: write }` (write only because `softprops/action-gh-release` needs to create the GitHub Release / tag)

### D10 — Trigger summary

| Trigger | `ci.yaml` | `release.yaml` |
|---|:---:|:---:|
| `pull_request` (any branch) | ✓ | – |
| `push` to `master` | ✓ | – |
| `workflow_dispatch` (manual) | ✓ | ✓ (only trigger) |

No tag trigger anywhere. No nightly cron anywhere.

## Risks / Trade-offs

- **[Risk]** Multi-arch Python builds (especially PaddleOCR with PaddlePaddle) are slow and may time out on free-tier runners → **Mitigation**: aggressive `cache-to: type=gha,mode=max` per-service scope; first build is slow, subsequent builds reuse layers. If still slow, fall back to `linux/amd64` only and revisit arm64 later.
- **[Risk]** GHA cache eviction policy is per-branch and capped at 10 GB per repo → **Mitigation**: scope caches per service so a single hot service's cache cannot evict the others'. Document the cache size budget in `.github/workflows/README.md`.
- **[Risk]** A Docker Hub outage during `release.yaml` produces a partial image set (e.g., 4 of 6 services pushed) → **Mitigation**: matrix uses `fail-fast: false` so all six services attempt. Re-running the workflow with the same `version` input re-pushes; Docker Hub is content-addressed for layers so this is safe and idempotent.
- **[Risk]** Secrets leak via a malicious PR from a fork → **Mitigation**: secrets are only available to workflows running on the base repo (default GitHub behavior for forked PRs). `release.yaml` does not run on `pull_request` events at all. `ci.yaml` runs on `pull_request` but uses zero secrets.
- **[Trade-off]** No e2e in CI, no coverage gating, no SAST, no Dependabot, no sticky PR comment on release. They are valuable but each has its own design surface; pulling them in here would balloon the scope. Tracked as follow-ups in `.github/workflows/README.md`.

## Migration Plan

No migration. This change is purely additive — two new workflow files plus an operator README. Rollback is `git revert` of the same files. No service code is touched. No `docker-compose.yaml` change. Existing manual release flows continue to work as-is.

After merge, the maintainer:

1. Adds the two Docker Hub secrets (`DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`) under `Settings → Secrets and variables → Actions`.
2. Cuts the first manual release: Actions tab → `Release` → `Run workflow` → enter `0.1.0` → confirm. Watches the run complete; verifies `lukk17/<service>:0.1.0` and `:latest` exist on Docker Hub for all six services.
