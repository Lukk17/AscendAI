# ADR-014: The Directory Lookup Is the Primary Membership Path, Not a Fallback

## Status

Deferred, 2026-09-04. Not implemented by the OpenSpec change `add-auth-and-identity`, and not accepted by it. This file is the draft that task 12.8 installs into `apps/ascend-ai-agent/docs/architecture/decisions/` with this status intact, taking the next free number at that time.

## Deferral, 2026-09-04

There is one membership path in this version and it is the Keycloak group claim, so there is no ordering to decide between a directory and a claim.

This is the record whose analysis is most worth keeping, and it is kept whole. Microsoft's cap of 200 group identifiers for the token protocols and 150 for SAML, counting nested groups, and the fact that above the cap it emits no groups claim at all rather than a truncated one, is a primary-source finding that took work to establish and that a future reader would otherwise rediscover by shipping the bug. So is the compounding effect of brokering, where the overage markers cannot cross the attribute importer and an over-cap person becomes indistinguishable from a groupless one. So is the asymmetry between Microsoft and Google, where Google's sign-in token carries no groups claim under any configuration and a document that treats the two as a pair produces an onboarding waiting for a claim that never arrives.

None of it applies while groups live only in Keycloak, because a Keycloak group claim has no vendor cap and no overage markers, and an absent claim genuinely means an administrator placed the person in no groups.

What has to happen for this record to become active: directory lookups have to exist at all, which is ADR-010's deferral, and that in turn waits on the owner's decision about how a directory's groups relate to Keycloak's.

## Context

ADR-M007 fixes the order in which a caller's group membership is resolved: use the token's group claim when it is complete, otherwise call the provider's transitive membership endpoint. That order was written when the agent was expected to validate a provider's token directly, and it treats the directory call as the exception.

Two facts, both checked against primary sources, make that ordering wrong in practice.

The first is a cap. Microsoft limits the groups claim to 200 group identifiers for the token protocols and 150 for SAML, counting nested groups. Above the cap it does not truncate the list. It emits no groups claim at all and substitutes a pointer to a Graph endpoint, which is the overage the `_claim_names` and `_claim_sources` markers describe. That is not a rare condition in a company of any size, and it lands on the people who belong to the most groups, which is to say the people whose access matters most.

The second is brokering, decided in ADR-013. ascend-ai-agent no longer reads the provider's token. It reads a Keycloak token, and the only group data in that token is whatever an Attribute Importer copied across. That importer copies a JSON array of textual elements into a multivalued attribute. The overage markers are not an array of strings, so they do not cross the broker through it, and no supported importer shape carries a JSON object claim across in a form the completeness test could read. Under the force synchronisation mode ADR-015 mandates, the attribute is correctly removed when the upstream claim is absent.

Compose those two and the result is specific: an over-cap person arrives with an empty group claim carrying no marker of any kind, which is byte-for-byte what a person who genuinely belongs to no groups looks like. The completeness test from ADR-M007 is not merely unreliable on the brokered path. There is nothing in the token to test.

Google adds a third fact that removes the claim path entirely for one vendor. Google's sign-in token carries no groups claim at all, under any configuration, at any tenant size. The two providers were described in this change as a symmetric pair and they are not.

## Decision

Where a directory adapter is configured for the caller's brokered identity provider, it is called and its answer is used. That is the primary path.

The token group claim is read only when no directory adapter is configured for that provider. That is the fast path, it is a deliberate per-customer configuration, and it is valid only for a tenant known to sit comfortably under the emission cap.

This is stated as the normal case rather than as a preference, because the difference shows up in what gets built. The directory path is the one the default test configuration exercises, the one the latency budget is measured against, and the one the onboarding runbook describes first. The claim path is the special case, and its tests say which cap they assume.

Where ascend-ai-agent validates a directly-issued provider token instead of a brokered one, the completeness test from ADR-M007 still applies and still earns its place, because on that path the overage markers are visible. An absent claim there means fall through to the directory and never an empty group set.

