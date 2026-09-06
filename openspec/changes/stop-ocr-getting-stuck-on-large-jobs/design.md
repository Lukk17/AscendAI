## Context

See [proposal.md](proposal.md) for the motivation and the measurements. The constraints below were each verified
against the repository or the module's own `.venv`, never assumed.

- One inference worker. `_WORKER_POOL_SIZE = 1` in
  [ocr_service.py](../../../PaddleOCR/src/service/ocr_service.py), a `ProcessPoolExecutor` on a `spawn` context.
  The docstring gives the reason: PaddleOCR's CPU inference holds the GIL continuously, so running it in the API
  process would freeze the event loop.
- The timeout is `asyncio.wait_for(loop.run_in_executor(...), timeout=settings.OCR_REQUEST_TIMEOUT)` in both
  [rest_endpoints.py](../../../PaddleOCR/src/api/rest/rest_endpoints.py) and
  [mcp_server.py](../../../PaddleOCR/src/api/mcp/mcp_server.py). It cancels the awaiting coroutine and nothing else.
- The library offers a page-by-page seam. `PaddleOCR.predict()` in
  `paddleocr/_pipelines/ocr.py` is `list(self.predict_iter(...))`, and `predict_iter` is public and returns the
  paddlex generator, which yields one result per page. Consuming that generator instead of the list is what makes a
  per-page deadline possible without taking over rasterization.
- PDF pages are rendered at a fixed scale. `PDF_RENDER_SCALE = get_flag_from_env_var("PADDLE_PDX_PDF_RENDER_SCALE",
  2.0, float)` in `paddlex/utils/flags.py`, passed as `PDFReader(zoom=PDF_RENDER_SCALE, ...)` in
  `paddlex/inference/common/batch_sampler/image_batch_sampler.py`. A scale of 2.0 on PDF points is 144 dpi. The
  only other bound on that path is `DEFAULT_MAX_IMAGE_PIXELS = 178_956_970`, which no real page approaches.
- Raw images bypass rasterization entirely. The same sampler appends the image path straight to the batch. The only
  thing between an image and the detector is the detection resize, configured `limit_side_len: 64`,
  `limit_type: min`, `max_side_limit: 4000` in `paddlex/configs/pipelines/OCR.yaml`. With `limit_type: min` that
  resize only ever upscales an image whose shorter side is below 64 px, so for every real image the ratio is 1.0
  until the 4000 px long side clamp fires. That clamp admits 16 megapixels of detector input on a square image,
  which the measured cost model below prices at six times the container limit, so it bounds nothing that matters.
- The detector's resize is overridable from the constructor. `text_det_limit_side_len` and `text_det_limit_type` are
  parameters of `PaddleOCR.__init__` in `paddleocr/_pipelines/ocr.py`, mapped onto
  `SubModules.TextDetection.limit_side_len` and `.limit_type` in the pipeline configuration. They are two arguments
  on the `PaddleOCR(lang=language, enable_mkldnn=False)` call this service already makes, and they are the whole of
  Decision 11.
- A broken pool stays broken. `ProcessPoolExecutor` marks itself permanently broken when a worker dies, and nothing
  in `ocr_service.py` ever rebuilds it: `start_worker_pool` runs once from the lifespan and `get_process_pool`
  returns whatever the module global holds. Verified live after the OOM kill: every request returned 500 instantly,
  no worker process existed, the container stayed in that state for about five hours, both `/health` and `/ready`
  reported healthy throughout, and restarting the container was the only recovery.
- The worker writes the upload to a `tempfile.NamedTemporaryFile(suffix=..., delete=False)` and removes it in a
  `finally`. A killed worker never runs that `finally`, so every kill leaks one file of up to `MAX_FILE_SIZE_MB` in
  the container's temporary directory.
- Pillow's own bomb guard is weaker than it looks. `MAX_IMAGE_PIXELS` defaults to 89,478,485, and
  `_decompression_bomb_check` only raises above twice that, warning in between. It cannot be the guard on its own.
- The error model is fixed: `OCR_FAILED` 422, `FILE_TOO_LARGE` 400, `UNSUPPORTED_FILE_TYPE` 400, `UNSAFE_URI` 400,
  `DOWNLOAD_FAILED` 502, `INTERNAL_ERROR` 500 (`src/api/exception_handlers.py`, ADR-002).
- The liveness and readiness split is already decided in ADR-004: `/health` is liveness and carries the Docker
  healthcheck, `/ready` answers 200 in both states with the condition in the body.
- Container limits are 12 GiB and 4.0 CPUs (`docker-compose.yaml`), and `apply_cpu_thread_limit()` already caps the
  intra-op thread pool to the CPU limit, so one inference already saturates the cores.
- The test gate is `--cov-fail-under=100` with `--cov-branch`.

## Goals / Non-Goals

Goals:

- A budget that a healthy document can meet, and that a pathological one cannot exceed.
- A stop that stops. Bounded, stated, and measured in pages rather than in hope.
- A queue whose waiting requests cannot become orphaned work.
- One statement, in one place, of the concurrency the memory ceiling depends on.
- A readiness answer that is false exactly when the service cannot take work, and true when it is merely busy.
- A refusal that happens before allocation, using the error model that already exists.
- A bound on what one inference costs that does not depend on the caller behaving, since the caller controls the
  pixel count and nothing else currently does.
- A service that comes back on its own after a worker dies, instead of answering 500 until someone restarts it.
- Every number derived from the measured cost model, and every number that is an accuracy or a product trade left
  to the owner with its consequence stated.

Non-Goals:

- Making OCR faster. Nothing here changes what inference costs. It changes what happens when that cost exceeds the
  budget.
