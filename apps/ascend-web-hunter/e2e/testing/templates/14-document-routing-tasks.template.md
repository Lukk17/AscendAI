# Document routing: run tasks template

Spec: [../14-document-routing-test.md](../14-document-routing-test.md)

Copy this file to `../runs/<UTC-timestamp>_14-document-routing-tasks.md` before starting a run. For a repeated run of the same spec in the same sweep, which shares the sweep's timestamp, add `-rerun<N>` before `.md` (`-rerun2` for the second run, `-rerun3` for the third). Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-web-hunter `/health` returns HTTP 200 with `status` `ok`, `service` `ascend-web-hunter` and a non-empty `version`
- [ ] docling-serve `/health` returns HTTP 200 with `{"status":"ok"}`
- [ ] ascend-ocr `/health` returns HTTP 200 with `status` `ok`, `service` `ascend-ocr` and a non-empty `version`
- [ ] ascend-audio-scribe `/health` returns HTTP 200 with `status` `ok`, `service` `ascend-audio-scribe` and a non-empty `version`
- [ ] Fake site reachable: `curl -fsS http://127.0.0.1:7031/__requests` returns a request list

### Reset state

- [ ] `POST http://127.0.0.1:7031/__reset` returned `{"reset":true}`
- [ ] `POST http://127.0.0.1:7021/api/v2/web/session/clear` with `{"url":"http://e2e-fake-site:7031/","profile":"default"}` returned HTTP 200 with `status` `"cleared"`
- [ ] `docker exec redis redis-cli DEL "session:e2e-fake-site:default" "novnc_window_result:e2e-fake-site:default" "tier_memory:e2e-fake-site"` returned a number from `0` to `3`
- [ ] `GET http://127.0.0.1:7022/v1/ocr/jobs` listed `0` jobs (the queue is empty, no work waiting or running)

### Run

- [ ] From the repository root, `cd docs/api/request/AscendAI`
- [ ] Sent `route-pdf.yml` via `bru run` and got HTTP 200
- [ ] Sent `route-image.yml` via `bru run` and got HTTP 200
- [ ] Sent `route-audio.yml` via `bru run` and got HTTP 200
- [ ] Sent `route-pdf-oversized.yml` via `bru run` and got HTTP 200
- [ ] Sent `route-private-link.yml` via `bru run` and got HTTP 200

### Expected

- [ ] Call 1 body: `content` holds `"HELIX-FINCH"`
- [ ] Call 2 body: `content` holds `"Mirellion"`, and `GET /v1/ocr/jobs` then lists `0` jobs (the job is in a final state and the queue is empty, the list never shows finished jobs)
- [ ] Found Call 2's job identifier in the `Job <job_id> -> succeeded` line of `docker logs ascend-ocr --since "<Start (UTC)>"` (used only to find it, not a pass criterion). No line fails Call 2
- [ ] Polled `GET http://127.0.0.1:7022/v1/ocr/jobs/<job_id>` once a second for at most 10 tries, because the delete runs in the background after the read answers (the poll only waits, it is not a pass criterion)
- [ ] `GET http://127.0.0.1:7022/v1/ocr/jobs/<job_id>` returned HTTP 404 with `code` `"JOB_NOT_FOUND"` (ascend-web-hunter deleted the job in the background after the read). HTTP 200 with `state` `succeeded` after the poll fails Call 2
- [ ] Call 3 body: `content` holds `"KAKSMA"` or `"Kaxma"` (case-insensitive; CPU `KAKSMA` vs GPU `Kaxma.`)
- [ ] Call 4 body: HTTP 200, no 428, `routing_error` equal to `"file_too_large"`
- [ ] Call 4 request log: exactly one entry for `/files/oversized.pdf` and it is a GET with `bytes_sent` equal to `0`
- [ ] Call 4 `GET http://127.0.0.1:7021/api/v2/session/interventions` reported `active_flows` `0`
- [ ] Call 4 `docker exec redis redis-cli EXISTS "session:e2e-fake-site:default" "novnc_window_result:e2e-fake-site:default"` returned `0`
- [ ] Call 5 body: `content` holds `"HALCYON-PLOVER"` plus `routing_error`. The request log holds `/pdf-link-blocked` and exactly one `/files/canary.pdf` entry, the one from Call 1

### Post-run cleanup

- [ ] `POST http://127.0.0.1:7031/__reset` returned `{"reset":true}`
- [ ] `docker exec redis redis-cli DEL "session:e2e-fake-site:default" "novnc_window_result:e2e-fake-site:default" "tier_memory:e2e-fake-site"` returned a number from `0` to `3`

### Verdict

- [ ] Verdict: PASS / FAIL (delete the wrong one)

## Result summary



Input tokens:

Output tokens:

Start (UTC):

End (UTC):

Duration:

---

## Additional tasks I did

<!-- Optional. List anything outside the spec, e.g. diagnostic curls, manual log inspection, retries with different inputs. Leave empty if nothing extra. -->
