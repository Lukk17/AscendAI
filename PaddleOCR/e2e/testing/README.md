# e2e testing guide

Self-contained walkthroughs that an AI agent (or a human) can execute end-to-end against a live PaddleOCR container.
Each `<N>-<capability>-test.md` spec in this directory drives one OCR capability through its Bruno request, with
explicit prerequisite checks, reset commands, run steps, and expected outcomes. The paired run-record templates live
in the `templates/` subdirectory; executed run records land in `runs/`.

## Format

Every `<N>-<capability>-test.md` file is the **immutable spec** for one test and uses the same fixed template.

1. **What this verifies.** Bullet list of behaviours.
2. **Prerequisites.** Concrete check commands (`curl`, `bru --version`) the runner executes before starting. Each
   command is its own code block; the prose around it states what success looks like.
3. **Reset state.** One command per code block, executed in order, to wipe state so the test is reproducible. Most
   PaddleOCR tests do not need reset (OCR is stateless and the engine cache is warmed at startup).
4. **Run.** One or more numbered steps. Each step is a single Bruno CLI invocation (or, for MCP tests, a `curl`
   `initialize` handshake followed by a Bruno `tools/call`). Steps wait for HTTP 200 before continuing.
5. **Expected.** Observable-behaviour assertions verified after each step: HTTP status codes, response JSON shape,
   the echoed `language` value, the concatenated `pages[*].lines[*].text` content (asserted substrings, not full
   strings — PaddleOCR may segment a single rendered line into multiple `OcrTextLine` entries depending on font
   spacing). NOT log substrings.
6. **Fixtures.** Paths to local files the test reads — for OCR tests, the canary PNGs under
   [`../fixtures/`](../fixtures/).

Each spec has a matching `<N>-<capability>-tasks.template.md` in the [templates/](templates/) subdirectory — the
**checkbox template** for a run. The runner never edits the spec or the template directly. Before starting a run, it
copies the template from `templates/` into [runs/](runs/) with a timestamped filename, ticks boxes as it progresses,
fills in `Result summary` and `Verdict`, and logs anything done outside the spec under `Additional tasks I did`. See
[runs/README.md](runs/README.md) for the full contract and naming convention.

## Bruno is the source of truth

Every test runs the matching Bruno request file under `docs/api/request/AscendAI/paddle-ocr/testing/` via the Bruno
CLI.

```powershell
cd docs/api/request/AscendAI
```

```powershell
bru run "paddle-ocr/testing/<request>.yml" --env ascend-local
```

The request's saved default rows are what gets sent. To test an alternative payload, edit the disabled rows in the
YAML directly.

Install Bruno CLI once with `npm install -g @usebruno/cli`.

## Execution order

The twelve specs fall into two execution classes. Mixing them in the wrong shape causes false failures from CPU
contention, not from real defects, so the fan-out shape matters as much as the spec content.

**Reject-fast specs (1, 5, 7, 8, 9, 10, 11, 12).** These return before any `engine.predict` call:
spec 1 short-circuits at FastAPI validation, spec 5 is a `tools/list` lookup, spec 7 reads `/ready`, specs 8 to
11 are rejected by the SSRF guard / scheme guard / credentials guard / `file://` jail before any fetch, spec 12 is
rejected by the magic-byte sniffer. Each finishes in well under 2 seconds. Safe to run all eight in parallel up to
the runner cap of 5 concurrent; the rest queue and pick up as slots free.

**Engine-bound specs (2, 3, 4, 6).** These all invoke PaddleOCR's blocking `engine.predict` inside
`asyncio.to_thread`. PaddleOCR inference is CPU-bound; on WSL2 / Docker Desktop with the documented `cpus: 4.0`
budget, a single 212 KB image takes 5 to 15 seconds. Running two engine specs at the same time saturates every
core, throughput per call drops 4 to 8 times, and `asyncio.wait_for` exhausts `OCR_REQUEST_TIMEOUT=300` before any
of them returns: the entire engine batch fails with `HTTP 500 INTERNAL_ERROR` or, in the MCP case, with
`result.isError=true`. **Engine specs run one at a time.** It is fine to interleave them with reject-fast specs.

