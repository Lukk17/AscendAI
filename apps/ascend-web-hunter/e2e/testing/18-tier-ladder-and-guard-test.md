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
   with `code` `unsafe_uri`: the page answers a redirect to the article under the blocked name. The fake
   site request log is emptied before each tier's read, and after each read it holds exactly one
   `/redirect-blocked` entry and no request to the private path.
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
   browser tier as `mode`. A second read of the same page under a new query string (so the read cache
   cannot answer) answers with the same `mode`. After the second read, Redis holds
   `tier_memory:e2e-fake-site` with that tier and a TTL greater than 0 and no larger than
   `TIER_MEMORY_TTL_SECONDS`. Tier memory is deleted right
   before the first read as a guard, so that read climbs the full ladder by construction. Steps 3
   and 5 name an explicit tier, and such a read never writes tier memory, so the key is normally
   already absent at that point. The mechanism-stable
   property the log then shows is per-read, not an absolute count: the first read issues at least
   three full non-conditional fetches (both static tiers fetch and fail, then at least one browser
   tier serves), and the second read adds exactly one full non-conditional fetch (the remembered
   tier answers alone, with no read-cache hit on either read).

The removed `3-flaresolverr` tier and the `/ready` probe without FlareSolverr are not steps of this spec:
the unit tests of tasks 3.1 and 3.2 prove both (owner answer 91.3 of 2026-10-08).

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

Check the fake site is reachable from the host.

```bash
curl -fsS http://127.0.0.1:7031/__requests
```

Expect a request list (empty on a fresh start; the reset step below empties it anyway).

Check Redis is reachable for the tier-memory reset and assertions. On the main stack the service's session store is
the host's `redis` container. When the scraping file runs alone with the redis profile, the store is the container
`ascend-scrapper-redis`, so every `docker exec redis` command in this spec targets that container instead, per the
suite README and [docs/E2E_RUN_SCENARIOS.md](../../../../docs/E2E_RUN_SCENARIOS.md).

```bash
docker exec redis redis-cli PING
```

Expect `PONG`.

## Reset state

Delete the tier memory this spec's domain may hold from a previous run. The key is
`tier_memory:<registrable domain>` and the domain here is `e2e-fake-site`.

```bash
docker exec redis redis-cli DEL "tier_memory:e2e-fake-site"
```

Expect an integer reply (`1` when a previous run left the key, `0` on a fresh start).

Empty the service's in-process read cache for the fake site. It keeps a successful read for
`READ_CACHE_TTL_SECONDS` (300 s) and Redis cannot reach it, so within 300 s of an earlier run a read of
steps 3, 5 or 6 would be answered from the cache, fetch nothing, and leave the request log and the tier
memory checks with nothing to see. The call also deletes `session:e2e-fake-site:default` if one exists.

PowerShell:

```powershell
curl.exe -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/clear -H "Content-Type: application/json" -d '{"url":"http://e2e-fake-site:7031/","profile":"default"}'
```

Unix:

```bash
curl -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/clear -H "Content-Type: application/json" -d '{"url":"http://e2e-fake-site:7031/","profile":"default"}'
```

Expect HTTP 200 with `status` `"cleared"`. `cleared_cache_entries` is the number of cached reads removed.

Empty the fake site request log.

```bash
curl -fsS -X POST http://127.0.0.1:7031/__reset
```

Expect `{"reset":true}`.

## Run

