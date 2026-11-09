# Real-world + authenticated scraping: e2e test

## What this verifies

Two things, both against **real sites** (no mocks):

1. **A categorized real-world URL matrix** - each URL asserts its **expected verdict** (`success` / `intervention` /
   `hard-fail`). Stable canaries are **gated** (must match); live sites are **best-effort** (the response must be a
   valid terminal verdict, but which one is recorded, not gated). The retail anti-bot rows add a content gate on the
   success branch: a success must carry the requested product page, never an anti-bot interstitial or a block page.
2. **Login → session reuse** (automated, saucedemo) - a **2-call before/after**: read the page **(1) blocked** (no
   session) returns no logged-in content, then **(2) after** a scripted login + session seed returns logged-in
   content. Proves the auth session is **stored and reused**.

The human-solved hCaptcha that used to be Part 3 of this spec is spec 11
([11-captcha-solve-and-capture-test.md](../../../apps/ascend-web-hunter/e2e/testing/11-captcha-solve-and-capture-test.md)), which asserts the capture that
solve leaves behind. This spec has no human step and runs fully automated.

### Contract (how the service signals each verdict)

- **success** - HTTP `200`, body `status="success"`, non-empty content.
- **intervention** - HTTP `428 Precondition Required`, body `code="human_intervention_required"` + a non-empty
  `vnc_url`. This is the documented interactive-challenge contract (`api/exception_handlers.py`).
- **hard-fail** - a non-2xx the SSRF / host guard fail-closes with (e.g. HTTP `400` for an unresolvable host).
- session_expired, not a verdict: HTTP `200`, body `status="session_expired"`, empty `content`, and a `message`
  naming the domain and profile. The service answers it when a login was saved for the row's domain and profile
  and no longer validates, and it refuses to read anonymously instead (`_create_session_expired_response` in
  `src/reader/web_reader.py`). On this spec it means the reset left a stale `session:<domain>:default` key behind,
  so the row is a FAIL of the run setup: delete that key as Reset state says and re-run the row.
- busy, not a verdict: HTTP `409`, body `code="novnc_busy"` with a `holder_url`, and a `Retry-After` header,
  meaning every NoVNC window slot is held. The runner reads the
  `Retry-After` header and the `holder_url` from the folder run's JSON output file (see Run) and records both, then
  closes the windows this spec's earlier rows opened (see "Closing this spec's windows" under Run), and re-runs
  only that row's own request file, up to 3 attempts in total, recording each attempt and the `holder_url` from
  each 409 body in the run record. Only after the third 409 is the row a FAIL. Waiting the `Retry-After` seconds
  alone may not free a slot here, because each earlier row's window stays open until it is closed or its
  `NOVNC_TIMEOUT_SECONDS` (600 s by default) runs out. A window can also end on its own when the wall clears
  without a person.
- a `409` on a best-effort row is itself a FAIL unless the run genuinely saturated `NOVNC_MAX_CONCURRENT_FLOWS`
  at that moment, with the `409` body itself reporting `active_flows` equal to `max_concurrent_flows`. The body
  carries both numbers as they stood when the service refused the read, so the runner reads them from that row's
  entry in the folder run's JSON output file, never from a later listing. On the 2026-09-10
  run, rows n, o, p and t answered `409` while another row's intervention held the only window, so a busy
  answer proved nothing about the row's own target and hid real regressions behind retries. A `409` with a free
  window slot is a defect in the row or the service, not congestion: record it as a FAIL at once instead of
  retrying it.

### Part 1 - Real-world URL matrix (single-call verdict)