Canonical fan-out shape for the full suite from a fresh container:

1. Dispatch all 8 reject-fast specs in parallel (runner default cap of 5; queue 3).
2. Once those settle (usually under 90 seconds in aggregate), dispatch the 4 engine specs **sequentially**, one at
   a time. Each will take 30 to 90 seconds against the documented hardware budget.

Total wall-clock with this shape on a 4-vCPU, 12 GB WSL2 container: roughly 5 to 8 minutes for 12 specs.

The historical numbering reflects setup cost (lowest first). Run order within each class is free; the only hard
constraint is "no two engine specs at the same time."

1. [1-invalid-input-test.md](1-invalid-input-test.md). Validator short-circuit. **No fixture, no OCR call.**
2. [2-ocr-english-test.md](2-ocr-english-test.md). English canary OCR.
3. [3-ocr-polish-test.md](3-ocr-polish-test.md). Polish canary OCR.
4. [4-ocr-default-language-test.md](4-ocr-default-language-test.md). Default-language fallback.
5. [5-mcp-tools-list-test.md](5-mcp-tools-list-test.md). MCP `tools/list` advertises `ocr_process`.
6. [6-mcp-ocr-test.md](6-mcp-ocr-test.md). MCP `ocr_process` happy path via MinIO URL.
7. [7-ready-endpoint-test.md](7-ready-endpoint-test.md). `/ready` returns `status="ready"` post warm-up.
8. [8-mcp-ssrf-rejection-test.md](8-mcp-ssrf-rejection-test.md). SSRF guard rejects link-local / private-IP targets.
9. [9-mcp-bad-scheme-test.md](9-mcp-bad-scheme-test.md). Scheme guard rejects `ftp://`, `data:`, etc.
10. [10-mcp-credentials-rejection-test.md](10-mcp-credentials-rejection-test.md). URI with `user:pass@` rejected.
11. [11-mcp-file-uri-jail-test.md](11-mcp-file-uri-jail-test.md). `file://` rejected unless `MCP_FILE_URI_ROOT` set + jailed.
12. [12-ocr-unsupported-mime-test.md](12-ocr-unsupported-mime-test.md). Magic-byte rejection on REST upload.

## Cross-cutting conventions

Pass criteria are observable behaviour only. HTTP status, response body content, the echoed `language`, the
concatenated extracted-text substring matches. Logs are diagnostic, not authoritative. Log lines drift across
versions and aren't visible from every runner's shell. If a behaviour assertion fails, a tail of the PaddleOCR log
(or `docker logs paddle-ocr`) is the next diagnostic step, but not a pass criterion.

OCR extraction is a fuzzy match against the canary substring (case-insensitive, substring of the concatenated
extracted text). The fixtures are large, single-line, high-contrast images precisely so the assertion does not
flake on engine drift; if a fixture's canary substring stops being reliably extracted, regenerate the fixture with
a larger font rather than weakening the assertion.

## Adding a new test

1. Add a Bruno request under `docs/api/request/AscendAI/paddle-ocr/testing/<request>.yml`.
2. Create `PaddleOCR/e2e/testing/<N>-<capability>-test.md` using the template above. Pick the lowest unused number
   prefix that matches its setup-cost position in the order.
3. Create `PaddleOCR/e2e/testing/templates/<N>-<capability>-tasks.template.md` mirroring the spec's checkboxes.
4. If the test needs a new canary fixture, add a row to [`../fixtures/README.md`](../fixtures/README.md) with the
   distinctive content and a one-line Pillow generation recipe.
5. Add the file to the ordered list in this README and in the capability table in the parent
   [../README.md](../README.md).
