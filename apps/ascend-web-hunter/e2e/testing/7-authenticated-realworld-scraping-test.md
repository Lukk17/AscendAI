# Real-world + authenticated scraping: e2e test

## What this verifies

Two things, both against **real sites** (no mocks):

1. **A categorized real-world URL matrix** — each URL asserts its **expected verdict** (`success` / `intervention` /
   `hard-fail`). Stable canaries are **gated** (must match); live sites are **best-effort** (the response must be a
   valid terminal verdict, but which one is recorded, not gated). The retail anti-bot rows add a content gate on the
   success branch: a success must carry the requested product page, never an anti-bot interstitial or a block page.
2. **Login → session reuse** (automated, saucedemo) — a **2-call before/after**: read the page **(1) blocked** (no
   session) returns no logged-in content, then **(2) after** a scripted login + session seed returns logged-in
   content. Proves the auth session is **stored and reused**.

The human-solved hCaptcha that used to be Part 3 of this spec is spec 11
([11-captcha-solve-and-reuse-test.md](11-captcha-solve-and-reuse-test.md)), which also asserts that the captured
session is reused. This spec has no human step and runs fully automated.

### Contract (how the service signals each verdict)

- **success** — HTTP `200`, body `status="success"`, non-empty content.
- **intervention** — HTTP `428 Precondition Required`, body `status="human_intervention_required"` + a non-empty
  `vnc_url`. This is the documented interactive-challenge contract (`api/exception_handlers.py`).
- **hard-fail** — a non-2xx the SSRF / host guard fail-closes with (e.g. HTTP `400` for an unresolvable host).
- busy, not a verdict: HTTP `409`, body `status="novnc_busy"` with a `holder_url`, and a `Retry-After` header,
  meaning another row's NoVNC intervention still holds the single shared browser. The runner reads the
  `Retry-After` header and the `holder_url` from the folder run's JSON output file (see Run), waits that many
  seconds, and re-runs only that row's own request file, up to 3 attempts in total, recording each attempt and
  the `holder_url` from each 409 body in the run record. Only after the third 409 is the row a FAIL.

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
| **Retail anti-bot — content-gated (a success must be the requested product page)** | | | | |
| u | `{{scrap_url_allegro}}` (Allegro offer) | hard block page, no solvable challenge | success or intervention | best-effort + content-gated |
| v | `{{scrap_url_amazon}}` (amazon.pl product) | click-through interstitial | success or intervention | best-effort + content-gated |
| w | `{{scrap_url_amazon_com}}` (amazon.com product) | click-through interstitial | success or intervention | best-effort + content-gated |
| x | `{{scrap_url_amazon_uk}}` (amazon.co.uk product) | click-through interstitial | success or intervention | best-effort + content-gated |
| y | `{{scrap_url_amazon_se}}` (amazon.se product) | click-through interstitial | success or intervention | best-effort + content-gated |

> **Gated rows** (a, b, c, d, e, q) hard-assert their verdict. **Best-effort rows** assert only that the response is a
> *valid terminal verdict* — either (`200` + `success` + content) **or** (`428` + `human_intervention_required` +
> `vnc_url`) — never gated on which; a malformed/5xx/empty response fails them. The login behavior is fully covered by
> Part 2 (saucedemo, a real login + real session); LinkedIn/indeed stay here as best-effort rows (real scripted login
> to them violates ToS / risks bans).
>
> **Content-gated rows** (u, v, w, x, y) are best-effort on *which* branch fires and hard-gated on *what a success
> contains*. A `200` + `status="success"` that carries an anti-bot interstitial instead of the requested page fails
> the row — it does not get recorded as "a valid verdict". See "Retail anti-bot rows" below.

### Retail anti-bot rows (u, v, w, x, y)

These five rows exist to catch one specific defect: the service reporting an anti-bot interstitial or a block page as
a successful scrape. A row that only checks for HTTP `200` is worse than useless against that bug, because HTTP `200`
is exactly what the bug produces. Each row therefore adds a second assertion that runs only on the success branch:

- **Product-identity canary (must be present).** A real product page carries a stable identifier of *that product*
  that no interstitial can carry: the ISBN-13 `9780132350884` for the three Clean Code listings (w, x, y), the ASIN
  `B09D14YFR9` for the amazon.pl listing (v), and the model code `er-cbn1` (case-insensitive) for the Allegro offer
  (u). This half is wording-independent, so it survives Amazon rotating its interstitial copy or switching between
  the click-through and character-entry variants.
