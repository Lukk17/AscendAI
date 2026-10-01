# Cancelling a document while it is being read: e2e test

## What this verifies

- `DELETE /v1/ocr/jobs/{job_id}` on a document the worker is reading right now answers 204, and the record then reads
  `cancelled`, with `error_code` and `result` both null and no `poll_after_seconds` key at all.
- The reading really stops. `pages_done` on the cancelled record does not change across reads taken fifteen seconds
  apart, and never exceeds the document's own page count.
- Nothing of the cancelled document reaches the `ocr-results` bucket: there is no object under its identifier.
- The worker comes back. The service returns to `ready` with nothing queued or running, and the next document,
  submitted after `/ready` reads `ready`, has nothing ahead of it, waits in the queue less than 5 seconds instead of
  waiting out the rest of the cancelled document, and succeeds with the canary in its Markdown.

This is the regression the job surface shipped with and then fixed: a cancel of running work used to leave the worker
reading the whole document, because the pool shutdown waited for the work item in flight, and the work item is the
whole document. The service now kills the worker on a cancel and starts a new one. If the old worker were still
reading, the next document would wait in the queue for every page of the cancelled document still unread when the
cancel landed. The queue wait bound in step 9 tells the two apart. "Why 5 seconds" under Expected gives the numbers.

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

Expect both file paths printed. If either is missing, regenerate it per
[`apps/ascend-ocr/e2e/fixtures/README.md`](../fixtures/README.md).

Check the page ceiling the container is running with, because the long document has to be accepted.

```bash
docker exec ascend-ocr printenv OCR_JOB_MAX_PAGES
```

Expect nothing printed, which means the code default of 100, or a value of at least 25 if the operator set one.

Check the object store is reachable.

```bash
curl -fsS http://localhost:9070/_floci/health
```

Expect HTTP 200 with `"s3":"running"` in the JSON body.

## Reset state

Drop every job record the service holds.

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

Step 1. Submit the twenty five page document. Read `job_id` from the answer: this is the cancelled job.

```bash
bru run "ocr/testing/ocr-long-document.yml" --env ascend-local
```

Step 2. Read the state, waiting `poll_after_seconds` between reads, until it reads `running` with `pages_done` of at
least 1. Record the last `pages_done` you saw.

```bash
bru run "ocr/ocr-job-status.yml" --env ascend-local --env-var "ocrJobId=<cancelled job_id>"
```

Step 3. Cancel it, and record the UTC time the answer arrived.

```bash
bru run "ocr/ocr-job-delete.yml" --env ascend-local --env-var "ocrJobId=<cancelled job_id>"
```

Step 4. Read the cancelled record immediately. Record `pages_done`.

```bash
bru run "ocr/testing/ocr-job-cancelled.yml" --env ascend-local --env-var "ocrJobId=<cancelled job_id>"
```

Step 5. Wait fifteen seconds, then read it again. Record `pages_done`.

```bash
bru run "ocr/testing/ocr-job-cancelled.yml" --env ascend-local --env-var "ocrJobId=<cancelled job_id>"
```

Step 6. Look for a result object under the cancelled identifier.

```bash
bru run "ocr/testing/ocr-result-absent.yml" --env ascend-local --env-var "ocrJobId=<cancelled job_id>"
```

Step 7. Read readiness, repeating every five seconds for up to 60 seconds until it reads `ready`. A replaced worker
reports `not-ready` while it comes up, which is expected here and not a failure.

```bash
curl -fsS http://localhost:7022/ready
```

Step 8. Only once step 7 has read `ready`, submit the next document. Read its `job_id`.

```bash
bru run "ocr/ocr.yml" --env ascend-local
```

Step 9. Read its state, waiting `poll_after_seconds` between reads, until it is terminal.

```bash
bru run "ocr/ocr-job-status.yml" --env ascend-local --env-var "ocrJobId=<next job_id>"
```

Step 10. Collect its result.

```bash
bru run "ocr/ocr-job-result.yml" --env ascend-local --env-var "ocrResultUrl=<result.url from step 9>"
```

Step 11. Delete both jobs, the cancelled one and the next one, then read each once more.

