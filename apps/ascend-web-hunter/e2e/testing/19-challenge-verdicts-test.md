# Challenge verdicts on the fake site: e2e test

## What this verifies

`POST /api/v2/web/read` returns the gated challenge verdict for each page of the shared e2e fake site,
read under its allowed name `e2e-fake-site` (design D11 and D12 of `add-web-search-scraping-e2e`,
owner answer 67.3 of 2026-10-04). The fake site pages are the ones task 11.12 adds or rebuilds, served
from `e2e/fake-site/pages/`, and the unit test `tests/reader/cloudflare/test_fake_site_verdicts.py` runs
`assess` over the same page files, so these rows and the unit test judge the same markup.

Rows, with their fake site path and gated verdict:

1. `/wall-ko`, a site's own captcha page in Korean with no vendor marker: HTTP 428 with
   `intervention_type` `captcha`.
2. `/wall-tr`, a Turkish login form with a password input and a captcha input: HTTP 428 with
   `intervention_type` `login`.
3. `/wall-vendor-thin`, a catalogued vendor script on a thin page: HTTP 428.
4. `/wall-header`, a 403 carrying the definitive `cf-mitigated` challenge header beside a rich body:
   HTTP 428.
5. `/wall-oversized`, a wall page larger than `CHALLENGE_DETECTION_MAX_BYTES`: HTTP 428.
6. `/captcha-wall`, a blog post of at least 150 words with a catalogued widget under its comment form:
   HTTP 200 with `status` `success` and its canary sentence.
7. `/article-ja`, a Japanese article with no vendor marker: HTTP 200 `success` with its canary sentence.
8. `/article-ar`, an Arabic article with no vendor marker: HTTP 200 `success` with its canary sentence.
9. `/prose-captcha`, a page with the word `captcha` only in its prose: HTTP 200 `success`.
10. `/rich-403`, a 403 with a rich body and no other signal: any answer but HTTP 428.

Every 428 passes the problem body check of design D13 of `add-web-search-scraping-e2e` with a non-empty
`vnc_url`. The spec closes the window of each wall row with `DELETE /api/v2/session/interventions/{flow_id}`
(HTTP 204) before the next row, so no window is left open for up to 660 seconds. After the rows, `/metrics` shows `challenge_verdicts_total` with `verdict="wall"` grown by at
least the number of wall rows and with `verdict="content"` grown by at least twice the number of gated
content rows (the serving tier and the reader second look each count one, see Expected), with no
`verdict="content"` growth under the `tier` label `novnc-monitor` (a window judges its last check with the
main frame response headers, so even the header-only wall `/wall-header` ends as a wall), and
every `vendor` label value of `challenge_signals_fired_total` is a catalogue vendor name or the fixed
label `none` of the observability spec. Cleanup closes any window still open for `e2e-fake-site:default`
and waits until `GET /api/v2/session/interventions` reports `active_flows` 0.

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

Check no intervention flow is left over from an earlier run.

```bash
curl -fsS http://127.0.0.1:7021/api/v2/session/interventions
```

Expect a body with `active_flows` `0`. If it is not `0`, wait for the flows to drain and retry; do not
start the rows while a flow is still open.

## Reset state

Reads of the fake site are not stateless. A successful read is kept in the service's in-process read
cache for `READ_CACHE_TTL_SECONDS` (300 s), the tier that served it is remembered in Redis under
`tier_memory:e2e-fake-site`, and every NoVNC window a wall row opens leaves its result under
`novnc_window_result:e2e-fake-site:default` (kept about 14 days, and `session/clear` does not remove it).
Within 300 s of an earlier run a content row would be answered from the cache and count no verdict, and a
remembered tier makes a read skip the tiers before it. The Prerequisites check already gates on a drained
flow registry, so no window is open while these keys are deleted.

Empty the read cache for the fake site. The call also deletes `session:e2e-fake-site:default` if one exists.

PowerShell:

```powershell
curl.exe -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/clear -H "Content-Type: application/json" -d '{"url":"http://e2e-fake-site:7031/","profile":"default"}'
```

