# 2. Constraints

---

### Technical constraints

| Constraint | Source | Impact |
| :--- | :--- | :--- |
| Python 3.11 | `pyproject.toml` `requires-python = ">=3.11"`, Dockerfile base `python:3.11-slim` | Cannot use 3.12+ syntax or standard-library additions from those versions. |
| PaddlePaddle 3.3.1 / PaddleOCR 3.7.0 | `pyproject.toml` pinned versions | Wheel availability is platform-gated: pre-built CUDA wheels exist for Linux x86-64 only. Running on macOS ARM or Windows requires CPU inference and manual wheel selection. |
| Container-only deployment | Dockerfile + docker-compose service `ascend-ocr` | No native install path is tested. Model files are baked into the image during the builder stage (line 23 of Dockerfile, one `PaddleOCR(...)` call naming the pair `OCR_TEXT_DETECTION_MODEL` and `OCR_TEXT_RECOGNITION_MODEL` hold); the runtime image copies `/root/.paddlex` from the builder, so model downloads do not happen at container start. |
| Single-process, no worker pool | Uvicorn started with default workers (1) in `CMD` | Documents queue behind each other, explicitly and observably: the job runner is the single consumer of the queue and dispatches one document at a time. `PaddleOCR.predict()` holds the interpreter lock for the whole call, so the engine runs in a single-worker `ProcessPoolExecutor` (`start_worker_pool` in `src/service/ocr_service.py`) instead of a thread pool, keeping the event loop free for `/health`, `/ready` and every status read while inference runs. Throughput still scales with CPU cores per pod, not with additional worker processes, since only one worker is configured. |
| One external service dependency | `OCR_RESULT_S3_BUCKET` in the platform's S3-compatible object store | Every successful reading writes one Markdown object there ([ADR-009](../decisions/ADR-009-results-in-object-storage.md)). The job record stays local, so an outage of that store stops delivery rather than the service: submissions are still accepted, documents are still read, and the failure is recorded against the job with the `RESULT_STORE_UNAVAILABLE` reason. |
| State on the container's own disk | `OCR_JOBS_DIR` | Job records survive a restart and not a recreate. The text survives either way, because it is in the bucket, so what a recreate destroys is the address rather than the document. Mount a volume there if the address must survive too. |
| No GPU in the default compose stack | `enable_mkldnn=False` in `OcrService._get_engine` (`src/service/ocr_service.py`) | Intel acceleration (MKL-DNN, now oneDNN) is disabled because enabling it breaks inference on the pinned versions. On 2026-09-24, with PaddleOCR 3.7.0 and PaddlePaddle 3.3.1, turning it on made every inference fail with `NotImplementedError: (Unimplemented) ConvertPirAttribute2RuntimeAttribute not support [pir::ArrayAttribute<pir::DoubleAttribute>]`, raised from `onednn_instruction.cc`. The same error is reported upstream in [PaddleOCR issue 17955](https://github.com/PaddlePaddle/PaddleOCR/issues/17955). Re-test it on the next PaddlePaddle upgrade before turning it back on. GPU inference requires a separate Dockerfile with CUDA base and `paddlepaddle-gpu`. |
| In-monorepo service | `apps/ascend-ocr/` directory inside `AscendAI` monorepo | Shares the monorepo's AGENTS.md conventions, docker-compose network, and e2e tooling. Cannot be extracted without carrying those dependencies. |

---

### Organisational constraints

| Constraint | Impact |
| :--- | :--- |
| No separate release cadence | ascend-ocr ships with the rest of the monorepo. There is no independent versioning of the container image beyond the `0.3.0` tag in `pyproject.toml`. |
| No external public traffic | The service runs inside the docker-compose network. Port `7022` is exposed on the host for development only. In a cloud deployment it would sit behind a private load balancer. |
| Secrets handled by the host | No secrets manager integration. API keys and config are injected as environment variables at container start. |
