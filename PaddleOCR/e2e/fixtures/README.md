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
| `argent-saga-chronicles-page1.png` | `2-ocr-english-test.md`, `4-ocr-default-language-test.md`, `6-mcp-ocr-test.md` | Screenshot of page 1 of `AscendAgent/e2e/fixtures/argent-saga-chronicle.pdf`. Tests assert the extracted text contains `Argent Saga`, `Aenaria`, `Halen Veyr` (case-insensitive). |
| `argent-saga-chronicles-page1-polish.png` | `3-ocr-polish-test.md` | Polish translation of page 1, screenshotted from a text editor. Tests assert the extracted text contains `Saga Swietlna` / `Saga Swietlna`, `Aenaria`, and at least one Polish-specific accented character. |

## MCP fixture mount

Test 6 (the MCP `ocr_process` call) takes a server-side `file_path` rather than a multipart upload. The fixture must
be visible inside the PaddleOCR container. Document the mount in a `docker-compose.override.yaml` that bind-mounts
`./PaddleOCR/e2e/fixtures` to `/e2e-fixtures:ro` (do NOT edit the committed `docker-compose.yaml`); test 6's Bruno
request references `/e2e-fixtures/argent-saga-chronicles-page1.png`.

## How to regenerate

To regenerate `argent-saga-chronicles-page1.png`:

1. Open `AscendAgent/e2e/fixtures/argent-saga-chronicle.pdf` in any PDF viewer.
2. Screenshot page 1 at a comfortable zoom level (>= 100 percent). Save as `argent-saga-chronicles-page1.png`.

For the Polish version: the Polish translation lives in the commit message of the fixture-update commit. Paste it
into a text editor, screenshot at the same zoom, save as `argent-saga-chronicles-page1-polish.png`.
