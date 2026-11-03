# Logs reach Loki: run tasks template

Spec: [../2-logs-reach-loki-test.md](../2-logs-reach-loki-test.md)

Copy this file to `../runs/<UTC-timestamp>_2-logs-reach-loki-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] Loki `/ready` prints `ready`

### Reset state

- [ ] None required

### Run

- [ ] Start time recorded in nanoseconds
- [ ] Refused request to `ascend-agent` answers 404
- [ ] Refused request to `ascend-weather-mcp` answers 404
- [ ] Refused request to `ascend-memory` answers 404
- [ ] Refused request to `ascend-audio-scribe` answers 404
- [ ] Refused request to `ascend-web-hunter` answers 404
- [ ] Refused request to `ascend-ocr` answers 404
- [ ] Waited 10 seconds
- [ ] Loki queried once per service with the recorded start time

### Expected

- [ ] Each Loki answer holds at least one stream with at least one entry newer than the recorded time
- [ ] No assertion matched the text of a log line

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

<!-- Optional. List anything outside the spec, e.g. diagnostic curls, manual log inspection, retries with different inputs. Leave empty if nothing extra. -->
