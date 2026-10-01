## 1. Spec 6 - tiered extraction coverage

- [x] 1.1 Write `apps/ascend-web-hunter/e2e/testing/6-tiered-scraping-test.md` from the `test-spec` artifact, with the six-section structure (What this verifies / Prerequisites / Reset state / Run / Expected / Fixtures).
- [x] 1.2 Map each gated row to the tier it forces: row 1 `en.wikipedia.org/wiki/Web_scraping` for curl_cffi, row 2 `www.scrapingcourse.com/cloudflare-challenge` for FlareSolverr, row 3 `quotes.toscrape.com/js/` for a browser tier.
- [x] 1.3 Add the Bruno requests `extract-tier-static-wikipedia.yml`, `extract-tier-cloudflare.yml` and `extract-tier-js-quotes.yml` under `docs/api/request/AscendAI/web-hunter/testing/`.
- [x] 1.4 Write the sidecar `testing/templates/6-tiered-scraping-tasks.template.md` from the `tasks-template` artifact, checkbox for checkbox, with the Result summary block and the Additional tasks I did section.
- [x] 1.5 Harden row 3's assertion beyond the proposal's wording. The shipped spec asserts the canary phrase AND that the serving `mode` names a browser tier, because the phrase does appear inside an inline `<script>` block in the raw markup, so a raw-HTML absence check alone was not the proof it claimed to be.
- [x] 1.6 Record the scrapingcourse.com per-address cool-down in the spec, with the verbatim FlareSolverr timeout line, so a row 2 failure caused by rate limiting is not read as a stack defect.

## 2. Spec 7 - authenticated and real-world coverage

- [x] 2.1 Write `apps/ascend-web-hunter/e2e/testing/7-authenticated-realworld-scraping-test.md` covering both parts.
- [x] 2.2 Part 1: build the difficulty-graded matrix with per-row expected verdicts, gating the stable canaries and leaving live sites best-effort on which branch fires.
- [x] 2.3 Part 1: encode the expected negatives, so a dead domain must hard-fail with HTTP 400 and the login walls must answer HTTP 428 with a `vnc_url` rather than a success body.
- [x] 2.4 Part 1: content-gate the five retail anti-bot rows on a product-identity canary plus the absence of every measured interstitial and block-page marker, so an interstitial can never be recorded as a successful scrape.
- [x] 2.5 Part 1: define the `409` / `novnc_busy` retry rule (wait the advertised `Retry-After`, up to three attempts, record every attempt and holder, fail only on the third).
- [x] 2.6 Part 2: write the scripted-login harness `apps/ascend-web-hunter/e2e/harness/seed_authenticated_session.py` against `saucedemo.com` with its public demo credentials and no secrets.
- [x] 2.7 Part 2: add the `auth-read-secure-anon.yml` and `auth-read-secure.yml` Bruno requests, the anonymous call asserting the login wall and the absence of every auth-only marker, the authenticated call asserting at least one of them.
- [x] 2.8 Add the twenty-four `realworld/` Bruno requests, one per Part 1 row, plus their folder settings.
- [x] 2.9 Write the sidecar `testing/templates/7-authenticated-realworld-scraping-tasks.template.md`.
- [x] 2.10 Retarget the human-solved CAPTCHA part. The proposal put it in spec 7 against the Google reCAPTCHA v2 demo; it shipped as its own spec 11 against the democaptcha hCaptcha demo form, which leaves an `hmt_id` cookie on the human's checkbox click. Spec 7 is fully automated as a result.

## 3. Suite scaffolding

