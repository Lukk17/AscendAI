# Platform contract: run tasks template

Spec: [../21-platform-contract-test.md](../21-platform-contract-test.md)

Copy this file to `../runs/<UTC-timestamp>_21-platform-contract-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-ocr `/health` returns HTTP 200 with `status` `ok`, `service` `ascend-ocr` and a non-empty `version`
- [ ] Job listing is empty before the run (`GET /v1/ocr/jobs` returns `{"jobs":[]}`)

### Reset state

- [ ] None required

### Run

- [ ] `bru run "ocr/testing/platform-contract" --env ascend-local` from `docs/api/request/AscendAI` returns success

### Expected

- [ ] `health.yml`: HTTP 200, `status` `ok`, `service` `ascend-ocr`, non-empty `version`
- [ ] `ready.yml`: HTTP 200, `status` `ready`, same `service` and `version`, every `checks` entry `ok` or `skipped`
- [ ] `unknown-path.yml`: HTTP 404 problem body, `code` `not_found`, `type` `https://ascend.ai/errors/not-found`, `title` `Not Found`, `instance` `/does-not-exist`, `traceId` 32 lower case hex
- [ ] `errors-counter-after.yml`: the `not_found` `rest` `unmatched` counter grew by exactly one
- [ ] `delete-health.yml`: HTTP 405 problem body, `code` `method_not_allowed`, an `Allow` header
- [ ] `traceparent-refusal.yml`: `traceId` equals `4bf92f3577b34da6a3ce929d0e0e4736`
- [ ] `request-id-echo.yml`: `x-request-id` `e2e-canary-req-0001` echoed
- [ ] `request-id-too-long.yml`: a different id of 1 to 128 characters echoed
- [ ] `validation-error.yml`: HTTP 400, `code` `validation`, `errors` sorted by `field`, no location prefix
- [ ] `security-headers.yml`: every security header present on `GET /health`
- [ ] `mcp-refusal.yml`: error text starts with `JOB_NOT_FOUND: ` (well formed unknown id)
- [ ] `job-not-found.yml`: HTTP 404, `code` `JOB_NOT_FOUND`, `type` `https://ascend.ai/errors/job-not-found`, `instance` equal to the request path
- [ ] `initialize-2025-06-18.yml`: HTTP 200, no `mcp-session-id`, `protocolVersion` `2025-06-18`, `serverInfo.name` `ascend-ocr`, non-empty `serverInfo.version`
- [ ] `initialize-2025-11-25.yml`: HTTP 200, no `mcp-session-id`, `protocolVersion` `2025-11-25`, `serverInfo.name` `ascend-ocr`, non-empty `serverInfo.version`
- [ ] `initialized-notification.yml`: HTTP 200 or 202
- [ ] `tool-call-session.yml`: HTTP 200, no `mcp-session-id`, `ocr_list_jobs` content and structured content `{"jobs": []}`
- [ ] `tool-call-sessionless.yml`: HTTP 200, no `mcp-session-id`, same `ocr_list_jobs` content in the sessionless form
- [ ] `host-not-allowed.yml`: 4xx and no `mcp-session-id`
- [ ] `health-foreign-host.yml`: `GET /health` with a foreign `Host`, HTTP 200
- [ ] `origin-refused.yml`: 4xx and no `mcp-session-id`
- [ ] `oversized-body.yml`: HTTP 413 and no `mcp-session-id`
- [ ] `tools-list-after-oversize.yml`: HTTP 200, lists the four OCR tools
- [ ] `job-status-route-template.yml`: HTTP 404, `code` `JOB_NOT_FOUND`
- [ ] `metrics-route-template.yml`: `http_requests_total` `handler` `/v1/ocr/jobs/{job_id}`, no id in any label
- [ ] Job listing is unchanged after the run (`GET /v1/ocr/jobs` still returns `{"jobs":[]}`)

### Post-run cleanup

- [ ] None required (no job is ever submitted)

### Verdict

- [ ] Verdict: PASS / FAIL (delete the wrong one)

## Result summary



Input tokens: 0

Output tokens: 0

Start (UTC):

End (UTC):

Duration:

---

## Additional tasks I did

<!-- Optional. List anything outside the spec, e.g. diagnostic curls, manual log inspection, retries with different inputs. Leave empty if nothing extra. -->
