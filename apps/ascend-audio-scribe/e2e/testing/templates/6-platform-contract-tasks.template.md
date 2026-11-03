# Platform contract: run tasks template

Spec: [../6-platform-contract-test.md](../6-platform-contract-test.md)

Copy this file to `../runs/<UTC-timestamp>_6-platform-contract-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-audio-scribe `/health` returns HTTP 200 with `status` `ok`, `service` `ascend-audio-scribe` and a non-empty `version`
- [ ] The redirect helper answers `302 http://10.0.0.5/a.mp3` (curl of the exact redirect URL)

### Reset state

- [ ] None required

### Run

- [ ] `bru run "transcribe/testing/platform-contract" --env ascend-local` from `docs/api/request/AscendAI` returns success

### Expected

- [ ] `health.yml`: HTTP 200, `status` `ok`, `service` `ascend-audio-scribe`, non-empty `version`
- [ ] `ready.yml`: HTTP 200, `status` `ready`, same `service` and `version`, every `checks` entry `ok` or `skipped`
- [ ] `unknown-path.yml`: HTTP 404 problem body, `code` `not_found`, `type` `https://ascend.ai/errors/not-found`, `title` `Not Found`, `instance` `/does-not-exist`, `traceId` 32 lower case hex
- [ ] `errors-counter-after.yml`: the `not_found` `rest` `unmatched` counter grew by exactly one
- [ ] `delete-health.yml`: HTTP 405 problem body, `code` `method_not_allowed`, an `Allow` header
- [ ] `traceparent-refusal.yml`: `traceId` equals `4bf92f3577b34da6a3ce929d0e0e4736`
- [ ] `request-id-echo.yml`: `x-request-id` `e2e-canary-req-0001` echoed
- [ ] `request-id-too-long.yml`: a different id of 1 to 128 characters echoed
- [ ] `validation-error.yml`: HTTP 400, `code` `validation`, `errors` sorted by `field`, no location prefix
- [ ] `security-headers.yml`: every security header present on `GET /health`
- [ ] `mcp-refusal.yml`: error text starts with `validation: ` (`ftp://` URI)
- [ ] `mcp-userinfo-uri.yml`: error text starts with `validation: `, no response text holds `secret`
- [ ] `mcp-redirect-to-private.yml`: error text starts with `validation: ` (redirect to a private address)
- [ ] `initialize-2025-06-18.yml`: HTTP 200, no `mcp-session-id`, `protocolVersion` `2025-06-18`, `serverInfo.name` `ascend-audio-scribe`, non-empty `serverInfo.version`
- [ ] `initialize-2025-11-25.yml`: HTTP 200, no `mcp-session-id`, `protocolVersion` `2025-11-25`, `serverInfo.name` `ascend-audio-scribe`, non-empty `serverInfo.version`
- [ ] `initialized-notification.yml`: HTTP 200 or 202
- [ ] `tool-call-session.yml`: HTTP 200, no `mcp-session-id`, `health` content and structured content `{"status": "ok"}`
- [ ] `tool-call-sessionless.yml`: HTTP 200, no `mcp-session-id`, same `health` content in the sessionless form
- [ ] `host-not-allowed.yml`: 4xx and no `mcp-session-id`
- [ ] `health-foreign-host.yml`: `GET /health` with a foreign `Host`, HTTP 200
- [ ] `origin-refused.yml`: 4xx and no `mcp-session-id`
- [ ] `oversized-body.yml`: HTTP 413 and no `mcp-session-id`
- [ ] `tools-list-after-oversize.yml`: HTTP 200, lists the transcription tools and `health`

### Post-run cleanup

- [ ] None required (no transcript is ever written)

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
