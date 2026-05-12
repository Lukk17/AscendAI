## 1. Repository scaffolding

- [ ] 1.1 Create `.github/workflows/` directory at the repo root
- [ ] 1.2 Add `.github/workflows/README.md` with operator notes: required secrets table, how to cut a release (`git tag v1.2.3 && git push origin v1.2.3`), how to retry a failed e2e run, GHA cache size budget
- [ ] 1.3 Document the required GitHub repository settings: branch protection on `master` requiring the `CI` status check; "Automatically delete head branches" enabled (optional)

## 2. `ci.yml` — Build + test on push and PR

- [ ] 2.1 Add `name: CI`, triggers: `pull_request`, `push` (branches `master`), `workflow_dispatch`
- [ ] 2.2 Declare top-level `permissions: { contents: read }`
- [ ] 2.3 Declare `concurrency: { group: ci-${{ github.ref }}, cancel-in-progress: true }`
- [ ] 2.4 First job `changes`: uses `dorny/paths-filter@v3` with one filter per service (`ascend-agent`, `weather-mcp`, `audio-scribe`, `ascend-web-search`, `ascend-memory`, `paddle-ocr`); also a `workflows` filter that matches `.github/workflows/**` and forces all services to run
- [ ] 2.5 Second job `build` with `strategy.matrix` enumerating each service: `{ service, language, path, python-version | java-version }`. `if:` consumes the matching `changes` output OR the `workflows` output
- [ ] 2.6 Java step set: `actions/checkout@v4`, `actions/setup-java@v4` (temurin 21), `gradle/actions/setup-gradle@v3`, then `./gradlew --no-daemon build test` in `${{ matrix.path }}`
- [ ] 2.7 Python step set: `actions/checkout@v4`, `actions/setup-python@v5` with `cache: pip` and the right version per service, `pip install -e .[dev]`, then `pytest` in `${{ matrix.path }}`
- [ ] 2.8 Upload test reports as artifact `test-results-${{ matrix.service }}` on always() so failures are downloadable
- [ ] 2.9 `strategy.fail-fast: false` so all services report regardless of one failing

## 3. `release.yml` — Versioned multi-arch image build + push

- [ ] 3.1 Add `name: Release`, triggers: `push` tags `v*.*.*`, `workflow_dispatch` (with manual `version` input for emergency repushes)
- [ ] 3.2 Declare top-level `permissions: { contents: write, packages: write }`
- [ ] 3.3 Declare `concurrency: { group: release-${{ github.ref }}, cancel-in-progress: false }`
- [ ] 3.4 First job `prepare`: extract version from tag (`echo "version=${GITHUB_REF#refs/tags/v}"`), compute `is_stable` boolean (regex `^[0-9]+\.[0-9]+\.[0-9]+$`), expose as job outputs
- [ ] 3.5 Second job `build-and-push` with `strategy.matrix` enumerating each service. `strategy.fail-fast: false`
- [ ] 3.6 Per matrix entry: `actions/checkout@v4`, `docker/setup-qemu-action@v3`, `docker/setup-buildx-action@v3`, `docker/login-action@v3` (Docker Hub), `docker/build-push-action@v6` with `platforms: linux/amd64,linux/arm64`, scoped GHA cache, conditional `:latest` tag
- [ ] 3.7 Java services: pass `--build-arg GRADLE_ARGS="-Pversion=${{ needs.prepare.outputs.version }}"` (or wire equivalent in the Dockerfile)
- [ ] 3.8 Python services: pass `--build-arg BUILD_VERSION=${{ needs.prepare.outputs.version }}` so the Dockerfile can `LABEL` and write a `VERSION` file at build time without committing back
- [ ] 3.9 Final job `github-release` (depends on `build-and-push`): `softprops/action-gh-release@v2` with `generate_release_notes: true` so PR titles since the previous tag become the body
- [ ] 3.10 Document in `.github/workflows/README.md` that pushing `v1.2.3-rc.1` skips `:latest` and skips no other steps

## 4. `e2e.yml` — End-to-end Bruno smoke run

