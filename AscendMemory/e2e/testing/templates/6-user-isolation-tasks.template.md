# Cross-user memory isolation: run tasks template

Spec: [../6-user-isolation-test.md](../6-user-isolation-test.md)

Copy this file to `../runs/<UTC-timestamp>_6-user-isolation-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] AscendMemory `/health` returns HTTP 200 with `{"status":"ok"}`
- [ ] Qdrant `:6333/readyz` returns HTTP 200

### Reset state

- [ ] `POST /api/v1/memory/wipe?user_id=frostyMemoryIsolationUserA` returns HTTP 200 with `{"status":"success", ...}`

### Run

- [ ] Send `insert-isolation-user-a.yml` via `bru run` and wait for HTTP 200
- [ ] Send `search-isolation-user-b.yml` via `bru run` and wait for HTTP 200

### Expected

- [ ] `insert-isolation-user-a.yml`: response body is a non-empty JSON array with at least one entry carrying a string `id`
- [ ] `search-isolation-user-b.yml`: response body is a JSON array (empty or non-empty)
- [ ] No entry in the search result has `user_id` equal to `"frostyMemoryIsolationUserA"`
- [ ] No entry in the search result has a `memory` field containing `"Tromsø"` (case-insensitive)

### Post-run cleanup

- [ ] `POST /api/v1/memory/wipe?user_id=frostyMemoryIsolationUserA` returns HTTP 200 with `{"status":"success", ...}`

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
