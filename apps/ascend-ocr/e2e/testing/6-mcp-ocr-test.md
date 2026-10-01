# MCP reading through the job surface: e2e test

## What this verifies

- `tools/call` for `ocr_submit` with a `file_uri` pointing at the object store answers with a job record, not with
  the document's text.
- The record carries a 22 character `job_id`, `state` `"waiting"`, and where the state can be read.
- `ocr_job_status` on the same identifier reports the same states the REST surface reports, and once the work has
  succeeded it names the bucket, the key and a time-limited URL.
- Fetching that URL returns the same Markdown a REST caller would get, carrying the canary substring.
- The fixture is fetched by the service over HTTP from the object store, with no container mount involved.

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

Check the object store is reachable on the host. It serves the S3 API on port 9070 without authentication, so this
spec needs no client, no credentials, and no container name.

```bash
curl -fsS http://localhost:9070/_floci/health
```

Expect HTTP 200 with `"s3":"running"` in the JSON body.

Check the ascend-ocr container has `MCP_ALLOWED_HOSTS` including `host.docker.internal`. The MCP tool's SSRF guard
blocks RFC1918 destinations by default, and the docker-internal `host.docker.internal` host-gateway resolves to a
private address. See [ADR-001](../../docs/architecture/decisions/ADR-001-mcp-file-transport-uri-only.md).

```bash
docker exec ascend-ocr printenv MCP_ALLOWED_HOSTS
```

Expect `host.docker.internal,localhost,127.0.0.1`, or any superset containing `host.docker.internal`.

## Reset state

Every command below names a bucket literally. Those buckets belong to this repository. Never issue a command that
sweeps buckets instead of naming one, because the same object store also backs other projects on this machine.

Create the dedicated `e2e-fixtures` bucket. The call is idempotent.

```bash
curl -sS -o /dev/null -w "%{http_code}\n" -X PUT "http://localhost:9070/e2e-fixtures"
```

Expect `200`.

Drop only this test's fixture so the re-upload is clean.

```bash
curl -fsS -X DELETE "http://localhost:9070/e2e-fixtures/argent-saga-chronicles-page1.png"
```

Upload the fixture straight from the host.

```bash
curl -sS -o /dev/null -w "%{http_code}\n" -X PUT -H "Content-Type: image/png" --data-binary "@apps/ascend-ocr/e2e/fixtures/argent-saga-chronicles-page1.png" "http://localhost:9070/e2e-fixtures/argent-saga-chronicles-page1.png"
```

Expect `200`.

Drop every job record the service holds, so the listing this run leaves behind is this run's own.

```bash
docker exec ascend-ocr sh -c 'rm -f /tmp/ascend-ocr-jobs/*'
```

Drop every stored result from the service's own bucket.

```bash
curl -fsS "http://localhost:9070/ocr-results?list-type=2" | grep -o "<Key>[^<]*</Key>" | sed -e "s/<Key>//" -e "s|</Key>||" | xargs -I {} curl -fsS -X DELETE "http://localhost:9070/ocr-results/{}"
```

## Run

Open an MCP session and keep the session id. FastMCP answers the `initialize` call with an
`Mcp-Session-Id` response header, and every `tools/call` in this spec carries it back.

```bash
curl -isS -X POST http://localhost:7022/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d "{\"jsonrpc\":\"2.0\",\"id\":0,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2025-06-18\",\"capabilities\":{},\"clientInfo\":{\"name\":\"e2e\",\"version\":\"1\"}}}"
```

Expect HTTP 200 and an `mcp-session-id` response header. Use that value as the `mcp_session_id` env-var below.

```bash
cd docs/api/request/AscendAI
```

Complete the handshake. The MCP protocol requires the client to send the `notifications/initialized` notification
after `initialize` and before any other request on the session.

```bash
bru run "ocr/testing/mcp-initialized.yml" --env ascend-local --env-var "mcp_session_id=<paste session id>"
```

Expect HTTP 202 with an empty body.

Step 1. Submit through the tool. Read `job_id` from the answer.

```bash
bru run "ocr/testing/mcp-ocr.yml" --env ascend-local --env-var "mcp_session_id=<paste session id>"
```

Step 2. Read the state through the tool right away, as soon as step 1 has answered, without waiting for a hint
first. One page reads in about 15 to 24 seconds, so a first read taken later usually finds the work already finished,
and the checks on work in flight never run. Then keep reading the state through the tool until it is terminal,
waiting `poll_after_seconds` between reads. The first read and every later read use the same request.

```bash
bru run "ocr/testing/mcp-job-status.yml" --env ascend-local --env-var "mcp_session_id=<paste session id>" --env-var "ocrJobId=<job_id from step 1>"
```

Step 3. Collect the result from the address the successful state carried.

```bash
bru run "ocr/ocr-job-result.yml" --env ascend-local --env-var "ocrResultUrl=<result.url from step 2>"
```

Step 4. Cancel the job through the tool, which forgets a finished one along with its stored result.

```bash
bru run "ocr/testing/mcp-cancel-job.yml" --env ascend-local --env-var "mcp_session_id=<paste session id>" --env-var "ocrJobId=<job_id from step 1>"
```

Step 5. Read the forgotten identifier through the tool once more.

```bash
bru run "ocr/testing/mcp-job-not-found.yml" --env ascend-local --env-var "mcp_session_id=<paste session id>" --env-var "ocrJobId=<job_id from step 1>"
```

## Expected

Step 1:

- HTTP 200 and a JSON-RPC result that is not an error frame.
- The tool payload carries a 22 character `job_id`, `state` `"waiting"`, `page_count` 1 and
  `status_url` equal to `/v1/ocr/jobs/<job_id>`.
- The payload carries no `pages` key and no line text.

Step 2:

- Every read returns one of the five states.
- The first read, taken right away, has `state` `waiting`, `running` or `succeeded`.
- When the first read is `waiting` or `running`, it carries `poll_after_seconds` between 1 and 30.
- When the first read is already `succeeded`, the check on work in flight (the hint on a non-terminal read) is
  recorded as not observed, not as failed. The checks on the terminal read below still apply to it.
- Non-terminal reads carry `poll_after_seconds`. The terminal read does not.
- The terminal state is `succeeded`, with `result.key` equal to `<job_id>.md` and a bucket and URL beside it.

Step 3:

- HTTP 200, first line `## Page 1`, and the canary substring `Argent Saga`, `Aenaria` or `Halen Veyr`.

Step 4:

- The tool answers with the same `job_id` and `cancelled: true`.

Step 5:

- HTTP 200 at the transport, with a JSON-RPC error frame or an `isError` result carrying `JOB_NOT_FOUND`.
- No record in the answer: no `poll_after_seconds` and no `succeeded` state.

## Fixtures

- [`apps/ascend-ocr/e2e/fixtures/argent-saga-chronicles-page1.png`](../fixtures/argent-saga-chronicles-page1.png),
  uploaded to the object store's `e2e-fixtures` bucket during Reset state. ascend-ocr fetches it over HTTP.

## Concurrency

Engine-bound. This spec runs alone, exactly as specs 2, 3, 4 and 13 do: no runner of any suite active while it is in
flight. The submission itself is fast, because it only fetches the bytes and queues the work, but the reading behind
it is a full inference on the single worker.
