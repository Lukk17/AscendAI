# Crawl jobs: fake-site crawl e2e test

## What this verifies

Crawl jobs against the fake site's small crawl site under its allowed name `e2e-fake-site`
(design D12 of `add-web-search-scraping-e2e`, owner answer 67.3 of 2026-10-04): a robots.txt that
disallows `/crawl/disallowed`, pages down to depth 3 (`/crawl/a/b/c`), a page outside the include
pattern (`/crawl/outside`) and a page (`/crawl/blocked-link`) that links to a fake site path under the
blocked name `e2e-fake-site-blocked`. Tenants `e2e-crawl-a` and `e2e-crawl-b`.

Sitemap discovery: the fake site's robots.txt names its sitemap by its full address,
`http://e2e-fake-site:7031/sitemap.xml`, and the sitemap lists the page `/crawl/a-sitemap-only`, which
no link on the site points to. The crawl can reach that page only through the sitemap. The crawl reads
the sitemap once per job and site, when the instance takes its first page of that site that is not
disallowed, so in a `respect_robots` true job whose first page is disallowed the sitemap is read at the
first allowed page. With the one ascend-web-hunter instance of this stack and an allowed seed, that
page is the seed at depth 0. Every sitemap address then
enters the queue at depth 1, whatever its depth by links would be. The same rules as for a discovered
link apply to it before it is queued: the depth limit (`max_depth` 0 keeps no sitemap address), the
same-domain rule, the include and exclude patterns, and the SSRF guard (a refused address counts as
`skipped_unsafe`). robots.txt `Disallow` is checked when the page is taken from the queue, as for every
page. An address already queued or read is not queued again. The page name starts with `/crawl/a` so it
matches the include pattern `/crawl/[ab]*`. The sitemap lists no page deeper than depth 1 by links.
Such a page would enter at depth 1, and the page it links to would then fall inside the depth limit and
be read, which breaks the depth check of Call 2.

Two crawl rules this spec depends on. A crawl job never uses the service's read cache: every page of a job
is fetched from the site, even a page a `POST /api/v2/web/read` put in that cache moments before, as the
Prerequisites read of `/crawl/` does. And in a job that sends `respect_robots` true, robots.txt decides what
the job may read from an origin: an answer of 200 applies its rules, any other 4xx answer except 429 means allow
all, and an answer of 5xx or 429, or a network error, means the job reads nothing from that origin. The fake site
answers `/robots.txt` with 200, so that crawl follows its `Disallow` line. A job that leaves `respect_robots` out
ignores those rules and still reads robots.txt once per site for its sitemap addresses, so every submission below
sends it as true to get the `Disallow` line, apart from Call 8, which shows a default crawl reading the page
robots.txt forbids.

1. A submission for `e2e-crawl-a` with the include pattern `/crawl/[ab]*`, `max_depth` 2 and
   `page_budget` 5 answers HTTP 202 with a `job_id` and state `waiting`, and polling with the
   `poll_after_seconds` hint reaches `succeeded`.
2. The object store holds `tenant/e2e-crawl-a/crawl-results/<job_id>/pages.ndjson` in the crawl
   bucket (read with `curl` from the host at the address in `OBJECT_STORE_S3_PUBLIC_ENDPOINT`,
   default `http://localhost:9070`, `http://localhost:4566` on this host), listing at most 5 pages,
   none deeper than depth 2, none outside the include pattern and not the disallowed path. The
   request log shows no request to the disallowed path or to `/article`, the path the blocked-name
   link points to, and the job counts hold at least one `skipped_unsafe`.
   `pages.ndjson` lists `/crawl/a-sitemap-only` as `fetched`, its page file holds the canary sentence
   `The KESTREL-BUOY register lists 19 marker buoys moored off the Mirell south point.`, and the
   request log shows a request to `/sitemap.xml`.
3. A second identical submission reaches `succeeded`, its `pages.ndjson` marks the unchanged pages
   `unchanged`, a page file exists under the second job's own key for each of them, and the request
   log shows those requests carried `If-None-Match` or `If-Modified-Since`.
4. A submission for `e2e-crawl-b` reaches `succeeded`.
5. A submission for `e2e-crawl-a` cancelled with `DELETE /api/v1/crawl/jobs/{job_id}` while
   `running` reads `cancelled`.
