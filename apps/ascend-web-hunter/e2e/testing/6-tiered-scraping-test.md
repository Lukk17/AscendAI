# Tiered web scraping: e2e test

## What this verifies

This test drives `POST /api/v2/web/read` against a tier-mapped list of real websites. Each URL is chosen to force
a specific extraction tier so a per-tier regression is caught. The list is **provisional** - live external sites
rotate WAFs and go down, so refine it as real targets are discovered.

| Row | Tier / strategy | URL | Canary assertion | In automated gate |
| :-- | :-------------- | :-- | :--------------- | :---------------- |
| 1 | `curl_cffi` - static article | `https://en.wikipedia.org/wiki/Web_scraping` | content (lowercased) contains `"web scraping"` | yes |
| 2 | Browser tier - Cloudflare WAF | `https://www.scrapingcourse.com/cloudflare-challenge` | `status="success"` with `"cloudflare challenge"` in the content, or HTTP 428 with a `vnc_url` when the site rates and gates this address | yes |
| 3 | Playwright - JS-rendered | `https://quotes.toscrape.com/js/` | content contains `"The world as we have created it"`, and the serving `mode` is a browser tier | yes |
| 4 | NoVNC - hard CAPTCHA | covered by spec 11, `11-captcha-solve-and-capture-test.md` (owner decision 65.26 of 2026-10-04) | human solves CAPTCHA, content returned | no - manual, run in spec 11 |
| 5-8 | real-world categories | covered by spec 7 Part 1, `7-authenticated-realworld-scraping-test.md` (owner decision 65.26 of 2026-10-04) | per-site, as spec 7 defines | no - run in spec 7 |

Row 2's target, scrapingcourse.com, rates the caller's address. After several challenge solves from one address in a
day it can refuse headless browsers for a while. A row 2 failure after a tens-of-seconds browser-tier solve is
a cool-down case, not a stack defect: rerun the spec after about 40 minutes, and do not probe the address in between,
because every attempt counts against the rating. When the address stays rated, the row accepts HTTP 428 with a
non-empty `vnc_url` in place of the solved page, because that is the service answering correctly with the human-help
tier rather than returning the block page as content. Measured 2026-11-03, after days of no probing, the address was
still gated and the row answered 428.

- `POST /api/v2/web/read` returns HTTP 200 with `status="success"` and a non-empty content field
  (`content` / `text` / `markdown`) for each gated row (1, 2, 3), or, for row 2 only, HTTP 428 with `code`
  `human_intervention_required` and a non-empty `vnc_url`.
- **Row 1 (static):** the content field, lowercased, contains `"web scraping"`.
- **Row 2 (Cloudflare):** either `status="success"` and a content field of length ≥ 50 containing
  `"cloudflare challenge"`, which proves the challenge was solved rather than the block interstitial returned, or the
  428 human-help body when the address is rated.
- **Row 3 (JavaScript):** the content field contains `"The world as we have created it"` and the response's `mode`
  names a browser-executing tier. The phrase is absent from the page's raw markup once inline `<script>` blocks are
  stripped, so its presence in extracted prose means a browser ran the page's JavaScript.
- Every row that answers HTTP 200 has the same response shape (`url`, `content`, `status`, `mode`). Only the `mode` value differs, naming the tier that succeeded. A row 2 answer of HTTP 428 is the problem body instead.
- **Row 4 (CAPTCHA):** documented here but excluded from the pass/fail verdict; it requires human interaction via
  the NoVNC/Ngrok path and cannot be asserted unattended.

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

Check outbound HTTPS to the static target works from this host (independently of the container).

```bash
curl -fsS https://en.wikipedia.org/wiki/Web_scraping
```

Expect HTTP 200 with article HTML. If this fails, the host cannot reach the public internet and the test cannot
pass.

Confirm the JavaScript target's canary phrase is not already present in its raw markup, so row 3's assertion
means something. Strip inline `<script>` blocks first, then look for the phrase.

**PowerShell:**

```powershell
((Invoke-WebRequest -Uri "https://quotes.toscrape.com/js/" -UseBasicParsing).Content -replace '(?s)<script.*?</script>', '') -match 'The world as we have created it'
```

**Unix:**

