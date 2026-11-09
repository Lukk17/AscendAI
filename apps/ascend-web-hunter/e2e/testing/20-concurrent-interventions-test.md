# Concurrent interventions: e2e test

## What this verifies

That the service holds several NoVNC intervention windows at once, one flow per profile, against one wall page.

`POST /api/v2/web/read` of the synthetic captcha wall page `/turnstile-wall` of task 11.9 on the shared fake
site under its allowed name `e2e-fake-site` (design D12 of `add-web-search-scraping-e2e`, owner answer 67.3 of
2026-10-04), read under the profiles `e2e-w1` to `e2e-w5`: the first four profiles open four distinct flows and
the fifth profile is refused. The page is a
thin page holding only a title, one short line asking the visitor to confirm they are human, and a
`<div class="cf-turnstile">` element, with no script. `ChallengeDetector.is_blocked` treats it as a wall because
the page's score reaches the threshold `CHALLENGE_SCORE_THRESHOLD` (`cf-turnstile` is only the marker of the
`captcha_element` signal), and the read escalates to NoVNC.

Prerequisite: `GET /api/v2/session/interventions` reports `active_flows` 0 and `max_concurrent_flows` 4
(the listing fields of design Decision 9), the shipped default of `NOVNC_MAX_CONCURRENT_FLOWS`.

Run and Expected, each step checked before the next:

1. Reads under `e2e-w1` to `e2e-w4` each answer HTTP 428 with the problem body check of design D13 of
   `add-web-search-scraping-e2e` (`code` `human_intervention_required`, `type`, `status`, `instance`, `traceId`,
   non-empty `vnc_url`), `joined` false, four distinct `flow_id` values, four distinct `window.slot` values, and a
   `window` position and size inside the display size `NOVNC_DISPLAY_SIZE` the startup banner prints.
2. The REST listing reports `active_flows` 4, `max_concurrent_flows` 4 and each `flow_id` once with its target,
   profile, `window.slot`, window and a positive remaining lease, and its body holds no cookie name, cookie value or
   storage state. The MCP `session_interventions` tool returns the same four `flow_id` values.
3. A read under `e2e-w5` answers HTTP 409 with the problem body check (`code` `novnc_busy`), a `Retry-After`
   header, `active_flows` 4, `max_concurrent_flows` 4, `flows` with four entries, `holder_profile` `e2e-w1` (the
   profile of the oldest flow) and `holder_url` the wall page address. All four flows read the same page, so only
   `holder_profile` tells which flow is the oldest.
4. A second read under `e2e-w2` answers HTTP 428 with `joined` true and the `flow_id` of step 1 for `e2e-w2`, and
   the listing still reports `active_flows` 4.
5. `/ready` answers the same status it answered before step 1, and a read of the fake site's plain article page
   answers HTTP 200 with `status` `success`.
6. `/metrics` shows `novnc_active_flows` 4, `human_intervention_total{joined="true"}` one higher and
   `novnc_flow_busy_total` one higher than before step 1. A line missing from the baseline counts as 0, because
   the service writes a labelled counter line only after its first count.
7. Closing one window frees its slot at once. `DELETE /api/v2/session/interventions/{flow_id}` of the `e2e-w1`
   flow answers HTTP 204 with no body, and the listing right after reports `active_flows` 3 with no entry for that
   `flow_id`. A second `DELETE` of the same flow answers HTTP 404 with the problem body check and `code`
   `flow_not_found`. The MCP tool `session_cancel_intervention` closes the `e2e-w2` flow the same way: it answers
   `{"status":"cancelled","flow_id":"<the e2e-w2 flow_id>"}`, the listing then reports `active_flows` 2, and a
   second call with the same `flow_id` answers a tool error whose text starts with `flow_not_found: `.
   `POST /api/v2/web/session/status` for `e2e-w1` and for `e2e-w2` answers `status` `none`, because nothing in a
   closed window is saved, and a `last_window` object with that profile's `flow_id`, `intervention_type`
   `captcha` and `outcome` `cancelled`.
