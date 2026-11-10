## Context

Owner answer 87 of 2026-10-08 (rule R1): several containers of the same service run at once, and every change must be
safe with several instances. Owner answer 94.5 of 2026-10-08 asks for this change: ascend-ocr and ascend-audio-scribe
become safe with several containers, with OCR job records and queue state in Redis, submitted files and results in
object storage, audio-scribe downloads in object storage, and every job visible from any container.

Read on 2026-10-08 in the code (line numbers move, so each task re-reads its file first):

- ascend-ocr keeps one JSON record, the submitted bytes and a progress file per job in one flat folder,
  `OCR_JOBS_DIR` (`src/service/job_store.py`, suffixes `.json`, `.input` and `.progress`, default
  `tempfile.gettempdir()/ascend-ocr-jobs`, no volume in `compose.yaml`). The record model is `JobRecord` in
  `src/model/ocr_models.py` (states `waiting`, `running`, `succeeded`, `failed`, `cancelled`, failure reasons
  `SERVICE_RESTARTED`, `LIFETIME_EXCEEDED`, `RESULT_STORE_UNAVAILABLE`). No lock guards it: safety rests on one event
  loop and an atomic file replace, and the API process is the only writer.
- The queue is a `collections.deque` of `QueueEntry` in `JobRunner` (`src/service/job_runner.py`), with in-memory
  reservations of pages and documents (`reserve`, `release`, `admit`), one consumer task, and the counts, positions,
  poll hints and `Retry-After` computed from that deque. `JobService.list_jobs` builds the listing from this runner
  only, and `/ready` reports its counts.
- `JobStore.recover_after_restart` fails every non-terminal record of the folder at start-up. With a folder that two
  containers share, a restart of one container would fail the running work of the other.
- The worker process writes the progress file between pages (`write_progress`, called from `src/service/ocr_service.py`).
  A cancel of running work removes the queue entry, writes the record and asks for a worker replacement of the process
  pool (`request_worker_replacement_for_cancel`), which only the container that runs the document can do.
- Results already live in object storage: `src/service/result_store.py`, boto3 through `asyncio.to_thread`, bucket
  `OCR_RESULT_S3_BUCKET` (default `ocr-results`), key `{job_id}.md`, presigned links through
  `OCR_RESULT_S3_PUBLIC_ENDPOINT`.
- ascend-audio-scribe keeps each transcript offered for download in the container's temp folder
  (`src/adapters/download_file_manager.py`: `store_transcript` writes `ascendaudioscribe_{file_id}_{filename}` and
  registers it in the in-process `_file_registry` under a `threading.Lock`, with `time.monotonic` timestamps).
  `GET /api/v1/transcribe/download/{file_id}` (`src/api/rest/rest_endpoints.py`, `download_transcript`) serves only a
  file of the same process. `run_cleanup_loop` removes expired files every `DOWNLOAD_CLEANUP_INTERVAL_SECONDS` (75)
  after `DOWNLOAD_FILE_TTL_SECONDS` (300). The input audio of a request (an upload or an MCP `audio_uri` download) is a
  temp file of that one request, deleted in its `finally`, and never seen by another request.
- Neither service has Redis or an S3 client of its own beyond the above today. `add-ascend-python-common` (build group 2,
  position 1, owner answer 94.3 of 2026-10-08) gives all four Python services `REDIS_URL` and the `redis` client pin
  for their rate limit windows, so both services reach the shared Redis prerequisite before this change starts.
  `add-python-runtime-upgrades` (build group 2, position 2, owner answer 94.2) runs every MCP server in stateless HTTP
  mode, so any container answers any MCP call.

## Goals / Non-Goals

Goals:

- Any container of ascend-ocr answers status, listing, cancel and removal of every job, and any container reads any
  waiting document in its turn.
- The queue bounds, the order and the one-document-at-a-time rule per container hold for the whole service.
- A stopped container fails only the document it was reading, and waiting work survives it.
- Any container of ascend-audio-scribe serves every transcript download until it expires.
- Every mechanism uses the one mechanism of CANON 26.1 for a Python service: Redis for cross-instance state, a pub/sub
  channel for a cross-instance signal, and timed work that is correct when every container runs it.

