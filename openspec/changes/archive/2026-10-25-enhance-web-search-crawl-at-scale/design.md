## Context

ascend-web-hunter reads one URL per request through its tier ladder, with an SSRF guard re-validated on every redirect
hop and connect-time address pinning (ADR-012). ascend-ocr already ships a job API with polling and results in Floci
(its ADR-008 and ADR-009). The crawl job API follows the same shape so callers learn one idiom.

## Decisions

### D1: Polling job API, no webhook

Endpoints under `/api/v1/crawl`:

| Method | Path | Answer |
| :-- | :-- | :-- |
| POST | `/api/v1/crawl/jobs` | 202 with `job_id`, `state` `waiting`, `poll_after_seconds` (the setting `CRAWL_POLL_AFTER_SECONDS`, D16) |
| GET | `/api/v1/crawl/jobs/{job_id}` | 200 with state, counts and result keys, 404 `job_not_found` |
| GET | `/api/v1/crawl/jobs` | 200 with the jobs of the caller's tenant still retained |
| DELETE | `/api/v1/crawl/jobs/{job_id}` | 200 with state `cancelled`, 404 `job_not_found` when unknown or of another tenant |

MCP tools: `crawl_submit`, `crawl_job_status`, `crawl_list_jobs`, `crawl_cancel_job`, same arguments and results. Once `add-mcp-tool-servers` (build group 4, its D4) lands, the agent sees them as `web_crawl_submit`, `web_crawl_job_status`, `web_crawl_list_jobs` and `web_crawl_cancel_job`, because its connection entry `ascend-web-hunter` then puts the prefix `web` before every tool name that does not already start with it. This change names the tools and does not wait for that change.
States: `waiting`, `running`, `succeeded`, `failed`, `cancelled`. A webhook was rejected for v1: it needs its own SSRF
guard on an address the caller chooses, signing and retries, and polling covers every current caller.

### D2: Request schema

```json
{
  "seeds": ["https://docs.example.com/"],
  "include_patterns": ["/guide/*"],
  "exclude_patterns": ["*/archive/*"],
  "max_depth": 2,
  "page_budget": 100,
  "same_domain_only": true,
  "respect_robots": true,
  "output_format": "text",
  "extraction_schema": null,
  "profile": null
}
```

- `seeds`: 1 to `CRAWL_MAX_SEEDS` (default 20) absolute `http` or `https` URLs.
- `include_patterns` and `exclude_patterns`: up to `CRAWL_MAX_PATTERNS` (default 50) each, glob patterns matched with
  `fnmatch` against the URL path. Globs, not regular expressions, so a caller cannot submit a pattern with catastrophic
  backtracking.
- `max_depth`: 0 to `CRAWL_MAX_DEPTH` (default 5), default `CRAWL_DEFAULT_DEPTH` (default 2).
- `page_budget`: 1 to `CRAWL_MAX_PAGES` (default 10000), default `CRAWL_DEFAULT_PAGE_BUDGET` (default 100).
- A default above its maximum (`CRAWL_DEFAULT_DEPTH` above `CRAWL_MAX_DEPTH`, `CRAWL_DEFAULT_PAGE_BUDGET` above
  `CRAWL_MAX_PAGES`) is refused at startup (D16).
- `same_domain_only`: default true, links outside the seeds' registrable domains are dropped.
- `respect_robots`: default true. False is allowed only for a seed domain listed in `CRAWL_ROBOTS_OPT_OUT_DOMAINS`
  (default empty), meaning a site the operator owns.
- `output_format`, `extraction_schema`, `profile`: the same meaning and rules as on a single read.

### D3: Results in Floci through one shared S3 client

