# Listing the work in flight: e2e test

## What this verifies

- `GET /v1/ocr/jobs` answers with an empty listing on an idle service rather than with an error.
- With more documents submitted than the single worker can serve at once, the listing reports the running document
  first and every waiting document after it, in submission order.
- A waiting document's position is its place in submission order, counting the running document as place zero, and
  matches what the document's own state reports. The running document carries a null `queue_position`.
- The running document is reported with live progress, and a waiting one reports zero pages done.
- Finished work never appears in the listing, even while its record is still retained and still readable by its own
  identifier.
- The listing needs no paging, because it is bounded by the queue's own document bound plus the one running
  document. Three documents cannot reach that bound, so this spec does not assert it: spec 16 fills the queue to its
  bound and asserts the listing holds exactly the running document and the waiting ones, with no further entry after
  the refused submission.
- `ocr_list_jobs` on the MCP surface reports the same entries, in the same order, with the same positions.

## What this hands out, and to whom

This service has no authentication, and the job identifier is the only credential a result has. A listing that
returns identifiers therefore hands the credential for every piece of work in flight to anyone who can reach the
port, who can then wait for those jobs to finish and read their results. That is recorded deliberately rather than
discovered: it is acceptable while the deployment is single user on a private network, and it stops being acceptable
the moment the service has more than one user. See the disclosure section of
[ADR-008](../../docs/architecture/decisions/ADR-008-every-request-is-a-job.md). Whoever runs this spec should know
that its output is a list of credentials.

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
ls apps/ascend-ocr/e2e/fixtures/halcyon-ledger-25-pages.pdf apps/ascend-ocr/e2e/fixtures/argent-saga-chronicles-page1-polish.png apps/ascend-ocr/e2e/fixtures/argent-saga-chronicles-page1.png
```

Expect all three file paths printed. If one is missing, generate it per
[`apps/ascend-ocr/e2e/fixtures/README.md`](../fixtures/README.md).

Check the page ceiling the container is running with, because the first document has twenty five pages.

```bash
docker exec ascend-ocr printenv OCR_JOB_MAX_PAGES
```

Expect nothing printed, which means the code default of 100, or a value of at least 25 if the operator set one.

## Reset state

Drop every job record the service holds, so the listing this spec reads is this spec's own.

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

Expect `"jobs_queued":0` and `"jobs_running":0`.

## Run

```bash
cd docs/api/request/AscendAI
```

Step 1. Read the listing while nothing is in flight.

```bash
bru run "ocr/testing/ocr-jobs-list-empty.yml" --env ascend-local
```

Step 2. Submit three documents in quick succession, without waiting for any of them. Record each `job_id` and the
order you submitted them in. The first is the twenty five page document spec 13 reads, so the single worker stays
busy with it for about three minutes while steps 3 to 6 read the queue behind it. The two after it are one page each.

```bash
bru run "ocr/testing/ocr-long-document.yml" --env ascend-local
```

```bash
bru run "ocr/testing/ocr-polish.yml" --env ascend-local
```

```bash
bru run "ocr/testing/ocr-default-lang.yml" --env ascend-local
```

Step 3. Read the listing right away, while the first document is being read.

```bash
bru run "ocr/ocr-jobs-list.yml" --env ascend-local
```

Step 4. Read the readiness surface while the same work is in flight.

```bash
curl -fsS http://localhost:7022/ready
```

Step 5. Read the state of the second document by its own identifier, and compare its `queue_position` with the
position the listing gave it.

```bash
bru run "ocr/ocr-job-status.yml" --env ascend-local --env-var "ocrJobId=<second job_id>"
```

Step 6. Read the listing on the MCP surface. Open a session first and keep the session id, because the listing has
to land inside the same window as steps 3 to 5. Opening it before step 2 is fine.

```bash
curl -isS -X POST http://localhost:7022/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d "{\"jsonrpc\":\"2.0\",\"id\":0,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2025-06-18\",\"capabilities\":{},\"clientInfo\":{\"name\":\"e2e\",\"version\":\"1\"}}}"
```

Expect HTTP 200 and an `mcp-session-id` response header. Complete the handshake: the MCP protocol requires the
`notifications/initialized` notification after `initialize` and before any other request on the session.

```bash
bru run "ocr/testing/mcp-initialized.yml" --env ascend-local --env-var "mcp_session_id=<paste session id>"
```

Expect HTTP 202 with an empty body. Then read the listing.

```bash
bru run "ocr/testing/mcp-list-jobs.yml" --env ascend-local --env-var "mcp_session_id=<paste session id>"
```

Step 7. Wait for all three to finish, polling each one's state and waiting `poll_after_seconds` between reads, then
read the listing again. The twenty five page document takes about three minutes, and the two single pages after it
about 15 to 24 seconds each.

```bash
bru run "ocr/testing/ocr-jobs-list-empty.yml" --env ascend-local
```

Step 8. Read one of the finished identifiers directly.

```bash
bru run "ocr/ocr-job-status.yml" --env ascend-local --env-var "ocrJobId=<first job_id>"
```

Step 9. Delete all three jobs.

```bash
bru run "ocr/ocr-job-delete.yml" --env ascend-local --env-var "ocrJobId=<each job_id in turn>"
```

Step 10. Read each deleted identifier once more.

```bash
bru run "ocr/testing/ocr-job-not-found.yml" --env ascend-local --env-var "ocrJobId=<each job_id in turn>"
```

## Expected

Step 1:

- HTTP 200 with `{"jobs": []}`. An idle service answers with an empty listing, not with an error.

Step 2:

- Each submission answers 202. The first reports `queue_position` 0, and each later one reports a position one
  higher than the last.
- The first answer carries `page_count` 25, and the two later ones carry `page_count` 1.

Step 3:

- HTTP 200 with three entries.
- The entries are in submission order. A `running` first entry has a null `queue_position` and the two waiting
  entries have 1 and 2. If the runner has not picked the first one up yet, all three are `waiting` with 0, 1 and 2.
- The first entry's `state` is `running`, or `waiting` if the runner has not picked it up yet.
- Every later entry's `state` is `waiting` and its `pages_done` is 0.
- The running entry's `pages_done` is between 0 and its own `page_count`, which is 25.
- Every entry carries a non-negative `elapsed_seconds`.

Step 4:

- `jobs_running` is 1 and `jobs_queued` is 2.
- `status` is still `ready`. A queue with work in it is busy, and busy stays ready.

Step 5:

- The `queue_position` the document reports for itself equals the one the listing reported for it.

Step 6:

- The MCP listing carries the same entries, in the same order, with the same positions.

Step 7:

- HTTP 200 with `{"jobs": []}`. Finished work is not listed.

Step 8:

- HTTP 200 with `state` `succeeded`, proving the record is still retained and still readable even though the listing
  no longer mentions it.

Step 9:

- HTTP 204 for each.

Step 10:

- HTTP 404 with `code` equal to `"JOB_NOT_FOUND"` for each.

## Fixtures

- [`apps/ascend-ocr/e2e/fixtures/halcyon-ledger-25-pages.pdf`](../fixtures/halcyon-ledger-25-pages.pdf), the twenty
  five page document spec 13 reads, submitted first to hold the worker while the queue behind it is read.
- [`apps/ascend-ocr/e2e/fixtures/argent-saga-chronicles-page1-polish.png`](../fixtures/argent-saga-chronicles-page1-polish.png)
  (submitted through `ocr/testing/ocr-polish.yml`) and
  [`apps/ascend-ocr/e2e/fixtures/argent-saga-chronicles-page1.png`](../fixtures/argent-saga-chronicles-page1.png)
  (submitted through `ocr/testing/ocr-default-lang.yml`), the two single page documents that wait behind it.
  The listing assertions do not depend on the text, only on the queue, so any accepted document would do.

## Concurrency

Engine-bound, because three documents are read end to end. This spec runs alone: no runner of any suite active while
it is in flight, from this suite or from any other module's sweep.

The timing window in steps 3 to 6 is the one thing to be careful about. All of those reads have to happen while the
first document is still being read. The first document is the twenty five page one for exactly that reason: the run
of 2026-09-25 on image `7605748a6afa` with a 4 GiB memory limit read it in 172.1 seconds (spec 13), about 7 seconds a
page, so steps 3 to 6 have about three minutes, not the 15 to 24 seconds one page gives. The first attempt of that
run submitted a single page first and missed the window. The three documents together take about three and a half
minutes of reading. The service's own limit on the first document is its reading budget, 25 pages times the page
allowance of 112.95 seconds, which is 2823.75 seconds. If the listing in step 3 is already empty, the documents
finished before the read landed: reset and run the steps again rather than recording a failure, because an empty
listing after the work finished is correct behaviour, not a defect.