8. Post-run cleanup closes the two windows still open (`e2e-w3` and `e2e-w4`) the same way, so the listing reports
   `active_flows` 0 at once with no wait for the flow lease, then asserts no `session:<fake site domain>:e2e-w*` key
   and no `novnc_flow:<fake site domain>:e2e-w*` key exists in Redis, because nobody solved a wall, and deletes the
   `novnc_window_result:<fake site domain>:e2e-w*` keys the closes wrote. The window close replaces the earlier
   wait for every lease to expire, which review item C13 of the overengineering review wanted to replace with a
   restart of ascend-web-hunter.

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

Expect a request list.

Check Redis is reachable from the host's Docker context (the cleanup step asserts the flow keys are gone).

```bash
docker exec redis redis-cli PING
```

Expect `PONG`.

Check no intervention flow is left over from an earlier run and the cap is 4.

```bash
curl -fsS http://127.0.0.1:7021/api/v2/session/interventions
```

Expect a body with `active_flows` `0` and `max_concurrent_flows` `4`. If `active_flows` is not `0`, wait for the
flows to drain and retry; do not start the rows while a flow is still open.

## Reset state

Nobody solves a wall, so no session record is written, and the Prerequisites check already gates on a drained flow
registry. An earlier run can leave the window results of the four profiles behind, because a closed window writes
`novnc_window_result:<domain>:<profile>` and the cleanup of an interrupted run may not have deleted it. Delete the
four keys in one command, which is identical in PowerShell and Unix shells.

```bash
docker exec redis redis-cli DEL "novnc_window_result:e2e-fake-site:e2e-w1" "novnc_window_result:e2e-fake-site:e2e-w2" "novnc_window_result:e2e-fake-site:e2e-w3" "novnc_window_result:e2e-fake-site:e2e-w4"
```

Expect a number from `0` to `4`, the count of keys that existed.

## Run

Timing limit. Steps 1 to 7a must finish within the flow lease of the `e2e-w1` window, counted from its step 1
read. The lease is `NOVNC_TIMEOUT_SECONDS` plus `NOVNC_FLOW_LEASE_GRACE_SECONDS`, 600 + 30 = 630 s at the
defaults. Each wall read takes about 43 s (run of 2026-11-07, where the four flows' `expires_in_seconds` in the
step 2 listing were about 45 s apart), so steps 1 to 4 take about 4.5 minutes and leave the `e2e-w1` flow about
430 s at step 3. Run the steps back to back. If the `e2e-w1` flow expires first, the sweeper closes it, and steps
3, 6 and 7 fail for a reason that is not a defect: record the run as BLOCKED with the step 2 `expires_in_seconds`
values as evidence.

From the repository root, move into the Bruno collection root first.

```bash
cd docs/api/request/AscendAI
```

The Bruno requests below live in `web-hunter/testing/interventions/` (added by task 11.4).

Step 0 - capture the baselines before any row runs, so steps 5 and 6 can measure against them. Record the
`/ready` status and the `NOVNC_DISPLAY_SIZE` value the startup banner prints on its `NoVNC display` line, for the
window bounds check of step 1.

```bash
curl -fsS http://127.0.0.1:7021/ready
```

PowerShell:

```powershell
docker logs ascend-web-hunter 2>&1 | Select-String -Pattern "NoVNC display: *\d+x\d+" | ForEach-Object { $_.Matches.Value } | Select-Object -Last 1
```

Unix:

```bash
docker logs ascend-web-hunter 2>&1 | grep -o "NoVNC display: *[0-9]*x[0-9]*" | tail -1
```

Expect one line such as `NoVNC display:        1920x1080`.

