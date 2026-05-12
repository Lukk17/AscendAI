## ADDED Requirements

### Requirement: Triggers — post-CI on master, nightly cron, and manual

`e2e.yml` SHALL trigger via `workflow_run` chained on a successful `ci.yml` completion against the `master` branch, via `schedule` cron `0 3 * * *` (03:00 UTC nightly), and via `workflow_dispatch` for manual runs. It SHALL NOT trigger on pull requests.

#### Scenario: Master push runs CI then E2E

- **WHEN** a commit lands on `master` and the `CI` workflow finishes with conclusion `success`
- **THEN** the `E2E` workflow's `workflow_run` trigger fires
- **AND** the e2e job runs against the same commit SHA

#### Scenario: Failed CI does not trigger E2E

- **WHEN** a commit lands on `master` but `CI` finishes with conclusion `failure`
- **THEN** the `E2E` workflow does not run
- **AND** the maintainer can still trigger it manually via `workflow_dispatch` if desired

#### Scenario: Nightly cron triggers regardless of activity

- **WHEN** 03:00 UTC arrives and there have been no commits to `master` for 24 hours
- **THEN** `E2E` runs against the current `master` HEAD
- **AND** the artifact is named to disambiguate scheduled vs push runs (e.g., includes `${{ github.run_number }}`)

### Requirement: Data-layer prerequisites run as GitHub Actions service containers

The e2e job SHALL declare `services:` for `postgres:16` (with `POSTGRES_DB=ascend_ai`, `POSTGRES_USER=postgres`, `POSTGRES_PASSWORD=local`), `redis:7-alpine`, `qdrant/qdrant:latest`, and `minio/minio:latest`. Each service SHALL declare a healthcheck so the application stack does not start before the data layer is ready.

#### Scenario: Postgres service container ready before app stack

- **WHEN** the e2e job starts
- **THEN** GitHub Actions waits for `pg_isready` on the Postgres service before running the first job step
- **AND** the application stack started by `docker compose up` connects to `localhost:5432` successfully

#### Scenario: All four data services have healthchecks

- **WHEN** any of Postgres, Redis, Qdrant, or MinIO fails its healthcheck
- **THEN** the e2e job fails before the Bruno run starts
- **AND** the failure log identifies the failing service container

### Requirement: Application stack via `docker compose up`

After the data layer is healthy, the workflow SHALL run `docker compose up -d --build` from the repo root so the application services (AscendAgent, WeatherMCP, AudioScribe, AscendWebSearch, AscendMemory, PaddleOCR, plus support services in compose) come up using their per-service `Dockerfile`s and the checked-in `docker-compose.yaml`. The workflow SHALL then poll `http://localhost:9917/actuator/health` until it returns `200 OK` (with a bounded retry, e.g., `curl --retry 30 --retry-delay 5 --retry-all-errors`) before invoking Bruno.

#### Scenario: Stack starts and AscendAgent reports healthy

- **WHEN** `docker compose up -d --build` completes
- **THEN** the readiness poll observes `http://localhost:9917/actuator/health` returning `200` within the retry budget
- **AND** the workflow proceeds to the Bruno step

#### Scenario: Stack fails to come healthy

- **WHEN** AscendAgent fails to report healthy within the retry budget
- **THEN** the workflow fails the step with a clear message
- **AND** the cleanup step still runs and uploads `docker compose logs` as an artifact

### Requirement: Bruno CLI runs the AscendAgent test collection

The workflow SHALL install the Bruno CLI via `npm install -g @usebruno/cli` and run `bru run docs/api/request/AscendAI/ascend-agent/testing --env ascend-local` (with reporter flags appropriate to the installed CLI version). The workflow SHALL fail if Bruno exits non-zero.

#### Scenario: All Bruno tests pass

- **WHEN** every request in the collection completes with assertions satisfied
- **THEN** `bru run` exits zero
- **AND** the workflow conclusion is `success`

#### Scenario: A Bruno assertion fails

- **WHEN** a single request's assertion fails (e.g., `/api/v1/ai/prompt` returns 500 instead of 200)
- **THEN** `bru run` exits non-zero
- **AND** the workflow conclusion is `failure`
- **AND** the Bruno report artifact is still uploaded (covered by the always() upload step)

### Requirement: Bruno report and compose logs uploaded as artifact

The workflow SHALL upload Bruno's run output (HTML and JSON reporter files) and the captured `docker compose logs` as a workflow artifact via `actions/upload-artifact@v4`, regardless of whether Bruno passed or failed. The artifact name SHALL include `${{ github.run_number }}` so multiple runs of the same workflow do not collide.

#### Scenario: Artifact contains Bruno report on failure

- **WHEN** a Bruno assertion fails
- **THEN** the always() upload step runs
- **AND** the artifact contains the JSON reporter file with per-request status codes and assertion diffs
- **AND** the artifact also contains a `compose-logs.txt` from `docker compose logs --no-color`

### Requirement: Runtime secrets sourced from repository secrets

The workflow SHALL pass the runtime secrets the Bruno collection actually exercises — `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `MINIMAX_API_KEY`, `HF_TOKEN`, `NGROK_AUTHTOKEN` — into the application stack via a `.env` file written from `${{ secrets.* }}`. Secrets SHALL never appear in workflow logs in plain text.

#### Scenario: Secrets reach AscendAgent via .env

- **WHEN** the workflow writes `.env` and runs `docker compose up -d`
- **THEN** the AscendAgent container reads `OPENAI_API_KEY` (etc.) via Spring's environment-variable binding
- **AND** the `${{ secrets.OPENAI_API_KEY }}` expression is masked in the workflow log

#### Scenario: A scheduled run with no recent secret rotation still works

- **WHEN** the nightly cron fires and no secret has been rotated since the previous successful run
- **THEN** the same secrets are read and the stack starts identically

### Requirement: Cleanup runs even on failure

The workflow SHALL run `docker compose down -v` in an always() step so volumes from the failed run do not accumulate on the runner. (Self-hosted runners would otherwise leak disk; GitHub-hosted runners reset between jobs but the explicit cleanup is still good practice.)

#### Scenario: Compose teardown after pass

- **WHEN** Bruno passes and the workflow conclusion is `success`
- **THEN** `docker compose down -v` runs as a final step
- **AND** all six application service containers are stopped

#### Scenario: Compose teardown after failure

- **WHEN** Bruno fails and the workflow conclusion is `failure`
- **THEN** `docker compose down -v` still runs (because of `if: always()`)
- **AND** the artifact upload also still runs