- Explaining the remaining 6 percent of the cost curve. The measurement below accounts for 94 percent of the
  transient and that is enough to act on. The residual is characterised, not decomposed.
- Changing the model pipeline. All five models stay, by the owner's decision.
- Asynchronous job submission. A caller still holds the connection for the duration. If the measured per-page cost
  makes that untenable for large documents, that is a separate change and this one surfaces the evidence for it.
- Reading a page at higher quality than the library's fixed rendering resolution. Decision 10 records why, and
  building a knob for it is explicitly out of scope.
- Raising the worker count. Decision 5 makes the cap explicit rather than removing it.
- Choosing the deployed detector bound. Decision 11 builds the setting, states the three measured candidates with
  what each costs in memory and in accuracy, and leaves the value to the owner because it trades small text against
  memory on his own documents.
- Retrying a request whose worker died. Decision 12 rebuilds the pool and fails the request, because the input that
  killed the worker is the input a retry would feed it again.

## The measured memory model

Everything in this section was measured against the running container after this change was first written. It
answers the question the change originally carried as an open task, and two of its consequences change what has to
be built.

The fit. Peak resident memory for one call is

```text
peak_MiB = 635 + 5302 x megapixels_of_the_largest_single_page + 11.5 x pages
```

The slope is transient: 5302 MiB, about 5.3 GiB, per megapixel of input to one inference. It was fitted across six
input sizes from 0.016 to 0.901 megapixels with a correlation of 0.9993. The intercept covers the process and one
warm engine. Each further cached language adds 143 MiB, and the cache holds eight, so a worker that has served every
language it supports carries 1636 MiB before it reads anything.

Pages are cheap. Pages are already processed one at a time and each rendered image is released, so a page costs only
the 11.5 MiB its result retains. Peak is set by the largest single page and not by the length of the document. An A4
page at the library's fixed 144 dpi is 1190x1684, 2.004 megapixels, so one A4 page costs 11,260 MiB and twenty five
of them cost 11,547 MiB. Page count does not become the binding term until about ninety pages, which is where
11.5 MiB per page finally consumes the 1028 MiB an A4 page leaves under the 12,288 MiB container limit.

One ordinary page therefore sits at 92 percent of the container limit before the engine cache is counted. On a
worker that has served all eight languages the same page reaches 12,261 MiB, twenty seven mebibytes under the
limit, which is indistinguishable from over it the moment anything else in the process moves.

Where the cost goes. Text detection is 94 percent of the transient, so 4984 MiB per megapixel is detection and
318 MiB per megapixel is everything else. The other four models together account for 170 MiB. The owner's decision
to keep all five is nearly free, and it is settled rather than open.

Why detection is that large. Not the model. Detection is configured `limit_type: min` with `limit_side_len: 64`, a
minimum-side limit, which only ever scales an image up, so every real page reaches the detector at whatever
resolution it was rendered at. The detection model was exported expecting a long side of 960. The only upper clamp
on that path is `max_side_limit: 4000`, which prices at six times the container limit and so bounds nothing.
Decision 11 bounds it properly.

Two independent checks of the fit. The killed job's input is still in the container, twenty pages of A4: the model
predicts 11,259 MiB against a recorded peak of 10,929 MiB and an out-of-memory kill, which is within three percent.
The earlier kill was a 4.35 megapixel raw image, for which the model predicts 23,699 MiB against a 12,288 MiB
limit, which is why it died.

One correction to the proposal's account. That kill did not come from the container limit, which was never reached.
The host virtual machine has sixteen gigabytes, was running twenty eight containers, and exhausted its swap. The
container limit is an upper bound on what this service may take and not a description of what the host can give it,
which is why every budget below is written as a chosen resident ceiling rather than as the container limit.

One hypothesis refuted. The plateau in the original observation was attributed to the allocator holding memory it
had finished with. Returning allocator memory to the operating system recovers about two percent, so the plateau is
the largest page's transient and the memory is genuinely in use.

## The numbers, and where each comes from

Every value below is derived. The time values still rest on a timing measurement that has not been taken. The two
memory values are now derived from the fitted model above rather than bracketed, and what remains open about them is
a budget and an accuracy trade, both of which belong to the owner rather than to this design.

| Value | Default | Where it comes from | Open? |
|---|---|---|---|
| Worker count | 1 | Today's `_WORKER_POOL_SIZE`, unchanged. It is a memory constraint: peak is one job's cost multiplied by this value, and one job's cost is already most of the container limit. See Decision 5. | No |
| Per-page allowance | 120 s | The one live observation: a twenty page document had consumed more than 2100 s of worker time without finishing, so the average page on that document cost at least 105 s. 120 s is the first round value above the observed floor. | Yes, task 1.2 |
| Absolute request ceiling | 300 s, unchanged for now | Today's deployed `OCR_REQUEST_TIMEOUT` in `docker-compose.yaml`. Kept until measured, because changing it is a product decision about how long a caller holds a connection. | Yes, task 1.3 |
| Dispatch margin | 5 s | The worker must give up before the parent does. Covers pickling the arguments, the spawn-context handoff, and the result trip back. | Yes, task 1.2 |
| Detector long-side bound | none, which is today's behaviour | Decision 11. Three candidates are measured, 960, 1280 and 1536, with what each costs in memory and in detected lines. The deployed value trades small text against memory on the owner's own documents. | Owner decision, task 1.5 |
| Maximum pages | derived, not configured | `floor(ceiling / per-page allowance)`. At the provisional values that is 2. It is a deadline artifact and not a memory constraint, which the restatement below shows. | Follows its two inputs |
| Reclamation grace | derived, not configured | `per-page allowance + dispatch margin`. The latest a healthy worker can legitimately return is one page's inference after its own budget expired, plus the trip back. | Follows its two inputs |
| Pixel ceiling for one inference | 1,720,000, the unbounded row of the table below at 90 percent of the container limit | Derived from the fitted model with no detector bound, which is what the service survives today, at a budget that leaves headroom because the host measurement shows the container limit is not what the host can actually give. It replaces the provisional 2,500,000, which was bracketed between the one page size known to survive and the one known to die and is not survivable unbounded. The deployed value comes from the pair in tasks 1.4 and 1.5. | Owner decision on the budget, plus task 1.6 |
| Consecutive pool rebuild attempts | 3 | Decision 12. Enough to survive a transient kill, few enough that a genuine crash loop stops and stays visibly not-ready instead of respawning forever. | No |

