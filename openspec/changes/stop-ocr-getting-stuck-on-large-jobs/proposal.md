## Why

The OCR service wedges on a large job and then lies about it. All three parts of that were measured against the
running stack, not inferred.

A twenty page document was submitted and failed at 300 seconds, the value of `OCR_REQUEST_TIMEOUT` in
[docker-compose.yaml](../../../docker-compose.yaml). The caller got an error. The worker did not stop. It kept
running for a further thirty minutes at two to four cores, producing an answer no one was waiting for, and it was
still running when the observation ended. Throughout all of that `/ready` answered 200 with `status: "ready"`,
while the only worker the service has was permanently occupied.

Three separate faults produced that:

1. The timeout wraps the whole document. `asyncio.wait_for(loop.run_in_executor(...), timeout=OCR_REQUEST_TIMEOUT)`
   in both [rest_endpoints.py](../../../PaddleOCR/src/api/rest/rest_endpoints.py) and
   [mcp_server.py](../../../PaddleOCR/src/api/mcp/mcp_server.py) is one budget for every page. Any multi-page
   document whose total cost passes five minutes fails no matter how healthy the service is.
2. `asyncio.wait_for` cancels the coroutine that is waiting. It cannot touch work already running inside a
   `ProcessPoolExecutor`, so the timeout abandons the job rather than stopping it.
3. `_WORKER_POOL_SIZE = 1` in [ocr_service.py](../../../PaddleOCR/src/service/ocr_service.py), so the abandoned job
   holds the only worker and every request behind it waits for work that has already been given up on.

