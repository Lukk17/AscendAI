## Context

AscendAI is a six-service monorepo with two Java/Gradle services (`ascend-agent`, `ascend-weather-mcp`) and four Python/pyproject services (`ascend-audio-scribe`, `ascend-web-hunter`, `ascend-memory`, `ascend-ocr`). Each has its own `Dockerfile` and its own `CHANGELOG.md`. The compose files at the repo root wire them together with the external data-layer prerequisites (PostgreSQL, Redis, Qdrant, S3-compatible object storage).

Before this change there was no CI. The maintainer built and pushed Docker Hub images by hand. This change adds two GitHub Actions workflows: one that gives PRs a build, test and gate signal, and one that performs **manual, operator-selected, version-from-changelog** releases with an optional aggregated monorepo release record.

## Goals / Non-Goals

**Goals:**

- Every push to master, every PR, and every manual dispatch builds, lints, type checks and tests the affected services in parallel with caches, and enforces each module's coverage floor. CI never pushes images and holds no credentials.
- Every PR that touches an app carries a changelog version bump for that app.
- A change on either side of the agent to OCR REST boundary is checked against a committed consumer-driven contract.
- Releases are 100% manual. The operator selects exactly which apps to ship and whether to cut a monorepo stack release.
- Each app's version is owned by its committed `CHANGELOG.md`. The release reads it and never writes it. **No commits are produced by releasing.**
- A selected app whose version is already published on both registries fails the release loudly, before that app pushes.
- Every stack release leaves a durable record (Git tag `ascend-ai_<version>` plus GitHub Release) listing the current version of all six apps.

**Non-Goals:**

- No source changes to any service. The pipeline consumes existing `Dockerfile`s as-is.
- No version-bump-and-commit by the pipeline. No bot commits, ever.
- No changelog written by the pipeline. Developers write `apps/<app>/CHANGELOG.md` in their PRs.
- No end-to-end tests in `ci.yaml` or `release.yaml`. `e2e.yaml` exists but is outside this change. No SAST or DAST, no Dependabot, no deployment.
- No tag-push trigger, no cron. Nothing auto-builds or auto-pushes.

## Decisions

### D1: Two workflows, one responsibility each

`ci.yaml` (build and test) and `release.yaml` (build, push and release record). Separate files keep triggers obvious, isolate failure surfaces (a Docker Hub outage cannot block a PR), and allow least-privilege permissions per workflow. The `.yaml` extension is used everywhere to match the repo convention.

### D2: CI, a dynamic matrix built from path filters

The `changes` job runs `dorny/paths-filter@v3` with one filter per service directory (`apps/ascend-agent/**`, `apps/ascend-audio-scribe/**`, and so on), a `contract` filter for `contracts/**`, and a `workflows` filter for `.github/workflows/**`. A shell step then emits a JSON matrix: every service when `workflows` changed, otherwise only the changed services. The `build` job runs over that matrix and is skipped entirely when it is empty. Result: a docs-only PR runs zero builds, and a single-service PR runs one.

The job also exposes per-service `*_changed` outputs for `verify-changelog`, an `ascend_agent` output (agent or workflows changed) for `integration-test`, and a `contract` output for the contract jobs.

### D3: CI, explicit Java and Python matrix entries with gates

Each matrix entry declares `service`, `language`, `path` and `python_version`. `strategy.fail-fast: false` so every selected service reports.

- **Java**: `actions/setup-java@v4` (Temurin 21) and `gradle/actions/setup-gradle@v3`, then `./gradlew --no-daemon build test`. For `ascend-agent` only, `./gradlew --no-daemon jacocoTestCoverageVerification` follows, which fails below 80 percent instruction coverage. `ascend-weather-mcp` has no coverage floor.
- **Python**: `actions/setup-python@v5` (3.11, or 3.12 for `ascend-web-hunter`) with `cache: pip` and a `cache-dependency-path` of the service's own `pyproject.toml` and any `*requirements*.txt` beside it, so each cache key comes from that service. Then `pip install -e .[dev]`, `ruff check .`, `mypy src`, and the tests. `ascend-audio-scribe` and `ascend-ocr` run plain `pytest`, whose options already set `--cov-fail-under=100` with branch coverage. `ascend-web-hunter` and `ascend-memory` run `pytest --cov=src --cov-branch --cov-report=term-missing --cov-fail-under=100`, which repeats the same gate their options set.
- Test reports upload as `test-results-<service>` on every run, including failures.

### D4: CI, changelog version bump gate

`verify-changelog` runs on `pull_request` and `workflow_dispatch` (never on `push: master`) when at least one app directory changed. For each changed app it compares the top `## [x.y.z]` entry of `apps/<app>/CHANGELOG.md` at HEAD against the same file at the PR base ref (or `master` for a dispatch). It fails when the file or entry is missing at HEAD, when the entry is missing at the base ref while the file exists there, when HEAD is not strictly greater by `sort -V`, or when the top entry has no content. A file absent at the base ref is treated as a new module and passes.

