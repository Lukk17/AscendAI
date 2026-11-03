# Platform contract: run tasks template

Spec: [../21-platform-contract-test.md](../21-platform-contract-test.md)

Copy this file to `../runs/<UTC-timestamp>_21-platform-contract-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-web-hunter `/health` returns HTTP 200 with `status` `ok`, `service` `ascend-web-hunter` and a non-empty `version`

### Reset state

- [ ] None required

### Run

- [ ] `bru run "web-hunter/testing/platform-contract" --env ascend-local` from `docs/api/request/AscendAI` returns success

### Expected

- [ ] `health.yml`: HTTP 200, `status` `ok`, `service` `ascend-web-hunter`, non-empty `version`
- [ ] `ready.yml`: HTTP 200, `status` `ready`, same `service` and `version`, every `checks` entry `ok` or `skipped`
- [ ] `unknown-path.yml`: HTTP 404 problem body, `code` `not_found`, `type` `https://ascend.ai/errors/not-found`, `title` `Not Found`, `instance` `/does-not-exist`, `traceId` 32 lower case hex
- [ ] `errors-counter-after.yml`: the `not_found` `rest` `unmatched` counter grew by exactly one
- [ ] `delete-health.yml`: HTTP 405 problem body, `code` `method_not_allowed`, an `Allow` header
- [ ] `traceparent-refusal.yml`: `traceId` equals `4bf92f3577b34da6a3ce929d0e0e4736`
- [ ] `request-id-echo.yml`: `x-request-id` `e2e-canary-req-0001` echoed
- [ ] `request-id-too-long.yml`: a different id of 1 to 128 characters echoed
- [ ] `validation-error.yml`: HTTP 400, `code` `validation`, `errors` sorted by `field`, no location prefix
- [ ] `security-headers.yml`: every security header present on `GET /health`
- [ ] `mcp-refusal.yml`: error text starts with `unsafe_uri: ` (metadata address)
- [ ] `read-metadata-address.yml`: HTTP 400, `code` `unsafe_uri`
- [ ] `read-userinfo-url.yml`: HTTP 400, `code` `unsafe_uri`, no header or body text holds `secret`
- [ ] `read-blocked-name.yml`: a read of `fake_site_blocked_url`, HTTP 400 with the full problem body of design D23 (`Content-Type` `application/problem+json`, `code` `unsafe_uri`, `type` `https://ascend.ai/errors/unsafe-uri`, `status` 400, an `instance`, a 32 hex `traceId`)
- [ ] `initialize-2025-06-18.yml`: HTTP 200, no `mcp-session-id`, `protocolVersion` `2025-06-18`, `serverInfo.name` `ascend-web-hunter`, non-empty `serverInfo.version`
- [ ] `initialize-2025-11-25.yml`: HTTP 200, no `mcp-session-id`, `protocolVersion` `2025-11-25`, `serverInfo.name` `ascend-web-hunter`, non-empty `serverInfo.version`
- [ ] `initialized-notification.yml`: HTTP 200 or 202
- [ ] `tool-call-session.yml`: HTTP 200, no `mcp-session-id`, `session_interventions` `active_flows` `0` and empty `flows`
- [ ] `tool-call-sessionless.yml`: HTTP 200, no `mcp-session-id`, same `session_interventions` content in the sessionless form
- [ ] `host-not-allowed.yml`: 4xx and no `mcp-session-id`
- [ ] `health-foreign-host.yml`: `GET /health` with a foreign `Host`, HTTP 200
- [ ] `origin-refused.yml`: 4xx and no `mcp-session-id`
- [ ] `oversized-body.yml`: HTTP 413 and no `mcp-session-id`
- [ ] `tools-list-after-oversize.yml`: HTTP 200, lists the ten web-hunter tools

### Post-run cleanup

- [ ] None required (no Redis `session:*` key is ever written)

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
