# ascend-ocr - Architecture Documentation

> As of commit `cdbb447` (2026-05-31). Code SHA is the anchor; treat anything older with suspicion.

---

### Reading paths

| Audience | Start here |
| :--- | :--- |
| New contributor | [01 Introduction](arc42/01-introduction-and-goals.md), [04 Solution strategy](arc42/04-solution-strategy.md), [05 Building blocks](arc42/05-building-block-view.md) |
| Architect / reviewer | [02 Constraints](arc42/02-constraints.md), [03 Context](arc42/03-context-and-scope.md), [09 ADR index](arc42/09-architecture-decisions.md), [11 Risks](arc42/11-risks-and-technical-debt.md) |
| Operator (incident response) | [07 Deployment](arc42/07-deployment-view.md), [06 Runtime](arc42/06-runtime-view.md), [04 Solution strategy](arc42/04-solution-strategy.md) |
| Security reviewer | [ADR-001](decisions/ADR-001-mcp-file-transport-uri-only.md), [ADR-002](decisions/ADR-002-mcp-error-catalog.md), [10 Quality requirements](arc42/10-quality-requirements.md) |

---

### Arc42 chapters

| # | Chapter | One-line summary |
| :--- | :--- | :--- |
| 1 | [Introduction and goals](arc42/01-introduction-and-goals.md) | What the service does and who depends on it |
| 2 | [Constraints](arc42/02-constraints.md) | Python 3.11, container-only, single-process, paddle wheel platform |
| 3 | [Context and scope](arc42/03-context-and-scope.md) | ascend-ai-agent caller, S3-compatible object store for MCP, no database |
| 4 | [Solution strategy](arc42/04-solution-strategy.md) | Dual surface, lifespan warm-up, worker-process offload |
| 5 | [Building block view](arc42/05-building-block-view.md) | Module map: rest, mcp, service, config, model |
| 6 | [Runtime view](arc42/06-runtime-view.md) | Cold start, REST happy path, MCP via the object store, error mapping |
| 7 | [Deployment view](arc42/07-deployment-view.md) | docker-compose role, healthcheck wiring, env-var surface |
| 8 | [Crosscutting concepts](arc42/08-crosscutting-concepts.md) | Logging, error catalog, async hygiene, LRU engine cache |
| 9 | [Architecture decisions](arc42/09-architecture-decisions.md) | Index linking to ADRs |
| 10 | [Quality requirements](arc42/10-quality-requirements.md) | Security posture, observability targets, test coverage |
| 11 | [Risks and technical debt](arc42/11-risks-and-technical-debt.md) | DNS TOCTOU, paddle wheel availability, fastmcp version skew |
| 12 | [Glossary](arc42/12-glossary.md) | Domain vocabulary |

---

### ADRs

| ID | Title | Status |
| :--- | :--- | :--- |
| [ADR-001](decisions/ADR-001-mcp-file-transport-uri-only.md) | MCP file transport: URI-only with SSRF guard and `file://` jail | Accepted |
| [ADR-002](decisions/ADR-002-mcp-error-catalog.md) | Error code catalog shared by REST and MCP | Accepted |
| [ADR-003](decisions/ADR-003-versioning-strategy.md) | URL versioning for REST, tool-name versioning for MCP | Accepted |
| [ADR-004](decisions/ADR-004-liveness-readiness-split.md) | Liveness (`/health`) and readiness (`/ready`) split | Accepted |
| [ADR-005](decisions/ADR-005-fixed-pdf-render-resolution.md) | The fixed 144 dpi PDF rendering resolution | Superseded by ADR-010 |
| [ADR-006](decisions/ADR-006-detector-input-bound.md) | Bound what text detection sees | Partly superseded by ADR-010 |
| [ADR-007](decisions/ADR-007-explicit-ocr-model-selection.md) | Name the OCR models explicitly and key the engine cache by the pair | Accepted |
| [ADR-008](decisions/ADR-008-every-request-is-a-job.md) | Every request is a job, at every length, on both surfaces | Accepted |
| [ADR-009](decisions/ADR-009-results-in-object-storage.md) | A finished result is a Markdown file in object storage | Accepted |
| [ADR-010](decisions/ADR-010-quality-modes-and-service-side-rendering.md) | Render pages in the service, two locked quality modes, and a page allowance per engine | Accepted |
| [ADR-011](decisions/ADR-011-explicit-preprocessing-and-straighten.md) | Name every preprocessing step, straighten only on request, classify each text line on its own | Accepted |

For monorepo-level decisions see [docs/architecture/decisions/](../../../../docs/architecture/decisions/).

---

### Diagrams

| Diagram | File |
| :--- | :--- |
| C4 container diagram | [diagrams/container-diagram.md](diagrams/container-diagram.md) |
| MCP happy-path runtime | [diagrams/container-diagram.md](diagrams/container-diagram.md#mcp-runtime-happy-path) |
