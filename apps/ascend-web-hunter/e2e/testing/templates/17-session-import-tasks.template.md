# Session import: run tasks template

Spec: [../17-session-import-test.md](../17-session-import-test.md)

Copy this file to `../runs/<UTC-timestamp>_17-session-import-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-web-hunter `/health` returns HTTP 200 with `status` `ok`, `service` `ascend-web-hunter` and a non-empty `version`
- [ ] Redis reachable: `docker exec redis redis-cli PING` returns `PONG`

### Reset state

- [ ] `session:example.net:e2e-import` returns `0` from `EXISTS` (deleted the leftover key first if a prior
      run did not clean up)

### Run

- [ ] Sent `import-mixed.yml` via `bru run` and got HTTP 200
- [ ] Sent `import-status-active.yml` via `bru run` and got HTTP 200
- [ ] Sent `import-clear.yml` via `bru run` and got HTTP 200

### Expected

- [ ] Call 1 body: `status="imported"`, `domain="example.net"`, `profile="e2e-import"`, `auth_cookies=2`,
      `waf_cookies=0`, `dropped_cookies=1`
- [ ] `GET "session:example.net:e2e-import"` contains `CANARY-ALPHA-7741`, `CANARY-BETA-8823`, and
      `"produced_by":"import"`, and contains no `example.org`
- [ ] Call 2 body: `status="active"`, `profile="e2e-import"`
- [ ] Call 3 body: `status="cleared"`, `existed=true`
- [ ] `session:example.net:e2e-import` returns `0` from `EXISTS` after call 3
- [ ] `redis-cli --scan --pattern "session:*"` after the run matches the pre-test key list exactly (no leftover
      `e2e-import` key, no other domain's key touched)

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
