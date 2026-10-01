## Reconciled with fix-ocr-page-resolution (2026-09-24)

[fix-ocr-page-resolution](../fix-ocr-page-resolution/design.md) overturns several things this design treats as
settled, and where the two disagree that change is right. This document keeps its own figures as the record of the
single-allowance design and marks each overturned place with a pointer here rather than restating the new values.

- The per-page allowance. This design settles one allowance, 45 s, for every page. That change makes it per engine:
  `OCR_PAGE_ALLOWANCE_HEADROOM` times the worst page measured on the detection model that reads the page, because the
  server detector `ru` and `korean` load took 8.5 times as long as the small pair on the largest page `high` mode
  admits. The headroom replaces `OCR_PAGE_TIMEOUT_SECONDS` as the only configured time input. A document's reading
  budget, its reclamation grace, the poll hint and the queue's promised wait follow the engine of each page, and the
  reading ceiling and maximum lifetime follow the slowest engine any supported language loads. That change owns
  every one of those figures, in its Decision 8. The 45 s, 50 s, 4500 s, 13,500 s, 4505 s, 2 h 30 min and 33 minute
  figures below were worked at the single allowance and are superseded.
- The pixel ceiling and the detector bound. `OCR_MAX_INFERENCE_PIXELS` and `OCR_DETECTOR_MAX_SIDE` are deleted. A
  page larger than its quality mode supports is shrunk and read rather than refused, the only pixel refusal left is
  the decompression-bomb guard on `OCR_MAX_SOURCE_PIXELS`, and the detector bound comes from a per-request quality
  mode. So "Unchanged and not reopened" below, the non-goal of not moving them, the paragraph on what the 300 dots per
  inch measurement does not license, and Open Question 5 are overtaken, and in `ocr-job-admission` the scenario
  "Oversized page submitted" is replaced.
- The scratch file. The worker no longer writes a submission to disk, so the scratch sweep horizon in the number
  table has nothing left to sweep.

## Context

See [proposal.md](proposal.md) for the motivation. This change builds on two earlier ones and the order matters.

[stop-ocr-getting-stuck-on-large-jobs](../stop-ocr-getting-stuck-on-large-jobs/design.md) installed the deadline,
the reclamation path, the admission gate and the fitted memory model. Its mechanisms are reused here. Its numbers are
not, and the section below says why.

[upgrade-ocr-to-ppocrv6](../upgrade-ocr-to-ppocrv6/proposal.md) is implemented and gate-green and not yet archived.
It moved the library from PaddleOCR 3.6.0 to 3.7.0 and named `PP-OCRv6_small_det` and `PP-OCRv6_small_rec` as the
model pair every language but `ru` and `korean` now runs. **This change depends on that one.** Every duration and
every ceiling below is derived from measurements taken against that pair, so this change cannot be implemented
against the model it replaced and cannot be archived before it.

Read from the code and the configuration as they stand after both changes:

- The page limit is derived, not configured. `Settings.OCR_MAX_PAGES` is
  `floor(OCR_REQUEST_TIMEOUT / OCR_PAGE_TIMEOUT_SECONDS)` in
  [config.py](../../../apps/ascend-ocr/src/config/config.py). The code defaults are 120 s and 120 s, and
  `compose.yaml` deploys `OCR_REQUEST_TIMEOUT=300` with `OCR_PAGE_TIMEOUT_SECONDS=150`, so the deployed limit is
  two, and `enforce_page_limit` in [limits.py](../../../apps/ascend-ocr/src/api/limits.py) refuses anything above
  it with `FILE_TOO_LARGE`.
- One worker. `OCR_WORKER_COUNT` governs both the `ProcessPoolExecutor` size and the admission gate's permit count
  in [ocr_service.py](../../../apps/ascend-ocr/src/service/ocr_service.py). It was a memory constraint. After the
  model upgrade it is not, and the "What memory no longer constrains" section below states that plainly rather than
  leaving the old reason standing.
- The stop is cooperative and already page-granular. `_predict_pages` consumes `predict_iter()` and checks a
  deadline before pulling each page. The parent passes a remaining duration, never a wall clock time.
- The reclamation and rebuild path exists. `_rebuild_pool(observed_generation, reason)` replaces the pool, is
  guarded by a lock and a generation counter, counts consecutive failures, and is already reached from two triggers.
- Both surfaces already share one dispatch function. `dispatch_ocr_request(...)` in `ocr_service.py` is called from
  [rest_endpoints.py](../../../apps/ascend-ocr/src/api/rest/rest_endpoints.py) and
  [mcp_server.py](../../../apps/ascend-ocr/src/api/mcp/mcp_server.py), and both compute
  `min(pages x OCR_PAGE_TIMEOUT_SECONDS, OCR_REQUEST_TIMEOUT)` identically.
- The service holds no persisted state and has no external service dependency of its own today.
  `apps/ascend-ocr/e2e/README.md` says so in as many words, there is no database, no cache and no volume in
  `compose.yaml`, and the only cross-process state is the Prometheus multiprocess directory that `is_engine_warm`
  reads. Decision 3 and Decision 10 both change that, deliberately, and say what it costs.
- The platform already runs S3-compatible object storage and this service can already reach it. Locally it is Floci
  on host port 9070, and `compose.yaml` already sets
  `MCP_ALLOWED_HOSTS=host.docker.internal,localhost,127.0.0.1` on `ascend-ocr` precisely so the MCP download path
  can fetch documents from it.
- The ascend-ai-agent addresses that storage with the AWS SDK v2. `AppConfig.s3Client()` builds an `S3Client` with
  `endpointOverride(app.s3.endpoint)`, `Region.US_EAST_1` with a comment saying the local emulator reports that
  region, static credentials from `app.s3.access-key` and `app.s3.secret-key`, and `pathStyleAccessEnabled(true)`.
  `app.s3.public-endpoint` exists because the endpoint the agent reaches is not always the one a caller can reach.
  `BucketInitConfig` heads the bucket at startup and creates it when missing, logging a failure rather than
  refusing to boot. `S3PresignedUrlService` presigns GET URLs against the public endpoint with a TTL clamped to one
  minute to one hour. Decision 10 mirrors all of it rather than inventing a second convention.
- The agent reads objects with bucket and key. `ManualIngestionService` calls `s3Client.getObject(...)` and
  `listObjectsV2(...)` against `app.s3.bucket`, which is `knowledge-base`, and ingests whatever it lists under a
  prefix. That is why Decision 10 puts OCR results in their own bucket rather than in that one.
- The service has no authentication of its own. `SecurityHeadersMiddleware`, `CorrelationIdMiddleware` and the
  slowapi rate limiter are the whole of the request-level protection. `RATE_LIMIT_DEFAULT` is 60 per minute and is
  the limiter's default limit, and `RATE_LIMIT_OCR` is 20 per minute and decorates `POST /v1/ocr` alone.
- The error catalogue is fixed and mapped in one place. `exception_handlers.py` maps `OCR_FAILED` to 422,
  `FILE_TOO_LARGE` and `UNSUPPORTED_FILE_TYPE` and `UNSAFE_URI` to 400, `DOWNLOAD_FAILED` to 502 and
  `INTERNAL_ERROR` to 500. Adding a code is non-breaking under ADR-003, renaming or restatusing one is not, and
  removing an operation is breaking whatever the codes do.
- The scratch sweep horizon is the synchronous ceiling. `sweep_scratch_dir` removes anything older than
  `OCR_REQUEST_TIMEOUT + OCR_DISPATCH_MARGIN_SECONDS`.
- The in-platform caller times out at 300 s. `app.ingestion.read-timeout` is 300000 ms in the agent's
  `application.yaml`, used by the `ingestionRestClient` that `AscendOcrClient` holds. ascend-ocr is not in the
  agent's MCP connection list at all, so the agent reaches this module over REST and nothing else.
- The agent never sends a long document as one request. `DocumentRouter.routePdfPerPage` slices a PDF into
  single-page PDFs and dispatches them with `pdf-parallel-pages: 4`. Images go whole, and an image is one page.
- The agent flattens the OCR response to plain text. `AscendOcrClient.parseResponse` walks `pages[].lines[].text`,
  joins every line with a newline and builds exactly one Spring AI `Document`. It reads neither `confidence` nor
  `bounding_box`, which `OcrTextLine` also carries. Decision 10 depends on that being true.
- The container is allocated 12 GB and 4.0 CPUs. `compose.yaml`'s `deploy.resources.limits` says
  `memory: 12G`, `cpus: "4.0"`, and the previous change verified both from the running container rather than from
  the file. (Superseded 2026-09-25: the limit is 4 GiB, see `fix-ocr-page-resolution` design.md Decision 10.)
- **The deployed values, re-read on 2026-09-24 for task 1.1.** `compose.yaml` sets `OCR_REQUEST_TIMEOUT=300` and
  `OCR_PAGE_TIMEOUT_SECONDS=150`, so the derived `OCR_MAX_PAGES` is 2, confirmed. `config.py` carries
  `OCR_DETECTOR_MAX_SIDE=1536`, `OCR_MAX_INFERENCE_PIXELS=2500000`, `OCR_TEXT_DETECTION_MODEL=PP-OCRv6_small_det`
  and `OCR_TEXT_RECOGNITION_MODEL=PP-OCRv6_small_rec`, all confirmed.