6. The job list of `e2e-crawl-a` holds its three jobs and not the `e2e-crawl-b` job, and the job list
   of `e2e-crawl-b` holds only its own job.
7. A submission that leaves `respect_robots` out, seeded at `/crawl/disallowed`, reaches `succeeded` and
   lists that page as `fetched`.

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

Check the fake site is reachable from the host.

```bash
curl -fsS http://127.0.0.1:7031/__requests
```

Expect a request list.

Check the allow list names the allowed fake site name but not the blocked one, so the seed is
fetchable and the blocked-name link is refused. The service was started with
`WEB_HUNTER_ALLOWED_PRIVATE_HOSTS` holding `e2e-fake-site` and no blocked name:

```bash
curl -fsS http://127.0.0.1:7021/api/v2/web/read -H "Content-Type: application/json" -d '{"url":"http://e2e-fake-site:7031/crawl/"}'
```

Expect HTTP 200. A read of the blocked name is refused:

```bash
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:7021/api/v2/web/read -H "Content-Type: application/json" -d '{"url":"http://e2e-fake-site-blocked:7031/article"}'
```

Expect HTTP 400.

## Reset state

Empty the fake site request log.

```bash
curl -fsS -X POST http://127.0.0.1:7031/__reset
```

Expect `{"reset":true}`.

Every object store command in this spec runs on the host, so it takes the host's view of the store,
`OBJECT_STORE_S3_PUBLIC_ENDPOINT`, and falls back to `http://localhost:9070` when it is unset. The
container's own view, `OBJECT_STORE_S3_ENDPOINT` (for example `http://host.docker.internal:4566`), uses a
name the host may not resolve, so never use it here. When the root `.env` sets
`OBJECT_STORE_S3_PUBLIC_ENDPOINT` (on this host `http://localhost:4566`), set the same value in the
runner's shell before the first command. Floci speaks plain REST, so `curl` needs no credentials.

Delete both tenants' crawl objects from the crawl bucket. Bash:

```bash
for tenant in e2e-crawl-a e2e-crawl-b; do
  curl -fsS "${OBJECT_STORE_S3_PUBLIC_ENDPOINT:-http://localhost:9070}/web-hunter-crawls?list-type=2&prefix=tenant/${tenant}/" \
    | grep -o "<Key>[^<]*" | cut -d'>' -f2 \
    | while read -r key; do curl -fsS -X DELETE "${OBJECT_STORE_S3_PUBLIC_ENDPOINT:-http://localhost:9070}/web-hunter-crawls/${key}"; done
done
```

PowerShell 7:

```powershell
foreach ($tenant in "e2e-crawl-a", "e2e-crawl-b") { $s3 = $env:OBJECT_STORE_S3_PUBLIC_ENDPOINT ?? "http://localhost:9070"; [regex]::Matches((curl -fsS "$s3/web-hunter-crawls?list-type=2&prefix=tenant/$tenant/" | Out-String), "<Key>([^<]*)</Key>") | ForEach-Object { curl -fsS -X DELETE "$s3/web-hunter-crawls/$($_.Groups[1].Value)" } }
```

Expect no output. A following listing for each tenant holds no key. Bash:

```bash
curl -fsS "${OBJECT_STORE_S3_PUBLIC_ENDPOINT:-http://localhost:9070}/web-hunter-crawls?list-type=2&prefix=tenant/e2e-crawl-a/"
```

```bash
curl -fsS "${OBJECT_STORE_S3_PUBLIC_ENDPOINT:-http://localhost:9070}/web-hunter-crawls?list-type=2&prefix=tenant/e2e-crawl-b/"
```

PowerShell 7:

```powershell
curl -fsS "$($env:OBJECT_STORE_S3_PUBLIC_ENDPOINT ?? 'http://localhost:9070')/web-hunter-crawls?list-type=2&prefix=tenant/e2e-crawl-a/"
```

```powershell
curl -fsS "$($env:OBJECT_STORE_S3_PUBLIC_ENDPOINT ?? 'http://localhost:9070')/web-hunter-crawls?list-type=2&prefix=tenant/e2e-crawl-b/"
```

