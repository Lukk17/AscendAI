# Tiered web scraping: run tasks template

Spec: [test-spec.md](test-spec.md)

Copy this file to `../runs/<UTC-timestamp>_6-tiered-scraping-tasks.md` before starting a run. Tick boxes as you go.
Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] `bru --version` returns a version string.
- [ ] `curl -fsS http://localhost:7021/health` returns HTTP 200 with `{"status":"ok"}`.
- [ ] `curl -fsS http://localhost:8191/` returns HTTP 200 (FlareSolverr reachable, needed for row 2).
- [ ] `curl -fsS https://en.wikipedia.org/wiki/Web_scraping` returns HTTP 200 (host outbound HTTPS works).
- [ ] `curl -fsS https://quotes.toscrape.com/js/` returns HTTP 200 and the raw HTML does NOT contain
  `The world as we have created it` (confirms row 3's assertion is meaningful).

### Reset state

- [ ] (Optional) Flushed Redis keys matching `*en.wikipedia.org*`.
- [ ] (Optional) Flushed Redis keys matching `*nowsecure.nl*`.
- [ ] (Optional) Flushed Redis keys matching `*quotes.toscrape.com*`.

### Run

- [ ] `cd docs/api/request/AscendAI`.
- [ ] Step 1 — `bru run "web-hunter/testing/extract-tier-static-wikipedia.yml" --env ascend-local` returned HTTP 200.
- [ ] Step 2 — `bru run "web-hunter/testing/extract-tier-cloudflare.yml" --env ascend-local` returned HTTP 200.
- [ ] Step 3 — `bru run "web-hunter/testing/extract-tier-js-quotes.yml" --env ascend-local` returned HTTP 200.

### Expected

- [ ] Every gated step returned HTTP 200 with a JSON object body.
- [ ] Each body's `url` equals the requested URL and `status` equals `"success"`.
- [ ] Each body has a content field (`content` / `text` / `markdown`) of length ≥ 50.
- [ ] Row 1: the content field, lowercased, contains `"web scraping"`.
- [ ] Row 2: `status="success"` with content length ≥ 50 (Cloudflare challenge solved, not the block page).
- [ ] Row 3: content contains `"The world as we have created it"`, which is absent from the raw HTML captured in
  Prerequisites (proves Playwright executed the page JS).

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
