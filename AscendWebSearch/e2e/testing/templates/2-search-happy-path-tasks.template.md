# REST search happy path: run tasks template

Spec: [../2-search-happy-path-test.md](../2-search-happy-path-test.md)

Copy this file to `../runs/<UTC-timestamp>_2-search-happy-path-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] AscendWebSearch `/health` returns HTTP 200 with `{"status":"ok"}`
- [ ] SearXNG `/search?q=test&format=html` returns HTTP 200 with HTML content

### Reset state

- [ ] None required

### Run

- [ ] Send `search-stable-query.yml` via `bru run` and wait for HTTP 200

### Expected

- [ ] HTTP 200
- [ ] Body is a JSON array of length in `[1, 3]`
- [ ] Every entry has a non-empty string `title`
- [ ] Every entry has a string `url` starting with `http://` or `https://`
- [ ] Every entry has a string `content` field (may be empty)
- [ ] At least one entry's `title` or `content` (lowercased) contains `"openstreetmap"`

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
