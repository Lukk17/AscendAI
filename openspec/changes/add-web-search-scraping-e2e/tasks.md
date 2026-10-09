NEVER ARCHIVE: this living end-to-end suite change is never archived (owner decision 2026-10-08, answer 12). It stays open with its run artifact unchecked by design. No future agent run may archive it or propose archiving it.

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

This change stays open on purpose. It is the living ascend-web-hunter e2e suite, and new specs are added here as tasks in section 4 until the owner decides to archive it.

- [x] 6.1 Moved out of this change on 2026-10-01 by the owner's decision. The `POST /api/v2/web/session/import` endpoint, which removes the Part 2 harness's direct write of `session:{domain}:{profile}`, is now planned and tracked in `openspec/changes/add-web-session-import/`, whose task 3.5 points back here.
- [x] 6.2 Correct this module's spec count in `docs/E2E_COST.md`. Checked 2026-10-01: the document already states 12 ascend-web-hunter specs and the verified 58 / 43 / 15 split (58 specs outside the storage group, 43 free, 15 paid).

## 7. Shared end-to-end parts for the planned web-hunter changes

Owner request of 2026-10-04: every planned change carries end-to-end tests. These tasks build the parts the planned specs share, per design D10 to D14. This change is build group 1, position 3 of the owner build order of 2026-10-04, so these tasks land before every web-hunter change of build group 2 and need no earlier change. The parts that need the URL guard and the problem body of the `ascend-python-common` library (design D12 and D13) moved to `add-ascend-python-common` (build group 2, position 1).

- [x] 7.1 The owner answered how the fake site's success rows reach it (owner answer 67.3 of 2026-10-04): through the URL guard's own allow list, with a test-only settings file that allows exactly the fake site's host name `e2e-fake-site`, and a test that proves the production settings allow nothing. Design D12 records it, and tasks 9.10 and 9.11 of `add-ascend-python-common` build it (the former tasks 7.7 and 7.8 of this change, moved there by the dependency fix of 2026-10-05). No public address is needed, so no planned spec has a row waiting on this task. Rework by owner decision 90 of 2026-10-08: task 7.9.
- [x] 7.2 Build the fake site of design D11 in `apps/ascend-web-hunter/e2e/fake-site/` (app, `Dockerfile`, and `files/` with each canary file, its canary text and its SHA-256 listed in `apps/ascend-web-hunter/e2e/fixtures/README.md`), with the request log at `GET /__requests`, `POST /__reset` and `POST /__state`. Pick its loopback port at implementation time from the ports no service in the root `AGENTS.md` uses, and record it there. Verify that the image builds, that every page and file answers with its documented status, `Content-Type` and `Content-Length`, and that the request log records a request and is empty after a reset.
  Evidence 2026-10-07: port `7031` (bind-tested free; root AGENTS.md uses 9917/7017/7021/7020/9998/7022/5432/6379/6333/6334/9070/9071/5001/9080/9020/8191). `docker build -t e2e-fake-site:latest apps/ascend-web-hunter/e2e/fake-site` passes. Live run on 127.0.0.1:7031: pages `/article` `/product` `/tables` 200 `text/html; charset=utf-8` with `Content-Length`; files pdf/png/zip/docx/docm/kicad/elf 200 with documented `Content-Type` and `Content-Length` (664/1070/180/888/1048/125/124); `/redirect-1` 302, `/wall-header` and `/rich-403` 403, unknown path 404; `/oversized-declared` 200 with `content-length: 3309568`, `/oversized-undeclared` and `/slow` 200 chunked without `Content-Length`; matching `If-None-Match` answers 304 with 0 bytes; `POST /__state` toggles `/article` 200/404 and `/product` layouts 1/2; `GET /__requests` records method/path/headers/bytes and `POST /__reset` returns `{"reset":true}` with the log `[]` after.
- [x] 7.3 Add the fake site start and stop commands to "Prerequisites before any test" in `apps/ascend-web-hunter/e2e/README.md`: one `docker run` on the network `ascend-web-hunter` uses (checked with `docker network ls` at implementation time) with the two network names `e2e-fake-site` and `e2e-fake-site-blocked` of design D12, and `docker rm -f` after the sweep. `add-ascend-python-common` adds the allow list steps to the same section later. Verify that from inside the `ascend-web-hunter` container both names resolve to a private address, and that the runner reaches the request log from the host.
  Evidence 2026-10-07: network `ascend-ai_default` (inspect shows ascend-web-hunter on it, no ascend-scrapper_default in `docker network ls`). `docker run -d --name e2e-fake-site --network ascend-ai_default --network-alias e2e-fake-site --network-alias e2e-fake-site-blocked -p 127.0.0.1:7031:7031 e2e-fake-site:latest` up with `curl http://127.0.0.1:7031/__requests` answering `{"requests":[]}`; `docker exec ascend-web-hunter getent hosts` answers `172.25.0.5` for both names; `docker rm -f e2e-fake-site` removes it.
- [x] 7.5 Add "Deterministic first" to the cross-cutting conventions of `apps/ascend-web-hunter/e2e/testing/README.md` and `apps/ascend-web-hunter/e2e/README.md`: design D10, the rule that a new spec takes the next free number at implementation time, and the rule that a changed feature updates its existing spec in place (owner answer 67.2 of 2026-10-04). Verify both files state the rule once.
  Evidence 2026-10-07: one `Deterministic first` paragraph per file, `Select-String 'Deterministic first'` returns exactly one hit per file, em/en dash lint clean.
- [x] 7.6 Add the fake site to the preconditions of scenarios 1 to 6 and of the ascend-web-hunter service suite in `docs/E2E_RUN_SCENARIOS.md`, per design D14. Verify each precondition list names the fake site start command and each post-sweep list names its removal. `add-ascend-python-common` adds the allow list steps to the same lists later.
  Evidence 2026-10-07: scenarios 1 to 6 and the ascend-web-hunter service suite each name the 7.3 start command in preconditions and `docker rm -f e2e-fake-site` post-sweep, no allow list step added. `Select-String` returns 7 hits per command and 6 `### Post-sweep` headings plus the service suite post-sweep line, em/en dash lint clean.
- [ ] 7.9 Owner decision 90 of 2026-10-08 replaces the test-only settings file of task 7.1: `e2e-fake-site` is allowed only by the start command of a sweep, which sets `WEB_HUNTER_ALLOWED_PRIVATE_HOSTS=e2e-fake-site` in the shell of one `docker compose up -d ascend-web-hunter` command, and the development compose service passes it as `ALLOWED_PRIVATE_HOSTS=${WEB_HUNTER_ALLOWED_PRIVATE_HOSTS:-}`, empty by default (design D12, `add-ascend-python-common` D23 and its tasks 4.14, 9.10 and 9.11, which build it). Nothing in this change's done work names the old file: check that `apps/ascend-web-hunter/e2e/README.md` and `docs/E2E_RUN_SCENARIOS.md`, which tasks 7.3 and 7.6 wrote, name no `allowed-hosts.e2e.env`, no `e2e/.run/` folder and no copy step. Verify: `git grep -n "allowed-hosts.e2e.env\|e2e/.run" -- apps/ascend-web-hunter docs/E2E_RUN_SCENARIOS.md .gitignore compose.ascend-web-hunter.yaml` returns nothing.

Task 7.4 moved to `add-ascend-python-common` (dependency fix of 2026-10-05).
Task 7.7 moved to `add-ascend-python-common` (dependency fix of 2026-10-05).
Task 7.8 moved to `add-ascend-python-common` (dependency fix of 2026-10-05).