The S3 client is created in `src/storage/object_store.py`, not inside `src/crawl/result_store.py`, so every
ascend-web-hunter feature that writes objects shares one client and one set of connection settings
(`add-file-download` D12 stores downloads on the same client). Its connection settings are `OBJECT_STORE_S3_ENDPOINT`
(default `http://localhost:9070`, Floci, right only for a native run, because inside a container `localhost` is the
container itself), `OBJECT_STORE_S3_ACCESS_KEY` and `OBJECT_STORE_S3_SECRET_KEY`. Inside the container the endpoint is
`http://host.docker.internal:9070`, set as `OBJECT_STORE_S3_ENDPOINT=${OBJECT_STORE_S3_ENDPOINT:-http://host.docker.internal:9070}` (D16) in
`compose.ascend-web-hunter.yaml`, whose `ascend-web-hunter` service already declares
`extra_hosts: "host.docker.internal:host-gateway"`, so the name also resolves on Linux Docker Engine (rule of
`fix-linux-docker-host-access`, build group 1, position 4, in `docs/DEPLOYMENT.md` "Reaching the host from a
container"). There is no
`CRAWL_RESULT_S3_ENDPOINT`, `CRAWL_RESULT_S3_ACCESS_KEY` or `CRAWL_RESULT_S3_SECRET_KEY`. The client supports multipart
upload from a file, get and put of a small JSON object, head, delete, server-side copy of an object inside a bucket
(D6), list by prefix with a continuation token, bucket creation, and presigning a `GET`. `src/crawl/result_store.py` uses that client and keeps the crawl key layout and its
own `CRAWL_RESULT_S3_BUCKET` (default `web-hunter-crawls`) and `CRAWL_RESULT_S3_PREFIX` (default `crawl-results/`).
Keys carry the tenant prefix of D8: `tenant/<tenantId>/<prefix><job_id>/pages.ndjson` (one line per page: URL, status,
content hash, fetched time, result key) and `tenant/<tenantId>/<prefix><job_id>/pages/<sha256 of URL>.md` (or `.json`
for `schema`). Job records and results expire after `CRAWL_JOB_RETENTION_SECONDS` (default 604800).

### D4: SSRF rules for crawl URLs

- Every seed is checked at submission with the same guard single reads use. A seed with a scheme other than `http` or
  `https`, with userinfo, or resolving to a private, loopback, link-local or reserved address is refused with HTTP 400
  `unsafe_uri` and the job is not created.
- Every discovered link, every redirect hop, every robots.txt fetch and every sitemap fetch goes through the same
  guard and connect-time pinning (ADR-012). A link that fails is dropped and counted as `skipped_unsafe`.
- Links are taken only from `href` attributes and sitemap `loc` entries, never from scripts.

### D5: Frontier and politeness

Redis keys per job, each carrying the job's tenant: a per-domain queue, a seen set of normalised URLs, and a
per-domain in-flight counter. Defaults:
`CRAWL_DOMAIN_CONCURRENCY` 2, `CRAWL_DEFAULT_DELAY_SECONDS` 1, robots.txt `Crawl-delay` used when larger. robots.txt
is parsed with `protego`. Sitemaps from robots.txt seed the frontier. Each worker claims a URL atomically, so two
workers never fetch the same URL. Politeness applies only inside crawl jobs. Single reads stay unthrottled. These keys
are the crawl progress of the job, and they expire as D12 says. Their names are in D13. The cap, the delay and the page
budget hold across every ascend-web-hunter instance together, through the claim of D15.

### D6: Incremental recrawl

Per tenant and normalised URL the store keeps the content hash, `ETag` and `Last-Modified` from the last job of that
tenant with the same seeds and patterns, so one tenant's recrawl never reads another tenant's state. It also keeps
the result key of the page file that holds that content. A recrawl sends `If-None-Match` and `If-Modified-Since`.

A page found unchanged keeps its job complete (owner answer 59 of 2026-10-03). On a 304 or an equal hash the worker
copies the earlier page file forward to the new job's key `tenant/<tenantId>/<prefix><job_id>/pages/<sha256 of URL>`
with a server-side copy of the object store (D3), so the bytes never pass through the service. It marks the page
`unchanged` in `pages.ndjson`, with the new job's result key, and writes that key into the recrawl state, so the next
recrawl copies from the newest job. Every job's results therefore hold every page the job reached until that job
expires (D12), and the expiry of an earlier job never leaves a later job with a page it cannot serve. The copy carries
the new job's expiry. Before a conditional request the worker checks with a head request that the earlier page file
still exists. When it is gone (its job expired or was erased), the request is sent without conditional headers and the
page is written as a new file. When the copy itself fails because the source vanished between the head and the copy,
the page is fetched once more without conditional headers and written. Any other copy failure fails that page like a
failed write.

The recrawl state is kept in Redis, one hash per tenant and crawl scope (the SHA-256 of the sorted seeds and patterns)
with one field per normalised URL, and it expires as D12 says. Its name is in D13.

### D7: Customer proxy, crawl only

`CRAWL_PROXY_URL` (default empty) routes crawl fetches through a proxy the customer supplies. Single reads keep using
the existing `PROXY_*` seam. The project never runs or resells a proxy.

### D8: Tenant scoping

Every job belongs to exactly one tenant, the rule `add-file-download` D8 uses in this service. `add-tenant-isolation`
(company, build group 5) later relies on this tenant key layout and registers its implementation later. This change
does not wait for it:

- MCP: the tenant comes from the `_meta` object of the tool call, key `ascend.ai/tenant_id`. The agent fills it from
  its tool context once `add-mcp-tool-servers` (build group 4, its D3) lands, and until then no call carries it. The
  tool schemas have no tenant argument.
- REST: the header `X-Ascend-Tenant`. A personal deployment's callers send `X-Ascend-Tenant: default` or no header.
- When neither names one, the tenant `default` is used, the tenant a personal deployment runs as, the same rule
  `add-file-download` D8 follows (owner answer 54.5 of 2026-10-03). There is no `CRAWL_DEFAULT_TENANT` setting. A value
  outside `[a-z0-9-]{1,64}` is refused with 400 `invalid_tenant` and no job is created.

The job record, the frontier keys, the recrawl state and every result object carry the tenant. Status, list and cancel
see only the jobs of the caller's tenant, and a job of another tenant is answered with 404 `job_not_found`, the same
answer as an unknown id.

### D9: Error bodies

Every REST error of the crawl API is an RFC 7807 problem body with media type `application/problem+json`, the shape
`add-ascend-python-common` defines for every Python service (owner answer 70.1 of 2026-10-04, the agent follows the
same shape later in `upgrade-spring-boot-4` D19) and `add-file-download` D13 uses in this service: `type`
`https://ascend.ai/errors/<code with - for _>`, `title`, `status`, `detail`, `instance` (the request path), the
extension field `code` and the extension field `traceId`. `traceId` is the 32 character lower case hex trace id of the
current OpenTelemetry span when one is valid, and the field is left out otherwise, never empty and never invented
(the rule of `add-ascend-python-common` D10). This change adds no problem helper. Each code below is a
`ProblemCode` entry in ascend-web-hunter's `ErrorRegistry` in `src/api/exception_handlers.py`, mapped from the
exception that raises it, and the body is built by `problem_response` of the `ascend-python-common` library (its D5),
which `add-ascend-python-common` (build group 2, position 1) puts in every Python service before this change. Codes of
this change:

| Code | Status | When |
| :--- | :--- | :--- |
| `unsafe_uri` | 400 | D4 seed refusal |
| `invalid_tenant` | 400 | D8 |
| `job_not_found` | 404 | Unknown id, an id of another tenant, or an expired job |

The codes `crawl_erase_busy` and `storage_unavailable` of the tenant erase and export calls moved with those calls to
`add-audit-and-gdpr-compliance` (D11).

A request body outside the D2 bounds keeps the validation answer every web-hunter endpoint gives (the library's 400
`validation` with `errors`). A 5xx detail never names an internal host, path or exception text. The MCP tools raise
the same registered exceptions, and the library's `McpRefusalMiddleware` turns each into a tool error whose text
starts with its code. The library logs and counts every refusal on both surfaces (`ascend_service_errors_total{code,
surface, operation}`, where `operation` is the route template or the tool name, so a crawl refusal is told apart from
a download refusal with the same code), so this change adds no refusal logging or counter of its own. Only the
internal 500 carries the library's fixed detail.

### D10: Module

The crawl API and its four MCP tools are part of ascend-web-hunter. They need no module of their own and no setting
that switches them: they exist whenever the service runs. `add-deployment-modules` (build group 3, position 6) lands
later and lists ascend-web-hunter as its module `web-search` (its D3), and from then on the agent offers the tools only
where that module is active. This change does not wait for it.

### D11: Tenant erase and export calls (moved)

Owner answer 57 of 2026-10-03 planned two internal calls of this service, `DELETE /api/v1/crawl/data` and
`GET /api/v1/crawl/data/export`, through which tenant erasure and tenant export reach one tenant's crawl data. Owner
answer 70.3 of 2026-10-04 moved them, with their codes, their setting `CRAWL_ERASE_DRAIN_SECONDS`, their tests and
their e2e checks, into `add-audit-and-gdpr-compliance` (company, build group 5). Company work adds them later on the
key layout of D3, D5 and D6, the tenant of D8 and the expiry of D12. This change does not build them and does not wait
for them. A crawl job holds its tenant and no user id (D8), so no crawl data belongs to one user.

### D12: Expiry of crawl progress and recrawl state

Nothing the crawl keeps lives without a bound, and every bound is `CRAWL_JOB_RETENTION_SECONDS` (default 604800,
7 days), so one setting governs the whole crawl store:

- Results and job records expire after it, as D3 says.
- Frontier keys (the per-domain queue, the seen set and the in-flight counter of D5, and the claim set, the next fetch
  times and the page lines of D15) are deleted when the job reaches
  `succeeded`, `failed` or `cancelled`. For a worker or a service that dies during a job, every frontier key also
  carries a Redis expiry of `CRAWL_JOB_RETENTION_SECONDS`, set when the key is created and set again on every write,
  so a key nobody writes any more is gone at most that long after its last write.
- Each recrawl state hash of D6 carries a Redis expiry of `CRAWL_JOB_RETENTION_SECONDS`, set again whenever a job of
  that tenant and scope writes it, so the state of a scope nobody crawls again is gone that long after its last job.

### D13: Redis key names

Every crawl key follows the existing key style of ascend-web-hunter (`session:{domain}:{profile}`,
`tier_memory:{registrable_domain}`, and `download_budget:{tenantId}:{yyyy-MM}` of `add-file-download`): a lower case
name with underscores, then the tenant, then the rest, joined by `:`. Every crawl key starts with `crawl_` and holds the
tenant in the second place, so `crawl_*:{tenantId}:*` finds every Redis key of one tenant's crawl data. The one
exception is the shared pickup set `crawl_runnable` of D15, which holds only references to the jobs that are `waiting`
or `running` and loses each one when its job ends or its job record is gone.

| Key | Redis type | Holds | Expiry |
| :-- | :-- | :-- | :-- |
| `crawl_job:{tenantId}:{job_id}` | string (JSON) | The job record: state, request, counts, result keys and times. Status, list and cancel read it. | `CRAWL_JOB_RETENTION_SECONDS`, as the results (D3) |
| `crawl_queue:{tenantId}:{job_id}:{domain}` | list | The per-domain queue of D5. | D12 |
| `crawl_seen:{tenantId}:{job_id}` | set | The seen set of normalised URLs of D5. | D12 |
| `crawl_inflight:{tenantId}:{job_id}:{domain}` | string (counter) | The per-domain in-flight counter of D5. | D12 |
| `crawl_recrawl:{tenantId}:{scope}` | hash | The recrawl state of D6, `{scope}` the SHA-256 of the sorted seeds and patterns, one field per normalised URL. | D12 |
| `crawl_claims:{tenantId}:{job_id}` | sorted set | The URLs a worker is reading now, scored by their lease deadline (D15). | D12 |
| `crawl_next_fetch:{tenantId}:{job_id}:{domain}` | string | The earliest time of the next fetch of the domain, which carries the crawl delay across instances (D15). | D12 |
| `crawl_pages:{tenantId}:{job_id}` | list | The `pages.ndjson` lines of the job while it runs, written to the object store when it ends (D15). | D12 |
| `crawl_runnable` | sorted set | `{tenantId}:{job_id}` of every job that is `waiting` or `running`, scored by its submission time (D15). | A member leaves when its job ends or its job record is gone |

`{domain}` is the registrable domain of `CookieManager.registrable_domain(url)`, the same form `tier_memory` uses. The
frontier keys of one job are `crawl_queue:{tenantId}:{job_id}:*`, `crawl_seen:{tenantId}:{job_id}`,
`crawl_inflight:{tenantId}:{job_id}:*`, `crawl_claims:{tenantId}:{job_id}`, `crawl_next_fetch:{tenantId}:{job_id}:*` and
`crawl_pages:{tenantId}:{job_id}`. The e2e reset of task 8.3 deletes `crawl_*:e2e-crawl-a:*` and
`crawl_*:e2e-crawl-b:*`.

### D14: ADR-019 and version 0.0.15

The crawl model is recorded in ADR-019. ADR-013 to ADR-018 are taken by the group 2 changes that land before this
one (ADR-018 by `remove-flaresolverr-tier`), and `add-file-download` takes ADR-020. The version moves from 0.0.14
(`add-web-session-import`, build group 2, position 8) to 0.0.15 with one CHANGELOG entry, by the owner decision of
2026-10-08 of one named version per change, in build order. The bump moves `pyproject.toml`, the `AGENTS.md` version
line and `docs/architecture/arc42/02-constraints.md` together.

### D15: Several instances

Several ascend-web-hunter containers run at once (owner decision 87 of 2026-10-08), and each one is a crawl worker.
No part of a crawl lives only inside one process. Redis holds every piece of shared state of D5, D6 and D13, and every
change of it is one Redis Lua script, so it is atomic across instances:

- Pickup. A submission writes the job record in state `waiting`, puts the seeds into their domain queues and the seen
  set, and adds `{tenantId}:{job_id}` to `crawl_runnable`, all in one script. Each instance starts crawl worker tasks in
  its lifespan and stops them on shutdown. A worker reads `crawl_runnable` oldest first and tries to claim a URL of one
  of those jobs. The first claim of a job moves it from `waiting` to `running`. A member whose job record no longer
  exists (expired or deleted) is removed by the worker that reads it. A worker that finds nothing it may claim waits
  `CRAWL_WORKER_IDLE_SECONDS` (D16) before it reads `crawl_runnable` again.
- Claim. The claim script refuses when the job is not `waiting` or `running`, when the job's page count has reached
  `page_budget`, when the domain's in-flight counter is at `CRAWL_DOMAIN_CONCURRENCY`, or when the domain's
  `crawl_next_fetch` time is still ahead. Otherwise it pops the URL, raises the in-flight counter and the page count,
  sets `crawl_next_fetch` to now plus the domain's delay (the larger of `CRAWL_DEFAULT_DELAY_SECONDS` and the
  robots.txt `Crawl-delay`), and records the URL in `crawl_claims` with its lease deadline. So the per-domain cap, the
  crawl delay and the page budget hold for all instances together, not once per instance.