- [ ] 4.1 Add `name: E2E`, triggers: `workflow_run` chained on `ci.yml` completion against `master`, `schedule` (cron `0 3 * * *` for 03:00 UTC nightly), `workflow_dispatch`
- [ ] 4.2 Declare top-level `permissions: { contents: read }`
- [ ] 4.3 Declare `concurrency: { group: e2e-${{ github.ref }}, cancel-in-progress: true }`
- [ ] 4.4 Single job `e2e` with `services:` block declaring `postgres:16`, `redis:7-alpine`, `qdrant/qdrant:latest`, `minio/minio:latest` — each with healthcheck and ports mapped to the runner's localhost
- [ ] 4.5 Step: `actions/checkout@v4`
- [ ] 4.6 Step: `docker/setup-buildx-action@v3` (compose's build will use the buildkit driver)
- [ ] 4.7 Step: write `.env` file with the runtime secrets the Bruno collection needs — `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `MINIMAX_API_KEY`, `HF_TOKEN`, `NGROK_AUTHTOKEN` — all sourced from `${{ secrets.* }}`
- [ ] 4.8 Step: `docker compose up -d --build`. Wait for `/health` on AscendAgent (`curl --retry 30 --retry-delay 5 --retry-all-errors http://localhost:9917/actuator/health`)
- [ ] 4.9 Step: `actions/setup-node@v4` then `npm install -g @usebruno/cli`
- [ ] 4.10 Step: `bru run docs/api/request/AscendAI/ascend-agent/testing --env ascend-local --reporter-html bruno-report.html --reporter-json bruno-report.json` (or equivalent reporter flags supported by the installed Bruno CLI version)
- [ ] 4.11 Step (always()): `actions/upload-artifact@v4` with the Bruno report files and `docker compose logs` dumped to a file
- [ ] 4.12 Step (always()): `docker compose down -v` for cleanup
- [ ] 4.13 Workflow fails iff `bru run` exits non-zero

## 5. Documentation

- [ ] 5.1 Document the secrets table in `.github/workflows/README.md`. Mark which secrets each workflow consumes:
  - `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN` → `release.yml` only
  - `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `MINIMAX_API_KEY`, `HF_TOKEN`, `NGROK_AUTHTOKEN` → `e2e.yml` only
- [ ] 5.2 Document the trigger matrix (which workflow runs on PR vs master vs tag vs cron vs manual)
- [ ] 5.3 Document the cache scoping policy (per-service `scope: <service-name>`) and the 10 GB GHA cache budget
- [ ] 5.4 Document how to skip CI on a release commit (the answer is: don't — release commits are tag pushes, not branch pushes; CI does not trigger on tag pushes)
- [ ] 5.5 Cross-link from the root `README.md` "Build & Run" section to `.github/workflows/README.md` so contributors find the operator notes

## 6. Verification

- [ ] 6.1 Open a PR that touches only `README.md` → confirm zero matrix entries run
- [ ] 6.2 Open a PR that touches `AscendAgent/` → confirm only the `ascend-agent` matrix entry runs and it passes
- [ ] 6.3 Open a PR that touches a Python service → confirm only that entry runs and `pytest` is executed
- [ ] 6.4 Push a tag `v0.0.1-test` → confirm all six images push to Docker Hub at `lukk17/<service>:0.0.1-test`, `:latest` is NOT updated (because of the `-test` suffix), and a draft GitHub Release is created
- [ ] 6.5 Push a tag `v0.0.2` → confirm `:latest` IS updated this time, and the GitHub Release notes include PR titles since `v0.0.1-test`
- [ ] 6.6 Trigger `e2e.yml` manually via `workflow_dispatch` → confirm Postgres/Redis/Qdrant/MinIO start as service containers, the application stack comes up, Bruno runs, and the report artifact is uploaded
- [ ] 6.7 Force-push to a PR while CI is running → confirm the prior CI run is cancelled
- [ ] 6.8 Confirm a fork PR cannot read any secret (verify by inspecting a fork PR run's environment block — secrets should be empty)
