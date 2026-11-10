# Tier ladder and guard: run tasks template

Spec: [../18-tier-ladder-and-guard-test.md](../18-tier-ladder-and-guard-test.md)

Copy this file to `../runs/<UTC-timestamp>_18-tier-ladder-and-guard-tasks.md` before starting a run. For a repeated run of the same spec in the same sweep, which shares the sweep's timestamp, add `-rerun<N>` before `.md` (`-rerun2` for the second run, `-rerun3` for the third). Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-web-hunter `/health` returns HTTP 200 with `status` `ok`, `service` `ascend-web-hunter` and a non-empty `version`
- [ ] Fake site reachable: `curl -fsS http://127.0.0.1:7031/__requests` returns a request list
- [ ] Redis reachable: `docker exec redis redis-cli PING` returns `PONG`

### Reset state

- [ ] `docker exec redis redis-cli DEL "tier_memory:e2e-fake-site"` returned an integer reply
- [ ] `POST /api/v2/web/session/clear` for `http://e2e-fake-site:7031/` returned HTTP 200 `status` `"cleared"` (read cache emptied)
- [ ] `POST http://127.0.0.1:7031/__reset` returned `{"reset":true}`

### Run

- [ ] From the repository root, `cd docs/api/request/AscendAI`.
- [ ] Step 1 - sent `tier-ladder/private-target-per-tier.yml` with `tier=1-beautifulsoup`, got HTTP 400.
- [ ] Step 1 - sent `tier-ladder/private-target-per-tier.yml` with `tier=2-trafilatura`, got HTTP 400.
- [ ] Step 1 - sent `tier-ladder/private-target-per-tier.yml` with `tier=4-playwright_stealth`, got HTTP 400.
- [ ] Step 1 - sent `tier-ladder/private-target-per-tier.yml` with `tier=4a-patchright`, got HTTP 400.
- [ ] Step 1 - sent `tier-ladder/private-target-per-tier.yml` with `tier=4b-camoufox`, got HTTP 400.
- [ ] Step 1 - sent `tier-ladder/private-target-per-tier.yml` with `tier=5-crawlee_adaptive`, got HTTP 400.
- [ ] Step 1b - MCP `initialize` handshake returned HTTP 200 with no `Mcp-Session-Id` response header.
- [ ] Step 1b - sent `tier-ladder/mcp-private-target.yml` and got HTTP 200.
- [ ] Step 2 - ran the Step 1 request log check (`0` requests) before the first Step 2 reset.
- [ ] Step 2 - `POST http://127.0.0.1:7031/__reset` returned `{"reset":true}`, sent `tier-ladder/redirect-to-private-per-tier.yml` with `tier=1-beautifulsoup`, got HTTP 400, and the log count printed `1 ['/redirect-blocked']`.
- [ ] Step 2 - `POST http://127.0.0.1:7031/__reset` returned `{"reset":true}`, sent `tier-ladder/redirect-to-private-per-tier.yml` with `tier=2-trafilatura`, got HTTP 400, and the log count printed `1 ['/redirect-blocked']`.
- [ ] Step 2 - `POST http://127.0.0.1:7031/__reset` returned `{"reset":true}`, sent `tier-ladder/redirect-to-private-per-tier.yml` with `tier=4-playwright_stealth`, got HTTP 400, and the log count printed `1 ['/redirect-blocked']`.
- [ ] Step 2 - `POST http://127.0.0.1:7031/__reset` returned `{"reset":true}`, sent `tier-ladder/redirect-to-private-per-tier.yml` with `tier=4a-patchright`, got HTTP 400, and the log count printed `1 ['/redirect-blocked']`.
- [ ] Step 2 - `POST http://127.0.0.1:7031/__reset` returned `{"reset":true}`, sent `tier-ladder/redirect-to-private-per-tier.yml` with `tier=4b-camoufox`, got HTTP 400, and the log count printed `1 ['/redirect-blocked']`.
- [ ] Step 2 - `POST http://127.0.0.1:7031/__reset` returned `{"reset":true}`, sent `tier-ladder/redirect-to-private-per-tier.yml` with `tier=5-crawlee_adaptive`, got HTTP 400, and the log count printed `1 ['/redirect-blocked']`.
- [ ] Step 3 - sent `tier-ladder/private-subresource-per-tier.yml` with `tier=4-playwright_stealth`, got HTTP 200.
- [ ] Step 3 - sent `tier-ladder/private-subresource-per-tier.yml` with `tier=4a-patchright`, got HTTP 200.
- [ ] Step 3 - sent `tier-ladder/private-subresource-per-tier.yml` with `tier=4b-camoufox`, got HTTP 200.
- [ ] Step 3 - sent `tier-ladder/private-subresource-per-tier.yml` with `tier=5-crawlee_adaptive`, got HTTP 200.
- [ ] Step 4 - sent `tier-ladder/script-navigation-per-tier.yml` with `tier=4-playwright_stealth`, got HTTP 400.
- [ ] Step 4 - sent `tier-ladder/script-navigation-per-tier.yml` with `tier=4a-patchright`, got HTTP 400.
- [ ] Step 4 - sent `tier-ladder/script-navigation-per-tier.yml` with `tier=4b-camoufox`, got HTTP 400.
- [ ] Step 4 - sent `tier-ladder/script-navigation-per-tier.yml` with `tier=5-crawlee_adaptive`, got HTTP 400.
- [ ] Step 5 - created the private report directory `E2E_OUT` (`mktemp -d`, or a random folder under the temp path in PowerShell), no fixed `/tmp` path.
- [ ] Step 5 - steps 5 to 6b ran in one shell that kept `E2E_OUT`, or (shell keeps no variables) wrote the path to `runs/<UTC-timestamp>_18-tier-ladder-and-guard-e2e-out.txt` in the same command and read it back at the start of every later command that names `E2E_OUT`.
- [ ] Step 5 - sent `tier-ladder/patched-tier-serves.yml` with `tier=4a-patchright` (captured output), got HTTP 200, and the captured `mode` is exactly `4a-patchright`.
- [ ] Step 5 - sent `tier-ladder/patched-tier-serves.yml` with `tier=4b-camoufox` (captured output), got HTTP 200, and the captured `mode` is exactly `4b-camoufox`.
- [ ] Step 6 - deleted `tier_memory:e2e-fake-site` before the first read and got `0` (steps 3 and 5 name an explicit tier and never write tier memory).
- [ ] Step 6 - sent `tier-ladder/tier-memory-first.yml` (captured output) and got HTTP 200.
- [ ] Step 6 - printed the served `mode` from the captured first-read output.
- [ ] Step 6 - recorded `C1` = ___ (`/js-only` log count after the first read, at least `3`).
- [ ] Step 6b - sent `tier-ladder/tier-memory-second.yml` (captured output) and got HTTP 200.
- [ ] Step 6b - printed the served `mode` from the captured second-read output.
- [ ] Step 6b - removed the `E2E_OUT` report directory.

