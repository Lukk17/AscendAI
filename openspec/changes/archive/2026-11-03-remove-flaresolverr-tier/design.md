## Context

After `enhance-web-search-tier-ladder` the FlareSolverr tier is off by default and the patched-browser tiers carry
its work. One release with the flag off is the evidence that nothing needs it.

## Decisions

### D1: The public value is removed and never reused

ADR-011 made tier values public. `3-flaresolverr` is removed from `TierName`, from the ladder and from `TIER_ORDER`, so
it leaves the accepted input set like any value that never existed. A request that passes it gets the normal refusal
for a value outside the allowed set: HTTP 400 with the problem body code `validation` of `add-ascend-python-common` on
REST, and the refusal of an invalid tool argument on MCP. No code of its own is kept for it (owner answer 93 of
2026-10-08, review item C16, which replaces for the removed value the part of owner answer 67.7 of 2026-10-04 that kept
`tier_disabled` for it). A future tier never takes the name or the number 3, and ADR-018 records that rule.

### D2: No compatibility with old session records

The `PRODUCED_BY_FLARESOLVERR` constant and its handling are deleted, with no special case and no test for records
the FlareSolverr tier stored before this change. The owner decided on 2026-10-02 (confirmed by owner answer 73.1 of 2026-10-06) that there is no existing data to
keep, so such records are not migrated, and the owner clears stored sessions at will. This holds only until the first
real customer deployment.

### D3: The container goes from both compose files in the same commit

The development file and the standalone file must stay aligned, per the sync rule in
`apps/ascend-web-hunter/AGENTS.md`. The root `AGENTS.md` list of fixed container names drops `flaresolverr` in the
same commit.

### D4: ADR-018 and version 0.0.13

The ADR numbers ADR-013 to ADR-017 are taken by `open-several-novnc-windows-at-once` (ADR-013),
`detect-challenge-walls-in-any-language` (ADR-014), `enhance-web-search-tier-ladder` (ADR-015) and
`enhance-web-search-extraction-and-tiers` (ADR-016 and ADR-017), which land before this change. This change writes
ADR-018. `enhance-web-search-crawl-at-scale` writes ADR-019 and `add-file-download` writes ADR-020. The version follows
the owner decision of 2026-10-08, one named version per change, in build order: 0.0.7 (`add-ascend-python-common`),
0.0.8 (`add-python-runtime-upgrades`), 0.0.9 (`open-several-novnc-windows-at-once`), 0.0.10
(`detect-challenge-walls-in-any-language`), 0.0.11 (`enhance-web-search-tier-ladder`), 0.0.12
(`enhance-web-search-extraction-and-tiers`), and 0.0.13 for this change.

## Risks

- A site that only FlareSolverr could clear. Mitigated by the one release with the flag: if an operator had to turn
  it on, this change does not start, and the reason is recorded first.

## Owner decisions of 2026-10-06

Answer 73.1: the data that exists today in the development database, Redis, Qdrant, object storage and AscendMemory is disposable. No change converts it, backfills it or depends on it, and any change may start from empty stores. Session records the FlareSolverr tier stored before this change stay unsupported, and the change needs none of today's data.

## Owner decisions of 2026-10-08

The owner approved on 2026-10-08 the fixes of the review of the group 1 and group 2 changes of 2026-10-07.

- Item 1: the deltas against the text of `enhance-web-search-tier-ladder` are written now. `web-search-tier-ladder`
  removes "FlareSolverr is disabled by default for one release" and modifies "Ladder order with two patched-browser
  tiers". `web-search-authenticated-sessions` modifies "Stored session is replayed into every fetch tier", and removes "A stored
  session is replayed by the tier that earned it" in favour of the new requirement "A stored session is replayed by
  the browser family that earned it" with the same browser rule, because a MODIFIED block may not drop the FlareSolverr
  scenarios. Task 1.1, which put this off, is removed.
- Item 10: this change writes ADR-018 (D4).
- Item 22: the version is one patch step after the change before this one (D4).
- Owner decision of 2026-10-08, "one named version per change, in build order": this change ships as
  ascend-web-hunter 0.0.13, one patch step after 0.0.12 of `enhance-web-search-extraction-and-tiers` (build group 2,
  position 6), with one CHANGELOG entry (D4, task 4.3).

Answer 93: review item C16 is applied. `3-flaresolverr` is no longer kept as a reserved value that answers
`tier_disabled`. It leaves the accepted tier values, and a request that passes it gets the normal 400 validation
refusal on REST and the invalid argument refusal on MCP (D1, the spec requirement "The removed FlareSolverr tier value
is refused", tasks 2.1 and 2.2). This replaces, for the removed value only, the part of owner answer 67.7 of
2026-10-04 that kept `tier_disabled` for it. The rule that no future tier takes the name or the number 3 stays, in
ADR-018.

Answer 92: review item B1 (remove FlareSolverr inside `enhance-web-search-tier-ladder` and drop this change) is not
applied, by the owner's own list of things not to apply. This change stays a change of its own after one release with
the flag off.

Answer 91.3: tasks 5.1 and 5.2 are removed. The tier-ladder spec of `enhance-web-search-tier-ladder` task 7.2 no
longer holds the steps on a selected `3-flaresolverr` and on `/ready`, because unit tests prove both, so this change has
nothing to update in it and adds no Bruno request for the removed value. The refusal of the removed value is proven by
the unit tests of task 2.1, readiness by task 2.2, and the missing container by the check of task 3.1. The real-site
specs 6 and 12 still run on a stack without FlareSolverr (task 5.5).

Answer 87: confirmed, nothing to change. Removing a tier adds no state, and nothing of this change has to be shared
between several ascend-web-hunter containers.

Answer 85.1: no task of this change exports a key or a secret in a shell.

Answer 94.6: `4b-camoufox` raises `tier_disabled` (409) while Camoufox is switched off (`enhance-web-search-tier-ladder` D7), so task 2.2 keeps the `tier_disabled` registry entry and its test, and removes only the handling the FlareSolverr flag needed. The removed value `3-flaresolverr` still gets the normal 400 validation refusal (D1).

Answer 98: this change adds no setting and no value with a default. It removes two settings, `FLARESOLVERR_URL` and
`FLARESOLVERR_ENABLED`, and the configuration rule makes their removal complete in one commit: the code, the lines of
the `ascend-web-hunter` service in both compose files, the lines of both `.env.example` files and the rows of the bundle
README (sync rule), and the rows of `docs/configuration.md`, the per-service configuration reference of
ascend-web-hunter (tasks 2.2, 3.1 and 4.1). The resource limits of the `flaresolverr` compose service leave with the
service. The `tier_disabled` code and its status 409 stay a constant of the error registry. No ticked task changes.
No test or measurement of this change uses LM Studio, and no text of this change names the old `e2e` profile or plans
several copies elsewhere.

## Owner decisions of 2026-10-09

Answer 100.6: every published host port is a setting. `fix-linux-docker-host-access` task 10.2 makes the loopback host port of `flaresolverr` the setting `FLARESOLVERR_HOST_PORT` (default 8191) with a root `.env.example` line, a row in the bundle README's differences table and a row in `docs/CONFIGURATION.md`. This change removes the service, so task 3.1 removes that setting with all of them in the same commit.
