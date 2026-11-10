## Context

Build group 4, position 16 of the owner build order of 2026-10-04. It needs `add-connector-framework` and the earlier
changes named in proposal.md, and no company change.


`add-connector-framework` (the connector framework, split out of `add-document-connectors` on 2026-10-04, decision numbers unchanged) defines a connector contract: land bytes in object storage under the prefix its `TenantPrefixResolver` gives the connector's tenant (the empty prefix by default, `tenant/{tenantId}/` once `add-tenant-isolation` registers its implementation later), register
each landed file in the document registry with the `source_type`, `origin_uri` and connector id the connector supplies,
then trigger the existing ingestion. It runs every connector sync on the shared scheduler of `add-shared-scheduler`
(one `connector-sync` execution per connector, from the connector's five-field cron and time zone), and the whole
framework is part of document search (`rag`), which belongs to the always-on core and is not a module (owner decision of 2026-10-03, `add-deployment-modules` D0). `enhance-web-search-crawl-at-scale` writes crawl
output to its own bucket and prefix with a `pages.ndjson` index that marks each page new, changed or `unchanged`.

## Decisions

### D0: The connector type `WEB_CRAWL` and its module

The type is `WEB_CRAWL`, admitted by this change's migration, which replaces the framework's named connector type check constraint (`add-connector-framework` D3) to admit `WEB_CRAWL` next to every value already admitted. It
needs no credential and takes its schedule from the connector's own cron and time zone, so the framework schedules it
like any connector. The connector, its crawl client and its configuration carry
`@ConditionalOnModule("web-search")`, because it reads crawl output of ascend-web-hunter. It writes into the knowledge
base, which is part of document search, part of the core, and needs no marking. A class of the module `web-search` may refer to core classes, because the import rule of `add-deployment-modules` D6 only forbids a core class that refers to a class of a switchable module. With `web-search` off the type does not exist, and a create of a `WEB_CRAWL` connector answers 400
with code `validation`. A refused configuration (a seed that is not an absolute `http` or `https` URL, a depth or page
budget out of bounds) answers the RFC 7807 problem detail of `upgrade-spring-boot-4` with code `validation` and the
`errors` field.

### D1: The connector copies, it does not parse

The connector reads `pages.ndjson`, copies the page files of new and changed pages into the prefix that the framework's
`TenantPrefixResolver` answers for the connector's tenant (taken from the connector row, bound with `TenantContext.runAs`
of `add-keycloak-login` for the run), and calls
the framework's ingestion trigger. For each page it supplies `source_type` `connector:web-crawl` and the page URL as
`origin_uri`, so the framework registers the page with them and its connector id, and every chunk carries
`source_type` and `connector_id`. Parsing, chunking and embedding stay in the existing pipeline.

### D2: Polling with a bounded wait

The connector polls the crawl job with the `poll_after_seconds` hint until a terminal state or the run's deadline from
the framework. A timed-out run cancels the crawl with `DELETE /api/v1/crawl/jobs/{job_id}` and records the run failed.

### D3: Deletion by comparison

The previous run's set of pages is the document registry of `add-document-management-api`: the `documents` rows that
carry this connector's id and `source_type` `connector:web-crawl`, one per landed page, keyed by `origin_uri` (answer 93
of 2026-10-08). There is no second index of this change. A page whose `origin_uri` has a registry row of this connector
and is absent from this run's `pages.ndjson` is deleted through the single-document deletion path, which also removes
its registry row, and is recorded as `DELETED`. A page that the crawl lists as `unchanged` keeps its row and is not
copied again.

### D4: Several agent instances

Answer 87 of 2026-10-08 (rule R1, CANON 26.1): a run of this connector is a `connector-sync` execution of the shared
scheduler, so it runs on exactly one agent instance per firing, and the framework's one-run-at-a-time rule per
connector (`add-connector-framework` D22) is kept in Postgres: the session advisory lock of that decision, taken in the
two-key form with the class key `AdvisoryLockClass.CONNECTOR_RUN` (value 1) of `add-connector-framework` and a key
derived from the connector id (owner answer 98.10 of 2026-10-08). This change takes no lock of its own and adds no
value to `AdvisoryLockClass`. The crawl job lives in ascend-web-hunter and is followed
by its id, the previous run's pages are read from the registry rows (D3), and the polling of D2 runs inside the one
execution. Nothing of this change keeps a lock, a queue, a cache or run state in memory only.