`build`, `integration-test` and `contract-consumer` all need `verify-changelog` and use `!cancelled() && needs.verify-changelog.result != 'failure'`, so a failed check blocks them and a skipped one does not.

### D5: CI, integration tests in their own job

`integration-test` runs when `ascend-agent` or the workflows changed. It sets up Temurin 21 and Gradle and runs `./gradlew --no-daemon integrationTest` in `apps/ascend-agent`, which starts Postgres, Redis and Qdrant through Testcontainers on the runner's Docker daemon. It is a separate job so the slow container start does not delay the unit-test matrix. JUnit XML uploads as `integration-test-results-ascend-agent` on every run.

### D6: Release trigger, manual `workflow_dispatch` with per-app selection

`release.yaml` is triggered **only** from the Actions UI. Inputs:

- `create_github_release`: required boolean, default `true`. Unticked, the run publishes images only, with no Git tag, no GitHub Release, and no stack version consumed.
- `stack_version`: optional string, e.g. `1.1.1`. Required when `create_github_release` is ticked, ignored otherwise. The monorepo release is named `ascend-ai_<stack_version>`. Normal semver with the `ascend-ai_` prefix, **not** date-based.
- Six required booleans, one per app: `release_ascend_agent`, `release_ascend_weather_mcp`, `release_ascend_audio_scribe`, `release_ascend_web_hunter`, `release_ascend_memory`, `release_ascend_ocr` (default `false`). GitHub dispatch inputs have no native multi-select, so a boolean per app is the clearest control.

**Why no tag trigger and no version input:** the operator's "I'm shipping these apps now" gesture must be explicit, and the per-app versions must already be in the source. The release is a pure read, build, push and record over committed state.

### D7: Versions come from each app's committed `CHANGELOG.md`, never from the workflow

The release does **not** accept or inject a per-app version. For each selected app `prepare` reads the top entry of `apps/<app>/CHANGELOG.md` with one extractor shared by all six apps:

```
grep -oP -m1 '##\s*\[\K[0-9]+\.[0-9]+\.[0-9]+' <path>/CHANGELOG.md
```

A missing or unreadable entry fails the run. The `version` in `build.gradle.kts` or `pyproject.toml` is not read, and a mismatch with the changelog has no pipeline consequence. There is **no `-Pversion` override, no version build-arg, and no in-place file edit**, so releasing produces **zero commits**.

`prepare` emits a matrix of `{service, path, version, image_name}` for the selected apps, with `image_name = ascend-ai-<service>`. It fails when no app is selected, and, when a release is being cut, when `stack_version` is empty or the tag `ascend-ai_<stack_version>` already exists.

**Alternative considered (rejected):** reading the manifest version. Rejected because the changelog is already the file every PR must bump (D4), so reading it keeps one source of truth.

### D8: Bump guard against the registries

The guard runs per app inside `build-and-push`, after logging in to both registries, and checks `<image>:v<version>` with `docker manifest inspect` on Docker Hub and on GHCR:

- Found on both: this version is already fully published. The job fails and asks for a new `CHANGELOG.md` entry.
- Found on neither: the normal case. The job proceeds.
- Found on exactly one: an incomplete previous publish. The job warns and proceeds, completing the missing registry.
- Lookup failed for another reason (auth or network): the job fails closed without pushing.

It does not look at git history, so it survives a module's path moving between releases, and a never-published image passes on its own, so there is no first-release special case.

### D9: Build and push selected apps to two registries

The `build-and-push` matrix (selected apps only, `fail-fast: false`) runs `docker/setup-qemu-action@v3`, `docker/setup-buildx-action@v3`, `docker/login-action@v3` for Docker Hub (secrets) and for GHCR (`GITHUB_TOKEN`), the guard, then `docker/build-push-action@v6` with `context: <path>`, `platforms: linux/amd64,linux/arm64`, `cache-from` and `cache-to: type=gha,scope=<service>,mode=max`, and:

```yaml
tags: |
  lukk17/ascend-ai-<service>:v<version>
  lukk17/ascend-ai-<service>:latest
  ghcr.io/lukk17/ascend-ai-<service>:v<version>
  ghcr.io/lukk17/ascend-ai-<service>:latest
```

The `v` prefix matches the tags published by hand before this workflow existed. `latest` is updated for every released app. Unselected apps are never built and their `latest` is untouched.

### D10: Aggregated monorepo release record, no commit

When `create_github_release` is ticked and `build-and-push` succeeded, a `release` job:

1. Reads the **current** changelog version of **all six** apps (selected or not).
2. Writes a release body with a table of every app and its version, marking the ones shipped in this run with `(released)`.
3. Creates Git tag `ascend-ai_<stack_version>` and a GitHub Release via `softprops/action-gh-release@v2` with that body, `generate_release_notes: true`, not a draft and not a prerelease.

The per-app detail lives in the committed changelogs. The GitHub Release is the coarser stack record.

### D11: Permissions, secrets, concurrency

