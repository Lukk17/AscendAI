# Tiered web scraping: e2e test

## What this verifies

This test drives `POST /api/v2/web/read` against a tier-mapped list of real websites. Each URL is chosen to force
a specific extraction tier so a per-tier regression is caught. The list is **provisional** — live external sites
rotate WAFs and go down, so refine it as real targets are discovered.

| Row | Tier / strategy | URL | Canary assertion | In automated gate |
| :-- | :-------------- | :-- | :--------------- | :---------------- |
| 1 | `curl_cffi` — static article | `https://en.wikipedia.org/wiki/Web_scraping` | content (lowercased) contains `"web scraping"` | yes |
| 2 | FlareSolverr — Cloudflare WAF | `https://www.scrapingcourse.com/cloudflare-challenge` | `status="success"`, content contains `"cloudflare challenge"` (FlareSolverr bypassed the challenge) | yes |
| 3 | Playwright — JS-rendered | `https://quotes.toscrape.com/js/` | content contains `"The world as we have created it"`, which is **absent** from the raw (non-JS) HTML | yes |
| 4 | NoVNC — hard CAPTCHA | *TBD* | human solves CAPTCHA, content returned | **no — manual / best-effort** |
| 5–8 | real-world categories | *TBD* (job board, news article, product page, docs page) | per-site, defined when added | no — added later |

- `POST /api/v2/web/read` returns HTTP 200 with `status="success"` and a non-empty content field
  (`content` / `text` / `markdown`) for each gated row (1, 2, 3).
- **Row 1 (static):** the content field, lowercased, contains `"web scraping"`.
- **Row 2 (Cloudflare):** `status="success"` and a content field of length ≥ 50 — proves the Cloudflare challenge
  was solved rather than the bot-block interstitial being returned.
- **Row 3 (JavaScript):** the content field contains `"The world as we have created it"`; a direct host-side
  `curl` of the same URL does **not** contain that phrase — proving JS execution rendered the DOM.
- The response shape is identical across all three rows; the caller never learns which tier served the request.
- **Row 4 (CAPTCHA):** documented here but excluded from the pass/fail verdict; it requires human interaction via
  the NoVNC/Ngrok path and cannot be asserted unattended.

## Prerequisites

Check Bruno CLI is installed.

```powershell
bru --version
```

Expect a version string.

Check the ascend-web-hunter server is reachable.

```powershell
curl -fsS http://localhost:7021/health
```

Expect HTTP 200 with `{"status":"ok"}`.

Check FlareSolverr is reachable (required for the Cloudflare tier, row 2).

```powershell
curl -fsS http://localhost:8191/
```

Expect HTTP 200 with a JSON body announcing FlareSolverr. If this fails, row 2 cannot pass for environmental
reasons.

Check outbound HTTPS to the static target works from this host (independently of the container).

```powershell
curl -fsS https://en.wikipedia.org/wiki/Web_scraping
```

Expect HTTP 200 with article HTML. If this fails, the host cannot reach the public internet and the test cannot
pass.

Capture the raw (non-JS) HTML of the JavaScript target, to later prove JS rendering added content.

```powershell
curl -fsS https://quotes.toscrape.com/js/
```

Expect HTTP 200. The returned HTML should NOT contain the plain phrase `The world as we have created it` (the
quotes are injected by client-side JavaScript), confirming row 3's assertion is meaningful.

## Reset state

Optional. Flush the Redis session-cache keys for the target domains to force cold extractions through the full
tiered fallback. Not required — the response shape is identical for cache hits and misses. Run one block per
domain; document the choice under **Additional tasks I did** if you skip it.

```powershell
docker exec redis redis-cli --scan --pattern "*en.wikipedia.org*" | ForEach-Object { docker exec redis redis-cli DEL $_ }
```

```powershell
docker exec redis redis-cli --scan --pattern "*scrapingcourse.com*" | ForEach-Object { docker exec redis redis-cli DEL $_ }
```

```powershell
docker exec redis redis-cli --scan --pattern "*quotes.toscrape.com*" | ForEach-Object { docker exec redis redis-cli DEL $_ }
```

## Run

Move into the Bruno collection root first.

```powershell
cd docs/api/request/AscendAI
```

Step 1 — static tier (row 1). Send the request and wait for HTTP 200 before continuing.

```powershell
bru run "web-hunter/testing/extract-tier-static-wikipedia.yml" --env ascend-local
```

Step 2 — Cloudflare tier (row 2). Send the request and wait for HTTP 200 before continuing.

```powershell
bru run "web-hunter/testing/extract-tier-cloudflare.yml" --env ascend-local
```

Step 3 — JavaScript tier (row 3). Send the request and wait for HTTP 200 before continuing.

```powershell
bru run "web-hunter/testing/extract-tier-js-quotes.yml" --env ascend-local
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
- **Row 3:** the populated content field contains the substring `"The world as we have created it"`. The raw HTML
  captured in Prerequisites does NOT contain that phrase, so its presence proves the Playwright tier executed the
  page's JavaScript.

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