- **The image on this host does not yet run the pair those numbers were measured on.** There is no running
  `ascend-ocr` container to read: the one on this host exited 137 forty four hours before the check, and its image,
  `ascend-ai-ascend-ocr:latest`, was built on 2026-09-18, before `upgrade-ocr-to-ppocrv6` landed in the working
  tree. Its own logs show `Creating model: ('PP-OCRv5_server_det', None, None)` and
  `('en_PP-OCRv5_mobile_rec', None, None)`, which is the pair that change replaced. The code is right and the image
  is stale, so the container-side half of task 1.1 is settled by one rebuild and one look at the startup banner,
  and not by anything in the source tree.

## The measurements this change is derived from

**Superseded 2026-09-25**, see `fix-ocr-page-resolution` design.md Decision 10. The figures in this section came from a probe that sampled memory at intervals and missed the peak. Measured as a Linux container's cgroup `memory.peak`, 4 CPUs, worst of three runs, one A4 page at 300 dpi on the `PP-OCRv6_small` pair peaks at 1016 MiB in 20.5 s, a photo read with `straighten` at up to 2771 MiB in up to 28.4 s, and the API process at rest holds 259 MiB. The page allowance is 127.8 s and the container limit is 4 GiB. The text below is kept as written.

Taken by the owner on his own machine against the `PP-OCRv6_small` detection and recognition pair, one A4 page of
the same synthetic text at three densities, rendered at 300 dots per inch, with the detection input bounded to a
long side of 1536.

| Lines of text on the page | Wall time | Peak memory |
|---|---|---|
| 6 | 4.1 s | 439 MB |
| 20 | 6.0 s | 439 MB |
| 50 | 10.0 s | 441 MB |

Two conclusions, and they are not equally safe.

**Memory is flat and density does not move it.** 439, 439 and 441 MB across an eightfold change in text. That is
what the structure of the cost predicts: detection dominates, detection sees a fixed input because
`OCR_DETECTOR_MAX_SIDE` bounds the long side to 1536 whatever the page's own resolution, and recognition operates on
crops that are released as it goes. **This conclusion is safe to build on**, including for real scans, because the
mechanism that makes it flat does not care whether the text is clean.

**Time is 2.9 s fixed plus about 0.14 s per line, and that conclusion is provisional.** The owner's fit predicts
3.7 s, 5.7 s and 9.9 s against the measured 4.1, 6.0 and 10.0, so it runs slightly under the observations at low
density and is within 0.4 s everywhere. **This conclusion is not safe to build on for real scans**, because a real
scan is noisy, skewed and textured, and detection on it may produce many more regions than a clean render of the
same words. Every duration below therefore carries a headroom factor over the measurement, and the end-to-end run
against real scanned documents is what confirms or moves it.

For comparison, the configuration this replaces cost 51 to 94 seconds a page and peaked at 9.76 GiB for one
inference. The previous change's own twenty-four-observation table records 51.3 s to 93.8 s across its fixtures,
which is the measurement that band comes from. So one page went from tens of seconds to single-digit seconds,
and from most of a twelve gigabyte container to under half a gigabyte.

The predictions this change was originally written against were 9,060 MB for one A4 page at 144 dots per inch and
44,847 MB at 300. The measured figure at 300 dots per inch is 441 MB. Both predictions were wrong by more than an
order of magnitude on the new pair, the second by a factor of a hundred, and everything derived from them is void
rather than merely conservative.

Overtaken on 2026-09-24, the pixel ceiling is deleted by `fix-ocr-page-resolution`, see the section at the top of this document. One thing the 300 dots per inch measurement does not license. An A4 page rendered at 300 dpi is about 8.7
megapixels, and `OCR_MAX_INFERENCE_PIXELS` is 2,500,000, so this service would refuse that page at the request
boundary before any decode. The figure describes what the engine costs, not what the service currently accepts. The
pixel ceiling stays where it is in this change. What the measurement does settle is the mechanism: a page's own
resolution stops driving memory once the detector bound is deployed, so if the pixel ceiling is ever raised, memory
is no longer the argument against it.

## What memory no longer constrains

**Superseded 2026-09-25**, see `fix-ocr-page-resolution` design.md Decision 10. The figures in this section came from a probe that sampled memory at intervals and missed the peak. Measured as a Linux container's cgroup `memory.peak`, 4 CPUs, worst of three runs, one A4 page at 300 dpi on the `PP-OCRv6_small` pair peaks at 1016 MiB in 20.5 s, a photo read with `straighten` at up to 2771 MiB in up to 28.4 s, and the API process at rest holds 259 MiB. The page allowance is 127.8 s and the container limit is 4 GiB. The text below is kept as written.

This is stated plainly because the previous design, this change's own first draft, and the module's documentation
all still reason from a model that is now wrong for every language but `ru` and `korean`.

Gone, and deleted from this document rather than left to mislead:

- The fitted `peak_MiB = 635 + 5302 x megapixels + 11.5 x pages`, as a whole-model statement. The 5302 MiB per
  megapixel term was 94 percent text detection and it was `PP-OCRv5_server_det`'s cost. That detector is 88.4 MB of
  artifacts against `PP-OCRv6_small_det`'s 10.1 MB, and the measurement above is what the difference is worth.
- "One A4 page's peak is already most of the container's 12,288 MiB." One A4 page is 441 MB of a 12,288 MB
  container, which is 3.6 percent.
- "Page count does not become the binding term until roughly ninety pages." That threshold was the point at which
  11.5 MiB a page consumed the 1028 MiB an A4 page left under the container limit. There is no such crowding now.
- The three-page-size ceiling table, and the finding that US Letter was the expensive size because its long side
  sat closest to the 1536 bound. The relationship is still real and it is worth 2 MB rather than 750.
- "One page of US Letter does not fit a 90 percent resident budget." It fits nineteen times over.
- The ninety percent resident budget itself, as a design input. A budget is a way of rationing a scarce resource,
  and this resource stopped being scarce.
- The forty page ceiling, and the arithmetic that produced it from the smaller of A4 at a 90 percent budget and US
  Letter at the container limit.

What survives, and it is one term. Each page retains about 11.5 MiB of result inside the worker while the document
is read. That is recognised text and polygons rather than model weights, so it is the term least likely to have
moved with the model, and it is the only way page count enters memory at all. It is unmeasured on the new pair and
task 1.2 measures it. Until it reports, 11.5 MiB a page is used here as an upper bound carried forward, and it is
the single memory number the page ceiling still leans on.

So the memory picture is now: about 440 MB is one call's peak, whatever the page holds, and about 1.1 GB is the
whole service with the API process, the worker and the warm engine cache counted in. Each page of a document adds
about 11.5 MiB of retained result on top, once. At the page ceiling this change sets, the whole service is about
2.3 GB.

## The container allocation is a live question this change names and does not settle

Settled 2026-09-25, see `fix-ocr-page-resolution` design.md Decision 10: the limit is 4 GiB, from the worst straightened call, 2771 MiB, plus the
API process at rest, 259 MiB, plus room for one idle engine, about 3.1 GiB in all.

The service is allocated 12 GB in `compose.yaml` and now needs about 1.1 GB, which is the API process plus the
worker plus the warm engine cache plus one call's 440 MB transient. The owner and this change's author have
discussed 3 GB.

Recorded as a recommendation with its arithmetic, not as an edit: 3 GB is 2.7 times what the service needs at rest
plus one call, and it leaves about 1.9 GB for the per-page accumulation term, which is about 157 pages at 11.5 MiB
each. At the 100 page ceiling below, the accumulation is about 1.2 GB and the whole service is about 2.3 GB, so 3 GB
leaves roughly 57 pages of headroom at the ceiling.

It should be set only after the end-to-end specs have run against real scanned documents rather than synthetic
pages, for the same reason the durations carry headroom: nothing here has measured a real scan. Task 10.6 is the
gate, and task 2.7 is the compose edit that waits on it.

## Goals / Non-Goals

Goals:

- A long document is read, and no caller is ever asked to hold a connection for the length of the reading, whatever
  the document's length.
- One shape for every request. There is no page count, no flag and no header at which the service behaves
  differently, so there is one queue, one set of bounds and one refusal vocabulary.
- The protection the previous change installed survives intact. Nothing here lets the service compute pages for a
  caller who has gone, and nothing here removes a page ceiling.
- Every number is derived from the measurements above, and the ones that are a product trade rather than a
  derivation say so.
- Everything a long-running job drags in is settled here rather than discovered later: where state lives, where the
  result lives, what a restart does to both, how long a result survives, what the queue promises, whether cancel
  actually cancels, and what stops a wedged record being polled forever.
- An operator can see what the service is working on without reading logs.
- The platform's own caller moves with the contract. The ascend-ai-agent is migrated in this change rather than
  left pointing at an endpoint that answers 410.

Non-Goals:

- Making OCR faster. The upgrade to `PP-OCRv6_small` already did that and this change spends the result rather than
  chasing more.
- Raising the worker count. It stays one here, and the reason has changed: it is no longer memory, it is that
  nothing has measured two concurrent inferences on this hardware and that every queue promise below is written
  against one worker. Open Question 4 records that the new memory figure makes raising it possible for the first
  time.
- Changing the agent's per-page fan-out. `pdf-parallel-pages` stays at 4, and Decision 12 records what that number
  now buys and what it no longer needs to.
