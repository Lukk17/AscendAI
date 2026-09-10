# ADR-010: Access-List Capture Reads Effective Permissions, Not the Change Feed

## Status

Deferred, 2026-09-05. Not implemented by the OpenSpec change `add-document-connectors`, and not accepted by it. This file is the draft that moves into `apps/ascend-agent/docs/architecture/decisions/` on archive with this status intact, taking the next free number at that time.

## Deferral, 2026-09-05

Group membership now comes from Keycloak realm groups alone, so `add-auth-and-identity` mints principals only in the `local` and `tenant` namespaces. A SharePoint permission entry names an Entra ID directory object id, which no principal in this version can equal and which the typed factory rejects outright. Capture has nothing it can produce, so there is no capture trigger to separate from the content feed and no `permissions_confirmed_through` on the cursor.

Nothing below was found to be wrong. It is kept whole because the reasoning is the expensive part: that a source may or may not report a sharing edit at all, that a folder-level revocation is reported once on the folder and never on its descendants, and that both failures are silent, are findings that a future reader would otherwise rediscover by shipping the bug.

What has to happen for this record to become active: a principal namespace a source identifier can mint into, which is deferred on the identity side, and the owner's open decision about how a customer's directory groups relate to Keycloak's.

The consequence of leaving it deferred is stated as a named limitation in this change's design document: a connector-synced document is visible to everyone in the company that owns it.

## Context

ADR-M004 settles that every chunk carries a mirrored access list. It does not say where a connector gets that list from, and there are two candidates.

The cheap one is the content change feed the connector already consumes. Microsoft Graph's drive delta and Google Drive's changes feed both return changed items, and if a permission edit showed up there as a change, capture would be free: process the entry, read whatever permission data it carries, done. No extra requests, no extra schedule, no extra throttling budget.

The other is to ask the source what an item's effective permissions are, on a trigger of capture's own, whether or not the item appeared in the change feed.

The current shape of `add-document-connectors` assumes the first without saying so. Its change detection is a content delta query and nothing in it reads permissions, so an access list would only ever be refreshed on the runs where a file's bytes happened to change.

## Decision

Capture reads the item's effective permissions from the source. It does not derive them from the content change feed, and it does not treat an item's absence from that feed as evidence that its permissions are unchanged.

Capture runs on its own trigger. Every sync run confirms permissions for the items whose confirmation is due, regardless of what the content delta returned, and records the confirmation time in a `permissions_confirmed_through` field on the sync cursor that advances independently of the content cursor.

## Consequences

### Why the change feed cannot carry this

Sources are inconsistent about reporting permission edits at all. A sharing change on an item whose bytes did not change may or may not surface as a change, depending on the source, the kind of edit, and the API version. A pipeline that reads "not in the delta" as "permissions unchanged" is correct exactly as often as the source happens to be generous, and there is no way to find out which case a given customer is in short of asking the source directly.

Sources are also inconsistent about inherited changes, and this one is worse because it is systematic rather than occasional. Revoking a group's access to a folder changes the effective permissions of every item beneath it, and sources report that as one change on the folder, not as a change on each descendant. A pipeline reading only the item feed sees a folder event it has no item to act on, and every document in that tree keeps serving an access list that stopped being true. The revocation an administrator performed is invisible to the system that was supposed to enforce it.

Both failures share a shape. Nothing errors, no counter moves, no log line appears, and the product keeps answering. The only observable symptom is somebody retrieving a document they were revoked from, which nobody reports because it looks like the product working.

### Trade-offs

- Capture costs requests the content sync would not have made, against the same per-tenant throttling budget. ADR-011 exists to make that cost survivable, and the two decisions only work together.
- The revocation latency a customer is told is now the permission confirmation interval, not the content sync interval. Those are different numbers and the confirmation one is the honest answer.
- The sync cursor grows a second dimension, and a run can now succeed on content and fail on permissions. That is a real increase in the number of states an operator has to understand, and it is the price of the two being genuinely independent.
- `acl_synced_at` now means what ADR-M004 says it means, when the list was last confirmed rather than when it last changed, which is what makes the staleness sweep in ADR-014 measurable at all.

### Alternatives considered

- **Read permissions only for items that appear in the content delta.** Cheapest option and it handles the case where an edit and a share happen together. Rejected because it is exactly the inference this decision rejects: it leaves a permission-only change undetected until something unrelated touches the bytes, which for a policy document that nobody edits is never.
- **Subscribe to permission-change notifications from the source.** Attractive, and it is where this should eventually go. Rejected for the first iteration because it is provider-specific plumbing with its own delivery guarantees, its own renewal lifecycle, and its own failure mode of silently expiring, and because a polling confirmation schedule is needed as the backstop regardless of whether notifications exist.
- **Confirm every item on every run.** Simple and always fresh. Rejected on throttling: a large drive would spend an entire run's budget confirming permissions and land no documents. The confirmation schedule is what makes the cost bounded.

## Related

- ADR-M004 (`docs/architecture/decisions/ADR-M004-acl-mirroring-onto-chunks.md`) for why the list is mirrored at all
- `docs/architecture/permission-aware-retrieval.md`, "Failure mode one: the permission-only change"
- Design decision D8, and D12 for the cursor state this requires
- ADR-011, which makes the request cost of this decision affordable
