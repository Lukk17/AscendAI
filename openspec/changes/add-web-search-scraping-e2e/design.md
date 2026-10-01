## Context

ascend-web-hunter answers a read by escalating through a fixed chain of tiers: `1-beautifulsoup` and `2-trafilatura` over the shared curl_cffi fetcher, then `3-flaresolverr`, `4-playwright_stealth`, `5-crawlee_adaptive`, and `6-novnc` for a human. Before this change the e2e suite proved only the cheapest of those, through spec 3's read of `example.com`, which the curl_cffi tier satisfies on its own. The WAF, JavaScript and human tiers, which are the reason the service exists, had no end-to-end coverage at all, and neither did the authenticated capture-and-replay path that `enhance-web-search-scraping` landed.

The suite that shipped is larger than the two specs this change proposed. Specs 6 and 7 are the ones proposed here. Specs 8 through 12 grew out of them: 8, 9 and 10 close the gap between the session endpoints that existed in the router and the specs that covered them, 11 is the human CAPTCHA part carved out of spec 7, and 12 is the clearance-reuse proof that spec 11 cannot give. All twelve share one contract, one README and one set of ordering rules, so they are described here as a single capability rather than twelve unrelated files.

## Goals / Non-Goals

**Goals:**

- Prove each extraction tier separately, so a per-tier regression fails a named row rather than silently degrading a read.
- Prove that a captured session is replayed on a later read, which is the behaviour most likely to rot and hardest to notice when it does.
- Encode expected negatives, so a login page or an anti-bot interstitial returned as `status="success"` fails the suite instead of passing it.
- Keep every assertion observable: HTTP status, response body, and persisted Redis state.

**Non-Goals:**

- Unit or integration coverage. Those live in `apps/ascend-web-hunter/tests/` behind the 100 percent branch-coverage gate and are not duplicated here.
- Asserting which tier served a read, except where the tier is the thing under test (spec 6 row 3 and spec 12).
- Unattended coverage of the human CAPTCHA path. A human solve cannot be asserted without a human.
- Any scraping that needs a real credential. Every login in the suite uses a site's own public demo account.

## Decisions

**D1 - One spec per capability, numbered by setup cost.** The suite follows the same runner contract as `ai-driven-e2e-runner`, applied to `apps/ascend-web-hunter/e2e/`: an immutable `<N>-<feature>-test.md` with the six fixed sections, an immutable sidecar `<N>-<feature>-tasks.template.md` whose checkboxes mirror it one for one, and a per-run record copied into `runs/` under a UTC timestamp shared by every spec in one sweep. The number prefix orders by setup cost, cheapest first, so a broken validator fails before any egress is spent.

**D2 - Tiers are forced by target choice, not by a tier override.** The read API exposes no way to ask for a particular tier, so spec 6 picks three targets whose own properties force the escalation: a static article the cheap tier can serve, a Cloudflare-challenged page only FlareSolverr clears, and a page whose text is injected by client-side JavaScript. This keeps the test honest about the production path, since a tier override would test a code path no caller uses.

**D3 - Row 3's proof had to be strengthened.** The proposal asserted that the JS canary phrase is absent from the raw HTML, so its presence proves rendering. That turned out to be false: the phrase is present in the page's raw markup inside an inline `<script>` block. The shipped spec therefore asserts both the phrase in the extracted prose and a `mode` naming a browser-executing tier, which is a claim the raw markup cannot satisfy by accident.

**D4 - Authenticated coverage is a two-call before-and-after, not a single authenticated read.** A single read of a gated page proves nothing, because the page might be public. Spec 7 Part 2 reads `https://www.saucedemo.com/inventory.html` twice: once with no session, which must return the login wall and none of the auth-only markers, and once with `profile=e2e` after a scripted login seeded the session, which must return the inventory content. Same URL, same service, only the stored session different. saucedemo is a real login with a real session against a stable SPA, and its credentials are the public demo pair printed on its own login page, so no secret enters the repository.

**D5 - Expected negatives carry equal weight.** Spec 7 Part 1 asserts a verdict per row rather than "some content came back". A dead domain must hard-fail with HTTP 400, the login walls must answer HTTP 428 with a `vnc_url`, and the five retail anti-bot rows are content-gated: a `200` / `success` must carry the requested product's identity canary and none of the measured interstitial or block-page markers. An interstitial recorded as a successful scrape is the defect those rows exist to catch.

**D6 - Live sites are best-effort on the branch, strict on the content.** A live site can legitimately answer either branch on a given day, and failing the suite for that would make it noise. So a live row passes on any valid terminal verdict, but if it takes the success branch it must satisfy the content gate. A `409` / `novnc_busy` is not a verdict at all: the row waits the advertised `Retry-After` and retries, up to three attempts, and fails only on the third.

**D7 - The human CAPTCHA path is its own spec, and capture is the assertion.** It started as spec 7 Part 3 against the Google reCAPTCHA v2 demo. It shipped as spec 11 against the democaptcha hCaptcha demo form, for two reasons: keeping it inside spec 7 made an otherwise fully automated spec need a human, and the assertion had to be capture rather than reuse, because that form renders its widget on every load and so can never demonstrate reuse (register A60). Spec 11 asserts that the human's checkbox click left `session:democaptcha.com:default` behind carrying the `hmt_id` cookie hCaptcha sets on that click. Reuse is spec 12's job, on a site whose wall disappears once the clearance is stored.

**D8 - Ordering constraints are declared, not discovered.** Every spec names the exact Redis keys it mutates and which specs it therefore conflicts with, and the README carries a recommended order. This matters more here than in other modules because several specs compare a whole `session:*` scan before and after, which any concurrent session write breaks. Spec 12 runs after spec 6 because both write `session:scrapingcourse.com:default`, and before spec 7 because spec 7's reset flushes every `session:*` key.

**D9 - The Bruno collection stays at the repo root.** The requests live under `docs/api/request/AscendAI/web-hunter/testing/` rather than inside the module, so the collection remains a portable API-client artifact a human can open and drive by hand. The pre-existing ad-hoc requests one level up are left untouched as dev-time fixtures.

## Risks / Trade-offs

- **Live external targets rotate.** The tier table is provisional by design. scrapingcourse.com in particular rates the caller's address and refuses headless browsers for a while after several solves in a day, which is why the spec records that cool-down verbatim: a failure with that FlareSolverr timeout line is a rate limit, not a stack defect.
- **Spec 10 leaves a browser running.** It launches a real headful Playwright browser that a background monitor can hold for up to ten minutes after its own assertions pass. It makes no priced call, but it is the highest per-run resource cost in the module and must not run alongside itself.
- **The Part 2 harness writes the store's key format directly.** `seed_authenticated_session.py` writes `session:{domain}:{profile}` itself, which couples the test to an internal key shape. A `POST /session/import` endpoint would decouple it. Left open.
- **The run records are gitignored.** Evidence for a sweep lives on the machine that ran it unless an operator force-adds a record, so a claim about a past run has to cite the record path rather than a commit.

## What shipped differently from the proposal

- The CAPTCHA part moved out of spec 7 into spec 11 and changed target from Google reCAPTCHA v2 to the democaptcha hCaptcha demo form (D7).
- Spec 7 Part 1 grew from the proposal's sketch of a category list into a twenty-four row graded matrix, including five retail anti-bot rows the proposal did not anticipate.
- Row 3's rendering proof changed from a raw-HTML absence check to a canary plus serving-tier check (D3).
- Five specs beyond the two proposed here shipped as part of the same suite (8 through 12).
