# Real-world + authenticated + human-captcha scraping: run tasks template

Spec: [7-authenticated-realworld-scraping-test.md](7-authenticated-realworld-scraping-test.md)

Copy this file to `../runs/<UTC-timestamp>_7-authenticated-realworld-scraping-tasks.md` before starting a run. Tick
boxes as you go. Record each best-effort row's actual verdict and any skip under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] `bru --version` returns a version string.
- [ ] `curl -fsS http://localhost:7021/health` returns HTTP 200 with `{"status":"ok"}`.
- [ ] `curl -fsS http://localhost:8191/` returns HTTP 200 (FlareSolverr reachable).

### Reset state

- [ ] Flushed Redis `session:*` keys so the before/after pairs start genuinely blocked.

### Part 3 — CAPTCHA human-solve + capture (HUMAN, run by the MAIN agent, FIRST on the main session)

- [ ] Run by the **main agent** (NOT a fanned-out e2e-runner subagent — its output never reaches the user).
- [ ] Call 1 (blocked): `captcha-clearance-blocked.yml` → HTTP 428, `status="human_intervention_required"` + non-empty `vnc_url`.
- [ ] Main agent **printed the `vnc_url` verbatim in the chat** for the human to open.
- [ ] Human solve: opened the `vnc_url`, solved the reCAPTCHA in the NoVNC browser; confirmed back to the agent.
- [ ] Capture check: `docker exec redis redis-cli GET "session:google.com:default"` → JSON whose `auth` entry contains a `_GRECAPTCHA` cookie.

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

<!-- Record each best-effort row's actual verdict + serving tier, how long the Part 3 human solve took, and any
tier the pipeline escalated to unexpectedly. -->