```bash
bru run "ocr/ocr-job-delete.yml" --env ascend-local --env-var "ocrJobId=<each job_id in turn>"
```

```bash
bru run "ocr/testing/ocr-job-not-found.yml" --env ascend-local --env-var "ocrJobId=<each job_id in turn>"
```

## Expected

Step 1:

- HTTP 202, `page_count` 25, `state` `waiting`.

Step 2:

- Every read is HTTP 200, and the last one reads `running` with `pages_done` between 1 and 24.

Step 3:

- HTTP 204.

Steps 4 and 5:

- HTTP 200 on both, `state` `cancelled` on both.
- `error_code` and `result` are null, the `poll_after_seconds` key is absent, and `finished_at` is set.
- `pages_done` is the same number on both reads, and it is never above 25.

Step 6:

- HTTP 404 from the object store. There is no `<cancelled job_id>.md` in the `ocr-results` bucket.

Step 7:

- Within 60 seconds of the cancel, `status` reads `ready` with `jobs_queued` 0 and `jobs_running` 0. The cancelled
  document is not running any more.

Step 8:

- HTTP 202, with `queue_position` 0 and `pages_ahead` 0. Nothing of the cancelled document is ahead of it.

Step 9:

- The terminal state is `succeeded`.
- Its queue wait, `started_at` minus `submitted_at` on the terminal read, is less than the queue wait bound of 5
  seconds. Both are the service's own epoch timestamps on the same record, so no clock of the runner's enters the
  comparison.

Queue wait bound: 5 seconds.

Why 5 seconds. A worker still reading the cancelled document would hold the next one for every page still unread.
The run of 2026-09-25 cancelled with 7 of 25 pages done, which left 18 pages unread, and at the measured 7 seconds a
page (spec 13, image `7605748a6afa`) that is about 2 minutes of waiting. Even one unread page, about 7 seconds, is
above the bound. A replaced worker takes the next document at once: the same run measured a queue wait of 0.0057
seconds. The next document is submitted only after `/ready` reads `ready`, so the time the new worker takes to come
up is not part of the wait, and neither is the runner's own pace. The earlier bound measured from the cancelled
record's `finished_at` to the next document's `started_at`, which put the cancel answer, the fifteen second wait of
step 5, the readiness polling of step 7 and every Bruno start-up inside the gap, and so needed 120 seconds of room.

Step 10:

- HTTP 200, and the Markdown carries one of the canaries `Argent Saga`, `Aenaria` or `Halen Veyr` under `## Page 1`.

Step 11:

- HTTP 204 for each delete, including the cancelled one, which is finished work and so is forgotten rather than
  cancelled a second time. Each identifier then answers 404 `JOB_NOT_FOUND`.

Record: the `pages_done` from step 2, the value from steps 4 and 5, the next document's queue wait, its `started_at`
minus its `submitted_at`, and, for diagnosis only, the seconds from the cancelled record's `finished_at` to the next
document's `started_at`.

## Fixtures

- [`apps/ascend-ocr/e2e/fixtures/halcyon-ledger-25-pages.pdf`](../fixtures/halcyon-ledger-25-pages.pdf), the twenty
  five page document spec 13 reads. It is long enough that the cancel always lands with most of it unread.
- [`apps/ascend-ocr/e2e/fixtures/argent-saga-chronicles-page1.png`](../fixtures/argent-saga-chronicles-page1.png), the
  English canary, as the next document that proves the worker came back.

## Concurrency

Engine-bound, and it replaces the worker. It runs alone: no runner of any suite active while it is in flight, from
this suite or from any other module's sweep, not even a reject-fast spec of this suite. A second runner would slow
the first pages enough to miss the window in step 2, and anything submitted by another runner would sit in the queue
ahead of the next document in step 8 and break the `pages_ahead` 0 assertion.

The cancel restarts the worker, and a fresh worker loads its engine before it reads anything, so this spec also makes
the next engine-bound spec of any suite pay that load. Run it after the shorter engine-bound specs of this suite, not
between them, and before specs 14 and 13, the two long specs that run last.
