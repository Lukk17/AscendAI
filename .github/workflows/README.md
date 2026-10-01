# GitHub Actions Workflows

This directory contains the three GitHub Actions workflows for the AscendAI monorepo.

---

## Workflows at a glance

| Workflow | File | Triggers | Pushes images? |
|---|---|---|---|
| CI | `ci.yaml` | `pull_request`, `push: master`, `workflow_dispatch` | Never |
| Release | `release.yaml` | `workflow_dispatch` only | Yes (selected apps only) |
| E2E (free specs) | `e2e.yaml` | `push: master`, `workflow_dispatch` | Never |

No tag-push trigger, no cron, no auto-push. Nothing runs automatically except when a PR is opened or a commit lands on `master`.

---

## Required secrets

Secrets are configured at **Settings → Secrets and variables → Actions** on the GitHub repository.

| Secret | Used by | Purpose |
|---|---|---|
| `DOCKERHUB_USERNAME` | `release.yaml` only | Docker Hub login username |
| `DOCKERHUB_TOKEN` | `release.yaml` only | Docker Hub access token (not your password - create a token at hub.docker.com → Security) |

GitHub Container Registry needs no configured secret. The `build-and-push` job authenticates with the automatically provided `GITHUB_TOKEN`, which is why that job declares `packages: write` in its own `permissions` block rather than at workflow level.

`ci.yaml` consumes **no secrets**. Pull requests from forks therefore run CI safely with no privileged access.

`e2e.yaml` consumes **no secrets** either. The one secret-like value it needs, `SEARXNG_SECRET`, is generated fresh for each run.

---

## CI workflow (`ci.yaml`)

### What it does

On every pull request, every push to `master`, and every manual dispatch, CI detects which service directories changed and runs build + unit tests only for those services. A docs-only PR (changes only to `README.md`, `docs/`, etc.) emits an empty matrix and completes in under a minute with no build jobs.

When `.github/workflows/**` itself changes, every service runs regardless of whether its own directory changed. This ensures a workflow edit is always tested against the full matrix before merge.

### Changelog version bump gate

A new `verify-changelog` job runs on every `pull_request` and manual `workflow_dispatch` (never on `push: master`, since there is no meaningful base ref to diff against after the merge already happened). For each app whose directory changed in the diff, it compares the topmost `## [x.y.z]` entry in that app's `apps/<app>/CHANGELOG.md` at HEAD against the same file at the PR's base ref (or `master` for a manual dispatch with no PR). The check fails the job if:

- the app's changelog does not exist, or has no `## [x.y.z]` entry, at HEAD or at the base ref
- the HEAD version equals the base version (not bumped)
- the HEAD version is not strictly greater than the base version by semver ordering (`sort -V`)
- the top entry has no content beneath it (an empty bump)

`build` and `integration-test` both declare `needs: [changes, verify-changelog]` with `!cancelled() && needs.verify-changelog.result != 'failure'` in their `if:`, so a changelog failure blocks the build/test jobs for the affected apps, and a *skipped* `verify-changelog` (for example on `push: master`, or when no app directory changed) does not block them.

**Cost.** The gate fires on every change under `apps/<app>/**` for that app, including a documentation-only edit to that app's own `README.md` or a comment-only refactor, not only user-facing or deployable changes. A multi-app PR needs a changelog bump in every touched app. There is no check on changelog *quality* beyond "non-blank content beneath the entry" - a one-word bump satisfies it. This mirrors the tradeoff the Pharmacy monorepo's own `verify-version-bump` job accepts for the same reason: catching an unbumped release is worth the friction of an occasional forced bump on a trivial change.

### Per-service toolchain

| Service | Language | Python version | Test command |
|---|---|---|---|
| `ascend-agent` | Java | - | `./gradlew --no-daemon build test` |
| `ascend-weather-mcp` | Java | - | `./gradlew --no-daemon build test` |
| `ascend-audio-scribe` | Python | 3.11 | `pytest` |
| `ascend-web-hunter` | Python | 3.12 | `pytest` |
| `ascend-memory` | Python | 3.11 | `pytest` |
| `ascend-ocr` | Python | 3.11 | `pytest -m "not contract"` |