Non-Goals:

- No change to the REST and MCP contracts of either service: every route, tool, field, code and status stays.
- No change to the OCR engines, the page rendering, the quality modes, the allowances or any measured figure.
- No shared S3 client in `ascend-python-common`. Each service keeps one client module of its own (YAGNI).
- No compose shape for several containers (owner answer 98.6 of 2026-10-08). Local development runs one container of
  each service, so `compose.yaml` keeps one container of `ascend-ocr` and of `ascend-audio-scribe` with its
  `container_name` and its one published host port. No host port range, no `OCR_REPLICAS`, no `AUDIO_SCRIBE_REPLICAS`
  and no port publishing for further copies is planned. Callers inside Docker reach each service by its compose service
  name (`http://ascend-ocr:7022` and `http://ascend-audio-scribe:7017` in the agent's `application-docker.yaml`, read on
  2026-10-08), which Docker's network resolves to every copy. Every piece of this change that makes the two services
  safe with several copies stays. The deployment of several copies: company plans it later in
  `plan-scaled-deployment` (build group 5), this change does not wait for it (owner answer 99.1 of 2026-10-08, the
  change is created after this round). The e2e checks start a second container with `docker compose run`, which publishes no
  host port and needs no replica setting (D12).

## Decisions

### D1: One shared job store in Redis

Every job record is one Redis string of JSON under `ocr_job:{job_id}`, the same `JobRecord` fields as today plus
`owner_instance` (D4). Every change of a record, of the queue and of the counts is one Lua script, so it is atomic
across containers, and no code path writes a record outside the scripts:

| Key | Type | Holds | Expiry |
| --- | --- | --- | --- |
| `ocr_job:{job_id}` | string (JSON) | the record | none while not terminal, then the retention window from `finished_at` (D7) |
| `ocr_job_queue` | list | the identifiers of waiting jobs, oldest first | none |
| `ocr_job_queue_totals` | hash | `documents` and `pages` waiting | none |
| `ocr_jobs_running` | set | the identifiers of running jobs | none |
| `ocr_job_progress:{job_id}` | string | pages done of a running job (D6) | deleted at the terminal state |
| `ocr_job_lease:{job_id}` | string | the `owner_instance` holding a running job (D4) | the job's lease |
| `ocr_jobs_finished` | sorted set | terminal jobs scored by `finished_at` (D7) | none |
| `ocr_job_cancel` | pub/sub channel | the identifier of a cancelled running job (D5) | not stored |

The scripts are `submit` (write the record and append to the queue only when both bounds still hold, D2), `claim` (pop
the head of the queue for one container, move the record to `running`, add it to `ocr_jobs_running`, write the lease),
`finish` (write the terminal state, remove the job from `ocr_jobs_running`, delete its progress and lease keys, add it
to `ocr_jobs_finished`), `cancel` (D5) and `expire` (D4 and D7). `JobStore` keeps its public methods (`create`, `read`,
`start`, `fail`, `cancel`, `succeed`, `delete`, `records`, the sweeps) on top of these scripts, so `JobService` and both
surfaces keep their shape. The keys are built in one place in `src/service/job_store.py`.

Rejected: a Postgres table. ascend-ocr has no database, and Redis is the one store for cross-instance state of a Python
service (CANON 26.1). Rejected: a Redis stream with consumer groups. A stream gives at-least-once delivery and pending
lists, but the queue must also answer positions and pages ahead for every waiting job, which a list answers directly.

### D2: One queue, one consumer per container, bounds for the whole service

`submit` checks `OCR_JOB_QUEUE_MAX_DOCUMENTS` and `OCR_JOB_QUEUE_MAX_PAGES` against `ocr_job_queue_totals` and, in the
same script, appends the job and raises both totals. So two submissions on two containers can never both pass a bound
that only one fits under. A refusal keeps today's `QUEUE_FULL` with `Retry-After`. The in-memory `reserve` and
`release` of `JobRunner` go.

