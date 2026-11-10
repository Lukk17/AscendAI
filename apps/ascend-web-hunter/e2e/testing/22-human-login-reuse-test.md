# Human login with save and reuse: e2e test

## What this verifies

A human logs in to their own LinkedIn account in a NoVNC window that `POST /api/v2/web/session/establish` opened.
The window saves that login, the saved login then reads the logged-in LinkedIn feed before and after a restart of
the ascend-web-hunter container, and a later login window on the same saved login ends at once. Every check is on
an HTTP answer or on the Redis record, never on a log line.

1. Login window. The establish call for `https://www.linkedin.com/feed/` and the profile `e2e-linkedin` answers HTTP 200 with `status`
   `"login_required"`, `intervention_type` `"login"`, a non-empty `vnc_url`, a non-empty `flow_id` and `joined`
   `false`.
2. Save. After the human confirms the login, `POST /api/v2/web/session/status` for the same URL and profile answers
   `status` `"active"` and a `last_window` with that `flow_id`, `intervention_type` `"login"` and `outcome`
   `"resolved"`. The record `session:linkedin.com:e2e-linkedin` holds a cookie named `li_at`, LinkedIn's sign-in cookie,
   with provenance `6-novnc`.
3. Reuse. `POST /api/v2/web/read` for the feed with the same profile and `include_links` `true` answers HTTP 200
   with `status` `"success"`, and the links it returns show the logged-in feed (see "The logged-in marker" below).
   No window opens.
4. Reuse after a restart. After a restart of the ascend-web-hunter container alone, the same read answers the same
   way, with no HTTP 428 and no window. A restart empties the in-process read cache and every browser the service
   held, so this read is a new read built only from the record in Redis.
5. A login window on a site that is already logged in. A second establish call for the same URL and profile opens a
   new window, and that window ends on its own with `outcome` `"already_authenticated"`. The listing no longer
   shows it, and the record still holds `li_at` with provenance `6-novnc`.

Spec 10 ([10-session-establish-test.md](10-session-establish-test.md)) checks `already_authenticated` and
`cancelled` with an imported cookie and no human. This spec is the only one that checks `resolved`, because only a
real login in the window produces it.

### The logged-in marker

The read answer carries no final address, and the read drops the page's `nav`, `footer`, `script`, `style` and
`iframe` parts before it lists links, so the spec judges the feed by the link map that `include_links` returns. The
summary command prints counts only, never the feed text or any address, because the feed shows other people's
posts and names.

- At least one link whose address contains `linkedin.com/in/`. These are member profile addresses. On the
  logged-in feed the card with the signed-in member's own name and the author of every post link to
  `/in/<member>/`. A logged-out request for `/feed/` is sent to the sign-in page or to the sign-up wall, and neither
  shows a member card or posts. The check reads addresses, not words, so it holds whatever language the account
  uses.
- No link whose path starts with `/login`, `/uas/login`, `/authwall`, `/checkpoint` or `/signup`. LinkedIn sends a
  visitor who is not logged in, or who must pass a security check, to those paths, and their pages link to each
  other.
- HTTP 200 with `status` `"success"` is the third part. A sign-in page has a password field, so a read that lands
  on one is judged a login wall and answers HTTP 428, not 200. A read whose stored login no longer counts answers
  `status` `"session_expired"`.

### LinkedIn's terms

LinkedIn's User Agreement forbids automated access to its site, including scraping and bots, and LinkedIn may
restrict an account it thinks is automated. This spec reads only two pages, the feed twice, and opens two windows.
Run it rarely, and use a second LinkedIn account rather than your main one, because the risk to the account is
yours.

### Human-intervention forwarding (mandatory)

Step 1 returns a `vnc_url` that a human must open. The agent driving the test prints that `vnc_url` verbatim in the
chat the moment it is received, then waits for the human to confirm the login before Step 3.

The human types the password and passes any security check in the remote window. The runner never asks for the
password, never types into the window, and never sees the password. The runner never prints a cookie value: the
cookie check below prints cookie names and a count only, and no step prints the raw record.

A fanned-out `e2e-runner` subagent's output is never shown to the user, so this whole test runs on the main session,
never in a subagent. If it is ever delegated despite this, the main agent must re-print the subagent's `vnc_url` to
the user, or the human never receives the link and the test stalls.