- Moving `OCR_MAX_INFERENCE_PIXELS` or `OCR_DETECTOR_MAX_SIDE`. Overtaken on 2026-09-24, `fix-ocr-page-resolution`
  deletes both. Both keep the owner's measured values from
  [ADR-006](../../../apps/ascend-ocr/docs/architecture/decisions/ADR-006-detector-input-bound.md).
- Authentication. Possession of an unguessable identifier is the whole access control, which is the same posture the
  service already has, and raising it is a platform-wide decision rather than this change's. Decision 18 states what
  the new list operation costs while that remains true.
- Persisting the job record across a container recreate by default. Decision 4 states what survives what, and a
  volume is documented rather than assumed. The result itself is in object storage and survives regardless.

## The numbers, and where each comes from

Overtaken on 2026-09-24: the per-page allowance and every figure derived from it are owned by `fix-ocr-page-resolution`, see the section at the top of this document. Every figure is worked at the 45 s allowance the first row settles. Every derived figure is expressed in allowances
or in pages so it moves with its inputs rather than having to be recomputed by hand.

| Value | Setting | Default | Where it comes from | Kind |
|---|---|---|---|---|
| Per-page allowance | `OCR_PAGE_TIMEOUT_SECONDS`, replaced by `OCR_PAGE_ALLOWANCE_HEADROOM` | per engine, `fix-ocr-page-resolution` now owns this figure (its design.md Decision 8) | Measured 4.1 s, 6.0 s and 10.0 s for 6, 20 and 50 lines on one A4 page. The owner's fit is 2.9 s plus 0.14 s a line, so the 115 line page the previous change reasoned about extrapolates to 19.0 s. 45 s is 4.5 times the measured worst case and 2.4 times that extrapolation. The multiple is larger than the 1.9 the previous change used because this sample is synthetic and a real scan may detect many more regions. It is the service's only configured time input, so task 1.4 sets it once in `config.py` and deletes the `compose.yaml` override. The 45 s was one allowance for every page and is superseded by one per engine. | Superseded |
| Job page ceiling | `OCR_JOB_MAX_PAGES` | 100 | Memory no longer sets this and no deadline sets it either. What sets it is how long one document may hold the single worker and block everything behind it: 100 pages is about 17 minutes at the measured cost and 4500 s at the allowance. The memory cross-check is the surviving per-page term, about 1.2 GB at 100 pages, which fits the 3 GB recommendation with about 57 pages to spare. Four times the twenty five pages the request named. | Chosen from a queue-blocking budget, with a memory cross-check |
| One document's reading budget | derived | pages x the allowance of the document's own engine, `fix-ocr-page-resolution` now owns this figure (its design.md Decision 8) | The old `min(pages x allowance, OCR_REQUEST_TIMEOUT)` loses its second term. The page ceiling already caps pages, so a cap on the product can never bind first. | Derived |
| Job reading ceiling | derived | from the slowest engine any supported language loads, `fix-ocr-page-resolution` now owns this figure (its design.md Decision 8). It was 4500 s at the single allowance | `OCR_JOB_MAX_PAGES x OCR_PAGE_TIMEOUT_SECONDS`. The longest one document may be read for, and the horizon the scratch sweep now uses. At the measured cost the same document is about 17 minutes, so this is a backstop and not an estimate, and the gap between the two is the headroom the allowance carries. | Derived |
| Reclamation grace | derived, unchanged in form | the document's own engine's allowance + dispatch margin, `fix-ocr-page-resolution` now owns this figure (its design.md Decision 8). It was 50 s at the single allowance | Unchanged mechanism, and it falls with the allowance from 125 s at the old code default, or 155 s as deployed, to 50 s. A worker that will not stop is replaced sooner in proportion. | Derived |
| Maximum lifetime in a non-terminal state | derived | from the slowest engine any supported language loads, `fix-ocr-page-resolution` now owns this figure (its design.md Decision 8). It was 13,500 s at the single allowance | `(OCR_JOB_QUEUE_MAX_PAGES + OCR_JOB_MAX_PAGES) x OCR_PAGE_TIMEOUT_SECONDS`, the worst case wait plus the longest read. Nothing may sit waiting or running past it, so a wedged record is failed rather than polled forever. | Derived |
| Queue page bound | `OCR_JOB_QUEUE_MAX_PAGES` | 200 | Two maximal documents may wait while one is read. It is what turns the wait into a number: pages ahead, each at the allowance of the engine that will read it, which `fix-ocr-page-resolution` now owns this figure (its design.md Decision 8). The 2 h 30 min at the bound and about 33 minutes at the measured cost were worked at one 45 s allowance and 10 s a page, and are superseded. It must be at least the page ceiling or a single maximal document could never be queued, which task 2.4's validator enforces. | Derived from a stated promise |
| Queue document bound | `OCR_JOB_QUEUE_MAX_DOCUMENTS` | 8 | Unchanged, and its reason is untouched by the model upgrade because it is about bytes on disk rather than inference: a chosen 400 MB storage budget for waiting submissions divided by the existing `MAX_FILE_SIZE_MB` of 50. It is also the bound the agent's fan-out must stay under, and at `pdf-parallel-pages: 4` it does. It bounds the list operation too, which can therefore never return more than nine entries. | Chosen, stated |
| Poll hint | derived | a tenth of the allowed seconds ahead, each page at its own engine's allowance, clamped to 1 to 30 s, `fix-ocr-page-resolution` now owns this figure (its design.md Decision 8). The 45 s reasoning beside it is superseded | At a 45 s allowance that is 4.5 s a remaining page against a measured 10 s a page, so a caller that honours it wakes roughly twice per page of remaining work, never polls faster than once a second, and never leaves a finished result sitting for more than 30 s. | Derived |
| Result retention | `OCR_JOB_RETENTION_SECONDS` | 3600 s | More than three times the roughly 17 minutes the longest document the service accepts takes to read, so a caller whose polling died has a full working session to restart it and collect. Half the four hours the first draft chose, because that was sized against a reading time four times longer, and because the window is also how long a document's text sits in the bucket. | Chosen, stated |
| Retained record cap | `OCR_JOB_MAX_RETAINED` | 1000 | The fastest the single worker can produce finished records is one sparse single page document every 4.1 s measured, so at most 878 can be produced inside one retention window. 1000 is that rounded up, which keeps the time bound the thing that removes a record and leaves the count bound a backstop against a defect rather than an eviction policy callers meet. | Derived from the measured floor |
| Jobs directory | `OCR_JOBS_DIR` | an `ascend-ocr-jobs` directory beside the scratch directory | Matches `OCR_SCRATCH_DIR`'s own default shape, kept separate because the lifetimes and sweep horizons differ. | Convention |
| Result store endpoint | `OCR_RESULT_S3_ENDPOINT` | `http://localhost:9070` | The same default the agent's `app.s3.endpoint` carries, which is Floci on its host port. `compose.yaml` overrides it to `http://host.docker.internal:9070`, which is the address the SSRF allowlist already names for this container. | Convention, mirrors the agent |
| Result store public endpoint | `OCR_RESULT_S3_PUBLIC_ENDPOINT` | the endpoint above | The address baked into a presigned URL, which is not always the one the service itself reaches. Exactly the agent's `app.s3.public-endpoint` and it exists for exactly that reason. | Convention, mirrors the agent |
| Result bucket | `OCR_RESULT_S3_BUCKET` | `ocr-results` | Its own bucket rather than the agent's `knowledge-base`, because `ManualIngestionService` lists and ingests whatever it finds there and would ingest OCR results as source documents. A dedicated bucket also makes a lifecycle rule for orphans safe to write. | Chosen, stated |
| Result store credentials | `OCR_RESULT_S3_ACCESS_KEY`, `OCR_RESULT_S3_SECRET_KEY` | empty | Static credentials, the way the agent supplies them. Empty by default so a deployment that has not configured a result store fails loudly at startup rather than silently writing nowhere. | Convention, mirrors the agent |
| Scratch sweep horizon | derived | none left, `fix-ocr-page-resolution` removes the scratch file. It was reading ceiling + dispatch margin, 4505 s | Replaces `OCR_REQUEST_TIMEOUT + OCR_DISPATCH_MARGIN_SECONDS`, whose first term no longer exists. | Derived |
| Removed | `OCR_REQUEST_TIMEOUT` | gone | It bounded a held connection, and no connection is held. Its four consumers move: the page limit becomes `OCR_JOB_MAX_PAGES`, the effective budget loses the second term of its `min`, the scratch sweep horizon becomes the job reading ceiling, and the startup banner reports the ceiling instead of the timeout. | Deleted |
| Removed | `OCR_MAX_PAGES` | gone | It was `floor(OCR_REQUEST_TIMEOUT / allowance)`, which is 2 at the deployed pair. Nothing derives a page limit from a deadline any more, because there is no deadline to derive it from. | Deleted |
| Not a setting of this service | container memory limit | 12 G today, 3 G recommended | See "The container allocation is a live question" above. Recommendation only, gated on task 10.6. | Recommendation, not settled |

