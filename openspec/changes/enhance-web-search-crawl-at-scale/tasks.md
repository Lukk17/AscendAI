Every command runs from `apps/ascend-web-hunter/` through `.venv/Scripts/python.exe -m <tool>` (Windows) or
`.venv/bin/python -m <tool>` (Linux and macOS). The gate is
`python -m pytest --cov=src --cov-branch --cov-report=term-missing --cov-fail-under=100`.
Start only after `add-ascend-python-common` is applied, so ascend-web-hunter already imports the library.

## 1. Configuration and dependencies

- [ ] 1.1 Add the S3 client and `protego` to `pyproject.toml` with exact pins. Verify `python -m pip install -e ".[dev]"`.
- [ ] 1.2 Add every setting in `design.md` D2, D3, D5, D7 and D8 to `src/config/config.py`: the shared
      `OBJECT_STORE_S3_ENDPOINT`, `OBJECT_STORE_S3_ACCESS_KEY` and `OBJECT_STORE_S3_SECRET_KEY`, the crawl
      `CRAWL_RESULT_S3_BUCKET` and `CRAWL_RESULT_S3_PREFIX`, and no `CRAWL_ERASE_DRAIN_SECONDS` (it moved with the erase
      call of design D11 to `add-audit-and-gdpr-compliance`), `CRAWL_RESULT_S3_ENDPOINT`,
      `CRAWL_RESULT_S3_ACCESS_KEY`, `CRAWL_RESULT_S3_SECRET_KEY` or `CRAWL_DEFAULT_TENANT`. Add also the two settings
      of design D15 (owner answer 94.1 of 2026-10-08): `CRAWL_CLAIM_LEASE_SECONDS` (default 120, at least 1) and
      `CRAWL_WORKER_CONCURRENCY` (default 4, at least 1). The default
      `http://localhost:9070` of `OBJECT_STORE_S3_ENDPOINT` serves a native run only (design D3). Owner rule 98 of
      2026-10-08 (design D16): every row of the D16 table is a `Settings` field with exactly the default of that table,
      the new `CRAWL_MAX_PATTERNS` (50), `CRAWL_DEFAULT_DEPTH` (2), `CRAWL_DEFAULT_PAGE_BUDGET` (100) and
      `CRAWL_CLAIM_MAX_EXPIRIES` (2, at least 1) included, and no module constant of `src/crawl/` holds a value of that
      table. `CRAWL_DEFAULT_DEPTH` above `CRAWL_MAX_DEPTH` and `CRAWL_DEFAULT_PAGE_BUDGET` above `CRAWL_MAX_PAGES` are
      refused at startup. `CRAWL_WORKER_IDLE_SECONDS` has the default 1 and `CRAWL_POLL_AFTER_SECONDS` the default 5
      (owner answer 100.1 of 2026-10-09, design D16). The two object store keys have no default. Verify
      with cases in `tests/config/test_config.py` for every default, every bound and both startup refusals.
- [ ] 1.3 Add every setting of design D16 to the `ascend-web-hunter` service of `compose.ascend-web-hunter.yaml` and of
      `deploy-standalone/compose.yaml` as `- VAR=${VAR:-default}` with the D16 default, the two object store keys as
      `${VAR}` with no default, and add each to the root `.env.example`, `deploy-standalone/.env.example` (a commented
      `# VAR=default` line with a one line comment for a setting with a default, an empty line for each key) and the
      standalone README table, all in the same commit (sync rule of `apps/ascend-web-hunter/AGENTS.md`). In both compose
      files the endpoint is `OBJECT_STORE_S3_ENDPOINT=${OBJECT_STORE_S3_ENDPOINT:-http://host.docker.internal:9070}`,
      which resolves on Linux Docker Engine because the `ascend-web-hunter` service already declares
      `extra_hosts: "host.docker.internal:host-gateway"` (design D3). Verify `docker compose config` from the repository
      root succeeds and shows that endpoint, every D16 setting with its default and the `extra_hosts` line on
      `ascend-web-hunter`, that `CRAWL_WORKER_CONCURRENCY=8 docker compose config` shows `8`, and that every `${VAR` of
      `deploy-standalone/compose.yaml` appears in `deploy-standalone/.env.example` and in the README table.
