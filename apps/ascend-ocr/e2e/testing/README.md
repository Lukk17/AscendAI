# e2e testing guide

Self-contained walkthroughs that an AI agent (or a human) can execute end-to-end against a live ascend-ocr container.
Each `<N>-<capability>-test.md` spec in this directory drives one OCR capability through its Bruno request, with
explicit prerequisite checks, reset commands, run steps, and expected outcomes. The paired run-record templates live
in the `templates/` subdirectory; executed run records land in `runs/`.

## Format

Every `<N>-<capability>-test.md` file is the **immutable spec** for one test and uses the same fixed template.

1. **What this verifies.** Bullet list of behaviours.
2. **Prerequisites.** Concrete check commands (`curl`, `bru --version`) the runner executes before starting. Each
   command is its own code block; the prose around it states what success looks like.
3. **Reset state.** One command per code block, executed in order, to wipe state so the test is reproducible. Any
   spec that submits a document needs one, because a run leaves a job record under `OCR_JOBS_DIR` and a Markdown
   object in the `ocr-results` bucket. The two commands are in
   [`../README.md`](../README.md) under "Resetting between runs".
4. **Run.** One or more numbered steps. Each step is a single Bruno CLI invocation (or, for MCP tests, a `curl`
   `initialize` handshake, then `ocr/testing/mcp-initialized.yml` sending the `notifications/initialized`
   notification the MCP protocol requires before any other request, then a Bruno `tools/call`). Steps wait for HTTP
   200 before continuing, except the notification, which answers HTTP 202 with no body.
5. **Expected.** Observable-behaviour assertions verified after each step: HTTP status codes, the job record's
   shape and state, the stored Markdown fetched from the object store (asserted substrings, not full strings, because
   PaddleOCR may segment a single rendered line into more than one line of output depending on font spacing). NOT log
   substrings, with the single exception spec 10 carries and "Cross-cutting conventions" below explains.
6. **Fixtures.** Paths to local files the test reads. For OCR tests, the canary images and phone photos under
   [`../fixtures/`](../fixtures/).

Each spec has a matching `<N>-<capability>-tasks.template.md` in the [templates/](templates/) subdirectory: the
**checkbox template** for a run. The runner never edits the spec or the template directly. Before starting a run, it
copies the template from `templates/` into [runs/](runs/) with a timestamped filename, ticks boxes as it progresses,
fills in `Result summary` and `Verdict`, and logs anything done outside the spec under `Additional tasks I did`. See
[runs/README.md](runs/README.md) for the full contract and naming convention.

## Bruno is the source of truth

Every test runs the matching Bruno request file under `docs/api/request/AscendAI/ocr/` via the Bruno CLI. The
canonical single-endpoint demonstrations (`ocr.yml`, `health.yml`, `ready.yml`) live at that top level; every other
variation, including all MCP requests, lives under `testing/`.

```powershell
cd docs/api/request/AscendAI
```

```powershell
bru run "ocr/<request-path>.yml" --env ascend-local
```

The request's saved default rows are what gets sent. To test an alternative payload, edit the disabled rows in the
YAML directly.

Install Bruno CLI once with `npm install -g @usebruno/cli`.

## Execution order

The twenty specs fall into two execution classes. Mixing them in the wrong shape causes false failures from CPU
contention, not from real defects, so the fan-out shape matters as much as the spec content.

**Reject-fast specs (1, 5, 7, 8, 9, 10, 11, 12, 20).** These return before anything is queued: spec 1 covers the
validation refusal and the unsupported-language refusal, spec 5 is a `tools/list` lookup,
spec 7 reads `/ready`, specs 8 to 11 are rejected by the SSRF guard / scheme guard / credentials guard / `file://` jail
before any fetch, spec 12 is rejected by the magic-byte sniffer, spec 20 by the language allowlist. Each finishes in well under 2 seconds except spec 11,
whose jail steps start a throwaway `ascend-ocr-jail` container on `127.0.0.1:7023` with `MCP_FILE_URI_ROOT` set and
remove it again, up to about two minutes. Safe to run all nine in parallel up to the runner cap of 5 concurrent, and the
rest queue and pick up as slots free. Specs 1, 9, 11, 12 and 20 assert an empty job listing, so nothing may be queued or
running when they start.

**Engine-bound specs (2, 3, 4, 6, 13, 14, 15, 16, 17, 18, 19).** Each puts at least one document through the single
OCR worker. They run one at a time with no other runner active anywhere. Specs 15 and 16 each cancel a running
document, which replaces the worker and makes the next spec pay an engine load, so they run after the shorter
engine-bound specs. Specs 14 and 13 both read the twenty five page document to the end, spec 14 with two single pages
after it, so they are the two longest specs in the suite and run last, spec 14 and then spec 13. Every one of them
needs the queue and the bucket reset first.