Expect no `<Key>` element in either answer.

Delete both tenants' crawl keys from Redis (design D13):

```bash
docker exec redis redis-cli --scan --pattern "crawl_*:e2e-crawl-a:*" | xargs -r docker exec -i redis redis-cli DEL
```

```bash
docker exec redis redis-cli --scan --pattern "crawl_*:e2e-crawl-b:*" | xargs -r docker exec -i redis redis-cli DEL
```

Each `DEL` prints the number of keys it removed, for example `9`, and prints nothing when the scan found
no key (`xargs -r` then runs no `DEL`). The crawl keys carry each job's id, so they cannot be named in
advance. A following scan returns nothing:

```bash
docker exec redis redis-cli --scan --pattern "crawl_*:e2e-crawl-a:*"
```

```bash
docker exec redis redis-cli --scan --pattern "crawl_*:e2e-crawl-b:*"
```

Expect no output. The container `ascend-scrapper-redis` exists only when the scraping file runs alone
with `COMPOSE_PROFILES=redis` in the root `.env`. In that case every `docker exec redis` command above
targets `ascend-scrapper-redis` instead. On the main stack and on a host with its own Redis it does not
exist.

## Run

Move into the Bruno collection root first, from the repository root.

```bash
cd docs/api/request/AscendAI
```

Call 1 - submit the crawl for `e2e-crawl-a`.

```bash
bru run "web-hunter/testing/crawl/submit-fake-site.yml" --env ascend-local --env-var tenant=e2e-crawl-a
```

Record the `job_id` from the answer. Poll the status until it reads `succeeded`, waiting
`poll_after_seconds` between polls:

```bash
job_id="<job_id from call 1>"
hint=5
while true; do
  state=$(curl -fsS "http://127.0.0.1:7021/api/v1/crawl/jobs/${job_id}" -H "X-Ascend-Tenant: e2e-crawl-a" | python3 -c "import json,sys; print(json.load(sys.stdin)['state'])")
  echo "state: ${state}"
  if [ "${state}" = "succeeded" ]; then break; fi
  sleep "${hint}"
done
```

Call 2 - read the result index back from the object store. Bash:

```bash
curl -fsS "${OBJECT_STORE_S3_PUBLIC_ENDPOINT:-http://localhost:9070}/web-hunter-crawls/tenant/e2e-crawl-a/crawl-results/${job_id}/pages.ndjson"
```

PowerShell 7, with `$job_id` holding the same id:

```powershell
curl -fsS "$($env:OBJECT_STORE_S3_PUBLIC_ENDPOINT ?? 'http://localhost:9070')/web-hunter-crawls/tenant/e2e-crawl-a/crawl-results/$job_id/pages.ndjson"
```

Call 2a - read the page file of the sitemap-only page. The `key` field of its `pages.ndjson` line names
the file. Bash:

```bash
sitemap_key=$(curl -fsS "${OBJECT_STORE_S3_PUBLIC_ENDPOINT:-http://localhost:9070}/web-hunter-crawls/tenant/e2e-crawl-a/crawl-results/${job_id}/pages.ndjson" | python3 -c "import json,sys; print(next(json.loads(l)['key'] for l in sys.stdin if l.strip() and json.loads(l)['url'] == 'http://e2e-fake-site:7031/crawl/a-sitemap-only'))")
```

```bash
curl -fsS "${OBJECT_STORE_S3_PUBLIC_ENDPOINT:-http://localhost:9070}/web-hunter-crawls/${sitemap_key}"
```

PowerShell 7, with `$job_id` holding the same id:

```powershell
$s3 = $env:OBJECT_STORE_S3_PUBLIC_ENDPOINT ?? "http://localhost:9070"; $sitemap_key = (curl -fsS "$s3/web-hunter-crawls/tenant/e2e-crawl-a/crawl-results/$job_id/pages.ndjson" | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json } | Where-Object { $_.url -eq "http://e2e-fake-site:7031/crawl/a-sitemap-only" } | Select-Object -First 1).key
```

```powershell
curl -fsS "$($env:OBJECT_STORE_S3_PUBLIC_ENDPOINT ?? 'http://localhost:9070')/web-hunter-crawls/$sitemap_key"
```

