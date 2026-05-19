## 1. Repository scaffolding

- [ ] 1.1 Create `.github/workflows/` directory at the repo root
- [ ] 1.2 Add `.github/workflows/README.md` with operator notes: required Docker Hub secrets table, how to cut a release manually (Actions tab → `Release` → `Run workflow` → enter version), GHA cache size budget, follow-up ideas (CodeQL, Dependabot, coverage gating, sticky comment)

## 2. `ci.yaml` — Build + test on master / PR / manual

- [ ] 2.1 Add `name: CI`, triggers: `pull_request`, `push: branches: [master]`, `workflow_dispatch`
- [ ] 2.2 Declare top-level `permissions: { contents: read }`
- [ ] 2.3 Declare `concurrency: { group: ci-${{ github.ref }}, cancel-in-progress: true }`
- [ ] 2.4 First job `changes`: uses `dorny/paths-filter@v3` with one filter per service (`ascend-agent`, `weather-mcp`, `audio-scribe`, `ascend-web-search`, `ascend-memory`, `paddle-ocr`); also a `workflows` filter that matches `.github/workflows/**` and forces all services to run
- [ ] 2.5 Second job `build` with `strategy.matrix` enumerating each service: `{ service, language, path, python-version | java-version }`. `if:` consumes the matching `changes` output OR the `workflows` output
- [ ] 2.6 Java step set: `actions/checkout@v4`, `actions/setup-java@v4` (temurin 21), `gradle/actions/setup-gradle@v3`, then `./gradlew --no-daemon build test` in `${{ matrix.path }}`
- [ ] 2.7 Python step set: `actions/checkout@v4`, `actions/setup-python@v5` with `cache: pip` and the right version per service, `pip install -e .[dev]`, then `pytest` in `${{ matrix.path }}`
- [ ] 2.8 Upload test reports as artifact `test-results-${{ matrix.service }}` on `always()` so failures are downloadable
- [ ] 2.9 `strategy.fail-fast: false` so all services report regardless of one failing

## 3. `release.yaml` — Manual-only versioned multi-arch build + push

- [ ] 3.1 Add `name: Release`, single trigger: `workflow_dispatch` with required `inputs.version` (string, e.g. `1.2.3`). No tag trigger.
- [ ] 3.2 Declare top-level `permissions: { contents: write, packages: write }`
- [ ] 3.3 Declare `concurrency: { group: release-${{ github.event.inputs.version }}, cancel-in-progress: false }`
- [ ] 3.4 First job `prepare`: read `inputs.version`, compute `is_stable` boolean (regex `^[0-9]+\.[0-9]+\.[0-9]+$`), expose as job outputs
- [ ] 3.5 Second job `build-and-push` with `strategy.matrix` enumerating each service. `strategy.fail-fast: false`
- [ ] 3.6 Per matrix entry: `actions/checkout@v4`, `docker/setup-qemu-action@v3`, `docker/setup-buildx-action@v3`, `docker/login-action@v3` (Docker Hub), `docker/build-push-action@v6` with `platforms: linux/amd64,linux/arm64`, scoped GHA cache, conditional `:latest` tag
- [ ] 3.7 Java services: pass `--build-arg GRADLE_ARGS="-Pversion=${{ needs.prepare.outputs.version }}"` (or wire equivalent in the Dockerfile)
- [ ] 3.8 Python services: pass `--build-arg BUILD_VERSION=${{ needs.prepare.outputs.version }}` so the Dockerfile can `LABEL` and write a `VERSION` file at build time without committing back
- [ ] 3.9 Final job `github-release` (depends on `build-and-push`): `softprops/action-gh-release@v2` with `tag_name: v${{ needs.prepare.outputs.version }}` and `generate_release_notes: true` so PR titles since the previous tag become the body
- [ ] 3.10 Document in `.github/workflows/README.md` that running with version `1.2.3-rc.1` skips `:latest` and that re-running with the same version is safe (Docker Hub is content-addressed)

## 4. Documentation

- [ ] 4.1 Document the secrets table in `.github/workflows/README.md`. Only two entries: `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`, both consumed only by `release.yaml`. `ci.yaml` consumes zero secrets.
- [ ] 4.2 Document the trigger matrix (which workflow runs on PR vs master vs manual). Note explicitly: no tag trigger, no nightly cron.
- [ ] 4.3 Document the cache scoping policy (per-service `scope: <service-name>`) and the 10 GB GHA cache budget
- [ ] 4.4 Document how to cut a release: Actions tab → `Release` → `Run workflow` → enter version → confirm. Tag is created automatically via `softprops/action-gh-release`.
- [ ] 4.5 Cross-link from the root `README.md` "Build & Run" section to `.github/workflows/README.md` so contributors find the operator notes

## 5. Verification

- [ ] 5.1 Open a PR that touches only `README.md` → confirm zero matrix entries run
- [ ] 5.2 Open a PR that touches `AscendAgent/` → confirm only the `ascend-agent` matrix entry runs and it passes
- [ ] 5.3 Open a PR that touches a Python service → confirm only that entry runs and `pytest` is executed
- [ ] 5.4 Run `Release` manually with version `0.0.1-test` → confirm all six images push to Docker Hub at `lukk17/<service>:0.0.1-test`, `:latest` is NOT updated (because of the `-test` suffix), and a GitHub Release with tag `v0.0.1-test` is created
- [ ] 5.5 Run `Release` manually with version `0.0.2` → confirm `:latest` IS updated this time, and the GitHub Release notes include PR titles since `v0.0.1-test`
- [ ] 5.6 Force-push to a PR while CI is running → confirm the prior CI run is cancelled
- [ ] 5.7 Confirm a fork PR cannot read any secret (verify by inspecting a fork PR run's environment block — secrets should be empty)
