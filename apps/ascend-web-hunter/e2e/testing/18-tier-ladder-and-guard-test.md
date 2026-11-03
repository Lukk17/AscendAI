# Tier ladder and guard: e2e test

## What this verifies

Part A proves the fetch guard refuses a private target on every read tier before any fetch happens.

1. For each of `1-beautifulsoup`, `2-trafilatura`, `4-playwright_stealth`, `4a-patchright`, `4b-camoufox` and
   `5-crawlee_adaptive`, a REST read of the fake site article under its blocked name `e2e-fake-site-blocked`
   with that `tier` answers HTTP 400 with the problem body holding `code` `unsafe_uri`. The MCP `web_read`
   call for `4a-patchright` answers a tool error whose text starts with `unsafe_uri`. The fake site request
   log is empty afterwards, so no read reached the fake site.

Part B reads pages under the allowed name `e2e-fake-site` (design D12 of `add-web-search-scraping-e2e`,
owner answer 67.3 of 2026-10-04).

2. For each tier of step 1, a read of the `/redirect-blocked` page under the allowed name answers HTTP 400
   with `code` `unsafe_uri`: the page answers a redirect to the article under the blocked name, and the
   request log shows the allowed page fetched but no request to the private path.
3. For each browser tier (`4-playwright_stealth`, `4a-patchright`, `4b-camoufox`, `5-crawlee_adaptive`), a
   read of the `/private-image` page under the allowed name, which loads an image from a path under the
   blocked name, answers HTTP 200 with `status` `success` and the page's canary sentence, and the request
   log shows no request to the image path.
4. For each of `4-playwright_stealth`, `4a-patchright`, `4b-camoufox` and `5-crawlee_adaptive`, a read of the
   `/script-nav` page under the allowed name, whose script sets `window.location` to a path under the blocked
   name, answers HTTP 400 with `code` `unsafe_uri`, and the request log shows no request to that path. The
   crawlee tier refused this read with HTTP 428 until 2026-10-28, when its static path was made to surface
   the refused redirect instead of escalating to an intervention window.
5. A read of the fake site article with `tier` `4a-patchright` answers HTTP 200 with `mode`
   `4a-patchright`, and with `tier` `4b-camoufox` answers HTTP 200 with `mode` `4b-camoufox`.
6. A read of the JavaScript-only page with no `tier` answers HTTP 200 with its canary sentence and a
   browser tier as `mode`. Redis then holds `tier_memory:e2e-fake-site` with that tier and a TTL no
   larger than `TIER_MEMORY_TTL_SECONDS`, and a second read of the same page under a new query string
   (so the read cache cannot answer) answers with the same `mode`. Tier memory is deleted right
   before the first read, so that read climbs the full ladder by construction instead of starting
   from a tier steps 3 or 5 remembered on the same registrable domain. The mechanism-stable
   property the log then shows is per-read, not an absolute count: the first read issues at least
   three full non-conditional fetches (both static tiers fetch and fail, then at least one browser
   tier serves), and the second read adds exactly one full non-conditional fetch (the remembered
   tier answers alone, with no read-cache hit on either read).

The removed `3-flaresolverr` tier and the `/ready` probe without FlareSolverr are not steps of this spec:
the unit tests of tasks 3.1 and 3.2 prove both (owner answer 91.3 of 2026-10-08).

## Concurrency

Writes only `tier_memory:e2e-fake-site`, opens no NoVNC flow, safe beside every spec that does not read
the fake site's JavaScript-only page.

## Prerequisites

Check Bruno CLI is installed.

```bash
bru --version
```

Expect a version string.

Check the ascend-web-hunter server is reachable.

```bash
curl -fsS http://localhost:7021/health
```

Expect HTTP 200 with `status` `ok`, `service` `ascend-web-hunter` and a non-empty `version`.

Check the fake site is reachable from the host.

```bash
curl -fsS http://127.0.0.1:7031/__requests
```

Expect a request list (empty on a fresh start; the reset step below empties it anyway).

Check Redis is reachable for the tier-memory reset and assertions. The container must be the one the service's
`REDIS_URL` names; on this stack that is `e2e-redis-sidecar`, because containers here reach the host through a
sidecar. Substitute the container your own `REDIS_URL` names if it differs.

