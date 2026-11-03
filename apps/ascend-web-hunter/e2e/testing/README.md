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

Each spec has a matching `<N>-<capability>-tasks.template.md` in the [templates/](templates/) subdirectory - the
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
   browser-tier Cloudflare, Playwright JS-rendered) against real sites.
7. [7-authenticated-realworld-scraping-test.md](7-authenticated-realworld-scraping-test.md). Real-world URL matrix
   plus automated saucedemo login-reuse. Two parts, both automated, no human step. Runs after test 6 because its
   reset flushes every `session:*` key.
8. [8-session-clear-test.md](8-session-clear-test.md). `POST /api/v2/web/session/clear` against a seeded and an
   unseeded session. Redis-only, no egress - cheapest test in the suite alongside 1 and 4. Do not run in parallel
   with test 10.
9. [9-session-status-test.md](9-session-status-test.md). `POST /api/v2/web/session/status` across its `none`,
   `expired`, and `active` states. Redis-only, no egress - same cost tier as 1, 4, and 8.
10. [10-session-establish-test.md](10-session-establish-test.md). `POST /api/v2/web/session/establish` - asserts
    the immediate response, plus a live-verified finding: the background monitor's "cleared" check accepts any
    unchallenged page, so it captures a session within seconds even though nobody solved a challenge. Launches a
    real headful Playwright browser that can be held by a background monitor for up to 10 minutes. Highest per-run
    resource cost in this module's suite; do not run in parallel with test 8 or with itself; see the spec's own
    cost note.
11. [11-captcha-solve-and-capture-test.md](11-captcha-solve-and-capture-test.md). Human-solved hCaptcha on the
    democaptcha demo form, proven by the `hmt_id` cookie a human's checkbox click sets and captured under
    `session:democaptcha.com:default`. Asserts the capture only, since the form renders its widget on every load and
    a second read of it can never show reuse (register A60). Part 2 opens two windows at once (profiles `e2e-h1`
    then `e2e-h2`) and solves them out of order (`e2e-h2` first), asserting the listing frees exactly that flow's
    slot each time and each profile's session holds `hmt_id` with the other key unchanged. Runs last of all, alone,
    on the main session, and only on a human's go.
12. [12-clearance-reuse-test.md](12-clearance-reuse-test.md). Stored Cloudflare clearance reused on a second read
    of the same site, fully automated: a cold read of `scrapingcourse.com` stores `cf_clearance`, and a read of the
    same page under a different address must answer HTTP 200 with `status="success"` faster than the cold read,
    never a 428. A 428 is a FAIL and register defect A61 until its fix lands. Runs after test 6, which reads the
    same site, and not alongside tests 6, 7, 8 or 10.
13. [13-structured-extraction-test.md](13-structured-extraction-test.md). Deterministic formats on the shared
    fake site: structured JSON-LD metadata, tables cell for cell, and screenshot twice on the pinned
    Playwright tier with the request log proving the second read re-ran the chain. Reads only, no NoVNC
    flow, safe beside every spec.
14. [14-document-routing-test.md](14-document-routing-test.md). Non-HTML routing against the full stack:
    direct PDF, image (OCR job to terminal state), audio, oversized PDF refused before reading, and a page
    linking a PDF under the blocked name. OCR engine-bound and docling-bound, so the whole spec runs alone
    in the quarantine lane.
15. [15-schema-extraction-ai-test.md](15-schema-extraction-ai-test.md). Schema extraction with the real
    hosted model (provider `minimax`, model `MiniMax-M2.7`, never LM Studio): validated answer, recipe
    stored with TTL, replay without the model, drift rebuild, second schema separation, prompt-injection
    resistance, unsatisfiable schema refusal. Writes only `recipe:e2e-fake-site:*`, safe beside every
    spec. Token use goes into the run record and the spec's `docs/E2E_COST.md` row.
16. [16-crawl-jobs-test.md](16-crawl-jobs-test.md). Crawl jobs on the fake site crawl tree: submission
    and polling, result index under the tenant prefix with depth, pattern and robots bounds, unsafe
    links counted, unchanged pages copied forward on recrawl, tenant isolation across two tenants, and
    cancel while running. Mutates only the two tenants' crawl data and the fake site request log.