| # | URL | Forces | Expected | Gate |
| :- | :-- | :----- | :------- | :--- |
| **Easy - curl_cffi static + extraction** | | | | |
| a | `https://example.com/` | static fetch | success (`"documentation examples"`, measured 2026-10-28) | **gated** |
| b | `https://en.wikipedia.org/wiki/Web_scraping` | static article | success (`"web scraping"`) | **gated** |
| c | `https://books.toscrape.com/` | scraping sandbox | success (`"in stock"`, measured 2026-10-28) | **gated** |
| d | `https://news.ycombinator.com/` | minimal static HTML | success | **gated** |
| **Medium - Playwright JS render** | | | | |
| e | `https://quotes.toscrape.com/js/` | JS sandbox | success (`"The world as we have created it"`) | **gated** |
| f | `https://wp.pl` | heavy news portal | success or intervention | best-effort |
| g | `https://old.reddit.com/r/programming/` | server-rendered Reddit | success or intervention | best-effort + content-gated |
| h | `https://stackoverflow.com/questions` | server-rendered Q&A | success or intervention | best-effort |
| i | `https://github.com/python/cpython` | light-JS repo page | success or intervention | best-effort |
| j | `https://www.bbc.com/news` | news + JS | success or intervention | best-effort |
| **Hard - SPA + anti-bot** | | | | |
| k | `https://www.reddit.com/` | React SPA + bot checks | success or intervention | best-effort |
| l | `https://justjoin.it/job-offers/remote/java?employment-type=b2b&experience-level=senior&with-salary=yes` | Next.js SPA | success or intervention | best-effort |
| m | `https://www.glassdoor.com/Job/index.htm` | aggressive anti-bot | success or intervention | best-effort |
| **Very hard - enterprise WAF** | | | | |
| n | `https://nowsecure.nl` | Cloudflare challenge | success or intervention | best-effort |
| o | `https://www.indeed.com/jobs?q=AI&l=usa&radius=25&fromage=7&from=searchOnDesktopSerp` | DataDome-class | success or intervention | best-effort + content-gated |
| p | `https://www.g2.com/` | Cloudflare-hard | success or intervention | best-effort |
| **Impossible - negative** | | | | |
| q | `https://this-domain-does-not-exist-xyzzy.invalid/` | unresolvable host → fail-closed | hard-fail (HTTP 400) | **gated** |
| **Login wall - intervention-only (not solved here)** | | | | |
| s | `https://www.linkedin.com/jobs/search/?keywords=Java%20Developer&location=United%20States&f_AL=true` | login wall → NoVNC | success or intervention | best-effort |
| t | `https://secure.indeed.com/auth?co=US&hl=en_US&branding=page-two-signin` | login wall → NoVNC | success or intervention | best-effort |
| **Retail anti-bot - content-gated (a success must be the requested product page)** | | | | |
| u | `{{scrap_url_allegro}}` (Allegro offer) | hard block page, no solvable challenge | success or intervention | best-effort + content-gated |
| v | `{{scrap_url_amazon}}` (amazon.pl product) | click-through interstitial | success or intervention | best-effort + content-gated |
| w | `{{scrap_url_amazon_com}}` (amazon.com product) | click-through interstitial | success or intervention | best-effort + content-gated |
| x | `{{scrap_url_amazon_uk}}` (amazon.co.uk product) | click-through interstitial | success or intervention | best-effort + content-gated |
| y | `{{scrap_url_amazon_se}}` (amazon.se product) | click-through interstitial | success or intervention | best-effort + content-gated |
| **Challenge walls in other languages** | | | | |
| aa | `https://www.amazon.de/errors/validateCaptcha` | validateCaptcha page (German) | intervention | **gated** |
| ab | `https://www.amazon.fr/errors/validateCaptcha` | validateCaptcha page (French) | intervention | **gated** |
| ac | `https://www.amazon.it/errors/validateCaptcha` | validateCaptcha page (Italian) | intervention | **gated** |
| ad | `https://www.amazon.es/errors/validateCaptcha` | validateCaptcha page (Spanish) | intervention | **gated** |
| ae | `https://www.amazon.co.jp/errors/validateCaptcha` | validateCaptcha page (Japanese) | intervention | **gated** |
| **Widgets that are not walls** | | | | |
| af | `https://friendlycaptcha.com/` | catalogue widget + 786-word page | success | **gated** |
| ag | `https://www.mtcaptcha.com/` | catalogue widget + 702-word page | success | **gated** |
| ah | `https://www.hcaptcha.com/` | catalogue widget + 442-word page | success | **gated** |
| **Wikipedia in other languages (live guard check on non-Latin scripts)** | | | | |
| ai | `https://ja.wikipedia.org/wiki/日本` | Japanese article (infobox canary `君が代`, measured 2026-10-26) | success (`"君が代"`) | **gated** |
| aj | `https://ar.wikipedia.org/wiki/مصر` | Arabic article (infobox canary `جمهورية مصر العربية`, measured 2026-10-26) | success (`"جمهورية مصر العربية"`) | **gated** |
| **Tier-pinned live check (moved from task 6.2)** | | | | |
| ak | `https://nowsecure.nl` | tier `4a-patchright` | success or intervention | best-effort |

> **Gated rows** (a, b, c, d, e, q, aa, ab, ac, ad, ae, af, ag, ah, ai, aj) hard-assert their verdict. **Best-effort rows** assert only that the response is a
> *valid terminal verdict* - either (`200` + `success` + content) **or** (`428` + `human_intervention_required` +
> `vnc_url`) - never gated on which; a malformed/5xx/empty response fails them. The login behavior is fully covered by
> Part 2 (saucedemo, a real login + real session); LinkedIn/indeed stay here as best-effort rows (real scripted login
> to them violates ToS / risks bans).
>
> **Content-gated rows** (g, o, u, v, w, x, y) are best-effort on *which* branch fires and hard-gated on *what a success
> contains*. A `200` + `status="success"` that carries an anti-bot interstitial or an account wall instead of the
> requested page fails the row - it does not get recorded as "a valid verdict". See "Retail anti-bot rows", "Row g"
> and "Row o" below.

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
  `waf_strict_phrases` and `ERROR_KEYWORDS` - the exact strings a sibling row would treat as needing intervention.
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
behaviour: the service answers `428` with code `human_intervention_required`. If that answer changes shape later,
these rows will fail and that failure is the signal to reconcile the contract - not a licence to widen the accept-set.

