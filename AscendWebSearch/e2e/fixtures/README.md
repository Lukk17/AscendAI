# e2e fixtures

AscendWebSearch tools (`web_search`, `web_read` via MCP; `/api/v1/web/search`, `/api/v2/web/read` via REST) take
string arguments only — no file uploads.

- `session-clear-seed.json` — a synthetic minimal `storage_state` record used by test 8
  ([../testing/8-session-clear-test.md](../testing/8-session-clear-test.md)) to seed a session for `example.net`
  directly in Redis, without a login flow, FlareSolverr, or a human. `docker cp`'d into the `redis` container and
  loaded via `redis-cli -x SETEX ... < file`, since piping the JSON through a shell pipe corrupts it (PowerShell
  prepends a BOM, bash treats a bare quoted string as a command).

Reserved for future tests that might need canary content, e.g. a small static HTML page hosted under
`fixtures/static/` for an extraction-tier regression test against a known body.