PaddleOCR inference on this deployment is CPU-only, capped to the container's documented `cpus: 4.0` budget, and the one
worker uses every CPU of that budget for one document at a time. Measured inside the container with the engine's threads capped to the container's CPUs
(image `9c100951f59b`, the third 2026-09-25 amendment to
[ADR-011](../../docs/architecture/decisions/ADR-011-explicit-preprocessing-and-straighten.md)), a dense A4 page of
English prose costs 22.1 seconds in `high` mode, the default, a dense Polish page 25.1 seconds, the slowest page
measured, and the dense English page 22.7 seconds in `normal` mode. The full sweep of 2026-09-25 on image
`7605748a6afa` recorded these processing times: 18.9 seconds for the English canary (spec 2), 24.3 seconds for the
Polish canary (spec 3), 172.1 seconds for the twenty five page document (spec 13), 14.9 seconds for the rotated photo
in `high` mode (spec 17), 41.3 seconds for the crumpled photo straightened in `high` mode (spec 18), and 7.2 seconds
for the same photo in `normal` mode without straightening (spec 19). Specs 17 to 19 keep recording their own figures.
Round trip adds the polling interval on top of the engine time.

Running two engine specs at the same time, or running one beside any other runner on the host, slows every page. No
connection is held any more, so nothing times out at the HTTP layer: what a loaded host does instead is push a page
past its engine's page allowance (112.95 s on the small pair at the default `OCR_PAGE_ALLOWANCE_HEADROOM`), which stops
the whole document with `OCR_FAILED`. Engine specs run one at a time, and each runs alone: no runner of any suite
active while one is in flight, not even a reject-fast spec of this suite. Measured on 2026-09-10 with the English
fixture, against the `PP-OCRv5_server` pair the service ran then: 59.2 seconds on a quiet host, 160.9 seconds on a
loaded one.

Canonical fan-out shape for the full suite from a fresh container:

1. Dispatch all 9 reject-fast specs in parallel (runner default cap of 5, queue 4).
2. Once those settle (4 minutes 35 seconds in the sweep of 2026-09-25, the longest of them being spec 1) and
   `ascend-ocr-jail` is gone, dispatch the 11 engine specs sequentially, one at a time, with nothing else running
   anywhere on the host and every other module's sweep held until the last one returns: 2, 3, 4, 6, 17, 18 and 19
   first, then 15, then 16, then 14, then 13.

The whole 20-spec suite ran as one sweep on 2026-09-25 on image `7605748a6afa` with a 4 GiB memory limit, run prefix
`2026-09-25T21-00-00`, and all 20 specs passed. Measured from the Start and End lines of its run records in
[runs/](runs/): the sweep took 58 minutes 24 seconds of wall-clock, from 18:55:05Z to 19:53:29Z. The reject-fast
phase took 4 minutes 35 seconds and the engine phase 52 minutes 56 seconds. The eleven engine specs' own durations add
up to 40 minutes 58 seconds, and the rest of the engine phase is the resets and dispatch between them. That sweep ran
the engine specs in the order 2, 3, 4, 6, 14, 15, 16, 17, 18, 19, 13, and its spec 14 still submitted three single
pages. Spec 14 now puts the twenty five page document first, which adds about three minutes of reading to it. Spec 13
read its twenty five pages in 172.1 seconds of processing, 177.2 seconds from submission to the terminal state, about
7 seconds a page.

The historical numbering reflects setup cost (lowest first). Run order within each class is free apart from the
engine-bound order above. The only hard constraint is "no two engine specs at the same time."