Move into the Bruno collection root first, from the repository root.

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
curl.exe -fsS -i -X POST http://127.0.0.1:7021/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"e2e","version":"0.1.0"}}}'
```

**Unix:**

```bash
curl -fsS -i -X POST http://127.0.0.1:7021/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"e2e","version":"0.1.0"}}}'
```

Then send the `tools/call` with a dummy session ID injected:

```bash
bru run "web-hunter/testing/tier-ladder/mcp-private-target.yml" --env ascend-local --env-var "mcp_session_id=00000000000000000000000000000000"
```

Step 2 - redirect to the blocked name, per tier of step 1. Run the Step 1 request log check under
Expected before the first reset below, because each reset empties the log. For each tier, empty the
fake site request log, send the read, then count the log entries. Expect `{"reset":true}` from each
reset and `1 ['/redirect-blocked']` from each count.

Tier `1-beautifulsoup`.

```bash
curl -fsS -X POST http://127.0.0.1:7031/__reset
```

```bash
bru run "web-hunter/testing/tier-ladder/redirect-to-private-per-tier.yml" --env ascend-local --env-var "tier=1-beautifulsoup"
```

```bash
curl -fsS http://127.0.0.1:7031/__requests | python3 -c "import json,sys; rs=json.load(sys.stdin)['requests']; print(sum(1 for r in rs if r['path']=='/redirect-blocked'), sorted(set(r['path'] for r in rs)))"
```

Tier `2-trafilatura`.

```bash
curl -fsS -X POST http://127.0.0.1:7031/__reset
```

```bash
bru run "web-hunter/testing/tier-ladder/redirect-to-private-per-tier.yml" --env ascend-local --env-var "tier=2-trafilatura"
```

```bash
curl -fsS http://127.0.0.1:7031/__requests | python3 -c "import json,sys; rs=json.load(sys.stdin)['requests']; print(sum(1 for r in rs if r['path']=='/redirect-blocked'), sorted(set(r['path'] for r in rs)))"
```

Tier `4-playwright_stealth`.

```bash
curl -fsS -X POST http://127.0.0.1:7031/__reset
```

```bash
bru run "web-hunter/testing/tier-ladder/redirect-to-private-per-tier.yml" --env ascend-local --env-var "tier=4-playwright_stealth"
```

```bash
curl -fsS http://127.0.0.1:7031/__requests | python3 -c "import json,sys; rs=json.load(sys.stdin)['requests']; print(sum(1 for r in rs if r['path']=='/redirect-blocked'), sorted(set(r['path'] for r in rs)))"
```

Tier `4a-patchright`.

```bash
curl -fsS -X POST http://127.0.0.1:7031/__reset
```

```bash
bru run "web-hunter/testing/tier-ladder/redirect-to-private-per-tier.yml" --env ascend-local --env-var "tier=4a-patchright"
```

```bash
curl -fsS http://127.0.0.1:7031/__requests | python3 -c "import json,sys; rs=json.load(sys.stdin)['requests']; print(sum(1 for r in rs if r['path']=='/redirect-blocked'), sorted(set(r['path'] for r in rs)))"
```

Tier `4b-camoufox`.

```bash
curl -fsS -X POST http://127.0.0.1:7031/__reset
```

```bash
bru run "web-hunter/testing/tier-ladder/redirect-to-private-per-tier.yml" --env ascend-local --env-var "tier=4b-camoufox"
```

```bash
curl -fsS http://127.0.0.1:7031/__requests | python3 -c "import json,sys; rs=json.load(sys.stdin)['requests']; print(sum(1 for r in rs if r['path']=='/redirect-blocked'), sorted(set(r['path'] for r in rs)))"
```

Tier `5-crawlee_adaptive`.

```bash
curl -fsS -X POST http://127.0.0.1:7031/__reset
```

```bash
bru run "web-hunter/testing/tier-ladder/redirect-to-private-per-tier.yml" --env ascend-local --env-var "tier=5-crawlee_adaptive"
```

```bash
curl -fsS http://127.0.0.1:7031/__requests | python3 -c "import json,sys; rs=json.load(sys.stdin)['requests']; print(sum(1 for r in rs if r['path']=='/redirect-blocked'), sorted(set(r['path'] for r in rs)))"
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

Step 5 - patched tiers serve the article under their own names. The request file can only check that `mode` is
one of the two patched tiers, because Bruno 4.2.1 does not fill `--env-var` values inside test scripts. So the
runner captures each answer body and checks there that `mode` equals the requested tier. Bruno's console output
never prints the response body, so write each report into a new private directory, never a fixed path under
`/tmp`, so two runs never share a file. Create it once, in the same shell the rest of steps 5 and 6 runs in.

Steps 5, 6 and 6b assume that one shell keeps the variable `E2E_OUT` from the command below until the
directory is removed at the end of step 6b. Every later command of these steps that names `E2E_OUT` reads it
from that shell.

**PowerShell:**