- [ ] 1.4 Owner rule 98 of 2026-10-08, configuration reference: in the same commit as tasks 1.2 and 1.3, add one row per
      setting of design D16 to `apps/ascend-web-hunter/docs/configuration.md` (variable, default, purpose), each
      description ending with "Added by `enhance-web-search-crawl-at-scale`.", the object store rows in a section of
      their own because `add-file-download` adds to them later. Verify every D16 setting appears there once with the
      default of D16.

## 2. Job model and API

- [ ] 2.1 Create `src/crawl/models.py` with the D2 request model (Pydantic, every bound a `Field` constraint) and the job
      record. Every bound and every numeric default comes from the settings of design D16 (`CRAWL_MAX_SEEDS`,
      `CRAWL_MAX_PATTERNS`, `CRAWL_MAX_DEPTH`, `CRAWL_DEFAULT_DEPTH`, `CRAWL_MAX_PAGES`, `CRAWL_DEFAULT_PAGE_BUDGET`), and
      the submission answer's `poll_after_seconds` is `CRAWL_POLL_AFTER_SECONDS`. Verify with tests for each bound, for a
      request with no `max_depth` and no `page_budget` taking the two defaults, for a changed setting changing the
      bound, and for regular-expression syntax being treated as a literal glob.
- [ ] 2.2 Create `src/api/rest/crawl_endpoints.py` with the four D1 endpoints and mount it in `src/main.py`, and
      register every D9 code in the `ErrorRegistry` of `src/api/exception_handlers.py`, so the library's problem
      builder answers every error, with no helper of this change.
      Verify with tests for 202, 200, cancel, and 404 with `Content-Type: application/problem+json`, `code`
      `job_not_found`, `type` `https://ascend.ai/errors/job-not-found` and a `traceId` of 32 lower case hex characters
      when a span is current.
- [ ] 2.3 Add `crawl_submit`, `crawl_job_status`, `crawl_list_jobs` and `crawl_cancel_job` to `src/api/mcp/mcp_server.py`.
      Verify with tests that each returns the same fields as its REST twin, and that an unknown `job_id` answers a
      tool error whose text starts with `job_not_found`, raised as the registered exception and mapped by the library.
- [ ] 2.4 Implement the tenant scoping of D8 on both surfaces. Verify with tests that a job submitted for tenant
      `acme` is answered 404 `job_not_found` on status and cancel for tenant `globex` and is absent from its list,
      that a call naming no tenant and a call with `X-Ascend-Tenant: default` both run as the tenant `default` (no
      setting changes it), and that `X-Ascend-Tenant: ../acme` is refused with 400 `invalid_tenant` and creates no job.

## 3. SSRF rules

- [ ] 3.1 Check every seed at submission per D4. Verify with tests that `http://127.0.0.1/`, `http://10.0.0.1/`,
      `file:///etc/passwd`, `https://user:pass@example.com/` and a hostname resolving to a private address each get HTTP
      400 with `code` `unsafe_uri` and create no job.
- [ ] 3.2 Route discovered links, redirect hops, robots.txt and sitemap fetches through the guard and pinning. Verify a
      link to a private address is dropped and counted as `skipped_unsafe`.

## 4. Frontier, workers and politeness

- [ ] 4.1 Create `src/crawl/frontier.py` per D5. Verify with a fake Redis that two workers never claim the same URL and
      the per-domain cap holds.
- [ ] 4.2 Create `src/crawl/robots.py`. Verify a disallowed path is not fetched, `Crawl-delay` is honoured, sitemap URLs
      seed the frontier, and `respect_robots=false` is refused for a domain not in `CRAWL_ROBOTS_OPT_OUT_DOMAINS`.
