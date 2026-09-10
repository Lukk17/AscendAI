# Cloudflare clearance reuse: run tasks template

Spec: [../12-clearance-reuse-test.md](../12-clearance-reuse-test.md)

Copy this file to `../runs/<UTC-timestamp>_12-clearance-reuse-tasks.md` before starting a run. Tick boxes as you
go. Record both calls' `mode` and `responseTime` under Additional tasks I did.

## Tasks

### Prerequisites

- [ ] `bru --version` returns a version string.
- [ ] `curl -fsS http://localhost:7021/health` returns HTTP 200 with `{"status":"ok"}`.
- [ ] `curl -fsS http://localhost:8191/` returns HTTP 200 (FlareSolverr reachable).
- [ ] `docker exec redis redis-cli PING` returns `PONG`.

### Reset state

- [ ] Deleted `session:scrapingcourse.com:default`, `EXISTS` returns `0`.
- [ ] `POST /api/v2/web/session/clear` for `https://www.scrapingcourse.com/cloudflare-challenge` answered HTTP 200 with `status="cleared"` (in-process read cache for the domain emptied).

### Run

- [ ] `cd docs/api/request/AscendAI`.
- [ ] Call 1 (cold): `clearance-cold.yml` answered HTTP 200, JSON report written.
- [ ] Step 2: read back Call 1's `mode` and `responseTime` from the report and recorded both.
- [ ] Capture check: `docker exec redis redis-cli GET "session:scrapingcourse.com:default"` returned JSON whose `waf` entry contains a `cf_clearance` cookie.
- [ ] Call 2 (warm): `clearance-reuse.yml` sent against the `?reuse=1` address with no profile, JSON report written.
- [ ] Step 5: read back Call 2's `mode` and `responseTime` from the report and recorded both.

### Expected

- [ ] Call 1: HTTP 200, `status="success"`, a content-carrying field (`content`, `text` or `markdown`) of at least 50 characters. `mode` and `responseTime` recorded.
- [ ] Capture check: `session:scrapingcourse.com:default` exists with a `cf_clearance` cookie in its `waf` entry.
- [ ] Call 2: HTTP 200, `status="success"`, a content-carrying field of at least 50 characters, no `vnc_url`, no 428. `mode` and `responseTime` recorded.
- [ ] Call 2's `responseTime` is smaller than Call 1's.
- [ ] If Call 2 answered 428: verdict FAIL, register defect A61 in `docs/DEFECT_REGISTER.md`, response body recorded verbatim under Additional tasks I did.
- [ ] Cleanup: deleted `session:scrapingcourse.com:default`, `EXISTS` returns `0`.
- [ ] Ran after test 6, and not alongside tests 6, 7, 8 or 10.

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

<!-- Record Call 1's and Call 2's mode and responseTime, any 409 novnc_busy body with its holder_url, and, on a
Call 2 that answered 428, the response body verbatim so the A61 register entry can cite it. -->
