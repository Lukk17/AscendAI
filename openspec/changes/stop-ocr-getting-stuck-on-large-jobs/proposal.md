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
Documents are bounded by accident rather than by design, and the bound is not low enough to protect them: it holds
an A4 page to 2.0 megapixels, which the fifth fact below prices at 11.0 GiB. PaddleOCR rasterizes every PDF page at
a fixed zoom of 2.0, which is 144 dpi (`PDF_RENDER_SCALE` in `paddlex/utils/flags.py`, applied by `PDFReader` in
`paddlex/inference/common/batch_sampler/image_batch_sampler.py`, both read from the module's own `.venv`). An A4
page therefore reaches the engine at 1190x1684, 2.0 megapixels, whatever resolution the caller scanned it at. Raw
images skip that path entirely and arrive at whatever size they are.

A fifth fact was measured after this change was first written, and it is the one that decides what has to be built.
Peak memory for one call fits `peak_MiB = 635 + 5302 x megapixels_of_one_page + 11.5 x pages`, correlation 0.9993
across six input sizes. So a page costs about 5.3 GiB per megapixel of transient, a page of a document costs only
the 11.5 MiB its result retains, and the peak is set by the largest single page rather than by the length of the
document. An A4 page at the library's fixed 144 dpi is 2.004 megapixels, which prices at 11.0 GiB against a 12 GiB
container limit, and a worker that has served all eight cached languages is carrying 1.6 GiB before it starts.
One ordinary page is therefore already over the limit on a warm worker. Text detection is 94 percent of that
transient, and it is 94 percent for a configuration reason rather than a model reason: detection is configured with
a minimum-side limit, which only ever scales an image up, so every real page reaches a detector exported for a long
side of 960 at its full rendered resolution.

A sixth: when the sole worker is killed, `ProcessPoolExecutor` marks the pool permanently broken and nothing
respawns it. Verified live: every request returned 500 instantly, no worker process existed, and the container sat
in that state for about five hours while both `/health` and `/ready` reported healthy. Restarting the container was
the only recovery. A seventh follows from it: the killed process never runs its cleanup, so each kill leaks the
uploaded document in the container's temporary directory, up to the 50 MB limit.

Two corrections to the account above. The twenty page job's kill did not come from the container limit, which was
never reached: its recorded peak was 10,929 MiB against 12,288, and the host virtual machine, sixteen gigabytes
running twenty eight containers, exhausted its swap. And the memory cost is no longer unexplained, so the sentence
in this proposal's first draft that called it unknown has been replaced by the model above.

This change supersedes `add-ocr-full-resolution-reading`, which is deleted in the same commit. That change had the
cost law right and the remedy wrong, which is worth stating precisely now that the law is measured. Its claim of
roughly 5 GiB per megapixel is confirmed at 5.3 GiB per megapixel. What was wrong was the resolution it applied
that law at: it costed the page at the resolution the caller scanned it, giving 44 GiB, where the library renders
every page at a fixed 144 dpi and the real figure for A4 is 11.0 GiB. That is not comfortable either, which is the
second correction to its dismissal, since 11.0 GiB against a 12 GiB limit is not a service serving those pages
comfortably every day, it is the incident. Its remedy, cutting a page into overlapping pieces and reassembling the
result, is still rejected: two constructor arguments reach a smaller detector input with no joining, no duplicate
removal and no reading-order reconstruction to own. Its reasoning about a pixel ceiling on raw image input is
correct and is carried forward here.

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
  down. Today nothing says the cap is about memory: the code justifies the separate process by the interpreter
  lock, and the architecture pages describe the single worker as a throughput limit, so someone could raise it for
  throughput and double a ceiling that one unbounded A4 page already fills to 92 percent.

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

A bound on what the detector sees, which is the fix the measurement points at:

- Make the detector's input size configurable and bound it, using `text_det_limit_type` and
  `text_det_limit_side_len` on the `PaddleOCR(...)` call the service already makes. Two arguments. Measured at
  0.901 megapixels, a 960 long-side bound cut peak from 5358 to 4242 MiB, and accuracy went from 29 of 29 lines to
  28 of 29 with mean confidence moving from 0.9869 to 0.9834. Applied to A4 the effect is far larger because the
  downscale is larger: about 4.1 GiB at 960, 6.8 GiB at 1280 and 9.2 GiB at 1536, against 11.0 GiB unbounded.
- The change itself does not pick the deployed value; that is left to task 1.5. This is an accuracy trade against
  small text, which is what the owner cares about, so the three candidates and their costs are stated and choosing
  between them is a task that requires measuring against his own documents. Said plainly: a lower bound reads less
  small text, in the sense that small lines stop being detected at all rather than being detected and misread.
  **Resolved**: the owner measured 960, 1280 and 1536 against five real documents and chose 1536 as near lossless —
  see [ADR-006](../../../PaddleOCR/docs/architecture/decisions/ADR-006-detector-input-bound.md) for the full table.
- The bound and the pixel ceiling are one decision in two settings. **Resolved**: they ship together as
  `OCR_DETECTOR_MAX_SIDE=1536` and `OCR_MAX_INFERENCE_PIXELS=2,500,000`, so an image deployed with its shipped
  defaults accepts A4 rather than refusing it. The paragraph below and the migration plan in `design.md` describe
  the state before this resolution, kept for the reasoning it carries about why an unresolved pair is not neutral.
- This is the only guard here that bounds memory for arbitrary caller input while still serving it. The caller
  controls the pixel count and nothing else does. The pixel ceiling bounds memory by refusing, the worker cap
  bounds how many such costs run at once, and neither reduces what one page costs.

A service that comes back on its own:

- Rebuild the worker pool when it is found broken, instead of answering 500 until someone restarts the container.
  It is the same rebuild path the change already builds for a worker that will not stop, with a second trigger.
- A request that arrives during a rebuild waits on the admission gate holding its own budget, exactly as it would
  behind a long job, and is dispatched with what is left or fails at the gate without being dispatched. The request
  that was in flight when the worker died is not retried, because a retry would feed the worker the input that just
  killed it.
- Rebuilding is bounded so a crash loop cannot hide inside it: one rebuild in flight at a time, a cap on
  consecutive failures past which the service stays not-ready rather than respawning forever, a counter reset by
  the first successful job, and one log line and one metric per rebuild.
- Reclaim the scratch file a killed worker leaves behind. Every fresh worker, including every rebuilt one, sweeps
  the service's scratch directory of anything older than one request's ceiling.

The memory question, now answered:

- Peak is flat across page count, so the ceiling is one job's cost and the single worker cap is the whole
  concurrency story. That was the reassuring branch of the decision rule this change carried, and it turned out not
  to be reassuring, because one job's cost is itself most of the container limit. The fix is per-inference input
  size, which is the detector bound above.
- The measurements that rule things out are recorded with their numbers so nobody retries them: thread count makes
  no difference to peak, Paddle's memory optimisation is already on, returning allocator memory recovers about two
  percent, recycling the worker after each job costs five to seven seconds and cannot help because the peak is a
  transient inside one call, and cutting models saves 170 MiB of a 3.2 GiB peak.
- All five models in the pipeline stay, and that is now settled rather than merely asserted. The owner has decided
  correctness beats memory on a service that reads documents, and at 170 MiB of a 3.2 GiB peak the decision is
  nearly free.

A decision recorded:

- The fixed 144 dpi rasterization is a real constraint with a real trade and it is currently neither documented nor
  exposed. It is what bounds memory for every document, and it also means a dense scan cannot be read at higher
  quality even when the caller wants that, with no way to ask. The decision, its trade and its rejected
  alternatives are written in [design.md](design.md) Decision 10, and a task lands them as an ADR under
  `PaddleOCR/docs/architecture/decisions/` in the existing format. No configuration knob is built for it, because
  that is a future need. The measurement reopened its one deferred question, whether to raise the rendering scale,
  and Decision 10 now answers it with numbers and still says no.
- The detector's input bound is the second decision worth recording, and it is the one with an accuracy trade
  attached, so it gets its own ADR alongside the rendering one: what the bound buys in memory, what it costs in
  detected lines, and why the deployed value is measured against real documents rather than defaulted.

No contract here is BREAKING. Every response field is additive and no error code changes meaning. The behaviour a
caller sees does change in one way worth naming rather than burying: with the shipped defaults, input above the
pixel ceiling is refused. With the resolved detector bound and pixel ceiling pair (1536 / 2,500,000) that ceiling
covers A4 and the other standard page sizes, so this is not the loss of function it would have been had the pair
shipped unresolved — see the two paragraphs above. What remains true regardless of the pair chosen: a caller
submitting a genuinely oversized page gets a fast, named refusal in exchange for never again holding a connection
open against a service that has killed itself reading it.

## Capabilities

### New Capabilities

- `ocr-request-deadlines`: How long a request may run, how that budget is divided across the pages of a document,
  how the worker stops itself, what happens when it does not, how requests queue behind the single worker, and the
  worker cap the memory argument depends on.
- `ocr-service-readiness`: What `/health` and `/ready` each promise, and specifically when the service reports that
  it cannot take work.
- `ocr-input-limits`: The pixel ceiling on one inference for both input types, the decode-time decompression bomb
  guard, the page count refusal, and the error code all three use.
- `ocr-memory-bounds`: What one inference is allowed to cost. The configurable bound on the detector's input, the
  accuracy trade it makes, and the memory model the worker cap and the pixel ceiling are both derived from.

### Modified Capabilities

None. No capability under `openspec/specs/` covers the PaddleOCR module today, so all four stand on their own.

## Impact

Code, all under `PaddleOCR/`:

- `src/service/ocr_service.py`: `process_file` iterates pages through `predict_iter()` and checks a cooperative
  deadline between them. `run_ocr_in_worker` carries the remaining budget as a duration. The pool gains a
  replacement path, reached both by reclamation and by finding the pool broken, and the worker count moves to
  configuration. `_get_engine` passes the detector bound to the `PaddleOCR(...)` constructor, so the cache key
  stays the language and the bound is fixed for the process's lifetime. The temporary file moves to the service's
  own scratch directory, and the pool initializer sweeps that directory of anything a dead worker left.
- `src/api/rest/rest_endpoints.py` and `src/api/mcp/mcp_server.py`: both surfaces move from a bare `wait_for` to
  the shared admission gate, and both apply the pixel and page count guards at the boundary before the worker is
  touched.
- `src/api/limits.py`: new. Header-only size inspection for images and PDFs, shared by both surfaces, next to the
  existing `sniff_mime`. Pure enough to test to the project's coverage gate without loading a model.
- `src/main.py` and `src/model/ocr_models.py`: `ReadinessResponse` gains `accepting_work` and `queue_depth`, and
  `readiness_check` reads the new signal.
- `src/config/config.py`: new settings for the per-page allowance, the worker count, the pixel ceiling, the
  dispatch margin, the detector long-side bound, the scratch directory and the consecutive pool rebuild cap. The
  page count limit and the reclamation grace are derived properties rather than settings. Every default is derived
  in [design.md](design.md), and the two that are owner trades rather than derivations, the detector bound and the
  pixel ceiling that goes with it, ship as today's behaviour until the task that decides them reports.
- `src/observability/metrics.py`: queue depth, queue wait, per-page duration, deadline stops, worker replacements
  and pool rebuilds.

Tests, all under `PaddleOCR/tests/`. The gate is `--cov-fail-under=100` with `--cov-branch`, so every branch added
needs a test. Detail in [tasks.md](tasks.md).

Dependencies: `pypdfium2` is already installed as a transitive dependency of paddlex and becomes a declared direct
dependency of this module, because reading a PDF header is now this module's own behaviour and must not rest on
someone else's dependency tree. Pillow 12.2.0 is already declared and currently unused by `src/`. No new install.

API: additive on both surfaces. No request parameter is added. A caller who submits work the service will not
accept now gets a 400 with `FILE_TOO_LARGE` and a message naming the measurement and the limit, in place of a
timeout, an OOM kill or a thirty minute orphan. A caller who arrives while the pool is being rebuilt waits and is
served, in place of an instant 500 that would have persisted until someone noticed.

Accuracy: deploying a detector bound is the one change here a caller can see in the output. It costs detected lines
on small text and leaves recognition quality alone, one line in twenty nine at the single measured point, and the
deployed value is chosen by measuring against the owner's own documents rather than defaulted.

Operational: `OCR_REQUEST_TIMEOUT` in `docker-compose.yaml` is 300 today and that value is what turned a healthy
twenty page job into an error. It is re-derived from the measured per-page time in task 1.2, together with the page
count limit it implies, and the pair is an owner decision because it trades how large a document the service
accepts against how long a caller must hold a connection. Memory does not constrain that trade: a page retains
11.5 MiB, so page count does not become the binding term until about ninety pages unbounded and several hundred
with a detector bound deployed. The second operational pair is the detector bound and the pixel ceiling, which are
one decision in two settings and are deployed together, because there is no safe default for either alone.

Docs: the environment variable list in `PaddleOCR/AGENTS.md`, `PaddleOCR/README.md`, the arc42 pages under
`PaddleOCR/docs/architecture/arc42/`, an amendment to ADR-004 for the readiness condition, and two new ADRs, one
for the fixed rendering resolution and one for the detector input bound. AGENTS.md, the README and the arc42 pages
also gain the memory model and the sentence that makes the worker cap a memory constraint rather than a throughput
one. All written when the change is applied.

Superseded: `openspec/changes/add-ocr-full-resolution-reading/` is deleted. Its pixel ceiling reasoning survives
here, and so, as it turns out, does its cost law, at a measured 5.3 GiB per megapixel. Its piece cutting, joining,
duplicate removal, reading order and `high_res` parameter do not, because bounding the detector's input reaches the
same per-inference size with two constructor arguments and nothing to maintain.

## Relevant Skills

Load before implementing:

- `/python-patterns`, `/python-testing`, `/tdd-workflow`
- `/api-design`, `/docker-patterns`, `/deployment-patterns`
- `/security-review` for the decompression bomb guard and the header parsing
- `/coding-standards`, `/code-reviewer`
- `/architecture-decision-records` for the ADR in task 8.4
