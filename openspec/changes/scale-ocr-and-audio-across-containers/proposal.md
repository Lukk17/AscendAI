# Proposal

## Why

The owner runs several containers of each service at once (owner answer 87 of 2026-10-08), and every plan must work
that way. ascend-ocr and ascend-audio-scribe still keep state that only one container sees: ascend-ocr holds its job
records, the submitted bytes and the progress files on the container's own disk and its queue in the memory of one
process, and ascend-audio-scribe keeps the transcript download files in the container's temp folder and their index in
process memory. With two containers a job submitted to one is unknown to the other, two queues each promise a wait
that ignores the other, a restart of one container fails the jobs of the other, and a transcript download link works
only on the container that wrote it. Owner answer 94.5 of 2026-10-08 asks for one change that fixes both services.

## What Changes

- ascend-ocr job records, the queue, the admission counts, the progress of a running job and the ownership of a running
  job move to Redis, the store every Python service already reaches through `REDIS_URL` (`add-ascend-python-common`,
  owner answer 94.3 of 2026-10-08). Every change of shared job state is one Redis Lua script, so it is atomic across
  containers.
- The submitted bytes of a job move from the container's disk to object storage, in ascend-ocr's own bucket under a
  prefix of their own, and are removed when the job reaches a terminal state, as today. Results stay where they are.
- Every job is visible from any container: status, listing, cancel and the removal of a finished job answer the same
  on every container. A cancel received by any container stops the inference on the container that reads the document.
- One shared queue in strict submission order. Each container keeps its one worker and its one consumer, so each
  container still reads one document at a time, and the queue bounds and the promised wait hold for the whole service.
- **BREAKING** for operators: a restart of one container no longer fails the waiting jobs, because they wait in the
  shared queue and any container reads them. A running job whose container stopped fails with the existing reason
  `SERVICE_RESTARTED` once its lease ends. `OCR_JOBS_DIR` is deleted, and a leftover value is ignored.
- ascend-audio-scribe writes each transcript download file to object storage and indexes it in Redis with the existing
  expiry `DOWNLOAD_FILE_TTL_SECONDS`, so `GET /api/v1/transcribe/download/{file_id}` answers on any container. The
  cleanup of expired files runs on every container and is safe to repeat.
- No compose shape for several containers (owner answer 98.6 of 2026-10-08): local development keeps one container of
  each service with its one published host port, callers inside Docker use the compose service name, and no host port
  range or replica setting is added. The deployment of several copies: company plans it later in
  `plan-scaled-deployment` (build group 5), this change does not wait for it.
- Every new value with a default is a setting with the same default in code and on its compose line (owner rule 98 of
  2026-10-08): `OCR_JOB_IDLE_TICK_SECONDS` and the three poll hint values `OCR_JOB_POLL_HINT_*` in ascend-ocr, the result store client values of ascend-ocr that the
  submitted bytes now reuse (`OCR_RESULT_S3_CONNECT_TIMEOUT_SECONDS`, `OCR_RESULT_S3_READ_TIMEOUT_SECONDS`,
  `OCR_RESULT_S3_UPLOAD_MAX_ATTEMPTS`, `OCR_RESULT_S3_UPLOAD_RETRY_BASE_SECONDS` and `OCR_RESULT_S3_REGION`, today
  module constants), and in ascend-audio-scribe `TRANSCRIPT_S3_BUCKET` (default `audio-transcripts`, owner answer
  98.5), the object store endpoint, the client region and the two client timeouts. The input audio of a request stays
  a temporary file of that request (owner answer 98.7).
- The e2e specs that check these behaviours are updated in place: ascend-ocr specs 14 and 15 and the suite README
  reset, and ascend-audio-scribe spec 2. No new spec.

## Capabilities

### New Capabilities

- `audio-transcript-downloads`: transcript download files of ascend-audio-scribe live in object storage with a bounded
  lifetime and are served by any container.

### Modified Capabilities

- `ocr-job-admission`: the queue, its bounds and its single consumer per container hold for every container together,
  and the operator view reports the whole service.
- `ocr-job-lifecycle`: listing, progress and cancel answer the same on every container, and every job is visible from
  any container.
- `ocr-job-retention`: records and submitted bytes live outside the container, a restart of one container fails only
  the work that container was reading, and waiting work is kept.

## Impact

- Code: `apps/ascend-ocr/src/service/job_store.py`, `job_runner.py`, `job_service.py`, `result_store.py`,
  `ocr_service.py` (progress from the worker), `src/config/config.py`, `src/main.py`, the readiness probes, and their
  tests. `apps/ascend-audio-scribe/src/adapters/download_file_manager.py`, `src/api/rest/rest_endpoints.py`,
  `src/config/config.py`, `src/main.py`, `pyproject.toml` (an S3 client), and their tests.
- Configuration: `compose.yaml` (`ascend-audio-scribe` gets the object store and transcript settings, `ascend-ocr`
  gets `OCR_JOB_IDLE_TICK_SECONDS`, the three `OCR_JOB_POLL_HINT_*` values and the five result store client
  values), a comment of the root `.env.example`, both services' `AGENTS.md` and README,
  `apps/ascend-ocr/docs/CONFIGURATION.md` and the ascend-audio-scribe rows of `docs/CONFIGURATION.md`.
- Tests and e2e: unit and integration tests with two simulated containers on one Redis, ascend-ocr e2e specs 14 and 15
  and `apps/ascend-ocr/e2e/README.md`, ascend-audio-scribe e2e spec 2 and its template, one new Bruno request.
- Build order (owner build order of 2026-10-04, which supersedes the earlier orders, and owner answer 94.5 of
  2026-10-08): build group 3 (base), position 5, directly after `harden-cloud-deployment` (position 4). It needs
  `add-ascend-python-common` (build group 2, position 1: the shared library, `REDIS_URL` and the Redis rate limit
  storage of answer 94.3), `add-python-runtime-upgrades` (build group 2, position 2: stateless HTTP MCP of answer 94.2),
  `fix-linux-docker-host-access` (build group 1, position 4: the `extra_hosts` line of `ascend-audio-scribe`) and
  `harden-cloud-deployment` (build group 3, position 4: the production compose settings it builds on).
  `add-deployment-modules` (build group 3, position 6) and every later change land after it. It depends on no company
  change.

## Relevant Skills

- `python-patterns`, `coding-standards`, `backend-patterns`
- `docker-patterns` for the compose lines
- `api-design` for the unchanged REST contracts
- `e2e-runbooks` for the updated specs
