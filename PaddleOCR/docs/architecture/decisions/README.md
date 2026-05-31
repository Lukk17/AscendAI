# PaddleOCR — Architecture Decision Records

| ID                                                                              | Decision                                                                 | Status   |
| :------------------------------------------------------------------------------ | :----------------------------------------------------------------------- | :------- |
| [ADR-001](ADR-001-mcp-file-transport-uri-only.md)                               | MCP file transport — URI-only with SSRF guard and `file://` jail.        | Accepted |
| [ADR-002](ADR-002-mcp-error-catalog.md)                                         | MCP error code catalog mirrors the REST surface.                         | Accepted |
| [ADR-003](ADR-003-versioning-strategy.md)                                       | Versioning — URL versioning for REST, tool-name versioning for MCP.      | Accepted |
| [ADR-004](ADR-004-liveness-readiness-split.md)                                  | Liveness (`/health`) and readiness (`/ready`) endpoints serve different audiences. | Accepted |

For monorepo-level decisions see [`../../../../docs/architecture/decisions/`](../../../../docs/architecture/decisions/).
