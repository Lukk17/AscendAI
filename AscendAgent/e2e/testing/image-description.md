### Image Description — End-to-End Test

---

Verifies that an attached image is sent to a vision-capable model and the response is grounded in the actual image content (not a hallucinated description).

### Pre-flight

---

Bash:

```bash
curl http://localhost:9917/
```

PowerShell:

```powershell
curl.exe http://localhost:9917/
```

The fixture lives at `AscendAgent/e2e/fixtures/image.png`. Pick something with one obvious correct answer (a banana on a plain background, a known logo, a chart with a unique title). The chat provider must be vision-capable: `anthropic` (claude-sonnet-4-6, claude-opus-4-6), `openai` (gpt-4o, gpt-5.x), or `gemini` (gemini-3.1-pro, gemini-2.5-pro). LM Studio depends on the loaded model and is usually text-only.

### Test — prompt with attached image

---

**Bruno request:** `docs/api/request/AscendAI/ascend-agent/testing/image-description-prompt.yml`

**Bruno CLI** (Bash):

```bash
bru run docs/api/request/AscendAI/ascend-agent/testing/image-description-prompt.yml --env ascend-local
```

**Bruno CLI** (PowerShell):

```powershell
bru run docs/api/request/AscendAI/ascend-agent/testing/image-description-prompt.yml --env ascend-local
```

**Equivalent curl** (Bash):

```bash
curl -X POST http://localhost:9917/api/v1/ai/prompt -H "X-User-Id: imgtest-001" -F "prompt=Describe what you see in this image in one sentence." -F "image=@AscendAgent/e2e/fixtures/image.png" -F "provider=anthropic" -F "model=claude-sonnet-4-6"
```

**Equivalent curl** (PowerShell):

```powershell
curl.exe -X POST http://localhost:9917/api/v1/ai/prompt -H "X-User-Id: imgtest-001" -F "prompt=Describe what you see in this image in one sentence." -F "image=@AscendAgent/e2e/fixtures/image.png" -F "provider=anthropic" -F "model=claude-sonnet-4-6"
```

### Pass criteria

---

- ✅ HTTP 200; the `content` field accurately describes the image (the right object, scene, or text).
- ✅ AscendAgent log shows `HasImage: true` for this request.
- ⚠️ Sanity check — repeat with a clearly different image. If the two prompts produce similar generic answers, the image isn't reaching the model. Look for "data URL too short" warnings or `InvalidMimeTypeException` traces in the agent log.
