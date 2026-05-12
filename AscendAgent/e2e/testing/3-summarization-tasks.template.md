# Document summarization — run tasks template

Spec: [3-summarization-test.md](3-summarization-test.md)

Copy this file to `runs/<UTC-timestamp>_3-summarization-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] AscendAgent `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [ ] Docling Serve `/health` returns HTTP 200
- [ ] Fixture `AscendAgent/e2e/fixtures/argent-saga-chronicle.pdf` exists

### Run

- [ ] Send `doc-summarization-prompt.yml` via `bru run` and wait for response (may take 30–90s)

### Expected

- [ ] HTTP 200
- [ ] Response `content` quotes specific facts from the source document
- [ ] AscendAgent log shows `HasDoc: true` for this request id
- [ ] AscendAgent log shows `[DocumentRouter] PDF <name> has <N> pages`
- [ ] AscendAgent log shows one `Page i/N ... Routing to Docling` line per page
- [ ] AscendAgent log shows `[DocumentRouter] Dispatching <N> pages of <name> in parallel`
- [ ] AscendAgent log shows one `[DoclingClient] Extracted <chars> characters from <page>.pdf` line per page, each with a non-zero char count
- [ ] AscendAgent log contains no HTTP 404 or 422 responses from Docling for this request

### Verdict

- [ ] Verdict: PASS / FAIL (delete the wrong one)

## Result summary

<!-- One short paragraph: what happened, key evidence, anything noteworthy. -->

---

## Additional tasks I did

<!-- Optional. List anything outside the spec. Leave empty if nothing extra. -->
