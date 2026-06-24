## Context

AscendAI is a six-service monorepo with two Java/Gradle services (`AscendAgent`, `WeatherMCP`) and four Python/pyproject services (`AudioScribe`, `AscendWebSearch`, `AscendMemory`, `PaddleOCR`). Each has its own `Dockerfile`. The compose files at the repo root wire them together with the external data-layer prerequisites (PostgreSQL, Redis, Qdrant, MinIO).

There is no CI today. The maintainer builds and pushes Docker Hub images by hand (`lukk17/<service>:<tag>`). This change adds two GitHub Actions workflows: one that gives PRs a build/test signal, and one that performs **manual, operator-selected, version-from-manifest** releases with an aggregated monorepo release record.

## Goals / Non-Goals

**Goals:**

- Every push to master, every PR, and every manual dispatch builds + unit-tests the affected services in parallel with caches. CI never pushes images and holds no credentials.
- Releases are 100% manual. The operator picks a monorepo `stack_version` and selects exactly which apps to ship.
- Each app's version is owned by its committed manifest (bumped by developers in PRs). The release reads it; it never writes it. **No commits are produced by releasing.**
- A selected app that was not version-bumped since the last stack release fails the release loudly, before any image is pushed.
- Every monorepo release leaves a durable record (Git tag `ascend-ai_<version>` + GitHub Release) listing the current version of all six apps.

**Non-Goals:**

- No source changes to any service. The pipeline consumes existing `Dockerfile`s and manifests as-is.
- No version-bump-and-commit by the pipeline. No bot commits, ever.
- No committed `CHANGELOG.md` updated by the pipeline (that would be a post-release commit). The GitHub Release body is the changelog.
- No e2e/Bruno-in-CI, no coverage gating, no SAST/DAST, no Dependabot, no deployment. Each is its own follow-up.
- No tag-push trigger, no cron. Nothing auto-builds or auto-pushes.

## Decisions

### D1 — Two workflows, one responsibility each

`ci.yaml` (build + test) and `release.yaml` (build + push + release record). Separate files keep triggers obvious, isolate failure surfaces (a Docker Hub outage cannot block a PR), and allow least-privilege permissions per workflow. The `.yaml` extension is used everywhere to match the repo convention.

### D2 — CI: path-filtered matrix per service

`ci.yaml` uses `dorny/paths-filter@v3` to compute one boolean per service from its directory (`AscendAgent/**`, `AudioScribe/**`, …). The matrix `build` job skips an entry whose service was untouched. A change to `.github/workflows/**` forces all services to run via a `workflows` fallback filter. Result: a docs-only PR runs zero builds; a single-service PR runs one.

### D3 — CI: explicit Java/Python matrix entries

Each matrix entry declares `service`, `language`, `path`, and the toolchain version. Java: `actions/setup-java@v4` (temurin 21) + `gradle/actions/setup-gradle@v3`, then `./gradlew --no-daemon build test`. Python: `actions/setup-python@v5` (3.11, or 3.12 for AscendWebSearch) with `cache: pip`, then `pip install -e .[dev]` + `pytest`. `strategy.fail-fast: false` so every selected service reports.

### D4 — Release trigger: manual `workflow_dispatch` with a stack version + per-app selection

`release.yaml` is triggered **only** from the Actions UI. Inputs:

- `stack_version` — required string, e.g. `1.1.1`. The monorepo release is named `ascend-ai_<stack_version>` (so the Git tag is `ascend-ai_1.1.1`). Normal semver with the `ascend-ai_` prefix; **not** date-based.
- Six required booleans, one per app — `release_ascend_agent`, `release_weather_mcp`, `release_audio_scribe`, `release_ascend_web_search`, `release_ascend_memory`, `release_paddle_ocr` (default `false`). GitHub dispatch inputs have no native multi-select, so a boolean per app is the clearest "which apps to release" control.

**Why no tag trigger / no version input that overrides the manifest:** the operator's "I'm shipping these apps now" gesture must be explicit, and the per-app versions must already be in the source. The release is a pure read-build-push-record over committed state.

### D5 — Versions come from each app's committed manifest, never from the workflow

The release does **not** accept or inject a per-app version. For each selected app it reads the version already committed in the manifest:

- **Java** (`AscendAgent`, `WeatherMCP`): the `version = "<x.y.z>"` assignment in `build.gradle.kts` (resolved by Gradle at build time; the built image inherently carries it).
- **Python** (`AudioScribe`, `AscendWebSearch`, `AscendMemory`, `PaddleOCR`): `[project].version` in `pyproject.toml`.

That read version is the Docker tag. There is **no `-Pversion` override, no `--build-arg BUILD_VERSION`, and no in-place file edit**. Because the version is already in the source the developer committed, releasing produces **zero commits** — the property the maintainer explicitly requires.

**Alternative considered (rejected):** a single `version` dispatch input applied to all apps. Rejected because the apps move independently — forcing one version onto all of them (or committing per-app bumps from the pipeline) is exactly the "mess" the per-manifest model avoids.

