# Web-scraping e2e capability tests proposal: tiered (#6) + authenticated/real-world (#7)

## Why

The AscendWebSearch read path escalates across four extraction tiers — `curl_cffi` (fast static HTTP),
FlareSolverr (Cloudflare WAF bypass), Playwright (client-side-rendered pages), and NoVNC (human CAPTCHA
intervention). Today the e2e suite proves only the cheapest tier: test 3 reads `example.com`, a plain static page
that the `curl_cffi` tier satisfies on its own. The Cloudflare, JavaScript-rendering, and CAPTCHA tiers — the
escalation logic that is the entire reason this service exists — have **zero end-to-end coverage**. A regression
that broke FlareSolverr wiring or Playwright rendering would pass the current suite and only surface when a real
WAF'd or JS-heavy page silently returned empty content.

This change adds one capability test that drives `POST /api/v2/web/read` against a tier-mapped list of real
websites — each URL chosen to force a specific extraction tier — so every tier is exercised and a per-tier
breakage is caught. The URL list is deliberately provisional: live external sites rotate WAFs and go down, so the
table is a living fixture refined as real targets are discovered.

## What this will verify

- `POST /api/v2/web/read` returns HTTP 200 with `status="success"` and a non-empty content field
  (`content` / `text` / `markdown`) for each site in the tier table that is in the automated gate.
- **Static tier (`curl_cffi`):** `https://en.wikipedia.org/wiki/Web_scraping` returns content containing the
  canary phrase `"web scraping"` — proves real server-rendered article extraction beyond the `example.com`
  baseline.
- **Cloudflare tier (FlareSolverr):** a Cloudflare-challenged URL returns `status="success"` with non-empty
  content — proves the challenge was solved rather than the bot-block page being returned.
- **JavaScript tier (Playwright):** a client-side-rendered page returns content that is **absent from the raw
  HTML** — proves JS execution actually rendered the DOM (e.g. quote text from `quotes.toscrape.com/js/`).
- The response shape is identical across tiers (the caller never learns which tier served the request) — proves
  the escalation is transparent.
- **CAPTCHA tier (NoVNC):** documented as a manual, best-effort step **outside** the pass/fail gate, since it
  requires human interaction and cannot be asserted unattended.

## Setup cost class

- [x] 1: No state to reset, no fixtures, hits a single endpoint or MCP tool.
- [ ] 2: Single fixture upload OR vision-capable model OR PDF parsing.
- [ ] 3: Single-service reset (e.g. Redis only).
- [ ] 4: Multi-service reset (DB + Redis + Qdrant + MinIO).
- [ ] 5: Seeded state + observation of an async background process.

No backing state is reset (the optional Redis-key flush is the same idempotent step test 3 already uses). The
rubric class is 1, but the **egress and dependency cost is the highest in the suite** — it needs outbound HTTPS to
several external sites plus healthy FlareSolverr and Playwright tiers — so by the suite's cost-ordering convention
it takes the highest number and runs **last**.

## Fixtures needed

None. The AscendWebSearch read tool takes a URL string argument, not an uploaded file; the "fixtures" here are the
live external URLs declared in the tier table of the test-spec.

## Concurrency profile

- **Mutates:** Redis — AscendWebSearch session / cookie cache, keys for this test's target domains
  (`en.wikipedia.org`, the Cloudflare target, `quotes.toscrape.com`, and any real-world category sites added
  later). The extraction pipeline writes per-domain session cookies on a successful fetch.
- **Conflicts with:** any other test that reads or scrapes the same target URLs and may flush their Redis keys —
  in the current suite that is test 3 (shared `example.com` key only if `example.com` is added to this table;
  otherwise no overlap). Does not conflict with the search tests (1, 2, 4, 5), which touch only ephemeral SearXNG
  cache.
- **Serial:** false.

## API client invocation

Bruno requests under `docs/api/request/AscendAI/web-search/testing/`, one per gated tier (created when this change
is applied):

- `extract-tier-static-wikipedia.yml` — `POST /api/v2/web/read` for the Wikipedia article.
- `extract-tier-cloudflare.yml` — `POST /api/v2/web/read` for the Cloudflare-challenged URL.
- `extract-tier-js-quotes.yml` — `POST /api/v2/web/read` for the JS-rendered page.

Run individually or via Bruno directory mode against `web-search/testing` with `--env ascend-local`.

## Number assignment

N: 6

## Next steps

After this proposal is approved:

- Generate `e2e/testing/6-tiered-scraping-test.md` from the `test-spec` artifact.
- Generate `e2e/testing/templates/6-tiered-scraping-tasks.template.md` from the `tasks-template` artifact.
- Each execution generates a `run` record under `e2e/testing/runs/`.

---

## Test 7 — Authenticated + real-world scraping coverage

### Why

Test 6 proves each extraction *tier* works against fixed canaries. It does not prove the scraper behaves correctly
across a **broad set of real-world URLs** (job boards, news, social, login walls), nor does it cover the
**authenticated capture→replay** path that the `enhance-web-search-scraping` anchor just shipped (the LinkedIn-class
fix). A regression that makes the scraper return a login/block page as `success`, or that breaks session replay,
would pass test 6. This test closes both gaps and — crucially — encodes **expected negatives** so false positives
are caught.

### What this will verify

- A categorized matrix of real-world URLs each produces its **expected verdict** — `success`, `intervention`
  (`status="human_intervention_required"` + `vnc_url`), or `hard-fail` (`status != "success"`). The verdict, not
  just "some content", is asserted. **LinkedIn / indeed-auth are tested as intervention-only** (no scripted login —
  ToS / account-ban risk).
- The **authenticated capture→replay** flow: a test-harness Playwright login on a stable, automation-friendly site
  using `.env.local` credentials → capture `storage_state` → seed the session store → an authenticated read returns
  logged-in-only content, while the same read **without** a session does not.
- Stable canaries (the Cloudflare site, the dead-domain negative) are **gated/must-pass**; live real-world URLs are
  **best-effort** (verdict recorded, a miss does not fail the suite).

### Setup cost class

- [x] 5: Seeded state + observation of an async/secondary flow. The authenticated section seeds the session store
  from a captured browser login before reading. Highest cost in the suite — runs after test 6.

### Fixtures needed

None uploaded. The only secrets are the per-service login credentials in `AscendWebSearch/e2e/.env.local`
(`SAUCEDEMO_USER` / `SAUCEDEMO_PASS`, one pair per login-walled service) — never committed. Login/secure URLs,
selectors, and markers are hardcoded in the harness and Bruno requests. The login-and-seed harness is a Playwright
script under `e2e/harness/`.

### Concurrency profile

- **Mutates:** Redis — AscendWebSearch session store, keys for the matrix domains and the `e2e` profile of the
  login site.
- **Conflicts with:** test 6 and any test sharing a target domain's session key; the internal Steps B→C→D are
  strictly ordered.
- **Serial:** false (vs non-overlapping tests).

### API client invocation

Bruno requests under `docs/api/request/AscendAI/web-search/testing/realworld/` (one per matrix row), plus
`auth-read-secure.yml` / `auth-read-secure-anon.yml` for Steps C/D, plus the Playwright harness
`e2e/harness/seed_authenticated_session.py` for Step B. **All created when this change is applied** — this proposal
defines the test; implementation follows approval.

### Number assignment

N: 7

### Open design point

The Step-B seed writes the captured `storage_state` into the service's Redis session store at
`session:{domain}:{profile}` (white-box coupling to the store's key format). A future `POST /session/import`
endpoint would decouple the harness from store internals; flagged for a follow-up.