Two numbers deliberately are not configuration. The maximum page count and the reclamation grace are computed from
the two time settings, so they cannot drift out of agreement with them. An operator tunes them by tuning the times.

### The pixel ceiling, recomputed

The ceiling is now derived rather than bracketed, and it depends on the deployed detector bound, because the bound
decides how much of the 5302 MiB per megapixel a large input still buys.

Write the budget down first. Under a chosen resident ceiling of R MiB, one call may use R minus what the worker
already holds: 635 MiB of process and first engine, 1001 MiB for the other seven cached languages, and 11.5 MiB for
each page of the document. At R = 12,288 MiB with a full cache and a twenty five page document that leaves
10,365 MiB for the transient.

With the detector bounded to a long side of L, detection sees at most L x L pixels whatever the input's shape, so
the worst case over all aspect ratios is

```text
ceiling_MP = (R - 635 - 1001 - 11.5 x pages - 4984 x L x L / 1,000,000) / 318
```

With no bound the whole 5302 applies to the input's own pixel count, the L term disappears, and the divisor is 5302.

At a full engine cache and a twenty five page document:

| Detector bound | Ceiling at R = 12,288 MiB, the container limit with no headroom | Ceiling at R = 11,059 MiB, 90 percent of it |
|---|---|---|
| none, today | 1.95 MP | 1.72 MP |
| 1536 | 1.95 MP | 1.72 MP |
| 1280 | 6.9 MP | 3.1 MP |
| 960 | 18.2 MP | 14.3 MP |

Four things to read off it.

Without a bound the ceiling sits below A4's 2.004 megapixels at any budget that keeps headroom, so the service would
refuse the page it exists to read. US Legal at 2.47 MP is already refused even at the full container limit.

The provisional 2,500,000 is not safe in today's configuration. An unbounded 2.5 MP input costs 15,178 MiB on a
worker with a full cache, which is over the limit. It becomes comfortable at 7311 MiB once the detector is bounded
to 960. The old ceiling was not wrong about which pages matter, it was wrong about what they cost.

A 1536 bound buys nothing in the worst case. A square page bounded to 1536 is 2.36 megapixels of detector input,
which is already above the ceiling, so the ceiling binds first and the bound never fires. It helps only inputs whose
long side exceeds 1536.

A 960 bound is what turns an ordinary twelve megapixel photograph from a refusal into a job the service can serve.

The extrapolation is named rather than hidden. The 318 MiB per megapixel residual was fitted between 0.016 and 0.901
megapixels, and the 960 row uses it twenty times beyond that range. Task 1.6 confirms it at the top of the intended
range before any ceiling much above the standard page sizes is deployed. Until it reports, the defensible ceiling is
one that covers the standard page sizes, roughly where the provisional 2,500,000 already sat, deployed together with
a detector bound, since that combination uses the residual barely beyond the range it was fitted in. The same value
without a bound is not defensible, for the reason two paragraphs above, and the larger values in the 960 row are not
defensible either until 1.6 reports.

### The page count limit, restated

The deadline arithmetic is unchanged. The limit is `floor(absolute ceiling / per-page allowance)`, which is 2 pages
at the provisional 300 s and 120 s. What the measurement changes is why.

Memory does not cap page count anywhere near there. A page retains 11.5 MiB, so under a 12,288 MiB resident ceiling
an unbounded A4 job runs out of memory at about ninety pages counted from a fresh worker, and an A4 job whose
detector is bounded to 960 costs 5518 MiB on a worker with a full cache and does not run out until roughly 590
pages.

So the two page limit is entirely an artifact of the deployed 300 s ceiling. The consequence for the owner is
direct: a service that must read twenty page documents needs an absolute ceiling of twenty per-page allowances, and
the memory that decision costs is 230 MiB rather than a multiple of anything. What it costs instead is how long a
caller holds a connection, which is the trade task 1.3 puts to the owner.

## Decisions

### Decision 1: a per-page allowance under an absolute ceiling, not one number for both

The present budget is one number covering an entire document, which fails a healthy twenty page job for being
twenty pages long. A per-page deadline is the obvious replacement and, on its own, it is worse: it lets a thousand
page document run for a thousand allowances, which is days.

So both, and the effective budget for a request is `min(pages x per_page_allowance, absolute_ceiling)`. The per-page
allowance is what makes a long healthy document legal. The ceiling is what makes an absurd one illegal. Neither
alone does both jobs.

The page count is not known at the request boundary for a raw image, which is always one page, nor is it worth
guessing for a document. It is read from the document header by the same inspection that enforces the pixel
ceiling and the page count limit (Decision 7), so it costs nothing extra.

Alternative considered: per-page only, with no ceiling. Rejected above.

Alternative considered: ceiling only, raised to a large value such as an hour. Rejected. It admits the thousand
page document, and it makes every failure mode take an hour to appear.

### Decision 2: the worker enforces its own deadline, page by page, from a duration

`asyncio.wait_for` cannot stop a `ProcessPoolExecutor` task. Nothing outside the worker process can, short of
killing it. So the stop has to be cooperative, and cooperative means the worker holds the deadline and checks it.

