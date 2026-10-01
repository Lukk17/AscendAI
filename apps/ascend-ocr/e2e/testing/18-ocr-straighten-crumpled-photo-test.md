# A crumpled page read with straightening: e2e test

## What this verifies

- `POST /v1/ocr/jobs` with `straighten=true` accepts a full resolution phone photo of a crumpled and hand-flattened
  page, 6144 x 8160 pixels and 3.4 MiB (3,524,016 bytes), as one page of work.
- The successful state echoes `straighten` `true`, `quality` `"high"` (the default, since the submission sends none)
  and `language` `"pl"`, so the setting the caller asked for is the setting the page was read with.
- With the page flattened before it is read, the Markdown carries every one of the page's 21 lines, each matched to
  its closest line of output, and at least 15 of the 21 canary phrases word for word. The canaries avoid the three
  characters the engine is known to get wrong on this page: the Spanish inverted exclamation mark is never output,
  and the Polish `ź` and `ż` may swap.
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
ls apps/ascend-ocr/e2e/fixtures/straightening-photo-crumpled-1.jpg apps/ascend-ocr/e2e/fixtures/straightening-test-page.txt
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

Step 1. Submit the photo with `lang=pl`, `straighten=true` and no `quality` part. Read `job_id` from the answer.

```bash
bru run "ocr/testing/ocr-crumpled-straighten.yml" --env ascend-local
```

Step 2. Read the state until it is terminal. Wait `poll_after_seconds` from the previous answer between reads, and
stop as soon as `state` is `succeeded`, `failed` or `cancelled`.

```bash
bru run "ocr/ocr-job-status.yml" --env ascend-local --env-var "ocrJobId=<job_id from step 1>"
```

Step 3. Read the terminal state once more, against the settings the submission asked for.

```bash
bru run "ocr/testing/ocr-crumpled-straighten-status.yml" --env ascend-local --env-var "ocrJobId=<job_id from step 1>"
```

Step 4. Collect the result from the address the successful state carried. Spec 17 uses the same request with its
default of all 21 canaries, so this spec sets its own threshold of 15 on the command line. The request accepts only
15 or 21 and fails on any other value.

```bash
bru run "ocr/testing/ocr-straightening-page-result.yml" --env ascend-local --env-var "ocrResultUrl=<result.url from step 3>" --env-var "straighteningMinCanaries=15"
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
- `result.straighten` equals `true`, `result.quality` equals `"high"` and `result.language` equals `"pl"`.
- `result.page_count` equals 1 and `result.key` equals `<job_id>.md`.

Step 4:

- HTTP 200, the first line is `## Page 1` and it is the only page heading.
- Compared case-insensitively, with every run of whitespace, line breaks included, read as one space, the Markdown
  carries at least 15 of the 21 canaries, one per line of
  [`straightening-test-page.txt`](../fixtures/straightening-test-page.txt), in any order: `Test page for straightening`,
  `Invoice 2026-0917`, `Harbour Lane Bakery`, `HLB-4471`, `rye sourdough loaves`, `poppy seed rolls`,
  `oat and honey biscuits`, `Subtotal 207.00 EUR`, `Total due 254.61 EUR`, `PL61 1090 1014 0000 0712 1981 2874`,
  `quote the order reference`, `gęślą`, `Brzęczyszczykiewicz`, `pingüino Wenceslao`, `señora Muñoz`,
  `quick brown fox jumps over the lazy dog`, `five dozen liquor jugs`, `QX-5083-01`, `orders@harbourlane.example`,
  `keep refrigerated below 6 degrees`, `Marta Kowalczyk`. Record how many were found and which were missing.
- All 21 lines of `straightening-test-page.txt` are present. A line is present when its closest match in the Markdown,
  over every output line and every two neighbouring output lines joined (the engine may split one printed line in
  two), reaches a similarity of at least 0.8, where similarity is one minus the edit distance over the longer
  string's length, both sides lower-cased with whitespace runs read as one space.
- No front matter and no `schema_version`.

Why 15 and not 21. The canaries are exact phrases, and a crumpled page read through the flattening pass loses single
characters at the folds: the run of 2026-09-25 found 17 of 21, missing `HLB-4471` (read `HLB-441`),
`rye sourdough loaves` (read `rye sourdough (oaves`), `quote the order reference` (read `orderreference`) and
`Marta Kowalczyk` (read `Kowalczuk`), while every one of the 21 lines was there, the worst at 0.929 similarity. 15
leaves two phrases of margin below that measurement for fold damage that shifts between readings of the same photo.
It still proves the flattening pass helps: spec 19 read the same photo without straightening on the same day and found
14 of 21, and lost two whole lines (`Order reference HLB-4471 ...` and `Item 1: rye sourdough loaves ...`), which the
line check above refuses. The 0.8 line similarity sits below this spec's measured worst line (0.929) and above the
worst line spec 19 still produced without straightening (`Customer: Harbour Lane Bakery ...` read as
`ustomer Habou Lae er 1 M  ee`, 0.60), so the line check refuses that line as well. The owner accepted the 15 of 21
threshold on 2026-09-25 for now, and improving crumpled-photo accuracy (a stronger recognition model, a better
unwarping model, or image cleanup before recognition) is future work, tracked as task 7.11 in
`openspec/changes/fix-ocr-page-resolution/tasks.md`.

Step 5:

- HTTP 204 with an empty body.

Step 6:

- HTTP 404 with `code` equal to `"JOB_NOT_FOUND"`.

Record the wall time from submission to the terminal state and `result.processing_time_seconds`. Straightening adds
a flattening pass before detection. The first timed reading, on 2026-09-25, took 33.5 seconds of processing and
34.4 seconds from submission to the terminal state.

## Fixtures

- [`apps/ascend-ocr/e2e/fixtures/straightening-photo-crumpled-1.jpg`](../fixtures/straightening-photo-crumpled-1.jpg),
  the owner's printed test page crumpled, flattened by hand and photographed, 6144 x 8160 pixels, with no metadata.
- [`apps/ascend-ocr/e2e/fixtures/straightening-test-page.txt`](../fixtures/straightening-test-page.txt), the page's 21
  expected lines. None of the canaries contains the inverted exclamation mark, `ź` or `ż`, so a known engine
  weakness on those three characters cannot fail the spec and cannot hide a real miss either.

## Concurrency

Engine-bound. This spec runs alone: no runner of any suite active while it is in flight, from this suite or from any
other module's sweep, not even a reject-fast spec of this suite. Start it only when nothing else is running anywhere,
and start nothing else until it has returned.

The one OCR worker reads one document at a time and uses every CPU the container is given. A second engine-bound
spec would wait in the queue behind this one, and any other runner on the host takes CPU away from inference, so the
timings this spec records stop being true. On a loaded host, a page that takes longer than its engine's page allowance (112.95 s on the small pair at the default
`OCR_PAGE_ALLOWANCE_HEADROOM`) stops the document with `OCR_FAILED`. The flattening pass makes this the most
expensive single page in the suite, so it is the spec most exposed to a loaded host. Run it alone.
