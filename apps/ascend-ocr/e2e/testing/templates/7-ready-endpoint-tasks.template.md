# Readiness endpoint: run tasks template

Spec: [../7-ready-endpoint-test.md](../7-ready-endpoint-test.md)

Copy this file to `../runs/<UTC-timestamp>_7-ready-endpoint-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-ocr `/health` returns HTTP 200 with `"status":"ok"`

### Reset state

- [ ] None required

### Run

- [ ] `bru run "ocr/ready.yml" --env ascend-local` returns HTTP 200

### Expected

- [ ] HTTP 200
- [ ] Body `status` equals `"ready"`
- [ ] `checks.engine.status` equals `"ok"` and `checks.engine` reports `warm` true
- [ ] `checks.worker_pool.status` equals `"ok"` and `checks.worker_pool` reports `accepting_work` true
- [ ] `checks.jobs.status` equals `"ok"`, and on an idle service it reports zero `queued` and zero `running`
- [ ] Body has no `queue_depth` key
- [ ] Body `version` is a non-empty string

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