**Intervention handling on these rows.** Row u returns `428` on most runs, and each `428` spawns a NoVNC monitor that
holds a headful browser and one window slot until the window is closed or `NOVNC_TIMEOUT_SECONDS` (600 s by default)
runs out. A window can also end on its own when the wall clears without a person. Because u is best-effort, an
intervention is a valid recorded verdict and **no human is expected to solve it**: record the `vnc_url` in the run
record, and do not stall the sweep waiting on a human. The window is closed by
the busy-row step or by Post-run cleanup (see "Closing this spec's windows" under Run). The mandatory print-and-wait rule lives in
spec 11 ([11-captcha-solve-and-capture-test.md](../../../apps/ascend-web-hunter/e2e/testing/11-captcha-solve-and-capture-test.md)), whose whole point is the
human solve.

**Intervention handling on rows aa to ae.** Each of rows aa to ae returns `428` and spawns a NoVNC monitor
that holds a headful browser and one window slot until the window is closed or `NOVNC_TIMEOUT_SECONDS` (600 s by default)
runs out. A window can also end on its own when the wall clears without a person. These rows are gated on the
intervention verdict, and **no human is expected to solve them**: record each `vnc_url` in the run record, and do
not stall the sweep waiting on a human. They run late in the folder, after rows such as s, t and u have already
opened windows, so at a cap of 4 any row that runs after four windows are held can meet every slot held and answer
`409`. The busy-row step closes this spec's earlier windows first, so those rows get a free slot on their re-run.

**The anti-bot fix is this change.** Rows v, w, x and y use the scored challenge verdict this change
adds: an interstitial on the locale path answers HTTP `428` with `code="human_intervention_required"` and a
non-empty `vnc_url`, never HTTP `200` with `status="success"` carrying the interstitial as content. Rows v, w, x
and y stay best-effort and content-gated. Row u needs no fix - Allegro's block page already escalates to
intervention.

### Row g (old Reddit, r/programming)

Old Reddit now sends an anonymous visitor to `/login/?reason=lor2`, a page that says
`accounts are required to access old Reddit`. That page is an account wall, not the subreddit, so a `200`
`status="success"` that carries it is the defect this gate catches: a login wall reported as a successful scrape.

The success branch carries a content gate, the same idea as row o: the content, compared in lower case, must not
contain `accounts are required to access old reddit`. The accepted verdicts are a success that passes the gate,
or HTTP `428` with `code="human_intervention_required"` and a non-empty `vnc_url`. A `428` with
`intervention_type` `login` is the expected answer to the account wall. The subreddit's own content was not
measured, because the redirect reaches every anonymous visitor, so the gate names what a success must not be
rather than a canary it must carry.

### Row o (Indeed job search, page 1)

Row o reads the first page of Indeed's job search. It does not ask for a later page (`start=20`), because Indeed shows
pages past the first only to a signed-in user. On 2026-11-07 the `start=20` address answered HTTP `200`
`status="success"` with 315 characters of Indeed's own sign-in prompt ("To see more than one page of jobs, create an
account or sign in", "Continue with Apple"). That prompt is Indeed's rule for anonymous visitors, not a defect of
the service, and the first page has no such rule.

The success branch carries a content gate, the same idea as the retail rows: the content must be at least 1000
characters, far more than the 315-character sign-in prompt, and must carry none of these markers:
`create an account or sign in`, `Continue with Apple`, `Security Check`, `Just a moment...`, `Checking if the site
connection is secure`, `Additional Verification Required`, `Ray ID`. The first page's own content was not measured,
because Indeed answers a direct fetch from this host with HTTP `403` and a `Security Check` page, so the gate names
what a success must not be rather than a canary it must carry.

### Part 2 - Login → session reuse (saucedemo, AUTOMATED, 2 calls)

saucedemo.com is a **real** web app: a real form login that sets a real session cookie, captured as a real
`storage_state` and replayed through the real browser tier. It is automatable (no human, no ban risk), so it gates
the login-reuse behavior in CI.

- **Call 1 - blocked (confirm the login wall):** read `https://www.saucedemo.com/inventory.html` with **no** session.
  Expect HTTP 200, the content carries saucedemo's login-required message ("You can only access … when you are logged
  in") and has **none** of the authenticated-inventory product descriptions. This proves the read hit the login wall
  *before* any login is attempted.