```bash
docker exec e2e-redis-sidecar redis-cli PING
```

Expect `PONG`.

## Reset state

Delete the tier memory this spec's domain may hold from a previous run. The key is
`tier_memory:<registrable domain>` and the domain here is `e2e-fake-site`.

```bash
docker exec e2e-redis-sidecar redis-cli DEL "tier_memory:e2e-fake-site"
```

Expect an integer reply (`1` when a previous run left the key, `0` on a fresh start).

Empty the fake site request log.

```bash
curl -fsS -X POST http://127.0.0.1:7031/__reset
```

Expect `{"reset":true}`.

## Run

Move into the Bruno collection root first.

```bash
cd docs/api/request/AscendAI
```

The Bruno requests below live in `web-hunter/testing/tier-ladder/` (added by task 7.3 of
`enhance-web-search-tier-ladder`).

Step 1 - blocked article per tier. Send one request per tier and wait for HTTP 400 before continuing;
the tier travels in the `--env-var`.

```bash
bru run "web-hunter/testing/tier-ladder/private-target-per-tier.yml" --env ascend-local --env-var "tier=1-beautifulsoup"
```

```bash
bru run "web-hunter/testing/tier-ladder/private-target-per-tier.yml" --env ascend-local --env-var "tier=2-trafilatura"
```

```bash
bru run "web-hunter/testing/tier-ladder/private-target-per-tier.yml" --env ascend-local --env-var "tier=4-playwright_stealth"
```

```bash
bru run "web-hunter/testing/tier-ladder/private-target-per-tier.yml" --env ascend-local --env-var "tier=4a-patchright"
```

```bash
bru run "web-hunter/testing/tier-ladder/private-target-per-tier.yml" --env ascend-local --env-var "tier=4b-camoufox"
```

```bash
bru run "web-hunter/testing/tier-ladder/private-target-per-tier.yml" --env ascend-local --env-var "tier=5-crawlee_adaptive"
```

Step 1b - MCP refusal for `4a-patchright`. Send the MCP `initialize` handshake first. Expect HTTP 200
with no `Mcp-Session-Id` response header (the service is stateless; verified by full header dump).

**PowerShell:**

```powershell
curl.exe -fsS -i -X POST http://localhost:7021/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"e2e","version":"0.1.0"}}}'
```

**Unix:**

```bash
curl -fsS -i -X POST http://localhost:7021/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"e2e","version":"0.1.0"}}}'
```

Then send the `tools/call` with a dummy session ID injected:

```bash
bru run "web-hunter/testing/tier-ladder/mcp-private-target.yml" --env ascend-local --env-var "mcp_session_id=00000000000000000000000000000000"
```

Step 2 - redirect to the blocked name, per tier of step 1.

```bash
bru run "web-hunter/testing/tier-ladder/redirect-to-private-per-tier.yml" --env ascend-local --env-var "tier=1-beautifulsoup"
```

```bash
bru run "web-hunter/testing/tier-ladder/redirect-to-private-per-tier.yml" --env ascend-local --env-var "tier=2-trafilatura"
```

```bash
bru run "web-hunter/testing/tier-ladder/redirect-to-private-per-tier.yml" --env ascend-local --env-var "tier=4-playwright_stealth"
```

```bash
bru run "web-hunter/testing/tier-ladder/redirect-to-private-per-tier.yml" --env ascend-local --env-var "tier=4a-patchright"
```

```bash
bru run "web-hunter/testing/tier-ladder/redirect-to-private-per-tier.yml" --env ascend-local --env-var "tier=4b-camoufox"
```

```bash
bru run "web-hunter/testing/tier-ladder/redirect-to-private-per-tier.yml" --env ascend-local --env-var "tier=5-crawlee_adaptive"
```

Step 3 - image from the blocked name, per browser tier.

```bash
bru run "web-hunter/testing/tier-ladder/private-subresource-per-tier.yml" --env ascend-local --env-var "tier=4-playwright_stealth"
```

```bash
bru run "web-hunter/testing/tier-ladder/private-subresource-per-tier.yml" --env ascend-local --env-var "tier=4a-patchright"
```

