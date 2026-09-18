# ADR-011: A caller may choose where the escalation chain starts

## Status

Accepted, 2026-09-18. Reverses Alternative 3 of [ADR-001](ADR-001-multi-tier-extraction-strategy.md) in part.

## Context

ADR-001 fixed the escalation order at six tiers and rejected a caller-selectable strategy under its Alternative 3,
on the grounds that "the service is the expert on extraction; callers should only control `heavy_mode` as a coarse
override". That reasoning has held for the default path and still holds: the ascend-ai-agent has no site-specific
knowledge and should not acquire any.

What has changed is everything around that default. `heavy_mode` is not a general override, it means one specific
thing: skip tiers 1 and 2 and start at Playwright. There is no way to ask for FlareSolverr first, which is now a
meaningful request since [ADR-010](ADR-010-producer-aware-session-replay.md) made a FlareSolverr-produced clearance
worth replaying through the tier that earned it. There is no way to force the cheap tiers for a page an operator
knows is static, and no way for the e2e suite in `e2e/` to exercise one tier deliberately, which is how per-tier
behaviour is verified against a live stack.

The archived change `2026-09-18-enhance-web-search-scraping` specified a starting-tier override and did not build
it. The same change also left `output_format` reachable only from inside the process. Both are now exposed, and this
ADR covers the routing half.

## Decision

### D1, `tier` names one of the six existing strategy keys

The accepted values are exactly the keys `WebReader._build_strategies` uses and exactly the strings a successful read
already returns in `mode`: `1-beautifulsoup`, `2-trafilatura`, `3-flaresolverr`, `4-playwright_stealth`,
`5-crawlee_adaptive`, `6-novnc`. They are declared once as the `TierName` literal in `src/reader/web_reader.py` and
imported by the REST model and the MCP tool, so the three surfaces cannot drift and an unknown value is rejected by
the schema rather than by a runtime branch.

### D2, `tier` selects that tier and every tier after it

The override moves where the chain starts, it does not reduce the chain to one tier. `tier=3-flaresolverr` runs
FlareSolverr, then Playwright, then Crawlee, then NoVNC, exactly as the default ladder would from that point. A
caller that wants exactly one tier asks for the last one, or reads the `mode` in the response to see where it
actually landed.

### D3, precedence is login-redirect, then `tier`, then `heavy_mode` and the producer routing

A URL that matches a known login-redirect pattern still goes straight to `6-novnc` and is not fetched by the cheap
tiers, because `web-search-authenticated-sessions` requires that and a caller preference does not get to switch a
safety rule off. Below that, `tier` is the most specific instruction available and outranks both `heavy_mode` and
the producer-aware routing. With no `tier`, nothing changes at all.

### D4, `tier` joins the read cache key

A read at tier 1 and a read at tier 4 of the same URL can legitimately produce different content, so they are
different cache entries.

## Alternatives Considered

### Alternative 1: keep `heavy_mode` as the only override
- Pros: no new field, ADR-001 stands untouched.
- Cons: leaves the three needs above unmet, and pushes operators toward crude workarounds such as appending a query
  string to dodge the read cache, which is what the ADR-010 measurement had to do.
- Why not: the cost of the override is one optional field that defaults to unset, and the alternative is no route to
  a specific tier at all.

### Alternative 2: a per-domain tier configuration instead of a per-request field
- Pros: the service stays the expert, an operator encodes site knowledge once.
- Cons: a new configuration surface, a reload story, and a source of truth that drifts from the sites it describes.
  ADR-001 already names the missing per-domain tuning as a known negative, and this would be a much larger answer to
  it than the problem in front of us.
- Why not: YAGNI for a local single-user service, and it does not help the e2e suite, which needs a per-request
  choice.

### Alternative 3: let `tier` select exactly one tier with no escalation
- Pros: a sharper diagnostic tool, the answer comes from the named tier or not at all.
- Cons: every normal caller that names a tier as a hint then loses escalation and gets a failure where today it gets
  content from the next tier.
- Why not: D2 keeps the common case useful, and naming the last tier already gives the sharp case.

## Consequences

### Positive
- The e2e suite can address one tier directly rather than inferring it from `mode`.
- An operator debugging a site can ask for the tier they are debugging.
- A caller holding a FlareSolverr clearance can ask for FlareSolverr explicitly, without relying on the stored
  producer being read back correctly.

### Negative
- A caller can now choose a worse tier than the service would have chosen. That is what an override is.
- ADR-001's Alternative 3 is no longer wholly true and has to be read together with this ADR.

### Risks
- If a strategy key is ever renamed, `TierName`, the REST schema, the MCP tool description and any caller that
  hardcoded a value all move together. The single literal keeps the first three in step, not the fourth.

## Related

- `src/reader/web_reader.py` — `TierName`, `_from_tier`, `_select_strategies`, `_cache_key`.
- `src/api/rest/rest_endpoints.py` — the `tier` field on `ReadRequest`.
- `src/api/mcp/mcp_server.py` — the `tier` argument on `web_read`.
- [ADR-001](ADR-001-multi-tier-extraction-strategy.md), whose Alternative 3 this reverses in part.
- [ADR-010](ADR-010-producer-aware-session-replay.md), the routing this override sits above.