Three properties of that, each load-bearing:

- The parent passes a remaining duration, not a wall clock deadline. `time.monotonic()` is per-process and its zero
  point is arbitrary, so a timestamp taken in the API process means nothing in the worker. The worker reads its own
  `time.monotonic()` on entry and adds the duration it was given.
- The worker's budget is the request's effective budget minus the dispatch margin, so the worker gives up slightly
  before the parent rather than slightly after. That is the safe direction: the parent then sees a clean failure
  from a live worker instead of a cancellation against a worker it has to reason about.
- The check happens between pages, which is the only seam the library offers. `predict()` is
  `list(predict_iter(...))`, so switching to `predict_iter` and consuming it page by page costs nothing and gives a
  check point per page. The honest consequence is that the granularity of the stop is one page: a worker that
  blows its budget in the middle of a page keeps going until that page finishes. Decision 3 covers the case where
  that overrun is unbounded.

Alternative considered: a watchdog thread inside the worker that raises into the inference thread. Rejected. The
inference call is native code holding the GIL, so an asynchronous exception is not delivered until it returns,
which is the same page boundary with more machinery.

Alternative considered: `signal.alarm` inside the worker. Rejected for the same reason on the same grounds, plus it
does not exist on Windows, where the module's tests run.

### Decision 3: a worker that will not return is replaced, and the queue design makes that cheap

Once the parent's budget has fired, the worker has at most one page's inference plus the trip back before it should
be finished. Past the reclamation grace it is not coming back, and it is holding the only worker.

The parent then discards the pool and builds a new one. The cost is the engine warm-up, five to fifteen seconds by
ADR-004's measurement. What it explicitly does not cost is other people's queued work, and that is a consequence of
Decision 4: because requests wait on an admission gate in the API process rather than inside the pool's own queue,
the pool queue is always empty, so there is never anything in it to lose. The two decisions hold each other up.

Readiness reports not-ready for the duration of the replacement, which is the honest answer and is the one case
`/ready` exists for.

Alternative considered: restart the container on a stuck worker, by making `/health` reflect worker state. Rejected.
It is a strictly larger hammer for the same nail: it throws away the warm engine, every queued request and the HTTP
listener, to fix something a worker replacement fixes on its own. It also contradicts ADR-004, whose `/health`
means "the process is wedged so badly it cannot respond", which is not true here.

Alternative considered: terminate the individual child process and let `ProcessPoolExecutor` heal itself. Rejected.
Reaching into the executor's private process list to do that couples this service to a CPython implementation
detail, and with a pool of one there is nothing to save by being surgical.

### Decision 4: requests queue on an explicit gate in the API process, holding their own deadlines

Today a request is submitted to the pool immediately and waits in the pool's queue, invisible, while its
`asyncio.wait_for` counts down. When it finally reaches the worker, the worker has no idea how much of the budget
was spent queuing, so it starts a job whose caller may already have given up. That is the mechanism by which one
abandoned job poisons everything behind it.

Instead, requests wait on an admission gate in the API process, with as many permits as there are workers. Three
things follow, and each of them is a defect fixed:

- A request that runs out of budget while waiting fails at the gate and is never dispatched. No inference is ever
  started for a caller who has already been told the request failed.
- A request that is admitted after waiting is dispatched with the budget it has left, computed at the moment of
  dispatch, not with a fresh one. The duration the worker receives is therefore truthful.
- The pool's own queue is always empty, which is what makes replacing a worker cheap (Decision 3).

Queue depth is exposed as a metric and in the readiness body, because "how many are waiting" is the number an
operator needs to tell a busy service from a stuck one.

Alternative considered: bounding the queue by count and refusing beyond it. Rejected as unnecessary machinery. The
queue is already bounded by time, since every waiter fails at its own deadline, and a count bound would need a
response for the overflow case, which means either a new error code or overloading the rate limiter's 429. Time is
the honest bound here, and it needs nothing new.

### Decision 5: the worker count is one setting, and it governs both the pool and the gate

The safety of everything above rests on there being one job in flight. That fact currently lives in a private
module constant with a comment, which is not where a load-bearing constraint belongs.

It becomes a setting with a derived meaning: the pool size and the gate's permit count are both read from it, so
they cannot disagree, and a test asserts they agree. The memory ceiling in the documentation is stated as one job's
peak multiplied by that value, so raising it is visibly a memory decision rather than a throughput tweak.

The owner's position is recorded rather than reinterpreted: "we can always limit max worker to 1 so we will have
fixed size at all times only reading will took longer which is not a problem". The measurement confirms the premise:
the size is fixed per call, because peak is set by the largest single page and not by document length.

What the code and the documentation both fail to say is that this cap is a memory constraint. The module constant is
justified by the interpreter lock, which is a throughput and event-loop argument, and the architecture pages
describe the single worker purely as a throughput limit. Neither mentions memory, so someone could raise it for
throughput and double the ceiling without knowing. The number makes the stake plain: one unbounded A4 page costs
11,260 MiB against a 12,288 MiB container limit, so two workers is not slower, it is dead. The stated ceiling
becomes

```text
service_peak_MiB = worker_count x per_worker_peak_MiB
per_worker_peak_MiB = 635 + 143 x (cached_languages - 1) + 5302 x megapixels_of_the_largest_page + 11.5 x pages
```

with the detector bound of Decision 11 replacing part of the 5302 when one is deployed. That sentence goes into
`PaddleOCR/AGENTS.md`, the README and the arc42 pages beside the setting, so raising the worker count reads as a
memory decision rather than as a throughput tweak.

### Decision 6: readiness gains a second condition, liveness gains nothing

