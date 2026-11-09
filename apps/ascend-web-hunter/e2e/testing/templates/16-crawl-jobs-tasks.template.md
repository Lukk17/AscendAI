# Crawl jobs: run tasks template

Spec: [../16-crawl-jobs-test.md](../16-crawl-jobs-test.md)

Copy this file to `../runs/<UTC-timestamp>_16-crawl-jobs-tasks.md` before starting a run. For a repeated run of the same spec in the same sweep, which shares the sweep's timestamp, add `-rerun<N>` before `.md` (`-rerun2` for the second run, `-rerun3` for the third). Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-web-hunter `/health` returns HTTP 200 with `status` `ok`, `service` `ascend-web-hunter` and a non-empty `version`
- [ ] Fake site reachable: `curl -fsS http://127.0.0.1:7031/__requests` returns a request list
- [ ] Allow list names `e2e-fake-site` but not `e2e-fake-site-blocked` (allowed-name read 200, blocked-name read 400)
- [ ] `OBJECT_STORE_S3_PUBLIC_ENDPOINT` (the host's view of the store, `http://localhost:4566` on this host) in the runner's shell holds the value the root `.env` sets, or is unset so every object store command uses `http://localhost:9070`

### Reset state

- [ ] `POST http://127.0.0.1:7031/__reset` returned `{"reset":true}`
- [ ] Deleted every object under `tenant/e2e-crawl-a/` and `tenant/e2e-crawl-b/` at the `OBJECT_STORE_S3_PUBLIC_ENDPOINT` address (default `http://localhost:9070`). Both listings hold no `<Key>`
- [ ] Deleted every Redis key matching `crawl_*:e2e-crawl-a:*` and `crawl_*:e2e-crawl-b:*` (each `DEL` printed its count, or nothing when no key matched). Both scans return nothing

### Run

- [ ] Sent `submit-fake-site.yml` via `bru run` and got HTTP 202; recorded `job_id`
- [ ] Polled the job with the `poll_after_seconds` hint until `succeeded`
- [ ] Read `pages.ndjson` of `job_id` from the object store at the `OBJECT_STORE_S3_PUBLIC_ENDPOINT` address
- [ ] Read the page file of `/crawl/a-sitemap-only` (Call 2a) through the `key` of its `pages.ndjson` line, at the `OBJECT_STORE_S3_PUBLIC_ENDPOINT` address
- [ ] Sent the identical submission again, polled until `succeeded`; recorded `job_id_2`
- [ ] Read `pages.ndjson` of `job_id_2` from the object store at the `OBJECT_STORE_S3_PUBLIC_ENDPOINT` address
- [ ] Submitted for `e2e-crawl-b`, polled until `succeeded`; recorded `job_id_b`
- [ ] Submitted the wide crawl, recorded `wide_id`, polled until `running`, cancelled it via `bru run`
- [ ] Listed the jobs of both tenants via `bru run`
- [ ] Saved the fake site request log, used for the Call 2 and Call 4 request log checks
- [ ] Submitted the crawl that leaves `respect_robots` out, seeded at `/crawl/disallowed`, recorded `default_id`, polled until `succeeded`
- [ ] Read `pages.ndjson` of `default_id` from the object store at the `OBJECT_STORE_S3_PUBLIC_ENDPOINT` address
- [ ] Read the fake site request log again

### Expected

- [ ] Call 1 body: `job_id` present, `state` `waiting`; polling reached `succeeded`
- [ ] Call 2 body: at most 5 pages, all `fetched`, none deeper than depth 2, none outside the include pattern, not the disallowed path
- [ ] Request log: a `/robots.txt` request, a `/sitemap.xml` request, a `/crawl/` request (the seed fetched from the site, not from the read cache the Prerequisites read filled), no `/crawl/disallowed` path and no `/article` path (the blocked-name link's path, the log records no host), and the job counts hold `skipped_unsafe` of at least 1
- [ ] Call 2 body: `/crawl/a-sitemap-only` listed with `status` `fetched`
- [ ] Call 2a body: the page file answers HTTP 200 and holds `The KESTREL-BUOY register lists 19 marker buoys moored off the Mirell south point.`
- [ ] Call 4 body: every page `unchanged` with the second job's own key. One page file per unchanged page under the second job's key, listed at the `OBJECT_STORE_S3_PUBLIC_ENDPOINT` address
- [ ] Request log: the recrawled requests carried `if_none_match` or `if_modified_since`
- [ ] Call 5 reached `succeeded`
- [ ] Call 6 body: state `cancelled`
- [ ] Call 7 bodies: tenant `a` list holds `job_id`, `job_id_2` and `wide_id` but not `job_id_b`; tenant `b` list holds only `job_id_b`
- [ ] Call 8 body: polling reached `succeeded`, `/crawl/disallowed` listed with `status` `fetched`, and the request log read after Call 8 holds a request with path `/crawl/disallowed`

### Verdict

- [ ] Verdict: PASS / FAIL (delete the wrong one)

## Result summary



Start (UTC):

End (UTC):

Duration:

---

## Additional tasks I did

<!-- Optional. List anything outside the spec, e.g. diagnostic curls, manual log inspection, retries with different inputs. Leave empty if nothing extra. -->