- Finish. After the read, the finish script removes the claim, lowers the in-flight counter, appends the page's
  `pages.ndjson` line to `crawl_pages`, updates the counts in the job record, and adds the new links that are not yet in
  the seen set to their queues. When it finds every queue of the job empty and `crawl_claims` empty, it moves the job to
  `succeeded` and removes it from `crawl_runnable`. The instance that ran that script then writes `pages.ndjson` from
  `crawl_pages` to the object store and deletes the frontier keys (D12).
- Cancel. `DELETE` and `crawl_cancel_job` run the cancel script on whichever instance receives the call: the state
  becomes `cancelled` (only from `waiting` or `running`), the job leaves `crawl_runnable`, and its frontier keys are
  deleted. A worker on another instance that still reads a page of that job finds the job cancelled in its finish
  script, which then writes nothing. So a cancel reaches every instance through the shared job record, with no
  message between instances.
- An instance that stops. A claim whose lease deadline has passed is taken back by the next claim script of any
  instance: the URL goes back to the front of its domain queue and the in-flight counter is lowered. A URL whose claim
  expires `CRAWL_CLAIM_MAX_EXPIRIES` times (default 2, so a second expiry) is counted as failed, so a page that stops
  every instance that reads it cannot hold the job open. The claim lease lasts `CRAWL_CLAIM_LEASE_SECONDS` (default 120), and each instance starts
  `CRAWL_WORKER_CONCURRENCY` crawl worker tasks (default 4), so one container reads at most 4 pages at once across all
  jobs (owner answer 94.1 of 2026-10-08). The per-domain cap and the crawl delay still hold for all instances together.
