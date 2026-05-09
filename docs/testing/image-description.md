### Image Description — End-to-End Test

Verifies that an attached image is sent to a vision-capable model and the model responds based on its actual content.

#### Pre-flight

```bash
curl http://localhost:9917/   # AscendAgent
```

Use a recognisable image — a photo of a banana, a screenshot of a known UI, a chart with a legible title. Whatever you use, you should know the correct answer beforehand so you can tell hallucinations from genuine vision.

The chat provider must be vision-capable. Known good: `anthropic` (claude-sonnet-4-6, claude-opus-4-6), `openai` (gpt-4o, gpt-5.x), `gemini` (gemini-3.1-pro, gemini-2.5-pro). LM Studio depends on the loaded model and is usually text-only.

#### Test — Prompt with attached image

```bash
curl -X POST http://localhost:9917/api/v1/ai/prompt \
  -H "X-User-Id: imgtest-001" \
  -F "prompt=Describe what you see in this image in one sentence." \
  -F "image=@/path/to/photo.jpg" \
  -F "provider=anthropic" -F "model=claude-sonnet-4-6"
```

**Pass:**
- HTTP 200; response `content` accurately describes the image (object, colour, scene — whatever fits).
- AscendAgent log shows `HasImage: true` for the request.
- Try an obviously different image as a sanity check; if both prompts produce similar generic answers, the image isn't reaching the model.