### D6 — Bump guard against the previous stack release

Before building, a `prepare` job establishes the previous monorepo release and validates the selection:

1. Find the previous stack tag: `git tag -l 'ascend-ai_*' | sort -V | tail -n1`.
2. Reject the run if a tag `ascend-ai_<stack_version>` already exists (a stack version is cut once).
3. For each **selected** app, read its current manifest version and its version at the previous stack tag (`git show <prev-tag>:<path>/<manifest>`). If they are equal, the app was **not bumped since the last release** → **fail the whole run with a clear message naming the app**, before any login or push.
4. If there is no previous stack tag (first ever release), skip step 3 — every selected app simply ships at its current manifest version.

The job emits a matrix of `{service, path, language, version}` for the selected, validated apps only.

### D7 — Build + push selected apps with the manifest version

The `build-and-push` matrix (selected apps only, `fail-fast: false`) runs `docker/setup-qemu-action@v3` + `docker/setup-buildx-action@v3` + `docker/login-action@v3` (Docker Hub secrets), then `docker/build-push-action@v6` with `platforms: linux/amd64,linux/arm64`, per-service GHA cache scope, and:

```yaml
tags: |
  lukk17/<service>:<manifest-version>
  lukk17/<service>:latest
```

`:latest` is updated for every released app (a release is an intentional, manifest-bumped ship). Unselected apps are never built and their `:latest` is untouched.

### D8 — Aggregated monorepo release record (the changelog), no commit

After `build-and-push` succeeds, a `release` job:

1. Reads the **current** manifest version of **all six** apps (selected or not).
2. Composes a release body listing every app and its version, marking which were shipped in this run, e.g.:
   ```text
   ascend-ai_1.1.1
   - ascend-agent: 1.3.0  (released)
   - weather-mcp: 1.0.0
   - audio-scribe: 0.2.1  (released)
   - ascend-web-search: 1.2.0
   - ascend-memory: 0.4.0
   - ascend-paddle-ocr: 0.1.0
   ```
3. Creates Git tag `ascend-ai_<stack_version>` and a GitHub Release via `softprops/action-gh-release@v2` with that body **plus** `generate_release_notes: true` for the PR-title summary since the previous tag.

This GitHub Release is the durable changelog. It is **not** a committed file — committing a `CHANGELOG.md` from the pipeline would violate the no-post-release-commit rule. If a developer wants a tracked `CHANGELOG.md`, they update it in the same PR that bumps the version (so it is part of the committed source the release reads).

### D9 — Permissions, secrets, concurrency

- `ci.yaml`: `permissions: { contents: read }`, no secrets, `concurrency: { group: ci-${{ github.ref }}, cancel-in-progress: true }`.
- `release.yaml`: `permissions: { contents: write }` (Git tag + GitHub Release only), secrets `DOCKERHUB_USERNAME` / `DOCKERHUB_TOKEN`, `concurrency: { group: release-${{ inputs.stack_version }}, cancel-in-progress: false }` (a manual release must finish).

### D10 — Trigger summary

| Trigger | `ci.yaml` | `release.yaml` |
|---|:---:|:---:|
| `pull_request` (any branch) | ✓ | – |
| `push` to `master` | ✓ | – |
| `workflow_dispatch` (manual) | ✓ | ✓ (only trigger) |

No tag-push trigger, no cron. Nothing auto-builds or auto-pushes.

## Risks / Trade-offs

- **[Risk] A developer forgets to bump a selected app's version.** → The D6 guard fails the run before any push, naming the app. The operator bumps it in a follow-up PR and re-dispatches.
- **[Risk] Reading the version out of `build.gradle.kts` / `pyproject.toml` is parser-fragile.** → Pin the extraction: Python via `tomllib`, Java via a narrow `version = "<x>"` match (documented in the workflow README); both are unit-checked against the real manifests in the verification tasks.
- **[Risk] Multi-arch Python builds (esp. PaddleOCR) are slow.** → Per-service `cache-to: type=gha,mode=max`. If still too slow, fall back to `linux/amd64` only and revisit arm64.
- **[Risk] Partial push if Docker Hub blips.** → `fail-fast: false` so all selected apps attempt; re-running the same dispatch re-pushes idempotently. The `release` job runs only after `build-and-push` succeeds, so a partial push does not cut a misleading stack release.
- **[Risk] Fork PR secret exfiltration.** → `release.yaml` never runs on `pull_request`; `ci.yaml` runs on PRs but holds no secrets.
- **[Trade-off] The changelog lives only in the GitHub Release, not a committed file.** Accepted — it is the direct consequence of the no-post-release-commit requirement.

## Migration Plan

Purely additive — two workflow files + an operator README. Rollback is `git revert`. After merge the maintainer: (1) adds the two Docker Hub secrets; (2) ensures each app's manifest version is set; (3) cuts the first release via Actions → `Release` → `Run workflow` → enter `stack_version` + tick the apps to ship. The first run has no previous `ascend-ai_*` tag, so the bump guard is skipped and selected apps ship at their current manifest versions.
