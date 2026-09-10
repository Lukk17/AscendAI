# e2e testing guide

Self-contained walkthroughs that an AI agent (or a human) can execute end-to-end against a live ascend-web-hunter
container. Each `<N>-<capability>-test.md` spec in this directory drives one capability through its Bruno request
(plus, for MCP tests, a `curl` `initialize` handshake), with explicit prerequisite checks, reset commands, run
steps, and expected outcomes. The paired run-record templates live in the `templates/` subdirectory; executed run
records land in `runs/`.

## Format

Every `<N>-<capability>-test.md` file is the **immutable spec** for one test and uses the same fixed template.

1. **What this verifies.** Bullet list of behaviours.
2. **Prerequisites.** Concrete check commands (`curl`, `bru --version`) the runner executes before starting. Each
   command is its own code block; the prose around it states what success looks like.
3. **Reset state.** One command per code block, executed in order, to wipe state so the test is reproducible.
   Most ascend-web-hunter tests do not need reset (REST search is stateless against the host; SearXNG owns its own
   cache). The v2 read tests can optionally flush the per-URL Redis session key.
4. **Run.** One or more numbered steps. Each step is a single Bruno CLI invocation. MCP-path tests start with a
   `curl` POST to `/mcp` for the `initialize` handshake, capture the `Mcp-Session-Id` value (a 32 character hexadecimal session id without hyphens, as
   FastMCP emits it), then pass it into subsequent Bruno calls via `--env-var "mcp_session_id=<session id>"`. Steps wait for HTTP 200 before continuing.
5. **Expected.** Observable-behaviour assertions verified after each step: HTTP status codes, JSON response shape
   (array length, presence of `title` / `url` / `content` keys), MCP `tools/list` enumeration, MCP `tools/call`
   payload contents. NOT log substrings.
6. **Fixtures.** Paths to local files the test reads (none for the current suite).

Each spec has a matching `<N>-<capability>-tasks.template.md` in the [templates/](templates/) subdirectory — the
**checkbox template** for a run. The runner never edits the spec or the template directly. Before starting a run,
it copies the template from `templates/` into [runs/](runs/) with a timestamped filename, ticks boxes as it
progresses, fills in `Result summary` and `Verdict`, and logs anything done outside the spec under
`Additional tasks I did`. See [runs/README.md](runs/README.md) for the full contract and naming convention.

## Bruno is the source of truth

Every test runs the matching Bruno request file under `docs/api/request/AscendAI/web-hunter/testing/` via the
Bruno CLI.

```bash
cd docs/api/request/AscendAI
```

```bash
bru run "web-hunter/testing/<request>.yml" --env ascend-local
```

The request's saved default rows are what gets sent. To test an alternative payload, edit the disabled rows in the
YAML directly.

Install Bruno CLI once with `npm install -g @usebruno/cli`.

## Test order

Numbered by setup cost (lowest first). Run earliest first when stepping through; each is self-contained so any can
be run on its own.

1. [1-invalid-input-test.md](1-invalid-input-test.md). REST validator short-circuit on blank / over-long `query`.
   **Air-gap-safe.**
2. [2-search-happy-path-test.md](2-search-happy-path-test.md). `GET /api/v1/web/search` against a stable query.
3. [3-read-example-com-test.md](3-read-example-com-test.md). `POST /api/v2/web/read` against `example.com`.
4. [4-mcp-tools-list-test.md](4-mcp-tools-list-test.md). MCP `tools/list` advertises `web_search` and `web_read`.
5. [5-mcp-search-test.md](5-mcp-search-test.md). MCP `tools/call` for `web_search` returns structured results.
6. [6-tiered-scraping-test.md](6-tiered-scraping-test.md). Per-tier regression sweep (`curl_cffi` static,
   FlareSolverr Cloudflare, Playwright JS-rendered) against real sites.
7. [7-authenticated-realworld-scraping-test.md](7-authenticated-realworld-scraping-test.md). Real-world URL matrix
   plus automated saucedemo login-reuse plus human-solved reCAPTCHA capture. **Runs last; Part 3 needs a human on
   the main session.**
8. [8-session-clear-test.md](8-session-clear-test.md). `POST /api/v2/web/session/clear` against a seeded and an
   unseeded session. Redis-only, no egress — cheapest test in the suite alongside 1 and 4. Do not run in parallel
   with test 10.
9. [9-session-status-test.md](9-session-status-test.md). `POST /api/v2/web/session/status` across its `none`,
   `expired`, and `active` states. Redis-only, no egress — same cost tier as 1, 4, and 8.
10. [10-session-establish-test.md](10-session-establish-test.md). `POST /api/v2/web/session/establish` — asserts
    the immediate response, plus a live-verified finding: the background monitor's "cleared" check accepts any
    unchallenged page, so it captures a session within seconds even though nobody solved a challenge. Launches a
    real headful Playwright browser that can be held by a background monitor for up to 10 minutes. Highest per-run
    resource cost in this module's suite; do not run in parallel with test 8 or with itself; see the spec's own
    cost note.

## Cross-cutting conventions

Pass criteria are observable behaviour only. HTTP status, JSON response body content (array length, field
presence and value patterns), MCP tool registry contents. Logs are diagnostic, not authoritative. Log lines drift
across versions and aren't visible from every runner's shell. If a behaviour assertion fails, a tail of the
ascend-web-hunter log (or `docker logs ascend-web-hunter`) is the next diagnostic step, but not a pass criterion.

## Adding a new test

1. Add a Bruno request under `docs/api/request/AscendAI/web-hunter/testing/<request>.yml`.
2. Create `apps/ascend-web-hunter/e2e/testing/<N>-<capability>-test.md` using the template above. Pick the lowest unused
   number prefix that matches its setup-cost position in the order.
3. Create `apps/ascend-web-hunter/e2e/testing/templates/<N>-<capability>-tasks.template.md` mirroring the spec's
   checkboxes.
4. Add the file to the ordered list in this README and in the capability table in the parent
   [../README.md](../README.md).