## Prerequisites

Check the ascend-web-hunter server is reachable.

```bash
curl -fsS http://127.0.0.1:7021/health
```

Expect HTTP 200 with `status` `ok`, `service` `ascend-web-hunter` and a non-empty `version`.

Check Redis is reachable from the host's Docker context.

```bash
docker exec redis redis-cli PING
```

Expect `PONG`.

Check a window slot is free.

```bash
curl -fsS http://127.0.0.1:7021/api/v2/session/interventions
```

Expect HTTP 200 and `active_flows` below `max_concurrent_flows`. A `linkedin.com` entry for the profile `e2e-linkedin` is
a window an earlier run left open, and the Reset state closes it.

Check whether the NoVNC desktop has a password, because the human types a real password into the window. The
container writes the password file at boot only when `VNC_PASSWORD` is set, and it stays optional, so local runs are
passwordless. The command prints `set` or `unset`, never the value, and is identical in both shells.

```bash
docker exec ascend-web-hunter sh -c 'test -s /run/vnc/passwd && echo set || echo unset'
```

Record the printed word in the run record. On `unset` the run goes on, and the record carries this one sentence of
risk: anyone who can reach the NoVNC address during the run can watch and control the window the human logs in to.

A human is at the keyboard on the main session with a LinkedIn account of their own, ideally a second account, and
can receive any security code LinkedIn sends to that account's email or phone. No credential is stored in this
repository or in the run record.

## Reset state

Close any window an earlier run left open for this spec's profile.

PowerShell:

```powershell
(Invoke-RestMethod http://127.0.0.1:7021/api/v2/session/interventions).flows | Where-Object { $_.domain -eq 'linkedin.com' -and $_.profile -eq 'e2e-linkedin' } | ForEach-Object { "$((Invoke-WebRequest -Method Delete -SkipHttpErrorCheck -Uri "http://127.0.0.1:7021/api/v2/session/interventions/$($_.flow_id)").StatusCode) $($_.flow_id)" }
```

Unix:

```bash
curl -fsS http://127.0.0.1:7021/api/v2/session/interventions | python3 -c 'import json,sys; [print(f["flow_id"]) for f in json.load(sys.stdin)["flows"] if f["domain"] == "linkedin.com" and f["profile"] == "e2e-linkedin"]' | while read id; do curl -sS -o /dev/null -w "%{http_code} $id\n" -X DELETE "http://127.0.0.1:7021/api/v2/session/interventions/$id"; done
```

Expect one line `204 <flow_id>` for each window closed, and no line when none was open.

Clear the stored session for the feed. The clear also empties the in-process read cache for `linkedin.com`, so
Step 5 cannot answer from an old result.

PowerShell:

```powershell
curl.exe -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/clear -H "Content-Type: application/json" -d '{"url":"https://www.linkedin.com/feed/","profile":"e2e-linkedin"}'
```

Unix:

```bash
curl -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/clear -H "Content-Type: application/json" -d '{"url":"https://www.linkedin.com/feed/","profile":"e2e-linkedin"}'
```

Expect HTTP 200 with `status` `"cleared"`, `existed` `true` or `false`.

Delete every other `linkedin.com` key: the window result, the tier memory, and a session another profile left.

PowerShell:

```powershell
docker exec redis redis-cli --scan --pattern "*linkedin.com*" | ForEach-Object { docker exec redis redis-cli DEL $_ }
```

Unix:

```bash
docker exec redis redis-cli --scan --pattern "*linkedin.com*" | while read key; do docker exec redis redis-cli DEL "$key"; done
```

Expect one `1` per key deleted, and nothing when there was none. Then confirm none is left. The command is identical
in both shells.

```bash
docker exec redis redis-cli --scan --pattern "*linkedin.com*"
```

Expect no output.

## Run

> Execution model: this whole test is run by the main agent on the main session, never by an `e2e-runner`
> subagent, whose output is not shown to the user. See "Human-intervention forwarding (mandatory)" above.

Step 1 - open the login window.

PowerShell:

```powershell
curl.exe -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/establish -H "Content-Type: application/json" -d '{"url":"https://www.linkedin.com/feed/","profile":"e2e-linkedin"}'
```

Unix:

