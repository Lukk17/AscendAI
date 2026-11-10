# Session establish: e2e test

## What this verifies

`POST /api/v2/web/session/establish` is the proactive counterpart to the passive NoVNC capture other reads fall
back to: it opens the NoVNC flow for a `url` on demand and always returns HTTP 200 with a `vnc_url` a human can open
to complete a login or captcha, without waiting for that human to act. This test asserts the immediate, synchronous
contract:

- HTTP 200, body `status="login_required"`, `intervention_type="login"`, `target` equal to the
  (pydantic-normalised) request URL, a non-empty `vnc_url` string, a non-empty `flow_id` string, `joined` false,
  and a `window` object carrying `slot`, `x`, `y`, `width` and `height`.
- No session record is written for a page that never showed a login, which `example.net` never does.
- `DELETE /api/v2/session/interventions/{flow_id}` closes that window: HTTP 204 with no body, the listing no longer
  shows the flow, and `POST /api/v2/web/session/status` for the same URL and profile answers `status` `none` with
  `last_window` holding the same `flow_id`, `intervention_type` `login` and `outcome` `cancelled`. Closing the window
  is also what stops this spec from leaving a headful browser running for 10 minutes.
- A login window opened on a site that is already logged in ends on its own and keeps the stored login. After an
  import of a login cookie for `example.net` under the profile `e2e-establish-auth`, a second establish call opens
  a new window, and within two minutes the session status for that profile answers `status` `active` and a
  `last_window` with the new `flow_id`, `intervention_type` `login` and `outcome` `already_authenticated`. The
  listing no longer shows that flow, and the stored record still holds the imported cookie with provenance
  `import`.

The outcome `resolved`, which a window reports after a real login in it, needs a human to log in, and this spec
has no human. Spec 22 ([22-human-login-reuse-test.md](22-human-login-reuse-test.md)) checks `resolved` after a
human login on LinkedIn, then checks `already_authenticated` again on the same saved login.

## Two behaviours this spec depends on

A first draft of this spec assumed the call writes no session record at all until a human or scripted login
resolves the background monitor. Running it against the live service on port 7021 disproved that within seconds at
the time: `session:example.net:default` existed, holding an empty-cookie record, well before any human could have
acted. The code has changed since then, and both behaviours below describe the code as it stands:

1. **The requested `profile` reaches the capture path.** `SessionManager.establish` threads `profile` all the way
   through: `NoVNCStrategy(effective_profile)`, the `NoVNCFlow` the strategy reserves, and the
   `save_storage_state(flow.url, storage_state, user_agent, flow.profile, ...)` call inside the monitor's poll loop,
   falling back to `settings.SESSION_DEFAULT_PROFILE` only when the caller supplied none, the same rule `status()`
   and `clear()` already use. Covered by
   `tests/session/test_session_manager.py::test_establish_forwards_named_profile_to_novnc_strategy` and
   `::test_establish_defaults_profile_when_none_given`.

   *Corrected observation, not a new feature:* this spec originally found the opposite here.
   `SessionManager.establish`'s second parameter was named `_profile`, the leading underscore marking it unused, so
   every capture landed under the default profile regardless of what the caller asked for. That has since been
   fixed in the codebase. This bullet was rewritten on 2026-09-08 to match the code as it stands, not the code this
   spec first ran against.
2. **A login flow saves the session only after a real login.** `SessionManager.establish` always opens the NoVNC
   flow with `intervention_type="login"`, and the monitor's login branch (`_poll_login` in
   `src/reader/strategies/novnc_strategy.py`) saves only once three things hold in the same flow: a login page was
   observed, the page stopped being one, and an auth cookie (any cookie that is not a WAF cookie) appeared or
   changed since that login page. `example.net` never shows a login page, so the monitor never saves and
   `session:example.net:e2e-establish` is never written. The NoVNC browser context also starts from the stored
   session for the same site and profile, when one exists.

   *Corrected observation, not a new feature:* until 2026-11-06 this spec expected the record to exist. The monitor
   then ran the captcha branch's "cleared" check, which accepts any page that is not a recognised block page and has
   real content, so an ordinary page like `example.net` was treated as solved on its first poll and whatever cookies
   it held, often none, were saved. The login flow no longer does that, and the `EXISTS` assertion below now
   expects `0`. This bullet was rewritten on 2026-11-06 to match the code as it stands.