- [ ] 4.3 Create `src/crawl/worker.py` reading each page through `WebReader` and honouring depth, patterns,
      `same_domain_only` and `page_budget`. Verify with a fixture site that a faked `WebReader` serves on the test side,
      with no allowed test host and no seam in the service (owner decision 90 of 2026-10-08).
- [ ] 4.4 Owner decision 87 of 2026-10-08, design D15. Tests first, against a Redis that runs the Lua scripts in the
      test (the test tool is chosen at implementation time and named in the CHANGELOG entry): the submission script
      writes the job record, the seed queues, the seen set and the `crawl_runnable` member together, the first claim
      moves the job to `running`, two workers of two simulated instances never claim the same URL, the domain cap, the
      crawl delay through `crawl_next_fetch` and the page budget hold for both instances together, the finish script
      appends to `crawl_pages`, adds only unseen links and moves the job to `succeeded` only when every queue and
      `crawl_claims` are empty, the instance that ends the job writes `pages.ndjson` once, and a `crawl_runnable`
      member whose job record is gone is removed, and a worker that finds nothing to claim waits
      `CRAWL_WORKER_IDLE_SECONDS` (design D16, under a fake clock) before it reads `crawl_runnable` again. Then write the
      scripts in `src/crawl/frontier.py` and start the worker tasks in the service lifespan. Verify: the tests fail
      before the code and pass after, inside the gate.
- [ ] 4.5 Design D15, cancel and an instance that stops. Tests first: a cancel through one instance moves the job to
      `cancelled`, removes it from `crawl_runnable` and deletes its frontier keys, a worker of a second instance that
      finishes a page of it writes nothing, and a cancelled job never turns back into `running` or `succeeded`. A claim
      whose lease deadline has passed is taken back by the next claim of any instance, with the URL at the front of its
      queue and the in-flight counter lowered, and a URL whose claim expires `CRAWL_CLAIM_MAX_EXPIRIES` times (default
      2, so a second expiry, design D16) is counted as failed, with a test that a setting of 3 allows a third claim. The
      claim lease is `CRAWL_CLAIM_LEASE_SECONDS` (default 120) and each instance starts `CRAWL_WORKER_CONCURRENCY`
      worker tasks (default 4), and a test shows one instance never reads more than that many pages at once (design
      D15, owner answer 94.1 of 2026-10-08).
      Verify: the tests fail before the code and pass after, inside the gate.
- [ ] 4.6 Make every change of the job record a script of task 4.4 or 4.5, so no code path writes the record outside
      them. Verify a test with two simulated instances that update the counts of one job at the same time and lose no
      update.

## 5. Results and recrawl

- [ ] 5.0 Create `src/storage/object_store.py` per D3: one S3 client configured by the `OBJECT_STORE_S3_*` settings,
      with multipart upload from a file, get and put of a small JSON object, head, delete, server-side copy inside a
      bucket, list by prefix with a continuation token, bucket creation and presigning a `GET`. Verify each operation with tests against a stubbed S3
      endpoint, and that no other module of the service creates an S3 client.
- [ ] 5.1 Create `src/crawl/result_store.py` per D3 on the client of 5.0. Verify with a stubbed S3 client that keys
      start with `tenant/<tenantId>/` followed by the prefix and the NDJSON lines match the pages.
- [ ] 5.2 Implement D6. Verify with a stubbed S3 client that a 304 and an equal hash both copy the earlier page file
      to the new job's key with a server-side copy (no upload of page bytes), mark the page `unchanged` with the new
      key in `pages.ndjson` and in the recrawl state, that the new job's page file is still readable after the
      earlier job's objects are deleted, that a missing earlier file makes the request go out without conditional
      headers and the page be written as a new file, and that a source that vanishes between the head and the copy
      leads to one unconditional fetch and a written file.