```bash
curl -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/establish -H "Content-Type: application/json" -d '{"url":"https://www.linkedin.com/feed/","profile":"e2e-linkedin"}'
```

Record the `flow_id` from the answer. It is `<first-flow-id>` below.

Step 2 - print the `vnc_url` from Step 1 verbatim in the chat. The human opens it, logs in to LinkedIn in the remote
window, passes any security check LinkedIn shows (an email or phone code, a puzzle, or an approval in the LinkedIn
app), and waits until the feed shows. Then the human confirms in the chat. Wait for that confirmation.

Step 3 - poll the session status every 5 seconds, at most 24 times, until its `last_window` carries
`<first-flow-id>`. Replace `<first-flow-id>` with the recorded value.

PowerShell:

```powershell
for ($i = 0; $i -lt 24; $i++) { $b = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:7021/api/v2/web/session/status -ContentType "application/json" -Body '{"url":"https://www.linkedin.com/feed/","profile":"e2e-linkedin"}'; if ($b.last_window -and $b.last_window.flow_id -eq '<first-flow-id>') { break }; Start-Sleep 5 }; $b | ConvertTo-Json -Depth 5
```

Unix:

```bash
for i in $(seq 1 24); do body=$(curl -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/status -H "Content-Type: application/json" -d '{"url":"https://www.linkedin.com/feed/","profile":"e2e-linkedin"}'); if echo "$body" | python3 -c 'import json,sys; w=json.load(sys.stdin)["last_window"]; sys.exit(0 if w and w["flow_id"] == "<first-flow-id>" else 1)'; then break; fi; sleep 5; done; echo "$body"
```

Step 4 - check the saved cookies by name.

PowerShell:

```powershell
$a = (docker exec redis redis-cli GET "session:linkedin.com:e2e-linkedin" | ConvertFrom-Json).auth; $n = @($a.storage_state.cookies.name | Sort-Object -Unique); "$($n -contains 'li_at') $($a.produced_by) $($n.Count) $($n -join ',')"
```

Unix:

```bash
docker exec redis redis-cli GET "session:linkedin.com:e2e-linkedin" | python3 -c "import json,sys; a=json.load(sys.stdin)['auth']; n=sorted({c['name'] for c in a['storage_state']['cookies']}); print('li_at' in n, a['produced_by'], len(n), ','.join(n))"
```

Step 5 - read the feed with the saved login.

PowerShell:

```powershell
$r = Invoke-WebRequest -Method Post -SkipHttpErrorCheck -Uri http://127.0.0.1:7021/api/v2/web/read -ContentType "application/json" -Body '{"url":"https://www.linkedin.com/feed/","profile":"e2e-linkedin","include_links":true}'; $b = $r.Content | ConvertFrom-Json -AsHashtable; $l = @($b.links.Values | Where-Object { $_ }); "$($r.StatusCode) $($b.status) $(if ($b.code) { $b.code } else { '-' }) $(if ($b.mode) { $b.mode } else { '-' }) $(@($l | Where-Object { $_ -like '*linkedin.com/in/*' }).Count) $(@($l | Where-Object { ([uri]$_).AbsolutePath -match '^/(login|uas/login|authwall|checkpoint|signup)' }).Count)"
```

Unix:

```bash
curl -sS -X POST http://127.0.0.1:7021/api/v2/web/read -H "Content-Type: application/json" -d '{"url":"https://www.linkedin.com/feed/","profile":"e2e-linkedin","include_links":true}' -w '\n%{http_code}' | python3 -c 'import json,sys; from urllib.parse import urlparse; body,code=sys.stdin.read().rsplit("\n",1); r=json.loads(body); l=[u for u in (r.get("links") or {}).values() if u]; print(code, r.get("status"), r.get("code") or "-", r.get("mode") or "-", sum("linkedin.com/in/" in u for u in l), sum(urlparse(u).path.startswith(("/login","/uas/login","/authwall","/checkpoint","/signup")) for u in l))'
```

Step 6 - check no window opened for `linkedin.com`.

PowerShell:

```powershell
(Invoke-RestMethod http://127.0.0.1:7021/api/v2/session/interventions).flows | Where-Object { $_.domain -eq 'linkedin.com' } | ForEach-Object { "$($_.flow_id) $($_.profile)" }
```