This spec still only documents behaviour: it targets `example.net` (not the `example.com` key tests 3, 8, and 9
depend on being sessionless) and checks that the first call leaves no record behind. The second part writes one
record on purpose, `session:example.net:e2e-establish-auth`, through the import endpoint, and its cleanup removes
it.

A third behaviour the second part depends on: the window starts from the stored session of its site and profile,
and when that session is a valid login (an import, a login seed, or an earlier resolved login window) and the
first page the window shows on the site is content and not a login page, the window ends at once with the outcome
`already_authenticated` and saves nothing (`_already_authenticated` in `src/reader/strategies/novnc_strategy.py`).

## Why this spec is not "free" the way 1, 4, 8, and 9 are

Every other cheap ascend-web-hunter spec either touches no external process at all or only Redis. This one is
different: `SessionManager.establish` launches a real headful Chromium browser through Patchright and hands it to
NoVNC, then starts a background monitor task (`_monitor_for_cookies`) that polls the page for up to
`NOVNC_TIMEOUT_SECONDS` (600 seconds, 10 minutes, by default) before giving up and closing the browser on its own.
Nothing in this test asks a human to act. `example.net` never shows a login page, so the first window never ends
on its own. Until 2026-11-07 every run left that browser running in the background for the full 10 minutes. The
spec now closes the window with `DELETE /api/v2/session/interventions/{flow_id}` right after its checks, and the
second window ends on its own within seconds, so each window holds a browser and one slot for well under a
minute. Running this spec again before a previous run's first window was closed does not open a second
browser: the call joins the open flow for the same site and profile and answers `joined` true, which fails the
Expected section. The two browser launches still make it heavier than test 6 or 7's browser-tier reads per call,
even though, like every other ascend-web-hunter spec, it makes no call to any priced LLM or embedding provider and
so still belongs in the cost-free set in dollar terms.

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

Check Redis is reachable from the host's Docker context. Step 6 seeds one record,
`session:example.net:e2e-establish-auth`, through the service's own `POST /api/v2/web/session/import` call (no
direct Redis write), and the cleanup removes it. The test also inspects the key the first establish call must not
create, `session:example.net:e2e-establish`, and removes it if a regression created it.

```bash
docker exec redis redis-cli PING
```

Expect `PONG`.

Check no NoVNC flow is open for this test's site and profile, and a window slot is free. Each NoVNC flow launches
its own Chromium and holds one of `NOVNC_MAX_CONCURRENT_FLOWS` window slots, and each live flow has a record in
Redis under `novnc_flow:<domain>:<profile>` that the flows listing reads. A flow still open for `example.net` and
the `e2e-establish` profile, for example from a previous run of this test, makes this test's call join it and
answer `joined` true. Flows for other sites matter only when they hold every slot, which makes the call answer
HTTP 409 with `code="novnc_busy"`.

```bash
curl -fsS http://127.0.0.1:7021/api/v2/session/interventions
```

Expect HTTP 200 and `active_flows` below `max_concurrent_flows`. An entry in `flows` whose `domain` is
`example.net` and whose `profile` is `e2e-establish` or `e2e-establish-auth` is a window an earlier run of this
spec left open. It does not block the run, because the Reset state closes it. If every slot is taken by other
flows, wait 30 seconds, run the check again, and start the Run section only once a slot is free. The wait is bounded, because a flow's
`expires_in_seconds` counts down its lease, `NOVNC_TIMEOUT_SECONDS` (600 in the container) plus
`NOVNC_FLOW_LEASE_GRACE_SECONDS` (30 by default), after which its Redis record expires and the sweeper frees its
slot.

## Reset state

