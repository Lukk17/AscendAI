# ADR-011: Capture Permissions Container-First, Not Per Document

## Status

Deferred, 2026-09-05. Not implemented by the OpenSpec change `add-document-connectors`, and not accepted by it. This file is the draft that moves into `AscendAgent/docs/architecture/decisions/` on archive with this status intact, taking the next free number at that time.

## Deferral, 2026-09-05

This record exists to make ADR-010's request cost affordable, and ADR-010 is deferred, so there is no cost to manage. No permission is read, no container list is captured, no `connector_item_acl` row is written, and the permission throttling budget is not split from the content budget.

The analysis is kept whole and it is the part most worth keeping. That companies set sharing on team folders and inherit it downwards, that Graph exposes the distinction through `inheritedFrom`, that this turns one request per document into one per folder plus one per uniquely-shared item, and that the one real gap it opens is an item which stops inheriting between runs and is closed by the per-item confirmation schedule rather than eliminated, are all conclusions that took work and that return unchanged.

What has to happen for this record to become active: ADR-010 becomes active, since this decision is only ever a way of paying for that one.

## Context

ADR-010 requires capture to ask the source for effective permissions rather than infer them. That decision is correct and, taken literally, unusable.

Microsoft Graph exposes an item's sharing through a separate request per item. A first full enumeration of a corporate drive is commonly tens of thousands of items. One permission request each, against a per-tenant Graph throttling budget the content sync is already competing for, means the first sync either runs for days or spends its whole budget on permission reads and lands no documents. Either way the customer's first impression of the product is that it does not work.

Something has to make the common case cheap without making the uncommon case wrong.

The lever is how sharing is actually configured in companies. Permissions are set on team folders and inherited by their contents. A drive with 40,000 documents typically has a few hundred distinct permission sets, almost all of them attached to folders, and a small number of individually-shared exceptions. Sources expose that structure: Graph marks a permission entry inherited from an ancestor with `inheritedFrom`, so an item whose collection contains an entry without that marker is one that has something of its own.

## Decision

Capture is container-first.

The connector reads permissions for the drive root and for each in-scope folder, and records the resulting list against that container. An item that inherits its container's permissions takes the container's captured list with no request of its own, and its stored access-list record names the container it inherited from.

A per-item read is issued in exactly two cases: an item whose permission collection carries an entry the source does not mark as inherited, and an item whose permission confirmation has come due under the schedule from ADR-010.

A container's permission change invalidates every item recorded as inheriting from it, and each of those items receives a payload-only access-list update in that run.

## Consequences

### What this buys

A first full enumeration goes from one request per document to one request per folder plus one per genuinely uniquely-shared document. On the corpus shape described above that is two to three orders of magnitude fewer requests, which is the difference between a first sync that completes and one that does not.

Detection of a folder-level revocation becomes cheap in the direction that matters. One folder read detects a change affecting a thousand documents, and the run then performs a thousand payload-only updates, which are local and fast, rather than a thousand permission reads, which are remote and throttled. The container reference on each item's access-list record turns that fan-out into a local query rather than a scan.

### Trade-offs

- An item that stops inheriting, because somebody set a unique permission on it between runs, is invisible to a container read. That is the one real correctness gap this optimisation introduces, and it is closed by the per-item confirmation schedule: such an item is read individually on the first run after its confirmation is due, so the window is one confirmation interval rather than unbounded. The gap is real and bounded, not eliminated.
- The connector now stores per-item inheritance state, which is another table that can drift from the truth. The staleness sweep in ADR-014 reconciles by age rather than by trust, so drift costs an extra payload write rather than a missed revocation.
- Container permissions are captured for folders that may contain no in-scope documents, so some reads are wasted. Cheap compared to the alternative, and bounded by folder count rather than item count.
- The optimisation is specific to sources that expose an inheritance marker. A source that does not would need per-item reads, which is a per-connector cost rather than a framework one, and is part of why the capture abstraction is a separate interface from the connector itself.

### Alternatives considered

- **One permission read per item, always.** Correct, simple, and no inheritance state to keep. Rejected on cost: it is the option that makes ADR-010 unusable, and the throttling budget is not negotiable on a large tenant.
- **Read permissions only at the drive root and treat the whole drive as one access list.** The extreme version of container-first. Rejected because it is wrong rather than merely coarse: it grants the whole drive's audience access to a folder that was deliberately restricted, which is exactly the over-sharing this design exists to prevent.
- **Cache permission lists by their content hash and read each distinct list once.** Attractive because it dedupes across containers. Rejected as premature: the hash is only known after the read, so it saves storage rather than requests, and the shared `acl_version` already gives the same comparison benefit without a second cache to keep coherent.
- **Reconstruct inheritance ourselves from the folder tree rather than trusting the source's marker.** Rejected for the same reason ADR-M007 rejects walking a group hierarchy: it means reimplementing the source's own semantics to arrive at the source's own answer, more slowly and with more ways to be wrong.

## Related

- ADR-010, which creates the cost this decision manages
- ADR-013, for the payload-only updates a container revocation fans out into
- ADR-014, which reconciles the inheritance state this decision stores
- Design decision D9, and D3 for the `connector_item_acl` table
