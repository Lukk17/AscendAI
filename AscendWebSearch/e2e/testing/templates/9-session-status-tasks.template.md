# Session status: run tasks template

Spec: [../9-session-status-test.md](../9-session-status-test.md)

Copy this file to `../runs/<UTC-timestamp>_9-session-status-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] AscendWebSearch `/health` returns HTTP 200 with `{"status":"ok"}`
- [ ] Redis reachable: `docker exec redis redis-cli PING` returns `PONG`

### Reset state

- [ ] `session:example.com:default` and `session:example.org:default` both return `0` from `EXISTS` (deleted
      `example.org`'s leftover key first if a prior run did not clean up)
- [ ] Copied `fixtures/session-status-expired-seed.json` into the `redis` container
- [ ] Seeded `session:example.org:default` via `redis-cli -x SETEX ... < /tmp/session-status-expired-seed.json`, got `OK`

### Run

- [ ] Sent `session-status-none.yml` via `bru run` and got HTTP 200
- [ ] Sent `session-status-expired.yml` via `bru run` and got HTTP 200
- [ ] Generated a fresh `saved_at` JSON and re-seeded `session:example.org:default`, got `OK`
- [ ] Sent `session-status-active.yml` via `bru run` and got HTTP 200

### Expected

- [ ] Call 1 body: `status="none"`, `auth_ttl_remaining_seconds=0`, `last_validated=null`, `profile="default"`
- [ ] Call 2 body: `status="expired"`, `auth_ttl_remaining_seconds=0`, `last_validated=null`
- [ ] Call 3 body: `status="active"`, `auth_ttl_remaining_seconds` above `1209000`, `last_validated` within the last
      5 minutes
- [ ] `session:example.org:default` deleted at cleanup
- [ ] `redis-cli --scan --pattern "session:*"` after the run matches the pre-test key list exactly
- [ ] Deleted the locally-generated `session-status-active-seed.json` (not a committed fixture)

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