- robots.txt is fetched and parsed once per instance and job, and kept in that instance's memory until the job ends.
  That is correct per instance, because every instance reads the same file. Sitemap URLs are added through the seen
  set, so a sitemap entry that two instances find is queued once.
- The job record stays one string of JSON (D13). It is changed only inside these scripts, so two instances never lose
  each other's update, and a cancelled job never turns back into `running` or `succeeded`.

Alternative rejected (review item A3 of 2026-10-08): one asyncio crawler per job inside one process with the frontier
in memory. It would lose several instances working on one crawl and a crawl that survives the instance that started
it, which the owner keeps (owner decision 87 of 2026-10-08).

### D16: Every crawl value is a setting (owner rule 98 of 2026-10-08)

Every value of this change that has a default is a field of the web-hunter `Settings` in `src/config/config.py`, read
from the environment variable of the same name, with the code default equal to the default below. Both compose files
pass each one as `- VAR=${VAR:-default}` on the `ascend-web-hunter` service (`compose.ascend-web-hunter.yaml` and
`apps/ascend-web-hunter/deploy-standalone/compose.yaml`). The sync rule of `apps/ascend-web-hunter/AGENTS.md` applies to
each: a commented line `# VAR=default` with a one line comment in the root `.env.example` and in
`deploy-standalone/.env.example`, and a row in the configuration table of `deploy-standalone/README.md`, in the same
commit. Each gets a row in `apps/ascend-web-hunter/docs/configuration.md` whose description ends with "Added by
`enhance-web-search-crawl-at-scale`.", in the same commit as the setting.