- **Seed:** run the harness `e2e/harness/seed_authenticated_session.py` - scripted login with saucedemo's hardcoded
  public credentials → capture `storage_state` → import it over HTTP with `POST /api/v2/web/session/import` and
  `profile=e2e` (the service stores it under `session:saucedemo.com:e2e`; the key uses the
  *registrable* domain; `www.` is stripped).
- **Call 2 - after login (fresh request):** read the same URL with `profile=e2e`. Expect HTTP 200, `status="success"`,
  and content containing an **auth-only product description** (e.g. `"ringspun combed cotton"`, `"quarter-zip fleece"`,
  `"lighting modes"`) - present only on the logged-in inventory. The stored session is **reused** through the browser
  tier. (Product *titles* like "Sauce Labs Backpack" are stripped by extraction, so the markers are descriptions.)

## Prerequisites

Check Bruno CLI is installed.

```bash
bru --version
```

Expect a version string.

Check the ascend-web-hunter server is reachable.

```bash
curl -fsS http://127.0.0.1:7021/health
```

Expect HTTP 200 with `status` `ok`, `service` `ascend-web-hunter` and a non-empty `version`.

Check the matrix runs with a cap of at least 4, the shipped default of `NOVNC_MAX_CONCURRENT_FLOWS`, which the
sibling change `open-several-novnc-windows-at-once` provides and which is built before this change. Spec 11 holds
one window, so at the default the matrix keeps at least three free slots beside it. No cap protects the matrix
from spec 20 ([20-concurrent-interventions-test.md](../../../apps/ascend-web-hunter/e2e/testing/20-concurrent-interventions-test.md)), which fills every
window slot on purpose, so the two never run side by side (see Concurrency).

```bash
curl -fsS http://127.0.0.1:7021/api/v2/session/interventions
```

Expect a body with `active_flows` `0` and `max_concurrent_flows` at least `4`. This is the one cap rule of
spec 7.

Part 2 (saucedemo) needs no credentials: saucedemo's public demo credentials are hardcoded in the harness.

## Reset state

Delete the keys this spec writes, so the before/after pairs start from a genuine **blocked** state and every matrix
row climbs the tier ladder from its first tier (otherwise a stale session, clearance or remembered tier hides the
regression). The keys are named exactly, one `DEL` per key family, for the registrable domain of every site of the
matrix and of Part 2: `example.com`, `wikipedia.org`, `toscrape.com`, `ycombinator.com`, `wp.pl`, `reddit.com`, `stackoverflow.com`, `github.com`, `bbc.com`, `justjoin.it`, `glassdoor.com`, `nowsecure.nl`, `indeed.com`, `g2.com`, `linkedin.com`, `allegro.pl`, `amazon.pl`, `amazon.com`, `amazon.co.uk`, `amazon.se`, `amazon.de`, `amazon.fr`, `amazon.it`, `amazon.es`, `amazon.co.jp`, `friendlycaptcha.com`, `mtcaptcha.com`, `hcaptcha.com`, `saucedemo.com`. Matrix rows and Part 2 Call 1 read under profile `default`, Part 2's seed
and Call 2 under profile `e2e`. The commands are identical in PowerShell and Unix shells.

Close this spec's open windows first, as "Closing this spec's windows" under Run describes, because a window still
open can save a session after the delete.

Saved sessions and clearances:

```bash
docker exec redis redis-cli DEL session:example.com:default session:wikipedia.org:default session:toscrape.com:default session:ycombinator.com:default session:wp.pl:default session:reddit.com:default session:stackoverflow.com:default session:github.com:default session:bbc.com:default session:justjoin.it:default session:glassdoor.com:default session:nowsecure.nl:default session:indeed.com:default session:g2.com:default session:linkedin.com:default session:allegro.pl:default session:amazon.pl:default session:amazon.com:default session:amazon.co.uk:default session:amazon.se:default session:amazon.de:default session:amazon.fr:default session:amazon.it:default session:amazon.es:default session:amazon.co.jp:default session:friendlycaptcha.com:default session:mtcaptcha.com:default session:hcaptcha.com:default session:saucedemo.com:default session:saucedemo.com:e2e
```

Remembered tiers (`tier_memory:<domain>`):

```bash
docker exec redis redis-cli DEL tier_memory:example.com tier_memory:wikipedia.org tier_memory:toscrape.com tier_memory:ycombinator.com tier_memory:wp.pl tier_memory:reddit.com tier_memory:stackoverflow.com tier_memory:github.com tier_memory:bbc.com tier_memory:justjoin.it tier_memory:glassdoor.com tier_memory:nowsecure.nl tier_memory:indeed.com tier_memory:g2.com tier_memory:linkedin.com tier_memory:allegro.pl tier_memory:amazon.pl tier_memory:amazon.com tier_memory:amazon.co.uk tier_memory:amazon.se tier_memory:amazon.de tier_memory:amazon.fr tier_memory:amazon.it tier_memory:amazon.es tier_memory:amazon.co.jp tier_memory:friendlycaptcha.com tier_memory:mtcaptcha.com tier_memory:hcaptcha.com tier_memory:saucedemo.com
```

