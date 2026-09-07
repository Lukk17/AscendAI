# Real-world + authenticated + human-captcha scraping: e2e test

## What this verifies

Three things, all against **real sites** (no mocks):

1. **A categorized real-world URL matrix** — each URL asserts its **expected verdict** (`success` / `intervention` /
   `hard-fail`). Stable canaries are **gated** (must match); live sites are **best-effort** (the response must be a
   valid terminal verdict, but which one is recorded, not gated).
2. **Login → session reuse** (automated, saucedemo) — a **2-call before/after**: read the page **(1) blocked** (no
   session) returns no logged-in content, then **(2) after** a scripted login + session seed returns logged-in
   content. Proves the auth session is **stored and reused**.
3. **CAPTCHA human-solve + capture** (human, reCAPTCHA v2, runs **first**) — read **blocked** returns HTTP 428 + a
   human-intervention `vnc_url`; the human solves the reCAPTCHA in the NoVNC browser; we then assert the solved
   session (the `_GRECAPTCHA` cookie reCAPTCHA sets on interaction) was **captured into the session store**. The
   Google reCAPTCHA v2 demo is used because it always requires a human click — it can't be auto-passed by a headful
   browser or solved by FlareSolverr — so it reliably needs a human, and a captured `_GRECAPTCHA` cookie proves one
   acted.

### Contract (how the service signals each verdict)

- **success** — HTTP `200`, body `status="success"`, non-empty content.
- **intervention** — HTTP `428 Precondition Required`, body `status="human_intervention_required"` + a non-empty
  `vnc_url`. This is the documented interactive-challenge contract (`api/exception_handlers.py`).
- **hard-fail** — a non-2xx the SSRF / host guard fail-closes with (e.g. HTTP `400` for an unresolvable host).

### Why Part 3 asserts capture, not cross-request reuse

A reCAPTCHA token (and a WAF clearance like a Cloudflare `cf_clearance`) is single-use or bound to the exact browser
fingerprint (TLS/JA3, headful build) and IP that solved it. The human solves it in the NoVNC browser, but a later read
runs in a different browser context, so it is not reusable. Cross-request reuse is therefore not meaningfully
observable. **Capture** (the solved session landing in the session store) is the deterministic, real signal that the
human-intervention path works. (Contrast Part 2: an app session cookie is not fingerprint-bound, so it reuses cleanly.)

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
| f | `https://wp.pl` | heavy news portal | success or intervention | best-effort |
| g | `https://old.reddit.com/r/programming/` | server-rendered Reddit | success or intervention | best-effort |
| h | `https://stackoverflow.com/questions` | server-rendered Q&A | success or intervention | best-effort |
| i | `https://github.com/python/cpython` | light-JS repo page | success or intervention | best-effort |
| j | `https://www.bbc.com/news` | news + JS | success or intervention | best-effort |
| **Hard — SPA + anti-bot** | | | | |
| k | `https://www.reddit.com/` | React SPA + bot checks | success or intervention | best-effort |
| l | `https://justjoin.it/job-offers/remote/java?employment-type=b2b&experience-level=senior&with-salary=yes` | Next.js SPA | success or intervention | best-effort |
| m | `https://www.glassdoor.com/Job/index.htm` | aggressive anti-bot | success or intervention | best-effort |
| **Very hard — enterprise WAF** | | | | |
| n | `https://nowsecure.nl` | Cloudflare challenge | success or intervention | best-effort |
| o | `https://www.indeed.com/jobs?q=AI&l=usa&radius=25&fromage=7&from=searchOnDesktopSerp&start=20` | DataDome-class | success or intervention | best-effort |
| p | `https://www.g2.com/` | Cloudflare-hard | success or intervention | best-effort |
| **Impossible — negative** | | | | |
| q | `https://this-domain-does-not-exist-xyzzy.invalid/` | unresolvable host → fail-closed | hard-fail (HTTP 400) | **gated** |
| **Login wall — intervention-only (not solved here)** | | | | |
| s | `https://www.linkedin.com/jobs/search/?keywords=Java%20Developer&location=United%20States&f_AL=true` | login wall → NoVNC | success or intervention | best-effort |
| t | `https://secure.indeed.com/auth?co=US&hl=en_US&branding=page-two-signin` | login wall → NoVNC | success or intervention | best-effort |

