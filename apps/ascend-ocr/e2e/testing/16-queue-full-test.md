# The queue refusing work past its bound: e2e test

## What this verifies

- A submission that would put more documents in the queue than `OCR_JOB_QUEUE_MAX_DOCUMENTS` allows is refused at the
  request boundary with HTTP 503, the code `QUEUE_FULL`, and a `Retry-After` header in whole seconds.
- The refusal issues no identifier and queues nothing: the listing and the readiness counters are the same after the
  refused submission as before it.
- The service is busy, not broken: `/ready` still reads `ready` while the queue is full.
- Every submission up to the bound is accepted, so the refusal is the bound working and not the service refusing
  everything.

## How the queue is filled

The queue has two bounds, read in this order by `JobRunner.reserve` in `src/service/job_runner.py`. The document bound
counts waiting documents only, never the one being read, and refuses a submission once that count reaches
`OCR_JOB_QUEUE_MAX_DOCUMENTS` (default 8). The page bound refuses a submission whose pages, added to every unread page
ahead of it, running document included, would pass `OCR_JOB_QUEUE_MAX_PAGES` (default 200).

The cheapest honest way to reach a bound on a running container, with no setting changed and no restart, is the
document bound. Put the twenty five page fixture on the worker first, which holds it for about three minutes (spec 13
measured 172.1 seconds for it on image `7605748a6afa` on 2026-09-25, about 7 seconds a page in `high` mode), then
submit single page images until eight are waiting. The ninth single page
image is the one refused. That is ten submissions and about 2 MB of upload, and the refusal lands on the same
submission however far the worker has got, because the document bound never counts the running document. Reaching the
page bound instead takes about as much upload, nine copies of the twenty five page fixture, but where it refuses
depends on how many pages of the running document are still unread when each copy arrives, so the count this spec
asserts would drift with the host's speed. The page bound is covered by the unit suite
(`tests/service/test_job_runner.py`) and is not exercised here.

A `Retry-After` value follows from the same numbers. It is the poll hint for every unread page ahead of a new
submission, a tenth of every unread page ahead at its own engine's page allowance, held between 1 and 30 seconds.
With at least eight English pages waiting at the default allowance of 112.95 seconds a page the hint is 90 seconds or
more, so the header reads exactly `30`.

## Prerequisites

Check Bruno CLI is installed.

```bash
bru --version
```

Expect a version string.

Check the ascend-ocr server is reachable.

```bash
curl -fsS http://localhost:7022/health
```

Expect HTTP 200 with `"status":"ok"` in the body.

Check the fixtures exist.

```bash
ls apps/ascend-ocr/e2e/fixtures/halcyon-ledger-25-pages.pdf apps/ascend-ocr/e2e/fixtures/argent-saga-chronicles-page1.png
```

Expect both file paths printed.

This spec assumes the container runs the code defaults for the queue and the allowance. Check each of the four.

```bash
docker exec ascend-ocr printenv OCR_JOB_QUEUE_MAX_DOCUMENTS
```

Expect nothing printed, which means the default of 8. If the operator set a value, the refusal comes at the
submission after that many single page images instead of after eight, and every count of eight below changes with it.

```bash
docker exec ascend-ocr printenv OCR_JOB_QUEUE_MAX_PAGES
```

Expect nothing printed, which means the default of 200. Any value of at least 34 works, so the page bound cannot fire
before the document bound does: 25 unread pages of the running document plus eight waiting pages plus the refused one.

```bash
docker exec ascend-ocr printenv OCR_PAGE_ALLOWANCE_HEADROOM
```

Expect nothing printed, which means the default headroom of 4.5 and an allowance of 112.95 seconds an English page,
which is what makes the header read `30`. Any headroom of at least 1.5 keeps it there.

```bash
docker exec ascend-ocr printenv RATE_LIMIT_OCR
```

Expect `20/minute`, which `compose.yaml` sets. The spec makes ten submissions, and they must all land within one
minute of each other without meeting that limit. A limit below 10 per minute answers 429 before the queue is full,
which is a failure of the setup, not of this spec.

Check the fixture's page count against the page ceiling, because the long document has to be accepted.

```bash
docker exec ascend-ocr printenv OCR_JOB_MAX_PAGES
```

Expect nothing printed, which means the default of 100, or a value of at least 25.

## Reset state

Drop every job record the service holds, so the queue this spec fills is empty when it starts.

```bash
docker exec ascend-ocr sh -c 'rm -f /tmp/ascend-ocr-jobs/*'
```

Drop every stored result. The command names the `ocr-results` bucket literally, which belongs to this service alone.
Never issue a command that sweeps buckets instead of naming one, because the same object store also backs other
projects on this machine.

```bash
curl -fsS "http://localhost:9070/ocr-results?list-type=2" | grep -o "<Key>[^<]*</Key>" | sed -e "s/<Key>//" -e "s|</Key>||" | xargs -I {} curl -fsS -X DELETE "http://localhost:9070/ocr-results/{}"
```