| Setting | Default | Meaning |
| :--- | :--- | :--- |
| `CRAWL_MAX_SEEDS` | `20` | Most seeds in one request (D2) |
| `CRAWL_MAX_PATTERNS` | `50` | Most include patterns and most exclude patterns in one request (D2) |
| `CRAWL_MAX_DEPTH` | `5` | Largest `max_depth` (D2) |
| `CRAWL_DEFAULT_DEPTH` | `2` | `max_depth` when the request has none (D2), refused at startup above `CRAWL_MAX_DEPTH` |
| `CRAWL_MAX_PAGES` | `10000` | Largest `page_budget` (D2) |
| `CRAWL_DEFAULT_PAGE_BUDGET` | `100` | `page_budget` when the request has none (D2), refused at startup above `CRAWL_MAX_PAGES` |
| `CRAWL_ROBOTS_OPT_OUT_DOMAINS` | empty | Seed domains for which `respect_robots` false is accepted (D2) |
| `CRAWL_RESULT_S3_BUCKET` | `web-hunter-crawls` | Bucket of the crawl results (D3) |
| `CRAWL_RESULT_S3_PREFIX` | `crawl-results/` | Key prefix of the crawl results after the tenant prefix (D3) |
| `CRAWL_JOB_RETENTION_SECONDS` | `604800` | Lifetime of job records, results, frontier keys and recrawl state (D3, D12) |
| `CRAWL_DOMAIN_CONCURRENCY` | `2` | Pages of one domain read at once, all instances together (D5, D15) |
| `CRAWL_DEFAULT_DELAY_SECONDS` | `1` | Least time between two fetches of one domain (D5, D15) |
| `CRAWL_PROXY_URL` | empty | Customer proxy for crawl fetches only (D7) |
| `CRAWL_CLAIM_LEASE_SECONDS` | `120` | Lifetime of a page claim (D15, owner answer 94.1) |
| `CRAWL_CLAIM_MAX_EXPIRIES` | `2` | Claim expiries after which a URL counts as failed (D15) |
| `CRAWL_WORKER_CONCURRENCY` | `4` | Crawl worker tasks each instance starts (D15, owner answer 94.1) |
| `CRAWL_WORKER_IDLE_SECONDS` | `1` | Wait of a worker that found nothing to claim (D15) |
| `CRAWL_POLL_AFTER_SECONDS` | `5` | The `poll_after_seconds` hint of a submission (D1) |
| `OBJECT_STORE_S3_ENDPOINT` | `http://localhost:9070` | Address of the S3-compatible store (D3) |
| `OBJECT_STORE_S3_ACCESS_KEY` | none, a secret | Access key of the store (D3) |
| `OBJECT_STORE_S3_SECRET_KEY` | none, a secret | Secret key of the store (D3) |