Write both metrics files into a new private directory, never a fixed path under `/tmp`, so two runs never share a
file and the Expected section never compares against an old baseline. Create it once, in the same shell the rest of
this spec runs in, up to the Post-run cleanup. A runner whose shell does not keep variables between commands uses
the literal path `mktemp` printed in place of `$E2E_OUT` in every later command, and removes that same path in the
Post-run cleanup.

**PowerShell:**

```powershell
$E2E_OUT = (New-Item -ItemType Directory -Path (Join-Path ([IO.Path]::GetTempPath()) ([IO.Path]::GetRandomFileName()))).FullName
```

**Unix:**

```bash
E2E_OUT="$(mktemp -d)"
```

**PowerShell:**

```powershell
curl.exe -fsS http://127.0.0.1:7021/metrics -o "$E2E_OUT\concurrent-interventions-before.txt"
```

**Unix:**

```bash
curl -fsS http://127.0.0.1:7021/metrics -o "$E2E_OUT/concurrent-interventions-before.txt"
```

Step 1 - open four windows, one request per profile. The open request takes the profile from the `profile`
variable (named and defined by task 11.4), passed with `--env-var`. Run it once for each of `e2e-w1`, `e2e-w2`,
`e2e-w3` and `e2e-w4` in that order, and wait for HTTP 428 before continuing.

```bash
bru run "web-hunter/testing/interventions/intervention-window-open.yml" --env ascend-local --env-var profile=e2e-w1
```

```bash
bru run "web-hunter/testing/interventions/intervention-window-open.yml" --env ascend-local --env-var profile=e2e-w2
```

```bash
bru run "web-hunter/testing/interventions/intervention-window-open.yml" --env ascend-local --env-var profile=e2e-w3
```

```bash
bru run "web-hunter/testing/interventions/intervention-window-open.yml" --env ascend-local --env-var profile=e2e-w4
```

The four runs above use the profiles `e2e-w1`, `e2e-w2`, `e2e-w3` and `e2e-w4` in that order, one window per
profile. Record each response's `flow_id` and `window.slot` in the run record.

Step 2 - list the flows from both surfaces.

```bash
bru run "web-hunter/testing/interventions/interventions-list.yml" --env ascend-local
```

```bash
bru run "web-hunter/testing/interventions/mcp-session-interventions.yml" --env ascend-local
```

Step 3 - the fifth window does not fit. Send one read under `e2e-w5` and wait for HTTP 409.

```bash
bru run "web-hunter/testing/interventions/intervention-window-5th-busy.yml" --env ascend-local
```

Step 4 - rejoining an open flow answers the same flow. Send a second read under `e2e-w2` and wait for
HTTP 428.

```bash
bru run "web-hunter/testing/interventions/intervention-window-duplicate-join.yml" --env ascend-local
```

Then confirm the listing still reports `active_flows` `4`.

```bash
curl -fsS http://127.0.0.1:7021/api/v2/session/interventions
```

Step 5 - the stack still serves beside four open windows.

```bash
curl -fsS http://127.0.0.1:7021/ready
```

```bash
curl -fsS -X POST http://127.0.0.1:7021/api/v2/web/read -H "Content-Type: application/json" -d '{"url":"http://e2e-fake-site:7031/article"}'
```

The article request reads the fake site's plain article page under its allowed name `e2e-fake-site`. It needs
no Bruno file: the page carries no challenge, so one anonymous `POST /api/v2/web/read` answers HTTP 200 with
`status` `success`.

Step 6 - capture the metrics output after the run for the growth comparison.

**PowerShell:**

```powershell
curl.exe -fsS http://127.0.0.1:7021/metrics -o "$E2E_OUT\concurrent-interventions-after.txt"
```

**Unix:**

```bash
curl -fsS http://127.0.0.1:7021/metrics -o "$E2E_OUT/concurrent-interventions-after.txt"
```

Step 7 - close windows one at a time, from both surfaces. Replace `<w1-flow-id>` and `<w2-flow-id>` below with the
`flow_id` values step 1 recorded for `e2e-w1` and `e2e-w2`.

Step 7a - close the `e2e-w1` window over REST.