Overtaken on 2026-09-24 for the first two settings, which `fix-ocr-page-resolution` deletes, see the section at the top of this document. Unchanged and not reopened: `OCR_DETECTOR_MAX_SIDE` at 1536 and `OCR_MAX_INFERENCE_PIXELS` at 2,500,000, the
owner's measured pair recorded in
[ADR-006](../../../apps/ascend-ocr/docs/architecture/decisions/ADR-006-detector-input-bound.md), `OCR_WORKER_COUNT`
at 1, `OCR_DISPATCH_MARGIN_SECONDS` at 5, `MAX_FILE_SIZE_MB` at 50, `MCP_DOWNLOAD_TIMEOUT_SECONDS` at 30,
`ENGINE_CACHE_MAX_SIZE` at 2, `OCR_TEXT_DETECTION_MODEL` and `OCR_TEXT_RECOGNITION_MODEL` at the small pair, and
both rate limits.

One meaning change worth its own line: `MCP_DOWNLOAD_TIMEOUT_SECONDS` now bounds work inside a submission, because
the submit tool fetches the URI and reads its header before it can answer 202. Submission is bounded by a constant
that does not scale with the document, which is the property that matters, and it is not instant for a slow URI.

## What the caller experiences, end to end

At the defaults, for a twenty five page A4 scan submitted with nothing else in the queue:

1. The submission is answered in the time it takes to read the file and its page headers, with an identifier.
2. The document is read for about four minutes at the measured ten seconds a page, with a hard stop at 1125 s, which
   is twenty five allowances.
3. Polling on the hint the status answer carries costs a few dozen status reads over the reading, each a small file
   read against the 60 per minute default rate limit rather than the 20 per minute OCR limit.
4. The status answer for the finished work carries the bucket, the key and a presigned URL for a Markdown file, plus
   the page count, the language and the reading time. The caller fetches the Markdown from object storage. The
   ascend-ai-agent already holds an S3 client for that bucket's endpoint and uses bucket and key. A caller that does
   not, such as a Bruno request or curl, uses the presigned URL.
5. The result stays collectable for an hour, or until the caller deletes it, which deletes the object too.

A one page image goes through exactly the same five steps and finishes in about five seconds. There is no shorter
path and no different one, which is the point of Decision 2.

If another document is being read when the submission arrives, everything above shifts by that document's remaining
time. The shift is not a mystery: the submission is told how many pages are ahead of it, every status answer repeats
the pages ahead and carries a poll hint derived from them, `GET /v1/ocr/jobs` shows the whole queue, and nothing is
ever failed for having waited. The wait itself is bounded by the queue page bound rather than by any clock running
against the document.

## Decisions

### Decision 1: the shape is submit and collect, and the speedup narrows the case for it without changing it

This argument has to be re-derived rather than repeated, because the model upgrade moved the numbers it rested on.
The first draft said a twenty five page document needs about 2250 s against a 300 s client timeout. It needs about
250 s now, which is inside that timeout. A synchronous path would in fact serve twenty five clean pages today.

It still loses, on three counts that the speedup does not touch.

The ceiling, not the request, is what has to fit. This change accepts documents up to 100 pages, which is about
17 minutes at the measured cost and up to 4500 s at the allowance. Both are far past the agent's
`app.ingestion.read-timeout` of 300 s and past the 300 s `spring.ai.mcp.client.request-timeout` every MCP connection
uses. A contract that works up to about thirty pages and silently stops working above it is a contract with a page
count threshold in it, which is what Decision 2 exists to refuse.

The queue is now the dominant term, not the reading. One worker, first in first out. A caller holding a connection
waits for everything ahead of it as well as for its own document, and that wait does not shrink when inference gets
faster. Two callers each submitting twenty five pages means the second holds a connection for about 500 s for a
document that costs 250 s. Speeding up the model moved the reading below the client timeout and left the waiting
above it.

And the original incident's mechanism is untouched. FastAPI does not notice that a client has gone for an ordinary
request handler, so any held connection can be abandoned while the service keeps inferring pages for nobody. That is
true at 4 s a page exactly as it was at 90.

The three cheaper shapes still fail for their own reasons. Streaming the result page by page holds the connection
for the whole reading and loses the rest on a disconnect, changes the response shape so it is a new endpoint under
ADR-003 anyway, has no MCP equivalent, and contradicts the existing requirement that an expired request returns
nothing partial. Splitting the document caller-side is what the agent already does, pushes ordering and reassembly
onto every caller, does nothing for a raw image and nothing for an MCP client holding one PDF. Delivering by
callback requires this service to make an outbound request to a caller-supplied URL, which is exactly the capability
its SSRF guard exists to deny, and brings retries, delivery failure states and a shared secret with it. All three
rejected.

So: submit, poll, collect.

### Decision 2: the synchronous request is removed, and keeping it is the rejected alternative

`POST /v1/ocr` and the `ocr_process` tool are removed. Every document, of every length, is submitted and collected.
An earlier version of this change decided the opposite and recorded replacing the synchronous request as rejected,
on the grounds that it is breaking and worse for the common case. The owner overturned that. The old position is
kept here as the alternative that lost.

Two paths mean two sets of bounds. The synchronous path was bounded by a deadline, because a caller held a
connection. The job path is bounded by the queue and by what one document may do to it. Keeping both means every
admission guard, every ceiling, every queue rule and every refusal message exists in two versions that have to be
kept in agreement forever, and the only thing that distinguishes them is a page count threshold nobody can defend.
The speedup makes that threshold movable, which makes it worse rather than better: the honest place to draw it is
wherever the slowest real page happens to sit this month.

The common case argument was real and it is smaller than it looked. A one page image costs a submission and a poll,
so it goes from one round trip to two against this service, plus one fetch against the object store. It buys the
property that a caller can lose its connection at any moment without losing the work.

Breaking is the honest cost and it is not hidden. Under ADR-003's own table this is a breaking change on both
surfaces. It changes the agent's `AscendOcrClient`, the fifteen Bruno requests that drive `POST /v1/ocr` or
`ocr_process`, and eleven of the twelve e2e specs. A deprecation window of the kind ADR-003 imagines does not help,
because the thing that changed is what a submission's answer means, so a caller that keeps calling the old name
still has to be rewritten. Decision 17 states what each surface does in place of one.

### Decision 3: the job record lives in files, the result body does not

One record per job as JSON under `OCR_JOBS_DIR`, written by temporary file and atomic replace, plus the submitted
bytes beside it until the job reaches a terminal state, plus a small progress file while it runs. The recognised
text is not in any of them. It goes to object storage, which is Decision 10.

The split is the decision, and it is not arbitrary. The record is written on every state transition and read on
every poll, which is a chatty small-object workload that a local file serves better than a bucket, and it is what
lets the service record that a job failed even when the bucket is the thing that failed. The result is written once,
read once or twice, may be megabytes, and is the only part anyone wants to keep.

Files rather than Redis for the record, even though the platform runs one. A job store that is unreachable would
make every request fail while the OCR engine itself is perfectly healthy, and after this change every request goes
through the store. The bucket is a dependency this change accepts for the result, and accepting a second one for the
record would mean the service could not even tell a caller that its work had failed.

Files rather than SQLite, because there is exactly one writer, no query beyond fetch by identifier and enumerate the
non-terminal ones, and at most a few hundred records inside a retention window. SQLite would buy transactions this
design has no use for and add a schema to migrate.

The single-writer property is what makes files safe here. The API process runs one event loop, so record writes are
serialised by construction, and the only thing the worker process writes is its own job's progress file. Every write
is temp plus `os.replace`, so a reader never sees half a record. Writing the submitted bytes is done off the event
loop, because 50 MB of file I/O inside a request handler would block every other request including `/health`.

### Decision 4: a restart fails work in flight rather than resuming it

At startup, before the runner starts, every record found waiting or running becomes failed with a distinct
`SERVICE_RESTARTED` reason, and its submitted bytes are removed. Finished records are left alone and keep their
original expiry.

Resuming a running job is wrong for the reason Decision 12 of the previous change already established: the service
cannot know whether the document it was reading is what brought it down, and a resume feeds the killer its input
again. Re-queueing work that was merely waiting is safer and was still rejected, because the service cannot
distinguish a deliberate restart from a crash loop, and a queue that replays itself on every boot is a crash loop
with a longer period. The caller still holds the bytes and a resubmission is one call.

What the distinct reason buys is the thing a caller actually needs: `OCR_FAILED` means the service tried and could
not read this document, and resubmitting it will fail again, while `SERVICE_RESTARTED` means nothing was learned
about the document and resubmitting is exactly right. Decision 12 makes the agent act on exactly that distinction.

The honest limit of the durability, and it is better than it was before Decision 10. The recognised text lives in
object storage, so it survives the process restarting, the container restarting and the container being recreated.
The record lives on the container's filesystem, so it survives the first two and not the third. What a recreate
destroys is therefore the address rather than the text: the Markdown is still in the bucket under the job's own
identifier, an operator can fetch it, and a caller holding the identifier cannot, because the service will answer
`JOB_NOT_FOUND`. An operator who wants the address to survive too mounts a volume at `OCR_JOBS_DIR`, and that is a
documented option rather than a default.

### Decision 5: one retention window, a count bound, and an expired identifier is a plain not-found

A finished record, and the result object it points at, live for `OCR_JOB_RETENTION_SECONDS` from the moment the work
finished. The sweep that removes them runs at startup and on the runner's idle tick, so removal never waits for a
caller to arrive, and it deletes the object before it deletes the record, so a failure between the two leaves an
orphaned record pointing at nothing rather than an orphaned object nothing points at. The count bound evicts the
oldest finished record when there are more than `OCR_JOB_MAX_RETAINED`, on the same two-step order.

