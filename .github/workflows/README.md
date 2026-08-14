# GitHub Actions Workflows

This directory contains the two GitHub Actions workflows for the AscendAI monorepo.

---

## Workflows at a glance

| Workflow | File | Triggers | Pushes images? |
|---|---|---|---|
| CI | `ci.yaml` | `pull_request`, `push: master`, `workflow_dispatch` | Never |
| Release | `release.yaml` | `workflow_dispatch` only | Yes (selected apps only) |

No tag-push trigger, no cron, no auto-push. Nothing runs automatically except when a PR is opened or a commit lands on `master`.

---

## Required secrets

Secrets are configured at **Settings → Secrets and variables → Actions** on the GitHub repository.

| Secret | Used by | Purpose |
|---|---|---|
| `DOCKERHUB_USERNAME` | `release.yaml` only | Docker Hub login username |
| `DOCKERHUB_TOKEN` | `release.yaml` only | Docker Hub access token (not your password — create a token at hub.docker.com → Security) |

GitHub Container Registry needs no configured secret. The `build-and-push` job authenticates with the automatically provided `GITHUB_TOKEN`, which is why that job declares `packages: write` in its own `permissions` block rather than at workflow level.

`ci.yaml` consumes **no secrets**. Pull requests from forks therefore run CI safely with no privileged access.

---

## CI workflow (`ci.yaml`)

### What it does

On every pull request, every push to `master`, and every manual dispatch, CI detects which service directories changed and runs build + unit tests only for those services. A docs-only PR (changes only to `README.md`, `docs/`, etc.) emits an empty matrix and completes in under a minute with no build jobs.

When `.github/workflows/**` itself changes, every service runs regardless of whether its own directory changed. This ensures a workflow edit is always tested against the full matrix before merge.

### Per-service toolchain

| Service | Language | Python version | Test command |
|---|---|---|---|
| `ascend-agent` | Java | — | `./gradlew --no-daemon build test` |
| `weather-mcp` | Java | — | `./gradlew --no-daemon build test` |
| `audio-scribe` | Python | 3.11 | `pytest` |
| `ascend-web-search` | Python | 3.12 | `pytest` |
| `ascend-memory` | Python | 3.11 | `pytest` |
| `ascend-paddle-ocr` | Python | 3.11 | `pytest` |

Java services use Eclipse Temurin 21 via `actions/setup-java@v4` and Gradle dependency caching via `gradle/actions/setup-gradle@v3`. Python services use `actions/setup-python@v5` with `cache: pip` and install with `pip install -e .[dev]`.

### Test report artifacts

Test results are uploaded as `test-results-<service>` artifacts on every run (including failures), so you can download JUnit XML or pytest output from the Actions UI without re-running.

### Concurrency

CI uses `cancel-in-progress: true`. A force-push or new commit to the same PR cancels the in-flight run for that ref immediately.

---

## Release workflow (`release.yaml`)

### Model summary

- Per-app versions are the **source of truth** and live in each service's manifest. Developers bump them in PRs; the release workflow reads them and never writes them.
- A release is initiated from **Actions → Release → Run workflow** in the GitHub UI.
- Releasing is **selective**: you choose a `stack_version` and tick exactly the apps you want to ship. Unticked apps are not built and their images are untouched.
- The workflow produces **zero commits**. The only refs created are the Git tag and the GitHub Release.

### Inputs

| Input | Type | Required | Description |
|---|---|---|---|
| `stack_version` | string | yes | Semver string for the monorepo release, e.g. `1.1.1`. The Git tag will be `ascend-ai_1.1.1`. |
| `release_ascend_agent` | boolean | yes | Ship `ascend-agent`. Default `false`. |
| `release_weather_mcp` | boolean | yes | Ship `weather-mcp`. Default `false`. |
| `release_audio_scribe` | boolean | yes | Ship `audio-scribe`. Default `false`. |
| `release_ascend_web_search` | boolean | yes | Ship `ascend-web-search`. Default `false`. |
| `release_ascend_memory` | boolean | yes | Ship `ascend-memory`. Default `false`. |
| `release_paddle_ocr` | boolean | yes | Ship `ascend-paddle-ocr`. Default `false`. |

### How to cut a release

1. Open a PR for each app you intend to ship, bump its manifest `version` (see "Developer convention" below), and merge.
2. Go to **Actions → Release → Run workflow**.
3. Enter the `stack_version` (e.g. `1.2.0`).
4. Tick the checkboxes for each app you want to ship.
5. Click **Run workflow**.

The workflow runs three sequential jobs:

- **`prepare`**: validates inputs, checks the tag does not already exist, reads manifest versions, runs the bump guard. If anything fails, no login or push occurs.
- **`build-and-push`**: for each selected app, logs in to Docker Hub and to GitHub Container Registry, builds a multi-arch image (`linux/amd64,linux/arm64`) once, and pushes it to four tags: `v<version>` and `latest` on each registry. Jobs are `fail-fast: false` so a single app failure does not abort the others.
- **`release`**: after all pushes succeed, reads the current version of all six apps, composes a release body listing every app and marking which were shipped, and creates the Git tag `ascend-ai_<stack_version>` plus a GitHub Release via `softprops/action-gh-release@v2`. `generate_release_notes: true` appends the PR-title changelog since the previous tag automatically.

