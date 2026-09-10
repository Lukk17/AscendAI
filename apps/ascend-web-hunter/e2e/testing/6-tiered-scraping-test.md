# Tiered web scraping: e2e test

## What this verifies

This test drives `POST /api/v2/web/read` against a tier-mapped list of real websites. Each URL is chosen to force
a specific extraction tier so a per-tier regression is caught. The list is **provisional** — live external sites
rotate WAFs and go down, so refine it as real targets are discovered.

| Row | Tier / strategy | URL | Canary assertion | In automated gate |
| :-- | :-------------- | :-- | :--------------- | :---------------- |
| 1 | `curl_cffi` — static article | `https://en.wikipedia.org/wiki/Web_scraping` | content (lowercased) contains `"web scraping"` | yes |
| 2 | FlareSolverr — Cloudflare WAF | `https://www.scrapingcourse.com/cloudflare-challenge` | `status="success"`, content contains `"cloudflare challenge"` (FlareSolverr bypassed the challenge) | yes |
| 3 | Playwright — JS-rendered | `https://quotes.toscrape.com/js/` | content contains `"The world as we have created it"`, and the serving `mode` is a browser tier | yes |
| 4 | NoVNC — hard CAPTCHA | *TBD* | human solves CAPTCHA, content returned | **no — manual / best-effort** |
| 5–8 | real-world categories | *TBD* (job board, news article, product page, docs page) | per-site, defined when added | no — added later |

Row 2's target, scrapingcourse.com, rates the caller's address. After several challenge solves from one address in a
day it can refuse headless browsers for a while: measured on 2026-09-10, FlareSolverr timed out on the "Just a moment"
page after 58 seconds three times in a row between 16:43 and 16:52 UTC while it cleared nowsecure.nl in 14 seconds,
and it cleared scrapingcourse.com again in 17 seconds at 17:31 UTC. A row 2 failure with that FlareSolverr log line is
a cool-down case, not a stack defect: rerun the spec after about 40 minutes, and do not probe the address in between,
because every attempt counts against the rating. The FlareSolverr log line to look for is this one, verbatim:

```text
Error: Error solving the challenge. Timeout after 58.0 seconds.
```

- `POST /api/v2/web/read` returns HTTP 200 with `status="success"` and a non-empty content field
  (`content` / `text` / `markdown`) for each gated row (1, 2, 3).
- **Row 1 (static):** the content field, lowercased, contains `"web scraping"`.
- **Row 2 (Cloudflare):** `status="success"` and a content field of length ≥ 50 — proves the Cloudflare challenge
  was solved rather than the bot-block interstitial being returned.
- **Row 3 (JavaScript):** the content field contains `"The world as we have created it"` and the response's `mode`
  names a browser-executing tier. The phrase is absent from the page's raw markup once inline `<script>` blocks are
  stripped, so its presence in extracted prose means a browser ran the page's JavaScript.
