Not started. Build group 4, position 16 of the owner build order of 2026-10-04. Start only after `add-connector-framework`
is archived, together with the earlier changes it really uses: `enhance-web-search-crawl-at-scale`,
`upgrade-spring-boot-4`, `add-keycloak-login`, `add-deployment-modules`, `add-shared-scheduler` and
`add-document-management-api`, which all land earlier. It waits for no company change: `add-tenant-isolation` registers
the `tenant/{tenantId}/` prefix implementation of `TenantPrefixResolver` later. Commands run from `apps/ascend-agent/`.

## 1. Connector

- [ ] 1.1 Add the `WEB_CRAWL` connector type and its configuration (seeds, patterns, depth, page budget) under
      `src/main/java/com/lukk/ascend/ai/agent/service/connector/web/`, validated with Bean Validation, with
      `@ConditionalOnModule("web-search")`, no credential and the framework's cron and time zone as its
      schedule (design D0), and the Flyway migration that admits `WEB_CRAWL` in the connector type check constraint.
      The bounds are settings of design D5 (owner rule 98), each in `application.yaml` as `key: ${ENV:default}`, in
      the `@ConfigurationProperties` record with the same default, and on the `ascend-agent` service of `compose.yaml`
      as `- ENV=${ENV:-default}`: `app.connector.web-crawl.max-seeds` (`APP_CONNECTOR_WEBCRAWL_MAXSEEDS`, 20),
      `app.connector.web-crawl.max-depth` (`APP_CONNECTOR_WEBCRAWL_MAXDEPTH`, 5),
      `app.connector.web-crawl.max-pages` (`APP_CONNECTOR_WEBCRAWL_MAXPAGES`, 10000) and
      `app.connector.web-crawl.max-patterns` (`APP_CONNECTOR_WEBCRAWL_MAXPATTERNS`, 50, for the include and for the
      exclude list each). Verify with a unit test for each bound, a test that a bound set through its environment
      variable replaces the default, a MockMvc test that a refused configuration answers 400 with `code`
      `validation` and the `errors` field, and a context test that the type is absent when `web-search` is not in
      `ASCEND_MODULES`.
- [ ] 1.2 Add a crawl client for the four `/api/v1/crawl/jobs` operations with timeouts. Its base address and timeouts
      are settings of design D5 (owner rule 98): `app.connector.web-crawl.base-url`
      (`APP_CONNECTOR_WEBCRAWL_BASEURL`, `${APP_CONNECTOR_WEBCRAWL_BASEURL:http://localhost:7021}` in
      `application.yaml` and the record, `${APP_CONNECTOR_WEBCRAWL_BASEURL:http://ascend-web-hunter:7021}` in
      `application-docker.yaml`, and `- APP_CONNECTOR_WEBCRAWL_BASEURL=${APP_CONNECTOR_WEBCRAWL_BASEURL:-http://ascend-web-hunter:7021}`
      on the `ascend-agent` service of `compose.yaml`), `app.connector.web-crawl.connect-timeout`
      (`APP_CONNECTOR_WEBCRAWL_CONNECTTIMEOUT`) and `app.connector.web-crawl.read-timeout`
      (`APP_CONNECTOR_WEBCRAWL_READTIMEOUT`), written the same way, with the defaults `5s` and `30s` (owner answer
      103.5 of 2026-10-09). Verify with a test against a local
      JDK `HttpServer` fake of the crawl API (as in `close-agent-test-gaps` D1)
      for submit, poll to `succeeded`, poll to `failed` and cancel on deadline, and a test that the client calls the
      configured base address.
- [ ] 1.3 Implement D1: copy new and changed pages into the prefix that the framework's `TenantPrefixResolver` answers
      for the connector's tenant (bound from the connector row with `TenantContext.runAs` of `add-keycloak-login`),
      supply `source_type` `connector:web-crawl` and the page URL as `origin_uri` for each page, and trigger ingestion.
      The bucket the pages are copied from is the setting `app.connector.web-crawl.result-bucket`
      (`APP_CONNECTOR_WEBCRAWL_RESULTBUCKET`, default `web-hunter-crawls`, the default of `CRAWL_RESULT_S3_BUCKET` of
      `enhance-web-search-crawl-at-scale` D3), written in `application.yaml`, the record and `compose.yaml` like the
      settings of task 1.1. Verify with an integration test (Testcontainers object storage and Postgres) that with the default resolver the
      landed keys follow today's key layout, that with a test `TenantPrefixResolver` bean answering `tenant/acme/` every
      landed key sits under `tenant/acme/` only, and that each page has a registry row with those values and the
      connector id.
- [ ] 1.4 Implement D3, reading the previous run's pages from the registry rows of the connector (answer 93 of
      2026-10-08). Verify a page missing on the second run is deleted with its registry row and recorded `DELETED`, a
      page listed `unchanged` is not copied again, and a page of another connector with the same URL is never deleted.

## 2. Documentation and verification

- [ ] 2.1 Add the web crawl connector section to `docs/CONNECTORS.md`, including that it needs the module `web-search` in
      `ASCEND_MODULES`. Verify it lists every configuration field.
