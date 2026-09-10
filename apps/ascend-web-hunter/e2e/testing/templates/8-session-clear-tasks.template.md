# Session clear: run tasks template

Spec: [../8-session-clear-test.md](../8-session-clear-test.md)

Copy this file to `../runs/<UTC-timestamp>_8-session-clear-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-web-hunter `/health` returns HTTP 200 with `{"status":"ok"}`
- [ ] Redis reachable: `docker exec redis redis-cli PING` returns `PONG`

### Reset state

- [ ] `session:example.net:default` and `session:example.com:default` both return `0` from `EXISTS` (deleted
      `example.net`'s leftover key first if a prior run did not clean up)
- [ ] Primed the no-op path: `POST /api/v2/web/session/clear` for `https://example.com/` returned HTTP 200 with
      `existed=false` (empties the in-process read cache spec 3 fills, which the Redis deletes cannot reach)
- [ ] Copied `fixtures/session-clear-seed.json` into the `redis` container
- [ ] Seeded `session:example.net:default` via `redis-cli -x SETEX ... < /tmp/session-clear-seed.json`, got `OK`
- [ ] Confirmed `session:example.net:default` now returns `1` from `EXISTS`

### Run

- [ ] Sent `session-clear-existing.yml` via `bru run` and got HTTP 200
- [ ] Sent `session-clear-idempotent.yml` via `bru run` and got HTTP 200

### Expected

- [ ] Call 1 body: `status="cleared"`, `url="https://example.net/"`, `existed=true`
- [ ] `session:example.net:default` returns `0` from `EXISTS` after call 1
- [ ] Call 2 body: `status="cleared"`, `url="https://example.com/"`, `existed=false`, `cleared_cache_entries=0`
- [ ] `session:example.com:default` returns `0` from `EXISTS` after call 2
- [ ] `redis-cli --scan --pattern "session:*"` after the run matches the pre-test key list exactly (no leftover
      `example.net` key, no other domain's key touched)

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