### Developer convention

Bumping an app's `version` in its manifest within a PR is what makes that app eligible for the next release.

- **Java services** (`AscendAgent`, `WeatherMCP`): edit the `version = "<x.y.z>"` line in `build.gradle.kts`.
- **Python services** (`AudioScribe`, `AscendWebSearch`, `AscendMemory`, `PaddleOCR`): edit the `version = "<x.y.z>"` line in `[project]` section of `pyproject.toml`.

### Manifest version extractors

The `prepare` job reads versions with pinned extractors matched to the actual line shape in each file.

Java (`build.gradle.kts`) — actual line shape: `version = "0.0.1"`

```
grep -oP '(?<=^version = ")[^"]+' <path>/build.gradle.kts | head -1
```

Python (`pyproject.toml`) — actual line shape under `[project]`: `version = "0.9.0"`

```
python3 -c "import tomllib; print(tomllib.load(open('<path>/pyproject.toml','rb'))['project']['version'])"
```

`tomllib` is part of the Python 3.11 standard library. The GitHub-hosted `ubuntu-latest` runner ships Python 3.12+, so no extra install is needed.

### The bump guard

Before any login or push, the `prepare` job compares each selected app's current manifest version against its version at the most recent `ascend-ai_*` tag.

If the versions match — the app was not bumped since the last stack release — the entire run fails immediately with a message naming the offending app. No image is pushed for any app, even those that were bumped.

To fix a bump-guard failure:

1. Open a PR for the failing app.
2. Increment its `version` in the manifest.
3. Merge the PR.
4. Re-dispatch the Release workflow with the same (or a new) `stack_version`.

When no `ascend-ai_*` tag exists yet (first ever release), the guard is skipped entirely. All selected apps ship at their current manifest versions.

### Stack version uniqueness

Each `stack_version` is cut once. If the tag `ascend-ai_<stack_version>` already exists, the workflow fails in `prepare` before any push. Choose a different `stack_version`.

### The GitHub Release is the changelog

The GitHub Release body lists the current version of all six apps, marking which were released in that run. GitHub's auto-generated PR notes (`generate_release_notes: true`) add a summary of every merged PR since the previous `ascend-ai_*` tag.

No committed `CHANGELOG.md` is produced. The release workflow never edits files or creates commits.

### Image naming

Each build is pushed to both registries under the same name, tagged `v<version>` and `latest`. The `v` prefix matches the tags already published by hand before this workflow existed (`v0.0.1`, `v0.0.2`), so the tag history on Docker Hub reads consistently.

| Service key | Docker Hub image | GHCR image |
|---|---|---|
| `ascend-agent` | `lukk17/ascend-agent` | `ghcr.io/lukk17/ascend-agent` |
| `weather-mcp` | `lukk17/weather-mcp` | `ghcr.io/lukk17/weather-mcp` |
| `audio-scribe` | `lukk17/audio-scribe` | `ghcr.io/lukk17/audio-scribe` |
| `ascend-web-search` | `lukk17/ascend-web-search` | `ghcr.io/lukk17/ascend-web-search` |
| `ascend-memory` | `lukk17/ascend-memory` | `ghcr.io/lukk17/ascend-memory` |
| `ascend-paddle-ocr` | `lukk17/ascend-paddle-ocr` | `ghcr.io/lukk17/ascend-paddle-ocr` |

The GHCR owner segment is hardcoded lowercase. `${{ github.repository_owner }}` would resolve to `Lukk17`, and GHCR rejects uppercase in image names.

Note: the compose file refers to the PaddleOCR service as `ascend-paddle-ocr` (local build name), but its published image is `lukk17/ascend-paddle-ocr` — consistent with the service filter key and the spec.

### GHCR package visibility

Docker Hub repositories under `lukk17/` are already public, so anyone can pull without logging in.

GHCR is the opposite. A package is **private** when first published, even from a public repository, and there is no API or workflow setting that changes this. After the first release pushes a new service, make it public by hand once:

1. Go to the package page under github.com/Lukk17?tab=packages.
2. Package settings → Danger Zone → Change visibility → Public.

This is a one-time step per service. Until it is done, `docker pull ghcr.io/lukk17/<service>` fails with an authentication error for everyone except you.

### GHA cache budget

Each service has its own Buildx cache scope (`scope=<service>`). Six services × two architectures. The `mode=max` setting caches all intermediate layers, maximising hit rates on subsequent releases. GitHub Actions cache has a 10 GB limit per repository; entries are evicted LRU. If the cache grows large, reduce to `mode=min` for the large Python services.

---

## Trigger matrix

| Event | `ci.yaml` | `release.yaml` |
|---|:---:|:---:|
| `pull_request` (any branch) | runs | does not run |
| `push` to `master` | runs | does not run |
| `push` to feature branch | does not run | does not run |
| `workflow_dispatch` | runs | runs (only trigger) |
| Tag push | does not run | does not run |
| Schedule (cron) | does not run | does not run |

---

## Follow-up ideas (not in scope for this change)

- CodeQL SAST scan on PRs.
- Coverage gating (fail CI if coverage drops below threshold).
- Dependabot for dependency version bumps.
- Bruno e2e tests run against a live stack in CI.
- Automatic draft release on merge to master.
