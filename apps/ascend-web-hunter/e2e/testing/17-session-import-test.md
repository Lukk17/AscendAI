# Session import: e2e test

## What this verifies

`POST /api/v2/web/session/import` stores a Playwright `storage_state` captured outside the service, so an
operator can seed an auth session without a login flow, a browser tier, or a human. Five behaviours are gated,
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
- A saved login counts when it holds cookies or localStorage entries of the site's own origin. A state with no
  cookie and one localStorage entry on `https://www.example.net` is accepted: HTTP 200, `status` `"imported"`,
  `auth_cookies` `0`, `waf_cookies` `0`, `dropped_cookies` `0`, the Redis record holds the localStorage canary,
  and `session/status` reads it back as `"active"`. Some sites keep their login in browser storage and set no
  cookie, so such a state is a real login.
- A state with neither is still refused. A state whose only cookie belongs to `example.org`, whose only
  `example.net` localStorage entry is the analytics key `_ga`, and whose other localStorage entry sits on the
  `example.org` origin answers HTTP 400 with the problem body check and `code` `no_cookies_for_domain`, and
  writes no record.

The other refusal steps and the 1000-cookie step are not repeated here: the unit tests of
`tests/api/rest/test_session_import.py` (task 2.1, owner decision 91.3 of 2026-10-08) prove them. The
neither-state refusal is checked here beside the localStorage row because the two rows together show where the
new rule draws its line.

This spec makes no egress call. The import validates the URL host with no address lookup (a registrable-domain
check only), and all seven calls touch Redis alone: no search, no read, no browser tier, no priced provider.

## Prerequisites

Check Bruno CLI is installed.

```bash
bru --version
```

Expect a version string.

Check the ascend-web-hunter server is reachable.

```bash
curl -fsS http://127.0.0.1:7021/health
```

Expect HTTP 200 with `status` `ok`, `service` `ascend-web-hunter` and a non-empty `version`.

Check Redis is reachable from the host's Docker context (this test reads a key directly).

```bash
docker exec redis redis-cli PING
```

Expect `PONG`.

## Reset state

Record the session key list first, so the "No collateral damage" check under Expected has a baseline to compare
against. Copy the output into the run record. `--scan` only reads, it changes nothing.

```bash
docker exec redis redis-cli --scan --pattern "session:*"
```

Confirm `example.net` currently carries no session under the `e2e-import` profile this spec uses (no other
spec touches that key).

```bash
docker exec redis redis-cli EXISTS "session:example.net:e2e-import"
```

Expect `0`. If it returns `1`, a previous run of this spec did not clean up - delete it before continuing, and
leave it out of the baseline above.

```bash
docker exec redis redis-cli DEL "session:example.net:e2e-import"
```

## Run

Move into the Bruno collection root first, from the repository root.

```bash
cd docs/api/request/AscendAI
```

Call 1 - import the mixed fixture for `https://www.example.net/` with profile `e2e-import`. The request file
sends the same body as the committed fixture
[fixtures/session-import-mixed.json](../fixtures/session-import-mixed.json), written inline in the request
file: two `example.net` cookies with canary values and one `example.org` cookie.

```bash
bru run "web-hunter/testing/session-import/import-mixed.yml" --env ascend-local
```

Call 2 - read back the imported session's lifecycle state.

```bash
bru run "web-hunter/testing/session-import/import-status-active.yml" --env ascend-local
```

Call 3 - clear the mixed-fixture session that Call 1 imported.

```bash
bru run "web-hunter/testing/session-import/import-clear.yml" --env ascend-local
```

Call 4 - import a localStorage-only state for the same URL and profile: no cookie, and one entry with a canary
value that the `https://www.example.net` origin holds.

PowerShell:

```powershell
curl.exe -sS -i -X POST http://127.0.0.1:7021/api/v2/web/session/import -H "Content-Type: application/json" -d '{"url":"https://www.example.net/","profile":"e2e-import","user_agent":"e2e-session-import-test/1.0","storage_state":{"cookies":[],"origins":[{"origin":"https://www.example.net","localStorage":[{"name":"e2e-canary-token","value":"CANARY-GAMMA-5517"}]}]}}'
```

Unix:

