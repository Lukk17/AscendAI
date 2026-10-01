# OCR default language through the job surface: e2e test

## What this verifies

- `POST /v1/ocr/jobs` with the `argent-saga-chronicles-page1.png` fixture answers HTTP 202 with a job identifier, a relative `Location`
  header naming the status resource, and no page content at all.
- The submission sends no `lang` part at all, so the record carries the server's `DEFAULT_LANGUAGE`, which is `en` out of the box.
- Reading the state returns exactly one of the five states, carries `poll_after_seconds` while the work is in flight
  and omits it once the work is terminal.
- The work reaches `succeeded`, and the successful state names the bucket, the key and a time-limited URL.
- Fetching that URL returns Markdown whose first line is `## Page 1` and which carries the canary substring
  `Argent Saga`, `Aenaria` or `Halen Veyr`.
- The successful state's `result.language` equals the container's own `DEFAULT_LANGUAGE`, which the runner reads
  with `docker exec ascend-ocr printenv DEFAULT_LANGUAGE` rather than assuming.
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
ls apps/ascend-ocr/e2e/fixtures/argent-saga-chronicles-page1.png
```

Expect the file path printed. If missing, generate it per
[`apps/ascend-ocr/e2e/fixtures/README.md`](../fixtures/README.md).

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

Read the container's default language, which step 2 asserts against.

```bash
docker exec ascend-ocr printenv DEFAULT_LANGUAGE
```

Expect a language code such as `en`. Nothing printed means the variable is unset and the code default `en` applies.
Pass that value as `ocrExpectedLanguage` in step 2.

## Reset state

This suite leaves job records on the container's disk and result objects in the bucket. Both are removed by the
service at the end of their retention window, and a spec that asserts a listing or a count needs them gone first.

Drop every job record the service holds.

```bash
docker exec ascend-ocr sh -c 'rm -f /tmp/ascend-ocr-jobs/*'
```

Expect no output. The records are files named for their own job identifier, so nothing else lives in that directory.

Drop every stored result. The command names the `ocr-results` bucket literally, which belongs to this service alone.
Never issue a command that sweeps buckets instead of naming one, because the same object store also backs other
projects on this machine.

```bash
curl -fsS "http://localhost:9070/ocr-results?list-type=2" | grep -o "<Key>[^<]*</Key>" | sed -e "s/<Key>//" -e "s|</Key>||" | xargs -I {} curl -fsS -X DELETE "http://localhost:9070/ocr-results/{}"
```

Expect no output. Re-running it against an empty bucket is also silent.

Confirm the bucket is empty.

```bash
curl -fsS "http://localhost:9070/ocr-results?list-type=2"
```

Expect a `ListBucketResult` with no `<Key>` elements.

## Run

```bash
cd docs/api/request/AscendAI
```

Step 1. Submit the document. Read `job_id` from the answer.

```bash
bru run "ocr/testing/ocr-default-lang.yml" --env ascend-local
```

Step 2. Read the state right away, as soon as step 1 has answered, without waiting for the hint first. One page
reads in about 15 to 24 seconds, so a first read taken only after the step 1 hint usually finds the work already
finished, and the checks on work in flight never run. Then keep reading the state until it is terminal. Wait
`poll_after_seconds` from the previous answer between reads, and stop as soon as `state` is `succeeded`, `failed` or
`cancelled`. A terminal answer carries no `poll_after_seconds` at all, which is the signal that there is nothing left
to ask. The first read and every later read use the same request.

```bash
bru run "ocr/ocr-job-status.yml" --env ascend-local --env-var "ocrJobId=<job_id from step 1>" --env-var "ocrExpectedLanguage=<DEFAULT_LANGUAGE read in the prerequisites>"
```

Step 3. Collect the result from the address the successful state carried.

```bash
bru run "ocr/ocr-job-result.yml" --env ascend-local --env-var "ocrResultUrl=<result.url from step 2>"
```

Step 4. Delete the job.

```bash
bru run "ocr/ocr-job-delete.yml" --env ascend-local --env-var "ocrJobId=<job_id from step 1>"
```

Step 5. Read the deleted identifier once more.

```bash
bru run "ocr/testing/ocr-job-not-found.yml" --env ascend-local --env-var "ocrJobId=<job_id from step 1>"
```

## Expected

Step 1:

- HTTP 202.
- `job_id` is a 22 character identifier.
- `state` equals `"waiting"`.
- `page_count` equals 1.
- `status_url` and the `Location` header both equal `/v1/ocr/jobs/<job_id>`.
- `poll_after_seconds` is a number greater than zero.
- No `pages` key and no line text anywhere in the body.

Step 2:

- HTTP 200 on every read.
- The first read, taken right away, has `state` `waiting`, `running` or `succeeded`.
- When the first read is `waiting` or `running`, it carries `poll_after_seconds` between 1 and 30, and its
  `pages_done` is not above `page_count`.
- When the first read is already `succeeded`, the checks on work in flight (a status read seen `waiting` or
  `running`, and the hint on a non-terminal status read) are recorded as not observed, not as failed. The checks on
  the terminal read below still apply to it.
- `state` moves through `waiting` or `running` to `succeeded`.
- Every non-terminal read carries `poll_after_seconds` between 1 and 30.
- `pages_done` never exceeds `page_count`.
- The terminal read carries no `poll_after_seconds`.
- The terminal read carries `result.bucket`, `result.key` equal to `<job_id>.md`, `result.url`,
  `result.page_count` equal to `page_count`, and a finite non-negative `result.processing_time_seconds`.
- The terminal read's `result.language` equals the `DEFAULT_LANGUAGE` read in the prerequisites.
- No read at any point carries page text.

Step 3:

- HTTP 200.
- The first line of the body is `## Page 1`.
- The body carries the canary substring `Argent Saga`, `Aenaria` or `Halen Veyr`.
- The body carries no front matter and no `schema_version`.

Step 4:

- HTTP 204 with an empty body.

Step 5:

- HTTP 404 with `code` equal to `"JOB_NOT_FOUND"` and a detail saying the identifier is unknown or expired.

## Fixtures

- [`apps/ascend-ocr/e2e/fixtures/argent-saga-chronicles-page1.png`](../fixtures/argent-saga-chronicles-page1.png),
  the same English canary page spec 2 uses. This spec differs only in sending no `lang` part.

## Concurrency

Engine-bound. This spec runs alone: no runner of any suite active while it is in flight, from this suite or from any
other module's sweep, not even a reject-fast spec of this suite. Start it only when nothing else is running anywhere,
and start nothing else until it has returned.

The reason is the engine, not the fixture. The one OCR worker reads one document at a time and
uses every CPU the container is given, so a second engine-bound spec would wait in the queue behind this one and any
other runner on the host takes CPU away from it, and either way the timings this spec records stop being true. A loaded host does not fail the spec the way it used to, because no
connection is held and nothing times out at the HTTP layer: what it does instead is stretch the polling, and a
document whose pages each take longer than their engine's page allowance (112.95 s on the small pair at the default
`OCR_PAGE_ALLOWANCE_HEADROOM`) is stopped by its own reading budget and
reported as `failed` with `OCR_FAILED`. Run it alone and that does not happen.

See [`apps/ascend-ocr/e2e/README.md`](../README.md) "Parallelism and execution order" and
[`apps/ascend-ocr/e2e/testing/README.md`](README.md) "Execution order".
