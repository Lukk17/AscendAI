# 1. Introduction and Goals

---

### Purpose

ascend-ocr is a single-purpose OCR microservice in the AscendAI monorepo. It wraps the PaddleOCR library behind two
parallel surfaces: a REST API for direct upload workflows and an MCP server for agent-driven workflows. The service
accepts images and PDFs and reads text out of them.

Every request is a job. A submission is answered with an identifier rather than with the document's text, the caller
polls for the state, and a successful reading leaves one Markdown file in the platform's object storage whose address
the state carries. Nothing holds a connection open for the length of a reading, which is what lets the service accept
a hundred page document at all (see
[ADR-008](../decisions/ADR-008-every-request-is-a-job.md) and
[ADR-009](../decisions/ADR-009-results-in-object-storage.md)).

Within the monorepo, ascend-ocr is a peer of ascend-audio-scribe and ascend-web-hunter: a FastMCP-based Python service
that the ascend-ai-agent calls. It has no database and no message queue, it keeps its job records as files on its own
disk, and it has exactly one external service dependency, the S3-compatible object store the platform already runs.

---

### Stakeholders

| Role | Expectation |
| :--- | :--- |
| Developer / owner | Ability to add a language without a code change; clear local run story. |
| ascend-ai-agent | A REST job surface it can submit to, poll, and collect from, plus MCP tools with the same four operations. |
| Operator | Container that starts healthy, signals readiness only after warm-up, and does not expose SSRF. |
| Security reviewer | No path-traversal from `file://`, no SSRF from `http(s)://`, no internal detail in error responses. |

---

### Quality Goals

| Priority | Goal | Scenario |
| :--- | :--- | :--- |
| 1 | Security | MCP file fetch cannot reach private IPs or escape the `file://` jail; error responses contain no stack frames. |
| 2 | Operational correctness | Container does not accept traffic before the OCR engine is warm; liveness and readiness are separate signals. |
| 3 | Contract stability | REST and MCP error codes are identical strings; breaking changes get a new version, not a quiet rename. |
| 4 | Bounded waiting | A document that has to wait is told how many pages are ahead of it, and the queue's own bounds turn that into a worst case with a number attached. |
| 5 | Language coverage | The default `en` engine loads at startup; additional languages load lazily on demand and are cached LRU. |
| 6 | Observability | Startup banner prints both probe URLs, the result store and every runtime config value; an operator can see what the service is working on without reading logs. |