The count bound's role changed with the numbers. At 1000 records against the 878 the worker can produce inside one
window, it is a backstop against a defect rather than a policy any caller meets, which is why the first draft's
consequence, that a caller submitting faster than it collects can evict its own oldest result, is deleted rather
than restated.

Orphaned objects are still possible, because an upload that succeeds and a record write that then fails leave one.
The service does not hunt for them, because it cannot distinguish an orphan from an object another writer put in the
bucket. The dedicated bucket of Decision 10 is what makes the answer cheap: an object lifecycle rule that expires
everything in `ocr-results` older than the retention window is correct for that bucket and for no shared one, and
the deployment page documents it.

It does delete the one orphan it can name. When a job is cancelled or removed while its result is being written, the
runner still holds that object's key at the moment it discovers the record is gone, so it deletes the object there.
That is not hunting for orphans, it is not dropping something it is still holding.

An expired identifier answers `JOB_NOT_FOUND` with a 404, the same as an identifier that never existed, and the
message says unknown or expired. The alternative was a tombstone, keeping the identifier and its expiry after the
result is dropped so that expiry can answer 410 Gone. Rejected as machinery that buys a distinction nobody acts on:
identifiers are 128 bit random tokens, so an identifier that reaches the service and is not held is an expired one
in practice, and a tombstone needs its own lifetime and its own bound.

### Decision 6: the queue is bounded twice, and a full queue is a 503 with its own code

Two bounds, because they bound different resources. Pages bound the wait, which is the only reason a caller cares:
the promise is that a newly accepted submission starts within the pages ahead of it multiplied by the per-page
allowance of the engine that reads each of them. The figures once given here, 2 h 30 min at the bound and about 33 minutes at the measured cost, were worked at one 45 s allowance and are superseded, because `fix-ocr-page-resolution` now owns the allowance and the promise derived from it. Documents bound the storage,
because every waiting submission's bytes sit on disk until it runs, and a queue bounded only in pages admits two
hundred single page submissions at 50 MB each.

At the platform's own typical document the two bounds bind at about the same point, which is a sign they are sized
against each other: eight waiting documents of twenty five pages is exactly two hundred pages.

The previous change rejected a count bound on its own admission gate, for a reason that was good then: a request
waiting on that gate was already bounded by its own deadline, so time was the honest bound, and a count bound would
have needed an overflow response it did not have. Neither half applies to the queue this change adds. A queued job
has no deadline running against it, so time bounds nothing, and the overflow response is a new code, which ADR-003
permits outright.

`QUEUE_FULL` with a 503 rather than the rate limiter's 429, because the two mean different things to a client. 429
says this caller is asking too often and the fix is for it to slow down. 503 says the service is temporarily out of
capacity and the fix is to come back, which is true regardless of who is asking, and it carries `Retry-After`
naturally. Overloading 429 would also make the rate limiter's own metrics lie.

### Decision 7: the wait is not charged to the reading budget, and that does not contradict the deadline capability

A document's reading budget starts when the worker starts reading it. Time spent waiting in the queue is not
deducted.

The existing requirement that a queued request counts its wait against its own budget exists for a stated purpose:
no inference is ever started for a caller who has already been told the request failed. That purpose is preserved by
construction rather than by arithmetic. No caller anywhere is holding anything, and no caller is ever told a
submission failed for waiting, so wall clock time spent in the queue has no claim on the answer's usefulness. What
bounds waiting is the queue page bound of Decision 6, which is why that bound is expressed in pages: it converts
directly into the longest possible wait.

Mechanically the job runner acquires the same admission gate before it starts the document's clock, so a document
never consumes a permit and a budget at the same time. The gate now has exactly one client, and it survives for a
reason that outlasts the second one: it is the mechanism that enforces `OCR_WORKER_COUNT`, and it stays correct if
that count is ever raised, which Open Question 4 says is now thinkable.

### Decision 8: cancelling a running job replaces the worker

Cancelling work that has not started is a list removal and needs nothing. Cancelling work that is running has two
possible mechanisms.

The cooperative one mirrors the deadline: signal the worker, and it stops at the next page boundary. It costs a new
cross-process signal, and it costs up to one page of continued inference, which is now about 10 s rather than 90.

The chosen one reuses `_rebuild_pool` with a third reason. The worker is replaced, the inference stops with the
process, and the next queued job starts as soon as the new worker has warmed, which ADR-004 measures at 5 to 15 s.

**Implementation correction, 2026-09-24.** "The worker is replaced" was not enough on its own, and the design said
it as though it were. `_rebuild_pool` tears the pool down with `ProcessPoolExecutor.shutdown(wait=True)`, and that
call waits for the work item already running, which for this service is a whole document rather than a page. A
cancel that only shut the pool down would therefore go on reading the exact document it was asked to stop, for up to
the document's entire reading budget. The replacement path now kills the pool's worker processes before it shuts the
pool down, and only on the cancel trigger: `stop_worker_pool(terminate=True)`. Reclamation and a broken pool keep the
draining behaviour they already had, because neither is asking the current document to stop. The kill reaches for
`ProcessPoolExecutor`'s own process table, because `concurrent.futures` offers no public way to stop a work item that
is already running, and the alternative is exactly the cooperative signal this decision rejected above.

The speedup narrowed this one and did not flip it. Replacement still needs no new machinery at all, where the
cooperative path needs a signal that has to survive a pool rebuild and be cleared correctly between jobs, and the
empty pool queue that Decision 4 of the previous change established is what makes replacement cheap. What changed is
the stopping time: replacement now costs a 5 to 15 s warm-up to save about 10 s of inference, so on that axis alone
the two are level, and replacement wins on machinery rather than on speed. The thing being reclaimed is also bigger
than one page: a cancel on a 100 page document at page five saves about sixteen minutes.

### Decision 9: progress is a file the worker writes between pages

The worker already has a per-page seam and already writes to the service's own directories. After each page it
writes the completed page count to a small file named for the job, by temp plus replace, and the API process reads
it when a status poll arrives or the list operation is served.

A shared `multiprocessing.Value` passed through the pool's initargs was the alternative. It is faster, and it is
worse here: it depends on synchronisation primitives surviving pickling into initargs under the spawn context on
both Linux and Windows, which is exactly the kind of platform-dependent behaviour this module's Windows test runs
keep discovering, and one counter tied to a pool does not survive a pool rebuild. Reading progress out of the
Prometheus multiprocess files, the way `is_engine_warm` reads warm-up, was also rejected: those counters are not
attributed per job, so they cannot answer how far this document has got.

A hundred writes of a few bytes across about seventeen minutes of inference is not a cost worth measuring.

### Decision 10: the result is a Markdown file in object storage, and the status answer carries its address

This inverts the first draft, which had the status answer carry the complete result inline so that collecting cost
no further call. That decision is kept here rather than deleted, because the reasoning that replaced it is only
legible next to it.

The owner's call, in his own words: use object storage, store text as Markdown files there, the main service can
download them, we already use S3 buckets so there is no reason not to.

What it is, concretely:

- When a document finishes successfully the runner renders the pages to Markdown and writes one object,
  `{job_id}.md`, to `OCR_RESULT_S3_BUCKET`, before it writes the terminal record. A record never claims success with
  no object behind it.
- The Markdown is the document's text and nothing else. One level-two heading per page naming the page number, then
  that page's recognised lines in reading order, one per line. No front matter, because the agent indexes whatever
  it fetches and would index a YAML block as body text, and because the record already carries the metadata.
- The status answer for successful work carries the bucket, the key, a presigned GET URL, and the bounded metadata
  that does not grow with the document: `schema_version`, `filename`, `language`, `page_count` and
  `processing_time_seconds`. The rule is one line long and worth stating as a rule: what is bounded stays in the
  status body, what grows goes to the object.
- The presigned URL is signed against `OCR_RESULT_S3_PUBLIC_ENDPOINT` for the record's remaining retention, so it
  can never outlive the object it points at, and it is regenerated on each status read rather than stored.
- Deleting the job deletes the object. The retention sweep deletes the object. Decision 5 has the ordering.
- The bucket is headed at startup and created if missing, the way `BucketInitConfig` does it in the agent, and a
  failure is a `WARNING` in the startup banner rather than a refusal to boot, which is the same "warn, do not
  refuse" posture the module already takes for the cgroup memory check.

Why the inline answer lost. It was sized against a forty page ceiling and a result the first draft estimated at
100 KB. At a hundred pages of a dense scan the result is megabytes, and a caller polls the status resource every few
seconds, so every poll would carry the risk of a multi-megabyte body and the last one would certainly carry it.
Object storage is also where the platform already puts documents, so a result in a bucket is a thing the agent's
ingestion pipeline already knows how to consume, gets range reads and lifecycle rules for free, and survives a
container recreate that a file on the service's disk does not.

What it costs, stated rather than waved at:

- This module gains an external service dependency, which it did not have. That is the real price, and Decision 3 is
  written to contain it: the record is local, so a bucket outage cannot stop the service accepting work, reading it
  or recording that something failed. What a bucket outage stops is delivery.
- An upload that fails after bounded retries fails the job with a record-level `RESULT_STORE_UNAVAILABLE` reason,
  which is retryable in the way `SERVICE_RESTARTED` is, because nothing was learned about the document. Losing
  seventeen minutes of reading to a bucket blip is the failure mode, and bounded retries are what keep it rare.
