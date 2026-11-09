# Cloudflare clearance reuse: e2e test

## What this verifies

That a Cloudflare clearance the reader stored on one read is reused on the next read of the same site. Fully
automated, against the real `https://www.scrapingcourse.com/cloudflare-challenge` page (no mocks, no human), except
for the human branch below, which runs only when a human is at the keyboard and Call 1 answers 428.

1. Cold read. A read of `https://www.scrapingcourse.com/cloudflare-challenge` with no stored session answers HTTP
   200, `status="success"` and a content-carrying field of at least 50 characters. The curl tier is blocked by the
   Cloudflare challenge, a browser tier solves it, and the reader stores the site's session under
   `session:scrapingcourse.com:default` with the `cf_clearance` cookie in its `waf` entry. The run record captures
   the `mode` and the duration of this call.
2. Capture. Between the two calls, `session:scrapingcourse.com:default` exists and its `waf` entry holds a cookie
   named `cf_clearance`.
3. Warm read. A read of `https://www.scrapingcourse.com/cloudflare-challenge?reuse=1`, the same page under a
   different address, answers HTTP 200, `status="success"` and a content-carrying field of at least 50 characters,
   with no 428, in less time than Call 1 took. The query string is what makes the call meaningful: the reader keeps
   a five-minute in-memory read cache keyed by address (`READ_CACHE_TTL_SECONDS`, 300 s), and a repeat of Call 1's
   exact address is answered from that cache in a fraction of a second without touching the stored session, which
   proves nothing about reuse. A different address on the same site misses the cache and has to go through the site
   again, so a success there that is faster than the cold read is the stored clearance doing its job.

When Call 1 is answered by the human-help tier (HTTP 428) or by the busy refusal (HTTP 409), the site has rated
this address and refused the automated tiers. With nobody at the keyboard the run then records an environment gate,
skips the capture check and Call 2, and passes without exercising reuse. A 428 on Call 2 is still a FAIL, because
there the cold read already succeeded and the stored clearance was expected to be reused.

Human branch. When a human is at the keyboard and Call 1 answers 428, the run does not stop at the environment gate.
The human passes the challenge in the window at the `vnc_url` of the 428 body, the runner waits until that window has
saved the session, and the run goes on with the capture check and Call 2 as written. A 428 on Call 2 is still a FAIL.
Call 2 compares its time against Call 1's, and in this branch Call 1 returned at once with the 428, so the time
comparison is not made and the rest of the Call 2 criteria apply unchanged. A 409 on Call 1 stays the environment gate.

A `cf_clearance` cookie saved while the page is still a wall is a FAIL of the capture check. Cloudflare can set that
cookie on its own while the page stays HTTP 403 "Just a moment", and such a cookie opens nothing, so the cookie alone
proves nothing. A NoVNC window saves only once its page verdict is accepted.

A 428 on Call 2 is a FAIL. It is register defect F54 in
[../../../../docs/DEFECT_REGISTER.md](../../../../docs/DEFECT_REGISTER.md) until its fix lands: a stored session
routes the read straight to the browser tiers, whose fingerprint is not the one the `cf_clearance` cookie was
issued to, so Cloudflare challenges it again and the read ends at the human window. Record the response body
verbatim in the run record so the register entry can cite it.

Why this site and not the democaptcha form spec 11 uses: the democaptcha form renders its hCaptcha widget on every
load regardless of cookies, so a second read of it always carries a block signature and can never show reuse
(register A60). A Cloudflare-protected page serves plain content once the browser holds its clearance, so the wall
disappears when the clearance is reused, and the test needs nobody at the keyboard unless Call 1 answers 428.

### Contract (how the service signals each verdict)

- success: HTTP `200`, body `status="success"`, non-empty content, `mode` naming the tier that served it.
- intervention: HTTP `428 Precondition Required`, body `code="human_intervention_required"` and a non-empty
  `vnc_url`. Never a valid verdict on Call 2, where it is the F54 failure. On Call 1 with nobody at the keyboard it is
  the environment gate described above: no automated tier solved the challenge, so record the body, skip the capture
  check and Call 2, and pass without exercising reuse. On Call 1 with a human at the keyboard it starts the human
  branch.
