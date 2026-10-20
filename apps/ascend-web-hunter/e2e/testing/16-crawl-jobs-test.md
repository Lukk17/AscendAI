# Crawl jobs: fake-site crawl e2e test

## What this verifies

Crawl jobs against the fake site's small crawl site under its allowed name `e2e-fake-site`
(design D12 of `add-web-search-scraping-e2e`, owner answer 67.3 of 2026-10-04): a sitemap naming
`/crawl/`, `/crawl/a`, `/crawl/a/b`, `/crawl/a/b/c` and `/crawl/outside`, a robots.txt that disallows
`/crawl/disallowed`, pages down to depth 3 (`/crawl/a/b/c`), a page outside the include pattern
(`/crawl/outside`) and a page (`/crawl/blocked-link`) that links to a fake site path under the
blocked name `e2e-fake-site-blocked`. Tenants `e2e-crawl-a` and `e2e-crawl-b`.

1. A submission for `e2e-crawl-a` with the include pattern `/crawl/[ab]*`, `max_depth` 2 and
   `page_budget` 5 answers HTTP 202 with a `job_id` and state `waiting`, and polling with the
   `poll_after_seconds` hint reaches `succeeded`.
2. The object store holds `tenant/e2e-crawl-a/crawl-results/<job_id>/pages.ndjson` in the crawl
   bucket (read with `curl` on port 9070), listing at most 5 pages, none deeper than depth 2, none
   outside the include pattern and not the disallowed path. The request log shows no request to the
   disallowed path or the private path, and the job counts hold at least one `skipped_unsafe`.
3. A second identical submission reaches `succeeded`, its `pages.ndjson` marks the unchanged pages
   `unchanged`, a page file exists under the second job's own key for each of them, and the request
   log shows those requests carried `If-None-Match` or `If-Modified-Since`.
4. A submission for `e2e-crawl-b` reaches `succeeded`, and the job list of `e2e-crawl-a` does not
   hold it.
5. A submission for `e2e-crawl-a` cancelled with `DELETE /api/v1/crawl/jobs/{job_id}` while
   `running` reads `cancelled`.

## Concurrency

Mutates only the two tenants' crawl data and the fake site request log, so it runs beside every spec
that does not reset that log.

## Prerequisites

Check Bruno CLI is installed.

```bash
bru --version
```

Expect a version string.

Check the ascend-web-hunter server is reachable.

```bash
curl -fsS http://localhost:7021/health
```

Expect HTTP 200 with `{"status":"ok"}`.

Check the fake site is reachable from the host.

```bash
curl -fsS http://127.0.0.1:7031/__requests
```

Expect a request list.

Check the allow list names the allowed fake site name but not the blocked one, so the seed is
fetchable and the blocked-name link is refused. The service was started with
`WEB_HUNTER_ALLOWED_PRIVATE_HOSTS` holding `e2e-fake-site` and no blocked name:

```bash
curl -fsS http://localhost:7021/api/v2/web/read -H "Content-Type: application/json" -d '{"url":"http://e2e-fake-site:7031/crawl/"}'
```

Expect HTTP 200. A read of the blocked name is refused:

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:7021/api/v2/web/read -H "Content-Type: application/json" -d '{"url":"http://e2e-fake-site-blocked:7031/article"}'
```

Expect HTTP 400.

## Reset state

Empty the fake site request log.

```bash
curl -fsS -X POST http://127.0.0.1:7031/__reset
```

Expect `{"reset":true}`.

Delete both tenants' crawl objects from the crawl bucket (Floci speaks plain REST on port 9070):

```bash
for tenant in e2e-crawl-a e2e-crawl-b; do
  curl -fsS "http://127.0.0.1:9070/web-hunter-crawls?list-type=2&prefix=tenant/${tenant}/" \
    | grep -o "<Key>[^<]*" | cut -d'>' -f2 \
    | while read -r key; do curl -fsS -X DELETE "http://127.0.0.1:9070/web-hunter-crawls/${key}"; done
done
```

Expect no output. A following listing for each tenant holds no key:

```bash
curl -fsS "http://127.0.0.1:9070/web-hunter-crawls?list-type=2&prefix=tenant/e2e-crawl-a/"
```

```bash
curl -fsS "http://127.0.0.1:9070/web-hunter-crawls?list-type=2&prefix=tenant/e2e-crawl-b/"
```

Expect no `<Key>` element in either answer.

Delete both tenants' crawl keys from Redis (design D13):

```bash
docker exec redis redis-cli --scan --pattern "crawl_*:e2e-crawl-a:*" | xargs -r docker exec -i redis redis-cli DEL
```

```bash
docker exec redis redis-cli --scan --pattern "crawl_*:e2e-crawl-b:*" | xargs -r docker exec -i redis redis-cli DEL
```

Expect no output and a following scan to return nothing:

```bash
docker exec redis redis-cli --scan --pattern "crawl_*:e2e-crawl-a:*"
```

```bash
docker exec redis redis-cli --scan --pattern "crawl_*:e2e-crawl-b:*"
```

Expect no output. When the scraping file runs alone, the Redis container is `ascend-scrapper-redis`,
so every `docker exec redis` command above targets that container instead.

## Run

Move into the Bruno collection root first.

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
  state=$(curl -fsS "http://localhost:7021/api/v1/crawl/jobs/${job_id}" -H "X-Ascend-Tenant: e2e-crawl-a" | python3 -c "import json,sys; print(json.load(sys.stdin)['state'])")
  echo "state: ${state}"
  if [ "${state}" = "succeeded" ]; then break; fi
  sleep "${hint}"
done
```

