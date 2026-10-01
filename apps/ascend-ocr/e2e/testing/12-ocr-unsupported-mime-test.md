# Unsupported MIME rejection: e2e test

## What this verifies

- `POST /v1/ocr/jobs` refuses a payload whose magic bytes do not match an allowed image or PDF signature, even when
  the declared `Content-Type` says otherwise.
- The refusal is HTTP 400 with the `UNSUPPORTED_FILE_TYPE` code.
- No identifier is issued, so nothing reaches the queue, the jobs directory or the bucket.

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

Check the decoy fixture exists.

```bash
ls apps/ascend-ocr/e2e/fixtures/not-an-image.txt
```

Expect the file path printed.

Check nothing is in flight, because the last assertion is an empty listing.

```bash
curl -fsS http://localhost:7022/ready
```

Expect `"jobs_queued":0` and `"jobs_running":0`. Anything else means an earlier run left work behind: wait for it to
finish or reset per [`../README.md`](../README.md) "Resetting between runs" before starting.

## Reset state

None. The type check refuses the submission before a record is written.

## Run

```bash
cd docs/api/request/AscendAI
```

```bash
bru run "ocr/testing/ocr-unsupported-mime.yml" --env ascend-local
```

Confirm nothing was queued.

```bash
bru run "ocr/testing/ocr-jobs-list-empty.yml" --env ascend-local
```

## Expected

- HTTP 400.
- `code` equals `"UNSUPPORTED_FILE_TYPE"`.
- No `job_id` in the body.
- The listing answers HTTP 200 with `{"jobs": []}`, so the refused submission was not queued.

## Fixtures

- [`apps/ascend-ocr/e2e/fixtures/not-an-image.txt`](../fixtures/not-an-image.txt), plain text sent with a lying
  `image/png` content type.

## Concurrency

Reject-fast. The submission is refused at the request boundary before anything is queued, so this spec never reaches
the OCR engine and finishes in well under two seconds. Safe to run in parallel with the other reject-fast specs, up
to the runner's default cap of five concurrent. Never alongside an engine-bound spec
(2, 3, 4, 6, 13, 14, 15, 16, 17, 18, 19).
