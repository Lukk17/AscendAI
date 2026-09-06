# Session clear: e2e test

## What this verifies

`POST /api/v2/web/session/clear` is the operator-recovery path for a poisoned session: it deletes the stored
session for a `url` + `profile` and any in-process cached read results for that domain, and it is documented as
idempotent — it always returns HTTP 200 whether or not a session existed. Two behaviours are gated:

- **Clearing an existing session** removes the Redis record and reports `existed=true`.
- **Clearing a session that was never stored** is a no-op, not an error — it still returns HTTP 200 with
  `existed=false`. This is deliberate per the endpoint's own docstring and must not regress into a 404 or 500.

Both calls are asserted on response body plus persisted Redis state, never on log output.

## Concurrency

Do not run this test in parallel with test 10
([10-session-establish-test.md](10-session-establish-test.md)) — both mutate `session:example.net:default`. Safe to
run in parallel with everything else in the suite.

## Prerequisites

Check Bruno CLI is installed.

```powershell
bru --version
```

Expect a version string.

Check the AscendWebSearch server is reachable.

```powershell
curl -fsS http://localhost:7021/health
```

Expect HTTP 200 with `{"status":"ok"}`.

Check Redis is reachable from the host's Docker context (this test seeds and reads a key directly).

```powershell
docker exec redis redis-cli PING
```

Expect `PONG`.

## Reset state

Confirm `example.net` and `example.com` currently carry no session (both are IANA-reserved documentation
domains touched by no other spec in this suite, so this should already be true on a clean run).

```powershell
docker exec redis redis-cli EXISTS "session:example.net:default"
```

```powershell
docker exec redis redis-cli EXISTS "session:example.com:default"
```

Expect `0` for both. If either returns `1`, a previous run of this spec did not clean up — delete it before
continuing.

```powershell
docker exec redis redis-cli DEL "session:example.net:default"
```

Seed a session record for `example.net` so the "existing session" call has something real to remove. The fixture
[fixtures/session-clear-seed.json](../fixtures/session-clear-seed.json) holds the same JSON shape
`CookieManager.save_storage_state` produces, so the test needs no login flow, no FlareSolverr, and no human — it
only needs a record to exist under the key the service reads. Copy it into the `redis` container first (piping
JSON through a PowerShell or bash pipe into `redis-cli -x` mangles it — PowerShell prepends a BOM, bash treats a
bare quoted string as a command — a file + shell redirection avoids both).

```powershell
docker cp AscendWebSearch/e2e/fixtures/session-clear-seed.json redis:/tmp/session-clear-seed.json
```

```powershell
docker exec redis sh -c "redis-cli -x SETEX 'session:example.net:default' 1209600 < /tmp/session-clear-seed.json"
```

Expect `OK`.

```powershell
docker exec redis redis-cli EXISTS "session:example.net:default"
```

Expect `1`.

## Run

Move into the Bruno collection root first.

```powershell
cd docs/api/request/AscendAI
```

Call 1 — clear the session just seeded for `example.net`.

```powershell
bru run "web-search/testing/session-clear-existing.yml" --env ascend-local
```

Call 2 — clear `example.com`, which has never carried a session (the idempotent / no-op path).

```powershell
bru run "web-search/testing/session-clear-idempotent.yml" --env ascend-local
```

## Expected

- **Call 1 (existing session):** HTTP 200. Body `status` equals `"cleared"`, `url` equals
  `"https://example.net/"`, `existed` equals `true`. After the call, `session:example.net:default` no longer
  exists in Redis:

  ```powershell
  docker exec redis redis-cli EXISTS "session:example.net:default"
  ```

  Expect `0`.

- **Call 2 (idempotent no-op):** HTTP 200 — not 404, not 500. Body `status` equals `"cleared"`, `url` equals
  `"https://example.com/"`, `existed` equals `false`, `cleared_cache_entries` equals `0`. Redis never held
  `session:example.com:default` before or after the call:

  ```powershell
  docker exec redis redis-cli EXISTS "session:example.com:default"
  ```

  Expect `0`.

- **No collateral damage:** every session key that existed before this test started (any domain other than
  `example.net`) is still present and unchanged after the run.

  ```powershell
  docker exec redis redis-cli --scan --pattern "session:*"
  ```

  Compare the key list against the one recorded before Reset state ran; it must be identical except for the
  `example.net` key this test added and removed itself.

## Fixtures

[fixtures/session-clear-seed.json](../fixtures/session-clear-seed.json) — a synthetic minimal `storage_state`
record for `example.net`, not a captured real login. `clear_session` only checks whether a Redis key exists; it
never inspects the record's contents, so the fixture's shape only needs to match what `save_storage_state`
would have written, not come from a real browser session.