PowerShell:

```powershell
curl.exe -sS -i -X DELETE http://127.0.0.1:7021/api/v2/session/interventions/<w1-flow-id>
```

Unix:

```bash
curl -sS -i -X DELETE http://127.0.0.1:7021/api/v2/session/interventions/<w1-flow-id>
```

Step 7b - the slot is free at once.

PowerShell:

```powershell
Invoke-RestMethod http://127.0.0.1:7021/api/v2/session/interventions
```

Unix:

```bash
curl -fsS http://127.0.0.1:7021/api/v2/session/interventions
```

Step 7c - a second close of the same window is refused.

PowerShell:

```powershell
curl.exe -sS -i -X DELETE http://127.0.0.1:7021/api/v2/session/interventions/<w1-flow-id>
```

Unix:

```bash
curl -sS -i -X DELETE http://127.0.0.1:7021/api/v2/session/interventions/<w1-flow-id>
```

Step 7d - close the `e2e-w2` window over MCP. Send the MCP `initialize` handshake first and expect HTTP 200 with no
`Mcp-Session-Id` response header (the service is stateless), as in spec 18.

PowerShell:

```powershell
curl.exe -fsS -i -X POST http://127.0.0.1:7021/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"e2e","version":"0.1.0"}}}'
```

Unix:

```bash
curl -fsS -i -X POST http://127.0.0.1:7021/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"e2e","version":"0.1.0"}}}'
```

Then call the tool, with the same dummy session id spec 18 sends.

PowerShell:

```powershell
curl.exe -fsS -X POST http://127.0.0.1:7021/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -H "Mcp-Session-Id: 00000000000000000000000000000000" -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"session_cancel_intervention","arguments":{"flow_id":"<w2-flow-id>"}}}'
```

Unix:

```bash
curl -fsS -X POST http://127.0.0.1:7021/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -H "Mcp-Session-Id: 00000000000000000000000000000000" -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"session_cancel_intervention","arguments":{"flow_id":"<w2-flow-id>"}}}'
```

Step 7e - the listing shows one flow fewer again.

PowerShell:

```powershell
Invoke-RestMethod http://127.0.0.1:7021/api/v2/session/interventions
```

Unix:

```bash
curl -fsS http://127.0.0.1:7021/api/v2/session/interventions
```

Step 7f - a second MCP close of the same window is refused.

PowerShell:

```powershell
curl.exe -fsS -X POST http://127.0.0.1:7021/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -H "Mcp-Session-Id: 00000000000000000000000000000000" -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"session_cancel_intervention","arguments":{"flow_id":"<w2-flow-id>"}}}'
```

Unix:

```bash
curl -fsS -X POST http://127.0.0.1:7021/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -H "Mcp-Session-Id: 00000000000000000000000000000000" -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"session_cancel_intervention","arguments":{"flow_id":"<w2-flow-id>"}}}'
```

Step 7g - nothing was saved, and the session status names how each closed window ended. One call per profile.

PowerShell:

```powershell
curl.exe -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/status -H "Content-Type: application/json" -d '{"url":"http://e2e-fake-site:7031/turnstile-wall","profile":"e2e-w1"}'
```

Unix:

```bash
curl -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/status -H "Content-Type: application/json" -d '{"url":"http://e2e-fake-site:7031/turnstile-wall","profile":"e2e-w1"}'
```

PowerShell:

```powershell
curl.exe -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/status -H "Content-Type: application/json" -d '{"url":"http://e2e-fake-site:7031/turnstile-wall","profile":"e2e-w2"}'
```

Unix:

```bash
curl -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/status -H "Content-Type: application/json" -d '{"url":"http://e2e-fake-site:7031/turnstile-wall","profile":"e2e-w2"}'
```

## Expected