Unix:

```bash
curl -fsS http://127.0.0.1:7021/api/v2/session/interventions | python3 -c 'import json,sys; [print(f["flow_id"], f["profile"]) for f in json.load(sys.stdin)["flows"] if f["domain"] == "linkedin.com"]'
```

Step 7 - restart the ascend-web-hunter container alone, from the repository root. When the main stack runs (project
`ascend-ai`), the command is identical in both shells.

```bash
docker compose restart ascend-web-hunter
```

When the scraping file runs alone (project `ascend-scrapper`), use this one instead.

```bash
docker compose -f compose.ascend-web-hunter.yaml restart ascend-web-hunter
```

Then wait until the service answers again, at most two minutes.

PowerShell:

```powershell
for ($i = 0; $i -lt 24; $i++) { try { Invoke-RestMethod http://127.0.0.1:7021/health; break } catch { Start-Sleep 5 } }
```

Unix:

```bash
for i in $(seq 1 24); do curl -fsS http://127.0.0.1:7021/health && break; sleep 5; done
```

Step 8 - read the feed again.

PowerShell:

```powershell
$r = Invoke-WebRequest -Method Post -SkipHttpErrorCheck -Uri http://127.0.0.1:7021/api/v2/web/read -ContentType "application/json" -Body '{"url":"https://www.linkedin.com/feed/","profile":"e2e-linkedin","include_links":true}'; $b = $r.Content | ConvertFrom-Json -AsHashtable; $l = @($b.links.Values | Where-Object { $_ }); "$($r.StatusCode) $($b.status) $(if ($b.code) { $b.code } else { '-' }) $(if ($b.mode) { $b.mode } else { '-' }) $(@($l | Where-Object { $_ -like '*linkedin.com/in/*' }).Count) $(@($l | Where-Object { ([uri]$_).AbsolutePath -match '^/(login|uas/login|authwall|checkpoint|signup)' }).Count)"
```

Unix:

```bash
curl -sS -X POST http://127.0.0.1:7021/api/v2/web/read -H "Content-Type: application/json" -d '{"url":"https://www.linkedin.com/feed/","profile":"e2e-linkedin","include_links":true}' -w '\n%{http_code}' | python3 -c 'import json,sys; from urllib.parse import urlparse; body,code=sys.stdin.read().rsplit("\n",1); r=json.loads(body); l=[u for u in (r.get("links") or {}).values() if u]; print(code, r.get("status"), r.get("code") or "-", r.get("mode") or "-", sum("linkedin.com/in/" in u for u in l), sum(urlparse(u).path.startswith(("/login","/uas/login","/authwall","/checkpoint","/signup")) for u in l))'
```

Step 9 - check again that no window opened, and that the status still names the first window.

PowerShell:

```powershell
(Invoke-RestMethod http://127.0.0.1:7021/api/v2/session/interventions).flows | Where-Object { $_.domain -eq 'linkedin.com' } | ForEach-Object { "$($_.flow_id) $($_.profile)" }
```

Unix:

```bash
curl -fsS http://127.0.0.1:7021/api/v2/session/interventions | python3 -c 'import json,sys; [print(f["flow_id"], f["profile"]) for f in json.load(sys.stdin)["flows"] if f["domain"] == "linkedin.com"]'
```

PowerShell:

```powershell
curl.exe -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/status -H "Content-Type: application/json" -d '{"url":"https://www.linkedin.com/feed/","profile":"e2e-linkedin"}'
```

Unix:

```bash
curl -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/status -H "Content-Type: application/json" -d '{"url":"https://www.linkedin.com/feed/","profile":"e2e-linkedin"}'
```

Step 10 - open a login window again.

PowerShell:

```powershell
curl.exe -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/establish -H "Content-Type: application/json" -d '{"url":"https://www.linkedin.com/feed/","profile":"e2e-linkedin"}'
```

Unix:

```bash
curl -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/establish -H "Content-Type: application/json" -d '{"url":"https://www.linkedin.com/feed/","profile":"e2e-linkedin"}'
```

Record the `flow_id` from the answer. It is `<second-flow-id>` below.

Step 11 - poll the session status every 5 seconds, at most 24 times, until its `last_window` carries
`<second-flow-id>`.

