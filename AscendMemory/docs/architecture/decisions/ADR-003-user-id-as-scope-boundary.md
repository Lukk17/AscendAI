# ADR-003: `user_id` as Memory Scope Boundary

**Date**: 2026-06-01
**Status**: Accepted
**Deciders**: Łukasz Sarna

---

## Context

Memory operations must be isolated per user. Without isolation, a search by user A could return memories belonging to
user B. The scope boundary must be enforced consistently on both the REST API and the MCP surface.

The question is where to enforce the boundary: inside this service (at the mem0ai filter level), at the caller
(AscendAgent), or at a separate identity/auth layer.

---

## Decision

Every operation (insert, search, delete, wipe) requires a `user_id` string parameter. mem0ai passes `user_id` to
Qdrant as a payload filter on every insert and search. The service itself performs no authentication; it trusts the
caller to provide the correct `user_id`.

(`src/api/rest/rest_endpoints.py:21,35,66,79`, `src/api/mcp/mcp_server.py:12,27,41,53`)

---

## Alternatives Considered

### Alternative 1: Session token / JWT on the memory endpoint

- **Pros**: The service could verify the caller's identity and derive the `user_id` from the token without trusting
  the caller.
- **Cons**: Adds an auth dependency (key management, token validation library) to a service that is only reachable
  from AscendAgent on the internal compose network. Significant complexity for a service that is not directly exposed
  to the internet.
- **Why not**: Authentication is the responsibility of AscendAgent, which enforces its own auth before calling
  AscendMemory. Adding a second auth layer inside AscendMemory is premature.

### Alternative 2: Implicit session derived from connection context

- **Pros**: The caller does not have to pass `user_id` on every request.
- **Cons**: Stateful sessions break the stateless REST contract and complicate the MCP surface. Both REST and MCP
  callers would need session management.
- **Why not**: Stateless per-request `user_id` is simpler and consistent with how other platform services identify
  users.

---

## Consequences

### Positive

- The API is stateless. No session management.
- The same `user_id` parameter works identically on REST and MCP.
- Isolation is enforced by Qdrant payload filter at query time.

### Negative

- The service trusts the caller's `user_id`. A malicious or misconfigured caller can read or wipe another user's
  memories.
- There is no audit log of which caller accessed which user's data.

### Risks

- **Caller misconfiguration**: AscendAgent passes the `user_id` it receives from the chat request. If AscendAgent
  has a bug that passes the wrong `user_id`, memories leak across users silently.
