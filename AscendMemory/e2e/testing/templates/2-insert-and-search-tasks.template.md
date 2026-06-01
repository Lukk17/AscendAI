# REST insert and search round-trip: run tasks template

Spec: [../2-insert-and-search-test.md](../2-insert-and-search-test.md)

Copy this file to `../runs/<UTC-timestamp>_2-insert-and-search-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] AscendMemory `/health` returns HTTP 200 with `{"status":"ok"}`
- [ ] Qdrant `:6333/readyz` returns HTTP 200

### Reset state

- [ ] `POST /api/v1/memory/wipe?user_id=frostyMemoryInsertSearchTest` returns HTTP 200 with `{"status":"success", ...}`

### Run

- [ ] Send `insert-reykjavik.yml` via `bru run` and wait for HTTP 200
- [ ] Send `search-reykjavik.yml` via `bru run` and wait for HTTP 200

### Expected

- [ ] `insert-reykjavik.yml`: response body is a non-empty JSON array with at least one entry carrying a string `id`
- [ ] `search-reykjavik.yml`: response body is a non-empty JSON array
- [ ] At least one search entry's `memory` field contains `"Reykjavik"` (case-insensitive)
- [ ] That entry's `user_id` equals `"frostyMemoryInsertSearchTest"`
- [ ] That entry's `score` is a finite number > 0

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
