# ADR-M012: Shared Python Platform Library

---

### Status

Accepted (2026-10-07)

---

### Context

The four Python services (ascend-audio-scribe, ascend-web-hunter, ascend-memory, ascend-ocr) each carried their own copy of the same cross-cutting code: error handlers, the settings class, logging setup, request id middleware, OpenTelemetry setup, readiness checks and the app wiring in `main.py`. A read-only measurement found about 1,000 duplicated lines, and the copies had drifted apart: three services ignored their `LOG_LEVEL` setting, only ascend-ocr had rate limiting, ascend-ocr did not answer RFC 7807 problem bodies while the other three did, ascend-web-hunter pinned older OpenTelemetry versions, ascend-memory named its MCP server `AscendMemory`, and ascend-audio-scribe named its port setting `MCP_PORT`. Every later Python change would otherwise reimplement the same helpers a fourth and fifth time.

---

### Decision

Create one shared Python library, `ascend-python-common`, under `libs/ascend-python-common/`, imported by all four services:

- It is a normal Python dependency pinned exact (`ascend-python-common==<version>`) in each service's `pyproject.toml`, starting at `0.1.0` with semantic versioning and a changelog.
- It installs from its folder in this repository: editable (`pip install -e`) in local virtual environments, and in Docker through a Compose additional build context named `ascend-python-common`. Nothing is published to a package index and the name is not registered on one.
- Every documented install, the CI job and every Dockerfile install the library from the folder before the service, so pip finds the pinned version already installed and never asks an index for it.
- It pins one version set for the shared dependencies (FastAPI, uvicorn, FastMCP, MCP SDK, OpenTelemetry, prometheus, logging, slowapi), and each service removes its own pin of those packages.
- It holds the error problem body, settings base, logging, request id and session digest, tracing, readiness, rate limiting, security headers, app factory, startup banner frame, URI fetch guard and shared tooling configuration. Each service keeps only its business code, its own error codes, its own settings fields and its own readiness probes.

The operating details are in [libs/ascend-python-common/README.md](../../../libs/ascend-python-common/README.md) and the full design in [openspec/changes/add-ascend-python-common/design.md](../../../openspec/changes/add-ascend-python-common/design.md).

---

### Alternatives Considered

#### Alternative 1: Pinned git URL

- Pros: No local path coupling. Each build resolves a tagged, immutable version.
- Cons: A library change and its use become two steps, because the tag must exist before the service build can resolve it. Every build needs network access to the host. One pull request cannot change the library and its services atomically.
- Why not: Atomic same-commit changes across library and services matter more than immutable tags at this stage of the project.

#### Alternative 2: Private package index

- Pros: Standard dependency resolution. Immutable published versions per release.
- Cons: A publish job, an index account and credentials in every build. The project has none of those today and CI uses no secrets.
- Why not: The cost of new infrastructure and the first CI secret outweighs the benefit while all consumers live in this one repository.

---

### Consequences

- Positive: One source of truth for configuration, error handling, logging and behaviour across the four Python services.
- Positive: No new infrastructure, no secret in CI, no release step beyond the version in `pyproject.toml`.
- Positive: A library change and its service migrations stay atomic in one pull request.
- Negative: The package name is free on the public index and not registered there. A service install that runs before the library install would ask the index for it. Every documented install puts the library first, which closes that path.
- Negative: `libs/` is not a deployable like `apps/`, so CI and release workflows must special-case it with a path filter and a build context instead of treating it as another matrix entry.

#### Risks

- A library change breaks a service that CI does not rebuild. The CI path filter runs all four Python services and the library job whenever `libs/ascend-python-common/**` changes, which is the mitigation.