```powershell
$E2E_OUT = (New-Item -ItemType Directory -Path (Join-Path ([IO.Path]::GetTempPath()) ([IO.Path]::GetRandomFileName()))).FullName
```

**Unix:**

```bash
E2E_OUT="$(mktemp -d)"
```

A runner whose shell does not keep variables from one command to the next (each command starts a new shell)
writes the path to a file right after it creates the directory, in the same command, and reads it back at the
start of every later command that names `E2E_OUT`. The file sits next to the run record in
`apps/ascend-web-hunter/e2e/testing/runs/`, which git ignores, and carries the run record's own timestamp,
so two runs never share it. The paths below are relative to the Bruno collection root. Replace
`<UTC-timestamp>` with the run record's timestamp, followed by its `-rerun<N>` suffix when it has one. Create
the directory and write its path:

PowerShell:

```powershell
$E2E_OUT = (New-Item -ItemType Directory -Path (Join-Path ([IO.Path]::GetTempPath()) ([IO.Path]::GetRandomFileName()))).FullName; Set-Content -Path "..\..\..\..\apps\ascend-web-hunter\e2e\testing\runs\<UTC-timestamp>_18-tier-ladder-and-guard-e2e-out.txt" -Value $E2E_OUT
```

Unix:

```bash
E2E_OUT="$(mktemp -d)" && printf '%s\n' "$E2E_OUT" > "../../../../apps/ascend-web-hunter/e2e/testing/runs/<UTC-timestamp>_18-tier-ladder-and-guard-e2e-out.txt"
```

Then put the read back in front of each later command of steps 5, 6 and 6b that names `E2E_OUT`, the
`Remove-Item` and `rm -rf` of step 6b included, in the same command: joined with `;` in PowerShell and with
`&&` in Unix.

PowerShell:

```powershell
$E2E_OUT = (Get-Content -Path "..\..\..\..\apps\ascend-web-hunter\e2e\testing\runs\<UTC-timestamp>_18-tier-ladder-and-guard-e2e-out.txt" -Raw).Trim()
```

Unix:

```bash
E2E_OUT="$(cat "../../../../apps/ascend-web-hunter/e2e/testing/runs/<UTC-timestamp>_18-tier-ladder-and-guard-e2e-out.txt")"
```

The Post-run cleanup removes this file.

**PowerShell:**

```powershell
bru run "web-hunter/testing/tier-ladder/patched-tier-serves.yml" --env ascend-local --env-var "tier=4a-patchright" -o "$E2E_OUT\patched-4a-patchright-run.json" -f json
```

**Unix:**

```bash
bru run "web-hunter/testing/tier-ladder/patched-tier-serves.yml" --env ascend-local --env-var "tier=4a-patchright" -o "$E2E_OUT/patched-4a-patchright-run.json" -f json
```

Read back which tier served it. Expect exactly `4a-patchright`.

**PowerShell:**

```powershell
(Get-Content "$E2E_OUT\patched-4a-patchright-run.json" -Raw | ConvertFrom-Json)[0].results[0].response.data.mode
```

**Unix:**

```bash
"$(command -v python3 || command -v python)" -c "import json, sys; d = json.load(open(sys.argv[1])); print(d[0]['results'][0]['response']['data']['mode'])" "$E2E_OUT/patched-4a-patchright-run.json"
```

**PowerShell:**

```powershell
bru run "web-hunter/testing/tier-ladder/patched-tier-serves.yml" --env ascend-local --env-var "tier=4b-camoufox" -o "$E2E_OUT\patched-4b-camoufox-run.json" -f json
```

**Unix:**

```bash
bru run "web-hunter/testing/tier-ladder/patched-tier-serves.yml" --env ascend-local --env-var "tier=4b-camoufox" -o "$E2E_OUT/patched-4b-camoufox-run.json" -f json
```

Read back which tier served it. Expect exactly `4b-camoufox`.

**PowerShell:**

```powershell
(Get-Content "$E2E_OUT\patched-4b-camoufox-run.json" -Raw | ConvertFrom-Json)[0].results[0].response.data.mode
```

**Unix:**

