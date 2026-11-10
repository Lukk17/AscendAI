# Structured extraction: run tasks template

Spec: [../13-structured-extraction-test.md](../13-structured-extraction-test.md)

Copy this file to `../runs/<UTC-timestamp>_13-structured-extraction-tasks.md` before starting a run. For a repeated run of the same spec in the same sweep, which shares the sweep's timestamp, add `-rerun<N>` before `.md` (`-rerun2` for the second run, `-rerun3` for the third). Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-web-hunter `/health` returns HTTP 200 with `status` `ok`, `service` `ascend-web-hunter` and a non-empty `version`
- [ ] Fake site reachable: `curl -fsS http://127.0.0.1:7031/__requests` returns a request list

### Reset state

- [ ] `POST http://127.0.0.1:7031/__reset` returned `{"reset":true}` (log empty, product layout 1)

### Run

- [ ] Sent `structured-jsonld.yml` via `bru run` and got HTTP 200
- [ ] Sent `tables.yml` via `bru run` and got HTTP 200
- [ ] Sent `screenshot.yml` via `bru run` twice, HTTP 200 both times

### Expected

- [ ] Step 1 body: article fields plus `metadata["json-ld"][0].name="Brassbound Meridian Astrolabe"` and `offers.price=847.25`
- [ ] Step 2 body: `tables` equals the three fixture rows, cell for cell
- [ ] Step 3 bodies: `content` starts with `"iVBOR"` both times
- [ ] Request log shows exactly `2` requests to `/article`

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