- **Interstitial markers (must be absent).** The measured text of each locale's interstitial, plus the service's own
  `waf_strict_phrases` and `ERROR_KEYWORDS` — the exact strings a sibling row would treat as needing intervention.
  Naming them turns a failure into a diagnosis rather than a bare "canary missing".

Both halves were verified against captured responses: the four Amazon interstitials (fetched from each locale's
`/errors/validateCaptcha`) carry none of the canaries and trip the locale markers, and the four real product pages
carry their canary and trip no marker. The Allegro block page (`Please enable JS and disable any ad blocker`, served
as HTTP `403` on a direct fetch) likewise carries no `er-cbn1` and trips two markers.

**Why best-effort and not gated.** Retail anti-bot behaviour varies by day and by egress address. Gating u to
`intervention` would fail on a day the scraper legitimately gets through; gating v/w/x/y to `success` would flake the
moment Amazon decides this address looks automated. Both are real, correct outcomes for the service, so neither can
be the hard-asserted one. What is *never* correct is a success carrying an interstitial, and that is what the rows
gate on.

**Why the accept-set is `{success, intervention}` and excludes hard-fail.** Both sites resolve and are reachable, so
`400` (the SSRF / host guard's fail-closed code, row q's verdict) is not a legitimate outcome here. The service's
documented honest answer to an unsolvable challenge is the `428` intervention contract in
`api/exception_handlers.py`, which is what row u already produces today. These rows are written against that
behaviour. If a pending fix chooses a different shape for an honest failure, these rows will fail and that failure
is the signal to reconcile the contract — not a licence to widen the accept-set.

**Intervention handling on these rows.** Row u returns `428` on most runs, and each `428` spawns a NoVNC monitor that
holds a headful browser for `NOVNC_TIMEOUT_SECONDS` (600 s by default). Because u is best-effort, an intervention is a
valid recorded verdict and **no human is expected to solve it**: record the `vnc_url` in the run record, leave the
monitor to time out, and do not stall the sweep waiting on a human. The mandatory print-and-wait rule lives in
spec 11 ([11-captcha-solve-and-reuse-test.md](11-captcha-solve-and-reuse-test.md)), whose whole point is the human
solve.

**Dependency on the pending anti-bot fix.** Rows v, w, x and y assert behaviour the currently deployed build does not
have on the interstitial path: a live probe of each locale's `/errors/validateCaptcha` through
`POST /api/v2/web/read` returns HTTP `200` with `status="success"` and the interstitial as `content`. Whenever a run
of v/w/x/y lands on an interstitial rather than the real product page, the row will FAIL until the fix that converts
that case into an honest `428` is deployed. Row u needs no fix — Allegro's block page already escalates to
intervention.

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

## Prerequisites

Check Bruno CLI is installed.

```bash
bru --version
```

Expect a version string.

Check the ascend-web-hunter server is reachable.

```bash
curl -fsS http://localhost:7021/health
```

Expect HTTP 200 with `{"status":"ok"}`.

Check FlareSolverr is reachable (used by the Cloudflare tiers).

```bash
curl -fsS http://localhost:8191/
```

Expect HTTP 200.

Part 2 (saucedemo) needs no credentials: saucedemo's public demo credentials are hardcoded in the harness.

## Reset state

Flush the Redis session keys so the before/after pairs start from a genuine **blocked** state (otherwise a stale
session/clearance hides the regression).

**PowerShell:**

```powershell
docker exec redis redis-cli --scan --pattern "session:*" | ForEach-Object { docker exec redis redis-cli DEL $_ }
```

**Unix:**

```bash
docker exec redis redis-cli --scan --pattern "session:*" | while read key; do docker exec redis redis-cli DEL "$key"; done
```

## Run

> Execution model: every step is automated, so the Part 1 matrix rows and Part 2 (saucedemo) may fan out across
> parallel e2e-runner agents. Part 2's three steps stay in order on one runner. A row that answers 428 is recorded,
> its monitor left to time out, and no human is asked to act (see "Intervention handling on these rows" above).

Move into the Bruno collection root first.

```bash
cd docs/api/request/AscendAI
```

Part 2, Call 1 — login blocked (anonymous).

```bash
bru run "web-hunter/testing/auth-read-secure-anon.yml" --env ascend-local
```

