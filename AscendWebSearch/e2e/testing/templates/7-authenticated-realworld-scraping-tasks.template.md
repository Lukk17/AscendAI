# Real-world + reuse-behavior scraping: run tasks template

Spec: [../7-authenticated-realworld-scraping-test.md](../7-authenticated-realworld-scraping-test.md)

Copy this file to `../runs/<UTC-timestamp>_7-authenticated-realworld-scraping-tasks.md` before starting a run. Tick
boxes as you go. Record each best-effort row's actual verdict and any skip under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] `bru --version` returns a version string.
- [ ] `curl -fsS http://localhost:7021/health` returns HTTP 200 with `{"status":"ok"}`.
- [ ] `curl -fsS http://localhost:8191/` returns HTTP 200 (FlareSolverr reachable, needed for row n).
- [ ] `AscendWebSearch/e2e/.env.local` exists with `SAUCEDEMO_USER` / `SAUCEDEMO_PASS` — OR record Part 2 as **skipped**.

### Reset state

- [ ] Flushed Redis `session:*` keys so both before/after pairs start genuinely blocked.

### Part 3 — CAPTCHA clearance reuse (HUMAN, runs FIRST on the main session)

- [ ] Call 1 (blocked): `captcha-clearance-blocked.yml` → `status="human_intervention_required"` + non-empty `vnc_url`.
- [ ] Human solve: opened the `vnc_url`, solved the Cloudflare interactive challenge in the NoVNC browser.
- [ ] Call 2 (after solve): `captcha-clearance-after-solve.yml` → HTTP 200, `status="success"`, non-empty content
  (challenge skipped — `cf_clearance` reused).

### Part 2 — Login session reuse (saucedemo, AUTOMATED; skip if no `.env.local`)

- [ ] Call 1 (blocked/anon): `auth-read-secure-anon.yml` → content does NOT contain `"Sauce Labs Backpack"`.
- [ ] Seed: `seed_authenticated_session.py` logged in and stored the session under `session:www.saucedemo.com:e2e`.
- [ ] Call 2 (after login): `auth-read-secure.yml` → HTTP 200, `status="success"`, content contains `"Sauce Labs Backpack"`.

### Part 1 — Real-world matrix (gated rows MUST match; best-effort record the verdict)

- [ ] a `example.com` → success, `"example domain"`.
- [ ] b `en.wikipedia.org/wiki/Web_scraping` → success, `"web scraping"`.
- [ ] c `books.toscrape.com` → success.
- [ ] d `news.ycombinator.com` → success.
- [ ] e `quotes.toscrape.com/js/` → **gated**: success, `"The world as we have created it"`.
- [ ] f `wp.pl` → verdict recorded (expect success).
- [ ] g `old.reddit.com/r/programming/` → verdict recorded (expect success).
- [ ] h `stackoverflow.com/questions` → verdict recorded (expect success).
- [ ] i `github.com/python/cpython` → verdict recorded (expect success).
- [ ] j `bbc.com/news` → verdict recorded (expect success).
- [ ] k `www.reddit.com/` → verdict recorded (expect success).
- [ ] l `justjoin.it/job-offers/...` → verdict recorded (expect success).
- [ ] m `glassdoor.com/Job/...` → verdict recorded (expect success or intervention).
- [ ] n `nowsecure.nl` → **gated**: success (Cloudflare auto-solved), non-empty content.
- [ ] o `indeed.com/jobs?...` → verdict recorded (expect success or intervention).
- [ ] p `g2.com/` → verdict recorded (expect success or intervention).
- [ ] q `this-domain-does-not-exist-xyzzy.invalid` → **gated**: `status != "success"`.
- [ ] s `linkedin.com/jobs/...` → verdict recorded (expect intervention + `vnc_url`).
- [ ] t `secure.indeed.com/auth?...` → verdict recorded (expect intervention + `vnc_url`).

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

<!-- Record each best-effort row's actual verdict + serving tier, whether Part 2 was skipped (no .env.local), how
long the Part 3 human solve took, and any tier the pipeline escalated to unexpectedly. -->
