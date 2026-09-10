# ADR-M005: Filter Inside the Vector Search, Not After It

---

### Status

Accepted (2026-09-04)

---

### Context

Once every chunk carries an access list (ADR-M004), the permission test can run in one of two places: inside the Qdrant search, as a filter applied while the index is traversed, or in Java, over the candidate list the search returned.

`RagRetrievalService` already does something that looks like the second. It requests `topK` candidates with a Qdrant-side threshold of zero and applies the similarity threshold in Java, deliberately, so operators can see near-miss scores and tune the floor empirically. That is a sound reason for a score filter and a disastrous pattern for a permission filter, and the difference is worth stating explicitly because the code invites the mistake.

---

### Decision

The access-list predicate goes into the `SearchRequest`, composed with the tenant predicate from [add-tenant-isolation](../../../openspec/changes/add-tenant-isolation/) into one expression built through `FilterExpressionBuilder`:

```text
tenant_id == '<currentTenant>' AND acl IN <principalSet>
```

The existing Java-side threshold filtering and score logging stay exactly as they are. They operate on what Qdrant returned, and what Qdrant returns is already permitted.

---

### Alternatives Considered

#### Alternative 1: Filter in Java after the search

- Pros: No dependency on the vector store's filter semantics. Consistent with how the score threshold is already applied. The near-miss score log keeps showing every candidate.
- Cons: `topK` is spent before the filter runs. A caller permitted only chunks ranked below the cut receives nothing, and the model answers from an empty context. It does not leak, it suppresses, so the obvious test comes back clean and the design looks correct.
- Why not: With `topK` of 5 and a caller whose permitted chunks rank sixth, seventh, and eighth, this returns zero results where the pre-filter returns three. The symptom lands hardest on the narrow-access users, which is to say on the new joiner, the contractor, and the person the customer's security team asked to check whether permissions work.

#### Alternative 2: Over-fetch, then filter in Java

- Pros: Fixes the eight-candidate case with a one-line change. Keeps the filter in application code where it is easy to read.
- Cons: It does not fix the general case, only makes it rarer. A caller whose permitted chunks rank below a hundred others still gets nothing, and whether that happens depends on what else is in the collection at the moment the question is asked. The same question can succeed today and fail next week after an unrelated ingest. It also means embedding and transferring candidates the caller may never see.
- Why not: It converts a deterministic failure into a non-deterministic one. That is worse, not better, because it cannot be tested.

---

### Consequences

- Positive: Chunks the caller may not read are never scored, never returned, never logged, and never reach the model. Suppression is structural rather than a step that can be skipped.
- Positive: `topK` means what it says. The caller gets up to `topK` results they are entitled to, not `topK` results minus whatever was filtered out.
- Positive: One filter expression carries both the tenant predicate and the access-list predicate, so there is a single composition point rather than two things that each believe they own filtering.
- Negative: Correctness now depends on Spring AI translating its `IN` operator against a keyword-array payload field into Qdrant match-any semantics. That is library behaviour, not our code.
- Negative: The near-miss score log no longer shows chunks the caller cannot read, which removes a debugging affordance. That is the point, and it is a real cost when diagnosing a retrieval miss.

#### Risks

- The Spring AI to Qdrant filter translation is not what the API shape suggests. Mitigated by pinning it with an integration test against a real Qdrant rather than a mocked vector store, since a mock would happily confirm whatever we assumed.
- A future code path issues a `SearchRequest` without the filter. Mitigated by the fail-closed rule [add-tenant-isolation](../../../openspec/changes/add-tenant-isolation/) already applies: retrieval without resolved context throws rather than searching unfiltered.
