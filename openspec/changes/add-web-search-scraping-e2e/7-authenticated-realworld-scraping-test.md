# Authenticated + real-world scraping: e2e test

## What this verifies

This test drives `POST /api/v2/web/read` against a **difficulty-graded, categorized** list of real-world URLs and
proves the **authenticated capture→replay** path end-to-end with a test-harness scripted login. It deliberately
includes **expected negatives** so a regression that turns a refusal into a false `success` (or the reverse) is
caught.

Every URL carries an **expected verdict**, and the test asserts the scraper produces *that* verdict:

- **`success`** — HTTP 200, `status="success"`, non-empty content field (`content` / `text` / `markdown`), plus a
  per-URL canary phrase where the page is stable.
- **`intervention`** — `status="human_intervention_required"` with a non-empty `vnc_url`. The scraper must *refuse
  and signal*, not return the login/block page as success. **LinkedIn and indeed-auth are intervention-only** (no
  scripted login — automated LinkedIn login violates ToS and risks an account ban).
- **`hard-fail`** — `status != "success"`. Validates the fail-closed path produces a clean negative, not a false
  positive.

Each difficulty tier forces a **specific scraper code path**, so a verdict pinpoints what broke. Stable rows are
**gated** (canary — must match its verdict); volatile real-world rows are **best-effort** (verdict recorded in the
run, a miss does NOT fail the suite, because live sites rotate WAFs and go down).

### URL matrix (by difficulty)

| # | URL | Forces | Expected | Gate |
| :- | :-- | :----- | :------- | :--- |
| **Easy — curl_cffi static + extraction** | | | | |
| a | `https://example.com/` | static fetch | success (`"example domain"`) | **gated** |
| b | `https://en.wikipedia.org/wiki/Web_scraping` | static article extraction | success (`"web scraping"`) | **gated** |
| c | `https://books.toscrape.com/` | scraping sandbox (static) | success | **gated** |
| d | `https://news.ycombinator.com/` | minimal static HTML | success | **gated** |
| **Medium — Playwright JS render** | | | | |
| e | `https://quotes.toscrape.com/js/` | JS sandbox | success (`"The world as we have created it"`) | **gated** |
| f | `https://wp.pl` | heavy news portal | success | best-effort |
| g | `https://old.reddit.com/r/programming/` | server-rendered Reddit | success | best-effort |
| h | `https://stackoverflow.com/questions` | server-rendered Q&A | success | best-effort |
| i | `https://github.com/python/cpython` | light-JS repo page | success | best-effort |
| j | `https://www.bbc.com/news` | news + JS | success | best-effort |
| **Hard — SPA + anti-bot (stealth/fingerprint)** | | | | |
| k | `https://www.reddit.com/` | React SPA + bot checks | success | best-effort |
| l | `https://justjoin.it/job-offers/remote/java?employment-type=b2b&experience-level=senior&with-salary=yes` | Next.js SPA job board | success | best-effort |
| m | `https://www.glassdoor.com/Job/index.htm` | aggressive anti-bot | success **or** intervention | best-effort |
| **Very hard — enterprise WAF** | | | | |
| n | `https://nowsecure.nl` | Cloudflare JS challenge → FlareSolverr | success (challenge solved) | **gated** |
| o | `https://www.indeed.com/jobs?q=AI&l=usa&radius=25&fromage=7&start=20` | DataDome-class | success **or** intervention | best-effort |
| p | `https://www.g2.com/` | Cloudflare-hard | success **or** intervention | best-effort |
| **Impossible — negative** | | | | |
| q | `https://this-domain-does-not-exist-xyzzy.invalid/` | DNS failure → fail-closed | hard-fail | **gated** |
| **CAPTCHA — human-intervention path** | | | | |
| r | `https://www.google.com/recaptcha/api2/demo` | real reCAPTCHA v2 → NoVNC | intervention (+ `vnc_url`) | best-effort |
| **Login wall — intervention-only** | | | | |
| s | `https://www.linkedin.com/jobs/search/?keywords=Java%20Developer&location=United%20States&f_AL=true` | login wall → NoVNC | intervention (+ `vnc_url`) | best-effort |
| t | `https://secure.indeed.com/auth?co=US&hl=en_US&branding=page-two-signin` | login wall → NoVNC | intervention (+ `vnc_url`) | best-effort |

> Rows l, o, s, t use abbreviated query strings here for readability; the Bruno request files carry the full URLs
> verbatim (from the dev request collection).

### Authenticated capture→replay (the test-harness scripted-login flow)

Proves the anchor end-to-end: log in once on a **stable, automation-friendly** site using `.env.local`
credentials → capture the browser `storage_state` → seed the AscendWebSearch session store → an authenticated read
returns **logged-in-only** content, while the same read **without** a session does **not**.