- [x] 3.1 Create `apps/ascend-web-hunter/e2e/` with `README.md`, `fixtures/`, `harness/` and `testing/`, and `testing/` holding the numbered specs plus `templates/` and `runs/`.
- [x] 3.2 Gitignore the run records at `apps/ascend-web-hunter/e2e/testing/runs/*` with an exception for that directory's `README.md`.
- [x] 3.3 Write the suite README: the file tree, the flow diagram, the per-spec cost ordering, the capability table, the prerequisites, the invocation commands and the how-to-add-a-test steps.
- [x] 3.4 Declare the concurrency and ordering constraints per spec in the README, naming the exact Redis keys each spec mutates and which specs therefore cannot run together.
- [x] 3.5 Point the README at `docs/E2E_RUN_SCENARIOS.md` and require a run scenario to be chosen before any execution.
- [x] 3.6 Keep the Bruno collection at the repo root under `docs/api/request/AscendAI/web-hunter/testing/` rather than inside the module, so it stays a portable API-client artifact, and leave the pre-existing ad-hoc requests one level up untouched.
- [x] 3.7 Add the seed fixtures `session-clear-seed.json` and `session-status-expired-seed.json` with their own `fixtures/README.md`.

## 4. Suite growth past the two proposed specs

- [x] 4.1 Spec 8, `session/clear`: the operator-recovery path, proving a seeded session is removed and that clearing a session that never existed is a documented no-op rather than a 404.
- [x] 4.2 Spec 9, `session/status`: all three states the endpoint's own type declares, `none`, `expired` and `active`.
- [x] 4.3 Spec 10, `session/establish`: the immediate response plus the live-verified finding that the background monitor captures a session on its first poll without any challenge having been solved.
- [x] 4.4 Spec 11, human-solved hCaptcha and its capture, carved out of spec 7 so spec 7 could become fully automated.
- [x] 4.5 Spec 12, stored Cloudflare clearance reused on a second read of the same site, with the second call addressed differently so the in-memory read cache cannot answer it.
- [x] 4.6 Add the matching templates and Bruno requests for specs 8 through 12.

## 5. Execution evidence

- [x] 5.1 Run the suite under a named scenario from `docs/E2E_RUN_SCENARIOS.md`. Executed 2026-09-18 under scenario 6, the `ascend-scrapper` compose project alone, fully automated, no human.
- [x] 5.2 Eleven of eleven automated specs returned PASS, all sharing the sweep timestamp `2026-09-18T14-20-20` in `apps/ascend-web-hunter/e2e/testing/runs/`.
- [x] 5.3 Spec 6 proved all three tiers: row 1 through `1-beautifulsoup`, row 2 through `3-flaresolverr`, row 3 through `4-playwright_stealth`.
- [x] 5.4 Spec 7 Part 2 proved authenticated capture and replay: the cold read of `https://www.saucedemo.com/inventory.html` returned 283 characters reading "You can only access '/inventory.html' when you are logged in" with none of the auth-only markers, and after the harness stored a 621-byte `storage_state` under `session:saucedemo.com:e2e` the same URL with `profile=e2e` returned 1062 characters carrying `carry.allTheThings()`, "lighting modes", "ringspun combed cotton" and "quarter-zip fleece" through the `4-playwright_stealth` tier.
- [x] 5.5 Spec 7 Part 1 proved the expected negatives: the dead domain answered HTTP 400 with no success body, and the login walls answered HTTP 428 with a `vnc_url`.
- [x] 5.6 Spec 7's five retail anti-bot rows all took the success branch and all carried their product-identity canary with no interstitial marker, so the interstitial-reported-as-success defect those rows exist to catch did not appear.
- [x] 5.7 Spec 12 proved clearance reuse, so register defect A61 did not reproduce on this run.
- [x] 5.8 Spec 11 was correctly excluded, since scenario 6 has no human at the keyboard.

## 6. Still open

- [ ] 6.1 Add a `POST /api/v2/web/session/import` endpoint so the Part 2 harness stops writing `session:{domain}:{profile}` directly and loses its white-box coupling to the store's key format. Flagged as an open design point in the proposal and still open.
- [ ] 6.2 Correct this module's spec count in `docs/E2E_COST.md`, which still reads 10 ascend-web-hunter specs against the 12 now on disk, and update the 48 / 33 / 15 totals that number feeds.
