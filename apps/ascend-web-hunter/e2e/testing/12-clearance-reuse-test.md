# Cloudflare clearance reuse: e2e test

## What this verifies

That a Cloudflare clearance the reader stored on one read is reused on the next read of the same site. Fully
automated, against the real `https://www.scrapingcourse.com/cloudflare-challenge` page (no mocks, no human).

1. Cold read. A read of `https://www.scrapingcourse.com/cloudflare-challenge` with no stored session answers HTTP
   200, `status="success"` and a content-carrying field of at least 50 characters. The curl tier is blocked by the
   Cloudflare challenge, FlareSolverr solves it, and the reader stores the site's session under
   `session:scrapingcourse.com:default` with the `cf_clearance` cookie in its `waf` entry (measured on 2026-09-10:
   HTTP 200 through `3-flaresolverr` in 25.2 seconds). The run record captures the `mode` and the duration of this
   call.
2. Capture. Between the two calls, `session:scrapingcourse.com:default` exists and its `waf` entry holds a cookie
   named `cf_clearance`.
3. Warm read. A read of `https://www.scrapingcourse.com/cloudflare-challenge?reuse=1`, the same page under a
   different address, answers HTTP 200, `status="success"` and a content-carrying field of at least 50 characters,
   with no 428, in less time than Call 1 took. The query string is what makes the call meaningful: the reader keeps
   a five-minute in-memory read cache keyed by address (`READ_CACHE_TTL_SECONDS`, 300 s), and a repeat of Call 1's
   exact address is answered from that cache in a fraction of a second without touching the stored session, which
   proves nothing about reuse. A different address on the same site misses the cache and has to go through the site
   again, so a success there that is faster than the cold read is the stored clearance doing its job.

A 428 on Call 2 is a FAIL. It is register defect A61 in
[../../../../docs/DEFECT_REGISTER.md](../../../../docs/DEFECT_REGISTER.md) until its fix lands: a stored session
routes the read straight to the browser tiers, whose fingerprint is not the one the `cf_clearance` cookie was
issued to, so Cloudflare challenges it again and the read ends at the human window. Record the response body
verbatim in the run record so the register entry can cite it.

Why this site and not the democaptcha form spec 11 uses: the democaptcha form renders its hCaptcha widget on every
load regardless of cookies, so a second read of it always carries a block signature and can never show reuse
(register A60). A Cloudflare-protected page serves plain content once the browser holds its clearance, so the wall
disappears when the clearance is reused, and the whole test runs with nobody at the keyboard.

### Contract (how the service signals each verdict)

- success: HTTP `200`, body `status="success"`, non-empty content, `mode` naming the tier that served it.
- intervention: HTTP `428 Precondition Required`, body `status="human_intervention_required"` and a non-empty
  `vnc_url`. Never a valid verdict on either call of this spec. On Call 2 it is the A61 failure. On Call 1 it means
  FlareSolverr did not solve the challenge, so re-check the FlareSolverr prerequisite and record the body before
  deciding the verdict, since the reuse property was never reached.
- busy, not a verdict on its own: HTTP `409`, body `status="novnc_busy"` with a `holder_url`, and a `Retry-After`
  header, meaning the read escalated past every automated tier and found the single shared browser held by an
  earlier intervention. For this spec that carries the same meaning as a 428 on the same call, since the read did
  not succeed through an automated tier. Record the `holder_url` in the run record.

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

Expect HTTP 200 with `{"status":"ok"}`.

Check FlareSolverr is reachable (Call 1 needs it to solve the Cloudflare challenge and store the clearance).

```bash
curl -fsS http://localhost:8191/
```

Expect HTTP 200 with a JSON body announcing FlareSolverr.

Check Redis is reachable from the host's Docker context (the reset and the capture check use the session key).

```bash
docker exec redis redis-cli PING
```

Expect `PONG`.

No credentials are needed.

## Reset state

Delete the scrapingcourse.com session so Call 1 starts cold and stores a fresh clearance. The command is identical
in PowerShell and Unix shells. When the scraping file runs alone with the redis profile, the session store is the
container `ascend-scrapper-redis`, so every `docker exec redis` command in this spec targets that container
instead, per the suite README.

```bash
docker exec redis redis-cli DEL "session:scrapingcourse.com:default"
```

Expect `0` or `1`. Then confirm the key is gone.

```bash
docker exec redis redis-cli EXISTS "session:scrapingcourse.com:default"
```

Expect `0`.

Empty the reader's in-process read cache for the domain. Spec 6 reads Call 1's exact address, and this spec runs
after it, so within `READ_CACHE_TTL_SECONDS` (300 s) of that read Call 1 would be answered from the cache without
going through FlareSolverr and would store no session, failing the capture check for a reason that is not the
product. The Redis delete above cannot reach that cache. The session clear endpoint drops both the Redis record and
the cached reads for the domain.

PowerShell:

```powershell
curl.exe -fsS -X POST http://localhost:7021/api/v2/web/session/clear -H "Content-Type: application/json" -d '{"url":"https://www.scrapingcourse.com/cloudflare-challenge","profile":"default"}'
```