A fourth measured fact is unrelated to the timeout and needs its own guard. The service was OOM-killed once at
12 GiB while reading a 4.35 megapixel raw image. Nothing in the request path looks at pixels: the only size guard is
`MAX_FILE_SIZE_MB`, a 50 MB byte count, and bytes are not pixels, since a 40 KB PNG can declare 100 megapixels.
Documents are protected by accident rather than by design. PaddleOCR rasterizes every PDF page at a fixed zoom of
2.0, which is 144 dpi (`PDF_RENDER_SCALE` in `paddlex/utils/flags.py`, applied by `PDFReader` in
`paddlex/inference/common/batch_sampler/image_batch_sampler.py`, both read from the module's own `.venv`). An A4
page therefore reaches the engine at 1190x1684, 2.0 megapixels, whatever resolution the caller scanned it at. Raw
images skip that path entirely and arrive at whatever size they are.

This change supersedes `add-ocr-full-resolution-reading`, which is deleted in the same commit. That change was built
on an unverified claim that inference costs roughly 5 GiB per megapixel, which puts an ordinary A4 page at 44 GiB
and is contradicted by the service serving such pages every day. Its central proposal, cutting a page into
overlapping pieces, solved a memory problem documents do not have, because the library never reads a document at
the resolution it was sent. Its reasoning about a pixel ceiling on raw image input is correct and is carried
forward here.

## What Changes

Deadlines that mean something, and a stop that actually stops:

- Replace the single whole-document budget with a per-page allowance plus an absolute request ceiling. The
  effective budget for a job is the smaller of the two, so a healthy multi-page document is no longer failed for
  being long, and a thousand page document still cannot run forever.
- Give the worker a cooperative deadline it enforces itself. The parent passes a remaining duration, never a wall
  clock time, because `time.monotonic()` is not comparable across processes. The worker switches from
  `engine.predict()` to the library's own `predict_iter()` and checks its deadline before consuming each page, so
  it stops itself instead of being abandoned.
- Reclaim a worker that does not stop. A single page's inference cannot be interrupted from outside, so when the
  worker fails to return within a grace period after its own budget expired, the parent replaces the worker
  process. Costed and bounded in [design.md](design.md), and rare by construction because the cooperative deadline
  normally fires first.
- Make the queue explicit. Requests wait on an admission gate in the parent whose permit count is the worker count,
  rather than piling up invisibly inside the process pool. A request that runs out of budget while waiting fails
  there and is never dispatched, so no inference is ever started for a caller who has already been told the request
  failed.
- Make the single worker cap a named, tested constraint rather than a private module constant. The gate permits and
  the pool size come from one setting, so they cannot drift, and the memory argument that rests on it is written
  down.

Readiness that tells the truth:

- `/health` is unchanged. It stays liveness of the API process and the Docker healthcheck stays pointed at it. A
  wedged worker must not restart the container, because a restart destroys the warm engine and every queued
  request to fix something a worker replacement fixes on its own.
- `/ready` reports `not-ready` when the service cannot take work: the engine never warmed, the pool is broken, the
  worker is being replaced, or the in-flight job is past its budget and has not yet been reclaimed. Being merely
  busy with an in-budget job stays `ready`, because a queued request will be served.
- The readiness body gains `accepting_work` and `queue_depth` so an operator can tell busy from stuck. Additive,
  and the endpoint keeps answering 200 in both states as ADR-004 specifies.

A pixel ceiling on the image path:

- Refuse any input whose pixel count for one inference exceeds a configured ceiling, using the existing
  `FILE_TOO_LARGE` code and its 400. No new error code. For a raw image that count is its decoded size, read from
  the header before any pixel is allocated. For a PDF it is the page size rendered at the library's fixed 144 dpi,
  computable from the same header read.
- Set Pillow's `Image.MAX_IMAGE_PIXELS` to the same ceiling so a decompression bomb is rejected while the header is
  being read rather than after 300 MB has been allocated.
- Refuse a document whose page count multiplied by the per-page allowance exceeds the request ceiling, same error
  code, before any work starts. Accepting a job that provably cannot finish wastes the only worker the service has.

The memory question, as a task rather than a decided fix:

- A call costs about 10 GiB and no one knows why. A small image costs 3 GiB, a twenty page document climbs to
  10 GiB over six minutes and then plateaus, and the container limit is 12 GiB. The shape of that curve, climbing
  and then flattening, is consistent with the allocator holding memory it has finished with, but that is untested.
- The change carries the investigation as a task with a stated decision rule, not a fix. A separate investigation
  is running now and will produce the measurement. If peak memory is flat across page count, the ceiling is one
  job's cost and the single worker cap is the whole safety story. If it rises with page count, the fix is chosen
  then, and the worker replacement mechanism this change already builds is the obvious lever.
- All five models in the pipeline stay. The owner has decided correctness beats memory on a service that reads
  documents, so cutting models is not on the table and is not proposed.

A decision recorded:

- The fixed 144 dpi rasterization is a real constraint with a real trade and it is currently neither documented nor
  exposed. It is what bounds memory for every document, and it also means a dense scan cannot be read at higher
  quality even when the caller wants that, with no way to ask. The decision, its trade and its rejected
  alternatives are written in [design.md](design.md) Decision 7, and a task lands them as an ADR under
  `PaddleOCR/docs/architecture/decisions/` in the existing format. No configuration knob is built for it, because
  that is a future need.

Nothing here is BREAKING. Every response field is additive, no error code changes meaning, and the only behaviour a
current caller loses is the ability to submit work that cannot succeed.

## Capabilities

### New Capabilities

- `ocr-request-deadlines`: How long a request may run, how that budget is divided across the pages of a document,
  how the worker stops itself, what happens when it does not, how requests queue behind the single worker, and the
  worker cap the memory argument depends on.
- `ocr-service-readiness`: What `/health` and `/ready` each promise, and specifically when the service reports that
  it cannot take work.
- `ocr-input-limits`: The pixel ceiling on one inference for both input types, the decode-time decompression bomb
  guard, the page count refusal, and the error code all three use.

### Modified Capabilities

None. No capability under `openspec/specs/` covers the PaddleOCR module today, so all three stand on their own.

## Impact

Code, all under `PaddleOCR/`:

- `src/service/ocr_service.py`: `process_file` iterates pages through `predict_iter()` and checks a cooperative
  deadline between them. `run_ocr_in_worker` carries the remaining budget as a duration. The pool gains a
  replacement path and the worker count moves to configuration.
- `src/api/rest/rest_endpoints.py` and `src/api/mcp/mcp_server.py`: both surfaces move from a bare `wait_for` to
  the shared admission gate, and both apply the pixel and page count guards at the boundary before the worker is
  touched.
- `src/api/limits.py`: new. Header-only size inspection for images and PDFs, shared by both surfaces, next to the
  existing `sniff_mime`. Pure enough to test to the project's coverage gate without loading a model.
- `src/main.py` and `src/model/ocr_models.py`: `ReadinessResponse` gains `accepting_work` and `queue_depth`, and
  `readiness_check` reads the new signal.
- `src/config/config.py`: new settings for the per-page allowance, the worker count, the pixel ceiling, the page
  count limit, the reclamation grace and the dispatch margin. Every default is derived in
  [design.md](design.md), and every one that depends on the running measurement is marked provisional there
  against the task that confirms it.
- `src/observability/metrics.py`: queue depth, queue wait, per-page duration, deadline stops and worker
  replacements.

Tests, all under `PaddleOCR/tests/`. The gate is `--cov-fail-under=100` with `--cov-branch`, so every branch added
needs a test. Detail in [tasks.md](tasks.md).

Dependencies: `pypdfium2` is already installed as a transitive dependency of paddlex and becomes a declared direct
dependency of this module, because reading a PDF header is now this module's own behaviour and must not rest on
someone else's dependency tree. Pillow 12.2.0 is already declared and currently unused by `src/`. No new install.

API: additive on both surfaces. No request parameter is added. A caller who submits work the service will not
accept now gets a 400 with `FILE_TOO_LARGE` and a message naming the measurement and the limit, in place of a
timeout, an OOM kill or a thirty minute orphan.

Operational: `OCR_REQUEST_TIMEOUT` in `docker-compose.yaml` is 300 today and that value is what turned a healthy
twenty page job into an error. It is re-derived from the measured per-page time in task 1.2, together with the page
count limit it implies, and the pair is an owner decision because it trades how large a document the service
accepts against how long a caller must hold a connection.

Docs: the environment variable list in `PaddleOCR/AGENTS.md`, `PaddleOCR/README.md`, the arc42 pages under
`PaddleOCR/docs/architecture/arc42/`, an amendment to ADR-004 for the readiness condition, and a new ADR for the
fixed rendering resolution. All written when the change is applied.

Superseded: `openspec/changes/add-ocr-full-resolution-reading/` is deleted. Its pixel ceiling reasoning survives
here. Its piece cutting, joining, duplicate removal, reading order and `high_res` parameter do not, because the
premise they rested on was wrong.

## Relevant Skills

Load before implementing:

- `/python-patterns`, `/python-testing`, `/tdd-workflow`
- `/api-design`, `/docker-patterns`, `/deployment-patterns`
- `/security-review` for the decompression bomb guard and the header parsing
- `/coding-standards`, `/code-reviewer`
- `/architecture-decision-records` for the ADR in task 8.4
