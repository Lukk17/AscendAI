# A phone photo turned 90 degrees, read without straightening: e2e test

## What this verifies

- `POST /v1/ocr/jobs` accepts a full resolution phone photo, 8160 x 6144 pixels and 6.6 MiB (6,955,324 bytes), as
  one page of work, without refusing it for its pixel count and without the caller shrinking it first.
- The photo is stored landscape with no orientation tag, so the page's pixels themselves are turned 90 degrees. The
  submission does not ask for straightening, and the service's page orientation step alone turns the page upright:
  the Markdown carries every one of the page's 21 lines.
- The successful state echoes `language` `"pl"`, `quality` `"high"` (the default, since the submission sends none)
  and `straighten` `false` (the default, since the submission sends none).
- Deleting the job answers HTTP 204, after which reading the identifier answers HTTP 404 `JOB_NOT_FOUND`.

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

Check the fixture and the page's expected text exist.

```bash
ls apps/ascend-ocr/e2e/fixtures/straightening-photo-rotated-90.jpg apps/ascend-ocr/e2e/fixtures/straightening-test-page.txt
```

Expect both file paths printed. The photos cannot be regenerated, see
[`apps/ascend-ocr/e2e/fixtures/README.md`](../fixtures/README.md) "Straightening photo set".

Check the object store is reachable on the host, because every successful reading writes its result there.

```bash
curl -fsS http://localhost:9070/_floci/health
```

Expect HTTP 200 with `"s3":"running"` in the JSON body.

Check the service resolved a result store at boot rather than warning about one it could not reach.

```bash
docker logs ascend-ocr 2>&1 | grep "Result store"
```

Expect a line naming the endpoint with `[answered]`. A `[did NOT answer]` line means every job in this run will
finish with `RESULT_STORE_UNAVAILABLE`, so fix the store before running the spec.

## Reset state

Drop every job record the service holds.

```bash
docker exec ascend-ocr sh -c 'rm -f /tmp/ascend-ocr-jobs/*'
```

Expect no output.

Drop every stored result. The command names the `ocr-results` bucket literally, which belongs to this service alone.
Never issue a command that sweeps buckets instead of naming one, because the same object store also backs other
projects on this machine.

```bash
curl -fsS "http://localhost:9070/ocr-results?list-type=2" | grep -o "<Key>[^<]*</Key>" | sed -e "s/<Key>//" -e "s|</Key>||" | xargs -I {} curl -fsS -X DELETE "http://localhost:9070/ocr-results/{}"
```

Expect no output.

Confirm the service is idle and the bucket is empty.

```bash
curl -fsS http://localhost:7022/ready
```

Expect `"jobs_queued":0` and `"jobs_running":0`.

```bash
curl -fsS "http://localhost:9070/ocr-results?list-type=2"
```

Expect a `ListBucketResult` with no `<Key>` elements.

## Run

```bash
cd docs/api/request/AscendAI
```

Step 1. Submit the photo with `lang=pl` and no `quality` or `straighten` part. Read `job_id` from the answer.

```bash
bru run "ocr/testing/ocr-rotated-photo.yml" --env ascend-local
```

Step 2. Read the state until it is terminal. Wait `poll_after_seconds` from the previous answer between reads, and
stop as soon as `state` is `succeeded`, `failed` or `cancelled`.

```bash
bru run "ocr/ocr-job-status.yml" --env ascend-local --env-var "ocrJobId=<job_id from step 1>"
```

Step 3. Read the terminal state once more, against the settings the submission implied.

```bash
bru run "ocr/testing/ocr-rotated-photo-status.yml" --env ascend-local --env-var "ocrJobId=<job_id from step 1>"
```

Step 4. Collect the result from the address the successful state carried. The request's default threshold is all 21
canaries, which is this spec's. Spec 18 shares the request and sets its own lower threshold on the command line, so
pass no `straighteningMinCanaries` here.