- [ ] 5.3 Implement the expiry of D12. Verify with a fake Redis that the frontier keys of a job are gone when it reaches
      `succeeded`, `failed` and `cancelled`, that every frontier key and every recrawl state hash carries an expiry of
      `CRAWL_JOB_RETENTION_SECONDS` set again on each write, and that a recrawl state hash of another tenant is never
      written by a job.

Task 5.4 moved to `add-audit-and-gdpr-compliance` (dependency fix of 2026-10-05).
Task 5.5 moved to `add-audit-and-gdpr-compliance` (dependency fix of 2026-10-05).

## 6. Proxy hook

- [ ] 6.1 Add `CRAWL_PROXY_URL` to `src/proxy/proxy_provider.py` per D7 and the MODIFIED requirement in
      `specs/web-search-antibot-evasion/spec.md`. Verify a crawl uses it and a single read does not.

## 7. Documentation and verification

- [ ] 7.1 Update `AGENTS.md`, `README.md` and `docs/configuration.md` (its prose around the rows of task 1.4) with the API, the settings, the SSRF rules and the
      honest scale statement. Write `docs/architecture/decisions/ADR-019-crawl-jobs.md` for the crawl model (design
      D14), including how several instances share one crawl (design D15), with its line in the ADR index. Verify every setting appears in all three files and the index links ADR-019.
- [ ] 7.2 Bump `version` in `pyproject.toml`, the version line in `AGENTS.md` and the version in
      `docs/architecture/arc42/02-constraints.md` from `0.0.14` (set by `add-web-session-import`) to `0.0.15` with one
      `## [0.0.15]` CHANGELOG entry at the top (design D14, owner decision of 2026-10-08, one named version per change,
      in build order). Verify the four agree and `## [0.0.15]` is the topmost version heading.
- [ ] 7.3 Run the gate, `python -m ruff check .` and `python -m mypy src tests`. Verify all pass with no suppression.
- [ ] 7.4 With the stack up, crawl a small public documentation site with `page_budget` 10 and confirm the job reaches
      `succeeded`, `pages.ndjson` exists in Floci under `tenant/default/` followed by the prefix, and a second run marks
      unchanged pages and holds a page file for each of them under its own job id. Verify by reading the objects back
      from Floci.

Task 7.5 moved to `add-audit-and-gdpr-compliance` (dependency fix of 2026-10-05).

## 8. End-to-end coverage

Owner request of 2026-10-04: every behaviour this change adds has an end-to-end test. The shared fake site, the problem
body check and the scenario rule are design D10 to D14 of `add-web-search-scraping-e2e`, built by its tasks 7.1 to 7.3, 7.5 and 7.6 and by `add-ascend-python-common` (build group 2, position 1), which carries its tasks 7.4, 7.7 and 7.8 (the Bruno variables, the problem body check and the allow list) since the dependency fix of 2026-10-05.
Task 7.4 stays as the first live check, and the spec below makes that check repeatable. The e2e checks of the tenant erase and export calls (owner answer 70.3 of 2026-10-04) moved with those calls to `add-audit-and-gdpr-compliance`, which adds them to the spec below in place (owner decision 91.3 of 2026-10-08 removed the refusal spec of task 8.2, so its task 10.10 extends the jobs spec of task 8.3).

- [ ] 8.1 Write the job record, the frontier keys and the recrawl state hash under the exact Redis key names of design
      D13 (`crawl_job:{tenantId}:{job_id}`, `crawl_queue:{tenantId}:{job_id}:{domain}`, `crawl_seen:{tenantId}:{job_id}`,
      `crawl_inflight:{tenantId}:{job_id}:{domain}`, `crawl_recrawl:{tenantId}:{scope}`, and the D15 keys
      `crawl_claims:{tenantId}:{job_id}`, `crawl_next_fetch:{tenantId}:{job_id}:{domain}`, `crawl_pages:{tenantId}:{job_id}`
      and `crawl_runnable`), built in one place in `src/crawl/`. Verify with a fake Redis that a job of tenant `acme`
      writes only keys that match `crawl_*:acme:*`, apart from its member `acme:<job_id>` in `crawl_runnable`, and that
      each key name equals its D13 pattern.