> **Gated rows** (a, b, c, d, e, q) hard-assert their verdict. **Best-effort rows** assert only that the response is a
> *valid terminal verdict* — either (`200` + `success` + content) **or** (`428` + `human_intervention_required` +
> `vnc_url`) — never gated on which; a malformed/5xx/empty response fails them. The login behavior is fully covered by
> Part 2 (saucedemo, a real login + real session); LinkedIn/indeed stay here as best-effort rows (real scripted login
> to them violates ToS / risks bans).

### Part 2 — Login → session reuse (saucedemo, AUTOMATED, 2 calls)

saucedemo.com is a **real** web app: a real form login that sets a real session cookie, captured as a real
`storage_state` and replayed through the real browser tier. It is automatable (no human, no ban risk), so it gates
the login-reuse behavior in CI.

- **Call 1 — blocked (confirm the login wall):** read `https://www.saucedemo.com/inventory.html` with **no** session.
  Expect HTTP 200, the content carries saucedemo's login-required message ("You can only access … when you are logged
  in") and has **none** of the authenticated-inventory product descriptions. This proves the read hit the login wall
  *before* any login is attempted.
- **Seed:** run the harness `e2e/harness/seed_authenticated_session.py` — scripted login with saucedemo's hardcoded
  public credentials → capture `storage_state` → store under `session:saucedemo.com:e2e` (the key uses the
  *registrable* domain; `www.` is stripped).
- **Call 2 — after login (fresh request):** read the same URL with `profile=e2e`. Expect HTTP 200, `status="success"`,
  and content containing an **auth-only product description** (e.g. `"ringspun combed cotton"`, `"quarter-zip fleece"`,
  `"lighting modes"`) — present only on the logged-in inventory. The stored session is **reused** through the browser
  tier. (Product *titles* like "Sauce Labs Backpack" are stripped by extraction, so the markers are descriptions.)

### Part 3 — CAPTCHA human-solve + capture (reCAPTCHA v2, HUMAN, runs FIRST)

`https://www.google.com/recaptcha/api2/demo` always renders the reCAPTCHA v2 "I'm not a robot" widget. A headful
browser cannot auto-pass it (the checkbox needs a human click) and FlareSolverr cannot solve it, so the scraper
escalates to NoVNC and a human solves the reCAPTCHA — reliably exercising the human-solve path that a Cloudflare or
DataDome target no longer does (the scraper now auto-passes those).

- **Call 1 — blocked:** read `https://www.google.com/recaptcha/api2/demo` with **no** session. Expect HTTP **428
  Precondition Required**, `status="human_intervention_required"` with a non-empty `vnc_url`.
- **Human solve (main thread, first):** the runner **must print the `vnc_url` verbatim into the chat** (see
  "Human-intervention forwarding" below). The human opens it and solves the reCAPTCHA in the NoVNC browser (click the
  checkbox, solve any image challenge). The monitor captures the cleared session under `session:google.com:default`.
- **Capture check:** assert the session store now holds the solved session — `session:google.com:default` exists with
  a `_GRECAPTCHA` cookie in its `auth` entry. reCAPTCHA sets `_GRECAPTCHA` only on interaction, and the widget can't be
  auto-passed, so its presence is deterministic proof a human solved it. (Cross-request *reuse* is not asserted — see
  "Why Part 3 asserts capture, not cross-request reuse".)

#### Human-intervention forwarding (mandatory)

Any call in this test that returns `status="human_intervention_required"` returns a `vnc_url` that **a human must
open**. The agent driving the test **must print that `vnc_url` verbatim into the chat** the moment it is received,
then **wait** for the human to confirm they solved it before the capture check.

Because a fanned-out `e2e-runner` subagent's output is **never shown to the user**, Part 3 (and any intervention this
test surfaces that a human must act on) **must be run by the main agent/session**, not delegated to a subagent. The
automated, no-human parts — the Part 1 matrix and Part 2 (saucedemo) — may still fan out across parallel runners. If
Part 3 is ever delegated despite this, the **main agent must re-print the subagent's `vnc_url` to the user**;
otherwise the human never receives the link and the test stalls forever.

## Prerequisites

Check Bruno CLI is installed.

```powershell
bru --version
```

Expect a version string.

Check the ascend-web-hunter server is reachable.

```powershell
curl -fsS http://localhost:7021/health
```

