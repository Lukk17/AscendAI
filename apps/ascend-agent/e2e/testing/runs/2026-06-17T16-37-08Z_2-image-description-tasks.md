# Image description: run tasks template

Spec: [2-image-description-test.md](2-image-description-test.md)

Copy this file to `runs/<UTC-timestamp>_2-image-description-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [x] Bruno CLI present (`bru --version` returns a version)
- [x] AscendAgent `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [x] Fixture `AscendAgent/e2e/fixtures/image.png` exists

### Run

- [x] Send `image-description-prompt.yml` via `bru run` and wait for response

### Expected

- [ ] HTTP 200
- [ ] Response `content` is a detailed description (more than a few sentences)
- [ ] Response `content` references concrete visual features of `image.png`: specific subjects, colors, objects, or text
- [ ] Response `content` is NOT a refusal like "I don't see an image" or "I'm unable to view images"

### Verdict

- [ ] Verdict: FAIL

## Result summary

The Bruno run returned HTTP 502 on both attempts. The AscendAgent received the request and successfully routed it to the OpenAI provider (gpt-5.1) with the image attached (image bytes were sent: 5,895,902 bytes read by Bruno). However, OpenAI rejected the request with a 400 `invalid_request_error` because one of the MCP tool function names registered with the agent does not conform to OpenAI's required pattern `^[a-zA-Z0-9_-]+$` — specifically `tools[5].function.name` contains an illegal character. This is an application-level defect in MCP tool name sanitisation, not a missing API key. The OpenAI API key is working (the error is a validation rejection, not an authentication failure). The three Expected assertions requiring HTTP 200, a detailed description, and concrete visual features all fail; only the non-refusal assertion is untestable because the request never reached the model.

Input tokens:

Output tokens:

Start (UTC): 2026-06-17T16:37:08Z

End (UTC): 2026-06-17T16:39:09Z

Duration: 00:02:01

---

## Additional tasks I did

- Inspected AscendAgent container logs (`docker logs ascend-agent`) to identify the root cause of the 502: OpenAI 400 `invalid_request_error` on `tools[5].function.name` not matching `^[a-zA-Z0-9_-]+$`.
- Confirmed that the OpenAI API key is present and valid (the error is a request-validation rejection, not an authentication failure — OpenAI processes the request far enough to validate the tool schema).
- Noted that prior successful runs left chat history for user `frostyImageDescriptionTest` containing an assistant description of the image, confirming the capability worked previously. The defect is a regression in MCP tool name registration.
