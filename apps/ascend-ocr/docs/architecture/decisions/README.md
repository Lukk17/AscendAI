# ascend-ocr - Architecture Decision Records

| ID                                                                              | Decision                                                                 | Status   |
| :------------------------------------------------------------------------------ | :----------------------------------------------------------------------- | :------- |
| [ADR-001](ADR-001-mcp-file-transport-uri-only.md)                               | MCP file transport - URI-only with SSRF guard and `file://` jail.        | Accepted |
| [ADR-002](ADR-002-mcp-error-catalog.md)                                         | MCP error code catalog mirrors the REST surface.                         | Accepted |
| [ADR-003](ADR-003-versioning-strategy.md)                                       | Versioning - URL versioning for REST, tool-name versioning for MCP.      | Accepted |
| [ADR-004](ADR-004-liveness-readiness-split.md)                                  | Liveness (`/health`) and readiness (`/ready`) endpoints serve different audiences. | Accepted |
| [ADR-005](ADR-005-fixed-pdf-render-resolution.md)                               | The fixed 144 dpi PDF rendering resolution is accepted, recorded, and not exposed. | Superseded by ADR-010 |
| [ADR-006](ADR-006-detector-input-bound.md)                                      | Bound what text detection sees; the deployed value is measured against real documents. | Partly superseded by ADR-010 |
| [ADR-007](ADR-007-explicit-ocr-model-selection.md)                              | Name the OCR models explicitly, ship PP-OCRv6 small, key the engine cache by the pair. | Accepted |
| [ADR-008](ADR-008-every-request-is-a-job.md)                                    | Every request is a job, at every length, on both surfaces.               | Accepted |
| [ADR-009](ADR-009-results-in-object-storage.md)                                 | A finished result is a Markdown file in object storage, and the state carries its address. | Accepted |
| [ADR-010](ADR-010-quality-modes-and-service-side-rendering.md)                  | Render pages in the service, two locked quality modes, and a page allowance per engine. | Accepted |
| [ADR-011](ADR-011-explicit-preprocessing-and-straighten.md)                     | Name every preprocessing step, straighten only on request, classify each text line on its own. | Accepted |

For monorepo-level decisions see [`../../../../../docs/architecture/decisions/`](../../../../../docs/architecture/decisions/).
