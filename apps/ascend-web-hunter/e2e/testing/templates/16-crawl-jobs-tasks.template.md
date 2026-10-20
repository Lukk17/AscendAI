# Crawl jobs: run tasks template

Spec: [../16-crawl-jobs-test.md](../16-crawl-jobs-test.md)

Copy this file to `../runs/<UTC-timestamp>_16-crawl-jobs-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-web-hunter `/health` returns HTTP 200 with `{"status":"ok"}`
- [ ] Fake site reachable: `curl -fsS http://127.0.0.1:7031/__requests` returns a request list
- [ ] Allow list names `e2e-fake-site` but not `e2e-fake-site-blocked` (allowed-name read 200, blocked-name read 400)

### Reset state

- [ ] `POST http://127.0.0.1:7031/__reset` returned `{"reset":true}`
- [ ] Deleted every object under `tenant/e2e-crawl-a/` and `tenant/e2e-crawl-b/`; both listings hold no `<Key>`
- [ ] Deleted every Redis key matching `crawl_*:e2e-crawl-a:*` and `crawl_*:e2e-crawl-b:*`; both scans return nothing

### Run

- [ ] Sent `submit-fake-site.yml` via `bru run` and got HTTP 202; recorded `job_id`
- [ ] Polled the job with the `poll_after_seconds` hint until `succeeded`
- [ ] Read `pages.ndjson` of `job_id` from the object store
- [ ] Sent the identical submission again, polled until `succeeded`; recorded `job_id_2`
- [ ] Read `pages.ndjson` of `job_id_2` from the object store
- [ ] Submitted for `e2e-crawl-b`, polled until `succeeded`; recorded `job_id_b`
- [ ] Listed the jobs of both tenants via `bru run`
- [ ] Submitted the wide crawl, polled until `running`, cancelled it via `bru run`

### Expected

- [ ] Call 1 body: `job_id` present, `state` `waiting`; polling reached `succeeded`
- [ ] Call 2 body: at most 5 pages, all `fetched`, none deeper than depth 2, none outside the include pattern, not the disallowed path
- [ ] Request log: no `/crawl/disallowed` path and no blocked-name host; job counts hold `skipped_unsafe` of at least 1
- [ ] Call 4 body: every page `unchanged` with the second job's own key; one page file per unchanged page under the second job's key
- [ ] Request log: the recrawled requests carried `if_none_match` or `if_modified_since`
- [ ] Call 5 reached `succeeded`
- [ ] Call 6 bodies: tenant `a` list holds its three jobs but not `job_id_b`; tenant `b` list holds only `job_id_b`
- [ ] Call 7 body: state `cancelled`

### Verdict

- [ ] Verdict: PASS / FAIL (delete the wrong one)

## Result summary



Start (UTC):

End (UTC):

Duration:

---

## Additional tasks I did

<!-- Optional. List anything outside the spec, e.g. diagnostic curls, manual log inspection, retries with different inputs. Leave empty if nothing extra. -->