```bash
bru run "web-hunter/testing/tier-ladder/private-subresource-per-tier.yml" --env ascend-local --env-var "tier=4b-camoufox"
```

```bash
bru run "web-hunter/testing/tier-ladder/private-subresource-per-tier.yml" --env ascend-local --env-var "tier=5-crawlee_adaptive"
```

Step 4 - script navigation to the blocked name, per browser tier.

```bash
bru run "web-hunter/testing/tier-ladder/script-navigation-per-tier.yml" --env ascend-local --env-var "tier=4-playwright_stealth"
```

```bash
bru run "web-hunter/testing/tier-ladder/script-navigation-per-tier.yml" --env ascend-local --env-var "tier=4a-patchright"
```

```bash
bru run "web-hunter/testing/tier-ladder/script-navigation-per-tier.yml" --env ascend-local --env-var "tier=4b-camoufox"
```

```bash
bru run "web-hunter/testing/tier-ladder/script-navigation-per-tier.yml" --env ascend-local --env-var "tier=5-crawlee_adaptive"
```

Step 5 - patched tiers serve the article under their own names.

```bash
bru run "web-hunter/testing/tier-ladder/patched-tier-serves.yml" --env ascend-local --env-var "tier=4a-patchright"
```

```bash
bru run "web-hunter/testing/tier-ladder/patched-tier-serves.yml" --env ascend-local --env-var "tier=4b-camoufox"
```

Step 6 - JavaScript-only page with no `tier`, first read. Delete the tier memory steps 3 and 5
left on this domain first, so this read climbs the full ladder by construction instead of starting
from a remembered tier.

```bash
docker exec e2e-redis-sidecar redis-cli DEL "tier_memory:e2e-fake-site"
```

Expect an integer reply (`1` when steps 3 and 5 remembered their tier, `0` when those writes
failed).

Bruno's console output never prints the response body, so capture it to read back the serving `mode`.

**PowerShell:**

```powershell
bru run "web-hunter/testing/tier-ladder/tier-memory-first.yml" --env ascend-local -o "$env:TEMP\tier-memory-first-run.json" -f json
```

**Unix:**

```bash
bru run "web-hunter/testing/tier-ladder/tier-memory-first.yml" --env ascend-local -o "/tmp/tier-memory-first-run.json" -f json
```

Read back which tier served the first read.

**PowerShell:**

```powershell
(Get-Content "$env:TEMP\tier-memory-first-run.json" -Raw | ConvertFrom-Json)[0].results[0].response.data.mode
```

**Unix:**

```bash
"$(command -v python3 || command -v python)" -c "import json, sys; d = json.load(open(sys.argv[1])); print(d[0]['results'][0]['response']['data']['mode'])" /tmp/tier-memory-first-run.json
```

Snapshot how many `/js-only` fetches the first read issued. No earlier step fetches this page, so
the number below is the first read's alone; record it as `C1`.

```bash
curl -fsS http://127.0.0.1:7031/__requests | python3 -c "import json,sys; rs=json.load(sys.stdin)['requests']; print(sum(1 for r in rs if r['path']=='/js-only'))"
```

Expect at least `3`: both static tiers fetched and failed, then at least one browser tier served.

Step 6b - same page under a new query string, second read, captured the same way.

**PowerShell:**

```powershell
bru run "web-hunter/testing/tier-ladder/tier-memory-second.yml" --env ascend-local -o "$env:TEMP\tier-memory-second-run.json" -f json
```

**Unix:**

```bash
bru run "web-hunter/testing/tier-ladder/tier-memory-second.yml" --env ascend-local -o "/tmp/tier-memory-second-run.json" -f json
```

**PowerShell:**

```powershell
(Get-Content "$env:TEMP\tier-memory-second-run.json" -Raw | ConvertFrom-Json)[0].results[0].response.data.mode
```

**Unix:**

```bash
"$(command -v python3 || command -v python)" -c "import json, sys; d = json.load(open(sys.argv[1])); print(d[0]['results'][0]['response']['data']['mode'])" /tmp/tier-memory-second-run.json
```

## Expected