- [ ] 8.3 Write the new automated spec `apps/ascend-web-hunter/e2e/testing/<N>-crawl-jobs-test.md` and its template,
      against the fake site's small crawl site under its allowed name `e2e-fake-site` (design D12 of `add-web-search-scraping-e2e`, owner answer 67.3 of 2026-10-04): a
      sitemap, a robots.txt that disallows one path, pages down to depth 3, a page outside the include pattern and a
      page that links to a fake site path under the blocked name `e2e-fake-site-blocked`. Tenants `e2e-crawl-a` and `e2e-crawl-b`. Reset deletes both tenants'
      crawl data directly: every object under `tenant/e2e-crawl-a/` and `tenant/e2e-crawl-b/` in the crawl bucket (with
      `curl` on port 9070) and every Redis key that matches `crawl_*:e2e-crawl-a:*` or `crawl_*:e2e-crawl-b:*` (design
      D13), each command written in the spec, and empties the request log. Run and Expected:
      1. A submission for `e2e-crawl-a` with the include pattern, `max_depth` 2 and `page_budget` 5 answers HTTP 202
         with a `job_id` and state `waiting`, and polling with the `poll_after_seconds` hint reaches `succeeded`.
      2. The object store holds `tenant/e2e-crawl-a/crawl-results/<job_id>/pages.ndjson` in the crawl bucket (read with
         `curl` on port 9070), listing at most 5 pages, none deeper than depth 2, none outside the include pattern and
         not the disallowed path. The request log shows no request to the disallowed path or the private path, and the
         job counts hold at least one `skipped_unsafe`.
      3. A second identical submission reaches `succeeded`, its `pages.ndjson` marks the unchanged pages `unchanged`,
         a page file exists under the second job's own key for each of them, and the request log shows those requests
         carried `If-None-Match` or `If-Modified-Since`.
      4. A submission for `e2e-crawl-b` reaches `succeeded`, and the job list of `e2e-crawl-a` does not hold it.
      5. A submission for `e2e-crawl-a` cancelled with `DELETE /api/v1/crawl/jobs/{job_id}` while `running` reads
         `cancelled`.
      Owner decision 91.3 of 2026-10-08 removed the step that read one tenant's job as the other tenant and the step
      that scanned the frontier keys and the recrawl state expiry, because the tests of tasks 2.4 and 5.3 prove them.
      Concurrency: mutates only the two tenants' crawl data and the fake site request log, so it runs beside every spec
      that does not reset that log. Verify every assertion is an HTTP status, a response body, an object store listing
      or the fake site request log.
- [ ] 8.4 Add the Bruno requests of task 8.3 in the folder `docs/api/request/AscendAI/web-hunter/testing/crawl/`
      (`submit-fake-site.yml`, `job-status.yml`, `job-list.yml`, `job-cancel.yml`, the requests of the removed task 8.2
      are not written), each with its assertions in the request file, the tenant
      from an env variable. Verify each runs with `bru run "<file>" --env ascend-local` against a live stack.
- [ ] 8.5 Add the spec of task 8.3 to the spec lists, counts and run order of scenarios 1 to 6 and of the
      ascend-web-hunter service suite in `docs/E2E_RUN_SCENARIOS.md`, after spec 1, and to
      `e2e/README.md`'s capability table and `e2e/testing/README.md`'s ordered list. Verify every count still adds up.
- [ ] 8.6 Ask the owner which run scenario to use, then run the spec of task 8.3. Verify its run record under
      `e2e/testing/runs/` reads PASS, and attach it to this change.

Task 8.2 removed by owner decision 91.3 of 2026-10-08.
