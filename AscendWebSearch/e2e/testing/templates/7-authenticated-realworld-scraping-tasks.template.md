# Authenticated + real-world scraping: run tasks template

Spec: [../7-authenticated-realworld-scraping-test.md](../7-authenticated-realworld-scraping-test.md)

Copy this file to `../runs/<UTC-timestamp>_7-authenticated-realworld-scraping-tasks.md` before starting a run. Tick
boxes as you go. Record every best-effort row's actual verdict and any skip under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] `bru --version` returns a version string.
- [ ] `curl -fsS http://localhost:7021/health` returns HTTP 200 with `{"status":"ok"}`.
- [ ] `curl -fsS http://localhost:8191/` returns HTTP 200 (FlareSolverr reachable, needed for row n).
- [ ] `AscendWebSearch/e2e/.env.local` exists with `E2E_LOGIN_URL`, `E2E_LOGIN_USER`, `E2E_LOGIN_PASS`, `E2E_LOGIN_SECURE_URL`,
  `E2E_LOGIN_SUCCESS_MARKER` — OR record the authenticated section as **skipped**.

### Reset state

- [ ] (Optional) Flushed Redis `session:*` keys for the target domains + the `e2e` profile.

### Run — Step A: URL matrix (gated rows MUST match; best-effort rows record the verdict)

Easy (gated):
- [ ] a `example.com` → success, content has `"example domain"`.
- [ ] b `en.wikipedia.org/wiki/Web_scraping` → success, content has `"web scraping"`.
- [ ] c `books.toscrape.com` → success.
- [ ] d `news.ycombinator.com` → success.

Medium:
- [ ] e `quotes.toscrape.com/js/` → **gated**: success, content has `"The world as we have created it"`.
- [ ] f `wp.pl` → verdict recorded (expect success).
- [ ] g `old.reddit.com/r/programming/` → verdict recorded (expect success).
- [ ] h `stackoverflow.com/questions` → verdict recorded (expect success).
- [ ] i `github.com/python/cpython` → verdict recorded (expect success).
- [ ] j `bbc.com/news` → verdict recorded (expect success).

Hard / very-hard:
- [ ] k `www.reddit.com/` → verdict recorded (expect success).
- [ ] l `justjoin.it/job-offers/...` → verdict recorded (expect success).
- [ ] m `glassdoor.com/Job/...` → verdict recorded (expect success or intervention).
- [ ] n `nowsecure.nl` → **gated**: success (Cloudflare challenge solved), non-empty content.
- [ ] o `indeed.com/jobs?...` → verdict recorded (expect success or intervention).
- [ ] p `g2.com/` → verdict recorded (expect success or intervention).

Impossible (gated negative):
- [ ] q `this-domain-does-not-exist-xyzzy.invalid` → **gated**: `status != "success"`.

CAPTCHA / login wall:
- [ ] r `google.com/recaptcha/api2/demo` → verdict recorded (expect intervention + `vnc_url`).
- [ ] s `linkedin.com/jobs/...` → verdict recorded (expect intervention + `vnc_url`).
- [ ] t `secure.indeed.com/auth?...` → verdict recorded (expect intervention + `vnc_url`).

### Run — Steps B–D: authenticated capture→replay (skip if no `.env.local`)

- [ ] Step B — login-and-seed harness ran; `storage_state` captured and seeded under profile `e2e`.
- [ ] Step C — authenticated read of `E2E_LOGIN_SECURE_URL` with `profile=e2e` returned HTTP 200.
- [ ] Step D — anonymous read of `E2E_LOGIN_SECURE_URL` (no session) ran.

### Expected

- [ ] Every gated row (a, b, c, d, e, n, q) matched its verdict exactly.
- [ ] Best-effort verdicts recorded; intervention rows returned `status="human_intervention_required"` + a
  non-empty `vnc_url`.
- [ ] Step C content contains `E2E_LOGIN_SUCCESS_MARKER` (session replayed headlessly through the browser tier).
- [ ] Step D content does NOT contain the success marker (auth content gated on the session).

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

<!-- Record each best-effort row's actual verdict + which tier served it, whether the authenticated section was
skipped (no .env.local), any manual NoVNC login performed for the intervention rows (r/s/t), and any tier the
pipeline escalated to unexpectedly. -->
