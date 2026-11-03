# Platform contract: e2e test

## What this verifies

- The ascend-ocr platform contract, the shared library behaviour every Python service serves the same way, holds
  against a live container on port 7022. Every assertion is observable only: HTTP status, headers, problem body fields,
  the MCP tool result, the job listing and the Prometheus counter `/metrics` serves.
- `/health` answers 200 with `status` `ok`, `service` `ascend-ocr` and a non-empty `version`, and `/ready` answers 200
  with `status` `ready`, the same `service` and `version`, and every `checks` entry with `status` `ok` or `skipped`.
- An unknown path answers a 404 problem body with `Content-Type: application/problem+json`, `code` `not_found`, `type`
  `https://ascend.ai/errors/not-found`, `title` `Not Found`, `instance` `/does-not-exist` and a `traceId` of 32 lower
  case hex characters.
- `DELETE /health` answers a 405 problem body with `code` `method_not_allowed` and an `Allow` header.
- A request that carries a `traceparent` header answers with a `traceId` equal to the header's trace id, a request's
  `x-request-id` is echoed back in the response header, and an over-long `x-request-id` is replaced by a fresh id of 1
  to 128 characters.
- A request that misses a required field answers 400 `validation` with an `errors` array sorted by `field`, each entry
  carrying `field` and `message` and no location prefix.
- Every security response header the library sets is present on `GET /health`.
- The `ascend_service_errors_total{code="not_found",surface="rest",operation="unmatched"}` counter grows by exactly one
  across the unknown-path request.
- The MCP endpoint runs in stateless HTTP mode: `initialize` with protocol 2025-06-18 and 2025-11-25 each answer 200 with
  no `mcp-session-id` response header, echo the protocol version sent, and report `serverInfo.name` `ascend-ocr` and a
  non-empty `serverInfo.version`.
- An `ocr_list_jobs` tool call after the 2025-06-18 handshake, and the same call in the sessionless 2026-07-28 form, each
  answer 200 with no `mcp-session-id` response header and the pinned content and structured content `{"jobs": []}`.
- `initialize` with `Host: attacker.example` answers a 4xx with no session, `initialize` with an `Origin` header answers
  a 4xx with no session, `GET /health` with `Host: attacker.example` still answers 200, a 5 MiB body answers 413 with no
  session, and `tools/list` right after still lists the four OCR tools.
- A refused tool call's error text starts with the code.
- A `GET /v1/ocr/jobs/<well formed unknown id>` answers a 404 problem body with `code` `JOB_NOT_FOUND`, `type`
  `https://ascend.ai/errors/job-not-found` and `instance` equal to the request path.
- The `http_requests_total` series the run produces carries the `handler` label `/v1/ocr/jobs/{job_id}`, the route
  template with the parameter name, and no series label holds the id that was sent.
- No job is submitted and nothing is queued: every request is refused or reads only, so the job listing is unchanged by
  the run.

## Prerequisites

Check Bruno CLI is installed.

```bash
bru --version
```

Expect a version string.

Check the ascend-ocr server is reachable and ready.

```bash
curl -fsS http://localhost:7022/health
```

Expect HTTP 200 with `status` `ok`, `service` `ascend-ocr` and a non-empty `version`.

Check the job listing is empty before the run, so the "unchanged" assertion has a baseline.

```bash
curl -fsS http://localhost:7022/v1/ocr/jobs
```

Expect HTTP 200 with `{"jobs":[]}`.

## Reset state

None. Every request is refused or reads only, so no job record and no result object is written.

## Run

```bash
cd docs/api/request/AscendAI
```

```bash
bru run "ocr/testing/platform-contract" --env ascend-local
```

The folder runs its requests in `seq` order: `health`, `ready`, `errors-counter-before`, `unknown-path`,
`errors-counter-after`, `delete-health`, `traceparent-refusal`, `request-id-echo`, `request-id-too-long`,
`validation-error`, `security-headers`, `mcp-refusal`, `job-not-found`, `initialize-2025-06-18`,
`initialize-2025-11-25`, `initialized-notification`, `tool-call-session`, `tool-call-sessionless`, `host-not-allowed`,
`health-foreign-host`, `origin-refused`, `oversized-body`, `tools-list-after-oversize`, `job-status-route-template`,
`metrics-route-template`. Each request carries its own assertions in its `tests` script, and the run succeeds only when
every one of them passes.