```bash
curl -sS -i -X POST http://127.0.0.1:7021/api/v2/web/session/import -H "Content-Type: application/json" -d '{"url":"https://www.example.net/","profile":"e2e-import","user_agent":"e2e-session-import-test/1.0","storage_state":{"cookies":[],"origins":[{"origin":"https://www.example.net","localStorage":[{"name":"e2e-canary-token","value":"CANARY-GAMMA-5517"}]}]}}'
```

Call 5 - read back the localStorage-only session's lifecycle state.

PowerShell:

```powershell
curl.exe -sS -i -X POST http://127.0.0.1:7021/api/v2/web/session/status -H "Content-Type: application/json" -d '{"url":"https://www.example.net/","profile":"e2e-import"}'
```

Unix:

```bash
curl -sS -i -X POST http://127.0.0.1:7021/api/v2/web/session/status -H "Content-Type: application/json" -d '{"url":"https://www.example.net/","profile":"e2e-import"}'
```

Call 6 - clear the localStorage-only session that Call 4 imported.

PowerShell:

```powershell
curl.exe -sS -i -X POST http://127.0.0.1:7021/api/v2/web/session/clear -H "Content-Type: application/json" -d '{"url":"https://www.example.net/","profile":"e2e-import"}'
```

Unix:

```bash
curl -sS -i -X POST http://127.0.0.1:7021/api/v2/web/session/clear -H "Content-Type: application/json" -d '{"url":"https://www.example.net/","profile":"e2e-import"}'
```

Call 7 - import a state with neither: the only cookie belongs to `example.org`, the only `example.net` entry is the
analytics key `_ga`, and the other entry sits on the `example.org` origin.

PowerShell:

```powershell
curl.exe -sS -i -X POST http://127.0.0.1:7021/api/v2/web/session/import -H "Content-Type: application/json" -d '{"url":"https://www.example.net/","profile":"e2e-import","user_agent":"e2e-session-import-test/1.0","storage_state":{"cookies":[{"domain":".example.org","expires":-1,"httpOnly":false,"name":"e2e-canary-foreign","path":"/","sameSite":"Lax","secure":true,"value":"CANARY-FOREIGN-1199"}],"origins":[{"origin":"https://www.example.net","localStorage":[{"name":"_ga","value":"GA1.1.e2e"}]},{"origin":"https://www.example.org","localStorage":[{"name":"e2e-canary-foreign-token","value":"CANARY-FOREIGN-3361"}]}]}}'
```

Unix:

```bash
curl -sS -i -X POST http://127.0.0.1:7021/api/v2/web/session/import -H "Content-Type: application/json" -d '{"url":"https://www.example.net/","profile":"e2e-import","user_agent":"e2e-session-import-test/1.0","storage_state":{"cookies":[{"domain":".example.org","expires":-1,"httpOnly":false,"name":"e2e-canary-foreign","path":"/","sameSite":"Lax","secure":true,"value":"CANARY-FOREIGN-1199"}],"origins":[{"origin":"https://www.example.net","localStorage":[{"name":"_ga","value":"GA1.1.e2e"}]},{"origin":"https://www.example.org","localStorage":[{"name":"e2e-canary-foreign-token","value":"CANARY-FOREIGN-3361"}]}]}}'
```

## Expected

- **Call 1 (import):** HTTP 200. Body `status` equals `"imported"`, `domain` equals `"example.net"`,
  `profile` equals `"e2e-import"`, `auth_cookies` equals `2`, `waf_cookies` equals `0`, `dropped_cookies`
  equals `1`. The Redis record holds both canary cookies, no `example.org` cookie, and provenance `import`:

  ```bash
  docker exec redis redis-cli GET "session:example.net:e2e-import"
  ```

  Expect the output to contain `CANARY-ALPHA-7741` and `CANARY-BETA-8823`, and to contain no `example.org`.

  Check the provenance by parsing the record rather than by matching text, because Redis stores the JSON with a
  space after each colon and a text match depends on that spacing:

  ```bash
  docker exec redis redis-cli GET "session:example.net:e2e-import" | python3 -c "import json,sys; print(json.load(sys.stdin)['auth']['produced_by'] == 'import')"
  ```

  Expect `True`.

- **Call 2 (status):** HTTP 200. Body `status` equals `"active"`, `profile` equals `"e2e-import"`.

- **Call 3 (clear of the Call 1 import):** HTTP 200. Body `status` equals `"cleared"`, `existed` equals `true`. The key is gone:

  ```bash
  docker exec redis redis-cli EXISTS "session:example.net:e2e-import"
  ```

  Expect `0`.

