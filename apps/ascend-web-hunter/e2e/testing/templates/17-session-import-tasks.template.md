# Session import: run tasks template

Spec: [../17-session-import-test.md](../17-session-import-test.md)

Copy this file to `../runs/<UTC-timestamp>_17-session-import-tasks.md` before starting a run. For a repeated run of the same spec in the same sweep, which shares the sweep's timestamp, add `-rerun<N>` before `.md` (`-rerun2` for the second run, `-rerun3` for the third). Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-web-hunter `/health` returns HTTP 200 with `status` `ok`, `service` `ascend-web-hunter` and a non-empty `version`
- [ ] Redis reachable: `docker exec redis redis-cli PING` returns `PONG`

### Reset state

- [ ] Recorded the `redis-cli --scan --pattern "session:*"` key list as the baseline (pasted under Additional tasks I did)
- [ ] `session:example.net:e2e-import` returns `0` from `EXISTS` (deleted the leftover key first if a prior
      run did not clean up)

### Run

- [ ] Moved into `docs/api/request/AscendAI` from the repository root
- [ ] Sent `import-mixed.yml` via `bru run` and got HTTP 200
- [ ] Sent `import-status-active.yml` via `bru run` and got HTTP 200
- [ ] Call 3: sent the clear of the Call 1 import (`import-clear.yml` via `bru run`) and got HTTP 200
- [ ] Call 4: sent the localStorage-only import with `curl` and got HTTP 200
- [ ] Call 5: sent the status call with `curl` and got HTTP 200
- [ ] Call 6: sent the clear of the Call 4 import with `curl` and got HTTP 200
- [ ] Call 7: sent the import with neither cookies nor localStorage of the site and got HTTP 400

### Expected

- [ ] Call 1 body: `status="imported"`, `domain="example.net"`, `profile="e2e-import"`, `auth_cookies=2`,
      `waf_cookies=0`, `dropped_cookies=1`
- [ ] `GET "session:example.net:e2e-import"` contains `CANARY-ALPHA-7741` and `CANARY-BETA-8823`, and contains
      no `example.org`
- [ ] The parsed record's `auth.produced_by` equals `"import"` (the `python3` check prints `True`)
- [ ] Call 2 body: `status="active"`, `profile="e2e-import"`
- [ ] Call 3 body: `status="cleared"`, `existed=true`, and `EXISTS` returns `0` after it
- [ ] Call 4 body: `status="imported"`, `domain="example.net"`, `profile="e2e-import"`, `auth_cookies=0`,
      `waf_cookies=0`, `dropped_cookies=0`
- [ ] The parsed record after call 4 prints `True True True` (provenance `import`, no cookie, the
      `CANARY-GAMMA-5517` localStorage canary present)
- [ ] Call 5 body: `status="active"`, `profile="e2e-import"`
- [ ] Call 6 body: `status="cleared"`, `existed=true`, and `EXISTS` returns `0` after it
- [ ] Call 7: HTTP 400 problem body with `code="no_cookies_for_domain"`, `type`
      `https://ascend.ai/errors/no-cookies-for-domain`, `status` `400`, `instance`, a 32 character lower case hex
      `traceId`, and `EXISTS` returns `0` after it
- [ ] `redis-cli --scan --pattern "session:*"` after the run matches the baseline recorded in Reset state exactly (no leftover
      `e2e-import` key, no other domain's key touched)

### Post-run cleanup

- [ ] `session:example.net:e2e-import` returns `0` from `EXISTS` (deleted it first only when a call failed before
      its clear)

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