Java services use Eclipse Temurin 21 via `actions/setup-java@v4` and Gradle dependency caching via `gradle/actions/setup-gradle@v3`. Python services use `actions/setup-python@v5` with `cache: pip` and install with `pip install -e .[dev]`. The pip cache key comes from `cache-dependency-path`, set to the service's own `pyproject.toml` and any `*requirements*.txt` beside it, so a dependency change in one service does not touch another service's cache. `contract-provider` keys its cache on `apps/ascend-ocr/pyproject.toml` the same way.

### Lint, type check and coverage gates

The `build` job runs more than the test command for each service:

- **Jacoco coverage gate (`ascend-agent` only).** After the Gradle build and tests, the job runs `./gradlew --no-daemon jacocoTestCoverageVerification`. The build fails if instruction coverage is below 80 percent. `ascend-weather-mcp` has no coverage floor, so this step does not run for it.
- **Ruff lint (every Python service).** `ruff check .` runs in the service directory after the install step.
- **Mypy type check (every Python service).** `mypy src` runs after Ruff.
- **pytest coverage gate (every Python service).** `ascend-audio-scribe` runs plain `pytest` and `ascend-ocr` runs `pytest -m "not contract"`, and both pick up the `--cov-fail-under=100` their `pyproject.toml` sets. The `build` job leaves the `ascend-ocr` contract test to the contract jobs below, which verify it only after the committed pact file is proved current. `ascend-web-hunter` and `ascend-memory` run `pytest --cov=src --cov-branch --cov-report=term-missing --cov-fail-under=100` with the flags written out. Their `pyproject.toml` now sets the same flags, so the command repeats the gate rather than adds it. In every case a Python service fails if branch coverage is below 100 percent.

### Integration test job

The `integration-test` job runs only when `ascend-agent` changed. Like `build`, it needs `changes` and `verify-changelog` and is blocked only by a failed changelog check. It sets up Temurin 21 and Gradle, then runs `./gradlew --no-daemon integrationTest` in `apps/ascend-agent`. Those tests use Testcontainers to start Postgres, Redis and Qdrant on the runner's own Docker daemon. It is a separate job so the slow container start does not delay the unit test results for the other services. Its JUnit XML is uploaded as the `integration-test-results-ascend-agent` artifact on every run, including failures.

### Contract tests

Two jobs check the Pact contract between `ascend-agent` (the consumer) and `ascend-ocr` (the provider). The contract file is committed at `contracts/pacts/ascend-agent-ascend-ocr.json`, and there is no Pact Broker. See [contracts/README.md](../../contracts/README.md) and [ADR-M010](../../docs/architecture/decisions/ADR-M010-consumer-driven-contract-in-repo.md).

| Job | Needs | What it runs |
|---|---|---|
| `contract-consumer` | `changes`, `verify-changelog` | Sets up Temurin 21 and Gradle like `build`, runs `./gradlew --no-daemon test --tests "com.lukk.ascend.ai.agent.service.ingestion.client.AscendOcrClientPactTest"` in `apps/ascend-agent`, then fails if `git status --porcelain -- contracts/pacts` prints anything. Uploads `contracts/pacts` as the `pact-ascend-agent-ascend-ocr` artifact on every run. |
| `contract-provider` | `changes`, `contract-consumer` | Sets up Python 3.11 with the pip cache, runs `pip install -e .[dev]` and then `pytest tests/contract --no-cov` in `apps/ascend-ocr`. |

**Order.** `contract-provider` runs only after `contract-consumer` succeeded. A stale pact fails the consumer job, and the provider job is then skipped, so it never verifies a file the consumer no longer produces.

**Triggers.** Both jobs run when `apps/ascend-agent/**`, `apps/ascend-ocr/**`, `contracts/**` or `.github/workflows/**` changed (the `contract` output of `changes`). A docs-only change runs neither. Like `build`, the consumer job is blocked only by a failed `verify-changelog`, never by a skipped one.

**Fixing a drift failure.** The job log prints the diff and an error that the committed pact is out of date. Regenerate the file on your machine with the consumer test (the commands are in [contracts/README.md](../../contracts/README.md)), check that `git status --porcelain -- contracts/pacts` shows the change you expect, and commit the updated JSON on the same branch. Never edit the JSON by hand.

**Fixing a provider failure.** ascend-ocr no longer answers the way the agent expects. Either fix ascend-ocr, or, when the change to the interface is intended, change the agent and its consumer test first, regenerate the pact, and commit both sides together.

The contract jobs use no secrets.

### Test report artifacts

