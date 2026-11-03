# Concurrent interventions: run tasks template

Spec: [../20-concurrent-interventions-test.md](../20-concurrent-interventions-test.md)

Copy this file to `../runs/<UTC-timestamp>_20-concurrent-interventions-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-web-hunter `/health` returns HTTP 200 with `status` `ok`, `service` `ascend-web-hunter` and a non-empty `version`
- [ ] Fake site reachable: `curl -fsS http://127.0.0.1:7031/__requests` returns a request list
- [ ] Redis reachable: `docker exec redis redis-cli PING` returns `PONG`
- [ ] `GET /api/v2/session/interventions` reports `active_flows` `0` and `max_concurrent_flows` `5` before starting

### Reset state

- [ ] No reset needed: reads are stateless, no wall is solved, and the flow registry is already drained (see Prerequisites)

### Run

- [ ] `cd docs/api/request/AscendAI`.
- [ ] Step 0 - recorded the `/ready` status, the `NOVNC_DISPLAY_SIZE` banner value, and the metrics baseline to `/tmp/concurrent-interventions-before.txt`.
- [ ] Step 1 - sent `interventions/intervention-window-open.yml` with the profile variable set to `e2e-w1`, got HTTP 428; recorded `flow_id` and `window.slot`.
- [ ] Step 1 - sent `interventions/intervention-window-open.yml` with the profile variable set to `e2e-w2`, got HTTP 428; recorded `flow_id` and `window.slot`.
- [ ] Step 1 - sent `interventions/intervention-window-open.yml` with the profile variable set to `e2e-w3`, got HTTP 428; recorded `flow_id` and `window.slot`.
- [ ] Step 1 - sent `interventions/intervention-window-open.yml` with the profile variable set to `e2e-w4`, got HTTP 428; recorded `flow_id` and `window.slot`.
- [ ] Step 2 - sent `interventions/interventions-list.yml`, got the four flows.
- [ ] Step 2 - sent `interventions/mcp-session-interventions.yml`, got the same four `flow_id` values.
- [ ] Step 3 - sent `interventions/intervention-window-open.yml` with the profile variable set to `e2e-w5`, got HTTP 428; recorded `flow_id` and `window.slot`.
- [ ] Step 3 - sent `interventions/intervention-window-6th-busy.yml`, got HTTP 409.
- [ ] Step 4 - sent `interventions/intervention-window-duplicate-join.yml`, got HTTP 428; listing still reports `active_flows` `5`.
- [ ] Step 5 - `/ready` answers the same status as Step 0; the article `POST /api/v2/web/read` answers HTTP 200.
- [ ] Step 6 - captured the after-run metrics to `/tmp/concurrent-interventions-after.txt`.
- [ ] Step 7 - polled `GET /api/v2/session/interventions` until `active_flows` `0`.
- [ ] Step 7 - both Redis scans (`session:e2e-fake-site:e2e-w*`, `novnc_flow:e2e-fake-site:e2e-w*`) print nothing.

### Expected

- [ ] Step 1 bodies: `code` `human_intervention_required`, `type`, `status`, `instance`, `traceId`, non-empty `vnc_url`, `joined` `false`.
- [ ] Step 1: four distinct `flow_id` values and four distinct `window.slot` values, each window inside the Step 0 display size.
- [ ] Step 2 listing: `active_flows` `4`, `max_concurrent_flows` `5`, each step-1 `flow_id` once with its target URL, profile, slot, window and a positive `expires_in_seconds`; no `cookies`, no `storage_state`, no page content.
- [ ] Step 2 MCP: same four `flow_id` values.
- [ ] Step 3 `e2e-w5` body: `code` `human_intervention_required`, `joined` `false`, a fifth distinct `flow_id` and a fifth distinct `window.slot` inside the Step 0 display size.
- [ ] Step 3 `e2e-w6` body: `code` `novnc_busy`, `active_flows` `5`, `max_concurrent_flows` `5`, `flows` with five entries, `holder_url` naming the oldest flow; response carries a `Retry-After` header.
- [ ] Step 4 body: `joined` `true` with the step-1 `flow_id` of `e2e-w2`; `active_flows` still `5`.
- [ ] Step 5: `/ready` status matches Step 0; article body `status` `success`.
- [ ] Step 6: `novnc_active_flows` is `5`; `human_intervention_total{joined="true"}` grew by exactly one; `novnc_flow_busy_total` grew by exactly one.
- [ ] Step 7: final listing body reports `active_flows` `0`.
- [ ] Every assertion checked was an HTTP status, a response body, `/metrics`, or a Redis key.

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