```bash
curl -fsS "https://quotes.toscrape.com/js/" | perl -0777 -pe 's/<script[^>]*>.*?<\/script>//gs' | grep -c "The world as we have created it"
```

Expect `False` from the PowerShell command and `0` from the Unix command, which counts the matching lines.

The strip is the whole point of this check. The page ships its ten quotes as a JavaScript array literal inside an
inline `<script>` block and calls `document.write()` to build the visible DOM from it, so the canary phrase sits in
the raw response as literal source text whether or not any JavaScript ever runs. A plain `curl` piped to a grep
matches it and proves nothing. Dropping `<script>` contents leaves only the markup a non-executing client would
see, and there the phrase is genuinely absent.

To see the difference for yourself, run the same expression without the strip. Expect `True` from the PowerShell
command and `1` from the Unix command, because the phrase sits on one line of the inline script.

**PowerShell:**

```powershell
(Invoke-WebRequest -Uri "https://quotes.toscrape.com/js/" -UseBasicParsing).Content -match 'The world as we have created it'
```

**Unix:**

```bash
curl -fsS "https://quotes.toscrape.com/js/" | grep -c "The world as we have created it"
```

## Reset state

Optional. Flush the Redis session-cache keys for the target domains to force cold extractions through the full
tiered fallback. Not required - the response shape is identical for cache hits and misses. Run one block per
domain; document the choice under **Additional tasks I did** if you skip it.

