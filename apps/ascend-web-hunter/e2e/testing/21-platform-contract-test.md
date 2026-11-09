# Platform contract: e2e test

## What this verifies

- The ascend-web-hunter platform contract, the shared library behaviour every Python service serves the same way, holds
  against a live container on port 7021. Every assertion is observable only: HTTP status, headers, problem body fields,
  the MCP tool result and the Prometheus counter `/metrics` serves.
- `/health` answers 200 with `status` `ok`, `service` `ascend-web-hunter` and a non-empty `version`, and `/ready`
  answers 200 with `status` `ready`, the same `service`, a `version` equal to the one `/health` answered (`0.0.15`,
  the `version` in `pyproject.toml`, at the time of writing), and every `checks` entry with `status` `ok` or
  `skipped`.
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
  no `mcp-session-id` response header, echo the protocol version sent, and report `serverInfo.name` `ascend-web-hunter`
  and a non-empty `serverInfo.version`.
- A `session_interventions` tool call after the 2025-06-18 handshake, and the same call in the sessionless 2026-07-28
  form, each answer 200 with no `mcp-session-id` response header and the pinned content and structured content with
  `active_flows` `0` and an empty `flows` array.
- `initialize` with `Host: attacker.example` answers a 4xx with no session, `initialize` with an `Origin` header answers
  a 4xx with no session, `GET /health` with `Host: attacker.example` still answers 200, a 5 MiB body answers 413 with no
  session, and `tools/list` right after still lists exactly the eleven tools `src/api/mcp/mcp_server.py` registers,
  no more and no fewer.
- A refused tool call's error text starts with the code.
- The REST read of `http://169.254.169.254/latest/meta-data`, of `https://user:secret@example.com/` and of the name in
  `fake_site_blocked_url` each answer a 400 problem body with `code` `unsafe_uri`, and no header or body text holds
  `secret`. The MCP `web_read` of the same metadata address answers a tool error whose text starts with `unsafe_uri: `.
- No Redis `session:*` key is written: every request is refused or reads only.

## Prerequisites

Check Bruno CLI is installed.

```bash
bru --version
```

Expect a version string.

Check the ascend-web-hunter server is reachable and ready.

```bash
curl -fsS http://127.0.0.1:7021/health
```

Expect HTTP 200 with `status` `ok`, `service` `ascend-web-hunter` and a non-empty `version`.

## Reset state

None. Every request is refused or reads only, so no Redis key is written.

## Run

```bash
cd docs/api/request/AscendAI
```

```bash
bru run "web-hunter/testing/platform-contract" --env ascend-local
```

The folder runs its requests in `seq` order: `health`, `ready`, `errors-counter-before`, `unknown-path`,
`errors-counter-after`, `delete-health`, `traceparent-refusal`, `request-id-echo`, `request-id-too-long`,
`validation-error`, `security-headers`, `mcp-refusal`, `read-metadata-address`, `read-userinfo-url`,
`initialize-2025-06-18`, `initialize-2025-11-25`, `initialized-notification`, `tool-call-session`,
`tool-call-sessionless`, `host-not-allowed`, `health-foreign-host`, `origin-refused`, `oversized-body`,
`tools-list-after-oversize`, `read-blocked-name`. `read-blocked-name` runs last because its `seq` is 113. Each request carries its own assertions in its `tests` script, and the run succeeds only
when every one of them passes.

## Expected

The `bru run` returns success, which means every assertion inside each request's `tests` script passed. In order:

- `health.yml`: HTTP 200, `status` `ok`, `service` `ascend-web-hunter`, non-empty `version`.
- `ready.yml`: HTTP 200, `status` `ready`, same `service`, a `version` equal to the one `health.yml` stored, every
  `checks` entry `ok` or `skipped`.
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
- `mcp-refusal.yml`: the `web_read` of the metadata address answers a tool error whose text starts with `unsafe_uri: `.
- `read-metadata-address.yml`: HTTP 400 problem body, `code` `unsafe_uri`.
- `read-userinfo-url.yml`: HTTP 400 problem body, `code` `unsafe_uri`, and no header or body text holds `secret`.
- `initialize-2025-06-18.yml`: HTTP 200, no `mcp-session-id` response header, `protocolVersion` `2025-06-18`,
  `serverInfo.name` `ascend-web-hunter`, non-empty `serverInfo.version`.
- `initialize-2025-11-25.yml`: HTTP 200, no `mcp-session-id` response header, `protocolVersion` `2025-11-25`,
  `serverInfo.name` `ascend-web-hunter`, non-empty `serverInfo.version`.
- `initialized-notification.yml`: HTTP 200 or 202.
- `tool-call-session.yml`: HTTP 200, no `mcp-session-id` response header, `session_interventions` content and
  structured content with `active_flows` `0` and an empty `flows` array.
- `tool-call-sessionless.yml`: HTTP 200, no `mcp-session-id` response header, the same `session_interventions` content
  and structured content in the sessionless 2026-07-28 form.
- `host-not-allowed.yml`: `initialize` with `Host: attacker.example`, a 4xx and no `mcp-session-id` response header.
- `health-foreign-host.yml`: `GET /health` with `Host: attacker.example`, HTTP 200.
- `origin-refused.yml`: `initialize` with `Origin: https://attacker.example`, a 4xx and no `mcp-session-id` response
  header.
- `oversized-body.yml`: a 5 MiB JSON-RPC body, HTTP 413 and no `mcp-session-id` response header.
- `tools-list-after-oversize.yml`: HTTP 200, `result.tools` holds exactly 11 entries, named `web_search`, `web_read`,
  `session_establish`, `session_interventions`, `session_cancel_intervention`, `session_status`, `session_clear`,
  `crawl_submit`, `crawl_job_status`, `crawl_list_jobs` and `crawl_cancel_job`, the tools `src/api/mcp/mcp_server.py`
  registers.
- `read-blocked-name.yml`: a read of `fake_site_blocked_url`, HTTP 400 with the full problem body of design D23:
  `Content-Type` `application/problem+json`, `code` `unsafe_uri`, `type` `https://ascend.ai/errors/unsafe-uri`, `status`
  400, an `instance`, and a `traceId` of 32 lower case hex characters.

## Post-run cleanup

None. No Redis `session:*` key is ever written and nothing is left behind.

## Fixtures

None.

## Concurrency

Reads `/health`, `/ready` and `/metrics` and answers problem bodies and refusals only. It writes no `session:*` key
and no crawl, recipe or tier-memory key. Its errors-counter assertion depends on no other spec answering an unknown
path while it runs, which none of the others do, and its `session_interventions` calls expect `active_flows` `0`, so
not beside a spec that holds a NoVNC window open (6, 7, 10, 11, 12, 19, 20 and 22).

- Serial: false
