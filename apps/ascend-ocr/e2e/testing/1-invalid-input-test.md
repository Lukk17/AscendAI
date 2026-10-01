# Invalid input: e2e test

## What this verifies

- `POST /v1/ocr/jobs` without the required `file` multipart part is rejected with HTTP 422 by FastAPI's request
  validation, before any record is written and before anything is queued.
- No job identifier is issued for a refused submission.
- A submission with `lang=korean`, a language the service no longer reads, is refused at the request boundary with
  HTTP 400 and the `UNSUPPORTED_LANGUAGE` code, with no job identifier and no `Location` header.
- Neither refused call leaves work behind: the job listing is empty afterwards.

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

Check nothing is in flight, because step 3 asserts an empty listing.

```bash
curl -fsS http://localhost:7022/ready
```

Expect `"jobs_queued":0` and `"jobs_running":0`. Anything else means an earlier run left work behind: wait for it to
finish or reset per [`../README.md`](../README.md) "Resetting between runs" before starting.

## Reset state

None. No call reaches the queue, the jobs directory or the bucket.

## Run

```bash
cd docs/api/request/AscendAI
```

Step 1. Submit with no file.

```bash
bru run "ocr/testing/ocr-invalid-no-file.yml" --env ascend-local
```

Step 2. Submit the English canary with `lang=korean`.

```bash
bru run "ocr/testing/ocr-unsupported-language.yml" --env ascend-local
```

Step 3. Read the listing.

```bash
bru run "ocr/testing/ocr-jobs-list-empty.yml" --env ascend-local
```

## Expected

Step 1:

- HTTP 422.
- The body carries FastAPI's validation detail, not a job record.
- No `job_id` anywhere in the body.

Step 2:

- HTTP 400.
- `code` equals `"UNSUPPORTED_LANGUAGE"`.
- `detail` contains `Supported languages:` and does not contain `korean`. The full list is not asserted, so adding a
  language later does not break this step.
- No `job_id` and no `state` in the body, and no `Location` header.

Step 3:

- HTTP 200 with `{"jobs": []}`.

## Fixtures

- [`apps/ascend-ocr/e2e/fixtures/argent-saga-chronicles-page1.png`](../fixtures/argent-saga-chronicles-page1.png), sent
  by step 2 and refused before it is read. Step 1 sends only the `lang` part.

## Concurrency

Reject-fast. Every submission is refused at the request boundary before anything is queued, so this spec never
reaches the OCR engine and finishes in well under two seconds. Safe to run in parallel with the other reject-fast
specs, up to the runner's default cap of five concurrent. Never alongside an engine-bound spec (2, 3, 4, 6, 13, 14,
15, 16, 17, 18, 19).
