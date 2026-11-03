# Real-world + authenticated scraping: run tasks template

Spec: [../7-authenticated-realworld-scraping-test.md](../7-authenticated-realworld-scraping-test.md)

Copy this file to `../runs/<UTC-timestamp>_7-authenticated-realworld-scraping-tasks.md` before starting a run. Tick
boxes as you go. Record each best-effort row's actual verdict and any skip under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] `bru --version` returns a version string.
- [ ] `curl -fsS http://localhost:7021/health` returns HTTP 200 with `status` `ok`, `service` `ascend-web-hunter` and a non-empty `version`.
- [ ] `GET /api/v2/session/interventions` reports `active_flows` `0` and `max_concurrent_flows` at least `4`, so the window of spec 11 or of spec 20 ([../20-concurrent-interventions-test.md](../20-concurrent-interventions-test.md)) cannot starve this matrix (the one cap rule of the spec).

### Reset state

- [ ] Flushed Redis `session:*` keys so the before/after pairs start genuinely blocked.

### Part 2 - Login session reuse (saucedemo, AUTOMATED)

- [ ] Call 1 (blocked/anon): `auth-read-secure-anon.yml` → confirms the login wall (login-required message present) and NO auth-only inventory markers.
- [ ] Seed: `seed_authenticated_session.py` (copied into the container) logged in and imported the session over HTTP (`POST /api/v2/web/session/import` with `profile=e2e`), stored by the service under `session:saucedemo.com:e2e`.
- [ ] Call 2 (after login): `auth-read-secure.yml` → HTTP 200, `status="success"`, content contains an auth-only product description (e.g. `"ringspun combed cotton"`).

### Part 1 - Real-world matrix (gated rows MUST match; best-effort record the verdict)

- [ ] a `example.com` → success, `"documentation examples"` (measured 2026-10-28).
- [ ] b `en.wikipedia.org/wiki/Web_scraping` → success, `"web scraping"`.
- [ ] c `books.toscrape.com` → success, `"in stock"` (measured 2026-10-28).
- [ ] d `news.ycombinator.com` → success.
- [ ] e `quotes.toscrape.com/js/` → **gated**: success, `"The world as we have created it"`.
- [ ] f `wp.pl` → valid terminal verdict recorded.
- [ ] g `old.reddit.com/r/programming/` → valid terminal verdict recorded.
- [ ] h `stackoverflow.com/questions` → valid terminal verdict recorded.
- [ ] i `github.com/python/cpython` → valid terminal verdict recorded.
- [ ] j `bbc.com/news` → valid terminal verdict recorded.
- [ ] k `www.reddit.com/` → valid terminal verdict recorded.
- [ ] l `justjoin.it/job-offers/...` → valid terminal verdict recorded.
- [ ] m `glassdoor.com/Job/...` → valid terminal verdict recorded.
- [ ] n `nowsecure.nl` → valid terminal verdict recorded (success or intervention).
- [ ] o `indeed.com/jobs?...` → valid terminal verdict recorded.
- [ ] p `g2.com/` → valid terminal verdict recorded.
- [ ] q `this-domain-does-not-exist-xyzzy.invalid` → **gated**: HTTP 400, `status != "success"`.
- [ ] s `linkedin.com/jobs/...` → valid terminal verdict recorded.
- [ ] t `secure.indeed.com/auth?...` → valid terminal verdict recorded.
- [ ] Any Part 1 row that answered `409`/`novnc_busy` had its `Retry-After` and `holder_url` read from the folder run's JSON output file. First confirmed the run genuinely saturated the cap: the listing reported `active_flows` equal to `max_concurrent_flows` at that moment. A `409` with a free window slot is a FAIL at once (a defect in the row or the service, never congestion), never a retry. For a saturated `409`, only that row's own request file was re-run after waiting the `Retry-After` seconds, up to 3 attempts in total, with each attempt and each 409 body's `holder_url` recorded under Additional tasks I did. Such a row is a FAIL only after its third 409.

### Part 1 - retail anti-bot rows (content-gated: a success MUST be the requested product page)

- [ ] u `{{scrap_url_allegro}}` (Allegro offer) → valid terminal verdict recorded; any success contains `er-cbn1` and no block-page marker.
- [ ] v `{{scrap_url_amazon}}` (amazon.pl) → valid terminal verdict recorded; any success contains `B09D14YFR9` and no interstitial marker.
- [ ] w `{{scrap_url_amazon_com}}` (amazon.com) → valid terminal verdict recorded; any success contains `9780132350884` and no interstitial marker.
- [ ] x `{{scrap_url_amazon_uk}}` (amazon.co.uk) → valid terminal verdict recorded; any success contains `9780132350884` and no interstitial marker.
- [ ] y `{{scrap_url_amazon_se}}` (amazon.se) → valid terminal verdict recorded; any success contains `9780132350884` and no interstitial marker.
- [ ] Row u's `vnc_url` (if it returned `428`) recorded below; monitor left to time out, no human solve requested.

> The pending anti-bot fix is this change. Rows v, w, x and y use the scored challenge verdict this change
> adds: an interstitial on the locale path answers HTTP `428` with `code="human_intervention_required"` and a
> non-empty `vnc_url`, never HTTP `200` with `status="success"` carrying the interstitial as content. Rows v, w, x
> and y stay best-effort and content-gated. Row u needs no fix - Allegro's block page already escalates to
> intervention.

### Part 1 - Challenge walls in other languages (gated: intervention, no human solve)

- [ ] aa `www.amazon.de/errors/validateCaptcha` → **gated**: intervention (German validateCaptcha page).
- [ ] ab `www.amazon.fr/errors/validateCaptcha` → **gated**: intervention (French validateCaptcha page).
- [ ] ac `www.amazon.it/errors/validateCaptcha` → **gated**: intervention (Italian validateCaptcha page).
- [ ] ad `www.amazon.es/errors/validateCaptcha` → **gated**: intervention (Spanish validateCaptcha page).
- [ ] ae `www.amazon.co.jp/errors/validateCaptcha` → **gated**: intervention (Japanese validateCaptcha page).
- [ ] Rows aa to ae `vnc_url`s (each returned `428`) recorded below; monitors left to time out, no human solve requested.

### Part 1 - Widgets that are not walls (gated: success)

- [ ] af `friendlycaptcha.com/` → **gated**: success, catalogue widget + 786-word page.
- [ ] ag `www.mtcaptcha.com/` → **gated**: success, catalogue widget + 702-word page.
- [ ] ah `www.hcaptcha.com/` → **gated**: success, catalogue widget + 442-word page.

### Part 1 - Wikipedia in other languages (gated: success)

- [ ] ai `ja.wikipedia.org/wiki/日本` → **gated**: success, Japanese article with infobox canary `"君が代"`.
- [ ] aj `ar.wikipedia.org/wiki/مصر` → **gated**: success, Arabic article with infobox canary `"جمهورية مصر العربية"`.

### Part 1 - Tier-pinned live check (best-effort, never a 5xx)

- [ ] ak `nowsecure.nl` with tier `4a-patchright` → HTTP 200 success or HTTP 428 with the human-help problem body recorded; a 5xx fails the row.

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

<!-- Record each best-effort row's actual verdict + serving tier and any
tier the pipeline escalated to unexpectedly. For the retail anti-bot rows (u, v, w, x, y) also record which branch
fired per row, and for any FAIL whether the cause was a missing product canary, a tripped interstitial marker, or
both - a success carrying an interstitial is the defect these rows exist to catch, not a flaky site. -->