- Readiness is deliberately not wired to the bucket. A blip would flap `/ready` for a queue that is perfectly able
  to keep reading, and ADR-004's rule is that not-ready means the service cannot take work. The startup check and
  the job metrics are where a bucket problem shows.
- Collecting costs one more fetch, against the object store rather than against this service.
- Per-line `confidence` and `bounding_box`, which `OcrTextLine` carries today, are not in the Markdown. Nothing in
  the platform reads either: the agent flattens to text, the Bruno requests assert substrings and the e2e specs
  assert canaries. A caller that needs them later gets a structured sibling object beside the Markdown, and that is
  an addition rather than a change.
- The text the agent indexes changes shape slightly, because the Markdown carries page headings that the flattened
  JSON did not. That is an improvement for attribution and it is still a caller-visible difference, so task 11.1
  names it.

Rejected alternatives. Putting the results in the agent's `knowledge-base` bucket, because `ManualIngestionService`
lists and ingests what it finds there and would ingest OCR results as source documents. Returning bucket and key
only and making every caller bring credentials, because Bruno, curl and the e2e suite then cannot collect a result
at all and the change becomes untestable from outside Java. Returning a presigned URL only, because the agent
already holds an S3 client for that endpoint and bucket and key is the cheaper path for it.

`GET /v1/ocr/jobs/{job_id}` still answers with the state, and every non-terminal answer carries a poll hint,
`clamp(pages_remaining x allowance / 10, 1 s, 30 s)`, while every terminal answer omits it, so the absence of a hint
is itself the signal that there is nothing left to ask.

`DELETE /v1/ocr/jobs/{job_id}` means stop it if it is running, delete its result object, and forget it, in one verb,
because that is one intention rather than three. A separate cancel action plus a delete was rejected as two
operations, two tools and two sets of state rules for the one thing a caller wants.

**What that verb does depends on whether the work had finished, and the two spec requirements only agree this way.**
The lifecycle capability requires that a caller who cancels running work can then read a `cancelled` state, and that
a caller who deletes finished work gets `JOB_NOT_FOUND` on the next read. Both cannot be true of one behaviour, so
the verb has two: deleting work that has not finished stops it and leaves a terminal `cancelled` record, which is
readable until its retention window ends and carries no result; deleting work that has finished, in any of the three
terminal states, removes the record and its stored object together, after which the identifier answers
`JOB_NOT_FOUND` like any other unknown one. Both answer 204. Deleting twice therefore cancels and then forgets, and
a third call answers 404.

Submission answers 202 rather than 201, because the interesting fact is that the work was accepted and is not
finished. The `Location` header is relative and points at the status resource, and the identifier is in the body as
well so no caller has to parse a header to proceed.

### Decision 11: one queue, strict submission order, no priority classes

The question is whether a short document may overtake a long one, and the answer is no.

Shortest first was considered, because it is the scheduling policy that minimises mean wait and it would let a one
page image slip past a hundred page scan. It loses on three counts. It starves exactly the documents this change
exists to serve, since a steady trickle of single pages holds a long document out of the worker indefinitely. It
breaks the only promise the queue makes, because pages ahead multiplied by the allowance stops being an upper bound
on the wait once the order can change. And no caller can express priority anyway: the service has no authentication
and no tenancy, so priority would be a property of the document rather than of who asked, which is not what anybody
actually wants.

So: first in, first out, across everything, with the position and the pages ahead reported at submission, on every
status read, and in the list operation. A short document behind a long one waits, it is told how long, and it never
fails for having waited.

### Decision 12: the ascend-ai-agent migrates in this change

The first draft justified this decision with an arithmetic that the model upgrade has since falsified, and the
correction matters because it stops this change claiming a benefit somebody else already delivered.

What the first draft said: the agent slices every PDF page by page and dispatches four at a time, each with an
effective budget of `min(1 x 150, 300)`, and against one worker at about 90 s a page the first was served, the
second failed after paying for a whole page, and the third and fourth expired on the admission gate, so one page in
four succeeded.

What is true now: at about 10 s a page the four are served at roughly 10, 20, 30 and 40 seconds, all comfortably
inside a 45 s allowance and a 300 s read timeout. The four-way fan-out does not fail any more, and the upgrade fixed
that, not this change.

What this change still buys the agent, stated at its real size. The agent stops being bounded by a connection at
all, which is what lets it slice less aggressively or not at all in future, and which matters the moment any other
caller is using the worker at the same time: under contention the held request's budget was being spent on the
queue, and now nothing is. It gains a retryable-versus-not distinction on failure that it did not have. And it stops
being a caller of an endpoint that no longer exists, which on its own is the reason the migration is in this change
rather than after it.

Concretely, in `apps/ascend-agent/`:

- `AscendOcrClient.process(byte[], String, String)` keeps its signature and its return type, so `DocumentRouter` is
  untouched. Inside, it becomes submit, poll, fetch, delete: `POST {base-url}/v1/ocr/jobs` multipart with the
  existing `file` and `lang` parts, expect 202, read `job_id` from the body (the relative `Location` header is a
  cross-check, not the parse path), then `GET {base-url}/v1/ocr/jobs/{job_id}` until a terminal state, then fetch
  the Markdown object with the existing `S3Client` using the bucket and key the record carries, then `DELETE` the
  job.
- The record fields the agent parses, and the only ones it parses, are `job_id` on the submission answer, and
  `state`, `poll_after_seconds`, `error_code`, `error_reason` and `result.bucket` with `result.key` on a status
  answer. It treats `succeeded`, `failed` and `cancelled` as the terminal states and every other state as work
  still in flight, so how the two non-terminal states are spelled is the service's own choice and not a thing the
  agent can break. It reads neither the presigned URL, because it addresses the bucket directly, nor the progress
  and queue position, because it acts on the hint alone. A status answer that says `succeeded` without a bucket and
  a key is a contract breach and the client fails the page on it rather than indexing nothing.
- `parseResponse`, `extractPagesText` and `extractLinesText` are deleted, not adapted. They existed to flatten
  `pages[].lines[].text` into one newline-joined string, and the Markdown already is that string with page headings
  in it. The first draft's claim that `parseResponse` needs no change was true of an inline JSON result and is false
  of this one.
- The indexed text gains a level-two heading per page. That is a deliberate, caller-visible difference and
  `DocumentRouter`'s downstream chunking sees it, so task 11.7 asserts the canary text still survives chunking.
- While waiting it sleeps on its own worker thread for `poll_after_seconds`, floored and capped by configuration.
  The thread is already dedicated to that page, and `DocumentRouter`'s pool is fixed at `pdf-parallel-pages`, so at
  most four threads ever sleep at once. No new executor, no reactive rewrite.
- `app.ascend-ocr.api-path` moves from `/v1/ocr` to `/v1/ocr/jobs`. New properties: `poll-min-interval`,
  `poll-max-interval`, `poll-timeout`, `submit-retry-attempts`, `submit-retry-max-delay`.
  `application-docker.yaml` needs no change, because it overrides `base-url` only.
- The existing `S3Client` bean is reused for the fetch. It is already pointed at the same endpoint with the same
  credentials and path-style addressing, and it reads a different bucket, which is a parameter on the request rather
  than on the client.
- `app.ingestion.read-timeout: 300000` stops being the thing that bounds an OCR operation and becomes a per-call
  timeout on short calls, which is all it ever should have been. The bound on one document is `poll-timeout`, which
  defaults to 15 minutes: far above one page at the measured cost even behind the agent's own four-way fan-out, and
  deliberately below the service's own maximum lifetime, so the agent gives up and cancels rather than holding an
  ingestion open for hours while a wedged record waits to be swept.
- On a `failed` record it throws `IngestionException` carrying the record's code and reason, and on `cancelled` the
  same. On `SERVICE_RESTARTED` and on `RESULT_STORE_UNAVAILABLE` specifically it resubmits once, at most once per
  page, because those reasons exist precisely to say nothing was learned about the document. It never resubmits on
  `OCR_FAILED`, which says the opposite.
- When its own `poll-timeout` expires it issues the `DELETE` before throwing, so the service stops reading a
  document nobody will collect. The agent giving up has to cancel, or this change has reintroduced abandoned work
  through its only caller. A status read that itself fails is the one exception and is not followed by a cancel,
  because the call that would carry the cancel is the call that just failed, and what it abandons is bounded by the
  document's own reading budget, which is one page for everything this caller sends.
- It retries a submission only on a definitive 503 `QUEUE_FULL`, honouring `Retry-After` with bounded attempts and
  jitter, and never on a timeout or a connection error, because a lost response may be hiding an accepted job.
- `pdf-parallel-pages` stays at 4, and the number still has to stay at or under `OCR_JOB_QUEUE_MAX_DOCUMENTS`,
  which is 8.

Tests that move with it: `AscendOcrClientTest`, `AscendOcrClientResponseParsingTest`,
`AscendOcrClientLiveContractTest`, `DocumentRouterTest`, `DocumentRouterFileTypeRoutingTest` and
`DocumentRouterPdfExceptionTest`.

Two things the migration deliberately does not do. It does not change the fan-out, because per-page slicing is still
the right shape for a PDF whose pages the ingestion pipeline indexes separately. And it does not put ascend-ocr into
the agent's MCP connection list, because it is not there today and adding it is a separate decision with its own
tool-budget cost.

