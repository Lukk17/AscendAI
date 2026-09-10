# CAPTCHA solve and session reuse: run tasks template

Spec: [../11-captcha-solve-and-reuse-test.md](../11-captcha-solve-and-reuse-test.md)

Copy this file to `../runs/<UTC-timestamp>_11-captcha-solve-and-reuse-tasks.md` before starting a run. Tick boxes as
you go. Record how long the human solve took and any 409 retry under Additional tasks I did.

## Tasks

### Prerequisites

- [ ] `bru --version` returns a version string.
- [ ] `curl -fsS http://localhost:7021/health` returns HTTP 200 with `{"status":"ok"}`.
- [ ] `curl -fsS http://localhost:8191/` returns HTTP 200 (FlareSolverr reachable).
- [ ] `docker exec redis redis-cli PING` returns `PONG`.

### Reset state

- [ ] Deleted `session:democaptcha.com:default`, `EXISTS` returns `0`.

### Run

- [ ] Run by the main agent on the main session (NOT a fanned-out e2e-runner subagent, whose output never reaches the user).
- [ ] Call 1 (blocked): `captcha-clearance-blocked.yml` answered HTTP 428, `status="human_intervention_required"` and a non-empty `vnc_url`.
- [ ] Main agent printed the `vnc_url` verbatim in the chat for the human to open.
- [ ] Human solve: opened the `vnc_url`, ticked the hCaptcha widget and submitted the form in the NoVNC browser, then confirmed back to the agent.
- [ ] Capture check: `docker exec redis redis-cli GET "session:democaptcha.com:default"` returned JSON whose `auth` entry contains an `hmt_id` cookie (proves a human acted in the window, not that the image task was solved).
- [ ] Call 2 (reuse): `captcha-clearance-reuse.yml` sent against the same URL with no profile.

### Expected

- [ ] Call 1: HTTP 428, `status="human_intervention_required"`, non-empty `vnc_url`.
- [ ] Capture check: `session:democaptcha.com:default` exists with an `hmt_id` cookie in its `auth` entry.
- [ ] Call 2: HTTP 200, `status="success"`, a content-carrying field (`content`, `text` or `markdown`) of at least 50 characters, no 428.
- [ ] If Call 2 answered 428: verdict FAIL, finding recorded in `docs/DEFECT_REGISTER.md` as a product defect in the stored-session routing, not as an environment problem.
- [ ] Cleanup: deleted `session:democaptcha.com:default`, `EXISTS` returns `0`.
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

<!-- Record how long the human solve took, any 409 novnc_busy retry on Call 1 with its holder_url, and, on a Call 2
that answered 428, the response body verbatim so the defect register entry can cite it. -->
