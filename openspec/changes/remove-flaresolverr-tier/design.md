## Context

After `enhance-web-search-tier-ladder` the FlareSolverr tier is off by default and the patched-browser tiers carry
its work. One release with the flag off is the evidence that nothing needs it.

## Decisions

### D1: The public value is reserved, not reused

ADR-011 made tier values public. `3-flaresolverr` stays in the accepted input set only to answer HTTP 400 on REST and
a tool error on MCP with a detail naming a removed tier. It is removed from the ladder and from `TIER_ORDER`. A future
tier never takes the name or the number 3.

### D2: Old sessions are replayed by the browser tiers

A record with `produced_by` `3-flaresolverr` is read like any session without a browser producer: the browser tiers
replay it. No migration of Redis data is needed.

### D3: The container goes from both compose files in the same commit

The development file and the standalone file must stay aligned, per the sync rule in
`apps/ascend-web-hunter/AGENTS.md`. The root `AGENTS.md` list of fixed container names drops `flaresolverr` in the
same commit.

## Risks

- A site that only FlareSolverr could clear. Mitigated by the one release with the flag: if an operator had to turn
  it on, this change does not start, and the reason is recorded first.