Window results (`novnc_window_result:<domain>:<profile>`, kept about 14 days and not removed by
`session/clear`):

```bash
docker exec redis redis-cli DEL novnc_window_result:example.com:default novnc_window_result:wikipedia.org:default novnc_window_result:toscrape.com:default novnc_window_result:ycombinator.com:default novnc_window_result:wp.pl:default novnc_window_result:reddit.com:default novnc_window_result:stackoverflow.com:default novnc_window_result:github.com:default novnc_window_result:bbc.com:default novnc_window_result:justjoin.it:default novnc_window_result:glassdoor.com:default novnc_window_result:nowsecure.nl:default novnc_window_result:indeed.com:default novnc_window_result:g2.com:default novnc_window_result:linkedin.com:default novnc_window_result:allegro.pl:default novnc_window_result:amazon.pl:default novnc_window_result:amazon.com:default novnc_window_result:amazon.co.uk:default novnc_window_result:amazon.se:default novnc_window_result:amazon.de:default novnc_window_result:amazon.fr:default novnc_window_result:amazon.it:default novnc_window_result:amazon.es:default novnc_window_result:amazon.co.jp:default novnc_window_result:friendlycaptcha.com:default novnc_window_result:mtcaptcha.com:default novnc_window_result:hcaptcha.com:default novnc_window_result:saucedemo.com:default novnc_window_result:saucedemo.com:e2e
```

Each `DEL` prints the number of keys it removed, `0` or more. Any count is fine.

The reader's in-process read cache keeps a successful read for `READ_CACHE_TTL_SECONDS` (300 s) and Redis cannot
reach it. Start this spec at least 300 s after a previous read of any of its addresses (an earlier run of this spec,
spec 3 or spec 6), or the matrix rows answer from the cache without climbing the tier ladder.

## Run

> Execution model: every step is automated, so the Part 1 matrix rows and Part 2 (saucedemo) may fan out across
> parallel e2e-runner agents. Part 2's three steps stay in order on one runner. A row that answers 428 is recorded,
> its window is closed later by the busy-row step or by Post-run cleanup, and no human is asked to act (see
> "Intervention handling on these rows" above).

Move into the Bruno collection root first, from the repository root.

```bash
cd docs/api/request/AscendAI
```

Part 2, Call 1 - login blocked (anonymous).

```bash
bru run "web-hunter/testing/auth-read-secure-anon.yml" --env ascend-local
```

Part 2, Seed - scripted saucedemo login. The harness is not in the image, so the command feeds the script to the
container's Python on standard input and leaves no file behind in the container. The path below is relative to the
Bruno collection root `docs/api/request/AscendAI`, the working directory the Run section moves into.

PowerShell:

```powershell
Get-Content -Raw ../../../../apps/ascend-web-hunter/e2e/harness/seed_authenticated_session.py | docker exec -i -e PYTHONPATH=/app -w /app ascend-web-hunter python -
```

Unix:

```bash
docker exec -i -e PYTHONPATH=/app -w /app ascend-web-hunter python - < ../../../../apps/ascend-web-hunter/e2e/harness/seed_authenticated_session.py
```

Expect the line `[seed] saucedemo: session seeded under profile 'e2e'.`

Part 2, Call 2 - after login.

```bash
bru run "web-hunter/testing/auth-read-secure.yml" --env ascend-local
```

Part 1, the real-world matrix (parallel-safe across runners). A folder run prints only pass or fail per request,
never a response body or header, so it writes its full results to a file. That file is where a `409` row's
`Retry-After` header and `holder_url` are read from. Write it into a new private directory, never a fixed path
under `/tmp` or `$env:TEMP`, so two runs never share a file. Create it once, in the same shell the rest of Part 1,
the Expected checks and the Post-run cleanup run in.

PowerShell:

```powershell
$E2E_OUT = (New-Item -ItemType Directory -Path (Join-Path ([IO.Path]::GetTempPath()) ([IO.Path]::GetRandomFileName()))).FullName
```

Unix:

```bash
E2E_OUT="$(mktemp -d)"
```

PowerShell:

```powershell
bru run "web-hunter/testing/realworld" --env ascend-local -o "$E2E_OUT\realworld-run.json" -f json
```

Unix:

```bash
bru run "web-hunter/testing/realworld" --env ascend-local -o "$E2E_OUT/realworld-run.json" -f json
```

