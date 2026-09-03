# Tiered web scraping: run tasks template

Spec: [../6-tiered-scraping-test.md](../6-tiered-scraping-test.md)

Copy this file to `../runs/<UTC-timestamp>_6-tiered-scraping-tasks.md` before starting a run. Tick boxes as you go.
Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] `bru --version` returns a version string.
- [ ] `curl -fsS http://localhost:7021/health` returns HTTP 200 with `{"status":"ok"}`.
- [ ] `curl -fsS http://localhost:8191/` returns HTTP 200 (FlareSolverr reachable, needed for row 2).
- [ ] `curl -fsS https://en.wikipedia.org/wiki/Web_scraping` returns HTTP 200 (host outbound HTTPS works).
- [ ] The `<script>`-stripped raw markup of `https://quotes.toscrape.com/js/` does NOT contain
  `The world as we have created it` (the spec's `Invoke-WebRequest` one-liner prints `False`), confirming row 3's
  assertion is meaningful. The same expression without the strip prints `True`, because the page carries the
  quotes as a JavaScript array literal.

### Reset state

- [ ] (Optional) Flushed Redis keys matching `*en.wikipedia.org*`.
- [ ] (Optional) Flushed Redis keys matching `*scrapingcourse.com*`.
- [ ] (Optional) Flushed Redis keys matching `*quotes.toscrape.com*`.

### Run

- [ ] `cd docs/api/request/AscendAI`.
- [ ] Step 1 — `bru run "web-search/testing/extract-tier-static-wikipedia.yml" --env ascend-local` returned HTTP 200.
- [ ] Step 2 — `bru run "web-search/testing/extract-tier-cloudflare.yml" --env ascend-local` returned HTTP 200.
- [ ] Step 3 — `bru run "web-search/testing/extract-tier-js-quotes.yml" --env ascend-local -o "$env:TEMP\js-quotes-run.json" -f json` returned HTTP 200.
- [ ] Step 4. Printed the served `mode` from the captured JSON output.

### Expected

- [ ] Every gated step returned HTTP 200 with a JSON object body.
- [ ] Each body's `url` equals the requested URL and `status` equals `"success"`.
- [ ] Each body has a content field (`content` / `text` / `markdown`) of length ≥ 50.
- [ ] Row 1: the content field, lowercased, contains `"web scraping"`.
- [ ] Row 2: `status="success"` with content length ≥ 50 (Cloudflare challenge solved, not the block page).
- [ ] Row 3: content contains `"The world as we have created it"`, and the `mode` from step 4 is one of
  `3-flaresolverr`, `4-playwright_stealth`, `5-crawlee_adaptive`, or the NoVNC tier, never `1-beautifulsoup` or
  `2-trafilatura` (proves a browser executed the page JS).

### Verdict

- [ ] Verdict: PASS / FAIL (delete the wrong one)

## Result summary

Input tokens:

Output tokens:

Start (UTC):

End (UTC):

Duration:

---

## Additional tasks I did

<!-- Optional. Record the row 4 (CAPTCHA / NoVNC) manual best-effort attempt here if performed, any tier the
pipeline escalated to unexpectedly, diagnostic curls, or retries. Leave empty if nothing extra. -->
