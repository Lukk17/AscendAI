# e2e fixtures

Small canary images used by upload-style OCR tests. Each fixture holds distinctive proper nouns so a passing test
proves the text came from the OCR pipeline rather than memorised knowledge.

## Conventions

- PNG, high contrast (black text on white background).
- Include rare proper nouns the test asserts against by substring (case-insensitive).
- Keep fixtures < 500 KB so upload completes quickly.

## Per-fixture documentation

| File | Used by | Distinctive content |
| :--- | :--- | :--- |
| `argent-saga-chronicles-page1.png` | `2-ocr-english-test.md`, `4-ocr-default-language-test.md`, `6-mcp-ocr-test.md` | Screenshot of page 1 of `apps/ascend-ai-agent/e2e/fixtures/argent-saga-chronicle.pdf`. Tests assert the extracted text contains `Argent Saga`, `Aenaria`, `Halen Veyr` (case-insensitive). |
| `argent-saga-chronicles-page1-polish.png` | `3-ocr-polish-test.md` | Polish translation of page 1, screenshotted from a text editor. Tests assert the extracted text contains `Saga Świetlna`, `Aenaria`, `Eklipsą`, and at least one Polish-specific accented character. |
| `not-an-image.txt` | `12-ocr-unsupported-mime-test.md` | Plain-text file with no image/PDF magic bytes. Proves the magic-byte sniffer (`src/api/mime_sniffer.py`) rejects the upload even when the client lies about `Content-Type`. |

## MCP fixture delivery

Test 6 (the MCP `ocr_process` call) takes a `file_uri` argument rather than a multipart upload or a container-visible
path. It uses no bind mount. The runner uploads the fixture from the host during the spec's Reset state, with a plain
`PUT` against the object store's S3 endpoint on port 9070, into the `e2e-fixtures` bucket under the key
`argent-saga-chronicles-page1.png`. The bucket is created by the same step and is never deleted by the spec.

Test 6's Bruno request then passes `file_uri="http://host.docker.internal:9070/e2e-fixtures/argent-saga-chronicles-page1.png"`.
ascend-ocr's MCP tool follows that URL back out to the host-published object store and pulls the bytes itself over
HTTP, so the fixture never has to be visible on the container filesystem. This requires the ascend-ocr container's
`MCP_ALLOWED_HOSTS` to include `host.docker.internal`, since the MCP SSRF guard blocks RFC1918 destinations by
default (see [ADR-001](../../docs/architecture/decisions/ADR-001-mcp-file-transport-uri-only.md)).

## How to regenerate

To regenerate `argent-saga-chronicles-page1.png`:

1. Open `apps/ascend-ai-agent/e2e/fixtures/argent-saga-chronicle.pdf` in any PDF viewer.
2. Screenshot page 1 at a comfortable zoom level (>= 100 percent). Save as `argent-saga-chronicles-page1.png`.

For the Polish version: the Polish translation lives in the commit message of the fixture-update commit. Paste it
into a text editor, screenshot at the same zoom, save as `argent-saga-chronicles-page1-polish.png`.
