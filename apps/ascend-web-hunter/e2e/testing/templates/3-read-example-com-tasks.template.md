# REST v2 read happy path: run tasks template

Spec: [../3-read-example-com-test.md](../3-read-example-com-test.md)

Copy this file to `../runs/<UTC-timestamp>_3-read-example-com-tasks.md` before starting a run. For a repeated run of the same spec in the same sweep, which shares the sweep's timestamp, add `-rerun<N>` before `.md` (`-rerun2` for the second run, `-rerun3` for the third). Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-web-hunter `/health` returns HTTP 200 with `status` `ok`, `service` `ascend-web-hunter` and a non-empty `version`
- [ ] Outbound HTTPS works: `curl -fsS https://www.example.com/` returns HTTP 200 with `"This domain is for use in documentation examples"`

### Reset state

- [ ] Optionally cleared the read cache with `POST /api/v2/web/session/clear` for `https://www.example.com/` and profile `default` (HTTP 200, `status` `"cleared"`)
- [ ] Optionally deleted `tier_memory:example.com` with one `DEL` (document the choice below if the reset was skipped)

### Run

- [ ] From the repository root, `cd docs/api/request/AscendAI`, send `extract-example-com.yml` via `bru run` and wait for HTTP 200

### Expected

- [ ] HTTP 200
- [ ] Body `url` equals `"https://www.example.com/"`
- [ ] Body `status` equals `"success"`
- [ ] One of `content` / `text` / `markdown` is a string with length ≥ 50 characters
- [ ] The populated content field (lowercased) contains `"this domain is for use in documentation examples"`
- [ ] `mode` recorded (a cold read answers `"1-beautifulsoup"`, another tier is logged, not failed)

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
