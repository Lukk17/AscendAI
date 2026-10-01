# A document longer than a single request could ever have carried: e2e test

## What this verifies

- A twenty five page document is accepted, which the service refused outright before the job surface existed: the
  page ceiling was the derived `floor(OCR_REQUEST_TIMEOUT / OCR_PAGE_TIMEOUT_SECONDS)`, and at the deployed 300 s and
  150 s that was two.
- The submission is answered in the time an ordinary request takes, with `page_count` 25 and no page content.
- Progress advances while the document is read: a later status read reports at least as many completed pages as an
  earlier one, and never more than 25.
- The work reaches `succeeded` and the result is one Markdown object carrying all twenty five page headings.
- The canary string sits on page 24, so finding it proves the whole document was read rather than the first page or
  two.

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

Check the fixture exists.

```bash
ls apps/ascend-ocr/e2e/fixtures/halcyon-ledger-25-pages.pdf
```

Expect the file path printed. If missing, regenerate it per
[`apps/ascend-ocr/e2e/fixtures/README.md`](../fixtures/README.md).

Check the page ceiling the container is running with, because this spec only means anything above two.

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

## Run

```bash
cd docs/api/request/AscendAI
```

Step 1. Submit the twenty five page document with `lang=en` and no `quality` part, which is what the request sends.
Note the wall time of this call and read `job_id` from the answer.

```bash
bru run "ocr/testing/ocr-long-document.yml" --env ascend-local
```

Step 2. Read the state once, immediately, while the reading is under way.

```bash
bru run "ocr/ocr-job-status.yml" --env ascend-local --env-var "ocrJobId=<job_id from step 1>"
```

Step 3. Keep reading the state, waiting `poll_after_seconds` between reads, until it is terminal. Record
`pages_done` on each read: it must never go backwards and never exceed 25.

```bash
bru run "ocr/ocr-job-status.yml" --env ascend-local --env-var "ocrJobId=<job_id from step 1>"
```

Step 4. Collect the result.

```bash
bru run "ocr/testing/ocr-long-document-result.yml" --env ascend-local --env-var "ocrResultUrl=<result.url from step 3>"
```

Step 5. Delete the job.

```bash
bru run "ocr/ocr-job-delete.yml" --env ascend-local --env-var "ocrJobId=<job_id from step 1>"
```

Step 6. Read the deleted identifier once more.

```bash
bru run "ocr/testing/ocr-job-not-found.yml" --env ascend-local --env-var "ocrJobId=<job_id from step 1>"
```

## Expected

Step 1:

- HTTP 202, answered in roughly the time an upload takes rather than in the time a reading takes.
- `page_count` equals 25.
- `state` equals `"waiting"`, with a `job_id` and a `Location` header.
- No page content anywhere in the answer.

Steps 2 and 3:

- Every read is HTTP 200.
- `pages_done` on the later read is greater than or equal to `pages_done` on the earlier one.
- `pages_done` never exceeds 25.
- Non-terminal reads carry `poll_after_seconds` between 1 and 30, and the hint on a later read is no longer than the
  hint on an earlier one.
- The terminal state is `succeeded` and carries no hint.
- The successful state's `result.page_count` equals 25.

Step 4:

- HTTP 200.
- The Markdown carries `## Page 1` as its first line and `## Page 25` somewhere later.
- The Markdown carries the canary `Halcyon Ledger Canary`, which the fixture places on page 24.
- The Markdown carries twenty five page headings in ascending order.

Step 5:

- HTTP 204.

Step 6:

- HTTP 404 with `code` equal to `"JOB_NOT_FOUND"`.

Record, for the number table this change is waiting on: the wall time from submission to the terminal state, and the
`result.processing_time_seconds` the service reports for itself. This spec submits without `quality`, so it reads in
`high` mode, the default. The run of 2026-09-25 on image `7605748a6afa`, with a 4 GiB container memory limit,
measured a `result.processing_time_seconds` of 172.1 seconds, and 177.2 seconds from submission to the terminal
state, about 7 seconds a page. That is a measurement of this fixture, not a bound, and no step of this spec asserts it. The
only time limit the service itself applies is the reading budget, 25 pages times the page allowance of 112.95 seconds,
which is 2823.75 seconds. A page slower than its allowance fails the document with `OCR_FAILED` (see Concurrency).

## Fixtures

- [`apps/ascend-ocr/e2e/fixtures/halcyon-ledger-25-pages.pdf`](../fixtures/halcyon-ledger-25-pages.pdf), twenty five
  A4-in-points pages of clean rendered text, 193 KB. Every page carries its own number in the heading, and page 24
  carries the canary `Halcyon Ledger Canary` and nothing else does. The service renders each page itself, and in the
  default `high` mode each page reaches inference at 2,480 x 3,509 pixels (1,240 x 1,755 in `normal`). No page is
  refused for its pixel count.

## Concurrency

Engine-bound, and one of the two heaviest specs in this suite, with spec 14. It runs alone: no runner of any suite active while it is in
flight, from this suite or from any other module's sweep, not even a reject-fast spec of this suite. Start it only
when nothing else is running anywhere, and start nothing else until it has returned.

Twenty five pages is twenty five inferences on the single worker, one after another. On a loaded host each page
takes longer, and a page that takes longer than its engine's page allowance (112.95 s on the small pair at the
default `OCR_PAGE_ALLOWANCE_HEADROOM`) stops the whole document with
`OCR_FAILED`, which is a real failure of this spec and not a flake to retry: it means the allowance is wrong for the
host, and the fix is the allowance or the host, never a retry.