Confirm `example.net` currently carries no session under the `e2e-establish` profile the request sends. The
request's `profile` is forwarded to the capture path since the 2026-09-08 fix described above, so a record this
call wrongly created would land under `session:example.net:e2e-establish`. No other spec touches that key (test 8 only touches
the same domain's `default`-profile key, and only transiently during its own run).

```bash
docker exec redis redis-cli EXISTS "session:example.net:e2e-establish"
```

Expect `0`. If it returns `1`, a previous run of this spec failed and did not clean up. Delete it before
continuing.

```bash
docker exec redis redis-cli DEL "session:example.net:e2e-establish"
```

Do the same for the second part's profile, `e2e-establish-auth`, which only this spec uses.

```bash
docker exec redis redis-cli DEL "session:example.net:e2e-establish-auth"
```

Expect `0` or `1`. Then delete the two window result keys an earlier run may have left, so each `last_window` this
run reads comes from this run's windows.

```bash
docker exec redis redis-cli DEL "novnc_window_result:example.net:e2e-establish" "novnc_window_result:example.net:e2e-establish-auth"
```

Expect `0`, `1` or `2`. Close any window an earlier run left open for the two profiles. The commands differ by
shell.

PowerShell:

```powershell
(Invoke-RestMethod http://127.0.0.1:7021/api/v2/session/interventions).flows | Where-Object { $_.domain -eq 'example.net' -and $_.profile -in @('e2e-establish','e2e-establish-auth') } | ForEach-Object { "$((Invoke-WebRequest -Method Delete -SkipHttpErrorCheck -Uri "http://127.0.0.1:7021/api/v2/session/interventions/$($_.flow_id)").StatusCode) $($_.flow_id)" }
```

Unix:

```bash
curl -fsS http://127.0.0.1:7021/api/v2/session/interventions | python3 -c 'import json,sys; [print(f["flow_id"]) for f in json.load(sys.stdin)["flows"] if f["domain"] == "example.net" and f["profile"] in ("e2e-establish","e2e-establish-auth")]' | while read id; do curl -sS -o /dev/null -w "%{http_code} $id\n" -X DELETE "http://127.0.0.1:7021/api/v2/session/interventions/$id"; done
```

Expect one line `204 <flow_id>` for each window closed, and no line when none was open.

## Run

Move into the Bruno collection root first.

```bash
cd docs/api/request/AscendAI
```

Step 1 - open the login window for `example.net` under the profile `e2e-establish`.

```bash
bru run "web-hunter/testing/session-establish.yml" --env ascend-local
```

Record the `flow_id` from the answer. It is `<first-flow-id>` below.

Step 2 - wait 15 seconds, then check that nothing was saved (the command is identical in both shells). See the
Expected section.

```bash
docker exec redis redis-cli EXISTS "session:example.net:e2e-establish"
```

Step 3 - close the window. Replace `<first-flow-id>` with the recorded value.

PowerShell:

```powershell
curl.exe -sS -i -X DELETE http://127.0.0.1:7021/api/v2/session/interventions/<first-flow-id>
```

Unix:

```bash
curl -sS -i -X DELETE http://127.0.0.1:7021/api/v2/session/interventions/<first-flow-id>
```

Step 4 - the listing no longer shows the flow.

PowerShell:

```powershell
curl.exe -fsS http://127.0.0.1:7021/api/v2/session/interventions
```

Unix:

```bash
curl -fsS http://127.0.0.1:7021/api/v2/session/interventions
```

Step 5 - the session status names how the window ended.

PowerShell:

```powershell
curl.exe -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/status -H "Content-Type: application/json" -d '{"url":"https://example.net/","profile":"e2e-establish"}'
```

Unix:

```bash
curl -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/status -H "Content-Type: application/json" -d '{"url":"https://example.net/","profile":"e2e-establish"}'
```

Step 6 - import a login cookie for `example.net` under the profile `e2e-establish-auth`, so the site is already
logged in for that profile.

PowerShell:

```powershell
curl.exe -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/import -H "Content-Type: application/json" -d '{"url":"https://example.net/","profile":"e2e-establish-auth","user_agent":"e2e-session-establish-test/1.0","storage_state":{"cookies":[{"domain":".example.net","expires":-1,"httpOnly":false,"name":"e2e-establish-login","path":"/","sameSite":"Lax","secure":true,"value":"CANARY-DELTA-4402"}],"origins":[]}}'
```

Unix:

```bash
curl -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/import -H "Content-Type: application/json" -d '{"url":"https://example.net/","profile":"e2e-establish-auth","user_agent":"e2e-session-establish-test/1.0","storage_state":{"cookies":[{"domain":".example.net","expires":-1,"httpOnly":false,"name":"e2e-establish-login","path":"/","sameSite":"Lax","secure":true,"value":"CANARY-DELTA-4402"}],"origins":[]}}'
```

Step 7 - open a login window for the same site under that profile.

PowerShell:

```powershell
curl.exe -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/establish -H "Content-Type: application/json" -d '{"url":"https://example.net","profile":"e2e-establish-auth"}'
```

Unix:

```bash
curl -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/establish -H "Content-Type: application/json" -d '{"url":"https://example.net","profile":"e2e-establish-auth"}'
```

Record the `flow_id` from the answer. It is `<second-flow-id>` below.

Step 8 - poll the session status every 5 seconds, at most 24 times (two minutes, enough for one browser launch and
one page load), until its `last_window` carries `<second-flow-id>`. Replace `<second-flow-id>` with the recorded
value.

PowerShell:

```powershell
for ($i = 0; $i -lt 24; $i++) { $b = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:7021/api/v2/web/session/status -ContentType "application/json" -Body '{"url":"https://example.net/","profile":"e2e-establish-auth"}'; if ($b.last_window -and $b.last_window.flow_id -eq '<second-flow-id>') { break }; Start-Sleep 5 }; $b | ConvertTo-Json -Depth 5
```

Unix:

```bash
for i in $(seq 1 24); do body=$(curl -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/status -H "Content-Type: application/json" -d '{"url":"https://example.net/","profile":"e2e-establish-auth"}'); if echo "$body" | python3 -c 'import json,sys; w=json.load(sys.stdin)["last_window"]; sys.exit(0 if w and w["flow_id"] == "<second-flow-id>" else 1)'; then break; fi; sleep 5; done; echo "$body"
```

Step 9 - the window released itself, so the listing no longer shows the flow.

PowerShell:

```powershell
curl.exe -fsS http://127.0.0.1:7021/api/v2/session/interventions
```

Unix:

```bash
curl -fsS http://127.0.0.1:7021/api/v2/session/interventions
```

Step 10 - the stored login is unchanged. The command is identical in both shells.

```bash
docker exec redis redis-cli GET "session:example.net:e2e-establish-auth" | python3 -c "import json,sys; a=json.load(sys.stdin)['auth']; print(a['produced_by'] == 'import', [c['name'] for c in a['storage_state']['cookies']] == ['e2e-establish-login'], 'CANARY-DELTA-4402' in json.dumps(a['storage_state']))"
```

## Expected

- Step 1: HTTP 200. Body `status` equals `"login_required"`, `intervention_type` equals `"login"`, `target`
  equals `"https://example.net/"`, `vnc_url` is a non-empty string, `flow_id` is a non-empty string, `joined`
  equals `false`, and `window` is an object with the integer fields `slot`, `x`, `y`, `width` and `height`. A
  `joined` of `true` means a flow for the same site and profile was still open from an earlier run: close it as in
  Reset state and run again.
- Step 2: after the 15 second wait for the background monitor's first poll cycles
  (`NOVNC_COOKIE_SYNC_POLL_SECONDS` is 5 seconds by default, and 15 gives a safe margin over browser launch and
  navigation), `EXISTS` returns `0`: the monitor saved nothing for a page that never showed a login, as the "Two
  behaviours" section above describes. A `1` is a defect: the login flow saved a session without a real login.
- Step 3: HTTP `204` with an empty body.
- Step 4: HTTP 200, and `flows` holds no entry with `<first-flow-id>`.
- Step 5: HTTP 200. Body `status` equals `"none"`, `profile` equals `"e2e-establish"`, and `last_window` is an
  object with `flow_id` equal to `<first-flow-id>`, `intervention_type` `"login"`, `outcome` `"cancelled"` and a
  numeric `finished_at`.
- Step 6: HTTP 200. Body `status` equals `"imported"`, `domain` equals `"example.net"`, `profile` equals
  `"e2e-establish-auth"`, `auth_cookies` equals `1`, `waf_cookies` equals `0`, `dropped_cookies` equals `0`.
- Step 7: HTTP 200. Body `status` equals `"login_required"`, `intervention_type` equals `"login"`, `target`
  equals `"https://example.net/"`, `flow_id` is a non-empty string different from `<first-flow-id>`, and `joined`
  equals `false`.
- Step 8: the last body printed has `status` `"active"`, `profile` `"e2e-establish-auth"`, and `last_window`
  with `flow_id` equal to `<second-flow-id>`, `intervention_type` `"login"`, `outcome` `"already_authenticated"`
  and a numeric `finished_at`. A body still without `<second-flow-id>` after the last poll is a FAIL: the window did
  not see that the site was already logged in. Any other `outcome` is a FAIL.
- Step 9: HTTP 200, and `flows` holds no entry with `<second-flow-id>`.
- Step 10: prints `True True True`: the record still has provenance `import`, the imported cookie is its only
  cookie, and its canary value is unchanged, so the window kept the stored login and saved nothing over it.

## Post-run cleanup

Leave `example.net` sessionless for test 8, test 17 or a repeat of this test. Close any window this spec's two
profiles still hold. The commands differ by shell.

PowerShell:

```powershell
(Invoke-RestMethod http://127.0.0.1:7021/api/v2/session/interventions).flows | Where-Object { $_.domain -eq 'example.net' -and $_.profile -in @('e2e-establish','e2e-establish-auth') } | ForEach-Object { "$((Invoke-WebRequest -Method Delete -SkipHttpErrorCheck -Uri "http://127.0.0.1:7021/api/v2/session/interventions/$($_.flow_id)").StatusCode) $($_.flow_id)" }
```

Unix:

```bash
curl -fsS http://127.0.0.1:7021/api/v2/session/interventions | python3 -c 'import json,sys; [print(f["flow_id"]) for f in json.load(sys.stdin)["flows"] if f["domain"] == "example.net" and f["profile"] in ("e2e-establish","e2e-establish-auth")]' | while read id; do curl -sS -o /dev/null -w "%{http_code} $id\n" -X DELETE "http://127.0.0.1:7021/api/v2/session/interventions/$id"; done
```

Expect no line when Steps 3 and 8 worked, or one line `204 <flow_id>` for each window still open.

Clear the imported login. The clear also empties the in-process read cache for `example.net`.

PowerShell:

```powershell
curl.exe -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/clear -H "Content-Type: application/json" -d '{"url":"https://example.net/","profile":"e2e-establish-auth"}'
```

Unix:

```bash
curl -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/clear -H "Content-Type: application/json" -d '{"url":"https://example.net/","profile":"e2e-establish-auth"}'
```

Expect HTTP 200 with `status` `"cleared"` and `existed` `true`. Then delete the window result keys this run wrote
and the first profile's key, which exists only when Step 2 returned `1`. Each command is identical in both shells.

```bash
docker exec redis redis-cli DEL "novnc_window_result:example.net:e2e-establish" "novnc_window_result:example.net:e2e-establish-auth"
```

```bash
docker exec redis redis-cli DEL "session:example.net:e2e-establish"
```

```bash
docker exec redis redis-cli EXISTS "session:example.net:e2e-establish" "session:example.net:e2e-establish-auth"
```

Expect `0`.

## Fixtures

None.

## Concurrency

Do not run this test in parallel with test 8 ([8-session-clear-test.md](8-session-clear-test.md)) or test 17
([17-session-import-test.md](17-session-import-test.md)). Its second part writes
`session:example.net:e2e-establish-auth` until its cleanup, and test 8 compares a scan of `session:*` before and
after its run, so that key, or a regression that writes `session:example.net:e2e-establish`, would fail test 8's
comparison and hide which test is at fault. Test 17 runs the same before and after scan. Test 7's reset deletes
only the named keys of its own domains, none of them on `example.net`, so it does not touch the imported login.
Each NoVNC window holds one slot until Step 3 closes it or it ends on its own, so not beside spec 20
([20-concurrent-interventions-test.md](20-concurrent-interventions-test.md)), which fills every slot on purpose,
test 7, whose 428 rows can hold every slot, the wall rows of spec 19
([19-challenge-verdicts-test.md](19-challenge-verdicts-test.md)), test 11's human window, or spec 22's human
window. Not beside spec 21 ([21-platform-contract-test.md](21-platform-contract-test.md)) either, whose
`session_interventions` calls expect `active_flows` `0`. Safe to run in parallel with everything else in the suite.

- Serial: false