- **Call 4 (localStorage-only import):** HTTP 200. Body `status` equals `"imported"`, `domain` equals
  `"example.net"`, `profile` equals `"e2e-import"`, `auth_cookies` equals `0`, `waf_cookies` equals `0`,
  `dropped_cookies` equals `0`. The Redis record holds the localStorage canary and provenance `import`:

  ```bash
  docker exec redis redis-cli GET "session:example.net:e2e-import" | python3 -c "import json,sys; a=json.load(sys.stdin)['auth']; print(a['produced_by'] == 'import', a['storage_state']['cookies'] == [], 'CANARY-GAMMA-5517' in json.dumps(a['storage_state']['origins']))"
  ```

  Expect `True True True`.

- **Call 5 (status):** HTTP 200. Body `status` equals `"active"`, `profile` equals `"e2e-import"`.

- **Call 6 (clear of the Call 4 import):** HTTP 200. Body `status` equals `"cleared"`, `existed` equals `true`. The key is gone:

  ```bash
  docker exec redis redis-cli EXISTS "session:example.net:e2e-import"
  ```

  Expect `0`.

- **Call 7 (neither):** HTTP 400. The problem body check holds: `Content-Type` starts with
  `application/problem+json`, `code` equals `"no_cookies_for_domain"`, `type` equals
  `https://ascend.ai/errors/no-cookies-for-domain`, `status` equals `400`, `instance` is present and `traceId` is 32
  lower case hex characters. No record was written:

  ```bash
  docker exec redis redis-cli EXISTS "session:example.net:e2e-import"
  ```

  Expect `0`.

- **No collateral damage:** every session key that existed before this test started is still present and
  unchanged afterward, and the `e2e-import` key - created only by this test - is removed by Calls 3 and 6:

  ```bash
  docker exec redis redis-cli --scan --pattern "session:*"
  ```

  Compare the key list against the baseline recorded at the start of Reset state. It must be identical.

## Post-run cleanup

Calls 3 and 6 remove every record this spec writes and Call 7 writes none. Only when a call failed before its clear,
delete the key and confirm it is gone. The commands are identical in PowerShell and Unix shells.

```bash
docker exec redis redis-cli DEL "session:example.net:e2e-import"
```

```bash
docker exec redis redis-cli EXISTS "session:example.net:e2e-import"
```

Expect `0`.

## Fixtures

[fixtures/session-import-mixed.json](../fixtures/session-import-mixed.json) - the full import request body:
the `url` `https://www.example.net/`, the `profile` `e2e-import`, a fixed `user_agent`
(`e2e-session-import-test/1.0`) so the run is deterministic, and a Playwright `storage_state` with two
`example.net` cookies carrying canary values (`CANARY-ALPHA-7741`, `CANARY-BETA-8823`), one `example.org` cookie
(`CANARY-FOREIGN-1199`) and an empty `origins` list. Bruno does not read this file. The request file
`docs/api/request/AscendAI/web-hunter/testing/session-import/import-mixed.yml` carries the same body inline, so a
change to one of them must be made to the other in the same commit. Neither cookie name is a WAF-clearance name, so both `example.net` cookies land in the
auth sub-record and the expected split is `auth_cookies` 2, `waf_cookies` 0, `dropped_cookies` 1.

Calls 4 and 7 send their bodies inline, with no fixture file. Call 4 carries the canary `CANARY-GAMMA-5517` in an
`example.net` localStorage entry named `e2e-canary-token`. Call 7 carries the foreign canaries `CANARY-FOREIGN-1199`
(cookie) and `CANARY-FOREIGN-3361` (localStorage on the `example.org` origin) plus the analytics key `_ga`, none of
which counts as the site's own login state.

## Concurrency

Do not run this test in parallel with test 8
([8-session-clear-test.md](8-session-clear-test.md)) or test 10
([10-session-establish-test.md](10-session-establish-test.md)). This test writes
`session:example.net:e2e-import`, and tests 8 and 10 scan or check `example.net` session keys. Its own "No
collateral damage" check compares a scan of `session:*` before and after the run, so it is meaningful only
while no other spec writes or deletes a session key (tests 3, 6, 7, 9, 12 and 22 do). Safe to run in parallel with
everything else in the suite.

- Serial: false
