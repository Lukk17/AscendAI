# Session establish: run tasks template

Spec: [../10-session-establish-test.md](../10-session-establish-test.md)

Copy this file to `../runs/<UTC-timestamp>_10-session-establish-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-web-hunter `/health` returns HTTP 200 with `{"status":"ok"}`
- [ ] Redis reachable: `docker exec redis redis-cli PING` returns `PONG`

### Reset state

- [ ] `session:example.net:e2e-establish` returns `0` from `EXISTS` (deleted a leftover key first if a prior run of
      this test did not clean up)

### Run

- [ ] Sent `session-establish.yml` via `bru run` and got HTTP 200

### Expected

- [ ] Body: `status="login_required"`, `target="https://example.net/"`, `vnc_url` non-empty string
- [ ] Waited 15 seconds, then `session:example.net:e2e-establish` returned `1` from `EXISTS` (the documented capture
      behaviour, not a defect this test is trying to catch)
- [ ] Deleted `session:example.net:e2e-establish`, `EXISTS` now returns `0`
- [ ] Did not run this test concurrently with test 8

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