### D5: Settings of the connector

Owner rule 98 of 2026-10-08: every value with a default is a setting. The agent reads each one from its environment
variable, `application.yaml` writes `key: ${ENV:default}`, the `@ConfigurationProperties` record of the connector carries
the same default, and the `ascend-agent` service of `compose.yaml` writes `- ENV=${ENV:-default}`.

| Property | Environment variable | Default | What it does |
| :-- | :-- | :-- | :-- |
| `app.connector.web-crawl.base-url` | `APP_CONNECTOR_WEBCRAWL_BASEURL` | `http://localhost:7021` (`http://ascend-web-hunter:7021` in `application-docker.yaml` and in `compose.yaml`, like the MCP connection `ascend-web-hunter` today) | Address of the ascend-web-hunter crawl API |
| `app.connector.web-crawl.connect-timeout` | `APP_CONNECTOR_WEBCRAWL_CONNECTTIMEOUT` | `5s` (owner answer 103.5 of 2026-10-09) | Connect timeout of the crawl client |
| `app.connector.web-crawl.read-timeout` | `APP_CONNECTOR_WEBCRAWL_READTIMEOUT` | `30s` (owner answer 103.5 of 2026-10-09) | Read timeout of one crawl API call (the wait for a whole crawl is the framework's sync timeout, not this value) |
| `app.connector.web-crawl.result-bucket` | `APP_CONNECTOR_WEBCRAWL_RESULTBUCKET` | `web-hunter-crawls` | Bucket the crawl output is copied from, equal to `CRAWL_RESULT_S3_BUCKET` of ascend-web-hunter |
| `app.connector.web-crawl.max-seeds` | `APP_CONNECTOR_WEBCRAWL_MAXSEEDS` | 20 | Most seeds a connector accepts |
| `app.connector.web-crawl.max-depth` | `APP_CONNECTOR_WEBCRAWL_MAXDEPTH` | 5 | Highest depth a connector accepts |
| `app.connector.web-crawl.max-pages` | `APP_CONNECTOR_WEBCRAWL_MAXPAGES` | 10000 | Highest page budget a connector accepts |
| `app.connector.web-crawl.max-patterns` | `APP_CONNECTOR_WEBCRAWL_MAXPATTERNS` | 50 | Most include patterns, and most exclude patterns, a connector accepts |

The four bounds and the bucket take the defaults of the crawl API of `enhance-web-search-crawl-at-scale` (its D2 and
D3: `CRAWL_MAX_SEEDS`, `CRAWL_MAX_DEPTH`, `CRAWL_MAX_PAGES`, 50 patterns per list, `CRAWL_RESULT_S3_BUCKET`), so the
agent refuses at create time exactly what the crawl API would refuse at submit time. An operator who changes one of
them on ascend-web-hunter changes the matching agent setting too. The polling interval is the `poll_after_seconds`
hint of the crawl API and the run deadline is the framework's sync timeout, so this change plans no value for either.
Kept as constants, because they are not operational: the connector type `WEB_CRAWL`, the `source_type`
`connector:web-crawl`, the crawl API paths, the `pages.ndjson` name and its page states, and the run outcome `DELETED`.

## Risks

- A crawl that runs longer than the schedule interval: the framework's one-run-at-a-time rule per connector applies. A
  scheduled start during a run starts no second run and queues exactly one follow-up run (`add-connector-framework`
  D22).
- A tenant without the module grant `web-search`: its scheduled runs of a `WEB_CRAWL` connector are skipped with the
  reason `module_denied` by the framework (`add-connector-framework` D20).

## Owner decisions of 2026-10-07

Answer 75.1 (review of the group 3, 4 and 5 changes of 2026-10-07, fix of all 75 items approved): items 32, 34, 37 and 71 are fixed here. Item 32: document search (`rag`) is part of the core, not a module (D0 and the context above). Item 34, answer 75.4: the scenario lists of task 3.4 are written from this change's requirements. Item 37: task group 3 names the tasks of `add-web-search-scraping-e2e` that stayed there and the three that moved to `add-ascend-python-common`. Item 71: the change folder gets its `.openspec.yaml` with the date of its first commit, 2026-10-01.

## Owner decisions of 2026-10-08

Answer 76.2 (the owner strongly prefers Mockoon, and no group 3 to 5 change uses the earlier mock server any more), applied to this change's own tests and confirmed by owner answer 78.3 of 2026-10-08 (unit tests use the JDK `HttpServer`, integration and e2e fakes use Mockoon containers): the crawl client test of task 1.2 runs against a local JDK `com.sun.net.httpserver.HttpServer` fake, as `close-agent-test-gaps` D1 already uses, so no test dependency is added.

Answer 78.3: both kinds of fake stay for this change's own tests: unit tests use the JDK `HttpServer`, and integration and e2e fakes use Mockoon containers. This confirms the application recorded in the answer 76.2 entry above.

Answer 87 (rule R1): confirmed for every mechanism of this change. Each run is one `connector-sync` execution of the shared scheduler on one instance, the one-run-at-a-time rule of the framework is kept in Postgres, and the previous run's pages come from the registry rows. Nothing changed in the mechanisms, and the confirmation is written down in D4.

Answer 88 (rule R2): the company plug-in point `TenantPrefixResolver` stays, and so does the test that a test bean answering `tenant/acme/` replaces the default with no edit (task 1.3, the scenario "Output stays within the tenant prefix"). The review's suggestion to drop that tenant prefix test is not applied.

Answer 91.3: step 6 of the deterministic spec of task 3.1, which set the cron to every minute and waited up to 150 seconds for a scheduled run, is removed, because the scheduled start of a connector sync is proven by the shared scheduler and the connector framework below this change. The Bruno request `connector-update-cron.yml` goes with it (tasks 3.1 and 3.3). The manual runs, the landing, the registry rows, the Qdrant points and the deletion stay, and the AI-run spec stays.

Answer 93: the previous run's index of D3 had no defined store. It is now the registry rows of the connector (D3, task 1.4), so nothing new is stored.

Answer 85.1: no plan text of this change exports a key or a secret in a shell. The connector needs no credential, and the AI-run spec of task 3.2 takes its hosted chat key from the repository `.env` through the existing Bruno rows. Nothing changes here.

Answer 98 (owner rule 98, every value with a default is a setting): the settings of this change are listed in D5:
`app.connector.web-crawl.base-url` (`http://localhost:7021`, `http://ascend-web-hunter:7021` in the docker profile and
in compose), `app.connector.web-crawl.connect-timeout` and `app.connector.web-crawl.read-timeout` (defaults not
decided, listed for the owner), `app.connector.web-crawl.result-bucket` (`web-hunter-crawls`),
`app.connector.web-crawl.max-seeds` (20), `app.connector.web-crawl.max-depth` (5), `app.connector.web-crawl.max-pages`
(10000) and `app.connector.web-crawl.max-patterns` (50), each with its environment variable in Spring Boot's canonical
form and its compose line on the `ascend-agent` service (tasks 1.1 to 1.3). New task 2.3 adds their rows to
`apps/ascend-agent/docs/CONFIGURATION.md` in the same commit. The constants kept and why are in D5. No test or
measurement of this change uses LM Studio: the deterministic spec of task 3.1 judges no model output and embeds with
the provider the agent suite already uses (`openai`), and the AI-run spec of task 3.2 uses a hosted chat provider of the
existing Bruno rows.

Answer 98.10: the one-run-at-a-time rule of `add-connector-framework` D22 takes its advisory lock with the class key
`AdvisoryLockClass.CONNECTOR_RUN` (value 1) of that change. D4 names it, and this change adds no lock class.

## Owner decisions of 2026-10-09

Answer 103.5: the crawl client connect timeout `app.connector.web-crawl.connect-timeout`
(`APP_CONNECTOR_WEBCRAWL_CONNECTTIMEOUT`) has the default `5s` and the read timeout `app.connector.web-crawl.read-timeout`
(`APP_CONNECTOR_WEBCRAWL_READTIMEOUT`) the default `30s`, under the names this change already gave them in D5. Each is
written as `${ENV:default}` in `application.yaml`, carried by the properties record, passed as `${ENV:-default}` on the
`ascend-agent` service of `compose.yaml`, and has its row in `apps/ascend-agent/docs/CONFIGURATION.md` (D5, tasks 1.2 and
2.3). The open point of the Answer 98 record above is closed.
