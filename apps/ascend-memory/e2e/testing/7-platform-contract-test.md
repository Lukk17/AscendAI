# Platform contract: e2e test

## What this verifies

- The AscendMemory platform contract, the shared library behaviour every Python service serves the same way, holds
  against a live container on port 7020. Every assertion is observable only: HTTP status, headers, problem body
  fields, the MCP tool result and the Prometheus counter `/metrics` serves.
- `/health` answers 200 with `status` `ok`, `service` `ascend-memory` and a non-empty `version`, and `/ready` answers
  200 with `status` `ready`, the same `service` and `version`, and every `checks` entry with `status` `ok` or `skipped`.
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
  no `mcp-session-id` response header, echo the protocol version sent, and report `serverInfo.name` `ascend-memory` and a
  non-empty `serverInfo.version`.
- A `memory_wipe` tool call after the 2025-06-18 handshake, and the same call in the sessionless 2026-07-28 form, each
  answer 200 with no `mcp-session-id` response header and the pinned content and structured content `{"status":
  "success", "message": "All memories wiped for user e2e-platform-contract."}`.
- `initialize` with `Host: attacker.example` answers a 4xx with no session, `initialize` with an `Origin` header answers
  a 4xx with no session, `GET /health` with `Host: attacker.example` still answers 200, a 5 MiB body answers 413 with no
  session, and `tools/list` right after still lists the four memory tools.
- A refused tool call's error text starts with the code.
- No Qdrant write and no user state are touched: every request is refused or reads only, and the `memory_wipe` wipes an
  empty user.

## Prerequisites

Check Bruno CLI is installed.

```bash
bru --version
```

Expect a version string.

Check the AscendMemory server is reachable and ready.

```bash
curl -fsS http://localhost:7020/health
```

Expect HTTP 200 with `status` `ok`, `service` `ascend-memory` and a non-empty `version`.

## Reset state

None. Every request is refused or reads only, so no `user_id` and no memory is written.

## Run

```bash
cd docs/api/request/AscendAI
```

```bash
bru run "memory/testing/platform-contract" --env ascend-local
```

The folder runs its requests in `seq` order: `health`, `ready`, `errors-counter-before`, `unknown-path`,
`errors-counter-after`, `delete-health`, `traceparent-refusal`, `request-id-echo`, `request-id-too-long`,
`validation-error`, `security-headers`, `mcp-refusal`, `initialize-2025-06-18`, `initialize-2025-11-25`,
`initialized-notification`, `tool-call-session`, `tool-call-sessionless`, `host-not-allowed`, `health-foreign-host`,
`origin-refused`, `oversized-body`, `tools-list-after-oversize`. Each request carries its own assertions in its `tests`
script, and the run succeeds only when every one of them passes.

## Post-run cleanup

None. No `user_id` is ever written and nothing is left behind.

## Expected

The `bru run` returns success, which means every assertion inside each request's `tests` script passed. In order:

- `health.yml`: HTTP 200, `status` `ok`, `service` `ascend-memory`, non-empty `version`.
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
- `mcp-refusal.yml`: the `memory_insert` with an empty `text` answers a tool error whose text starts with
  `validation: `.
- `initialize-2025-06-18.yml`: HTTP 200, no `mcp-session-id` response header, `protocolVersion` `2025-06-18`,
  `serverInfo.name` `ascend-memory`, non-empty `serverInfo.version`.
- `initialize-2025-11-25.yml`: HTTP 200, no `mcp-session-id` response header, `protocolVersion` `2025-11-25`,
  `serverInfo.name` `ascend-memory`, non-empty `serverInfo.version`.
- `initialized-notification.yml`: HTTP 200 or 202.
- `tool-call-session.yml`: HTTP 200, no `mcp-session-id` response header, `memory_wipe` content and structured content
  equal `{"status": "success", "message": "All memories wiped for user e2e-platform-contract."}`.
- `tool-call-sessionless.yml`: HTTP 200, no `mcp-session-id` response header, the same `memory_wipe` content and
  structured content in the sessionless 2026-07-28 form.
- `host-not-allowed.yml`: `initialize` with `Host: attacker.example`, a 4xx and no `mcp-session-id` response header.
- `health-foreign-host.yml`: `GET /health` with `Host: attacker.example`, HTTP 200.
- `origin-refused.yml`: `initialize` with `Origin: https://attacker.example`, a 4xx and no `mcp-session-id` response
  header.
- `oversized-body.yml`: a 5 MiB JSON-RPC body, HTTP 413 and no `mcp-session-id` response header.
- `tools-list-after-oversize.yml`: HTTP 200, lists the four memory tools.

## Fixtures

None.