- [ ] 2.2 Run `./gradlew test` and `./gradlew integrationTest` (`.\gradlew.bat` on Windows). Verify both pass.
- [ ] 2.3 In the same commit as tasks 1.1 to 1.3, add one row per setting of design D5 to
      `apps/ascend-agent/docs/CONFIGURATION.md` (the agent's configuration reference of owner rule 98): the property,
      its environment variable, its default (the docker profile default of the base address too), what it does, and a
      description that ends with "Added by `add-web-crawl-rag-connector`.". Verify every setting of design D5 has a row
      and every default in the rows equals the one in `application.yaml` and `compose.yaml`.

## 3. End-to-end coverage

Owner request of 2026-10-04: every planned change carries end-to-end tests. The shared fake site, the problem body
check and the scenario rule are design D10 to D14 of `add-web-search-scraping-e2e`, built by its tasks 7.1 to 7.3, 7.5 and 7.6, and by tasks 7.4, 7.7 and 7.8, which moved to `add-ascend-python-common` (its tasks 9.12, 9.10 and 9.11). The
crawl site below is the fake site's small crawl site under its allowed name `e2e-fake-site` (design D12 there, owner answer 67.3 of 2026-10-04), whose pages carry invented
canary sentences. Each new spec takes the next free number at implementation time.

- [ ] 3.1 Write the new automated agent spec `apps/ascend-agent/e2e/testing/<N>-web-crawl-connector-test.md` and its
      template, for tenant `default` of the spec's Keycloak ADMIN e2e user `e2e-admin` of `add-keycloak-login`, with `web-search`
      in `ASCEND_MODULES`. No chat model decides a verdict, and the embedding provider is the one the agent suite
      already uses. Reset deletes the spec's connector and its documents through the single-document deletion path,
      cancels any crawl job of the spec that is still running with `DELETE /api/v1/crawl/jobs/{job_id}`, and empties
      the fake site request log with `POST /__reset`. It does not call the tenant crawl data erase of
      `enhance-web-search-crawl-at-scale`, which moved to `add-audit-and-gdpr-compliance` (owner answer 70.3 of
      2026-10-04). Instead each run starts from a crawl scope no earlier run used: the connector of step 2 carries one
      extra exclude pattern `*/__e2e-never-<run id>*` that matches no page of the crawl site. The recrawl state of
      `enhance-web-search-crawl-at-scale` is kept per tenant and crawl scope, the SHA-256 of the sorted seeds and
      patterns (its D6), so a new pattern gives a new scope with no recrawl state, every page of the first run is
      fetched and landed as new, and the state an earlier run left expires by its own retention (its D12). Run and Expected:
      1. A create of a `WEB_CRAWL` connector with the seed `ftp://example.com/` answers HTTP 400 with the RFC 7807 problem
         detail, `code` `validation` and an `errors` field naming the seed, and one with a depth above the bound answers
         the same naming the depth. No connector is created.
      2. A create with the crawl site as seed, its include pattern, the run's extra exclude pattern, depth 2 and page
         budget 5 answers 201.
      3. `POST /api/v1/connectors/{id}/sync` starts a `MANUAL` run, and a second call while it runs answers HTTP 409
         `connector_run_in_progress`.
      4. Polling the connector's run history reaches a finished run. The object store then holds each landed page
         in `knowledge-base` under the key layout of the default `TenantPrefixResolver` (today's layout), Postgres holds one
         `documents` row per landed page with `source_type` `connector:web-crawl`, the page URL as `origin_uri` and the
         connector id, and Qdrant holds points for those documents carrying `source_type` and `connector_id`.
      5. After `POST /__state` on the fake site makes one landed page answer 404, a second `MANUAL` run finishes with a
         `DELETED` outcome for that page, and its object, its `documents` row and its Qdrant points are gone while the
         other pages stay.
      6. A `DELETE` of the connector answers 204. The scheduled start of a sync is not repeated here, because the
         shared scheduler and the connector framework prove it below this change (answer 91.3 of 2026-10-08).
      Concurrency: writes the tenant's knowledge base, its Qdrant points and its crawl data, and step 4 parses through
      the existing pipeline, so it runs alone in the quarantine lane with the other docling-bound agent specs. Verify
      every assertion is an HTTP status, a response body, an object store listing, a Postgres row or a Qdrant query,
      never a log line.
- [ ] 3.2 Write the new AI-run agent spec `apps/ascend-agent/e2e/testing/<N>-web-crawl-rag-ai-test.md` and its
      template, because a retrieval answer needs a real model. After one `MANUAL` run of a connector on the crawl site,
      a chat prompt that only a crawled page's canary sentence can answer returns that canary, and a prompt about a
      page outside the include pattern does not return that page's canary. Token use goes into the run record and the
      spec's row in `docs/E2E_COST.md`.
- [ ] 3.3 Add the Bruno requests of tasks 3.1 and 3.2 in the folder
      `docs/api/request/AscendAI/ascend-agent/testing/web-crawl-connector/` (`connector-create-bad-seed.yml`,
      `connector-create-bad-depth.yml`, `connector-create.yml`, `connector-sync.yml`, `connector-sync-busy.yml`,
      `connector-runs.yml`, `connector-delete.yml`, `prompt-crawled-canary.yml`,
      `prompt-excluded-canary.yml`), each with its assertions in the request file. Verify each runs with
      `bru run "<file>" --env ascend-local` against a live stack.
- [ ] 3.4 Add the deterministic spec to scenarios 1 to 4 and the ascend-agent service suite of
      `docs/E2E_RUN_SCENARIOS.md` in the quarantine lane, with `web-search` in the scenario preconditions, the AI spec to
      the same scenarios 1 to 4 and the same ascend-agent service suite, because both need the full stack with the agent,
      ascend-web-hunter and the fake site and only the AI spec needs a hosted chat key, which scenarios 1 to 4 already
      list, and to no scraping-only scenario 5 or 6, which run no agent (owner answer 75.4 of 2026-10-07), and both to
      `apps/ascend-agent/e2e/README.md`. Verify every
      count in the document still adds up.
- [ ] 3.5 Ask the owner which run scenario to use, then run both specs. Verify both run records under
      `apps/ascend-agent/e2e/testing/runs/` read PASS, and attach them to this change.
