# Concurrent interventions: run tasks template

Spec: [../20-concurrent-interventions-test.md](../20-concurrent-interventions-test.md)

Copy this file to `../runs/<UTC-timestamp>_20-concurrent-interventions-tasks.md` before starting a run. For a repeated run of the same spec in the same sweep, which shares the sweep's timestamp, add `-rerun<N>` before `.md` (`-rerun2` for the second run, `-rerun3` for the third). Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-web-hunter `/health` returns HTTP 200 with `status` `ok`, `service` `ascend-web-hunter` and a non-empty `version`
- [ ] Fake site reachable: `curl -fsS http://127.0.0.1:7031/__requests` returns a request list
- [ ] Redis reachable: `docker exec redis redis-cli PING` returns `PONG`
- [ ] `GET /api/v2/session/interventions` reports `active_flows` `0` and `max_concurrent_flows` `4` before starting

### Reset state

- [ ] One `DEL` named `novnc_window_result:e2e-fake-site:e2e-w1` to `e2e-w4`, answered a number from `0` to `4`

### Run

- [ ] Steps 1 to 7a ran back to back, inside the 630 s lease of the `e2e-w1` flow (BLOCKED if it expired first).
- [ ] From the repository root, `cd docs/api/request/AscendAI`.
- [ ] Step 0 - created the private report directory `E2E_OUT` (`mktemp -d`, or a random folder under the temp path in PowerShell), no fixed `/tmp` path.
- [ ] Step 0 - recorded the `/ready` status, the `NoVNC display` banner value, and the metrics baseline to `concurrent-interventions-before.txt` in `E2E_OUT`.
- [ ] Step 1 - sent `interventions/intervention-window-open.yml` with the profile variable set to `e2e-w1`, got HTTP 428; recorded `flow_id` and `window.slot`.
- [ ] Step 1 - sent `interventions/intervention-window-open.yml` with the profile variable set to `e2e-w2`, got HTTP 428; recorded `flow_id` and `window.slot`.
- [ ] Step 1 - sent `interventions/intervention-window-open.yml` with the profile variable set to `e2e-w3`, got HTTP 428; recorded `flow_id` and `window.slot`.
- [ ] Step 1 - sent `interventions/intervention-window-open.yml` with the profile variable set to `e2e-w4`, got HTTP 428; recorded `flow_id` and `window.slot`.
- [ ] Step 2 - sent `interventions/interventions-list.yml`, got the four flows.
- [ ] Step 2 - sent `interventions/mcp-session-interventions.yml`, got the same four `flow_id` values.
- [ ] Step 3 - sent `interventions/intervention-window-5th-busy.yml` (profile `e2e-w5`), got HTTP 409.
- [ ] Step 4 - sent `interventions/intervention-window-duplicate-join.yml`, got HTTP 428; listing still reports `active_flows` `4`.
- [ ] Step 5 - `/ready` answers the same status as Step 0; the article `POST /api/v2/web/read` answers HTTP 200.
- [ ] Step 6 - captured the after-run metrics to `concurrent-interventions-after.txt` in `E2E_OUT`.
- [ ] Step 7a - `DELETE /api/v2/session/interventions/<w1-flow-id>` sent.
- [ ] Step 7b - listing read right after the close.
- [ ] Step 7c - the same `DELETE` sent a second time.
- [ ] Step 7d - MCP `initialize` answered HTTP 200 with no `Mcp-Session-Id` header, then `session_cancel_intervention` called with `<w2-flow-id>`.
- [ ] Step 7e - listing read right after the MCP close.
- [ ] Step 7f - `session_cancel_intervention` called a second time with `<w2-flow-id>`.
- [ ] Step 7g - `POST /api/v2/web/session/status` sent for `e2e-w1` and for `e2e-w2`.

### Expected

- [ ] Step 1 bodies: `code` `human_intervention_required`, `type`, `status`, `instance`, `traceId`, non-empty `vnc_url`, `joined` `false`.
- [ ] Step 1: four distinct `flow_id` values and four distinct `window.slot` values, each window inside the Step 0 display size.
- [ ] Step 2 listing: `active_flows` `4`, `max_concurrent_flows` `4`, each step-1 `flow_id` once with its target URL, profile, `window.slot`, window and a positive `expires_in_seconds`; no `cookies`, no `storage_state`, no page content.
- [ ] Step 2 MCP: same four `flow_id` values.
- [ ] Step 3 `e2e-w5` body: `code` `novnc_busy`, `active_flows` `4`, `max_concurrent_flows` `4`, `flows` with four entries, `holder_profile` `e2e-w1` (the oldest flow), `holder_url` `http://e2e-fake-site:7031/turnstile-wall`. The response carries a `Retry-After` header.
- [ ] Step 4 body: `joined` `true` with the step-1 `flow_id` of `e2e-w2`; `active_flows` still `4`.
- [ ] Step 5: `/ready` status matches Step 0; article body `status` `success`.
- [ ] Step 6: `novnc_active_flows` is `4`. `human_intervention_total{intervention_type="captcha",joined="true"}` grew by exactly one. `novnc_flow_busy_total` grew by exactly one. A line missing from the baseline counted as 0.
- [ ] Step 7a: HTTP `204` with an empty body.
- [ ] Step 7b: `active_flows` `3`, no entry with the `e2e-w1` `flow_id` (the slot was free at once).
- [ ] Step 7c: HTTP `404` problem body with `code` `flow_not_found`, `type` `https://ascend.ai/errors/flow-not-found`, `status` `404`, `instance`, and a 32 character lower case hex `traceId`.
- [ ] Step 7d: a result that is not an error with payload `{"status":"cancelled","flow_id":"<w2-flow-id>"}`.
- [ ] Step 7e: `active_flows` `2`, no entry with the `e2e-w2` `flow_id`.
- [ ] Step 7f: a result with `isError` `true` whose text starts with `flow_not_found: `.
- [ ] Step 7g: both answers `status` `none` (nothing saved), each with a `last_window` holding its own `flow_id`, `intervention_type` `captcha`, `outcome` `cancelled` and a numeric `finished_at`.
- [ ] Every assertion checked was an HTTP status, a response body, `/metrics`, or a Redis key.

### Post-run cleanup

- [ ] Closed the `e2e-w3` and `e2e-w4` flows with `DELETE /api/v2/session/interventions/{flow_id}`, two lines `204 <flow_id>`.
- [ ] The listing after it reports `active_flows` `0`.
- [ ] Both Redis scans (`session:e2e-fake-site:e2e-w*`, `novnc_flow:e2e-fake-site:e2e-w*`) print nothing.
- [ ] One `DEL` named `novnc_window_result:e2e-fake-site:e2e-w1` to `e2e-w4`, answered `4`.
- [ ] Removed the `E2E_OUT` report directory with both metrics files.

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