- The response shape is identical across all three rows (`url`, `content`, `status`, `mode`). Only the `mode` value differs, naming the tier that succeeded.
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
curl -fsS http://localhost:7021/health
```

Expect HTTP 200 with `{"status":"ok"}`.

Check FlareSolverr is reachable (required for the Cloudflare tier, row 2).

```bash
curl -fsS http://localhost:8191/
```

Expect HTTP 200 with a JSON body announcing FlareSolverr. If this fails, row 2 cannot pass for environmental
reasons.

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

Expect `False`.

The strip is the whole point of this check. The page ships its ten quotes as a JavaScript array literal inside an
inline `<script>` block and calls `document.write()` to build the visible DOM from it, so the canary phrase sits in
the raw response as literal source text whether or not any JavaScript ever runs. A plain `curl` piped to a grep
matches it and proves nothing. Dropping `<script>` contents leaves only the markup a non-executing client would
see, and there the phrase is genuinely absent.

To see the difference for yourself, run the same expression without the strip and expect `True`.

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
tiered fallback. Not required — the response shape is identical for cache hits and misses. Run one block per
domain; document the choice under **Additional tasks I did** if you skip it.

**PowerShell:**

```powershell
docker exec redis redis-cli --scan --pattern "*en.wikipedia.org*" | ForEach-Object { docker exec redis redis-cli DEL $_ }
```

**Unix:**

```bash
docker exec redis redis-cli --scan --pattern "*en.wikipedia.org*" | while read key; do docker exec redis redis-cli DEL "$key"; done
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
docker exec redis redis-cli --scan --pattern "*quotes.toscrape.com*" | ForEach-Object { docker exec redis redis-cli DEL $_ }
```

**Unix:**

```bash
docker exec redis redis-cli --scan --pattern "*quotes.toscrape.com*" | while read key; do docker exec redis redis-cli DEL "$key"; done
```

## Run

Move into the Bruno collection root first.

```bash
cd docs/api/request/AscendAI
```

Step 1 — static tier (row 1). Send the request and wait for HTTP 200 before continuing.

```bash
bru run "web-hunter/testing/extract-tier-static-wikipedia.yml" --env ascend-local
```

Step 2 — Cloudflare tier (row 2). Send the request and wait for HTTP 200 before continuing.

```bash
bru run "web-hunter/testing/extract-tier-cloudflare.yml" --env ascend-local
```

Step 3 — JavaScript tier (row 3). Send the request and wait for HTTP 200 before continuing.

**PowerShell:**

```powershell
bru run "web-hunter/testing/extract-tier-js-quotes.yml" --env ascend-local -o "$env:TEMP\js-quotes-run.json" -f json
```

**Unix:**

```bash
bru run "web-hunter/testing/extract-tier-js-quotes.yml" --env ascend-local -o "/tmp/js-quotes-run.json" -f json
```

Step 4. Read back which tier served row 3. Bruno's console output never prints the response body, so this is what
makes the `mode` assertion checkable.

**PowerShell:**

```powershell
(Get-Content "$env:TEMP\js-quotes-run.json" -Raw | ConvertFrom-Json)[0].results[0].response.data.mode
```

**Unix:**

```bash
python3 -c "import json, sys; d = json.load(open('/tmp/js-quotes-run.json')); print(d[0]['results'][0]['response']['data']['mode'])"
```

## Expected

Each step returns HTTP 200 with a JSON object body.

For every gated row, the body has:

- `url` equal to the requested URL.
- `status` equal to `"success"`.
- A content-carrying string field present — one of `content`, `text`, or `markdown` — with length ≥ 50.

Per-row canary assertions:

- **Row 1:** the populated content field, lowercased, contains `"web scraping"`.
- **Row 2:** `status` equals `"success"` and the content field length is ≥ 50 (the Cloudflare challenge was
  solved; the bot-block page is short and would fail this bound). A duration in the tens of seconds is normal for
  the FlareSolverr tier — log it but do not fail on duration alone.
- **Row 3:** the populated content field contains the substring `"The world as we have created it"`, and the
  `mode` printed by Run step 4 is one of `3-flaresolverr`, `4-playwright_stealth`, `5-crawlee_adaptive`, or the
  NoVNC tier. It is never `1-beautifulsoup` or `2-trafilatura`. Those two lightweight tiers do not execute
  JavaScript, so a browser-tier `mode` plus the canary phrase in extracted prose is the proof that the DOM was
  rendered. The tier that serves this row varies between runs (both `3-flaresolverr` and `4-playwright_stealth`
  have served it), so assert the set, not one value.

A gated row that returns HTTP 200 but `status != "success"`, or an empty/short content field, or a missing canary
phrase, fails the test. Row 4 (CAPTCHA) is recorded under **Additional tasks I did**, never in the verdict.

## Fixtures

None. The read tool takes a URL string; the "fixtures" are the live external URLs in the tier table above.

## Concurrency

- **Mutates:** Redis — ascend-web-hunter session / cookie cache, keys for this test's target domains
  (`en.wikipedia.org`, `scrapingcourse.com`, `quotes.toscrape.com`, and any real-world category sites added later). The
  extraction pipeline writes per-domain session cookies on a successful fetch.
- **Conflicts with:** any other test that reads or scrapes the same target URLs and may flush their Redis keys. In
  the current suite there is no overlap with test 3 (`example.com`) unless `example.com` is added to this table.
  Does not conflict with the search tests (1, 2, 4, 5).
- **Serial:** false.