Close every NoVNC window this spec's sites still hold before the deletes. A row that answers 428 opens a NoVNC
flow that stays open up to its timeout, and the browser in that window can still pass the challenge on its own and
save a session for the site after the deletes ran (seen 2026-11-06: a spec 6 flow saved
`session:scrapingcourse.com:default` after the spec's cleanup). `DELETE /api/v2/session/interventions/{flow_id}`
closes one window at once, saves nothing from it and frees its slot, so the spec no longer waits for the window to
time out. List the open flows and close each one whose `domain` (the registrable domain) is `wikipedia.org`,
`scrapingcourse.com` or `toscrape.com`, in one command.

**PowerShell:**

```powershell
(Invoke-RestMethod http://127.0.0.1:7021/api/v2/session/interventions).flows | Where-Object { $_.domain -in @('wikipedia.org','scrapingcourse.com','toscrape.com') } | ForEach-Object { "$((Invoke-WebRequest -Method Delete -SkipHttpErrorCheck -Uri "http://127.0.0.1:7021/api/v2/session/interventions/$($_.flow_id)").StatusCode) $($_.flow_id)" }
```

**Unix:**

```bash
curl -fsS http://127.0.0.1:7021/api/v2/session/interventions | python3 -c 'import json,sys; [print(f["flow_id"]) for f in json.load(sys.stdin)["flows"] if f["domain"] in ("wikipedia.org","scrapingcourse.com","toscrape.com")]' | while read id; do curl -sS -o /dev/null -w "%{http_code} $id\n" -X DELETE "http://127.0.0.1:7021/api/v2/session/interventions/$id"; done
```

Expect one line `204 <flow_id>` for each window closed, and no line when no such window was open. A `404` line
means the window ended on its own between the listing and the delete, and is accepted only when the listing below
no longer shows that flow. Then list the flows again.

PowerShell:

```powershell
Invoke-RestMethod http://127.0.0.1:7021/api/v2/session/interventions
```

Unix:

```bash
curl -fsS http://127.0.0.1:7021/api/v2/session/interventions
```

Expect the body to list no flow for those three domains. If one is still listed, record it under Additional tasks
I did and stop, because the run cannot start from a clean state.

Scan by the registrable domain, never by the host. Every Redis key a read writes is named after the registrable
domain of the URL: `session:<domain>:<profile>`, `tier_memory:<domain>`, `recipe:<domain>:<digest>` and
`novnc_window_result:<domain>:<profile>` (`src/reader/cloudflare/cookie_manager.py:199`, `src/reader/tier_memory.py:26`,
`src/reader/recipe_store.py:34`, `src/reader/novnc/flow_registry.py:495`). A read that answers 428 opens a NoVNC
window, which holds `novnc_flow:<domain>:<profile>` while it is open (`src/reader/novnc/flow_registry.py:82`). Closing
the window, or the window ending on its own, writes `novnc_window_result:<domain>:<profile>`, so the close above
leaves that key behind. `en.wikipedia.org` writes under `wikipedia.org` and `quotes.toscrape.com` under
`toscrape.com`, and each `*<domain>*` pattern below deletes every one of these keys for its site,
`novnc_window_result:` included. No Redis key is named by host. The only store keyed by the full URL is the in-process read cache, which a Redis delete cannot reach.

PowerShell:

```powershell
docker exec redis redis-cli --scan --pattern "*wikipedia.org*" | ForEach-Object { docker exec redis redis-cli DEL $_ }
```

Unix:

```bash
docker exec redis redis-cli --scan --pattern "*wikipedia.org*" | while read key; do docker exec redis redis-cli DEL "$key"; done
```

**PowerShell:**

```powershell
docker exec redis redis-cli --scan --pattern "*scrapingcourse.com*" | ForEach-Object { docker exec redis redis-cli DEL $_ }
```

**Unix:**

```bash
docker exec redis redis-cli --scan --pattern "*scrapingcourse.com*" | while read key; do docker exec redis redis-cli DEL "$key"; done
```

**PowerShell:**

```powershell
docker exec redis redis-cli --scan --pattern "*toscrape.com*" | ForEach-Object { docker exec redis redis-cli DEL $_ }
```

**Unix:**

```bash
docker exec redis redis-cli --scan --pattern "*toscrape.com*" | while read key; do docker exec redis redis-cli DEL "$key"; done
```

Then clear the in-process read cache, which the Redis deletes above cannot reach. Without this step a read can come
from memory and never climb the tier ladder. Send one `POST /api/v2/web/session/clear` per site. The service takes a
`url`, works out its registrable domain, and drops every cached read whose URL has that domain
(`clear_session` in `src/api/rest/rest_endpoints.py`), so each call below uses this spec's own URL for that site.

wikipedia.org, PowerShell:

```powershell
curl.exe -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/clear -H "Content-Type: application/json" -d '{"url":"https://en.wikipedia.org/wiki/Web_scraping","profile":"default"}'
```

wikipedia.org, Unix:

```bash
curl -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/clear -H "Content-Type: application/json" -d '{"url":"https://en.wikipedia.org/wiki/Web_scraping","profile":"default"}'
```

scrapingcourse.com, PowerShell:

```powershell
curl.exe -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/clear -H "Content-Type: application/json" -d '{"url":"https://www.scrapingcourse.com/cloudflare-challenge","profile":"default"}'
```

scrapingcourse.com, Unix:

```bash
curl -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/clear -H "Content-Type: application/json" -d '{"url":"https://www.scrapingcourse.com/cloudflare-challenge","profile":"default"}'
```

toscrape.com, PowerShell:

```powershell
curl.exe -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/clear -H "Content-Type: application/json" -d '{"url":"https://quotes.toscrape.com/js/","profile":"default"}'
```

toscrape.com, Unix:

```bash
curl -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/clear -H "Content-Type: application/json" -d '{"url":"https://quotes.toscrape.com/js/","profile":"default"}'
```

Expect HTTP 200 with `status="cleared"` from each call. `existed` is `false` after the deletes above, and a non-zero
`cleared_cache_entries` is the cache being emptied, not a failure.

## Run

Move into the Bruno collection root first.

```bash
cd docs/api/request/AscendAI
```

Step 1 - static tier (row 1). Send the request and wait for HTTP 200 before continuing.

```bash
bru run "web-hunter/testing/extract-tier-static-wikipedia.yml" --env ascend-local
```

Step 2 - Cloudflare tier (row 2). Send the request and wait for HTTP 200, or HTTP 428 when the site gates this
address, before continuing.

```bash
bru run "web-hunter/testing/extract-tier-cloudflare.yml" --env ascend-local
```

Bruno's console output never prints the response body, so Step 3 captures it to a report file. Write it into a
new private directory, never a fixed path under `/tmp` or `$env:TEMP`, so two runs never share a file. Create it
once, in the same shell Steps 3 and 4 run in.

**PowerShell:**

```powershell
$E2E_OUT = (New-Item -ItemType Directory -Path (Join-Path ([IO.Path]::GetTempPath()) ([IO.Path]::GetRandomFileName()))).FullName
```

**Unix:**

```bash
E2E_OUT="$(mktemp -d)"
```

Step 3 - JavaScript tier (row 3). Send the request and wait for HTTP 200 before continuing.

**PowerShell:**

```powershell
bru run "web-hunter/testing/extract-tier-js-quotes.yml" --env ascend-local -o "$E2E_OUT\js-quotes-run.json" -f json
```

**Unix:**

```bash
bru run "web-hunter/testing/extract-tier-js-quotes.yml" --env ascend-local -o "$E2E_OUT/js-quotes-run.json" -f json
```

Step 4. Read back which tier served row 3. Bruno's console output never prints the response body, so this is what
makes the `mode` assertion checkable.

**PowerShell:**

```powershell
(Get-Content "$E2E_OUT\js-quotes-run.json" -Raw | ConvertFrom-Json)[0].results[0].response.data.mode
```

**Unix:**

```bash
"$(command -v python3 || command -v python)" -c "import json, sys; d = json.load(open(sys.argv[1])); print(d[0]['results'][0]['response']['data']['mode'])" "$E2E_OUT/js-quotes-run.json"
```

Remove the report directory once the `mode` is recorded. Nothing after this point reads it.

**PowerShell:**

```powershell
Remove-Item -Recurse -Force $E2E_OUT
```

**Unix:**

```bash
rm -rf "$E2E_OUT"
```

## Expected

Steps 1 and 3 return HTTP 200 with a JSON object body. Step 2 (row 2) passes with either of two answers:

- HTTP 200 with a JSON object body, the solved page.
- HTTP 428 with an `application/problem+json` body whose `code` is `human_intervention_required` and whose
  `vnc_url` is a non-empty string, the human-help answer when the site rates and gates this address.

For every gated row that answers HTTP 200, the body has:

- `url` equal to the requested URL.
- `status` equal to `"success"`.
- A content-carrying string field present - one of `content`, `text`, or `markdown` - with length ≥ 50.

Per-row canary assertions:

- **Row 1:** the populated content field, lowercased, contains `"web scraping"`.
- **Row 2:** on HTTP 200, `status` equals `"success"`, the content field length is ≥ 50 and the content field,
  lowercased, contains `"cloudflare challenge"`. This proves the Cloudflare challenge was solved, because the
  bot-block page is short and would fail this bound. On HTTP 428, the body has `code` `human_intervention_required`
  and a non-empty `vnc_url`. Either answer passes. A duration in the tens of seconds is normal for a browser-tier
  solve - log it but do not fail on duration alone.
- **Row 3:** the populated content field contains the substring `"The world as we have created it"`, and the
  `mode` printed by Run step 4 is one of `4-playwright_stealth`, `4a-patchright`, `4b-camoufox`,
  `5-crawlee_adaptive`, or the
  NoVNC tier. It is never `1-beautifulsoup` or `2-trafilatura`. Those two lightweight tiers do not execute
  JavaScript, so a browser-tier `mode` plus the canary phrase in extracted prose is the proof that the DOM was
  rendered. The tier that serves this row varies between runs (both `4-playwright_stealth` and the patched
  browser tiers have served it), so assert the set, not one value.

A gated row that returns HTTP 200 but `status != "success"`, or an empty/short content field, or a missing canary
phrase, fails the test. Rows 1 and 3 fail on any status other than 200. Row 2 fails on any status other than 200
or 428, and on a 428 body whose `code` is not `human_intervention_required` or whose `vnc_url` is empty. Row 4 (CAPTCHA) is recorded under **Additional tasks I did**, never in the verdict.

## Post-run cleanup

When row 2 answered 428, its NoVNC flow is still open and can save `session:scrapingcourse.com:default` later, which
spec 12 then meets as a clearance it did not obtain. Close the windows of this spec's three sites the same way as
Reset state, then delete every key the spec can write for its three sites, by registrable domain as in Reset state,
so no late write can survive the cleanup. The deletes include the `novnc_window_result:<domain>:<profile>` key that
the close writes.

PowerShell:

```powershell
(Invoke-RestMethod http://127.0.0.1:7021/api/v2/session/interventions).flows | Where-Object { $_.domain -in @('wikipedia.org','scrapingcourse.com','toscrape.com') } | ForEach-Object { "$((Invoke-WebRequest -Method Delete -SkipHttpErrorCheck -Uri "http://127.0.0.1:7021/api/v2/session/interventions/$($_.flow_id)").StatusCode) $($_.flow_id)" }
```

Unix:

```bash
curl -fsS http://127.0.0.1:7021/api/v2/session/interventions | python3 -c 'import json,sys; [print(f["flow_id"]) for f in json.load(sys.stdin)["flows"] if f["domain"] in ("wikipedia.org","scrapingcourse.com","toscrape.com")]' | while read id; do curl -sS -o /dev/null -w "%{http_code} $id\n" -X DELETE "http://127.0.0.1:7021/api/v2/session/interventions/$id"; done
```

Expect one line `204 <flow_id>` for each window closed (a `404` only for a window that ended on its own, as in Reset
state). Then list the flows again.

PowerShell:

```powershell
Invoke-RestMethod http://127.0.0.1:7021/api/v2/session/interventions
```

Unix:

```bash
curl -fsS http://127.0.0.1:7021/api/v2/session/interventions
```

Expect the body to list no flow for those three domains.

PowerShell:

```powershell
docker exec redis redis-cli --scan --pattern "*wikipedia.org*" | ForEach-Object { docker exec redis redis-cli DEL $_ }
```

Unix:

```bash
docker exec redis redis-cli --scan --pattern "*wikipedia.org*" | while read key; do docker exec redis redis-cli DEL "$key"; done
```

PowerShell:

```powershell
docker exec redis redis-cli --scan --pattern "*scrapingcourse.com*" | ForEach-Object { docker exec redis redis-cli DEL $_ }
```

Unix:

```bash
docker exec redis redis-cli --scan --pattern "*scrapingcourse.com*" | while read key; do docker exec redis redis-cli DEL "$key"; done
```

PowerShell:

```powershell
docker exec redis redis-cli --scan --pattern "*toscrape.com*" | ForEach-Object { docker exec redis redis-cli DEL $_ }
```

Unix:

```bash
docker exec redis redis-cli --scan --pattern "*toscrape.com*" | while read key; do docker exec redis redis-cli DEL "$key"; done
```

## Fixtures

None. The read tool takes a URL string; the "fixtures" are the live external URLs in the tier table above.

## Concurrency

- **Mutates:** Redis keys named by the registrable domain of this test's targets (`wikipedia.org`,
  `scrapingcourse.com`, `toscrape.com`, and any real-world category sites added later). The reads of rows 1 and 2
  write `tier_memory:wikipedia.org` and `tier_memory:scrapingcourse.com`. Row 3 reads with `heavy_mode` true, and a
  `heavy_mode` read writes no tier memory (`_remember_tier` in `src/reader/web_reader.py`), so the spec writes no
  `tier_memory:toscrape.com`, and only its reset deletes one an earlier read left. When row 2 answers 428, the read
  also writes the NoVNC window record, and the close writes the window result. An automatic browser read that saw a
  wall and ended accepted saves the site's `cf_clearance` to `session:<domain>:<profile>` with no window opened
  (`_save_earned_clearance` in `src/reader/strategies/browser_read.py`), so when row 2 answers 200 after a wall it
  writes `session:scrapingcourse.com:default`. The only other writer this spec can start is a NoVNC window that ends after a
  solve or a login, and this spec closes its window, which saves nothing. The reset and the Post-run cleanup delete every key of
  the three domains, `session:*` included.
- **Conflicts with:** any other test that reads or scrapes the same target URLs and may flush their Redis keys. In
  the current suite there is no overlap with test 3 (`example.com`) unless `example.com` is added to this table.
  Spec 12 ([12-clearance-reuse-test.md](12-clearance-reuse-test.md)) may not run at the same time as this spec: both
  write and delete `session:scrapingcourse.com:default`, so one run would hand the other a clearance it did not
  obtain or wipe the one it did. Does not conflict with the search tests (1, 2, 4, 5).
- **Serial:** false.
