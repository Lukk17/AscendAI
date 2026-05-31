# 1. Introduction and Goals

---

### Purpose

PaddleOCR is a single-purpose OCR microservice in the AscendAI monorepo. It wraps the PaddleOCR library behind two
parallel surfaces: a REST API for direct upload workflows and an MCP server for agent-driven workflows. The service
accepts images and PDFs, runs text extraction, and returns structured JSON with per-page, per-line text, confidence
scores, and bounding boxes.

Within the monorepo, PaddleOCR is a peer of AudioScribe and AscendWebSearch: a FastMCP-based Python service that the
AscendAgent calls via the Model Context Protocol. It has no database, no message queue, and no dependencies on the
other MCP services.

---

### Stakeholders

| Role | Expectation |
| :--- | :--- |
| Developer / owner | Ability to add a language without a code change; clear local run story. |
| AscendAgent | An MCP `ocr_process` tool that accepts a URI, fetches the file, and returns structured text. |
| Operator | Container that starts healthy, signals readiness only after warm-up, and does not expose SSRF. |
| Security reviewer | No path-traversal from `file://`, no SSRF from `http(s)://`, no internal detail in error responses. |

---

### Quality Goals

| Priority | Goal | Scenario |
| :--- | :--- | :--- |
| 1 | Security | MCP file fetch cannot reach private IPs or escape the `file://` jail; error responses contain no stack frames. |
| 2 | Operational correctness | Container does not accept traffic before the OCR engine is warm; liveness and readiness are separate signals. |
| 3 | Contract stability | REST and MCP error codes are identical strings; breaking changes get a new version, not a quiet rename. |
| 4 | Language coverage | The default `en` engine loads at startup; additional languages load lazily on demand and are cached LRU. |
| 5 | Observability | Startup banner prints both probe URLs and every runtime config value; log lines carry structured context. |