Part 2, Seed — scripted saucedemo login (harness not in the image; copy it in, then run).

```bash
docker cp apps/ascend-web-hunter/e2e/harness/seed_authenticated_session.py ascend-web-hunter:/tmp/seed.py
```

```bash
docker exec -e PYTHONPATH=/app -w /app ascend-web-hunter python /tmp/seed.py
```

Part 2, Call 2 — after login.

```bash
bru run "web-hunter/testing/auth-read-secure.yml" --env ascend-local
```

Part 1, the real-world matrix (parallel-safe across runners). A folder run prints only pass or fail per request,
never a response body or header, so it writes its full results to a file. That file is where a `409` row's
`Retry-After` header and `holder_url` are read from.

PowerShell:

```powershell
bru run "web-hunter/testing/realworld" --env ascend-local -o "$env:TEMP\realworld-run.json" -f json
```

Unix:

```bash
bru run "web-hunter/testing/realworld" --env ascend-local -o "/tmp/realworld-run.json" -f json
```

Part 1, retry of a busy row. For each entry in that JSON whose response is HTTP `409` with `status="novnc_busy"`,
read the `Retry-After` header and the body's `holder_url` from the entry, wait the `Retry-After` seconds, then
re-run only that row's own request file (`web-hunter/testing/realworld/realworld-<row>-<site>.yml`, for example
`realworld-u-allegro-product.yml`) with the same `-o <file> -f json` flags into its own file, up to 3 attempts in
total. Record each attempt and each 409 body's `holder_url` in the run record. The row is a FAIL only after its
third 409.

## Expected

- **Part 1:** gated rows (a, b, c, d, e, q) match their verdict exactly — a–e are `200`/`success` (+ canary where
  noted), q is the `400` hard-fail. Best-effort rows each return a valid terminal verdict (`200`/`success`/content
  **or** `428`/`human_intervention_required`/`vnc_url`); which one is recorded, not failed. A `409` with
  `status="novnc_busy"` is not a verdict: the runner reads its `Retry-After` header and `holder_url` from the
  folder run's JSON output file, waits the `Retry-After` seconds, and re-runs only that row's own request file,
  up to 3 attempts in total, records each attempt and each 409 body's `holder_url` in the run record, and fails
  the row only on the third 409.
- **Part 1, retail anti-bot rows (u, v, w, x, y):** a valid terminal verdict as above, and on the success branch the
  `content` contains the row's product-identity canary (`er-cbn1` for u, `B09D14YFR9` for v, `9780132350884` for
  w/x/y) and none of the row's interstitial / block-page markers. A `200`/`success` carrying an interstitial fails
  the row.
- **Part 2 — login reuse:** Call 1 (anon) content has **no** auth-only inventory markers; Call 2 (after login)
  returns `status="success"` with an auth-only product description.

## Fixtures

None — and **no secrets**: saucedemo's credentials are its public demo values, hardcoded in the harness;
LinkedIn/indeed are intervention-only. URLs, selectors, and markers are hardcoded
in the harness and Bruno requests, except the five retail anti-bot rows (u, v, w, x, y), whose target URLs come from
the collection variables `scrap_url_allegro`, `scrap_url_amazon`, `scrap_url_amazon_com`, `scrap_url_amazon_uk` and
`scrap_url_amazon_se` in `docs/api/request/AscendAI/web-hunter/folder.yml`. Swapping a listing that goes out of stock
is then a one-line variable edit, and the row's product-identity canary is the only other thing to update with it. (A future real-secret login would read from the environment, never commit creds.)
The login-and-seed harness is a Playwright script under `e2e/harness/`.

## Concurrency

- Mutates: Redis, the ascend-web-hunter session store, keys for the matrix domains (including `allegro.pl`,
  `amazon.pl`, `amazon.com`, `amazon.co.uk` and `amazon.se` from the retail anti-bot rows) and `saucedemo.com`
  (`e2e` profile).
- Conflicts with: test 6 and any test sharing a target domain's session key, and test 11, because this spec's reset
  flushes every `session:*` key (which would wipe test 11's democaptcha capture between its two calls) and row u's
  428 holds the single NoVNC browser test 11's human needs. Within this test, Part 2's sequence (anon, then seed,
  then authed) is strictly ordered.
- Serial: false vs non-overlapping tests. No human step, so every part may fan out across e2e-runner subagents.
