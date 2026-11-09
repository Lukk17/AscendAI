# Cloudflare clearance reuse: run tasks template

Spec: [../12-clearance-reuse-test.md](../12-clearance-reuse-test.md)

Copy this file to `../runs/<UTC-timestamp>_12-clearance-reuse-tasks.md` before starting a run. For a repeated run of the same spec in the same sweep, which shares the sweep's timestamp, add `-rerun<N>` before `.md` (`-rerun2` for the second run, `-rerun3` for the third). Tick boxes as you
go. Record both calls' `mode` and `responseTime` under Additional tasks I did.

## Tasks

### Prerequisites

- [ ] `bru --version` returns a version string.
- [ ] `curl -fsS http://127.0.0.1:7021/health` returns HTTP 200 with `status` `ok`, `service` `ascend-web-hunter` and a non-empty `version`.
- [ ] `docker exec redis redis-cli PING` returns `PONG`.

### Reset state

- [ ] Listed `GET /api/v2/session/interventions` and closed each flow for `scrapingcourse.com` with `DELETE /api/v2/session/interventions/{flow_id}`, each answering `204` (a `404` only for a window that ended on its own), and the listing after it showed no flow for `scrapingcourse.com`, before the delete.
- [ ] Deleted `session:scrapingcourse.com:default` and `tier_memory:scrapingcourse.com`, `EXISTS` returns `0`.
- [ ] `POST /api/v2/web/session/clear` for `https://www.scrapingcourse.com/cloudflare-challenge` answered HTTP 200 with `status="cleared"` (in-process read cache for the domain emptied).

### Run

- [ ] `cd docs/api/request/AscendAI`.
- [ ] Created the private report directory `E2E_OUT` (`mktemp -d`, or a random folder under the temp path in PowerShell), no fixed `/tmp` or `$env:TEMP` path.
- [ ] Call 1 (cold): `clearance-cold.yml` answered HTTP 200 with a solved page, or HTTP 428/409 as an environment gate with nobody at the keyboard, JSON report written.
- [ ] Step 2: read back Call 1's HTTP status, `mode` (or the problem `code` on a 428 or 409) and `responseTime` from the report and recorded them.
- [ ] Human branch (only when Call 1 answered 428 and a human is at the keyboard): printed the `vnc_url`, the human passed the challenge in the window and confirmed in the chat, and the session status `last_window` carried the 428's `flow_id` with `intervention_type` `"captcha"` and `outcome` `"resolved"`.
- [ ] Capture check: `docker exec redis redis-cli GET "session:scrapingcourse.com:default"` returned JSON whose `waf` entry contains a `cf_clearance` cookie (skipped when Call 1 was gated).
- [ ] Call 2 (warm): `clearance-reuse.yml` sent against the `?reuse=1` address with no profile, JSON report written.
- [ ] Step 5: read back Call 2's HTTP status, `mode` (or the problem `code` on a 428) and `responseTime` from the report and recorded them.

### Expected

- [ ] Call 1: HTTP 200, `status="success"`, a content-carrying field (`content`, `text` or `markdown`) of at least 50 characters. `mode` and `responseTime` recorded.
- [ ] Capture check: `session:scrapingcourse.com:default` exists with a `cf_clearance` cookie in its `waf` entry, not saved while the page was still a wall (a cookie saved on a wall is a FAIL).
- [ ] Call 2: HTTP 200, `status="success"`, a content-carrying field of at least 50 characters, no `vnc_url`, no 428. `mode` and `responseTime` recorded.
- [ ] Call 2's `responseTime` is smaller than Call 1's (not compared in the human branch).
- [ ] If Call 2 answered 428: verdict FAIL, register defect F54 in `docs/DEFECT_REGISTER.md`, response body recorded verbatim under Additional tasks I did.
- [ ] Cleanup: closed each flow for `scrapingcourse.com` with `DELETE /api/v2/session/interventions/{flow_id}` (each `204`, a `404` only for a window that ended on its own), the listing after it showed no flow for `scrapingcourse.com`, then deleted `session:scrapingcourse.com:default`, `novnc_window_result:scrapingcourse.com:default` and `tier_memory:scrapingcourse.com` with one `DEL`, `EXISTS` on all three returns `0`.
- [ ] Cleanup: removed the `E2E_OUT` report directory.
- [ ] Ran after test 6, and not alongside tests 6, 8, 10 or 17 or spec 20.

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
Call 2 that answered 428, the response body verbatim so the F54 register entry can cite it. -->