ADR-004 already separates the two questions and this design does not redefine either. It adds the condition ADR-004
did not need at the time, because the service could not previously be stuck.

`/health` stays exactly as it is: the API process answers, therefore it is alive. It never consults the worker.
Making it fail on a stuck worker would restart the container, and Decision 3 explains why that is the wrong
response.

`/ready` reports ready only when the engine is warm and the service is accepting work. It is not accepting work
when the engine never warmed, when the pool is unusable, when a replacement is in progress, or when the in-flight
job is past its budget and has not been reclaimed yet.

Being busy is not the same as being unable, and readiness must not confuse them. A service that flipped to
not-ready for the duration of every ordinary job would be pulled out of rotation on every request, which is absurd
for a service whose normal state is one long job at a time. So a healthy in-budget job leaves readiness ready, and
the body carries `accepting_work` and `queue_depth` so an operator can see the difference without inferring it.

The endpoint keeps answering 200 in both states, with the condition in the body, because that is ADR-004's contract
and consumers already read `status`. The general convention of answering 503 when not ready was considered and
rejected here on that ground alone: it would be a breaking change to an existing contract, made in passing, in a
change about something else.

### Decision 7: the pixel ceiling is checked on the header, at the boundary, and refuses with `FILE_TOO_LARGE`

Where. At the request boundary in the API process, beside the existing `sniff_mime` call, which already has the
bytes in hand on both surfaces. Refusing there means the worker is never occupied by a request that was never going
to work, which is the entire point of refusing rather than crashing.

When. Before decode. The inspection opens the header only and reads the declared dimensions. A 40 KB PNG can
declare 100 megapixels, so bytes are not a proxy and the existing 50 MB check does not help. Pillow's own bomb
guard is set as defence in depth, but it cannot be the guard on its own: it warns above `MAX_IMAGE_PIXELS` and only
raises above twice that, so the service enforces its own ceiling explicitly on the size it read and sets Pillow's
constant to the same number as a backstop.

What is measured. The pixels one inference will receive. For a raw image that is its decoded dimensions. For a
document it is the page box rendered at the library's fixed 144 dpi, which is computable from the same header read
that yields the page count, so both limits come from one inspection. Measuring the inference input rather than the
file makes one number cover both input types, which is what makes it possible to reason about at all.

Which error. `FILE_TOO_LARGE` and its 400, the code the service already has for oversized input, with a detail
naming the measured pixel count and the ceiling. No new code, per the brief.

Alternative considered: downscale the image to the ceiling instead of refusing it. It is not absurd, because the
document path already does exactly that at 144 dpi and Decision 10 accepts it there. Rejected here because the
brief asks for a ceiling, because a resize path on the image surface is a behaviour change that deserves its own
decision rather than arriving inside a change about timeouts, and because refusing is the reversible choice: a
caller who is refused can resize and retry, whereas a caller whose page was silently shrunk cannot tell it happened.

That last argument needs squaring with Decision 11, which does bound the resolution detection runs at, without
telling the caller. The two are not the same thing. This alternative is a per-request rescue that would apply only
to submissions above the ceiling, so two callers sending comparable pages would get incomparable treatment and
neither would know which they got. Decision 11 is a service-wide operating resolution, identical for every request,
recorded in an ADR and stated in the README, which is exactly the shape Decision 10 already accepts for documents.
A documented constant is not a silent rescue.

Decision 11 also changes what this alternative would be for. The measurement, taken after this decision was
written, shows the ceiling has to stay low only while the detector is unbounded, and it rises far above the page
sizes that matter once a bound is deployed. So downscaling to rescue an oversized image is no longer the natural
follow-up it looked like, and it is not carried forward as one.

Alternative considered: put the check in the worker. Rejected. It would occupy the only worker in order to say no.

### Decision 8: a document that provably cannot finish is refused before it starts

`floor(ceiling / per-page allowance)` is the largest page count that can finish inside the service's own budget.
Beyond it, accepting the job means holding the only worker for the entire ceiling and then telling the caller it
failed, which is the exact behaviour this change exists to remove. So it is refused at the boundary, with the same
`FILE_TOO_LARGE` code and a detail naming the page count and the limit.

At the provisional numbers the limit is `floor(300 / 120) = 2` pages, and that is worth stating plainly rather than
shipping quietly. It means the service as currently configured cannot read a three page document, which was already
true and simply invisible: it would have accepted the job, held the worker, and failed. The change makes it say so
in milliseconds instead of five minutes, and it makes the underlying trade legible, which is that the deployed
ceiling and the per-page cost together decide how large a document this service accepts.

Task 1.3 sets the deployed pair, and it is an owner decision because it trades document size against how long a
caller holds a connection.

### Decision 9: the memory ceiling is measured, and the answer is the flat branch

This decision was written as a question with a rule stated in advance. The measurement has since been taken and the
rule resolves cleanly, so what follows is the answer rather than the question. The model, its fit and its two
validations are in "The measured memory model" above.

The rule's first branch applies. Peak resident memory is flat across page count: a page adds 11.5 MiB of retained
result and nothing else, because pages are already processed one at a time and their rendered images are released.
The ceiling is one job's cost, the single worker cap of Decision 5 is the whole concurrency story, and the measured
ceiling is recorded in the documentation.

What the rule did not anticipate is that one job's cost is itself unacceptable. An ordinary A4 page costs 92 percent
of the container limit, and on a worker with a full engine cache it reaches 12,261 MiB against a 12,288 MiB limit.
That is not a page count problem and no amount of worker recycling touches it, because the peak is a transient
inside a single call. It is a per-inference input problem, and Decision 11 is the fix.

