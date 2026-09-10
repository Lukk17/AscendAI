# ADR-M007: Access Lists Name Groups, Membership Resolves at Login

---

### Status

Accepted (2026-09-04)

Amended (2026-09-04): scope narrowed to Keycloak-native groups only for this version, resolving membership from a customer's own directory deferred. See Amendment below.

---

### Context

The access list on a chunk has to name something. It can name the people who may read the chunk, or it can name the groups that may read it and leave the question of who is in those groups to be answered elsewhere.

The two choices differ in where a change lands. A person joining a team is a membership change. A document being shared with a team is a sharing change. They happen at different rates, in different systems, and they should not cost the same thing.

---

### Decision

Access lists name groups only. Membership is never copied into the vector store.

Principals use one namespaced format everywhere, `namespace:type:id`, capped at 128 characters and restricted to lowercase letters, digits, and `.`, `-`, `_`, `@`, so they are safe as keyword payload values with no escaping layer. Examples: `entra:group:<object id>`, `google:group:<group address>`, `local:group:<slug>`, `tenant:everyone:<tenant id>`. Namespace and type come from a closed set, and principals are produced by one typed factory rather than assembled as strings at the point of use.

For this version, membership resolves from Keycloak's own groups only. An administrator creates a group in the realm and assigns people to it, and every token issued to a member carries it. Per token: read the group claim already on the validated JWT and mint each entry into a principal. No cache sits in front of this: the claim is already decoded by the time it is read, minting a bounded set of principals from it costs nothing worth saving, and nothing here calls out anywhere else. The resolved principal set is capped, and a caller exceeding the cap fails the request rather than proceeding on a truncated set.

---

### Alternatives Considered

#### Alternative 1: Materialise per-user access into the payload

- Pros: The filter is a single equality on a user id, which is the cheapest possible predicate. No membership resolution in the request path at all.
- Cons: Every membership change rewrites the payload of every chunk the affected group can reach. One person joining a large team is a mass update across the collection. Storage grows with users times documents rather than groups times documents. Offboarding somebody becomes a batch job rather than a directory edit.
- Why not: It makes the frequent, low-value event (membership) expensive in order to make the rare, high-value event (a search) marginally cheaper.

#### Alternative 2: Store the groups but expand them at ingest into a flat user list

- Pros: Same cheap filter, and the expansion happens once rather than per request.
- Cons: Identical to Alternative 1 in every consequence that matters, because the stored artifact is still a user list that goes stale the moment anybody joins or leaves.
- Why not: Same reason.

#### Alternative 3: Walk the group hierarchy ourselves rather than using a transitive endpoint

- Pros: No dependency on a provider-specific endpoint, and the nesting logic is visible in our code.
- Cons: It means reimplementing each provider's nesting semantics, cycle handling, and limits, in order to arrive at the same answer more slowly and with more ways to be wrong. Both Microsoft and Google publish a transitive endpoint precisely because this is not a problem worth re-solving.
- Why not: More code, more calls, more bugs, same answer.

#### Alternative 4: Truncate an over-large principal set or access list

- Pros: The request always succeeds. Nobody sees an error.
- Cons: A truncated allow list silently denies people access they actually have, and the symptom is indistinguishable from a bug in retrieval, embedding, chunking, or the model. It is the most expensive possible way to fail, because it costs a debugging session rather than a line in a sync history.
- Why not: Rejected in both directions. A list over 64 principals is a capture failure. A principal set over the cap fails the request.

---

### Consequences

- Positive: A membership change costs one directory edit and takes effect at the person's next sign-in. Nothing is re-indexed and nothing is re-embedded.
- Positive: A sharing change costs a payload update on the affected document's chunks and nothing else.
- Positive: The two staleness windows stay separate and separately bounded, which is what makes each of them explainable to a customer.
- Positive: There is no cache to keep consistent, no cache key to get wrong, and no dependency on Redis being up in order to resolve who somebody is. The whole membership answer comes from a token that was already being validated.
- Negative: The filter is a set-intersection rather than an equality, so it is more expensive than the per-user alternative on every single query.
- Negative: A person's effective access is now a function of two systems, so answering "why can this person see this" means looking at the chunk's list and at their resolved set.
- Negative: A membership change is invisible until the person's session ends and they sign in again, and that window is the realm's SSO session and token lifetime, not something this decision can shorten on its own.

#### Risks

- A document synced from a customer's own SharePoint or Google Drive carries an access list naming that source's provider group identifiers, `entra:group:*` or `google:group:*`, and a Keycloak group mints only into `local:group:*`. Nothing maps one onto the other yet, so a synced document is retrievable by nobody until a mapping mechanism exists. Mitigated only by naming it here rather than letting it surface as a support ticket.

See the Amendment below for the Microsoft and Google directory risks this decision carried before the scope cut, and why they are deferred rather than resolved.

---

### Amendment — 2026-09-04

Scope was narrowed after this decision was first accepted. The original decision resolved membership by reading a provider's own group claim or by calling that provider's transitive membership endpoint, against a customer's own Microsoft Entra ID or Google Workspace directory. The owner has since decided that, for this version, group data lives in Keycloak and nowhere else: an administrator creates a group in the realm and assigns people to it, and the token carries those groups directly. Reading membership from a customer's own directory, whether brokered through Keycloak or looked up directly, is deferred, not abandoned.

The core decision is unchanged. Membership still resolves at login into an immutable, capped principal set rather than being looked up per query, and access lists still name groups only. What changed is where the group data comes from.

The reasoning behind the deferred approach is preserved because it will be needed again. Microsoft Entra ID stops emitting a groups claim once nested membership passes 200 groups for the token protocols, 150 for SAML, and substitutes a Graph pointer instead of a truncated list, which makes a claim-only read wrong for any tenant of real size. Google Workspace never emits a groups claim at all, in any token. Both facts mean that the moment a customer's own directory is consulted again, a directory lookup has to be the primary path and a claim can only ever be a small-tenant fast path for Microsoft, with no equivalent for Google. Neither fact applies to the current, Keycloak-only source, because a Keycloak-native group is not subject to either provider's emission limits and nothing here reads a provider's directory at all.

One consequence of the narrowed scope has to be stated rather than discovered. A document synced from SharePoint or Google Drive carries an access list naming that source's own group identifiers, `entra:group:*` or `google:group:*`. A Keycloak group mints only into `local:group:*`. Nothing maps one onto the other. So permission filtering is correct and complete for a document uploaded directly into the product, where an administrator assigns Keycloak groups by hand, and it silently matches nobody for a document synced from a customer's own storage, until something maps that source's groups onto Keycloak groups. What that mapping mechanism is, and who builds it, is not decided by this amendment.
