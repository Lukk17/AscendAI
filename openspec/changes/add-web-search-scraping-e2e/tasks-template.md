# Tiered web scraping: run tasks template

Spec: [test-spec.md](test-spec.md)

Copy this file to `../runs/<UTC-timestamp>_6-tiered-scraping-tasks.md` before starting a run. For a repeated run of the same spec in the same sweep, which shares the sweep's timestamp, add `-rerun<N>` before `.md` (`-rerun2` for the second run, `-rerun3` for the third). Tick boxes as you go.
Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] `bru --version` returns a version string.
- [ ] `curl -fsS http://127.0.0.1:7021/health` returns HTTP 200 with `status` `ok`, `service` `ascend-web-hunter` and a non-empty `version`.
- [ ] `curl -fsS https://en.wikipedia.org/wiki/Web_scraping` returns HTTP 200 (host outbound HTTPS works).
- [ ] The `<script>`-stripped raw markup of `https://quotes.toscrape.com/js/` does NOT contain
  `The world as we have created it` (the spec's PowerShell one-liner prints `False` and its Unix one-liner prints
  `0`), confirming row 3's assertion is meaningful. The same expression without the strip prints `True` in
  PowerShell and `1` in Unix, because the page carries the quotes as a JavaScript array literal.

### Reset state

- [ ] Listed `GET /api/v2/session/interventions` and closed each flow for `wikipedia.org`, `scrapingcourse.com` or `toscrape.com` with `DELETE /api/v2/session/interventions/{flow_id}`, each answering `204` (a `404` only for a window that ended on its own), before any delete.
- [ ] The listing after the closes showed no flow for those three domains.
- [ ] (Optional) Flushed Redis keys matching `*wikipedia.org*` (keys use the registrable domain, never the host `en.wikipedia.org`).
- [ ] (Optional) Flushed Redis keys matching `*scrapingcourse.com*`.
- [ ] (Optional) Flushed Redis keys matching `*toscrape.com*` (keys use the registrable domain, never the host `quotes.toscrape.com`).
- [ ] (Optional) `POST /api/v2/web/session/clear` with `{"url":"https://en.wikipedia.org/wiki/Web_scraping","profile":"default"}` returned HTTP 200 with `status="cleared"`, after the Redis deletes (clears the in-process read cache for `wikipedia.org`).
- [ ] (Optional) `POST /api/v2/web/session/clear` with `{"url":"https://www.scrapingcourse.com/cloudflare-challenge","profile":"default"}` returned HTTP 200 with `status="cleared"`, after the Redis deletes (clears the in-process read cache for `scrapingcourse.com`).
- [ ] (Optional) `POST /api/v2/web/session/clear` with `{"url":"https://quotes.toscrape.com/js/","profile":"default"}` returned HTTP 200 with `status="cleared"`, after the Redis deletes (clears the in-process read cache for `toscrape.com`).

### Run

- [ ] `cd docs/api/request/AscendAI`.
- [ ] Step 1 - `bru run "web-hunter/testing/extract-tier-static-wikipedia.yml" --env ascend-local` returned HTTP 200.
- [ ] Step 2 - `bru run "web-hunter/testing/extract-tier-cloudflare.yml" --env ascend-local` returned HTTP 200, or HTTP 428 with the human-help body when the address is rated.
- [ ] Created the private report directory `E2E_OUT` (`mktemp -d`, or a random folder under the temp path in PowerShell), no fixed `/tmp` or `$env:TEMP` path.
- [ ] Step 3 - `bru run "web-hunter/testing/extract-tier-js-quotes.yml" --env ascend-local -o "$E2E_OUT/js-quotes-run.json" -f json` returned HTTP 200.
- [ ] Step 4. Printed the served `mode` from the captured JSON output.
- [ ] Removed the `E2E_OUT` report directory.

### Expected

- [ ] Steps 1 and 3 returned HTTP 200 with a JSON object body. Step 2 returned HTTP 200 with a JSON object body, or HTTP 428 with an `application/problem+json` body.
- [ ] Each HTTP 200 body's `url` equals the requested URL and `status` equals `"success"`.
- [ ] Each HTTP 200 body has a content field (`content` / `text` / `markdown`) of length ≥ 50.
- [ ] Row 1: the content field, lowercased, contains `"web scraping"`.
- [ ] Row 2: either HTTP 200 with `status="success"`, content length ≥ 50 and `"cloudflare challenge"` in the lowercased content, or HTTP 428 with `code` `human_intervention_required` and a non-empty `vnc_url`. Never the block page as content.
- [ ] Row 3: content contains `"The world as we have created it"`, and the `mode` from step 4 is one of
  `4-playwright_stealth`, `4a-patchright`, `4b-camoufox`, `5-crawlee_adaptive`, or the NoVNC tier, never `1-beautifulsoup` or
  `2-trafilatura` (proves a browser executed the page JS).

### Post-run cleanup

- [ ] Closed each flow for this spec's three domains with `DELETE /api/v2/session/interventions/{flow_id}`, each answering `204` (a `404` only for a window that ended on its own), and the listing after it showed no flow for those domains, so no late NoVNC save can outlive the cleanup.
- [ ] Then flushed Redis keys matching `*wikipedia.org*`, `*scrapingcourse.com*` and `*toscrape.com*`, which includes the `novnc_window_result:<domain>:<profile>` key the close writes.

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
