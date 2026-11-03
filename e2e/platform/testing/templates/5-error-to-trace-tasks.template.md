# Error to trace: run tasks template

Spec: [../5-error-to-trace-test.md](../5-error-to-trace-test.md)

Copy this file to `../runs/<UTC-timestamp>_5-error-to-trace-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] AscendMemory `/health` prints `200`
- [ ] Tempo search for `service.name=ascend-memory` answers through Grafana with at least one trace

### Reset state

- [ ] None required

### Run

- [ ] `bru run "platform/observability/memory-unknown-path.yml" --env ascend-local` passes
- [ ] Recorded the printed `traceId=<value>` of the problem body
- [ ] Waited 15 seconds
- [ ] `docker compose exec grafana wget -qO- http://tempo:3200/api/traces/<traceId>` answered with the trace

### Expected

- [ ] The request answered HTTP 404 with content type `application/problem+json`, `status` 404 and `code` `not_found`
- [ ] The problem body carries a `traceId` matching `^[0-9a-f]{32}$`
- [ ] The Tempo answer holds at least one batch whose resource attribute `service.name` is `ascend-memory`
- [ ] No assertion matched the text of a log line

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