### Expected

- [ ] Step 1 bodies: problem body with `code` `unsafe_uri` for all six tiers; the request log holds `0` requests.
- [ ] Step 1b body: JSON-RPC `result` with `isError: true` and a text entry starting with `unsafe_uri: `.
- [ ] Step 2 bodies: `code` `unsafe_uri` for all six tiers. After each tier's read the request log, emptied right before it, holds exactly one `/redirect-blocked` entry and no other path.
- [ ] Step 3 bodies: `status` `success` with `"QUARRY-THRUSH"` for all four browser tiers; the request log holds no `/canary.png` entry.
- [ ] Step 4 bodies: `code` `unsafe_uri` for all four browser tiers including `5-crawlee_adaptive`; the request log holds no `/article` entry.
- [ ] Step 5 bodies, read from the captured output: `mode` `4a-patchright` for the first call and `mode` `4b-camoufox` for the second call, both holding `"QUARRY-THRUSH"`.
- [ ] Step 6 first body: `mode` is one of `4-playwright_stealth`, `4a-patchright`, `4b-camoufox`, `5-crawlee_adaptive`, content holds `"NIGHT-HERON"`.
- [ ] Read after the second read of step 6b: `GET "tier_memory:e2e-fake-site"` equals the first read's `mode`, and its `TTL` is greater than `0` and no larger than `TIER_MEMORY_TTL_SECONDS`.
- [ ] Step 6b body: `mode` equals the first read's `mode`; the second read added exactly one `/js-only` request (`len - C1` is `1`) and every `/js-only` entry is a full non-conditional fetch.
- [ ] Every assertion checked was an HTTP status, a response body, a Redis key or the fake site request log.

### Post-run cleanup

- [ ] `docker exec redis redis-cli DEL "tier_memory:e2e-fake-site"` returned an integer reply (`1` after a full run)
- [ ] `POST /api/v2/web/session/clear` for `http://e2e-fake-site:7031/` returned HTTP 200 `status` `"cleared"` (read cache emptied)
- [ ] `POST http://127.0.0.1:7031/__reset` returned `{"reset":true}`
- [ ] Only when step 5 used the file fallback: removed `runs/<UTC-timestamp>_18-tier-ladder-and-guard-e2e-out.txt`

### Verdict

- [ ] Verdict: PASS / FAIL (delete the wrong one)

## Result summary

Input tokens:

Output tokens:

Start (UTC):

End (UTC):

Duration:

---

## Additional tasks I did

<!-- Optional. List anything outside the spec, e.g. diagnostic curls, manual log inspection, retries with different inputs. Leave empty if nothing extra. -->