Call 3 - submit the identical crawl again for `e2e-crawl-a` and poll it to `succeeded` the same way.
Record the second `job_id` as `job_id_2`.

Call 4 - read the second result index. Bash:

```bash
curl -fsS "${OBJECT_STORE_S3_PUBLIC_ENDPOINT:-http://localhost:9070}/web-hunter-crawls/tenant/e2e-crawl-a/crawl-results/${job_id_2}/pages.ndjson"
```

PowerShell 7, with `$job_id_2` holding the same id:

```powershell
curl -fsS "$($env:OBJECT_STORE_S3_PUBLIC_ENDPOINT ?? 'http://localhost:9070')/web-hunter-crawls/tenant/e2e-crawl-a/crawl-results/$job_id_2/pages.ndjson"
```

Call 5 - submit the crawl for `e2e-crawl-b` and poll it to `succeeded` the same way. Record its
`job_id` as `job_id_b`.

Call 6 - submit a wide crawl for `e2e-crawl-a` (no patterns, `max_depth` 5, `page_budget` 100),
poll its status every second until it reads `running`, then cancel it at once. Its id is `wide_id`:

```bash
wide_id=$(curl -fsS -X POST http://127.0.0.1:7021/api/v1/crawl/jobs -H "Content-Type: application/json" -H "X-Ascend-Tenant: e2e-crawl-a" -d '{"seeds":["http://e2e-fake-site:7031/crawl/"],"max_depth":5,"page_budget":100,"respect_robots":true}' | python3 -c "import json,sys; print(json.load(sys.stdin)['job_id'])")
while true; do
  state=$(curl -fsS "http://127.0.0.1:7021/api/v1/crawl/jobs/${wide_id}" -H "X-Ascend-Tenant: e2e-crawl-a" | python3 -c "import json,sys; print(json.load(sys.stdin)['state'])")
  if [ "${state}" = "running" ]; then break; fi
  sleep 1
done
bru run "web-hunter/testing/crawl/job-cancel.yml" --env ascend-local --env-var tenant=e2e-crawl-a --env-var job_id="${wide_id}"
```

Call 7 - list the jobs of each tenant, after every job of this spec exists.

```bash
bru run "web-hunter/testing/crawl/job-list.yml" --env ascend-local --env-var tenant=e2e-crawl-a
```

```bash
bru run "web-hunter/testing/crawl/job-list.yml" --env ascend-local --env-var tenant=e2e-crawl-b
```

Save the fake site request log now and keep the answer. The request log checks of Call 2 and Call 4 under
Expected read this saved answer, because Call 8 requests `/crawl/disallowed` on purpose.

```bash
curl -fsS http://127.0.0.1:7031/__requests
```

Call 8 - submit a crawl for `e2e-crawl-a` that leaves `respect_robots` out, seeded at the page robots.txt
forbids, and poll it to `succeeded` the same way as Call 1. Its id is `default_id`:

```bash
default_id=$(curl -fsS -X POST http://127.0.0.1:7021/api/v1/crawl/jobs -H "Content-Type: application/json" -H "X-Ascend-Tenant: e2e-crawl-a" -d '{"seeds":["http://e2e-fake-site:7031/crawl/disallowed"],"max_depth":0,"page_budget":1}' | python3 -c "import json,sys; print(json.load(sys.stdin)['job_id'])")
```

Read its result index. Bash:

```bash
curl -fsS "${OBJECT_STORE_S3_PUBLIC_ENDPOINT:-http://localhost:9070}/web-hunter-crawls/tenant/e2e-crawl-a/crawl-results/${default_id}/pages.ndjson"
```

PowerShell 7, with `$default_id` holding the same id:

```powershell
curl -fsS "$($env:OBJECT_STORE_S3_PUBLIC_ENDPOINT ?? 'http://localhost:9070')/web-hunter-crawls/tenant/e2e-crawl-a/crawl-results/$default_id/pages.ndjson"
```

Read the fake site request log again:

```bash
curl -fsS http://127.0.0.1:7031/__requests
```

## Expected

- **Call 1:** HTTP 202 with a `job_id` and state `waiting`, and polling with the `poll_after_seconds`
  hint reaches `succeeded`.