17. [17-session-import-test.md](17-session-import-test.md). `POST /api/v2/web/session/import` stores an
    out-of-band Playwright `storage_state` for `https://www.example.net/` under profile `e2e-import` (keeps the
    domain's two canary cookies, drops the foreign cookie), reads back `active` via `session/status` and clears
    via `session/clear`. Redis-only, no egress. Runs after test 8 and before test 10.
18. [18-tier-ladder-and-guard-test.md](18-tier-ladder-and-guard-test.md). Tier ladder guard and tier
    memory on the shared fake site: blocked-name reads refused with `unsafe_uri` on every read tier
    before any fetch, redirect, subresource and script navigation toward the blocked name contained,
    patched tiers serving under their own names, JavaScript-only page warming `tier_memory` and reused
    on the second read. Writes only `tier_memory:e2e-fake-site`, safe beside every spec that does not
    read the fake site's JavaScript-only page.
19. [19-challenge-verdicts-test.md](19-challenge-verdicts-test.md). Challenge verdicts on the shared
    fake site: five wall pages answer HTTP 428 with the gated intervention type and a non-empty `vnc_url`,
    five content pages answer HTTP 200 `success` with their canaries, and `/metrics` grows both verdicts.
    Each wall row opens a NoVNC flow, so it runs alone after the concurrent-intervention spec of
    `open-several-novnc-windows-at-once`, beside no spec that can answer a 428.
20. [20-concurrent-interventions-test.md](20-concurrent-interventions-test.md). Concurrent NoVNC windows on the
    shared fake site's thin turnstile wall page, fully automated, no human: reads under profiles `e2e-w1` to
    `e2e-w4` answer HTTP 428 with four distinct `flow_id` values and four distinct `window.slot` values, the REST
    listing and the MCP `session_interventions` tool report the same four flows, a fifth read under `e2e-w5`
    answers HTTP 428 with a fifth flow and slot, a sixth read under `e2e-w6` answers HTTP 409 with `holder_url`,
    a rejoin under `e2e-w2` answers HTTP 428 `joined`, and lease expiry drains
    every flow back to `active_flows` 0 with no session key left behind. Fills every window slot, so it runs alone
    after spec 10, beside no spec that can answer a 428.
21. [21-platform-contract-test.md](21-platform-contract-test.md). The shared platform contract: health, readiness,
    the problem bodies, the errors counter, security headers, the MCP `initialize` plus refusal, and the REST
    `unsafe_uri` refusals. Reads and refusals only, no `session:*` key, safe beside every spec.
    Twenty one specs in all, twenty of them automated (spec 11 needs a human).

## Cross-cutting conventions

Pass criteria are observable behaviour only. HTTP status, JSON response body content (array length, field
presence and value patterns), MCP tool registry contents. Logs are diagnostic, not authoritative. Log lines drift
across versions and aren't visible from every runner's shell. If a behaviour assertion fails, a tail of the
ascend-web-hunter log (or `docker logs ascend-web-hunter`) is the next diagnostic step, but not a pass criterion.

Deterministic first: a behaviour checkable by HTTP status, response body, or persisted state (Redis, the object store,
Postgres, Qdrant, the fake site request log) is checked by a Bruno request with its assertions inside the request file,
and no AI model decides the verdict. An AI-run spec is added only where the result needs a real model (schema extraction,
a chat that must call a tool, a retrieval answer). A new spec takes the next free number at implementation time. When a
feature changes, its existing spec and template are updated in place under the same number, and a new spec is written only
when no existing spec can be updated to cover the change (owner answer 67.2 of 2026-10-04).

## Problem body check

Every REST error a planned web-hunter spec asserts is checked the same way in its Bruno request, so a future request
copies the block below into its `runtime.scripts` tests and changes only the expected `code`. The check is:

- `Content-Type` starts with `application/problem+json`.
- `code` equals the expected lower case snake case code.
- `type` equals `https://ascend.ai/errors/` followed by the code with every `_` replaced by `-`.
- `status` equals the HTTP status.
- `instance` is present.
- `traceId` matches `^[0-9a-f]{32}$`.
- A refusal with a retry hint also asserts the `Retry-After` header.
- The 428 human help body asserts `code` `human_intervention_required` and a non-empty `vnc_url`.
- The 409 busy body asserts `code` `novnc_busy`.

A sample Bruno `tests` script a request copies, for a refusal with code `unsafe_uri`:

```javascript
test("Content-Type is a problem body", function () {
    expect(res.getHeaders()["content-type"]).to.include("application/problem+json");
});
test("code is unsafe_uri", function () {
    expect(res.getBody().code).to.equal("unsafe_uri");
});
test("type is the unsafe_uri error URI", function () {
    expect(res.getBody().type).to.equal("https://ascend.ai/errors/unsafe-uri");
});
test("status equals the HTTP status", function () {
    expect(res.getBody().status).to.equal(res.getStatus());
});
test("instance is present", function () {
    expect(res.getBody().instance).to.be.a("string").and.not.empty;
});
test("traceId is 32 lower case hex characters", function () {
    expect(res.getBody().traceId).to.match(/^[0-9a-f]{32}$/);
});
```

The `type` slug follows `problem_type_slug` in `libs/ascend-python-common/src/ascend_python_common/errors/problem.py`:
lower case, every `_` replaced by `-`. A retry hint on a refusal also asserts the `Retry-After` header.

## Adding a new test

1. Add a Bruno request under `docs/api/request/AscendAI/web-hunter/testing/<request>.yml`.
2. Create `apps/ascend-web-hunter/e2e/testing/<N>-<capability>-test.md` using the template above. Pick the lowest unused
   number prefix that matches its setup-cost position in the order.
3. Create `apps/ascend-web-hunter/e2e/testing/templates/<N>-<capability>-tasks.template.md` mirroring the spec's
   checkboxes.
4. Add the file to the ordered list in this README and in the capability table in the parent
   [../README.md](../README.md).