The recycling lever this decision named as the obvious candidate for the rising branch is therefore not used, and
the measurement says why: recycling the worker after each job costs five to seven seconds and does not move the
peak, since there is nothing retained between calls to reclaim. It is listed with the other measured dead ends
below.

The two things ruled out in advance stay ruled out, and both now have numbers. Cutting models saves 170 MiB of a
3.2 GiB peak, so all five stay by the owner's decision that correctness beats memory on a service that reads
documents. Raising the container limit still moves the cliff without bounding anything, and the host measurement
makes it worse than that: the kill came from the host exhausting its swap with twenty eight containers on sixteen
gigabytes, so a larger container limit would buy nothing the host can honour.

### Decision 10: the fixed 144 dpi rendering resolution is accepted, recorded, and not exposed

This is the decision the proposal asks to have written down, and it is the reason a document's cost depends on the
page rather than on the scanner. It lands as an ADR under `PaddleOCR/docs/architecture/decisions/` in the format of
the existing four, written in task 8.4. The content is settled here.

The constraint. PaddleOCR rasterizes every PDF page at `PDF_RENDER_SCALE = 2.0`, which is 144 dpi, and neither the
service nor the caller has any say in it. A page's cost therefore depends on its physical size and not at all on
the resolution it was scanned at, which is why a 300 dpi and a 600 dpi scan of the same page cost the same to read.

What it buys. A hard, predictable memory bound per page for every document, with no work by this service. A4 is
2.00 MP, US Letter 1.94 MP, US Legal 2.47 MP, whatever the caller sends. Predictable is not the same as low, which
the measurement has since made plain: at 5302 MiB per megapixel those are 11,260, 10,921 and 13,731 MiB, so this
constraint bounds the cost of a document without making it affordable. Decision 11 is what makes it affordable.

What it costs, named rather than buried. A dense scan cannot be read at higher quality even when the caller knows
it needs to be, and there is no way to ask. A rule of thumb is that a line needs roughly 20 px of height to be
recognised dependably, which at 144 dpi puts the smallest reliable type at about 10 pt. Body text sits right at
that edge, so small print and dense tables are where this constraint will be felt. Large format pages are also
affected the other way: an A0 poster at 144 dpi is 32 MP, far above the pixel ceiling, so it is refused rather than
downscaled.

Rejected: raising `PADDLE_PDX_PDF_RENDER_SCALE`. Cost grows with the square of the scale, so 300 dpi is a little
over four times the pixels and therefore roughly four times the memory of a path whose memory is already the live
problem. This decision said to revisit it when Decision 9's measurement was in. It is in, and the answer is still
no, but the arithmetic is now explicit instead of hand-waved. Unbounded, an A4 page at 300 dpi is 8.7 megapixels and
the model prices it at 46.7 GiB, which is not a trade-off, it is impossible. With the detector bounded to 960 the
detector's share stops growing and the same page prices at roughly 7.7 GiB, which is arithmetically feasible.
Feasible is not the same as tested, and rendering higher only to downscale it again for detection buys quality only
in recognition, which Decision 11 shows was never the part that suffered. It is recorded here as a follow-up
question with its numbers attached, not as work this change does.

Rejected: exposing the scale as a per-request parameter. It hands a caller a lever that multiplies the memory cost
of a shared single worker, which is the failure mode this whole change exists to close. It is also a future need
rather than a current one, and the brief says not to build it.

Rejected: rasterizing in this service instead of letting the library do it. It takes on ownership of rasterization
across every library upgrade in exchange for a knob nobody has asked for yet.

### Decision 11: bound what the detector sees, and let the owner choose the bound

This is the fix the memory measurement points at, and it is the only guard in this change that bounds memory for
arbitrary caller input while still serving it. The pixel ceiling of Decision 7 bounds memory by refusing. The worker
cap of Decision 5 bounds how many of those costs run at once. Neither reduces what one page costs, and the caller
controls the pixel count of the page.

The cause is one line of pipeline configuration rather than the model. Detection is configured with a minimum-side
limit, `limit_type: min` and `limit_side_len: 64`, which only ever scales an image up, so every real page reaches
the detector at native resolution while the detection model was exported expecting a long side of 960. The fix is
`text_det_limit_type="max"` and `text_det_limit_side_len` set to the bound, on the `PaddleOCR(...)` call this
service already makes. Two arguments.

What it is measured to do. At 0.901 megapixels, a 960 long-side bound cut peak from 5358 MiB to 4242 MiB, and
accuracy went from 29 of 29 lines to 28 of 29 with mean confidence moving from 0.9869 to 0.9834. Applied to A4 the
effect is much larger, because the downscale is much bigger:

| Detector bound | Predicted peak on one A4 page | Downscale applied to a 1190x1684 page |
|---|---|---|
| none, today | 11.0 GiB | none |
| 1536 | 9.2 GiB | 0.91 |
| 1280 | 6.8 GiB | 0.76 |
| 960 | 4.1 GiB | 0.57 |

Where the accuracy goes, precisely. The loss is in detection and not in recognition. The detector works on the
downscaled image and its boxes are mapped back, so recognition still crops from the page at full resolution. That is
exactly the shape of the measurement: one line was lost, which is a detection miss, while mean confidence moved by
0.0035, which is recognition being untouched. Said plainly for the record: a lower bound reads less small text, in
the sense that small lines stop being found at all rather than being found and misread.

How much less, as an expectation rather than a measurement. Decision 10's rule of thumb is that a line needs roughly
20 px of height to be handled dependably, which at the fixed 144 dpi puts the smallest reliable type at about 10 pt.
The detection floor scales inversely with the downscale, so a 960 bound on A4 would put it near 17 pt, 1280 near
13 pt and 1536 near 11 pt. Those are extrapolations from one rule of thumb, and they are the reason the value has to
be chosen against real documents rather than from this table.