1. [1-invalid-input-test.md](1-invalid-input-test.md). Validator short-circuit and `lang=korean` refused. **No OCR call.**
2. [2-ocr-english-test.md](2-ocr-english-test.md). English canary, submitted and collected.
3. [3-ocr-polish-test.md](3-ocr-polish-test.md). Polish canary, submitted and collected.
4. [4-ocr-default-language-test.md](4-ocr-default-language-test.md). Default-language fallback.
5. [5-mcp-tools-list-test.md](5-mcp-tools-list-test.md). MCP `tools/list` advertises the four job tools and not the removed one.
6. [6-mcp-ocr-test.md](6-mcp-ocr-test.md). MCP submit, poll and collect via an object-store URL.
7. [7-ready-endpoint-test.md](7-ready-endpoint-test.md). `/ready` returns `status="ready"` post warm-up, with the queue counters.
8. [8-mcp-ssrf-rejection-test.md](8-mcp-ssrf-rejection-test.md). SSRF guard rejects link-local / private-IP targets.
9. [9-mcp-bad-scheme-test.md](9-mcp-bad-scheme-test.md). Scheme guard rejects `ftp://`, `data:` and a bare Windows path.
10. [10-mcp-credentials-rejection-test.md](10-mcp-credentials-rejection-test.md). URI with `user:pass@` rejected.
11. [11-mcp-file-uri-jail-test.md](11-mcp-file-uri-jail-test.md). `file://` rejected while `MCP_FILE_URI_ROOT` is unset, and a `realpath` escape rejected on a throwaway container with the root set.
12. [12-ocr-unsupported-mime-test.md](12-ocr-unsupported-mime-test.md). Magic-byte rejection at submission.
13. [13-long-document-test.md](13-long-document-test.md). Twenty five pages, progress, and the canary on page 24. **One of the two longest specs in the suite, with 14.**
14. [14-job-listing-test.md](14-job-listing-test.md). The listing of work in flight behind the twenty five page document, and what it hands out.
15. [15-cancel-running-job-test.md](15-cancel-running-job-test.md). A cancel stops the worker mid-document, and the worker comes back.
16. [16-queue-full-test.md](16-queue-full-test.md). A submission past the queue's document bound is refused with 503 `QUEUE_FULL` and `Retry-After`.
17. [17-ocr-rotated-photo-test.md](17-ocr-rotated-photo-test.md). A phone photo turned 90 degrees, read upright without straightening.
18. [18-ocr-straighten-crumpled-photo-test.md](18-ocr-straighten-crumpled-photo-test.md). A crumpled page photo read with `straighten=true`, all 21 lines present and at least 15 of 21 canaries found word for word.
19. [19-ocr-crumpled-photo-default-test.md](19-ocr-crumpled-photo-default-test.md). The same photo in `normal` mode, not straightened by default.
20. [20-mcp-unsupported-language-test.md](20-mcp-unsupported-language-test.md). `ocr_submit` refuses `lang` `korean` with `UNSUPPORTED_LANGUAGE` before fetching. **No OCR call.**

## Cross-cutting conventions

Pass criteria are observable behaviour only. HTTP status, the job record's shape and state, the Markdown object the
service left in the bucket, and substring matches inside it. Logs are diagnostic, not authoritative. Log lines drift across
versions and aren't visible from every runner's shell. If a behaviour assertion fails, a tail of the ascend-ocr log
(or `docker logs ascend-ocr`) is the next diagnostic step, but not a pass criterion.

One exception is sanctioned, and only one: spec 10 asserts that `docker logs ascend-ocr --since 1m` contains no
`pass@` after a URI with credentials is refused. That a credential never reaches the logs is a security property
with no other observable, since no response, record or stored object can show what the service wrote to its log. The
assertion is negative, so it does not break when log wording changes, which is what the rule guards against. A new
spec may not add a log assertion on the strength of this one: a further exception has to meet the same test (a
security property, no other observable, a negative assertion) and be listed here beside it.

OCR extraction is a fuzzy match against the canary substring (case-insensitive, substring of the concatenated
extracted text). The fixtures are large, single-line, high-contrast images precisely so the assertion does not
flake on engine drift; if a fixture's canary substring stops being reliably extracted, regenerate the fixture with
a larger font rather than weakening the assertion. The straightening photos used by specs 17 to 19 are real phone
photos and cannot be regenerated. Their canaries already avoid the three characters the engine is known to get wrong
on that page (the Spanish inverted exclamation mark, and the Polish `ź` and `ż`), so a missing canary is a finding
about the service, never a reason to drop the canary.

## Adding a new test

1. Add a Bruno request under `docs/api/request/AscendAI/ocr/testing/<request>.yml`.
2. Create `apps/ascend-ocr/e2e/testing/<N>-<capability>-test.md` using the template above. Pick the lowest unused number
   prefix that matches its setup-cost position in the order.
3. Create `apps/ascend-ocr/e2e/testing/templates/<N>-<capability>-tasks.template.md` mirroring the spec's checkboxes.
4. If the test needs a new canary fixture, add a row to [`../fixtures/README.md`](../fixtures/README.md) with the
   distinctive content and a one-line Pillow generation recipe.
5. Add the file to the ordered list in this README and in the capability table in the parent
   [../README.md](../README.md).
