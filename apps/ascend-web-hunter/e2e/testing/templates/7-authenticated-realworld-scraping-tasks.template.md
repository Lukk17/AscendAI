# Real-world + authenticated scraping: run tasks template

Spec: [../7-authenticated-realworld-scraping-test.md](../7-authenticated-realworld-scraping-test.md)

Copy this file to `../runs/<UTC-timestamp>_7-authenticated-realworld-scraping-tasks.md` before starting a run. Tick
boxes as you go. Record each best-effort row's actual verdict and any skip under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] `bru --version` returns a version string.
- [ ] `curl -fsS http://localhost:7021/health` returns HTTP 200 with `{"status":"ok"}`.
- [ ] `curl -fsS http://localhost:8191/` returns HTTP 200 (FlareSolverr reachable).

### Reset state

- [ ] Flushed Redis `session:*` keys so the before/after pairs start genuinely blocked.

### Part 2 — Login session reuse (saucedemo, AUTOMATED)

- [ ] Call 1 (blocked/anon): `auth-read-secure-anon.yml` → confirms the login wall (login-required message present) and NO auth-only inventory markers.
- [ ] Seed: `seed_authenticated_session.py` (copied into the container) logged in and stored the session under `session:saucedemo.com:e2e`.
- [ ] Call 2 (after login): `auth-read-secure.yml` → HTTP 200, `status="success"`, content contains an auth-only product description (e.g. `"ringspun combed cotton"`).

### Part 1 — Real-world matrix (gated rows MUST match; best-effort record the verdict)

- [ ] a `example.com` → success, `"example domain"`.
- [ ] b `en.wikipedia.org/wiki/Web_scraping` → success, `"web scraping"`.
- [ ] c `books.toscrape.com` → success.
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
- [ ] Any Part 1 row that answered `409`/`novnc_busy` was re-run after waiting its `Retry-After` seconds, up to 3 attempts in total, with each attempt and each 409 body's `holder_url` recorded under Additional tasks I did. Such a row is a FAIL only after its third 409.

### Part 1 — retail anti-bot rows (content-gated: a success MUST be the requested product page)

- [ ] u `{{scrap_url_allegro}}` (Allegro offer) → valid terminal verdict recorded; any success contains `er-cbn1` and no block-page marker.
- [ ] v `{{scrap_url_amazon}}` (amazon.pl) → valid terminal verdict recorded; any success contains `B09D14YFR9` and no interstitial marker.
- [ ] w `{{scrap_url_amazon_com}}` (amazon.com) → valid terminal verdict recorded; any success contains `9780132350884` and no interstitial marker.
- [ ] x `{{scrap_url_amazon_uk}}` (amazon.co.uk) → valid terminal verdict recorded; any success contains `9780132350884` and no interstitial marker.
- [ ] y `{{scrap_url_amazon_se}}` (amazon.se) → valid terminal verdict recorded; any success contains `9780132350884` and no interstitial marker.
- [ ] Row u's `vnc_url` (if it returned `428`) recorded below; monitor left to time out, no human solve requested.

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
both — a success carrying an interstitial is the defect these rows exist to catch, not a flaky site. -->
