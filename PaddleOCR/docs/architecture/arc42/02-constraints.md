# 2. Constraints

---

### Technical constraints

| Constraint | Source | Impact |
| :--- | :--- | :--- |
| Python 3.11 | `pyproject.toml` `requires-python = ">=3.11"`, Dockerfile base `python:3.11-slim` | Cannot use 3.12+ syntax or standard-library additions from those versions. |
| PaddlePaddle 3.3.1 / PaddleOCR 3.6.0 | `pyproject.toml` pinned versions | Wheel availability is platform-gated: pre-built CUDA wheels exist for Linux x86-64 only. Running on macOS ARM or Windows requires CPU inference and manual wheel selection. |
| Container-only deployment | Dockerfile + docker-compose service `ascend-paddle-ocr` | No native install path is tested. Model files are baked into the image during the builder stage (line 23 of Dockerfile: `PaddleOCR(lang='en'...); PaddleOCR(lang='pl'...)`); the runtime image copies `/root/.paddlex` from the builder, so model downloads do not happen at container start. |
| Single-process, no worker pool | Uvicorn started with default workers (1) in `CMD` | Concurrent OCR requests queue behind each other. The OCR engine call is offloaded to a thread pool (`asyncio.to_thread`) to avoid blocking the event loop, but throughput scales with CPU cores per pod, not with horizontal thread pools. |
| No GPU in the default compose stack | `enable_mkldnn=False` in `OcrService._get_engine` (`src/service/ocr_service.py:66`) | MKL-DNN is disabled for compatibility. GPU inference requires a separate Dockerfile with CUDA base and `paddlepaddle-gpu`. |
| In-monorepo service | `PaddleOCR/` directory inside `AscendAI` monorepo | Shares the monorepo's AGENTS.md conventions, docker-compose network, and e2e tooling. Cannot be extracted without carrying those dependencies. |

---

### Organisational constraints

| Constraint | Impact |
| :--- | :--- |
| No separate release cadence | PaddleOCR ships with the rest of the monorepo. There is no independent versioning of the container image beyond the `0.1.0` tag in `pyproject.toml`. |
| No external public traffic | The service runs inside the docker-compose network. Port `7022` is exposed on the host for development only. In a cloud deployment it would sit behind a private load balancer. |
| Secrets handled by the host | No secrets manager integration. API keys and config are injected as environment variables at container start. |