PowerShell:

```powershell
for ($i = 0; $i -lt 24; $i++) { $b = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:7021/api/v2/web/session/status -ContentType "application/json" -Body '{"url":"https://www.linkedin.com/feed/","profile":"e2e-linkedin"}'; if ($b.last_window -and $b.last_window.flow_id -eq '<second-flow-id>') { break }; Start-Sleep 5 }; $b | ConvertTo-Json -Depth 5
```

Unix:

```bash
for i in $(seq 1 24); do body=$(curl -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/status -H "Content-Type: application/json" -d '{"url":"https://www.linkedin.com/feed/","profile":"e2e-linkedin"}'); if echo "$body" | python3 -c 'import json,sys; w=json.load(sys.stdin)["last_window"]; sys.exit(0 if w and w["flow_id"] == "<second-flow-id>" else 1)'; then break; fi; sleep 5; done; echo "$body"
```

Step 12 - check the window released itself.

PowerShell:

```powershell
(Invoke-RestMethod http://127.0.0.1:7021/api/v2/session/interventions).flows | Where-Object { $_.domain -eq 'linkedin.com' } | ForEach-Object { "$($_.flow_id) $($_.profile)" }
```

Unix:

```bash
curl -fsS http://127.0.0.1:7021/api/v2/session/interventions | python3 -c 'import json,sys; [print(f["flow_id"], f["profile"]) for f in json.load(sys.stdin)["flows"] if f["domain"] == "linkedin.com"]'
```

Step 13 - check the saved cookies again.

PowerShell:

```powershell
$a = (docker exec redis redis-cli GET "session:linkedin.com:e2e-linkedin" | ConvertFrom-Json).auth; $n = @($a.storage_state.cookies.name | Sort-Object -Unique); "$($n -contains 'li_at') $($a.produced_by) $($n.Count) $($n -join ',')"
```

Unix:

```bash
docker exec redis redis-cli GET "session:linkedin.com:e2e-linkedin" | python3 -c "import json,sys; a=json.load(sys.stdin)['auth']; n=sorted({c['name'] for c in a['storage_state']['cookies']}); print('li_at' in n, a['produced_by'], len(n), ','.join(n))"
```

## Expected

- Step 1: HTTP 200. Body `status` equals `"login_required"`, `intervention_type` equals `"login"`, `target` equals
  `"https://www.linkedin.com/feed/"`, `vnc_url` and `flow_id` are non-empty strings, `joined` equals `false`. The main agent printed the
  `vnc_url` verbatim in the chat.
- Step 3: the last body printed has `status` `"active"`, `profile` `"e2e-linkedin"`, and `last_window` with `flow_id` equal to
  `<first-flow-id>`, `intervention_type` `"login"`, `outcome` `"resolved"` and a numeric `finished_at`. An `outcome`
  of `"timeout"`, `"rejected"` or `"browser_closed"`, or no `<first-flow-id>` after the last poll, is a FAIL.
- Step 4: prints `True 6-novnc <count> <names>`, where the names hold `li_at`. A `False` is a FAIL: the window saved
  before LinkedIn set its sign-in cookie, for example while a security check page was still open.
- Step 5: prints `200 success - <mode> <n> 0` with `<n>` at least `1`. The `-` stands for the problem `code`,
  which a success has none of, and `<mode>` names the tier that read the page. A `428` is a FAIL: the saved login did not reach the feed and the read asked for a human. A
  `400` with `code` `unsafe_uri` is a FAIL: the URI guard refused the read of a page whose main address is public. A
  `session_expired` status, an `<n>` of `0`, or a last number above `0` is a FAIL.
- Step 6: no line. A line is a FAIL: the read opened a window.
- Step 7: the restart command ends without an error, and the health loop prints a body with `status` `ok`.
- Step 8: the same as Step 5. The read cache was emptied by the restart, so this is a new read.
- Step 9: the listing prints no line. The status answers HTTP 200 with `status` `"active"` and the same
  `last_window` as Step 3, because the window result lives in Redis and survives the restart.
- Step 10: HTTP 200. Body `status` equals `"login_required"`, `intervention_type` equals `"login"`, `flow_id` is a
  non-empty string different from `<first-flow-id>`, `joined` equals `false`.
