# CAPTCHA solve and capture: run tasks template

Spec: [../11-captcha-solve-and-capture-test.md](../11-captcha-solve-and-capture-test.md)

Copy this file to `../runs/<UTC-timestamp>_11-captcha-solve-and-capture-tasks.md` before starting a run. Tick boxes
as you go. Record how long the human solve took and any 409 retry under Additional tasks I did.

## Tasks

### Prerequisites

- [ ] `bru --version` returns a version string.
- [ ] `curl -fsS http://localhost:7021/health` returns HTTP 200 with `status` `ok`, `service` `ascend-web-hunter` and a non-empty `version`.
- [ ] `docker exec redis redis-cli PING` returns `PONG`.

### Reset state

- [ ] Deleted `session:democaptcha.com:default`, `EXISTS` returns `0`.
- [ ] Deleted `session:democaptcha.com:e2e-h1` and `session:democaptcha.com:e2e-h2`, `EXISTS` returns `0`.

### Run

- [ ] Run by the main agent on the main session (NOT a fanned-out e2e-runner subagent, whose output never reaches the user).
- [ ] Call 1 (blocked): `captcha-clearance-blocked.yml` answered HTTP 428, `code="human_intervention_required"` and a non-empty `vnc_url`.
- [ ] Main agent printed the `vnc_url` verbatim in the chat for the human to open.
- [ ] Human solve: opened the `vnc_url`, ticked the hCaptcha widget and submitted the form in the NoVNC browser, then confirmed back to the agent.
- [ ] Capture check: `docker exec redis redis-cli GET "session:democaptcha.com:default"` returned JSON whose `auth` entry contains an `hmt_id` cookie (proves a human acted in the window, not that the image task was solved).

### Part 2 - Two windows solved out of order

- [ ] Call 2 (blocked under `e2e-h1`): same request with `"profile": "e2e-h1"` answered HTTP 428 with its own `flow_id` and its own `window.slot`; recorded both.
- [ ] Call 3 (blocked under `e2e-h2`): same request with `"profile": "e2e-h2"` answered HTTP 428 with its own `flow_id` and a different `window.slot`; recorded both.
- [ ] Main agent printed both `vnc_url` values and both slots verbatim in the chat.
- [ ] Human solved the `e2e-h2` window first, then confirmed.
- [ ] Listing after the `e2e-h2` solve: holds the Call 2 `flow_id` with its slot and no entry with the Call 3 slot (exactly that flow's slot freed).
- [ ] Capture check: `session:democaptcha.com:e2e-h2` holds an `hmt_id` cookie in its `auth` entry; `session:democaptcha.com:e2e-h1` still absent (`EXISTS` returns `0`).
- [ ] Human solved the `e2e-h1` window second, then confirmed.
- [ ] Listing after the `e2e-h1` solve: holds neither the Call 2 nor the Call 3 `flow_id`.
- [ ] Capture check: `session:democaptcha.com:e2e-h1` holds an `hmt_id` cookie in its `auth` entry; the `e2e-h2` record unchanged.

### Expected

- [ ] Call 1: HTTP 428, `code="human_intervention_required"`, non-empty `vnc_url`.
- [ ] Capture check: `session:democaptcha.com:default` exists with an `hmt_id` cookie in its `auth` entry.
- [ ] Part 2 open: two HTTP 428 answers with two different `flow_id` values and two different `window.slot` values.
- [ ] Part 2 `e2e-h2` solved first: listing keeps the `e2e-h1` flow only; `session:democaptcha.com:e2e-h2` holds `hmt_id`; `session:democaptcha.com:e2e-h1` still absent.
- [ ] Part 2 `e2e-h1` solved second: listing holds neither flow; `session:democaptcha.com:e2e-h1` holds `hmt_id`; `e2e-h2` record unchanged.
- [ ] Cleanup: deleted `session:democaptcha.com:default`, `EXISTS` returns `0`.
- [ ] Cleanup: deleted `session:democaptcha.com:e2e-h1` and `session:democaptcha.com:e2e-h2`, `EXISTS` returns `0`.
- [ ] Ran alone: no other spec opened the human window or flushed `session:*` during this run.

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

<!-- Record how long the human solve took and any 409 novnc_busy retry on Call 1 with its holder_url. -->