- busy, not a verdict on its own: HTTP `409`, body `code="novnc_busy"` with a `holder_url`, and a `Retry-After`
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
curl -fsS http://127.0.0.1:7021/health
```

Expect HTTP 200 with `status` `ok`, `service` `ascend-web-hunter` and a non-empty `version`.

Check Redis is reachable from the host's Docker context (the reset and the capture check use the session key).

```bash
docker exec redis redis-cli PING
```

Expect `PONG`.

No credentials are needed.

## Reset state

Delete the scrapingcourse.com session and the tier remembered for that domain, so Call 1 starts cold at the bottom of
the ladder and stores a fresh clearance. A remembered tier from an earlier run would start Call 1 at that tier, and
its time would then prove nothing against Call 2. The command is identical
in PowerShell and Unix shells. When the scraping file runs alone with the redis profile, the session store is the
container `ascend-scrapper-redis`, so every `docker exec redis` command in this spec targets that container
instead, per the suite README.

Close every NoVNC window `scrapingcourse.com` still holds before the delete. A read that answers 428, here or in
spec 6, opens a NoVNC flow that stays open up to its timeout, and the browser in that window can still pass the
challenge on its own and save `session:scrapingcourse.com:default` after the delete ran (seen 2026-11-06 after a
spec 6 run). `DELETE /api/v2/session/interventions/{flow_id}` closes one window at once, saves nothing from it and
frees its slot, so the spec no longer waits for the window to time out. List the open flows and close each one whose
`domain` is `scrapingcourse.com`, in one command.

PowerShell:

```powershell
(Invoke-RestMethod http://127.0.0.1:7021/api/v2/session/interventions).flows | Where-Object { $_.domain -in @('scrapingcourse.com') } | ForEach-Object { "$((Invoke-WebRequest -Method Delete -SkipHttpErrorCheck -Uri "http://127.0.0.1:7021/api/v2/session/interventions/$($_.flow_id)").StatusCode) $($_.flow_id)" }
```

Unix:

```bash
curl -fsS http://127.0.0.1:7021/api/v2/session/interventions | python3 -c 'import json,sys; [print(f["flow_id"]) for f in json.load(sys.stdin)["flows"] if f["domain"] in ("scrapingcourse.com",)]' | while read id; do curl -sS -o /dev/null -w "%{http_code} $id\n" -X DELETE "http://127.0.0.1:7021/api/v2/session/interventions/$id"; done
```

Expect one line `204 <flow_id>` for each window closed, and no line when no such window was open. A `404` line means
the window ended on its own between the listing and the delete, and is accepted only when the listing below no
longer shows that flow. Then list the flows again.

PowerShell:

```powershell
Invoke-RestMethod http://127.0.0.1:7021/api/v2/session/interventions
```

Unix:

```bash
curl -fsS http://127.0.0.1:7021/api/v2/session/interventions
```

Expect the body to list no flow for `scrapingcourse.com`. If one is still listed, record it under Additional tasks I
did and stop, because Call 1 cannot start cold.

```bash
docker exec redis redis-cli DEL "session:scrapingcourse.com:default" "tier_memory:scrapingcourse.com"
```

Expect `0`, `1` or `2`, the number of keys removed. Then confirm both keys are gone.

```bash
docker exec redis redis-cli EXISTS "session:scrapingcourse.com:default" "tier_memory:scrapingcourse.com"
```

Expect `0`.

Empty the reader's in-process read cache for the domain. Spec 6 reads Call 1's exact address, and this spec runs
after it, so within `READ_CACHE_TTL_SECONDS` (300 s) of that read Call 1 would be answered from the cache without
going through a browser tier and would store no session, failing the capture check for a reason that is not the
product. The Redis delete above cannot reach that cache. The session clear endpoint drops both the Redis record and
the cached reads for the domain.

PowerShell:

```powershell
curl.exe -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/clear -H "Content-Type: application/json" -d '{"url":"https://www.scrapingcourse.com/cloudflare-challenge","profile":"default"}'
```

Unix:

```bash
curl -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/clear -H "Content-Type: application/json" -d '{"url":"https://www.scrapingcourse.com/cloudflare-challenge","profile":"default"}'
```

Expect HTTP 200 with `status="cleared"`. `existed` is `false` after the delete above, and a non-zero
`cleared_cache_entries` is the cache being emptied, not a failure.

## Run

Move into the Bruno collection root first, from the repository root.

```bash
cd docs/api/request/AscendAI
```

Calls 1 and 2 write Bruno's JSON reports into a new private directory, never a fixed path under `/tmp` or
`$env:TEMP`, so two runs never share a file. Create it once, in the same shell the rest of this spec runs in, up to
the cleanup under Expected.

PowerShell:

```powershell
$E2E_OUT = (New-Item -ItemType Directory -Path (Join-Path ([IO.Path]::GetTempPath()) ([IO.Path]::GetRandomFileName()))).FullName
```

Unix:

```bash
E2E_OUT="$(mktemp -d)"
```

1. Call 1, cold. Read the page with no stored session and write Bruno's JSON report so the served `mode` and the
   response time can be read back. Wait for HTTP 200 before continuing.

PowerShell:

```powershell
bru run "web-hunter/testing/clearance-cold.yml" --env ascend-local -o "$E2E_OUT\clearance-cold-run.json" -f json
```

Unix:

```bash
bru run "web-hunter/testing/clearance-cold.yml" --env ascend-local -o "$E2E_OUT/clearance-cold-run.json" -f json
```

2. Read back Call 1's HTTP status, `mode` and `responseTime` (milliseconds) and record them in the run record. A
   success body carries `mode`. A `428` or `409` problem body carries no `mode`, so the command prints its `code`
   (`human_intervention_required` or `novnc_busy`) in that place instead.

PowerShell:

```powershell
(Get-Content "$E2E_OUT\clearance-cold-run.json" -Raw | ConvertFrom-Json)[0].results[0].response | Select-Object status, @{n="mode";e={$_.data.mode}}, @{n="code";e={$_.data.code}}, responseTime
```

Unix:

```bash
"$(command -v python3 || command -v python)" -c "import json, sys; r = json.load(open(sys.argv[1]))[0]['results'][0]['response']; d = r.get('data') or {}; print(r.get('status'), d.get('mode') or d.get('code'), r['responseTime'])" "$E2E_OUT/clearance-cold-run.json"
```

Human branch, only when Call 1 answered 428 and a human is at the keyboard. Record the `flow_id` of the 428 body. It
is `<flow-id>` below. Print the `vnc_url` of the 428 body verbatim in the chat. The human opens it and passes the
challenge in the remote window until the real page shows. Then the human confirms in the chat. Wait for that
confirmation, then poll the session status every 5 seconds, at most 120 times, which is the 600 s default of
`NOVNC_TIMEOUT_SECONDS`, until its `last_window` carries `<flow-id>`. Replace `<flow-id>` with the recorded value.

PowerShell:

```powershell
for ($i = 0; $i -lt 120; $i++) { $b = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:7021/api/v2/web/session/status -ContentType "application/json" -Body '{"url":"https://www.scrapingcourse.com/cloudflare-challenge","profile":"default"}'; if ($b.last_window -and $b.last_window.flow_id -eq '<flow-id>') { break }; Start-Sleep 5 }; $b | ConvertTo-Json -Depth 5
```

Unix:

```bash
for i in $(seq 1 120); do body=$(curl -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/status -H "Content-Type: application/json" -d '{"url":"https://www.scrapingcourse.com/cloudflare-challenge","profile":"default"}'); if echo "$body" | python3 -c 'import json,sys; w=json.load(sys.stdin)["last_window"]; sys.exit(0 if w and w["flow_id"] == "<flow-id>" else 1)'; then break; fi; sleep 5; done; echo "$body"
```

Expect `last_window` with `flow_id` equal to `<flow-id>`, `intervention_type` `"captcha"` and `outcome` `"resolved"`, the
only outcome that means the window saved the session. Any other `outcome`, or no `<flow-id>` after the last poll, is a
FAIL. Then go on with the capture check and Call 2.

3. Capture check.

```bash
docker exec redis redis-cli GET "session:scrapingcourse.com:default"
```

Expect a JSON value whose `waf` entry contains a cookie named `cf_clearance`. A `cf_clearance` cookie saved while the
page was still a wall is a FAIL: in the human branch that is any session present with a `last_window` `outcome` other
than `"resolved"`, or the human reporting that the page still showed the challenge when it was saved.

4. Call 2, warm. Read the same page under a different address, with no profile, so the read resolves to the
   `default` profile Call 1 stored under and misses the in-memory read cache.

PowerShell:

```powershell
bru run "web-hunter/testing/clearance-reuse.yml" --env ascend-local -o "$E2E_OUT\clearance-reuse-run.json" -f json
```

Unix:

```bash
bru run "web-hunter/testing/clearance-reuse.yml" --env ascend-local -o "$E2E_OUT/clearance-reuse-run.json" -f json
```

5. Read back Call 2's HTTP status, `mode` and `responseTime` and record them in the run record. On a `428` the
   command prints the problem body's `code` in the place of `mode`, as in step 2.

PowerShell:

```powershell
(Get-Content "$E2E_OUT\clearance-reuse-run.json" -Raw | ConvertFrom-Json)[0].results[0].response | Select-Object status, @{n="mode";e={$_.data.mode}}, @{n="code";e={$_.data.code}}, responseTime
```

Unix:

```bash
"$(command -v python3 || command -v python)" -c "import json, sys; r = json.load(open(sys.argv[1]))[0]['results'][0]['response']; d = r.get('data') or {}; print(r.get('status'), d.get('mode') or d.get('code'), r['responseTime'])" "$E2E_OUT/clearance-reuse-run.json"
```

## Expected

- Call 1: HTTP `200`, `status="success"`, and one of `content`, `text` or `markdown` is a string of at least 50
  characters. The `mode` and the `responseTime` from step 2 are recorded in the run record. A duration in the tens
  of seconds is normal for a browser-tier solve. Alternatively HTTP `428` with `code`
  `human_intervention_required` and a non-empty `vnc_url`, or HTTP `409` with `code` `novnc_busy`: with nobody at the
  keyboard that is the environment gate, and steps 3 to 5 are skipped with the body recorded. With a human at the
  keyboard a `428` starts the human branch, and steps 3 to 5 run after the window has saved the session.
- Capture check: `session:scrapingcourse.com:default` exists and its `waf` entry carries a cookie named
  `cf_clearance`. On the 2026-09-10 read the `auth` entry also carried six site cookies, none of which are asserted.
  A `cf_clearance` cookie saved while the page was still a wall is a FAIL of this check.
- Call 2: HTTP `200`, `status="success"`, one of `content`, `text` or `markdown` is a string of at least 50
  characters, the body carries no `vnc_url`, and the `responseTime` from step 5 is smaller than Call 1's from step
  2, a comparison the human branch does not make. Both values go into the run record. No `428`. A `428` on Call 2 is a FAIL and is register defect F54 in
  [../../../../docs/DEFECT_REGISTER.md](../../../../docs/DEFECT_REGISTER.md) until its fix lands. Record the
  response body verbatim under Additional tasks I did.
- Clean up the records this test created, so the next run starts cold again. When Call 1 or Call 2 answered 428,
  its NoVNC flow is still open and can save the session later, so first close the `scrapingcourse.com` windows the
  same way as Reset state, then delete. The delete is identical in PowerShell and Unix shells.

  PowerShell:

  ```powershell
  (Invoke-RestMethod http://127.0.0.1:7021/api/v2/session/interventions).flows | Where-Object { $_.domain -in @('scrapingcourse.com') } | ForEach-Object { "$((Invoke-WebRequest -Method Delete -SkipHttpErrorCheck -Uri "http://127.0.0.1:7021/api/v2/session/interventions/$($_.flow_id)").StatusCode) $($_.flow_id)" }
  ```

  Unix:

  ```bash
  curl -fsS http://127.0.0.1:7021/api/v2/session/interventions | python3 -c 'import json,sys; [print(f["flow_id"]) for f in json.load(sys.stdin)["flows"] if f["domain"] in ("scrapingcourse.com",)]' | while read id; do curl -sS -o /dev/null -w "%{http_code} $id\n" -X DELETE "http://127.0.0.1:7021/api/v2/session/interventions/$id"; done
  ```

  Expect one line `204 <flow_id>` for each window closed (a `404` only for a window that ended on its own, as in
  Reset state). Then list the flows again.

  PowerShell:

  ```powershell
  Invoke-RestMethod http://127.0.0.1:7021/api/v2/session/interventions
  ```

  Unix:

  ```bash
  curl -fsS http://127.0.0.1:7021/api/v2/session/interventions
  ```

  Expect the body to list no flow for `scrapingcourse.com`.

  Delete the session and the window result in one call. Closing a window above writes
  `novnc_window_result:scrapingcourse.com:default` (kept about 14 days, and `session/clear` does not remove it), so
  the delete comes after the closes.

  ```bash
  docker exec redis redis-cli DEL "session:scrapingcourse.com:default" "novnc_window_result:scrapingcourse.com:default" "tier_memory:scrapingcourse.com"
  ```

  Expect `0`, `1`, `2` or `3`, the number of keys removed.

  ```bash
  docker exec redis redis-cli EXISTS "session:scrapingcourse.com:default" "novnc_window_result:scrapingcourse.com:default" "tier_memory:scrapingcourse.com"
  ```

  Expect `0`.

  Last, once any Call 2 body has been copied into the run record, remove the report directory and the two
  reports in it.

  PowerShell:

  ```powershell
  Remove-Item -Recurse -Force $E2E_OUT
  ```

  Unix:

  ```bash
  rm -rf "$E2E_OUT"
  ```

  Expect no output.

## Fixtures

None, and no secrets. The two URLs are hardcoded in the two Bruno requests.

## Concurrency

- Mutates: Redis, the ascend-web-hunter session store, key `session:scrapingcourse.com:default`, the tier memory
  key `tier_memory:scrapingcourse.com`, and the reader's
  in-process read cache for `scrapingcourse.com`. On the F54 failure path Call 2 also holds one NoVNC window
  slot until the cleanup closes it.
- Conflicts with: test 6, which reads the same site and stores under the same session key, so a concurrent run
  would hand this spec a clearance it did not obtain or wipe the one it did. Tests 8, 10 and 17, which compare or
  extend the `session:*` key scan, since this spec's key would appear in it. Spec 20
  ([20-concurrent-interventions-test.md](20-concurrent-interventions-test.md)) fills every window slot on
  purpose, so never beside it.
- Serial: false against tests 1, 2, 3, 4, 5 and 9. Runs after test 6. No human, except in the human branch.
