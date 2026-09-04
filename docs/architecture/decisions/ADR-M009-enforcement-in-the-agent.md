# ADR-M009: Enforcement Lives in the Agent's Retrieval Path

---

### Status

Accepted (2026-09-04)

---

### Context

Something has to hold the caller's principal set, compose it into the search filter, and re-check every source reference before a download link is signed. That work can live inside AscendAgent, alongside the code that builds the `SearchRequest`, or behind a network hop in a separate authorization service, in the spirit of the MCP tool services that ADR-M002 standardised on.

The platform's existing instinct pushes toward the second. Tool capabilities became MCP servers. Semantic memory became a REST service. Extracting authorization would be consistent with that pattern.

It would also be wrong here, and the reason is worth writing down because the consistency argument is genuinely appealing.

---

### Decision

Permission enforcement stays inside AscendAgent, in the retrieval path, in the same code that composes the `SearchRequest` and in the same code that presigns source downloads.

Concretely: principal resolution and its Redis cache sit in the agent, the access-list predicate is composed into the same `FilterExpressionBuilder` expression that carries the tenant predicate from [add-tenant-isolation](../../../openspec/changes/add-tenant-isolation/), and `S3PresignedUrlService` re-checks each reference against the principal set itself rather than trusting that retrieval filtered it.

---

### Alternatives Considered

#### Alternative 1: A separate authorization service the agent calls

- Pros: Consistent with ADR-M002's service-per-capability shape. Reusable if a second consumer of the corpus ever exists. Independently deployable, so a permission change ships without an agent release.
- Cons: The service can only answer questions, and the question the search needs answered is not "may this person read this document" but "restrict this index traversal to what this person may read". A remote service cannot participate in a Qdrant filter, so the best it can return is a principal set, which is a value the agent then has to hold and compose anyway. The service ends up being a network hop in front of a Redis lookup. It also adds a failure mode inside the request path whose only safe response is to refuse the request, so availability of the authorization service becomes availability of the product.
- Why not: It cannot do the thing that matters (pre-filtering, ADR-M005) and it adds an outage surface for the part it can do.

#### Alternative 2: Enforce in the vector store via per-tenant collections or Qdrant-side access control

- Pros: Enforcement below the application entirely, so no application bug can bypass it.
- Cons: Qdrant has no per-principal authorization model, and collection-per-group multiplies collections by groups times embedding dimensions. [add-tenant-isolation](../../../openspec/changes/add-tenant-isolation/) already rejected collection-per-tenant for the weaker case of tenants, and groups are far more numerous than tenants.
- Why not: The store does not offer the primitive, and the workaround does not scale.

#### Alternative 3: Enforce at the API gateway, before the request reaches the agent

- Pros: One choke point in front of everything, and the agent stays unaware of permissions.
- Cons: A gateway can authenticate a caller and authorize an endpoint. It cannot authorize the contents of a search result it has not run. By the time there is anything to authorize, the search has already happened, which is post-filtering with an extra process.
- Why not: Wrong layer. The decision needs the query, and the gateway does not have it.

---

### Consequences

- Positive: The filter is composed where the search is built, so pre-filtering is possible at all.
- Positive: No network hop between resolving the principal set and using it, so no partial-failure state where the agent has a query and no permission answer.
- Positive: One expression carries both the tenant predicate and the access-list predicate, so there is a single place a filter can be got wrong rather than two.
- Negative: A security-relevant control lives in application code, so an agent bug can bypass it. That is mitigated by tests, not by architecture, and the test table in the design document is the mitigation.
- Negative: Diverges from the service-per-capability pattern ADR-M002 established, which future readers will notice and should not copy without reading this record.
- Negative: A second consumer of the corpus, if one ever exists, has to reimplement the check rather than call it.

#### Risks

- A future code path issues a search or a presign without the check, because the check is a convention in application code rather than a boundary. Mitigated by two things: the fail-closed rule from [add-tenant-isolation](../../../openspec/changes/add-tenant-isolation/), where retrieval without resolved context throws instead of searching, and the presigner re-checking references itself instead of trusting its caller. The second matters most, because the presigner is downstream of retrieval and is exactly where "the caller already checked" turns into a leak.
