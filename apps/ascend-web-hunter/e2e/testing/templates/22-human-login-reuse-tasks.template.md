# Human login with save and reuse: run tasks template

Spec: [../22-human-login-reuse-test.md](../22-human-login-reuse-test.md)

Copy this file to `../runs/<UTC-timestamp>_22-human-login-reuse-tasks.md` before starting a run. For a repeated run of the same spec in the same sweep, which shares the sweep's timestamp, add `-rerun<N>` before `.md` (`-rerun2` for the second run, `-rerun3` for the third). Tick boxes as you
go. Record how long the human login took, and which security check LinkedIn showed, under Additional tasks I did.
Never write a password or a cookie value into this record, only cookie names and counts.

## Tasks

### Prerequisites

- [ ] `curl -fsS http://127.0.0.1:7021/health` returns HTTP 200 with `status` `ok`, `service` `ascend-web-hunter` and a non-empty `version`.
- [ ] `docker exec redis redis-cli PING` returns `PONG`.
- [ ] The interventions listing reports `active_flows` below `max_concurrent_flows`.
- [ ] The `VNC_PASSWORD` check printed `set` or `unset` (never the value), the word is recorded, and on `unset` the record carries the one sentence of risk from the spec. `unset` does not stop the run.
- [ ] A human with their own LinkedIn account, ideally a second account, is at the keyboard on the main session.

### Reset state

- [ ] Closed any `linkedin.com` window of the profile `e2e-linkedin`: one `204 <flow_id>` line per window, or no line.
- [ ] `POST /api/v2/web/session/clear` for `https://www.linkedin.com/feed/` and `e2e-linkedin` answered HTTP 200 with `status` `cleared`.
- [ ] Deleted every `*linkedin.com*` key, and the scan for `*linkedin.com*` printed nothing.

### Run

- [ ] Run by the main agent on the main session (NOT a fanned-out e2e-runner subagent, whose output never reaches the user).
- [ ] Step 1: the establish call answered HTTP 200, recorded `<first-flow-id>`.
- [ ] Step 2: printed the `vnc_url` verbatim in the chat. The human logged in and passed any security check in the remote window, then confirmed. The runner never asked for or typed the password.
- [ ] Step 3: polled the session status until `last_window` carried `<first-flow-id>`.
- [ ] Step 4: ran the cookie names check.
- [ ] Step 5: read the feed with `include_links` true.
- [ ] Step 6: read the `linkedin.com` entries of the listing.
- [ ] Step 7: restarted the ascend-web-hunter container alone, then the health loop answered.
- [ ] Step 8: read the feed again.
- [ ] Step 9: read the listing and the session status.
- [ ] Step 10: the second establish call answered HTTP 200, recorded `<second-flow-id>`.
- [ ] Step 11: polled the session status until `last_window` carried `<second-flow-id>`.
- [ ] Step 12: read the `linkedin.com` entries of the listing.
- [ ] Step 13: ran the cookie names check again.

### Expected

- [ ] Step 1: `status="login_required"`, `intervention_type="login"`, `target="https://www.linkedin.com/feed/"`, non-empty `vnc_url` and `flow_id`, `joined=false`.
- [ ] Step 3: `status="active"`, `last_window` with `flow_id` `<first-flow-id>`, `intervention_type="login"`, `outcome="resolved"` and a numeric `finished_at`.
- [ ] Step 4: printed `True 6-novnc <count> <names>` with `li_at` among the names.
- [ ] Step 5: printed `200 success - <mode> <n> 0` with `<n>` at least `1` (no 428, no 400 `unsafe_uri`, no `session_expired`).
- [ ] Step 6: no line (the read opened no window).
- [ ] Step 7: the restart ended without an error and `/health` answered `status` `ok`.
- [ ] Step 8: printed `200 success - <mode> <n> 0` with `<n>` at least `1`.
- [ ] Step 9: no listing line, and the status still `active` with the Step 3 `last_window`.
- [ ] Step 10: `status="login_required"`, `flow_id` different from `<first-flow-id>`, `joined=false`.
- [ ] Step 11: `status="active"`, `last_window` with `flow_id` `<second-flow-id>`, `intervention_type="login"`, `outcome="already_authenticated"` and a numeric `finished_at`.
- [ ] Step 12: no line.
- [ ] Step 13: printed `True 6-novnc`, with `li_at` still among the names.
- [ ] Ran alone: no other spec ran during this run, because of the restart in Step 7.

### Post-run cleanup

- [ ] Closed any `linkedin.com` window of the profile `e2e-linkedin`: no line, or one `204 <flow_id>` line per window.
- [ ] `POST /api/v2/web/session/clear` answered HTTP 200 with `status` `cleared` and `existed` `true`.
- [ ] Deleted every other `*linkedin.com*` key, and the scan printed nothing.

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

<!-- Optional. List anything outside the spec, e.g. diagnostic curls, retries, the security check LinkedIn showed. Leave empty if nothing extra. -->
