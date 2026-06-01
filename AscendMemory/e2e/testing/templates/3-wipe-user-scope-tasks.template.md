# Wipe user-scope isolation: run tasks template

Spec: [../3-wipe-user-scope-test.md](../3-wipe-user-scope-test.md)

Copy this file to `../runs/<UTC-timestamp>_3-wipe-user-scope-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] AscendMemory `/health` returns HTTP 200 with `{"status":"ok"}`
- [ ] Qdrant `:6333/readyz` returns HTTP 200

### Reset state

- [ ] `POST /api/v1/memory/wipe?user_id=frostyMemoryWipeAlpha` returns HTTP 200 with `{"status":"success", ...}`
- [ ] `POST /api/v1/memory/wipe?user_id=frostyMemoryWipeBeta` returns HTTP 200 with `{"status":"success", ...}`

### Run

- [ ] Send `insert-alpha.yml` via `bru run` and wait for HTTP 200
- [ ] Send `insert-beta.yml` via `bru run` and wait for HTTP 200
- [ ] Send `wipe-alpha.yml` via `bru run` and wait for HTTP 200
- [ ] Send `search-alpha.yml` via `bru run` and wait for HTTP 200
- [ ] Send `search-beta.yml` via `bru run` and wait for HTTP 200

### Expected

- [ ] `insert-alpha.yml`: response body is a non-empty JSON array with at least one entry carrying a string `id`
- [ ] `insert-beta.yml`: response body is a non-empty JSON array with at least one entry carrying a string `id`
- [ ] `wipe-alpha.yml`: response body has `status="success"` and `message` references `"frostyMemoryWipeAlpha"`
- [ ] `search-alpha.yml`: response body is a JSON array with NO entry whose `memory` contains `"Lisbon"` (case-insensitive)
- [ ] `search-beta.yml`: response body is a non-empty JSON array
- [ ] At least one Beta search entry's `memory` contains `"Madrid"` (case-insensitive)
- [ ] That entry's `user_id` equals `"frostyMemoryWipeBeta"`
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