### Decision 13: the identifier is the credential, so it is random, it is never a path, and the bucket is never public

The service has no authentication. Anyone who can reach it can submit, and under this change anyone holding an
identifier can read a document's extracted text. So the identifier is 128 bits from a cryptographic random source,
URL-safe, and never derived from the filename, the content or a counter.

The identifier becomes part of a filename in the job store and part of an object key in the bucket, which makes it
an injection surface twice. Every identifier arriving from a caller is validated against a strict character and
length pattern before it is used to build any path or any key, and rejected as `JOB_NOT_FOUND` if it does not match,
so a traversal attempt is indistinguishable from a typo and never reaches the filesystem or the bucket.

Because the object key is the identifier, the bucket must not allow anonymous listing or anonymous reads. Listing it
would enumerate every result, and a public read would make the identifier's unguessability the only thing between
the internet and a document's text, with no rate limit in front of it. The deployment page states this as a
requirement of the bucket rather than as advice.

### Decision 14: three new codes, three record-level reasons, and no existing code changes meaning

`QUEUE_FULL` at 503, `JOB_NOT_FOUND` at 404 and `ENDPOINT_REMOVED` at 410 join the catalogue in
`exception_handlers.py` and in ADR-002. `SERVICE_RESTARTED`, `LIFETIME_EXCEEDED` and `RESULT_STORE_UNAVAILABLE` are
different in kind: they are failure reasons inside a job record and never HTTP statuses, because the request that
reads a failed record succeeded.

The record carries them in three fields, named here because Decision 12 pins the wire contract on them: `error_code`
holds the code, `error_reason` holds a human sentence, and `retryable` is a boolean that is true for exactly
`SERVICE_RESTARTED` and `RESULT_STORE_UNAVAILABLE`. The boolean exists so a caller acts on the contract rather than
on a hardcoded list of strings. `LIFETIME_EXCEEDED` is deliberately not retryable: a record wedged past the longest
legitimate wait plus the longest legitimate read is a defect, and resubmitting invites it again. A `cancelled` record
carries no code at all, because a cancellation is not a failure and the state says everything there is to say.

That last point is the one place where the shape of a failure changes, and it deserves saying plainly rather than
being discovered. A failure of the reading is a successful read of a record that says it failed, carrying a code.
`OCR_FAILED` means what it always meant, which is that the service tried to read this document and could not.

The input-limits requirement that refusals introduce no new error code is not contradicted. It governs refusals of
oversized input, and those still answer `FILE_TOO_LARGE`, including the page ceiling. None of the three new codes is
a refusal of oversized input.

### Decision 15: the model is given the identifier and its own tools, and no tool polls on its behalf

The tool could poll internally: `ocr_process` keeps its name and its shape, and underneath it submits, polls and
returns the finished result, so the model sees a synchronous tool and never learns a job exists. It is attractive
because a model has no sleep primitive, so anything that asks it to wait is asking it to burn turns.

It is rejected, because it is the removed synchronous path wearing a tool's name. A blocking tool holds a connection
for the length of the document, and the ceiling it hides behind is not one this service chose: it is the client's
own request timeout, 300 s in `spring.ai.mcp.client.request-timeout`. A hundred page document needs about 1000 s, so
the client gives up and the model is left holding an error and no handle while the work continues. It also makes the
two surfaces disagree about what a submission returns, which this change's own cross-surface requirement forbids.

So the tool surface offers `ocr_submit`, `ocr_job_status`, `ocr_cancel_job` and `ocr_list_jobs`, taking the same
arguments and returning the same records as their REST counterparts, raising the same codes with the surface's
existing `CODE: detail` convention.

Two costs are named rather than waved at.

A model cannot sleep, so a naive one polls in a tight loop. Every non-terminal status answer carries
`poll_after_seconds`, so the model is told when to ask rather than left to guess, and the status read is a file read
against the default sixty per minute rate limit, not the twenty per minute OCR limit, so a badly behaved poller
costs the service almost nothing and is throttled before it costs anything.

A model gets an address rather than text, and it may have no way to fetch it. That is a real regression on this
surface against the removed `ocr_process`, and it is accepted because there is no MCP caller of this module in the
platform today, so the cost is theoretical. The trigger that would change it is the first MCP caller that needs the
text in band, and the addition is an `ocr_fetch_result` tool that returns the object's content for an identifier the
service already holds, which needs no new guard because the service is fetching its own key from its own bucket.

What was deliberately not built is a bounded wait argument on `ocr_job_status`, which would let one tool call cover
thirty seconds of waiting. The trigger that would change it is one observation of a caller polling faster than the
hint, which the rate limiter and the job metrics both make visible.

### Decision 16: no idempotency key in this version

The `/api-design` skill asks for an `Idempotency-Key` on non-idempotent POSTs, and this change does not build one.
What keeps duplicates out is a rule rather than a store: the agent retries a submission only on a definitive 503
`QUEUE_FULL`, and never on a timeout or a connection error, because a lost response may be hiding an accepted job. A
retry that only ever follows a definitive refusal cannot duplicate anything. The queue bound is the backstop for
callers that do not follow the rule, because it converts duplicate submission from unbounded waste into a refusal.

What would change the decision is one observation of a caller, most likely an MCP client, submitting the same
document twice. At that point the key maps to the existing job identifier and inherits the retention window, which
is a small addition to a store that already exists.

### Decision 17: the removal is asymmetric, 410 on REST and gone on MCP

`POST /v1/ocr` answers 410 with `ENDPOINT_REMOVED` and names `POST /v1/ocr/jobs`, for one documented window. The
`ocr_process` tool is removed outright.

The asymmetry follows from how each surface is consumed. A REST caller has a URL compiled into it, it will call that
URL again, and the cheapest way to tell it what happened is to answer the call. A 410 with a code and a replacement
name is a better failure than a 404, because 404 reads as a typo and sends whoever is debugging it looking in the
wrong place.

An MCP client discovers its tools on every connection rather than holding a compiled URL, so a removed tool is a
tool the model stops being offered. Keeping a stub `ocr_process` that only raises would put a tool in every model's
context, cost tokens on every request, and invite the model to call it. There is nothing to soften, because no MCP
client of this module exists in the platform today.

The window is documented rather than eternal: the 410 exists so the callers this change does not own have one
release to notice, and the ADR amendment records that it is removed outright in the release after that.

### Decision 18: work in flight is listable, and that is a disclosure this change names rather than hides

`GET /v1/ocr/jobs` returns everything currently queued and running. One entry per piece of work, carrying the
identifier, the state, how many of the document's pages are done out of how many, how long it has been waiting or
running, and its position in the queue. `ocr_list_jobs` is the same thing on the MCP surface. The owner asked for it
as an operational need: without it, the only way to find out what the service is chewing on is to read logs or to
already hold an identifier.

Three properties fall out of the scope rather than out of extra machinery.

It is bounded. Only queued and running work is listed, so the list can never exceed `OCR_JOB_QUEUE_MAX_DOCUMENTS`
plus the one running document, which is nine at the defaults. No pagination, no cursor, no limit parameter.

It excludes finished records. That is what the owner asked for, and it also happens to be the smallest useful scope,
which keeps retained results out of the disclosure below.

It is read at the default rate limit rather than the OCR one, like the status read, because it is a directory listing
rather than inference.

Now the honest part. This service has no authentication, and Decision 13 makes the identifier the credential. A list
operation that returns identifiers therefore hands the credential for every piece of work in flight to anybody who
can reach the port. Whoever calls it can wait for those jobs to finish and then read their results. That is not a
subtlety, it is the access control of this service, and the list operation is a hole in it for as long as the
service is reachable by more than one party.

Two things are true at once and both are recorded. It is acceptable today, because the deployment is single user on
a private network and the operational need is real. It stops being acceptable the moment this service has more than
one user, and the answer at that point is authentication, scoping the list to the caller's own work, and nothing
less. The honest thing is to revisit it when authentication arrives rather than to pretend the problem does not
exist.

The cheap mitigation was considered and rejected on the owner's own stated need. Truncating the identifier in the
list, to eight characters, would make the list useful for correlating with logs and useless as a credential. It
would also make it useless for the thing an operator most wants to do with it, which is cancel a stuck job, because
cancelling takes the whole identifier. A list you cannot act on is a log line with extra steps.

## What the four pending capabilities now say

`stop-ocr-getting-stuck-on-large-jobs` is implemented but not archived, so its four capabilities are still deltas.
Eight of its requirements hold as written, with "synchronous request" read as "document", and two are superseded.
Task 12.1 carries the reconciliation into whichever change archives first.

- A request budget is derived per page and capped overall. Superseded. The per-page term survives, the overall cap
  does not, because the cap was `OCR_REQUEST_TIMEOUT` and no request is capped. The replacement invariant is that a
  document's budget is its page count multiplied by the allowance, and the page ceiling is what makes that bounded.
- Requests waiting for the worker hold their own deadline. Superseded outright. Nothing waits for the worker holding
  a deadline any more. The purpose it served, never starting inference for a caller already told the request failed,
  is preserved by construction, because no caller is ever told a submission failed for waiting.
- An expired request stops computing, from a duration, checked between pages. Holds unchanged. Documents go through
  the same worker and the same `_predict_pages` loop.
