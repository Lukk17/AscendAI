# e2e fixtures

ascend-web-hunter tools (`web_search`, `web_read` via MCP; `/api/v1/web/search`, `/api/v2/web/read` via REST) take
string arguments only — no file uploads.

- `session-clear-seed.json` — a synthetic minimal `storage_state` record used by test 8
  ([../testing/8-session-clear-test.md](../testing/8-session-clear-test.md)) to seed a session for `example.net`
  directly in Redis, without a login flow, FlareSolverr, or a human. `docker cp`'d into the `redis` container and
  loaded via `redis-cli -x SETEX ... < file`, since piping the JSON through a shell pipe corrupts it (PowerShell
  prepends a BOM, bash treats a bare quoted string as a command).
- `session-status-expired-seed.json` — the same kind of synthetic `storage_state` record, used by test 9
  ([../testing/9-session-status-test.md](../testing/9-session-status-test.md)) to seed a deliberately stale session
  for `example.org`, `saved_at` set far outside the auth TTL so the `expired` branch of `session/status` is
  reachable without waiting 14 days for one to lapse naturally. Test 9's `active`-branch call needs a `saved_at` of
  "now" instead, which can't be a committed fixture without going stale immediately, so that JSON is built inline
  in the spec's Run section rather than checked in here.

Reserved for future tests that might need canary content, e.g. a small static HTML page hosted under
`fixtures/static/` for an extraction-tier regression test against a known body.
