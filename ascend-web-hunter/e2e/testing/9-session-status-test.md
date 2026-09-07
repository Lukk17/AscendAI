# Session status: e2e test

## What this verifies

`POST /api/v2/web/session/status` reports the auth-session lifecycle state for a `url` + `profile` without changing
anything. The endpoint's own contract (`SessionManager.status`) is a three-way state, and all three are gated:

- **`none`** — no session record was ever stored for this `url` + `profile`. `auth_ttl_remaining_seconds` is `0` and
  `last_validated` is `null`.
- **`expired`** — a session record exists, but its `saved_at` timestamp is older than `SESSION_AUTH_TTL_SECONDS`
  (14 days by default). `auth_ttl_remaining_seconds` is `0` and `last_validated` is `null`, identical to `none` on
  those two fields — the only observable difference is the `status` string itself, so this test seeds a real record
  to exercise that branch rather than assuming it from the `none` case.
- **`active`** — a session record exists with a `saved_at` inside the TTL window. `auth_ttl_remaining_seconds` is
  close to the 14-day ceiling and `last_validated` is a recent Unix timestamp.

All three are asserted on the response body only, never on log output.

## Prerequisites

Check Bruno CLI is installed.

```powershell
bru --version
```

Expect a version string.

Check the ascend-web-hunter server is reachable.

```powershell
curl -fsS http://localhost:7021/health
```

Expect HTTP 200 with `{"status":"ok"}`.

Check Redis is reachable from the host's Docker context (this test seeds and reads keys directly).

```powershell
docker exec redis redis-cli PING
```

Expect `PONG`.

## Reset state

Confirm `example.com` and `example.org` currently carry no session (both are IANA-reserved documentation domains;
`example.com` is read constantly by test 3 through the `curl_cffi` tier, which never writes a session record, and
`example.org` is touched by no other spec in this suite).

```powershell
docker exec redis redis-cli EXISTS "session:example.com:default"
```

```powershell
docker exec redis redis-cli EXISTS "session:example.org:default"
```

Expect `0` for both. If `example.org` returns `1`, a previous run of this spec did not clean up — delete it before
continuing.

```powershell
docker exec redis redis-cli DEL "session:example.org:default"
```

Seed a **stale** session record for `example.org`. The fixture
[fixtures/session-status-expired-seed.json](../fixtures/session-status-expired-seed.json) carries a `saved_at` of
`1735689600` (2025-01-01T00:00:00Z), far older than the 14-day TTL, so `status()` computes an already-lapsed auth
window without the test needing to wait 14 days for one to occur naturally.

```powershell
docker cp ascend-web-hunter/e2e/fixtures/session-status-expired-seed.json redis:/tmp/session-status-expired-seed.json
```

```powershell
docker exec redis sh -c "redis-cli -x SETEX 'session:example.org:default' 1209600 < /tmp/session-status-expired-seed.json"
```

Expect `OK`.

## Run

Move into the Bruno collection root first.

```powershell
cd docs/api/request/AscendAI
```

Call 1 — `example.com`, which has never carried a session (the `none` branch).

```powershell
bru run "web-hunter/testing/session-status-none.yml" --env ascend-local
```

Call 2 — `example.org`, seeded with the stale fixture above (the `expired` branch).

```powershell
bru run "web-hunter/testing/session-status-expired.yml" --env ascend-local
```

Re-seed `example.org` with a **fresh** `saved_at` (current Unix time) so the same key now falls inside the TTL
window. This has no static fixture — the timestamp has to be "now" at run time — so build it inline instead of
committing a file that would immediately go stale.

```powershell
$epoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$json = '{"auth":{"storage_state":{"cookies":[{"name":"e2e-probe","value":"1","domain":".example.org","path":"/","expires":-1,"httpOnly":false,"secure":true,"sameSite":"Lax"}],"origins":[]},"user_agent":"e2e-session-status-test/1.0","saved_at":' + $epoch + '}}'
Set-Content -Path session-status-active-seed.json -Value $json -NoNewline -Encoding ascii
```

```powershell
docker cp session-status-active-seed.json redis:/tmp/session-status-active-seed.json
```

```powershell
docker exec redis sh -c "redis-cli -x SETEX 'session:example.org:default' 1209600 < /tmp/session-status-active-seed.json"
```

Expect `OK`.

Call 3 — `example.org` again, now inside its TTL window (the `active` branch).

```powershell
bru run "web-hunter/testing/session-status-active.yml" --env ascend-local
```

## Expected

- **Call 1 (`none`):** HTTP 200. Body `status` equals `"none"`, `auth_ttl_remaining_seconds` equals `0`,
  `last_validated` is `null`, `profile` equals `"default"`.
- **Call 2 (`expired`):** HTTP 200. Body `status` equals `"expired"`, `auth_ttl_remaining_seconds` equals `0`,
  `last_validated` is `null`.
- **Call 3 (`active`):** HTTP 200. Body `status` equals `"active"`, `auth_ttl_remaining_seconds` is above
  `1209000` (within a few minutes of the 1,209,600-second ceiling), `last_validated` is a number within the last
  5 minutes.
- **No collateral damage:** every session key that existed before this test started is still present and unchanged
  afterward, and `example.org`'s key — created only by this test — is removed at cleanup.

  ```powershell
  docker exec redis redis-cli DEL "session:example.org:default"
  ```

  ```powershell
  docker exec redis redis-cli --scan --pattern "session:*"
  ```

  Compare the key list against the one recorded before Reset state ran; it must be identical.

  Delete the locally-generated seed file the Run section created (it is not a committed fixture):

  ```powershell
  Remove-Item session-status-active-seed.json
  ```

## Fixtures

[fixtures/session-status-expired-seed.json](../fixtures/session-status-expired-seed.json) — a synthetic minimal
`storage_state` record for `example.org` with a `saved_at` timestamp already outside the auth TTL, not a captured
real login. `status()` only reads `saved_at` and the record's presence; it never inspects the cookies themselves,
so the fixture's shape only needs to match what `save_storage_state` would have written.