```bash
"$(command -v python3 || command -v python)" -c "import json, sys; d = json.load(open(sys.argv[1])); print(d[0]['results'][0]['response']['data']['mode'])" "$E2E_OUT/patched-4b-camoufox-run.json"
```

Step 6 - JavaScript-only page with no `tier`, first read. Delete any tier memory on this domain
first as a guard, so this read climbs the full ladder by construction instead of starting from a
remembered tier.

```bash
docker exec redis redis-cli DEL "tier_memory:e2e-fake-site"
```

Expect `0`. Steps 3 and 5 name an explicit tier, and by the owner's decision a read that names its
tier never writes tier memory, so no earlier step of this run leaves the key behind.

Capture the response body the same way as step 5, into the same `E2E_OUT` directory, to read back the serving
`mode`.

**PowerShell:**

```powershell
bru run "web-hunter/testing/tier-ladder/tier-memory-first.yml" --env ascend-local -o "$E2E_OUT\tier-memory-first-run.json" -f json
```

**Unix:**

```bash
bru run "web-hunter/testing/tier-ladder/tier-memory-first.yml" --env ascend-local -o "$E2E_OUT/tier-memory-first-run.json" -f json
```

Read back which tier served the first read.

**PowerShell:**

```powershell
(Get-Content "$E2E_OUT\tier-memory-first-run.json" -Raw | ConvertFrom-Json)[0].results[0].response.data.mode
```

**Unix:**

```bash
"$(command -v python3 || command -v python)" -c "import json, sys; d = json.load(open(sys.argv[1])); print(d[0]['results'][0]['response']['data']['mode'])" "$E2E_OUT/tier-memory-first-run.json"
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
bru run "web-hunter/testing/tier-ladder/tier-memory-second.yml" --env ascend-local -o "$E2E_OUT\tier-memory-second-run.json" -f json
```

**Unix:**

```bash
bru run "web-hunter/testing/tier-ladder/tier-memory-second.yml" --env ascend-local -o "$E2E_OUT/tier-memory-second-run.json" -f json
```

**PowerShell:**

```powershell
(Get-Content "$E2E_OUT\tier-memory-second-run.json" -Raw | ConvertFrom-Json)[0].results[0].response.data.mode
```

**Unix:**

```bash
"$(command -v python3 || command -v python)" -c "import json, sys; d = json.load(open(sys.argv[1])); print(d[0]['results'][0]['response']['data']['mode'])" "$E2E_OUT/tier-memory-second-run.json"
```

Remove the report directory once both modes are recorded. Nothing after this point reads it.

**PowerShell:**

```powershell
Remove-Item -Recurse -Force $E2E_OUT
```

**Unix:**

