# ADR-012: Fail Closed on a Missing Tenant Context or Principal Set

## Status

Proposed, 2026-09-04. Becomes Accepted when the OpenSpec change `add-tenant-isolation` is implemented.

## Context

Every tenant-scoped operation needs a resolved tenant id, and similarity search and source presigning additionally need the caller's resolved principal set. Both come from the request, by way of `add-auth-and-identity`. Both can be absent: an unauthenticated path, a misconfiguration, an internal caller that forgot to propagate context, an asynchronous worker running off the request thread, a scheduled job.

Something has to decide what happens then, and the tempting answers are the dangerous ones. Falling back to the `default` tenant keeps local workflows working. Falling back to a tenant-only filter when only the principal set is missing keeps search returning results and looks like a graceful degradation.

There is a second distinction hiding here. A principal set that resolves to an empty set is not the same as one that failed to resolve. The first is a real answer that belongs to real callers, for example somebody whose cross-provider identity link is broken and who legitimately holds only `tenant:everyone`. The second is a failure. Code that represents both as an empty collection cannot tell them apart, and will treat the failure as the answer.

## Decision

Fail closed, on both values, with no fallback of any kind.

- An unresolved tenant id throws. It does not degrade to the `default` tenant, to an unfiltered query, or to a shared Redis key.
- An unresolved principal set throws for similarity search and for source presigning. It does not degrade to a filter carrying the tenant conjunct alone.
- The web layer surfaces both as 401 or 403 per the error contract in `add-auth-and-identity`, and service-layer callers get an exception.
- The principal accessor returns an `Optional` of the set, so an unresolved set and an empty set are distinguishable at the type level. An empty set is a successful answer, and a search runs with it and returns nothing.

`default` is a migration target reached through ordinary authenticated context like any other tenant, never a fallback.

## Consequences

- A propagation bug produces an error, not a leak. The failure is loud, immediate, and attributable to the request that caused it.
- Degradation is visible rather than silent. A tenant-only fallback would return 200 with a fluent answer drawn from documents the caller is not entitled to, and nothing in the response or the logs would say the access axis was skipped.
- Anything running off the request thread has to carry the context explicitly. The presign fan-out onto the task executor is the concrete case: tenant and principals are captured on the request thread and passed into the asynchronous work, because reading the accessors inside the worker throws on every request, which is fail-closed as an outage rather than as a control.
- Existing unauthenticated local workflows break the day this lands. That is the explicit cost of depending on `add-auth-and-identity`, and the development-profile token that carries `tenant=default` is owned by that change.
- A background or scheduled job that legitimately spans tenants cannot rely on ambient context and must loop over tenants explicitly, passing each id. The one-shot migration task is written that way.

### Alternatives considered

Fall back to the `default` tenant when context is missing. Keeps everything working and turns every propagation bug into a cross-tenant read into the default tenant's pool, which after the migration is exactly where the existing single-company corpus lives. Rejected.

Fall back to a tenant-only filter when only the principal set is missing. Rejected for the same shape of reason, one level down. It over-shares inside a tenant, it is invisible in the response, and it hands the caller precisely the documents their company chose to restrict, which is the failure the access axis exists to prevent.

Treat an unresolved principal set as an empty set and return no results. Fails closed on retrieval, and is still wrong: it makes a resolution outage indistinguishable from a legitimately narrow caller, so the symptom is a support ticket saying search finds nothing, with nothing in the system to explain it. An error names the cause.

Log a warning and continue. A log line on a system that returns 200 is not a control. It is found during the incident review rather than before it.

## Related

- OpenSpec change `add-tenant-isolation`, design decision 2, and the `tenant-isolation` requirement "Tenant context and principal set resolved per request, fail-closed"
- ADR-010, the discriminator model this rule protects
- ADR-011, the single call site the rule is applied at
- `docs/architecture/decisions/ADR-M006-deny-by-default-on-missing-acl.md`, the same instinct applied to a chunk rather than a request
