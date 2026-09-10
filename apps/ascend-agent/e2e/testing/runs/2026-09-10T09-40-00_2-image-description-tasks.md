# Image description: run tasks template

Spec: [../2-image-description-test.md](../2-image-description-test.md)

Copy this file to `runs/<UTC-timestamp>_2-image-description-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [x] Bruno CLI present (`bru --version` returns a version)
- [x] ascend-ai-agent `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [x] Fixture `apps/ascend-agent/e2e/fixtures/image.png` exists

### Reset state

- [x] Deleted Postgres `chat_history` rows where `user_id = 'frostyImageDescriptionTest'`
- [x] Deleted Redis key `chat:frostyImageDescriptionTest`
- [x] Deleted Redis key `user:frostyImageDescriptionTest:instructions`

### Run

- [x] Send `image-description-prompt.yml` via `bru run` and wait for response

### Expected

- [x] HTTP 200
- [x] Response `content` is a detailed description (more than a few sentences)
- [x] Response `content` references concrete visual features of `image.png`: specific subjects, colors, objects, or text
- [x] Response `content` is NOT a refusal like "I don't see an image" or "I'm unable to view images"

### Post-run cleanup

Run regardless of Run-step verdict. Every command is idempotent.

- [x] Deleted Postgres `chat_history` rows where `user_id = 'frostyImageDescriptionTest'`
- [x] Deleted Redis key `chat:frostyImageDescriptionTest`
- [x] Deleted Redis key `user:frostyImageDescriptionTest:instructions`
- [x] `POST http://localhost:7020/api/v1/memory/wipe?user_id=frostyImageDescriptionTest` returned `{"status":"success", ...}`

### Verdict

- [x] Verdict: PASS

## Result summary

The Bruno request `image-description-prompt.yml` returned HTTP 200 (both invocations). The response body's `content` field is a multi-paragraph, section-headed description (~700 words) that accurately names the image's concrete visual features: spiky blond hair with blue rim lighting, narrowed electric-blue glowing eyes, a dark high-collar jacket with a glowing blue geometric chest emblem, and a warm-lit night-city skyline background — all of which are directly visible in `apps/ascend-agent/e2e/fixtures/image.png`. No refusal language appears anywhere in the response. All three Expected assertions hold: HTTP 200, a detailed description well beyond a few sentences, and concrete-feature grounding with no refusal.

Input tokens: 3544 (OpenAI `gpt-5.1-2025-11-13` call, from the re-run's captured `nativeUsage.prompt_tokens`; the canonical Run-step invocation used an identical request and was not JSON-captured)

Output tokens: 695 (same call, `nativeUsage.completion_tokens`)

Start (UTC): 2026-09-10T07:56:49Z

End (UTC): 2026-09-10T07:58:37Z

Duration: 00:01:48

---

## Additional tasks I did

- Re-ran `bru run "ascend-agent/testing/image-description-prompt.yml" --env ascend-local --output ... --format json` a second time (beyond the spec's single Run invocation) to capture the raw response JSON for direct inspection of the `content` field and `nativeUsage` token counts, rather than trusting only the embedded Bruno test script's pass/fail. Viewed `apps/ascend-agent/e2e/fixtures/image.png` directly and compared it side by side against the returned description. The extra chat-history row pair this second call wrote was removed by the spec's normal Post-run cleanup (`DELETE 4` confirms both pairs were dropped). The temporary JSON output file was written to and then deleted from the scratchpad directory.
