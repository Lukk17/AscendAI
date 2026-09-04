# ADR-M006: A Chunk With No Access List Is Invisible

---

### Status

Accepted (2026-09-04)

---

### Context

Chunks without an `acl` payload field will exist. Every chunk currently in the two Qdrant collections predates this design. A connector run can fail after landing bytes and before capturing permissions. A future ingestion producer can be added by somebody who does not know the field is mandatory. A migration can be interrupted halfway.

Something has to decide what the search does with such a chunk, and there are only two answers.

---

### Decision

A chunk with no `acl` field, or with an empty one, matches no caller's principal set and is retrieved by nobody. This holds regardless of the caller's roles: an `ADMIN` or `PLATFORM_ADMIN` sees exactly what their group principals allow, because a role is not a principal and an administrative role does not widen the filter.

The `tenant:everyone:{tenantId}` pseudo-group is the deliberate way to make a chunk broadly readable. It is written onto the payload on purpose, by a producer that decided to, and it is visible in `acl` when anybody inspects the point.

---

### Alternatives Considered

#### Alternative 1: Missing list means readable by the tenant

- Pros: Existing chunks keep working through the migration with no backfill. A capture bug degrades into over-sharing inside one company rather than into a product that finds nothing. Nobody files a support ticket.
- Cons: Every failure in the capture path becomes a silent widening of access, and it is silent in the worst way: the system behaves normally, answers well, and nothing anywhere indicates that a document is being served to people the source does not permit. The one bug class this whole design exists to prevent is the one this default reintroduces, on every path that forgets the field.
- Why not: A default that makes the failure mode invisible is the wrong default for an authorization control. Nobody discovers over-sharing by using the product.

#### Alternative 2: Missing list means readable, with a warning log

- Pros: Keeps the migration easy and leaves a trace.
- Cons: The trace is a log line nobody reads on a system that is behaving correctly. It is Alternative 1 with a paper record that will be found during the incident review rather than before it.
- Why not: A log line is not a control.

#### Alternative 3: Backfill everything to `tenant:everyone` and then require the field

- Pros: Existing chunks stay reachable, and after the backfill the strict rule applies.
- Cons: This is not an alternative to the decision, it is a migration step underneath it. Adopted as such: the one-shot migration that [add-tenant-isolation](../../../openspec/changes/add-tenant-isolation/) already runs stamps `tenant:everyone:{tenantId}` onto pre-existing points at the same time it stamps `tenant_id`, so pre-existing content becomes explicitly tenant-wide rather than implicitly so.
- Why not: Not rejected. Folded in.

---

### Consequences

- Positive: Every capture failure produces visible degradation instead of silent over-sharing. A document nobody can find gets reported within a day.
- Positive: Access is always explainable. Whatever is in `acl` is why the chunk was returned, and there is no unwritten rule that also grants access.
- Positive: Combined with the staleness sweep, a capture outage has a defined end state: lists age out, documents go quiet, the age metric says when it started.
- Negative: A producer that forgets the field silently indexes content nobody will ever retrieve. The chunk exists, costs storage, and does nothing.
- Negative: An administrator cannot see a document by virtue of being an administrator, which will surprise somebody debugging a retrieval problem.

#### Risks

- Pre-existing chunks become unreachable if the backfill does not run. Mitigated by folding the `tenant:everyone` stamp into the same one-shot migration that [add-tenant-isolation](../../../openspec/changes/add-tenant-isolation/) already requires for `tenant_id`, so the two cannot diverge.
- A silently-invisible corpus after a bad ingest. Mitigated by the capture-failure counter and the access-list-age metric, and by making a cap violation fail the file loudly rather than writing a truncated list.
