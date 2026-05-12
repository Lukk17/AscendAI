## Context

AscendAI is a six-service monorepo with two Java/Gradle services (`AscendAgent`, `WeatherMCP`) and four Python/pyproject services (`AudioScribe`, `AscendWebSearch`, `AscendMemory`, `PaddleOCR`). Each has its own `Dockerfile`. The compose files at the repo root (`docker-compose.yaml`, `ascend-scrapper.docker-compose.yaml`) wire them together with the data-layer prerequisites (PostgreSQL, Redis, Qdrant, MinIO) which are intentionally external in production.

There is no CI today. The maintainer builds and pushes Docker Hub images by hand (`lukk17/<service>:<tag>`). PRs merge with no automated proof of build or test correctness. The Bruno collection at `docs/api/request/AscendAI/ascend-agent/testing` is the de-facto smoke test but only the maintainer runs it. This change adds three GitHub Actions workflows to close those gaps.

## Goals / Non-Goals

**Goals:**
- Every push and PR that touches a service's source files runs that service's build + unit tests, in parallel, with caches.
- A Git tag `v*.*.*` produces a complete, reproducible multi-arch image set on Docker Hub plus a GitHub Release — with no manual steps.
- Master commits and nightly cron trigger an end-to-end smoke run of the full stack against the Bruno collection.
- Secrets stay in GitHub's encrypted store; nothing is checked into the repo.
- Workflows are least-privilege: `contents: read` everywhere except `release.yml`.
- PR builds are fast: a docs-only PR runs zero matrix entries; a single-service PR runs one.

**Non-Goals:**
- No changes to any service's source code. The pipeline consumes existing `Dockerfile`s and build files as-is.
- No changes to `docker-compose.yaml`. The e2e workflow uses it as a black box.
- No replacement for the local dev loop. `./gradlew bootRun` and `uvicorn ... --reload` keep working unchanged.
- No deployment. This change builds and tags images; rolling them out to a target environment is a separate concern.
- No code coverage gating, no SAST, no DAST, no Dependabot setup. Those are follow-up changes.

## Decisions

### D1 — Three workflows, one responsibility each

`ci.yml`, `release.yml`, `e2e.yml`. Each does exactly one job. This keeps each workflow file readable end-to-end, makes triggers obvious, and isolates failure surfaces (a flaky e2e run cannot block a release tag, a Docker Hub outage cannot block a PR).

**Alternative considered:** one mega-workflow with conditional jobs. Rejected — harder to reason about, harder to grant least-privilege permissions per job, harder to retry just the failed concern.

### D2 — Path-filtered matrix per service

`ci.yml` uses `dorny/paths-filter@v3` to compute six boolean outputs (`ascend-agent`, `weather-mcp`, `audio-scribe`, `ascend-web-search`, `ascend-memory`, `paddle-ocr`), one per service. Each output is true if files under that service's directory changed. The matrix job's `if:` consumes the filter output to skip the entry if untouched.

```yaml
filters: |
  ascend-agent:
    - 'AscendAgent/**'
  audio-scribe:
    - 'AudioScribe/**'
  # ...etc
```

A docs-only PR runs zero builds. A change touching `AscendAgent/` runs only the AscendAgent build. A change to a shared file (e.g., root `README.md`) runs zero builds; a change to a shared CI file (`.github/workflows/ci.yml` itself) re-runs everything via a wildcard fallback filter (`workflows`).

### D3 — Java vs Python jobs are separate matrix entries with separate setup

Each matrix entry declares `language: java | python`, `service: <name>`, `path: <subdir>`. The job conditionally sets up the right toolchain:

