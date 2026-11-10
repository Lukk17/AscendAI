# Session clear: e2e test

## What this verifies

`POST /api/v2/web/session/clear` is the operator-recovery path for a poisoned session: it deletes the stored
session for a `url` + `profile` and any in-process cached read results for that domain, and it is documented as
idempotent - it always returns HTTP 200 whether or not a session existed. Two behaviours are gated:

- **Clearing an existing session** removes the Redis record and reports `existed=true`.
- **Clearing a session that was never stored** is a no-op, not an error - it still returns HTTP 200 with
  `existed=false`. This is deliberate per the endpoint's own docstring and must not regress into a 404 or 500.

Both calls are asserted on response body plus persisted Redis state, never on log output.

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

Check Redis is reachable from the host's Docker context (this test seeds and reads a key directly).

```bash
docker exec redis redis-cli PING
```

Expect `PONG`.

## Reset state

Run every command of this section and of Run from the repository root, except where Run moves into the Bruno
collection root.

Record the session key list before anything else, so the "No collateral damage" check under Expected has a
baseline to compare against. Copy the output into the run record.

```bash
docker exec redis redis-cli --scan --pattern "session:*"
```

Expect one line per stored session, or no line. `--scan` only reads, it changes nothing.

Confirm `example.net` and `example.edu` currently carry no session. `example.net` is IANA-reserved for
documentation, and `example.edu` is a resolving domain no other spec of this suite reads, so this should already be
true on a clean run.

```bash
docker exec redis redis-cli EXISTS "session:example.net:default"
```

```bash
docker exec redis redis-cli EXISTS "session:example.edu:default"
```

Expect `0` for both. If either returns `1`, a previous run of this spec did not clean up. Delete both keys in one
call before continuing, and leave both keys out of the baseline above.

```bash
docker exec redis redis-cli DEL "session:example.net:default" "session:example.edu:default"
```

Expect `0`, `1` or `2`, the number of keys removed.

Prime the no-op path. Call the session clear endpoint once for `https://example.edu/`, with the same endpoint and
body shape call 2 below sends. This empties the service's in-process per-domain read cache for `example.edu`, which a
manual read of that domain would fill and which the Redis deletes above cannot reach, so the call under test is a
true no-op and reports `cleared_cache_entries` equal to `0`.

PowerShell:

```powershell
curl.exe -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/clear -H "Content-Type: application/json" -d '{"url":"https://example.edu","profile":"default"}'
```

Unix:

```bash
curl -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/clear -H "Content-Type: application/json" -d '{"url":"https://example.edu","profile":"default"}'
```

Expect HTTP 200 with `existed` equal to `false`. A non-zero `cleared_cache_entries` here is the priming doing its
job, not a failure.

Seed a session record for `example.net` so the "existing session" call has something real to remove. The fixture
[fixtures/session-clear-seed.json](../fixtures/session-clear-seed.json) holds the same JSON shape
`CookieManager.save_storage_state` produces, so the test needs no login flow, no browser tier, and no human. It
only needs a record to exist under the key the service reads. Copy it into the `redis` container first. Piping
JSON through a PowerShell or bash pipe into `redis-cli -x` mangles it (PowerShell prepends a BOM, and bash treats
a bare quoted string as a command), and a file plus shell redirection avoids both. The path below is relative to
the repository root, and it is the same in both shells.

```bash
docker cp apps/ascend-web-hunter/e2e/fixtures/session-clear-seed.json redis:/tmp/session-clear-seed.json
```

```bash
docker exec redis sh -c "redis-cli -x SETEX 'session:example.net:default' 1209600 < /tmp/session-clear-seed.json"
```

Expect `OK`.

```bash
docker exec redis redis-cli EXISTS "session:example.net:default"
```

Expect `1`.

Remove the copied seed file now that the record is in Redis. Nothing after this point reads `/tmp`, and leaving the
copy in the container would carry one run's state into the next. The `sh -c` wrapper is the same guard the seed
command above uses, and here it keeps the container path intact, because Git Bash on Windows rewrites a bare
`/tmp/...` argument into a host path before Docker ever sees it.

```bash
docker exec redis sh -c "rm /tmp/session-clear-seed.json"
```

Expect no output.

## Run

Move into the Bruno collection root first, from the repository root.

```bash
cd docs/api/request/AscendAI
```

Call 1 - clear the session just seeded for `example.net`.

```bash
bru run "web-hunter/testing/session-clear-existing.yml" --env ascend-local
```

Call 2 - clear `example.edu`, which has never carried a session (the idempotent / no-op path).

```bash
bru run "web-hunter/testing/session-clear-idempotent.yml" --env ascend-local
```

## Expected

- **Call 1 (existing session):** HTTP 200. Body `status` equals `"cleared"`, `url` equals
  `"https://example.net/"`, `existed` equals `true`. After the call, `session:example.net:default` no longer
  exists in Redis:

  ```bash
  docker exec redis redis-cli EXISTS "session:example.net:default"
  ```

  Expect `0`.

- **Call 2 (idempotent no-op):** HTTP 200 - not 404, not 500. Body `status` equals `"cleared"`, `url` equals
  `"https://example.edu/"`, `existed` equals `false`, `cleared_cache_entries` equals `0`. Redis never held
  `session:example.edu:default` before or after the call:

  ```bash
  docker exec redis redis-cli EXISTS "session:example.edu:default"
  ```

  Expect `0`.

- **No collateral damage:** every session key that existed before this test started (any domain other than
  `example.net`) is still present and unchanged after the run.

  ```bash
  docker exec redis redis-cli --scan --pattern "session:*"
  ```

  Compare the key list against the baseline recorded at the start of Reset state. It must be identical: the
  `example.net` key this test added was removed by Call 1.

## Post-run cleanup

The only key this test writes is `session:example.net:default` (the seed), and Call 1 removes it. If Call 1 failed,
the seed is still there, and a regression in Call 2 could have written `session:example.edu:default`. Delete both
in one call, whatever the verdict.

```bash
docker exec redis redis-cli DEL "session:example.net:default" "session:example.edu:default"
```

Expect `0` on a passing run (Call 1 already removed the seed), `1` or `2` otherwise.

## Fixtures

[fixtures/session-clear-seed.json](../fixtures/session-clear-seed.json) - a synthetic minimal `storage_state`
record for `example.net`, not a captured real login. `clear_session` only checks whether a Redis key exists; it
never inspects the record's contents, so the fixture's shape only needs to match what `save_storage_state`
would have written, not come from a real browser session.

## Concurrency

Do not run this test in parallel with test 10
([10-session-establish-test.md](10-session-establish-test.md)). A regression in test 10 would write
`session:example.net:e2e-establish`, a different key from the `session:example.net:default` this test seeds and
clears, but this test compares a scan of `session:*` before and after its run, so that key would appear in the scan
and fail the comparison. The same holds for any spec that writes or deletes any `session:*` key while this test
runs (tests 3, 6, 7, 9, 10, 12, 17 and 22 do), so the comparison is meaningful only when this test runs alone. The
idempotent call clears `example.edu`, a domain no other spec of this suite reads, so no other spec fills its read
cache. Safe to run in parallel with tests 1, 2, 4, 5 and 15.

- Serial: false