Call 2 - read the result index back from the object store.

```bash
curl -fsS "http://127.0.0.1:9070/web-hunter-crawls/tenant/e2e-crawl-a/crawl-results/${job_id}/pages.ndjson"
```

Call 3 - submit the identical crawl again for `e2e-crawl-a` and poll it to `succeeded` the same way.
Record the second `job_id` as `job_id_2`.

Call 4 - read the second result index.

```bash
curl -fsS "http://127.0.0.1:9070/web-hunter-crawls/tenant/e2e-crawl-a/crawl-results/${job_id_2}/pages.ndjson"
```

Call 5 - submit the crawl for `e2e-crawl-b` and poll it to `succeeded` the same way. Record its
`job_id` as `job_id_b`.

Call 6 - list the jobs of each tenant.

```bash
bru run "web-hunter/testing/crawl/job-list.yml" --env ascend-local --env-var tenant=e2e-crawl-a
```

```bash
bru run "web-hunter/testing/crawl/job-list.yml" --env ascend-local --env-var tenant=e2e-crawl-b
```

Call 7 - submit a wide crawl for `e2e-crawl-a` (no patterns, `max_depth` 5, `page_budget` 100),
poll its status every second until it reads `running`, then cancel it at once:

```bash
wide_id=$(curl -fsS -X POST http://localhost:7021/api/v1/crawl/jobs -H "Content-Type: application/json" -H "X-Ascend-Tenant: e2e-crawl-a" -d '{"seeds":["http://e2e-fake-site:7031/crawl/"],"max_depth":5,"page_budget":100}' | python3 -c "import json,sys; print(json.load(sys.stdin)['job_id'])")
while true; do
  state=$(curl -fsS "http://localhost:7021/api/v1/crawl/jobs/${wide_id}" -H "X-Ascend-Tenant: e2e-crawl-a" | python3 -c "import json,sys; print(json.load(sys.stdin)['state'])")
  if [ "${state}" = "running" ]; then break; fi
  sleep 1
done
bru run "web-hunter/testing/crawl/job-cancel.yml" --env ascend-local --env-var tenant=e2e-crawl-a --env-var job_id="${wide_id}"
```

## Expected

- **Call 1:** HTTP 202 with a `job_id` and state `waiting`, and polling with the `poll_after_seconds`
  hint reaches `succeeded`.
- **Call 2:** `pages.ndjson` lists at most 5 pages: `/crawl/`, `/crawl/a`, `/crawl/a/b` and
  `/crawl/blocked-link`, each with `status` `fetched`; no line deeper than depth 2 (no
  `/crawl/a/b/c`), no line outside the include pattern (no `/crawl/outside`) and not the disallowed
  path. The request log holds no request with path `/crawl/disallowed` and none whose host is the
  blocked name, and the job status counts hold `skipped_unsafe` of at least 1:

  ```bash
  curl -fsS http://127.0.0.1:7031/__requests
  ```

  ```bash
  curl -fsS "http://localhost:7021/api/v1/crawl/jobs/${job_id}" -H "X-Ascend-Tenant: e2e-crawl-a"
  ```

- **Call 4:** every page of call 2 is marked `unchanged` with the second job's own result key, a page
  file exists under the second job's own key for each of them:

  ```bash
  curl -fsS "http://127.0.0.1:9070/web-hunter-crawls?list-type=2&prefix=tenant/e2e-crawl-a/crawl-results/${job_id_2}/pages/"
  ```

  Expect one `<Key>` element per unchanged page. The request log shows the recrawled requests carried
  `if_none_match` or `if_modified_since`.
- **Call 5:** HTTP 202 and polling reaches `succeeded`.
- **Call 6:** the job list of `e2e-crawl-a` holds `job_id`, `job_id_2` and the wide job but not
  `job_id_b`; the job list of `e2e-crawl-b` holds `job_id_b` and none of the other three.
- **Call 7:** the cancel answers the job with state `cancelled`.

Every assertion above is an HTTP status, a response body, an object store listing or the fake site
request log.

## Fixtures

The fake site crawl tree (`/crawl/`, `/crawl/a`, `/crawl/a/b`, `/crawl/a/b/c`, `/crawl/outside`,
`/crawl/blocked-link`, `/crawl/disallowed`), `/robots.txt` and `/sitemap.xml` from
[fixtures/README.md](../fixtures/README.md).
