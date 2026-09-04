# ADR-M007: Access Lists Name Groups, Membership Resolves at Login

---

### Status

Accepted (2026-09-04)

---

### Context

The access list on a chunk has to name something. It can name the people who may read the chunk, or it can name the groups that may read it and leave the question of who is in those groups to be answered elsewhere.

The two choices differ in where a change lands. A person joining a team is a membership change. A document being shared with a team is a sharing change. They happen at different rates, in different systems, and they should not cost the same thing.

---

### Decision

Access lists name groups only. Membership is never copied into the vector store.

Principals use one namespaced format everywhere, `namespace:type:id`, capped at 128 characters and restricted to lowercase letters, digits, and `.`, `-`, `_`, `@`, so they are safe as keyword payload values with no escaping layer. Examples: `entra:group:<object id>`, `google:group:<group address>`, `local:group:<slug>`, `tenant:everyone:<tenant id>`. Namespace and type come from a closed set, and principals are produced by one typed factory rather than assembled as strings at the point of use.

Membership resolves per token: use the token's group claim when it is complete, otherwise call the provider's transitive membership endpoint, and cache the result in Redis under the subject for the shorter of the remaining token lifetime and five minutes. Nested groups are flattened by the provider, not by walking the hierarchy ourselves. The resolved principal set is capped, and a caller exceeding the cap fails the request rather than proceeding on a truncated set.

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

- Positive: A membership change costs one directory edit and takes effect within the cache window. Nothing is re-indexed and nothing is re-embedded.
- Positive: A sharing change costs a payload update on the affected document's chunks and nothing else.
- Positive: The two staleness windows stay separate and separately bounded, which is what makes each of them explainable to a customer.
- Negative: Membership resolution sits in the request path on a cache miss, and against a large directory that is a real cost nobody has measured yet.
- Negative: The filter is a set-intersection rather than an equality, so it is more expensive than the per-user alternative on every single query.
- Negative: A person's effective access is now a function of two systems, so answering "why can this person see this" means looking at the chunk's list and at their resolved set.

#### Risks

- Microsoft Entra ID omits the `groups` claim entirely when the user belongs to more groups than the token can carry, substituting `_claim_names` and `_claim_sources`. A resolver that reads `groups` and treats absence as "no groups" gives the most heavily-permissioned users the least access. Mitigated by treating an absent claim as fall-through to the transitive endpoint, never as an empty set, and by monitoring the distribution of principal set sizes so a population-wide collapse toward one is visible.
- Redis unavailable means every request pays the directory call. Accepted, and it degrades latency rather than correctness.