Unix:

```bash
curl -fsS -X POST http://localhost:7021/api/v2/web/session/clear -H "Content-Type: application/json" -d '{"url":"https://www.scrapingcourse.com/cloudflare-challenge","profile":"default"}'
```

Expect HTTP 200 with `status="cleared"`. `existed` is `false` after the delete above, and a non-zero
`cleared_cache_entries` is the cache being emptied, not a failure.

## Run

Move into the Bruno collection root first.

```bash
cd docs/api/request/AscendAI
```

1. Call 1, cold. Read the page with no stored session and write Bruno's JSON report so the served `mode` and the
   response time can be read back. Wait for HTTP 200 before continuing.

PowerShell:

```powershell
bru run "web-hunter/testing/clearance-cold.yml" --env ascend-local -o "$env:TEMP\clearance-cold-run.json" -f json
```

Unix:

```bash
bru run "web-hunter/testing/clearance-cold.yml" --env ascend-local -o "/tmp/clearance-cold-run.json" -f json
```

2. Read back Call 1's `mode` and `responseTime` (milliseconds) and record both in the run record.

PowerShell:

```powershell
(Get-Content "$env:TEMP\clearance-cold-run.json" -Raw | ConvertFrom-Json)[0].results[0].response | Select-Object @{n="mode";e={$_.data.mode}}, responseTime
```

Unix:

```bash
python3 -c "import json; r = json.load(open('/tmp/clearance-cold-run.json'))[0]['results'][0]['response']; print(r['data']['mode'], r['responseTime'])"
```

3. Capture check.

```bash
docker exec redis redis-cli GET "session:scrapingcourse.com:default"
```

Expect a JSON value whose `waf` entry contains a cookie named `cf_clearance`.

4. Call 2, warm. Read the same page under a different address, with no profile, so the read resolves to the
   `default` profile Call 1 stored under and misses the in-memory read cache.

PowerShell:

```powershell
bru run "web-hunter/testing/clearance-reuse.yml" --env ascend-local -o "$env:TEMP\clearance-reuse-run.json" -f json
```

Unix:

```bash
bru run "web-hunter/testing/clearance-reuse.yml" --env ascend-local -o "/tmp/clearance-reuse-run.json" -f json
```

5. Read back Call 2's `mode` and `responseTime` and record both in the run record.

PowerShell:

```powershell
(Get-Content "$env:TEMP\clearance-reuse-run.json" -Raw | ConvertFrom-Json)[0].results[0].response | Select-Object @{n="mode";e={$_.data.mode}}, responseTime
```

Unix:

```bash
python3 -c "import json; r = json.load(open('/tmp/clearance-reuse-run.json'))[0]['results'][0]['response']; print(r['data']['mode'], r['responseTime'])"
```

## Expected

- Call 1: HTTP `200`, `status="success"`, and one of `content`, `text` or `markdown` is a string of at least 50
  characters. The `mode` and the `responseTime` from step 2 are recorded in the run record (2026-09-10 measurement:
  `3-flaresolverr`, 25.2 seconds). A duration in the tens of seconds is normal for the FlareSolverr tier.
- Capture check: `session:scrapingcourse.com:default` exists and its `waf` entry carries a cookie named
  `cf_clearance`. On the 2026-09-10 read the `auth` entry also carried six site cookies, none of which are asserted.
- Call 2: HTTP `200`, `status="success"`, one of `content`, `text` or `markdown` is a string of at least 50
  characters, the body carries no `vnc_url`, and the `responseTime` from step 5 is smaller than Call 1's from step
  2. Both values go into the run record. No `428`. A `428` on Call 2 is a FAIL and is register defect A61 in
  [../../../../docs/DEFECT_REGISTER.md](../../../../docs/DEFECT_REGISTER.md) until its fix lands. Record the
  response body verbatim under Additional tasks I did.
- Clean up the record this test created, so the next run starts cold again. The command is identical in
  PowerShell and Unix shells.

  ```bash
  docker exec redis redis-cli DEL "session:scrapingcourse.com:default"
  ```

  ```bash
  docker exec redis redis-cli EXISTS "session:scrapingcourse.com:default"
  ```

  Expect `0`.

## Fixtures

None, and no secrets. The two URLs are hardcoded in the two Bruno requests.

## Concurrency

- Mutates: Redis, the ascend-web-hunter session store, key `session:scrapingcourse.com:default`, and the reader's
  in-process read cache for `scrapingcourse.com`. On the A61 failure path Call 2 also opens the single shared NoVNC
  browser for `NOVNC_TIMEOUT_SECONDS` (600 s by default).
- Conflicts with: test 6, which reads the same site and stores under the same session key, so a concurrent run
  would hand this spec a clearance it did not obtain or wipe the one it did. Tests 8 and 10, which compare or
  extend the `session:*` key scan, since this spec's key would appear in it. Test 7's reset flushes every
  `session:*` key and would wipe the capture between the two calls.
- Serial: false against tests 1, 2, 3, 4, 5 and 9. Runs after test 6. No human.