- `ci.yaml`: `permissions: { contents: read }`, no secrets, `concurrency: { group: ci-${{ github.ref }}, cancel-in-progress: true }`.
- `release.yaml`: `permissions: { contents: write }` at workflow level (Git tag and GitHub Release). `build-and-push` narrows to `contents: read` and `packages: write` (GHCR). Secrets `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`. `concurrency: { group: release-${{ inputs.stack_version || github.run_id }}, cancel-in-progress: false }`, so an image-only run with no stack version gets its own group and a manual release always finishes.

### D12: Trigger summary

| Trigger | `ci.yaml` | `release.yaml` |
|---|:---:|:---:|
| `pull_request` (any branch) | runs | does not run |
| `push` to `master` | runs | does not run |
| `workflow_dispatch` (manual) | runs | runs (only trigger) |

No tag-push trigger, no cron. Nothing auto-builds or auto-pushes.

### D13: Agent to OCR contract, two ordered jobs over a pact committed in the repo

`ci.yaml` checks the Pact contract between `ascend-agent` (consumer) and `ascend-ocr` (provider) with two jobs, in order:

1. `contract-consumer` (needs `changes` and `verify-changelog`) sets up Temurin 21 and Gradle exactly as `build` does, runs only `AscendOcrClientPactTest` in `apps/ascend-agent`, and then fails if `git status --porcelain -- contracts/pacts` is not empty. The pact it writes must be byte-identical to the committed `contracts/pacts/ascend-agent-ascend-ocr.json`. It uploads `contracts/pacts` as the `pact-ascend-agent-ascend-ocr` artifact on every run.
2. `contract-provider` (needs `changes` and `contract-consumer`, runs only when the consumer job succeeded) installs ascend-ocr on Python 3.11 with its dev extras and runs `pytest tests/contract --no-cov`, which replays the committed pact against the provider.

Both run on the `contract` output of `changes`, true when `ascend-agent`, `ascend-ocr`, `contracts/**` or the `workflows` filter changed.

The pact file lives in git, with no Pact Broker. The format is Pact specification V4, written by Pact JVM 4.6.21 and read by pact-python 3.4.0. The full record, including why Pact JVM stays on the 4.6 line, is ADR-M010 (`docs/architecture/decisions/ADR-M010-consumer-driven-contract-in-repo.md`).

**Why two ordered jobs rather than one:** the consumer runs on Java and the provider on Python, so one job would need both toolchains. Ordering them means the provider is never verified against a pact the consumer no longer produces. A drift failure stops the run at the consumer, which is the side that has to be fixed.

**Why the provider runs only after a consumer success, not on `!= 'failure'`:** a skipped consumer job means no fresh pact was checked for drift, and the provider result would then say nothing useful.

**Alternatives considered (rejected):** a Pact Broker, because it adds a hosted service and the first CI secret while both sides already live in one repository. Diffing a saved OpenAPI file, because it checks the provider's whole description rather than what the agent actually uses, and it does not run the provider.

## Risks / Trade-offs

- **[Risk] A developer forgets to bump a changed app's changelog.** `verify-changelog` fails the PR before merge, naming the app.
- **[Risk] A selected app is released again at an unchanged version.** The D8 guard fails that app's job before its push when the version is on both registries.
- **[Risk] The changelog extractor misreads a file.** One pinned `grep -oP` pattern, matched to the real `## [x.y.z]` line shape in every `CHANGELOG.md`. An unreadable entry fails the run rather than guessing.
- **[Trade-off] The changelog gate fires on every change inside an app directory**, including a documentation-only edit to that app. Accepted, catching an unbumped release is worth the occasional forced bump.
- **[Risk] Multi-arch Python builds (especially ascend-ocr) are slow.** Per-service `cache-to: type=gha,mode=max`. If still too slow, fall back to `linux/amd64` only and revisit arm64.
- **[Risk] Partial push if one registry blips.** `fail-fast: false` so all selected apps attempt. Re-running the dispatch completes a one-registry publish (D8). The `release` job runs only after `build-and-push` succeeds, so a partial push does not cut a misleading stack release.
- **[Risk] New GHCR packages are private.** GHCR offers no API to change this, so the maintainer makes each package public by hand once after its first push, as the workflow README describes.
- **[Risk] Fork PR secret exfiltration.** `release.yaml` never runs on `pull_request`, and `ci.yaml` runs on PRs but holds no secrets.
- **[Risk] No Pact Broker, so no `can-i-deploy`.** The contract proves that ascend-agent and ascend-ocr agree at the same commit. Images are released per app from possibly different commits, so nothing proves that a released agent image works with a released OCR image built elsewhere. The MCP surface of ascend-ocr is not covered, because the agent does not call it. Accepted for now (ADR-M010). Release both apps from the same commit when the interface changes. Adding a broker later is additive: the consumer test can publish the same file.

## Migration Plan

Purely additive: two workflow files and an operator README. Rollback is `git revert`. After merge the maintainer: (1) adds the two Docker Hub secrets, (2) ensures each app's `CHANGELOG.md` has a top `## [x.y.z]` entry, (3) cuts the first release via Actions → `Release` → `Run workflow`, entering `stack_version` and ticking the apps to ship, and (4) makes each new GHCR package public once. The guard needs no first-release special case, because an image that was never published is found on neither registry.
