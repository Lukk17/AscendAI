# 1. Introduction and Goals

---

### Purpose

AscendWebSearch is a single-purpose web search and content extraction microservice in the AscendAI monorepo.
It exposes two parallel surfaces: a REST API for direct integration and an MCP server for agent-driven use via
AscendAgent. Given a search query it returns ranked result URLs via SearXNG; given a URL it returns extracted
plain text using a six-strategy escalation chain that ranges from a lightweight HTTP client to a human-operated
browser session.

Within the monorepo, AscendWebSearch is a peer of AudioScribe and PaddleOCR: a FastMCP-based Python service
called by AscendAgent through the Model Context Protocol. It has no database and no other inbound callers.

---

### Stakeholders

| Role | Expectation |
| :--- | :--- |
| AscendAgent | MCP tools `web_search` and `web_read` that return structured results without the agent knowing which extraction strategy ran. |
| Developer / owner | Ability to add a strategy or adjust escalation order without touching callers; clear local run story. |
| Operator | Container that starts healthy; structured 428 response when human CAPTCHA intervention is needed; session cookies persist across restarts. |
| Security reviewer | No SSRF on user-supplied URLs (both REST and MCP surfaces); no internal stack traces in error responses. |

---

### Quality Goals

| Priority | Goal | Scenario |
| :--- | :--- | :--- |
| 1 | Content availability | A page blocked by Cloudflare is reachable through escalation; a human-intervention case surfaces a clear 428 with a VNC URL rather than empty content. |
| 2 | Security | User-supplied URLs pass SSRF validation before any outbound request; private/loopback addresses are blocked. |
| 3 | Transparency | The response `mode` field always identifies which strategy produced the content. Callers can observe escalation cost. |
| 4 | Session reuse | Cloudflare clearance cookies acquired by any strategy are persisted to Redis and reused on subsequent requests to the same domain. |
| 5 | Operational simplicity | A single `SEARXNG_BASE_URL` and `FLARESOLVERR_URL` env var covers the two most common deployment variants; defaults work for local development. |