Test results are uploaded as `test-results-<service>` artifacts on every run (including failures), so you can download JUnit XML or pytest output from the Actions UI without re-running.

### Concurrency

CI uses `cancel-in-progress: true`. A force-push or new commit to the same PR cancels the in-flight run for that ref immediately.

---

## Release workflow (`release.yaml`)

### Model summary

- Each app's `CHANGELOG.md` is the **source of truth** for its release version: the release workflow reads the topmost `## [x.y.z]` entry and never writes to any file. The `version` line in `build.gradle.kts` / `pyproject.toml` is a cosmetic per-module label the release workflow does not read; if it disagrees with the changelog, the changelog wins for release purposes and nothing fails because of the mismatch.
- Developers bump the changelog in PRs (enforced by `ci.yaml`'s `verify-changelog` job, see below); the release workflow only reads the result.
- A release is initiated from **Actions → Release → Run workflow** in the GitHub UI.
- Releasing is **selective**: you choose a `stack_version` and tick exactly the apps you want to ship. Unticked apps are not built and their images are untouched.
- The workflow produces **zero commits**. The only refs created are the Git tag and the GitHub Release.

### Inputs

| Input | Type | Required | Description |
|---|---|---|---|
| `create_github_release` | boolean | yes | Default `true`. Untick to publish images only: no Git tag, no GitHub Release, no stack version consumed. |
| `stack_version` | string | no | Semver string for the monorepo release, e.g. `1.1.1`. The Git tag will be `ascend-ai_1.1.1`. Required when `create_github_release` is ticked, ignored otherwise. |
| `release_ascend_agent` | boolean | yes | Ship `ascend-agent`. Default `false`. |
| `release_ascend_weather_mcp` | boolean | yes | Ship `ascend-weather-mcp`. Default `false`. |
| `release_ascend_audio_scribe` | boolean | yes | Ship `ascend-audio-scribe`. Default `false`. |
| `release_ascend_web_hunter` | boolean | yes | Ship `ascend-web-hunter`. Default `false`. |
| `release_ascend_memory` | boolean | yes | Ship `ascend-memory`. Default `false`. |
| `release_ascend_ocr` | boolean | yes | Ship `ascend-ocr`. Default `false`. |

### How to cut a release

1. Open a PR for each app you intend to ship, add a new top `## [x.y.z]` entry to its `CHANGELOG.md` (see "Developer convention" below), and merge.
2. Go to **Actions → Release → Run workflow**.
3. Enter the `stack_version` (e.g. `1.2.0`).
4. Tick the checkboxes for each app you want to ship.
5. Click **Run workflow**.

### Publishing images without cutting a release

Untick `create_github_release` and leave `stack_version` blank. The `prepare` and `build-and-push` jobs run normally, the `release` job is skipped, and you get published images with no Git tag and no GitHub Release.

Use this to ship an image without spending a stack version, for example when only one service has changed and the platform is not at a release point.

One consequence to be aware of. The per-registry guard (see "The bump guard" below) checks the exact `v<version>` tag on both registries, not any git tag. An image-only run publishes that version to both registries; a *second* image-only run at the same unchanged changelog version is now blocked outright, because the guard finds the tag on both registries and fails closed rather than overwriting. Bump the changelog before the next image-only run at the same app.

### The three jobs

- **`prepare`**: validates inputs, checks the stack tag does not already exist when one is being cut, and reads each selected app's current version from its `CHANGELOG.md`. If anything fails, no login or push occurs.
- **`build-and-push`**: for each selected app, logs in to Docker Hub and to GitHub Container Registry, runs the per-registry bump guard (see below), builds a multi-arch image (`linux/amd64,linux/arm64`) once, and pushes it to four tags: `v<version>` and `latest` on each registry. Jobs are `fail-fast: false` so a single app failure does not abort the others.
- **`release`**: skipped entirely when `create_github_release` is unticked. Otherwise, after all pushes succeed, it reads the current version of all six apps from their changelogs, composes a release body listing every app and marking which were shipped, and creates the Git tag `ascend-ai_<stack_version>` plus a GitHub Release via `softprops/action-gh-release@v2`. `generate_release_notes: true` appends the PR-title changelog since the previous tag automatically.

### Developer convention

Adding a new top `## [x.y.z]` entry to an app's `CHANGELOG.md` within a PR is what makes that app eligible for the next release. `ci.yaml`'s `verify-changelog` job enforces this on every PR that touches the app's directory (see the CI section above).

The `version = "<x.y.z>"` line in `build.gradle.kts` / `pyproject.toml` is a separate, cosmetic label. Nothing enforces that it matches the changelog; keep it in step by convention if you want `./gradlew build` output or `pip show` to read sensibly, but the release workflow never reads it and a mismatch has no pipeline consequence.

### Changelog version extractor

Both `prepare` and `release` read versions with the same extractor, applied uniformly to all six apps regardless of language, matched to the actual line shape in every `CHANGELOG.md`: `## [0.0.1]`, optionally followed by ` - <date>`.

```
grep -oP -m1 '##\s*\[\K[0-9]+\.[0-9]+\.[0-9]+' <path>/CHANGELOG.md
```

### The bump guard

The guard no longer looks at git history at all, which is what makes it immune to a module's path moving between releases (the previous git-tag-based guard was retired for exactly this reason - see the defect register). Instead, inside `build-and-push`, after logging in to both registries, each matrix leg checks whether `<image>:v<version>` already exists:

- **Found on both registries** - this exact version was already fully published. The job fails with a message to add a new `CHANGELOG.md` entry before releasing.
- **Found on neither** - the normal case. The job proceeds to build and push.
- **Found on exactly one** - treated as an incomplete previous publish (for example Docker Hub succeeded and GHCR failed on a transient auth or network error), not a failure. The job logs a warning and proceeds, completing the missing registry. This does not open a loophole for re-shipping changed code under an old version number, because `ci.yaml`'s `verify-changelog` job already refused to merge any module change without a version bump - a same-version re-run only ever rebuilds the same merged commit.
- **Ambiguous** (the registry lookup itself failed, for example an auth or network error rather than a clean "not found") - the job fails closed rather than guessing.

To fix a bump-guard failure:

1. Open a PR for the failing app.
2. Add a new top `## [x.y.z]` entry to its `CHANGELOG.md`.
3. Merge the PR.
4. Re-dispatch the Release workflow with the same (or a new) `stack_version`.

There is no "first ever release, guard skipped" case anymore: a brand-new image name that has never been published passes on its own (found on neither registry), so the guard behaves identically on the very first release and on every one after it.

### Stack version uniqueness

Each `stack_version` is cut once. If the tag `ascend-ai_<stack_version>` already exists, the workflow fails in `prepare` before any push. Choose a different `stack_version`.

### Where the changelog lives

Each app carries its own committed `apps/<app>/CHANGELOG.md`, written by developers in the PR that ships the change, not by the release workflow - the workflow only ever reads these files and never edits them or creates commits. The per-app detail (what changed, in prose) lives there.

The GitHub Release body is a second, coarser record: it lists the current version of all six apps, marking which were shipped in that run. GitHub's auto-generated PR notes (`generate_release_notes: true`) add a summary of every merged PR since the previous `ascend-ai_*` tag on top of that.

### Image naming

Each build is pushed to both registries under the same name, tagged `v<version>` and `latest`. The `v` prefix matches the tags already published by hand before this workflow existed (`v0.0.1`, `v0.0.2`), so the tag history on Docker Hub reads consistently.

| Service key | Docker Hub image | GHCR image |
|---|---|---|
| `ascend-agent` | `lukk17/ascend-ai-ascend-agent` | `ghcr.io/lukk17/ascend-ai-ascend-agent` |
| `ascend-weather-mcp` | `lukk17/ascend-ai-ascend-weather-mcp` | `ghcr.io/lukk17/ascend-ai-ascend-weather-mcp` |
| `ascend-audio-scribe` | `lukk17/ascend-ai-ascend-audio-scribe` | `ghcr.io/lukk17/ascend-ai-ascend-audio-scribe` |
| `ascend-web-hunter` | `lukk17/ascend-ai-ascend-web-hunter` | `ghcr.io/lukk17/ascend-ai-ascend-web-hunter` |
| `ascend-memory` | `lukk17/ascend-ai-ascend-memory` | `ghcr.io/lukk17/ascend-ai-ascend-memory` |
| `ascend-ocr` | `lukk17/ascend-ai-ascend-ocr` | `ghcr.io/lukk17/ascend-ai-ascend-ocr` |

The GHCR owner segment is hardcoded lowercase. `${{ github.repository_owner }}` would resolve to `Lukk17`, and GHCR rejects uppercase in image names.

The workflow derives each published image name as `ascend-ai-${service}`, where `${service}` is the service filter key. The local build name (used in compose) omits the `lukk17/` registry prefix but includes the full image name, for example `ascend-ai-ascend-ocr:latest`.

### GHCR package visibility

Docker Hub repositories under `lukk17/` are already public, so anyone can pull without logging in.

GHCR is the opposite. A package is **private** when first published, even from a public repository, and there is no API or workflow setting that changes this. After the first release pushes a new service, make it public by hand once:

1. Go to the package page under github.com/Lukk17?tab=packages.
2. Package settings → Danger Zone → Change visibility → Public.

This is a one-time step per service. Until it is done, `docker pull ghcr.io/lukk17/<service>` fails with an authentication error for everyone except you.

### GHA cache budget

Each service has its own Buildx cache scope (`scope=<service>`). Six services × two architectures. The `mode=max` setting caches all intermediate layers, maximising hit rates on subsequent releases. GitHub Actions cache has a 10 GB limit per repository; entries are evicted LRU. If the cache grows large, reduce to `mode=min` for the large Python services.

---

## E2E workflow (`e2e.yaml`)

### What it does

On every push to `master` and every manual dispatch, the workflow boots each service under test with `docker compose` on a hosted runner and runs its free end-to-end specs through the Bruno CLI (`bru run`) from `docs/api/request/AscendAI`. Free means the spec needs no paid API call and no human at the keyboard. It never runs on `pull_request`, because every job starts a live stack and a PR from an untrusted fork should not be able to trigger that.

### The four jobs

The jobs are independent and run in parallel. Each job installs the Bruno CLI with `npm install -g @usebruno/cli`, runs its specs one after another in a single step, and prints the service's `docker logs` if a step fails. MCP specs open a fresh MCP session with an `initialize` call and pass its `Mcp-Session-Id` to Bruno as `mcp_session_id`.

| Job | Service started | Wait before specs | Specs run | Left out |
|---|---|---|---|---|
| `ascend-weather-mcp` | `ascend-weather-mcp` | polls `/actuator/health` on port 9998, because the service has no compose healthcheck | 7 of 7 | nothing. The container is restarted before spec 7, which needs a cold geocoding cache |
| `ascend-ocr` | `ascend-ocr` (`--wait`) | polls `/ready` on port 7022 until the default engine is warm | 12 of 16 | the other 4 specs |
| `ascend-web-hunter` | `searxng`, `flaresolverr`, `ascend-web-hunter` (`--wait`) | the compose healthchecks | 11 of 12 | spec 11, which needs a human to solve a CAPTCHA through NoVNC |
| `ascend-memory` | `ascend-memory` (`--wait`) | the compose healthcheck | 2 of 6 (specs 1 and 4) | specs 2, 3, 5 and 6, which make paid OpenAI embedding calls |

The external prerequisites are job-level service containers, not compose services: `redis:7-alpine` on port 6379 for `ascend-web-hunter` and `qdrant/qdrant:v1.13.0` on port 6333 for `ascend-memory`. The `ascend-web-hunter` job writes a random `SEARXNG_SECRET` (`openssl rand -hex 32`) to the job environment before compose starts, because compose refuses to start SearXNG without one.

Some `ascend-web-hunter` specs (tiered scraping, the real-world URL matrix, clearance reuse) read live third-party sites, so they can fail on upstream rate limits or bot blocking that has nothing to do with the service's own code.

### Permissions and concurrency

The workflow has `contents: read` only. It uses `cancel-in-progress: false` with one group per ref, so a new push to `master` waits for the running e2e run instead of cancelling it.

---

## Trigger matrix

| Event | `ci.yaml` | `release.yaml` | `e2e.yaml` |
|---|:---:|:---:|:---:|
| `pull_request` (any branch) | runs | does not run | does not run |
| `push` to `master` | runs | does not run | runs |
| `push` to feature branch | does not run | does not run | does not run |
| `workflow_dispatch` | runs | runs (only trigger) | runs |
| Tag push | does not run | does not run | does not run |
| Schedule (cron) | does not run | does not run | does not run |

---

## Follow-up ideas (not in scope for this change)

- CodeQL SAST scan on PRs.
- Dependabot for dependency version bumps.
- Automatic draft release on merge to master.