Why this change does not pick a default. The owner cares about small text, this is an accuracy trade against small
text, and the right value depends entirely on what his documents look like. So the setting is built, the candidates
and their costs are stated, and task 1.5 makes choosing the deployed value a measurement against his own documents.

The honest consequence of not picking, spelled out because it is not comfortable. The bound and the pixel ceiling
are one decision in two settings and there is no comfortable pair to default to. Shipping unbounded forces the
ceiling under 2 MP, which refuses A4 and US Legal. Shipping unbounded with a ceiling above that admits jobs that can
exhaust the container, which is today's behaviour and is the incident.

The shipped defaults choose the first: the detector bound is unset, which is today's detection behaviour exactly,
and the pixel ceiling is 1,720,000, the unbounded row at 90 percent of the container limit, which is what an
unbounded service survives with headroom left for the host. So an image deployed
on its own refuses A4, loudly, with the numbers in the error, instead of accepting a page it has a measured history
of dying on. That is a real loss of function and it is meant to be visible, because it is the true statement of what
the service can do today. The pair from tasks 1.4 and 1.5 removes it in the same deploy and leaves the service
accepting more than it does now, not less. Decision 12 makes a kill survivable rather than terminal, which is not
the same as making it acceptable.

Alternative considered: leaving the pipeline configuration alone and relying on the pixel ceiling. Rejected, because
that ceiling then has to sit below the pages the service exists to read, so the service would be safe and useless.

Alternative considered: cutting the page into overlapping pieces, which is what the superseded
`add-ocr-full-resolution-reading` proposed. Rejected. It reaches a similar per-inference input size through joining,
duplicate removal and reading-order reconstruction, all of which this service would then own forever, where two
constructor arguments reach it with none.

### Decision 12: a broken pool is rebuilt, and rebuilding is bounded so a crash loop cannot hide in it

`ProcessPoolExecutor` marks itself permanently broken when its worker dies, and nothing rebuilds it. Measured
consequence: after the kill the service answered 500 to every request instantly, with no worker process alive, for
about five hours, while `/health` and `/ready` both reported healthy. A container restart was the only recovery.

The pool becomes a resource with a state, and the rebuild path is the one Decision 3 already builds for replacing a
worker that will not stop. One mechanism, two triggers: a worker past its reclamation grace, and a pool observed
broken. Readiness reports not-ready for the duration in both cases, which is the state Decision 6 already defines.

The request that was in flight when the worker died is not retried. It fails with the existing OCR failure code. A
retry would feed the worker the input that just killed it, which is the definition of a loop.

A request that arrives during a rebuild needs nothing new. It waits on the admission gate of Decision 4, holding its
own budget, exactly as it would behind a long job. If the rebuild finishes while it still has budget, it is
dispatched with what is left. If not, it fails at the gate and is never dispatched. That is Decision 4's existing
behaviour applied to a different reason for waiting, which is the payoff of having made the queue explicit.

Three properties keep this from turning a crash loop into an invisible retry loop:

- At most one rebuild is ever in flight, and an arriving request never triggers a second one.
- Consecutive failed rebuilds are counted and capped. Past the cap the service stops rebuilding, stays not-ready and
  answers definitively rather than spawning another process every few seconds. The counter resets on the first job
  that completes. The rebuild rate needs no timer of its own, because a rebuild pays the engine warm-up of five to
  fifteen seconds before it can fail again.
- Every rebuild emits one log line and increments a counter, so a service that is quietly rebuilding once a minute
  is visible as a number rather than as a rumour.

Alternative considered: let the Docker healthcheck notice and restart the container. Rejected on Decision 3's
grounds, and additionally because it demonstrably would not have fired: `/health` reported healthy for the whole
five hours by design, since liveness is deliberately independent of worker state, and making it dependent is the
change Decision 6 rejects.

Alternative considered: rebuild eagerly on a background timer rather than on demand. Rejected. It pays a warm-up
against no request, and an on-demand rebuild already has a waiter to serve at the end of it.

### Decision 13: a worker that dies takes its scratch file with it, so a fresh worker sweeps

The worker writes the upload to a temporary file with `delete=False` and removes it in a `finally`. A killed worker
never runs that `finally`, so every kill leaks one file of up to `MAX_FILE_SIZE_MB` in the container's temporary
directory. It is small next to the memory problem and it is the same defect underneath: cleanup that assumes the
process survives.

The service writes to a scratch directory of its own, and the pool initializer, which runs in every fresh worker
including every rebuilt one, deletes files in that directory older than the absolute request ceiling plus the
dispatch margin. Startup does the same sweep for anything a previous container process left behind. Nothing in that
directory legitimately outlives one request, so age is a sound test and no bookkeeping is needed.

Alternative considered: have the parent delete the file after a reclamation. Rejected. The parent does not know the
name, and inventing a naming convention purely so it can guess is more coupling than an age sweep.

Alternative considered: pass the bytes and let the worker keep them in memory instead of on disk. Rejected. It adds
the file's size to a peak that is already the problem, and the library's entry point takes a path.

## Measured and ruled out

Each of these is an obvious-looking idea. Each was measured against the running container and each fails for a
stated reason, recorded here so that nobody spends the afternoon again.

| Idea | Measured result | Why it cannot help |
|---|---|---|
| Tuning the inference thread count | No difference to peak | The transient is per-call buffers, not per-thread ones |
| Enabling Paddle's memory optimisation | Already on | Nothing to enable |
| Returning allocator memory to the operating system | Recovers about 2 percent | The memory is in use, not retained garbage |
| Recycling the worker after every job | 5 to 7 s per job, peak unchanged | The peak is a transient inside one call, not retention between calls |
| Cutting models from the pipeline | 170 MiB of a 3.2 GiB peak | Detection is 94 percent of the transient, and detection is the one model that cannot be cut |