Part 1, retry of a busy row. For each entry in that JSON whose response is HTTP `409` with `code="novnc_busy"`,
first confirm the run genuinely saturated the cap: read `active_flows` and `max_concurrent_flows` from that
entry's `409` body, which carries both as they stood when the service refused the read, and check they are
equal. A listing taken after the folder run cannot show that moment, so never use one for this check. A `409`
whose body reports `active_flows` below `max_concurrent_flows` had a free window slot and is a FAIL at once (see
Contract), never a retry. For a saturated `409`, read the `Retry-After` header and the body's `holder_url` from the entry and record
both, close this spec's windows as described just below, then
re-run only that row's own request file (`web-hunter/testing/realworld/realworld-<row>-<site>.yml`, for example
`realworld-ad-amazon-es-captcha.yml`) with the same `-o <file> -f json` flags into its own file in `E2E_OUT`, up to 3 attempts in
total. Record each attempt and each 409 body's `holder_url` in the run record. The row is a FAIL only after its
third 409. A re-run that answers 428 opens a new window, so close this spec's windows again before the next busy
row's re-run.

Closing this spec's windows. `DELETE /api/v2/session/interventions/{flow_id}` closes one window at once, saves
nothing from it and frees its slot. Every row whose window is closed here has already recorded its verdict, so
closing it changes no verdict. List the open flows whose `domain` (the registrable domain) is one of this spec's
sites. The list covers every site of the matrix and of Part 2, so a window another spec holds is never listed and
never closed.

PowerShell:

```powershell
(Invoke-RestMethod http://127.0.0.1:7021/api/v2/session/interventions).flows | Where-Object { $_.domain -in @('example.com','wikipedia.org','toscrape.com','ycombinator.com','wp.pl','reddit.com','stackoverflow.com','github.com','bbc.com','justjoin.it','glassdoor.com','nowsecure.nl','indeed.com','g2.com','linkedin.com','allegro.pl','amazon.pl','amazon.com','amazon.co.uk','amazon.se','amazon.de','amazon.fr','amazon.it','amazon.es','amazon.co.jp','friendlycaptcha.com','mtcaptcha.com','hcaptcha.com','saucedemo.com') } | Select-Object flow_id, domain
```

Unix:

```bash
curl -fsS http://127.0.0.1:7021/api/v2/session/interventions | python3 -c 'import json,sys; [print(f["flow_id"], f["domain"]) for f in json.load(sys.stdin)["flows"] if f["domain"] in ("example.com","wikipedia.org","toscrape.com","ycombinator.com","wp.pl","reddit.com","stackoverflow.com","github.com","bbc.com","justjoin.it","glassdoor.com","nowsecure.nl","indeed.com","g2.com","linkedin.com","allegro.pl","amazon.pl","amazon.com","amazon.co.uk","amazon.se","amazon.de","amazon.fr","amazon.it","amazon.es","amazon.co.jp","friendlycaptcha.com","mtcaptcha.com","hcaptcha.com","saucedemo.com")]'
```

Expect one line per open window of this spec's sites, and no line when none is open. Close each listed window with
its own call, replacing `<flow_id>` with the listed value.

PowerShell:

```powershell
(Invoke-WebRequest -Method Delete -SkipHttpErrorCheck -Uri "http://127.0.0.1:7021/api/v2/session/interventions/<flow_id>").StatusCode
```

Unix:

```bash
curl -sS -o /dev/null -w "%{http_code}\n" -X DELETE "http://127.0.0.1:7021/api/v2/session/interventions/<flow_id>"
```

Expect `204` for each window closed. A `404` means the window ended on its own between the listing and the delete,
and is accepted only when the listing below no longer shows that flow. Then list the flows again.

PowerShell:

```powershell
Invoke-RestMethod http://127.0.0.1:7021/api/v2/session/interventions
```

Unix:

```bash
curl -fsS http://127.0.0.1:7021/api/v2/session/interventions
```

Expect the body to list no flow for this spec's sites.

## Expected

- **Part 1:** gated rows (a, b, c, d, e, q, aa, ab, ac, ad, ae, af, ag, ah, ai, aj) match their verdict exactly - a-e are `200`/`success` (+ canary where
  noted), q is the `400` hard-fail. Best-effort rows each return a valid terminal verdict (`200`/`success`/content
  **or** `428`/`human_intervention_required`/`vnc_url`); which one is recorded, not failed. A `409` with
  `code="novnc_busy"` is not a verdict: the runner reads its `Retry-After` header and `holder_url` from the
  folder run's JSON output file, closes this spec's earlier windows, and re-runs only that row's own request file,
  up to 3 attempts in total, records each attempt and each 409 body's `holder_url` in the run record, and fails
  the row only on the third 409.
- **Part 1, retail anti-bot rows (u, v, w, x, y):** a valid terminal verdict as above, and on the success branch the
  `content` contains the row's product-identity canary (`er-cbn1` for u, `B09D14YFR9` for v, `9780132350884` for
  w/x/y) and none of the row's interstitial / block-page markers. A `200`/`success` carrying an interstitial fails
  the row.
