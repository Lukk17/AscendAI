# Real-world + reuse-behavior scraping: e2e test

## What this verifies

Three things, all against **real sites** (no mocks):

1. **A categorized real-world URL matrix** — each URL asserts its **expected verdict** (`success` / `intervention` /
   `hard-fail`). Stable canaries are **gated** (must match); live sites are **best-effort** (verdict recorded, a
   miss does not fail the suite).
2. **Login → session reuse** (automated, saucedemo) — a **2-call before/after**: read the gated page **(1) blocked**
   (no session) returns no logged-in content, then **(2) after** a scripted login + session seed returns logged-in
   content. Proves the auth session is **stored and reused**.
3. **CAPTCHA → clearance reuse** (human, Cloudflare, runs **first**) — a **2-call before/after**: read **(1)
   blocked** returns the human-intervention `vnc_url` (the interactive challenge can't be auto-solved), the human
   solves it in the NoVNC browser, then a fresh read **(2) after** reuses the captured `cf_clearance` and returns
   content. Proves the clearance is **stored and reused** (the challenge is skipped on the second request).

The blocked→unblocked behaviors (login, captcha) are **exactly 2 calls each** — first while blocked, then a fresh
request after auth/solve — because the regression-prone behavior is precisely "scrape blocked → authorize → scrape
now succeeds and the session/clearance is reused".

### Part 1 — Real-world URL matrix (single-call verdict)

| # | URL | Forces | Expected | Gate |
| :- | :-- | :----- | :------- | :--- |
| **Easy — curl_cffi static + extraction** | | | | |
| a | `https://example.com/` | static fetch | success (`"example domain"`) | **gated** |
| b | `https://en.wikipedia.org/wiki/Web_scraping` | static article | success (`"web scraping"`) | **gated** |
| c | `https://books.toscrape.com/` | scraping sandbox | success | **gated** |
| d | `https://news.ycombinator.com/` | minimal static HTML | success | **gated** |
| **Medium — Playwright JS render** | | | | |
| e | `https://quotes.toscrape.com/js/` | JS sandbox | success (`"The world as we have created it"`) | **gated** |
| f | `https://wp.pl` | heavy news portal | success | best-effort |
| g | `https://old.reddit.com/r/programming/` | server-rendered Reddit | success | best-effort |
| h | `https://stackoverflow.com/questions` | server-rendered Q&A | success | best-effort |
| i | `https://github.com/python/cpython` | light-JS repo page | success | best-effort |
| j | `https://www.bbc.com/news` | news + JS | success | best-effort |
| **Hard — SPA + anti-bot** | | | | |
| k | `https://www.reddit.com/` | React SPA + bot checks | success | best-effort |
| l | `https://justjoin.it/job-offers/remote/java?employment-type=b2b&experience-level=senior&with-salary=yes` | Next.js SPA | success | best-effort |
| m | `https://www.glassdoor.com/Job/index.htm` | aggressive anti-bot | success or intervention | best-effort |
| **Very hard — enterprise WAF** | | | | |
| n | `https://nowsecure.nl` | Cloudflare JS challenge → FlareSolverr auto-solve | success | **gated** |
| o | `https://www.indeed.com/jobs?q=AI&l=usa&radius=25&fromage=7&from=searchOnDesktopSerp&start=20` | DataDome-class | success or intervention | best-effort |
| p | `https://www.g2.com/` | Cloudflare-hard | success or intervention | best-effort |
| **Impossible — negative** | | | | |
| q | `https://this-domain-does-not-exist-xyzzy.invalid/` | DNS failure → fail-closed | hard-fail | **gated** |
| **Login wall — intervention-only (not solved here)** | | | | |
| s | `https://www.linkedin.com/jobs/search/?keywords=Java%20Developer&location=United%20States&f_AL=true` | login wall → NoVNC | intervention (+ `vnc_url`) | best-effort |
| t | `https://secure.indeed.com/auth?co=US&hl=en_US&branding=page-two-signin` | login wall → NoVNC | intervention (+ `vnc_url`) | best-effort |

> The login behavior is fully covered by Part 2 (saucedemo, a real login + real session); LinkedIn/indeed stay here
> as best-effort intervention rows (real scripted login to them violates ToS / risks bans).

### Part 2 — Login → session reuse (saucedemo, AUTOMATED, 2 calls)

saucedemo.com is a **real** web app: a real form login that sets a real session cookie, captured as a real
`storage_state` and replayed through the real browser tier. It is automatable (no human, no ban risk), so it gates
the login-reuse behavior in CI.

- **Call 1 — blocked:** read `https://www.saucedemo.com/inventory.html` with **no** session. Expect the response
  does **not** contain the logged-in marker `"Sauce Labs Backpack"` (the SPA redirects to the login screen).
- **Seed:** run the harness `e2e/harness/seed_authenticated_session.py` — scripted login with the `.env.local`
  saucedemo credentials → capture `storage_state` → store under `session:www.saucedemo.com:e2e`.
- **Call 2 — after login (fresh request):** read the same URL with `profile=e2e`. Expect HTTP 200,
  `status="success"`, content contains `"Sauce Labs Backpack"` — the stored session is **reused** through the
  browser tier.

### Part 3 — CAPTCHA → clearance reuse (Cloudflare, HUMAN, runs FIRST, 2 calls)

`https://nopecha.com/demo/cloudflare` is a real Cloudflare **interactive challenge** page (it 403s plain clients).
FlareSolverr cannot auto-solve an interactive challenge, so the scraper escalates to NoVNC and a human solves it;
the NoVNC monitor captures the resulting `cf_clearance` into the session store, which the **second** request reuses.

- **Call 1 — blocked:** read `https://nopecha.com/demo/cloudflare` with **no** clearance. Expect
  `status="human_intervention_required"` with a non-empty `vnc_url`.
- **Human solve (main thread, first):** open the `vnc_url`, solve the Cloudflare interactive challenge in the NoVNC
  browser. The monitor stores the captured `cf_clearance` under `session:nopecha.com:default`.
- **Call 2 — after solve (fresh request):** read the **same** `https://nopecha.com/demo/cloudflare`. Expect HTTP
  200, `status="success"`, non-empty content — the challenge is **skipped** because the stored `cf_clearance` is
  reused (the headline regression check: solve once, the next request to the domain is clear).

## Prerequisites

Check Bruno CLI is installed.

```powershell
bru --version
```

Expect a version string.

Check the AscendWebSearch server is reachable.

```powershell
curl -fsS http://localhost:7021/health
```

Expect HTTP 200 with `{"status":"ok"}`.

Check FlareSolverr is reachable (required for the Cloudflare canary, row n).

```powershell
curl -fsS http://localhost:8191/
```

Expect HTTP 200.

Check the saucedemo login credentials for Part 2. `AscendWebSearch/e2e/.env.local` (gitignored, copied from
`.env.local.example` in that folder) must define `SAUCEDEMO_USER` and `SAUCEDEMO_PASS`.

```powershell
Test-Path AscendWebSearch/e2e/.env.local
```

If absent, **skip Part 2** (record as skipped) — do not fail the test. Part 3 needs no credentials (the human types
nothing; they solve the challenge in the NoVNC browser).

## Reset state

Flush the Redis session keys so both before/after pairs start from a genuine **blocked** state (otherwise a stale
session/clearance hides the regression).

```powershell
docker exec ascend-redis redis-cli --scan --pattern "session:*" | ForEach-Object { docker exec ascend-redis redis-cli DEL $_ }
```

## Run

> Execution model: **Part 3 (human captcha) runs FIRST on the main session** — read #1, you solve the challenge in
> the NoVNC browser, then read #2. The Part 1 matrix rows and Part 2 (automated saucedemo) fan out across parallel
> e2e-runner agents while you solve Part 3.

Move into the Bruno collection root first.

```powershell
cd docs/api/request/AscendAI
```

Part 3, Call 1 — captcha blocked (main thread, first).

```powershell
bru run "web-search/testing/captcha-clearance-blocked.yml" --env ascend-local
```

Part 3, Call 2 — after you solve the challenge via the returned `vnc_url`.

```powershell
bru run "web-search/testing/captcha-clearance-after-solve.yml" --env ascend-local
```

Part 2, Call 1 — login blocked (anonymous).

```powershell
bru run "web-search/testing/auth-read-secure-anon.yml" --env ascend-local
```

Part 2, Seed — scripted saucedemo login.

```powershell
python AscendWebSearch/e2e/harness/seed_authenticated_session.py
```

Part 2, Call 2 — after login.

```powershell
bru run "web-search/testing/auth-read-secure.yml" --env ascend-local
```

Part 1 — the real-world matrix (parallel-safe across runners).

```powershell
bru run "web-search/testing/realworld" --env ascend-local
```

## Expected

- **Part 1:** gated rows (a, b, c, d, e, n, q) match their verdict exactly; best-effort rows are recorded
  (intervention rows return `status="human_intervention_required"` + a `vnc_url`; success rows return
  `status="success"` + content). A best-effort miss is logged, not failed.
- **Part 2 — login reuse:** Call 1 (anon) content does NOT contain `"Sauce Labs Backpack"`; Call 2 (after login)
  returns `status="success"` with `"Sauce Labs Backpack"`.
- **Part 3 — clearance reuse:** Call 1 returns `status="human_intervention_required"` + a `vnc_url`; after the human
  solve, Call 2 returns `status="success"` with non-empty content (no second challenge).
- Skipped Part 2 (no `.env.local`) is not a failure.

## Fixtures

None uploaded. The only secrets are the per-service credentials in `AscendWebSearch/e2e/.env.local`
(`SAUCEDEMO_USER`/`SAUCEDEMO_PASS`, one pair per login-walled service), never committed. Login/secure/captcha URLs,
selectors, and markers are hardcoded in the harness and Bruno requests. The login-and-seed harness is a Playwright
script under `e2e/harness/`.

## Concurrency

- **Mutates:** Redis — AscendWebSearch session store, keys for the matrix domains, `www.saucedemo.com` (`e2e`
  profile), and `nopecha.com` (`default` profile).
- **Conflicts with:** test 6 and any test sharing a target domain's session key. Within this test, each before/after
  pair (Part 2: anon → seed → authed; Part 3: blocked → solve → after) is **strictly ordered**.
- **Serial:** false vs non-overlapping tests; Part 3's human solve runs first on the main session.
