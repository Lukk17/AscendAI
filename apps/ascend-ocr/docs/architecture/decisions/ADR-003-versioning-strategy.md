# ADR-003: Versioning strategy - URL versioning for REST, tool-name versioning for MCP

## Status

Accepted - 2026-05-31. Amended - 2026-09-24: the first breaking change on both surfaces was taken knowingly, and
neither surface used the mechanism this ADR designed (see "Amendment" below).

## Context

ascend-ocr has two long-lived contracts: the REST endpoint and the MCP tool. Both will need to evolve - new fields in the response, new arguments, new error codes, breaking renames. A versioning strategy chosen up-front prevents the "every caller breaks at once" failure mode and gives operators a clean migration window.

REST already follows URL-segment versioning (`/v1/ocr`). MCP has no equivalent - the tool is registered by name (`ocr_process`), and changing the tool's argument shape is a breaking change with no transition. The MCP protocol itself has a `protocolVersion` handshake but it's about the protocol, not about individual tools.

## Decision

### REST: URL-segment versioning

REST routes are mounted under `/v{N}/`. Today: `/v1/ocr`. A breaking change introduces `/v2/ocr` alongside `/v1/ocr`; the old version stays available for a documented deprecation window before removal. Tracked in the response openapi schema.

### MCP: tool-name versioning + `schema_version` field

MCP has no transport-level versioning of individual tools, so we use the tool name itself. Today: `ocr_process`. A breaking change registers `ocr_process_v2` alongside the v1 tool. The v1 tool's description is updated to start with `Deprecated: use ocr_process_v2`. The agent's tool-router pattern-matches on the description.

Inside the response payload, both surfaces carry a `schema_version: Literal["1"]` field on `OcrJsonResponse`. Agents that consume the JSON can branch on this field to pick the right deserialisation path. This catches the corner case where two tool versions return *structurally similar* payloads - agents don't have to compare field-by-field, they can read one field.

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

- **MCP request header versioning.** Rejected - MCP has no request-header concept at the tool layer.
- **MCP namespace prefix (e.g., `v1/ocr_process`).** Rejected - `/` in tool names is not portable across all MCP clients.
- **No versioning, "we just don't break things."** Rejected - at the rate this codebase moves, every breaking change without a transition window is a paging incident waiting to happen.

## Related

- `apps/ascend-ocr/src/api/rest/rest_endpoints.py` - `APIRouter(prefix="/v1")`.
- `apps/ascend-ocr/src/api/mcp/mcp_server.py` - `@mcp.tool() async def ocr_process(...)`.
- `apps/ascend-ocr/src/model/ocr_models.py` - `OcrJsonResponse.schema_version: Literal["1"] = "1"`.
- ADR-002 - error codes evolve under the same rules as fields.


## Amendment (2026-09-24): the first breaking change, and why neither surface bumped a version

[ADR-008](ADR-008-every-request-is-a-job.md) is breaking on both surfaces under this ADR's own table: it removes an
endpoint, removes a tool, and changes what a submission's answer means. The owner accepted that knowingly. This
amendment records what each surface did **instead of** the version bump this ADR prescribes, because the honest thing
is to say the mechanism was not used rather than to pretend it was.

**REST did not get a `/v2/ocr`.** The old path is removed and answers 404 like any unknown path, and the new operations live under the same `/v1` prefix as new resources rather than as a second
version of an old one. A `/v2/ocr` would have had to mean something, and what replaced the synchronous request is not
a second version of it: it is a different resource with a different lifecycle. A 410 stub with an
`ENDPOINT_REMOVED` code was planned for one release window, and the owner decided on 2026-10-01 to delete the
endpoint outright instead, so the changelog is where a caller learns what happened.

**MCP did not get an `ocr_process_v2`.** The tool is removed outright, with no stub. An MCP client discovers its tools
on every connection rather than holding a compiled name, so a removed tool is simply a tool the model stops being
offered. A stub that only raises would put a tool in every model's context, cost tokens on every request, and invite
the model to call it. There is nothing to soften, because no MCP caller of this module exists in the platform today.

**A deprecation window of the kind this ADR imagines buys less than usual here**, and that is the general lesson
worth keeping. The thing that changed is what a submission's answer means, so a caller that keeps calling the old name
still has to be rewritten. A window helps when the shape of an answer changes; it helps much less when the shape of
the interaction does.

`schema_version` is unchanged at `"1"` and still rides on the result description a successful job carries, so a
caller reading a result branches on one field exactly as before.