- Default stable login site (NOT LinkedIn): `https://www.saucedemo.com/` — a React SPA test app
  (`standard_user` / `secret_sauce`). Its logged-in page (`/inventory.html`) is **client-side rendered**, so a
  successful read also proves the **browser-tier** session replay (the actual LinkedIn-class fix), not just cookie
  replay. Only the **credentials** (`SAUCEDEMO_USER` / `SAUCEDEMO_PASS`) come from `.env.local`; the login URL,
  secure URL, DOM selectors, and the success marker (`"Sauce Labs Backpack"`) are **hardcoded** in the harness
  (`e2e/harness/seed_authenticated_session.py`) and the auth-read Bruno requests, so the test is fixed. Adding
  another login-walled service = one more `LoginService` entry in the harness + its `<SERVICE>_USER`/`<SERVICE>_PASS`
  env pair.
- **Seeding mechanism (white-box):** the harness writes the captured `storage_state` into the same Redis the
  service uses, at the session store key `session:{registrable_domain}:{profile}` with the auth-record shape
  (`{"auth": {"storage_state": …, "user_agent": …, "saved_at": …}}`). This couples the harness to the store's key
  format — flagged deliberately; a future `POST /session/import` endpoint would decouple it.
- The authenticated section (Steps B–D) is **skipped (not failed)** when the `.env.local` credential keys are
  absent.

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

Expect HTTP 200. If this fails, row n cannot pass for environmental reasons.

Check the authenticated-section credentials. `AscendWebSearch/e2e/.env.local` (gitignored, copied from `.env.local.example` in that folder) must define the per-service login
credentials — for saucedemo, `SAUCEDEMO_USER` and `SAUCEDEMO_PASS` (login/secure URLs, selectors, and markers are
hardcoded in the tests, not here).

```powershell
Test-Path AscendWebSearch/e2e/.env.local
```

If `.env.local` (or any key) is absent, **skip** the authenticated section (Steps B–D) and record it as skipped
under **Additional tasks I did** — do not fail the test.

## Reset state

Optional. Flush the Redis session keys for the target domains and the `e2e` login profile to force cold runs.

```powershell
docker exec ascend-redis redis-cli --scan --pattern "session:*" | ForEach-Object { docker exec ascend-redis redis-cli DEL $_ }
```

## Run

Move into the Bruno collection root first.

```powershell
cd docs/api/request/AscendAI
```

Step A — public URL matrix (rows a–t). Run the directory; record each row's verdict (gated rows must match;
best-effort rows are logged).

```powershell
bru run "web-search/testing/realworld" --env ascend-local
```

Step B — authenticated capture (skip if no `.env.local`). The login-and-seed harness logs into each configured login service (saucedemo)
with the `.env.local` creds via Playwright, captures `storage_state`, and seeds the session store under profile
`e2e`.

```powershell
python AscendWebSearch/e2e/harness/seed_authenticated_session.py
```

Step C — authenticated read. Read the logged-in-only page with the seeded profile.

```powershell
bru run "web-search/testing/auth-read-secure.yml" --env ascend-local
```

Step D — negative auth read. Read the same page with **no** profile/session.

```powershell
bru run "web-search/testing/auth-read-secure-anon.yml" --env ascend-local
```

## Expected

- **Step A — gated rows must match exactly:** a, b, c, d, e, n return `status="success"` with non-empty content
  (and their canary phrase where listed); q returns `status != "success"`.
- **Step A — best-effort rows are recorded, not gated:** success rows (f, g, h, i, j, k, l) return
  `status="success"` + content; intervention rows (r, s, t, and m/o/p when walled) return
  `status="human_intervention_required"` with a non-empty `vnc_url`. A best-effort miss is logged, not failed.
- **Step C (auth read):** HTTP 200, `status="success"`, content contains the saucedemo marker (`Sauce Labs Backpack`) — proving the
  seeded session was replayed headlessly through the browser tier.
- **Step D (negative auth):** the response does **not** contain the success marker (gets the login page or an
  intervention signal) — proving authenticated content is gated on the session, not leaked anonymously.
- A skipped authenticated section (no `.env.local`) is not a failure.

## Fixtures

None uploaded. The only secrets are the per-service credentials in `.env.local` (`SAUCEDEMO_USER`/`SAUCEDEMO_PASS`, one pair per login service), never committed. The
login-and-seed harness is a Playwright script under `e2e/harness/`.

## Concurrency

- **Mutates:** Redis — AscendWebSearch session store, keys for the matrix domains and the `e2e` profile of the
  login site.
- **Conflicts with:** test 6 and any test sharing a target domain's session key; the internal Steps B→C→D are
  strictly ordered.
- **Serial:** false (vs non-overlapping tests).
