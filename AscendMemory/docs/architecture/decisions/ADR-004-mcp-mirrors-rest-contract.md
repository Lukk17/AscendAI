# ADR-004: MCP Surface Mirrors the REST Contract

**Date**: 2026-06-01
**Status**: Accepted
**Deciders**: Łukasz Sarna

---

## Context

AscendMemory must be reachable both from AscendAgent (which uses an HTTP client) and from any FastMCP-capable agent
(which uses the MCP tool-call protocol). The question is whether these two surfaces should expose the same operations,
a subset, or a different abstraction.

---

## Decision

The four MCP tools (`memory_insert`, `memory_search`, `memory_delete`, `memory_wipe`) map one-to-one to the four REST
endpoints. Both surfaces delegate to `get_memory_client()` from the same `src/service/memory_client.py` module. There
is one code path for all memory operations regardless of the caller's protocol.

The one intentional divergence: `memory_insert` (MCP) accepts only `text`, not `messages`. The REST `insert` endpoint
accepts both. This is because the `messages` format (list of `{role, content}` dicts) is natural for a REST JSON
body but awkward as a typed MCP tool argument. AscendAgent uses the REST endpoint and can pass `messages`; MCP
callers pass `text` only.

(`src/api/rest/rest_endpoints.py`, `src/api/mcp/mcp_server.py`)

---

## Alternatives Considered

### Alternative 1: MCP only (no REST endpoint)

- **Pros**: Single API surface; simpler to document.
- **Cons**: AscendAgent is a Java Spring Boot service. It calls AscendMemory via a Java `RestClient`. Adding MCP
  client setup in Java for an internal service adds complexity. REST is already available via Spring's HTTP client.
  See AscendAgent ADR-003.
- **Why not**: REST is the natural fit for AscendAgent's existing Java HTTP infrastructure.

### Alternative 2: REST only (no MCP endpoint)

- **Pros**: No MCP session management overhead.
- **Cons**: Blocks future MCP-native agents from using memory without an HTTP client. The platform's direction is MCP
  for tool services.
- **Why not**: Adding the MCP surface costs little (FastMCP wraps the same service module), and the platform's
  monorepo-level ADR-M002 establishes MCP as the standard tool protocol.

---

## Consequences

### Positive

- No duplication of business logic; both surfaces call `get_memory_client()`.
- MCP-capable agents can use memory without an HTTP client.
- REST remains available for Java callers that cannot use MCP.

### Negative

- The MCP `memory_insert` tool does not support `messages`, creating a feature gap between the two surfaces.
- The MCP mount-last constraint (`app.mount("/", mcp_asgi_app)` must be last) requires discipline when adding new
  FastAPI routes.

### Risks

- **FastMCP version changes**: FastMCP 3.3.1 is pinned (upgraded from 2.14.5 to align with AscendWebSearch). The ASGI
  mount pattern and lifespan integration must be re-validated on each upgrade.