Each container keeps exactly one consumer task and one worker pool of `OCR_WORKER_COUNT`, as today. The consumer runs
`claim` when its worker is free, so the head of the shared queue goes to whichever container is free first, and a job
is claimed once. Order is strict submission order across the service. Each container still reads one document at a
time, so the per-container memory figures and the startup banner do not change.

Positions, pages ahead, the poll hint and `Retry-After` are computed from the shared queue and the running set, with
the same formulas as today. With several containers the promised wait stays an upper bound, because more than one
worker drains the queue. The three inputs of the poll hint that are module constants of `src/service/job_runner.py`
today (10 wakes per wait, held between 1 and 30 seconds) become the settings `OCR_JOB_POLL_HINT_WAKES_PER_WAIT`,
`OCR_JOB_POLL_HINT_MIN_SECONDS` and `OCR_JOB_POLL_HINT_MAX_SECONDS` with the same defaults (owner rule 98 of
2026-10-08, task 2.4).

### D3: Submitted bytes in object storage

The submitted bytes of a job are written at submission to the bucket `OCR_RESULT_S3_BUCKET` under the key
`inputs/{job_id}`, through the existing `ResultStore` client (its upload attempts and back-off), before `submit` runs.
When the upload still fails, the job is recorded straight away as failed with the existing record reason
`RESULT_STORE_UNAVAILABLE` (retryable), the submission answers as an accepted job with its identifier as today, and
nothing is queued. No new error code is needed, because that reason already lives inside a job record. The claiming
container reads them back when the job starts. `finish`, `cancel` and every expiry delete the object, as today the
input file is deleted. Results keep the key `{job_id}.md`, so the `result` location the agent and the Pact contract read
does not change. The two prefixes keep the bucket's rule that it holds only this service's objects: results may be
expired after the retention window, and `inputs/` objects after `OCR_JOB_MAX_LIFETIME_SECONDS`, the longest any job can
live. `OCR_JOBS_DIR` is deleted, and a leftover value in the environment is ignored rather than refused, the rule the
service already uses for deleted settings. The `ResultStore` client values that the submitted bytes now reuse are module
constants of `src/service/result_store.py` today (read on 2026-10-08): connect timeout 5 seconds, read timeout 30
seconds, 3 upload attempts, a retry base of 0.5 seconds and the region `us-east-1`. Each becomes a setting with the same
default (owner rule 98 of 2026-10-08, D11, task 3.3), because an operator of a real object store may need to change any
of them.

### D4: Who reads a document, and what happens when that container stops

Each container gets an `owner_instance` at start: its host name and a random suffix made at process start, so a
restarted container is a new owner. `claim` writes it into the record and into `ocr_job_lease:{job_id}` with an expiry
of the job's reclamation grace (`reclamation_grace_seconds` of the job's model pair: one page allowance plus
`OCR_DISPATCH_MARGIN_SECONDS`, 117.95 seconds at the defaults). The consumer renews the lease every
`OCR_JOB_IDLE_TICK_SECONDS` while the document runs. That setting replaces the runner's module constant
`IDLE_TICK_SECONDS` (5 seconds, `src/service/job_runner.py`, read on 2026-10-08) with the same default, because the tick
now also paces the lease and the sweeps of every container and an operator may need to change it (owner rule 98 of
2026-10-08). The service refuses to start, naming both values, when the tick is not positive or is not shorter than
the shortest reclamation grace of any engine a supported language can load, because a lease would then lapse while
its document still runs. The lease expiry itself stays derived from the allowance, so no new time value is needed.

The `expire` script, run by every container on its idle tick, finds each job in `ocr_jobs_running` whose lease key no
longer exists and fails it with `SERVICE_RESTARTED` (retryable, as today), deleting its submitted bytes. A job is
failed once, because the script removes it from `ocr_jobs_running` in the same step. `recover_after_restart` goes:
waiting jobs are no longer failed at start-up, because they wait in the shared queue with their bytes in object
storage. This replaces the requirement "Work in flight when the service stopped is failed" for waiting work, which only
existed because the queue lived in one process.