- **Part 1, tier-pinned row (ak):** read with tier `4a-patchright`; a valid terminal verdict as above
  (HTTP `200`/`success`/content **or** HTTP `428`/`human_intervention_required`/`vnc_url`), never a 5xx.
- **Part 2 - login reuse:** Call 1 (anon) content has **no** auth-only inventory markers; Call 2 (after login)
  returns `status="success"` with an auth-only product description.
- Window closes: every `DELETE` of the busy-row step answered `204` (or `404` only for a window that ended on
  its own), and the listing after each close held no flow for this spec's sites.
- Part 1, row g: a success whose content, in lower case, does not contain
  `accounts are required to access old reddit`, or HTTP `428` with `code="human_intervention_required"` and a
  non-empty `vnc_url` (`intervention_type` `login` expected). A success that carries
  the account wall text fails the row.
- Part 1, row o: a valid terminal verdict as above, and on the success branch the content is at least 1000
  characters and carries none of the sign-in or block-page markers named in "Row o" above.
- No row answered `status="session_expired"`. One that did is a FAIL of the reset (see Contract).

## Post-run cleanup

Close every window this spec's rows still hold, so no row's window keeps a slot or a headful browser after the run.
These are the same commands as "Closing this spec's windows" under Run.

PowerShell:

```powershell
(Invoke-RestMethod http://127.0.0.1:7021/api/v2/session/interventions).flows | Where-Object { $_.domain -in @('example.com','wikipedia.org','toscrape.com','ycombinator.com','wp.pl','reddit.com','stackoverflow.com','github.com','bbc.com','justjoin.it','glassdoor.com','nowsecure.nl','indeed.com','g2.com','linkedin.com','allegro.pl','amazon.pl','amazon.com','amazon.co.uk','amazon.se','amazon.de','amazon.fr','amazon.it','amazon.es','amazon.co.jp','friendlycaptcha.com','mtcaptcha.com','hcaptcha.com','saucedemo.com') } | Select-Object flow_id, domain
```

Unix:

```bash
curl -fsS http://127.0.0.1:7021/api/v2/session/interventions | python3 -c 'import json,sys; [print(f["flow_id"], f["domain"]) for f in json.load(sys.stdin)["flows"] if f["domain"] in ("example.com","wikipedia.org","toscrape.com","ycombinator.com","wp.pl","reddit.com","stackoverflow.com","github.com","bbc.com","justjoin.it","glassdoor.com","nowsecure.nl","indeed.com","g2.com","linkedin.com","allegro.pl","amazon.pl","amazon.com","amazon.co.uk","amazon.se","amazon.de","amazon.fr","amazon.it","amazon.es","amazon.co.jp","friendlycaptcha.com","mtcaptcha.com","hcaptcha.com","saucedemo.com")]'
```

Expect one line per open window of this spec's sites, and no line when none is open. Close each listed window with
its own call, replacing `<flow_id>` with the listed value.

PowerShell:

```powershell
(Invoke-WebRequest -Method Delete -SkipHttpErrorCheck -Uri "http://127.0.0.1:7021/api/v2/session/interventions/<flow_id>").StatusCode
```

Unix:

```bash
curl -sS -o /dev/null -w "%{http_code}\n" -X DELETE "http://127.0.0.1:7021/api/v2/session/interventions/<flow_id>"
```

Expect `204` for each window closed. A `404` means the window ended on its own between the listing and the delete,
and is accepted only when the listing below no longer shows that flow. Then list the flows again.

PowerShell:

```powershell
Invoke-RestMethod http://127.0.0.1:7021/api/v2/session/interventions
```

Unix:

```bash
curl -fsS http://127.0.0.1:7021/api/v2/session/interventions
```

Expect the body to list no flow for this spec's sites.

Then delete the keys this run wrote, the same three `DEL` commands as Reset state. Closing a window writes its
`novnc_window_result` key, so the deletes come after the closes. The commands are identical in PowerShell and Unix
shells.

```bash
docker exec redis redis-cli DEL session:example.com:default session:wikipedia.org:default session:toscrape.com:default session:ycombinator.com:default session:wp.pl:default session:reddit.com:default session:stackoverflow.com:default session:github.com:default session:bbc.com:default session:justjoin.it:default session:glassdoor.com:default session:nowsecure.nl:default session:indeed.com:default session:g2.com:default session:linkedin.com:default session:allegro.pl:default session:amazon.pl:default session:amazon.com:default session:amazon.co.uk:default session:amazon.se:default session:amazon.de:default session:amazon.fr:default session:amazon.it:default session:amazon.es:default session:amazon.co.jp:default session:friendlycaptcha.com:default session:mtcaptcha.com:default session:hcaptcha.com:default session:saucedemo.com:default session:saucedemo.com:e2e
```