Expect HTTP 200 with `{"status":"ok"}`.

Check FlareSolverr is reachable (used by the Cloudflare tiers).

```powershell
curl -fsS http://localhost:8191/
```

Expect HTTP 200.

Part 2 (saucedemo) and Part 3 (captcha) need **no credentials**: saucedemo's public demo credentials are hardcoded
in the harness, and the human types nothing for the captcha (they solve it in the NoVNC browser).

## Reset state

Flush the Redis session keys so the before/after pairs start from a genuine **blocked** state (otherwise a stale
session/clearance hides the regression).

```powershell
docker exec redis redis-cli --scan --pattern "session:*" | ForEach-Object { docker exec redis redis-cli DEL $_ }
```

## Run

> Execution model: **Part 3 (human captcha) is run by the main agent on the main session, FIRST** — never delegate it
> to an `e2e-runner` subagent, whose output is not shown to the user. Call 1 returns a `vnc_url`; the main agent
> **prints that `vnc_url` verbatim in the chat** and waits for you to solve the challenge in the NoVNC browser before
> the capture check. The Part 1 matrix rows and Part 2 (automated saucedemo) may fan out across parallel e2e-runner
> agents while you solve Part 3. See "Human-intervention forwarding (mandatory)" under Part 3.

Move into the Bruno collection root first.

```powershell
cd docs/api/request/AscendAI
```

Part 3, Call 1 — captcha blocked (main thread, first).

```powershell
bru run "web-hunter/testing/captcha-clearance-blocked.yml" --env ascend-local
```

Part 3, Capture check — after you solve the challenge via the returned `vnc_url`.

```powershell
docker exec redis redis-cli GET "session:google.com:default"
```

Expect a JSON value whose `auth` entry contains a `_GRECAPTCHA` cookie.

Part 2, Call 1 — login blocked (anonymous).

```powershell
bru run "web-hunter/testing/auth-read-secure-anon.yml" --env ascend-local
```

Part 2, Seed — scripted saucedemo login (harness not in the image; copy it in, then run).

```powershell
docker cp apps/ascend-web-hunter/e2e/harness/seed_authenticated_session.py ascend-web-hunter:/tmp/seed.py
```

```powershell
docker exec -e PYTHONPATH=/app -w /app ascend-web-hunter python /tmp/seed.py
```

Part 2, Call 2 — after login.

```powershell
bru run "web-hunter/testing/auth-read-secure.yml" --env ascend-local
```

Part 1 — the real-world matrix (parallel-safe across runners).

```powershell
bru run "web-hunter/testing/realworld" --env ascend-local
```

## Expected

- **Part 1:** gated rows (a, b, c, d, e, q) match their verdict exactly — a–e are `200`/`success` (+ canary where
  noted), q is the `400` hard-fail. Best-effort rows each return a valid terminal verdict (`200`/`success`/content
  **or** `428`/`human_intervention_required`/`vnc_url`); which one is recorded, not failed.
- **Part 2 — login reuse:** Call 1 (anon) content has **no** auth-only inventory markers; Call 2 (after login)
  returns `status="success"` with an auth-only product description.
- **Part 3 — human-solve capture:** Call 1 returns HTTP `428`, `status="human_intervention_required"` + a `vnc_url`;
  after the human solve, `session:google.com:default` holds a `_GRECAPTCHA` cookie in its `auth` entry.

## Fixtures

None — and **no secrets**: saucedemo's credentials are its public demo values, hardcoded in the harness; the captcha
is human-solved (no credentials); LinkedIn/indeed are intervention-only. URLs, selectors, and markers are hardcoded
in the harness and Bruno requests. (A future real-secret login would read from the environment, never commit creds.)
The login-and-seed harness is a Playwright script under `e2e/harness/`.

## Concurrency

- **Mutates:** Redis — ascend-web-hunter session store, keys for the matrix domains, `saucedemo.com` (`e2e` profile),
  and `google.com` (`default` profile, the reCAPTCHA demo).
- **Conflicts with:** test 6 and any test sharing a target domain's session key. Part 3 targets `google.com`, which no
  matrix row touches, so there is no overlap. Within this test, Part 2's sequence (anon → seed → authed) is **strictly
  ordered**, and Part 3's human solve runs first on the main session.
- **Serial:** false vs non-overlapping tests; Part 3's human solve runs first on the main session.