Owner answer 100.1 of 2026-10-09 set the two defaults that were open: `CRAWL_WORKER_IDLE_SECONDS` 1 and
`CRAWL_POLL_AFTER_SECONDS` 5. The two keys are secrets: no default in code, the compose
line `${VAR}` with no default, the value from the repository `.env` only (owner answer 85.1). `OBJECT_STORE_S3_ENDPOINT`
serves a native run with its code default, and inside a container `localhost` is the container itself, so both compose
files write `OBJECT_STORE_S3_ENDPOINT=${OBJECT_STORE_S3_ENDPOINT:-http://host.docker.internal:9070}`, the same form owner
answer 94.3 gave `REDIS_URL` (`${REDIS_URL:-redis://host.docker.internal:6379/0}`). Any further timeout, interval or
limit the implementation finds it needs, for example a timeout of the robots.txt or sitemap fetch, becomes a `CRAWL_*`
setting the same way, with its default asked from the owner first and never guessed.

Values that stay constants, because they are not operational: the request field defaults `same_domain_only` true and
`respect_robots` true and the format name `output_format` `text` (API contract of D2, kept equal to a single read), the
tenant format `[a-z0-9-]{1,64}` and the tenant `default` (identifier format and the fixed tenant of owner answer 54.5),
the Redis key names of D13, the object key layout of D3, the error codes of D9, the API paths of D1 and the tool names.