The Google path is always a directory call. A Google customer with no directory adapter configured resolves the tenant floor and nothing else, and that is documented as a deployment shape rather than as a fault.

This refines ADR-M007 rather than contradicting its intent, which was that a claim is used only when it can be trusted. What is new is the finding that on the brokered path trustworthiness cannot be established at all. Amending ADR-M007 and `docs/architecture/permission-aware-retrieval.md` to match is task 12.11 of the change.

## Consequences

### Why this way

- The correctness of the resolved set stops depending on the size of the customer. Under the old order a customer growing past 200 groups per person degrades silently from correct to empty, with no error and no deployment change to point at.
- Testing follows the primary path. A design that calls the directory an exception gets integration tests that stub it, latency budgets measured without it, and a runbook that mentions it last, which means the first real customer exercises a path nobody has run.
- The revocation window improves. On the claim path a membership change is invisible until the person signs in through the broker again, because a brokered provider writes its attributes at login and at no other time. On the directory path it is bounded by the five-minute principal cache. That is the difference between a bound we set and a bound the realm's session lifetime sets.
- The Microsoft and Google paths stop being described as a pair. Google has no claim path, so a document that treats them symmetrically produces a Google onboarding that waits for a claim that will never arrive.

### Trade-offs

- Every cache miss now pays a directory call, for every customer with an adapter configured rather than only for over-cap users. Directory availability becomes product availability on that path, which ADR-011 already accepted deliberately and turns into a 503 rather than a quiet narrowing. The design document's open question about synchronous resolution latency against a large directory stays open and gets more weight, not less.
- Directory credentials become a per-customer prerequisite rather than a fallback arrangement. A customer who will consent to sign-in but not to an application identity reading their directory now has no working small-tenant path unless they are genuinely small, and the stored-token escape hatch is the only other answer.
- ADR-M007 and the retrieval design now say something this change does not do, until task 12.11 lands. That is a real inconsistency for the duration, and it is called out in the task rather than papered over.
- The claim path still exists and still has to be maintained and tested, for the small tenant and for the direct-issuer escape hatch. Two paths is more than one, and deleting the claim path would have been simpler and would have removed a legitimate configuration.

### Alternatives considered

- Keep ADR-M007's order and rely on the completeness test. Pro: no change, and it is correct when the agent validates a provider token directly. Con: on the brokered path the test has no input, and the failure it is supposed to catch is exactly the one that hits the most heavily permissioned people. Rejected on the facts rather than on preference.
- Import the overage markers across the broker with a second mapper, so the completeness test keeps working. Pro: preserves the existing order and the existing reasoning. Con: the markers are a JSON object rather than an array of textual elements, which is the shape the array importer accepts, so this is not available through the documented mechanism. Rejected as unimplementable rather than as undesirable.
- Call the directory always, and delete the claim path. Pro: one path, one set of tests, no cap to reason about anywhere. Con: it forces directory credentials onto every customer including the small ones and the ones with no corporate directory at all, and it removes the only configuration that works when a customer refuses an application identity. Rejected.
- Use the claim and reconcile against the directory in the background. Pro: keeps the fast path and eventually corrects it. Con: it means serving a knowingly wrong principal set for the reconciliation interval, which is precisely the silent narrowing ADR-011 refuses, and the wrongness is largest for the people it affects most. Rejected.

## Related

- `docs/architecture/permission-aware-retrieval.md`, sections "Resolving group membership" and "Staleness"
- `docs/architecture/decisions/ADR-M007-group-principals-membership-at-login.md`, whose resolution order this record refines
- ADR-011, which refuses to narrow a principal set quietly, and which this record leans on for the directory-failure behaviour
- ADR-013, which decides brokering, and ADR-015, which decides how group identifiers cross the broker
- OpenSpec change `add-auth-and-identity`, decisions D9, D13 and D18, capabilities `principal-resolution` and `identity-provider`
