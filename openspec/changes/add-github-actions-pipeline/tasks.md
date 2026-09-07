## 1. Repository scaffolding

- [x] 1.1 Create `.github/workflows/` directory at the repo root
- [x] 1.2 Add `.github/workflows/README.md` with operator notes: required Docker Hub secrets table, the per-app-version + app-selection release model, how the bump guard works, how to cut a release, GHA cache budget, and follow-up ideas (CodeQL, Dependabot, coverage gating)

## 2. `ci.yaml` — Build + test only (never pushes images)

- [x] 2.1 Add `name: CI`, triggers: `pull_request`, `push: branches: [master]`, `workflow_dispatch`
- [x] 2.2 Declare top-level `permissions: { contents: read }`; no secrets referenced anywhere in this workflow
- [x] 2.3 Declare `concurrency: { group: ci-${{ github.ref }}, cancel-in-progress: true }`
- [x] 2.4 First job `changes`: `dorny/paths-filter@v3` with one filter per service (`ascend-agent`, `weather-mcp`, `ascend-audio-scribe`, `ascend-web-hunter`, `ascend-memory`, `ascend-paddle-ocr`) plus a `workflows` filter (`.github/workflows/**`) that forces all services to run
- [x] 2.5 Second job `build` with `strategy.matrix` over each service `{ service, language, path, version }`; `if:` consumes the matching `changes` output OR the `workflows` output; `strategy.fail-fast: false`
- [x] 2.6 Java step set: `actions/checkout@v4`, `actions/setup-java@v4` (temurin 21), `gradle/actions/setup-gradle@v3`, then `./gradlew --no-daemon build test` in `${{ matrix.path }}`
- [x] 2.7 Python step set: `actions/checkout@v4`, `actions/setup-python@v5` (`cache: pip`, right version per service), `pip install -e .[dev]`, then `pytest` in `${{ matrix.path }}`
- [x] 2.8 Upload test reports as artifact `test-results-${{ matrix.service }}` on `always()`

## 3. `release.yaml` — Manual, app-selective, version-from-manifest

- [x] 3.1 Add `name: Release`, single trigger `workflow_dispatch` with inputs: `stack_version` (required string) and six required booleans `release_<app>` (default `false`), one per service. No tag/push/PR/cron trigger.
- [x] 3.2 Declare top-level `permissions: { contents: write }` (Git tag + GitHub Release only)
- [x] 3.3 Declare `concurrency: { group: release-${{ inputs.stack_version }}, cancel-in-progress: false }`
- [x] 3.4 Job `prepare`: collect the selected apps from the booleans; fail early if zero apps selected
- [x] 3.5 `prepare`: reject the run if a tag `ascend-ai_${{ inputs.stack_version }}` already exists
- [x] 3.6 `prepare`: resolve the previous stack tag via `git tag -l 'ascend-ai_*' | sort -V | tail -n1` (empty ⇒ first release, guard skipped)
- [x] 3.7 `prepare`: read each app's current manifest version — Python via `tomllib` on `pyproject.toml` `[project].version`, Java via a pinned `version = "<x>"` match on `build.gradle.kts`. Pin these extractors and document them in the workflow README.
- [x] 3.8 `prepare`: bump guard — for each selected app, read its version at the previous stack tag (`git show <prev-tag>:<path>/<manifest>`); if equal to the current version, fail the run naming the app. Skip when there is no previous tag.
- [x] 3.9 `prepare`: emit a JSON matrix of `{ service, path, language, version }` for the selected, validated apps (job output)
- [x] 3.10 Job `build-and-push` (matrix from `prepare`, `strategy.fail-fast: false`): `actions/checkout@v4`, `docker/setup-qemu-action@v3`, `docker/setup-buildx-action@v3`, `docker/login-action@v3` (Docker Hub secrets)
- [x] 3.11 `build-and-push`: `docker/build-push-action@v6` with `context: ${{ matrix.path }}`, `platforms: linux/amd64,linux/arm64`, `cache-from`/`cache-to: type=gha,scope=${{ matrix.service }},mode=max`, and `tags: lukk17/${{ matrix.service }}:${{ matrix.version }}` + `lukk17/${{ matrix.service }}:latest`. No version build-arg / `-Pversion` override.
- [x] 3.12 Job `release` (needs `build-and-push`, runs only on success): read the current manifest version of all six apps; compose a body listing every app + version, marking the released ones
- [x] 3.13 `release`: `softprops/action-gh-release@v2` with `tag_name: ascend-ai_${{ inputs.stack_version }}`, the composed body, and `generate_release_notes: true`. No commit is made anywhere in the workflow.

## 4. Documentation

- [x] 4.1 Document the secrets table (`DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`, release-only; CI uses none)
- [x] 4.2 Document the developer convention: bump the app's manifest `version` in the PR; that is what makes the app eligible for the next release
- [x] 4.3 Document the release procedure: Actions → `Release` → `Run workflow` → enter `stack_version` + tick the apps to ship; explain the bump-guard failure and how to fix it; explain that the GitHub Release is the changelog and that no commits are produced
- [x] 4.4 Document the trigger matrix (no tag trigger, no cron) and the per-service cache scoping / GHA cache budget
- [x] 4.5 Cross-link from the root `README.md` to `.github/workflows/README.md`

## 5. Verification

- [ ] 5.1 PR touching only `README.md` → zero matrix entries run
- [ ] 5.2 PR touching `AscendAgent/` → only the `ascend-agent` CI entry runs and passes
- [ ] 5.3 PR touching a Python service → only that CI entry runs and `pytest` executes
- [ ] 5.4 Dispatch `Release` selecting an app whose manifest version was NOT bumped since the last `ascend-ai_*` tag → run fails in `prepare` naming the app, no push occurs
- [ ] 5.5 Dispatch `Release` with `stack_version` and one bumped app selected → only that image pushes at its manifest version + `:latest`; a `ascend-ai_<stack_version>` tag + GitHub Release is created listing all six app versions; the default branch gains no workflow commit
- [ ] 5.6 Dispatch `Release` reusing an existing `stack_version` → run fails before any push
- [ ] 5.7 Force-push to a PR while CI runs → prior CI run is cancelled
- [ ] 5.8 Confirm a fork PR run exposes no secrets (CI holds none; release never runs on PRs)