### D5: Cancel from any container

`cancel` on any container runs the `cancel` script: a waiting job leaves the queue and the totals and reads
`cancelled`, a finished job is deleted with its result (today's `delete`). A running job reads `cancelled` at once and
leaves `ocr_jobs_running`, and the script publishes the identifier on `ocr_job_cancel`. Each container subscribes to
the channel in its lifespan. The container whose consumer runs that job calls its existing
`request_worker_replacement_for_cancel`, the path a local cancel uses today. A missed message is caught on the next
idle tick, when the consumer re-reads its running job's record and finds it `cancelled`. `_store_result` keeps its
check that deletes a result whose job was cancelled while it was being stored. A publish error is logged once at
WARNING and the cancel still stands, because the record is the source of truth and the tick finds it.

### D6: Progress from the worker in Redis

The worker process writes the pages done of its job to `ocr_job_progress:{job_id}` between pages, through a small
synchronous Redis client it opens at worker start from `REDIS_URL`, instead of the progress file. Every container reads
that key for status, listing and the pages still ahead. A write error in the worker is logged at WARNING and never
fails the page.

### D7: Sweeps that every container runs

The retention sweep (`OCR_JOB_RETENTION_SECONDS`, `OCR_JOB_MAX_RETAINED`), the lifetime sweep (`LIFETIME_EXCEEDED`
past `OCR_JOB_MAX_LIFETIME_SECONDS`) and the lease expiry of D4 run on every container on its idle tick. Each removal
is one script that acts only while the job still qualifies, so two containers that sweep at the same moment remove a
job once and both succeed, and an S3 delete of an object that is already gone is harmless. This is timed work that is
correct when every container runs it, so it takes no lock (CANON 26.1). A finished record also carries a Redis expiry
of the retention window, as a backstop if no container runs.

### D8: Readiness and metrics report the whole service

`/ready` keeps its fields and status rules. `jobs_queued` reads the length of `ocr_job_queue` and `jobs_running` the
size of `ocr_jobs_running`, so every container reports the same counts. The queue gauges
(`ascendocr_job_queue_documents`, `ascendocr_job_queue_pages`) become service-wide values that every container
exports, so a dashboard panel that sums them over containers counts them twice: the Grafana panels that read them use
`max` across containers. A Redis that cannot be reached makes `/ready` report not-ready with a `redis` check, because
the service cannot admit or claim work without it.

### D9: Audio transcripts in object storage

`store_transcript` writes the transcript to object storage under `transcripts/{file_id}/{filename}` and records
`audio_transcript:{file_id}` in Redis (the object key, the file name, the content type) with an expiry of
`DOWNLOAD_FILE_TTL_SECONDS`, and adds the identifier to the sorted set `audio_transcripts_expiry` scored by its expiry
time. `download_transcript` reads the Redis entry on any container and streams the object with the same file name and
content type as today, or answers the existing 404 when the entry is gone. `run_cleanup_loop` keeps its interval and
now removes, on every container, each identifier of `audio_transcripts_expiry` whose time has passed: one script removes
the member only while it is still due, then the object is deleted, so two containers remove a transcript once and an
already deleted object is harmless (CANON 26.1, timed work correct on every container). The in-process registry, its
lock and the temp folder files go. The `stream=false` answer keeps today's `FileResponse`, built from the transcript in
memory, and still stores the transcript for download as it does today.

The S3 client is a new module `src/adapters/transcript_store.py` (boto3 through `asyncio.to_thread`, the pattern of
ascend-ocr's `result_store.py`), configured by `OBJECT_STORE_S3_ENDPOINT`, `OBJECT_STORE_S3_ACCESS_KEY` and
`OBJECT_STORE_S3_SECRET_KEY`, the shared names `enhance-web-search-crawl-at-scale` D3 introduced for ascend-web-hunter,
and the new `TRANSCRIPT_S3_BUCKET`, default `audio-transcripts` (owner answer 98.5 of 2026-10-08). The client's region
is the new setting `TRANSCRIPT_S3_REGION`, default `us-east-1`, the region ascend-ocr's result store and the agent's
client name for the same store. The client's connect
and read timeouts are the new settings `TRANSCRIPT_S3_CONNECT_TIMEOUT_SECONDS` and `TRANSCRIPT_S3_READ_TIMEOUT_SECONDS`
(owner rule 98 of 2026-10-08), never module constants. Their defaults are not decided (ascend-ocr's `result_store.py`
uses the constants 5 and 30 seconds today, read on 2026-10-08, listed for the owner). The bucket is created at start when missing, and a store that cannot be reached
shows in the startup banner and in `/ready` as a check of its own. ascend-audio-scribe pins `boto3` at the version
ascend-ocr pins (`boto3==1.42.6` on 2026-10-08, re-read at implementation time).

The input audio of a request stays a temp file of that request on the container's disk (owner answer 98.7 of
2026-10-08). One request uses it inside one container and deletes it in its `finally`, so no other container ever needs
it (rule R1 holds). Only the transcript download files move to object storage.

### D10: What stays per container

The OCR engine cache, the worker process pool, its admission permit and its replacement on cancel or failure, the SSE
progress queue of a streamed transcription (one held connection), and the request's own temp files stay per
container, because each belongs to that container's process and to one request. Every one of them is correct when each
container keeps its own.

### D11: Settings

Deleted: `OCR_JOBS_DIR` (D3). Added in ascend-ocr: `OCR_JOB_IDLE_TICK_SECONDS` (D4, default 5), and the five
result store client values of D3, `OCR_RESULT_S3_CONNECT_TIMEOUT_SECONDS` (5), `OCR_RESULT_S3_READ_TIMEOUT_SECONDS`
(30), `OCR_RESULT_S3_UPLOAD_MAX_ATTEMPTS` (3), `OCR_RESULT_S3_UPLOAD_RETRY_BASE_SECONDS` (0.5) and
`OCR_RESULT_S3_REGION` (`us-east-1`), and the three poll hint values of D2, `OCR_JOB_POLL_HINT_WAKES_PER_WAIT` (10),
`OCR_JOB_POLL_HINT_MIN_SECONDS` (1) and `OCR_JOB_POLL_HINT_MAX_SECONDS` (30), each with the same default in code and on
the compose line. Added in
ascend-audio-scribe (D9): `TRANSCRIPT_S3_BUCKET` (default `audio-transcripts`), `TRANSCRIPT_S3_REGION` (default
`us-east-1`), `OBJECT_STORE_S3_ENDPOINT` (default
`http://localhost:9070` for a native run), `OBJECT_STORE_S3_ACCESS_KEY` and `OBJECT_STORE_S3_SECRET_KEY` (secrets, no
default), `TRANSCRIPT_S3_CONNECT_TIMEOUT_SECONDS` and `TRANSCRIPT_S3_READ_TIMEOUT_SECONDS` (defaults not decided).
Reused: `REDIS_URL` of both services
(`add-ascend-python-common` tasks 3.15 and 5.8), `OCR_RESULT_S3_*` for the submitted bytes, every existing queue, retention and
lifetime setting, and `DOWNLOAD_FILE_TTL_SECONDS` and `DOWNLOAD_CLEANUP_INTERVAL_SECONDS`.

Every added setting with a default follows owner rule 98 of 2026-10-08: a `Settings` field with that default, read
from its upper case environment name, and the compose line `- VAR=${VAR:-default}` on its service. In `compose.yaml`
the `ascend-ocr` service gets `OCR_JOB_IDLE_TICK_SECONDS=${OCR_JOB_IDLE_TICK_SECONDS:-5}` and the five result store
client values and the three poll hint values in the same form, and the `ascend-audio-scribe` service gets
`TRANSCRIPT_S3_BUCKET=${TRANSCRIPT_S3_BUCKET:-audio-transcripts}`,
`TRANSCRIPT_S3_REGION=${TRANSCRIPT_S3_REGION:-us-east-1}`, the two timeouts
in the same form with their decided defaults, and
`OBJECT_STORE_S3_ENDPOINT=${OBJECT_STORE_S3_ENDPOINT:-http://host.docker.internal:9070}` (reached through its
`extra_hosts` line from `fix-linux-docker-host-access` task 2.1). The endpoint is the one value whose compose default
differs from the code default, because the code default serves a native run and the compose default the container,
the same split the existing `OCR_RESULT_S3_ENDPOINT` has. The two keys are secrets: no default in code or in compose,
in the form `enhance-web-search-crawl-at-scale` task 1.3 gives them, read from the repository `.env` (owner answer 85.1
of 2026-10-08). No `.env.example` line is added for a setting with a default. The rows go into
`apps/ascend-ocr/docs/CONFIGURATION.md` for ascend-ocr and into `docs/CONFIGURATION.md` for ascend-audio-scribe, which
has no reference of its own, in the same commit as the setting (owner rule 98, tasks 2.4, 3.3, 4.3 and 9.5).

### D12: Tests

Unit tests run the scripts against a Redis that runs Lua in the test, the same test tool `enhance-web-search-crawl-at-scale`
task 4.4 chose (it lands earlier, in build group 2, and names the tool in its CHANGELOG entry), and S3 through the fakes
`tests/service/test_result_store.py` already uses. Every multi-container rule has a test with two simulated containers
(two `JobRunner`, `JobService` and `JobStore` sets with two `owner_instance` values on one Redis, and two audio app
instances on one Redis and one fake bucket). Each service gate keeps its 100 percent branch coverage. The e2e specs are
updated in place (owner answer 67.2 of 2026-10-04, no new spec): ascend-ocr spec 14 (listing) and spec 15 (cancel) gain
a part with a second container started by `docker compose run`, and ascend-audio-scribe spec 2 gains a streamed
transcription whose download link is read on a second container. These specs run only when the owner chooses a scenario
(the rule of `docs/E2E_RUN_SCENARIOS.md`), and the OCR specs stay engine-bound specs that run alone.

### D13: Versions

One named version per change, in build order (owner decision of 2026-10-08): each of the two services moves one patch
step above the highest version an earlier change in the build order names for it. The numbers are read at
implementation time from `openspec/BUILD_ORDER.md` and the earlier changes, because `add-python-runtime-upgrades` and
`harden-cloud-deployment` may name versions of their own first.

## Risks / Trade-offs

- [Redis becomes a hard dependency of ascend-ocr's job path] → It already is a prerequisite of the stack and every
  Python service reads `REDIS_URL` after `add-ascend-python-common`. `/ready` reports it (D8), and a submission while
  Redis is down fails with the existing internal error answer and records nothing, so no work is lost unseen.
- [The promised wait is no longer exact with several containers] → It stays an upper bound, which is what a caller
  needs, and the documentation says so (D2).
- [A container killed during a document holds it for one reclamation grace] → The lease bounds it at 117.95 seconds at
  the defaults, and the job then fails as retryable.
- [Two copies of the queue gauges] → Dashboards read `max` (D8).
- [The object store now holds waiting bytes] → They live at most `OCR_JOB_MAX_LIFETIME_SECONDS`, are deleted at every
  terminal state, and an operator may expire `inputs/` objects older than that.

## Migration Plan

1. Land after `harden-cloud-deployment` (build group 3, position 4). Both services already read `REDIS_URL`.
2. Deploy: the old on-disk records are not carried over (owner answer 73.1 of 2026-10-06: today's data is disposable).
   Work in flight at the moment of the upgrade is resubmitted by its caller, as after any restart today.
3. Rollback: the previous images. Records written to Redis are then ignored and expire on their own.

## Open Questions

1. The default of `TRANSCRIPT_S3_BUCKET` and its value in `compose.yaml`. Answered by owner answer 98.5 of 2026-10-08:
   `audio-transcripts` (D9, D11).
2. How compose starts several containers of `ascend-ocr` and `ascend-audio-scribe`. Answered by owner answer 98.6 of
   2026-10-08: it does not. Local development runs one container of each, no host port range and no replica setting is
   planned. The deployment of several copies: company plans it later in `plan-scaled-deployment` (build group 5), this
   change does not wait for it (Non-Goals).
3. Whether "audio-scribe downloads" in answer 94.5 also means the input audio of a request. Answered by owner answer
   98.7 of 2026-10-08: no, the input audio stays a temporary file of the request (D9).

Values nobody decided: the defaults of `TRANSCRIPT_S3_CONNECT_TIMEOUT_SECONDS` and `TRANSCRIPT_S3_READ_TIMEOUT_SECONDS`
(D9, task 9.1).

## Owner decisions of 2026-10-08

Answer 94.5: this change exists by owner answer 94.5 of 2026-10-08, in build group 3 directly after
`harden-cloud-deployment`, as position 5. It makes ascend-ocr and ascend-audio-scribe safe with several containers:
OCR job records and queue state in Redis (D1, D2), submitted files and results in object storage (D3), audio-scribe
downloads in object storage (D9), and every job visible from any container (D1, D5, D6, D8). It is spec-driven, created
2026-10-08, with tests (D12) and the e2e spec updates in place.

Answer 87 (rule R1): every mechanism of this change is the one of CANON 26.1 for a Python service: Redis for shared
state (D1, D2, D6, D9), a Redis lease for the ownership of running work (D4), a Redis pub/sub channel with a poll
fallback for a cancel (D5), and timed work that is correct when every container runs it, with each step guarded by a
script (D7, D9).

Answer 94.3: both services reach Redis through the `REDIS_URL` that `add-ascend-python-common` gives them for their rate
limit windows, so this change adds no Redis setting.

Answer 94.2: every MCP server runs in stateless HTTP mode (`add-python-runtime-upgrades`), so the MCP tools of both
services are served by any container once the job state of this change is shared.

Answer 98 (owner rule 98, every value with a default is a setting): made external, each as a `Settings` field with the
default in code and `- VAR=${VAR:-default}` on its compose service: `OCR_JOB_IDLE_TICK_SECONDS` (ascend-ocr, default 5,
replacing the module constant `IDLE_TICK_SECONDS`, D4, task 4.3), `TRANSCRIPT_S3_BUCKET` (default `audio-transcripts`),
`OBJECT_STORE_S3_ENDPOINT` (default `http://localhost:9070` in code for a native run and
`http://host.docker.internal:9070` on the compose line, the split of the existing `OCR_RESULT_S3_ENDPOINT`),
`TRANSCRIPT_S3_REGION` (default `us-east-1`), `TRANSCRIPT_S3_CONNECT_TIMEOUT_SECONDS` and
`TRANSCRIPT_S3_READ_TIMEOUT_SECONDS` (defaults not decided), all of ascend-audio-scribe (D9, D11, task 9.1). The resumed
round of 2026-10-08 also made external the five module constants of ascend-ocr's `src/service/result_store.py` that the
submitted bytes reuse: `OCR_RESULT_S3_CONNECT_TIMEOUT_SECONDS` (5), `OCR_RESULT_S3_READ_TIMEOUT_SECONDS` (30),
`OCR_RESULT_S3_UPLOAD_MAX_ATTEMPTS` (3), `OCR_RESULT_S3_UPLOAD_RETRY_BASE_SECONDS` (0.5) and `OCR_RESULT_S3_REGION`
(`us-east-1`) (D3, D11, task 3.3). `OBJECT_STORE_S3_ACCESS_KEY` and `OBJECT_STORE_S3_SECRET_KEY` are secrets with
no default, read from `.env`. The lease expiry, the Redis expiry of a finished record, the expiry of a transcript entry
and the lifetime of `inputs/` objects stay derived from existing settings (`reclamation_grace_seconds`,
`OCR_JOB_RETENTION_SECONDS`, `DOWNLOAD_FILE_TTL_SECONDS`, `OCR_JOB_MAX_LIFETIME_SECONDS`). Kept as constants, because
they are not operational: the Redis key and channel names of D1 and D9 (`ocr_job:{job_id}`, `ocr_job_queue`,
`ocr_job_queue_totals`, `ocr_jobs_running`, `ocr_job_progress:{job_id}`, `ocr_job_lease:{job_id}`,
`ocr_jobs_finished`, `ocr_job_cancel`, `audio_transcript:{file_id}`, `audio_transcripts_expiry`), the object key layouts
`inputs/{job_id}`, `{job_id}.md` and `transcripts/{file_id}/{filename}`, the failure reasons and the metric names. The
boto3 pin stays a value read at implementation time. Rows: `apps/ascend-ocr/docs/CONFIGURATION.md` (the new row ends
"Added by `scale-ocr-and-audio-across-containers`.", the `OCR_JOBS_DIR` row goes) and `docs/CONFIGURATION.md` for
ascend-audio-scribe, in the same commit as the setting (tasks 2.4, 3.2, 3.3, 4.3 and 9.5). The poll hint of task 2.3, computed
with today's formula, reads three module constants of `src/service/job_runner.py` today, which become settings with
the same defaults: `OCR_JOB_POLL_HINT_WAKES_PER_WAIT` (10), `OCR_JOB_POLL_HINT_MIN_SECONDS` (1) and
`OCR_JOB_POLL_HINT_MAX_SECONDS` (30) (D2, D11, task 2.4). No test or measurement of this change
uses LM Studio: the one paid model call is the OpenAI transcription of ascend-audio-scribe spec 2 (task 10.4).

Answer 98.5: the transcript bucket is `audio-transcripts`, setting `TRANSCRIPT_S3_BUCKET` (D9, D11, tasks 9.1 and
9.5). This closes Open Question 1.

Answer 98.6: no host port ranges, no `OCR_REPLICAS`, no `AUDIO_SCRIBE_REPLICAS` and no port publishing for further
copies. None of them was written into a task of this change, so no task is removed, and Open Question 2, which asked
for that compose shape, is closed. Local development runs one container of each service, and callers inside Docker
reach each service by its compose service name, which Docker's network resolves to every copy. Every mechanism that
makes ascend-ocr and ascend-audio-scribe safe with several copies stays (D1 to D10). The deployment of several copies:
company plans it later in `plan-scaled-deployment` (build group 5), this change does not wait for it (owner answer
99.1, the change is created after this round, Non-Goals). The e2e Part B of ascend-ocr specs 14 and 15 and the
second container of ascend-audio-scribe spec 2 stay as test steps: `docker compose run -d --no-deps --name ascend-ocr-2
ascend-ocr` publishes no host port (`docker compose run` publishes ports only with `--service-ports`), the spec reaches
the second container with `docker exec` on its own `localhost`, and the first container keeps its one published port,
so the steps need none of the removed publishing (tasks 10.2 to 10.4, unchanged).

Answer 98.7: the input audio of an ascend-audio-scribe request stays a temporary file of that request, and only the
transcript download files move to object storage (D9). This closes Open Question 3.

Answer 99.1: `plan-scaled-deployment` (company, build group 5, a Kubernetes Helm chart with a Horizontal Pod
Autoscaler for company deployments, created after this round) plans how several copies of each service are deployed.
Company plans it later in `plan-scaled-deployment` (build group 5), this change does not wait for it, and names it
only in that form (Non-Goals, Open Question 2, proposal).

## Owner decisions of 2026-10-09

Answer 100.6: every published host port is a setting `${<SERVICE>_HOST_PORT:-<today's port>}:<container port>`. The one published host port each of ascend-ocr and ascend-audio-scribe keeps is the setting `add-ascend-python-common` gives it (`OCR_HOST_PORT` 7022 in task 5.14 and `AUDIO_SCRIBE_HOST_PORT` 7017 in task 3.18), with the bind address of `harden-cloud-deployment` task 1.1 in front. This change adds no published port, so no task changes. A second container started with `docker compose run` still publishes no host port.