- **Step 1:** HTTP 400 for each of the six tiers. Each body is the problem body with `code`
  `unsafe_uri`. The request log is then empty, so every tier refused before fetching:

  ```bash
  curl -fsS http://127.0.0.1:7031/__requests | python3 -c "import json,sys; rs=json.load(sys.stdin)['requests']; print(len(rs))"
  ```

  Expect `0`.

- **Step 1b:** the handshake returns HTTP 200 with no `Mcp-Session-Id` response header. The
  `tools/call` returns HTTP 200 with a JSON-RPC `result` carrying `isError: true` and a text entry
  starting with `unsafe_uri: `.
- **Step 2:** HTTP 400 with `code` `unsafe_uri` for each of the six tiers. The request log then holds
  only the allowed redirect page, one entry per run, and no request to the private path:

  ```bash
  curl -fsS http://127.0.0.1:7031/__requests | python3 -c "import json,sys; rs=json.load(sys.stdin)['requests']; print(sorted(set(r['path'] for r in rs)))"
  ```

  Expect `['/redirect-blocked']`.
- **Step 3:** HTTP 200 for each of the four browser tiers. Each body has `status` `success` and a
  content field holding the page's canary sentence (`"QUARRY-THRUSH"`). The request log shows no
  request to the image path:

  ```bash
  curl -fsS http://127.0.0.1:7031/__requests | python3 -c "import json,sys; rs=json.load(sys.stdin)['requests']; print([r['path'] for r in rs if r['path']=='/canary.png'])"
  ```

  Expect `[]`.
- **Step 4:** HTTP 400 with `code` `unsafe_uri` for every browser tier including `5-crawlee_adaptive`. The
  request log still shows no request to the private article path:

  ```bash
  curl -fsS http://127.0.0.1:7031/__requests | python3 -c "import json,sys; rs=json.load(sys.stdin)['requests']; print(sum(1 for r in rs if r['path']=='/article'))"
  ```

  Expect `0`.
- **Step 5:** HTTP 200 with `mode` `4a-patchright` for the first call, HTTP 200 with `mode`
  `4b-camoufox` for the second call. Both bodies hold the article's canary sentence
  (`"QUARRY-THRUSH"`).
- **Step 6:** the first read answers HTTP 200 with `mode` naming one of `4-playwright_stealth`,
  `4a-patchright`, `4b-camoufox` or `5-crawlee_adaptive`, and a content field holding the canary
  sentence (`"NIGHT-HERON"`). Redis then holds that same tier under `tier_memory:e2e-fake-site`:

  ```bash
  docker exec e2e-redis-sidecar redis-cli GET "tier_memory:e2e-fake-site"
  ```

  Expect the tier the Run step printed for the first read. Its TTL is no larger than the service's
  `TIER_MEMORY_TTL_SECONDS` (default `86400`):

  ```bash
  docker exec e2e-redis-sidecar redis-cli TTL "tier_memory:e2e-fake-site"
  ```

  Expect a non-negative integer no larger than that setting. The second read answers HTTP 200 with the
  same `mode` as the first read. The second read adds exactly one request to the JavaScript-only
  page, and every request to that page across both reads is a full non-conditional fetch, so each
  read re-ran the chain instead of serving a cached page (the first read climbs the full ladder
  from the deletion above; the remembered tier answers the second read with one fetch):

  ```bash
  export C1=<number recorded after the first read>; curl -fsS http://127.0.0.1:7031/__requests | python3 -c "import json,os,sys; rs=json.load(sys.stdin)['requests']; js=[r for r in rs if r['path']=='/js-only']; print(len(js)-int(os.environ['C1']), all(r['if_none_match'] is None and r['if_modified_since'] is None and r['bytes_sent']>0 for r in js))"
  ```

  Expect `1 True`.

Every assertion above is an HTTP status, a response body, a Redis key or the fake site request log.

## Fixtures

None checked in. The fake site pages `/article` (QUARRY-THRUSH survey canary), `/redirect-blocked`,
`/private-image`, `/script-nav` and `/js-only` (NIGHT-HERON ledger canary) carry the canaries, all
indexed in [fixtures/README.md](../fixtures/README.md).
