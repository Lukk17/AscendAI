# Session establish: run tasks template

Spec: [../10-session-establish-test.md](../10-session-establish-test.md)

Copy this file to `../runs/<UTC-timestamp>_10-session-establish-tasks.md` before starting a run. For a repeated run of the same spec in the same sweep, which shares the sweep's timestamp, add `-rerun<N>` before `.md` (`-rerun2` for the second run, `-rerun3` for the third). Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-web-hunter `/health` returns HTTP 200 with `status` `ok`, `service` `ascend-web-hunter` and a non-empty `version`
- [ ] Redis reachable: `docker exec redis redis-cli PING` returns `PONG`
- [ ] NoVNC flows listing checked: `curl -fsS http://127.0.0.1:7021/api/v2/session/interventions` reported
      `active_flows` below `max_concurrent_flows` (re-checked every 30 seconds until it did, before starting the Run
      section). An `example.net` entry for `e2e-establish` or `e2e-establish-auth` is left for the Reset state to close

### Reset state

- [ ] `session:example.net:e2e-establish` returns `0` from `EXISTS` (deleted a leftover key first if a prior failed
      run of this test did not clean up)
- [ ] Deleted `session:example.net:e2e-establish-auth` (`DEL` returned `0` or `1`)
- [ ] Deleted `novnc_window_result:example.net:e2e-establish` and `novnc_window_result:example.net:e2e-establish-auth`
      (`DEL` returned `0`, `1` or `2`)
- [ ] Closed any open `example.net` window for the two profiles: one `204 <flow_id>` line per window, or no line

### Run

- [ ] Step 1: sent `session-establish.yml` via `bru run` and got HTTP 200, recorded `<first-flow-id>`
- [ ] Step 2: waited 15 seconds, then ran `EXISTS` on `session:example.net:e2e-establish`
- [ ] Step 3: sent `DELETE /api/v2/session/interventions/<first-flow-id>`
- [ ] Step 4: read the interventions listing
- [ ] Step 5: sent `POST /api/v2/web/session/status` for `https://example.net/` and `e2e-establish`
- [ ] Step 6: imported the `e2e-establish-login` cookie for `example.net` under `e2e-establish-auth`
- [ ] Step 7: sent the establish call for `https://example.net` and `e2e-establish-auth`, recorded `<second-flow-id>`
- [ ] Step 8: polled the session status every 5 seconds, at most 24 times, until `last_window` carried
      `<second-flow-id>`
- [ ] Step 9: read the interventions listing
- [ ] Step 10: read the `session:example.net:e2e-establish-auth` record through the Python check

### Expected

- [ ] Step 1 body: `status="login_required"`, `intervention_type="login"`, `target="https://example.net/"`, `vnc_url`
      non-empty string, `flow_id` non-empty string, `joined=false`, `window` object with integer `slot`, `x`, `y`,
      `width` and `height`
- [ ] Step 2: `EXISTS` returned `0` (no session is saved for a page that never showed a login, a `1` is a defect)
- [ ] Step 3: HTTP `204` with an empty body
- [ ] Step 4: no `flows` entry with `<first-flow-id>`
- [ ] Step 5: HTTP 200, `status="none"`, `profile="e2e-establish"`, `last_window` with `flow_id` `<first-flow-id>`,
      `intervention_type="login"`, `outcome="cancelled"` and a numeric `finished_at`
- [ ] Step 6: HTTP 200, `status="imported"`, `domain="example.net"`, `profile="e2e-establish-auth"`,
      `auth_cookies=1`, `waf_cookies=0`, `dropped_cookies=0`
- [ ] Step 7: HTTP 200, `status="login_required"`, `intervention_type="login"`, `target="https://example.net/"`,
      `flow_id` non-empty and different from `<first-flow-id>`, `joined=false`
- [ ] Step 8: last body `status="active"`, `profile="e2e-establish-auth"`, `last_window` with `flow_id`
      `<second-flow-id>`, `intervention_type="login"`, `outcome="already_authenticated"` and a numeric
      `finished_at` (no `<second-flow-id>` after the last poll, or any other `outcome`, is a FAIL)
- [ ] Step 9: no `flows` entry with `<second-flow-id>`
- [ ] Step 10: printed `True True True`
- [ ] Did not run this test concurrently with test 7, test 8, test 17, spec 20, test 11 or spec 22

### Post-run cleanup

- [ ] Closed any `example.net` window still open for the two profiles: no line, or one `204 <flow_id>` line per
      window
- [ ] `POST /api/v2/web/session/clear` for `https://example.net/` and `e2e-establish-auth` answered HTTP 200 with
      `status="cleared"` and `existed=true`
- [ ] Deleted the two `novnc_window_result:example.net:*` keys of this spec and `session:example.net:e2e-establish`
- [ ] `EXISTS` on `session:example.net:e2e-establish` and `session:example.net:e2e-establish-auth` returned `0`

### Verdict

- [ ] Verdict: PASS / FAIL (delete the wrong one)

## Result summary



Input tokens: 0

Output tokens: 0

Start (UTC):

End (UTC):

Duration:

---

## Additional tasks I did

<!-- Optional. List anything outside the spec, e.g. diagnostic curls, manual log inspection, retries with different inputs. Leave empty if nothing extra. -->
