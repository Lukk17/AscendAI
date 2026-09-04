# ADR-014: Access Lists Past a Maximum Age Are Emptied

## Status

Proposed, 2026-09-04

## Context

Every permission decision in this design is made against a mirrored copy, and the copy is only as good as the process that refreshes it. That process can stop without anything failing loudly: a client secret revoked in Entra ID, a delta token stuck in a resync loop, a scheduler that silently never fires after a deployment, an administrator removing the directory permission the app registration needed, a connector left disabled after a migration.

When it stops, nothing breaks. The chunks still have access lists. The searches still filter. The answers still come. The only thing that has changed is that the lists stopped being true, and there is no observable difference between a corpus whose permissions are current and one whose permissions froze three weeks ago.

That is the worst failure shape a control can have: it keeps returning a plausible answer after it stopped being an answer at all. Somebody revoked in week one keeps retrieving the document through week four, and the first person to find out is whoever the leak harms.

Something has to make that state visible, and it has to do so without depending on the thing that broke.

## Decision

A scheduled sweep finds items whose access list has not been confirmed within a configured maximum age and empties the `acl` on those items' chunks, through the payload-only path from ADR-013, recording each as an outcome under a run with trigger type `PERMISSION_SWEEP`.

Under the deny-by-default rule in ADR-M006, an emptied list makes the document invisible immediately.

The maximum age is configured per connector with a platform default, and it must be greater than that connector's permission confirmation interval. The framework rejects a configuration where it is not, at write time.

An administrator-triggered permissions-only resync exists alongside it, so a deliberate revocation does not have to wait for a confirmation tick.

## Consequences

### Why the blunt version is the right one

The sweep trades availability for correctness on a control that exists for correctness. A product that goes quiet is a support ticket on the first day, with `acl_synced_at` saying exactly when capture stopped. A product that keeps answering from permissions that stopped being true is an incident, discovered late, by the wrong person, with no timestamp to point at.

The sweep does not depend on the capture path working, which matters because the capture path is what failed. It reads a local table and writes payloads. A revoked client secret, an unreachable Graph, and a dead scheduler thread all leave the sweep able to run.

It also gives the outage a defined end state rather than an indefinite drift. Without it, "capture has been broken for a while" has no boundary and no moment at which anybody notices. With it, the boundary is the maximum age and the moment is the day search goes quiet.

### Trade-offs

- A capture outage now takes documents offline for people who were legitimately entitled to them. That is a real availability cost paid by innocent users, chosen deliberately over the alternative of serving documents to people who were not entitled to them.
- The misconfiguration where the maximum age sits below the confirmation interval makes a healthy connector sweep its own corpus. It is silent right up until it empties everything, which is why it is rejected at configuration write time rather than discovered at sweep time.
- Emptying a list is destructive to the mirrored copy, so recovery requires a full re-confirmation rather than a flag flip. Acceptable, because the state being recovered from is one where the mirrored copy was already wrong.
- The sweep writes a `PERMISSIONS_UPDATED` outcome per emptied item, which on a large corpus is a large run record. Bounded by the history retention cap, and worth the row count, because a sweep that emptied a corpus with no trace would itself be an unexplained outage.
- A disabled connector's documents age out and are eventually emptied. Intended and worth stating plainly, since an operator disabling a connector for a week will not otherwise expect its documents to go quiet.

### Alternatives considered

- **Alert on access-list age and change nothing.** Keeps everybody's access working and tells an operator about the problem. Rejected for the same reason ADR-M006 rejects a warning log in place of a control: an alert is a notification, not an enforcement, and the failure it notifies about is one where the system is actively serving stale authorization decisions in the meantime. If the alert is missed, nothing else stops it.
- **Fall back to `tenant:everyone` for stale lists.** Keeps the documents findable. Rejected because it converts a capture outage into deliberate company-wide over-sharing, which is precisely the outcome the whole design exists to prevent, applied automatically and at scale.
- **Delete the stale documents outright.** Achieves invisibility and frees storage. Rejected as unrecoverable: the documents would have to be re-ingested and re-embedded once capture is fixed, at full cost, where emptying a list only needs re-confirmation.
- **Sweep by re-reading the source rather than by age.** That is not a sweep, it is capture, and it fails whenever capture fails. The sweep's value comes precisely from not depending on the source being reachable.

## Related

- ADR-M004 for the `acl_synced_at` field and the staleness this backstops
- ADR-M006 (`docs/architecture/decisions/ADR-M006-deny-by-default-on-missing-acl.md`) for why an empty list means invisible
- ADR-013, whose payload-only path the sweep uses
- ADR-010, for the confirmation interval the maximum age must exceed
- Design decision D14