- **Step 1:** four HTTP 428 answers, one per profile `e2e-w1` to `e2e-w4`. Each problem body holds `code`
  `human_intervention_required`, `type`, `status`, `instance`, `traceId`, a non-empty `vnc_url` and `joined`
  `false`. The four `flow_id` values are distinct, the four `window.slot` values are distinct, and each
  `window` position (`x`, `y`) plus size (`width`, `height`) sits inside the `NOVNC_DISPLAY_SIZE` display from
  Step 0.
- **Step 2:** the REST listing body reports `active_flows` `4` and `max_concurrent_flows` `4`, and its `flows`
  array holds each step-1 `flow_id` exactly once, each with its target URL, profile, `window.slot`, window and a
  positive `expires_in_seconds`. The body carries no `cookies`, no `storage_state` and no page content. The
  MCP `session_interventions` result holds the same four `flow_id` values.
- **Step 3:** the `e2e-w5` read answers HTTP `409`. Its problem body holds `code` `novnc_busy`,
  `active_flows` `4`, `max_concurrent_flows` `4`, `flows` with four entries, `holder_profile` `e2e-w1` (the
  profile of the oldest flow of step 1) and `holder_url` `http://e2e-fake-site:7031/turnstile-wall`. The response
  carries a `Retry-After` header.
- **Step 4:** HTTP `428` with `joined` `true` and the step-1 `flow_id` of `e2e-w2`. The listing still reports
  `active_flows` `4`, so the rejoin opened no fifth flow.
- **Step 5:** `/ready` answers the same status it answered in Step 0, and the article read answers HTTP 200
  with `status` `success`.
- **Step 6:** `novnc_active_flows` is `4` in the after-output:

  **PowerShell:**

  ```powershell
  Select-String -Path "$E2E_OUT\concurrent-interventions-after.txt" -Pattern '^novnc_active_flows'
  ```

  **Unix:**

  ```bash
  grep '^novnc_active_flows' "$E2E_OUT/concurrent-interventions-after.txt"
  ```

  `human_intervention_total` with `intervention_type="captcha"` and `joined="true"` is exactly one higher in the
  after-output than in the baseline, and `novnc_flow_busy_total` is exactly one higher. A line missing from the
  baseline counts as 0: the service writes the `human_intervention_total` line for a label pair only after its
  first count, so a freshly started service has no `joined="true"` line before step 4.

  **PowerShell:**

  ```powershell
  Select-String -Path "$E2E_OUT\concurrent-interventions-before.txt", "$E2E_OUT\concurrent-interventions-after.txt" -Pattern 'human_intervention_total\{[^}]*joined="true"'
  ```

  ```powershell
  Select-String -Path "$E2E_OUT\concurrent-interventions-before.txt", "$E2E_OUT\concurrent-interventions-after.txt" -Pattern 'novnc_flow_busy_total'
  ```

  **Unix:**

  ```bash
  grep 'human_intervention_total{[^}]*joined="true"' "$E2E_OUT/concurrent-interventions-before.txt" "$E2E_OUT/concurrent-interventions-after.txt"
  ```

  ```bash
  grep 'novnc_flow_busy_total' "$E2E_OUT/concurrent-interventions-before.txt" "$E2E_OUT/concurrent-interventions-after.txt"
  ```

- Step 7a: HTTP `204` with an empty body.
- Step 7b: the listing reports `active_flows` `3`, and its `flows` array holds no entry with the `e2e-w1`
  `flow_id`. The slot is free at once, with no wait for the lease.
- Step 7c: HTTP `404`. The problem body check holds: `Content-Type` starts with `application/problem+json`,
  `code` `flow_not_found`, `type` `https://ascend.ai/errors/flow-not-found`, `status` `404`, `instance` present
  and `traceId` 32 lower case hex characters.
- Step 7d: HTTP 200. The `data:` line of the answer holds a result that is not an error, whose payload (the
  structured content, or the JSON in the text entry) is `{"status":"cancelled","flow_id":"<w2-flow-id>"}`.
