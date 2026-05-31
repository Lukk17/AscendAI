# e2e fixtures

AscendWebSearch tools (`web_search`, `web_read` via MCP; `/api/v1/web/search`, `/api/v2/web/read` via REST) take
string arguments only — no file uploads. The current suite has no fixtures.

Reserved for future tests that might need canary content, e.g. a small static HTML page hosted under
`fixtures/static/` for an extraction-tier regression test against a known body.