## Post-run cleanup

None. No job is ever submitted and nothing is left behind.

## Expected

The `bru run` returns success, which means every assertion inside each request's `tests` script passed. In order:

- `health.yml`: HTTP 200, `status` `ok`, `service` `ascend-ocr`, non-empty `version`.
- `ready.yml`: HTTP 200, `status` `ready`, same `service` and `version`, every `checks` entry `ok` or `skipped`.
- `errors-counter-before.yml`: HTTP 200, stores the `not_found` `rest` `unmatched` counter value.
- `unknown-path.yml`: HTTP 404 problem body, `Content-Type` `application/problem+json`, `code` `not_found`, `type`
  `https://ascend.ai/errors/not-found`, `title` `Not Found`, `instance` `/does-not-exist`, `traceId` 32 lower case hex
  characters.
- `errors-counter-after.yml`: HTTP 200, the counter read before grew by exactly one.
- `delete-health.yml`: HTTP 405 problem body, `code` `method_not_allowed`, an `Allow` header.
- `traceparent-refusal.yml`: `traceId` equals `4bf92f3577b34da6a3ce929d0e0e4736`.
- `request-id-echo.yml`: `x-request-id` `e2e-canary-req-0001` echoed in the response header.
- `request-id-too-long.yml`: a different id of 1 to 128 characters echoed.
- `validation-error.yml`: HTTP 400, `code` `validation`, `errors` sorted by `field`, each entry `field` and `message`
  and no location prefix.
- `security-headers.yml`: every security header the library sets is present on `GET /health`.
- `mcp-refusal.yml`: the `ocr_job_status` with a well formed unknown id answers a tool error whose text starts with
  `JOB_NOT_FOUND: `.
- `job-not-found.yml`: HTTP 404 problem body, `code` `JOB_NOT_FOUND`, `type` `https://ascend.ai/errors/job-not-found`,
  `instance` equal to the request path.
- `initialize-2025-06-18.yml`: HTTP 200, no `mcp-session-id` response header, `protocolVersion` `2025-06-18`,
  `serverInfo.name` `ascend-ocr`, non-empty `serverInfo.version`.
- `initialize-2025-11-25.yml`: HTTP 200, no `mcp-session-id` response header, `protocolVersion` `2025-11-25`,
  `serverInfo.name` `ascend-ocr`, non-empty `serverInfo.version`.
- `initialized-notification.yml`: HTTP 200 or 202.
- `tool-call-session.yml`: HTTP 200, no `mcp-session-id` response header, `ocr_list_jobs` content and structured content
  equal `{"jobs": []}`.
- `tool-call-sessionless.yml`: HTTP 200, no `mcp-session-id` response header, the same `ocr_list_jobs` content and
  structured content in the sessionless 2026-07-28 form.
- `host-not-allowed.yml`: `initialize` with `Host: attacker.example`, a 4xx and no `mcp-session-id` response header.
- `health-foreign-host.yml`: `GET /health` with `Host: attacker.example`, HTTP 200.
- `origin-refused.yml`: `initialize` with `Origin: https://attacker.example`, a 4xx and no `mcp-session-id` response
  header.
- `oversized-body.yml`: a 5 MiB JSON-RPC body, HTTP 413 and no `mcp-session-id` response header.
- `tools-list-after-oversize.yml`: HTTP 200, lists the four OCR tools.
- `job-status-route-template.yml`: `GET /v1/ocr/jobs/BBBBBBBBBBBBBBBBBBBBBB` answers 404 `JOB_NOT_FOUND`.
- `metrics-route-template.yml`: the `http_requests_total` series carries `handler` `/v1/ocr/jobs/{job_id}`, not the id
  that was sent.

After the run, the job listing is unchanged:

```bash
curl -fsS http://localhost:7022/v1/ocr/jobs
```

Expect HTTP 200 with `{"jobs":[]}`. No request in the run submits a job, so the listing the Prerequisites read is the
listing the run leaves.

## Fixtures

None.
