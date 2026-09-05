# ADR-016: A Non-Destructive Freshness Check Watches the Connector, Not the Access List

## Status

Proposed, 2026-09-05. Accepted when the OpenSpec change `add-document-connectors` lands. This file is the draft that moves into `AscendAgent/docs/architecture/decisions/` on archive, taking the next free number at that time.

## Context

ADR-014 answered a real question with a blunt control: when the process that refreshes a mirrored access list stops, nothing breaks, nothing errors, and the product keeps answering from permissions that stopped being true, so the lists are emptied once they pass a maximum age and the documents go invisible. The reasoning was that a product which goes quiet is a support ticket on day one, and a product which keeps answering from stale authorization is an incident found late by whoever it harmed.

The scope this change now ships removes the thing that control was protecting. Per-document access-list capture is deferred, because group membership lives in Keycloak alone and no principal this version can mint equals an identifier a file store hands back. A connector-landed document therefore carries `tenant:everyone:{tenantId}` and nothing else, stamped at ingestion by `add-tenant-isolation`'s producer default.

That single grant cannot go stale. Everyone in the company holds it, nobody at the source can revoke it, and no capture path exists to stop running. Emptying it would remove documents from people who were never restricted from them, to contain an authorization decision that was never made.

But the failure shape ADR-014 identified has not gone anywhere. It has moved. What can still stop silently in this version is the sync: a client secret revoked in Entra ID, a delta token stuck in a resync loop, a scheduler thread that never fires again after a deployment, a connector disabled during a migration and never re-enabled. When that happens nothing errors, the corpus keeps answering, and it answers from content that is weeks out of date, including from documents that were deleted at the source and are still retrievable here. That is the failure this change's own opening calls the worst one a RAG product has.

## Decision

A scheduled freshness check compares each enabled connector's last successful sync against its configured maximum sync age and marks the connector stale when it has exceeded it. The flag is returned by the connector read and list endpoints, and the time since each connector's last successful sync is exposed as a gauge alongside a count of stale connectors. A successful sync clears the flag. A run with trigger type `FRESHNESS_CHECK` is recorded only when a connector's stale state changes.

The check writes nothing to MinIO, writes nothing to the vector store, and does not call the source.

A connector's maximum sync age must be greater than the interval its cron schedule fires on. The framework rejects a configuration where it is not, at write time.

## Consequences

### What is kept from ADR-014 and what is dropped

Kept: the failure shape, that a silent outage in a refresh path is worse than a loud one. Kept: that the control must not depend on the path that failed, which is why this check reads two local columns and calls nothing. Kept: that a control needs a defined boundary, so "it has been broken for a while" becomes a specific age with a specific moment at which somebody sees it. Kept: the configuration invariant, in its new pair of values, because a maximum age below the refresh interval is silent right up until it fires on everything at once.

Dropped: the enforcement. ADR-014 traded availability for correctness on a control that existed for correctness, and that trade was right when the list was the only thing standing between a revoked person and a document. Here there is no correctness to buy, so the trade would be availability for nothing.

### Why a signal rather than an alert, given ADR-014 rejected an alert

ADR-014 rejected alerting for a specific reason: an alert is a notification and not an enforcement, and the system it would notify about is actively serving stale authorization decisions in the meantime. If the alert is missed, nothing else stops it.

Neither half of that applies here. Nothing is serving an authorization decision, so there is no enforcement available to be traded away, and what a missed signal costs is a knowledge base that answers from older content rather than a document reaching somebody who lost access to it. A signal is the proportionate control when the harm is staleness rather than disclosure. The distinction is worth stating because the two records otherwise appear to contradict each other on the same question.

### Trade-offs

- A stale connector's documents stay retrievable and stay stale. Somebody can get an answer from a policy that was superseded three weeks ago, and nothing in the response says so. That is the accepted cost, and it is the reason the flag is on the API rather than only in a metric.
- The check depends on an operator or a dashboard looking. It is a signal, and a signal nobody reads is worth nothing. Mitigated by exposing it on the same read an administrator already performs to see their connectors, rather than only as a metric behind a dashboard nobody has built yet.
- Basing the check on last successful sync rather than on document age means a connector whose runs all end `PARTIAL` looks fresh while making almost no progress. Accepted for this iteration: a `PARTIAL` run did complete a window, and the run history shows the pattern. A per-item content age would be a second table for a second failure that this scope does not need.
- One more scheduled job and one more claimed row lock. Cheap, and it reuses the claim the scheduled sync already needs.

### Alternatives considered

- **Keep ADR-014's sweep, emptying the tenant-everyone grant on stale connectors' documents.** Rejected as the option that pays a real availability cost for nothing. The grant it would strip is the whole company, so the failure it would contain is one that cannot occur.
- **Do nothing until capture returns, since nothing can go wrong with permissions.** Rejected because the outage did not disappear, it changed target. A connector that has silently stopped is exactly the "answers keep coming but stop being true" failure this change was written to prevent, and shipping automated sync without a way to see that it stopped would be shipping the problem alongside the fix.
- **Alert only, with no state on the connector row.** Rejected because a transient notification is harder to answer the question "is this connector healthy right now" with than a flag on the resource an administrator is already reading. The flag and the metric are the same fact at two latencies.
- **Delete or hide a stale connector's documents.** Rejected for ADR-014's own reason, inverted: unrecoverable, expensive to undo, and it takes availability from people to signal a problem that harms nobody.
- **Measure document age rather than connector freshness.** More precise and it would catch a connector making no progress. Rejected as premature here: it needs a per-item table this scope otherwise does not need, and it is the natural thing to add alongside `connector_item_acl` when that table returns with capture.

## Related

- ADR-014, whose instinct this record keeps and whose enforcement it drops, deferred rather than withdrawn
- ADR-M006 (`docs/architecture/decisions/ADR-M006-deny-by-default-on-missing-acl.md`) for why an emptied list means invisible, which is the mechanism this record declines to use
- Design decision D19, and D18 for the company-wide grant that makes enforcement unnecessary here
- `add-auth-and-identity`, whose named limitation states the same scope cut from the identity side