```bash
rm -rf "$E2E_OUT"
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
- **Step 2:** HTTP 400 with `code` `unsafe_uri` for each of the six tiers. After each tier's read the
  request log, emptied right before that read, holds exactly one `/redirect-blocked` entry and no
  request to the private path:

  ```bash
  curl -fsS http://127.0.0.1:7031/__requests | python3 -c "import json,sys; rs=json.load(sys.stdin)['requests']; print(sum(1 for r in rs if r['path']=='/redirect-blocked'), sorted(set(r['path'] for r in rs)))"
  ```

  Expect `1 ['/redirect-blocked']` for each of the six tiers.
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
  `4b-camoufox` for the second call, each read back from the captured answer body, not from the request
  file's own test, which accepts either patched tier. Both bodies hold the article's canary sentence
  (`"QUARRY-THRUSH"`).
- **Step 6:** the first read answers HTTP 200 with `mode` naming one of `4-playwright_stealth`,
  `4a-patchright`, `4b-camoufox` or `5-crawlee_adaptive`, and a content field holding the canary
  sentence (`"NIGHT-HERON"`). Redis then holds that same tier under `tier_memory:e2e-fake-site`. Read the
  key and its TTL after the second read of step 6b, not between the two reads. The second read writes the
  key again, so its TTL starts over at that moment:

  ```bash
  docker exec redis redis-cli GET "tier_memory:e2e-fake-site"
  ```

  Expect the tier the Run step printed for the first read. Its TTL, read after the second read, is greater
  than `0` and no larger than the service's `TIER_MEMORY_TTL_SECONDS` (default `86400`):

  ```bash
  docker exec redis redis-cli TTL "tier_memory:e2e-fake-site"
  ```

  Expect an integer greater than `0` and no larger than that setting. `-1` (no expiry) and `-2` (no key)
  both fail. The second read answers HTTP 200 with the same `mode` as the first read. The second read
  adds exactly one request to the JavaScript-only
  page, and every request to that page across both reads is a full non-conditional fetch, so each
  read re-ran the chain instead of serving a cached page (the first read climbs the full ladder
  from the deletion above; the remembered tier answers the second read with one fetch):

  ```bash
  export C1=<number recorded after the first read>; curl -fsS http://127.0.0.1:7031/__requests | python3 -c "import json,os,sys; rs=json.load(sys.stdin)['requests']; js=[r for r in rs if r['path']=='/js-only']; print(len(js)-int(os.environ['C1']), all(r['if_none_match'] is None and r['if_modified_since'] is None and r['bytes_sent']>0 for r in js))"
  ```

  Expect `1 True`.

Every assertion above is an HTTP status, a response body, a Redis key or the fake site request log.

## Post-run cleanup

After the Expected checks have read them, remove what this run leaves behind: `tier_memory:e2e-fake-site`
(written by step 6 with a 24 hour TTL), the fake site request log, and up to 300 seconds of read cache for
the fake site. Otherwise a later spec that reads the fake site starts from a remembered tier or a cached
answer.

Delete the tier memory.

```bash
docker exec redis redis-cli DEL "tier_memory:e2e-fake-site"
```

Expect `1` after a full run (`0` when the run stopped before step 6 wrote the key).

Empty the service's read cache for the fake site, the same call as Reset state.

PowerShell:

```powershell
curl.exe -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/clear -H "Content-Type: application/json" -d '{"url":"http://e2e-fake-site:7031/","profile":"default"}'
```

Unix:

```bash
curl -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/clear -H "Content-Type: application/json" -d '{"url":"http://e2e-fake-site:7031/","profile":"default"}'
```

Expect HTTP 200 with `status` `"cleared"`.

Empty the fake site request log.

PowerShell:

```powershell
curl.exe -fsS -X POST http://127.0.0.1:7031/__reset
```

Unix:

```bash
curl -fsS -X POST http://127.0.0.1:7031/__reset
```

Expect `{"reset":true}`.

Only when step 5 used the file fallback for `E2E_OUT`: remove the file that holds the path, from the Bruno
collection root as in Run. The report directory itself was already removed at the end of step 6b.

PowerShell:

```powershell
Remove-Item -Force "..\..\..\..\apps\ascend-web-hunter\e2e\testing\runs\<UTC-timestamp>_18-tier-ladder-and-guard-e2e-out.txt"
```

Unix:

```bash
rm -f "../../../../apps/ascend-web-hunter/e2e/testing/runs/<UTC-timestamp>_18-tier-ladder-and-guard-e2e-out.txt"
```

Expect no output.

## Fixtures

None checked in. The fake site pages `/article` (QUARRY-THRUSH survey canary), `/redirect-blocked`,
`/private-image`, `/script-nav` and `/js-only` (NIGHT-HERON ledger canary) carry the canaries, all
indexed in [fixtures/README.md](../fixtures/README.md).

## Concurrency

Writes `tier_memory:e2e-fake-site` and the fake site request log (its reset, every step 2 read and its
Post-run cleanup empty the log with `POST /__reset`), and empties the service's read cache for the fake site
domain `e2e-fake-site` in its reset and again in its Post-run cleanup, which also deletes the tier memory key.
Opens no NoVNC flow. Not beside a spec that asserts on the fake site request log (13, 14, 15, 16) or reads the
fake site's JavaScript-only page, and not beside a spec whose fake site reads would lose their cached answer
mid-run. Not beside spec 13 ([13-structured-extraction-test.md](13-structured-extraction-test.md)) or spec 19
([19-challenge-verdicts-test.md](19-challenge-verdicts-test.md)) either, whose reads write the same
`tier_memory:e2e-fake-site` key.

- Serial: false