## Risks / Trade-offs

The stop is only as fine-grained as one page. A worker that overruns badly inside a single page keeps computing
until that page finishes. Mitigation: the reclamation grace bounds the total exposure and replaces the worker past
it, and the exposure is one page rather than the thirty minutes and counting that was measured.

Worker replacement costs a warm-up, five to fifteen seconds, during which the service is honestly not ready.
Mitigation: it only happens after a job has already failed and refused to stop, the empty pool queue means nothing
else is lost, and readiness says so rather than accepting work it cannot serve.

The page count limit at the provisional numbers is two pages, which is a visible restriction on what the service
accepts. Mitigation: it is provisional, it is derived rather than chosen, task 1.3 sets the deployed pair, and the
alternative is accepting jobs that cannot finish. This is disclosure of an existing limit, not a new one.

The pixel ceiling and the detector bound are one decision split across two settings, and a deploy that sets only
one of them is wrong in a different direction each way. Worse, the defaults are not neutral: an image deployed
without the pair refuses A4, which is a real loss of function. Mitigation: the two are derived from the same model
in one table, tasks 1.4 and 1.5 produce them together, the migration plan ships them in the same deploy and states
the consequence of not doing so, and the direction the defaults fail in is a named refusal rather than a kill.

The detector bound is an accuracy regression against exactly the thing the owner cares about. Mitigation: the change
refuses to pick the value, the loss is characterised as missed small lines rather than misread text, the one
measured point is stated with its numbers, and task 1.5 makes the choice a measurement against the owner's own
documents with a stated fallback of no bound and a lower ceiling.

The 318 MiB per megapixel residual is extrapolated twenty times beyond the range it was fitted in, and every ceiling
above about 2 MP rests on it. Mitigation: it is labelled as an extrapolation wherever it is used, task 1.6 confirms
it at the top of the intended range, and until it reports the defensible ceilings are the ones inside the measured
range, which is where the change's original provisional value already sat.

Rebuilding the pool could mask a repeating crash. Mitigation: Decision 12 caps consecutive failed rebuilds, never
retries the request that killed the worker, and emits a counter and one log line per rebuild, so the failure is
loud and finite rather than silent and endless. The status quo it replaces is five hours of instant 500s behind two
endpoints reporting healthy.

The header inspection parses untrusted input in the API process. Mitigation: it is a header read only, no pixel
buffer is allocated, the existing 50 MB byte cap still bounds the input, and Pillow's bomb guard is set to the
service's own ceiling as a backstop. The `/security-review` skill is listed for the implementation of exactly this
part.

`pypdfium2` becomes a declared dependency of this module. Mitigation: it is already installed as a paddlex
dependency, so there is no new install and no version conflict, and declaring it is the correct response to relying
on it rather than a cost.

One A4 page still costs 92 percent of the container limit if the detector bound is not deployed. Mitigation: this
is a disclosure of today's behaviour rather than something the change introduces, the single worker cap holds the
peak at one job's cost, the pixel ceiling refuses the inputs that would exceed it, Decision 12 makes the kill
survivable if one gets through, and Decision 11 is the fix that removes the exposure once its value is chosen.

## Migration Plan

A normal image rebuild. No schema migration, no persisted state, no data migration. The readiness body gains two
fields and every other response is untouched, so consumers that ignore unknown fields are unaffected.

Configuration is the one ordered part. The new settings all have defaults, so the image starts without any compose
change, but two pairs have to be deployed as pairs. `OCR_REQUEST_TIMEOUT` and the per-page allowance together decide
the page limit, so ship the value task 1.3 derives in the same deploy as the image. The detector bound and the pixel
ceiling together decide what one call can cost, so ship the pair tasks 1.4 and 1.5 produce in that same deploy.

Deploying the image alone is safe but not neutral, and this is the one thing to read before deploying. It keeps
today's detection behaviour and applies the 1,720,000 pixel ceiling that behaviour actually survives, so an A4
document is refused with `FILE_TOO_LARGE` until the pair is deployed. Everything else in the change is unconditional
and arrives with the image: the deadline, the reclamation, the pool rebuild, the scratch sweep and the readiness
answer.

Rollback is reverting the image. Nothing persists, and no caller has to change anything to go back, because no
request parameter was added.

## Open Questions

1. What is the p95 per-page inference time on the deployment's 4.0 CPU allocation, and what should the deployed
   ceiling therefore be? Task 1.2 measures it and task 1.3 turns it into the deployed pair with the owner. It
   changes three defaults and no behaviour, so it is deferrable in the sense that the mechanism is correct whatever
   the numbers are, but the pair must be decided before the change is called done.
2. Closed. Peak memory is flat across page count, at 11.5 MiB of retained result per page. The model, its fit and
   its two validations are in "The measured memory model", and Decision 9 records which branch of its own rule
   applies and why the answer turned out not to be the reassuring one.
3. What detector long-side bound is deployed, and therefore what pixel ceiling goes with it? Task 1.5 measures 960,
   1280 and 1536 against the owner's own documents and he chooses. It changes two defaults and no behaviour, since
   the mechanism is the same at every value, but the pair must be decided before the change is called done because
   there is no safe default for it.
4. Does the 318 MiB per megapixel residual hold at the top of the intended ceiling? Task 1.6 measures it. It bounds
   how far the ceiling can be raised and nothing else.
5. If the measured per-page cost makes documents of a realistic size take longer than a caller can hold a
   connection, the answer is asynchronous job submission, which is a separate change. This one produces the
   evidence that would justify it, and deliberately does not pre-empt it.
