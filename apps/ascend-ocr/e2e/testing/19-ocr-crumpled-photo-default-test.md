# A crumpled page read in normal mode, not straightened by default: e2e test

## What this verifies

- `POST /v1/ocr/jobs` with `quality=normal` and no `straighten` part accepts the same crumpled page photo spec 18
  reads, as one page of work.
- The page is not straightened unless the caller asks: the successful state echoes `straighten` `false` even though
  the submission sent no `straighten` part at all, so `false` is the service's own default and not an echo of the
  caller.
- The successful state echoes `quality` `"normal"`, so the mode the caller picked is the mode the page was read in.
- The reading still succeeds and stores one page of Markdown with text under its heading. Which lines survive the
  creases unflattened is not asserted: that is what spec 18 measures with straightening on.
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

Check the fixture exists.

```bash
ls apps/ascend-ocr/e2e/fixtures/straightening-photo-crumpled-1.jpg
```

Expect the file path printed. The photos cannot be regenerated, see
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

Step 1. Submit the photo with `lang=pl`, `quality=normal` and no `straighten` part. Read `job_id` from the answer.

```bash
bru run "ocr/testing/ocr-crumpled-normal.yml" --env ascend-local
```

Step 2. Read the state until it is terminal. Wait `poll_after_seconds` from the previous answer between reads, and
stop as soon as `state` is `succeeded`, `failed` or `cancelled`.

```bash
bru run "ocr/ocr-job-status.yml" --env ascend-local --env-var "ocrJobId=<job_id from step 1>"
```

Step 3. Read the terminal state once more, against the settings the submission implied.

```bash
bru run "ocr/testing/ocr-crumpled-normal-status.yml" --env ascend-local --env-var "ocrJobId=<job_id from step 1>"
```

Step 4. Collect the result from the address the successful state carried.

```bash
bru run "ocr/testing/ocr-crumpled-normal-result.yml" --env ascend-local --env-var "ocrResultUrl=<result.url from step 3>"
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
- `result.straighten` equals `false`, `result.quality` equals `"normal"` and `result.language` equals `"pl"`.
- `result.page_count` equals 1 and `result.key` equals `<job_id>.md`.

Step 4:

- HTTP 200, the first line is `## Page 1` and it is the only page heading.
- At least one non-empty line of text under the heading.
- No front matter and no `schema_version`.

Step 5:

- HTTP 204 with an empty body.

Step 6:

- HTTP 404 with `code` equal to `"JOB_NOT_FOUND"`.

Record the wall time from submission to the terminal state and `result.processing_time_seconds`, and, for
comparison with spec 18, how many of the 21 canaries that spec lists the Markdown carries. The count is recorded,
not asserted. `normal` mode shrinks the photo to a long side of 2100 pixels, and the dense English A4 page measured with
the engine's threads capped to the container's CPUs took 22.7 seconds in `normal` mode.

## Fixtures

- [`apps/ascend-ocr/e2e/fixtures/straightening-photo-crumpled-1.jpg`](../fixtures/straightening-photo-crumpled-1.jpg),
  the same crumpled page photo spec 18 reads with straightening on.

## Concurrency

Engine-bound. This spec runs alone: no runner of any suite active while it is in flight, from this suite or from any
other module's sweep, not even a reject-fast spec of this suite. Start it only when nothing else is running anywhere,
and start nothing else until it has returned.

The one OCR worker reads one document at a time and uses every CPU the container is given. A second engine-bound
spec would wait in the queue behind this one, and any other runner on the host takes CPU away from inference, so the
timings this spec records stop being true. On a loaded host, a page that takes longer than its engine's page allowance (112.95 s on the small pair at the default
`OCR_PAGE_ALLOWANCE_HEADROOM`) stops the document with `OCR_FAILED`. Run it alone and that does not happen.