## Risks

- Scale claims: the honest ceiling is the hundreds-of-thousands-of-pages class per job across several workers, and
  the docs say so.
- A crawl getting the deployment's address blocked: politeness is on by default and the per-domain cap is low.

## Owner decisions of 2026-10-08

The owner approved on 2026-10-08 the fixes of the review of the group 1 and group 2 changes of 2026-10-07.

- Item 10: the crawl model is ADR-019, not ADR-018, because `remove-flaresolverr-tier` lands earlier and takes ADR-018
  (D14).
- Item 12: the Redis key names are fixed now (D13) instead of at implementation time, and task 8.1 checks that the
  code writes them.
- Item 22: the version is one patch step after the change before this one (D14).
- Owner decision of 2026-10-08, "one named version per change, in build order": this change ships as
  ascend-web-hunter 0.0.15, one patch step after 0.0.14 of `add-web-session-import` (D14, task 7.2).
- Item 19: the gate of task 7.3 runs mypy over `src tests`, the same gate as `add-ascend-python-common` D14.

Answer 87 (rule R1): the Redis frontier and its workers stay, and review item A3 (one in-process crawler per job) is not applied. D15 makes every part of a crawl safe with several ascend-web-hunter instances: job pickup through the shared set `crawl_runnable`, URL claims with a lease that another instance takes back when an instance stops, the per-domain cap, the crawl delay and the page budget counted across all instances, cancel through the shared job record, and every change of shared state as one Redis Lua script. robots.txt stays a per-instance cache, which is correct because every instance reads the same file. D12 and D13 list the four new keys, tasks 4.4 to 4.6 build them and task 8.1 checks their names.

Answer 85.1: no task of this change exports a key or a secret in a shell. The object store keys come from the repository `.env` through the compose files (task 1.3).

Answer 89.14: the spec scenario for an error body without trace export now names the standard switch, no trace endpoint set, instead of the custom `OTEL_ENABLED` that `add-ascend-python-common` drops.

Answer 91.3: the refusal spec `<N>-crawl-refusals` (task 8.2) is removed, because the unit tests of tasks 2.2 to 2.4, 3.1 and 4.2 prove every refusal it repeated. Its MCP tool list check is proven by the tests of task 2.3. In the jobs spec (task 8.3) the step that reads one tenant's job as the other tenant and the step that scans the frontier keys are removed, because tasks 2.4 and 5.3 prove them. The submission for `e2e-crawl-b` stays, because `add-audit-and-gdpr-compliance` task 10.11 checks that its erase leaves that tenant untouched, and that change gets through `inbox93` the note that its task 10.10 now extends the jobs spec.

Answer 93: the review items C19 are judged by rule R3 and none is applied. The recrawl copy forward stays, because it is the completeness rule of owner answer 59: a plain fresh fetch per job would let a job lose pages when the earlier job expires. `CRAWL_PROXY_URL` stays, because folding it into `PROXY_*` would lose routing crawl jobs through a customer proxy while single reads go direct (the spec scenario "Crawl proxy used only by crawls"). `CRAWL_ROBOTS_OPT_OUT_DOMAINS` stays, because removing it would lose crawling a site the operator owns with `respect_robots` false.

