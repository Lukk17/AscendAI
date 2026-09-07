# ADR-015: SharePoint Stays First, Although Google Drive Is Cheaper To Make Permission-Correct

## Status

Proposed, 2026-09-04. Amended 2026-09-05, see Amendment below. Accepted when the OpenSpec change `add-document-connectors` lands. This file is the draft that moves into `apps/ascend-ai-agent/docs/architecture/decisions/` on archive, taking the next free number at that time.

## Amendment, 2026-09-05

The decision stands. SharePoint is the first connector, Google Drive remains a named non-goal, and the reason is the one that always carried it: the customers this is being built for are on Microsoft.

What changed is the counter-argument's status. Access-list capture is deferred under the current scope, so neither connector reads permissions and the permission-correctness comparison below has no input in this version. The two candidate sources are equally cheap here, and the ordering question has one argument rather than two.

The comparison is not withdrawn, and it is the whole point of keeping this record. It becomes live again the day capture returns, and it will argue then exactly what it argues now. A future reader re-opening the ordering should find this analysis rather than rediscover it, and should not read the deferral as evidence that the difference between the two sources was overstated.

One consequence of the amendment is worth naming, because it is the opposite of the trade-off recorded below. The complexity this record apologises for, ADR-011 and the separate permission budget existing to serve a constraint the second connector will not have, is not being paid in this version at all. It is deferred with the capture work. So the first connector is no longer the expensive one, and the argument that the harder capture path should shape the abstraction is an argument about a future version rather than about the code this change ships.

## Context

SharePoint was chosen as the first connector because that is where EU corporate documents live. That reasoning was sound when a connector's job was to land bytes, and it is worth re-examining now that the job also includes capturing an access list, because on that second job the two candidate sources are not equally difficult.

Google Drive's change feed returns each changed file as a File resource, and that resource carries its permission list. One request can return the change and the effective permissions together.

Microsoft Graph's drive delta returns item metadata without permissions. The permission collection is a separate request per item.

That difference is not a detail. It is the entire reason ADR-011 exists: the container-first inheritance scheme, the per-item confirmation schedule, the separate permission throttling budget, and the inheritance table are all machinery for making per-item permission requests affordable. A Google Drive connector would need very little of it, because the expensive thing it avoids is not expensive there.

So on permission correctness alone, the ordering that was settled on other grounds is the wrong way round, and that deserves to be written down rather than left as something a future reader rediscovers and quietly reverses.

## Decision

SharePoint remains the first connector. Google Drive remains a named non-goal of this change.

## Consequences

### Why the inversion does not change the answer

The customers this is being built for are on Microsoft. A Google-first ordering would deliver a permission-correct connector to nobody who asked for one, which is a fast route to a correct product with no users.

The harder capture path is also the one that should shape the abstraction. An `AccessListSource` designed against a source that needs container-level inheritance, per-item exceptions, a separate throttling budget, and its own confirmation schedule will accommodate a source that hands permissions back for free. Designed the other way round, it would assume permissions are cheap and would be reworked the moment it met Graph, and the rework would land in the framework rather than in one implementation.

### Trade-offs

- The first connector is the one where getting permissions right is the most work, so it is the one most likely to ship late. Accepted knowingly rather than discovered later.
- A meaningful share of this change's complexity, specifically ADR-011 and the permission throttling budget, exists to serve a constraint the second connector will not have. That machinery is not wasted, but it is not amortised either, and a reader comparing the two implementations will find the Google one much smaller and should not read that as the SharePoint one being over-built.
- Deferring Google Drive defers the cheapest possible validation of the capture abstraction against a second source, so the abstraction's generality stays unproven until then.

### Alternatives considered

- **Build Google Drive first, then SharePoint.** Ships a permission-correct connector soonest and validates the abstraction cheaply. Rejected on the customer argument: the target customers are on Microsoft, and an ordering that optimises for engineering ease over the users who asked is the wrong optimisation.
- **Build both together.** Would prove the abstraction immediately and avoid designing it against one source. Rejected on scope: this change is already large, and two connectors plus the framework plus the permission machinery is more than one change should carry.
- **Build a Google Drive spike alongside SharePoint, not shipped, purely to check the abstraction.** Genuinely tempting and the closest call here. Rejected for now on YAGNI, and it is the thing to reach for first if the `AccessListSource` interface starts feeling shaped around Graph specifically rather than around capture generally.

## Related

- ADR-011, which exists because of the difference this record describes
- Design decision D17
- `add-document-connectors` design, Open Question 6, which flags that the Google Drive inline-permissions claim underpinning this record was not verified against the `changes.list` reference and must be before a Google connector is planned