- An expired request fails with the existing OCR failure code and returns nothing partial. Holds. A failed record
  carries `OCR_FAILED`, no page content and no result object. Decision 14 records that the code now arrives inside a
  successfully read record.
- One job at a time, and the limit is explicit. Holds and is reinforced: the job runner acquires the same gate and is
  the only thing that does. Its stated reason changes from memory to the queue's promise, which Decision 7 and Open
  Question 4 both record.
- A worker that will not stop is replaced, a broken pool is rebuilt, a killed worker's files are reclaimed. Holds,
  with cancellation added as a third trigger for the existing replacement path and the sweep horizon retargeted at
  the longest legitimate document.
- The pixel ceiling, the bomb guard, and refusals reusing the existing error model. Holds. All of them run at
  submission, with the same codes. Overtaken on 2026-09-24 for the pixel ceiling, which `fix-ocr-page-resolution`
  replaces with shrinking and a source pixel ceiling for decompression bombs only.
- A document with too many pages to finish is refused up front, derived from the per-page allowance and the ceiling.
  Holds, with the derivation inverted: the ceiling is now the page count and the reading ceiling is derived from it,
  rather than the reverse, so the invariant is true by construction.
- Readiness reports not-ready exactly when the service cannot take work, and busy stays ready. Holds. A long
  document is busy and in budget, so the status is unchanged, and the two new fields are additive in the way
  ADR-004's amendment already established for `queue_depth`.
- The memory bounds capability. Its mechanisms hold and its numbers do not. The detector bound and the pixel ceiling
  keep their deployed values and keep doing their job. Overtaken on 2026-09-24: `fix-ocr-page-resolution` deletes the
  pixel ceiling and moves the detector bound into per-request quality modes. Every figure fitted against `PP-OCRv5_server_det` is now an
  upper bound rather than a description for every language but `ru` and `korean`, which is what
  `upgrade-ocr-to-ppocrv6` task 4.6 exists to correct, and task 1.2 here reports into the same place.

## Risks / Trade-offs

Every duration rests on a synthetic page. The measurements are clean rendered text, not a scan, and a real scan may
detect many more regions than a clean render of the same words. Mitigation: the allowance carries 4.5 times the
measured worst case rather than the 1.9 the previous change used, the memory conclusion is separately safe because
detection is bounded by input size rather than by content, and task 10.6 runs the end-to-end specs against real
scanned documents before the container limit is touched. What is at risk if the allowance is wrong is a legitimate
page killed mid-document, which is why the headroom is deliberately generous rather than tight.

A long document delays every document behind it. Mitigation: the delay is bounded by the queue page bound, each
page at its own engine's allowance, which `fix-ocr-page-resolution` now owns (the 2 h 30 min and 33 minute figures
once given here were worked at one 45 s allowance and are superseded), it is reported as pages ahead at submission
and on every status read, the whole queue is visible through the list operation and on `/ready`, and nothing is ever
failed for having waited. It is the physics of one worker rather than a regression.

This module gains an external service dependency it did not have. Mitigation: Decision 3 keeps the record local so a
bucket outage cannot stop the service accepting, reading or recording a failure, the upload retries before it gives
up, the failure reason it gives up with is retryable, and the startup check reports a misconfigured bucket in the
banner before anything is submitted.

Every caller of this module has to be rewritten in this change. Mitigation: there is exactly one in-platform caller
and it is migrated here, the REST surface answers 410 with a replacement name for callers outside the platform, and
the Bruno collection and the e2e suite are rewritten in the same change rather than left red.

A result is a document's extracted text in a bucket for up to an hour, on a service with no authentication,
addressed by an identifier that the list operation hands out for work in flight. Mitigation: the identifier is the
credential and is random, the bucket allows neither anonymous listing nor anonymous reads, callers can delete early,
the retention window is one setting and is now half what the first draft chose, and Decision 18 records the list
operation's disclosure as a thing to fix with authentication rather than as an accepted cost forever.

The page ceiling rests on one carried-forward number. The 11.5 MiB a page retained result was fitted against the old
detector and is unmeasured on the new pair. Mitigation: it is the term least likely to have moved, because it is
recognised text rather than model weights, task 1.2 measures it on a hundred page document before anything relies on
it, and at the recommended 3 GB limit the ceiling still leaves about 57 pages of headroom if the old figure is
exactly right.

The container limit is still 12 GB for a service that needs about 1.1. Mitigation: the recommendation and its
arithmetic are recorded above, the change deliberately does not make the edit, and task 2.7 waits on the end-to-end
run rather than on an opinion.

A model with no sleep primitive can poll in a tight loop, and a model given an address may not be able to fetch it.
Mitigation: the poll hint on every non-terminal answer, the default rate limit on the status read rather than the
OCR one, and Decision 15's stated triggers for a bounded wait and for an `ocr_fetch_result` tool.

Two surfaces on two protocols is more to keep in agreement, and this change makes it four operations rather than
three. Mitigation: one service layer beneath both, the existing cross-surface test module extended, and a spec
requirement that says agreement in observable terms.

## Migration Plan

An image rebuild, a compose edit, a bucket, an agent rebuild, and a rewrite of every caller this repository owns.
There is no schema and no data migration, because there is no persisted state today.

Ordered, because the agent and the service cannot cross over silently:

1. Make sure the object store is reachable and the credentials exist. The service heads
   `OCR_RESULT_S3_BUCKET` at startup and creates it when missing, so the only prerequisite is an endpoint and a key
   pair that may create and write. An operator who prefers to pre-create the bucket may, and should add the
   lifecycle rule Decision 5 describes at the same time.
2. Deploy the image. Every new setting except the credentials has a default that is safe on its own.
   `POST /v1/ocr` starts answering 410 with `ENDPOINT_REMOVED` at this moment, and `ocr_process` stops being
   advertised.
3. Deploy the agent, built from the same commit. Between steps 2 and 3 the agent's OCR path is down, which is why
   the two steps are one deployment rather than two, and why the change is not done until both are built.
4. Edit `compose.yaml`: remove `OCR_REQUEST_TIMEOUT`, remove the `OCR_PAGE_TIMEOUT_SECONDS` override now that the
   code default is the settled value, and add the result store endpoint, bucket and credentials. The service ignores
   a leftover `OCR_REQUEST_TIMEOUT`, so that part of the edit is tidiness rather than a gate.
5. Optionally mount a volume at `OCR_JOBS_DIR` if job records must survive a container recreate. Without it, the
   records survive restarts but not recreates, and the results survive either way because they are in the bucket.
6. Only after the end-to-end specs have run against real scanned documents, consider lowering the container memory
   limit from 12 G toward the recommended 3 G. That is task 2.7 and it is deliberately last.

Rollback is reverting both images together. A caller that was rewritten against the job surface stops working when
the service goes back, which is the honest consequence of a breaking change, and it is why rollback is stated as a
pair rather than as a single service revert. Job records left on disk by the rolled-back version are inert files
that nothing reads, and result objects left in the bucket are collected by the lifecycle rule.

## Open Questions

None of the five below is a gate on this change. The decision that every request is a job does not depend on any of
them.

1. What does a real scanned document cost per page, as opposed to a synthetic page of clean rendered text? This is
   the one that matters, because the allowance and everything derived from it carry headroom for exactly this
   unknown. Task 10.6 answers it from the end-to-end run, and the answer either confirms each engine's allowance or
   moves it, and every derived duration moves with it. The single 45 s allowance this question was first written
   against is superseded, and `fix-ocr-page-resolution` now owns the allowances and the headroom they carry.
2. What does a hundred page document actually peak at, and what does its Markdown result weigh? Tasks 1.2 and 1.3
   measure them. The first confirms the per-page term the page ceiling leans on, the second confirms the retained
   record cap's storage figure.
3. Should the container limit be 3 GB, and is the retention window right at an hour on a service with no
   authentication? Both are owner trades with the arithmetic recorded above, both are one setting, and neither
   changes an interface.
4. Should the worker count rise above one, now that one call costs 440 MB instead of most of the container?
   (Superseded 2026-09-25: one straightened call is priced at 2859 MiB of the 4 GiB container, so a second worker
   does not fit, see `fix-ocr-page-resolution` design.md Decision 10.) It was
   a memory constraint and it is not one any more. What stops it here is that nothing has measured two concurrent
   inferences on this hardware, and that every queue promise in this design is written against one worker, so
   raising it is a change to the promise as well as to the setting. It is the first time the question has been
   answerable at all, which is why it is recorded rather than dropped.
5. Answered on 2026-09-24 by `fix-ocr-page-resolution`, which deletes the setting, reads an oversized page shrunk and keeps only a decompression-bomb refusal. Should `OCR_MAX_INFERENCE_PIXELS` rise? The 300 dots per inch measurement shows that a page's own resolution no
   longer drives memory, because the detector bound caps what detection sees, so the memory argument for a 2.5
   megapixel ceiling is gone. What remains is an accuracy and a time argument that nothing here has measured, and
   the page that was measured is itself above the current ceiling. It is a separate change with its own evidence.

Two questions the first draft carried are deleted rather than answered, because the model upgrade made them
meaningless. Whether the fitted 5302 MiB per megapixel holds at higher ceilings is void, because that constant
described a detector this service no longer runs for any language but `ru` and `korean`. Whether splitting a page
into tiles is a sound production technique is void as posed, because it was a way to fit a page into memory and a
page now fits nineteen times over.
