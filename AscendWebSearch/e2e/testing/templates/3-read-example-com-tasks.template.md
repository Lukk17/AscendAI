# REST v2 read happy path: run tasks template

Spec: [../3-read-example-com-test.md](../3-read-example-com-test.md)

Copy this file to `../runs/<UTC-timestamp>_3-read-example-com-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] AscendWebSearch `/health` returns HTTP 200 with `{"status":"ok"}`
- [ ] Outbound HTTPS works: `curl -fsS https://www.example.com/` returns HTTP 200 with `<h1>Example Domain</h1>`

### Reset state

- [ ] Optionally flushed Redis `*example.com*` keys (document choice below if skipped)

### Run

- [ ] Send `extract-example-com.yml` via `bru run` and wait for HTTP 200

### Expected

- [ ] HTTP 200
- [ ] Body `url` equals `"https://www.example.com/"`
- [ ] Body `status` equals `"success"`
- [ ] One of `content` / `text` / `markdown` is a string with length ≥ 50 characters
- [ ] The populated content field (lowercased) contains `"example domain"`

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