- Step 7e: the listing reports `active_flows` `2`, and holds no entry with the `e2e-w2` `flow_id`.
- Step 7f: HTTP 200. The `data:` line holds a result with `isError` `true` whose text entry starts with
  `flow_not_found: `.
- Step 7g: both answers are HTTP 200 with `status` `none`. The `e2e-w1` answer has a `last_window` object with
  `flow_id` equal to the `e2e-w1` `flow_id`, `intervention_type` `captcha`, `outcome` `cancelled` and a numeric
  `finished_at`. The `e2e-w2` answer has the same with the `e2e-w2` `flow_id`.

Every assertion above is an HTTP status, a response body, `/metrics`, or a Redis key.

## Post-run cleanup

Close the two windows step 7 left open, `e2e-w3` and `e2e-w4`, the same way. Nobody solved a wall, so closing
saves nothing, and the slots are free at once instead of after the flow lease. List the open flows and close each
one on the fake site under an `e2e-w` profile, in one command.

PowerShell:

```powershell
(Invoke-RestMethod http://127.0.0.1:7021/api/v2/session/interventions).flows | Where-Object { $_.domain -eq 'e2e-fake-site' -and $_.profile -like 'e2e-w*' } | ForEach-Object { "$((Invoke-WebRequest -Method Delete -SkipHttpErrorCheck -Uri "http://127.0.0.1:7021/api/v2/session/interventions/$($_.flow_id)").StatusCode) $($_.flow_id)" }
```

Unix:

```bash
curl -fsS http://127.0.0.1:7021/api/v2/session/interventions | python3 -c 'import json,sys; [print(f["flow_id"]) for f in json.load(sys.stdin)["flows"] if f["domain"] == "e2e-fake-site" and f["profile"].startswith("e2e-w")]' | while read id; do curl -sS -o /dev/null -w "%{http_code} $id\n" -X DELETE "http://127.0.0.1:7021/api/v2/session/interventions/$id"; done
```

Expect two lines, `204 <flow_id>` for the `e2e-w3` flow and for the `e2e-w4` flow. Then list the flows again.

PowerShell:

```powershell
Invoke-RestMethod http://127.0.0.1:7021/api/v2/session/interventions
```

Unix:

```bash
curl -fsS http://127.0.0.1:7021/api/v2/session/interventions
```

Expect the body to report `active_flows` `0`. Then assert no session key and no flow key survived in Redis. The
commands are identical in PowerShell and Unix shells.

```bash
docker exec redis redis-cli --scan --pattern "session:e2e-fake-site:e2e-w*"
```

```bash
docker exec redis redis-cli --scan --pattern "novnc_flow:e2e-fake-site:e2e-w*"
```

Expect no output from either scan. Then delete the window result keys the four closes wrote, which hold only how
each window ended and live for the session lifetime otherwise. The command is identical in PowerShell and Unix
shells.

```bash
docker exec redis redis-cli DEL "novnc_window_result:e2e-fake-site:e2e-w1" "novnc_window_result:e2e-fake-site:e2e-w2" "novnc_window_result:e2e-fake-site:e2e-w3" "novnc_window_result:e2e-fake-site:e2e-w4"
```

Expect `4`. Last, remove the report directory and the two metrics files in it.

**PowerShell:**

```powershell
Remove-Item -Recurse -Force $E2E_OUT
```

**Unix:**

```bash
rm -rf "$E2E_OUT"
```

Expect no output.

## Fixtures

None checked in. The `/turnstile-wall` page carries the canary
`Please confirm you are human to continue.`, indexed in [fixtures/README.md](../fixtures/README.md). The five
profiles `e2e-w1` to `e2e-w5` exist only as profile names on the read requests; no session is ever stored under
them.

## Concurrency

It fills every window slot, so it runs alone, with no other spec that can answer a 428 or open a window (6, 7, 10, 11,
12, 22 and the wall spec of `detect-challenge-walls-in-any-language`).

- Serial: true. It fills every window slot, so it runs alone.