- **Call 2:** `pages.ndjson` lists at most 5 pages: `/crawl/`, `/crawl/a`, `/crawl/a/b`,
  `/crawl/blocked-link` and `/crawl/a-sitemap-only`, each with `status` `fetched`. No line is deeper than
  depth 2 (no `/crawl/a/b/c`), no line outside the include pattern (no `/crawl/outside`) and not the
  disallowed path. The request log holds a request with path `/robots.txt`, a request with path
  `/sitemap.xml`, a request with path `/crawl/`, no request with path `/crawl/disallowed` and no request with
  path `/article`. The Prerequisites read put `/crawl/` in the read cache, which keeps a read for 300 s, and the
  reset emptied the log after it, so when Call 1 starts within 300 s of that read the request for `/crawl/`
  proves the crawl fetched its seed from the site and not from the read cache. The log records no host, so the blocked name
  is checked by path: `/crawl/blocked-link` links only to `http://e2e-fake-site-blocked:7031/article`,
  and no page of the crawl tree links to `/article` under the allowed name, so a request with that path
  means the crawl followed the blocked link. Those request log checks read the log saved before Call 8. The job
  status counts hold `skipped_unsafe` of at least 1:

  ```bash
  curl -fsS "http://127.0.0.1:7021/api/v1/crawl/jobs/${job_id}" -H "X-Ascend-Tenant: e2e-crawl-a"
  ```

- **Call 2a:** `sitemap_key` is not empty, and the page file answers HTTP 200 with a body that holds
  the canary sentence
  `The KESTREL-BUOY register lists 19 marker buoys moored off the Mirell south point.`
  No page of the site links to `/crawl/a-sitemap-only`, so this proves the crawl read the sitemap.
- **Call 4:** every page of call 2 is marked `unchanged` with the second job's own result key, a page
  file exists under the second job's own key for each of them:

  ```bash
  curl -fsS "${OBJECT_STORE_S3_PUBLIC_ENDPOINT:-http://localhost:9070}/web-hunter-crawls?list-type=2&prefix=tenant/e2e-crawl-a/crawl-results/${job_id_2}/pages/"
  ```

  ```powershell
  curl -fsS "$($env:OBJECT_STORE_S3_PUBLIC_ENDPOINT ?? 'http://localhost:9070')/web-hunter-crawls?list-type=2&prefix=tenant/e2e-crawl-a/crawl-results/$job_id_2/pages/"
  ```

  Expect one `<Key>` element per unchanged page. The request log saved before Call 8 shows the recrawled
  requests carried `if_none_match` or `if_modified_since`.
- **Call 5:** HTTP 202 and polling reaches `succeeded`.
- **Call 6:** the cancel answers the job with state `cancelled`.
- **Call 7:** the job list of `e2e-crawl-a` holds `job_id`, `job_id_2` and `wide_id` but not
  `job_id_b`; the job list of `e2e-crawl-b` holds `job_id_b` and none of the other three.
- **Call 8:** polling reaches `succeeded`, `pages.ndjson` holds the line for
  `http://e2e-fake-site:7031/crawl/disallowed` with `status` `fetched`, and the request log read after
  Call 8 holds a request with path `/crawl/disallowed`. That log can also hold new requests with path
  `/robots.txt` and `/sitemap.xml`, because a default crawl still reads its sitemaps, and `max_depth` 0 keeps
  no sitemap address, so Call 8 adds no other page. No other check reads this log.

Every assertion above is an HTTP status, a response body, an object store object, an object store
listing or the fake site request log.

## Fixtures

The fake site crawl tree (`/crawl/`, `/crawl/a`, `/crawl/a/b`, `/crawl/a/b/c`, `/crawl/outside`,
`/crawl/blocked-link`, `/crawl/disallowed`, `/crawl/a-sitemap-only`), `/robots.txt` and
`/sitemap.xml` from [fixtures/README.md](../fixtures/README.md). The sitemap lists `/crawl/`,
`/crawl/a`, `/crawl/outside` and `/crawl/a-sitemap-only`, each by its full address.

## Concurrency

Mutates only the two tenants' crawl data and the fake site request log, so it runs beside every spec
that does not reset that log.

- Serial: false