- **Java**: `actions/setup-java@v4` with `temurin@21`, then `gradle/actions/setup-gradle@v3` (handles Gradle's wrapper validation, dep cache, build cache). Run `./gradlew --no-daemon build test` from `${{ matrix.path }}`.
- **Python**: `actions/setup-python@v5` with the per-service version (`3.11` for AudioScribe/AscendMemory/PaddleOCR, `3.12` for AscendWebSearch) and `cache: pip`. Run `pip install -e .[dev]` then `pytest` from `${{ matrix.path }}`.

**Alternative considered:** Detect language from `Dockerfile` or presence of `build.gradle.kts` vs `pyproject.toml`. Rejected — explicit matrix is cheaper to read and harder to break by accident.

### D4 — Version sync for releases: build-time override, never committed

When `release.yml` runs against tag `v1.2.3`, the version is extracted as `1.2.3` (`tag_name#v`). The repo's `build.gradle.kts` may still say `version = "1.0.0"` and `pyproject.toml` may still say `version = "0.1.0"` — that is fine and intentional.

- **Java**: `./gradlew -Pversion=1.2.3 bootJar` — Gradle's standard convention; `version` in `build.gradle.kts` becomes the **default** that the `-P` overrides.
- **Python**: pass `--build-arg BUILD_VERSION=1.2.3` to `docker build`. The Dockerfile sets a `LABEL org.opencontainers.image.version=$BUILD_VERSION` and (where the Python service exposes a version, e.g., via `/version`) writes it to a `VERSION` file at image build time. The `pyproject.toml` `version` field is left alone; the source of truth for shipped images is the Git tag.

This keeps Git history clean — releases produce no automated commits, no diff churn, no `[skip ci]` loops, no risk of two runners racing to write `version = "..."`. The maintainer bumps `pyproject.toml` / `build.gradle.kts` manually only when they want the local dev version to advance.

**Alternative considered:** Have `release.yml` rewrite the version files in-place, commit, push, then build. Rejected — pollutes Git history with bot commits, adds a permission requirement (`contents: write` against `master`), and creates a window where the local dev version disagrees with `master`.

### D5 — Multi-arch builds with QEMU + Buildx + GHA cache

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

### D6 — `:latest` only on stable semver

```yaml
- id: tag
  run: |
    raw="${GITHUB_REF#refs/tags/v}"
    echo "version=$raw" >> $GITHUB_OUTPUT
    if [[ "$raw" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
      echo "is_stable=true" >> $GITHUB_OUTPUT
    else
      echo "is_stable=false" >> $GITHUB_OUTPUT
    fi
```

The Buildx step's `tags:` block conditionally includes `lukk17/<service>:latest` only when `steps.tag.outputs.is_stable == 'true'`. So `v1.2.3-rc.1` ships `lukk17/<service>:1.2.3-rc.1` but does NOT touch `:latest`.

### D7 — E2E uses GHA service containers for the data layer

`postgres:16`, `redis:7-alpine`, `qdrant/qdrant:latest`, and `minio/minio:latest` (with the `server /data` command and a healthcheck) are declared under `services:` in the e2e job. Compose then brings up the application stack, which connects to the service containers via the runner's localhost.

```yaml
services:
  postgres:
    image: postgres:16
    env:
      POSTGRES_DB: ascend_ai
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: local
    ports: ['5432:5432']
    options: >-
      --health-cmd pg_isready
      --health-interval 10s
      --health-timeout 5s
      --health-retries 5
```

**Alternative considered:** Bring everything up via `docker compose up` including the data layer. Rejected for two reasons: (a) the production architecture explicitly externalizes the data layer (see root AGENTS.md "External Prerequisites" table) so the e2e test should match; (b) GHA service containers handle healthchecks and shutdown cleanup natively.

### D8 — Bruno CLI artifact upload

After `bru run` finishes (success or failure), the run output is uploaded with `actions/upload-artifact@v4` named `bruno-results-${{ github.run_number }}`. This means a failed nightly e2e gives the maintainer a downloadable artifact with the per-request HTTP traces and assertion diffs, no need to reproduce locally.

### D9 — Concurrency keys

- `ci.yml`: `concurrency: { group: ci-${{ github.ref }}, cancel-in-progress: true }`. Force-pushing to a PR cancels the prior CI run.
- `e2e.yml`: `concurrency: { group: e2e-${{ github.ref }}, cancel-in-progress: true }`. The nightly cron and a master push will not run e2e simultaneously.
- `release.yml`: `concurrency: { group: release-${{ github.ref }}, cancel-in-progress: false }`. A tag push is final; never cancel a half-pushed image set.

### D10 — Permissions blocks (least privilege)

Each workflow declares an explicit `permissions:` block at the top, overriding the repo default (which is permissive on legacy repos):

- `ci.yml`: `permissions: { contents: read }`
- `e2e.yml`: `permissions: { contents: read }`
- `release.yml`: `permissions: { contents: write, packages: write }` (write only because `softprops/action-gh-release` needs to create the GitHub Release; no other step writes anything in this repo)

### D11 — Trigger summary

| Trigger | `ci.yml` | `release.yml` | `e2e.yml` |
|---|:---:|:---:|:---:|
| `pull_request` (any branch) | ✓ | – | – |
| `push` to `master` | ✓ | – | ✓ (after CI succeeds, via `workflow_run`) |
| `push` tag `v*.*.*` | – | ✓ | – |
| `schedule` (nightly cron) | – | – | ✓ |
| `workflow_dispatch` (manual) | ✓ | ✓ | ✓ |

`e2e.yml`'s `master` trigger uses `workflow_run` chained from `ci.yml` so it runs only when CI is green, never on a broken master.

## Risks / Trade-offs

- **[Risk]** Multi-arch Python builds (especially PaddleOCR with PaddlePaddle) are slow and may time out on free-tier runners → **Mitigation**: aggressive `cache-to: type=gha,mode=max` per-service scope; first build is slow, subsequent builds reuse layers. If still slow, fall back to `linux/amd64` only and revisit arm64 later.
- **[Risk]** GHA cache eviction policy is per-branch and capped at 10 GB per repo → **Mitigation**: scope caches per service so a single hot service's cache cannot evict the others'. Document the cache size budget in `.github/workflows/README.md`.
- **[Risk]** A Docker Hub outage during `release.yml` produces a partial image set (e.g., 4 of 6 services pushed) → **Mitigation**: `release.yml` matrix uses `fail-fast: false` so all six services attempt. Re-running the workflow on the same tag re-pushes; Docker Hub is content-addressed for layers so this is safe and idempotent.
- **[Risk]** Secrets leak via a malicious PR from a fork → **Mitigation**: secrets are only available to workflows running on the base repo (default GitHub behavior for forked PRs). `release.yml` and `e2e.yml` do not run on `pull_request` events at all. `ci.yml` runs on `pull_request` but uses zero secrets.
- **[Trade-off]** No coverage gating, no SAST, no Dependabot in this change. They are valuable but each has its own design surface; pulling them in here would balloon the scope. Tracked as follow-ups in `.github/workflows/README.md`.

## Migration Plan

No migration. This change is purely additive — three new files under `.github/workflows/` plus an operator README. Rollback is `git revert` of the same three files. No service code is touched. No `docker-compose.yaml` change. Existing manual release flows continue to work as-is.

After merge, the maintainer:
1. Adds the secrets listed in the proposal under `Settings → Secrets and variables → Actions`.
2. Optionally enables branch protection on `master` requiring the `CI` status check.
3. Cuts the first tagged release (`git tag v0.1.0 && git push origin v0.1.0`) and watches `release.yml` complete on the Actions tab.
