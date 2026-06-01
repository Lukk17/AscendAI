# ADR-003: Versioning strategy — URL versioning for REST, tool-name versioning for MCP

## Status

Accepted — 2026-05-31

## Context

PaddleOCR has two long-lived contracts: the REST endpoint and the MCP tool. Both will need to evolve — new fields in the response, new arguments, new error codes, breaking renames. A versioning strategy chosen up-front prevents the "every caller breaks at once" failure mode and gives operators a clean migration window.

REST already follows URL-segment versioning (`/v1/ocr`). MCP has no equivalent — the tool is registered by name (`ocr_process`), and changing the tool's argument shape is a breaking change with no transition. The MCP protocol itself has a `protocolVersion` handshake but it's about the protocol, not about individual tools.

## Decision

### REST: URL-segment versioning

REST routes are mounted under `/v{N}/`. Today: `/v1/ocr`. A breaking change introduces `/v2/ocr` alongside `/v1/ocr`; the old version stays available for a documented deprecation window before removal. Tracked in the response openapi schema.

### MCP: tool-name versioning + `schema_version` field

MCP has no transport-level versioning of individual tools, so we use the tool name itself. Today: `ocr_process`. A breaking change registers `ocr_process_v2` alongside the v1 tool. The v1 tool's description is updated to start with `Deprecated: use ocr_process_v2`. The agent's tool-router pattern-matches on the description.

Inside the response payload, both surfaces carry a `schema_version: Literal["1"]` field on `OcrJsonResponse`. Agents that consume the JSON can branch on this field to pick the right deserialisation path. This catches the corner case where two tool versions return *structurally similar* payloads — agents don't have to compare field-by-field, they can read one field.

### What counts as a breaking change

| Change                                              | Breaking? | Bump        |
| --------------------------------------------------- | --------- | ----------- |
| Add an optional field to the response               | No        | none        |
| Add an optional argument with a default             | No        | none        |
| Add a new error code                                | No        | none        |
| Rename a field                                      | Yes       | new version |
| Change a field's type                               | Yes       | new version |
| Make an optional argument required                  | Yes       | new version |
| Remove an argument                                  | Yes       | new version |
| Change an error code's HTTP status / retry semantic | Yes       | new version |
| Change the meaning of a field while keeping the name| Yes       | new version |

## Consequences

### Why this shape

- **MCP and REST evolve independently.** A breaking REST change does not force an MCP bump and vice versa. Each surface has its own release cadence.
- **`schema_version` is a belt-and-braces guard.** Even if a future maintainer ships a breaking change without minting a new tool name (the URL-segment equivalent doesn't apply), the `schema_version` field tells consumers what they're parsing.
- **Tool-name versioning is the only option MCP gives us today.** It's slightly clunkier than URL versioning (the version is part of the identifier, not orthogonal), but it works without coordination with the FastMCP roadmap.

### Trade-offs

- **Multiple tool names is awkward UX.** A caller browsing `tools/list` sees `ocr_process` and `ocr_process_v2` side by side. The description-prefix convention is the workaround. If FastMCP adds a `deprecated` flag on tool metadata in the future, switch to that.
- **`schema_version` adds one field to every response.** Trivial cost in bytes; meaningful payoff at upgrade time.
- **No semver, no `Sunset` header on REST.** Both could be added later; not needed for the small client population today.

### Alternatives considered

- **MCP request header versioning.** Rejected — MCP has no request-header concept at the tool layer.
- **MCP namespace prefix (e.g., `v1/ocr_process`).** Rejected — `/` in tool names is not portable across all MCP clients.
- **No versioning, "we just don't break things."** Rejected — at the rate this codebase moves, every breaking change without a transition window is a paging incident waiting to happen.

## Related

- `PaddleOCR/src/api/rest/rest_endpoints.py` — `APIRouter(prefix="/v1")`.
- `PaddleOCR/src/api/mcp/mcp_server.py` — `@mcp.tool() async def ocr_process(...)`.
- `PaddleOCR/src/model/ocr_models.py` — `OcrJsonResponse.schema_version: Literal["1"] = "1"`.
- ADR-002 — error codes evolve under the same rules as fields.