```bash
docker exec redis redis-cli DEL tier_memory:example.com tier_memory:wikipedia.org tier_memory:toscrape.com tier_memory:ycombinator.com tier_memory:wp.pl tier_memory:reddit.com tier_memory:stackoverflow.com tier_memory:github.com tier_memory:bbc.com tier_memory:justjoin.it tier_memory:glassdoor.com tier_memory:nowsecure.nl tier_memory:indeed.com tier_memory:g2.com tier_memory:linkedin.com tier_memory:allegro.pl tier_memory:amazon.pl tier_memory:amazon.com tier_memory:amazon.co.uk tier_memory:amazon.se tier_memory:amazon.de tier_memory:amazon.fr tier_memory:amazon.it tier_memory:amazon.es tier_memory:amazon.co.jp tier_memory:friendlycaptcha.com tier_memory:mtcaptcha.com tier_memory:hcaptcha.com tier_memory:saucedemo.com
```

```bash
docker exec redis redis-cli DEL novnc_window_result:example.com:default novnc_window_result:wikipedia.org:default novnc_window_result:toscrape.com:default novnc_window_result:ycombinator.com:default novnc_window_result:wp.pl:default novnc_window_result:reddit.com:default novnc_window_result:stackoverflow.com:default novnc_window_result:github.com:default novnc_window_result:bbc.com:default novnc_window_result:justjoin.it:default novnc_window_result:glassdoor.com:default novnc_window_result:nowsecure.nl:default novnc_window_result:indeed.com:default novnc_window_result:g2.com:default novnc_window_result:linkedin.com:default novnc_window_result:allegro.pl:default novnc_window_result:amazon.pl:default novnc_window_result:amazon.com:default novnc_window_result:amazon.co.uk:default novnc_window_result:amazon.se:default novnc_window_result:amazon.de:default novnc_window_result:amazon.fr:default novnc_window_result:amazon.it:default novnc_window_result:amazon.es:default novnc_window_result:amazon.co.jp:default novnc_window_result:friendlycaptcha.com:default novnc_window_result:mtcaptcha.com:default novnc_window_result:hcaptcha.com:default novnc_window_result:saucedemo.com:default novnc_window_result:saucedemo.com:e2e
```

Each `DEL` prints the number of keys it removed. Any count is fine.

Last, remove the report directory with the folder run's results file and every re-run file in it. The Expected
checks have read them by now.

PowerShell:

```powershell
Remove-Item -Recurse -Force $E2E_OUT
```

Unix:

```bash
rm -rf "$E2E_OUT"
```

Expect no output.

## Fixtures

None - and **no secrets**: saucedemo's credentials are its public demo values, hardcoded in the harness;
LinkedIn/indeed are intervention-only. URLs, selectors, and markers are hardcoded
in the harness and Bruno requests, except the five retail anti-bot rows (u, v, w, x, y), whose target URLs come from
the collection variables `scrap_url_allegro`, `scrap_url_amazon`, `scrap_url_amazon_com`, `scrap_url_amazon_uk` and
`scrap_url_amazon_se` in `docs/api/request/AscendAI/web-hunter/folder.yml`. Swapping a listing that goes out of stock
is then a one-line variable edit, and the row's product-identity canary is the only other thing to update with it. (A future real-secret login would read from the environment, never commit creds.)
The login-and-seed harness is a Playwright script under `e2e/harness/`.

## Concurrency

- Mutates: Redis, the `session:<domain>:default`, `tier_memory:<domain>` and
  `novnc_window_result:<domain>:default` keys for the matrix domains (including `allegro.pl`, `amazon.pl`,
  `amazon.com`, `amazon.co.uk` and `amazon.se` from the retail anti-bot rows, and the five rows aa to ae for five
  Amazon marketplaces: `amazon.de`, `amazon.fr`, `amazon.it`, `amazon.es` and `amazon.co.jp`), and
  `session:saucedemo.com:e2e` plus `novnc_window_result:saucedemo.com:e2e` for Part 2. Reset and cleanup delete
  exactly these keys.
- Conflicts with: test 6 and test 3 (they share `wikipedia.org`, `toscrape.com` and `example.com` keys and read
  cache entries with the matrix), and any test sharing a target domain's key. Row u's
  428 holds one NoVNC window slot test 11's human may need until this spec closes it, and the matrix must not run
  beside spec 20
  ([20-concurrent-interventions-test.md](../../../apps/ascend-web-hunter/e2e/testing/20-concurrent-interventions-test.md)), which fills every window slot on
  purpose. Never beside spec 22
  ([22-human-login-reuse-test.md](../../../apps/ascend-web-hunter/e2e/testing/22-human-login-reuse-test.md)): this spec's window closes cover `linkedin.com`,
  so they would close its login window, and its `tier_memory:linkedin.com` delete would remove the tier spec 22
  remembers. Within this
  test, Part 2's sequence (anon, then seed,
  then authed) is strictly ordered.
- Serial: false vs non-overlapping tests. No human step, so every part may fan out across e2e-runner subagents.