- Step 11: the last body printed has `status` `"active"` and `last_window` with `flow_id` equal to
  `<second-flow-id>`, `intervention_type` `"login"`, `outcome` `"already_authenticated"` and a numeric
  `finished_at`. Any other `outcome`, or no `<second-flow-id>` after the last poll, is a FAIL.
- Step 12: no line.
- Step 13: prints `True 6-novnc`, then a count and names that still hold `li_at`. The provenance is still `6-novnc`,
  so the second window saved nothing over the login.

## Post-run cleanup

Close any window this spec's profile still holds.

PowerShell:

```powershell
(Invoke-RestMethod http://127.0.0.1:7021/api/v2/session/interventions).flows | Where-Object { $_.domain -eq 'linkedin.com' -and $_.profile -eq 'e2e-linkedin' } | ForEach-Object { "$((Invoke-WebRequest -Method Delete -SkipHttpErrorCheck -Uri "http://127.0.0.1:7021/api/v2/session/interventions/$($_.flow_id)").StatusCode) $($_.flow_id)" }
```

Unix:

```bash
curl -fsS http://127.0.0.1:7021/api/v2/session/interventions | python3 -c 'import json,sys; [print(f["flow_id"]) for f in json.load(sys.stdin)["flows"] if f["domain"] == "linkedin.com" and f["profile"] == "e2e-linkedin"]' | while read id; do curl -sS -o /dev/null -w "%{http_code} $id\n" -X DELETE "http://127.0.0.1:7021/api/v2/session/interventions/$id"; done
```

Expect no line when Step 11 passed, or one line `204 <flow_id>` for each window still open.

Clear the saved login and the read cache for `linkedin.com`.

PowerShell:

```powershell
curl.exe -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/clear -H "Content-Type: application/json" -d '{"url":"https://www.linkedin.com/feed/","profile":"e2e-linkedin"}'
```

Unix:

```bash
curl -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/clear -H "Content-Type: application/json" -d '{"url":"https://www.linkedin.com/feed/","profile":"e2e-linkedin"}'
```

Expect HTTP 200 with `status` `"cleared"` and `existed` `true`. Then delete every other `linkedin.com` key.

PowerShell:

```powershell
docker exec redis redis-cli --scan --pattern "*linkedin.com*" | ForEach-Object { docker exec redis redis-cli DEL $_ }
```

Unix:

```bash
docker exec redis redis-cli --scan --pattern "*linkedin.com*" | while read key; do docker exec redis redis-cli DEL "$key"; done
```

Confirm none is left.

```bash
docker exec redis redis-cli --scan --pattern "*linkedin.com*"
```

Expect no output. The login is gone from the service, but LinkedIn still counts it as an open session of the account.
The human can end it in LinkedIn's settings, under the account's sign-in and security page, if they want to.

## Fixtures

None. The human's LinkedIn account is the only input, and nothing about it is written to the repository or to the
run record, apart from cookie names and counts.

## Concurrency

- Mutates: Redis keys `session:linkedin.com:e2e-linkedin`, `novnc_window_result:linkedin.com:e2e-linkedin`, `tier_memory:linkedin.com`
  and, while a window is open, `novnc_flow:linkedin.com:e2e-linkedin`. One NoVNC window slot while a window is open. The
  in-process read cache for `linkedin.com`. Step 7 restarts the ascend-web-hunter container, which ends every open
  window and every read in flight, whoever started them.
- Conflicts with: spec 20 ([20-concurrent-interventions-test.md](20-concurrent-interventions-test.md)), which fills
  every window slot on purpose. Any spec that deletes this spec's session key, because it would wipe the saved
  login between Step 3 and Step 13. Test 7's reset deletes only the named keys of its own domains, which do not
  include `session:linkedin.com:e2e-linkedin`, but its window closes cover `linkedin.com` and would close this
  spec's login window, and its reset deletes `tier_memory:linkedin.com`, the tier this spec remembers. Tests
  8, 10 and 17, which compare a scan of `session:*` before and after their run and would see this spec's key. Every
  other spec, because of the restart in Step 7.
- Serial: true. Runs alone on the main session, with the human at the keyboard, before or after spec 11
  ([11-captcha-solve-and-capture-test.md](11-captcha-solve-and-capture-test.md)), never beside it.
