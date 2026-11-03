# Session import: e2e test

## What this verifies

`POST /api/v2/web/session/import` stores a Playwright `storage_state` captured outside the service, so an
operator can seed an auth session without a login flow, a browser tier, or a human. Three behaviours are gated,
all asserted on HTTP status, response body, or a Redis key, never on log output:

- **Import keeps only the domain's cookies.** The mixed fixture holds two `example.net` cookies with canary
  values and one `example.org` cookie. The call answers HTTP 200 with `status` equal to `"imported"`, `domain`
  equal to `"example.net"`, `profile` equal to `"e2e-import"`, `auth_cookies` equal to `2`, `waf_cookies` equal
  to `0`, and `dropped_cookies` equal to `1`. The Redis record holds both canary cookies, no `example.org`
  cookie, and provenance `import`.
- **The imported session reads back as active.** `POST /api/v2/web/session/status` for the same URL and
  profile answers HTTP 200 with `status` equal to `"active"`.
- **The imported session clears like any other.** `POST /api/v2/web/session/clear` for the same profile
  answers HTTP 200 with `status` equal to `"cleared"` and `existed` equal to `true`, and the key is gone.

The refusal steps and the 1000-cookie step are not repeated here: the unit tests of
`tests/api/rest/test_session_import.py` (task 2.1, owner decision 91.3 of 2026-10-08) prove them.

This spec makes no egress call. The import validates the URL host with no address lookup (a registrable-domain
check only), and all three calls touch Redis alone: no search, no read, no browser tier, no priced provider.

## Concurrency

Do not run this test in parallel with test 7
([7-authenticated-realworld-scraping-test.md](7-authenticated-realworld-scraping-test.md)), test 8
([8-session-clear-test.md](8-session-clear-test.md)), or test 10
([10-session-establish-test.md](10-session-establish-test.md)). This test writes
`session:example.net:e2e-import`: test 7's reset flushes every `session:*` key, and tests 8 and 10 scan or
write `example.net` session keys. Safe to run in parallel with everything else in the suite.

## Prerequisites

Check Bruno CLI is installed.

```bash
bru --version
```

Expect a version string.

Check the ascend-web-hunter server is reachable.

```bash
curl -fsS http://localhost:7021/health
```

Expect HTTP 200 with `status` `ok`, `service` `ascend-web-hunter` and a non-empty `version`.

Check Redis is reachable from the host's Docker context (this test reads a key directly).

```bash
docker exec redis redis-cli PING
```

Expect `PONG`.

## Reset state

Confirm `example.net` currently carries no session under the `e2e-import` profile this spec uses (no other
spec touches that key).

```bash
docker exec redis redis-cli EXISTS "session:example.net:e2e-import"
```

Expect `0`. If it returns `1`, a previous run of this spec did not clean up - delete it before continuing.

```bash
docker exec redis redis-cli DEL "session:example.net:e2e-import"
```

## Run

Move into the Bruno collection root first.

```bash
cd docs/api/request/AscendAI
```

Call 1 - import the mixed fixture for `https://www.example.net/` with profile `e2e-import`. The request body
is the committed fixture
[fixtures/session-import-mixed.json](../fixtures/session-import-mixed.json): two `example.net` cookies with
canary values and one `example.org` cookie.

```bash
bru run "web-hunter/testing/session-import/import-mixed.yml" --env ascend-local
```

Call 2 - read back the imported session's lifecycle state.

```bash
bru run "web-hunter/testing/session-import/import-status-active.yml" --env ascend-local
```

Call 3 - clear the imported session.

```bash
bru run "web-hunter/testing/session-import/import-clear.yml" --env ascend-local
```

## Expected

- **Call 1 (import):** HTTP 200. Body `status` equals `"imported"`, `domain` equals `"example.net"`,
  `profile` equals `"e2e-import"`, `auth_cookies` equals `2`, `waf_cookies` equals `0`, `dropped_cookies`
  equals `1`. The Redis record holds both canary cookies, no `example.org` cookie, and provenance `import`:

  ```bash
  docker exec redis redis-cli GET "session:example.net:e2e-import"
  ```

  Expect the output to contain `CANARY-ALPHA-7741`, `CANARY-BETA-8823`, and `"produced_by":"import"`, and to
  contain no `example.org`.

- **Call 2 (status):** HTTP 200. Body `status` equals `"active"`, `profile` equals `"e2e-import"`.

- **Call 3 (clear):** HTTP 200. Body `status` equals `"cleared"`, `existed` equals `true`. The key is gone:

  ```bash
  docker exec redis redis-cli EXISTS "session:example.net:e2e-import"
  ```

  Expect `0`.

- **No collateral damage:** every session key that existed before this test started is still present and
  unchanged afterward, and the `e2e-import` key - created only by this test - is removed by call 3:

  ```bash
  docker exec redis redis-cli --scan --pattern "session:*"
  ```

  Compare the key list against the one recorded before Reset state ran; it must be identical.

## Fixtures

[fixtures/session-import-mixed.json](../fixtures/session-import-mixed.json) - the full import request body: a
Playwright `storage_state` with two `example.net` cookies carrying canary values (`CANARY-ALPHA-7741`,
`CANARY-BETA-8823`) and one `example.org` cookie (`CANARY-FOREIGN-1199`), plus a fixed `user_agent` so the
run is deterministic. Neither cookie name is a WAF-clearance name, so both `example.net` cookies land in the
auth sub-record and the expected split is `auth_cookies` 2, `waf_cookies` 0, `dropped_cookies` 1.