Unix:

```bash
curl -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/clear -H "Content-Type: application/json" -d '{"url":"http://e2e-fake-site:7031/","profile":"default"}'
```

Expect HTTP 200 with `status` `"cleared"`. `cleared_cache_entries` is the number of cached reads removed.

Delete the remembered tier and the window result of an earlier run in one call. The command is identical in
PowerShell and Unix shells.

```bash
docker exec redis redis-cli DEL "tier_memory:e2e-fake-site" "novnc_window_result:e2e-fake-site:default"
```

Expect `0`, `1` or `2`, the number of keys removed.

## Run

Move into the Bruno collection root first, from the repository root.

```bash
cd docs/api/request/AscendAI
```

The Bruno requests below live in `web-hunter/testing/challenge-verdicts/` (added by task 11.9 of
`detect-challenge-walls-in-any-language`).

Never pipe `bru run` output into `head` or any other command that stops reading early, because that cuts the
run short. Write the full output to a file instead, for example with `--reporter-json <file>`, and read the file.

Step 0 - capture the metrics baseline before any row runs, so the Expected section can measure growth.
Write both metrics files into a new private directory, never a fixed path under `/tmp`, so two runs never
share a file and the Expected section never compares against an old baseline. Create it once, in the same
shell the rest of this spec runs in, up to the Post-run cleanup.

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
curl.exe -fsS http://127.0.0.1:7021/metrics -o "$E2E_OUT\challenge-verdicts-before.txt"
```

**Unix:**

```bash
curl -fsS http://127.0.0.1:7021/metrics -o "$E2E_OUT/challenge-verdicts-before.txt"
```

Wall rows. Send one request per row and wait for HTTP 428 before continuing.

> Repair 2026-10-26 (no owning tasks box; documented here like the cap-5 fix): back-to-back wall
> rows joined one live flow. Flows are keyed by registrable domain + profile, so every wall row here
> shares `e2e-fake-site:default`: wall-tr's read joined wall-ko's still-live flow and answered
> `intervention_type` `captcha` instead of its specified `login` (run records
> `2026-10-26T09-37-51_19-challenge-verdicts-tasks.md` and
> `2026-10-26T10-30-00_19-challenge-verdicts-tasks.md`; every tier verdict log says `type=login`
> for the page while the 428 carries `captcha` from the joined flow). Each wall row after the first
> therefore starts with a drain: poll `GET /api/v2/session/interventions` until `active_flows` is
> `0`, up to 90 polls of 10 seconds (the flow lease plus sweep bound, as in Cleanup). The wall-tr
> row on a drained registry is the proof: it must answer `login` on its own fresh flow.

After each wall row, close its window first, then drain. A closed window frees its slot at once, saves
nothing and ends with the outcome `cancelled`, and the drain then confirms the registry is empty. The close
command is the same after every wall row and differs by shell. Do not run it before the first row: the steps
below repeat its Unix form right after each wall row, and in PowerShell run the PowerShell form there instead.

PowerShell:

```powershell
(Invoke-RestMethod http://127.0.0.1:7021/api/v2/session/interventions).flows | Where-Object { $_.domain -eq 'e2e-fake-site' -and $_.profile -eq 'default' } | ForEach-Object { "$((Invoke-WebRequest -Method Delete -SkipHttpErrorCheck -Uri "http://127.0.0.1:7021/api/v2/session/interventions/$($_.flow_id)").StatusCode) $($_.flow_id)" }
```

Unix:

```bash
curl -fsS http://127.0.0.1:7021/api/v2/session/interventions | python3 -c 'import json,sys; [print(f["flow_id"]) for f in json.load(sys.stdin)["flows"] if f["domain"] == "e2e-fake-site" and f["profile"] == "default"]' | while read id; do curl -sS -o /dev/null -w "%{http_code} $id\n" -X DELETE "http://127.0.0.1:7021/api/v2/session/interventions/$id"; done
```

After a wall row, expect one line `204 <flow_id>` for the window the row opened.

```bash
bru run "web-hunter/testing/challenge-verdicts/wall-own-captcha-korean.yml" --env ascend-local
```

Close the row's window (the close command above), then drain before the next wall row (see repair note
above).

```bash
curl -fsS http://127.0.0.1:7021/api/v2/session/interventions | python3 -c 'import json,sys; [print(f["flow_id"]) for f in json.load(sys.stdin)["flows"] if f["domain"] == "e2e-fake-site" and f["profile"] == "default"]' | while read id; do curl -sS -o /dev/null -w "%{http_code} $id\n" -X DELETE "http://127.0.0.1:7021/api/v2/session/interventions/$id"; done
```

```bash
for i in $(seq 1 90); do if [ "$(curl -fsS http://127.0.0.1:7021/api/v2/session/interventions | python3 -c 'import json,sys; print(json.load(sys.stdin)["active_flows"])')" = "0" ]; then break; fi; sleep 10; done; curl -fsS http://127.0.0.1:7021/api/v2/session/interventions
```

```bash
bru run "web-hunter/testing/challenge-verdicts/wall-login-turkish.yml" --env ascend-local
```

Close the row's window (the close command above), then drain before the next wall row (see repair note
above).

```bash
curl -fsS http://127.0.0.1:7021/api/v2/session/interventions | python3 -c 'import json,sys; [print(f["flow_id"]) for f in json.load(sys.stdin)["flows"] if f["domain"] == "e2e-fake-site" and f["profile"] == "default"]' | while read id; do curl -sS -o /dev/null -w "%{http_code} $id\n" -X DELETE "http://127.0.0.1:7021/api/v2/session/interventions/$id"; done
```

```bash
for i in $(seq 1 90); do if [ "$(curl -fsS http://127.0.0.1:7021/api/v2/session/interventions | python3 -c 'import json,sys; print(json.load(sys.stdin)["active_flows"])')" = "0" ]; then break; fi; sleep 10; done; curl -fsS http://127.0.0.1:7021/api/v2/session/interventions
```

```bash
bru run "web-hunter/testing/challenge-verdicts/wall-vendor-script-thin.yml" --env ascend-local
```

Close the row's window (the close command above), then drain before the next wall row (see repair note
above).

```bash
curl -fsS http://127.0.0.1:7021/api/v2/session/interventions | python3 -c 'import json,sys; [print(f["flow_id"]) for f in json.load(sys.stdin)["flows"] if f["domain"] == "e2e-fake-site" and f["profile"] == "default"]' | while read id; do curl -sS -o /dev/null -w "%{http_code} $id\n" -X DELETE "http://127.0.0.1:7021/api/v2/session/interventions/$id"; done
```

```bash
for i in $(seq 1 90); do if [ "$(curl -fsS http://127.0.0.1:7021/api/v2/session/interventions | python3 -c 'import json,sys; print(json.load(sys.stdin)["active_flows"])')" = "0" ]; then break; fi; sleep 10; done; curl -fsS http://127.0.0.1:7021/api/v2/session/interventions
```

```bash
bru run "web-hunter/testing/challenge-verdicts/wall-definitive-header.yml" --env ascend-local
```

Close the row's window (the close command above), then drain before the next wall row (see repair note
above).

```bash
curl -fsS http://127.0.0.1:7021/api/v2/session/interventions | python3 -c 'import json,sys; [print(f["flow_id"]) for f in json.load(sys.stdin)["flows"] if f["domain"] == "e2e-fake-site" and f["profile"] == "default"]' | while read id; do curl -sS -o /dev/null -w "%{http_code} $id\n" -X DELETE "http://127.0.0.1:7021/api/v2/session/interventions/$id"; done
```

```bash
for i in $(seq 1 90); do if [ "$(curl -fsS http://127.0.0.1:7021/api/v2/session/interventions | python3 -c 'import json,sys; print(json.load(sys.stdin)["active_flows"])')" = "0" ]; then break; fi; sleep 10; done; curl -fsS http://127.0.0.1:7021/api/v2/session/interventions
```

```bash
bru run "web-hunter/testing/challenge-verdicts/wall-oversized.yml" --env ascend-local
```

Close the last wall row's window, then drain, so every window has ended before the content rows and the
after-output.

```bash
curl -fsS http://127.0.0.1:7021/api/v2/session/interventions | python3 -c 'import json,sys; [print(f["flow_id"]) for f in json.load(sys.stdin)["flows"] if f["domain"] == "e2e-fake-site" and f["profile"] == "default"]' | while read id; do curl -sS -o /dev/null -w "%{http_code} $id\n" -X DELETE "http://127.0.0.1:7021/api/v2/session/interventions/$id"; done
```

```bash
for i in $(seq 1 90); do if [ "$(curl -fsS http://127.0.0.1:7021/api/v2/session/interventions | python3 -c 'import json,sys; print(json.load(sys.stdin)["active_flows"])')" = "0" ]; then break; fi; sleep 10; done; curl -fsS http://127.0.0.1:7021/api/v2/session/interventions
```

Content rows. Send one request per row and wait for its answer before continuing.

```bash
bru run "web-hunter/testing/challenge-verdicts/content-widget-under-article.yml" --env ascend-local
```

```bash
bru run "web-hunter/testing/challenge-verdicts/content-article-japanese.yml" --env ascend-local
```

```bash
bru run "web-hunter/testing/challenge-verdicts/content-article-arabic.yml" --env ascend-local
```

```bash
bru run "web-hunter/testing/challenge-verdicts/content-captcha-word-in-prose.yml" --env ascend-local
```

```bash
bru run "web-hunter/testing/challenge-verdicts/content-403-rich-body.yml" --env ascend-local
```

Metrics row, after all ten rows above.

```bash
bru run "web-hunter/testing/challenge-verdicts/metrics-challenge.yml" --env ascend-local
```

Capture the metrics output after the run for the growth comparison.

**PowerShell:**

```powershell
curl.exe -fsS http://127.0.0.1:7021/metrics -o "$E2E_OUT\challenge-verdicts-after.txt"
```

**Unix:**

```bash
curl -fsS http://127.0.0.1:7021/metrics -o "$E2E_OUT/challenge-verdicts-after.txt"
```

Cleanup. Close any window still open for `e2e-fake-site:default`, then wait until every NoVNC flow the wall
rows opened has drained.

**PowerShell:**

```powershell
(Invoke-RestMethod http://127.0.0.1:7021/api/v2/session/interventions).flows | Where-Object { $_.domain -eq 'e2e-fake-site' -and $_.profile -eq 'default' } | ForEach-Object { "$((Invoke-WebRequest -Method Delete -SkipHttpErrorCheck -Uri "http://127.0.0.1:7021/api/v2/session/interventions/$($_.flow_id)").StatusCode) $($_.flow_id)" }
```

**Unix:**

```bash
curl -fsS http://127.0.0.1:7021/api/v2/session/interventions | python3 -c 'import json,sys; [print(f["flow_id"]) for f in json.load(sys.stdin)["flows"] if f["domain"] == "e2e-fake-site" and f["profile"] == "default"]' | while read id; do curl -sS -o /dev/null -w "%{http_code} $id\n" -X DELETE "http://127.0.0.1:7021/api/v2/session/interventions/$id"; done
```

Expect no line when every wall row's window was closed, or one line `204 <flow_id>` for each window still open.

**Unix:**

```bash
for i in $(seq 1 60); do if [ "$(curl -fsS http://127.0.0.1:7021/api/v2/session/interventions | python3 -c 'import json,sys; print(json.load(sys.stdin)["active_flows"])')" = "0" ]; then break; fi; sleep 10; done; curl -fsS http://127.0.0.1:7021/api/v2/session/interventions
```

**PowerShell:**

```powershell
for ($i = 0; $i -lt 60 -and ((Invoke-RestMethod http://127.0.0.1:7021/api/v2/session/interventions).active_flows) -ne 0; $i++) { Start-Sleep 10 }; Invoke-RestMethod http://127.0.0.1:7021/api/v2/session/interventions
```

Expect the final body to report `active_flows` `0`.

## Expected

- **`/wall-ko`:** HTTP 428. The problem body holds `code` `human_intervention_required`,
  `intervention_type` `captcha`, and a non-empty `vnc_url`.
- **`/wall-tr`:** HTTP 428. The problem body holds `code` `human_intervention_required`,
  `intervention_type` `login`, and a non-empty `vnc_url`.
- **`/wall-vendor-thin`:** HTTP 428. The problem body holds `code`
  `human_intervention_required` and a non-empty `vnc_url`.
- **`/wall-header`:** HTTP 428. The problem body holds `code` `human_intervention_required`
  and a non-empty `vnc_url`.
- **`/wall-oversized`:** HTTP 428. The problem body holds `code`
  `human_intervention_required` and a non-empty `vnc_url`.
- **`/captcha-wall`:** HTTP 200. The body holds `status` `success` and the canary sentence
  `"The QUARRY-THRUSH survey logged 47 nesting pairs along the basalt cliffs of Lake Mirell on June 9th."`.
- **`/article-ja`:** HTTP 200. The body holds `status` `success` and the canary sentence
  `"QUARRY-THRUSHの調査で47組の営巣を確認した。"`.
- **`/article-ar`:** HTTP 200. The body holds `status` `success` and the canary sentence
  `"سجل مسح QUARRY-THRUSH 47 زوجا معششا."`.
- **`/prose-captcha`:** HTTP 200. The body holds `status` `success`.
- **`/rich-403`:** any HTTP answer but 428. A 428 is a FAIL.
- **Metrics:** `challenge_verdicts_total` with `verdict="wall"` is at least 5 higher in the
  after-output than in the baseline, and with `verdict="content"` is at least 8 higher. The counter has
  one line per `tier` label, so add up the values of every matching line in each file before comparing.
  How the counts grow: every read tier, the static tiers, the browser tiers and the crawlee tier alike,
  counts one verdict, one score and one signal set per read under its own `tier` label. The crawlee tier
  judges a 403, 429 or 503 page once and counts one verdict per read under the `tier` label `crawlee`
  (`retry_on_blocked` is off and those statuses reach its handler in `src/reader/strategies/crawlee_strategy.py`).
  Before that change it retried such a page ten times and counted no verdict at all. The reader's second
  look then judges the page a tier returned once more and counts one more verdict, score and signal set
  under the `tier` label `reader` (`_second_look` in `src/reader/web_reader.py`). So one content read
  through a browser tier adds 2 content verdicts, one under that tier and one under `reader`, and the same
  holds for a content read through a static tier. The two static tiers, `1-beautifulsoup` and
  `2-trafilatura`, share one `tier` label, `curl_cffi`, because both fetch through the same curl_cffi fetcher.
  So a read that passes through both static tiers adds 2 verdicts under `curl_cffi`, not 1. The four gated
  content rows (`/captcha-wall`,
  `/article-ja`, `/article-ar`, `/prose-captcha`) therefore add at least 8, more when a read climbed past a
  tier that also judged the page as content. A wall page never reaches the second look, because the tier
  that judges it a wall stops the read, so one wall page adds one wall verdict for each tier it passed
  before it opens a NoVNC window, and never less than one. A NoVNC window records one more verdict, from
  its last check, under the `tier` label `novnc-monitor` when the window ends, not on every recheck while
  it is open. That last check judges the rendered page with the status and headers of the main frame
  response, so a header-only wall such as the `cf-mitigated: challenge` 403 of `/wall-header` ends as a
  wall verdict, not as content. This spec closes every window before the after-output is captured, so each
  window that made at least one check before its close adds one wall verdict under `novnc-monitor`, and no
  window adds a content verdict. So each of the 5 wall pages adds at least one wall verdict, and the exact
  total depends on how many tiers each read used and on how many windows made a check before their close:

  **PowerShell:**

  ```powershell
  Select-String -Path "$E2E_OUT\challenge-verdicts-before.txt", "$E2E_OUT\challenge-verdicts-after.txt" -Pattern 'challenge_verdicts_total\{[^}]*verdict="wall"'
  ```

  ```powershell
  Select-String -Path "$E2E_OUT\challenge-verdicts-before.txt", "$E2E_OUT\challenge-verdicts-after.txt" -Pattern 'challenge_verdicts_total\{[^}]*verdict="content"'
  ```

  **Unix:**

  ```bash
  grep 'challenge_verdicts_total{[^}]*verdict="wall"' "$E2E_OUT/challenge-verdicts-before.txt" "$E2E_OUT/challenge-verdicts-after.txt"
  ```

  ```bash
  grep 'challenge_verdicts_total{[^}]*verdict="content"' "$E2E_OUT/challenge-verdicts-before.txt" "$E2E_OUT/challenge-verdicts-after.txt"
  ```

  No window ends as content: the `challenge_verdicts_total` line with `verdict="content"` and
  `tier="novnc-monitor"` has the same value in both files, or is absent from both. A higher value in the
  after-output is a FAIL, because a window judged a wall page, `/wall-header` among them, as content.

  **PowerShell:**

  ```powershell
  Select-String -Path "$E2E_OUT\challenge-verdicts-before.txt", "$E2E_OUT\challenge-verdicts-after.txt" -Pattern 'challenge_verdicts_total\{(?=[^}]*tier="novnc-monitor")(?=[^}]*verdict="content")'
  ```

  **Unix:**

  ```bash
  grep 'challenge_verdicts_total{[^}]*' "$E2E_OUT/challenge-verdicts-before.txt" "$E2E_OUT/challenge-verdicts-after.txt" | grep 'tier="novnc-monitor"' | grep 'verdict="content"'
  ```

  Every `vendor` label value on the `challenge_signals_fired_total` lines of the after-output
  is a catalogue vendor name or `none`:

  **PowerShell:**

  ```powershell
  Select-String -Path "$E2E_OUT\challenge-verdicts-after.txt" -Pattern 'challenge_signals_fired_total\{[^}]*\}' -AllMatches | ForEach-Object { $_.Matches.Value } | Select-String -Pattern 'vendor="[^"]*"' -AllMatches | ForEach-Object { $_.Matches.Value } | Sort-Object -Unique
  ```

  **Unix:**

  ```bash
  grep -o 'challenge_signals_fired_total{[^}]*}' "$E2E_OUT/challenge-verdicts-after.txt" | grep -o 'vendor="[^"]*"' | sort -u
  ```

- **Cleanup:** the final `GET /api/v2/session/interventions` body reports `active_flows` `0`.

Every assertion above is an HTTP status, a response body, or `/metrics`.

## Post-run cleanup

After the Expected checks have read them, remove the report directory and the two metrics files in it.

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

None checked in. The fake site pages `/wall-ko`, `/wall-tr`, `/wall-vendor-thin`, `/wall-header`,
`/wall-oversized`, `/captcha-wall`, `/article-ja`, `/article-ar`, `/prose-captcha` and `/rich-403`
carry the canaries, all indexed in [fixtures/README.md](../fixtures/README.md).

## Concurrency

Each wall row opens a NoVNC flow. This spec does not run beside the concurrent intervention spec of
`open-several-novnc-windows-at-once` or any spec that can answer a 428. Its reads write
`tier_memory:e2e-fake-site`, the key spec 18 ([18-tier-ladder-and-guard-test.md](18-tier-ladder-and-guard-test.md))
also writes and asserts on, so not beside spec 18 either. Not beside spec 13
([13-structured-extraction-test.md](13-structured-extraction-test.md)) either, whose reads write the same key, so a
wall or content row could start from its remembered tier. Its reset empties the service's read cache for the
fake site, so not beside a spec whose fake site reads would lose their cached answer mid-run. Not beside
spec 21 ([21-platform-contract-test.md](21-platform-contract-test.md)) either, whose `session_interventions`
calls expect `active_flows` `0` while a wall row's window is open.

- Serial: false