```bash
bru run "ocr/testing/ocr-straightening-page-result.yml" --env ascend-local --env-var "ocrResultUrl=<result.url from step 3>"
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

- HTTP 202.
- `job_id` is a 22 character identifier, `state` equals `"waiting"` and `page_count` equals 1.
- `status_url` and the `Location` header both equal `/v1/ocr/jobs/<job_id>`.
- No `pages` key anywhere in the body.

Step 2:

- HTTP 200 on every read.
- `state` moves through `waiting` or `running` to `succeeded`.
- Every non-terminal read carries `poll_after_seconds` between 1 and 30, and the terminal read carries none.

Step 3:

- HTTP 200 with `state` `succeeded`.
- `result.language` equals `"pl"`, `result.quality` equals `"high"` and `result.straighten` equals `false`.
- `result.page_count` equals 1 and `result.key` equals `<job_id>.md`.

Step 4:

- HTTP 200, the first line is `## Page 1` and it is the only page heading.
- Compared case-insensitively, with every run of whitespace, line breaks included, read as one space, the Markdown
  carries one canary from each of the 21 lines of
  [`straightening-test-page.txt`](../fixtures/straightening-test-page.txt), in any order: `Test page for straightening`,
  `Invoice 2026-0917`, `Harbour Lane Bakery`, `HLB-4471`, `rye sourdough loaves`, `poppy seed rolls`,
  `oat and honey biscuits`, `Subtotal 207.00 EUR`, `Total due 254.61 EUR`, `PL61 1090 1014 0000 0712 1981 2874`,
  `quote the order reference`, `gęślą`, `Brzęczyszczykiewicz`, `pingüino Wenceslao`, `señora Muñoz`,
  `quick brown fox jumps over the lazy dog`, `five dozen liquor jugs`, `QX-5083-01`, `orders@harbourlane.example`,
  `keep refrigerated below 6 degrees`, `Marta Kowalczyk`. All 21 must be found. The run of 2026-09-25 found all 21:
  only two lines differed from the page, the `ź` and `ż` swap and the dropped inverted exclamation mark, and no canary
  covers either.
- All 21 lines of `straightening-test-page.txt` are present. A line is present when its closest match in the Markdown,
  over every output line and every two neighbouring output lines joined, reaches a similarity of at least 0.8, where
  similarity is one minus the edit distance over the longer string's length, both sides lower-cased with whitespace
  runs read as one space. Spec 18 explains the 0.8.
- No front matter and no `schema_version`.

Step 5:

- HTTP 204 with an empty body.

Step 6:

- HTTP 404 with `code` equal to `"JOB_NOT_FOUND"`.

Record the wall time from submission to the terminal state and `result.processing_time_seconds`. The photo is shrunk
to a long side of 4200 pixels in `high` mode and detection is bounded to 1536 either way. The first timed reading, on
2026-09-25, took 44.1 seconds of processing, and the full sweep of 2026-09-25 on image `7605748a6afa` took 14.9
seconds. A dense A4 page of English prose costs 22.1 seconds in `high` mode with the engine's threads capped to the
container's CPUs.

## Fixtures

- [`apps/ascend-ocr/e2e/fixtures/straightening-photo-rotated-90.jpg`](../fixtures/straightening-photo-rotated-90.jpg),
  the owner's printed test page photographed flat and turned 90 degrees, 8160 x 6144 pixels, with no orientation tag
  and no other metadata.
- [`apps/ascend-ocr/e2e/fixtures/straightening-test-page.txt`](../fixtures/straightening-test-page.txt), the page's 21
  expected lines. The canaries are chosen from it to avoid the three characters the engine is known to get wrong on
  this page: it never outputs the Spanish inverted exclamation mark, and it may swap the Polish `ź` and `ż`. None of
  the canaries contains any of the three.

## Concurrency

Engine-bound. This spec runs alone: no runner of any suite active while it is in flight, from this suite or from any
other module's sweep, not even a reject-fast spec of this suite. Start it only when nothing else is running anywhere,
and start nothing else until it has returned.

The one OCR worker reads one document at a time and uses every CPU the container is given. A second engine-bound
spec would wait in the queue behind this one, and any other runner on the host takes CPU away from inference, so the
timings this spec records stop being true. On a loaded host, a page that takes longer than its engine's page allowance (112.95 s on the small pair at the default
`OCR_PAGE_ALLOWANCE_HEADROOM`) stops the document with `OCR_FAILED`. Run it alone and that does not happen.