Confirm the service is idle before starting.

```bash
curl -fsS http://localhost:7022/ready
```

Expect `"status":"ready"`, `"jobs_queued":0` and `"jobs_running":0`.

## Run

```bash
cd docs/api/request/AscendAI
```

Step 1. Submit the twenty five page document. Record its `job_id`.

```bash
bru run "ocr/testing/ocr-long-document.yml" --env ascend-local
```

Step 2. Read its state until it reads `running`. Only a document the worker has taken off the queue stops counting
against the document bound, so do not start step 3 before this.

```bash
bru run "ocr/ocr-job-status.yml" --env ascend-local --env-var "ocrJobId=<long job_id>"
```

Step 3. Submit the single page image eight times, one after another, without waiting for any of them. Record each
`job_id` in submission order.

```bash
bru run "ocr/ocr.yml" --env ascend-local
```

Step 4. Read the listing and the readiness counters while the queue is full.

```bash
bru run "ocr/ocr-jobs-list.yml" --env ascend-local
```

```bash
curl -fsS http://localhost:7022/ready
```

Step 5. Submit the single page image a ninth time.

```bash
bru run "ocr/testing/ocr-queue-full.yml" --env ascend-local
```

Step 6. Read the listing and the readiness counters again.

```bash
bru run "ocr/ocr-jobs-list.yml" --env ascend-local
```

```bash
curl -fsS http://localhost:7022/ready
```

Step 7. Clean up. Delete the eight waiting documents first, then the running one, which cancels it and replaces the
worker. Then read each identifier once more.

```bash
bru run "ocr/ocr-job-delete.yml" --env ascend-local --env-var "ocrJobId=<each job_id in turn>"
```

```bash
bru run "ocr/ocr-job-status.yml" --env ascend-local --env-var "ocrJobId=<each job_id in turn>"
```

Step 8. Delete each record again, now that every one of them is finished, so nothing is left behind. Then read each
identifier once more.

```bash
bru run "ocr/ocr-job-delete.yml" --env ascend-local --env-var "ocrJobId=<each job_id in turn>"
```

```bash
bru run "ocr/testing/ocr-job-not-found.yml" --env ascend-local --env-var "ocrJobId=<each job_id in turn>"
```

## Expected

Step 1:

- HTTP 202, `page_count` 25.

Step 2:

- The last read is HTTP 200 with `state` `running`.

Step 3:

- All eight answer HTTP 202 with a `job_id`, `state` `waiting` and `page_count` 1. The first reports `queue_position` 1
  and each later one a position one higher, ending at 8.

Step 4:

- The listing has nine entries: the long document first with `state` `running`, then the eight single page images in
  submission order with `state` `waiting`.
- `/ready` reads `status` `ready`, `jobs_running` 1 and `jobs_queued` 8. A full queue is busy, and busy stays ready.

Step 5:

- HTTP 503.
- Body `code` equals `QUEUE_FULL`.
- A `Retry-After` header is present, a whole number of seconds, and equals `30` under the defaults the prerequisites
  checked.
- No `job_id` in the body and no `Location` header.

Step 6:

- The listing is the same nine entries as in step 4, in the same order, with no tenth entry.
- `/ready` still reads `jobs_running` 1 and `jobs_queued` 8.

Step 7:

- HTTP 204 for all nine deletes, after which each identifier reads `cancelled`.

Step 8:

- HTTP 204 for all nine, after which each identifier answers 404 `JOB_NOT_FOUND`, and the `ocr-results` bucket holds
  no object for any of them.

## Fixtures

- [`apps/ascend-ocr/e2e/fixtures/halcyon-ledger-25-pages.pdf`](../fixtures/halcyon-ledger-25-pages.pdf), to hold the
  worker long enough for the queue to fill behind it.
- [`apps/ascend-ocr/e2e/fixtures/argent-saga-chronicles-page1.png`](../fixtures/argent-saga-chronicles-page1.png), the
  single page image submitted nine times. The text is never read by this spec, only its page count matters.

## Concurrency

Engine-bound, and it fills the one queue every engine-bound spec of this suite shares. It runs alone: no runner of any
suite active while it is in flight, from this suite or from any other module's sweep, not even a reject-fast spec of
this suite. Anything another runner submits during steps 3 to 6 changes the counts this spec asserts, and a full
queue refuses the other runner's own submission with the same 503.

The whole run from step 1 to step 6 has to fit inside the time the long document holds the worker, about 172 seconds
on a quiet host (spec 13, image `7605748a6afa`, 2026-09-25). Ten `bru run` invocations fit, at about 5 to 6 seconds
each, but do not pause between steps. If the long document finishes before step
5, the queue has drained below its bound: reset and run again rather than recording a failure. The cleanup cancels the
running document and replaces the worker, so run this spec after the shorter engine-bound specs of this suite, not
between them, and before specs 14 and 13, the two long specs that run last.