Answer 94.1: a page claim lease is 120 seconds and each ascend-web-hunter container reads 4 pages at once. The two settings follow the module's `CRAWL_*` naming: `CRAWL_CLAIM_LEASE_SECONDS` (default 120) and `CRAWL_WORKER_CONCURRENCY` (default 4, the number of crawl worker tasks each container starts). D15, tasks 1.2 and 4.5 and the spec requirement of the frontier carry them, with a scenario that one container never reads more pages at once than its worker count.

Answer 94.5: the new change `scale-ocr-and-audio-across-containers` takes build group 3, position 5, directly after `harden-cloud-deployment`, so `add-deployment-modules` is now position 6, `add-shared-scheduler` 7, `add-document-management-api` 8 and `add-chat-streaming-and-conversations` 9 (`openspec/BUILD_ORDER.md`). Every position of those changes that this change names was moved by one. Nothing else in this change changes.

Answer 98: every value of this change that has a default is a setting (new D16): a `Settings` field in the module's `CRAWL_*` and `OBJECT_STORE_S3_*` naming with the same code default, the compose line `${VAR:-default}` on `ascend-web-hunter` in `compose.ascend-web-hunter.yaml` and in `deploy-standalone/compose.yaml`, the sync rule (root `.env.example`, `deploy-standalone/.env.example`, bundle README table) and a row in `apps/ascend-web-hunter/docs/configuration.md` ending "Added by `enhance-web-search-crawl-at-scale`.", in the same commit as the setting. Made external (name, default): `CRAWL_MAX_SEEDS` 20, `CRAWL_MAX_PATTERNS` 50 (new, was the fixed "up to 50"), `CRAWL_MAX_DEPTH` 5, `CRAWL_DEFAULT_DEPTH` 2 (new, was the fixed request default), `CRAWL_MAX_PAGES` 10000, `CRAWL_DEFAULT_PAGE_BUDGET` 100 (new, was the fixed request default), `CRAWL_ROBOTS_OPT_OUT_DOMAINS` empty, `CRAWL_RESULT_S3_BUCKET` `web-hunter-crawls`, `CRAWL_RESULT_S3_PREFIX` `crawl-results/`, `CRAWL_JOB_RETENTION_SECONDS` 604800, `CRAWL_DOMAIN_CONCURRENCY` 2, `CRAWL_DEFAULT_DELAY_SECONDS` 1, `CRAWL_PROXY_URL` empty, `CRAWL_CLAIM_LEASE_SECONDS` 120, `CRAWL_CLAIM_MAX_EXPIRIES` 2 (new, was the fixed "a second time"), `CRAWL_WORKER_CONCURRENCY` 4, `OBJECT_STORE_S3_ENDPOINT` `http://localhost:9070` in code and `http://host.docker.internal:9070` as the compose default, the form answer 94.3 gave `REDIS_URL`. Two new settings have no decided default and are left for the owner: `CRAWL_WORKER_IDLE_SECONDS` (the wait of a worker that found nothing to claim, which the plan used without a value) and `CRAWL_POLL_AFTER_SECONDS` (the `poll_after_seconds` hint, which the plan returned without a value). The two object store keys are secrets with no default. Kept as constants, not operational: the request defaults `same_domain_only` and `respect_robots` true and `output_format` `text` (API contract), the tenant format and the tenant `default`, the Redis key names, the object key layout, the error codes, the API paths and the tool names. Tasks 1.2, 1.3 and 7.1 carry it, new task 1.4 writes the configuration rows, and the `web-search-crawl-jobs` requirements "Crawl request bounds" and "Redis frontier with per-domain politeness" name the new settings. No test or measurement of this change uses LM Studio, and no text of it names the old `e2e` Spring profile or the overlay mount.

## Owner decisions of 2026-10-09

Answer 100.1: the two settings that had no decided default get one: `CRAWL_WORKER_IDLE_SECONDS` 1 (the wait of a worker that found nothing to claim) and `CRAWL_POLL_AFTER_SECONDS` 5 (the `poll_after_seconds` hint of a submission). D16 and task 1.2 carry the values, and tasks 1.3 and 1.4 write them into both compose files as `${VAR:-default}` and into the configuration reference like every other D16 row.
